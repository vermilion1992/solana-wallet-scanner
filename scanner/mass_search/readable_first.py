"""Readable-first funnel. Drop or defer only. Gates stay fail-closed.

Stages: discovery → Rule A → cheap bot pre-screen → decodability sample →
deep pull of the top N survivors. A seed is never evidence.
"""
from __future__ import annotations

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
    deltas = _owned_asset_deltas(raw, address, keys)
    usdc = abs(deltas.get(USDC, Decimal("0")))
    if usdc > 0:
        return usdc
    usdt = abs(deltas.get(USDT, Decimal("0")))
    if usdt > 0:
        return usdt
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
    values = [_dec(row.get("value")) for row in swap_like]
    if any(item is None for item in values) or not values:
        value_share = None
        value_denom = None
    else:
        value_denom = sum(values)
        readable_value = sum(_dec(row.get("value")) or Decimal("0") for row in readable)
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


def rank_by_nansen_pnl(rows):
    return sorted(
        list(rows or []),
        key=lambda row: (-_pnl(row), str((row or {}).get("address") or "")),
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


def select_deep_pull(rows, *, n):
    walked = walk_ranked(
        [row for row in (rows or []) if isinstance(row, dict) and not row.get("dropped")],
        n=n,
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
    payload["funnel_decision"] = decision["decision"]
    payload["funnel_reason"] = decision.get("reason")
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
        "helius_requests": 0,
        "helius_units": 0,
        "note": f"Top {target} readable survivors only. Phase 4 isolation unchanged.",
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
    if extra:
        payload.update(extra)
    return payload


def format_funnel_markdown(report):
    lines = [
        f"# Readable-first funnel ({(report or {}).get('version')})",
        "",
        f"Kept: {len((report or {}).get('kept') or [])}",
        f"Deferred unreadable: {len((report or {}).get('deferred_unreadable') or [])}",
        f"Dropped: {len((report or {}).get('dropped') or [])}",
        f"Unscreened: {len((report or {}).get('unscreened') or [])}",
        "",
        "## Drop / defer reasons",
        "",
    ]
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


def write_funnel_report(output_dir, walked, *, extra=None):
    report = funnel_report(walked, extra=extra)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "READABLE_FIRST_FUNNEL.json").write_text(
        __import__("json").dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "READABLE_FIRST_FUNNEL.md").write_text(format_funnel_markdown(report), encoding="utf-8")
    return report
