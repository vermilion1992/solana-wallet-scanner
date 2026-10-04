"""Development-only dependency controls using the existing analytical FIFO.

The explicit checks below exercise an internal adapter interface. They are not
provider records, real population witnesses or genuine wallet acceptance.
"""
from copy import deepcopy
import unittest

from scanner.accounting import analyze
from scanner.metric_evidence import apply_metric_decisions, compose_metric_decisions

START = '2026-01-01T00:00:00Z'
END = '2026-01-31T00:00:00Z'
COMPONENTS = (
    'historical_population', 'event_ownership', 'quantity_continuity', 'chronology',
    'acquisition_basis', 'economic_costs', 'classification', 'positions',
    'boundary_inventory', 'historical_marks', 'valued_external_flows',
    'selected_record_identity', 'native_fee', 'fee_window',
)
INTERVALS = ('report_period', 'four_weeks', 'verification_90d')


def check(number=1, **extra):
    return {'state': 'PASS', 'evidence': [f'{number:064x}'],
            'scope': 'Synthetic internal interface; not real acceptance', **extra}


def inputs():
    return ({name: check(index) for index, name in enumerate(COMPONENTS, 1)},
            {name: check(index) for index, name in enumerate(INTERVALS, 101)})


def episode(mint, day, cost, proceeds):
    common = {'mint': mint, 'quantity_raw': '100', 'decimals': 0,
              'classification': 'meme', 'paid_by_wallet': True,
              'evidence': ['f' * 64]}
    return [{**common, 'kind': 'buy', 'timestamp': f'2026-01-{day:02d}T00:00:00Z',
             'order': 1, 'signature': mint + '-buy', 'path': 'swap/0', 'amount_sol': cost},
            {**common, 'kind': 'sell', 'timestamp': f'2026-01-{day:02d}T06:00:00Z',
             'order': 2, 'signature': mint + '-sell', 'path': 'swap/0', 'amount_sol': proceeds}]


def calculation():
    # Independently worked: +1 SOL, -1 SOL, 0 SOL; three six-hour episodes.
    rows = episode('WIN', 5, '1', '2') + episode('LOSS', 10, '2', '1') + episode('EVEN', 15, '1', '1')
    result = analyze(rows, START, END, opening_equity='10', closing_equity='10',
                     external_deposits='0', external_withdrawals='0')
    result['metrics']['observed_network_fees_sol'] = {
        'value': '0.000015', 'status': 'known', 'unit': 'SOL',
        'population': 'Selected records only', 'evidence': ['e' * 64]}
    result['metrics']['observed_native_delta_sol'] = {
        'value': '-0.1', 'status': 'known', 'unit': 'SOL',
        'population': 'Independent selected endpoints', 'evidence': ['d' * 64]}
    return result


