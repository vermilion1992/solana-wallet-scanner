"""Independent product assertions from blueprint PDF pages 7–10 and 15.

Synthetic accounting examples test rules, never certify a live wallet.
"""
from copy import deepcopy

import pytest

from scanner.accounting import METHODOLOGY, analyze, evaluate_policy
from scanner.config import STRICT


def passing_metrics():
    # Boundary values come directly from the strict-policy table on PDF page 9.
    values = {
        "profit_sol": "5", "realised_roi_pct": "10", "median_roi_pct": "5",
        "win_rate_pct": "50", "median_hold_hours": "1", "completed_positions": "50",
        "completed_positions_90d": "100", "traded_mints": "20", "rapid_sale_pct": "10",
        "avg_buys": "1", "avg_sells": "1", "positive_weeks": "3",
        "largest_contribution_pct": "25", "economic_pnl_sol": "0.1",
    }
    return {name: {"value": value, "status": "known"} for name, value in values.items()}


def asset(kind, timestamp, quantity, amount=None, **extra):
    return {"kind": kind, "timestamp": timestamp, "mint": "synthetic-mint", "quantity_raw": quantity,
            "decimals": 0, "amount_sol": amount, "classification": "meme", "evidence": ["synthetic-evidence"], **extra}


def test_pdf_page_9_starting_strict_preset_is_preserved_literally():
    expected = {
        "window_days": 30, "verification_days": 90,
        "min_profit_sol": "5", "min_realised_roi_pct": "10", "min_median_roi_pct": "5",
        "min_win_rate_pct": "50", "max_win_rate_pct": "85",
        "min_hold_hours": "1", "max_hold_hours": "72",
        "min_positions": 50, "min_positions_90d": 100,
        "min_mints": 20, "max_mints": 100,
        "max_rapid_sale_pct": "10", "min_avg_buys": "1", "max_avg_buys": "2",
        "min_avg_sells": "1", "max_avg_sells": "3", "min_positive_weeks": 3,
        "max_contribution_pct": "25", "require_positive_economic_pnl": True,
    }
    assert {key: STRICT[key] for key in expected} == expected
    assert set(STRICT) - {"name", "version"} == set(expected)


def test_pdf_requires_all_eight_evidence_gates_even_when_every_numeric_filter_passes():
    expected_gates = {"evidence_history", "evidence_identity", "evidence_basis", "evidence_positions",
                      "evidence_fees", "evidence_classification", "evidence_valuation", "evidence_findings"}
    outcome = evaluate_policy(passing_metrics(), STRICT, evidence_verified=False)
    gates = {check["key"]: check["state"] for check in outcome["checks"] if check["key"].startswith("evidence_")}
    assert set(gates) == expected_gates
    assert set(gates.values()) == {"UNKNOWN"}
    assert all(check["state"] == "PASS" for check in outcome["checks"] if check["key"] not in expected_gates)
    assert outcome["policy"] == "UNRESOLVED"
    # A missing review gate cannot disappear merely because the other seven pass.
    evidence = {key.removeprefix("evidence_"): "PASS" for key in expected_gates if key != "evidence_findings"}
    outcome = evaluate_policy(passing_metrics(), STRICT, evidence_verified=evidence)
    assert outcome["policy"] == "UNRESOLVED"
    assert next(check for check in outcome["checks"] if check["key"] == "evidence_findings")["state"] == "UNKNOWN"


def test_known_preference_failure_remains_miss_while_other_evidence_is_unknown():
    metrics = passing_metrics()
    metrics["median_hold_hours"] = {"value": "0.7166666666666667", "status": "known"}
    metrics["profit_sol"] = {"value": None, "status": "unknown", "reason": "Earlier acquisition costs missing"}
    result = evaluate_policy(metrics, STRICT, evidence_verified=False)
    hold = next(check for check in result["checks"] if check["key"] == "median_hold_hours")
    assert result["policy"] == "MISS"
    assert hold["state"] == "FAIL" and "preference mismatch" in hold["reason"]
    assert any(check["state"] == "UNKNOWN" for check in result["checks"])
    assert "scam" not in str(result).lower() and "fraud" not in str(result).lower()


