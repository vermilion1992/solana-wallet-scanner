"""Four-outcome stage decisions. Unknown is never zero, fail, or pass."""
from __future__ import annotations

import hashlib
from decimal import Decimal

from .metrics import compare_to_threshold, format_decimal
from .plan import MASS_RESEARCH_PLAN_NAME

STAGES = ("triage", "behaviour", "reconstruct", "forward_select")
OUTCOMES = ("PROMOTED", "REJECTED", "DEFERRED", "PENDING")
DECISION_VERSION = "mass-search-decision-v1"


def conserve_counts(input_count, promoted, rejected, deferred, pending):
    if type(input_count) is not int or input_count < 0:
        raise ValueError("Stage input must be a non-negative integer")
    parts = (promoted, rejected, deferred, pending)
    if any(type(value) is not int or value < 0 for value in parts):
        raise ValueError("Stage counts must be non-negative integers")
    if input_count != sum(parts):
        raise ValueError("Stage counts do not conserve")
    return {
        "input": input_count,
        "promoted": promoted,
        "rejected": rejected,
        "deferred": deferred,
        "pending": pending,
        "next_stage_input": promoted,
        "run_complete": pending == 0,
    }


def candidate_id(chain, address):
    return f"{chain}:{address}"


def _metric(metrics, key):
    return metrics.get(key) if isinstance(metrics, dict) else None


def evaluate_triage(candidate, metrics, plan, *, pending=False):
    if pending:
        return _decision("triage", candidate, "PENDING", ["not_evaluated"], plan, next_capability="provider_summary")
    ranking = plan["preliminary_ranking"]
    pnl = _metric(metrics, "provider_realized_pnl")
    trades = _metric(metrics, "provider_trade_count")
    active = _metric(metrics, "provider_last_active_days")
    reasons = []
    if pnl is None or pnl.get("state") in ("UNKNOWN", "CONFLICT", "STALE"):
        return _decision("triage", candidate, ranking["missing_metric_outcome"], ["missing_reported_pnl"], plan,
                         next_capability="provider_summary")
    if pnl.get("unit") == "USD":
        reasons.append("provider_pnl_usd_not_sol")
        strict = compare_to_threshold(pnl, plan.get("strict_min_profit_sol", "5"), "SOL")
        if strict["state"] != "KNOWN":
            reasons.append("usd_not_compared_to_sol_strict")
    if pnl.get("state") == "KNOWN":
        value = Decimal(pnl["value"])
        if ranking["reject_known_negative_reported_pnl"] and value < 0:
            return _decision("triage", candidate, "REJECTED", ["known_negative_reported_pnl", *reasons], plan)
        if value == 0:
            reasons.append("known_zero_reported_pnl")
        elif value < 0:
            reasons.append("known_negative_reported_pnl_ranked")
    if trades and trades.get("state") == "KNOWN":
        reasons.append("provider_trade_count_queue_priority_only")
        if int(Decimal(trades["value"])) < ranking["prefer_provider_trade_count_at_least"]:
            reasons.append("low_provider_trade_count_not_strict_fail")
    elif ranking["hard_fail_never_inferred_from_incompatible_proxy"]:
        reasons.append("provider_trade_count_not_completed_positions")
    if active and active.get("state") == "KNOWN":
        if Decimal(active["value"]) > ranking["prefer_recent_activity_within_days"]:
            reasons.append("stale_provider_activity_ranked")
    return _decision("triage", candidate, "PROMOTED", reasons or ["preliminary_summary_present"], plan,
                     next_capability="behaviour_history")


def evaluate_behaviour(candidate, metrics, plan, *, pending=False, budget_deferred=False):
    if pending:
        return _decision("behaviour", candidate, "PENDING", ["not_evaluated"], plan, next_capability="behaviour_history")
    if budget_deferred:
        return _decision("behaviour", candidate, "DEFERRED", ["budget_stage_cap"], plan, next_capability="behaviour_history")
    exit_metric = _metric(metrics, "material_exit_t90_seconds")
    if exit_metric is None or exit_metric.get("state") in ("UNKNOWN", "CONFLICT", "STALE"):
        return _decision("behaviour", candidate, "DEFERRED", ["missing_material_exit"], plan,
                         next_capability="behaviour_history")
    reasons = ["material_exit_observed"]
    final_hold = _metric(metrics, "final_hold_seconds")
    if final_hold and final_hold.get("state") == "KNOWN" and exit_metric.get("state") == "KNOWN":
        if Decimal(exit_metric["value"]) <= 300 and Decimal(final_hold["value"]) >= 3600:
            reasons.append("fast_material_exit_with_long_final_hold")
    return _decision("behaviour", candidate, "PROMOTED", reasons, plan, next_capability="targeted_history")


