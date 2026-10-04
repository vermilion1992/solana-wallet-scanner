"""Synthetic slot-protocol controls; these records are not mainnet evidence."""
import hashlib
import json
import unittest

from scanner.chronology_evidence import assess_chronology, reconcile_placements

MISSING = object()


def receipt(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {"hash": hashlib.sha256(encoded).hexdigest(), "payload": payload}


def native(signature, *, slot=100, timestamp=1000, index=None):
    raw = {"slot": slot, "blockTime": timestamp, "transaction": {"signatures": [signature]}}
    row = {"signature": signature, "raw": raw, "evidence_hash": receipt(raw)["hash"]}
    if index is not None:
        row["transaction_index"] = index
    return row


def block(signatures, *, slot=100, timestamp=MISSING, envelope_id=None):
    result = {"signatures": signatures}
    if timestamp is not MISSING:
        result["blockTime"] = timestamp
    payload = {"method": "getBlock", "slot": slot, "result": result}
    if envelope_id is not None:
        payload["local_request_id"] = envelope_id
    return receipt(payload)


def page(entries):
    return receipt({"method": "getSignaturesForAddress", "result": [
        {"signature": signature, "slot": slot, "blockTime": timestamp, "err": None,
         "confirmationStatus": "finalized"} for signature, slot, timestamp in entries]})


class ChronologyEvidenceTests(unittest.TestCase):
    def test_r9_raw_page_and_block_alternatives_form_one_dependency_envelope(self):
        raw = native("middle", slot=99)
        pages = [page([("middle", 101, 1000)])]
        blocks = [block(["middle"], slot=101)]
        result = assess_chronology([raw], page_receipts=pages, block_receipts=blocks)
        row = result["transactions"]["middle"]
        self.assertEqual(row["state"], "UNKNOWN")
        self.assertIsNone(row["slot"])
        self.assertIsNone(row["transaction_index"])
        self.assertEqual(row["placement"]["slot_bounds"], {"bounded": True, "min": 99, "max": 101})
        self.assertEqual(set(row["placement"]["evidence"]), {raw["evidence_hash"], pages[0]["hash"], blocks[0]["hash"]})

    def test_r9_every_alternative_raw_and_page_survives_reference_order(self):
        rows = [native("middle", slot=99), native("middle", slot=103)]
        pages = [page([("middle", 101, 1000)]), page([("middle", 102, 1000)])]
        for raw_order, page_order in ((rows, pages), (rows[::-1], pages[::-1])):
            with self.subTest(first_slot=raw_order[0]["raw"]["slot"]):
                placement = reconcile_placements(raw_order, page_receipts=page_order)["middle"]
                self.assertEqual(placement["possible_slots"], [99, 101, 102, 103])
                self.assertEqual(placement["slot_bounds"], {"bounded": True, "min": 99, "max": 103})
                self.assertEqual(len([fact for fact in placement["facts"] if fact["kind"] == "transaction"]), 2)

    def test_r9_missing_raw_can_be_bounded_by_consistent_pages(self):
        placement = reconcile_placements([{"signature": "later", "raw": None, "evidence_hash": "missing"}],
                                          page_receipts=[page([("later", 103, 1000)])])["later"]
        self.assertEqual(placement["state"], "UNKNOWN")
        self.assertFalse(placement["unbounded"])
        self.assertEqual(placement["slot_bounds"], {"bounded": True, "min": 103, "max": 103})
        self.assertFalse(placement["indices_by_slot"]["103"]["bounded"])

    def test_r9_explicit_impossible_native_slots_cannot_prove_exclusion(self):
        for slot in (None, False, "99", -1):
            with self.subTest(slot=slot):
                placement = reconcile_placements([native("middle", slot=slot)],
                                                  page_receipts=[page([("middle", 99, 1000)])])["middle"]
                self.assertTrue(placement["unbounded"])
                self.assertFalse(placement["slot_bounds"]["bounded"])
                self.assertIsNone(placement["slot"])

    def test_r9_different_account_page_locations_are_all_retained(self):
        first, second = page([("middle", 99, 1000)]), page([("middle", 103, 1000)])
        first["payload"]["address"], second["payload"]["address"] = "wallet", "token-account"
        placement = reconcile_placements([], page_receipts=[first, second])["middle"]
        self.assertEqual(placement["slot_bounds"], {"bounded": True, "min": 99, "max": 103})
        self.assertEqual({fact["account"] for fact in placement["facts"]}, {"wallet", "token-account"})

    def test_r9_no_placement_source_is_explicitly_unbounded(self):
        placement = reconcile_placements([{"signature": "missing", "raw": None}])["missing"]
        self.assertTrue(placement["unbounded"])
        self.assertEqual(placement["possible_slots"], [])
        self.assertIsNone(placement["slot_bounds"]["min"])

    def test_r9_removing_distinct_alternative_archive_cannot_narrow_an_episode_dependency(self):
        primary, alternate = native("middle", slot=99), native("middle", slot=101)
        pages = [page([("middle", 99, 1000)])]
        before = reconcile_placements([primary, alternate], page_receipts=pages)["middle"]
        self.assertEqual(before["slot_bounds"], {"bounded": True, "min": 99, "max": 101})
        missing = {**alternate, "raw": None}
        for rows in ([primary, missing], [missing, primary]):
            with self.subTest(first_archive=rows[0]["evidence_hash"]):
                placement = reconcile_placements(rows, page_receipts=pages)["middle"]
                self.assertTrue(placement["unbounded"])
                self.assertFalse(placement["slot_bounds"]["bounded"])
                self.assertIn(alternate["evidence_hash"], placement["evidence"])

    def test_r9_alternate_raw_cannot_overwrite_a_proven_saved_index_conflict(self):
        selected, alternate = native("middle", index=1), native("middle")
        for rows in ([selected, alternate], [alternate, selected]):
            with self.subTest(first_claim=rows[0].get("transaction_index")):
                result = assess_chronology(rows, block_receipts=[block(["middle", "other"])],
                                           checkpoint_indices={"middle": 0})
                self.assertEqual(result["transactions"]["middle"]["order_state"], "UNKNOWN")
                self.assertTrue(any(conflict["kind"] == "order" and conflict["field"] == "transaction_index"
                                    for conflict in result["conflicts"]))

    def test_r9_same_slot_index_envelope_includes_every_native_and_saved_claim(self):
        placement = reconcile_placements([native("middle", index=1)],
                                          block_receipts=[block(["middle", "a", "b"]), block(["a", "b", "middle"])],
                                          checkpoint_indices={"middle": 2})["middle"]
        self.assertEqual(placement["state"], "UNKNOWN")
        self.assertEqual(placement["indices_by_slot"]["100"],
                         {"bounded": True, "min": 0, "max": 2, "possible_indices": [0, 1, 2]})

    def test_r9_missing_or_invalid_index_expands_entire_slot(self):
        row = native("middle", index="invalid")
        placement = reconcile_placements([row], block_receipts=[block(["middle"])])["middle"]
        self.assertEqual(placement["state"], "UNKNOWN")
        self.assertFalse(placement["indices_by_slot"]["100"]["bounded"])
        missing = reconcile_placements([native("middle")])["middle"]
        self.assertFalse(missing["indices_by_slot"]["100"]["bounded"])

    def test_r9_block_membership_disagreement_does_not_supply_an_exclusion_index(self):
        placement = reconcile_placements([native("middle")],
                                          block_receipts=[block(["middle", "other"]), block(["other"])])["middle"]
        self.assertFalse(placement["indices_by_slot"]["100"]["bounded"])

    def test_block_order_does_not_expand_the_linked_transaction_population(self):
        result = assess_chronology([native("selected")], block_receipts=[block(["selected", "unrelated"])])
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(set(result["transactions"]), {"selected"})
        self.assertEqual(result["transactions"]["selected"]["transaction_index"], 0)

    def test_same_slot_distinct_native_times_remain_unknown_with_or_without_block_time(self):
        rows = [native("opening"), native("closing", timestamp=1000 + 6 * 3600)]
        for stamp in (MISSING, 1000):
            with self.subTest(optional_block_time=stamp):
                result = assess_chronology(rows, block_receipts=[block(["opening", "closing"], timestamp=stamp)])
                self.assertEqual(result["transactions"]["opening"]["time_state"], "UNKNOWN")
                self.assertEqual(result["transactions"]["closing"]["canonical_time"], None)
                self.assertEqual(result["transactions"]["opening"]["order_state"], "PASS")

    def test_absent_null_and_matching_optional_block_times_are_compatible(self):
        rows = [native("opening"), native("closing")]
        sources = [block(["opening", "closing"], timestamp=stamp) for stamp in (MISSING, None, 1000)]
        result = assess_chronology(rows, block_receipts=sources, checkpoint_indices={"opening": 0, "closing": 1})
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(result["transactions"]["closing"]["transaction_index"], 1)
        self.assertEqual(result["slots"]["100"]["canonical_time"], 1000)

    def test_single_transaction_explicit_block_time_contradiction_revokes_clock(self):
        result = assess_chronology([native("single")], page_receipts=[page([("single", 100, 1000)])],
                                   block_receipts=[block(["single"], timestamp=2000)])
        self.assertEqual(result["transactions"]["single"]["time_state"], "UNKNOWN")
        self.assertEqual(result["transactions"]["single"]["order_state"], "PASS")
        self.assertTrue(any(conflict["field"] == "blockTime" for conflict in result["conflicts"]))

    def test_conflicting_order_receipts_never_choose_first_or_last(self):
        rows = [native("opening"), native("closing")]
        sources = [block(["opening", "closing"]), block(["closing", "opening"])]
        for order in (sources, list(reversed(sources))):
            with self.subTest(receipt_order=order[0]["hash"]):
                result = assess_chronology(rows, block_receipts=order, checkpoint_indices={"opening": 0, "closing": 1})
                self.assertEqual(result["transactions"]["opening"]["order_state"], "UNKNOWN")
                self.assertIsNone(result["transactions"]["closing"]["transaction_index"])
                self.assertEqual(result["transactions"]["opening"]["time_state"], "PASS")

    def test_matching_selected_index_does_not_resolve_different_full_block_lists(self):
        result = assess_chronology([native("selected")],
                                   block_receipts=[block(["selected", "other-a"]), block(["selected", "other-b"])])
        self.assertEqual(result["transactions"]["selected"]["order_state"], "UNKNOWN")

    def test_semantically_identical_receipts_with_distinct_hashes_are_harmless(self):
        first = block(["opening", "closing"], timestamp=1000, envelope_id="first")
        second = block(["opening", "closing"], timestamp=1000, envelope_id="second")
        self.assertNotEqual(first["hash"], second["hash"])
        result = assess_chronology([native("opening"), native("closing")], block_receipts=[first, second, first])
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(result["transactions"]["closing"]["transaction_index"], 1)

    def test_checkpoint_indices_must_agree_with_actual_block_signature_order(self):
        result = assess_chronology([native("opening"), native("closing")],
                                   block_receipts=[block(["opening", "closing"])],
                                   checkpoint_indices={"opening": 1, "closing": 0})
        self.assertEqual(result["transactions"]["opening"]["order_state"], "UNKNOWN")
        self.assertTrue(any(conflict["field"] == "transaction_index" for conflict in result["conflicts"]))

    def test_duplicate_saved_indices_are_explicit_conflicts_without_block_proof(self):
        result = assess_chronology([native("opening"), native("closing")],
                                   checkpoint_indices={"opening": 0, "closing": 0})
        self.assertEqual(result["transactions"]["closing"]["order_state"], "UNKNOWN")
        self.assertTrue(any("same saved index" in conflict["reason"] for conflict in result["conflicts"]))

    def test_frozen_record_and_checkpoint_index_conflict_is_retained(self):
        result = assess_chronology([native("single", index=0)], checkpoint_indices={"single": 1})
        self.assertEqual(result["transactions"]["single"]["order_state"], "UNKNOWN")
        self.assertTrue(any("indices conflict" in conflict["reason"] for conflict in result["conflicts"]))

    def test_missing_same_slot_order_leaves_clock_known_and_order_unknown(self):
        result = assess_chronology([native("opening"), native("closing")])
        self.assertEqual(result["transactions"]["opening"]["time_state"], "PASS")
        self.assertEqual(result["transactions"]["opening"]["order_state"], "UNKNOWN")
        self.assertEqual(result["conflicts"], [])

    def test_malformed_block_for_known_later_slot_does_not_poison_prior_slot(self):
        malformed = receipt({"method": "getBlock", "slot": 200, "result": {"signatures": ["duplicate", "duplicate"]}})
        result = assess_chronology([native("earlier"), native("later", slot=200, timestamp=2000)], block_receipts=[malformed])
        self.assertEqual(result["transactions"]["earlier"]["state"], "PASS")
        self.assertEqual(result["transactions"]["later"]["order_state"], "UNKNOWN")
        self.assertEqual(result["slots"]["200"]["order_state"], "UNKNOWN")
        self.assertTrue(result["invalid_block_receipts"])

    def test_unassignable_malformed_source_is_global_issue_not_a_prior_slot_contradiction(self):
        malformed = receipt({"method": "getBlock", "result": None})
        result = assess_chronology([native("earlier")], block_receipts=[malformed])
        self.assertEqual(result["transactions"]["earlier"]["state"], "PASS")
        self.assertEqual(result["transactions"]["earlier"]["conflicts"], [])
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertIsNone(result["conflicts"][0]["slot"])

    def test_unselected_signature_page_clock_must_agree_with_same_slot_native_record(self):
        result = assess_chronology([native("selected")],
                                   page_receipts=[page([("selected", 100, 1000), ("unselected", 100, 1001)])])
        self.assertEqual(result["transactions"]["selected"]["time_state"], "UNKNOWN")

    def test_correcting_contradictory_block_time_recovers_without_changing_raw_selection(self):
        rows = [native("opening"), native("closing")]
        wrong = assess_chronology(rows, block_receipts=[block(["opening", "closing"], timestamp=2000)])
        corrected = assess_chronology(rows, block_receipts=[block(["opening", "closing"], timestamp=1000)])
        self.assertEqual(wrong["state"], "UNKNOWN")
        self.assertEqual(corrected["state"], "PASS")
        self.assertEqual(set(corrected["transactions"]), {"opening", "closing"})
