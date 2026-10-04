"""Scoped research monetary consumers; unsigned controls do not establish B3."""
from copy import deepcopy
from decimal import Decimal

import pytest

from scanner.archive_input import canonical_bytes, pack_bytes
from scanner.investigation import decode_supported_swaps
from scanner.research import VERSION, summarize_research
from scanner.wallet_evidence import VERSION as WALLET_VERSION, derive_wallet_evidence
from test_research import START, END, anchor, pair, swap, fee
from test_retained_protocol_funding import (originals, wrapped, foreign_cash_loop, native_pair,
    cash, WALLET as REAL_WALLET, WINDOW as REAL_WINDOW)
from test_real_coverage import closing_raws, source, record, archived_query_bundle
from test_position_evidence import WALLET, WINDOW
from test_indexed_report_integration import guarded, session, import_report, rebuild


def facts(raws, wallet, window=REAL_WINDOW, alternatives=()):
    rows = [wrapped(raw) for raw in raws]
    events = decode_supported_swaps(rows, wallet)['events']
    receipt = derive_wallet_evidence(rows, all_records=rows + list(alternatives), wallet=wallet,
        window=window, source_consistency={}, chronology={})
    return events, receipt


@pytest.mark.parametrize('native_quote', [False, True], ids=['wrapped', 'native'])
@pytest.mark.parametrize('ordinal', [0, 1], ids=['buy', 'sell'])
def test_raw_cash_roles_revoke_research_money_and_preserve_quantity_time_fees(native_quote, ordinal):
    if native_quote:
        raws, wallet, foreign = native_pair()
        expected, fees = '-0.10001', '0.00001'
    else:
        rows = originals(); raws, wallet = [rows[83], rows[85]], REAL_WALLET
        expected, fees = '-0.013270924', '0.000065767'
    events, receipt = facts(raws, wallet)
    clean = summarize_research(events, **{'start': REAL_WINDOW['start'], 'end': REAL_WINDOW['end']}, wallet_evidence=receipt)
    assert clean['conditional_observed_lot_profit_sol'] == expected
    assert clean['wallet_fees_paid_sol'] == fees
    damaged = deepcopy(raws)
    if native_quote:
        damaged[ordinal]['meta']['innerInstructions'][0]['instructions'] += [cash(wallet, foreign, 1), cash(foreign, wallet, 1)]
    else:
        if ordinal == 0:
            damaged[ordinal] = foreign_cash_loop(damaged[ordinal])
        else:
            # A same-route foreign loop needs no key-index shift on the parsed
            # sell control: use the normalization view and distinct named keys.
            from scanner.transaction_format import instruction_view
            damaged[ordinal] = deepcopy(instruction_view(damaged[ordinal]))
            foreign = 'development-foreign-native-role'
            route_index = 1  # Original genuine sell's reviewed outer route.
            group = next(g for g in damaged[ordinal]['meta']['innerInstructions'] if g['index'] == route_index)
            group['instructions'] += [cash(wallet, foreign, 1), cash(foreign, wallet, 1)]
    events, receipt = facts(damaged, wallet)
    before = deepcopy(events)
    result = summarize_research(events, REAL_WINDOW['start'], REAL_WINDOW['end'], wallet_evidence=receipt)
    assert result['version'] == VERSION
    assert result['unresolved_transactions'] == 2
    assert result['conditional_observed_lot_profit_sol'] is result['observed_profit_sol'] is result['known_matched_profit_sol'] is None
    assert result['sales_detail'][0]['conditional_profit_sol'] is None
    if ordinal == 0:
        assert result['sales_detail'][0]['conditional_matched_basis_sol'] is None
    else:
        assert result['sales_detail'][0]['conditional_matched_basis_sol'] is not None
    episode = result['episodes'][0]
    assert episode['monetary_state'] == 'UNKNOWN' and episode['pnl_sol'] is episode['roi_pct'] is None
    assert episode['timing_state'] == 'PASS'
    assert episode['hold_hours'] == clean['episodes'][0]['hold_hours']
    assert episode['first_sale_hours'] == clean['episodes'][0]['first_sale_hours']
    assert episode['acquired_raw'] == clean['episodes'][0]['acquired_raw']
    assert episode['sold_raw'] == clean['episodes'][0]['sold_raw']
    assert result['wallet_fees_paid_sol'] == fees
    assert any(f['title'] == 'Native monetary roles remain unresolved' for f in result['risk_findings'])
    assert summarize_research(list(reversed(events)), REAL_WINDOW['start'], REAL_WINDOW['end'], wallet_evidence=receipt) == result
    assert events == before


