"""Selected raw/FIFO cohort development controls, never genuine B3 proof."""
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json

import pytest

from scanner.archive_input import VERSION as ARCHIVE_VERSION, canonical_bytes, pack_bytes
from test_indexed_report_integration import guarded, session, import_report, rebuild
from test_position_evidence import raw_exchange, address, MINT, WALLET, START, END, WINDOW
from test_wallet_evidence import derive, record


def observations(raws, **kwargs):
    return derive(raws, **kwargs)['query_accounting']['selected_cohort_observations']


def interval(value, name='report_period'):
    return value['intervals'][name]


def exchange(signature, slot, at, before, after, *, mint=MINT, cash=1_000_000_000, fee=5000):
    """Integer source endpoints/instructions are the oracle, not decoder output."""
    raw = raw_exchange(signature, slot, at, before, after)
    buying = after > before
    for field in ('preTokenBalances', 'postTokenBalances'):
        for row in raw['meta'][field]:
            if row['mint'] == MINT:
                row['mint'] = mint
            if row['mint'] == 'So11111111111111111111111111111111111111112' and row['uiTokenAmount']['amount'] != '0':
                row['uiTokenAmount']['amount'] = str(cash)
    for instruction in raw['meta']['innerInstructions'][0]['instructions']:
        info = instruction['parsed']['info']
        if info['mint'] == MINT:
            info['mint'] = mint
        else:
            info['tokenAmount']['amount'] = str(cash)
    raw['transaction']['message']['instructions'][0]['accounts'][3] = mint
    for field in ('preBalances', 'postBalances'):
        raw['meta'][field] = [value if value != 1_002_000_000 else cash + 2_000_000 for value in raw['meta'][field]]
    raw['meta']['fee'] = fee
    raw['meta']['postBalances'][0] = raw['meta']['preBalances'][0] - fee
    return raw


def test_losing_and_breakeven_closed_cohort_keeps_open_stock_separate():
    raws = [exchange('buy-loss', 100, START + 3600, 0, 100),
            exchange('close-loss', 101, START + 7200, 100, 0),
            exchange('buy-even', 102, START + 10800, 0, 100),
            exchange('close-even', 103, START + 14400, 100, 0, cash=1_000_010_000),
            exchange('buy-open', 104, START + 18000, 0, 100, cash=1_000_010_000)]
    before = deepcopy(raws)
    result = derive(raws)
    cohort = result['query_accounting']['selected_cohort_observations']
    closed = interval(cohort)['closed_cohort']
    assert closed['candidate_count'] == 2
    assert closed['population_state'] == closed['monetary_state'] == closed['timing_state'] == 'PASS'
    assert closed['conditional_profit_sol'] == '-0.00001'
    assert closed['conditional_win_rate_pct'] == '0'
    assert closed['conditional_median_hold_hours'] == '1'
    assert cohort['open_stock']['candidate_count'] == 1
    assert cohort['open_stock']['cost_basis_state'] == 'PASS'
    assert cohort['open_stock']['conditional_remaining_basis_sol'] == '1.000015'
    assert cohort['open_stock']['closing_value_sol'] is None
    assert cohort['open_stock']['valuation_state'] == 'UNKNOWN'
    assert result['components']['observed_positions']['state'] == 'UNKNOWN'
    assert result['metric_dependencies']['profit_sol']['state'] == 'UNKNOWN'
    assert cohort['wallet_population_state'] == cohort['classification_state'] == 'UNKNOWN'
    assert cohort['qualification'] is False and raws == before


def test_partial_exit_preserves_exact_fifo_remaining_basis_and_disposal_profit():
    raws = [exchange('buy', 100, START + 3600, 0, 100),
            exchange('partial-exit', 101, START + 7200, 100, 50)]
    cohort = observations(raws)
    disposed = interval(cohort)['disposed_units']
    assert disposed['candidate_sale_count'] == 1
    assert disposed['monetary_state'] == disposed['quantity_state'] == 'PASS'
    assert disposed['disposed_raw_by_mint'] == {MINT: '50'}
    assert disposed['conditional_matched_basis_sol'] == '0.5000025'
    assert disposed['conditional_profit_sol'] == '0.4999925'
    assert cohort['open_stock']['conditional_remaining_basis_sol'] == '0.5000025'
    assert interval(cohort)['closed_cohort']['candidate_count'] == 0
    assert interval(cohort)['closed_cohort']['timing_state'] == 'UNKNOWN'


