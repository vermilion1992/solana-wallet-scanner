"""Independent synthetic accounting expectations; no live-provider validation."""
import unittest
from decimal import Decimal
from datetime import datetime, timezone, timedelta

from scanner.accounting import analyze, evaluate_policy, decimal

START = '2026-01-01T00:00:00Z'
END = '2026-01-31T00:00:00Z'


def event(kind, when, amount=None, quantity='100', mint='A', **extra):
    row = {'kind': kind, 'timestamp': when, 'order': 1, 'mint': mint,
           'quantity_raw': quantity, 'decimals': 6, 'classification': 'meme',
           'signature': 'synthetic', 'path': 'fixture', 'evidence': ['fixture-hash']}
    if amount is not None:
        row['amount_sol'] = amount
    row.update(extra)
    return row


def pair(day=5, hold=6, cost='1', proceeds='1.2', mint='A'):
    start = datetime(2026, 1, day, tzinfo=timezone.utc)
    return [event('buy', start.isoformat(), cost, mint=mint),
            event('sell', (start + timedelta(hours=hold)).isoformat(), proceeds, mint=mint)]


def permissive():
    return {'min_profit_sol': '0', 'min_realised_roi_pct': '0', 'min_median_roi_pct': '0',
            'min_win_rate_pct': '0', 'max_win_rate_pct': '100', 'min_hold_hours': '0',
            'max_hold_hours': '200', 'min_positions': 1, 'min_positions_90d': 1,
            'min_mints': 1, 'max_mints': 100, 'max_rapid_sale_pct': '100',
            'min_avg_buys': '0', 'max_avg_buys': '10', 'min_avg_sells': '0',
            'max_avg_sells': '10', 'min_positive_weeks': 0, 'max_contribution_pct': '100',
            'require_positive_economic_pnl': True}


def allocated_fee(trade, **extra):
    """Original network-fee observation retained beside its attributed trade."""
    return {'kind': 'fee', 'timestamp': trade['timestamp'], 'order': trade['order'] + 1,
            'amount_sol': trade['fee_sol'], 'paid_by_wallet': True,
            'signature': trade['signature'], 'path': 'meta.fee',
            'allocation': 'buy_basis' if trade['kind'] == 'buy' else 'sell_exit',
            'allocated_trade_path': trade['path'], 'evidence': ['fixture-hash'], **extra}


