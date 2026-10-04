"""Separately worked development arithmetic; not genuine B3 evidence."""
from copy import deepcopy
from decimal import Decimal

import pytest

from scanner.research import summarize_research

START = '2026-01-25T00:00:00Z'
END = '2026-01-31T00:00:00Z'


def trade(kind, at, quantity, amount, fee, signature):
    return {'kind': kind, 'timestamp': at, 'quantity_raw': str(quantity),
            'amount_sol': amount, 'fee_sol': fee, 'mint': 'development-mint',
            'decimals': 0, 'classification': 'unknown', 'paid_by_wallet': True,
            'order': 1, 'signature': signature, 'path': 'synthetic/swap',
            'evidence': ['a' * 64]}


def rows():
    # First basis 4.2: 20%=.84, 30%=1.26, 50%=2.1. Sale nets
    # 1-.01-.84=.15; 1-.02-1.26=-.28; 3-.03-2.1=.87.
    # Second basis 1.1 and exit 1-.1 => -.2; re-entry is a new episode.
    return [trade('buy', '2025-12-01T00:00:00Z', 100, '4', '0.2', 'first-buy'),
            trade('sell', '2025-12-20T00:00:00Z', 20, '1', '0.01', 'old-sell'),
            trade('sell', '2026-01-10T00:00:00Z', 30, '1', '0.02', '28d-sell'),
            trade('sell', '2026-01-29T00:00:00Z', 50, '3', '0.03', 'report-sell'),
            trade('buy', '2026-01-30T00:00:00Z', 10, '1', '0.1', 'reentry'),
            trade('sell', '2026-01-30T01:00:00Z', 10, '1', '0.1', 'reentry-sell'),
            trade('sell', END, 1, '100', '0', 'excluded-end')]


def calculate(source=None):
    return summarize_research(rows() if source is None else source, START, END)


def test_historical_disposals_reuse_exact_fifo_basis_and_independent_scopes():
    result = calculate()
    historical = result['historical_sales_detail']
    assert [r['signature'] for r in historical] == ['old-sell', '28d-sell', 'report-sell', 'reentry-sell']
    assert [r['conditional_matched_basis_sol'] for r in historical] == ['0.84', '1.26', '2.1', '1.1']
    assert [r['conditional_profit_sol'] for r in historical] == ['0.15', '-0.28', '0.87', '-0.2']
    assert [r['fifo_episode']['ordinal'] for r in historical] == [1, 1, 1, 2]
    assert result['conditional_observed_lot_profit_sol'] == '0.67'
    assert sum(Decimal(r['conditional_profit_sol']) for r in historical) == Decimal('.54')
    for begin, basis in [('2026-01-25', '3.2'), ('2026-01-03', '4.46'), ('2025-11-02', '5.3')]:
        selected = [r for r in historical if r['timestamp'][:10] >= begin]
        assert sum(Decimal(r['conditional_matched_basis_sol']) for r in selected) == Decimal(basis)
    assert result['sales'] == 2
    assert len(result['sales_detail']) == 2
    assert result['wallet_profit_verified'] is False


@pytest.mark.parametrize('field', ['amount_sol', 'fee_sol'])
def test_missing_prewindow_acquisition_money_does_not_erase_reentry_or_quantity(field):
    source = rows()
    source[0][field] = None
    result = calculate(source)
    historical = result['historical_sales_detail']
    assert all(r['monetary_state'] == 'UNKNOWN' and r['conditional_profit_sol'] is None for r in historical[:3])
    assert all(r['quantity_state'] == r['clock_state'] == 'PASS' for r in historical)
    assert historical[-1]['conditional_profit_sol'] == '-0.2'
    assert historical[-1]['monetary_state'] == 'PASS'
    assert result['wallet_fees_paid_sol'] == '0.23'


def test_permutation_and_private_copies_preserve_raw_events_and_scope_rows():
    source = rows()
    original = deepcopy(source)
    result = calculate(source)
    assert source == original
    assert calculate(list(reversed(source))) == result
    result['sales_detail'][0]['evidence'].append('mutated-child')
    result['sales_detail'][0]['fifo_episode']['ordinal'] = 100
    assert result['historical_sales_detail'][2]['evidence'] == ['a' * 64]
    assert result['historical_sales_detail'][2]['fifo_episode']['ordinal'] == 1
    assert source == original


def test_zero_and_losing_disposals_are_retained_in_selected_census():
    source = [trade('buy', '2026-01-26T00:00:00Z', 100, '1', '0', 'buy'),
              trade('sell', '2026-01-26T01:00:00Z', 50, '0.5', '0', 'even'),
              trade('sell', '2026-01-26T02:00:00Z', 50, '0.4', '0', 'loss')]
    result = calculate(source)
    assert [r['conditional_profit_sol'] for r in result['historical_sales_detail']] == ['0', '-0.1']
    assert result['observed_matched_sales'] == 2
    assert result['conditional_observed_lot_profit_sol'] == '-0.1'
