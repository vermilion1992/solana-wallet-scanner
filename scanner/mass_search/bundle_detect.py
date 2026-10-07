"""Bundle / distribution detection for pre-screen and qualification.

A wallet is not lead-eligible when its sample shows coordinated funding,
multi-signer bundle buys, sell proceeds routed to co-signers, or tokens
transferred in with no buy (zero basis). Detection is per-wallet on the
captured records; unknown stays excluded.
"""
from __future__ import annotations

from decimal import Decimal

from scanner.investigation import (
    PUMP,
    PUMP_SWAP,
    REVIEWED_OUTER_VENUES,
    TOKEN_2022_ID,
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


def _token_transfer_in(raw, keys, address):
    """True when another owner sends a token to this wallet with no swap."""
    meta = raw.get("meta") or {}
    message = (raw.get("transaction") or {}).get("message") or {}
    if _has_reviewed_swap(raw, keys):
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
                program = _program(instruction, keys)
            except (ValueError, TypeError, KeyError, IndexError):
                program = instruction.get("programId")
            if program not in TOKEN_PROGRAMS:
                continue
            parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else None
            if not parsed or parsed.get("type") not in ("transfer", "transferChecked"):
                continue
            info = parsed.get("info") or {}
            dest_owner = info.get("destination")
            source = info.get("source")
            authority = info.get("authority")
            if dest_owner == address or info.get("tokenOwner") == address:
                continue
            # Destination token account owned by wallet is visible via balances.
            if authority and authority != address and source != address:
                inbound = True
    deltas = _owned_token_deltas(raw, address)
    gained = any(qty > 0 for qty in deltas.values())
    return inbound or (gained and not _has_reviewed_swap(raw, keys))


def detect_bundle_or_distribution(records, address):
    """Return exclusion flags for one wallet's captured records."""
    reasons = []
    shared_funders = {}
    multi_signer = []
    proceeds_to_cosigner = []
    zero_basis = []
    for record in records or []:
        raw = _unwrap(record)
        if not isinstance(raw, dict) or (raw.get("meta") or {}).get("err") is not None:
            continue
        try:
            keys = _keys((raw.get("transaction") or {}).get("message") or {}, raw.get("meta") or {})
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if address not in keys:
            continue
        signers = _signers(raw, keys)
        native, paid = _native_delta(raw, keys, address)
        message = (raw.get("transaction") or {}).get("message") or {}
        signature = ((raw.get("transaction") or {}).get("signatures") or [None])[0] or record.get("signature")
        has_swap = _has_reviewed_swap(raw, keys)
        if len(signers) > 1 and address in signers and has_swap:
            others = [item for item in signers if item != address]
            multi_signer.append({
                "signature": signature,
                "co_signers": others,
                "fee_payer": keys[0] if keys else None,
                "wallet_is_fee_payer": paid,
            })
            if not paid:
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
        if not has_swap:
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
        if _token_transfer_in(raw, keys, address):
            zero_basis.append(signature)
            reasons.append("transfer_in_zero_basis")
    if any(count >= 1 and next(iter(shared_funders.values()), 0) >= 1 for count in shared_funders.values()):
        # A large SOL deposit from a single funder, then a bundle buy, is the
        # Gv3ksNUG pattern. Flag whenever a funder appears and a bundle buy did.
        if multi_signer:
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
