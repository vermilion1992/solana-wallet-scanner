"""Bundle / distribution detection for pre-screen and qualification.

A wallet is not lead-eligible when its sample shows coordinated funding,
multi-signer bundle buys (including when the wallet pays the fee), sell
proceeds routed to co-signers or the funder, or tokens transferred in with
no buy that are later sold (zero basis). Detection uses account keys and
token-balance owner changes, so inflows that never list the wallet in
accountKeys are still seen. Benign inflows (WSOL wrap, stablecoin deposit,
dust airdrop with no later sale) are not bundle flags.
"""
from __future__ import annotations

from decimal import Decimal

from scanner.investigation import (
    PUMP,
    PUMP_SWAP,
    REVIEWED_OUTER_VENUES,
    TOKEN_2022_ID,
    WSOL,
    _keys,
    _program,
)

TOKEN_PROGRAMS = frozenset({
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    TOKEN_2022_ID,
})
INFRA = frozenset({
    "11111111111111111111111111111111",
    "ComputeBudget111111111111111111111111111111",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
    "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo",
}) | TOKEN_PROGRAMS
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
STABLES = frozenset({USDC, USDT})
DUST_RAW = Decimal("1000000")


def _unwrap(record):
    if not isinstance(record, dict):
        return {}
    if "transaction" in record:
        return record
    raw = record.get("raw")
    if isinstance(raw, dict):
        result = raw.get("result")
        if isinstance(result, dict) and "transaction" in result:
            return result
        if "transaction" in raw:
            return raw
    return record


def _signers(raw, keys):
    message = (raw.get("transaction") or {}).get("message") or {}
    header = message.get("header") or {}
    required = header.get("numRequiredSignatures")
    if isinstance(required, int) and required > 0:
        return [key for key in keys[:required] if isinstance(key, str)]
    entries = message.get("accountKeys") or []
    out = []
    for item in entries:
        if isinstance(item, dict) and item.get("signer") and item.get("pubkey"):
            out.append(item["pubkey"])
    return out


def _native_delta(raw, keys, address):
    meta = raw.get("meta") or {}
    try:
        index = keys.index(address)
    except ValueError:
        return Decimal("0"), False
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    if index >= len(pre) or index >= len(post):
        return Decimal("0"), False
    fee = meta.get("fee") if isinstance(meta.get("fee"), int) else 0
    paid = bool(keys) and keys[0] == address
    delta = Decimal(post[index] - pre[index])
    if paid:
        delta += Decimal(fee)
    return delta, paid


def _owned_token_deltas(raw, address):
    """Owner-field deltas. Works even when the wallet is absent from accountKeys."""
    meta = raw.get("meta") or {}
    pre, post = {}, {}
    for field, dest in (("preTokenBalances", pre), ("postTokenBalances", post)):
        for balance in meta.get(field) or []:
            if not isinstance(balance, dict) or balance.get("owner") != address:
                continue
            mint = balance.get("mint")
            amount = (balance.get("uiTokenAmount") or {}).get("amount")
            if mint and amount not in (None, ""):
                dest[mint] = dest.get(mint, Decimal("0")) + Decimal(str(amount))
    return {mint: post.get(mint, Decimal("0")) - pre.get(mint, Decimal("0")) for mint in set(pre) | set(post)}


def _has_reviewed_swap(raw, keys):
    message = (raw.get("transaction") or {}).get("message") or {}
    for instruction in message.get("instructions") or []:
        if not isinstance(instruction, dict):
            continue
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, KeyError, IndexError):
            program = instruction.get("programId")
        if program in REVIEWED_OUTER_VENUES or program in (PUMP, PUMP_SWAP):
            return True
    return False


def _benign_inflow(gained, later_sold):
    if not gained:
        return True
    if all(mint == WSOL for mint in gained):
        return True
    # Fail-closed only when a gained mint is later sold. Airdrops, stable
    # deposits and other inbound tokens that are never sold are not bundle P&L.
    if not any(mint in later_sold for mint in gained):
        return True
    return False


def _outbound_transfer_mints(raw, keys, address):
    """Mints sent to another owner. ATA close/burn is not a sale."""
    sold = set()
    meta = raw.get("meta") or {}
    message = (raw.get("transaction") or {}).get("message") or {}
    for group in [message] + [
        {"instructions": group.get("instructions") or []}
        for group in (meta.get("innerInstructions") or [])
        if isinstance(group, dict)
    ]:
        for instruction in group.get("instructions") or []:
            if not isinstance(instruction, dict):
                continue
            try:
                program = _program(instruction, keys) if keys else instruction.get("programId")
            except (ValueError, TypeError, KeyError, IndexError):
                program = instruction.get("programId")
            if program not in TOKEN_PROGRAMS:
                continue
            parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else None
            if not parsed or parsed.get("type") not in ("transfer", "transferChecked"):
                continue
            info = parsed.get("info") or {}
            if info.get("authority") == address or info.get("source") == address:
                mint = info.get("mint")
                if mint:
                    sold.add(mint)
    return sold