@pytest.mark.parametrize('state', ['UNKNOWN', None, True, {}, [], 'future'])
def test_explicit_malformed_money_state_is_safe_and_never_invents_supported_basis(state):
    events = pair(); events[0]['native_cash_role_state'] = state
    result = summarize_research(events, START, END, opening_inventory=anchor())
    assert result['conditional_observed_lot_profit_sol'] is result['known_matched_profit_sol'] is result['observed_profit_sol'] is None
    assert result['sales_detail'][0]['conditional_matched_basis_sol'] is None
    assert result['episodes'][0]['pnl_sol'] is None
    assert result['episodes'][0]['hold_hours'] == '6'
    assert result['unresolved_transactions'] == 1


def test_unknown_earlier_basis_does_not_taint_later_same_mint_or_disjoint_episode():
    events = [swap('buy', '2025-12-31T23:00:00Z', '1', signature='earlier', native_cash_role_state='UNKNOWN'),
        swap('sell', '2026-01-01T01:00:00Z', '0.9', signature='first-exit'),
        swap('buy', '2026-01-05T01:00:00Z', '1', signature='reentry'),
        swap('sell', '2026-01-05T03:00:00Z', '1.3', signature='reentry-exit'),
        swap('buy', '2026-01-06T01:00:00Z', '1', mint='mint-B', signature='other'),
        swap('sell', '2026-01-06T03:00:00Z', '1', mint='mint-B', signature='other-exit')]
    result = summarize_research(events, START, END)
    assert [row['pnl_sol'] for row in result['episodes']] == [None, '0.3', '0']
    assert [row['hold_hours'] for row in result['episodes']] == ['2', '2', '2']
    assert [row['conditional_profit_sol'] for row in result['sales_detail']] == [None, '0.3', '0']
    assert result['conditional_observed_lot_profit_sol'] == '0.3'
    assert result['observed_matched_sales'] == 2
    # Restoration of the required basis re-enables only that result.
    restored = deepcopy(events); restored[0]['native_cash_role_state'] = 'PASS'
    assert summarize_research(restored, START, END)['conditional_observed_lot_profit_sol'] == '0.2'


def test_unknown_cash_overhead_blocks_aggregate_but_preserves_independent_matched_price():
    events = pair() + [fee(), {'kind': 'capital', 'timestamp': '2026-01-06T00:00:00Z',
        'economic_role': 'unknown', 'amount_sol': '0.1', 'signature': 'different', 'evidence': ['cash-source']}]
    result = summarize_research(events, START, END, opening_inventory=anchor())
    assert result['unresolved_transactions'] == 1
    assert result['observed_profit_sol'] is result['conditional_observed_lot_profit_sol'] is None
    assert result['known_matched_profit_sol'] == result['sales_detail'][0]['conditional_profit_sol'] == '0.2'
    assert result['episodes'][0]['pnl_sol'] == '0.2'
    assert result['wallet_fees_paid_sol'] == '0.000005'


@pytest.mark.parametrize('sale', ['0.9', '1', '1.1'])
def test_legacy_unannotated_model_prices_remain_valid_losing_breakeven_and_winning(sale):
    events = pair(); events[1]['amount_sol'] = sale
    result = summarize_research(events, START, END, opening_inventory=anchor())
    expected = str(Decimal(sale) - 1).rstrip('0').rstrip('.') if sale != '1' else '0'
    assert result['conditional_observed_lot_profit_sol'] == expected
    assert result['episodes'][0]['monetary_state'] == 'PASS'


@pytest.mark.parametrize('bad', [{}, {'version': WALLET_VERSION, 'transactions': None},
    {'version': WALLET_VERSION, 'transactions': {'synthetic': {'network_fee': None}}}])
def test_malformed_internal_receipt_does_not_throw_or_become_a_passing_price_declaration(bad):
    result = summarize_research(pair() + [fee()], START, END, wallet_evidence=bad)
    assert result['conditional_observed_lot_profit_sol'] is None
    assert result['wallet_fees_paid_sol'] is None
    assert result['episodes'][0]['timing_state'] == 'UNKNOWN'


def bundle(raws, sources=(), alternatives=()):
    value = archived_query_bundle(raws[0], list(sources))
    value['manifest']['transactions'] = [{'signature': record(raw)['signature'], 'hash': record(raw)['evidence_hash']} for raw in raws]
    value['manifest']['evidence'] += [{'kind': 'transaction', 'signature': row['signature'], 'hash': row['evidence_hash']} for row in alternatives]
    value['payloads'].update({record(raw)['evidence_hash']: raw for raw in raws})
    value['payloads'].update({row['evidence_hash']: row['raw'] for row in alternatives})
    return pack_bytes(value)


