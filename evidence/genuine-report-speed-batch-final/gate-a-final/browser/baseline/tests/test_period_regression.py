"""Independent fixed-history controls for PDF four-week consistency.

Changing the display start cannot change the exact [end-28d,end) population.
These are declared complete synthetic inputs, not independently verified wallets.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from scanner.accounting import analyze, evaluate_policy
from scanner.config import STRICT


END = datetime(2026, 1, 31, tzinfo=timezone.utc)
PRIMARY_HASH = 'a' * 64


def event(kind, when, amount, *, mint='token', quantity='100', **extra):
    row = {'kind': kind, 'timestamp': when.isoformat(), 'order': 1,
           'amount_sol': amount, 'signature': f'synthetic-{when.isoformat()}-{kind}',
           'path': 'synthetic/route', 'evidence': ['synthetic-history']}
    if kind in ('buy', 'sell'):
        row.update(mint=mint, quantity_raw=quantity, decimals=6, classification='meme')
    return {**row, **extra}


def history():
    rows = []
    for day in (6, 13, 20, 27):
        sale = datetime(2026, 1, day, tzinfo=timezone.utc)
        rows += [event('buy', sale - timedelta(hours=1), '1', mint=f'token-{day}'),
                 event('sell', sale, '2', mint=f'token-{day}')]
    return rows


def report(rows, days, **extra):
    return analyze(rows, (END - timedelta(days=days)).isoformat(), END.isoformat(), **extra)


def declaration(status='complete', *, start=None, evidence=None):
    return {'four_weeks': {'start': (start or END - timedelta(days=28)).isoformat(),
                           'end': END.isoformat(), 'status': status,
                           'evidence': [PRIMARY_HASH] if evidence is None else evidence}}


def display_fee(trade):
    return event('fee', datetime.fromisoformat(trade['timestamp']), trade['fee_sol'],
                 order=2, signature=trade['signature'], path='meta.fee',
                 paid_by_wallet=True,
                 allocation='buy_basis' if trade['kind'] == 'buy' else 'sell_exit',
                 allocated_trade_path=trade['path'])


@pytest.mark.parametrize(('days', 'period_profit'), [(7, '1'), (14, '2'), (21, '3'),
                                                    (28, '4'), (30, '4'), (90, '4')])
def test_same_history_has_four_positive_weeks_for_every_display_period(days, period_profit):
    rows = history()
    original = deepcopy(rows)
    result = report(rows, days)
    assert result['metrics']['positive_weeks']['value'] == '4'
    assert [week['profit_sol'] for week in result['weekly']] == ['1'] * 4
    assert [week['status'] for week in result['weekly']] == ['known'] * 4
    assert result['metrics']['profit_sol']['value'] == period_profit
    assert result['metrics']['completed_positions']['value'] == period_profit
    assert result['metrics']['realised_roi_pct']['value'] == '100'
    assert result['metric_coverage']['positive_weeks']['start'] == '2026-01-03T00:00:00+00:00'
    assert result['metric_coverage']['positive_weeks']['end'] == END.isoformat()
    assert result['metric_coverage']['positive_weeks']['interval'] == 'four_weeks'
    assert result['metric_coverage']['profit_sol']['start'] == (END - timedelta(days=days)).isoformat()
    assert rows == original


def test_weekly_overhead_uses_its_own_half_open_boundaries():
    rows = history()
    rows += [event('fee', datetime(2026, 1, 2, tzinfo=timezone.utc), '0.25'),
             event('fee', datetime(2026, 1, 3, tzinfo=timezone.utc), '2', failed=True),
             event('fee', datetime(2026, 1, 10, tzinfo=timezone.utc), '1.5'),
             event('fee', datetime(2026, 1, 24, tzinfo=timezone.utc), '1'),
             event('fee', datetime(2026, 1, 24, tzinfo=timezone.utc), '100', paid_by_wallet=False),
             event('fee', END, '100')]
    short = report(rows, 7)
    long = report(rows, 30)
    assert [week['profit_sol'] for week in short['weekly']] == ['-1', '-0.5', '1', '0']
    assert short['weekly'] == long['weekly']
    assert short['metrics']['positive_weeks']['value'] == long['metrics']['positive_weeks']['value'] == '1'
    assert short['metrics']['profit_sol']['value'] == '0'
    assert short['unallocated_overhead_sol'] == '1'
    assert long['metrics']['profit_sol']['value'] == '-0.75'
    assert long['unallocated_overhead_sol'] == '4.75'


def test_buy_basis_and_exit_fees_remain_exact_across_week_boundaries():
    buy = event('buy', datetime(2026, 1, 2, tzinfo=timezone.utc), '1',
                fee_sol='0.1', paid_by_wallet=True, mint='old-lot')
    sell = event('sell', datetime(2026, 1, 3, tzinfo=timezone.utc), '2',
                 fee_sol='0', paid_by_wallet=True, mint='old-lot')
    next_buy = event('buy', datetime(2026, 1, 9, tzinfo=timezone.utc), '1',
                     fee_sol='0.1', paid_by_wallet=True, mint='new-lot')
    next_sell = event('sell', datetime(2026, 1, 10, tzinfo=timezone.utc), '2',
                      fee_sol='0.2', paid_by_wallet=True, mint='new-lot')
    rows = [buy, display_fee(buy), sell, next_buy, display_fee(next_buy),
            next_sell, display_fee(next_sell)]
    result = report(rows, 7)
    assert [week['profit_sol'] for week in result['weekly']] == ['0.9', '0.7', '0', '0']
    assert result['metrics']['positive_weeks']['value'] == '2'
    assert result['metrics']['profit_sol']['value'] == '0'
    assert result['unallocated_overhead_sol'] == '0'


def test_partial_history_never_invents_empty_profitable_or_zero_weeks():
    result = report(history()[-2:], 7, history_complete=False)
    assert result['metrics']['positive_weeks']['value'] is None
    assert result['metrics']['positive_weeks']['status'] == 'unknown'
    assert all(week['profit_sol'] is None and week['status'] == 'unknown' for week in result['weekly'])
    assert result['metric_coverage']['positive_weeks']['status'] == 'partial'


def test_explicit_partial_four_week_scope_keeps_missing_weeks_unknown():
    result = report(history()[-2:], 7,
                    interval_coverage=declaration('partial', start=END - timedelta(days=7), evidence=[]))
    assert result['metrics']['profit_sol']['value'] == '1'
    assert result['metrics']['positive_weeks']['value'] is None
    assert all(week['profit_sol'] is None for week in result['weekly'])


def test_explicit_short_history_cannot_satisfy_the_four_week_interval():
    result = report(history(), 7, interval_coverage=declaration(start=END - timedelta(days=7)))
    assert result['metrics']['positive_weeks']['value'] is None
    assert result['metric_coverage']['positive_weeks']['status'] == 'partial'
    assert 'does not span' in result['metric_coverage']['positive_weeks']['reason']
    assert result['metrics']['profit_sol']['value'] == '1'


def test_independent_primary_interval_cannot_upgrade_whole_wallet_history():
    result = report(history(), 7, history_complete=False, interval_coverage=declaration())
    assert result['metrics']['positive_weeks']['value'] == '4'
    assert result['metric_coverage']['positive_weeks']['status'] == 'complete'
    assert result['metric_coverage']['positive_weeks']['evidence'] == [PRIMARY_HASH]
    assert result['metrics']['profit_sol']['value'] is None
    assert result['metrics']['completed_positions']['value'] is None
    assert evaluate_policy(result['metrics'], STRICT, False)['policy'] != 'MATCH'


def test_unknown_prior_week_fee_blocks_consistency_without_changing_short_period_profit():
    rows = history() + [event('fee', datetime(2026, 1, 4, tzinfo=timezone.utc), None)]
    result = report(rows, 7)
    assert [week['profit_sol'] for week in result['weekly']] == [None, '1', '1', '1']
    assert result['metrics']['positive_weeks']['value'] is None
    assert 'costs are unresolved' in result['weekly'][0]['reason']
    assert result['metrics']['profit_sol']['value'] == '1'


def test_unknown_cost_outside_four_weeks_does_not_truncate_or_invalidate_that_interval():
    rows = history() + [event('fee', END - timedelta(days=40), None)]
    result = report(rows, 90)
    assert result['metrics']['profit_sol']['value'] is None
    assert result['metrics']['positive_weeks']['value'] == '4'
    assert [week['profit_sol'] for week in result['weekly']] == ['1'] * 4


def test_primary_interval_cannot_override_unsupported_activity():
    rows = history() + [{'kind': 'unsupported', 'timestamp': '2026-01-20T12:00:00Z',
                         'order': 1, 'reason': 'Unsupported swap', 'evidence': ['synthetic-gap']}]
    result = report(rows, 7, history_complete=False, interval_coverage=declaration())
    assert result['metrics']['positive_weeks']['value'] is None
    assert all(week['profit_sol'] is None for week in result['weekly'])
    assert any('unsupported activity' in week['reason'] for week in result['weekly'])


def test_missing_prior_week_basis_remains_unknown_even_with_interval_declaration():
    rows = history()[1:]
    result = report(rows, 7, interval_coverage=declaration())
    assert [week['profit_sol'] for week in result['weekly']] == [None, '1', '1', '1']
    assert result['metrics']['positive_weeks']['value'] is None
    assert 'basis or exit costs' in result['weekly'][0]['reason']
    assert result['metrics']['profit_sol']['value'] == '1'


@pytest.mark.parametrize('evidence', [[], ['synthetic'], [True], ['A' * 64]])
def test_complete_interval_requires_valid_primary_hash_references(evidence):
    with pytest.raises(ValueError):
        report(history(), 7, interval_coverage=declaration(evidence=evidence))


@pytest.mark.parametrize('coverage', [{'four_weeks': None}, {'not_an_interval': {}},
                                      {'four_weeks': {'start': '2026-01-31T00:00:00Z',
                                                      'end': '2026-01-03T00:00:00Z',
                                                      'status': 'complete', 'evidence': [PRIMARY_HASH]}}])
def test_invalid_interval_record_does_not_fall_back_to_trusted_completeness(coverage):
    with pytest.raises(ValueError):
        report(history(), 7, interval_coverage=coverage)