def test_unmatched_sale_remains_in_the_disposal_denominator_without_free_basis():
    result = derive([exchange('missing-origin-sale', 101, START + 7200, 100, 0)])
    cohort = result['query_accounting']['selected_cohort_observations']
    disposed = interval(cohort)['disposed_units']
    assert disposed['candidate_sale_count'] == 1
    assert disposed['quantity_state'] == 'PASS'
    assert disposed['disposed_raw_by_mint'] == {MINT: '100'}
    assert disposed['monetary_state'] == 'UNKNOWN' and disposed['conditional_profit_sol'] is None
    assert interval(cohort)['closed_cohort']['candidate_count'] == 1
    assert interval(cohort)['closed_cohort']['monetary_state'] == 'UNKNOWN'
    assert result['components']['native_fee']['state'] == 'PASS'


def test_real_input_flags_classification_and_valuation_cannot_promote_selected_cohort():
    raws = [exchange('buy', 100, START + 3600, 0, 100), exchange('sale', 101, START + 7200, 100, 0)]
    sources = []
    for kind in ('classification', 'valuation'):
        payload = {'kind': kind, 'classification': 'meme', 'complete': True}
        sources.append({'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'kind': kind, 'payload': payload})
    result = derive(raws, raw_sources=sources, history_evidence={'wallet_history_complete': True},
        positions=[{'basis_sol': '0', 'status': 'closed'}], events=[{'kind': 'sell', 'amount_sol': '999'}])
    closed = interval(result['query_accounting']['selected_cohort_observations'])['closed_cohort']
    assert closed['monetary_state'] == closed['timing_state'] == 'PASS'
    assert closed['conditional_profit_sol'] == '-0.00001'
    assert closed['wallet_population_state'] == closed['classification_state'] == 'UNKNOWN'
    assert result['components']['boundary_inventory']['state'] == result['components']['historical_marks']['state'] == 'UNKNOWN'
    assert result['components']['native_fee']['state'] == 'PASS'


@pytest.mark.parametrize('variant', ['missing', 'conflicting', 'unsupported', 'malformed'])
def test_required_alternative_loss_never_strengthens_a_selected_cohort_and_restore_recovers(variant):
    raws = [exchange('buy', 100, START + 3600, 0, 100), exchange('sale', 101, START + 7200, 100, 0)]
    parent = observations(raws)
    alternative = deepcopy(raws[0])
    if variant == 'missing':
        link = {'signature': 'buy', 'evidence_hash': 'a' * 64, 'raw': None}
    else:
        if variant == 'conflicting':
            alternative['meta']['preTokenBalances'][0]['uiTokenAmount']['amount'] = '1'
            alternative['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '101'
        elif variant == 'unsupported':
            alternative['version'] = 1
        else:
            alternative['meta']['preTokenBalances'][0]['uiTokenAmount']['amount'] = []
        link = record(alternative)
    child = observations(raws, alternatives=[link])
    closed = interval(child)['closed_cohort']
    assert closed['candidate_count'] == 1
    assert closed['monetary_state'] == closed['timing_state'] == 'UNKNOWN'
    assert closed['conditional_profit_sol'] is None
    assert interval(child)['disposed_units']['candidate_sale_count'] == 1
    assert parent == observations(raws, alternatives=[record(deepcopy(raws[0]))])


def test_missing_trade_fee_revokes_money_and_open_basis_but_preserves_closed_holding_time():
    raws = [exchange('buy', 100, START + 3600, 0, 100), exchange('sale', 101, START + 7200, 100, 0)]
    raws[0]['meta']['fee'] = None
    closed = interval(observations(raws))['closed_cohort']
    assert closed['candidate_count'] == 1 and closed['timing_state'] == 'PASS'
    assert closed['conditional_median_hold_hours'] == '1'
    assert closed['monetary_state'] == 'UNKNOWN' and closed['conditional_profit_sol'] is None


@pytest.mark.parametrize('selected', [True, False], ids=['selected', 'alternative'])
def test_missing_exit_fee_retains_quantity_timing_and_independent_remaining_basis(selected):
    raws = [exchange('buy', 100, START + 3600, 0, 100), exchange('partial', 101, START + 7200, 100, 50)]
    before = observations(raws)
    original = deepcopy(raws[1])
    broken = deepcopy(original)
    broken['meta']['fee'] = None
    if selected:
        raws[1] = broken
        result = observations(raws)
    else:
        result = observations(raws, alternatives=[record(broken)])
    stock = result['open_stock']
    assert stock['quantity_state'] == stock['cost_basis_state'] == 'PASS'
    assert stock['conditional_remaining_basis_sol'] == '0.5000025'
    assert stock['lots'][0]['remaining_raw'] == '50'
    disposed = interval(result)['disposed_units']
    assert disposed['candidate_sale_count'] == 1
    assert disposed['quantity_state'] == 'PASS'
    assert disposed['monetary_state'] == 'UNKNOWN'
    assert disposed['conditional_profit_sol'] is None
    raws[1] = original
    assert observations(raws) == before


def test_later_missing_sale_fee_retains_earlier_supported_disposal_but_not_aggregate_profit():
    raws = [exchange('buy', 100, START + 3600, 0, 100),
            exchange('partial', 101, START + 7200, 100, 50),
            exchange('final', 102, START + 10800, 50, 0)]
    parent = observations(raws)
    original = deepcopy(raws[-1])
    raws[-1]['meta']['fee'] = None
    child = observations(raws)
    disposed = interval(child)['disposed_units']
    assert disposed['candidate_sale_count'] == 2 and disposed['quantity_state'] == 'PASS'
    assert disposed['monetary_state'] == 'UNKNOWN' and disposed['conditional_profit_sol'] is None
    rows = {row['signature']: row for row in disposed['sales']}
    assert rows['partial']['monetary_state'] == 'PASS'
    assert rows['partial']['conditional_matched_basis_sol'] == '0.5000025'
    assert rows['partial']['conditional_profit_sol'] == '0.4999925'
    assert rows['final']['monetary_state'] == 'UNKNOWN' and rows['final']['conditional_profit_sol'] is None
    closed = interval(child)['closed_cohort']
    assert closed['candidate_count'] == 1 and closed['timing_state'] == 'PASS'
    assert closed['conditional_median_hold_hours'] == '2'
    assert closed['monetary_state'] == 'UNKNOWN'
    raws[-1] = original
    assert observations(raws) == parent


def test_missing_fee_in_a_prior_closed_episode_does_not_erase_supported_reentry():
    raws = [exchange('old-buy', 100, START + 3600, 0, 100),
            exchange('old-close', 101, START + 7200, 100, 0),
            exchange('new-buy', 102, START + 10800, 0, 100),
            exchange('new-close', 103, START + 14400, 100, 0)]
    raws[0]['meta']['fee'] = None
    result = derive(raws)
    lots = result['query_accounting']['supported_selected_lots']
    assert lots[0]['monetary_state'] == 'UNKNOWN' and lots[0]['timing_state'] == 'PASS'
    assert lots[1]['monetary_state'] == lots[1]['timing_state'] == 'PASS'
    assert lots[1]['conditional_lot_profit_sol'] == '-0.00001'
    disposed = interval(result['query_accounting']['selected_cohort_observations'])['disposed_units']
    assert disposed['candidate_sale_count'] == 2 and disposed['monetary_state'] == 'UNKNOWN'
    new_sale = next(row for row in disposed['sales'] if row['signature'] == 'new-close')
    assert new_sale['monetary_state'] == 'PASS' and new_sale['conditional_profit_sol'] == '-0.00001'


def test_missing_fee_quantity_fallback_cannot_hide_another_evidenced_same_mint_holding():
    raw = exchange('buy', 100, START + 3600, 0, 100)
    raw['meta']['fee'] = None
    raw['transaction']['message']['accountKeys'].append(address(45))
    for field in ('preBalances', 'postBalances'):
        raw['meta'][field].append(2_000_000)
    for field in ('preTokenBalances', 'postTokenBalances'):
        row = deepcopy(raw['meta'][field][0])
        row['accountIndex'] = 5
        row['uiTokenAmount']['amount'] = '50'
        raw['meta'][field].append(row)
    result = derive([raw])
    lot = result['query_accounting']['supported_selected_lots'][0]
    assert lot['quantity_state'] == 'PASS'
    assert lot['origin_state'] == lot['remaining_quantity_state'] == 'UNKNOWN'
    assert lot['conditional_remaining_basis_sol'] is None
    stock = result['query_accounting']['selected_cohort_observations']['open_stock']
    assert stock['quantity_state'] == stock['cost_basis_state'] == 'UNKNOWN'
    assert stock['lots'][0]['remaining_raw'] is None


@pytest.mark.parametrize('fee', [None, -1, True, '5000', []])
def test_invalid_fee_fallback_never_replaces_a_quantity_or_route_proof(fee):
    raw = exchange('buy', 100, START + 3600, 0, 100)
    raw['meta']['fee'] = fee
    raw['transaction']['message']['instructions'][0]['programId'] = address(44)
    result = observations([raw])
    assert result['open_stock']['cost_basis_state'] == 'UNKNOWN'
    assert result['open_stock']['conditional_remaining_basis_sol'] is None
    assert interval(result)['closed_cohort']['timing_state'] == 'UNKNOWN'


def test_selected_cohorts_and_disposals_use_independent_report_28_and_90_day_scopes():
    raws = [exchange('old-buy', 100, START - 20 * 86400, 0, 100),
            exchange('old-close', 101, START - 19 * 86400, 100, 0),
            exchange('before-28-buy', 102, START + 3600, 0, 100),
            exchange('before-28-close', 103, START + 7200, 100, 0),
            exchange('recent-buy', 104, END - 7200, 0, 100),
            exchange('recent-close', 105, END - 3600, 100, 0)]
    cohort = observations(raws)
    assert interval(cohort)['closed_cohort']['candidate_count'] == 2
    assert interval(cohort, 'four_weeks')['closed_cohort']['candidate_count'] == 1
    assert interval(cohort, 'verification_90d')['closed_cohort']['candidate_count'] == 3
    assert interval(cohort)['disposed_units']['candidate_sale_count'] == 2
    assert interval(cohort, 'four_weeks')['disposed_units']['candidate_sale_count'] == 1
    assert interval(cohort, 'verification_90d')['disposed_units']['candidate_sale_count'] == 3
    assert interval(cohort, 'four_weeks')['closed_cohort']['conditional_profit_sol'] == '-0.00001'
    assert interval(cohort, 'verification_90d')['closed_cohort']['conditional_profit_sol'] == '-0.00003'


def test_pre_window_acquisition_basis_is_consumed_without_charging_its_fee_twice():
    raws = [exchange('pre-buy', 100, START - 3600, 0, 100),
            exchange('report-sale', 101, START + 3600, 100, 0)]
    result = derive(raws)
    disposed = interval(result['query_accounting']['selected_cohort_observations'])['disposed_units']
    assert disposed['conditional_matched_basis_sol'] == '1.000005'
    assert disposed['conditional_exit_fees_sol'] == '0.000005'
    assert disposed['conditional_profit_sol'] == '-0.00001'
    assert result['interval_checks']['report_period']['selected_record_membership']['pre-buy']['member'] is False
    assert result['components']['fee_window']['state'] == 'PASS'


def test_unknown_earlier_inventory_cannot_supply_a_supported_remaining_stock_quantity():
    result = observations([exchange('stock-plus-buy', 100, START + 3600, 50, 150)])
    stock = result['open_stock']
    assert stock['candidate_count'] == 1
    assert stock['quantity_state'] == stock['cost_basis_state'] == 'UNKNOWN'
    assert stock['lots'][0]['observed_physical_state'] == 'PASS'
    assert stock['lots'][0]['remaining_raw'] is None
    assert stock['conditional_remaining_basis_sol'] is None


def test_permutation_and_duplicate_source_declarations_do_not_duplicate_cohort_denominators():
    raws = [exchange('buy', 100, START + 3600, 0, 100), exchange('sale', 101, START + 7200, 100, 0)]
    assert observations(raws) == observations(list(reversed(raws * 2)))


@pytest.mark.parametrize('role', ['wallet-account-info', 'wallet-account-source', 'wallet-identity-affinity'])
def test_identity_source_label_cannot_hide_readable_native_alternatives(role):
    raws = [exchange('buy', 100, START + 3600, 0, 100), exchange('sale', 101, START + 7200, 100, 0)]
    original = observations(raws)
    foreign = deepcopy(raws[0])
    foreign['meta']['preTokenBalances'][0]['uiTokenAmount']['amount'] = '1'
    foreign['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '101'
    source = {'hash': hashlib.sha256(canonical_bytes(foreign)).hexdigest(), 'kind': role, 'payload': foreign}
    child = observations(raws, raw_sources=[source])
    closed = interval(child)['closed_cohort']
    assert closed['candidate_count'] == 1
    assert closed['timing_state'] == closed['monetary_state'] == 'UNKNOWN'
    assert closed['conditional_profit_sol'] is None
    assert observations(raws) == original


def test_readable_account_source_alias_does_not_erase_independent_selected_fees():
    from test_wallet_identity import paired, source
    raws = [exchange('buy', 100, START + 3600, 0, 100), exchange('sale', 101, START + 7200, 100, 0)]
    payload, _, _ = paired()
    current = source(payload, 'wallet-account-source')
    result = derive(raws, raw_sources=[current])
    assert result['components']['native_fee']['state'] == result['components']['fee_window']['state'] == 'PASS'
    assert interval(result['query_accounting']['selected_cohort_observations'])['closed_cohort']['timing_state'] == 'PASS'
    current['payload'] = None
    child = derive(raws, raw_sources=[current])
    assert child['components']['native_fee']['state'] == child['components']['fee_window']['state'] == 'PASS'
    assert child['wallet_identity']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('selected', [True, False], ids=['selected', 'alternative'])
def test_consumed_unknown_cost_does_not_erase_a_known_surviving_acquisition(selected):
    raws = [exchange('old-buy', 100, START + 3600, 0, 100),
            exchange('surviving-buy', 101, START + 7200, 100, 150),
            exchange('consume-old', 102, START + 10800, 150, 50)]
    original = deepcopy(raws[0])
    broken = deepcopy(original)
    broken['meta']['fee'] = None
    if selected:
        raws[0] = broken
        result = derive(raws)
    else:
        result = derive(raws, alternatives=[record(broken)])
    cohort = result['query_accounting']['selected_cohort_observations']
    stock = cohort['open_stock']
    assert stock['quantity_state'] == stock['cost_basis_state'] == 'PASS'
    assert stock['conditional_remaining_basis_sol'] == '1.000005'
    assert stock['lots'][0]['remaining_raw'] == '50'
    assert interval(cohort)['disposed_units']['monetary_state'] == 'UNKNOWN'
    assert interval(cohort)['disposed_units']['conditional_profit_sol'] is None
    assert result['query_accounting']['supported_selected_lots'][0]['cost_basis_state'] == 'UNKNOWN'
    assert result['query_accounting']['supported_selected_lots'][0]['remaining_cost_basis_state'] == 'PASS'
    surviving_hash = record(raws[1])['evidence_hash']
    bindings = result['query_accounting']['supported_selected_lots'][0]['remaining_acquisition_checks']
    assert any(check['dependencies'] == ['surviving_fifo_acquisition_binding'] and check['evidence'] == [surviving_hash]
               for check in bindings)
    raws[0] = original
    raws[1]['meta']['fee'] = None
    required_loss = observations(raws)
    assert required_loss['open_stock']['cost_basis_state'] == 'UNKNOWN'
    assert required_loss['open_stock']['conditional_remaining_basis_sol'] is None
    raws[1]['meta']['fee'] = 5000
    assert observations(raws)['open_stock']['conditional_remaining_basis_sol'] == '1.000005'


def test_same_second_ordered_reentry_keeps_each_episode_dependency_separate():
    raws = [exchange('buy-1', 100, START + 3600, 0, 100),
            exchange('close-1', 101, START + 3600, 100, 0),
            exchange('buy-2', 102, START + 3600, 0, 100),
            exchange('close-2', 103, START + 3600, 100, 0)]
    parent = derive(raws)
    lots = parent['query_accounting']['supported_selected_lots']
    assert [lot['required_signatures'] for lot in lots] == [['buy-1', 'close-1'], ['buy-2', 'close-2']]
    assert all(lot['monetary_state'] == lot['timing_state'] == 'PASS' for lot in lots)
    assert all(lot['conditional_hold_hours'] == '0' for lot in lots)
    closed = interval(parent['query_accounting']['selected_cohort_observations'])['closed_cohort']
    assert closed['candidate_count'] == 2 and closed['conditional_profit_sol'] == '-0.00002'
    assert closed['conditional_median_hold_hours'] == '0'
    assert observations(raws) == observations(list(reversed(raws)))
    raws[2]['meta']['fee'] = None
    child = derive(raws)['query_accounting']['supported_selected_lots']
    assert child[0]['monetary_state'] == child[0]['timing_state'] == 'PASS'
    assert child[1]['monetary_state'] == 'UNKNOWN' and child[1]['timing_state'] == 'PASS'
    for raw in raws:
        raw['slot'] = 100
    unknown_order = observations(raws)
    assert interval(unknown_order)['closed_cohort']['timing_state'] == 'UNKNOWN'


@pytest.mark.parametrize('alternative', [False, True], ids=['selected', 'linked-alternative'])
def test_same_second_ordered_topup_requires_zero_only_at_the_initial_acquisition(alternative):
    raws = [exchange('initial', 100, START + 3600, 0, 100),
            exchange('topup', 101, START + 3600, 100, 150),
            exchange('close', 102, START + 3601, 150, 0)]
    alternatives = [record(deepcopy(raws[1]))] if alternative else []
    result = derive(raws, alternatives=alternatives)
    lot = result['query_accounting']['supported_selected_lots'][0]
    assert lot['origin_state'] == lot['monetary_state'] == lot['timing_state'] == 'PASS'
    assert lot['conditional_lot_profit_sol'] == '-1.000015'
    with localcontext() as context:
        context.prec = 256
        assert abs(Decimal(lot['conditional_hold_hours']) - Decimal(1) / Decimal(3600)) < Decimal('1e-180')
    raws[1]['meta']['fee'] = None
    child = derive(raws)['query_accounting']['supported_selected_lots'][0]
    assert child['origin_state'] == child['timing_state'] == 'PASS'
    assert child['monetary_state'] == 'UNKNOWN'
    assert child['conditional_lot_profit_sol'] is None


@pytest.mark.parametrize('transfer_kind', ['incoming', 'outgoing'])
def test_proved_later_same_second_transfer_does_not_erase_prior_closed_lot(transfer_kind):
    raws = [exchange('buy', 100, START + 3599, 0, 100),
            exchange('close', 101, START + 3600, 100, 0)]
    later = exchange('later-transfer', 102, START + 3600, 0, 50) if transfer_kind == 'incoming' else exchange(
        'later-transfer', 102, START + 3600, 50, 0)
    later['transaction']['message']['instructions'][0]['programId'] = address(44)
    result = derive(raws + [later])
    lots = result['query_accounting']['supported_selected_lots']
    assert lots[0]['monetary_state'] == lots[0]['timing_state'] == 'PASS'
    assert lots[0]['conditional_lot_profit_sol'] == '-0.00001'
    assert 'later-transfer' in lots[0]['disjoint_signatures']
    assert lots[1]['monetary_state'] == lots[1]['timing_state'] == 'UNKNOWN'
    closed = interval(result['query_accounting']['selected_cohort_observations'])['closed_cohort']
    assert closed['population_state'] == closed['monetary_state'] == closed['timing_state'] == 'UNKNOWN'
    assert closed['conditional_profit_sol'] is None
    unknown_order = deepcopy(later)
    unknown_order['slot'] = 101
    lost_order = derive(raws + [unknown_order])['query_accounting']['supported_selected_lots'][0]
    assert lost_order['monetary_state'] == lost_order['timing_state'] == 'UNKNOWN'


def thirds_raws(*, close=False):
    raws = [exchange('buy-three', 100, START + 3600, 0, 3, fee=5001),
            exchange('sell-one', 101, START + 7200, 3, 2, fee=5001)]
    if close:
        raws.append(exchange('sell-two', 102, START + 10800, 2, 0, fee=5001))
    return raws


@pytest.mark.parametrize('close', [False, True], ids=['partial', 'closed'])
def test_high_precision_internal_fifo_outputs_remain_supported_and_conserve_cost(close):
    cohort = observations(thirds_raws(close=close))
    disposed = interval(cohort)['disposed_units']
    assert disposed['quantity_state'] == disposed['monetary_state'] == 'PASS'
    assert len(disposed['sales'][0]['conditional_matched_basis_sol']) > 100
    # Independent integer cash endpoints and rational allocation are the oracle.
    basis = Fraction(1_000_005_001, 1_000_000_000)
    fee = Fraction(5001, 1_000_000_000)
    with localcontext() as context:
        context.prec = 256
        first_basis = Decimal(basis.numerator) / Decimal(basis.denominator * 3)
        assert abs(Decimal(disposed['sales'][0]['conditional_matched_basis_sol']) - first_basis) < Decimal('1e-180')
        expected = Fraction(2) - basis - 2 * fee if close else Fraction(1) - basis / 3 - fee
        expected_decimal = Decimal(expected.numerator) / Decimal(expected.denominator)
        assert abs(Decimal(disposed['conditional_profit_sol']) - expected_decimal) < Decimal('1e-180')
        if close:
            assert disposed['conditional_matched_basis_sol'] == '1.000005001'
            assert disposed['conditional_exit_fees_sol'] == '0.000010002'
            assert interval(cohort)['closed_cohort']['conditional_profit_sol'] == '0.999984997'
        else:
            stock = cohort['open_stock']
            assert stock['cost_basis_state'] == 'PASS'
            assert abs(Decimal(stock['conditional_remaining_basis_sol']) - 2 * first_basis) < Decimal('1e-180')
            assert abs(Decimal(disposed['conditional_matched_basis_sol']) + Decimal(stock['conditional_remaining_basis_sol'])
                       - Decimal(basis.numerator) / Decimal(basis.denominator)) < Decimal('1e-180')


@pytest.mark.parametrize('close', [False, True], ids=['partial', 'closed'])
def test_high_precision_fifo_archive_api_rebuild_and_export_are_offline(guarded, close):
    client, app, _, calls = guarded
    parent = import_report(client, archive(thirds_raws(close=close)))
    stored = deepcopy(app.state.store.get('reports', parent['id']))
    cohort = parent['coverage']['wallet_evidence']['query_accounting']['selected_cohort_observations']
    assert interval(cohort)['disposed_units']['monetary_state'] == 'PASS'
    child = rebuild(client, parent)
    assert child['coverage']['wallet_evidence']['query_accounting']['selected_cohort_observations'] == cohort
    assert app.state.store.get('reports', parent['id']) == stored
    exported = client.get('/api/export/reports/' + child['id'] + '.json')
    assert exported.status_code == 200
    assert exported.json()['coverage']['wallet_evidence']['query_accounting']['selected_cohort_observations'] == cohort
    assert calls == {'provider': 0, 'credential': 0, 'transport': 0}


def test_surviving_acquisition_source_removal_restoration_keeps_report_parent_immutable(guarded):
    client, app, _, calls = guarded
    raws = [exchange('old-buy', 100, START + 3600, 0, 100),
            exchange('surviving-buy', 101, START + 7200, 100, 150),
            exchange('consume-old', 102, START + 10800, 150, 50)]
    raws[0]['meta']['fee'] = None
    parent = import_report(client, archive(raws))
    stored = deepcopy(app.state.store.get('reports', parent['id']))
    cohort = parent['coverage']['wallet_evidence']['query_accounting']['selected_cohort_observations']
    assert cohort['open_stock']['conditional_remaining_basis_sol'] == '1.000005'
    path = app.state.store.path / 'evidence' / (record(raws[1])['evidence_hash'] + '.json.gz')
    original = path.read_bytes()
    path.unlink()
    lost = rebuild(client, parent)['coverage']['wallet_evidence']['query_accounting']['selected_cohort_observations']
    assert lost['open_stock']['cost_basis_state'] == 'UNKNOWN'
    assert lost['open_stock']['conditional_remaining_basis_sol'] is None
    path.write_bytes(original)
    restored = rebuild(client, parent)
    assert restored['coverage']['wallet_evidence']['query_accounting']['selected_cohort_observations'] == cohort
    assert app.state.store.get('reports', parent['id']) == stored
    assert calls == {'provider': 0, 'credential': 0, 'transport': 0}


@pytest.mark.parametrize('role', ['wallet-account-info', 'wallet-account-source', 'wallet-identity-affinity'])
def test_account_byte_envelope_cannot_hide_conflicting_native_fee_or_lost_alternative(role):
    from scanner.wallet_identity import account_info_source
    from scanner.wallet_evidence import raw_native_dependencies
    raws = [exchange('buy', 100, START + 3600, 0, 100), exchange('sale', 101, START + 7200, 100, 0)]
    original = deepcopy(raws[0])
    conflicting = deepcopy(original)
    conflicting['meta']['fee'] = 6000
    conflicting['meta']['postBalances'][0] -= 1000
    request = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'getTransaction',
                          'params': ['buy', {'encoding': 'json', 'maxSupportedTransactionVersion': 0}]}).encode()
    response = json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': conflicting}).encode()
    payload = account_info_source(request, response)
    source = {'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'kind': role, 'payload': payload}
    links = raw_native_dependencies([source], (), ['buy', 'sale'])
    assert len(links) == 1 and links[0]['signature'] == 'buy'
    assert links[0]['raw'] == conflicting
    child = derive(raws, raw_sources=[source])
    assert child['components']['native_fee']['state'] == 'UNKNOWN'
    assert child['components']['observed_cost_roles']['state'] == 'UNKNOWN'
    lost_source = {**source, 'payload': None}
    frozen = [{**row, 'raw': None} for row in links]
    lost = derive(raws, raw_sources=[lost_source], alternatives=frozen)
    assert lost['components']['native_fee']['state'] == 'UNKNOWN'
    assert derive(raws, raw_sources=[source]) == child
    assert derive(raws)['components']['native_fee']['state'] == 'PASS'


@pytest.mark.parametrize('variant', ['corrupt-request', 'corrupt-response', 'malformed-native'])
def test_unreadable_or_unassignable_account_envelope_cannot_prove_native_disjointness(variant):
    from scanner.wallet_identity import account_info_source
    from scanner.wallet_evidence import raw_native_dependencies
    raws = [exchange('buy', 100, START + 3600, 0, 100), exchange('sale', 101, START + 7200, 100, 0)]
    response = {'jsonrpc': '2.0', 'id': 1, 'result': {'transaction': [], 'meta': {}}}
    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'getAccountInfo', 'params': [WALLET, {'commitment': 'finalized'}]}
    payload = account_info_source(json.dumps(request).encode(), json.dumps(response).encode())
    if variant == 'corrupt-request':
        payload['request_hash'] = 'a' * 64
    elif variant == 'corrupt-response':
        payload['response_hash'] = 'a' * 64
    source = {'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'kind': 'wallet-account-info', 'payload': payload}
    links = raw_native_dependencies([source], (), ['buy', 'sale'])
    assert any(row['signature'] is None for row in links)
    assert derive(raws, raw_sources=[source])['components']['native_fee']['state'] == 'UNKNOWN'


def archive(raws):
    rows = [record(raw) for raw in raws]
    manifest = {'version': ARCHIVE_VERSION, 'address': WALLET, 'window': WINDOW, 'dataset': 'real',
        'transactions': [{'signature': row['signature'], 'hash': row['evidence_hash']} for row in rows], 'evidence': []}
    return pack_bytes({'manifest': manifest, 'payloads': {row['evidence_hash']: row['raw'] for row in rows}})


def test_normal_archive_saved_report_rebuild_exports_and_source_restoration_stay_offline(guarded):
    client, app, _, calls = guarded
    raws = [exchange('buy', 100, START + 3600, 0, 100), exchange('sale', 101, START + 7200, 100, 0)]
    parent = import_report(client, archive(raws))
    stored = deepcopy(app.state.store.get('reports', parent['id']))
    parent_cohort = parent['coverage']['wallet_evidence']['query_accounting']['selected_cohort_observations']
    assert interval(parent_cohort)['closed_cohort']['conditional_profit_sol'] == '-0.00001'
    buy_hash = record(raws[0])['evidence_hash']
    path = app.state.store.path / 'evidence' / f'{buy_hash}.json.gz'
    original = path.read_bytes()
    path.unlink()
    lost = rebuild(client, parent)
    child_cohort = lost['coverage']['wallet_evidence']['query_accounting']['selected_cohort_observations']
    assert interval(child_cohort)['closed_cohort']['monetary_state'] == 'UNKNOWN'
    assert interval(child_cohort)['closed_cohort']['candidate_count'] == 1
    path.write_bytes(original)
    restored = rebuild(client, parent)
    assert restored['coverage']['wallet_evidence']['query_accounting']['selected_cohort_observations'] == parent_cohort
    assert app.state.store.get('reports', parent['id']) == stored
    export = client.get('/api/export/reports/' + restored['id'] + '.json')
    assert export.status_code == 200
    assert export.json()['coverage']['wallet_evidence']['query_accounting']['selected_cohort_observations'] == parent_cohort
    csv = client.get('/api/export/reports/' + restored['id'] + '.csv')
    assert csv.status_code == 200
    assert calls == {'provider': 0, 'credential': 0, 'transport': 0}
