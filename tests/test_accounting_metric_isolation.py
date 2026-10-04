"""Worked normalized-input contracts, not a genuine-wallet acceptance case.

These cases isolate cost evidence from evidenced acquisition quantities/clocks.
The production raw-source gates still have to establish each population.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from scanner.accounting import METHODOLOGY, analyze


START = '2026-01-01T00:00:00Z'
END = '2026-01-31T00:00:00Z'
BUY = '2026-01-05T00:00:00Z'
SELL = '2026-01-05T02:00:00Z'


def trade(kind, timestamp, amount, quantity='10', mint='A', **changes):
    return {'kind': kind, 'timestamp': timestamp, 'order': 1,
            'mint': mint, 'quantity_raw': quantity, 'decimals': 6,
            'classification': 'meme', 'amount_sol': amount, 'fee_sol': '0',
            'evidence': ['a' * 64], **changes}


def pair(cost='1', proceeds='1.2', **buy_changes):
    return [trade('buy', BUY, cost, **buy_changes), trade('sell', SELL, proceeds)]


class AccountingMetricIsolationTests(unittest.TestCase):
    def value(self, result, metric):
        return result['metrics'][metric]['value']

    def assert_quantity_population(self, result, *, count='1', hold='2', buys='1', sells='1'):
        for key, expected in {'completed_positions': count, 'completed_positions_90d': count,
                              'median_hold_hours': hold, 'avg_buys': buys, 'avg_sells': sells}.items():
            with self.subTest(metric=key):
                self.assertEqual(self.value(result, key), expected)
                self.assertEqual(result['metrics'][key]['status'], 'known')

    def assert_money_unknown(self, result):
        for key in ('profit_sol', 'realised_roi_pct', 'median_roi_pct', 'win_rate_pct',
                    'largest_contribution_pct'):
            with self.subTest(metric=key):
                self.assertIsNone(self.value(result, key))
                self.assertEqual(result['metric_domains'][key]['status'], 'unknown')

    def test_missing_buy_money_preserves_zero_sale_quantity_and_holding_population(self):
        result = analyze(pair(cost=None, proceeds='0'), START, END)
        self.assert_quantity_population(result)
        self.assert_money_unknown(result)
        self.assertEqual(self.value(result, 'rapid_sale_pct'), '0')
        position = result['positions'][0]
        self.assertEqual(position['status'], 'unresolved')  # Legacy monetary status.
        self.assertEqual(result['counts']['unresolved'], 1)
        self.assertEqual(position['cohort_quantity_status'], 'known')
        self.assertEqual(position['monetary_status'], 'unknown')
        self.assertEqual(position['quantity_raw'], '0')
        self.assertEqual(position['hold_hours'], '2')
        self.assertEqual(position['first_sale_status'], 'known')

    def test_missing_entry_fee_revokes_money_without_revoking_closure(self):
        result = analyze(pair(fee_sol=None), START, END)
        self.assert_quantity_population(result)
        self.assert_money_unknown(result)
        self.assertEqual(self.value(result, 'rapid_sale_pct'), '0')

    def test_missing_exit_fee_revokes_money_without_revoking_closure(self):
        rows = pair()
        rows[1]['fee_sol'] = None
        result = analyze(rows, START, END)
        self.assert_quantity_population(result)
        self.assert_money_unknown(result)
        self.assertEqual(self.value(result, 'rapid_sale_pct'), '0')

    def test_unknown_sale_money_preserves_hold_but_not_first_positive_sale(self):
        result = analyze(pair(proceeds=None), START, END)
        self.assert_quantity_population(result)
        self.assert_money_unknown(result)
        self.assertIsNone(self.value(result, 'rapid_sale_pct'))
        self.assertEqual(result['positions'][0]['first_sale_status'], 'unknown')

    def test_unknown_earlier_proceeds_cannot_hide_a_rapid_positive_sale(self):
        rows = [trade('buy', BUY, '1'),
                trade('sell', '2026-01-05T00:02:00Z', None, quantity='5'),
                trade('sell', SELL, '1.2', quantity='5')]
        result = analyze(rows, START, END)
        self.assert_quantity_population(result, sells='2')
        self.assertIsNone(self.value(result, 'rapid_sale_pct'))
        self.assertEqual(result['positions'][0]['first_sale_hours'], '2')
        self.assertEqual(result['positions'][0]['first_sale_status'], 'unknown')

    def test_unknown_later_proceeds_does_not_erase_proved_first_positive_sale(self):
        rows = [trade('buy', BUY, '1'),
                trade('sell', '2026-01-05T00:03:00Z', '0.5', quantity='5'),
                trade('sell', SELL, None, quantity='5')]
        result = analyze(rows, START, END)
        self.assert_quantity_population(result, sells='2')
        self.assert_money_unknown(result)
        self.assertEqual(self.value(result, 'rapid_sale_pct'), '100')
        self.assertEqual(result['positions'][0]['first_sale_hours'], '0.05')
        self.assertEqual(result['positions'][0]['first_sale_status'], 'known')

    def test_sponsored_unknown_fee_is_known_zero_wallet_cost(self):
        result = analyze(pair(fee_sol=None, paid_by_wallet=False), START, END)
        self.assert_quantity_population(result)
        self.assertEqual(self.value(result, 'profit_sol'), '0.2')
        self.assertEqual(self.value(result, 'median_roi_pct'), '20')
        self.assertEqual(result['positions'][0]['monetary_status'], 'known')

    def test_unallocated_fee_loss_is_independent_of_episode_win_and_hold(self):
        rows = pair() + [{'kind': 'fee', 'timestamp': '2026-01-06T00:00:00Z',
                          'amount_sol': None, 'paid_by_wallet': True, 'evidence': ['b' * 64]}]
        result = analyze(rows, START, END)
        self.assert_quantity_population(result)
        self.assertIsNone(self.value(result, 'profit_sol'))
        self.assertEqual(self.value(result, 'win_rate_pct'), '100')
        self.assertEqual(self.value(result, 'median_roi_pct'), '20')

    def test_cost_loss_restoration_is_monotonic_and_does_not_mutate_events(self):
        rows = pair()
        original = deepcopy(rows)
        known = analyze(rows, START, END)
        missing_rows = deepcopy(rows)
        missing_rows[0]['amount_sol'] = None
        missing = analyze(missing_rows, START, END)
        restored = analyze(rows, START, END)
        self.assertEqual(known, restored)
        self.assertEqual(rows, original)
        self.assert_quantity_population(missing)
        self.assert_money_unknown(missing)
        for key in ('median_hold_hours', 'completed_positions', 'completed_positions_90d',
                    'avg_buys', 'avg_sells', 'rapid_sale_pct'):
            with self.subTest(metric=key):
                self.assertEqual(missing['metrics'][key], known['metrics'][key])

    def test_unknown_exit_money_does_not_delete_supported_remaining_cost(self):
        for changes in ({'amount_sol': None}, {'fee_sol': None}):
            with self.subTest(changes=changes):
                rows = [trade('buy', BUY, '1'), trade('sell', SELL, '1', quantity='5', **changes)]
                result = analyze(rows, START, END)
                position = result['positions'][0]
                self.assertEqual(position['monetary_status'], 'unknown')
                self.assertIsNone(position['basis_sol'])  # Legacy monetary projection.
                self.assertEqual(position['acquisition_basis_status'], 'known')
                self.assertEqual(position['known_basis_sol'], '1')
                self.assertEqual(position['known_matched_basis_sol'], '0.5')
                self.assertEqual(position['remaining_basis_status'], 'known')
                self.assertEqual(position['remaining_basis_sol'], '0.5')
                self.assertEqual(position['quantity_raw'], '5')

    def test_unknown_opening_inventory_keeps_quantity_population_unknown(self):
        result = analyze([trade('sell', SELL, '1')], START, END)
        for key in ('median_hold_hours', 'completed_positions', 'completed_positions_90d',
                    'avg_buys', 'avg_sells', 'rapid_sale_pct'):
            with self.subTest(metric=key):
                self.assertIsNone(self.value(result, key))
                self.assertEqual(result['metric_domains'][key]['status'], 'unknown')
        self.assertEqual(result['positions'][0]['cohort_quantity_status'], 'unknown')

    def test_quantity_shortfall_is_not_treated_as_cost_only_uncertainty(self):
        rows = [trade('buy', BUY, None, quantity='5'), trade('sell', SELL, '1', quantity='10')]
        result = analyze(rows, START, END)
        self.assertIsNone(self.value(result, 'completed_positions'))
        self.assertIsNone(self.value(result, 'median_hold_hours'))
        self.assertEqual(result['positions'][0]['cohort_quantity_status'], 'unknown')

    def test_transferred_origin_and_transfer_exit_still_interrupt_cohort(self):
        for kind, rows in (
                ('transfer_in', [trade('transfer_in', BUY, None, basis_sol='1'), trade('sell', SELL, '2')]),
                ('transfer_out', [trade('buy', BUY, '1'), trade('transfer_out', SELL, None)])):
            with self.subTest(kind=kind):
                result = analyze(rows, START, END)
                self.assertIsNone(self.value(result, 'completed_positions'))
                self.assertIsNone(self.value(result, 'median_hold_hours'))
                self.assertEqual(result['positions'][0]['cohort_quantity_status'], 'unknown')

    def test_partial_history_cannot_gain_a_known_quantity_population(self):
        result = analyze(pair(cost=None), START, END, history_complete=False)
        self.assertIsNone(self.value(result, 'completed_positions'))
        self.assertIsNone(self.value(result, 'median_hold_hours'))
        self.assertEqual(result['positions'][0]['cohort_quantity_status'], 'unknown')
        self.assertEqual(result['positions'][0]['hold_hours'], '2')  # Conditional raw observation.

    def test_ambiguous_clocks_and_unsupported_activity_block_quantity_population(self):
        cases = [
            [trade('buy', BUY, None), trade('sell', BUY, '1')],
            [trade('buy', None, None), trade('sell', SELL, '1')],
            pair(cost=None) + [{'kind': 'unsupported', 'timestamp': SELL, 'reason': 'Unknown route'}],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                result = analyze(rows, START, END)
                self.assertIsNone(self.value(result, 'completed_positions'))
                self.assertIsNone(self.value(result, 'median_hold_hours'))
                self.assertIsNone(self.value(result, 'rapid_sale_pct'))

    def test_unknown_or_conflicting_classification_still_blocks_eligible_population(self):
        for buy_class, sell_class in (('unknown', 'unknown'), ('meme', 'unknown'), ('meme', 'settlement')):
            with self.subTest(classification=(buy_class, sell_class)):
                rows = pair(cost=None)
                rows[0]['classification'], rows[1]['classification'] = buy_class, sell_class
                result = analyze(rows, START, END)
                self.assertIsNone(self.value(result, 'completed_positions'))
                self.assertIsNone(self.value(result, 'median_hold_hours'))

    def test_partial_exit_missing_cost_is_open_not_a_completed_episode(self):
        rows = [trade('buy', BUY, None), trade('sell', SELL, '1', quantity='5')]
        result = analyze(rows, START, END)
        self.assertEqual(self.value(result, 'completed_positions'), '0')
        self.assertEqual(self.value(result, 'completed_positions_90d'), '0')
        self.assertIsNone(self.value(result, 'median_hold_hours'))
        self.assertEqual(result['metric_domains']['median_hold_hours']['status'], 'undefined')
        self.assertIsNone(self.value(result, 'profit_sol'))
        self.assertEqual(result['positions'][0]['quantity_raw'], '5')

    def test_missing_cost_on_open_episode_does_not_erase_other_completed_episode_money(self):
        rows = pair() + [trade('buy', '2026-01-06T00:00:00Z', None, mint='B')]
        result = analyze(rows, START, END)
        self.assert_quantity_population(result)
        self.assertEqual(self.value(result, 'win_rate_pct'), '100')
        self.assertEqual(self.value(result, 'median_roi_pct'), '20')
        self.assertEqual(self.value(result, 'profit_sol'), '0.2')

    def test_reentry_keeps_unknown_money_episode_in_quantity_denominator(self):
        rows = [trade('buy', BUY, None), trade('sell', SELL, '0.8'),
                trade('buy', '2026-01-06T00:00:00Z', '1'),
                trade('sell', '2026-01-06T04:00:00Z', '1')]
        result = analyze(rows, START, END)
        self.assert_quantity_population(result, count='2', hold='3')
        self.assert_money_unknown(result)
        self.assertEqual([p['quantity_raw'] for p in result['positions']], ['0', '0'])

    def test_loss_and_breakeven_both_remain_in_completed_denominator(self):
        rows = pair(proceeds='0.8') + [trade('buy', '2026-01-06T00:00:00Z', '1'),
                                     trade('sell', '2026-01-06T04:00:00Z', '1')]
        result = analyze(rows, START, END)
        self.assert_quantity_population(result, count='2', hold='3')
        self.assertEqual(self.value(result, 'profit_sol'), '-0.2')
        self.assertEqual(self.value(result, 'win_rate_pct'), '0')
        self.assertEqual(self.value(result, 'median_roi_pct'), '-10')

    def test_prewindow_cost_loss_does_not_revoke_acquisition_to_closing_hold(self):
        rows = [trade('buy', '2025-12-31T23:00:00Z', None),
                trade('sell', '2026-01-01T01:00:00Z', '1')]
        result = analyze(rows, START, END)
        self.assert_quantity_population(result)
        self.assert_money_unknown(result)

    def test_90day_quantity_count_is_independent_of_report_cost_population(self):
        rows = [trade('buy', '2025-12-15T00:00:00Z', None),
                trade('sell', '2025-12-15T02:00:00Z', '1')] + pair()
        result = analyze(rows, START, END)
        self.assertEqual(self.value(result, 'completed_positions'), '1')
        self.assertEqual(self.value(result, 'completed_positions_90d'), '2')
        self.assertEqual(self.value(result, 'median_hold_hours'), '2')
        self.assertEqual(self.value(result, 'win_rate_pct'), '100')
        self.assertEqual(self.value(result, 'profit_sol'), '0.2')

    def test_report_cost_loss_before_28days_does_not_revoke_four_week_profit(self):
        rows = [trade('buy', '2026-01-01T00:00:00Z', None),
                trade('sell', '2026-01-01T02:00:00Z', '2')] + pair()
        result = analyze(rows, START, END)
        self.assertEqual(self.value(result, 'completed_positions'), '2')
        self.assertIsNone(self.value(result, 'profit_sol'))
        self.assertEqual(self.value(result, 'positive_weeks'), '1')
        self.assertTrue(all(w['status'] == 'known' for w in result['weekly']))
        self.assertEqual(result['metric_intervals']['four_weeks']['start'], '2026-01-03T00:00:00+00:00')

    def test_explicit_28day_loss_does_not_change_declared_90day_count(self):
        ending = datetime(2026, 1, 31, tzinfo=timezone.utc)
        coverage = {'four_weeks': {'start': (ending - timedelta(days=28)).isoformat(),
                                  'end': ending.isoformat(), 'status': 'partial',
                                  'evidence': ['b' * 64]}}
        result = analyze(pair(cost=None), START, END, interval_coverage=coverage)
        self.assert_quantity_population(result)
        self.assertIsNone(self.value(result, 'positive_weeks'))
        self.assertEqual(result['metric_intervals']['verification_90d']['status'], 'complete')

    def test_ordered_event_permutation_preserves_cost_quantity_isolation(self):
        rows = [trade('buy', BUY, None), trade('sell', SELL, '0.8'),
                trade('buy', '2026-01-06T00:00:00Z', '1'),
                trade('sell', '2026-01-06T03:00:00Z', '1')]
        self.assertEqual(analyze(rows, START, END), analyze(list(reversed(rows)), START, END))

    def test_empty_known_population_has_undefined_ratios_not_fabricated_zero(self):
        result = analyze([], START, END)
        self.assertEqual(result['metric_domain_methodology'], METHODOLOGY)
        self.assertEqual(self.value(result, 'completed_positions'), '0')
        self.assertEqual(self.value(result, 'profit_sol'), '0')
        for key in ('median_hold_hours', 'win_rate_pct', 'rapid_sale_pct', 'avg_buys', 'avg_sells', 'median_roi_pct'):
            with self.subTest(metric=key):
                self.assertIsNone(self.value(result, key))
                self.assertEqual(result['metric_domains'][key], {
                    'status': 'undefined', 'reason_code': 'empty_completed_cohort',
                    'witness': {'completed_positions': '0'}})
        self.assertEqual(result['metric_domains']['realised_roi_pct']['reason_code'], 'zero_disposed_basis')
        self.assertEqual(result['metric_domains']['largest_contribution_pct']['reason_code'], 'nonpositive_period_profit')

    def test_zero_known_basis_has_undefined_roi_but_defined_win_and_hold(self):
        result = analyze(pair(cost='0', proceeds='1'), START, END)
        self.assert_quantity_population(result)
        self.assertEqual(self.value(result, 'profit_sol'), '1')
        self.assertEqual(self.value(result, 'win_rate_pct'), '100')
        self.assertIsNone(self.value(result, 'realised_roi_pct'))
        self.assertIsNone(self.value(result, 'median_roi_pct'))
        self.assertEqual(result['metric_domains']['realised_roi_pct'], {
            'status': 'undefined', 'reason_code': 'zero_disposed_basis',
            'witness': {'disposed_basis_sol': '0', 'profit_sol': '1'}})
        self.assertEqual(result['metric_domains']['median_roi_pct'], {
            'status': 'undefined', 'reason_code': 'zero_episode_basis',
            'witness': {'completed_positions': '1', 'zero_basis_episode_ids': ['A:1']}})

    def test_nonpositive_known_profit_has_undefined_concentration(self):
        for proceeds, profit in (('0.8', '-0.2'), ('1', '0')):
            with self.subTest(proceeds=proceeds):
                result = analyze(pair(proceeds=proceeds), START, END)
                self.assertIsNone(self.value(result, 'largest_contribution_pct'))
                self.assertEqual(result['metric_domains']['largest_contribution_pct'], {
                    'status': 'undefined', 'reason_code': 'nonpositive_period_profit',
                    'witness': {'profit_sol': profit}})

    def test_missing_population_or_money_does_not_masquerade_as_undefined(self):
        for rows, history in (([], False), (pair(cost=None), True)):
            with self.subTest(rows=rows, history=history):
                result = analyze(rows, START, END, history_complete=history)
                for key in ('realised_roi_pct', 'median_roi_pct', 'win_rate_pct', 'largest_contribution_pct'):
                    with self.subTest(metric=key):
                        self.assertEqual(result['metric_domains'][key]['status'], 'unknown')
        # An open, supported lot creates a genuinely empty completed cohort,
        # even when its unrealised acquisition money is unavailable.
        result = analyze([trade('buy', BUY, None)], START, END)
        self.assertEqual(result['metric_domains']['median_hold_hours']['status'], 'undefined')


if __name__ == '__main__':
    unittest.main()