@pytest.mark.parametrize('failure', ['cost', 'fee', 'clock', 'physical'])
def test_saved_api_linked_source_loss_restoration_rebuild_and_generation_are_offline(guarded, failure):
    client, app, _, calls = guarded
    raws = closing_raws()
    good = source(raws)
    positive = import_report(client, bundle(raws, [good]))
    assert positive['research']['conditional_observed_lot_profit_sol'] == '-0.00001'
    alternate = deepcopy(raws[0])
    if failure == 'cost':
        from test_retained_protocol_funding import cash
        alternate['meta']['innerInstructions'][0]['instructions'] += [cash(WALLET, 'development-other', 1), cash('development-other', WALLET, 1)]
    elif failure == 'fee':
        alternate['meta']['fee'] += 1; alternate['meta']['postBalances'][0] -= 1
    elif failure == 'clock':
        alternate['blockTime'] += 1
    else:
        from test_investigation import TOKEN_2022
        for phase in ('preTokenBalances', 'postTokenBalances'):
            for row in alternate['meta'][phase]:
                if row['mint'] == raws[0]['meta']['preTokenBalances'][0]['mint']:
                    row['programId'] = TOKEN_2022
    linked = record(alternate)
    parent = import_report(client, bundle(raws, [good], [linked]))
    frozen = deepcopy(app.state.store.get('reports', parent['id']))
    assert parent['research']['conditional_observed_lot_profit_sol'] is None
    assert parent['research']['episodes'][0]['pnl_sol'] is None
    if failure not in ('clock', 'physical'):
        assert parent['research']['episodes'][0]['timing_state'] == 'PASS'
    else:
        assert parent['research']['episodes'][0]['timing_state'] == 'UNKNOWN'
        assert parent['research']['conditional_median_hold_hours'] is None
    path = app.state.store.path / 'evidence' / (linked['evidence_hash'] + '.json.gz')
    original = path.read_bytes(); path.unlink()
    missing = rebuild(client, parent)
    assert missing['research']['conditional_observed_lot_profit_sol'] is None
    path.write_bytes(original)
    restored = rebuild(client, missing)
    assert restored['research'] == parent['research']
    assert app.state.store.get('reports', parent['id']) == frozen
    assert calls == {'provider': 0, 'credential': 0, 'transport': 0}
    # A persisted v2 result is never relabelled v3 or changed by read-time views.
    old = deepcopy(frozen); old['id'] = 'development-v2-research-' + failure
    old['research']['version'] = 'supported-subset-research-v2'
    old['research']['conditional_observed_lot_profit_sol'] = '999'
    app.state.store.put('reports', old['id'], old)
    saved = deepcopy(app.state.store.get('reports', old['id']))
    for url in ('/api/reports/' + old['id'], '/api/reports/' + old['id'] + '?view=display', '/api/export/reports/' + old['id'] + '.json'):
        response = client.get(url)
        assert response.status_code == 200
        assert response.json()['research_assessment']['state'] == 'rebuild_required'
        assert response.json()['qualification']['qualified'] is False
    summary = next(r for r in client.get('/api/state?view=summary').json()['reports'] if r['id'] == old['id'])
    assert summary['research_assessment']['state'] == 'rebuild_required'
    child = rebuild(client, client.get('/api/reports/' + old['id']).json())
    assert child['research']['version'] == VERSION
    assert child['research']['conditional_observed_lot_profit_sol'] is None
    assert app.state.store.get('reports', old['id']) == saved


