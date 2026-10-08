"""Exclusive captured-record partition. Decoder output is never inferred from deltas."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

from scanner.investigation import (
    ASSOCIATED_ID,
    COMPUTE_ID,
    JUPITER,
    LIGHTHOUSE,
    MEMO_IDS,
    PUMP,
    PUMP_SWAP,
    RAYDIUM_AMM,
    RAYDIUM_CPMM,
    SYSTEM_ID,
    TOKEN_IDS,
    WHIRLPOOL,
    WSOL,
    USDC,
    _keys,
)
from scanner.mass_search.canonical_records import unwrap_gta_record
from scanner.mass_search.research_profile import _display_decimal

INFRA_PROGRAMS = {
    SYSTEM_ID,
    COMPUTE_ID,
    ASSOCIATED_ID,
    *TOKEN_IDS,
    *MEMO_IDS,
    LIGHTHOUSE,
}
SOL_SWAP_FLOOR = Decimal("0.003")
LAMPORTS = Decimal(1_000_000_000)
WINDOW_CLASSES = (
    "outside_window",
    "failed",
    "non_swap",
    "unsupported_swap",
    "decoded_trade",
    "decoded_conversion",
)
# Item 12 replaces the 10% consideration gate. Coverage eligibility is
# evaluated in workflow.coverage_eligibility (99 / 95 / blocked + dependency).
COVERAGE_POLICY = {"provisional": Decimal("0.99"), "watchlist": Decimal("0.95")}


def _unix(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str) and value:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
    return None


def _account_keys(raw):
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    try:
        return _keys(message, meta)
    except (ValueError, TypeError, KeyError, IndexError):
        return []


def _program_of(instruction, keys):
    program = instruction.get("programId")
    if isinstance(program, str) and program:
        return program
    index = instruction.get("programIdIndex")
    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(keys):
        return keys[index]
    return None


def _outer_non_infra(raw, keys):
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    programs = []
    for instruction in message.get("instructions") or []:
        if not isinstance(instruction, dict):
            continue
        program = _program_of(instruction, keys)
        if program and program not in INFRA_PROGRAMS:
            programs.append(program)
    return programs


def _owned_asset_deltas(raw, address, keys):
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    pre_native = meta.get("preBalances") or []
    post_native = meta.get("postBalances") or []
    fee = meta.get("fee") if isinstance(meta.get("fee"), int) and not isinstance(meta.get("fee"), bool) else 0
    try:
        wallet_index = keys.index(address)
    except ValueError:
        return {}
    if wallet_index >= len(pre_native) or wallet_index >= len(post_native):
        return {}
    native = Decimal(post_native[wallet_index] - pre_native[wallet_index])
    if keys and keys[0] == address:
        native += Decimal(fee)
    token_deltas = {}
    wsol = Decimal("0")
    identities = {}
    for field, sign in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        for balance in meta.get(field) or []:
            if not isinstance(balance, dict) or balance.get("owner") != address:
                continue
            mint = balance.get("mint")
            amount = (balance.get("uiTokenAmount") or {}).get("amount")
            if not isinstance(mint, str) or amount in (None, ""):
                continue
            token_deltas[mint] = token_deltas.get(mint, Decimal("0")) + Decimal(str(amount)) * sign
            index = balance.get("accountIndex")
            if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(keys):
                identities[keys[index]] = mint
    wsol += token_deltas.pop(WSOL, Decimal("0"))
    # Same-tx native withdrawals to non-owned accounts are added back as tips.
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    tip = Decimal("0")
    for instruction in message.get("instructions") or []:
        parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else None
        if not isinstance(info, dict) or parsed.get("type") != "transfer":
            continue
        if info.get("source") != address:
            continue
        dest = info.get("destination")
        lamports = info.get("lamports")
        if dest in identities or dest == address:
            continue
        if isinstance(lamports, int) and not isinstance(lamports, bool):
            tip += Decimal(lamports)
    sol = (native + wsol + tip) / LAMPORTS
    deltas = dict(token_deltas)
    if sol != 0:
        deltas["SOL"] = sol
    return deltas


def _is_swap_heuristic(raw, address, keys):
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    if meta.get("err") is not None:
        return False
    if not _outer_non_infra(raw, keys):
        return False
    deltas = _owned_asset_deltas(raw, address, keys)
    if not deltas:
        return False
    sol = deltas.get("SOL", Decimal("0"))
    positives = [mint for mint, value in deltas.items() if value > 0]
    negatives = [mint for mint, value in deltas.items() if value < 0]
    if not positives or not negatives:
        return False
    if abs(sol) > 0 and abs(sol) <= SOL_SWAP_FLOOR and set(deltas) <= {"SOL", USDC}:
        # Tiny SOL dust against USDC is still a quote conversion when USDC moved.
        if USDC in deltas and deltas[USDC] != 0:
            return True
        return False
    if "SOL" in deltas and abs(sol) <= SOL_SWAP_FLOOR and all(mint in {"SOL", USDC} or True for mint in deltas):
        if abs(sol) <= SOL_SWAP_FLOOR and USDC not in deltas:
            token_moves = [mint for mint in deltas if mint not in {"SOL", USDC} and deltas[mint] != 0]
            if token_moves and abs(sol) <= SOL_SWAP_FLOOR:
                return True
    return True


def _decoded_kinds(decoded, signature):
    kinds = []
    for event in decoded.get("events") or []:
        if event.get("signature") != signature:
            continue
        if event.get("kind") in ("buy", "sell", "conversion"):
            kinds.append(event.get("kind"))
    return kinds


def _consideration(raw, address, keys, event=None):
    """Quote consideration for coverage. Fee/rent residual SOL is not a quote asset."""
    if event:
        usdc = event.get("amount_usdc") or event.get("consideration_usdc")
        sol = event.get("amount_sol") or event.get("consideration_sol")
        if usdc not in (None, ""):
            return "USDC", Decimal(str(usdc))
        if sol not in (None, ""):
            return "SOL", Decimal(str(sol))
    deltas = _owned_asset_deltas(raw, address, keys)
    usdc = abs(deltas.get(USDC, Decimal("0")))
    if usdc:
        return "USDC", usdc / Decimal(1_000_000)
    sol = abs(deltas.get("SOL", Decimal("0")))
    if sol <= SOL_SWAP_FLOOR:
        return None, Decimal("0")
    return "SOL", sol


def _span_hours(timestamps):
    if not timestamps:
        return None
    span = max(timestamps) - min(timestamps)
    hours = Decimal(span) / Decimal(3600)
    text = format(hours.quantize(Decimal("0.1")), "f")
    return {
        "seconds": span,
        "hours": text.rstrip("0").rstrip(".") if "." in text else text,
        "start": datetime.fromtimestamp(min(timestamps), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": datetime.fromtimestamp(max(timestamps), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def partition_records(records, decoded, address, *, window_start, window_end, acquisition_start=None):
    """Exclusive class for every captured record.

    Swap heuristic (box verifier): successful transaction, a non-infra outer
    program is present, and the wallet's owned assets move in opposite
    directions. SOL is native + wSOL plus fee and tip add-backs. |SOL| > 0.003
    is required when SOL is the only quote leg against a token. Counts may
    shift by ±1–2 only with a documented reason.
    """
    start = _unix(window_start)
    end = _unix(window_end)
    acquisition = _unix(acquisition_start) if acquisition_start else start
    decoded_by_sig = {}
    for event in decoded.get("events") or []:
        signature = event.get("signature")
        if event.get("kind") in ("buy", "sell", "conversion"):
            decoded_by_sig.setdefault(signature, []).append(event)
    rows = []
    counts = Counter()
    in_window_swaps = 0
    unsupported = []
    decoded_trade = 0
    decoded_conversion = 0
    consideration = {"decoded": {"SOL": Decimal("0"), "USDC": Decimal("0")},
                     "unsupported": {"SOL": Decimal("0"), "USDC": Decimal("0")}}
    in_window_times = []
    venue_counts = Counter()
    for record in records or []:
        raw = unwrap_gta_record(record)
        signature = None
        if isinstance(record, dict):
            signature = record.get("signature")
        if isinstance(raw, dict):
            signature = signature or raw.get("signature")
            tx = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
            sigs = tx.get("signatures") or []
            if not signature and sigs:
                signature = sigs[0]
        meta = raw.get("meta") if isinstance(raw, dict) and isinstance(raw.get("meta"), dict) else {}
        timestamp = raw.get("blockTime") if isinstance(raw, dict) else None
        version = raw.get("version", "legacy") if isinstance(raw, dict) else "legacy"
        keys = _account_keys(raw) if isinstance(raw, dict) else []
        programs = _outer_non_infra(raw, keys) if isinstance(raw, dict) else []
        kinds = _decoded_kinds(decoded, signature)
        in_window = True
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            if (acquisition is not None and timestamp < acquisition) or (end is not None and timestamp >= end):
                in_window = False
            elif in_window:
                in_window_times.append(int(timestamp))
        if not in_window:
            klass = "outside_window"
        elif meta.get("err") is not None:
            klass = "failed"
        elif "buy" in kinds or "sell" in kinds:
            klass = "decoded_trade"
            decoded_trade += 1
        elif "conversion" in kinds:
            klass = "decoded_conversion"
            decoded_conversion += 1
        elif _is_swap_heuristic(raw, address, keys):
            klass = "unsupported_swap"
        else:
            klass = "non_swap"
        reason = None
        if klass == "unsupported_swap":
            reasons = [
                issue.get("reason")
                for issue in (decoded.get("unresolved") or [])
                if issue.get("signature") == signature
            ]
            reason = reasons[0] if reasons else "No reviewed outer spot swap; transfers and balances alone do not prove trading"
            venue_counts[programs[0] if programs else "unknown"] += 1
            unsupported.append({
                "signature": signature,
                "program": programs[0] if programs else None,
                "programs": programs,
                "version": version,
                "reason": reason,
            })
        if klass in ("decoded_trade", "decoded_conversion", "unsupported_swap"):
            in_window_swaps += 1
            event = (decoded_by_sig.get(signature) or [None])[0]
            asset, amount = _consideration(raw, address, keys, event)
            if asset and amount:
                bucket = "decoded" if klass != "unsupported_swap" else "unsupported"
                consideration[bucket][asset] += amount
        counts[klass] += 1
        rows.append({
            "signature": signature,
            "class": klass,
            "version": version,
            "programs": programs,
            "reason": reason,
            "in_window": in_window,
        })
    by_count = None
    by_consideration = {}
    if in_window_swaps:
        by_count = _display_decimal(Decimal(counts["unsupported_swap"]) / Decimal(in_window_swaps))
    for asset in ("SOL", "USDC"):
        total = consideration["decoded"][asset] + consideration["unsupported"][asset]
        if total:
            by_consideration[asset] = _display_decimal(consideration["unsupported"][asset] / total)
    unresolved_count = Decimal(str(by_count)) if by_count is not None else None
    resolved_count = (Decimal("1") - unresolved_count) if unresolved_count is not None else None
    coverage_blocked = (
        resolved_count is None
        or resolved_count < COVERAGE_POLICY["watchlist"]
        or any(Decimal("1") - Decimal(str(share)) < COVERAGE_POLICY["watchlist"] for share in by_consideration.values())
    )
    return {
        "kind": "record-breakdown-v1",
        "address": address,
        "transactions": len(rows),
        "counts": {key: int(counts.get(key) or 0) for key in WINDOW_CLASSES},
        "rows": rows,
        "unsupported_swaps": unsupported,
        "unsupported_swaps_by_program": dict(venue_counts),
        "in_window_swaps": in_window_swaps,
        "decoded_trade": decoded_trade,
        "decoded_conversion": decoded_conversion,
        "unsupported_swap_share_in_window": {
            "by_count": by_count,
            "by_consideration": by_consideration,
        },
        "consideration": {
            "decoded": {asset: _display_decimal(value) for asset, value in consideration["decoded"].items() if value},
            "unsupported": {asset: _display_decimal(value) for asset, value in consideration["unsupported"].items() if value},
        },
        "in_window_span": _span_hours(in_window_times),
        "coverage_policy": {key: str(value) for key, value in COVERAGE_POLICY.items()},
        "coverage_blocked": coverage_blocked,
        "heuristic": (
            "successful tx, non-infra program, opposite-direction owned assets; "
            "SOL = native+wSOL + fee + tip add-backs; |SOL| > 0.003"
        ),
        "PRODUCT_READY": False,
    }


def attach_record_breakdown(report, records, decoded, address, *, window_start, window_end, acquisition_start=None):
    breakdown = partition_records(
        records, decoded, address,
        window_start=window_start,
        window_end=window_end,
        acquisition_start=acquisition_start,
    )
    report["record_breakdown"] = breakdown
    report["unsupported_swaps_in_window"] = breakdown["counts"]["unsupported_swap"]
    report["in_window_swaps"] = breakdown["in_window_swaps"]
    report["unsupported_swap_share_in_window"] = breakdown["unsupported_swap_share_in_window"]
    report["in_window_span"] = breakdown["in_window_span"]
    return breakdown
