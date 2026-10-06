"""Local research-profile metrics and versioned thresholds. Not a safe-to-copy claim."""
from __future__ import annotations

from decimal import Decimal

from scanner.mass_search.settlement import USDC, isolate_known_cost_by_mint, settlement_of

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
        "unset_does_not_pass": True,
        "unknown_never_passes": True,
        "not_safe_to_copy": True,
        "PRODUCT_READY": False,
    }


def _clean_proxy(incoming):
    proxy = _default_provider_proxy()
    source = incoming if isinstance(incoming, dict) else {}
    for key in ("min_provider_trade_count", "min_provider_score"):
        value = source.get(key)
        proxy[key] = None if value in (None, "", False) else str(value)
    for key in ("only_shortlist", "only_user_shortlist", "only_captured"):
        proxy[key] = bool(source.get(key))
    return proxy


def load_filters(store=None):
    if store is None:
        return default_filters()
    saved = store.get(FILTERS_KIND, FILTERS_KEY)
    if not isinstance(saved, dict):
        return default_filters()
    thresholds = dict(DEFAULT_THRESHOLDS)
    incoming = saved.get("thresholds") if isinstance(saved.get("thresholds"), dict) else {}
    reconstructed = saved.get("reconstructed") if isinstance(saved.get("reconstructed"), dict) else {}
    reconstructed_thresholds = reconstructed.get("thresholds") if isinstance(reconstructed.get("thresholds"), dict) else {}
    for key in THRESHOLD_KEYS:
        thresholds[key] = incoming.get(key) if incoming.get(key) not in (None, "") else reconstructed_thresholds.get(key)
    payload = default_filters()
    payload["thresholds"] = thresholds
    payload["reconstructed"] = {"thresholds": dict(thresholds)}
    payload["provider_proxy"] = _clean_proxy(saved.get("provider_proxy") or saved)
    payload["version"] = int(saved.get("version") or FILTERS_VERSION)
    payload["saved"] = True
    payload["only_shortlist"] = payload["provider_proxy"]["only_shortlist"]
    payload["only_captured"] = payload["provider_proxy"]["only_captured"]
    return payload


def save_filters(store, thresholds):
    payload = default_filters()
    incoming = thresholds if isinstance(thresholds, dict) else {}
    threshold_source = incoming.get("thresholds") if isinstance(incoming.get("thresholds"), dict) else incoming
    cleaned = {}
    for key in THRESHOLD_KEYS:
        value = threshold_source.get(key)
        if value in (None, "", False):
            cleaned[key] = None
            continue
        cleaned[key] = str(value)
    payload["thresholds"] = cleaned
    payload["reconstructed"] = {"thresholds": dict(cleaned)}
    payload["provider_proxy"] = _clean_proxy(incoming.get("provider_proxy") or incoming)
    payload["only_shortlist"] = payload["provider_proxy"]["only_shortlist"]
    payload["only_captured"] = payload["provider_proxy"]["only_captured"]
    store.put(FILTERS_KIND, FILTERS_KEY, payload)
    return payload


def _decimal(value):
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _share(part, whole):
    if not whole:
        return None
    return format(Decimal(part) / Decimal(whole), "f")