def test_unclassified_received_tokens_and_deposits_cannot_manufacture_meme_profit():
    events = [
        {"kind": "capital", "timestamp": "2026-01-02T00:00:00Z", "amount_sol": "100", "direction": "deposit"},
        asset("transfer_in", "2026-01-02T00:01:00Z", "100", classification="unknown", basis_sol=None),
        asset("sell", "2026-01-03T00:00:00Z", "100", "20", classification="unknown"),
    ]
    result = analyze(events, "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", history_complete=True)
    assert result["metrics"]["profit_sol"]["value"] is None
    assert result["metrics"]["traded_mints"]["value"] is None
    assert result["metrics"]["economic_pnl_sol"]["value"] is None
    assert result["positions"][0]["matched_basis_sol"] is None
    assert result["positions"][0]["pnl_sol"] is None
    assert evaluate_policy(result["metrics"], STRICT, evidence_verified=False)["policy"] != "MATCH"
    # No source is allowed to silently turn a new "spam" label into qualifying meme activity.
    invalid = deepcopy(events)
    invalid[1]["classification"] = "spam"
    with pytest.raises(ValueError, match="classification"):
        analyze(invalid, "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")


def test_small_residual_stays_open_without_fabricated_completed_holding_time():
    events = [asset("buy", "2026-01-01T00:00:00Z", "100", "1"),
              asset("sell", "2026-01-01T00:02:00Z", "99", "0.99")]
    result = analyze(events, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", history_complete=True)
    position = result["positions"][0]
    assert position["status"] == "open" and position["quantity_raw"] == "1"
    assert position["end"] is None and position["hold_hours"] is None
    assert result["metrics"]["completed_positions"]["value"] == "0"
    assert result["metrics"]["median_hold_hours"]["value"] is None
    assert position["sold_90_pct_hours"] == position["first_sale_hours"]


def test_late_final_exit_does_not_hide_early_majority_exit():
    events = [asset("buy", "2026-01-01T00:00:00Z", "100", "1"),
              asset("sell", "2026-01-01T00:02:00Z", "90", "1"),
              asset("sell", "2026-01-01T06:00:00Z", "10", "0.2")]
    result = analyze(events, "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z", history_complete=True)
    position = result["positions"][0]
    assert result["metrics"]["median_hold_hours"]["value"] == "6"
    assert result["metrics"]["rapid_sale_pct"]["value"] == "100"
    assert position["sold_90_pct_hours"] == position["first_sale_hours"]
    assert position["sold_90_pct_hours"] != position["hold_hours"]
    policy = evaluate_policy(result["metrics"], STRICT, evidence_verified=False)
    rapid = next(check for check in policy["checks"] if check["key"] == "rapid_sale_pct")
    assert rapid["state"] == "FAIL" and "preference mismatch" in rapid["reason"]
    assert policy["policy"] == "MISS"


def passing_report():
    from scanner.history_evidence import VERSION as HISTORY_METHODOLOGY
    from scanner.position_evidence import VERSION as POSITION_METHODOLOGY
    policy = evaluate_policy(passing_metrics(), STRICT, evidence_verified=True)
    return {"source": "live", "methodology": METHODOLOGY, "evidence_status": "verified", "preset": deepcopy(STRICT),
            "window": {"start": "2026-01-02T00:00:00Z", "end": "2026-02-01T00:00:00Z"},
            "coverage": {"history_evidence": {"version": HISTORY_METHODOLOGY}, "position_evidence": {"version": POSITION_METHODOLOGY}},
            "metrics": passing_metrics(), **policy}


@pytest.mark.parametrize("change", [
    {"source": "demo"}, {"preview": True}, {"evidence_status": "partial"}, {"policy": "MISS"},
])
def test_qualified_discovery_cannot_promote_demo_preview_or_partial_evidence(change):
    from scanner.copy_review import qualify_report
    report = {**passing_report(), **change}
    result = qualify_report(report)
    assert result["qualified"] is False
    assert report["source"] == change.get("source", "live")


def test_qualification_requires_each_mandatory_filter_and_review_gate():
    from scanner.copy_review import qualify_report
    assert qualify_report(passing_report())["qualified"] is True
    for missing in ("evidence_findings", "rapid_sale_pct", "economic_pnl_sol"):
        report = passing_report()
        report["checks"] = [check for check in report["checks"] if check["key"] != missing]
        assert qualify_report(report)["qualified"] is False
    report = passing_report()
    report["metrics"]["profit_sol"] = {"value": None, "status": "unknown"}
    assert qualify_report(report)["qualified"] is False


def test_copy_review_reports_early_majority_exit_without_inventing_exploitation_or_policy_failure():
    from scanner.copy_review import review_copy_behavior
    from scanner.research import summarize_research
    events = [asset("buy", "2026-01-01T00:00:00Z", "100", "1"),
              asset("sell", "2026-01-01T00:02:00Z", "90", "1"),
              asset("sell", "2026-01-01T06:00:00Z", "10", "0.2")]
    window = ("2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")
    accounting = analyze(events, *window, history_complete=True)
    report = {"source": "live", "preset": deepcopy(STRICT), "evidence_status": "partial",
              "research": summarize_research(events, *window), **accounting,
              **evaluate_policy(accounting["metrics"], STRICT, evidence_verified=False)}
    original = deepcopy(report)
    review = review_copy_behavior(report)
    long_tail = next(finding for finding in review["findings"] if finding["key"] == "long_tail_hold")
    assert long_tail["conditional"] is True
    assert long_tail["actual"]["final_hold_hours"] == "6"
    assert long_tail["actual"]["exit_90_hours"] == accounting["positions"][0]["sold_90_pct_hours"]
    assert review["checks"]["follower_exploitation"]["state"] == "UNKNOWN"
    assert "follower_exploitation" in review["unknown_checks"]
    assert "scam" not in long_tail["title"].lower() and "fraud" not in long_tail["title"].lower()
    assert report == original  # An observation must not rewrite financial policy or source evidence.


def test_short_holding_preference_miss_does_not_become_a_misconduct_finding():
    from scanner.copy_review import review_copy_behavior
    report = passing_report()
    report["metrics"]["median_hold_hours"] = {"value": "0.7166666666666667", "status": "known"}
    report.update(evaluate_policy(report["metrics"], STRICT, evidence_verified=False))
    review = review_copy_behavior(report)
    assert report["policy"] == "MISS"
    assert review["checks"]["follower_exploitation"]["state"] == "UNKNOWN"
    assert not any(finding["key"] == "long_tail_hold" for finding in review["findings"])


def test_invalid_wallet_review_does_not_hide_unreviewed_token_concentration():
    from scanner.copy_review import review_copy_behavior
    primary = "a" * 64
    report = {"source": "live", "evidence_status": "partial", "evidence": [{"hash": primary}],
              "reviewed_copy_checks": {"holder_concentration": {"state": "UNKNOWN"}},
              "token_risk": [
                  {"mint": "reviewed-mint", "gates": {"holder_concentration": {
                      "state": "PASS", "reviewed": True, "primary_evidence": True, "evidence": [primary]}}},
                  {"mint": "unreviewed-mint", "gates": {"holder_concentration": {"state": "UNKNOWN"}}},
              ]}
    review = review_copy_behavior(report)
    assert review["checks"]["holder_concentration"]["state"] == "UNKNOWN"
    assert "holder_concentration" in review["unknown_checks"]


def test_exact_five_minute_majority_exit_matches_pdf_inclusive_boundary():
    from scanner.copy_review import review_copy_behavior
    from scanner.research import summarize_research
    events = [asset("buy", "2026-01-01T00:00:00Z", "100", "1"),
              asset("sell", "2026-01-01T00:05:00Z", "90", "1"),
              asset("sell", "2026-01-01T06:00:00Z", "10", "0.2")]
    research = summarize_research(events, "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")
    review = review_copy_behavior({"source": "live", "evidence_status": "partial", "preset": deepcopy(STRICT), "research": research})
    assert any(finding["key"] == "long_tail_hold" for finding in review["findings"])
    assert review["checks"]["rapid_first_sales"]["actual"]["observed_pct"] == "100"
