"""Qualification never converts sampled observations into a profitable/safe label."""
from copy import deepcopy
from decimal import Decimal, localcontext
import unittest

from scanner.config import STRICT
from scanner.accounting import METHODOLOGY
from scanner.history_evidence import VERSION as HISTORY_METHODOLOGY
from scanner.position_evidence import VERSION as POSITION_METHODOLOGY
from scanner.copy_review import EVIDENCE_KEYS, METRIC_KEYS, qualify_report, review_copy_behavior


HASH = "a" * 64


def report():
    return {"id": "report-1", "source": "live", "methodology": METHODOLOGY, "policy": "MATCH", "evidence_status": "verified", "preset": dict(STRICT),
            "window": {"start": "2026-09-02T00:00:00+00:00", "end": "2026-10-02T00:00:00+00:00"},
            "metrics": {"profit_sol": {"status": "known", "value": "12.50"}},
            "coverage": {"history_evidence": {"version": HISTORY_METHODOLOGY}, "position_evidence": {"version": POSITION_METHODOLOGY}},
            "checks": [{"key": key, "state": "PASS", "actual": "12.50" if key == "profit_sol" else "1", "reason": "Fixture"}
                       for key in EVIDENCE_KEYS + METRIC_KEYS + ("economic_pnl_sol",)],
            "evidence": [{"hash": HASH, "kind": "transaction"}]}


def episode(hold="2", exit90="0.05", first="0.01"):
    return {"id": "mint:1", "mint": "public-mint", "status": "closed", "in_window": True,
            "hold_hours": hold, "sold_90_pct_hours": exit90, "first_sale_hours": first,
            "conditional": True, "evidence": [HASH]}


def observed_report(episodes=None):
    value = report()
    value.update(policy="UNRESOLVED", evidence_status="partial", events=[])
    value["research"] = {"episodes": episodes if episodes is not None else [episode()], "chronology_unknown": False,
                         "conditional_observed_lot_profit_sol": "999999", "unresolved_basis_sales": 2,
                         "observed_unmatched_sales": 1, "evidence": [HASH]}
    return value


