"""Independent synthetic checks for explicitly conditional subset research."""
import unittest
from copy import deepcopy
from decimal import Decimal

from scanner.research import summarize_research

START = '2026-01-01T00:00:00Z'
END = '2026-01-31T00:00:00Z'


def swap(kind, when, amount, quantity='100', mint='mint-A', **extra):
    return {'kind': kind, 'timestamp': when, 'order': 1, 'mint': mint,
            'quantity_raw': quantity, 'decimals': 6, 'amount_sol': amount,
            'fee_sol': '0', 'classification': 'unknown', 'paid_by_wallet': True,
            'signature': 'synthetic', 'path': 'synthetic/swap',
            'evidence': ['synthetic-evidence'], **extra}


def pair():
    return [swap('buy', '2026-01-05T00:00:00Z', '1'),
            swap('sell', '2026-01-05T06:00:00Z', '1.2')]


def fee(when='2026-01-05T06:00:00Z', amount='0.000005', **extra):
    return {'kind': 'fee', 'timestamp': when, 'order': 2, 'amount_sol': amount,
            'paid_by_wallet': True, 'signature': 'synthetic',
            'path': 'meta.fee', 'evidence': ['synthetic-evidence'], **extra}


def anchor(**extra):
    return {'mint-A': {'quantity_raw': '0', 'timestamp': START,
                       'evidence': ['independent-opening-evidence'],
                       'scope': 'wallet_owned_mint', 'verified': True,
                       'intervening_flows_complete': True, **extra}}


def allocated_fee(trade, **extra):
    return fee(trade['timestamp'], trade['fee_sol'], signature=trade['signature'],
               allocation='buy_basis' if trade['kind'] == 'buy' else 'sell_exit',
               allocated_trade_path=trade['path'], **extra)