class MetricEvidenceTests(unittest.TestCase):
    def gated(self, components=None, intervals=None, result=None):
        baseline_components, baseline_intervals = inputs()
        components = baseline_components if components is None else components
        intervals = baseline_intervals if intervals is None else intervals
        result = calculation() if result is None else result
        return apply_metric_decisions(result, compose_metric_decisions(components, intervals))

    def test_supported_fifo_results_and_zero_profit_are_preserved(self):
        parent = calculation()
        child = self.gated(result=parent)
        self.assertEqual(child['metrics']['profit_sol']['value'], '0')
        self.assertEqual(child['metrics']['completed_positions']['value'], '3')
        self.assertEqual(child['metrics']['median_hold_hours']['value'], '6')
        self.assertEqual(child['metrics']['median_roi_pct']['value'], '0')
        self.assertEqual(child['metrics']['economic_pnl_sol']['value'], '0')
        self.assertEqual([row['pnl_sol'] for row in child['positions']], ['1', '-1', '0'])
        self.assertEqual(parent, calculation())
        self.assertIsNot(child, parent)

    def test_losing_wallet_remains_a_known_losing_result(self):
        result = analyze(episode('LOSS', 10, '2', '1'), START, END)
        child = self.gated(result=result)
        self.assertEqual(child['metrics']['profit_sol']['value'], '-1')
        self.assertEqual(child['metrics']['win_rate_pct']['value'], '0')
        self.assertEqual(child['metrics']['median_roi_pct']['value'], '-50')

    def test_missing_marks_only_revoke_dependent_economic_result(self):
        components, intervals = inputs()
        del components['historical_marks']
        child = self.gated(components, intervals)
        self.assertIsNone(child['metrics']['economic_pnl_sol']['value'])
        self.assertEqual(child['metrics']['profit_sol']['value'], '0')
        self.assertEqual(child['metrics']['median_roi_pct']['value'], '0')
        self.assertEqual(child['metrics']['observed_network_fees_sol']['value'], '0.000015')

    def test_missing_basis_preserves_quantity_timing_and_independent_equity(self):
        components, intervals = inputs()
        del components['acquisition_basis']
        child = self.gated(components, intervals)
        for name in ('profit_sol', 'realised_roi_pct', 'median_roi_pct', 'win_rate_pct', 'positive_weeks'):
            self.assertEqual(child['metrics'][name]['status'], 'unknown')
        self.assertEqual(child['metrics']['median_hold_hours']['value'], '6')
        self.assertEqual(child['metrics']['completed_positions']['value'], '3')
        self.assertEqual(child['metrics']['economic_pnl_sol']['value'], '0')
        self.assertEqual(child['metrics']['observed_network_fees_sol']['value'], '0.000015')

    def test_unknown_fifo_basis_is_never_promoted_by_passing_components(self):
        result = analyze([episode('UNKNOWN', 5, '1', '2')[1]], START, END)
        child = self.gated(result=result)
        self.assertEqual(child['metrics']['profit_sol']['status'], 'unknown')
        self.assertIsNone(child['metrics']['profit_sol']['value'])
        self.assertEqual(child['positions'], result['positions'])

    def test_missing_population_does_not_erase_selected_observations(self):
        components, intervals = inputs()
        del components['historical_population']
        child = self.gated(components, intervals)
        self.assertEqual(child['metrics']['profit_sol']['status'], 'unknown')
        self.assertEqual(child['metrics']['median_hold_hours']['status'], 'unknown')
        self.assertEqual(child['metrics']['observed_network_fees_sol']['value'], '0.000015')
        self.assertEqual(child['metrics']['observed_native_delta_sol']['value'], '-0.1')

    def test_28_day_loss_does_not_revoke_report_or_90_day_results(self):
        components, intervals = inputs()
        intervals['four_weeks'] = check(102, state='UNKNOWN', reason='Required 28-day source removed.')
        child = self.gated(components, intervals)
        self.assertEqual(child['metrics']['positive_weeks']['status'], 'unknown')
        self.assertTrue(all(row['status'] == 'unknown' for row in child['weekly']))
        self.assertEqual(child['metrics']['profit_sol']['value'], '0')
        self.assertEqual(child['metrics']['completed_positions_90d']['value'], '3')

    def test_90_day_loss_does_not_revoke_report_or_28_day_results(self):
        components, intervals = inputs()
        del intervals['verification_90d']
        child = self.gated(components, intervals)
        self.assertEqual(child['metrics']['completed_positions_90d']['status'], 'unknown')
        self.assertEqual(child['metrics']['completed_positions']['value'], '3')
        self.assertEqual(child['metrics']['positive_weeks']['status'], 'known')
        self.assertTrue(all(row['status'] == 'known' for row in child['weekly']))

    def test_report_period_loss_does_not_revoke_independent_28_or_90_days(self):
        components, intervals = inputs()
        del intervals['report_period']
        child = self.gated(components, intervals)
        self.assertEqual(child['metrics']['profit_sol']['status'], 'unknown')
        self.assertEqual(child['metrics']['positive_weeks']['status'], 'known')
        self.assertEqual(child['metrics']['completed_positions_90d']['status'], 'known')
        self.assertEqual(child['metrics']['observed_network_fees_sol']['status'], 'known')

    def test_component_interval_maps_do_not_borrow_missing_90_day_proof(self):
        components, intervals = inputs()
        components['positions'] = {'report_period': check(107), 'four_weeks': check(108)}
        child = self.gated(components, intervals)
        self.assertEqual(child['metrics']['completed_positions']['status'], 'known')
        self.assertEqual(child['metrics']['completed_positions_90d']['status'], 'unknown')

    def test_explicit_wrong_interval_receipt_is_not_reused(self):
        components, intervals = inputs()
        intervals['four_weeks'] = check(102, interval='report_period')
        decisions = compose_metric_decisions(components, intervals)
        self.assertEqual(decisions['positive_weeks']['state'], 'UNKNOWN')
        self.assertIn('different independent interval', decisions['positive_weeks']['reason'])
        self.assertEqual(decisions['profit_sol']['state'], 'PASS')

    def test_source_loss_restoration_and_parent_immutability(self):
        components, intervals = inputs()
        parent = calculation()
        frozen = deepcopy(parent)
        supported = self.gated(components, intervals, parent)
        original = components.pop('acquisition_basis')
        missing = self.gated(components, intervals, parent)
        components['acquisition_basis'] = original
        restored = self.gated(components, intervals, parent)
        self.assertEqual(parent, frozen)
        self.assertEqual(restored, supported)
        self.assertEqual(missing['metrics']['profit_sol']['status'], 'unknown')
        self.assertEqual(restored['metrics']['profit_sol']['status'], 'known')

    def test_no_component_or_interval_checks_cannot_pass_vacuously(self):
        decisions = compose_metric_decisions({}, {})
        self.assertTrue(all(row['state'] == 'UNKNOWN' for row in decisions.values()))
        self.assertTrue(all(row['unresolved_dependencies'] for row in decisions.values()))

    def test_malformed_or_unsupported_dependencies_are_unknown(self):
        variants = [None, [], True, {}, {'state': True, 'evidence': ['a' * 64]},
                    {'state': 'PASS', 'evidence': []}, {'state': 'PASS', 'evidence': ['not-a-hash']},
                    {'state': 'PASS', 'evidence': [['a' * 64]]},
                    check(supported=False), check(supported=1), check(unsupported=True),
                    check(reason={}), check(state='UNSUPPORTED', reason='Parser contract unavailable.'),
                    check(state='FAIL', reason='Conflicting required records.')]
        for value in variants:
            with self.subTest(check=value):
                components, intervals = inputs()
                components['acquisition_basis'] = value
                decisions = compose_metric_decisions(components, intervals)
                self.assertEqual(decisions['profit_sol']['state'], 'UNKNOWN')
                self.assertIn('acquisition_basis', decisions['profit_sol']['unresolved_dependencies'])
                self.assertEqual(decisions['median_hold_hours']['state'], 'PASS')

    def test_relevant_dependency_hashes_exclude_unrelated_marks_from_profit(self):
        components, intervals = inputs()
        decisions = compose_metric_decisions(components, intervals)
        marks_hash = components['historical_marks']['evidence'][0]
        self.assertNotIn(marks_hash, decisions['profit_sol']['evidence'])
        self.assertIn(marks_hash, decisions['economic_pnl_sol']['evidence'])
        self.assertIn(intervals['four_weeks']['evidence'][0], decisions['positive_weeks']['evidence'])
        self.assertNotIn(intervals['four_weeks']['evidence'][0], decisions['profit_sol']['evidence'])

    def test_permutation_and_irrelevant_component_do_not_change_decisions(self):
        components, intervals = inputs()
        expected = compose_metric_decisions(components, intervals)
        permuted = dict(reversed(list(components.items())))
        permuted['unrelated_current_market_price'] = {'state': 'UNKNOWN'}
        self.assertEqual(compose_metric_decisions(permuted, dict(reversed(list(intervals.items())))), expected)

    def test_fee_source_loss_revokes_fees_without_erasing_wallet_timing(self):
        components, intervals = inputs()
        components['fee_window'] = check(state='UNKNOWN', reason='Linked alternative crosses report end.')
        child = self.gated(components, intervals)
        self.assertIsNone(child['metrics']['observed_network_fees_sol']['value'])
        self.assertEqual(child['metrics']['median_hold_hours']['value'], '6')
        self.assertEqual(child['metrics']['profit_sol']['value'], '0')

    def test_missing_or_forged_application_decision_cannot_keep_known_profit(self):
        for decisions in ({}, {'profit_sol': {'state': 'PASS'}}, None):
            with self.subTest(decisions=decisions):
                parent = calculation()
                child = apply_metric_decisions(parent, decisions)
                self.assertEqual(child['metrics']['profit_sol']['status'], 'unknown')
                self.assertEqual(parent['metrics']['profit_sol']['status'], 'known')
                self.assertEqual(child['metrics']['observed_native_delta_sol']['status'], 'known')

    def test_observation_gate_requires_actual_known_numerical_result(self):
        components, intervals = inputs()
        observations = calculation()['metrics']
        observations['profit_sol'].update(status='unknown', value=None, reason='Missing disposed lot origin.')
        decisions = compose_metric_decisions(components, intervals, metric_observations=observations)
        self.assertEqual(decisions['profit_sol']['state'], 'UNKNOWN')
        self.assertIn('metric_observation', decisions['profit_sol']['unresolved_dependencies'])
        self.assertEqual(decisions['median_hold_hours']['state'], 'PASS')

    def test_unknown_week_count_preserves_independently_known_week_observation(self):
        components, intervals = inputs()
        result = calculation()
        result['weekly'][0].update(profit_sol=None, status='unknown', reason='One independently unresolved week.')
        result['metrics']['positive_weeks'].update(value=None, status='unknown', reason='One week remains unresolved.')
        decisions = compose_metric_decisions(components, intervals, metric_observations=result['metrics'])
        child = apply_metric_decisions(result, decisions)
        self.assertEqual(child['metrics']['positive_weeks']['status'], 'unknown')
        self.assertEqual(child['weekly'], result['weekly'])

    def test_malformed_known_number_is_not_promoted(self):
        components, intervals = inputs()
        decisions = compose_metric_decisions(components, intervals)
        for value in (True, 1.5, 'NaN', None):
            with self.subTest(value=value):
                result = calculation()
                result['metrics']['profit_sol'].update(status='known', value=value)
                child = apply_metric_decisions(result, decisions)
                self.assertEqual(child['metrics']['profit_sol']['status'], 'unknown')
                self.assertIsNone(child['metrics']['profit_sol']['value'])

    def test_metric_coverage_status_tracks_revoked_value(self):
        components, intervals = inputs()
        del components['positions']
        child = self.gated(components, intervals)
        self.assertEqual(child['metric_coverage']['completed_positions']['metric_status'], 'unknown')
        self.assertEqual(child['metric_coverage']['profit_sol']['metric_status'], 'known')


if __name__ == '__main__':
    unittest.main()
