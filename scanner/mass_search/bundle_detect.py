"""Bundle / distribution detection for pre-screen and qualification.

A wallet is not lead-eligible when its sample shows coordinated funding,
multi-signer bundle buys (including when the wallet pays the fee), sell
proceeds routed to co-signers or the funder, tokens transferred in with
no buy that are later sold (zero basis), or a controller pair that both
funds and sweeps the wallet. Detection uses account keys and token-balance
owner changes, so inflows that never list the wallet in accountKeys are
still seen.

A co-signer is a bundle partner only when it has a material token or SOL
position change in the same swap: it buys or sells the same mint, or it
receives proceeds beyond fees and tips. Passive Jupiter / Axiom signers
and a Jito-tip payer are not bundle partners. sell_proceeds_to_cosigner
does not fire on a buy just because a relayer collected a fee.

Benign inflows (WSOL wrap, stablecoin deposit, dust airdrop) lose the
exemption as soon as that mint is later sold through any venue, decoded
or not. ATA close / rent reclaim is not a sale.
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
from scanner.mass_search.verified_costs import is_verified_tip_account

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
# Tips and relayer fees sit at or below 0.01 SOL. Material proceeds sit far above.
MATERIAL_SOL_LAMPORTS = Decimal("10000000")
RENT_LAMPORTS = Decimal("3000000")
CONTROLLED_SHARE = Decimal("0.80")


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


def _iter_instructions(raw):
    message = (raw.get("transaction") or {}).get("message") or {}
    meta = raw.get("meta") or {}
    yield from message.get("instructions") or []
    for group in meta.get("innerInstructions") or []:
        if isinstance(group, dict):
            yield from group.get("instructions") or []


def _is_close_only(raw, keys, address, mint):
    """ATA close / burn of leftover tokens is not a sale."""
    saw_close = False
    saw_other = False
    for instruction in _iter_instructions(raw):
        if not isinstance(instruction, dict):
            continue
        try:
            program = _program(instruction, keys) if keys else instruction.get("programId")
        except (ValueError, TypeError, KeyError, IndexError):
            program = instruction.get("programId")
        parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else None
        kind = parsed.get("type") if parsed else None
        if program in TOKEN_PROGRAMS and kind == "closeAccount":
            info = parsed.get("info") or {}
            if info.get("owner") == address or info.get("destination") == address:
                saw_close = True
                continue
        if program in TOKEN_PROGRAMS and kind in ("burn", "burnChecked"):
            continue
        if program in INFRA:
            continue
        if program in REVIEWED_OUTER_VENUES or program in (PUMP, PUMP_SWAP):
            saw_other = True
        elif program and program not in INFRA:
            saw_other = True
    native, _ = _native_delta(raw, keys, address) if keys else (Decimal("0"), False)
    if saw_other:
        return False
    if saw_close and native <= RENT_LAMPORTS:
        return True
    return False


def _sale_mints(raw, keys, address, deltas):
    """Mints sold through any venue, decoded or not. ATA close is not a sale."""
    sold = set()
    for mint, qty in (deltas or {}).items():
        if qty >= 0 or mint in (WSOL,):
            continue
        if keys and _is_close_only(raw, keys, address, mint):
            continue
        sold.add(mint)
    return sold


def _benign_inflow(gained, later_sold):
    if not gained:
        return True
    if all(mint == WSOL for mint in gained):
        return True
    if not any(mint in later_sold for mint in gained):
        return True
    return False


def _outbound_transfer_mints(raw, keys, address):
    """Mints sent to another owner. ATA close/burn is not a sale."""
    sold = set()
    for instruction in _iter_instructions(raw):
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
    if keys and _has_reviewed_swap(raw, keys):
        return False
    inbound = False
    for instruction in _iter_instructions(raw):
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


def _wallet_traded_mints(deltas):
    return {mint for mint, qty in (deltas or {}).items() if qty != 0 and mint != WSOL}


def _material_cosigner(raw, keys, other, wallet_deltas):
    """True when the co-signer buys/sells the same mint or takes material SOL."""
    other_native, _ = _native_delta(raw, keys, other)
    other_tokens = _owned_token_deltas(raw, other)
    traded = _wallet_traded_mints(wallet_deltas)
    for mint, qty in other_tokens.items():
        if mint in traded and qty != 0:
            return True
    if other_native >= MATERIAL_SOL_LAMPORTS:
        return True
    if other_native <= -MATERIAL_SOL_LAMPORTS:
        return True
    return False


def _cosigner_is_tip_payer(raw, keys, other):
    other_native, _ = _native_delta(raw, keys, other)
    if other_native >= 0 or abs(other_native) > MATERIAL_SOL_LAMPORTS:
        return False
    meta = raw.get("meta") or {}
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    for index, key in enumerate(keys):
        if key == other or index >= len(pre) or index >= len(post):
            continue
        gained = post[index] - pre[index]
        if gained > 0 and is_verified_tip_account(key):
            return True
    return False


def _native_counterparties(raw, keys, address):
    """Accounts whose native delta opposes the wallet by a material amount."""
    wallet_delta, _ = _native_delta(raw, keys, address)
    if abs(wallet_delta) < MATERIAL_SOL_LAMPORTS:
        return []
    found = []
    for key in keys:
        if key == address or key in INFRA:
            continue
        other_delta, _ = _native_delta(raw, keys, key)
        if wallet_delta > 0 and other_delta <= -MATERIAL_SOL_LAMPORTS:
            found.append((key, "funding", min(wallet_delta, -other_delta)))
        elif wallet_delta < 0 and other_delta >= MATERIAL_SOL_LAMPORTS:
            found.append((key, "withdrawal", min(-wallet_delta, other_delta)))
    return found


def _one_hop_forwarders(parsed_rows, address, destinations):
    """Fresh addresses funded only by this wallet that later send to a controller."""
    funded_only_by_wallet = {}
    other_funders = set()
    forwards = {}
    for raw, keys, _deltas, _record, _signers, has_swap in parsed_rows:
        if has_swap:
            continue
        for key in keys:
            if key == address or key in INFRA:
                continue
            other_delta, _ = _native_delta(raw, keys, key)
            wallet_delta, _ = _native_delta(raw, keys, address)
            if wallet_delta < 0 and other_delta > 0 and key in destinations:
                funded_only_by_wallet[key] = funded_only_by_wallet.get(key, Decimal("0")) + other_delta
            elif other_delta > 0 and wallet_delta >= 0:
                other_funders.add(key)
        for dest in destinations:
            if dest not in keys:
                continue
            dest_delta, _ = _native_delta(raw, keys, dest)
            if dest_delta <= 0:
                continue
            for key in keys:
                if key in (address, dest) or key in INFRA:
                    continue
                hop_delta, _ = _native_delta(raw, keys, key)
                if hop_delta < 0 and dest_delta >= MATERIAL_SOL_LAMPORTS:
                    forwards.setdefault(key, set()).add(dest)
    hops = {}
    for hop, controllers in forwards.items():
        if hop in other_funders:
            continue
        if hop not in funded_only_by_wallet:
            continue
        hops[hop] = controllers
    return hops


def _detect_controlled_pair(parsed_rows, address):
    """Funding and withdrawals dominated by one counterparty (need not co-sign)."""
    funding = {}
    withdrawals = {}
    cosigned_with = set()
    sweep_partners = set()
    swap_cosigners = set()
    for raw, keys, deltas, _record, signers, has_swap in parsed_rows:
        if address in signers:
            for other in signers:
                if other != address:
                    cosigned_with.add(other)
                    if has_swap:
                        swap_cosigners.add(other)
    for raw, keys, deltas, _record, signers, has_swap in parsed_rows:
        if has_swap:
            continue
        for party, kind, amount in _native_counterparties(raw, keys, address):
            bucket = funding if kind == "funding" else withdrawals
            row = bucket.setdefault(party, {"lamports": Decimal("0"), "cosigned": False, "party_signed": False, "count": 0})
            row["lamports"] += amount
            row["count"] += 1
            if party in signers:
                row["party_signed"] = True
            if address in signers and party in signers:
                row["cosigned"] = True
            if kind == "withdrawal" and party in swap_cosigners:
                sweep_partners.add(party)
    total_in = sum((row["lamports"] for row in funding.values()), Decimal("0"))
    total_out = sum((row["lamports"] for row in withdrawals.values()), Decimal("0"))
    explanations = []
    flagged = []
    parties = set(funding) | set(withdrawals)
    for party in parties:
        inbound = funding.get(party) or {"lamports": Decimal("0"), "cosigned": False, "party_signed": False, "count": 0}
        outbound = withdrawals.get(party) or {"lamports": Decimal("0"), "cosigned": False, "party_signed": False, "count": 0}
        in_share = (inbound["lamports"] / total_in) if total_in else Decimal("0")
        out_share = (outbound["lamports"] / total_out) if total_out else Decimal("0")
        cosigned = inbound["cosigned"] or outbound["cosigned"] or party in cosigned_with
        # Closed loop: one signer funds the wallet and later receives the
        # sweeps. The destination of a withdrawal need not sign. Exchange
        # hot-wallet funding (no return flow) does not match.
        dominated = (
            total_in > 0 and total_out > 0
            and in_share >= CONTROLLED_SHARE
            and out_share >= CONTROLLED_SHARE
            and bool(inbound.get("party_signed"))
        )
        swept = party in sweep_partners and outbound["lamports"] >= MATERIAL_SOL_LAMPORTS
        if dominated or swept:
            flagged.append(party)
            if dominated:
                signed = "signs funding and dominates" if inbound.get("party_signed") else "dominates"
                explanations.append(
                    f"{party[:8]} {signed} funding "
                    f"({in_share:.2%}) and withdrawals ({out_share:.2%})"
                )
            if swept:
                explanations.append(
                    f"{party[:8]} is a fee-paying / swap co-signer that later sweeps proceeds"
                )
    hops = _one_hop_forwarders(parsed_rows, address, set(flagged) | set(funding) | swap_cosigners)
    for hop, controllers in hops.items():
        for controller in controllers:
            if controller not in flagged:
                flagged.append(controller)
            explanations.append(
                f"{hop[:8]} is a one-hop forwarder funded only by this wallet "
                f"that sends proceeds to {controller[:8]}"
            )
    return flagged, explanations


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
        later_sold.update(_sale_mints(raw, keys, address, deltas))
        later_sold.update(_outbound_transfer_mints(raw, keys, address))
        signers = _signers(raw, keys) if keys else []
        has_swap = bool(keys) and (
            _has_reviewed_swap(raw, keys) or bool(_wallet_traded_mints(deltas))
        )
        parsed_rows.append((raw, keys, deltas, record, signers, has_swap))

    reasons = []
    shared_funders = {}
    multi_signer = []
    proceeds_to_cosigner = []
    zero_basis = []
    quarantined = set()
    sold_quarantined = set()
    counterparts = set()
    for raw, keys, deltas, record, signers, has_swap in parsed_rows:
        native, paid = _native_delta(raw, keys, address) if keys else (Decimal("0"), False)
        message = (raw.get("transaction") or {}).get("message") or {}
        signature = ((raw.get("transaction") or {}).get("signatures") or [None])[0] or record.get("signature")
        reviewed_swap = bool(keys) and _has_reviewed_swap(raw, keys)
        wallet_sold = any(qty < 0 and mint != WSOL for mint, qty in deltas.items())
        if len(signers) > 1 and address in signers and (reviewed_swap or has_swap):
            others = [item for item in signers if item != address]
            partners = []
            for other in others:
                # Same-mint / material SOL wins over a Jito-tip disguise.
                if not _material_cosigner(raw, keys, other, deltas):
                    continue
                partners.append(other)
            if partners:
                counterparts.update(partners)
                multi_signer.append({
                    "signature": signature,
                    "co_signers": partners,
                    "fee_payer": keys[0] if keys else None,
                    "wallet_is_fee_payer": paid,
                })
                reasons.append("multi_signer_bundle_buy")
                for other in partners:
                    other_delta, _ = _native_delta(raw, keys, other)
                    if wallet_sold and other_delta >= MATERIAL_SOL_LAMPORTS:
                        proceeds_to_cosigner.append({
                            "signature": signature,
                            "co_signer": other,
                            "co_signer_sol": str(other_delta / Decimal(1_000_000_000)),
                        })
                        reasons.append("sell_proceeds_to_cosigner")
        if keys and not reviewed_swap:
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
        if keys and len(signers) > 1 and address in signers and not reviewed_swap and native < 0:
            for other in signers:
                if other == address:
                    continue
                other_delta, _ = _native_delta(raw, keys, other)
                if other_delta >= MATERIAL_SOL_LAMPORTS and (other in counterparts or other in shared_funders):
                    proceeds_to_cosigner.append({
                        "signature": signature,
                        "co_signer": other,
                        "co_signer_sol": str(other_delta / Decimal(1_000_000_000)),
                    })
                    reasons.append("sell_proceeds_to_cosigner")
        if _token_transfer_in(raw, keys, address):
            gained = {mint: qty for mint, qty in deltas.items() if qty > 0}
            # A material SOL debit with a token credit is a paid (possibly
            # unreviewed) buy, not a gifted inflow. Unknown basis is a
            # history problem, not a bundle transfer-in.
            if native <= -MATERIAL_SOL_LAMPORTS and gained:
                continue
            for mint in gained:
                if mint in (WSOL,):
                    continue
                quarantined.add(mint)
            if any(mint in later_sold for mint in gained if mint != WSOL):
                sold_quarantined.update(mint for mint in gained if mint in later_sold and mint != WSOL)
                zero_basis.append(signature)
    if shared_funders and multi_signer:
        reasons.append("shared_funder")
    controlled, controlled_explanations = _detect_controlled_pair(parsed_rows, address)
    if controlled:
        reasons.append("controlled_pair")
    # Wallet-level zero-basis is gone. Never-sold inflows are quarantined
    # inventory only. A later sale of a quarantined mint is unresolved, not
    # a wallet-level lead block.
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
        "quarantined_mints": sorted(quarantined),
        "sold_quarantined_mints": sorted(sold_quarantined),
        "controlled_pair": controlled,
        "controlled_pair_explanation": "; ".join(controlled_explanations) if controlled_explanations else None,
        "lead_eligible": not excluded,
    }
