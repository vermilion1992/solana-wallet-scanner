"""Exact semantic fact controls; synthetic fixtures are not mainnet proof."""
from copy import deepcopy
import hashlib
import json
import unittest

from scanner.source_consistency import (assess_source_consistency, index_source_links,
                                        merge_source_manifests, source_index_receipt, SOURCE_HASH_LIMIT)
from scanner.providers import TOKEN_PROGRAM, TOKEN_2022_PROGRAM

WALLET, ACCOUNT, MINT, POOL = "wallet", "token-account", "mint", "pool"


def native():
    def balance(amount):
        return {"accountIndex": 1, "owner": WALLET, "mint": MINT, "programId": TOKEN_PROGRAM,
                "uiTokenAmount": {"amount": str(amount), "decimals": 6}}
    return {"slot": 100, "blockTime": 1000,
            "transaction": {"signatures": ["purchase"], "message": {"accountKeys": [WALLET, ACCOUNT, POOL], "instructions": []}},
            "meta": {"err": None, "fee": 5000, "preBalances": [100000, 2000, 2000],
                     "postBalances": [95000, 2000, 2000], "preTokenBalances": [balance(0)],
                     "postTokenBalances": [balance(100)], "innerInstructions": [{"index": 0, "instructions": [
                         {"programId": TOKEN_PROGRAM, "parsed": {"type": "transferChecked", "info": {
                             "source": POOL, "destination": ACCOUNT, "mint": MINT,
                             "tokenAmount": {"amount": "100", "decimals": 6}}}}]}]}}


def linked(raw):
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"signature": "purchase", "evidence_hash": digest, "raw": raw}