class QualificationTests(unittest.TestCase):
    def test_live_saved_match_requires_complete_explicit_passes_and_known_strict_profit(self):
        value = report()
        original = deepcopy(value)
        result = qualify_report(value)
        self.assertTrue(result["qualified"])
        self.assertEqual(result["profit_sol"], "12.5")
        self.assertEqual(result["preset_version"], "strict-v0.3")
        self.assertEqual(result["preset_snapshot"], STRICT)
        self.assertEqual(result["report_id"], "report-1")
        self.assertEqual(result["unknown_checks"], [])
        self.assertEqual(result["failed_checks"], [])
        self.assertEqual(value, original)

    def test_demo_synthetic_and_preview_matches_cannot_qualify(self):
        for changes in ({"source": "demo"}, {"source": "synthetic"}, {"preview": True}, {"preview": "false"}):
            with self.subTest(changes=changes):
                value = report()
                value.update(changes)
                self.assertFalse(qualify_report(value)["qualified"])

    def test_missing_repeated_unknown_and_failed_checks_cannot_qualify(self):
        for modification in ("empty", "missing", "duplicate", "unknown", "failed", "malformed"):
            with self.subTest(modification=modification):
                value = report()
                if modification == "empty":
                    value["checks"] = []
                elif modification == "missing":
                    value["checks"] = [check for check in value["checks"] if check["key"] != "completed_positions_90d"]
                elif modification == "duplicate":
                    value["checks"].append(deepcopy(value["checks"][0]))
                elif modification == "unknown":
                    value["checks"][0]["state"] = "UNKNOWN"
                elif modification == "failed":
                    value["checks"][0]["state"] = "FAIL"
                else:
                    value["checks"].append(None)
                result = qualify_report(value)
                self.assertFalse(result["qualified"])
                self.assertTrue(result["failed_checks"] or result["unknown_checks"])

    def test_known_miss_and_unknown_evidence_remain_separate_and_visible(self):
        value = report()
        value["policy"] = "MISS"
        value["checks"][0].update(state="UNKNOWN", reason="History incomplete")
        value["checks"][8].update(state="FAIL", actual="1", reason="Preference mismatch")
        result = qualify_report(value)
        self.assertEqual(result["financial_policy"], "MISS")
        self.assertEqual(result["failed_checks"][0]["reason"], "Preference mismatch")
        self.assertEqual(result["unknown_checks"][0]["reason"], "History incomplete")

    def test_conditional_profit_never_substitutes_for_unknown_strict_profit(self):
        value = report()
        value["metrics"]["profit_sol"].update(status="unknown", value=None)
        value["research"] = {"conditional_observed_lot_profit_sol": "1000000", "observed_profit_sol": "50000"}
        result = qualify_report(value)
        self.assertFalse(result["qualified"])
        self.assertIsNone(result["profit_sol"])

    def test_partial_stale_and_invalid_financial_values_cannot_qualify(self):
        for evidence in ("partial", "stale", "unknown"):
            value = report()
            value["evidence_status"] = evidence
            self.assertFalse(qualify_report(value)["qualified"])
        for value in (1.25, True, "NaN", "Infinity", None):
            candidate = report()
            candidate["metrics"]["profit_sol"]["value"] = value
            result = qualify_report(candidate)
            self.assertFalse(result["qualified"])
            self.assertIsNone(result["profit_sol"])

    def test_legacy_missing_fields_return_unknown_and_cannot_qualify(self):
        result = qualify_report({})
        self.assertFalse(result["qualified"])
        self.assertEqual(result["financial_policy"], "UNRESOLVED")
        self.assertEqual(result["evidence_status"], "unknown")
        self.assertEqual(len(result["unknown_checks"]), 26)

    def test_current_history_cannot_endorse_old_or_missing_position_method(self):
        for position in ({}, {"version": "account-position-evidence-v1"}, {"version": "account-position-evidence-v2"}, {"version": "account-position-evidence-v3"}, {"version": "account-position-evidence-v4"}, {"version": "future-unreviewed"}):
            with self.subTest(position=position):
                value = report()
                value["coverage"]["position_evidence"] = position
                original = deepcopy(value)
                result = qualify_report(value)
                self.assertFalse(result["qualified"])
                self.assertEqual(value, original)
                self.assertEqual(next(check for check in result["unknown_checks"] if check["key"] == "position_methodology")["expected"], POSITION_METHODOLOGY)

    def test_old_or_absent_account_receipt_method_cannot_qualify_saved_pass_checks(self):
        for history in ({}, {"version": "history-evidence-v1"}, {"version": "history-evidence-v3"}, {"version": "history-evidence-v4"}, {"version": "history-evidence-v5"}, {"version": "future-unreviewed"}):
            with self.subTest(history=history):
                value = report()
                value["coverage"]["history_evidence"] = history
                original = deepcopy(value)
                result = qualify_report(value)
                self.assertFalse(result["qualified"])
                self.assertEqual(value, original)
                self.assertEqual(next(check for check in result["unknown_checks"] if check["key"] == "history_methodology")["expected"], HISTORY_METHODOLOGY)

    def test_old_fee_methodology_requires_rebuild_even_when_saved_checks_all_pass(self):
        for methodology in (None, "fifo-v1", "future-unreviewed"):
            with self.subTest(methodology=methodology):
                value = report()
                value["methodology"] = methodology
                result = qualify_report(value)
                self.assertFalse(result["qualified"])
                self.assertIn("Rebuild", result["reason"])
                self.assertEqual(next(check for check in result["unknown_checks"] if check["key"] == "methodology")["expected"], METHODOLOGY)

    def test_saved_relaxed_filter_snapshot_is_retained_without_claiming_default_strict_match(self):
        value = report()
        value["preset"]["min_profit_sol"] = "1"
        value["preset"]["require_positive_economic_pnl"] = False
        value["checks"] = [check for check in value["checks"] if check["key"] != "economic_pnl_sol"]
        result = qualify_report(value)
        self.assertTrue(result["qualified"])
        self.assertEqual(result["preset_snapshot"]["min_profit_sol"], "1")
        self.assertIn("saved filters", result["reason"])


