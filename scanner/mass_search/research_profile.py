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
    amounts_agree,
    audit_fingerprint_matches,
    bindable_independent_audit,
    certificate_comparison_proof,
    completed_episode_ledger,
    compute_audit_fingerprint,
    concentration_from_episodes,
    coverage_shares,
    episode_net_from_ledger,
    exposure_outside_completed_episodes,
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
)
from scanner.mass_search.settlement import (
    USDC,
    _open_lot_count,
    isolate_known_cost_by_mint,
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


def _restrict_ledger_to_report_window(report, episodes):
    """Qualification and P&L use only episodes closed inside the report window."""
    start, end = _capture_window_unix(report)
    if start is None and end is None:
        return list(episodes or [])
    out = []
    for episode in episodes or []:
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
    for key in ("only_shortlist", "only_user_shortlist", "only_captured"):
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
                for key in ("consideration_sol", "amount_sol", "consideration_usdc", "amount_usdc"):
                    if event.get(key) not in (None, ""):
                        buy_consideration += Decimal(str(event[key]))
                        break
                continue
            if event.get("kind") != "sell" or not opened or inventory <= 0:
                continue
            inventory -= units
            episode_sigs.append(event.get("signature"))
            if inventory < 0:
                opened = False
                opened_at = None
                episode_sigs = []
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
            elif event.get("known_cost_pnl") not in (None, ""):
                net = Decimal(str(event["known_cost_pnl"]))
            unit = event.get("settlement_asset") or (
                "USDC" if event.get("amount_usdc") or event.get("consideration_usdc") else "SOL"
            )
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
                "net": str(net) if net is not None else None,
                "unit": unit,
                "settlement_asset": unit,
            })
            opened = False
            opened_at = None
            episode_sigs = []
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


def independently_audited(report, profile=None):
    """Genuine corpus requires a matching content fingerprint. No bypass.

    Saved profile copies are not an authoritative audit source.
    """
    audit = (report or {}).get("independent_audit") or {}
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
    completed = int(profile.get("completed_known_cost_positions") or 0)
    profit, _unit, _vector = qualifying_profit(profile, report)
    gate = mandatory_coverage_gate(report, profile)
    unresolved = int(profile.get("unresolved_basis_sales") or 0)
    mints = int((profile.get("concentration_detail") or {}).get("distinct_tokens") or 0)
    cost_dependency = sensitivity_sign_flips(report, profile)
    activity = profile.get("trading_activity") or trading_activity((report or {}).get("events") or [])
    audited = independently_audited(report, profile)
    if completed < 1:
        return {
            "level": "insufficient_evidence",
            "label": "insufficient evidence",
            "not": "unprofitable",
            "qualifying_ledger": "completed_episode_ledger",
        }
    unresolved_accounting = unresolved > 0 or bool(cost_dependency) or not audited
    clean = (
        completed >= 3
        and profit is not None
        and profit > 0
        and gate["passed"]
        and unresolved == 0
        and not cost_dependency
        and audited
    )
    stronger = (
        clean
        and completed >= 20
        and mints >= 3
        and stronger_shortlist_activity_ok(activity)
    )
    if stronger:
        level = "stronger_research_shortlist"
    elif clean:
        level = "provisional_research_lead"
    else:
        level = "conditional_captured_lot_result"
    return {
        "level": level,
        "label": level.replace("_", " "),
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
        "active_trading_days": activity.get("active_trading_days"),
        "span_days": activity.get("span_days"),
    }


def _coverage_fields(report):
    """Count and value stay separate; the mandatory gate is their conjunction."""
    shares = coverage_shares(report)
    return {
        "coverage_count_share": shares["coverage_count_share"],
        "coverage_value_share": shares["coverage_value_share"],
        "coverage_mandatory_share": shares["coverage_mandatory_share"],
        "coverage_historical_share": None,
        "decoder_coverage_share": shares["coverage_count_share"],
        "coverage_denominator_includes_unsupported_suspected_trading": True,
    }


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
        "consideration_sol": row.get("amount_sol") or row.get("consideration_sol"),
        "wallet_fee_sol": row.get("fee_sol") or row.get("wallet_fee_sol"),
        "timestamp": row.get("timestamp") or row.get("block_time"),
        "timestamp_missing": bool(row.get("timestamp_missing")),
        "order": row.get("order"),
        "role": row.get("role"),
        "window_qualified": row.get("window_qualified"),
    }