@pytest.mark.parametrize('ordinal', [0, 1], ids=['buy', 'sell'])
def test_linked_physical_token_program_conflict_revokes_only_dependent_research(ordinal):
    from test_investigation import TOKEN_PROGRAM
    rows = originals(); raws = [rows[83], rows[85]]
    altered = deepcopy(raws[ordinal])
    mint = 'BQJfL1yiHbJQ8AciHLcKxaCbQrWP2ws8oZHHYgbBpump'
    for phase in ('preTokenBalances', 'postTokenBalances'):
        for balance in altered['meta'][phase]:
            if balance['mint'] == mint:
                balance['programId'] = TOKEN_PROGRAM
    events, receipt = facts(raws, REAL_WALLET, alternatives=[wrapped(altered)])
    transaction = receipt['transactions'][altered['transaction']['signatures'][0]]
    assert all(transaction['checks'][key]['state'] == 'PASS' for key in ('identity', 'cost_roles', 'clock'))
    assert transaction['mint_aggregates'][mint]['check']['state'] == 'UNKNOWN'
    result = summarize_research(events, REAL_WINDOW['start'], REAL_WINDOW['end'], wallet_evidence=receipt)
    assert result['conditional_observed_lot_profit_sol'] is None
    assert result['episodes'][0]['monetary_state'] == result['episodes'][0]['quantity_state'] == 'UNKNOWN'
    assert result['sales_detail'][0]['conditional_profit_sol'] is None
    assert result['wallet_fees_paid_sol'] == '0.000065767'
    restored_events, restored_receipt = facts(raws, REAL_WALLET)
    restored = summarize_research(restored_events, REAL_WINDOW['start'], REAL_WINDOW['end'], wallet_evidence=restored_receipt)
    assert restored['conditional_observed_lot_profit_sol'] == '-0.013270924'


@pytest.mark.parametrize('role', [None, True, {}, [], 'unsupported-future-role'])
def test_explicit_unproved_capital_roles_block_period_overhead_but_not_disjoint_lot(role):
    result = summarize_research(pair() + [{'kind': 'capital', 'timestamp': '2026-01-06T00:00:00Z',
        'amount_sol': '0.01', 'economic_role': role, 'signature': 'different', 'evidence': []}], START, END)
    assert result['unresolved_transactions'] == 1
    assert result['conditional_observed_lot_profit_sol'] is None
    assert result['sales_detail'][0]['conditional_profit_sol'] == '0.2'
    assert result['episodes'][0]['pnl_sol'] == '0.2'


@pytest.mark.parametrize('placement', ['crosses', 'outside', 'zero'], ids=['boundary-loss', 'disjoint-clock', 'proved-zero'])
def test_period_fee_projection_reuses_all_linked_clocks_and_independent_zero(placement):
    from test_position_evidence import START
    raws = closing_raws()
    failed = deepcopy(raws[0])
    failed['transaction']['signatures'] = ['development-failed-outside']
    failed['slot'] += 5; failed['blockTime'] = START - 1
    failed['meta']['err'] = {'InstructionError': [0, {'Custom': 1}]}
    # Keep this fee-only record genuinely disjoint from the target's named
    # token population; a failed attempt touching that account has different
    # scoped chronology dependencies.
    from test_position_evidence import address
    failed['transaction']['message']['accountKeys'] = [WALLET, address(23)]
    failed['transaction']['message']['instructions'] = []
    failed['meta']['preBalances'] = [10_000_000_000, 1000]
    failed['meta']['preTokenBalances'] = []
    failed['meta']['innerInstructions'] = []
    failed['meta']['postBalances'] = list(failed['meta']['preBalances'])
    failed['meta']['postBalances'][0] -= failed['meta']['fee']
    failed['meta']['postTokenBalances'] = deepcopy(failed['meta']['preTokenBalances'])
    alternate = deepcopy(failed); alternate['blockTime'] = START + 1 if placement != 'outside' else START - 2
    if placement == 'zero':
        for row in (failed, alternate):
            row['meta']['fee'] = 0
            row['meta']['postBalances'] = list(row['meta']['preBalances'])
    events, receipt = facts(raws + [failed], WALLET, WINDOW, alternatives=[wrapped(alternate)])
    result = summarize_research(events, WINDOW['start'], WINDOW['end'], wallet_evidence=receipt)
    assert result['sales_detail'][0]['conditional_profit_sol'] == '-0.00001'
    assert result['episodes'][0]['timing_state'] == 'PASS'
    if placement == 'crosses':
        assert result['wallet_fees_paid_sol'] is result['unallocated_fees_sol'] is result['conditional_observed_lot_profit_sol'] is None
    else:
        assert result['wallet_fees_paid_sol'] == '0.00001'
        assert result['conditional_observed_lot_profit_sol'] == '-0.00001'
    restored_events, restored_receipt = facts(raws + [failed], WALLET, WINDOW)
    restored = summarize_research(restored_events, WINDOW['start'], WINDOW['end'], wallet_evidence=restored_receipt)
    assert restored['wallet_fees_paid_sol'] == '0.00001'


