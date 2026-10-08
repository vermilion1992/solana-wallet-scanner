"""Readable-first funnel. Drop or defer only. Gates stay fail-closed.

Stages: discovery → Rule A → cheap bot pre-screen → decodability sample →
deep pull of the top N survivors. A seed is never evidence.
"""
from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from scanner.investigation import (
    USDC,
    USDT,
    WSOL,
    decode_supported_swaps,
    net_balance_reviewed_swap,
)
from scanner.mass_search.canonical_records import canonical_decode_records, unwrap_gta_record
from scanner.mass_search.qualification_gates import (
    GT_ECONOMIC_TRADES_RULE,
    MAX_ECONOMIC_TRADES_PER_UTC_DAY,
)
from scanner.mass_search.record_breakdown import _account_keys, _is_swap_heuristic, _owned_asset_deltas, _outer_non_infra
from scanner.mass_search.seed_sources import (
    HELIUS_SIGNATURES_CREDIT_NOTE,
    HELIUS_SIGNATURES_HISTORY_CAP,
    HELIUS_SIGNATURES_METHOD,
    HELIUS_SIGNATURES_PAGE_SIZE,
    HELIUS_SIGNATURES_UNITS,
    NANSEN_DEX_TRADES_UNITS,
    NANSEN_LEADERBOARD_UNITS,
    NANSEN_PROFILER_UNITS,
    NANSEN_TGM_PNL_LEADERBOARD_UNITS,
    NANSEN_TIMEFRAMES_FUNNEL,
    helius_signatures_prescreen,
    nansen_dex_trades_drop,
    nansen_leaderboard_page_count,
)

FUNNEL_VERSION = "readable-first-v1"
READABLE_SHARE_THRESHOLD = Decimal("0.97")
SAMPLE_TX_TARGET = 100
SAMPLE_PAGES_DEFAULT = 2
SAMPLE_PAGE_UNITS = 10  # Helius enhanced full, limit 100
SAMPLE_CLASS_REVIEWED = "reviewed_decoder"
SAMPLE_CLASS_NET = "net_balance"
SAMPLE_CLASS_UNREADABLE = "unreadable"
KEEP = "keep"
DEFER_UNREADABLE = "deferred_unreadable"
DROP = "dropped"
UNSCREENED = "unscreened"
QUOTE_MINTS = frozenset({WSOL, USDC, USDT, "SOL"})
GATES_UNCHANGED = (
    "coverage_0.99_result_relevant",
    "min_3_completed_episodes",
    "independently_audited_within_2",
    "zero_unresolved_basis_sales",
    "bot_gt_15_economic_trades_full_history",
)
EARLY_WATCH_MIN_EPISODES = 1
# Lending / limit-order / dedicated MM programs. Spot-swap venues (Jupiter,
# Pump, Raydium, Orca) are not on this list even when they also host LPs.
INFRA_PRESCREEN_PROGRAMS = frozenset({
    "KLend2g3cP87szom1FxFdkHw6cCLVYqPAFHL7Lw5EJx",  # Kamino lend
    "So1endDq2YkqhipRh3WViPa8hdiSpxWy6z3Z6tMCpAo",  # Solend
    "MFv2hWf31Z9kbCa1snEPYctwafyhdvnV7FZnkobGM7s",  # Marginfi
    "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjHFBjDz",  # Phoenix
    "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX",  # OpenBook
    "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin",  # Serum
})
LP_LOG_HINTS = (
    "AddLiquidity", "RemoveLiquidity", "OpenPosition", "ClosePosition",
    "IncreaseLiquidity", "DecreaseLiquidity", "Deposit", "Withdraw",
)