def _token_transfer_in(raw, keys, address):
    """True when another owner sends a token to this wallet with no swap."""
    meta = raw.get("meta") or {}
    message = (raw.get("transaction") or {}).get("message") or {}
    if keys and _has_reviewed_swap(raw, keys):
        return False
    inbound = False
    for group in [message] + [
        {"instructions": group.get("instructions") or []}
        for group in (meta.get("innerInstructions") or [])
        if isinstance(group, dict)
    ]:
        for instruction in group.get("instructions") or []:
            if not isinstance(instruction, dict):
                continue
            try:
                program = _program(instruction, keys) if keys else instruction.get("programId")
            except (ValueError, TypeError, KeyError, IndexError):
                program = instruction.get("programId")
            if program not in TOKEN_PROGRAMS:
                continue
            parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else None
            if not parsed or parsed.get("type") not in ("transfer", "transferChecked"):
                continue
            info = parsed.get("info") or {}
            authority = info.get("authority")
            source = info.get("source")
            if authority and authority != address and source != address:
                inbound = True
    deltas = _owned_token_deltas(raw, address)
    gained = {mint: qty for mint, qty in deltas.items() if qty > 0}
    return inbound or (bool(gained) and not (keys and _has_reviewed_swap(raw, keys)))


def detect_bundle_or_distribution(records, address):
    """Return exclusion flags for one wallet's captured records."""
    later_sold = set()
    parsed_rows = []
    for record in records or []:
        raw = _unwrap(record)
        if not isinstance(raw, dict) or (raw.get("meta") or {}).get("err") is not None:
            continue
        try:
            keys = _keys((raw.get("transaction") or {}).get("message") or {}, raw.get("meta") or {})
        except (ValueError, TypeError, KeyError, IndexError):
            keys = []
        deltas = _owned_token_deltas(raw, address)
        if keys and _has_reviewed_swap(raw, keys):
            for mint, qty in deltas.items():
                if qty < 0:
                    later_sold.add(mint)
        else:
            later_sold.update(_outbound_transfer_mints(raw, keys, address))
        parsed_rows.append((raw, keys, deltas, record))

    reasons = []
    shared_funders = {}
    multi_signer = []
    proceeds_to_cosigner = []
    zero_basis = []
    counterparts = set()
    for raw, keys, deltas, record in parsed_rows:
        signers = _signers(raw, keys) if keys else []
        native, paid = _native_delta(raw, keys, address) if keys else (Decimal("0"), False)
        message = (raw.get("transaction") or {}).get("message") or {}
        signature = ((raw.get("transaction") or {}).get("signatures") or [None])[0] or record.get("signature")
        has_swap = bool(keys) and _has_reviewed_swap(raw, keys)
        if len(signers) > 1 and address in signers and has_swap:
            others = [item for item in signers if item != address]
            counterparts.update(others)
            multi_signer.append({
                "signature": signature,
                "co_signers": others,
                "fee_payer": keys[0] if keys else None,
                "wallet_is_fee_payer": paid,
            })
            reasons.append("multi_signer_bundle_buy")
            for other in others:
                other_delta, _ = _native_delta(raw, keys, other)
                if other_delta > 0 and native <= 0:
                    proceeds_to_cosigner.append({
                        "signature": signature,
                        "co_signer": other,
                        "co_signer_sol": str(other_delta / Decimal(1_000_000_000)),
                    })
                    reasons.append("sell_proceeds_to_cosigner")
        if keys and not has_swap:
            for instruction in message.get("instructions") or []:
                parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
                info = parsed.get("info") if isinstance(parsed, dict) else None
                if not isinstance(info, dict) or parsed.get("type") != "transfer":
                    continue
                if info.get("destination") != address:
                    continue
                lamports = info.get("lamports")
                source = info.get("source")
                if isinstance(lamports, int) and lamports >= 10_000_000 and source:
                    shared_funders[source] = shared_funders.get(source, 0) + 1
                    counterparts.add(source)
                if info.get("source") != address and info.get("destination") in counterparts and native < 0:
                    proceeds_to_cosigner.append({
                        "signature": signature,
                        "co_signer": info.get("destination"),
                    })
                    reasons.append("sell_proceeds_to_cosigner")
        if keys and len(signers) > 1 and address in signers and not has_swap and native < 0:
            for other in signers:
                if other == address:
                    continue
                other_delta, _ = _native_delta(raw, keys, other)
                if other_delta > 0 and (other in counterparts or other in shared_funders):
                    proceeds_to_cosigner.append({
                        "signature": signature,
                        "co_signer": other,
                        "co_signer_sol": str(other_delta / Decimal(1_000_000_000)),
                    })
                    reasons.append("sell_proceeds_to_cosigner")
        if _token_transfer_in(raw, keys, address):
            gained = {mint: qty for mint, qty in deltas.items() if qty > 0}
            if _benign_inflow(gained, later_sold):
                continue
            zero_basis.append(signature)
            reasons.append("transfer_in_zero_basis")
    if shared_funders and multi_signer:
        reasons.append("shared_funder")
    unique = []
    for item in reasons:
        if item not in unique:
            unique.append(item)
    excluded = bool(unique)
    return {
        "excluded": excluded,
        "reasons": unique,
        "reason": unique[0] if unique else None,
        "shared_funders": sorted(shared_funders),
        "multi_signer_buys": multi_signer,
        "sell_proceeds_to_cosigner": proceeds_to_cosigner,
        "zero_basis_signatures": [item for item in zero_basis if item],
        "lead_eligible": not excluded,
    }