class SourceConsistencyTests(unittest.TestCase):
    def result(self, records, wallet=WALLET):
        return assess_source_consistency(records, accounts={"purchase": [ACCOUNT]}, wallet=wallet)

    def account(self, result):
        return result["transactions"]["purchase"]["accounts"][ACCOUNT]

    def test_absolute_inventory_conflict_is_not_resolved_by_equal_transfer_delta(self):
        original, alternative = native(), native()
        for phase in ("preTokenBalances", "postTokenBalances"):
            row = alternative["meta"][phase][0]["uiTokenAmount"]
            row["amount"] = str(int(row["amount"]) + 200)
        records = [linked(original), linked(alternative)]
        for order in (records, records[::-1]):
            with self.subTest(first_hash=order[0]["evidence_hash"]):
                result = self.result(order)
                scope = self.account(result)
                self.assertEqual(result["state"], "UNKNOWN")
                self.assertEqual(scope["checks"]["pre_quantity"]["status"], "conflict")
                self.assertEqual(scope["checks"]["post_quantity"]["status"], "conflict")
                self.assertEqual(len(scope["native_hashes"]), 2)
                self.assertTrue(all(row["paths"] for row in scope["source_paths"]))
                self.assertEqual(result["transactions"]["purchase"]["native"]["wallet_network_fees_sol"]["state"], "PASS")

    def test_optional_logs_and_duplicate_links_are_semantically_idempotent(self):
        original, alternative = native(), native()
        alternative["meta"].update(logMessages=[], optionalProviderField={"foo": "bar"})
        one, two = linked(original), linked(alternative)
        result = self.result([one, two, one, two])
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(self.account(result)["native_hashes"], sorted([one["evidence_hash"], two["evidence_hash"]]))

    def test_same_linked_source_set_has_deterministic_fact_and_conflict_serialization(self):
        original, alternative = native(), native()
        alternative["meta"]["preTokenBalances"][0]["uiTokenAmount"]["amount"] = "200"
        sources = [linked(original), linked(alternative)]
        self.assertEqual(self.result(sources), self.result(sources[::-1]))

    def test_account_key_and_balance_order_normalize_to_resolved_pubkeys(self):
        original, alternative = native(), native()
        other = {**deepcopy(original["meta"]["preTokenBalances"][0]), "accountIndex": 2, "owner": POOL}
        for raw in (original, alternative):
            for name in ("preTokenBalances", "postTokenBalances"):
                raw["meta"][name].append(deepcopy(other))
        alternative["transaction"]["message"]["accountKeys"] = [WALLET, POOL, ACCOUNT]
        for name in ("preBalances", "postBalances"):
            alternative["meta"][name][1:] = alternative["meta"][name][1:][::-1]
        for name in ("preTokenBalances", "postTokenBalances"):
            for row in alternative["meta"][name]:
                row["accountIndex"] = 3 - row["accountIndex"]
            alternative["meta"][name].reverse()
        result = self.result([linked(original), linked(alternative)])
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(self.account(result)["checks"]["pre_quantity"]["facts"][0]["value"], "0")

    def test_identity_fields_and_explicit_execution_are_independent_conflicts(self):
        for field, value in (("owner", POOL), ("mint", "different-mint"), ("programId", TOKEN_2022_PROGRAM), ("decimals", 9), ("err", {"InstructionError": [0, "Custom"]})):
            with self.subTest(field=field):
                alternative = native()
                if field == "err":
                    alternative["meta"]["err"] = value
                elif field == "decimals":
                    alternative["meta"]["preTokenBalances"][0]["uiTokenAmount"][field] = value
                else:
                    alternative["meta"]["preTokenBalances"][0][field] = value
                check = self.account(self.result([linked(native()), linked(alternative)]))["checks"]["program" if field == "programId" else "execution" if field == "err" else field]
                self.assertEqual(check["status"], "conflict")
                self.assertEqual(check["state"], "UNKNOWN")

    def test_missing_fact_is_not_an_explicit_zero_or_conflict(self):
        alternative = native()
        alternative["meta"]["preTokenBalances"][0]["uiTokenAmount"].pop("amount")
        scope = self.account(self.result([linked(native()), linked(alternative)]))
        self.assertEqual(scope["checks"]["pre_quantity"]["status"], "missing")
        self.assertEqual(scope["checks"]["post_quantity"]["state"], "PASS")
        self.assertFalse(scope["conflicts"])

    def test_missing_archive_retains_hash_and_revokes_native_and_account_groups(self):
        primary = linked(native())
        missing = {"signature": "purchase", "evidence_hash": "missing-alternative", "raw": None}
        result = self.result([primary, missing])
        scope = self.account(result)
        self.assertEqual(scope["state"], "UNKNOWN")
        self.assertIn("missing-alternative", scope["native_hashes"])
        self.assertTrue(any(row["hash"] == "missing-alternative" for row in scope["source_paths"]))
        self.assertEqual(result["transactions"]["purchase"]["native"]["wallet_network_fees_sol"]["state"], "UNKNOWN")

    def test_optional_program_annotations_use_each_archives_parsed_token_operations(self):
        alternative = native()
        for name in ("preTokenBalances", "postTokenBalances"):
            alternative["meta"][name][0].pop("programId")
        result = self.result([linked(native()), linked(alternative)])
        check = self.account(result)["checks"]["program"]
        self.assertEqual(check["state"], "PASS")
        self.assertTrue(any("innerInstructions" in fact["path"] for fact in check["facts"]))

    def test_duplicate_scoped_balance_row_is_missing_proof_and_never_last_wins(self):
        alternative = native()
        alternative["meta"]["preTokenBalances"] += deepcopy(alternative["meta"]["preTokenBalances"])
        scope = self.account(self.result([linked(native()), linked(alternative)]))
        self.assertEqual(scope["checks"]["pre_quantity"]["status"], "missing")
        self.assertEqual(scope["state"], "UNKNOWN")

    def test_exact_unsigned_quantity_domain_and_large_integer_precision(self):
        for amount, expected in ((str(2**64 - 1), "PASS"), (str(2**64), "UNKNOWN"), (True, "UNKNOWN"), ("1.0", "UNKNOWN"), ("000100", "PASS")):
            with self.subTest(amount=amount):
                raw = native()
                raw["meta"]["postTokenBalances"][0]["uiTokenAmount"]["amount"] = amount
                check = self.account(self.result([linked(raw)]))["checks"]["post_quantity"]
                self.assertEqual(check["state"], expected)
                if amount == str(2**64 - 1):
                    self.assertEqual(check["facts"][0]["value"], str(2**64 - 1))

    def test_other_account_inventory_conflict_does_not_veto_scoped_token_or_native_facts(self):
        original, alternative = native(), native()
        for raw in (original, alternative):
            for name in ("preTokenBalances", "postTokenBalances"):
                row = deepcopy(raw["meta"][name][0])
                row.update(accountIndex=2, owner=POOL)
                raw["meta"][name].append(row)
        alternative["meta"]["preTokenBalances"][1]["uiTokenAmount"]["amount"] = "200"
        result = self.result([linked(original), linked(alternative)])
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(self.account(result)["state"], "PASS")
        self.assertEqual(result["transactions"]["purchase"]["native"]["wallet_network_fees_sol"]["state"], "PASS")

    def test_native_fee_and_wallet_endpoint_conflicts_have_separate_dependencies(self):
        for change, fee_state, delta_state in (("fee", "UNKNOWN", "PASS"), ("endpoint", "PASS", "UNKNOWN"), ("both", "UNKNOWN", "UNKNOWN")):
            with self.subTest(change=change):
                alternative = native()
                if change in ("fee", "both"):
                    alternative["meta"]["fee"] += 1000
                    alternative["meta"]["postBalances"][2] -= 1000
                if change in ("endpoint", "both"):
                    alternative["meta"]["postBalances"][0] -= 500
                    alternative["meta"]["postBalances"][2] += 500
                result = self.result([linked(native()), linked(alternative)])["transactions"]["purchase"]["native"]
                self.assertEqual(result["wallet_network_fees_sol"]["state"], fee_state)
                self.assertEqual(result["native_wallet_delta_sol"]["state"], delta_state)

    def test_native_conservation_and_failed_atomicity_remain_required(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                alternative = native()
                if failed:
                    alternative["meta"].update(err="failed", postBalances=[94000, 2500, 2500])
                else:
                    alternative["meta"]["postBalances"][0] += 1
                result = self.result([linked(native()), linked(alternative)])["transactions"]["purchase"]["native"]
                self.assertEqual(result["wallet_network_fees_sol"]["state"], "UNKNOWN")
                self.assertEqual(result["native_wallet_delta_sol"]["state"], "UNKNOWN")

    def test_absent_wallet_is_no_transaction_change_without_invented_balance_zero(self):
        result = self.result([linked(native())], wallet="unrelated-wallet")
        native_scope = result["transactions"]["purchase"]["native"]
        self.assertEqual(native_scope["native_wallet_delta_sol"]["state"], "PASS")
        fact = native_scope["checks"]["wallet_pre"]["facts"][0]
        self.assertEqual(fact["status"], "not_applicable")
        self.assertIsNone(fact["value"])
        self.assertEqual(fact["path"], "transaction.message.accountKeys")

    def test_complete_actual_duplicate_manifest_includes_the_last_distinct_fact(self):
        primary = linked(native())
        alternative = native()
        alternative["meta"]["preTokenBalances"][0]["uiTokenAmount"]["amount"] = "200"
        last = linked(alternative)
        first_ref = {"kind": "transaction", "hash": primary["evidence_hash"], "signature": "purchase"}
        last_ref = {"kind": "transaction", "hash": last["evidence_hash"], "signature": "purchase"}
        manifest = [first_ref] * SOURCE_HASH_LIMIT + [last_ref]
        index = index_source_links(manifest, authenticated_references=manifest)
        self.assertEqual(len(index["hashes_to_inspect"]), 2)
        result = assess_source_consistency([primary, last], accounts={"purchase": [ACCOUNT]}, wallet=WALLET,
                                           source_index=index, inspected_hashes=index["hashes_to_inspect"])
        self.assertTrue(result["source_set"]["complete"])
        self.assertEqual(result["source_set"]["raw_reference_count"], 40_001)
        self.assertEqual(self.account(result)["checks"]["pre_quantity"]["status"], "conflict")

    def test_actual_unique_hash_budget_never_admits_a_convenient_prefix(self):
        for count, complete in ((SOURCE_HASH_LIMIT, True), (SOURCE_HASH_LIMIT + 1, False)):
            with self.subTest(count=count):
                refs = [{"kind": "snapshot-slot", "hash": f"{index:064x}"} for index in range(count)]
                index = index_source_links(refs, authenticated_references=refs)
                receipt = source_index_receipt(index, index["hashes_to_inspect"])
                self.assertEqual(receipt["complete"], complete)
                self.assertEqual(receipt["inspected_hash_count"], count if complete else 0)
                self.assertEqual(receipt["omitted_hash_count"], 0 if complete else count)

    def test_saved_manifest_union_keeps_alternative_roles_and_raw_multiplicity(self):
        shared = {"kind": "transaction", "hash": "a" * 64, "signature": "purchase"}
        other = {"kind": "transaction", "hash": "b" * 64, "signature": "purchase"}
        mirrored = [shared] * SOURCE_HASH_LIMIT
        merged = merge_source_manifests(mirrored, mirrored)
        self.assertEqual(len(merged), SOURCE_HASH_LIMIT)
        merged = merge_source_manifests(mirrored, [*mirrored, other])
        self.assertEqual(len(merged), SOURCE_HASH_LIMIT + 1)
        self.assertIn(other, merged)
        role = {**shared, "kind": "block-order"}
        self.assertEqual(len(merge_source_manifests([shared], [role])), 2)

    def test_authenticated_universe_omissions_and_unknown_roles_are_not_complete(self):
        reference = {"kind": "transaction", "hash": "a" * 64, "signature": "purchase"}
        for auth in ([reference, {**reference, "signature": "other"}], [reference, None],
                     [reference, {"kind": "unsupported-provider-role", "hash": "b" * 64}]):
            with self.subTest(auth=auth):
                index = index_source_links([reference], authenticated_references=auth)
                self.assertFalse(source_index_receipt(index, index["hashes_to_inspect"])["complete"])

    def test_page_execution_conflict_withholds_quantity_but_not_an_immaterial_wallet_projection(self):
        source = linked(native())
        page_hash = "c" * 64
        page = {"hash": page_hash, "payload": {"method": "getSignaturesForAddress", "result": [
            {"signature": "purchase", "err": {"InstructionError": [0, "failed"]}}]}}
        result = assess_source_consistency([source], accounts={"purchase": [ACCOUNT]}, wallet=WALLET, page_receipts=[page])
        self.assertEqual(self.account(result)["checks"]["execution"]["status"], "conflict")
        self.assertIn(page_hash, self.account(result)["evidence"])
        native_scope = result["transactions"]["purchase"]["native"]
        self.assertEqual(native_scope["wallet_network_fees_sol"]["state"], "PASS")
        self.assertEqual(native_scope["native_wallet_delta_sol"]["state"], "PASS")
        moved = native()
        moved["meta"]["postBalances"][0] -= 1000
        moved["meta"]["postBalances"][2] += 1000
        result = assess_source_consistency([linked(moved)], wallet=WALLET, page_receipts=[page])
        delta = result["transactions"]["purchase"]["native"]["native_wallet_delta_sol"]
        self.assertEqual(delta["state"], "UNKNOWN")
        self.assertIn(page_hash, delta["evidence"])
