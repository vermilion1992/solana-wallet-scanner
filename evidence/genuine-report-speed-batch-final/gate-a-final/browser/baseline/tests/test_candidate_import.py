"""R4 controls: saved memberships and imports never manufacture audit completion."""
from copy import deepcopy
import unittest

from scanner.accounting import METHODOLOGY
from scanner.candidate_import import aggregate_candidate_universe, derive_candidate_progress, import_candidate_cohort

WALLET = "So11111111111111111111111111111111111111112"
OTHER = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
THIRD = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
POOL1 = "Cr469Kh7oCPtQk5YADEmjVpBWx1DiXXLiooPFJn23jsg"
POOL2 = "31eCTC8W3VcX7BiFwK2o5Ax41FPi2UyHcehcy2Gd3H5h"
POOL_HASH, TX_HASH, ACCOUNT_HASH = "a" * 64, "b" * 64, "c" * 64


def observed(address=WALLET):
    return {"address": address, "source": "pool-trades", "status": "unresolved", "signatures": ["sample-signature"],
            "pools": [POOL1], "evidence": [POOL_HASH], "reason": "Provider lead"}


def checked(address=WALLET):
    row = observed(address)
    row.update(status="candidate", evidence=[POOL_HASH, TX_HASH, ACCOUNT_HASH],
               validation={"identity_verified": True, "account_type": "system-owned signer", "economic_signers": [address],
                           "transaction_evidence_hash": TX_HASH, "account_evidence_hash": ACCOUNT_HASH,
                           "token_flows": [{"mint": OTHER, "raw_delta": "10", "decimals": 6}]})
    return row


def cohort(identifier="first", candidates=None, created_at="2026-10-02T14:00:00+00:00"):
    return {"id": identifier, "created_at": created_at, "cohort_date": created_at[:10], "source": "public-pool-discovery",
            "status": "completed", "candidates": candidates if candidates is not None else [observed()], "evidence": []}


def sample_report(address=WALLET):
    return {"id": "partial-report", "address": address, "source": "live", "created_at": "2026-10-02T16:00:00+00:00",
            "policy": "UNRESOLVED", "evidence_status": "partial", "methodology": METHODOLOGY,
            "evidence": [{"hash": TX_HASH, "kind": "transaction"}], "coverage": {"history_scope_complete": False, "historical_ownership_verified": False}}