def evaluate_reconstruct(candidate, metrics, plan, *, pending=False, budget_deferred=False, report=None):
    if pending:
        return _decision("reconstruct", candidate, "PENDING", ["not_evaluated"], plan, next_capability="targeted_history")
    if budget_deferred:
        return _decision("reconstruct", candidate, "DEFERRED", ["budget_stage_cap"], plan, next_capability="targeted_history")
    pnl = _metric(metrics, "subset_realised_pnl_sol")
    hold = _metric(metrics, "median_observed_hold_hours")
    if report is None and (pnl is None or hold is None):
        return _decision("reconstruct", candidate, "DEFERRED", ["missing_reconstruction"], plan,
                         next_capability="targeted_history")
    reasons = ["subset_report_persisted"]
    if pnl and pnl.get("state") == "KNOWN" and Decimal(pnl["value"]) < 0:
        reasons.append("loss_or_nonqualifying_control")
    if hold and hold.get("state") == "UNKNOWN":
        reasons.append("median_hold_unknown")
    return _decision("reconstruct", candidate, "PROMOTED", reasons, plan, next_capability="forward_observation")


def evaluate_forward_select(candidate, metrics, plan, *, pending=False, budget_deferred=False):
    if pending:
        return _decision("forward_select", candidate, "PENDING", ["not_evaluated"], plan,
                         next_capability="quote_observation")
    if budget_deferred:
        return _decision("forward_select", candidate, "DEFERRED", ["budget_stage_cap"], plan,
                         next_capability="quote_observation")
    exit_metric = _metric(metrics, "material_exit_t90_seconds")
    pnl = _metric(metrics, "provider_realized_pnl")
    if exit_metric is None or exit_metric.get("state") != "KNOWN":
        reasons = ["unknown_exit_blocks_forward"]
        if pnl and pnl.get("state") == "KNOWN":
            reasons.append("high_reported_pnl_cannot_override_unknown_exit")
        return _decision("forward_select", candidate, "DEFERRED", reasons, plan, next_capability="behaviour_history")
    return _decision("forward_select", candidate, "PROMOTED", ["forward_prerequisites_present"], plan,
                     next_capability="quote_observation")


def apply_stage_cap(decisions, cap, *, seed="mass-research-v1"):
    """Eligible promotions beyond the cap become budget deferrals, not rejects."""
    eligible = [row for row in decisions if row["result"] == "PROMOTED"]
    ranked = sorted(eligible, key=lambda row: row["_priority"])
    kept = {row["candidate_id"] for row in ranked[:cap]}
    revised = []
    for row in decisions:
        if row["result"] == "PROMOTED" and row["candidate_id"] not in kept:
            updated = dict(row)
            updated["result"] = "DEFERRED"
            updated["reason_codes"] = list(row["reason_codes"]) + ["budget_stage_cap"]
            updated.pop("_priority", None)
            revised.append(updated)
        else:
            cleaned = dict(row)
            cleaned.pop("_priority", None)
            revised.append(cleaned)
    return revised


def priority_tuple(candidate, metrics, *, cached=False):
    """cached -> decisive inexpensive signal -> research priority -> stable id."""
    pnl = _metric(metrics, "provider_realized_pnl")
    trades = _metric(metrics, "provider_trade_count")
    pnl_rank = 0
    if pnl and pnl.get("state") == "KNOWN" and pnl.get("unit") == "USD":
        pnl_rank = int(Decimal(pnl["value"]) * 100)
    trade_rank = 0
    if trades and trades.get("state") == "KNOWN":
        trade_rank = int(Decimal(trades["value"]))
    decisive = 1 if pnl and pnl.get("state") == "KNOWN" else 0
    return (0 if cached else 1, 0 if decisive else 1, -pnl_rank, -trade_rank, candidate["candidate_id"])


def audit_sample(rejected_or_deferred, *, share_pct, seed, authorised_slots):
    if authorised_slots < 1 or not rejected_or_deferred:
        return []
    raw = (Decimal(str(share_pct)) / Decimal("100")) * authorised_slots
    slots = int(raw.to_integral_value(rounding="ROUND_DOWN"))
    if slots < 1:
        return []
    ordered = sorted(rejected_or_deferred, key=lambda row: hashlib.sha256(f"{seed}:{row['candidate_id']}:{','.join(row['reason_codes'])}".encode()).hexdigest())
    return ordered[:slots]


def _decision(stage_id, candidate, result, reasons, plan, next_capability=None):
    if result not in OUTCOMES:
        raise ValueError("Unsupported decision result")
    if stage_id not in STAGES:
        raise ValueError("Unsupported stage")
    return {
        "stage_id": stage_id,
        "candidate_id": candidate["candidate_id"],
        "result": result,
        "reason_codes": list(reasons),
        "policy_version": MASS_RESEARCH_PLAN_NAME,
        "metric_versions": DECISION_VERSION,
        "next_capability": next_capability,
        "_priority": candidate.get("_priority") or (0, 0, 0, 0, candidate["candidate_id"]),
    }
