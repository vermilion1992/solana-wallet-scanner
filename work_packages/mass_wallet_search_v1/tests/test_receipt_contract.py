"""Tests of the HANDOFF CHECKER, not the wallet scanner or real market data."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
from statistics import median
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('contract_checker', ROOT/'tools/check_receipt_contract.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class ReceiptContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.receipt = json.loads((ROOT/'fixtures/receipt.synthetic.example.json').read_text())
        data = (ROOT/'fixtures/synthetic_run_evidence.json').read_bytes()
        (self.root/'synthetic_run_evidence.json').write_bytes(data)

    def validate(self, profile='development'):
        return checker.validate(self.receipt, self.root, profile)

    def invalid(self):
        with self.assertRaises(checker.InvalidReceipt):
            self.validate()

    def live_label_contract_fixture(self):
        # These bytes remain SYNTHETIC. We exercise declaration logic, NOT origin
        # authentication. This test is why the checker cannot certify provenance.
        r = self.receipt
        r['corpus_kind'] = 'GENUINE_LIVE'
        r['artifacts'][0]['corpus_kind'] = 'GENUINE_LIVE'
        r['budget'].update(live_authorized=True, authorization_sha256='a'*64,
                           providers=[{'id':'test-provider','billing_unit':'test-units','used':10,'reserved':0,'limit':100}])
        r['measurements']['cold_live_seconds'] = 60
        return r

    def test_synthetic_development_contract_valid(self):
        self.assertEqual(self.validate()['state'], 'CONTRACT_VALID')

    def test_synthetic_is_incomplete_for_live(self):
        self.assertEqual(self.validate('live-search')['exit_code'], 2)

    def test_synthetic_is_incomplete_for_forward(self):
        self.assertEqual(self.validate('forward-operation')['exit_code'], 2)

    def test_synthetic_positive_live_claim_invalid(self):
        self.receipt['claims']['mass_search_proven'] = True
        self.invalid()

    def test_full_wallet_claim_forbidden(self):
        self.receipt['claims']['strict_full_wallet_ready'] = True
        self.invalid()

    def test_universe_count_mismatch(self):
        self.receipt['universe']['raw_rows'] += 1
        self.invalid()

    def test_stage_conservation_mismatch(self):
        self.receipt['stages'][0]['rejected'] -= 1
        self.invalid()

    def test_stage_input_must_equal_previous_promoted(self):
        self.receipt['stages'][1].update(input=201, deferred=51)
        self.invalid()

    def test_stage_order_is_fixed(self):
        self.receipt['stages'][0]['name'] = 'behaviour'
        self.invalid()

    def test_pending_cannot_be_complete(self):
        self.receipt['stages'][0].update(deferred=99, pending=1)
        self.invalid()

    def test_pending_allowed_in_partial(self):
        self.receipt['execution']['status'] = 'PARTIAL'
        self.receipt['stages'][0].update(deferred=99, pending=1)
        self.assertEqual(self.validate()['exit_code'], 0)

    def test_oversubscribed_budget(self):
        self.live_label_contract_fixture()
        self.receipt['budget']['providers'][0].update(used=99, reserved=2)
        self.invalid()

    def test_unauthorised_units(self):
        self.receipt['budget']['providers'] = [{'id':'test','billing_unit':'calls','used':1,'reserved':0,'limit':1}]
        self.invalid()

    def test_authorisation_hash_required(self):
        self.receipt['budget']['live_authorized'] = True
        self.invalid()

    def test_no_paid_spend_in_v1(self):
        self.live_label_contract_fixture()
        self.receipt['budget'].update(paid_spend_usd='1', paid_limit_usd='2')
        self.invalid()

    def test_paid_spend_over_cap(self):
        self.receipt['budget']['paid_spend_usd'] = '0.01'
        self.invalid()

    def test_refilter_no_external_requests(self):
        self.receipt['measurements']['refilter_external_requests'] = 1
        self.invalid()

    def test_booleans_are_not_counts(self):
        self.receipt['universe']['raw_rows'] = True
        self.invalid()

    def test_nonfinite_timing_rejected(self):
        self.receipt['measurements']['refilter_p95_ms'] = float('nan')
        self.invalid()

    def test_unknown_fields_rejected(self):
        self.receipt['claims']['guaranteed_profit'] = True
        self.invalid()

    def test_dirty_source_rejected(self):
        self.receipt['application']['dirty'] = True
        self.invalid()

    def test_short_git_hash_rejected(self):
        self.receipt['application']['commit'] = '123abcd'
        self.invalid()

    def test_late_selection_rejected(self):
        self.receipt['selection']['plan_frozen_at'] = '2026-01-02T00:00:00Z'
        self.invalid()

    def test_timezone_required(self):
        self.receipt['execution']['started_at'] = '2026-01-01T00:00:00'
        self.invalid()

    def test_tampered_artifact_rejected(self):
        (self.root/'synthetic_run_evidence.json').write_text('tampered')
        self.invalid()

    def test_missing_artifact_rejected(self):
        (self.root/'synthetic_run_evidence.json').unlink()
        self.invalid()

    def test_path_traversal_rejected(self):
        self.receipt['artifacts'][0]['path'] = '../synthetic_run_evidence.json'
        self.invalid()

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside)/'outside.json'
            target.write_text('not permitted')
            (self.root/'link.json').symlink_to(target)
            self.receipt['artifacts'][0]['path'] = 'link.json'
            self.receipt['artifacts'][0]['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
            self.invalid()

    def test_duplicate_artifact_rejected(self):
        self.receipt['artifacts'].append(deepcopy(self.receipt['artifacts'][0]))
        self.invalid()

    def test_duplicate_json_keys_rejected(self):
        path = self.root/'duplicate.json'
        path.write_text('{"x":1,"x":2}')
        with self.assertRaises(checker.InvalidReceipt):
            checker.load_receipt(path)

    def test_nonfinite_json_constant_rejected(self):
        path = self.root/'nan.json'
        path.write_text('{"x": NaN}')
        with self.assertRaises(checker.InvalidReceipt):
            checker.load_receipt(path)

    def test_live_label_structure_can_pass_but_disclaimer_required(self):
        self.live_label_contract_fixture()
        result = self.validate('live-search')
        self.assertEqual(result['exit_code'], 0)
        self.assertIn('provenance', result['disclaimer'])
        self.assertIn('separate review', result['disclaimer'])

    def test_live_candidate_target_not_met(self):
        self.live_label_contract_fixture()
        self.receipt['universe'].update(raw_rows=1019, unique_candidates=999)
        self.receipt['stages'][0].update(input=999, rejected=699)
        self.assertEqual(self.validate('live-search')['exit_code'], 2)

    def test_live_reports_need_minimum_population(self):
        self.live_label_contract_fixture()
        self.receipt['analytics']['min_closed_observed_episodes_per_report'] = 9
        self.assertEqual(self.validate('live-search')['exit_code'], 2)

    def test_replay_does_not_prove_fresh_acquisition(self):
        self.receipt['corpus_kind'] = 'GENUINE_REPLAY'
        self.receipt['artifacts'][0]['corpus_kind'] = 'GENUINE_REPLAY'
        self.assertEqual(self.validate('live-search')['exit_code'], 2)

    def test_zero_signal_cannot_claim_operational_success(self):
        self.live_label_contract_fixture()
        self.receipt['claims']['forward_operational_proven'] = True
        self.invalid()

    def test_forward_contract_minimums(self):
        self.live_label_contract_fixture()
        self.receipt['selection'].update(cohort_frozen_at='2026-01-01T00:00:31Z', cohort_sha256='b'*64)
        self.receipt['forward'].update(state='COMPLETE', selection_frozen_before_observation=True,
            started_at='2026-01-01T00:00:32Z', signal_count=2, quote_count=2, closed_positions=1)
        self.assertEqual(self.validate('forward-operation')['exit_code'], 0)

    def test_forward_early_start_invalid(self):
        self.receipt['forward'].update(state='RUNNING', started_at='2025-01-01T00:00:00Z')
        self.invalid()


    def test_cohort_cannot_precede_universe_sealing(self):
        self.receipt['selection'].update(cohort_frozen_at='2026-01-01T00:00:01Z', cohort_sha256='b'*64)
        self.invalid()

    def test_plan_freeze_is_not_cohort_freeze(self):
        self.live_label_contract_fixture()
        self.receipt['forward'].update(state='RUNNING', started_at='2026-01-01T00:00:40Z')
        self.invalid()

    def test_cohort_hash_and_timestamp_required_together(self):
        self.receipt['selection']['cohort_sha256'] = 'b'*64
        self.invalid()

    def test_example_top_level_fields_match_json_schema(self):
        schema = json.loads((ROOT/'contracts/benchmark_receipt.schema.json').read_text())
        self.assertEqual(set(schema['required']), set(self.receipt))


class FixtureArithmeticTests(unittest.TestCase):
    def setUp(self):
        vectors = json.loads((ROOT/'fixtures/acceptance_cases.json').read_text())
        self.cases = {c['id']:c for c in vectors['cases']}
        self.assertEqual(vectors['corpus_kind'], 'SYNTHETIC')

    def test_manually_specified_fee_and_tail_expectations(self):
        case = self.cases['fees_and_dust_tail']
        events, expected = case['inputs']['events'], case['expected']
        buy = events[0]
        unit_basis = (Decimal(buy['consideration_sol'])+Decimal(buy['wallet_fee_sol'])) / Decimal(buy['units'])
        profits = []
        weighted = Decimal(0)
        for index, sale in enumerate(events[1:]):
            basis = unit_basis * Decimal(sale['units'])
            profit = Decimal(sale['consideration_sol'])-basis-Decimal(sale['wallet_fee_sol'])
            self.assertEqual(basis, Decimal(expected['sale_fifo_basis_sol'][index]))
            self.assertEqual(profit, Decimal(expected['sale_net_profit_sol'][index]))
            profits.append(profit)
            weighted += Decimal(sale['units'])*Decimal(sale['seconds_from_start'])
        self.assertEqual(sum(profits), Decimal(expected['total_profit_sol']))
        self.assertEqual(weighted/Decimal(buy['units']), Decimal(expected['quantity_weighted_exit_seconds']))

    def test_median_expectation(self):
        case = self.cases['median_not_average']
        actual = median(Decimal(x) for x in case['inputs']['eligible_closed_hold_hours'])
        self.assertEqual(actual, Decimal(case['expected']['median_hold_hours']))

    def test_weekly_expectation(self):
        case = self.cases['weekly_consistency']
        vals = [Decimal(x) for x in case['inputs']['complete_independent_week_net_sol']]
        self.assertEqual(sum(vals), Decimal(case['expected']['four_week_net_sol']))
        self.assertEqual(sum(v > 0 for v in vals), case['expected']['positive_weeks'])


if __name__ == '__main__':
    unittest.main()