def build_research_profile(report, *, filters=None, classification=None, decoded=None):
    """Build a scoped research profile from a reconstructed report. Unset ≠ passed."""
    filters = filters or default_filters()
    classification = classification or report.get("classification") or {}
    counts = classification.get("counts") or {}
    worksheet = report.get("worksheet") or report.get("independent_worksheet") or {}
    events = [row for row in (report.get("events") or []) if row.get("kind") in ("buy", "sell")]
    mapped = []
    for row in events:
        mapped.append({
            "kind": row["kind"],
            "units": str(row.get("quantity_raw") or row.get("units") or "0"),
            "mint": row.get("mint"),
            "seconds_from_start": row.get("seconds_from_start") or 0,
            "signature": row.get("signature"),
            "settlement_mint": row.get("settlement_mint"),
            "consideration_usdc": row.get("amount_usdc") or row.get("consideration_usdc"),
            "consideration_sol": row.get("amount_sol") or row.get("consideration_sol"),
            "timestamp_missing": False,
        })
    known, unresolved = isolate_known_cost_by_mint(mapped) if mapped else ([], [])
    known_sells = [row for row in known if row["kind"] == "sell"]
    known_buys = [row for row in known if row["kind"] == "buy"]
    open_buys = []
    if mapped:
        remaining_known, _ = isolate_known_cost_by_mint(mapped)
        inventory = {}
        from decimal import Decimal as D
        for row in sorted(remaining_known, key=lambda item: (item.get("seconds_from_start") or 0, item.get("signature") or "")):
            mint = row.get("mint")
            inventory.setdefault(mint, D("0"))
            units = D(str(row["units"]))
            if row["kind"] == "buy":
                inventory[mint] += units
                if inventory[mint] > 0:
                    open_buys.append(row)
            else:
                inventory[mint] -= units
                if inventory[mint] <= 0:
                    open_buys = [item for item in open_buys if item.get("mint") != mint]
    market_swaps = int((report.get("coverage") or {}).get("decoded_swaps") or len(events))
    holder_fees = int(counts.get("pump_holder_fee_distribution") or 0)
    failed = int(counts.get("failed_on_chain") or (report.get("coverage") or {}).get("failed_transactions") or 0)
    reviewed_jupiter = int(counts.get("reviewed_jupiter_route") or 0)
    inner_unreviewed = int(counts.get("inner_pumpswap_without_reviewed_outer") or 0)
    txs = int(classification.get("transactions") or (report.get("coverage") or {}).get("transactions") or 0)
    settlement = None
    if any(settlement_of(row) == USDC for row in mapped):
        settlement = "USDC"
    elif mapped:
        settlement = "SOL"
    scoped_pnl = worksheet.get("total_profit_usdc") if settlement == "USDC" else worksheet.get("total_profit_sol")
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
    completed = int(report.get("wallet_completed_episodes") or len(known_sells))
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
        "scoped_pnl_unit": settlement,
        "completed_known_cost_positions": completed,
        "known_cost_trades": len(known),
        "unresolved_basis_sales": len(unresolved),
        "open_buys_in_sample": len([row for row in known_buys if row not in known_sells]),
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
        "thresholds": filters.get("thresholds") or dict(DEFAULT_THRESHOLDS),
        "threshold_results": {},
        "criteria_met": False,
        "unset_does_not_pass": True,
        "safe_to_copy": False,
        "not_safe_to_copy": True,
        "PRODUCT_READY": False,
        "history_complete": False,
        "notes": [
            "Scoped subset only. Unset thresholds do not pass.",
            "Holder rewards and network fees are not trading P&L.",
            "No blanket safe-to-copy claim.",
        ],
    }
    results = evaluate_thresholds(profile, filters.get("thresholds") or {})
    profile["threshold_results"] = results["results"]
    profile["criteria_met"] = results["criteria_met"]
    profile["evaluated_thresholds"] = results["evaluated"]
    profile["unset_thresholds"] = results["unset"]
    profile["evidence_class"] = classify_evidence(report, profile)
    profile["qualification_category"] = qualification_category(report, profile)
    profile["candidate_assessment"] = candidate_assessment(report, profile)
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
        mapped = []
        for row in events:
            mapped.append({
                "kind": row["kind"],
                "units": str(row.get("quantity_raw") or row.get("units") or "0"),
                "mint": row.get("mint"),
                "seconds_from_start": row.get("seconds_from_start") or 0,
                "signature": row.get("signature"),
                "settlement_mint": row.get("settlement_mint"),
                "consideration_usdc": row.get("amount_usdc") or row.get("consideration_usdc"),
                "consideration_sol": row.get("amount_sol") or row.get("consideration_sol"),
                "timestamp_missing": False,
            })
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
        "active_trading_days": None,
        "active_trading_days_state": "NOT_EVALUATED",
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
            "quantity": str(unknown_qty),
            "proceeds": str(unknown_proceeds) if unknown_qty or unknown_proceeds else None,
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
        "min_sample_positions": ("completed_known_cost_positions", "min"),
        "min_coverage_share": ("unresolved_share", "max"),
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
            results[key] = {"state": "UNSET", "passed": False, "note": "Unset does not pass"}
            unset.append(key)
            continue
        field = spec[0]
        direction = spec[1]
        required_asset = spec[2] if len(spec) > 2 else None
        if required_asset and profile.get("settlement_asset") != required_asset:
            results[key] = {"state": "NOT_APPLICABLE", "passed": False, "note": f"Settlement is not {required_asset}"}
            evaluated.append(key)
            continue
        if isinstance(field, tuple):
            actual = profile
            for part in field:
                actual = (actual or {}).get(part) if isinstance(actual, dict) else None
        else:
            actual = profile.get(field)
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
            "actual": str(actual_d),
            "threshold": str(limit_d),
        }
        evaluated.append(key)
    criteria_met = bool(evaluated) and all(results[key].get("passed") for key in evaluated) and not unset
    if not evaluated:
        criteria_met = False
    return {"results": results, "criteria_met": criteria_met, "evaluated": evaluated, "unset": unset}