def build_research_profile(report, *, filters=None, classification=None, decoded=None):
    """Build a scoped research profile from a reconstructed report. Unset ≠ passed."""
    filters = filters or default_filters()
    classification = classification or report.get("classification") or {}
    counts = classification.get("counts") or {}
    worksheet = report.get("worksheet") or report.get("independent_worksheet") or {}
    events = [row for row in (report.get("events") or []) if row.get("kind") in ("buy", "sell")]
    mapped = [_mapped_trade_row(row) for row in events]
    known, unresolved = isolate_known_cost_by_mint(mapped) if mapped else ([], [])
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
        if worksheet.get("settlement_asset") == "USDC" or worksheet.get("total_profit_usdc") not in (None, ""):
            by_quote = {"USDC": worksheet}
        elif worksheet.get("total_profit_sol") not in (None, "") or worksheet.get("settlement_asset") == "SOL":
            by_quote = {"SOL": worksheet}
    if len(by_quote) > 1:
        settlement = "mixed"
    elif "USDC" in by_quote:
        settlement = "USDC"
    elif "SOL" in by_quote:
        settlement = "SOL"
    elif any(settlement_of(row) == USDC for row in mapped):
        settlement = "USDC"
    elif mapped:
        settlement = "SOL"
    else:
        settlement = None
    scoped_by_asset = {}
    if "USDC" in by_quote:
        scoped_by_asset["USDC"] = (by_quote["USDC"] or {}).get("total_profit_usdc")
    if "SOL" in by_quote:
        scoped_by_asset["SOL"] = (by_quote["SOL"] or {}).get("total_profit_sol")
    if settlement == "USDC":
        scoped_pnl = scoped_by_asset.get("USDC")
    elif settlement == "SOL":
        scoped_pnl = scoped_by_asset.get("SOL")
    else:
        scoped_pnl = None
    sizes = []
    for row in known_buys + known_sells:
        amount = row.get("consideration_usdc") if settlement == "USDC" else row.get("consideration_sol")
        if amount not in (None, ""):
            sizes.append({
                "kind": row["kind"],
                "mint": row.get("mint"),
                "amount": str(amount),
                "asset": settlement,
                "signature": row.get("signature"),
            })
    ledger = _episode_ledger_from_report(report)
    episode_net, episode_unit, episode_vector = episode_net_from_ledger(
        ledger, fallback_unit=settlement if settlement in ("SOL", "USDC") else None
    )
    completed = len(ledger)
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
    if completed < 1 and scoped_pnl not in (None, ""):
        matched_fragment_pnl = scoped_pnl
        matched_fragment_unit = settlement
        scoped_pnl = None
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
        "history_complete": False,
        "notes": [
            "Scoped subset only. Unset thresholds are not applied.",
            "Holder rewards and network fees are not trading P&L.",
            "Qualification reads the completed-episode ledger in the captured window, never the worksheet total or account performance.",
        ],
    }
    activity = trading_activity(events)
    profile["trading_activity"] = activity
    if "sensitivity_unverified_debits_sol" in (report or {}):
        profile["sensitivity_unverified_debits_sol"] = report.get("sensitivity_unverified_debits_sol")
        profile["sensitivity_evidence_state"] = "measured" if report.get("sensitivity_unverified_debits_sol") not in (None, "") else "not_established"
    else:
        profile["sensitivity_evidence_state"] = "not_established"
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
        field = spec[0]
        direction = spec[1]
        required_asset = spec[2] if len(spec) > 2 else None
        if required_asset:
            by_quote = profile.get("scoped_pnl_by_quote_asset") or {}
            has_asset = required_asset in by_quote or profile.get("settlement_asset") == required_asset
            if not has_asset:
                results[key] = {
                    "state": "NOT_APPLICABLE",
                    "passed": None,
                    "applied": False,
                    "note": f"not set for this wallet — settlement is not {required_asset}",
                }
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