def _dec(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _signature(record):
    if not isinstance(record, dict):
        return None
    raw = unwrap_gta_record(record)
    if isinstance(raw, dict):
        sigs = (raw.get("transaction") or {}).get("signatures") if isinstance(raw.get("transaction"), dict) else None
        if isinstance(sigs, list) and sigs:
            return sigs[0]
    return record.get("signature")


def _event_value(event):
    for key in ("consideration_usdc", "amount_usdc", "quote_usdc", "consideration"):
        amount = _dec(event.get(key) if isinstance(event, dict) else None)
        if amount is not None:
            return abs(amount)
    return None


def _delta_value(raw, address, keys):
    """Price a sample swap from the quote-side leg when one exists.

    Proof gates are unchanged. An unpriced swap-like row no longer poisons
    the whole sample denominator if any other row has a quote leg.
    """
    deltas = _owned_asset_deltas(raw, address, keys)
    usdc = abs(deltas.get(USDC, Decimal("0")))
    if usdc > 0:
        return usdc
    usdt = abs(deltas.get(USDT, Decimal("0")))
    if usdt > 0:
        return usdt
    wsol = abs(deltas.get(WSOL, Decimal("0")))
    if wsol > 0:
        return wsol
    sol = abs(deltas.get("SOL", Decimal("0")))
    return sol if sol > 0 else None


def classify_sample_tx(record, address, *, events_by_sig=None):
    """Classify one sample tx. Non-swap-like rows are omitted from the denom."""
    raw = unwrap_gta_record(record) if isinstance(record, dict) else None
    signature = _signature(record)
    if not isinstance(raw, dict) or not address:
        return {
            "signature": signature,
            "swap_like": True,
            "class": SAMPLE_CLASS_UNREADABLE,
            "value": None,
            "programs": [],
            "reason": "missing_raw",
        }
    try:
        keys = _account_keys(raw)
    except Exception:
        keys = []
    events = (events_by_sig or {}).get(signature) or []
    decoded_trade = any(
        isinstance(event, dict) and event.get("kind") in {"buy", "sell", "conversion"}
        for event in events
    )
    swap_like = bool(decoded_trade)
    if keys:
        try:
            swap_like = swap_like or bool(_is_swap_heuristic(raw, address, keys))
        except Exception:
            swap_like = True
    programs = []
    if keys:
        try:
            programs = list(_outer_non_infra(raw, keys))
        except Exception:
            programs = []
    value = None
    for event in events:
        value = _event_value(event)
        if value is not None:
            break
    if value is None and keys:
        value = _delta_value(raw, address, keys)
    if not swap_like:
        return {
            "signature": signature,
            "swap_like": False,
            "class": None,
            "value": value,
            "programs": programs,
        }
    if decoded_trade:
        return {
            "signature": signature,
            "swap_like": True,
            "class": SAMPLE_CLASS_REVIEWED,
            "value": value,
            "programs": programs,
        }
    try:
        net = net_balance_reviewed_swap(raw, address)
    except Exception:
        net = None
    if net:
        return {
            "signature": signature,
            "swap_like": True,
            "class": SAMPLE_CLASS_NET,
            "value": value if value is not None else _event_value(net),
            "programs": programs,
        }
    return {
        "signature": signature,
        "swap_like": True,
        "class": SAMPLE_CLASS_UNREADABLE,
        "value": value,
        "programs": programs,
        "reason": "unreadable_swap_like",
    }


def estimate_sample_round_trips(records, address, *, decoded=None):
    """Cheap sample estimate of buy-then-sell round trips.

    Transfer-in sells (token in, no quote out, then a sell) are not episodes.
    Used only to skip or rank deep pulls. Proof gates are unchanged.
    """
    grouped, decoded = _events_by_signature(records, address, decoded)
    buys, sells, transfer_ins = set(), set(), set()
    for record in records or []:
        raw = unwrap_gta_record(record) if isinstance(record, dict) else None
        if not isinstance(raw, dict) or not address:
            continue
        try:
            keys = _account_keys(raw)
            deltas = _owned_asset_deltas(raw, address, keys)
        except Exception:
            continue
        quote_down = any(deltas.get(mint, 0) < 0 for mint in QUOTE_MINTS)
        quote_up = any(deltas.get(mint, 0) > 0 for mint in QUOTE_MINTS)
        for mint, qty in deltas.items():
            if mint in QUOTE_MINTS or qty == 0:
                continue
            if qty > 0 and quote_down:
                buys.add(mint)
            elif qty > 0 and not quote_down:
                transfer_ins.add(mint)
            elif qty < 0 and quote_up:
                sells.add(mint)
    for events in grouped.values():
        for event in events:
            mint = event.get("mint")
            if not mint or mint in QUOTE_MINTS:
                continue
            if event.get("kind") == "buy":
                buys.add(mint)
            elif event.get("kind") == "sell":
                sells.add(mint)
    round_trips = len(buys & sells)
    transfer_in_sells = len((transfer_ins & sells) - buys)
    skip = round_trips == 0
    reason = None
    if skip and transfer_in_sells:
        reason = "sample_transfer_in_sells"
    elif skip:
        reason = "sample_no_round_trips"
    return {
        "expected_completed_episodes": round_trips,
        "transfer_in_sells": transfer_in_sells,
        "buy_mints": len(buys),
        "sell_mints": len(sells),
        "skip_deep_pull": skip,
        "skip_deep_pull_reason": reason,
    }


def _sample_programs(records):
    programs = set()
    logs = []
    for record in records or []:
        raw = unwrap_gta_record(record) if isinstance(record, dict) else None
        if not isinstance(raw, dict):
            continue
        try:
            keys = _account_keys(raw)
        except Exception:
            keys = []
        for key in keys or []:
            if key:
                programs.add(key)
        meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        for line in meta.get("logMessages") or []:
            if isinstance(line, str):
                logs.append(line)
    return programs, " ".join(logs)


def estimate_full_gate_prescore(records, address, *, decoded=None, signature_rows=None, nansen_row=None):
    """Cheap full-gate estimate from already-paid data. Never passes a wallet.

    Estimates every early_watch gate from the Nansen row, signatures pre-screen,
    and ~100-tx sample. Deep-pull only when the estimate could still pass
    early_watch (1+ completed round trips and no hard fail).
    """
    from scanner.mass_search.qualification_gates import raw_economic_trade_rate

    trips = estimate_sample_round_trips(records, address, decoded=decoded)
    shares = sample_readable_shares(records, address, decoded=decoded)
    rate = raw_economic_trade_rate(records, address)
    sig_max = None
    if signature_rows:
        screen = helius_signatures_prescreen(signature_rows)
        sig_max = screen.get("max_per_day") or screen.get("max_economic_trades_in_one_day")
    try:
        sig_max_i = int(sig_max) if sig_max not in (None, "") else 0
    except (TypeError, ValueError):
        sig_max_i = 0
    max_day = max(int(rate.get("max") or 0), sig_max_i)
    programs, logs = _sample_programs(records)
    infra = sorted(programs & INFRA_PRESCREEN_PROGRAMS)
    lp_hint = any(hint in logs for hint in LP_LOG_HINTS)
    readable_count = _dec(shares.get("count_share"))
    readable_value = _dec(shares.get("value_share"))
    sells = int(trips.get("sell_mints") or 0)
    transfer_in = int(trips.get("transfer_in_sells") or 0)
    known_sell_share = None
    if sells:
        known_sell_share = Decimal(sells - transfer_in) / Decimal(sells)
    rounds = int(trips.get("expected_completed_episodes") or 0)
    reasons = []
    if max_day > MAX_ECONOMIC_TRADES_PER_UTC_DAY:
        reasons.append(GT_ECONOMIC_TRADES_RULE)
    if rounds < EARLY_WATCH_MIN_EPISODES:
        reasons.append(trips.get("skip_deep_pull_reason") or "sample_no_round_trips")
    if readable_count is not None and readable_count < READABLE_SHARE_THRESHOLD:
        reasons.append("sample_readable_count_below_threshold")
    if readable_value is not None and readable_value < READABLE_SHARE_THRESHOLD:
        reasons.append("sample_readable_value_below_threshold")
    if known_sell_share is not None and known_sell_share < Decimal("0.5"):
        reasons.append("sample_transfer_in_sells")
    if infra or lp_hint:
        reasons.append("sample_lp_lending_or_mm_program")
    vendor_pnl = _pnl(nansen_row or {})
    if vendor_pnl is not None and vendor_pnl <= 0:
        reasons.append("nansen_realized_pnl_not_positive")
    # Probability is a ranking key only. 0 reasons → still not a pass.
    fail_weight = Decimal(len(reasons))
    pass_probability = (Decimal("1") / (Decimal("1") + fail_weight)).quantize(Decimal("0.0001"))
    skip = bool(reasons)
    return {
        "version": "full-gate-prescore-v1",
        "can_only_skip_or_defer": True,
        "never_passes": True,
        "max_economic_trades_in_one_day": max_day,
        "expected_completed_episodes": rounds,
        "readable_count_share": None if readable_count is None else str(readable_count),
        "readable_value_share": None if readable_value is None else str(readable_value),
        "known_basis_sell_share": None if known_sell_share is None else str(known_sell_share),
        "transfer_in_sells": transfer_in,
        "infra_programs": infra,
        "lp_or_mm_hint": lp_hint,
        "estimated_pass_probability": str(pass_probability),
        "skip_deep_pull": skip,
        "skip_deep_pull_reason": ";".join(reasons) if reasons else None,
        "reasons": reasons,
        "PRODUCT_READY": False,
    }


def _events_by_signature(records, address, decoded=None):
    if decoded is None:
        decoded = decode_supported_swaps(canonical_decode_records(records or []), address)
    grouped = {}
    for event in (decoded.get("events") or []) if isinstance(decoded, dict) else []:
        if not isinstance(event, dict):
            continue
        signature = event.get("signature")
        if signature:
            grouped.setdefault(signature, []).append(event)
    return grouped, decoded


def sample_readable_shares(records, address, *, decoded=None):
    """Count and value readable shares over swap-like txs in the sample."""
    grouped, decoded = _events_by_signature(records, address, decoded)
    rows = [classify_sample_tx(record, address, events_by_sig=grouped) for record in (records or [])]
    swap_like = [row for row in rows if row.get("swap_like")]
    readable = [row for row in swap_like if row.get("class") in {SAMPLE_CLASS_REVIEWED, SAMPLE_CLASS_NET}]
    unreadable = [row for row in swap_like if row.get("class") == SAMPLE_CLASS_UNREADABLE]
    count_n = len(swap_like)
    count_share = (Decimal(len(readable)) / Decimal(count_n)) if count_n else None
    priced = [row for row in swap_like if _dec(row.get("value")) is not None]
    if not priced:
        value_share = None
        value_denom = None
    else:
        value_denom = sum(_dec(row.get("value")) for row in priced)
        readable_value = sum(
            _dec(row.get("value")) or Decimal("0")
            for row in readable
            if _dec(row.get("value")) is not None
        )
        value_share = (readable_value / value_denom) if value_denom > 0 else None
    programs = Counter()
    for row in unreadable:
        for program in row.get("programs") or []:
            if program:
                programs[program] += 1
    return {
        "version": FUNNEL_VERSION,
        "swap_like_n": count_n,
        "readable_n": len(readable),
        "unreadable_n": len(unreadable),
        "count_share": None if count_share is None else str(count_share),
        "value_share": None if value_share is None else str(value_share),
        "value_denominator": None if value_denom is None else str(value_denom),
        "threshold": str(READABLE_SHARE_THRESHOLD),
        "unreadable_programs": programs.most_common(),
        "rows": rows,
        "decoded_events": len((decoded or {}).get("events") or []),
    }


def decide_sample(shares, *, threshold=None):
    """Keep only when both shares are known and ≥ threshold. Else defer."""
    floor = _dec(threshold) if threshold is not None else READABLE_SHARE_THRESHOLD
    count = _dec((shares or {}).get("count_share"))
    value = _dec((shares or {}).get("value_share"))
    if (shares or {}).get("swap_like_n") in (None, 0):
        return {
            "decision": DEFER_UNREADABLE,
            "reason": "empty_swap_like_sample",
            "can_only_drop_or_defer": True,
        }
    if count is None or value is None:
        return {
            "decision": DEFER_UNREADABLE,
            "reason": "missing_sample_value_denominator",
            "can_only_drop_or_defer": True,
        }
    if count >= floor and value >= floor:
        return {
            "decision": KEEP,
            "reason": None,
            "can_only_drop_or_defer": True,
        }
    return {
        "decision": DEFER_UNREADABLE,
        "reason": f"readable_share_below_{floor}",
        "can_only_drop_or_defer": True,
    }


def bot_prescreen_decision(signature_rows, *, dex_stats=None, max_per_day=None, history_cap=None):
    """Cheap signatures screen, then optional dex-trades. Drop or defer only."""
    screen = helius_signatures_prescreen(
        signature_rows, max_per_day=max_per_day, history_cap=history_cap,
    )
    if screen.get("deferred"):
        return {
            "decision": DEFER_UNREADABLE,
            "reason": "history_above_cap",
            "screen": screen,
            "can_only_drop_or_defer": True,
        }
    if screen.get("passed"):
        return {
            "decision": KEEP,
            "reason": None,
            "screen": screen,
            "needs_decode": False,
            "can_only_drop_or_defer": True,
        }
    if dex_stats:
        drop = nansen_dex_trades_drop(dex_stats, max_per_day=max_per_day)
        if drop.get("dropped"):
            return {
                "decision": DROP,
                "reason": GT_ECONOMIC_TRADES_RULE,
                "screen": screen,
                "dex": drop,
                "can_only_drop_or_defer": True,
            }
    return {
        "decision": KEEP,
        "reason": None,
        "screen": screen,
        "needs_decode": True,
        "can_only_drop_or_defer": True,
    }


def _pnl(row):
    for key in (
        "nansen_realized_pnl_usd",
        "realized_pnl_usd",
        "realized_pnl",
    ):
        amount = _dec(row.get(key) if isinstance(row, dict) else None)
        if amount is not None:
            return amount
    metrics = (row.get("vendor_metrics") if isinstance(row, dict) else None) or {}
    amount = _dec(metrics.get("realized_pnl_usd") or metrics.get("realizedPnlUsd"))
    return amount if amount is not None else Decimal("0")


def _expected_episodes(row):
    amount = _dec((row or {}).get("expected_completed_episodes"))
    return amount if amount is not None else Decimal("0")


def _pass_probability(row):
    amount = _dec((row or {}).get("estimated_pass_probability"))
    if amount is None:
        blob = (row or {}).get("prescore") or {}
        amount = _dec(blob.get("estimated_pass_probability"))
    if amount is not None:
        return amount
    episodes = _expected_episodes(row)
    if episodes > 0:
        return (episodes / (episodes + Decimal("1"))).quantize(Decimal("0.0001"))
    return Decimal("0")


def rank_by_nansen_pnl(rows):
    """Rank by estimated early_watch pass probability, then realized PnL."""
    return sorted(
        list(rows or []),
        key=lambda row: (
            -_pass_probability(row),
            -_pnl(row),
            str((row or {}).get("address") or ""),
        ),
    )


def walk_ranked(rows, *, n, cap=None):
    """Keep walking until N wallets pass the readable gate or the cap is hit."""
    try:
        target = max(0, int(n or 0))
    except (TypeError, ValueError):
        target = 0
    try:
        wallet_cap = int(cap) if cap not in (None, "") else None
    except (TypeError, ValueError):
        wallet_cap = None
    kept, deferred, dropped, unscreened = [], [], [], []
    examined = 0
    for row in rank_by_nansen_pnl(rows):
        if not isinstance(row, dict):
            continue
        if len(kept) >= target:
            unscreened.append({**row, "funnel_status": UNSCREENED, "funnel_reason": "n_reached"})
            continue
        if wallet_cap is not None and examined >= wallet_cap:
            unscreened.append({**row, "funnel_status": UNSCREENED, "funnel_reason": "cap_reached"})
            continue
        examined += 1
        # DC-8: Phase-2 drop wins over a 0.97 keep stamp.
        if row.get("dropped") is True:
            dropped.append({**row, "funnel_status": DROP})
            continue
        if row.get("skip_deep_pull"):
            dropped.append({
                **row,
                "funnel_status": DROP,
                "funnel_reason": row.get("skip_deep_pull_reason") or "sample_no_round_trips",
            })
            continue
        decision = row.get("funnel_decision") or row.get("decision") or DROP
        if decision == KEEP:
            kept.append({**row, "funnel_status": KEEP})
        elif decision == DEFER_UNREADABLE:
            deferred.append({**row, "funnel_status": DEFER_UNREADABLE})
        else:
            dropped.append({**row, "funnel_status": DROP})
    return {
        "version": FUNNEL_VERSION,
        "n": target,
        "cap": wallet_cap,
        "kept": kept,
        "deferred_unreadable": deferred,
        "dropped": dropped,
        "unscreened": unscreened,
        "examined": examined,
        "can_only_drop_or_defer": True,
        "gates_unchanged": list(GATES_UNCHANGED),
        "PRODUCT_READY": False,
    }


def readable_first_target_n(config):
    """Deep-pull N. Prefer --readable-first-n, else the per-run wallet cap."""
    raw = config or {}
    try:
        n = raw.get("readable_first_n")
        if n not in (None, ""):
            return max(0, int(n))
    except (TypeError, ValueError):
        pass
    cap = readable_first_walk_cap(raw)
    return cap or 0


def readable_first_walk_cap(config):
    """Examination budget. 0 / missing = unlimited (walk until N pass)."""
    raw = config or {}
    for key in ("readable_first_cap", "nansen_dex_trades_wallet_cap"):
        value = raw.get(key)
        if value in (None, "", 0, "0"):
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def select_deep_pull(rows, *, n, cap=None):
    walked = walk_ranked(
        [row for row in (rows or []) if isinstance(row, dict) and not row.get("dropped")],
        n=n,
        cap=cap,
    )
    return [row.get("address") for row in walked["kept"] if row.get("address")]


def attach_sample(row, records, address, *, decoded=None, threshold=None):
    """Stamp a phase-2 row with the readable-first sample decision."""
    shares = sample_readable_shares(records, address, decoded=decoded)
    decision = decide_sample(shares, threshold=threshold)
    payload = dict(row or {})
    payload["readable_first"] = {
        "version": FUNNEL_VERSION,
        "count_share": shares.get("count_share"),
        "value_share": shares.get("value_share"),
        "swap_like_n": shares.get("swap_like_n"),
        "unreadable_programs": shares.get("unreadable_programs"),
        "decision": decision["decision"],
        "reason": decision.get("reason"),
        "threshold": str(threshold or READABLE_SHARE_THRESHOLD),
    }
    trips = estimate_sample_round_trips(records, address, decoded=decoded)
    prescore = estimate_full_gate_prescore(
        records, address, decoded=decoded, nansen_row=payload,
    )
    payload["expected_completed_episodes"] = trips["expected_completed_episodes"]
    payload["prescore"] = {k: v for k, v in prescore.items() if k != "reasons"}
    payload["estimated_pass_probability"] = prescore["estimated_pass_probability"]
    payload["prescore_reason"] = prescore.get("skip_deep_pull_reason")
    skip = bool(
        (trips["skip_deep_pull"] or prescore["skip_deep_pull"])
        and decision["decision"] == KEEP
    )
    payload["skip_deep_pull"] = skip
    payload["skip_deep_pull_reason"] = (
        prescore.get("skip_deep_pull_reason") or trips.get("skip_deep_pull_reason")
    )
    payload["readable_first"]["expected_completed_episodes"] = trips["expected_completed_episodes"]
    payload["readable_first"]["transfer_in_sells"] = trips["transfer_in_sells"]
    payload["readable_first"]["prescore"] = payload["prescore"]
    payload["funnel_decision"] = decision["decision"]
    payload["funnel_reason"] = decision.get("reason")
    if skip:
        payload["dropped"] = True
        payload["drop_reason"] = payload["skip_deep_pull_reason"] or "prescore_cannot_pass_early_watch"
        payload["funnel_decision"] = DROP
        payload["funnel_reason"] = payload["drop_reason"]
    if decision["decision"] == DEFER_UNREADABLE:
        payload["dropped"] = False
        payload["deferred"] = True
        payload["drop_reason"] = payload.get("drop_reason") or decision.get("reason")
    return payload


def readable_first_plan(
    *,
    leaderboard_pages=1,
    timeframes=None,
    token_count=0,
    token_pnl_calls=0,
    discovered_wallets=0,
    dex_pages=3,
    sample_pages=SAMPLE_PAGES_DEFAULT,
    deep_n=10,
    history_cap=None,
    nansen_profile_cap=0,
    walk_cap=None,
):
    """Dry-run request and credit cost per stage. Plan ≥ runtime."""
    frames = tuple(timeframes) if timeframes else NANSEN_TIMEFRAMES_FUNNEL
    pages = nansen_leaderboard_page_count(leaderboard_pages)
    wallets = max(0, int(discovered_wallets or 0))
    try:
        sample_n = max(1, int(sample_pages or SAMPLE_PAGES_DEFAULT))
    except (TypeError, ValueError):
        sample_n = SAMPLE_PAGES_DEFAULT
    try:
        target = max(0, int(deep_n or 0))
    except (TypeError, ValueError):
        target = 0
    leaderboard_req = len(frames) * pages
    token_n = min(max(0, int(token_count or 0)), max(0, int(token_pnl_calls or 0)))
    profile_n = max(0, int(nansen_profile_cap or 0))
    cap = int(history_cap) if history_cap not in (None, "") else HELIUS_SIGNATURES_HISTORY_CAP
    sig_pages = (max(cap, 1) + HELIUS_SIGNATURES_PAGE_SIZE - 1) // HELIUS_SIGNATURES_PAGE_SIZE
    discovery = {
        "stage": "discovery",
        "nansen_requests": leaderboard_req + token_n,
        "nansen_units": (
            leaderboard_req * NANSEN_LEADERBOARD_UNITS
            + token_n * NANSEN_TGM_PNL_LEADERBOARD_UNITS
        ),
        "note": (
            f"{leaderboard_req} pnl-leaderboard calls "
            f"({len(frames)} windows × {pages} page(s)) plus {token_n} per-token."
        ),
    }
    rule_a = {
        "stage": "rule_a",
        "nansen_requests": profile_n,
        "nansen_units": profile_n * NANSEN_PROFILER_UNITS,
        "note": "Vendor-field drop only. Missing fields never pass.",
    }
    bot = {
        "stage": "bot_prescreen",
        "helius_requests": wallets * sig_pages,
        "helius_units": wallets * sig_pages * HELIUS_SIGNATURES_UNITS,
        "nansen_requests": wallets * max(0, int(dex_pages or 0)),
        "nansen_units": wallets * max(0, int(dex_pages or 0)) * NANSEN_DEX_TRADES_UNITS,
        "method": HELIUS_SIGNATURES_METHOD,
        "credit_note": HELIUS_SIGNATURES_CREDIT_NOTE,
        "threshold": MAX_ECONOMIC_TRADES_PER_UTC_DAY,
        "note": (
            f"getSignaturesForAddress 1 credit / {HELIUS_SIGNATURES_PAGE_SIZE} sigs. "
            f"Raw ≤{MAX_ECONOMIC_TRADES_PER_UTC_DAY}/UTC day cannot break the bot rule. "
            "Days over need dex-trades. Drop or defer only."
        ),
    }
    sample = {
        "stage": "decodability_sample",
        "helius_requests": wallets * sample_n,
        "helius_units": wallets * sample_n * SAMPLE_PAGE_UNITS,
        "threshold": str(READABLE_SHARE_THRESHOLD),
        "note": (
            f"{sample_n} enhanced page(s) (~{SAMPLE_TX_TARGET} txs). "
            f"Keep readable share ≥{READABLE_SHARE_THRESHOLD} count AND value."
        ),
    }
    deep = {
        "stage": "deep_pull",
        "wallets": target,
        "walk_cap": walk_cap,
        "helius_requests": 0,
        "helius_units": 0,
        "note": (
            f"Top {target} readable survivors only. "
            f"Walk cap {walk_cap if walk_cap is not None else 'off'}. "
            "Phase 4 isolation unchanged."
        ),
    }
    stages = [discovery, rule_a, bot, sample, deep]
    totals = {
        "nansen_requests": 0,
        "nansen_units": 0,
        "helius_requests": 0,
        "helius_units": 0,
    }
    for stage in stages:
        for key in totals:
            totals[key] += int(stage.get(key) or 0)
    return {
        "kind": "readable-first-plan-v1",
        "version": FUNNEL_VERSION,
        "timeframes": list(frames),
        "stages": stages,
        "totals": totals,
        "gates_unchanged": list(GATES_UNCHANGED),
        "can_only_drop_or_defer": True,
        "PRODUCT_READY": False,
    }


def format_dry_run_plan(plan):
    lines = [
        f"# Readable-first dry-run plan ({(plan or {}).get('version')})",
        "",
        "Gates unchanged. Drop or defer only. PRODUCT_READY false.",
        "",
    ]
    for stage in (plan or {}).get("stages") or []:
        lines.append(
            f"- {stage.get('stage')}: nansen {stage.get('nansen_requests') or 0} req / "
            f"{stage.get('nansen_units') or 0} cr; helius {stage.get('helius_requests') or 0} req / "
            f"{stage.get('helius_units') or 0} cr. {stage.get('note') or ''}"
        )
    totals = (plan or {}).get("totals") or {}
    lines.append("")
    lines.append(
        f"Totals: nansen {totals.get('nansen_requests') or 0} / {totals.get('nansen_units') or 0}; "
        f"helius {totals.get('helius_requests') or 0} / {totals.get('helius_units') or 0}."
    )
    return "\n".join(lines) + "\n"


def write_dry_run_plan(output_dir, plan):
    """Write READABLE_FIRST_PLAN.md/.json. Call before any live request."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    text = format_dry_run_plan(plan)
    (root / "READABLE_FIRST_PLAN.md").write_text(text, encoding="utf-8")
    (root / "READABLE_FIRST_PLAN.json").write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return text


def funnel_report(walked, *, extra=None):
    deferred = (walked or {}).get("deferred_unreadable") or []
    programs = Counter()
    for row in deferred:
        blob = row.get("readable_first") or {}
        for program, count in blob.get("unreadable_programs") or []:
            programs[program] += int(count or 0)
    payload = {
        "kind": "readable-first-funnel-v1",
        "version": FUNNEL_VERSION,
        "kept": [row.get("address") for row in (walked or {}).get("kept") or []],
        "deferred_unreadable": [
            {
                "address": row.get("address"),
                "reason": row.get("funnel_reason") or row.get("reason"),
                "unreadable_programs": (row.get("readable_first") or {}).get("unreadable_programs") or [],
            }
            for row in deferred
        ],
        "dropped": [
            {
                "address": row.get("address"),
                "reason": row.get("funnel_reason") or row.get("drop_reason") or row.get("reason"),
            }
            for row in (walked or {}).get("dropped") or []
        ],
        "unscreened": [
            {
                "address": row.get("address"),
                "reason": row.get("funnel_reason"),
            }
            for row in (walked or {}).get("unscreened") or []
        ],
        "dominant_unreadable_programs": programs.most_common(),
        "n": (walked or {}).get("n"),
        "examined": (walked or {}).get("examined"),
        "gates_unchanged": list(GATES_UNCHANGED),
        "can_only_drop_or_defer": True,
        "PRODUCT_READY": False,
    }
    early = []
    for row in list((walked or {}).get("kept") or []) + list((walked or {}).get("dropped") or []):
        if not isinstance(row, dict):
            continue
        level = row.get("qualification_level")
        name = level.get("level") if isinstance(level, dict) else level
        if name == "early_watch":
            early.append({
                "address": row.get("address"),
                "label": (level.get("label") if isinstance(level, dict) else None) or row.get("early_watch_label"),
                "prescore": row.get("prescore") or row.get("prescore_reason"),
                "never_proven": True,
                "PRODUCT_READY": False,
            })
    if extra and extra.get("early_watch"):
        seen = {item.get("address") for item in early if item.get("address")}
        for row in extra.get("early_watch") or []:
            address = row.get("address") if isinstance(row, dict) else row
            if address and address not in seen:
                early.append(row if isinstance(row, dict) else {"address": address})
                seen.add(address)
    payload["early_watch"] = early
    if extra:
        extra = dict(extra)
        extra.pop("early_watch", None)
        payload.update(extra)
    return payload


def format_funnel_markdown(report):
    lines = [
        f"# Readable-first funnel ({(report or {}).get('version')})",
        "",
        f"Kept: {len((report or {}).get('kept') or [])}",
        f"Early watch: {len((report or {}).get('early_watch') or [])}",
        f"Deferred unreadable: {len((report or {}).get('deferred_unreadable') or [])}",
        f"Dropped: {len((report or {}).get('dropped') or [])}",
        f"Unscreened: {len((report or {}).get('unscreened') or [])}",
        "",
        "## Early watch – not proven",
        "",
    ]
    for row in (report or {}).get("early_watch") or []:
        address = row.get("address") if isinstance(row, dict) else row
        label = row.get("label") if isinstance(row, dict) else None
        lines.append(f"- {address}: {label or 'Early watch – not proven'}")
    lines.extend([
        "",
        "## Drop / defer reasons",
        "",
    ])
    for group, label in (
        ("dropped", "dropped"),
        ("deferred_unreadable", "deferred_unreadable"),
        ("unscreened", "unscreened"),
    ):
        for row in (report or {}).get(group) or []:
            lines.append(f"- {row.get('address')}: {label} ({row.get('reason')})")
    programs = (report or {}).get("dominant_unreadable_programs") or []
    if programs:
        lines.append("")
        lines.append("## Dominant unreadable programs")
        lines.append("")
        for program, count in programs:
            lines.append(f"- {program}: {count}")
    lines.append("")
    lines.append("Gates unchanged. PRODUCT_READY false.")
    return "\n".join(lines) + "\n"


_FUNNEL_STATUS_KEYS = ("kept", "deferred_unreadable", "dropped", "unscreened")


def _funnel_status_entries(report):
    """Map address → (status, row). kept is a list of addresses."""
    entries = {}
    if not isinstance(report, dict):
        return entries
    for address in report.get("kept") or []:
        if address:
            entries[address] = ("kept", {"address": address, "status": "kept"})
    for key in ("deferred_unreadable", "dropped", "unscreened"):
        for row in report.get(key) or []:
            if not isinstance(row, dict):
                continue
            address = row.get("address")
            if address:
                entries[address] = (key, dict(row))
    return entries


def merge_funnel_reports(prior, incoming):
    """Accumulate funnel rows. One status per address; latest decision wins."""
    if not isinstance(prior, dict) or prior.get("kind") != "readable-first-funnel-v1":
        return incoming
    incoming = incoming or {}
    merged = dict(incoming)
    history = [dict(item) for item in (prior.get("history") or []) if isinstance(item, dict)]
    prior_entries = _funnel_status_entries(prior)
    incoming_entries = _funnel_status_entries(incoming)
    for address, (status, row) in prior_entries.items():
        history.append({
            "address": address,
            "status": status,
            "reason": row.get("reason") if isinstance(row, dict) else None,
        })
    final = dict(prior_entries)
    for address, (status, row) in incoming_entries.items():
        previous = prior_entries.get(address)
        history.append({
            "address": address,
            "status": status,
            "reason": row.get("reason") if isinstance(row, dict) else None,
            "supersedes": previous[0] if previous else None,
        })
        final[address] = (status, row)
    by_status = {key: [] for key in _FUNNEL_STATUS_KEYS}
    seen = set()
    # Prior order first, then newly seen incoming addresses. Latest status wins.
    for address, (status, row) in list(prior_entries.items()) + [
        item for item in incoming_entries.items() if item[0] not in prior_entries
    ]:
        if address in seen:
            continue
        seen.add(address)
        current_status, current_row = final[address]
        if current_status == "kept":
            by_status["kept"].append(address)
        else:
            by_status[current_status].append(current_row)
    for key in _FUNNEL_STATUS_KEYS:
        merged[key] = by_status[key]
    merged["history"] = history
    programs = Counter()
    for program, count in (prior.get("dominant_unreadable_programs") or []):
        programs[program] += int(count or 0)
    for program, count in incoming.get("dominant_unreadable_programs") or []:
        programs[program] += int(count or 0)
    merged["dominant_unreadable_programs"] = programs.most_common()
    merged["examined"] = int(prior.get("examined") or 0) + int(incoming.get("examined") or 0)
    merged["accumulated"] = True
    by_address = {}
    for row in list(prior.get("early_watch") or []) + list(incoming.get("early_watch") or []):
        if isinstance(row, dict) and row.get("address"):
            by_address[row["address"]] = row
        elif isinstance(row, str):
            by_address.setdefault(row, {"address": row})
    merged["early_watch"] = list(by_address.values())
    return merged


def merge_funnel_walks(prior, incoming):
    """Accumulate walk_ranked payloads so a resumed batch cannot erase kept wallets."""
    if not isinstance(prior, dict):
        return incoming
    incoming = incoming or {}
    merged_report = merge_funnel_reports(
        funnel_report(prior),
        funnel_report(incoming),
    )
    by_address = {}
    for row in list(prior.get("kept") or []) + list(prior.get("dropped") or []) + list(prior.get("deferred_unreadable") or []) + list(prior.get("unscreened") or []):
        if isinstance(row, dict) and row.get("address"):
            by_address[row["address"]] = row
    for row in list(incoming.get("kept") or []) + list(incoming.get("dropped") or []) + list(incoming.get("deferred_unreadable") or []) + list(incoming.get("unscreened") or []):
        if isinstance(row, dict) and row.get("address"):
            by_address[row["address"]] = row
    kept, deferred, dropped, unscreened = [], [], [], []
    for address in merged_report.get("kept") or []:
        kept.append(by_address.get(address) or {"address": address, "funnel_status": KEEP})
    for row in merged_report.get("deferred_unreadable") or []:
        address = row.get("address") if isinstance(row, dict) else None
        deferred.append(by_address.get(address) or row)
    for row in merged_report.get("dropped") or []:
        address = row.get("address") if isinstance(row, dict) else None
        dropped.append(by_address.get(address) or row)
    for row in merged_report.get("unscreened") or []:
        address = row.get("address") if isinstance(row, dict) else None
        unscreened.append(by_address.get(address) or row)
    return {
        "version": incoming.get("version") or prior.get("version") or FUNNEL_VERSION,
        "n": incoming.get("n") or prior.get("n"),
        "cap": incoming.get("cap") if incoming.get("cap") is not None else prior.get("cap"),
        "kept": kept,
        "deferred_unreadable": deferred,
        "dropped": dropped,
        "unscreened": unscreened,
        "examined": int(prior.get("examined") or 0) + int(incoming.get("examined") or 0),
        "can_only_drop_or_defer": True,
        "gates_unchanged": list(GATES_UNCHANGED),
        "accumulated": True,
        "PRODUCT_READY": False,
    }


def write_funnel_report(output_dir, walked, *, extra=None):
    report = funnel_report(walked, extra=extra)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "READABLE_FIRST_FUNNEL.json"
    if path.exists():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            prior = None
        report = merge_funnel_reports(prior, report)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "READABLE_FIRST_FUNNEL.md").write_text(format_funnel_markdown(report), encoding="utf-8")
    return report
