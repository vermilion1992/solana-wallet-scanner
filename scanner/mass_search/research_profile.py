"""Local research-profile metrics and versioned thresholds. Not a safe-to-copy claim."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from scanner.mass_search.qualification_gates import (
    ACCOUNTING_POLICY_VERSION,
    CROSS_CURRENCY_SENSITIVITY,
    SENSITIVITY_NOT_ESTABLISHED,
    aggregate_rounding_bridge,
    amounts_agree,
    audit_fingerprint_matches,
    bindable_independent_audit,
    certificate_comparison_proof,
    completed_episode_ledger,
    component_bridge,
    compute_audit_fingerprint,
    concentration_from_episodes,
    coverage_shares,
    episode_net_from_ledger,
    exposure_outside_completed_episodes,
    format_auditor_confirmation,
    hold_time_stats,
    is_synthetic_case,
    mandatory_coverage_gate,
    mark_synthetic,
    qualifying_profit,
    requested_history_interval,
    sensitivity_result,
    stronger_shortlist_activity_ok,
    trading_activity,
    worksheet_episode_bridge,
    GT_ECONOMIC_TRADES_RULE,
    GT25_ECONOMIC_TRADES_RULE,
    attach_economic_trade_rate,
    first_defined_int,
    trade_rate_from,
    with_gt25_blocker,
)
import scanner.mass_search.qualification_gates as _qual_gates
from scanner.mass_search.settlement import (
    USDC,
    USDT,
    _open_lot_count,
    isolate_known_cost_by_mint,
    quote_consideration,
    settlement_of,
)

PROFILE_KIND = "research-profile-v1"
FILTERS_KIND = "research_profile_filters"
FILTERS_KEY = "local-research-profile-filters-v1"
FILTERS_VERSION = 1

THRESHOLD_KEYS = (
    "min_completed_known_cost",
    "min_scoped_pnl_usdc",
    "min_scoped_pnl_sol",
    "max_hold_t90_seconds",
    "max_concentration",
    "max_unresolved_share",
    "min_market_vs_rewards_ratio",
    "max_holder_fee_share",
    "min_sample_positions",
    "min_coverage_share",
)

# User-editable research-screen filters. Proof gates stay in qualification_gates
# and cannot be weakened through this API.
THRESHOLD_RANGES = {
    "min_completed_known_cost": ("int", 0, 10_000),
    "min_sample_positions": ("int", 0, 10_000),
    "min_coverage_share": ("share", "0", "1"),
    "min_scoped_pnl_usdc": ("amount", "-1000000000000", "1000000000000"),
    "min_scoped_pnl_sol": ("amount", "-1000000000000", "1000000000000"),
    "max_hold_t90_seconds": ("int", 0, 1_000_000_000),
    "max_concentration": ("share", "0", "1"),
    "max_unresolved_share": ("share", "0", "1"),
    "min_market_vs_rewards_ratio": ("amount", "0", "1000000"),
    "max_holder_fee_share": ("share", "0", "1"),
}
WINDOW_DAYS_RANGE = (1, 365)
CANONICAL_AMOUNT = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")
PROVIDER_TRADE_COUNT_RANGE = (0, 1_000_000_000)
PROVIDER_SCORE_RANGE = (Decimal("0"), Decimal("1000000000000"))
PROOF_GATES = {
    "kind": "proof_gate_not_user_filter",
    "coverage_lead_share": "0.99",
    "coverage_watch_share": "0.95",
    "weakenable_via_filter_api": False,
    "note": (
        "Qualification floors for lead/watch. min_coverage_share is a research "
        "screen filter (count AND value). It does not lower these proof gates."
    ),
}


class FilterValidationError(ValueError):
    """Rejected at save time. Routes map this to HTTP 422."""

    status_code = 422

DEFAULT_THRESHOLDS = {key: None for key in THRESHOLD_KEYS}
PROVIDER_PROXY_KEYS = (
    "min_provider_trade_count",
    "min_provider_score",
    "only_shortlist",
    "only_user_shortlist",
    "only_captured",
    "only_early_watch",
)
THRESHOLD_UNITS = {
    "min_completed_known_cost": "positions",
    "min_scoped_pnl_usdc": "USDC",
    "min_scoped_pnl_sol": "SOL",
    "max_hold_t90_seconds": "seconds",
    "max_concentration": "share",
    "max_unresolved_share": "share",
    "min_market_vs_rewards_ratio": "ratio",
    "max_holder_fee_share": "share",
    "min_sample_positions": "positions",
    "min_coverage_share": "share",
    "min_provider_trade_count": "provider_trades",
    "min_provider_score": "provider_score",
}

# Documented research-screen defaults, fixed before evaluation.
# min_sample_positions=3 so a single matched trade never qualifies the account.
RESEARCH_SCREEN_DEFAULTS = {
    "min_completed_known_cost": "1",
    "min_sample_positions": "3",
    "min_coverage_share": None,
}
POSITIVE_RESEARCH_SHORTLIST = {
    "name": "Positive research shortlist",
    "min_completed_known_cost": "3",
    "min_sample_positions": "3",
    "min_coverage_share": "0.99",
    "min_scoped_pnl_sol": "0",
    "min_scoped_pnl_usdc": "0",
    "note": "Requires positive scoped net P&L plus the evidence gates. Unset fields stay not applied.",
}

EVIDENCE_CLASS = {
    1: "profitable_matched_position",
    2: "positive_known_basis_incomplete_history",
    3: "positive_net_realised_supported_window",
    4: "account_performance_claim",
    5: "missing_or_inconclusive",
}

# Evidence-quality categories mapped onto the existing classes.
# These are not research-screen pass/fail.
QUALIFICATION_CATEGORY = {
    "not_evaluated": "not_evaluated",
    "analysed_incomplete": "analysed_incomplete",
    "positive_matched_position_evidence": "positive_matched_position_evidence",
    "positive_net_realised_over_window": "positive_net_realised_over_window",
    "profitable_account_performance": "profitable_account_performance",
}


def _default_provider_proxy():
    return {
        "min_provider_trade_count": None,
        "min_provider_score": None,
        "only_shortlist": False,
        "only_user_shortlist": False,
        "only_captured": False,
        "only_early_watch": False,
    }


def default_filters():
    return {
        "kind": "research-profile-filters-v1",
        "version": FILTERS_VERSION,
        "thresholds": dict(DEFAULT_THRESHOLDS),
        "provider_proxy": _default_provider_proxy(),
        "reconstructed": {"thresholds": dict(DEFAULT_THRESHOLDS)},
        "units": dict(THRESHOLD_UNITS),
        "window_days": None,
        "proof_gates": dict(PROOF_GATES),
        "unset_does_not_pass": False,
        "unset_is_not_applied": True,
        "unknown_never_passes": True,
        "not_safe_to_copy": True,
        "PRODUCT_READY": False,
    }


def _finite_decimal(value):
    if value is None or value == "" or value is False:
        return None
    if isinstance(value, bool):
        return None
    try:
        text = str(value).strip()
        if not text or text.lower() in ("nan", "inf", "+inf", "-inf", "infinity", "-infinity"):
            return None
        amount = Decimal(text)
    except (InvalidOperation, ValueError, OverflowError, TypeError):
        return None
    if not amount.is_finite():
        return None
    return amount


def _canonical_number_text(value):
    if value is None or value == "" or value is False:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return format(value, "f")
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        text = format(Decimal(str(value)), "f")
        if CANONICAL_AMOUNT.fullmatch(text):
            return text
        return None
    if isinstance(value, str):
        if not CANONICAL_AMOUNT.fullmatch(value):
            return None
        return value
    return None


def _require_canonical_number(value, *, name):
    text = _canonical_number_text(value)
    if text is None:
        raise FilterValidationError(f"{name} must be a finite ASCII decimal")
    parsed = _finite_decimal(text)
    if parsed is None:
        raise FilterValidationError(f"{name} must be a finite number")
    return parsed


def validate_threshold_value(key, value):
    if value is None or value == "" or value is False:
        return None
    spec = THRESHOLD_RANGES.get(key)
    if spec is None:
        raise FilterValidationError(f"Unknown filter {key}")
    kind, lo, hi = spec
    parsed = _require_canonical_number(value, name=key)
    if kind == "int":
        if parsed != parsed.to_integral_value():
            raise FilterValidationError(f"{key} must be an integer")
        number = int(parsed)
        if number < lo or number > hi:
            raise FilterValidationError(f"{key} must be between {lo} and {hi}")
        return str(number)
    low = Decimal(str(lo))
    high = Decimal(str(hi))
    if parsed < low or parsed > high:
        raise FilterValidationError(f"{key} must be between {lo} and {hi}")
    return format(parsed, "f")


def validate_window_days(value):
    if value is None or value == "" or value is False:
        return None
    parsed = _require_canonical_number(value, name="window_days")
    if parsed != parsed.to_integral_value():
        raise FilterValidationError("window_days must be an integer")
    number = int(parsed)
    lo, hi = WINDOW_DAYS_RANGE
    if number < lo or number > hi:
        raise FilterValidationError(f"window_days must be between {lo} and {hi}")
    return number


def _stamp_unix(value):
    if value is None or value == "":
        return None
    if type(value) is int:
        if value > 10**12:
            return value // 1000
        return value
    if type(value) is float:
        if value != value:
            return None
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return int(text)
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return None


def _report_end_unix(report):
    """Anchor window_days to the report end, never last activity / in_window_span."""
    window = (report or {}).get("window") or {}
    for key in ("end", "end_exclusive", "report_end"):
        stamp = _stamp_unix(window.get(key))
        if stamp is not None:
            return stamp
    applied = (report or {}).get("research_window") or {}
    if applied.get("end_unix") is not None:
        try:
            return int(applied["end_unix"])
        except (TypeError, ValueError):
            pass
    created = _stamp_unix((report or {}).get("created_at"))
    if created is not None:
        return created
    return int(datetime.now(timezone.utc).timestamp())


def _capture_window_unix(report):
    window = (report or {}).get("window") or {}
    start = _stamp_unix(window.get("start") or window.get("start_inclusive"))
    end = _stamp_unix(window.get("end") or window.get("end_exclusive") or window.get("report_end"))
    applied = (report or {}).get("research_window") or {}
    if applied.get("applied"):
        if applied.get("start_unix") is not None:
            try:
                start = int(applied["start_unix"])
            except (TypeError, ValueError):
                pass
        if applied.get("end_unix") is not None:
            try:
                end = int(applied["end_unix"])
            except (TypeError, ValueError):
                pass
    return start, end


def _known_cost_episodes(episodes):
    """Known-cost completed episodes only. A missing net is not realized P&L."""
    out = []
    for episode in episodes or []:
        net = episode.get("net") if episode.get("net") not in (None, "") else episode.get("pnl")
        if net not in (None, ""):
            out.append(episode)
    return out


def _restrict_ledger_to_report_window(report, episodes):
    """Qualification and P&L use only episodes closed inside the report window."""
    start, end = _capture_window_unix(report)
    if start is None and end is None:
        return _known_cost_episodes(episodes)
    out = []
    for episode in episodes or []:
        net = episode.get("net") if episode.get("net") not in (None, "") else episode.get("pnl")
        if net in (None, ""):
            continue
        stamp = _stamp_unix(
            episode.get("closed_at") or episode.get("timestamp") or episode.get("day")
        )
        if stamp is None:
            out.append(episode)
            continue
        if start is not None and stamp < start:
            continue
        if end is not None and stamp >= end:
            continue
        out.append(episode)
    return out


def apply_research_window(report, window_days):
    """Clip events and completed episodes to the last window_days, then rebuild counts.

    window_days is a research-screen bound. Unset leaves the captured profile unchanged.
    Events or episodes without a usable timestamp are dropped while a window is applied
    so unknown time never silently stays in-window.
    """
    if report is None:
        return report
    if window_days in (None, ""):
        return report
    days = int(window_days)
    end_unix = _report_end_unix(report)
    start_unix = end_unix - (days * 86400)
    events = []
    for event in report.get("events") or []:
        stamp = _stamp_unix(event.get("timestamp") or event.get("block_time") or event.get("day"))
        if stamp is not None and start_unix <= stamp < end_unix:
            events.append(event)
    source_ledger = report.get("completed_episode_ledger")
    if source_ledger is None:
        source_ledger = ((report.get("research_profile") or {}).get("completed_episode_ledger")) or []
    ledger = []
    nets = {}
    for episode in source_ledger:
        stamp = _stamp_unix(
            episode.get("closed_at") or episode.get("timestamp") or episode.get("day")
        )
        if stamp is None or not (start_unix <= stamp < end_unix):
            continue
        ledger.append(episode)
        unit = episode.get("unit") or episode.get("settlement_asset")
        if unit and episode.get("net") not in (None, ""):
            nets[unit] = nets.get(unit, Decimal("0")) + Decimal(str(episode["net"]))
    worksheet = dict(report.get("worksheet") or {})
    prior_by_quote = dict(worksheet.get("by_quote_asset") or {})
    by_quote = {}
    for unit, amount in nets.items():
        key = f"total_profit_{unit.lower()}"
        worksheet[key] = str(amount)
        prior = dict(prior_by_quote.get(unit) or {})
        prior[key] = str(amount)
        by_quote[unit] = prior
    for key in list(worksheet):
        if key.startswith("total_profit_"):
            unit = key[len("total_profit_"):].upper()
            if unit not in nets:
                worksheet.pop(key, None)
    worksheet["by_quote_asset"] = by_quote
    if len(nets) == 1:
        worksheet["settlement_asset"] = next(iter(nets))
    elif not nets:
        worksheet["settlement_asset"] = None
    clipped = dict(report)
    clipped["events"] = events
    clipped["completed_episode_ledger"] = ledger
    clipped["wallet_completed_episodes"] = len(ledger)
    clipped["wallet_sale_count"] = sum(1 for event in events if event.get("kind") == "sell")
    clipped["worksheet"] = worksheet
    if len(nets) == 1:
        clipped["completed_episode_net"] = str(next(iter(nets.values())))
        clipped["completed_episode_net_unit"] = next(iter(nets))
    elif not nets:
        clipped["completed_episode_net"] = None
        clipped["completed_episode_net_unit"] = None
    clipped["research_window"] = {
        "window_days": days,
        "start_unix": start_unix,
        "end_unix": end_unix,
        "applied": True,
    }
    return clipped


def validate_provider_proxy_value(key, value):
    if value is None or value == "" or value is False:
        return None
    parsed = _require_canonical_number(value, name=key)
    if key == "min_provider_trade_count":
        if parsed != parsed.to_integral_value():
            raise FilterValidationError(f"{key} must be an integer")
        number = int(parsed)
        lo, hi = PROVIDER_TRADE_COUNT_RANGE
        if number < lo or number > hi:
            raise FilterValidationError(f"{key} must be between {lo} and {hi}")
        return str(number)
    lo, hi = PROVIDER_SCORE_RANGE
    if parsed < lo or parsed > hi:
        raise FilterValidationError(f"{key} must be between {lo} and {hi}")
    return format(parsed, "f")


def _clean_proxy(incoming, *, strict=False):
    proxy = _default_provider_proxy()
    source = incoming if isinstance(incoming, dict) else {}
    for key in ("min_provider_trade_count", "min_provider_score"):
        value = source.get(key)
        if value is None or value == "" or value is False:
            proxy[key] = None
            continue
        if strict:
            proxy[key] = validate_provider_proxy_value(key, value)
        else:
            try:
                proxy[key] = validate_provider_proxy_value(key, value)
            except FilterValidationError:
                proxy[key] = None
    for key in ("only_shortlist", "only_user_shortlist", "only_captured", "only_early_watch"):
        proxy[key] = _clean_bool(source.get(key), name=key, strict=strict)
    return proxy


def _clean_bool(value, *, name, strict):
    if value is None:
        return False
    if value is True:
        return True
    if value is False:
        return False
    if strict:
        raise FilterValidationError(f"{name} must be true, false, or null")
    return False


_PASSTHROUGH_FILTER_KEYS = {
    "kind",
    "version",
    "thresholds",
    "provider_proxy",
    "reconstructed",
    "units",
    "window_days",
    "proof_gates",
    "unset_does_not_pass",
    "unset_is_not_applied",
    "unknown_never_passes",
    "not_safe_to_copy",
    "PRODUCT_READY",
    "saved",
    "only_shortlist",
    "only_captured",
    "only_user_shortlist",
    "only_early_watch",
    "min_provider_trade_count",
    "min_provider_score",
}


def _sanitize_thresholds(incoming):
    cleaned = dict(DEFAULT_THRESHOLDS)
    source = incoming if isinstance(incoming, dict) else {}
    unknown = [
        key for key in source
        if key not in THRESHOLD_KEYS
        and key not in _PASSTHROUGH_FILTER_KEYS
        and source.get(key) not in (None, "")
    ]
    if unknown:
        raise FilterValidationError("Unknown filter keys: " + ", ".join(sorted(unknown)))
    for key in THRESHOLD_KEYS:
        cleaned[key] = validate_threshold_value(key, source.get(key))
    return cleaned


def _load_thresholds(incoming, reconstructed_thresholds):
    cleaned = dict(DEFAULT_THRESHOLDS)
    source = incoming if isinstance(incoming, dict) else {}
    fallback = reconstructed_thresholds if isinstance(reconstructed_thresholds, dict) else {}
    for key in THRESHOLD_KEYS:
        raw = source.get(key) if source.get(key) not in (None, "") else fallback.get(key)
        if raw in (None, ""):
            cleaned[key] = None
            continue
        try:
            cleaned[key] = validate_threshold_value(key, raw)
        except FilterValidationError:
            cleaned[key] = None
    return cleaned


def load_filters(store=None):
    if store is None:
        return default_filters()
    saved = store.get(FILTERS_KIND, FILTERS_KEY)
    if not isinstance(saved, dict):
        return default_filters()
    incoming = saved.get("thresholds") if isinstance(saved.get("thresholds"), dict) else {}
    reconstructed = saved.get("reconstructed") if isinstance(saved.get("reconstructed"), dict) else {}
    reconstructed_thresholds = reconstructed.get("thresholds") if isinstance(reconstructed.get("thresholds"), dict) else {}
    thresholds = _load_thresholds(incoming, reconstructed_thresholds)
    payload = default_filters()
    payload["thresholds"] = thresholds
    payload["reconstructed"] = {"thresholds": dict(thresholds)}
    payload["provider_proxy"] = _clean_proxy(saved.get("provider_proxy") or saved, strict=False)
    try:
        payload["window_days"] = validate_window_days(saved.get("window_days"))
    except FilterValidationError:
        payload["window_days"] = None
    try:
        payload["version"] = int(saved.get("version") or FILTERS_VERSION)
    except (TypeError, ValueError):
        payload["version"] = FILTERS_VERSION
    payload["saved"] = True
    payload["only_shortlist"] = payload["provider_proxy"]["only_shortlist"]
    payload["only_captured"] = payload["provider_proxy"]["only_captured"]
    payload["only_early_watch"] = payload["provider_proxy"]["only_early_watch"]
    return payload


def save_filters(store, thresholds):
    incoming = thresholds if isinstance(thresholds, dict) else {}
    threshold_source = incoming.get("thresholds") if isinstance(incoming.get("thresholds"), dict) else incoming
    cleaned = _sanitize_thresholds(threshold_source)
    payload = default_filters()
    payload["thresholds"] = cleaned
    payload["reconstructed"] = {"thresholds": dict(cleaned)}
    payload["provider_proxy"] = _clean_proxy(incoming.get("provider_proxy") or incoming, strict=True)
    payload["window_days"] = validate_window_days(incoming.get("window_days"))
    payload["only_shortlist"] = payload["provider_proxy"]["only_shortlist"]
    payload["only_captured"] = payload["provider_proxy"]["only_captured"]
    payload["only_early_watch"] = payload["provider_proxy"]["only_early_watch"]
    store.put(FILTERS_KIND, FILTERS_KEY, payload)
    return payload


def _decimal(value):
    return _finite_decimal(value)


DISPLAY_QUANTUM = Decimal("0.000000001")


def _share(part, whole):
    if not whole:
        return None
    return _display_decimal(Decimal(part) / Decimal(whole))


def _display_decimal(value):
    if value in (None, ""):
        return None
    quantized = Decimal(str(value)).quantize(DISPLAY_QUANTUM)
    text = format(quantized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _episode_day(event):
    stamp = event.get("timestamp") or event.get("block_time") or event.get("day")
    if stamp in (None, ""):
        return None
    activity = trading_activity([{**event, "kind": event.get("kind") or "sell"}])
    days = activity.get("active_trading_day_list") or []
    return days[0] if days else None


def _episode_ledger_from_report(report):
    if report and "completed_episode_ledger" in report:
        return _restrict_ledger_to_report_window(report, report.get("completed_episode_ledger") or [])
    explicit = completed_episode_ledger(report)
    if explicit:
        return _restrict_ledger_to_report_window(report, explicit)
    events = [row for row in (report.get("events") or []) if row.get("kind") in ("buy", "sell")]
    worksheet = report.get("worksheet") or {}
    sales = []
    seen = set()
    sources = [worksheet]
    sources.extend((worksheet.get("by_quote_asset") or {}).values())
    for part in sources:
        if not part:
            continue
        for row in part.get("sale_rows") or []:
            key = (row.get("signature"), row.get("split_part") or "matched", row.get("mint"))
            if key in seen:
                continue
            seen.add(key)
            sales.append(row)
    clean = [
        row for row in sales
        if not row.get("unresolved_basis") and not row.get("not_clean_episode") and row.get("split_part") != "unresolved"
    ]
    sales_by_sig = {}
    for row in clean:
        sales_by_sig.setdefault(row.get("signature"), []).append(row)
    episodes = []
    by_mint = {}
    for event in events:
        mint = event.get("mint")
        if mint:
            by_mint.setdefault(mint, []).append(event)
    for mint, rows in by_mint.items():
        rows = sorted(rows, key=lambda row: (
            row.get("order") if isinstance(row.get("order"), int) and not isinstance(row.get("order"), bool) else 10**12,
            row.get("seconds_from_start") or 0,
            row.get("slot") if isinstance(row.get("slot"), int) else 0,
            row.get("signature") or "",
        ))
        inventory = Decimal("0")
        opened = False
        opened_at = None
        episode_sigs = []
        episode_events = []
        buy_consideration = Decimal("0")
        for event in rows:
            raw_units = event.get("units")
            if raw_units in (None, ""):
                raw_units = event.get("quantity_raw")
            if raw_units in (None, ""):
                raw_units = event.get("quantity") or 0
            units = Decimal(str(raw_units))
            if event.get("kind") == "buy":
                inventory += units
                if not opened:
                    opened_at = event.get("timestamp") or event.get("block_time")
                opened = True
                episode_events.append(event)
                from scanner.mass_search.settlement import quote_consideration
                priced = quote_consideration(event)
                if priced is not None:
                    buy_consideration += priced
                continue
            if event.get("kind") != "sell" or not opened or inventory <= 0:
                continue
            inventory -= units
            episode_sigs.append(event.get("signature"))
            episode_events.append(event)
            if inventory < 0:
                opened = False
                opened_at = None
                episode_sigs = []
                episode_events = []
                inventory = Decimal("0")
                buy_consideration = Decimal("0")
                continue
            if inventory != 0:
                continue
            mint_sales = []
            for signature in episode_sigs:
                mint_sales.extend(sales_by_sig.get(signature) or [])
            net = basis = proceeds = costs = None
            if mint_sales:
                net = sum(Decimal(str(row.get("net_profit") or 0)) for row in mint_sales)
                basis = sum(Decimal(str(row.get("basis") or 0)) for row in mint_sales)
                proceeds = sum(
                    Decimal(str(row["proceeds"])) if row.get("proceeds") not in (None, "")
                    else Decimal(str(row.get("basis") or 0)) + Decimal(str(row.get("gross_profit") or 0))
                    for row in mint_sales
                )
                costs = sum(Decimal(str(row.get("fees_and_tips") or 0)) for row in mint_sales)
                # Acquisition is the swap-quote consideration when FIFO
                # allocation leaves a few-lamport residue (An9s was +4).
                if buy_consideration and abs(basis - buy_consideration) <= Decimal("0.000000010"):
                    basis = buy_consideration
                    if proceeds is not None and costs is not None:
                        net = proceeds - basis - costs
                # Per-sale-row quantization of fees_and_tips drifted ±5 atomics
                # on jXt (Fn9yPE7p / H1B8nhXL). Snap costs to the episode's
                # wallet-paid fee sum, same 10-lamport rule as basis.
                event_fees = Decimal("0")
                for ev in episode_events:
                    for key in ("fees_and_tips_sol", "wallet_fee_sol", "fee_sol"):
                        if ev.get(key) not in (None, ""):
                            event_fees += Decimal(str(ev[key]))
                            break
                if costs is not None and event_fees and abs(costs - event_fees) <= Decimal("0.000000010"):
                    costs = event_fees
                    if proceeds is not None and basis is not None:
                        net = proceeds - basis - costs
            elif event.get("known_cost_pnl") not in (None, ""):
                net = Decimal(str(event["known_cost_pnl"]))
            if net is None:
                # Completed flatten with known same-asset quotes but no
                # worksheet sale_row (isolate dropped the legs). Recover
                # the episode from the events; do not invent a quote.
                from scanner.mass_search.settlement import quote_consideration, settlement_of, WSOL
                acq = Decimal("0")
                proc = Decimal("0")
                fee_sum = Decimal("0")
                assets = []
                missing = False
                dirty = False
                for ev in episode_events:
                    if (
                        ev.get("unresolved_basis")
                        or ev.get("not_clean_episode")
                        or ev.get("opening_inventory_consumed")
                        or ev.get("partial_known_cost")
                        or ev.get("quarantined")
                        or ev.get("transfer_in_zero_basis")
                        or ev.get("undecoded_buy")
                        or ev.get("kind") == "undecoded_buy"
                        or ev.get("whole_sale_pnl_resolved") is False
                    ):
                        dirty = True
                        break
                    priced = quote_consideration(ev)
                    asset = settlement_of(ev)
                    if ev.get("kind") == "buy":
                        if priced is None or asset is None:
                            missing = True
                            break
                        acq += priced
                        assets.append(asset)
                    elif ev.get("kind") == "sell":
                        if priced is None or asset is None:
                            missing = True
                            break
                        proc += priced
                        assets.append(asset)
                    for key in ("fees_and_tips_sol", "wallet_fee_sol", "fee_sol"):
                        if ev.get(key) not in (None, ""):
                            fee_sum += Decimal(str(ev[key]))
                            break
                if not missing and not dirty and assets and len(set(assets)) == 1:
                    basis = acq
                    proceeds = proc
                    if assets[0] == WSOL:
                        costs = fee_sum
                        net = proceeds - basis - costs
                    else:
                        costs = Decimal("0")
                        net = proceeds - basis
            if net is None:
                continue
            from scanner.mass_search.settlement import quote_consideration, settlement_of, USDC, USDT
            if proceeds is not None and Decimal(str(proceeds)) == 0 and quote_consideration(event) is None:
                continue
            unit = event.get("settlement_asset") or (
                "USDC" if settlement_of(event) == USDC
                else "USDT" if settlement_of(event) == USDT
                else None
            )
            if unit in (None, "", "SOL") and (
                event.get("amount_usdt") not in (None, "")
                or event.get("consideration_usdt") not in (None, "")
            ):
                unit = "USDT"
            if unit in (None, ""):
                unit = "SOL"
            episodes.append({
                "mint": mint,
                "close_signature": event.get("signature"),
                "opened_at": opened_at,
                "closed_at": event.get("timestamp") or event.get("block_time"),
                "timestamp": event.get("timestamp") or event.get("block_time"),
                "day": _episode_day(event),
                "basis": str(basis) if basis is not None else None,
                "acquisition": str(basis) if basis is not None else None,
                "proceeds": str(proceeds) if proceeds is not None else None,
                "costs": str(costs) if costs is not None else None,
                "verified_costs": str(costs) if costs is not None else None,
                "net": str(net),
                "unit": unit,
                "settlement_asset": unit,
            })
            opened = False
            opened_at = None
            episode_sigs = []
            episode_events = []
            buy_consideration = Decimal("0")
    return _restrict_ledger_to_report_window(report, episodes)


def _concentration_detail(report, scoped_pnl, known_sells):
    del known_sells
    episodes = _episode_ledger_from_report(report)
    unit = (report.get("completed_episode_net_unit")
            or ((report.get("research_profile") or {}).get("completed_episode_net_unit")))
    return concentration_from_episodes(episodes, scoped_pnl, unit)


def sensitivity_sign_flips(report, profile):
    """Item 11/12: unresolved adjacent costs that can flip the sign block a lead.

    A non-SOL settlement returns the cross-currency string and is truthy, so it
    blocks lead status. Multi-currency results are a vector, not an all-in net.
    """
    judged = sensitivity_result(report, profile)
    if judged.get("reason") == CROSS_CURRENCY_SENSITIVITY:
        return CROSS_CURRENCY_SENSITIVITY
    if judged.get("reason") == SENSITIVITY_NOT_ESTABLISHED or judged.get("evidence_state") == "not_established":
        return SENSITIVITY_NOT_ESTABLISHED
    return bool(judged.get("flips"))


INDEPENDENT_AUDIT_PATH = (
    Path(__file__).resolve().parents[2]
    / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage/INDEPENDENT_AUDIT.json"
)


def load_committed_independent_audit(address, fingerprint=None, ledger=None):
    if not address or not INDEPENDENT_AUDIT_PATH.is_file():
        return None
    try:
        payload = json.loads(INDEPENDENT_AUDIT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for row in payload.get("wallets") or []:
        if row.get("address") != address:
            continue
        status = row.get("status")
        episodes = [item for item in (row.get("episodes") or []) if isinstance(item, dict)]
        bridges = [item for item in (row.get("component_bridges") or []) if isinstance(item, dict)]
        if not bridges:
            bridges = [
                item.get("component_bridge")
                for item in episodes
                if isinstance(item.get("component_bridge"), dict)
            ]
        loaded = {
            "status": status,
            "independently_audited": status == "independently_audited" or row.get("independently_audited") is True,
            "independently_audited_episode_net": row.get("independently_audited_episode_net"),
            "independently_audited_episode_net_unit": row.get("independently_audited_episode_net_unit"),
            "app_completed_episode_net": row.get("app_completed_episode_net"),
            "app_completed_episode_net_unit": row.get("app_completed_episode_net_unit"),
            "worksheet_total": row.get("worksheet_total"),
            "worksheet_total_unit": row.get("worksheet_total_unit"),
            "worksheet_total_independently_audited": row.get("worksheet_total_independently_audited"),
            "app_completed_episodes": row.get("app_completed_episodes"),
            "auditor_clean_episodes": row.get("auditor_clean_episodes"),
            "unaudited_venues": list(row.get("unaudited_venues") or []),
            "content_fingerprint": row.get("content_fingerprint") or row.get("fingerprint"),
            "accounting_policy_version": row.get("accounting_policy_version") or ACCOUNTING_POLICY_VERSION,
            "episodes": episodes,
            "component_bridges": bridges,
            "worksheet_episode_bridge": row.get("worksheet_episode_bridge"),
            "aggregate_rounding_bridge": row.get("aggregate_rounding_bridge"),
            "auditor_confirmation": row.get("auditor_confirmation"),
            "one_to_one_membership": row.get("one_to_one_membership"),
            "note": (
                "Decoder-independent auditor vs app per episode. "
                "independently_audited sits next to the audited episode net, "
                "not a wallet-level worksheet total. "
                "A venue the auditor does not cover keeps the wallet from being a lead. "
                "The badge attaches only when the content fingerprint matches."
            ),
        }
        if fingerprint is not None:
            if ledger is not None:
                return bindable_independent_audit(loaded, fingerprint, ledger)
            if not audit_fingerprint_matches(loaded, fingerprint):
                return None
            return loaded
        return loaded
    return None


def _iso_to_unix(text):
    if not text:
        return None
    return int(datetime.fromisoformat(str(text).replace("Z", "+00:00")).timestamp())


def apply_headline_losing_pnl(profile, report, headline_net, headline_unit):
    """Write in-window losing PnL onto every surface that ranks or filters."""
    if profile is None or headline_net in (None, "") or not headline_unit:
        return profile
    profile["completed_episode_net"] = headline_net
    profile["completed_episode_net_unit"] = headline_unit
    profile["headline_includes_losing_episodes"] = True
    if isinstance(profile.get("completed_episode_net_vector"), dict):
        vector = dict(profile["completed_episode_net_vector"])
        vector[headline_unit] = headline_net
        profile["completed_episode_net_vector"] = vector
    if profile.get("scoped_pnl") not in (None, "") or headline_net not in (None, ""):
        profile["scoped_pnl"] = headline_net
        profile["scoped_pnl_unit"] = headline_unit
        by_asset = dict(profile.get("scoped_pnl_by_quote_asset") or {})
        by_asset[headline_unit] = headline_net
        profile["scoped_pnl_by_quote_asset"] = by_asset
    if isinstance(report, dict):
        report["completed_episode_net"] = headline_net
        report["completed_episode_net_unit"] = headline_unit
        report["headline_includes_losing_episodes"] = True
    return profile


def _normalize_headline_unit(unit):
    if unit in (USDC, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"):
        return "USDC"
    if unit in (USDT, "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"):
        return "USDT"
    if unit in ("SOL", "So11111111111111111111111111111111111111112", "WSOL"):
        return "SOL"
    return unit


def _headline_including_dropped_losers(clean_net, clean_unit, dropped):
    """Add in-window same-unit dropped-loser PnL so headlines are not overstated.

    CYrC CdhZy (−46.66 USDC) was excluded from both app and auditor headlines.
    Membership still fails independently_audited when losers were dropped.
    A loser in another quote currency, or a mixed headline, cannot be folded
    without mixing units: return a blocked (None, None) headline rather than
    the overstated clean number.
    """
    rows = [row for row in (dropped or []) if isinstance(row, dict)]
    if clean_unit in (None, "", "mixed"):
        if rows:
            return None, None, []
        return clean_net, clean_unit, []
    included = []
    total = Decimal(str(clean_net)) if clean_net not in (None, "") else None
    for row in rows:
        unit = _normalize_headline_unit(row.get("settlement_asset") or "SOL")
        if unit != clean_unit:
            return None, None, []
        try:
            amount = Decimal(str(row.get("net_profit") if row.get("net_profit") not in (None, "") else (
                row.get("net_profit_usdc") if unit == "USDC" else
                row.get("net_profit_usdt") if unit == "USDT" else
                row.get("net_profit_sol")
            )))
        except (InvalidOperation, TypeError, ValueError):
            return None, None, []
        included.append(row)
        total = amount if total is None else total + amount
    if not included:
        return clean_net, clean_unit, []
    text = format(total, "f") if total is not None else None
    if text and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text, clean_unit, included


def apply_blocked_headline_pnl(profile, report):
    """Blank ranking/filter surfaces when losers cannot be folded in-unit."""
    if profile is None:
        return profile
    profile["completed_episode_net"] = None
    profile["completed_episode_net_unit"] = None
    profile["scoped_pnl"] = None
    profile["scoped_pnl_unit"] = None
    profile["headline_includes_losing_episodes"] = False
    profile["headline_pnl_blocked"] = True
    if isinstance(report, dict):
        report["completed_episode_net"] = None
        report["completed_episode_net_unit"] = None
        report["headline_includes_losing_episodes"] = False
        report["headline_pnl_blocked"] = True
    return profile


def early_watch_label(completed):
    return f"Early watch – not proven ({int(completed)} of 3 completed rounds)"


def app_omitted_losing_episodes(mapped, report, ledger=None):
    """App-side in-window losers the completed ledger omitted.

    Independently walks mapped buy/sell lots. Clean completed flattens already
    on the ledger are left alone. Losing flattens missing from the ledger and
    unclosed losing inventory are included in headline P&L only — they never
    raise the completed-episode count.
    """
    from collections import defaultdict

    start = _iso_to_unix(((report or {}).get("window") or {}).get("start") or ((report or {}).get("window") or {}).get("start_inclusive"))
    end = _iso_to_unix(((report or {}).get("window") or {}).get("end") or ((report or {}).get("window") or {}).get("end_exclusive"))
    ledger_ids = {
        (str(item.get("mint") or ""), str(item.get("close_signature") or item.get("close") or ""))
        for item in (ledger or [])
        if item.get("mint")
    }

    def _in_window(stamp):
        if start is None or end is None or stamp is None:
            return True
        try:
            ts = int(stamp)
        except (TypeError, ValueError):
            ts = _iso_to_unix(stamp)
        if ts is None:
            return True
        return start <= ts < end

    by_mint = defaultdict(list)
    for row in mapped or []:
        if not isinstance(row, dict) or row.get("kind") not in ("buy", "sell"):
            continue
        mint = row.get("mint")
        if mint:
            by_mint[mint].append(row)
    omitted = []
    for mint, rows in by_mint.items():
        rows = sorted(rows, key=lambda row: (
            row.get("order") if isinstance(row.get("order"), int) and not isinstance(row.get("order"), bool) else 10 ** 12,
            row.get("seconds_from_start") or 0,
            row.get("timestamp") or 0,
            row.get("signature") or "",
        ))
        inventory = Decimal("0")
        opened = False
        pnl = Decimal("0")
        asset = None
        last_ts = None
        last_sig = None
        for row in rows:
            raw_units = row.get("units")
            if raw_units in (None, ""):
                raw_units = row.get("quantity_raw") or row.get("quantity") or 0
            try:
                qty = Decimal(str(raw_units))
            except (InvalidOperation, TypeError, ValueError):
                continue
            priced = quote_consideration(row)
            unit = settlement_of(row) or row.get("settlement_asset") or "SOL"
            if unit in (USDC, "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"):
                unit = "USDC"
            elif unit in (USDT, "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"):
                unit = "USDT"
            elif unit in ("SOL", "So11111111111111111111111111111111111111112", "WSOL"):
                unit = "SOL"
            if priced is None:
                for key, guess in (
                    ("consideration_usdc", "USDC"),
                    ("amount_usdc", "USDC"),
                    ("consideration_usdt", "USDT"),
                    ("amount_usdt", "USDT"),
                    ("consideration_sol", "SOL"),
                    ("amount_sol", "SOL"),
                ):
                    if row.get(key) not in (None, ""):
                        try:
                            priced = Decimal(str(row[key]))
                        except (InvalidOperation, TypeError, ValueError):
                            continue
                        unit = unit if unit in ("SOL", "USDC", "USDT") else guess
                        break
            if priced is None:
                continue
            if asset is None:
                asset = unit
            elif unit != asset:
                continue
            last_ts = row.get("timestamp") or row.get("block_time")
            last_sig = row.get("signature")
            if row.get("kind") == "buy":
                inventory += qty
                opened = True
                pnl -= priced
                continue
            inventory -= qty
            pnl += priced
            if opened and inventory == 0:
                key = (str(mint), str(last_sig or ""))
                if _in_window(last_ts) and pnl < 0 and key not in ledger_ids:
                    omitted.append({
                        "mint": mint,
                        "net_profit": format(pnl, "f"),
                        "settlement_asset": asset,
                        "timestamp": last_ts,
                        "reason": "app_omitted_losing_flatten",
                    })
                opened = False
                pnl = Decimal("0")
                inventory = Decimal("0")
                asset = None
            elif inventory < 0:
                opened = False
                pnl = Decimal("0")
                inventory = Decimal("0")
                asset = None
        # Unclosed losses are included only when leftover inventory is still
        # open and every lot on the mint was priced. Incomplete decoder rows
        # must not invent a headline loser (that would un-audit clean wallets).
        priced_rows = [row for row in rows if quote_consideration(row) is not None
                       or row.get("consideration_usdc") not in (None, "")
                       or row.get("consideration_usdt") not in (None, "")
                       or row.get("consideration_sol") not in (None, "")]
        if opened and pnl < 0 and _in_window(last_ts) and len(priced_rows) == len(rows) and inventory > 0:
            omitted.append({
                "mint": mint,
                "net_profit": format(pnl, "f"),
                "settlement_asset": asset or "SOL",
                "timestamp": last_ts,
                "reason": "unflattened_losing_inventory",
            })
    return omitted


def attach_live_independent_audit(report, profile, records, address):
    """Bind tools/independent_episode_audit.py to this wallet's live Phase 4.

    Dropped losers or a net / membership mismatch is never independently_audited.
    Window globals are restored so a later isolated audit cannot inherit
    this wallet's report bounds.
    """
    import tools.independent_episode_audit as auditor

    saved = (auditor.REPORT_START, auditor.REPORT_END, auditor.ACQUISITION)
    try:
        return _attach_live_independent_audit_body(report, profile, records, address)
    finally:
        auditor.REPORT_START, auditor.REPORT_END, auditor.ACQUISITION = saved


def _attach_live_independent_audit_body(report, profile, records, address):
    import tools.independent_episode_audit as auditor

    window = (report or {}).get("window") or {}
    start = _iso_to_unix(window.get("start") or window.get("start_inclusive"))
    end = _iso_to_unix(window.get("end") or window.get("end_exclusive"))
    acquisition = (report or {}).get("acquisition_start") or ((report or {}).get("history") or {}).get("history_start_inclusive")
    acq_unix = _iso_to_unix(acquisition)
    if start is not None:
        auditor.REPORT_START = start
    if end is not None:
        auditor.REPORT_END = end
    if acq_unix is not None:
        auditor.ACQUISITION = acq_unix
    trades = []
    for record in records or []:
        event = auditor.reconstruct_record(record, address)
        if event:
            trades.append(event)
    episodes, unresolved, known_sales, omitted_losing = auditor._fifo(trades)
    net, unit, by_unit = auditor.episode_net_totals(episodes)
    relevant = auditor.result_relevant_coverage(address, records, trades, episodes)
    ledger = list((profile or {}).get("completed_episode_ledger") or [])
    fingerprint = (profile or {}).get("audit_fingerprint")
    app_net = (profile or {}).get("completed_episode_net")
    app_unit = (profile or {}).get("completed_episode_net_unit")
    base = {
        "content_fingerprint": fingerprint,
        "accounting_policy_version": ACCOUNTING_POLICY_VERSION,
        "auditor_clean_episodes": len(episodes),
        "app_completed_episodes": len(ledger),
        "independently_audited_episode_net": net,
        "independently_audited_episode_net_unit": unit,
        "independently_audited_episode_nets_by_unit": by_unit,
        "app_completed_episode_net": app_net,
        "app_completed_episode_net_unit": app_unit,
        "unresolved_basis_sales": unresolved,
        "known_cost_sales": known_sales,
        "dropped_losing_episodes": omitted_losing,
        "dropped_losers": bool(omitted_losing),
        "omitted_losing_all": omitted_losing,
        "reconstructed_trades": len(trades),
        "result_relevant": relevant,
        "source": "live_phase4_independent_episode_audit",
        "economic_trades_by_utc_day": auditor.combined_economic_trades_by_utc_day(trades, records, address),
        "episodes": episodes,
        "PRODUCT_READY": False,
    }
    base["max_economic_trades_in_one_day"] = (
        max(base["economic_trades_by_utc_day"].values()) if base["economic_trades_by_utc_day"] else 0
    )
    base["max_economic_trades_on"] = (
        max(base["economic_trades_by_utc_day"], key=lambda item: (base["economic_trades_by_utc_day"][item], item))
        if base["economic_trades_by_utc_day"] else None
    )
    def _drop_in_report_window(row):
        if row.get("reason") == "not_in_window_or_unresolved":
            return False
        ts = row.get("timestamp")
        if ts is None:
            return True
        return auditor.REPORT_START <= ts < auditor.REPORT_END

    in_window_drops = [
        row for row in (omitted_losing or [])
        if _drop_in_report_window(row)
    ]
    base["dropped_losing_episodes"] = in_window_drops
    base["dropped_losers"] = bool(in_window_drops)
    headline_net, headline_unit, included_drops = _headline_including_dropped_losers(
        net, unit, in_window_drops,
    )
    if included_drops and len(included_drops) == len(in_window_drops) and headline_net not in (None, ""):
        base["independently_audited_episode_net"] = headline_net
        base["independently_audited_episode_net_unit"] = headline_unit
        base["included_dropped_losing_pnl"] = included_drops
        # App silently omitted the same in-window losers (CYrC CdhZy -46.66,
        # 9DkBp3oY -251.13, 9bfcmF unclosed). Headline P&L must include them
        # even when clean nets already disagreed; membership stays unaudited.
        if profile is not None:
            apply_headline_losing_pnl(profile, report, headline_net, headline_unit)
            base["app_completed_episode_net"] = profile.get("completed_episode_net")
            base["app_completed_episode_net_unit"] = profile.get("completed_episode_net_unit")
    elif in_window_drops:
        base["independently_audited_episode_net"] = None
        base["independently_audited_episode_net_unit"] = None
        base["headline_pnl_blocked"] = True
        if profile is not None:
            apply_blocked_headline_pnl(profile, report)
            base["app_completed_episode_net"] = profile.get("completed_episode_net")
            base["app_completed_episode_net_unit"] = profile.get("completed_episode_net_unit")
    if in_window_drops:
        return {
            **base,
            "status": "not_independently_audited",
            "independently_audited": False,
            "reason": "auditor_dropped_losing_episodes",
            "dropped_losing_episodes": in_window_drops,
            "dropped_losers": True,
            "one_to_one_membership": False,
        }
    app_ids = {}
    for item in ledger:
        key = (str(item.get("mint") or ""), str(item.get("close_signature") or item.get("close") or ""))
        if not key[0] or not key[1]:
            return {
                **base,
                "status": "not_independently_audited",
                "independently_audited": False,
                "reason": "app_episode_missing_identity",
                "one_to_one_membership": False,
            }
        if key in app_ids:
            return {
                **base,
                "status": "not_independently_audited",
                "independently_audited": False,
                "reason": "app_episode_duplicate_identity",
                "one_to_one_membership": False,
            }
        app_ids[key] = item
    aud_ids = {}
    for item in episodes:
        key = (str(item.get("mint") or ""), str(item.get("close_signature") or ""))
        if not key[0] or not key[1] or key in aud_ids:
            return {
                **base,
                "status": "not_independently_audited",
                "independently_audited": False,
                "reason": "auditor_episode_identity",
                "one_to_one_membership": False,
            }
        aud_ids[key] = item
    if not app_ids or set(app_ids) != set(aud_ids):
        return {
            **base,
            "status": "not_independently_audited",
            "independently_audited": False,
            "reason": "episode_membership_mismatch",
            "one_to_one_membership": False,
        }
    bridges = []
    episode_rows = []
    all_agree = True
    for key, app_ep in app_ids.items():
        aud_ep = aud_ids[key]
        ep_unit = app_ep.get("unit") or app_ep.get("settlement_asset") or aud_ep.get("settlement_asset") or "SOL"
        app_norm = {
            "mint": app_ep.get("mint"),
            "close_signature": app_ep.get("close_signature") or app_ep.get("close"),
            "basis": app_ep.get("basis") or app_ep.get("acquisition") or app_ep.get("basis_sol"),
            "proceeds": app_ep.get("proceeds") or app_ep.get("proceeds_sol"),
            "verified_costs": app_ep.get("verified_costs") or app_ep.get("costs") or app_ep.get("verified_costs_sol"),
            "net": app_ep.get("net") or app_ep.get("net_profit_sol") or app_ep.get("pnl"),
        }
        aud_norm = {
            "mint": aud_ep.get("mint"),
            "close_signature": aud_ep.get("close_signature"),
            "basis": aud_ep.get("basis_sol"),
            "proceeds": aud_ep.get("proceeds_sol"),
            "verified_costs": aud_ep.get("verified_costs_sol"),
            "net": (
                aud_ep.get("net_profit")
                or aud_ep.get("net_profit_usdc")
                or aud_ep.get("net_profit_usdt")
                or aud_ep.get("net_profit_sol")
            ),
        }
        bridge = component_bridge(app_norm, aud_norm, ep_unit)
        bridges.append(bridge)
        if not bridge.get("agree"):
            all_agree = False
        episode_rows.append({
            "mint": key[0],
            "close_signature": key[1],
            "unit": ep_unit,
            "app": {name: app_norm.get(name) for name in ("basis", "proceeds", "verified_costs", "net")},
            "auditor": {name: aud_norm.get(name) for name in ("basis", "proceeds", "verified_costs", "net")},
            "match": bridge.get("agree"),
            "component_bridge": bridge,
        })
    if not all_agree:
        return {
            **base,
            "status": "not_independently_audited",
            "independently_audited": False,
            "reason": "component_mismatch",
            "one_to_one_membership": True,
            "component_bridges": bridges,
            "episodes": episode_rows,
        }
    if unit in (None, "", "mixed") or app_unit in (None, "", "mixed") or unit != app_unit:
        return {
            **base,
            "status": "not_independently_audited",
            "independently_audited": False,
            "reason": "unit_mismatch",
            "one_to_one_membership": True,
            "component_bridges": bridges,
            "episodes": episode_rows,
        }
    if not amounts_agree(app_net, net, unit):
        return {
            **base,
            "status": "not_independently_audited",
            "independently_audited": False,
            "reason": "net_mismatch",
            "one_to_one_membership": True,
            "component_bridges": bridges,
            "episodes": episode_rows,
        }
    headlines = {
        "app_completed_episode_net": str(app_net),
        "app_completed_episode_net_unit": app_unit,
        "independently_audited_episode_net": str(net),
        "independently_audited_episode_net_unit": unit,
        "auditor_confirmation": format_auditor_confirmation(
            str(app_net), str(net), unit, independently_audited=True
        ),
        "aggregate_rounding_bridge": aggregate_rounding_bridge(app_net, net, unit),
    }
    return {
        **base,
        **headlines,
        "status": "independently_audited",
        "independently_audited": True,
        "reason": None,
        "one_to_one_membership": True,
        "component_bridges": bridges,
        "episodes": episode_rows,
    }


def independently_audited(report, profile=None):
    """Genuine corpus requires a matching content fingerprint. No bypass.

    Saved profile copies are not an authoritative audit source.
    """
    audit = (report or {}).get("independent_audit") or {}
    if (profile or {}).get("app_omitted_losing_episodes") or (report or {}).get("app_omitted_losing_episodes"):
        return False
    if (profile or {}).get("headline_pnl_blocked") or (report or {}).get("headline_pnl_blocked"):
        return False
    if not audit:
        return False
    if audit.get("status") == "not_independently_audited":
        return False
    if audit.get("fingerprintless_not_certifying"):
        return False
    fingerprint = (profile or {}).get("audit_fingerprint") or (report or {}).get("audit_fingerprint")
    ledger = completed_episode_ledger(report, profile)
    if not fingerprint or not bindable_independent_audit(audit, fingerprint, ledger):
        return False
    if (profile or {}).get("ledger_summary_contradiction"):
        return False
    if not certificate_comparison_proof(audit, ledger):
        return False
    app_unit = (profile or {}).get("completed_episode_net_unit") or audit.get("app_completed_episode_net_unit")
    auditor_unit = audit.get("independently_audited_episode_net_unit")
    if app_unit and auditor_unit and app_unit != auditor_unit:
        return False
    if audit.get("status") == "independently_audited":
        return True
    return audit.get("independently_audited") is True


def qualification_level(report, profile):
    rate = trade_rate_from(report, profile)
    rate_fields = {
        "max_economic_trades_in_one_day": first_defined_int(rate.get("max")),
        "max_economic_trades_on": rate.get("max_on"),
        "max_trades_per_day": first_defined_int(rate.get("max")),
        "max_trades_per_day_on": rate.get("max_on"),
    }
    bundle = (report or {}).get("bundle_or_distribution") or (profile or {}).get("bundle_or_distribution") or {}
    if bundle.get("excluded"):
        reason = with_gt25_blocker(bundle.get("reason") or "bundle_or_distribution", rate)
        return {
            "level": "insufficient_evidence",
            "label": "bundle or distribution",
            "reason": reason,
            "blocker": reason,
            "not": "unprofitable",
            "qualifying_ledger": "completed_episode_ledger",
            "lead_eligible": False,
            **rate_fields,
        }
    history = (report or {}).get("history") or {}
    if (report or {}).get("history_complete") is False or history.get("history_complete") is False:
        reason = with_gt25_blocker(history.get("history_complete_reason") or "history_incomplete", rate)
        return {
            "level": "insufficient_evidence",
            "label": "history incomplete",
            "reason": reason,
            "blocker": reason,
            "not": "unprofitable",
            "qualifying_ledger": "completed_episode_ledger",
            "lead_eligible": False,
            **rate_fields,
        }
    completed = int(profile.get("completed_known_cost_positions") or 0)
    profit, _unit, _vector = qualifying_profit(profile, report)
    gate = mandatory_coverage_gate(report, profile)
    unresolved = int(profile.get("unresolved_basis_sales") or 0)
    mints = int((profile.get("concentration_detail") or {}).get("distinct_tokens") or 0)
    cost_dependency = sensitivity_sign_flips(report, profile)
    activity = profile.get("trading_activity") or trading_activity((report or {}).get("events") or [])
    audited = independently_audited(report, profile)
    if rate.get("incomplete"):
        reason = with_gt25_blocker("incomplete_trade_timestamps", rate) or "incomplete_trade_timestamps"
        return {
            "level": "insufficient_evidence",
            "label": "insufficient evidence",
            "reason": reason,
            "blocker": reason,
            "not": "unprofitable",
            "qualifying_ledger": "completed_episode_ledger",
            "lead_eligible": False,
            "max_economic_trades_in_one_day": first_defined_int(rate.get("max")),
            "max_economic_trades_on": rate.get("max_on"),
            "max_trades_per_day": first_defined_int(rate.get("max")),
            "max_trades_per_day_on": rate.get("max_on"),
        }
    if first_defined_int(rate.get("max")) is not None and rate["max"] > _qual_gates.MAX_ECONOMIC_TRADES_PER_UTC_DAY:
        reason = f"{GT_ECONOMIC_TRADES_RULE}: {rate['max']} on {rate['max_on']}"
        return {
            "level": "insufficient_evidence",
            "label": "insufficient evidence",
            "reason": reason,
            "blocker": reason,
            "not": "unprofitable",
            "qualifying_ledger": "completed_episode_ledger",
            "lead_eligible": False,
            "max_economic_trades_in_one_day": rate["max"],
            "max_economic_trades_on": rate["max_on"],
            "max_trades_per_day": rate["max"],
            "max_trades_per_day_on": rate["max_on"],
        }
    if completed < 1:
        reason = with_gt25_blocker("0 completed episodes", rate)
        return {
            "level": "insufficient_evidence",
            "label": "insufficient evidence",
            "reason": reason,
            "blocker": reason,
            "not": "unprofitable",
            "qualifying_ledger": "completed_episode_ledger",
            **rate_fields,
        }
    unresolved_accounting = unresolved > 0 or bool(cost_dependency) or not audited
    proof_except_episodes = (
        profit is not None
        and profit > 0
        and gate["passed"]
        and unresolved == 0
        and not cost_dependency
        and audited
    )
    clean = completed >= 3 and proof_except_episodes
    stronger = (
        clean
        and completed >= 20
        and mints >= 3
        and stronger_shortlist_activity_ok(activity, rate["max"])
    )
    if stronger:
        level = "stronger_research_shortlist"
        label = level.replace("_", " ")
    elif clean:
        level = "provisional_research_lead"
        label = level.replace("_", " ")
    elif completed in (1, 2) and proof_except_episodes:
        level = "early_watch"
        label = early_watch_label(completed)
    else:
        level = "conditional_captured_lot_result"
        label = level.replace("_", " ")
    return {
        "level": level,
        "label": label,
        "clean_episodes": completed,
        "positive_completed_episode_net": bool(profit is not None and profit > 0),
        "positive_scoped_net": bool(profit is not None and profit > 0),
        "qualifying_ledger": "completed_episode_ledger",
        "worksheet_is_not_qualifying": True,
        "coverage": gate.get("coverage_mandatory_share") or gate.get("coverage_count_share"),
        "coverage_gate": gate,
        "unresolved_accounting": unresolved_accounting,
        "sensitivity_sign_flip": cost_dependency,
        "independently_audited": audited,
        "lead_eligible": level in ("provisional_research_lead", "stronger_research_shortlist"),
        "proven": level in ("provisional_research_lead", "stronger_research_shortlist"),
        "PRODUCT_READY": False,
        "never_a_research_lead": level == "early_watch",
        "active_trading_days": activity.get("active_trading_days"),
        "span_days": activity.get("span_days"),
        "max_economic_trades_in_one_day": first_defined_int(rate.get("max")),
        "max_economic_trades_on": rate.get("max_on"),
        "max_trades_per_day": first_defined_int(rate.get("max")),
        "max_trades_per_day_on": rate.get("max_on"),
    }


def _coverage_fields(report):
    """Count and value stay separate; the mandatory gate is their conjunction."""
    shares = coverage_shares(report)
    fields = {
        "coverage_count_share": shares["coverage_count_share"],
        "coverage_value_share": shares["coverage_value_share"],
        "coverage_mandatory_share": shares["coverage_mandatory_share"],
        "coverage_historical_share": None,
        "decoder_coverage_share": shares["coverage_count_share"],
        "coverage_denominator_includes_unsupported_suspected_trading": True,
        "coverage_gate_version": shares.get("coverage_gate_version"),
        "coverage_count_share_whole_span": shares.get("coverage_count_share_whole_span"),
        "coverage_value_share_whole_span": shares.get("coverage_value_share_whole_span"),
        "result_relevant_size": shares.get("result_relevant_size"),
        "result_relevant_lineage_mints": shares.get("result_relevant_lineage_mints"),
    }
    relevant = ((report or {}).get("record_breakdown") or {}).get("result_relevant") or (report or {}).get("result_relevant")
    if relevant is not None:
        fields["result_relevant"] = {
            "version": relevant.get("version"),
            "size": relevant.get("size"),
            "lineage_mints": list(relevant.get("lineage_mints") or []),
            "signatures": list(relevant.get("signatures") or []),
            "empty": relevant.get("empty"),
            "gate_passed": relevant.get("gate_passed"),
        }
    return fields


def _coverage_share(report):
    return _coverage_fields(report)["coverage_count_share"]


def _mapped_trade_row(row):
    return {
        "kind": row["kind"],
        "units": str(row.get("quantity_raw") or row.get("units") or "0"),
        "mint": row.get("mint"),
        "seconds_from_start": row.get("seconds_from_start") or 0,
        "signature": row.get("signature"),
        "settlement_mint": row.get("settlement_mint"),
        "consideration_usdc": row.get("amount_usdc") or row.get("consideration_usdc"),
        "consideration_usdt": row.get("amount_usdt") or row.get("consideration_usdt"),
        "consideration_sol": row.get("amount_sol") or row.get("consideration_sol"),
        "amount_usdt": row.get("amount_usdt"),
        "settlement_asset": row.get("settlement_asset"),
        "wallet_fee_sol": row.get("fee_sol") or row.get("wallet_fee_sol"),
        "timestamp": row.get("timestamp") or row.get("block_time"),
        "timestamp_missing": bool(row.get("timestamp_missing")),
        "order": row.get("order"),
        "role": row.get("role"),
        "window_qualified": row.get("window_qualified"),
        "undecoded_buy": bool(row.get("undecoded_buy") or row.get("kind") == "undecoded_buy"),
    }


def _merge_decoded_taints(mapped, decoded):
    """Wire undecoded earlier buys from the decoder into FIFO mapped events."""
    if not decoded:
        return mapped
    seen = {
        (row.get("signature"), row.get("mint"), row.get("kind"))
        for row in mapped
    }
    out = list(mapped)
    for event in decoded.get("events") or []:
        if not (event.get("kind") == "undecoded_buy" or event.get("undecoded_buy")):
            continue
        key = (event.get("signature"), event.get("mint"), "undecoded_buy")
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "kind": "undecoded_buy",
            "undecoded_buy": True,
            "units": str(event.get("quantity_raw") or event.get("units") or "0"),
            "mint": event.get("mint"),
            "seconds_from_start": event.get("seconds_from_start") or 0,
            "signature": event.get("signature"),
            "settlement_mint": event.get("settlement_mint"),
            "consideration_usdc": event.get("amount_usdc") or event.get("consideration_usdc"),
            "consideration_usdt": event.get("amount_usdt") or event.get("consideration_usdt"),
            "consideration_sol": event.get("amount_sol") or event.get("consideration_sol"),
            "amount_usdt": event.get("amount_usdt"),
            "settlement_asset": event.get("settlement_asset"),
            "wallet_fee_sol": event.get("fee_sol") or event.get("wallet_fee_sol"),
            "timestamp": event.get("timestamp") or event.get("block_time"),
            "timestamp_missing": event.get("timestamp") is None and event.get("block_time") is None,
            "order": event.get("order"),
            "role": event.get("role"),
            "window_qualified": event.get("window_qualified"),
        })
    return out


def build_research_profile(report, *, filters=None, classification=None, decoded=None, records=None, address=None):
    """Build a scoped research profile from a reconstructed report. Unset ≠ passed."""
    filters = filters or default_filters()
    classification = classification or report.get("classification") or {}
    counts = classification.get("counts") or {}
    worksheet = report.get("worksheet") or report.get("independent_worksheet") or {}
    events = [row for row in (report.get("events") or []) if row.get("kind") in ("buy", "sell", "undecoded_buy")]
    mapped = _merge_decoded_taints([_mapped_trade_row(row) for row in events], decoded)
    known, unresolved = isolate_known_cost_by_mint(mapped) if mapped else ([], [])
    bundle = (report or {}).get("bundle_or_distribution") or {}
    if not bundle and records and (address or report.get("address")):
        from scanner.mass_search.bundle_detect import detect_bundle_or_distribution
        bundle = detect_bundle_or_distribution(records, address or report.get("address"))
        report["bundle_or_distribution"] = bundle
    sold_quarantined = {
        mint for mint in (bundle.get("sold_quarantined_mints") or []) if mint
    }
    quarantined_mints = {
        mint for mint in (bundle.get("quarantined_mints") or []) if mint
    }
    if sold_quarantined:
        completed_buy_sell = {
            mint
            for mint in {row.get("mint") for row in known if row.get("mint")}
            if any(row.get("kind") == "buy" and row.get("mint") == mint for row in known)
            and any(row.get("kind") == "sell" and row.get("mint") == mint for row in known)
        }
        kept = []
        for row in known:
            mint = row.get("mint")
            # A later dust transfer-in must not erase an existing buy-sell episode.
            if (
                row.get("kind") == "sell"
                and mint in sold_quarantined
                and mint not in completed_buy_sell
            ):
                unresolved.append({
                    **row,
                    "unresolved_basis": True,
                    "reason": "sold_quarantined_mint",
                    "split_part": "unresolved",
                })
            else:
                kept.append(row)
        known = kept
    known_sells = [row for row in known if row["kind"] == "sell"]
    known_buys = [row for row in known if row["kind"] == "buy"]
    open_lots = _open_lot_count(known) if known else 0
    market_swaps = int((report.get("coverage") or {}).get("decoded_swaps") or len(events))
    holder_fees = int(counts.get("pump_holder_fee_distribution") or 0)
    failed = int(counts.get("failed_on_chain") or (report.get("coverage") or {}).get("failed_transactions") or 0)
    reviewed_jupiter = int(counts.get("reviewed_jupiter_route") or 0)
    inner_unreviewed = int(counts.get("inner_pumpswap_without_reviewed_outer") or 0)
    txs = int(classification.get("transactions") or (report.get("coverage") or {}).get("transactions") or 0)
    by_quote = worksheet.get("by_quote_asset") or {}
    if not by_quote:
        if worksheet.get("settlement_asset") == "USDT" or worksheet.get("total_profit_usdt") not in (None, ""):
            by_quote = {"USDT": worksheet}
        elif worksheet.get("settlement_asset") == "USDC" or worksheet.get("total_profit_usdc") not in (None, ""):
            by_quote = {"USDC": worksheet}
        elif worksheet.get("total_profit_sol") not in (None, "") or worksheet.get("settlement_asset") == "SOL":
            by_quote = {"SOL": worksheet}
    if len(by_quote) > 1:
        settlement = "mixed"
    elif "USDT" in by_quote:
        settlement = "USDT"
    elif "USDC" in by_quote:
        settlement = "USDC"
    elif "SOL" in by_quote:
        settlement = "SOL"
    elif any(settlement_of(row) == USDT for row in mapped):
        settlement = "USDT"
    elif any(settlement_of(row) == USDC for row in mapped):
        settlement = "USDC"
    elif mapped:
        settlement = "SOL"
    else:
        settlement = None
    scoped_by_asset = {}
    if "USDT" in by_quote:
        scoped_by_asset["USDT"] = (by_quote["USDT"] or {}).get("total_profit_usdt") or (by_quote["USDT"] or {}).get("total_profit_usdc")
    if "USDC" in by_quote:
        scoped_by_asset["USDC"] = (by_quote["USDC"] or {}).get("total_profit_usdc")
    if "SOL" in by_quote:
        scoped_by_asset["SOL"] = (by_quote["SOL"] or {}).get("total_profit_sol")
    if settlement == "USDT":
        scoped_pnl = scoped_by_asset.get("USDT")
    elif settlement == "USDC":
        scoped_pnl = scoped_by_asset.get("USDC")
    elif settlement == "SOL":
        scoped_pnl = scoped_by_asset.get("SOL")
    else:
        scoped_pnl = None
    sizes = []
    for row in known_buys + known_sells:
        priced = quote_consideration(row)
        amount = priced if priced is not None else (
            row.get("consideration_usdc") if settlement == "USDC" else row.get("consideration_sol")
        )
        if amount not in (None, ""):
            sizes.append({
                "kind": row["kind"],
                "mint": row.get("mint"),
                "amount": str(amount),
                "asset": settlement,
                "signature": row.get("signature"),
            })
    ledger = _episode_ledger_from_report(report)
    if sold_quarantined:
        # A later dust transfer-in must not erase an existing buy-sell episode.
        ledger = [
            item for item in ledger
            if item.get("mint") not in sold_quarantined
            or item.get("mint") in completed_buy_sell
        ]
    episode_net, episode_unit, episode_vector = episode_net_from_ledger(
        ledger, fallback_unit=settlement if settlement in ("SOL", "USDC", "USDT") else None
    )
    omitted_losing = app_omitted_losing_episodes(mapped, report, ledger)
    headline_net, headline_unit, included_drops = _headline_including_dropped_losers(
        episode_net, episode_unit, omitted_losing,
    )
    completed = len(ledger)
    if completed >= 1 and episode_vector:
        scoped_by_asset = {
            asset: str(amount)
            for asset, amount in episode_vector.items()
            if amount not in (None, "")
        }
        scoped_pnl = str(episode_net) if episode_net is not None else None
        if settlement != "mixed" and episode_unit in ("SOL", "USDC", "USDT"):
            settlement = episode_unit
    summary_net = report.get("completed_episode_net")
    summary_count = report.get("wallet_completed_episodes")
    ledger_contradiction = False
    if summary_net not in (None, "") and episode_net is not None:
        if not amounts_agree(summary_net, episode_net, episode_unit or "SOL"):
            ledger_contradiction = True
    elif summary_net not in (None, "") and episode_net is None:
        ledger_contradiction = True
    if summary_count not in (None, "") and int(summary_count) != completed:
        ledger_contradiction = True
    matched_fragment_pnl = None
    matched_fragment_unit = None
    tainted = any(
        row.get("undecoded_buy") or row.get("kind") == "undecoded_buy"
        for row in mapped
    )
    if completed < 1 and scoped_pnl not in (None, "") and not tainted:
        matched_fragment_pnl = scoped_pnl
        matched_fragment_unit = settlement
        scoped_pnl = None
        scoped_by_asset = {}
    elif completed < 1:
        scoped_pnl = None
        scoped_by_asset = {}
    sale_count = report.get("wallet_sale_count")
    if sale_count is None:
        sale_count = len([row for row in mapped if row["kind"] == "sell"])
    else:
        sale_count = int(sale_count)
    mint_counts = {}
    for row in known_sells:
        mint_counts[row.get("mint")] = mint_counts.get(row.get("mint"), 0) + 1
    concentration = None
    if known_sells:
        top = max(mint_counts.values())
        concentration = _share(top, len(known_sells))
    unresolved_share = _share(len(unresolved) + inner_unreviewed, max(txs, 1)) if txs else None
    holder_share = _share(holder_fees, txs) if txs else None
    market_vs_rewards = _share(market_swaps, holder_fees) if holder_fees else (str(market_swaps) if market_swaps else None)
    exit_diag = report.get("material_exit") or {}
    hold_t90 = exit_diag.get("exit_90_seconds")
    final_hold = exit_diag.get("final_hold_seconds")
    privileged = []
    if holder_fees:
        privileged.append({
            "indicator": "holder_fee_distributions",
            "count": holder_fees,
            "detail": "Reviewed Pump distribute_fee_to_holders is a reward, not a market trade",
        })
    if inner_unreviewed:
        privileged.append({
            "indicator": "inner_pumpswap_without_reviewed_outer",
            "count": inner_unreviewed,
            "detail": "Inner PumpSwap under an unreviewed outer stays unresolved and is hard to follow",
        })
    difficult = []
    if reviewed_jupiter:
        difficult.append({
            "indicator": "jupiter_usdc_route_v2",
            "count": reviewed_jupiter,
            "detail": "Followable only after official route_v2 + USDC settlement reconstruction",
        })
    if unresolved:
        difficult.append({
            "indicator": "unresolved_basis_sales",
            "count": len(unresolved),
            "detail": "Leading/unbacked sells have no known acquisition cost in this sample",
        })
    transfer_sources = (bundle.get("transfer_in_sources") or {}) if isinstance(bundle, dict) else {}
    transfer_sigs = (bundle.get("transfer_in_signatures") or {}) if isinstance(bundle, dict) else {}
    transfer_mints = set(bundle.get("transfer_in_mints") or []) if isinstance(bundle, dict) else set()
    unresolved_detail = []
    for row in unresolved:
        mint = row.get("mint")
        reason = row.get("reason") or "unknown_basis"
        source = transfer_sources.get(mint) if mint else None
        inbound_sig = transfer_sigs.get(mint) if mint else None
        leftover = isinstance(reason, str) and (
            reason.startswith("Sale has no known acquisition")
            or reason.startswith("Sale remainder has no known acquisition")
            or reason == "sold_quarantined_mint"
        )
        if leftover and (source or mint in transfer_mints):
            reason = "transfer_in_zero_basis"
            row["reason"] = reason
            row["transfer_in_source"] = source
            if inbound_sig:
                row["transfer_in_signature"] = inbound_sig
        unresolved_detail.append({
            "signature": row.get("signature"),
            "mint": mint,
            "reason": reason,
            "transfer_in_source": row.get("transfer_in_source") or source,
            "transfer_in_signature": row.get("transfer_in_signature") or inbound_sig,
            "split_part": row.get("split_part"),
            "unresolved_basis": True,
        })
    profile = {
        "kind": PROFILE_KIND,
        "address": report.get("address"),
        "settlement_asset": settlement,
        "scoped_pnl": scoped_pnl,
        "scoped_pnl_unit": settlement if completed >= 1 else None,
        "scoped_pnl_by_quote_asset": scoped_by_asset if completed >= 1 else {},
        "matched_fragment_pnl": matched_fragment_pnl,
        "matched_fragment_unit": matched_fragment_unit,
        "matched_fragment_note": (
            "matched-fragment results; not a completed-episode net"
            if matched_fragment_pnl not in (None, "")
            else None
        ),
        "completed_known_cost_positions": completed,
        "sample_positions": len(mapped),
        "sale_count": sale_count,
        "known_cost_trades": len(known),
        "unresolved_basis_sales": len(unresolved),
        "unresolved_basis_sales_detail": unresolved_detail,
        "quarantined_mints": sorted(quarantined_mints),
        "sold_quarantined_mints": sorted(sold_quarantined),
        "quarantine_never_sold": sorted(quarantined_mints - sold_quarantined),
        "open_buys_in_sample": open_lots,
        "sizes": sizes,
        "hold_t90_seconds": hold_t90,
        "final_hold_seconds": final_hold,
        "concentration": concentration,
        "open_or_unresolved": {
            "unresolved_basis_sales": len(unresolved),
            "inner_unreviewed": inner_unreviewed,
            "failed": failed,
            "open_inventory_present": any(
                Decimal(str(row["units"])) > 0 for row in known_buys
            ) and completed >= 0,
        },
        "market_vs_rewards": {
            "market_swaps": market_swaps,
            "holder_fee_distributions": holder_fees,
            "failed": failed,
            "reviewed_jupiter_routes": reviewed_jupiter,
            "ratio_market_to_rewards": market_vs_rewards,
            "holder_fee_share": holder_share,
            "rewards_are_not_trading_pnl": True,
            "fees_are_not_profitability": True,
        },
        "privileged_or_difficult_follower": privileged + difficult,
        "unresolved_share": unresolved_share,
        "unsupported_swap_share_in_window": (report.get("record_breakdown") or {}).get("unsupported_swap_share_in_window"),
        **_coverage_fields(report),
        "in_window_span": (report.get("record_breakdown") or {}).get("in_window_span"),
        "completed_episode_ledger": ledger,
        "completed_episode_net": episode_net,
        "completed_episode_net_unit": episode_unit,
        "completed_episode_net_vector": episode_vector,
        "included_dropped_losing_pnl": included_drops,
        "app_omitted_losing_episodes": omitted_losing,
        "headline_includes_losing_episodes": False,
        "headline_pnl_blocked": False,
        "ledger_summary_contradiction": ledger_contradiction,
        "concentration_detail": _concentration_detail(
            {**report, "completed_episode_ledger": ledger, "completed_episode_net_unit": episode_unit},
            episode_net,
            known_sells,
        ),
        "qualification_level": None,
        "thresholds": filters.get("thresholds") or dict(DEFAULT_THRESHOLDS),
        "threshold_results": {},
        "criteria_met": False,
        "unset_does_not_pass": False,
        "unset_is_not_applied": True,
        "safe_to_copy": False,
        "not_safe_to_copy": True,
        "PRODUCT_READY": False,
        "history_complete": bool((report or {}).get("history_complete") or ((report or {}).get("history") or {}).get("history_complete")),
        "notes": [
            "Scoped subset only. Unset thresholds are not applied.",
            "Holder rewards and network fees are not trading P&L.",
            "Qualification reads the completed-episode ledger in the captured window, never the worksheet total or account performance.",
        ],
    }
    activity = trading_activity(events)
    profile["trading_activity"] = activity
    rate_events = []
    if decoded and decoded.get("events"):
        rate_events = list(decoded.get("events") or [])
    elif report.get("captured_history_events"):
        rate_events = list(report.get("captured_history_events") or [])
    else:
        rate_events = list(events)
    attach_economic_trade_rate(
        profile, rate_events, records=records, address=address or report.get("address"),
    )
    if report.get("captured_history_events") in (None, []):
        report["captured_history_events"] = [
            row for row in rate_events if isinstance(row, dict) and row.get("kind") in ("buy", "sell")
        ]
    attach_economic_trade_rate(
        report, rate_events, records=records, address=address or report.get("address"),
    )
    if "sensitivity_unverified_debits_sol" in (report or {}):
        profile["sensitivity_unverified_debits_sol"] = report.get("sensitivity_unverified_debits_sol")
        profile["sensitivity_evidence_state"] = "measured" if report.get("sensitivity_unverified_debits_sol") not in (None, "") else "not_established"
    else:
        profile["sensitivity_evidence_state"] = "not_established"
    if omitted_losing:
        if (
            included_drops
            and len(included_drops) == len(omitted_losing)
            and headline_net not in (None, "")
            and headline_unit not in (None, "", "mixed")
        ):
            apply_headline_losing_pnl(profile, report, headline_net, headline_unit)
        else:
            apply_blocked_headline_pnl(profile, report)
    profile["worksheet_episode_bridge"] = worksheet_episode_bridge(scoped_pnl, episode_net, episode_unit or settlement)
    profile["exposure_outside_completed_episodes"] = exposure_outside_completed_episodes(report, profile)
    profile["requested_history_interval"] = requested_history_interval(report)
    analytics_open = ((report.get("analytics") or {}).get("open_positions"))
    open_positions = analytics_open if isinstance(analytics_open, list) else None
    profile["hold_time_stats"] = hold_time_stats(ledger, open_positions)
    fingerprint = compute_audit_fingerprint(report, profile=profile, episodes=ledger)
    profile["audit_fingerprint"] = fingerprint
    profile["accounting_policy_version"] = ACCOUNTING_POLICY_VERSION
    attached = (report or {}).get("independent_audit")
    bound = bindable_independent_audit(attached, fingerprint, ledger) if attached else None
    if ledger_contradiction:
        profile["independent_audit"] = None
        if (report or {}).get("independent_audit"):
            report["independent_audit"] = None
    elif bound:
        profile["independent_audit"] = bound
        report["independent_audit"] = bound
    elif attached and attached.get("status") == "not_independently_audited":
        profile["independent_audit"] = attached
        report["independent_audit"] = attached
    elif attached and is_synthetic_case(report) and not attached.get("content_fingerprint") and not attached.get("fingerprint"):
        # Explicit synthetic marker only. Fingerprintless audits never certify.
        profile["independent_audit"] = {
            **attached,
            "not_a_genuine_research_wallet": True,
            "fingerprintless_not_certifying": True,
        }
    else:
        loaded = load_committed_independent_audit(report.get("address") if report else None, fingerprint, ledger)
        profile["independent_audit"] = loaded
        if loaded:
            report["independent_audit"] = loaded
        elif (report or {}).get("independent_audit"):
            report["independent_audit"] = None
    if is_synthetic_case(report, profile):
        profile.update(mark_synthetic(profile, reason=report.get("synthetic_reason") or "synthetic regression case"))
        profile["not_a_genuine_research_wallet"] = True
    results = evaluate_thresholds(profile, filters.get("thresholds") or {})
    profile["threshold_results"] = results["results"]
    profile["criteria_met"] = results["criteria_met"]
    profile["evaluated_thresholds"] = results["evaluated"]
    profile["unset_thresholds"] = results["unset"]
    profile["evidence_class"] = classify_evidence(report, profile)
    profile["qualification_category"] = qualification_category(report, profile)
    profile["qualification_level"] = qualification_level(report, profile)
    profile["candidate_assessment"] = candidate_assessment(report, profile)
    from scanner.mass_search.labels import wallet_status_fields
    fields = wallet_status_fields(report, profile)
    profile["coverage_status"] = fields["coverage_status"]
    profile["coverage_status_display"] = fields.get("coverage_status_display") or fields["coverage_status"]
    profile["blocking_reason"] = fields["blocking_reason"]
    return profile


def qualification_category(report=None, profile=None):
    """Map existing evidence-class states onto qualification categories.

    Screening pass/fail stays in research_screen / criteria_met. A loss or
    inconclusive analysed wallet stays analysed_incomplete, never dropped.
    """
    if not report:
        return {
            "category": "not_evaluated",
            "evidence_class": 5,
            "evidence_class_label": EVIDENCE_CLASS[5],
            "screening_separate": True,
            "note": "Evidence quality is not a research-screen pass or fail.",
        }
    evidence = (profile or {}).get("evidence_class") or {}
    account_class = (evidence.get("account") or {}).get("class")
    position_class = (evidence.get("position") or {}).get("class")
    if account_class == 4:
        category = "profitable_account_performance"
        klass = 4
    elif position_class == 3:
        category = "positive_net_realised_over_window"
        klass = 3
    elif position_class == 1:
        category = "positive_matched_position_evidence"
        klass = 1
    else:
        category = "analysed_incomplete"
        klass = position_class if position_class in (2, 5) else 5
    return {
        "category": category,
        "evidence_class": klass,
        "evidence_class_label": EVIDENCE_CLASS.get(klass),
        "screening_separate": True,
        "note": "Evidence quality is not a research-screen pass or fail.",
    }


def classify_evidence(report, profile):
    """Five mutually exclusive evidence classes. A matched trade never qualifies the account."""
    completed = int(profile.get("completed_known_cost_positions") or 0)
    scoped = profile.get("scoped_pnl")
    usdc_excludes = ((report.get("worksheet") or {}).get("sol_fees_not_converted")
                     or (report.get("analytics") or {}).get("known_cost_realised_pnl", {}).get("usdc_excludes_sol_fees"))
    profitable = False
    if scoped not in (None, ""):
        try:
            profitable = Decimal(str(scoped)) > 0
        except Exception:
            profitable = False
    account = {
        "class": 5,
        "label": EVIDENCE_CLASS[5],
        "reason": "A positive matched trade never qualifies the account. Valuations and external flows are not in this path.",
    }
    if completed < 1 or not report.get("id"):
        position = {"class": 5, "label": EVIDENCE_CLASS[5], "reason": "No completed known-cost position in the captured sample."}
    elif profitable and report.get("offline_replay"):
        position = {
            "class": 2,
            "label": EVIDENCE_CLASS[2],
            "reason": "Positive known-basis result from incomplete captured history. Conditional on captured inventory.",
        }
    elif profitable:
        position = {
            "class": 1,
            "label": EVIDENCE_CLASS[1],
            "reason": "Profitable matched position in the captured sample. Does not qualify the account.",
        }
    else:
        position = {"class": 5, "label": EVIDENCE_CLASS[5], "reason": "Completed position is not a positive known-basis result."}
    if usdc_excludes:
        position["usdc_excludes_sol_fees_never_net"] = True
        position["not_class_3"] = "USDC that excludes SOL fees is never net realised."
    return {
        "position": position,
        "account": account,
        "transfers_are_not_zero_cost_buys_income_or_sales": True,
    }


def candidate_assessment(report, profile):
    worksheet = report.get("worksheet") or {}
    window = report.get("window") or {}
    analytics = report.get("analytics") or {}
    classification = report.get("classification") or {}
    unresolved = int(profile.get("unresolved_basis_sales") or 0)
    completed = int(profile.get("completed_known_cost_positions") or 0)
    scoped = profile.get("scoped_pnl")
    largest = None
    without_largest = None
    profits = worksheet.get("sale_net_profit_usdc") or worksheet.get("sale_net_profit_sol") or []
    if profits:
        values = [Decimal(str(item)) for item in profits]
        largest = str(max(values))
        if scoped not in (None, "") and len(values) >= 1:
            without_largest = str(Decimal(str(scoped)) - max(values))
    unknown_qty = Decimal("0")
    unknown_proceeds = Decimal("0")
    events = [row for row in (report.get("events") or []) if row.get("kind") in ("buy", "sell")]
    if events:
        from scanner.mass_search.settlement import isolate_known_cost_by_mint
        mapped = [_mapped_trade_row(row) for row in events]
        _, unresolved_rows = isolate_known_cost_by_mint(mapped)
        for row in unresolved_rows:
            unknown_qty += Decimal(str(row.get("units") or 0))
            amount = row.get("consideration_usdc") if row.get("consideration_usdc") not in (None, "") else row.get("consideration_sol")
            if amount not in (None, ""):
                unknown_proceeds += Decimal(str(amount))
    return {
        "kind": "candidate-assessment-v1",
        "evaluated_window": {"start": window.get("start"), "end": window.get("end")},
        "coverage": {
            "history_complete": False,
            "transactions_in_capture": int(classification.get("transactions") or 0),
            "supported_swaps": int((report.get("coverage") or {}).get("decoded_swaps") or 0),
            "note": "Coverage of captured transactions is not completeness of wallet history.",
        },
        "completed_matched_positions": completed,
        "active_trading_days": (profile.get("trading_activity") or trading_activity(events)).get("active_trading_days"),
        "active_trading_days_state": "EVALUATED_FROM_TRADING_EVENTS",
        "span_days": (profile.get("trading_activity") or trading_activity(events)).get("span_days"),
        "gross_realised": scoped,
        "net_realised": None,
        "net_realised_reason": (
            "USDC that excludes SOL fees is never net."
            if (worksheet.get("sol_fees_not_converted") or profile.get("settlement_asset") == "USDC")
            else "Net realised requires complete fees and a supported window; not claimed here."
        ),
        "fees_by_currency": {
            "SOL": ((report.get("classification") or {}).get("fee_totals") or {}).get("fee_sol"),
            "USDC": None,
            "sol_fees_not_converted_into_usdc": True,
        },
        "unknown_basis_quantity_and_proceeds": {
            "sales": unresolved,
            "quantity": _display_decimal(unknown_qty),
            "proceeds": _display_decimal(unknown_proceeds) if unknown_qty or unknown_proceeds else None,
            "unit": profile.get("settlement_asset"),
        },
        "open_inventory": (analytics.get("open_positions") or profile.get("open_or_unresolved") or {}),
        "valuation_available": False,
        "largest_winner_contribution": largest,
        "result_without_largest_winner": without_largest,
        "result_scope": "conditional_on_captured_inventory",
        "pass_fail_reasons": profile.get("threshold_results") or {},
        "visible_report": report.get("visible_report") is True,
        "not_safe_to_copy": True,
        "PRODUCT_READY": False,
    }


def evaluate_thresholds(profile, thresholds):
    thresholds = thresholds or {}
    results = {}
    evaluated = []
    unset = []
    comparisons = {
        "min_completed_known_cost": ("completed_known_cost_positions", "min"),
        "min_sample_positions": ("sample_positions", "min"),
        "min_coverage_share": ("coverage_mandatory_share", "min"),
        "min_scoped_pnl_usdc": ("scoped_pnl", "min", "USDC"),
        "min_scoped_pnl_sol": ("scoped_pnl", "min", "SOL"),
        "max_hold_t90_seconds": ("hold_t90_seconds", "max"),
        "max_concentration": ("concentration", "max"),
        "max_unresolved_share": ("unresolved_share", "max"),
        "min_market_vs_rewards_ratio": (("market_vs_rewards", "ratio_market_to_rewards"), "min"),
        "max_holder_fee_share": (("market_vs_rewards", "holder_fee_share"), "max"),
    }
    for key, spec in comparisons.items():
        raw = thresholds.get(key)
        if raw in (None, ""):
            results[key] = {"state": "NOT_SET", "passed": None, "applied": False, "note": "not set"}
            unset.append(key)
            continue
        if key in ("min_scoped_pnl_sol", "min_scoped_pnl_usdc"):
            completed = int(profile.get("completed_known_cost_positions") or 0)
            if completed < 1:
                results[key] = {
                    "state": "FAIL",
                    "passed": False,
                    "applied": True,
                    "actual": None,
                    "threshold": str(raw),
                    "note": "zero completed episodes cannot pass min P&L",
                }
                evaluated.append(key)
                continue
        field = spec[0]
        direction = spec[1]
        required_asset = spec[2] if len(spec) > 2 else None
        if required_asset:
            by_quote = profile.get("scoped_pnl_by_quote_asset") or {}
            has_asset = required_asset in by_quote
            if not has_asset:
                results[key] = {
                    "state": "FAIL",
                    "passed": False,
                    "applied": True,
                    "actual": None,
                    "threshold": str(raw),
                    "note": f"wallet has no {required_asset} completed-episode P&L",
                }
                evaluated.append(key)
                continue
        if required_asset and field == "scoped_pnl":
            actual = (profile.get("scoped_pnl_by_quote_asset") or {}).get(required_asset)
            if actual is None:
                actual = profile.get("scoped_pnl")
            actual_d = _decimal(actual)
            limit_d = _decimal(raw)
            if actual_d is None or limit_d is None:
                results[key] = {"state": "UNKNOWN", "passed": False, "applied": True, "actual": actual, "threshold": str(raw)}
                evaluated.append(key)
                continue
            passed = actual_d >= limit_d if direction == "min" else actual_d <= limit_d
            results[key] = {
                "state": "PASS" if passed else "FAIL",
                "passed": passed,
                "applied": True,
                "actual": str(actual_d),
                "threshold": str(limit_d),
            }
            evaluated.append(key)
            continue
        if isinstance(field, tuple):
            actual = profile
            for part in field:
                actual = (actual or {}).get(part) if isinstance(actual, dict) else None
        else:
            actual = profile.get(field)
        if key == "min_coverage_share" and actual in (None, ""):
            count_d = _decimal(profile.get("coverage_count_share"))
            value_d = _decimal(profile.get("coverage_value_share"))
            if count_d is not None and value_d is not None:
                actual = min(count_d, value_d)
        actual_d = _decimal(actual)
        limit_d = _decimal(raw)
        if actual_d is None or limit_d is None:
            results[key] = {"state": "UNKNOWN", "passed": False, "actual": actual, "threshold": str(raw)}
            evaluated.append(key)
            continue
        passed = actual_d >= limit_d if direction == "min" else actual_d <= limit_d
        results[key] = {
            "state": "PASS" if passed else "FAIL",
            "passed": passed,
            "applied": True,
            "actual": str(actual_d),
            "threshold": str(limit_d),
        }
        evaluated.append(key)
    criteria_met = bool(evaluated) and all(results[key].get("passed") for key in evaluated)
    if not evaluated:
        criteria_met = False
    return {"results": results, "criteria_met": criteria_met, "evaluated": evaluated, "unset": unset}