class AccountingTests(unittest.TestCase):
    def value(self, report, key):
        return report['metrics'][key]['value']

    def test_partial_fifo_buy_fees_and_exit_fees(self):
        rows = [event('buy', '2025-12-31T00:00:00Z', '9', quantity='100', fee_sol='1'),
                event('buy', '2026-01-05T00:00:00Z', '38', quantity='200', fee_sol='2'),
                event('sell', '2026-01-05T03:00:00Z', '30', quantity='150', fee_sol='1'),
                event('sell', '2026-01-05T06:00:00Z', '45', quantity='150', fee_sol='1')]
        report = analyze(rows, START, END)
        self.assertEqual(self.value(report, 'profit_sol'), '23')
        self.assertEqual(self.value(report, 'realised_roi_pct'), '46')
        self.assertEqual(report['positions'][0]['matched_basis_sol'], '50')
        self.assertEqual(report['positions'][0]['first_sale_hours'], '123')
        self.assertEqual(report['positions'][0]['sold_50_pct_hours'], '123')
        self.assertEqual(report['positions'][0]['sold_90_pct_hours'], '126')
        self.assertEqual(self.value(report, 'avg_buys'), '2')

    def test_partial_open_profit_counts_disposal_not_episode(self):
        rows = [event('buy', '2025-12-01T00:00:00Z', '10'),
                event('sell', '2026-01-05T00:00:00Z', '8', quantity='50')]
        report = analyze(rows, START, END)
        self.assertEqual(self.value(report, 'profit_sol'), '3')
        self.assertEqual(self.value(report, 'completed_positions'), '0')
        self.assertEqual(report['counts']['open'], 1)
        self.assertIsNone(self.value(report, 'median_hold_hours'))

    def test_true_medians_not_means_and_reentry(self):
        report = analyze(pair(5, 1, proceeds='1.1') + pair(10, 2, proceeds='1.2') + pair(15, 100, proceeds='2'), START, END)
        self.assertEqual(self.value(report, 'median_hold_hours'), '2')
        self.assertEqual(self.value(report, 'median_roi_pct'), '20')
        self.assertEqual(self.value(report, 'completed_positions'), '3')
        self.assertEqual(self.value(report, 'traded_mints'), '1')

    def test_even_median_breakeven_denominator(self):
        report = analyze(pair(5, 2, proceeds='1') + pair(10, 4, proceeds='0.8'), START, END)
        self.assertEqual(self.value(report, 'median_hold_hours'), '3')
        self.assertEqual(self.value(report, 'median_roi_pct'), '-10')
        self.assertEqual(self.value(report, 'win_rate_pct'), '0')

    def test_half_open_window_prior_basis_and_verification(self):
        rows = [event('buy', '2025-12-15T00:00:00Z', '1'),
                event('sell', START, '1.5'),
                event('buy', '2026-01-30T00:00:00Z', '1'),
                event('sell', END, '100')]
        report = analyze(rows, START, END)
        self.assertEqual(self.value(report, 'profit_sol'), '0.5')
        self.assertEqual(self.value(report, 'completed_positions'), '1')
        self.assertEqual(report['counts']['open'], 1)

    def test_prior_completed_episode_only_in_90day_count(self):
        rows = [event('buy', '2025-12-15T00:00:00Z', '1'),
                event('sell', '2025-12-16T00:00:00Z', '2')] + pair()
        report = analyze(rows, START, END)
        self.assertEqual(self.value(report, 'completed_positions'), '1')
        self.assertEqual(self.value(report, 'completed_positions_90d'), '2')
        self.assertEqual(self.value(report, 'profit_sol'), '0.2')

    def test_unknown_prior_inventory_is_not_free_profit(self):
        report = analyze([event('sell', '2026-01-05T00:00:00Z', '100')], START, END)
        self.assertIsNone(self.value(report, 'profit_sol'))
        self.assertIsNone(self.value(report, 'median_roi_pct'))
        self.assertEqual(report['counts']['unresolved'], 1)
        self.assertIsNone(report['positions'][0]['basis_sol'])

    def test_transfer_in_unknown_basis_and_interrupted_denominator(self):
        rows = [event('transfer_in', '2026-01-05T00:00:00Z'),
                event('sell', '2026-01-05T06:00:00Z', '100')] + pair(10, mint='B')
        report = analyze(rows, START, END)
        self.assertIsNone(self.value(report, 'profit_sol'))
        self.assertIsNone(self.value(report, 'completed_positions'))
        self.assertIsNone(self.value(report, 'win_rate_pct'))
        self.assertEqual(report['counts']['interrupted'], 1)
        self.assertEqual(report['counts']['closed'], 1)

    def test_transfer_out_is_not_sale_and_internal_move_does_not_interrupt(self):
        rows = [event('buy', '2026-01-05T00:00:00Z', '10'),
                event('internal_transfer', '2026-01-05T01:00:00Z'),
                event('transfer_out', '2026-01-05T02:00:00Z', quantity='50'),
                event('sell', '2026-01-05T06:00:00Z', '8', quantity='50')]
        report = analyze(rows, START, END)
        self.assertEqual(self.value(report, 'profit_sol'), '3')
        self.assertIsNone(self.value(report, 'completed_positions'))
        self.assertEqual(report['counts']['interrupted'], 1)

    def test_fees_failed_and_sponsored(self):
        rows = pair() + [event('fee', '2026-01-06T00:00:00Z', '0.1', failed=True),
                         event('fee', '2026-01-06T01:00:00Z', '10', paid_by_wallet=False)]
        report = analyze(rows, START, END)
        self.assertEqual(self.value(report, 'profit_sol'), '0.1')
        self.assertEqual(report['unallocated_overhead_sol'], '0.1')
        rows = pair()
        rows[0]['fee_sol'] = '100'
        rows[0]['paid_by_wallet'] = False
        self.assertEqual(self.value(analyze(rows, START, END), 'profit_sol'), '0.2')

    def test_attributed_prewindow_entry_fee_stays_in_disposed_basis(self):
        buy = event('buy', '2025-12-31T00:00:00Z', '1', fee_sol='0.1',
                    paid_by_wallet=True, signature='entry', path='swap/0')
        rows = [buy, allocated_fee(buy), event('sell', '2026-01-05T00:00:00Z', '2')]
        report = analyze(rows, START, END)
        self.assertEqual(self.value(report, 'profit_sol'), '0.9')
        self.assertEqual(report['positions'][0]['matched_basis_sol'], '1.1')
        self.assertEqual(report['unallocated_overhead_sol'], '0')

    def test_attributed_fee_partial_disposal_consumes_only_matched_basis(self):
        buy = event('buy', '2025-12-31T00:00:00Z', '1', fee_sol='0.1',
                    paid_by_wallet=True, signature='entry', path='swap/0')
        rows = [buy, allocated_fee(buy), event('sell', '2026-01-05T00:00:00Z', '1', quantity='40')]
        report = analyze(rows, START, END)
        self.assertEqual(self.value(report, 'profit_sol'), '0.56')
        self.assertEqual(report['positions'][0]['matched_basis_sol'], '0.44')
        self.assertEqual(report['positions'][0]['basis_sol'], '1.1')
        self.assertEqual(report['positions'][0]['quantity_raw'], '60')
        self.assertEqual(report['unallocated_overhead_sol'], '0')

    def test_original_fee_display_does_not_duplicate_buy_or_exit_cost(self):
        buy = event('buy', '2026-01-05T00:00:00Z', '1', fee_sol='0.1',
                    paid_by_wallet=True, signature='entry', path='swap/0')
        sell = event('sell', '2026-01-05T06:00:00Z', '2', fee_sol='0.2',
                     paid_by_wallet=True, signature='exit', path='swap/0')
        rows = [buy, allocated_fee(buy), sell, allocated_fee(sell)]
        report = analyze(rows, START, END)
        self.assertEqual(self.value(report, 'profit_sol'), '0.7')
        self.assertEqual(report['positions'][0]['matched_basis_sol'], '1.1')
        self.assertEqual(report['positions'][0]['exit_fees_sol'], '0.2')
        self.assertEqual(report['unallocated_overhead_sol'], '0')
        rows += [event('fee', '2026-01-06T00:00:00Z', '0.05', failed=True, allocation='unallocated'),
                 event('fee', '2026-01-06T01:00:00Z', '10', paid_by_wallet=False, allocation='unallocated')]
        report = analyze(rows, START, END)
        self.assertEqual(self.value(report, 'profit_sol'), '0.65')
        self.assertEqual(report['unallocated_overhead_sol'], '0.05')

    def test_invalid_fee_allocation_never_suppresses_wallet_spend(self):
        buy = event('buy', '2026-01-05T00:00:00Z', '1', fee_sol='0.1',
                    paid_by_wallet=True, signature='entry', path='swap/0')
        for update in ({'amount_sol': '0.2'}, {'amount_sol': None},
                       {'paid_by_wallet': False}, {'signature': 'other'},
                       {'allocated_trade_path': 'other'}, {'allocation': 'sell_exit'},
                       {'allocation': None}, {'allocation': 'unsupported'},
                       {'timestamp': '2026-01-06T00:00:00Z'}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                analyze([buy, allocated_fee(buy, **update)] + pair(mint='B'), START, END)
        for update in ({'fee_sol': None}, {'paid_by_wallet': False}):
            with self.subTest(trade_update=update), self.assertRaises(ValueError):
                analyze([{**buy, **update}, allocated_fee(buy)] + pair(mint='B'), START, END)
        original_fee = allocated_fee(buy)
        missing_allocation = dict(original_fee)
        del missing_allocation['allocation']
        for rows in ([buy, original_fee, dict(original_fee)],
                     [buy, dict(buy), original_fee], [buy, missing_allocation]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                analyze(rows, START, END)

    def test_fee_of_excluded_settlement_trade_remains_period_overhead(self):
        settle = event('buy', '2026-01-05T00:00:00Z', '1', fee_sol='0.1',
                       classification='settlement', paid_by_wallet=True,
                       signature='settlement-entry', path='swap/0')
        report = analyze([settle, allocated_fee(settle)] + pair(mint='B'), START, END)
        self.assertEqual(self.value(report, 'profit_sol'), '0.1')
        self.assertEqual(report['unallocated_overhead_sol'], '0.1')

    def test_dust_keeps_strict_position_open(self):
        rows = [event('buy', '2026-01-05T00:00:00Z', '1', quantity='1000000'),
                event('sell', '2026-01-05T01:00:00Z', '2', quantity='999999')]
        report = analyze(rows, START, END)
        self.assertEqual(report['positions'][0]['quantity_raw'], '1')
        self.assertEqual(self.value(report, 'completed_positions'), '0')
        self.assertEqual(report['counts']['open'], 1)

    def test_first_sale_rapid_despite_long_final_hold(self):
        rows = [event('buy', '2026-01-05T00:00:00Z', '1'),
                event('sell', '2026-01-05T00:02:00Z', '1', quantity='90'),
                event('sell', '2026-01-05T06:00:00Z', '0.2', quantity='10')]
        report = analyze(rows, START, END)
        self.assertEqual(self.value(report, 'rapid_sale_pct'), '100')
        self.assertEqual(self.value(report, 'median_hold_hours'), '6')
        self.assertEqual(report['positions'][0]['sold_90_pct_hours'], report['positions'][0]['first_sale_hours'])
        self.assertEqual(Decimal(report['positions'][0]['first_sale_hours']).quantize(Decimal('0.0001')), Decimal('0.0333'))

    def test_week_population_last28_and_concentration_aggregate_by_mint(self):
        rows = pair(2, proceeds='100', mint='outside28') + pair(4, proceeds='11', mint='A') + pair(12, cost='10', proceeds='1', mint='A') + pair(20, proceeds='3', mint='B')
        report = analyze(rows, START, END)
        self.assertEqual(self.value(report, 'positive_weeks'), '2')
        # A aggregate +1; B +2; outside28 +99; total period +102.
        self.assertEqual(Decimal(self.value(report, 'largest_contribution_pct')).quantize(Decimal('0.0001')), Decimal('97.0588'))
        report = analyze(rows[2:], START, END)
        self.assertEqual(self.value(report, 'profit_sol'), '3')
        self.assertTrue(Decimal(self.value(report, 'largest_contribution_pct')) > Decimal('66.66'))
        self.assertTrue(Decimal(self.value(report, 'largest_contribution_pct')) < Decimal('66.67'))

    def test_unknown_classification_and_history_never_pass(self):
        rows = pair()
        rows[0]['classification'] = rows[1]['classification'] = 'unknown'
        report = analyze(rows, START, END)
        self.assertIsNone(self.value(report, 'traded_mints'))
        self.assertIsNone(self.value(report, 'profit_sol'))
        report = analyze(pair(), START, END, history_complete=False)
        self.assertIsNone(self.value(report, 'profit_sol'))
        self.assertIsNone(self.value(report, 'completed_positions'))

    def test_unsupported_route_blocks_financial_headline(self):
        rows = pair() + [event('unsupported', '2026-01-06T00:00:00Z', reason='unknown DEX')]
        report = analyze(rows, START, END)
        self.assertIsNone(self.value(report, 'profit_sol'))
        self.assertTrue(report['findings'])

    def test_economic_capital_not_trading_profit(self):
        report = analyze(pair(), START, END, opening_equity='10', closing_equity='111', external_deposits='100', external_withdrawals='0')
        self.assertEqual(self.value(report, 'economic_pnl_sol'), '1')
        self.assertEqual(self.value(report, 'profit_sol'), '0.2')
        self.assertEqual(evaluate_policy(report['metrics'], permissive(), True)['policy'], 'MATCH')
        self.assertEqual(evaluate_policy(report['metrics'], permissive(), False)['policy'], 'UNRESOLVED')

    def test_known_failure_survives_unknown_and_all_gates_required(self):
        report = analyze(pair(hold=0.5), START, END)
        preset = permissive()
        preset['min_hold_hours'] = '1'
        result = evaluate_policy(report['metrics'], preset, False)
        self.assertEqual(result['policy'], 'MISS')
        self.assertTrue(any(c['key'] == 'median_hold_hours' and c['state'] == 'FAIL' for c in result['checks']))
        report = analyze(pair(), START, END, opening_equity='0', closing_equity='1', external_deposits='0', external_withdrawals='0')
        result = evaluate_policy(report['metrics'], permissive(), {'history': 'FAIL'})
        self.assertEqual(result['policy'], 'MISS')
        self.assertTrue(any(c['key'] == 'evidence_fees' and c['state'] == 'UNKNOWN' for c in result['checks']))

    def test_mint_identity_and_settlement_exclusion(self):
        rows = pair(mint='mint-A') + pair(mint='mint-B')
        for row in rows:
            row['symbol'] = 'SAME'
        settle = pair(mint='USDC')
        for row in settle:
            row['classification'] = 'settlement'
        report = analyze(rows + settle, START, END)
        self.assertEqual(self.value(report, 'traded_mints'), '2')
        self.assertEqual(self.value(report, 'profit_sol'), '0.4')

    def test_basis_allocation_conserves_repeating_fraction(self):
        rows = [event('buy', '2026-01-05T00:00:00Z', '1', quantity='3')]
        rows += [event('sell', f'2026-01-05T0{i}:00:00Z', '1', quantity='1') for i in range(1, 4)]
        report = analyze(rows, START, END)
        self.assertEqual(report['positions'][0]['matched_basis_sol'], '1')
        self.assertEqual(self.value(report, 'profit_sol'), '2')

    def test_conflicting_settlement_classification_blocks_financial_metrics(self):
        rows = pair()
        rows[1]['classification'] = 'settlement'
        report = analyze(rows, START, END)
        self.assertIsNone(self.value(report, 'profit_sol'))
        self.assertIsNone(self.value(report, 'traded_mints'))

    def test_unknown_allocated_fee_blocks_basis_not_assumed_zero(self):
        rows = pair()
        rows[0]['fee_sol'] = None
        report = analyze(rows, START, END)
        self.assertIsNone(self.value(report, 'profit_sol'))
        self.assertIsNone(self.value(report, 'median_roi_pct'))
        rows[0]['paid_by_wallet'] = False
        self.assertEqual(self.value(analyze(rows, START, END), 'profit_sol'), '0.2')

    def test_duplicate_same_time_same_mint_order_is_unresolved(self):
        rows = [event('buy', '2026-01-05T00:00:00Z', '1'),
                event('sell', '2026-01-05T00:00:00Z', '2')]
        report = analyze(rows, START, END)
        self.assertIsNone(self.value(report, 'profit_sol'))
        self.assertTrue(any(f['title'] == 'Ambiguous event order' for f in report['findings']))
        rows[1]['order'] = 2
        self.assertEqual(self.value(analyze(rows, START, END), 'profit_sol'), '1')

    def test_verification_interrupted_episode_does_not_disappear(self):
        rows = [event('buy', '2025-12-15T00:00:00Z', '1'),
                event('transfer_out', '2025-12-16T00:00:00Z')]
        report = analyze(rows + pair(), START, END)
        self.assertEqual(self.value(report, 'completed_positions'), '1')
        self.assertIsNone(self.value(report, 'completed_positions_90d'))
        self.assertEqual(report['counts']['closed'], 1)
        self.assertEqual(report['counts']['interrupted'], 0)
        self.assertFalse(report['positions'][0]['in_window'])

    def test_reject_float_boolean_nonfinite_and_bad_quantities(self):
        for value in (1.0, True, 'NaN', 'Infinity', '1e3', '-1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decimal(value)
        for quantity in ('1.0', '-1', True, 10):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                analyze([event('buy', '2026-01-05T00:00:00Z', '1', quantity=quantity)], START, END)
        rows = pair()
        rows[1]['decimals'] = 9
        with self.assertRaises(ValueError):
            analyze(rows, START, END)


if __name__ == '__main__':
    unittest.main()
