"""Result-relevant coverage gate (coverage-gate result-relevant-v1).

The 0.99 count AND value gate applies to set R, not the whole captured span.

R contains:
1. Every swap-like tx (heuristic or decoded) in [REPORT_START, REPORT_END).
2. Every tx before REPORT_END whose wallet deltas touch a lineage mint.
   Lineage mints are non-quote mints with a sell, flatten, or counted episode
   close in the report window. SOL / wSOL / USDC / USDT are never lineage.
3. Any tx we cannot prove is irrelevant: missing timestamp, missing report
   bounds, or an outside-window tx whose mint set cannot be read.

Empty R or a missing value denominator blocks. Adding an unreadable member
to R can only lower coverage. PRODUCT_READY stays false.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from scanner.mass_search.canonical_records import unwrap_gta_record
from scanner.mass_search.record_breakdown import (
    USDC,
    USDT,
    WSOL,
    _account_keys,
    _consideration_legs,
    _decoded_kinds,
    _is_swap_heuristic,
    _owned_asset_deltas,
    _unix,
)
from scanner.mass_search.verified_costs import is_verified_tip_account

SYSTEM_PROGRAM = "11111111111111111111111111111111"
RENT_EXEMPT_BASE = 890880
RENT_EXEMPT_PER_BYTE = 6960
LAMPORTS = Decimal("1000000000")


def _rent_exempt_minimum_lamports(space):
    try:
        space_n = int(space)
    except (TypeError, ValueError):
        return None
    if space_n < 0:
        return None
    return RENT_EXEMPT_BASE + RENT_EXEMPT_PER_BYTE * space_n


def _iter_coverage_instructions(raw):
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    yield from message.get("instructions") or []
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    for group in meta.get("innerInstructions") or []:
        if isinstance(group, dict):
            yield from group.get("instructions") or []


def _proven_excluded_sol_lamports(raw, address, keys):
    """Exact createAccount rent (wallet-funded, non-System owner) and verified tips."""
    excluded = Decimal("0")
    for instruction in _iter_coverage_instructions(raw):
        if not isinstance(instruction, dict):
            continue
        parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else None
        if not parsed:
            continue
        info = parsed.get("info") or {}
        kind = parsed.get("type")
        program = instruction.get("programId")
        if program == SYSTEM_PROGRAM and kind in ("createAccount", "createAccountWithSeed"):
            if info.get("source") != address:
                continue
            owner = info.get("owner")
            if not owner or owner == SYSTEM_PROGRAM:
                continue
            expected = _rent_exempt_minimum_lamports(info.get("space"))
            try:
                lamports = int(info.get("lamports"))
            except (TypeError, ValueError):
                continue
            if expected is not None and lamports == expected:
                excluded += Decimal(lamports)
            continue
        if kind == "transfer" and info.get("source") == address:
            dest = info.get("destination")
            if dest and is_verified_tip_account(dest):
                try:
                    excluded += Decimal(int(info.get("lamports")))
                except (TypeError, ValueError):
                    pass
    return excluded


def _coverage_sol_after_proven_exclusions(raw, address, keys):
    """SOL that left the wallet after only proven fee / exact rent / verified-tip exclusions.

    Unknown System transfers and OTC-shaped instruction lists stay unreadable value.
    """
    if not isinstance(raw, dict) or not keys or not address:
        return Decimal("0")
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    try:
        idx = keys.index(address)
    except ValueError:
        return Decimal("0")
    if idx >= len(pre) or idx >= len(post):
        return Decimal("0")
    native = Decimal(post[idx] - pre[idx])
    fee = meta.get("fee") if isinstance(meta.get("fee"), int) and not isinstance(meta.get("fee"), bool) else 0
    if keys and keys[0] == address:
        native += Decimal(fee)
    native += _proven_excluded_sol_lamports(raw, address, keys)
    wsol = Decimal("0")
    for field, sign in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        for row in meta.get(field) or []:
            if not isinstance(row, dict) or row.get("owner") != address:
                continue
            if row.get("mint") != WSOL:
                continue
            amount = (row.get("uiTokenAmount") or {}).get("amount")
            if amount in (None, ""):
                continue
            try:
                wsol += Decimal(str(amount)) * sign
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                continue
    remaining = native + wsol
    if remaining >= 0:
        return Decimal("0")
    return abs(remaining) / LAMPORTS

_DISPLAY_QUANTUM = Decimal("0.000000001")


def _display_decimal(value):
    if value in (None, ""):
        return None
    quantized = Decimal(str(value)).quantize(_DISPLAY_QUANTUM)
    text = format(quantized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text

COVERAGE_GATE_VERSION = "result-relevant-v1"
QUOTE_MINTS = frozenset({WSOL, USDC, USDT, "SOL"})


def _signature(record, raw):
    signature = None
    if isinstance(record, dict):
        signature = record.get("signature")
    if isinstance(raw, dict):
        signature = signature or raw.get("signature")
        tx = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
        sigs = tx.get("signatures") or []
        if not signature and sigs:
            signature = sigs[0]
    return signature


def _block_time(record, raw):
    for source in (raw, record):
        if not isinstance(source, dict):
            continue
        stamp = source.get("blockTime")
        if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
            return int(stamp)
        stamp = source.get("timestamp")
        if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
            return int(stamp)
    return None


def _in_report(timestamp, start, end):
    return (
        timestamp is not None
        and start is not None
        and end is not None
        and start <= timestamp < end
    )


def _tx_failed(raw):
    meta = raw.get("meta") if isinstance(raw, dict) else None
    return isinstance(meta, dict) and meta.get("err") is not None


def _owner_token_maps(raw, address):
    """Owner-keyed mint→amount maps. None if any token row is unreadable."""
    if not isinstance(raw, dict) or not address:
        return None
    meta = raw.get("meta")
    if not isinstance(meta, dict):
        return None
    pre_token = meta.get("preTokenBalances")
    post_token = meta.get("postTokenBalances")
    if not isinstance(pre_token, list) or not isinstance(post_token, list):
        return None
    pre, post = {}, {}
    for sign, rows, dest in ((-1, pre_token, pre), (1, post_token, post)):
        del sign
        for row in rows:
            if not isinstance(row, dict):
                return None
            amount = (row.get("uiTokenAmount") or {}).get("amount")
            mint = row.get("mint")
            if mint in (None, "") or amount in (None, ""):
                return None
            if "owner" not in row or row.get("owner") in (None, ""):
                return None
            if row.get("owner") != address:
                continue
            try:
                dest[mint] = dest.get(mint, Decimal("0")) + Decimal(str(amount))
            except (InvalidOperation, ValueError, TypeError, OverflowError):
                return None
    return pre, post


def wallet_touched_mints(raw, address):
    """Owned mints with a nonzero wallet delta, or None if unreadably ambiguous.

    Wallet-not-in-keys still reads owner-keyed token rows (keeper fills and
    ATA airdrops). Native SOL is only visible when the wallet is in keys.
    Malformed token rows stay None (fail closed).
    """
    maps = _owner_token_maps(raw, address)
    if maps is None:
        return None
    pre, post = maps
    touched = {mint for mint in set(pre) | set(post) if pre.get(mint, Decimal("0")) != post.get(mint, Decimal("0"))}
    keys = _account_keys(raw) if isinstance(raw, dict) else []
    if address in keys:
        try:
            deltas = _owned_asset_deltas(raw, address, keys)
        except Exception:
            return None
        return frozenset(mint for mint, qty in deltas.items() if qty != 0)
    return frozenset(touched)


def _native_unexplained_by_fee(raw, address, keys):
    """True when native SOL movement is not exactly the paid meta.fee."""
    if address not in (keys or []):
        return False
    meta = raw.get("meta") if isinstance(raw, dict) else {}
    if not isinstance(meta, dict):
        return True
    pre_native = meta.get("preBalances")
    post_native = meta.get("postBalances")
    if not isinstance(pre_native, list) or not isinstance(post_native, list):
        return True
    index = keys.index(address)
    if index >= len(pre_native) or index >= len(post_native):
        return True
    try:
        delta = Decimal(str(post_native[index])) - Decimal(str(pre_native[index]))
        fee = Decimal(str(meta.get("fee") or 0))
    except Exception:
        return True
    return delta + fee != 0


def _positively_non_economic(raw, address, keys, mints, swap_like, decoded_kinds):
    """True only when the tx is proved idle (fee-only, failed, or zero deltas)."""
    if _tx_failed(raw):
        return True
    if swap_like or decoded_kinds:
        return False
    if mints is None:
        return False
    if mints - QUOTE_MINTS:
        return False
    if "SOL" in (mints or ()) and _native_unexplained_by_fee(raw, address, keys):
        return False
    if any(mint in (USDC, USDT, WSOL) for mint in (mints or ())):
        return False
    return True


def _in_window_heuristic_sell_mints(records, address, start, end, decoded=None):
    """Non-quote mints the wallet sold in-window, decoded or only swap-like.

    An undecoded window sell still creates lineage so a superset window cannot
    drop the pre-window buys of that mint from R.
    """
    found = set()
    if not records or not address:
        return found
    for record in records:
        raw = unwrap_gta_record(record)
        timestamp = _block_time(record, raw)
        if not _in_report(timestamp, start, end):
            continue
        keys = _account_keys(raw) if isinstance(raw, dict) else []
        signature = _signature(record, raw)
        kinds = _decoded_kinds(decoded or {}, signature)
        mints = wallet_touched_mints(raw, address)
        if mints is None:
            continue
        if not _swap_like(raw, address, keys, kinds) and not any(kind in ("sell", "flatten") for kind in kinds):
            continue
        maps = _owner_token_maps(raw, address)
        if maps is None:
            continue
        pre, post = maps
        for mint in mints - QUOTE_MINTS:
            if post.get(mint, Decimal("0")) < pre.get(mint, Decimal("0")):
                found.add(mint)
    return found


def lineage_mints(*, decoded_events=None, episodes=None, ledger=None, report_start=None, report_end=None, records=None, address=None, decoded=None):
    """Non-quote mints whose window sells/flattens/counted episodes matter."""
    start = _unix(report_start)
    end = _unix(report_end)
    lineage = set()
    for event in decoded_events or []:
        if not isinstance(event, dict):
            continue
        mint = event.get("mint")
        if not mint or mint in QUOTE_MINTS:
            continue
        kind = event.get("kind")
        timestamp = event.get("timestamp")
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            timestamp = int(timestamp)
        else:
            timestamp = None
        if kind in ("sell", "flatten") and _in_report(timestamp, start, end):
            lineage.add(mint)
    for item in ledger or []:
        if not isinstance(item, dict):
            continue
        mint = item.get("mint")
        if mint and mint not in QUOTE_MINTS:
            lineage.add(mint)
    detail = {}
    if isinstance(episodes, dict):
        detail = episodes.get("per_mint_detail") or episodes.get("per_mint") or {}
    for mint, info in detail.items():
        if not mint or mint in QUOTE_MINTS:
            continue
        count = info if isinstance(info, int) else (info or {}).get("completed_episodes") or 0
        if count:
            lineage.add(mint)
    lineage |= _in_window_heuristic_sell_mints(records, address, start, end, decoded)
    return frozenset(lineage)


def _swap_like(raw, address, keys, decoded_kinds):
    if decoded_kinds:
        return True
    if not isinstance(raw, dict) or not keys:
        return False
    return _is_swap_heuristic(raw, address, keys)


def relevant_membership(records, decoded, address, *, report_start, report_end, lineage):
    """Classify each captured tx for R. Fail closed when relevance cannot be proved."""
    start = _unix(report_start)
    end = _unix(report_end)
    rows = []
    for record in records or []:
        raw = unwrap_gta_record(record)
        signature = _signature(record, raw)
        timestamp = _block_time(record, raw)
        keys = _account_keys(raw) if isinstance(raw, dict) else []
        kinds = _decoded_kinds(decoded or {}, signature)
        mints = wallet_touched_mints(raw, address)
        swap_like = _swap_like(raw, address, keys, kinds)
        reasons = []
        failed = _tx_failed(raw)
        in_report = _in_report(timestamp, start, end)
        before_end = timestamp is not None and (end is None or timestamp < end)
        outside = timestamp is not None and start is not None and end is not None and not in_report
        if start is None or end is None:
            reasons.append("unknown_report_bounds")
        if timestamp is None:
            reasons.append("unknown_timestamp")
        if in_report and swap_like:
            reasons.append("in_window_swap_like")
        if before_end and mints is not None and (mints - QUOTE_MINTS) & set(lineage):
            reasons.append("lineage_touch")
        # DC-1: any in-window tx that touches the wallet and is not proved
        # non-economic is unreadable. Failed txs are non-economic.
        if in_report and not failed and not _positively_non_economic(
            raw, address, keys, mints, swap_like, kinds,
        ):
            if "in_window_swap_like" not in reasons:
                reasons.append("unreadable_in_window")
        # Unknown mint sets stay in R except out-of-window spam that is
        # proved idle or whose mints are known and not lineage (DC-11).
        if mints is None and not failed and (outside or timestamp is None or in_report):
            if "unreadable_in_window" not in reasons and "in_window_swap_like" not in reasons:
                reasons.append("unreadable_unknown_mints")
        in_r = bool(reasons)
        rows.append({
            "signature": signature,
            "timestamp": timestamp,
            "in_r": in_r,
            "reasons": reasons,
            "swap_like": swap_like,
            "decoded_kinds": list(kinds),
            "mints": None if mints is None else sorted(mints),
            "mints_known": mints is not None,
        })
    return rows


def _shares_from_totals(decoded_n, unsupported_n, consideration):
    denom = decoded_n + unsupported_n
    by_count = None
    if denom:
        by_count = _display_decimal(Decimal(unsupported_n) / Decimal(denom))
    by_consideration = {}
    for asset in ("SOL", "USDC", "USDT"):
        total = consideration["decoded"][asset] + consideration["unsupported"][asset]
        if total:
            by_consideration[asset] = _display_decimal(consideration["unsupported"][asset] / total)
    count_share = (Decimal("1") - Decimal(str(by_count))) if by_count is not None else None
    value_coverages = []
    for value in by_consideration.values():
        amount = Decimal(str(value))
        value_coverages.append(Decimal("1") - amount)
    value_share = min(value_coverages) if value_coverages else None
    mandatory = None
    if count_share is not None and value_share is not None:
        mandatory = min(count_share, value_share)
    return {
        "by_count": by_count,
        "by_consideration": by_consideration,
        "coverage_count_share": _display_decimal(count_share),
        "coverage_value_share": _display_decimal(value_share),
        "coverage_mandatory_share": _display_decimal(mandatory),
        "count_share": count_share,
        "value_share": value_share,
        "mandatory_share": mandatory,
        "decoded_n": decoded_n,
        "unsupported_n": unsupported_n,
        "denominator": denom,
    }


def coverage_over_relevant(records, decoded, address, membership):
    """Count/value coverage over swap-like, decoded, or unreadable members of R."""
    by_sig = {row["signature"]: row for row in membership if row.get("signature")}
    consideration = {
        "decoded": {"SOL": Decimal("0"), "USDC": Decimal("0"), "USDT": Decimal("0")},
        "unsupported": {"SOL": Decimal("0"), "USDC": Decimal("0"), "USDT": Decimal("0")},
    }
    decoded_n = 0
    unsupported_n = 0
    decoded_by_sig = {}
    for event in (decoded or {}).get("events") or []:
        signature = event.get("signature")
        if event.get("kind") in ("buy", "sell", "conversion"):
            decoded_by_sig.setdefault(signature, []).append(event)
    for record in records or []:
        raw = unwrap_gta_record(record)
        signature = _signature(record, raw)
        member = by_sig.get(signature)
        if not member or not member.get("in_r"):
            continue
        keys = _account_keys(raw) if isinstance(raw, dict) else []
        kinds = member.get("decoded_kinds") or []
        decoded_trade = any(kind in ("buy", "sell", "conversion") for kind in kinds)
        # DC-2: every member of R is counted. Lineage-only rows are unsupported.
        event = (decoded_by_sig.get(signature) or [None])[0]
        legs = _consideration_legs(raw, address, keys, event)
        if decoded_trade:
            decoded_n += 1
            bucket = "decoded"
        else:
            unsupported_n += 1
            bucket = "unsupported"
        # Count every R member (DC-2), including lineage-only rows. SOL that
        # left the wallet is unreadable value unless it is a proven fee, an
        # exact rent-exempt createAccount, or a verified tip. Unknown
        # instruction shapes (OTC System+Token) stay in the value bucket.
        for asset, amount in legs.items():
            if not asset or not amount:
                continue
            if asset == "SOL" and not decoded_trade:
                continue
            consideration[bucket][asset] += amount
        if not decoded_trade:
            sol = _coverage_sol_after_proven_exclusions(raw, address, keys)
            if sol:
                consideration[bucket]["SOL"] += sol
    shares = _shares_from_totals(decoded_n, unsupported_n, consideration)
    shares["consideration"] = {
        "decoded": {asset: _display_decimal(value) for asset, value in consideration["decoded"].items() if value},
        "unsupported": {asset: _display_decimal(value) for asset, value in consideration["unsupported"].items() if value},
    }
    return shares


def build_result_relevant(records, decoded, address, *, report_start, report_end, episodes=None, ledger=None):
    """Build R and the result-relevant coverage shares."""
    lineage = lineage_mints(
        decoded_events=(decoded or {}).get("events") or [],
        episodes=episodes,
        ledger=ledger,
        report_start=report_start,
        report_end=report_end,
        records=records,
        address=address,
        decoded=decoded,
    )
    membership = relevant_membership(
        records, decoded, address,
        report_start=report_start,
        report_end=report_end,
        lineage=lineage,
    )
    signatures = [row["signature"] for row in membership if row.get("in_r") and row.get("signature")]
    shares = coverage_over_relevant(records, decoded, address, membership)
    empty = not signatures or shares["denominator"] == 0
    count_share = None if empty else shares["count_share"]
    value_share = None if empty else shares["value_share"]
    gate_passed = (
        not empty
        and count_share is not None
        and value_share is not None
        and count_share >= Decimal("0.99")
        and value_share >= Decimal("0.99")
    )
    return {
        "version": COVERAGE_GATE_VERSION,
        "signatures": signatures,
        "size": len(signatures),
        "empty": empty,
        "lineage_mints": sorted(lineage),
        "membership": membership,
        "unsupported_swap_share": {
            "by_count": shares["by_count"],
            "by_consideration": shares["by_consideration"],
        },
        "coverage_count_share": None if empty else shares["coverage_count_share"],
        "coverage_value_share": None if empty else shares["coverage_value_share"],
        "coverage_mandatory_share": None if empty else shares["coverage_mandatory_share"],
        "count_share": None if empty else _display_decimal(shares["count_share"]),
        "value_share": None if empty else _display_decimal(shares["value_share"]),
        "mandatory_share": None if empty else _display_decimal(shares["mandatory_share"]),
        "gate_passed": gate_passed,
        "decoded_n": shares["decoded_n"],
        "unsupported_n": shares["unsupported_n"],
        "denominator": shares["denominator"],
        "consideration": shares["consideration"],
        "PRODUCT_READY": False,
    }


def attach_result_relevant(
    report,
    records,
    decoded,
    address,
    *,
    report_start,
    report_end,
    episodes=None,
    ledger=None,
):
    """Write R onto the report and its record_breakdown. Replaces cached shares."""
    relevant = build_result_relevant(
        records, decoded, address,
        report_start=report_start,
        report_end=report_end,
        episodes=episodes,
        ledger=ledger,
    )
    breakdown = (report or {}).setdefault("record_breakdown", {})
    breakdown["result_relevant"] = {
        key: relevant[key]
        for key in (
            "version", "signatures", "size", "empty", "lineage_mints",
            "unsupported_swap_share", "coverage_count_share", "coverage_value_share",
            "coverage_mandatory_share", "decoded_n", "unsupported_n",
            "denominator", "consideration", "gate_passed", "PRODUCT_READY",
        )
    }
    report["result_relevant"] = breakdown["result_relevant"]
    report["coverage_gate_version"] = COVERAGE_GATE_VERSION
    report["coverage_count_share_result_relevant"] = relevant["coverage_count_share"]
    report["coverage_value_share_result_relevant"] = relevant["coverage_value_share"]
    report["result_relevant_size"] = relevant["size"]
    report["result_relevant_lineage_mints"] = relevant["lineage_mints"]
    return relevant