def test_fresh_scoped_receipt_preserves_disjoint_episode_timing_without_restoring_global_coverage():
    raws = closing_raws()
    events, receipt = facts(raws, WALLET, WINDOW)
    clean = summarize_research(events, WINDOW['start'], WINDOW['end'], wallet_evidence=receipt)
    disjoint_gap = {'kind': 'unsupported', 'signature': 'different-lost-record',
                    'timestamp': None, 'evidence': ['missing-disjoint-source']}
    result = summarize_research(events + [disjoint_gap], WINDOW['start'], WINDOW['end'], wallet_evidence=receipt)
    assert result['chronology_unknown'] is True
    assert result['conditional_median_hold_hours'] is result['conditional_observed_lot_profit_sol'] is None
    assert result['episodes'][0]['timing_state'] == 'PASS'
    assert result['episodes'][0]['hold_hours'] == clean['episodes'][0]['hold_hours']
    assert result['episodes'][0]['pnl_sol'] == result['sales_detail'][0]['conditional_profit_sol'] == '-0.00001'
    assert result['wallet_fees_paid_sol'] == '0.00001'
    # Pure model events have no immutable source proof of disjointness.
    legacy = summarize_research(events + [disjoint_gap], WINDOW['start'], WINDOW['end'])
    assert legacy['episodes'][0]['timing_state'] == 'UNKNOWN'
    assert legacy['episodes'][0]['hold_hours'] is None


@pytest.mark.parametrize('gap', ['sale-only', 'one-preexisting-unit'])
def test_fresh_named_lot_origin_is_required_for_money_and_holding_time(gap):
    rows = originals(); raws = [deepcopy(rows[83]), deepcopy(rows[85])]
    mint = 'BQJfL1yiHbJQ8AciHLcKxaCbQrWP2ws8oZHHYgbBpump'
    if gap == 'sale-only':
        raws = [raws[1]]
        expected_fee = '0.000006849'
    else:
        # Unsigned development mutation: every wallet boundary gains one
        # earlier unit, retaining original Q trade conservation and continuity.
        for raw in raws:
            for phase in ('preTokenBalances', 'postTokenBalances'):
                for balance in raw['meta'][phase]:
                    if balance.get('owner') == REAL_WALLET and balance['mint'] == mint:
                        balance['uiTokenAmount']['amount'] = str(int(balance['uiTokenAmount']['amount']) + 1)
        expected_fee = '0.000065767'
    events, receipt = facts(raws, REAL_WALLET)
    named = next(p for p in receipt['query_accounting']['supported_selected_lots'] if p['mint'] == mint)
    assert named['origin_state'] == named['monetary_state'] == named['timing_state'] == 'UNKNOWN'
    result = summarize_research(events, REAL_WINDOW['start'], REAL_WINDOW['end'], wallet_evidence=receipt)
    episode = next(p for p in result['episodes'] if p['mint'] == mint)
    assert episode['monetary_state'] == episode['timing_state'] == 'UNKNOWN'
    assert episode['pnl_sol'] is episode['roi_pct'] is episode['hold_hours'] is episode['first_sale_hours'] is None
    assert result['conditional_observed_lot_profit_sol'] is None
    assert result['sales_detail'][0]['conditional_profit_sol'] is None
    assert result['wallet_fees_paid_sol'] == expected_fee
    restored_events, restored_receipt = facts([rows[83], rows[85]], REAL_WALLET)
    restored = summarize_research(restored_events, REAL_WINDOW['start'], REAL_WINDOW['end'], wallet_evidence=restored_receipt)
    assert restored['episodes'][0]['timing_state'] == restored['episodes'][0]['monetary_state'] == 'PASS'
    assert restored['episodes'][0]['pnl_sol'] == '-0.013270924'


def test_development_opening_anchor_and_fresh_receipt_preserve_original_evidence_union():
    from test_position_evidence import MINT
    raws = closing_raws()
    events, receipt = facts(raws, WALLET, WINDOW)
    opening = {MINT: {'quantity_raw': '0', 'timestamp': WINDOW['start'],
        'evidence': ['development-independent-opening'], 'scope': 'wallet_owned_mint',
        'verified': True, 'intervening_flows_complete': True}}
    result = summarize_research(events, WINDOW['start'], WINDOW['end'], wallet_evidence=receipt,
        opening_inventory=opening)
    assert result['known_matched_profit_sol'] == result['observed_profit_sol'] == '-0.00001'
    assert 'development-independent-opening' in result['evidence']
    assert set(h for event in events for h in event['evidence']) <= set(result['evidence'])
    assert result['episodes'][0]['attributable'] is True
    assert result['wallet_profit_verified'] is False
