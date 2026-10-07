"""Coverage status and qualification level are different fields.

One function produces both the per-wallet table and the per-level counts.
Do not write one surface from a different naming scheme than another.
"""
from __future__ import annotations

from scanner.mass_search.qualification_gates import (
    CROSS_CURRENCY_SENSITIVITY,
    SENSITIVITY_NOT_ESTABLISHED,
)
from scanner.mass_search.research_profile import (
    RESEARCH_SCREEN_DEFAULTS,
    independently_audited,
    qualification_level,
    sensitivity_sign_flips,
)

QUALIFICATION_LEVELS = (
    "insufficient_evidence",
    "conditional_captured_lot_result",
    "provisional_research_lead",
    "stronger_research_shortlist",
)

COVERAGE_STATUSES = (
    "provisional_eligible",
    "coverage_eligibility_pending_reassessment",
    "watchlist_incomplete_evidence",
    "coverage_blocked",
    "blocked_unknown_denominator",
)

MIN_SAMPLE_POSITIONS = int(RESEARCH_SCREEN_DEFAULTS["min_sample_positions"])


def _level_name(value):
    if isinstance(value, dict):
        return value.get("level") or "insufficient_evidence"
    return value or "insufficient_evidence"


def _coverage_name(value):
    if isinstance(value, dict):
        return value.get("status") or value.get("coverage_status") or "blocked_unknown_denominator"
    return value or "blocked_unknown_denominator"


def _empty_level_counts():
    return {name: 0 for name in QUALIFICATION_LEVELS}


def _empty_coverage_counts():
    return {name: 0 for name in COVERAGE_STATUSES}


def blocking_reason(report, profile, *, coverage_status, level):
    """Explicit why this wallet is not a stronger/provisional lead."""
    completed = int(profile.get("completed_known_cost_positions") or 0)
    open_lots = int(profile.get("open_buys_in_sample") or 0)
    unresolved = int(profile.get("unresolved_basis_sales") or 0)
    reasons = []
    level_reason = (level or {}).get("reason") or (level or {}).get("blocker") or ""
    if "gt_25_economic_trades_in_one_day" in str(level_reason):
        reasons.append(str(level_reason))
    if completed < 1:
        reasons.append("0 completed episodes")
    elif completed < MIN_SAMPLE_POSITIONS:
        noun = "episode" if completed == 1 else "episodes"
        reasons.append(f"{completed} completed {noun} < min_sample {MIN_SAMPLE_POSITIONS}")
    if open_lots:
        reasons.append(f"{open_lots} open lots")
    if unresolved:
        noun = "sale" if unresolved == 1 else "sales"
        reasons.append(f"{unresolved} unresolved-basis {noun}")
    sensitivity = (level or {}).get("sensitivity_sign_flip") or sensitivity_sign_flips(report, profile)
    if sensitivity == CROSS_CURRENCY_SENSITIVITY:
        reasons.append(CROSS_CURRENCY_SENSITIVITY)
    elif sensitivity == SENSITIVITY_NOT_ESTABLISHED:
        reasons.append(SENSITIVITY_NOT_ESTABLISHED)
    elif sensitivity:
        reasons.append("unresolved adjacent debits flip the sensitivity net sign")
    gate = (level or {}).get("coverage_gate") or {}
    if gate and not gate.get("passed"):
        if "coverage gate requires count AND value" not in "; ".join(reasons):
            reasons.append(gate.get("reason") or "coverage gate requires count AND value")
    genuine = (report or {}).get("corpus_kind") == "GENUINE_REPLAY"
    if completed >= 1 and genuine and not independently_audited(report, profile):
        reasons.append("not independently audited")
    if coverage_status == "coverage_blocked":
        reasons.append("coverage_blocked")
    elif coverage_status == "watchlist_incomplete_evidence":
        reasons.append("watchlist_incomplete_evidence")
    elif coverage_status == "blocked_unknown_denominator":
        reasons.append("blocked_unknown_denominator")
    elif coverage_status == "coverage_eligibility_pending_reassessment":
        if not any("unresolved-basis" in item or "sensitivity" in item for item in reasons):
            reasons.append("coverage_eligibility_pending_reassessment")
    if _level_name(level) in ("provisional_research_lead", "stronger_research_shortlist"):
        return None
    if not reasons:
        reasons.append("does not meet provisional_research_lead gates")
    return "; ".join(reasons)


def wallet_status_fields(report, profile=None):
    """Same names on every surface: qualification_level, coverage_status, blocking_reason."""
    from scanner.mass_search.workflow import coverage_eligibility

    profile = profile or (report or {}).get("research_profile") or {}
    level = qualification_level(report, profile)
    judged = coverage_eligibility(report, profile)
    coverage = judged.get("status")
    reason = blocking_reason(report, profile, coverage_status=coverage, level=level)
    coverage_display = coverage
    if coverage == "provisional_eligible":
        coverage_display = "Coverage gate eligible; not a research lead."
    return {
        "qualification_level": _level_name(level),
        "qualification_level_detail": level if isinstance(level, dict) else {"level": _level_name(level)},
        "coverage_status": coverage,
        "coverage_status_display": coverage_display,
        "coverage_status_detail": judged,
        "blocking_reason": reason,
    }


def research_label_tables(wallet_rows):
    """One source of truth: per-wallet table and per-level counts from the same rows.

    Each row must already carry qualification_level and coverage_status (strings or
    dicts). Counts are a histogram of those exact fields — they cannot diverge.
    """
    wallets = []
    level_counts = _empty_level_counts()
    coverage_counts = _empty_coverage_counts()
    for raw in wallet_rows or []:
        level = _level_name(raw.get("qualification_level"))
        coverage = _coverage_name(raw.get("coverage_status"))
        if level not in level_counts:
            level_counts[level] = 0
        if coverage not in coverage_counts:
            coverage_counts[coverage] = 0
        row = dict(raw)
        row["qualification_level"] = level
        row["coverage_status"] = coverage
        if "blocking_reason" not in row:
            row["blocking_reason"] = raw.get("blocking_reason")
        wallets.append(row)
        level_counts[level] += 1
        coverage_counts[coverage] += 1
    return {
        "kind": "research-label-tables-v1",
        "wallets": wallets,
        "qualification_level_counts": level_counts,
        "coverage_status_counts": coverage_counts,
        "note": (
            "coverage_status (item 12) is not qualification_level (item 11). "
            "An9s can be coverage_status=provisional_eligible and "
            "qualification_level=conditional_captured_lot_result at the same time."
        ),
        "PRODUCT_READY": False,
    }


def tables_from_reports(reports):
    """Build both tables from replayed reports. Used by RESULT.md / tests / dump."""
    rows = []
    for report in reports:
        profile = (report or {}).get("research_profile") or {}
        fields = wallet_status_fields(report, profile)
        rows.append({
            "address": report.get("address"),
            "qualification_level": fields["qualification_level"],
            "coverage_status": fields["coverage_status"],
            "blocking_reason": fields["blocking_reason"],
            "completed_known_cost_positions": int(profile.get("completed_known_cost_positions") or 0),
            "open_buys_in_sample": int(profile.get("open_buys_in_sample") or 0),
            "unresolved_basis_sales": int(profile.get("unresolved_basis_sales") or 0),
            "scoped_pnl": profile.get("scoped_pnl"),
            "scoped_pnl_unit": profile.get("scoped_pnl_unit"),
            "matched_fragment_pnl": profile.get("matched_fragment_pnl"),
            "matched_fragment_unit": profile.get("matched_fragment_unit"),
        })
    return research_label_tables(rows)