class ResearchTests(unittest.TestCase):
    def summarize(self, events, **extra):
        return summarize_research(events, START, END, **extra)

    def test_observed_buys_do_not_prove_opening_basis(self):
        research = self.summarize(pair() + [fee()])
        self.assertEqual(research['scope'], 'supported spot swaps in fetched subset')
        self.assertEqual(research['conditional_observed_lot_profit_sol'], '0.199995')
        self.assertIsNone(research['observed_profit_sol'])
        self.assertIsNone(research['known_matched_profit_sol'])
        self.assertFalse(research['history_complete'])
        self.assertFalse(research['wallet_profit_verified'])
        self.assertEqual(research['observed_matched_sales'], 1)
        self.assertEqual(research['matched_sales'], 0)
        self.assertEqual(research['unresolved_basis_sales'], 1)
        self.assertEqual(research['closed_episodes'], 1)
        self.assertEqual(research['conditional_first_sale_hours'], '6')
        self.assertTrue(research['episodes'][0]['conditional'])
        self.assertNotIn('policy', research)

    def test_complete_independent_zero_scope_establishes_attributable_subset(self):
        research = self.summarize(pair() + [fee()], opening_inventory=anchor())
        self.assertEqual(research['known_matched_profit_sol'], '0.2')
        self.assertEqual(research['observed_profit_sol'], '0.199995')
        self.assertEqual(research['matched_sales'], 1)
        self.assertEqual(research['verified_closed_episodes'], 1)
        self.assertIn('independent-opening-evidence', research['evidence'])
        self.assertFalse(research['wallet_profit_verified'])

    def test_transaction_account_zero_is_not_wallet_scope_zero(self):
        rows = pair()
        rows[0].update(observed_pre_quantity_raw='0', observed_post_quantity_raw='100',
                       observation_scope='Transaction account keys only')
        research = self.summarize(rows)
        self.assertIsNone(research['observed_profit_sol'])
        for amendment in ({'scope': 'transaction_accounts'}, {'intervening_flows_complete': False},
                          {'verified': False}, {'evidence': []}, {'quantity_raw': '10'},
                          {'timestamp': '2026-01-10T00:00:00Z'}):
            with self.subTest(amendment=amendment):
                research = self.summarize(rows, opening_inventory=anchor(**amendment))
                self.assertIsNone(research['observed_profit_sol'])

    def test_unmatched_sales_counted_and_do_not_become_zero_cost_wins(self):
        rows = [swap('sell', '2026-01-02T00:00:00Z', '100')] + pair()
        research = self.summarize(rows)
        self.assertEqual(research['sales'], 2)
        self.assertEqual(research['observed_matched_sales'], 1)
        self.assertEqual(research['observed_unmatched_sales'], 1)
        self.assertEqual(research['unresolved_basis_sales'], 2)
        self.assertEqual(research['conditional_observed_lot_profit_sol'], '0.2')
        self.assertIsNone(research['sales_detail'][0]['conditional_matched_basis_sol'])
        self.assertIsNone(research['sales_detail'][0]['conditional_profit_sol'])
        self.assertIsNone(research['observed_profit_sol'])

    def test_no_matched_sales_has_no_profit_number(self):
        research = self.summarize([swap('sell', '2026-01-02T00:00:00Z', '100')])
        self.assertIsNone(research['conditional_observed_lot_profit_sol'])
        self.assertIsNone(research['observed_profit_sol'])
        self.assertEqual(research['observed_unmatched_sales'], 1)

    def test_exact_partial_lots_and_fee_conservation(self):
        rows = [swap('buy', '2026-01-05T00:00:00Z', '1', quantity='3', fee_sol='0.000000003')]
        rows += [swap('sell', f'2026-01-05T0{i}:00:00Z', '1', quantity='1', fee_sol='0.000000001') for i in (1, 2, 3)]
        rows += [fee('2026-01-06T00:00:00Z', '0.000000005', failed=True)]
        research = self.summarize(rows, opening_inventory=anchor())
        self.assertEqual(research['observed_profit_sol'], '1.999999989')
        self.assertEqual(research['conditional_observed_lot_profit_sol'], '1.999999989')
        self.assertEqual(research['known_matched_profit_sol'], '1.999999994')
        self.assertEqual(research['wallet_fees_paid_sol'], '0.000000011')
        self.assertEqual(research['unallocated_fees_sol'], '0.000000005')
        self.assertEqual(research['matched_sales'], 3)
        self.assertEqual(research['episodes'][0]['matched_basis_sol'], '1.000000003')

    def test_attributed_prewindow_entry_fee_is_not_lost_or_period_overhead(self):
        buy = swap('buy', '2025-12-31T00:00:00Z', '1', fee_sol='0.1', signature='entry')
        rows = [buy, allocated_fee(buy), swap('sell', '2026-01-05T00:00:00Z', '2', signature='exit')]
        original = deepcopy(rows)
        research = self.summarize(rows)
        self.assertEqual(research['conditional_observed_lot_profit_sol'], '0.9')
        self.assertEqual(research['sales_detail'][0]['conditional_matched_basis_sol'], '1.1')
        self.assertEqual(research['episodes'][0]['matched_basis_sol'], '1.1')
        self.assertEqual(research['wallet_fees_paid_sol'], '0')
        self.assertEqual(research['unallocated_fees_sol'], '0')
        self.assertIsNone(research['observed_profit_sol'])
        self.assertEqual(rows, original)
        research = self.summarize(rows, opening_inventory=anchor(timestamp='2025-12-30T00:00:00Z'))
        self.assertEqual(research['observed_profit_sol'], '0.9')
        self.assertFalse(research['wallet_profit_verified'])

    def test_attributed_partial_entry_fee_and_exit_fee_conserve_costs(self):
        buy = swap('buy', '2026-01-05T00:00:00Z', '1', fee_sol='0.1', signature='entry')
        sell = swap('sell', '2026-01-05T06:00:00Z', '1', quantity='40', fee_sol='0.2', signature='exit')
        rows = [buy, allocated_fee(buy), sell, allocated_fee(sell)]
        research = self.summarize(rows, opening_inventory=anchor())
        self.assertEqual(research['observed_profit_sol'], '0.36')
        self.assertEqual(research['sales_detail'][0]['conditional_matched_basis_sol'], '0.44')
        self.assertEqual(research['wallet_fees_paid_sol'], '0.3')
        self.assertEqual(research['unallocated_fees_sol'], '0')
        self.assertEqual(research['episodes'][0]['quantity_raw'], '60')
        self.assertEqual(research['episodes'][0]['basis_sol'], '1.1')

    def test_allocated_original_fee_display_and_failed_sponsored_overhead(self):
        buy = swap('buy', '2026-01-05T00:00:00Z', '1', fee_sol='0.1', signature='entry')
        sell = swap('sell', '2026-01-05T06:00:00Z', '2', fee_sol='0.2', signature='exit')
        rows = [buy, allocated_fee(buy), sell, allocated_fee(sell),
                fee('2026-01-06T00:00:00Z', '0.05', failed=True, allocation='unallocated'),
                fee('2026-01-06T01:00:00Z', '10', paid_by_wallet=False, allocation='unallocated')]
        research = self.summarize(rows, opening_inventory=anchor())
        self.assertEqual(research['conditional_observed_lot_profit_sol'], '0.65')
        self.assertEqual(research['observed_profit_sol'], '0.65')
        self.assertEqual(research['known_matched_profit_sol'], '0.7')
        self.assertEqual(research['wallet_fees_paid_sol'], '0.35')
        self.assertEqual(research['unallocated_fees_sol'], '0.05')

    def test_invalid_allocation_claim_rejected_instead_of_hiding_fees(self):
        buy = swap('buy', '2026-01-05T00:00:00Z', '1', fee_sol='0.1', signature='entry')
        for amendment in ({'amount_sol': '0.2'}, {'paid_by_wallet': False},
                          {'allocated_trade_path': 'wrong'}, {'allocation': 'sell_exit'},
                          {'timestamp': '2026-01-06T00:00:00Z'}):
            with self.subTest(amendment=amendment), self.assertRaises(ValueError):
                self.summarize([buy, {**allocated_fee(buy), **amendment}])
        display = allocated_fee(buy)
        with self.assertRaises(ValueError):
            self.summarize([buy, display, dict(display)])
        del display['allocation']
        with self.assertRaises(ValueError):
            self.summarize([buy, display])

    def test_sponsored_fees_excluded_including_unknown_fee(self):
        rows = pair()
        rows[0]['fee_sol'] = '10'
        rows[0]['paid_by_wallet'] = False
        rows += [fee(amount=None, paid_by_wallet=False)]
        research = self.summarize(rows)
        self.assertEqual(research['conditional_observed_lot_profit_sol'], '0.2')
        self.assertEqual(research['wallet_fees_paid_sol'], '0')

    def test_missing_paid_fee_keeps_after_cost_profit_unknown(self):
        research = self.summarize(pair() + [fee(amount=None)], opening_inventory=anchor())
        self.assertIsNone(research['observed_profit_sol'])
        self.assertIsNone(research['conditional_observed_lot_profit_sol'])
        self.assertIsNone(research['wallet_fees_paid_sol'])
        self.assertEqual(research['known_matched_profit_sol'], '0.2')

    def test_unknown_route_invalidates_scope_certificate(self):
        rows = pair() + [{'kind': 'unsupported', 'timestamp': '2026-01-04T00:00:00Z',
                          'order': 1, 'reason': 'unreviewed route', 'evidence': ['unknown-route']}]
        research = self.summarize(rows, opening_inventory=anchor())
        self.assertIsNone(research['observed_profit_sol'])
        self.assertEqual(research['unresolved_transactions'], 1)
        self.assertEqual(research['conditional_observed_lot_profit_sol'], '0.2')
        self.assertEqual(research['matched_sales'], 0)
        self.assertTrue(any('interrupt' in finding['title'] for finding in research['risk_findings']))

    def test_same_time_ambiguous_order_never_computes_conditional_fifo(self):
        rows = pair()
        rows[1]['timestamp'] = rows[0]['timestamp']
        research = self.summarize(rows)
        self.assertTrue(research['chronology_unknown'])
        self.assertIsNone(research['conditional_observed_lot_profit_sol'])
        self.assertIsNone(research['conditional_median_hold_hours'])
        self.assertEqual(research['observed_matched_sales'], 0)

    def test_half_open_window_preserves_prior_purchase_cost(self):
        rows = [swap('buy', '2025-12-31T00:00:00Z', '1'), swap('sell', START, '1.5'),
                swap('buy', '2026-01-30T00:00:00Z', '1'), swap('sell', END, '100')]
        research = self.summarize(rows)
        self.assertEqual(research['supported_swaps'], 2)
        self.assertEqual(research['conditional_observed_lot_profit_sol'], '0.5')
        self.assertEqual(research['closed_episodes'], 1)
        self.assertEqual(len(research['episodes']), 2)

    def test_quick_first_sale_and_fractional_exits_are_observational(self):
        rows = [swap('buy', '2026-01-05T00:00:00Z', '1'),
                swap('sell', '2026-01-05T00:02:00Z', '1', quantity='90'),
                swap('sell', '2026-01-05T06:00:00Z', '0.2', quantity='10')]
        research = self.summarize(rows)
        self.assertEqual(research['conditional_median_hold_hours'], '6')
        self.assertEqual(research['conditional_rapid_sale_pct'], '100')
        self.assertEqual(Decimal(research['conditional_exit_50_hours']).quantize(Decimal('0.0001')), Decimal('0.0333'))
        self.assertEqual(research['conditional_exit_50_hours'], research['conditional_exit_90_hours'])
        self.assertIsNone(research['observed_profit_sol'])

    def test_transfer_interrupts_episode_and_verified_inventory(self):
        rows = [swap('buy', '2026-01-05T00:00:00Z', '1'),
                {**swap('transfer_out', '2026-01-05T01:00:00Z', '0', quantity='50')},
                swap('sell', '2026-01-05T06:00:00Z', '0.8', quantity='50')]
        research = self.summarize(rows, opening_inventory=anchor())
        self.assertIsNone(research['observed_profit_sol'])
        self.assertEqual(research['closed_episodes'], 0)
        self.assertEqual(research['episodes'][0]['status'], 'interrupted')

    def test_source_classification_unchanged_and_supplied_risks_retained(self):
        rows = pair()
        original = deepcopy(rows)
        risk = {'severity': 'warning', 'title': 'Active authority', 'detail': 'Synthetic finding', 'evidence': ['risk-evidence']}
        research = self.summarize(rows, findings=[risk])
        self.assertEqual(rows, original)
        self.assertTrue(all(row['classification'] == 'unknown' for row in rows))
        self.assertNotIn('classification', research['episodes'][0])
        self.assertEqual(research['risk_findings'][0], risk)

    def test_invalid_float_money_and_boolean_quantity_rejected(self):
        for update in ({'amount_sol': 1.0}, {'quantity_raw': True}, {'paid_by_wallet': 1}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                rows = pair()
                rows[0].update(update)
                self.summarize(rows)


if __name__ == '__main__':
    unittest.main()