class CopyBehaviorTests(unittest.TestCase):
    def test_early_ninety_percent_exit_with_long_final_hold_is_factual_conditional_warning(self):
        value = observed_report()
        original = deepcopy(value)
        result = review_copy_behavior(value)
        finding = next(item for item in result["findings"] if item.get("key") == "long_tail_hold")
        self.assertEqual(finding["title"], "Remainder extends final holding time")
        self.assertEqual(finding["actual"]["final_hold_hours"], "2")
        self.assertEqual(finding["actual"]["exit_90_hours"], "0.05")
        self.assertEqual(finding["evidence"], [HASH])
        self.assertTrue(finding["conditional"])
        self.assertEqual(result["checks"]["follower_exploitation"]["state"], "UNKNOWN")
        self.assertNotIn("safe", result)
        self.assertNotIn("score", result)
        self.assertEqual(value, original)

    def test_short_final_hold_and_saved_custom_minimum_do_not_trigger_long_tail_warning(self):
        for minimum, final in (("1", "0.5"), ("3", "2")):
            value = observed_report([episode(hold=final)])
            value["preset"]["min_hold_hours"] = minimum
            result = review_copy_behavior(value)
            self.assertFalse(any(item.get("key") == "long_tail_hold" for item in result["findings"]))
        value = observed_report()
        value["preset"]["min_hold_hours"] = "0.5"
        self.assertEqual(review_copy_behavior(value)["findings"][0]["actual"]["threshold_hours"], "0.5")

    def test_five_minute_boundary_uses_accounting_precision_and_rapid_share_is_only_observational(self):
        with localcontext() as context:
            context.prec = 192
            boundary = format(Decimal(1) / Decimal(12), "f")
        value = observed_report([episode(exit90=boundary, first=boundary)])
        result = review_copy_behavior(value)
        rapid = result["checks"]["rapid_first_sales"]
        self.assertEqual(rapid["state"], "OBSERVED")
        self.assertEqual(rapid["comparison"], "ABOVE_PRESET")
        self.assertEqual(rapid["actual"]["observed_pct"], "100")
        self.assertEqual(result["checks"]["long_tail_holds"]["actual"]["long_tail_episodes"], 1)
        self.assertTrue(all(item["state"] != "FAIL" for item in result["checks"].values()))

    def test_missing_first_sale_or_unknown_chronology_keeps_affected_diagnostics_unknown(self):
        value = observed_report([episode(first=None)])
        value["research"]["conditional_rapid_sale_pct"] = "100"
        self.assertEqual(review_copy_behavior(value)["checks"]["rapid_first_sales"]["state"], "UNKNOWN")
        value = observed_report()
        value["research"]["chronology_unknown"] = True
        result = review_copy_behavior(value)
        self.assertEqual(result["checks"]["rapid_first_sales"]["state"], "UNKNOWN")
        self.assertEqual(result["checks"]["long_tail_holds"]["state"], "UNKNOWN")
        self.assertFalse(any(item.get("key") == "long_tail_hold" for item in result["findings"]))

    def test_unmatched_cost_and_incoming_capital_counts_do_not_become_gifted_profit_or_intent(self):
        value = observed_report()
        value["events"] = [{"kind": "transfer_in", "mint": "mint1", "basis_sol": None, "evidence": [HASH]},
                           {"kind": "transfer_in", "mint": "mint2", "basis_sol": "1", "evidence": [HASH]},
                           {"kind": "transfer_out", "evidence": [HASH]}]
        result = review_copy_behavior(value)
        self.assertEqual(result["checks"]["unmatched_basis"]["actual"], {"unresolved_basis_sales": 2, "observed_unmatched_sales": 1})
        self.assertEqual(result["checks"]["incoming_transfers"]["actual"], {"observed_transfers": 2, "without_supplied_basis": 1})
        self.assertTrue(all(result["checks"][key]["state"] == "UNKNOWN" for key in ("creator_links", "follower_exploitation", "liquidity_withdrawal", "holder_concentration")))

    def test_verified_strict_positions_are_preferred_over_conditional_research(self):
        value = report()
        value["positions"] = [episode(hold="4")]
        value["positions"][0].pop("conditional")
        value["research"] = {"episodes": [episode(hold="20")]}
        result = review_copy_behavior(value)
        self.assertFalse(result["conditional"])
        finding = next(item for item in result["findings"] if item["key"] == "long_tail_hold")
        self.assertEqual(finding["actual"]["final_hold_hours"], "4")
        self.assertFalse(finding["conditional"])

    def test_current_token_capability_flags_are_retained_without_copy_safety_claim(self):
        value = observed_report()
        flag = {"key": "freeze_authority", "state": "FAIL", "severity": "warning", "title": "Freeze authority", "detail": "Authority active", "evidence": [HASH]}
        value["token_risk"] = [{"mint": "mint1", "findings": [flag]}]
        result = review_copy_behavior(value)
        self.assertEqual(result["checks"]["current_token_findings"]["state"], "FLAGGED")
        copied = next(item for item in result["findings"] if item["key"] == "freeze_authority")
        self.assertEqual(copied["detail"], "Authority active")
        self.assertEqual(copied["mint"], "mint1")
        self.assertEqual(result["checks"]["follower_exploitation"]["state"], "UNKNOWN")

    def test_all_unknown_token_controls_do_not_become_warning_cards_but_remain_visible(self):
        value = observed_report([])
        controls = ["mint_identity", "mint_authority", "freeze_authority", "token_extensions", "current_liquidity",
                    "liquidity_control", "holder_concentration", "creator_links", "historical_sellability"]
        value["token_risk"] = [{"mint": "mint" + str(number),
                                "gates": {key: {"state": "UNKNOWN", "detail": "Evidence needed", "evidence": [HASH]} for key in controls},
                                "findings": [{"key": key, "state": "UNKNOWN", "severity": "info", "title": key, "detail": "Evidence needed", "evidence": [HASH]} for key in controls]}
                               for number in range(3)]
        original = deepcopy(value)
        result = review_copy_behavior(value)
        self.assertEqual(result["findings"], [])
        current = result["checks"]["current_token_findings"]
        self.assertEqual(current["state"], "UNKNOWN")
        self.assertEqual(current["actual"]["unknown_control_findings"], 27)
        self.assertEqual(current["actual"]["flagged_findings"], 0)
        self.assertIn("27 control findings remain unresolved", current["detail"])
        self.assertIn("current_token_findings", result["unknown_checks"])
        self.assertEqual(value, original)

    def test_evidenced_known_gate_failure_survives_unknowns_without_duplicate_findings(self):
        value = observed_report([])
        flag = {"key": "freeze_authority", "state": "FAIL", "severity": "warning", "title": "Freeze authority", "detail": "Active freeze authority", "evidence": [HASH]}
        value["token_risk"] = [{"mint": "mint1", "gates": {"freeze_authority": {"state": "FAIL", "detail": flag["detail"], "evidence": [HASH]},
                                                               "creator_links": {"state": "UNKNOWN"}},
                                "findings": [flag, {"key": "creator_links", "state": "UNKNOWN", "detail": "Not investigated", "evidence": [HASH]}]}]
        result = review_copy_behavior(value)
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["state"], "FAIL")
        self.assertEqual(result["findings"][0]["evidence"], [HASH])
        current = result["checks"]["current_token_findings"]
        self.assertEqual(current["state"], "FLAGGED")
        self.assertEqual(current["actual"]["flagged_findings"], 1)
        self.assertEqual(current["actual"]["unknown_control_findings"], 1)
        # An older snapshot may store a gate without a redundant findings list.
        value["token_risk"][0]["findings"] = []
        self.assertEqual(review_copy_behavior(value)["findings"][0]["evidence"], [HASH])

    def test_review_gate_needs_explicit_primary_evidence_that_exists_in_report(self):
        value = observed_report()
        gate = {"state": "PASS", "detail": "Independently reviewed specified scope", "reviewed": True, "primary_evidence": True, "evidence": [HASH]}
        for invalid in ({"reviewed": False}, {"primary_evidence": False}, {"evidence": ["b" * 64]}, {"state": "UNKNOWN"}):
            with self.subTest(invalid=invalid):
                value["reviewed_copy_checks"] = {"creator_links": {**gate, **invalid}}
                self.assertEqual(review_copy_behavior(value)["checks"]["creator_links"]["state"], "UNKNOWN")
        value["reviewed_copy_checks"] = {"creator_links": gate}
        self.assertEqual(review_copy_behavior(value)["checks"]["creator_links"]["state"], "PASS")

    def test_one_reviewed_token_does_not_clear_another_unknown_token(self):
        value = observed_report()
        value["research"]["episodes"] = []
        gate = {"state": "PASS", "reviewed": True, "primary_evidence": True, "evidence": [HASH]}
        value["reviewed_copy_checks"] = {"holder_concentration": {"state": "UNKNOWN"}}
        value["token_risk"] = [{"gates": {"holder_concentration": gate}}, {"gates": {"holder_concentration": {"state": "UNKNOWN"}}}]
        self.assertEqual(review_copy_behavior(value)["checks"]["holder_concentration"]["state"], "UNKNOWN")
        value["token_risk"][1]["gates"]["holder_concentration"] = gate
        self.assertEqual(review_copy_behavior(value)["checks"]["holder_concentration"]["state"], "PASS")

    def test_reviewed_subset_of_mints_does_not_clear_uninspected_traded_asset(self):
        value = observed_report()
        gate = {"state": "PASS", "reviewed": True, "primary_evidence": True, "evidence": [HASH]}
        value["token_risk"] = [{"mint": "different-mint", "gates": {"holder_concentration": gate}}]
        self.assertEqual(review_copy_behavior(value)["checks"]["holder_concentration"]["state"], "UNKNOWN")
        value["token_risk"][0]["mint"] = "public-mint"
        self.assertEqual(review_copy_behavior(value)["checks"]["holder_concentration"]["state"], "PASS")

    def test_legacy_missing_fields_remain_unknown(self):
        result = review_copy_behavior({})
        self.assertTrue(result["conditional"])
        self.assertEqual(result["findings"], [])
        self.assertEqual(len(result["unknown_checks"]), 9)

    def test_malformed_legacy_provenance_cannot_raise_or_grant_reviewed_gate(self):
        value = observed_report()
        value["evidence"] = [{"hash": []}, None, {"hash": None}]
        value["token_risk"] = [{"findings": [{}]}]
        value["reviewed_copy_checks"] = {"creator_links": {"state": "PASS", "reviewed": True, "primary_evidence": True, "evidence": [HASH]}}
        result = review_copy_behavior(value)
        self.assertEqual(result["checks"]["creator_links"]["state"], "UNKNOWN")
        self.assertTrue(all(isinstance(item.get("detail"), str) for item in result["findings"]))