class CandidateImportTests(unittest.TestCase):
    def test_import_deduplicates_identifiers_and_leaves_identity_unresolved(self):
        rows = [WALLET, OTHER, WALLET]
        result = import_candidate_cohort(rows, cohort_id="a" * 32, created_at="2026-10-03T00:00:00Z")
        self.assertEqual(result["id"], "a" * 32)
        self.assertEqual(result["source"], "user-list")
        self.assertEqual(result["counts"]["duplicate_rows"], 1)
        self.assertEqual(result["counts"]["unique_addresses"], 2)
        self.assertEqual(result["sample"]["provider_requests"], 0)
        self.assertEqual([row["address"] for row in result["candidates"]], [WALLET, OTHER])
        for row in result["candidates"]:
            self.assertEqual(row["status"], "unresolved")
            self.assertEqual(row["stage"], "listed")
            self.assertFalse(any(row["states"].values()))
            self.assertNotIn("validation", row)
        self.assertEqual(rows, [WALLET, OTHER, WALLET])

    def test_capped_import_counts_omitted_unique_addresses_without_adding_work(self):
        result = import_candidate_cohort([WALLET, OTHER, THIRD, WALLET], candidate_cap=2)
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual(result["counts"]["omitted_addresses"], 1)
        self.assertEqual(result["counts"]["duplicate_rows"], 1)
        self.assertEqual(result["counts"]["native_transaction_lookups"], 0)
        self.assertEqual(result["counts"]["native_account_checks"], 0)

    def test_all_input_rows_are_validated_even_beyond_retained_cap(self):
        for invalid in ("../bad", "2" * 32, {"address": WALLET, "validation": {"identity_verified": True}}, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                import_candidate_cohort([WALLET, invalid], candidate_cap=1)

    def test_import_bounds_and_metadata_validation_are_explicit(self):
        for addresses, options in (([], {}), (WALLET, {}), ([WALLET] * 1001, {}), ([WALLET], {"candidate_cap": 21}),
                                   ([WALLET], {"candidate_cap": True}), ([WALLET], {"cohort_id": "../id"}),
                                   ([WALLET], {"created_at": "2026-10-03T00:00:00"})):
            with self.subTest(options=options), self.assertRaises(ValueError):
                import_candidate_cohort(addresses, **options)

    def test_completed_job_without_native_evidence_does_not_advance_identity_or_history(self):
        row = observed()
        result = derive_candidate_progress(row, cohort(candidates=[row]))
        self.assertEqual(result["stage"], "observed")
        self.assertTrue(result["states"]["observed"])
        self.assertFalse(result["states"]["identity_checked"])
        self.assertFalse(result["states"]["sample_audited"])
        self.assertFalse(result["states"]["history_reconstructed"])

    def test_identity_stage_requires_positive_native_evidence_not_a_label(self):
        row = checked()
        self.assertEqual(derive_candidate_progress(row)["stage"], "identity_checked")
        for field, value in (("identity_verified", False), ("account_type", "program-owned"), ("economic_signers", [OTHER]),
                             ("account_evidence_hash", None), ("token_flows", [])):
            with self.subTest(field=field):
                missing = deepcopy(row)
                missing["validation"][field] = value
                self.assertFalse(derive_candidate_progress(missing)["states"]["identity_checked"])
        missing = deepcopy(row)
        missing["evidence"] = [POOL_HASH]
        self.assertFalse(derive_candidate_progress(missing)["states"]["identity_checked"])

    def test_live_partial_report_advances_only_sample_audit_not_history(self):
        row, report = checked(), sample_report()
        result = derive_candidate_progress(row, reports=[report])
        self.assertEqual(result["stage"], "sample_audited")
        self.assertEqual(result["sample_report_ids"], ["partial-report"])
        self.assertFalse(result["states"]["history_reconstructed"])
        for changes in ({"source": "demo"}, {"preview": True}, {"address": OTHER}, {"evidence": []}):
            with self.subTest(changes=changes):
                self.assertFalse(derive_candidate_progress(row, reports=[{**report, **changes}])["states"]["sample_audited"])

    def test_verified_history_stage_needs_ownership_basis_fee_and_position_proof(self):
        report = sample_report()
        report.update(evidence_status="verified", policy="MISS", coverage={"history_scope_complete": True, "historical_ownership_verified": True},
                      checks=[{"key": "evidence_" + key, "state": "PASS"} for key in ("history", "identity", "basis", "positions", "fees")])
        result = derive_candidate_progress(checked(), reports=[report])
        self.assertEqual(result["stage"], "history_reconstructed")
        self.assertEqual(result["history_report_ids"], ["partial-report"])
        self.assertEqual(report["policy"], "MISS")  # Reconstruction need not mean profitable.
        for changes in ({"historical_ownership_verified": False}, {"history_scope_complete": False}, {"account_paging_finished": True}):
            missing = deepcopy(report)
            missing["coverage"] = changes
            self.assertFalse(derive_candidate_progress(checked(), reports=[missing])["states"]["history_reconstructed"])
        missing = deepcopy(report)
        missing["checks"][-1]["state"] = "UNKNOWN"
        self.assertFalse(derive_candidate_progress(checked(), reports=[missing])["states"]["history_reconstructed"])

    def test_aggregation_deduplicates_times_and_pool_sets_but_preserves_every_membership(self):
        first = cohort(candidates=[observed()])
        second_row = checked()
        second_row["pools"] = [POOL2]
        second_row["signatures"] = ["later-signature"]
        second = cohort("second", [second_row], "2026-10-03T14:00:00+00:00")
        before = deepcopy([first, second])
        result = aggregate_candidate_universe([second, first])
        row = result["candidates"][0]
        self.assertEqual(result["counts"]["unique_candidates"], 1)
        self.assertEqual(result["counts"]["memberships"], 2)
        self.assertEqual(len(row["origins"]), 2)
        self.assertEqual(row["first_seen"], first["created_at"])
        self.assertEqual(row["last_seen"], second["created_at"])
        self.assertEqual(set(row["pools"]), {POOL1, POOL2})
        self.assertEqual(set(row["signatures"]), {"sample-signature", "later-signature"})
        self.assertEqual(row["audit_eligible_cohort_ids"], ["second"])
        self.assertFalse(row["states"]["history_reconstructed"])
        self.assertEqual([first, second], before)
        self.assertNotIn("profit_sol", row)

    def test_imported_membership_does_not_inherit_native_audit_permission(self):
        imported = import_candidate_cohort([WALLET], cohort_id="a" * 32, created_at="2026-10-03T18:00:00Z")
        verified = cohort(candidates=[checked()])
        result = aggregate_candidate_universe([imported, verified])
        row = result["candidates"][0]
        self.assertEqual(set(row["origin_types"]), {"user-list", "pool-trades"})
        self.assertEqual(row["audit_eligible_cohort_ids"], ["first"])
        manual = next(origin for origin in row["origins"] if origin["origin_type"] == "user-list")
        self.assertFalse(manual["states"]["identity_checked"])
        self.assertEqual(manual["member_status"], "unresolved")

    def test_capped_saved_display_reports_omissions_and_keeps_original_cohorts(self):
        cohorts = [cohort(candidates=[observed(WALLET), observed(OTHER)]), cohort("later", [observed(THIRD)], "2026-10-04T00:00:00Z")]
        original = deepcopy(cohorts)
        result = aggregate_candidate_universe(cohorts, candidate_cap=1)
        self.assertEqual(result["candidates"][0]["address"], THIRD)
        self.assertEqual(result["counts"]["unique_candidates"], 3)
        self.assertEqual(result["counts"]["returned_candidates"], 1)
        self.assertEqual(result["counts"]["omitted_candidates"], 2)
        self.assertEqual(result["counts"]["returned_memberships"], 1)
        self.assertEqual(result["counts"]["omitted_memberships"], 2)
        self.assertEqual(cohorts, original)

    def test_sample_audit_state_comes_from_report_evidence_not_audit_job_id(self):
        source = cohort(candidates=[checked()])
        source["audit_scan_ids"] = ["finished-job"]
        source["candidates"][0]["report_id"] = "partial-report"
        report = sample_report()
        report["scan_id"] = "finished-job"
        self.assertEqual(aggregate_candidate_universe([source])["candidates"][0]["stage"], "identity_checked")
        result = aggregate_candidate_universe([source], [report])
        row = result["candidates"][0]
        self.assertEqual(row["stage"], "sample_audited")
        self.assertEqual(row["report_id"], "partial-report")
        self.assertFalse(row["states"]["history_reconstructed"])

    def test_invalid_and_demo_records_cannot_enter_saved_wallet_universe(self):
        source = cohort(candidates=[observed(), {"address": "2" * 32}, None, observed()])
        demo = cohort("demo", [checked(OTHER)])
        demo["source"] = "demo"
        result = aggregate_candidate_universe([source, demo, deepcopy(source)])
        self.assertEqual(result["counts"]["cohorts"], 1)
        self.assertEqual(result["counts"]["invalid_records"], 2)
        self.assertEqual(result["counts"]["duplicate_records"], 1)
        self.assertEqual(result["counts"]["unique_candidates"], 1)

    def test_offline_helpers_do_not_mutate_saved_quota_or_use_any_gateway(self):
        # The pure API accepts neither Store nor Gateway and returns no dispatch.
        imported = import_candidate_cohort([WALLET])
        result = aggregate_candidate_universe([imported])
        self.assertEqual(imported["sample"]["provider_requests"], 0)
        self.assertEqual(result["candidates"][0]["stage"], "listed")
        self.assertEqual(result["candidates"][0]["audit_eligible_cohort_ids"], [])
        self.assertFalse(any(result["candidates"][0]["states"].values()))

