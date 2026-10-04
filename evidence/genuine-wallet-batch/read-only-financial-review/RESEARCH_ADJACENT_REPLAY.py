"""Independent offline consumer review; no source edits or complete-wallet claim.

Unsigned mutations and opening anchors below are development controls. Genuine
83/85 records stay byte-for-byte unchanged in the clean path. Worked expectations
are pinned integer arithmetic, not read back from the production implementation.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
import inspect
import json
from pathlib import Path
import sys
import tempfile
import traceback
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]

import httpx
from pytest import MonkeyPatch
from scanner.accounting import utc
from scanner.archive_input import VERSION, canonical_bytes, pack_bytes
from scanner.investigation import decode_supported_swaps
from scanner.research import summarize_research
from scanner.wallet_evidence import derive_wallet_evidence
from test_retained_protocol_funding import originals, wrapped, WALLET, MINT, WINDOW, foreign_cash_loop
from test_discovery_integration_review import local_session, wait_record, cache_mint, candidate, save_cohort, TEST_KEY

HERE = Path(__file__).resolve().parent
START, END = '2026-01-01T00:00:00+00:00', '2026-01-31T00:00:00+00:00'
MONEY_FIELDS = ('basis_sol', 'matched_basis_sol', 'proceeds_sol', 'exit_fees_sol', 'pnl_sol', 'roi_pct')
results, failures = {}, []


def record(name, run):
    try:
        results[name] = {'status': 'PASS', 'details': run()}
    except Exception as error:
        results[name] = {'status': 'FAIL', 'error': repr(error), 'traceback': traceback.format_exc()}
        failures.append(name)


def entry(kind, timestamp, amount, signature, **extra):
    return {'kind': kind, 'timestamp': timestamp, 'order': 1, 'mint': MINT,
            'quantity_raw': '100', 'decimals': 6, 'amount_sol': amount,
            'fee_sol': '0.000005', 'classification': 'unknown', 'paid_by_wallet': True,
            'signature': signature, 'path': 'unsigned-development/swap',
            'evidence': ['a' * 64], **extra}


def display_fee(trade):
    return {'kind': 'fee', 'timestamp': trade['timestamp'], 'order': 2,
            'amount_sol': trade['fee_sol'], 'paid_by_wallet': True,
            'signature': trade['signature'], 'path': 'meta.fee', 'evidence': ['a' * 64],
            'allocation': 'buy_basis' if trade['kind'] == 'buy' else 'sell_exit',
            'allocated_trade_path': trade['path']}


def anchored(events):
    first = min(utc(row['timestamp']) for row in events)
    return {MINT: {'quantity_raw': '0', 'timestamp': (first - timedelta(seconds=1)).isoformat(),
        'scope': 'wallet_owned_mint', 'verified': True, 'intervening_flows_complete': True,
        'evidence': ['b' * 64]}}


def research(events, *, start=START, end=END, wallet=None):
    options = {'opening_inventory': anchored(events)}
    if wallet is not None:
        # An absent integration argument is a failed contract, never an implicit
        # fallback that masks the linked-source reproduction under review.
        assert 'wallet_evidence' in inspect.signature(summarize_research).parameters, 'Fresh wallet evidence is not accepted by the research consumer'
        options['wallet_evidence'] = wallet
    before = deepcopy(events)
    result = summarize_research(events, start, end, **options)
    assert events == before, 'Research mutated original events'
    return result


def money_unknown(result, *, sale=0):
    assert result['observed_profit_sol'] is None
    assert result['known_matched_profit_sol'] is None
    assert result['conditional_observed_lot_profit_sol'] is None
    assert result['sales_detail'][sale]['conditional_matched_basis_sol'] is None
    assert result['sales_detail'][sale]['conditional_profit_sol'] is None
    assert not result['sales_detail'][sale]['attributable']
    episode = result['episodes'][sale]
    for key in ('basis_sol', 'matched_basis_sol', 'pnl_sol', 'roi_pct'):
        assert episode[key] is None, (key, episode[key])
    assert not episode['attributable']


def pure_pair(*, before=False, state='absent', capital=False, reentry=False):
    buy = entry('buy', '2025-12-31T00:00:00+00:00' if before else '2026-01-05T00:00:00+00:00', '1', 'dev-entry')
    sale = entry('sell', '2026-01-05T06:00:00+00:00', '1.2', 'dev-exit')
    if state != 'absent':
        buy['native_cash_role_state'] = state
    rows = [buy, display_fee(buy), sale, display_fee(sale)]
    if capital:
        rows.append({'kind': 'capital', 'timestamp': buy['timestamp'], 'order': 3,
            'amount_sol': '0.000000001', 'economic_role': 'unknown', 'direction': 'withdrawal',
            'signature': buy['signature'], 'path': 'unsigned-development/capital',
            'reason': 'Independent explicit unknown native cost role', 'evidence': ['c' * 64]})
    if reentry:
        second = [entry('buy', '2026-01-06T00:00:00+00:00', '2', 'dev-reentry', native_cash_role_state='PASS'),
                  entry('sell', '2026-01-06T06:00:00+00:00', '2.3', 'dev-reexit', native_cash_role_state='PASS')]
        rows += [second[0], display_fee(second[0]), second[1], display_fee(second[1])]
    return rows


def pure_positive():
    answer = research(pure_pair())
    assert answer['conditional_observed_lot_profit_sol'] == '0.19999'
    assert answer['observed_profit_sol'] == '0.19999'
    assert answer['wallet_fees_paid_sol'] == '0.00001'
    assert answer['episodes'][0]['pnl_sol'] == '0.19999'
    assert answer['episodes'][0]['hold_hours'] == '6'
    return answer


def pure_loss(**options):
    answer = research(pure_pair(**options))
    money_unknown(answer)
    assert answer['wallet_fees_paid_sol'] == ('0.000005' if options.get('before') else '0.00001')
    assert answer['episodes'][0]['quantity_raw'] == '0'
    assert answer['episodes'][0]['hold_hours'] == ('126' if options.get('before') else '6')
    assert answer['unresolved_transactions'] >= 1
    return answer


def pure_reentry():
    answer = research(pure_pair(state='UNKNOWN', reentry=True))
    first, second = answer['episodes']
    assert first['pnl_sol'] is None and first['basis_sol'] is None
    assert second['pnl_sol'] == '0.29999' and second['basis_sol'] == '2.000005'
    assert second['hold_hours'] == '6' and second['attributable']
    assert answer['sales_detail'][0]['conditional_profit_sol'] is None
    assert answer['sales_detail'][1]['conditional_profit_sol'] == '0.29999'
    assert answer['known_matched_profit_sol'] == '0.29999'
    return answer


def malformed_state(value):
    rows = pure_pair()
    rows[0]['native_cash_role_state'] = value
    try:
        answer = research(rows)
    except ValueError as error:
        return {'rejected': str(error), 'original_events_unchanged': True}
    money_unknown(answer)
    assert answer['wallet_fees_paid_sol'] == '0.00001'
    return answer


def malformed_capital_role(value):
    rows = pure_pair(capital=True)
    next(row for row in rows if row['kind'] == 'capital')['economic_role'] = value
    try:
        answer = research(rows)
    except ValueError as error:
        return {'rejected': str(error), 'original_events_unchanged': True}
    money_unknown(answer)
    assert answer['wallet_fees_paid_sol'] == '0.00001'
    return answer


def missing_financial_value(field):
    rows = pure_pair()
    rows = [row for row in rows if row['kind'] != 'fee']
    rows[0][field] = None
    answer = research(rows)
    assert answer['conditional_observed_lot_profit_sol'] is None
    assert answer['episodes'][0]['pnl_sol'] is None
    assert answer['episodes'][0]['monetary_state'] == 'UNKNOWN'
    assert answer['episodes'][0]['hold_hours'] == '6'
    return answer


def episode_identity(control):
    rows = pure_pair(state='UNKNOWN', reentry=True)
    if control == 'full-transfer-out':
        rows = [row for row in rows if row['signature'] != 'dev-exit']
        rows.append(entry('transfer_out', '2026-01-05T01:00:00+00:00', '0', 'dev-transfer', fee_sol='0'))
    elif control == 'partial-transfer-out':
        rows.append(entry('transfer_out', '2026-01-05T01:00:00+00:00', '0', 'dev-transfer', quantity_raw='50', fee_sol='0'))
        for row in rows:
            if row['kind'] == 'sell' and row['signature'] == 'dev-exit':
                row['quantity_raw'] = '50'
    elif control == 'held-transfer-in':
        rows.append(entry('transfer_in', '2026-01-05T01:00:00+00:00', '0', 'dev-transfer', quantity_raw='50', fee_sol='0'))
        for row in rows:
            if row['kind'] == 'sell' and row['signature'] == 'dev-exit':
                row['quantity_raw'] = '150'
    elif control == 'inferred-earlier-lot':
        for row in rows:
            if row['kind'] == 'sell' and row['signature'] == 'dev-exit':
                row['quantity_raw'] = '150'
    elif control == 'sale-only-opening-gap':
        rows = [row for row in rows if row['signature'] != 'dev-entry']
    elif control == 'ordered-same-time-reentry':
        for row in rows:
            if row['signature'] == 'dev-reentry':
                row['timestamp'] = '2026-01-05T06:00:00+00:00'
                row['order'] = 3 if row['kind'] == 'buy' else 4
    else:
        raise AssertionError(control)
    answer = research(rows)
    assert len(answer['episodes']) == 2, answer['episodes']
    first, second = answer['episodes']
    assert first['pnl_sol'] is None
    assert first['monetary_state'] == 'UNKNOWN'
    assert second['pnl_sol'] == '0.29999' and second['basis_sol'] == '2.000005'
    assert second['monetary_state'] == 'PASS'
    assert second['hold_hours'] == ('24' if control == 'ordered-same-time-reentry' else '6')
    assert second['timing_state'] == 'PASS'
    return answer


def raw_research(selected, linked):
    before = deepcopy([selected, linked])
    decoded = decode_supported_swaps(selected, WALLET)
    wallet = derive_wallet_evidence(selected, all_records=linked, wallet=WALLET, window=WINDOW,
        source_consistency={}, chronology={})
    answer = research(decoded['events'], start=WINDOW['start'], end=WINDOW['end'], wallet=wallet)
    assert [selected, linked] == before
    return {'research': answer, 'typed_lots': wallet['query_accounting']['supported_selected_lots'],
        'checks': {signature: value['checks'] for signature, value in wallet['transactions'].items()},
        'native_fee': wallet['components']['native_fee']}


def linked_source_replay(kind):
    rows = originals()
    clean = [wrapped(rows[83]), wrapped(rows[85])]
    if kind == 'cash':
        bad_raw = foreign_cash_loop(rows[83])
    elif kind == 'program':
        # The swap-level asset observation stays the same, but linked physical
        # ownership/quantity proof contradicts its actual Token2022 CPI program.
        bad_raw = deepcopy(rows[83])
        for field in ('preTokenBalances', 'postTokenBalances'):
            for balance in bad_raw['meta'][field]:
                if balance['mint'] == MINT:
                    balance['programId'] = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
    else:
        # A different retained-program owner cannot support the acquisition.
        bad_raw = deepcopy(rows[83])
        from test_retained_protocol_funding import _data, b58
        data = bytearray(_data(bad_raw['meta']['innerInstructions'][1]['instructions'][0]['data']))
        data[-32:] = _data(WALLET)
        bad_raw['meta']['innerInstructions'][1]['instructions'][0]['data'] = b58(data)
    bad = wrapped(bad_raw)
    clean_answer = raw_research(clean, clean)
    assert clean_answer['research']['conditional_observed_lot_profit_sol'] == '-0.013270924'
    assert clean_answer['typed_lots'][0]['monetary_state'] == 'PASS'
    alternative = raw_research(clean, [*clean, bad])
    money_unknown(alternative['research'])
    assert alternative['typed_lots'][0]['monetary_state'] == 'UNKNOWN'
    permuted = raw_research(list(reversed(clean)), [bad, *reversed(clean)])
    assert permuted['research'] == alternative['research']
    missing = raw_research(clean, [*clean, {**bad, 'raw': None}])
    money_unknown(missing['research'])
    restored = raw_research(clean, [*clean, bad])
    assert restored == alternative
    selected = raw_research([bad, clean[1]], [bad, clean[1]])
    assert selected['research']['conditional_observed_lot_profit_sol'] is None
    return {'clean': clean_answer, 'linked_alternative': alternative, 'missing_linked': missing,
        'restored_linked': restored, 'bad_selected': selected}


def boundary_fee_scope():
    rows = originals()
    clean = [wrapped(rows[83]), wrapped(rows[85])]
    scoped_window = {'start': utc(rows[83]['blockTime'] + 1).isoformat(), 'end': WINDOW['end']}
    events = decode_supported_swaps(clean, WALLET)['events']
    positive_wallet = derive_wallet_evidence(clean, all_records=clean, wallet=WALLET, window=scoped_window,
        source_consistency={}, chronology={})
    positive = research(events, start=scoped_window['start'], end=scoped_window['end'], wallet=positive_wallet)
    assert positive['conditional_observed_lot_profit_sol'] == '-0.013270924'
    assert positive['wallet_fees_paid_sol'] == '0.000006849'
    alternative = deepcopy(rows[83])
    alternative['blockTime'] += 2
    bad_wallet = derive_wallet_evidence(clean, all_records=[*clean, wrapped(alternative)], wallet=WALLET,
        window=scoped_window, source_consistency={}, chronology={})
    uncertain = research(events, start=scoped_window['start'], end=scoped_window['end'], wallet=bad_wallet)
    assert uncertain['wallet_fees_paid_sol'] is None
    assert uncertain['conditional_observed_lot_profit_sol'] is None
    assert uncertain['episodes'][0]['timing_state'] == 'UNKNOWN'
    assert uncertain['episodes'][0]['hold_hours'] is None
    return {'window': scoped_window, 'positive': positive, 'cross_boundary_alternative': uncertain,
        'fee_projection_checks': bad_wallet['fee_projection_checks']}


def native_origin_dependencies(control):
    rows = originals()
    if control == 'sale-only':
        selected = [wrapped(rows[85])]
    else:
        changed = [deepcopy(rows[83]), deepcopy(rows[85])]
        for raw in changed:
            for field in ('preTokenBalances', 'postTokenBalances'):
                for balance in raw['meta'][field]:
                    if balance.get('owner') == WALLET and balance['mint'] == MINT:
                        balance['uiTokenAmount']['amount'] = str(int(balance['uiTokenAmount']['amount']) + 1)
        selected = [wrapped(raw) for raw in changed]
    wallet = derive_wallet_evidence(selected, all_records=selected, wallet=WALLET, window=WINDOW,
        source_consistency={}, chronology={})
    events = decode_supported_swaps(selected, WALLET)['events']
    result = summarize_research(events, WINDOW['start'], WINDOW['end'], wallet_evidence=wallet)
    assert wallet['query_accounting']['supported_selected_lots'][0]['monetary_state'] == 'UNKNOWN'
    assert wallet['query_accounting']['supported_selected_lots'][0]['timing_state'] == 'UNKNOWN'
    assert result['episodes'][0]['monetary_state'] == 'UNKNOWN'
    assert result['episodes'][0]['timing_state'] == 'UNKNOWN'
    assert result['episodes'][0]['hold_hours'] is None
    assert result['episodes'][0]['pnl_sol'] is None
    assert result['conditional_observed_lot_profit_sol'] is None
    assert result['wallet_fees_paid_sol'] == ('0.000006849' if control == 'sale-only' else '0.000065767')
    return {'development_control': control, 'research': result,
        'typed_lots': wallet['query_accounting']['supported_selected_lots']}


def genuine_disjoint_pointer():
    from scanner.archive_input import import_archive, decode_archive
    from scanner.indexed_input import convert_indexed_archive
    from scanner.storage import Store
    from test_retained_protocol_funding import assess
    archive_path = ROOT / 'evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip'
    with tempfile.TemporaryDirectory(prefix='research-named-proof-review-') as directory:
        store = Store(Path(directory))
        identifier = import_archive(store, convert_indexed_archive(archive_path.read_bytes()))
        loaded, _, receipt = assess(store, identifier)
        events, _ = decode_archive(loaded)
        parent = summarize_research(events, WINDOW['start'], WINDOW['end'], wallet_evidence=receipt['wallet_evidence'])
        target = lambda result: next(row for row in result['episodes'] if row['mint'] == MINT)
        sale_target = lambda result: next(row for row in result['sales_detail'] if row['mint'] == MINT)
        typed_target = lambda record: next(row for row in record['wallet_evidence']['query_accounting']['supported_selected_lots'] if row['mint'] == MINT)
        assert target(parent)['pnl_sol'] == '-0.013270924'
        with localcontext() as context:
            context.prec = 192
            assert Decimal(target(parent)['hold_hours']) == Decimal(529) / Decimal(3600)
        cases = {}
        raw_rows = originals()
        for ordinal in (72, 83):
            signature = raw_rows[ordinal]['transaction']['signatures'][0]
            pointer = next(row['hash'] for row in loaded['manifest']['transactions'] if row['signature'] == signature)
            path = store.path / 'evidence' / (pointer + '.json.gz')
            original = path.read_bytes()
            path.unlink()
            child_loaded, _, child_receipt = assess(store, identifier, loaded['dependency_input_hash'])
            child_events, _ = decode_archive(child_loaded)
            child = summarize_research(child_events, WINDOW['start'], WINDOW['end'], wallet_evidence=child_receipt['wallet_evidence'])
            row = target(child)
            typed = typed_target(child_receipt)
            if ordinal == 72:
                assert typed['monetary_state'] == typed['timing_state'] == typed['quantity_state'] == 'PASS'
                assert row['monetary_state'] == row['timing_state'] == row['quantity_state'] == 'PASS'
                for field in ('basis_sol', 'matched_basis_sol', 'pnl_sol', 'roi_pct', 'hold_hours',
                              'first_sale_hours', 'sold_50_pct_hours', 'sold_90_pct_hours'):
                    assert row[field] == target(parent)[field], (field, row[field], target(parent)[field])
                assert sale_target(child)['conditional_profit_sol'] == '-0.013270924'
                assert sale_target(child)['conditional_matched_basis_sol'] == '0.565194018'
                # Preserving one proved observation cannot certify aggregate
                # populations or the whole wallet after unresolved activity.
                assert child['chronology_unknown']
                assert child['conditional_median_hold_hours'] is None
                assert child['observed_profit_sol'] is None
                assert not child['wallet_profit_verified']
            else:
                assert typed['monetary_state'] == typed['timing_state'] == 'UNKNOWN'
                assert row['monetary_state'] == 'UNKNOWN' and row['pnl_sol'] is None
                assert row['timing_state'] == 'UNKNOWN' and row['hold_hours'] is None
            path.write_bytes(original)
            restored_loaded, _, restored_receipt = assess(store, identifier, loaded['dependency_input_hash'])
            restored_events, _ = decode_archive(restored_loaded)
            restored = summarize_research(restored_events, WINDOW['start'], WINDOW['end'], wallet_evidence=restored_receipt['wallet_evidence'])
            assert restored == parent
            cases[str(ordinal)] = {'removed_signature': signature, 'removed_pointer': pointer,
                'research_target': row, 'typed_target': typed, 'aggregate_chronology_unknown': child['chronology_unknown'],
                'research_sale': sale_target(child),
                'aggregate_median_hold': child['conditional_median_hold_hours'], 'restored_exactly': restored == parent}
        return {'archive_sha256': hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            'clean_research_target': target(parent), 'cases': cases}


def content(selected, alternatives=()):
    all_rows = selected + list(alternatives)
    return pack_bytes({'manifest': {'version': VERSION, 'dataset': 'real', 'address': WALLET,
        'window': WINDOW, 'transactions': [{'signature': row['signature'], 'hash': row['evidence_hash']} for row in selected],
        'evidence': [{'kind': 'transaction', 'signature': row['signature'], 'hash': row['evidence_hash']} for row in alternatives]},
        'payloads': {row['evidence_hash']: row['raw'] for row in all_rows if row['raw'] is not None}})


def api_sources():
    calls = {'provider': 0, 'credential': 0, 'transport': 0}
    async def deny_provider(*args, **kwargs):
        calls['provider'] += 1
        raise AssertionError('Review attempted a provider request')
    async def deny_transport(*args, **kwargs):
        calls['transport'] += 1
        raise AssertionError('Review attempted external HTTP transport')
    def deny_credential(*args, **kwargs):
        calls['credential'] += 1
        raise AssertionError('Review attempted a credential lookup')
    with MonkeyPatch.context() as patch, tempfile.TemporaryDirectory(prefix='research-financial-review-') as directory:
        patch.delenv('HELIUS_API_KEY', raising=False)
        patch.setattr('scanner.providers.Gateway.rpc', deny_provider)
        patch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', deny_transport)
        patch.setitem(sys.modules, 'keyring', SimpleNamespace(get_keyring=lambda: object(), get_password=deny_credential))
        with local_session(Path(directory) / 'data') as (client, app):
            store = app.state.store
            usage = deepcopy(client.get('/api/state?report_view=summary').json()['usage'])
            rows = originals()
            clean = [wrapped(rows[83]), wrapped(rows[85])]
            bad = wrapped(foreign_cash_loop(rows[83]))
            def imported(body):
                response = client.post('/api/archives/import', content=body, headers={'Content-Type': 'application/zip'})
                assert response.status_code == 200, response.text
                report = client.get('/api/reports/' + response.json()['report_id']).json()
                assert report['metrics']['profit_sol']['value'] is None and not report['qualification']['qualified']
                return report
            def rebuild(parent):
                response = client.post('/api/reports/' + parent['id'] + '/rebuild')
                assert response.status_code == 200, response.text
                child = client.get('/api/reports/' + response.json()['report_id']).json()
                assert child['id'] != parent['id'] and child['rebuilt_from'] == parent['id']
                return child
            parent = imported(content(clean, [bad]))
            assert parent['research']['conditional_observed_lot_profit_sol'] is None
            parent_bytes = client.get('/api/export/reports/' + parent['id'] + '.json').content
            evidence_path = store.path / 'evidence' / (bad['evidence_hash'] + '.json.gz')
            evidence_bytes = evidence_path.read_bytes()
            evidence_path.unlink()
            lost = rebuild(parent)
            assert lost['research']['conditional_observed_lot_profit_sol'] is None
            lost_bytes = client.get('/api/export/reports/' + lost['id'] + '.json').content
            evidence_path.write_bytes(evidence_bytes)
            restored = rebuild(lost)
            assert restored['research'] == parent['research']
            assert client.get('/api/export/reports/' + parent['id'] + '.json').content == parent_bytes
            assert client.get('/api/export/reports/' + lost['id'] + '.json').content == lost_bytes
            positive = imported(content(clean))
            assert positive['research']['conditional_observed_lot_profit_sol'] == '-0.013270924'
            contradictory = deepcopy(rows[83])
            for field in ('preTokenBalances', 'postTokenBalances'):
                for balance in contradictory['meta'][field]:
                    if balance['mint'] == MINT:
                        balance['programId'] = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
            program_parent = imported(content(clean, [wrapped(contradictory)]))
            assert program_parent['research']['conditional_observed_lot_profit_sol'] is None
            assert program_parent['research']['episodes'][0]['monetary_state'] == 'UNKNOWN'
            assert program_parent['metrics']['observed_network_fees_sol']['value'] == '0.000065767'
            positive_bytes = client.get('/api/export/reports/' + positive['id'] + '.json').content
            required_path = store.path / 'evidence' / (clean[0]['evidence_hash'] + '.json.gz')
            required_bytes = required_path.read_bytes()
            required_path.unlink()
            required_lost = rebuild(positive)
            assert required_lost['research']['conditional_observed_lot_profit_sol'] is None
            required_path.write_bytes(required_bytes)
            required_restored = rebuild(required_lost)
            assert required_restored['research'] == positive['research']
            assert client.get('/api/export/reports/' + positive['id'] + '.json').content == positive_bytes
            # An ordinary collector path must pass its freshly frozen wallet
            # receipt to the same research code, rather than only archive callers.
            original = json.loads((ROOT / 'tests/fixtures/mainnet-pumpswap-buy-exact-quote.json').read_text())
            wallet = '4drEkXDZhjun3vjZmz1g7pQGM7kxANQbDuD9jtPZwzJZ'
            now = datetime.now(timezone.utc)
            original['raw']['blockTime'] = int((now - timedelta(days=1)).timestamp())
            original['evidence_hash'] = store.archive(original['raw'])
            for balance in original['raw']['meta']['postTokenBalances']:
                if balance.get('owner') == wallet:
                    cache_mint(store, balance['mint'], None, now.isoformat())
            async def offline_collector(*args, **kwargs):
                return {'transactions': [deepcopy(original)], 'coverage': {'status': 'partial', 'history_scope_complete': False},
                        'evidence': [{'hash': original['evidence_hash'], 'kind': 'transaction'}]}
            patch.setattr('scanner.collector.collect_wallet', offline_collector)
            assert client.post('/api/provider/key', json={'api_key': TEST_KEY}).status_code == 200
            cohort = save_cohort(store, [candidate(wallet)])
            response = client.post('/api/discovery/' + cohort + '/audit', json={})
            assert response.status_code == 200, response.text
            assert wait_record(client, 'scans', response.json()['scan_id'])['status'] == 'completed'
            ordinary = next(report for report in client.get('/api/state').json()['reports'] if report['address'] == wallet)
            assert ordinary['research']['unresolved_transactions'] == 2
            assert ordinary['research']['conditional_observed_lot_profit_sol'] is None
            assert next(event for event in ordinary['events'] if event['kind'] == 'buy')['quantity_raw']
            assert len([event for event in ordinary['events'] if event['kind'] == 'fee']) == 1
            assert ordinary['metrics']['profit_sol']['value'] is None
            assert calls == {'provider': 0, 'credential': 0, 'transport': 0}, calls
            assert client.get('/api/state?report_view=summary').json()['usage'] == usage
            return {'calls': calls, 'parent_immutable_sha256': hashlib.sha256(parent_bytes).hexdigest(),
                'loss_child_immutable_sha256': hashlib.sha256(lost_bytes).hexdigest(),
                'partial_positive': positive['research'], 'linked_parent': parent['research'],
                'missing_child': lost['research'], 'restored_child': restored['research'],
                'linked_program_parent': program_parent['research'], 'required_source_lost': required_lost['research'],
                'required_source_restored': required_restored['research'],
                'ordinary_collector': ordinary['research']}


record('clean-positive-allocated-fees', pure_positive)
record('cash-only-money-loss', lambda: pure_loss(state='UNKNOWN'))
record('separate-unknown-capital-role', lambda: pure_loss(capital=True))
record('prewindow-required-acquisition', lambda: pure_loss(state='UNKNOWN', before=True))
record('same-mint-clean-later-reentry', pure_reentry)
for index, value in enumerate((None, True, [], {}, 'PASSING')):
    record('malformed-money-state-' + str(index), lambda value=value: malformed_state(value))
for index, value in enumerate((None, True, [], {}, 'future')):
    record('malformed-capital-role-' + str(index), lambda value=value: malformed_capital_role(value))
for field in ('amount_sol', 'fee_sol'):
    record('missing-required-financial-' + field, lambda field=field: missing_financial_value(field))
for control in ('full-transfer-out', 'partial-transfer-out', 'held-transfer-in', 'inferred-earlier-lot',
                'sale-only-opening-gap', 'ordered-same-time-reentry'):
    record('episode-identity-' + control, lambda control=control: episode_identity(control))
record('raw-selected-linked-cash-loss-restoration', lambda: linked_source_replay('cash'))
record('raw-selected-linked-identity-loss-restoration', lambda: linked_source_replay('identity'))
record('raw-selected-linked-program-physical-conflict', lambda: linked_source_replay('program'))
record('out-of-window-selected-fee-linked-boundary', boundary_fee_scope)
record('genuine-sale-only-required-origin-timing', lambda: native_origin_dependencies('sale-only'))
record('positively-observed-earlier-stock-cost-origin', lambda: native_origin_dependencies('earlier-stock'))
record('genuine-proved-disjoint-and-required-pointer', genuine_disjoint_pointer)
record('ordinary-and-archive-offline-consumers', api_sources)

receipt = {'scope': 'Distinct offline scoped consumer review. Development mutations and anchors cannot close genuine B3 or wallet qualification.',
    'review_control_counts': {'ordinary_replay_cases': len(results), 'failed': len(failures), 'not_unique_candidate_tests': True},
    'worked_expectations': {'development_clean_pair_profit_sol': '0.19999', 'development_clean_reentry_profit_sol': '0.29999',
        'genuine_scoped_pair_basis_lamports': 565194018, 'genuine_scoped_pair_net_exit_lamports': 551923094,
        'genuine_scoped_pair_loss_lamports': -13270924, 'genuine_scoped_pair_hold_seconds': 529},
    'source_sha256': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in
        ('scanner/research.py', 'scanner/accounting.py', 'scanner/app.py', 'scanner/wallet_evidence.py', 'scanner/investigation.py', 'scanner/archive_input.py')},
    'results': results, 'failed_cases': failures, 'PRODUCT_READY': False}
print(json.dumps(receipt, indent=2))
sys.exit(bool(failures))
