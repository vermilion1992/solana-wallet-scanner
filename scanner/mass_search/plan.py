"""Mass research v1 plan validation. The named Strict preset stays byte-identical."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path

from scanner.config import STRICT

MASS_RESEARCH_PLAN_NAME = "Mass research v1"
PLAN_SCHEMA_VERSION = "mass-search-plan-v1"
STRICT_PRESET_SNAPSHOT = {
    "name": "Strict research",
    "version": "strict-v0.3",
    "window_days": 30,
    "verification_days": 90,
    "min_profit_sol": "5",
    "min_realised_roi_pct": "10",
    "min_median_roi_pct": "5",
    "min_win_rate_pct": "50",
    "max_win_rate_pct": "85",
    "min_hold_hours": "1",
    "max_hold_hours": "72",
    "min_positions": 50,
    "min_positions_90d": 100,
    "min_mints": 20,
    "max_mints": 100,
    "max_rapid_sale_pct": "10",
    "min_avg_buys": "1",
    "max_avg_buys": "2",
    "min_avg_sells": "1",
    "max_avg_sells": "3",
    "min_positive_weeks": 3,
    "max_contribution_pct": "25",
    "require_positive_economic_pnl": True,
}

_PACKAGE_EXAMPLE = Path(__file__).resolve().parents[2] / "work_packages" / "mass_wallet_search_v1" / "config" / "search_plan.example.json"


def assert_strict_preset_unchanged(preset=None):
    actual = dict(preset or STRICT)
    if actual != STRICT_PRESET_SNAPSHOT:
        raise ValueError("Named Strict research preset values must remain unchanged")
    return deepcopy(actual)


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _positive_int(value, name, maximum):
    if type(value) is not int or isinstance(value, bool) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 1 and {maximum}")
    return value


def _decimal_string(value, name, *, allow_null=False):
    if value is None and allow_null:
        return None
    if not isinstance(value, str) or not value or len(value) > 40:
        raise ValueError(f"{name} must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"Invalid {name}") from error
    if not number.is_finite():
        raise ValueError(f"Invalid {name}")
    return value


def load_default_plan():
    if _PACKAGE_EXAMPLE.is_file():
        return validate_mass_plan(json.loads(_PACKAGE_EXAMPLE.read_text()))
    return validate_mass_plan({"schema_version": PLAN_SCHEMA_VERSION, "name": MASS_RESEARCH_PLAN_NAME})


def validate_mass_plan(value=None):
    assert_strict_preset_unchanged()
    incoming = {} if value is None else value
    if not isinstance(incoming, dict):
        raise ValueError("Mass research plan must be an object")
    plan = deepcopy(incoming)
    plan.setdefault("schema_version", PLAN_SCHEMA_VERSION)
    if plan["schema_version"] != PLAN_SCHEMA_VERSION:
        raise ValueError("Unsupported mass-search plan version")
    plan.setdefault("status", "PROPOSED_CONFIGURATION_NOT_LIVE_AUTHORIZATION")
    plan.setdefault("name", MASS_RESEARCH_PLAN_NAME)
    if plan["name"] != MASS_RESEARCH_PLAN_NAME:
        raise ValueError("Mass research plan must keep its separately named identity")
    plan.setdefault("chain", "solana")
    if plan["chain"] != "solana":
        raise ValueError("This funnel is Solana-only")
    plan.setdefault("live_enabled", False)
    if type(plan["live_enabled"]) is not bool:
        raise ValueError("live_enabled must be boolean")
    selection = dict(plan.get("selection") or {})
    selection.setdefault("report_window_days", 30)
    selection.setdefault("verification_window_days", 90)
    selection.setdefault("freeze_as_of_before_acquisition", True)
    selection.setdefault("atomic_provider_snapshot_required_for_exact_asof_claim", True)
    selection.setdefault("address_order_tie_break", "chain_then_address")
    selection.setdefault("preserve_source_memberships", True)
    selection.setdefault("universe_target_unique", 1000)
    selection.setdefault("local_universe_capacity", 10000)
    selection.setdefault("target_positive_candidates", 3)
    selection.setdefault("force_target_count", False)
    selection.setdefault("auto_relax_filters", False)
    _positive_int(selection["report_window_days"], "report_window_days", 365)
    _positive_int(selection["verification_window_days"], "verification_window_days", 365)
    if selection["report_window_days"] > selection["verification_window_days"]:
        raise ValueError("Report window must fit inside the verification window")
    _positive_int(selection["universe_target_unique"], "universe_target_unique", 10000)
    _positive_int(selection["local_universe_capacity"], "local_universe_capacity", 10000)
    if selection["local_universe_capacity"] > 10000:
        raise ValueError("Local universe capacity cannot exceed 10000")
    for flag in ("freeze_as_of_before_acquisition", "atomic_provider_snapshot_required_for_exact_asof_claim",
                 "preserve_source_memberships", "force_target_count", "auto_relax_filters"):
        if type(selection[flag]) is not bool:
            raise ValueError(f"{flag} must be boolean")
    if selection["force_target_count"] or selection["auto_relax_filters"]:
        raise ValueError("Mass research v1 cannot auto-relax filters or force a winner count")
    plan["selection"] = selection
    maxima = dict(plan.get("stage_workload_maxima_not_permissions") or {})
    maxima.setdefault("summary_enrichment", 200)
    maxima.setdefault("behaviour_history", 50)
    maxima.setdefault("detailed_reconstruction", 20)
    maxima.setdefault("forward_watch_candidates", 5)
    maxima.setdefault("legacy_route_and_approved_budget_caps_still_apply", True)
    for key, ceiling in (("summary_enrichment", 200), ("behaviour_history", 50),
                         ("detailed_reconstruction", 20), ("forward_watch_candidates", 5)):
        _positive_int(maxima[key], key, ceiling)
    if maxima["legacy_route_and_approved_budget_caps_still_apply"] is not True:
        raise ValueError("Legacy route and approved budget caps still apply")
    plan["stage_workload_maxima_not_permissions"] = maxima
    ranking = dict(plan.get("preliminary_ranking") or {})
    ranking.setdefault("provider_reported_metrics_only_for_queue_priority", True)
    ranking.setdefault("prefer_positive_reported_realised_pnl", True)
    ranking.setdefault("prefer_recent_activity_within_days", 7)
    ranking.setdefault("prefer_provider_trade_count_at_least", 20)
    ranking.setdefault("original_currency_and_population_required", True)
    ranking.setdefault("missing_metric_outcome", "DEFERRED")
    ranking.setdefault("hard_fail_never_inferred_from_incompatible_proxy", True)
    ranking.setdefault("no_opaque_safety_score", True)
    ranking.setdefault("reject_known_negative_reported_pnl", False)
    if ranking["missing_metric_outcome"] != "DEFERRED":
        raise ValueError("Missing preliminary metrics must defer, not fail or pass")
    for flag in ("provider_reported_metrics_only_for_queue_priority", "prefer_positive_reported_realised_pnl",
                 "original_currency_and_population_required", "hard_fail_never_inferred_from_incompatible_proxy",
                 "no_opaque_safety_score", "reject_known_negative_reported_pnl"):
        if type(ranking[flag]) is not bool:
            raise ValueError(f"{flag} must be boolean")
    _positive_int(ranking["prefer_recent_activity_within_days"], "prefer_recent_activity_within_days", 90)
    _positive_int(ranking["prefer_provider_trade_count_at_least"], "prefer_provider_trade_count_at_least", 100000)
    plan["preliminary_ranking"] = ranking
    audit = dict(plan.get("exploration_audit") or {})
    audit.setdefault("enabled", True)
    audit.setdefault("share_of_authorised_deep_work_pct", "5")
    audit.setdefault("sampling", "deterministic_hash_stratified_by_reason")
    audit.setdefault("selection_seed", "mass-research-v1")
    audit.setdefault("minimum_spend_override", False)
    _decimal_string(audit["share_of_authorised_deep_work_pct"], "share_of_authorised_deep_work_pct")
    if audit["minimum_spend_override"] is not False:
        raise ValueError("Exploration audit cannot override an insufficient budget")
    plan["exploration_audit"] = audit
    following = dict(plan.get("provisional_following_model") or {})
    following.setdefault("execution", "QUOTE_ONLY_NO_SIGNING")
    following.setdefault("baseline_strategy", "fixed-entry-first-sale-v1")
    following.setdefault("secondary_strategy", "fixed-entry-proportional-exit-v1")
    following.setdefault("primary_reaction_delay_seconds", 60)
    following.setdefault("stress_reaction_delay_seconds", [15, 60, 180])
    following.setdefault("detection_and_decoding_latency_added_separately", True)
    following.setdefault("initial_simulated_capital_sol", "10")
    following.setdefault("fixed_simulated_entry_sol", "0.1")
    following.setdefault("max_open_positions", 5)
    following.setdefault("extra_execution_cost_sol_per_leg", None)
    following.setdefault("adverse_quote_haircut_bps", None)
    following.setdefault("unset_cost_inputs_block_economic_run", True)
    following.setdefault("missing_exit_action", "RETAIN_OPEN_UNPRICED")
    following.setdefault("quotes_are_fills", False)
    if following["execution"] != "QUOTE_ONLY_NO_SIGNING" or following["quotes_are_fills"] is not False:
        raise ValueError("Following model is quote-only and never treats quotes as fills")
    if following["baseline_strategy"] != "fixed-entry-first-sale-v1":
        raise ValueError("Baseline following strategy must remain fixed-entry-first-sale-v1")
    if type(following["primary_reaction_delay_seconds"]) is not int or not 0 <= following["primary_reaction_delay_seconds"] <= 3600:
        raise ValueError("Primary reaction delay must be 0–3600 seconds")
    if following["stress_reaction_delay_seconds"] != [15, 60, 180]:
        raise ValueError("Stress reaction delays must remain 15, 60 and 180 seconds")
    _decimal_string(following["initial_simulated_capital_sol"], "initial_simulated_capital_sol")
    _decimal_string(following["fixed_simulated_entry_sol"], "fixed_simulated_entry_sol")
    _positive_int(following["max_open_positions"], "max_open_positions", 25)
    if following["missing_exit_action"] != "RETAIN_OPEN_UNPRICED":
        raise ValueError("Unavailable exits must remain open and unpriced")
    plan["provisional_following_model"] = following
    network = dict(plan.get("network_policy") or {})
    network.setdefault("maximum_additional_spend_usd", "0")
    network.setdefault("paid_upgrade_allowed", False)
    network.setdefault("overages_allowed", False)
    network.setdefault("per_provider_budgets_must_be_explicit", True)
    network.setdefault("offline_refilter_external_requests", 0)
    network.setdefault("max_concurrency_must_not_exceed_existing_route_caps", True)
    if network["maximum_additional_spend_usd"] != "0" or network["paid_upgrade_allowed"] or network["overages_allowed"]:
        raise ValueError("Mass research v1 forbids paid upgrades, overages and additional spend")
    if network["offline_refilter_external_requests"] != 0:
        raise ValueError("Cached refilter must make zero external requests")
    plan["network_policy"] = network
    plan.setdefault("benchmarks", {
        "genuine_unique_candidates_min": 1000,
        "genuine_reconciled_reports_min": 3,
        "supported_closed_observed_episodes_per_report_min": 10,
        "cached_rows": 10000,
        "warmups": 5,
        "measured_iterations": 20,
        "cached_refilter_p95_target_ms": 500,
        "summary_page_size": 50,
        "summary_api_p95_target_ms": 750,
        "fresh_acquisition_objective_seconds": 300,
        "fresh_objective_is_guaranteed_sla": False,
        "forward_operational_min_signals": 2,
        "forward_operational_min_quotes": 2,
        "forward_operational_min_closed_positions": 1,
    })
    return plan
