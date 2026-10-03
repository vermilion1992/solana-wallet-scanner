"""Synthetic negative controls for offline native collection receipts."""
from copy import deepcopy
import hashlib
import tempfile
import unittest
from unittest.mock import patch

from scanner.collector import VERSION as COLLECTOR_VERSION
from scanner.history_evidence import derive_history_evidence
from scanner.storage import Store
from scanner.providers import TOKEN_PROGRAM
from scanner.report_rebuild import freeze_report_inputs, load_report_inputs, partition_report_metadata

WALLET = "11111111111111111111111111111111"
TOKEN_ACCOUNT = "So11111111111111111111111111111111111111112"
START = 10_000_000
END = START + 30 * 86400
WINDOW = {"start": START, "end": END}
IDENTIFIER = hashlib.sha256(f"{WALLET}:{START}:{END}".encode()).hexdigest()


class HistoryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = Store(self.folder.name)
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(self.store.close)
        self.anchor = self.store.archive({"method": "getSlot", "commitment": "finalized", "result": 2000})
        self.cp = {"version": COLLECTOR_VERSION, "address": WALLET, "start": START, "end": END,
                   "basis_floor": START - 90 * 86400, "snapshot": {"slot": 2000, "commitment": "finalized", "anchor_evidence": self.anchor},
                   "accounts": {}, "transactions": {}, "evidence": [{"hash": self.anchor, "kind": "snapshot-slot"}],
                   "ordering": {}, "account_scope": {"included_account_count": 1, "omitted_account_count": 0}}
        self.entries = [self.entry("at-end", END, 1500)]
        self.add_transaction("inside", END - 86400, 1200)
        self.add_transaction("at-start", START, 1100)
        self.entries.append(self.entry("older-basis", self.cp["basis_floor"] - 1, 900))
        self.page = self.add_page(self.entries)
        self.cp["accounts"][WALLET] = self.account(WALLET, self.page, "older-basis")
        self.save()

    @staticmethod
    def entry(signature, timestamp, slot, err=None):
        return {"signature": signature, "blockTime": timestamp, "slot": slot, "err": err, "confirmationStatus": "finalized"}

    def account(self, address, terminal_hash, cursor):
        return {"address": address, "origin": "wallet" if address == WALLET else "current owner enumeration",
                "ownership_evidence": self.anchor, "cursor": cursor, "terminal": "bounded acquisition lookback reached",
                "terminal_evidence": terminal_hash}

    def add_transaction(self, signature, timestamp, slot, *, fee=5000, delta=-5000, payer=WALLET, err=None):
        keys = [WALLET] if payer == WALLET else [payer, WALLET]
        before = [1_000_000_000] * len(keys)
        after = before.copy()
        after[keys.index(WALLET)] += delta
        raw = {"slot": slot, "blockTime": timestamp, "version": "legacy",
               "transaction": {"signatures": [signature], "message": {"accountKeys": keys, "instructions": []}},
               "meta": {"err": err, "fee": fee, "preBalances": before, "postBalances": after,
                        "preTokenBalances": [], "postTokenBalances": []}}
        digest = self.store.archive(raw)
        self.cp["transactions"][signature] = {"signature": signature, "evidence_hash": digest}
        self.cp["evidence"].append({"hash": digest, "kind": "transaction", "signature": signature})
        self.entries.append(self.entry(signature, timestamp, slot, err))
        return digest

    def add_page(self, entries, *, address=WALLET, before=None, **params):
        options = {"limit": 100, "commitment": "finalized", "minContextSlot": 2000, **params}
        if before is not None:
            options["before"] = before
        digest = self.store.archive({"method": "getSignaturesForAddress", "address": address, "params": options, "result": entries})
        self.cp["evidence"].append({"hash": digest, "kind": "signature-page"})
        return digest

    def save(self):
        self.store.put("collector_checkpoints", IDENTIFIER, self.cp)

    def derive(self, **kwargs):
        return derive_history_evidence(self.store, WALLET, WINDOW, checkpoint=self.cp, **kwargs)

    def replace_transaction_link(self, signature, digest):
        """Replace this synthetic source set, retaining old immutable archives."""
        self.cp["transactions"][signature]["evidence_hash"] = digest
        self.cp["evidence"] = [ref for ref in self.cp["evidence"]
                               if ref.get("kind") != "transaction" or ref.get("signature") != signature]
        self.cp["evidence"].append({"kind": "transaction", "signature": signature, "hash": digest})

    def replace_page(self, entries, **params):
        self.cp["evidence"] = [ref for ref in self.cp["evidence"] if ref["kind"] != "signature-page"]
        self.page = self.add_page(entries, **params)
        self.cp["accounts"][WALLET]["terminal_evidence"] = self.page
        self.cp["accounts"][WALLET]["cursor"] = entries[-1]["signature"] if entries else None
        self.save()

    def two_account_receipts(self):
        """Synthetic owned-account overlap; both pages initially agree with raw."""
        for signature, item in self.cp["transactions"].items():
            raw = self.store.evidence(item["evidence_hash"])
            raw["transaction"]["message"]["accountKeys"].append(TOKEN_ACCOUNT)
            raw["meta"]["preBalances"].append(0)
            raw["meta"]["postBalances"].append(0)
            digest = self.store.archive(raw)
            self.replace_transaction_link(signature, digest)
        owner = self.store.archive({"method": "getTokenAccountsByOwner", "owner": WALLET, "program": TOKEN_PROGRAM,
                                    "result": {"context": {"slot": 2000}, "value": [{"pubkey": TOKEN_ACCOUNT,
                                               "account": {"data": {"parsed": {"info": {"owner": WALLET}}}}}]}})
        self.cp["evidence"].append({"kind": "owned-accounts", "hash": owner})
        token_page = self.add_page(deepcopy(self.entries), address=TOKEN_ACCOUNT)
        self.cp["accounts"][TOKEN_ACCOUNT] = self.account(TOKEN_ACCOUNT, token_page, "older-basis")
        self.cp["accounts"][TOKEN_ACCOUNT]["ownership_evidence"] = owner
        self.cp["account_scope"]["included_account_count"] = 2
        self.save()

    def replace_account_page(self, entries, address=WALLET):
        self.cp["evidence"] = [ref for ref in self.cp["evidence"] if ref["kind"] != "signature-page"
                               or self.store.evidence(ref["hash"])["address"] != address]
        page = self.add_page(entries, address=address)
        self.cp["accounts"][address]["terminal_evidence"] = page
        self.cp["accounts"][address]["cursor"] = entries[-1]["signature"] if entries else None
        self.save()

    def assert_cross_account_conflict(self, field, value, address=WALLET):
        self.two_account_receipts()
        entries = deepcopy(self.entries)
        entries[1][field] = value
        self.replace_account_page(entries, address)
        result = self.derive()
        self.assertEqual(result["paging"]["wallet_address_intervals"]["report_period"]["state"], "UNKNOWN")
        self.assertEqual(result["native_address_metrics"]["periods"]["report_period"]["wallet_network_fees_sol"]["status"], "unknown")
        self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"], "0.00001")
        self.assertTrue(any(conflict["account"] == address and conflict["signature"] == "inside" and conflict["field"] == field
                            for conflict in result["paging"]["conflicts"]))

    def test_r6_wallet_timestamp_conflict_is_not_hidden_by_token_receipt(self):
        self.assert_cross_account_conflict("blockTime", START - 1)

    def test_r6_wallet_slot_conflict_is_not_hidden_by_token_receipt(self):
        self.assert_cross_account_conflict("slot", 1201)

    def test_r6_wallet_execution_conflict_is_not_hidden_by_token_receipt(self):
        self.assert_cross_account_conflict("err", {"InstructionError": [0, "Custom"]})

    def test_r6_wallet_finality_conflict_is_not_hidden_by_token_receipt(self):
        self.assert_cross_account_conflict("confirmationStatus", "confirmed")

    def test_r6_token_conflicts_revoke_period_and_corrections_recover(self):
        self.two_account_receipts()
        for field, value in (("blockTime", START - 1), ("slot", 1201),
                             ("err", {"InstructionError": [0, "Custom"]}), ("confirmationStatus", "confirmed")):
            with self.subTest(field=field):
                entries = deepcopy(self.entries)
                entries[1][field] = value
                self.replace_account_page(entries, TOKEN_ACCOUNT)
                result = self.derive()
                self.assertEqual(result["paging"]["wallet_address_intervals"]["report_period"]["state"], "UNKNOWN")
                self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"], "0.00001")
                self.assertTrue(any(conflict["account"] == TOKEN_ACCOUNT and conflict["field"] == field
                                    for conflict in result["paging"]["conflicts"]))
                self.replace_account_page(deepcopy(self.entries), TOKEN_ACCOUNT)
                corrected = self.derive()
                self.assertEqual(corrected["paging"]["wallet_address_intervals"]["report_period"]["state"], "PASS")
                self.assertEqual(corrected["native_address_metrics"]["periods"]["report_period"]["wallet_network_fees_sol"]["value"], "0.00001")
                self.assertEqual(set(corrected["evidence_gates"].values()), {"UNKNOWN"})

    def test_r6_both_boundaries_use_raw_time_and_recover_after_either_page_correction(self):
        self.two_account_receipts()
        original = self.store.evidence(self.cp["transactions"]["at-start"]["evidence_hash"])
        for address in (WALLET, TOKEN_ACCOUNT):
            for canonical_time, wrong_time in ((START - 1, START), (START, START - 1), (END - 1, END), (END, END - 1)):
                with self.subTest(address=address, canonical_time=canonical_time):
                    raw = deepcopy(original)
                    raw["blockTime"] = canonical_time
                    digest = self.store.archive(raw)
                    self.replace_transaction_link("at-start", digest)
                    correct_entries = deepcopy(self.entries)
                    correct_entries[2]["blockTime"] = canonical_time
                    for account in (WALLET, TOKEN_ACCOUNT):
                        self.replace_account_page(correct_entries, account)
                    wrong_entries = deepcopy(correct_entries)
                    wrong_entries[2]["blockTime"] = wrong_time
                    self.replace_account_page(wrong_entries, address)
                    result = self.derive()
                    period = result["paging"]["wallet_address_intervals"]["report_period"]
                    self.assertEqual(period["state"], "UNKNOWN")
                    self.assertEqual(period["required_transactions"], 2 if START <= canonical_time < END else 1)
                    self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"], "0.00001")
                    self.replace_account_page(correct_entries, address)
                    corrected = self.derive()
                    expected = "0.00001" if START <= canonical_time < END else "0.000005"
                    self.assertEqual(corrected["native_address_metrics"]["periods"]["report_period"]["wallet_network_fees_sol"]["value"], expected)
                    self.assertEqual(corrected["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["record_count"], 2)

    def test_r6_rawless_boundary_disagreements_revoke_completion_not_observations(self):
        self.two_account_receipts()
        for index in (0, 3):
            with self.subTest(boundary_signature=self.entries[index]["signature"]):
                entries = deepcopy(self.entries)
                entries[index]["blockTime"] += 1
                self.replace_account_page(entries, TOKEN_ACCOUNT)
                result = self.derive()
                self.assertEqual(result["paging"]["wallet_address_intervals"]["report_period"]["state"], "UNKNOWN")
                self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"], "0.00001")
                self.assertTrue(any(conflict["signature"] == entries[index]["signature"]
                                    for conflict in result["paging"]["conflicts"]))
                self.replace_account_page(deepcopy(self.entries), TOKEN_ACCOUNT)
                self.assertEqual(self.derive()["paging"]["wallet_address_intervals"]["report_period"]["state"], "PASS")

    def test_r6_disconnected_upper_marker_cannot_anchor_wallet_period(self):
        self.two_account_receipts()
        for address in (WALLET, TOKEN_ACCOUNT):
            self.replace_account_page(deepcopy(self.entries[1:]), address)
        self.add_page([self.entry("detached-at-end", END, 1600)], address=TOKEN_ACCOUNT, before="unlinked-cursor")
        self.save()
        result = self.derive()
        self.assertEqual(result["paging"]["wallet_address_intervals"]["report_period"]["state"], "UNKNOWN")
        self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"], "0.00001")

    def test_frozen_intervals_enum_completion_never_global_wallet_proof(self):
        result = self.derive()
        self.assertEqual(result["paging"]["state"], "PASS")
        self.assertEqual(result["record_provenance"]["counts"], {"inspected": 2, "local_native_receipts": 2, "unresolved": 0})
        self.assertEqual(result["intervals"]["four_weeks"]["start"], "1970-04-28T17:46:40+00:00")
        self.assertEqual(result["intervals"]["report_period"]["status"], "partial")
        self.assertEqual(result["intervals"]["report_period"]["enumerated_scope_status"], "complete")
        self.assertEqual(set(result["evidence_gates"].values()), {"UNKNOWN"})
        self.assertFalse(result["account_scope"]["wallet_history_complete"])
        self.assertIn("opening_inventory_provenance", result["metric_decisions"]["profit_sol"]["requirements"])
        self.assertIn("historical_boundary_marks", result["metric_decisions"]["economic_pnl_sol"]["requirements"])
        self.assertIn("independent_four_week_records", result["metric_decisions"]["positive_weeks"]["requirements"])
        self.assertNotIn("verification_interval_records", result["metric_decisions"]["profit_sol"]["requirements"])

    def test_observed_and_wallet_period_native_totals_do_not_become_profit(self):
        result = self.derive()
        observed = result["native_address_metrics"]["observed"]
        self.assertEqual(observed["wallet_network_fees_sol"]["value"], "0.00001")
        self.assertEqual(observed["native_wallet_delta_sol"]["value"], "-0.00001")
        self.assertEqual(observed["wallet_network_fees_sol"]["record_count"], 2)
        self.assertEqual(result["native_address_metrics"]["periods"]["four_weeks"]["wallet_network_fees_sol"]["value"], "0.000005")
        self.assertEqual(result["metric_decisions"]["profit_sol"]["state"], "UNKNOWN")
        self.assertIn("not wallet profit", " ".join(result["native_address_metrics"]["notes"]))

    def test_report_exact_subset_keeps_observed_values_revokes_period(self):
        record = self.cp["transactions"]["inside"]
        result = self.derive(collected={"transactions": [record]})
        self.assertEqual(result["record_provenance"]["counts"]["inspected"], 1)
        self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"], "0.000005")
        self.assertEqual(result["paging"]["wallet_address_intervals"]["report_period"]["missing_signatures"], ["at-start"])
        self.assertEqual(result["native_address_metrics"]["periods"]["report_period"]["wallet_network_fees_sol"]["status"], "unknown")

    def test_old_frozen_checkpoint_replays_after_persisted_resume(self):
        frozen = deepcopy(self.cp)
        self.cp["gaps"] = []
        self.cp["credits"] = 100
        self.save()
        result = derive_history_evidence(self.store, WALLET, WINDOW, checkpoint=frozen)
        self.assertEqual(result["record_provenance"]["counts"]["local_native_receipts"], 2)

    def test_arbitrary_import_cannot_supply_a_trusted_checkpoint(self):
        self.store.delete("collector_checkpoints", IDENTIFIER)
        result = self.derive(collected={"transactions": list(self.cp["transactions"].values()), "coverage": {"history_scope_complete": True}})
        self.assertEqual(result["record_provenance"]["state"], "UNKNOWN")
        self.assertEqual(result["paging"]["state"], "UNKNOWN")
        self.assertEqual(result["evidence_gates"]["history"], "UNKNOWN")

    def test_missing_and_corrupt_transaction_revoke_observed_and_period(self):
        digest = self.cp["transactions"]["inside"]["evidence_hash"]
        path = self.store.path / "evidence" / f"{digest}.json.gz"
        for mutation in (lambda: path.unlink(), lambda: path.write_bytes(b"bad archive")):
            with self.subTest(mutation=mutation):
                mutation()
                result = self.derive()
                self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["status"], "unknown")
                self.assertEqual(result["paging"]["wallet_address_intervals"]["report_period"]["state"], "UNKNOWN")
                self.assertIn("inside", result["paging"]["intervals"]["report_period"]["missing_signatures"])

    def test_deleted_terminal_page_revokes_completion_and_receipts(self):
        (self.store.path / "evidence" / f"{self.page}.json.gz").unlink()
        result = self.derive()
        self.assertEqual(result["paging"]["state"], "UNKNOWN")
        self.assertEqual(result["record_provenance"]["counts"]["local_native_receipts"], 0)

    def test_missing_upper_chain_time_stays_partial_with_known_observed_set(self):
        self.replace_page(self.entries[1:])
        result = self.derive()
        self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["status"], "known")
        self.assertEqual(result["paging"]["wallet_address_intervals"]["report_period"]["state"], "UNKNOWN")

    def test_short_page_without_terminal_receipt_is_not_complete(self):
        self.cp["accounts"][WALLET]["terminal"] = None
        self.cp["accounts"][WALLET].pop("terminal_evidence")
        self.save()
        self.assertEqual(self.derive()["paging"]["state"], "UNKNOWN")

    def test_disconnected_cursor_and_wrong_finality_revoke_completion(self):
        for params in ({"before": "unobserved-cursor"}, {"commitment": "confirmed"}, {"minContextSlot": 1999}):
            with self.subTest(params=params):
                self.replace_page(self.entries, **params)
                self.assertEqual(self.derive()["paging"]["state"], "UNKNOWN")

    def test_mismatched_status_or_membership_cannot_be_primary_receipt(self):
        for mutation in ("err", "confirmationStatus", "slot", "blockTime"):
            with self.subTest(mutation=mutation):
                entries = deepcopy(self.entries)
                entries[1][mutation] = {"err": {"bad": "status"}, "confirmationStatus": "confirmed", "slot": 1201, "blockTime": END - 86401}[mutation]
                self.replace_page(entries)
                self.assertEqual(self.derive()["record_provenance"]["counts"]["local_native_receipts"], 1)

    def test_unknown_page_time_does_not_silently_drop_required_membership(self):
        entries = deepcopy(self.entries)
        entries[1]["blockTime"] = None
        self.replace_page(entries)
        result = self.derive()
        self.assertEqual(result["paging"]["wallet_address_intervals"]["report_period"]["state"], "UNKNOWN")
        self.assertEqual(result["record_provenance"]["counts"]["unresolved"], 1)

    def test_fixed_ninety_day_metric_and_additional_saved_verification_interval(self):
        result = self.derive(verification_days=60)
        self.assertEqual(result["intervals"]["verification_90d"]["start"], self.derive()["intervals"]["verification_90d"]["start"])
        self.assertNotEqual(result["intervals"]["selected_verification"]["start"], result["intervals"]["verification_90d"]["start"])
        self.assertEqual(result["metric_decisions"]["completed_positions_90d"]["interval"], "verification_90d")

    def test_omitted_token_scope_blocks_enum_not_native_address_totals(self):
        self.cp["account_scope"]["omitted_account_count"] = 1
        self.save()
        result = self.derive()
        self.assertEqual(result["paging"]["state"], "UNKNOWN")
        self.assertEqual(result["paging"]["wallet_address_intervals"]["report_period"]["state"], "PASS")
        self.assertEqual(result["native_address_metrics"]["periods"]["report_period"]["wallet_network_fees_sol"]["status"], "known")

    def test_legacy_account_inspection_cap_preserves_exact_native_observations(self):
        self.cp["accounts"][TOKEN_ACCOUNT] = self.account(TOKEN_ACCOUNT, self.page, "older-basis")
        self.cp["account_scope"]["included_account_count"] = 2
        self.save()
        with patch("scanner.history_evidence.MAX_ACCOUNTS", 1):
            result = self.derive()
        self.assertEqual(result["paging"]["state"], "UNKNOWN")
        self.assertEqual(result["account_scope"]["included_account_count"], 1)
        self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"], "0.00001")
        self.assertEqual(result["paging"]["wallet_address_intervals"]["report_period"]["state"], "PASS")

    def test_failed_transactions_are_native_fee_overhead_not_successful_trades(self):
        entries = deepcopy(self.entries)
        failure = {"InstructionError": [0, "Custom"]}
        raw = self.store.evidence(self.cp["transactions"]["inside"]["evidence_hash"])
        raw["meta"]["err"] = failure
        digest = self.store.archive(raw)
        self.replace_transaction_link("inside", digest)
        entries[1]["err"] = failure
        self.replace_page(entries)
        result = self.derive()
        self.assertEqual(result["record_provenance"]["counts"]["local_native_receipts"], 2)
        self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"], "0.00001")
        self.assertEqual(result["evidence_gates"]["fees"], "UNKNOWN")

    def test_missing_same_slot_block_order_blocks_economic_paging_not_additive_native_total(self):
        raw = self.store.evidence(self.cp["transactions"]["at-start"]["evidence_hash"])
        raw["slot"] = 1200
        raw["blockTime"] = END - 86400
        digest = self.store.archive(raw)
        self.replace_transaction_link("at-start", digest)
        entries = deepcopy(self.entries)
        entries[2]["slot"] = 1200
        entries[2]["blockTime"] = END - 86400
        self.replace_page(entries)
        result = self.derive()
        self.assertEqual(result["paging"]["intervals"]["report_period"]["state"], "UNKNOWN")
        self.assertEqual(result["paging"]["wallet_address_intervals"]["report_period"]["state"], "PASS")
        block = self.store.archive({"method": "getBlock", "slot": 1200, "result": {"signatures": ["inside", "at-start"]}})
        self.cp["evidence"].append({"kind": "block-order", "hash": block})
        self.cp["ordering"] = {"inside": 0, "at-start": 1}
        self.save()
        self.assertEqual(self.derive()["paging"]["intervals"]["report_period"]["state"], "PASS")

    def test_absent_native_endpoints_keep_amounts_unknown(self):
        raw = self.store.evidence(self.cp["transactions"]["inside"]["evidence_hash"])
        raw["meta"].pop("preBalances")
        digest = self.store.archive(raw)
        self.replace_transaction_link("inside", digest)
        self.save()
        result = self.derive()
        self.assertEqual(result["record_provenance"]["state"], "PASS")
        self.assertEqual(result["native_address_metrics"]["observed"]["native_wallet_delta_sol"]["status"], "unknown")

    def test_payer_identity_prevents_charging_wallet_other_payer_fee(self):
        raw = self.store.evidence(self.cp["transactions"]["inside"]["evidence_hash"])
        raw["transaction"]["message"]["accountKeys"] = [TOKEN_ACCOUNT, WALLET]
        raw["meta"]["preBalances"] = [1_000_000_000, 1_000_000_000]
        raw["meta"]["postBalances"] = [999_994_990, 1_000_000_010]
        digest = self.store.archive(raw)
        self.replace_transaction_link("inside", digest)
        self.save()
        observed = self.derive()["native_address_metrics"]["observed"]
        self.assertEqual(observed["wallet_network_fees_sol"]["value"], "0.000005")
        self.assertEqual(observed["native_wallet_delta_sol"]["value"], "-0.00000499")

    def test_report_hash_substitution_is_not_a_collector_receipt(self):
        raw = self.store.evidence(self.cp["transactions"]["inside"]["evidence_hash"])
        raw["meta"]["fee"] = 9
        forged = self.store.archive(raw)
        result = self.derive(collected={"transactions": [{"signature": "inside", "evidence_hash": forged}]})
        self.assertEqual(result["record_provenance"]["counts"]["local_native_receipts"], 0)
        self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["status"], "unknown")

    def test_native_fee_or_endpoint_conservation_failure_revokes_amounts(self):
        original = self.store.evidence(self.cp["transactions"]["inside"]["evidence_hash"])
        for field in ("fee", "postBalances"):
            with self.subTest(field=field):
                raw = deepcopy(original)
                if field == "fee":
                    raw["meta"]["fee"] += 1
                else:
                    raw["meta"]["postBalances"][0] += 1
                digest = self.store.archive(raw)
                self.replace_transaction_link("inside", digest)
                self.save()
                result = self.derive()
                self.assertEqual(result["record_provenance"]["state"], "PASS")
                self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["status"], "unknown")
                self.assertEqual(result["native_address_metrics"]["periods"]["report_period"]["native_wallet_delta_sol"]["status"], "unknown")

    def test_conserved_impossible_native_quantities_are_rejected_at_u64_boundary(self):
        original = self.store.evidence(self.cp["transactions"]["inside"]["evidence_hash"])
        u64_max = 2**64 - 1
        cases = (
            ("oversized_endpoints", [WALLET], 5000, [2**64 + 5000], [2**64], "unknown"),
            ("oversized_fee", [WALLET, TOKEN_ACCOUNT], 2 * u64_max, [u64_max, u64_max], [0, 0], "unknown"),
            ("valid_u64_endpoint", [WALLET], 5000, [u64_max], [u64_max - 5000], "known"),
        )
        for label, keys, fee, before, after, expected in cases:
            with self.subTest(label=label):
                self.assertEqual(sum(before) - sum(after), fee)
                raw = deepcopy(original)
                raw["transaction"]["message"]["accountKeys"] = keys
                raw["meta"].update(fee=fee, preBalances=before, postBalances=after)
                digest = self.store.archive(raw)
                self.replace_transaction_link("inside", digest)
                self.save()
                result = self.derive()
                self.assertEqual(result["record_provenance"]["state"], "PASS")
                self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["status"], expected)
                self.assertEqual(result["native_address_metrics"]["periods"]["report_period"]["native_wallet_delta_sol"]["status"], expected)

    def test_r9_linked_unselected_native_alternative_revokes_period_not_exact_observed_amounts(self):
        selected_hash = self.cp["transactions"]["inside"]["evidence_hash"]
        alternative = self.store.evidence(selected_hash)
        alternative["slot"] = 1000
        alternative_hash = self.store.archive(alternative)
        alternate_ref = {"kind": "transaction", "signature": "inside", "hash": alternative_hash}
        self.cp["evidence"].append(alternate_ref)
        self.save()
        result = self.derive()
        receipt = next(account for account in result["paging"]["accounts"] if account["address"] == WALLET)
        receipt = next(row for row in receipt["receipts"] if row["signature"] == "inside")
        self.assertEqual(receipt["placement"]["possible_slots"], [1000, 1200])
        self.assertIsNone(receipt["slot"])
        self.assertIn(alternative_hash, receipt["placement"]["evidence"])
        self.assertEqual(receipt["ordering"]["state"], "UNKNOWN")
        self.assertEqual(result["paging"]["wallet_address_intervals"]["report_period"]["state"], "UNKNOWN")
        self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"], "0.00001")
        self.assertEqual(result["record_provenance"]["counts"]["inspected"], 2)
        self.assertEqual(result["evidence_gates"]["history"], "UNKNOWN")
        # Recovery changes the active frozen source set, never old archives.
        self.cp["evidence"].remove(alternate_ref)
        self.save()
        self.assertEqual(self.derive()["paging"]["wallet_address_intervals"]["report_period"]["state"], "PASS")
        self.assertEqual(self.store.evidence(alternative_hash), alternative)

    def test_r9_missing_raw_retains_page_bound_and_required_record_dependency(self):
        digest = self.cp["transactions"]["inside"]["evidence_hash"]
        (self.store.path / "evidence" / f"{digest}.json.gz").unlink()
        result = self.derive()
        placement = result["paging"]["chronology"]["placements"]["inside"]
        self.assertEqual(placement["state"], "UNKNOWN")
        self.assertEqual(placement["slot_bounds"], {"bounded": True, "min": 1200, "max": 1200})
        self.assertFalse(placement["unbounded"])
        self.assertIn("inside", result["paging"]["intervals"]["report_period"]["missing_signatures"])
        self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["status"], "unknown")

    def test_r10_conserving_alternate_native_fee_revokes_observation_without_new_transaction(self):
        original = self.store.evidence(self.cp["transactions"]["inside"]["evidence_hash"])
        alternative = deepcopy(original)
        alternative["meta"]["fee"] += 1000
        alternative["meta"]["postBalances"][0] -= 1000
        digest = self.store.archive(alternative)
        self.cp["evidence"].append({"kind": "transaction", "signature": "inside", "hash": digest})
        self.save()
        result = self.derive()
        native = result["native_address_metrics"]["observed"]
        self.assertEqual(native["wallet_network_fees_sol"]["status"], "unknown")
        self.assertEqual(native["native_wallet_delta_sol"]["status"], "unknown")
        self.assertEqual(native["wallet_network_fees_sol"]["record_count"], 2)
        self.assertEqual(result["record_provenance"]["counts"]["local_native_receipts"], 2)
        self.assertIn(digest, native["wallet_network_fees_sol"]["evidence"])
        check = result["source_consistency"]["transactions"]["inside"]["native"]["checks"]["fee"]
        self.assertEqual(check["status"], "conflict")
        self.assertEqual({fact["value"] for fact in check["facts"]}, {"5000", "6000"})

    def test_r10_deleted_distinct_alternative_keeps_exact_source_population_and_unknown_amounts(self):
        original_hash = self.cp["transactions"]["inside"]["evidence_hash"]
        alternative = self.store.evidence(original_hash)
        alternative["meta"]["logMessages"] = []
        digest = self.store.archive(alternative)
        self.cp["evidence"].append({"kind": "transaction", "signature": "inside", "hash": digest})
        self.save()
        self.assertEqual(self.derive()["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"], "0.00001")
        (self.store.path / "evidence" / f"{digest}.json.gz").unlink()
        result = self.derive()
        observed = result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]
        self.assertEqual(observed["status"], "unknown")
        self.assertEqual(observed["record_count"], 2)
        check = result["source_consistency"]["transactions"]["inside"]["native"]["wallet_network_fees_sol"]
        self.assertEqual(check["checks"]["fee"]["status"], "missing")
        self.assertIn(digest, check["native_hashes"])
        self.assertIn(original_hash, check["native_hashes"])

    def test_no_disk_or_network_mutations(self):
        rows = self.store.db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        files = set((self.store.path / "evidence").iterdir())
        self.derive()
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM records").fetchone()[0], rows)
        self.assertEqual(set((self.store.path / "evidence").iterdir()), files)

    def test_malformed_primary_page_shapes_remain_unknown(self):
        for entry in (None, "bad entry", {"signature": ["not", "text"], "slot": 1200}, {"signature": "inside", "slot": True}):
            with self.subTest(entry=entry):
                entries = deepcopy(self.entries)
                entries[1] = entry
                self.replace_page(entries)
                result = self.derive()
                self.assertEqual(result["paging"]["state"], "UNKNOWN")
                self.assertEqual(result["evidence_gates"]["history"], "UNKNOWN")

    def metadata_report(self, raw=None):
        raw = raw if raw is not None else {"method": "getAccountInfo", "address": TOKEN_ACCOUNT,
             "commitment": "finalized", "result": {"context": {"slot": 2000}, "value": None}}
        digest = self.store.archive(raw)
        ref = {"kind": "current-mint-controls", "hash": digest, "mint": TOKEN_ACCOUNT}
        report = {"id": "stored-metadata-parent", "source": "live", "address": WALLET, "window": WINDOW,
                  "evidence": [*deepcopy(self.cp["evidence"]), ref],
                  "token_risk": [{"mint": TOKEN_ACCOUNT, "context_slot": 2000, "evidence": [digest]}]}
        self.store.put("reports", report["id"], report)
        return report, ref

    def test_valid_app_metadata_is_separate_from_native_receipts_and_survives_child_replay(self):
        report, ref = self.metadata_report()
        original_evidence = deepcopy(report["evidence"])
        collected = {"transactions": list(self.cp["transactions"].values()), "checkpoint": self.cp,
                     "snapshot": self.cp["snapshot"], "evidence": report["evidence"], "frozen_report_id": report["id"]}
        live = self.derive(collected=collected)
        self.assertEqual(live["source_set"]["raw_reference_count"], len(self.cp["evidence"]))
        self.assertEqual(live["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"], "0.00001")
        metadata = live["source_consistency"]["report_metadata"]
        self.assertEqual(metadata["excluded_reference_count"], 1)
        self.assertEqual(metadata["receipts"][0]["classification"], "report-metadata")
        digest = freeze_report_inputs(self.store, WALLET, WINDOW, collected)
        child = {**deepcopy(report), "id": "stored-metadata-child", "rebuilt_from": report["id"],
                 "collection_input_hash": digest, "token_risk": [],
                 "evidence": [*original_evidence, {"kind": "saved-rebuild-inputs", "hash": digest}]}
        self.store.put("reports", child["id"], child)
        loaded = load_report_inputs(self.store, child)
        replay = self.derive(collected=loaded)
        self.assertEqual(replay["source_set"]["state"], "PASS")
        self.assertEqual(replay["source_set"]["raw_reference_count"], len(self.cp["evidence"]))
        self.assertEqual(replay["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["value"], "0.00001")
        separated = partition_report_metadata(self.store, child["evidence"], report_id=child["id"],
                     address=WALLET, window=WINDOW, collector_references=self.cp["evidence"])
        self.assertEqual(separated["excluded_reference_count"], 2)
        self.assertEqual(self.store.get("reports", report["id"])["evidence"], original_evidence)
        self.assertEqual(self.store.evidence(digest)["evidence"], original_evidence)
        self.assertTrue(all(value == "UNKNOWN" for value in replay["evidence_gates"].values()))

    def test_masqueraded_metadata_missing_context_and_checkpoint_roles_stay_unresolved(self):
        cases = ("native-masquerade", "missing-stored-report", "inside-checkpoint", "missing-risk-citation")
        for case in cases:
            with self.subTest(case=case):
                report, ref = self.metadata_report(self.store.evidence(self.cp["transactions"]["inside"]["evidence_hash"])
                                                   if case == "native-masquerade" else None)
                if case == "missing-stored-report":
                    self.store.delete("reports", report["id"])
                elif case == "missing-risk-citation":
                    report["token_risk"] = []
                    self.store.put("reports", report["id"], report)
                elif case == "inside-checkpoint":
                    self.cp["evidence"].append(ref)
                    self.save()
                result = self.derive(collected={"evidence": report["evidence"], "frozen_report_id": report["id"]})
                self.assertEqual(result["source_set"]["state"], "UNKNOWN")
                self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["status"], "unknown")
                self.assertEqual(result["source_consistency"]["report_metadata"]["excluded_reference_count"], 0)
                if case == "inside-checkpoint":
                    self.cp["evidence"].remove(ref)
                    self.save()

    def test_metadata_archive_validation_never_exceeds_the_combined_distinct_hash_budget(self):
        report, ref = self.metadata_report()
        native = [{"kind": "snapshot-slot", "hash": f"{number:064x}"} for number in range(40_000)]
        with patch.object(self.store, "evidence", wraps=self.store.evidence) as read:
            separated = partition_report_metadata(self.store, [*native, ref], report_id=report["id"],
                         address=WALLET, window=WINDOW, collector_references=native)
        self.assertEqual(read.call_count, 0)
        self.assertEqual(separated["excluded_reference_count"], 0)
        self.assertEqual(separated["receipts"][0]["state"], "UNKNOWN")

    def test_transaction_with_added_metadata_labels_cannot_be_exempted(self):
        raw = self.store.evidence(self.cp["transactions"]["inside"]["evidence_hash"])
        raw.update(method="getAccountInfo", address=TOKEN_ACCOUNT, commitment="finalized",
                   result={"context": {"slot": 2000}, "value": None})
        report, _ = self.metadata_report(raw)
        separated = partition_report_metadata(self.store, report["evidence"], report_id=report["id"],
                    address=WALLET, window=WINDOW, collector_references=self.cp["evidence"])
        self.assertEqual(separated["excluded_reference_count"], 0)
        self.assertEqual(separated["receipts"][0]["state"], "UNKNOWN")
        result = self.derive(collected={"evidence": report["evidence"], "frozen_report_id": report["id"]})
        self.assertEqual(result["source_set"]["state"], "UNKNOWN")
        self.assertEqual(result["native_address_metrics"]["observed"]["wallet_network_fees_sol"]["status"], "unknown")
