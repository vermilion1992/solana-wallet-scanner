"""Independent offline review controls; no genuine monitoring/fill provenance."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path('/workspace/solana-wallet-scanner')
sys.path.insert(0, str(ROOT))
from scanner.storage import Store, QuotaExceeded
from scanner.paper import (create_run, record_signal, begin_quote, apply_quote,
                           get_run, export_run, request_marks, stop_run, resume_run)
from scanner.observer import ObserverService
from scanner.screening_routes import (saved_identity, collect_public_sample,
                                     observation_view, PublicSampleRPC, screening_view)
from tests.test_discovery_plan_views import identity_cohort
from tests.test_discovery import WALLET, MINT

TOKEN = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
BASE = datetime.now(timezone.utc) - timedelta(seconds=100)
stamp = lambda sec: (BASE + timedelta(seconds=sec)).isoformat()
results = []

def note(name, **facts):
    results.append({'control': name, 'status': 'PASS', **facts})

def emit(store, run, side, second, signature=None, **extra):
    evidence = store.archive({'kind': 'independent-offline-signal',
                              'signature': signature or side, 'time': stamp(second)})
    signal = {'signature': signature or side, 'mint': TOKEN, 'side': side,
              'detected_at': stamp(second), 'decoded_at': stamp(second),
              'decimals': 6, 'eligible': True, 'evidence_hash': evidence, **extra}
    return record_signal(store, run['id'], signal, at=stamp(second))

def quote(store, run, second, output):
    request = next(row for row in run['quote_requests'] if row['status'] == 'pending')
    request = begin_quote(store, run['id'], request['id'], at=stamp(second))
    payload = {'status': 'available', 'input_mint': request['input_mint'],
               'output_mint': request['output_mint'], 'in_amount': request['input_amount'],
               'out_amount': output, 'price_impact_pct': '0',
               'received_at': stamp(second + 1)}
    payload['evidence_hash'] = store.archive({'kind': 'independent-offline-quote',
                                            'request': request, 'response': payload})
    return apply_quote(store, run['id'], request['id'], payload, at=stamp(second + 1))

def paper_controls(store):
    run = create_run(store, WALLET, {'capital_sol': '2', 'entry_sol': '1',
        'reaction_delay_seconds': 0, 'adverse_bps': 0, 'execution_fee_sol': '0'}, at=stamp(0))
    run = quote(store, emit(store, run, 'buy', 1), 1, '100')
    run = quote(store, emit(store, run, 'sell', 3), 3, '1200000000')
    assert run['summary']['economic_pnl_sol'] == '0.2'
    assert run['summary']['complete_observation'] is True
    digest = run['quote_requests'][-1]['quote_evidence_hash']
    path = store.path / 'evidence' / (digest + '.json.gz')
    original = path.read_bytes()
    path.unlink()
    missing = get_run(store, run['id'])
    assert missing['summary']['economic_pnl_sol'] == '0.2'
    assert missing['summary']['supported_economic_pnl_sol'] is None
    assert missing['summary']['complete_observation'] is False
    path.write_bytes(original)
    assert get_run(store, run['id'])['summary']['complete_observation'] is True
    note('quote_source_loss_and_exact_restoration', retained_pnl='0.2',
         missing_supported_pnl=None, missing_complete=False, restored_complete=True)
    exported = export_run(store, run['id'])
    exported['run'] = observation_view(store, exported['run'])
    assert exported['run']['id'] == run['id'] and 'notifications' in exported['run']
    note('observation_export_wrapper_shape')
    empty = create_run(store, WALLET, at=stamp(0))
    empty = emit(store, empty, 'buy', 1, signature='excluded',
                 eligible=False, reason='unsupported_settlement')
    assert empty['copyability']['status'] == 'insufficient_evidence'
    assert empty['summary']['complete_observation'] is False
    assert empty['summary']['supported_economic_pnl_sol'] is None
    note('ineligible_only_has_no_supported_performance')
    late = create_run(store, WALLET, {'reaction_delay_seconds': 0,
        'max_duration_minutes': 1}, at=stamp(0))
    late = emit(store, late, 'buy', 59, signature='late')
    late = quote(store, late, 59, '100')  # receipt at deadline exactly: t60
    assert late['quote_requests'][0]['status'] == 'cancelled'
    assert late['positions'] == [] and late['summary']['cash_sol'] == '10'
    note('deadline_receipt_cannot_spend_cash', request_status='cancelled')
    costed = create_run(store, WALLET, {'capital_sol': '2', 'entry_sol': '1',
        'reaction_delay_seconds': 0, 'adverse_bps': 100,
        'execution_fee_sol': '0.01'}, at=stamp(0))
    costed = quote(store, emit(store, costed, 'buy', 1, signature='cost-buy'), 1, '10000')
    assert costed['positions'][0]['raw_units'] == '9900'
    costed = quote(store, emit(store, costed, 'sell', 3, signature='cost-sell'), 3, '900000000')
    assert costed['summary']['realised_pnl_sol'] == '-0.129'
    assert costed['summary']['cash_sol'] == '1.871'
    note('independently_worked_costs_once', expected_pnl='-0.129', expected_cash='1.871')
    settings_digest = run['settings_snapshot_hash']
    settings_path = store.path / 'evidence' / (settings_digest + '.json.gz')
    settings_original = settings_path.read_bytes()
    settings_path.unlink()
    exported_missing = export_run(store, run['id'])
    assert exported_missing['settings_evidence'] is None
    assert exported_missing['settings_evidence_availability']['state'] == 'UNKNOWN'
    assert exported_missing['run']['summary']['supported_economic_pnl_sol'] is None
    assert exported_missing['run']['summary']['economic_pnl_sol'] == '0.2'
    settings_path.write_bytes(settings_original)
    assert export_run(store, run['id'])['settings_evidence_availability']['state'] == 'KNOWN'
    note('missing_settings_export_is_reviewable_and_cannot_support_current_pnl')
    unfunded = create_run(store, WALLET, {'capital_sol': '1.1', 'entry_sol': '1',
        'reaction_delay_seconds': 0, 'adverse_bps': 0, 'execution_fee_sol': '0.1'}, at=stamp(0))
    unfunded = quote(store, emit(store, unfunded, 'buy', 1, signature='unfunded-entry'), 1, '100')
    assert unfunded['summary']['cash_sol'] == '0'
    unfunded = request_marks(store, unfunded['id'], at=stamp(3))
    unfunded = quote(store, unfunded, 3, '10000000')
    assert unfunded['quote_requests'][-1]['status'] == 'unavailable'
    assert unfunded['positions'][0]['mark'] is None
    assert unfunded['summary']['economic_pnl_sol'] is None
    unfunded = quote(store, emit(store, unfunded, 'sell', 5, signature='unfunded-exit'), 5, '10000000')
    assert unfunded['quote_requests'][-1]['status'] == 'unavailable'
    assert unfunded['positions'][0]['status'] == 'open'
    assert unfunded['positions'][0]['exit_unavailable'] is True
    assert unfunded['summary']['cash_sol'] == '0'
    note('unfunded_exit_and_mark_preserve_open_exposure_without_negative_cash')
    limited = create_run(store, WALLET, {'reaction_delay_seconds': 0, 'max_quotes': 1}, at=stamp(0))
    limited = quote(store, emit(store, limited, 'buy', 1, signature='limited'), 1, '100')
    stop_run(store, limited['id'], at=stamp(3))
    try:
        resume_run(store, limited['id'], at=stamp(4))
    except ValueError:
        pass
    else:
        raise AssertionError('Immutable quote allowance must survive stop/resume')
    assert get_run(store, limited['id'])['status'] == 'budget_exhausted'
    note('exhausted_quote_allowance_cannot_be_reset_by_stop_resume')


def identity_controls(store):
    cohort, hashes = identity_cohort(store)
    assert saved_identity(store, WALLET)['state'] == 'PASS'
    conflict = deepcopy(cohort)
    conflict['id'] = 'b' * 32
    raw = store.evidence(hashes['account'])
    raw['result']['value']['owner'] = MINT
    bad = store.archive(raw)
    conflict['candidates'][0]['validation']['account_evidence_hash'] = bad
    conflict['candidates'][0]['evidence'] = [bad if h == hashes['account'] else h
                                            for h in conflict['candidates'][0]['evidence']]
    conflict['evidence'] = [dict(row, hash=bad) if row['hash'] == hashes['account'] else row
                            for row in conflict['evidence']]
    store.put('discovery_cohorts', conflict['id'], conflict)
    assert saved_identity(store, WALLET)['state'] == 'UNKNOWN'
    note('cross_cohort_same_slot_conflict_is_dependency')
    # Model a later identity check in the SAME cohort: old archive is still linked,
    # but the current validation pointer now selects the newer system snapshot.
    fresh = store.evidence(hashes['account'])
    fresh['result']['context']['slot'] = 12
    newest = store.archive(fresh)
    conflict['candidates'][0]['validation']['account_evidence_hash'] = newest
    conflict['candidates'][0]['evidence'].append(newest)
    conflict['evidence'].append({'kind': 'wallet-account-info', 'hash': newest})
    store.put('discovery_cohorts', conflict['id'], conflict)
    result = saved_identity(store, WALLET)
    assert result['state'] == 'PASS', result
    assert bad in result['evidence']
    oldpath = store.path / 'evidence' / (bad + '.json.gz')
    oldpath.unlink()
    assert saved_identity(store, WALLET)['state'] == 'UNKNOWN'
    note('same_cohort_newer_current_snapshot_preserves_old_dependency')

def malformed_identity_controls(store):
    for index, owner in enumerate((None, {}, [], 123)):
        isolated = Store(store.path / ('owner-' + str(index)))
        try:
            cohort, hashes = identity_cohort(isolated)
            payload = isolated.evidence(hashes['account'])
            payload['result']['value']['owner'] = owner
            digest = isolated.archive(payload)
            cohort['candidates'][0]['validation']['account_evidence_hash'] = digest
            cohort['candidates'][0]['evidence'] = [digest if h == hashes['account'] else h
                                                 for h in cohort['candidates'][0]['evidence']]
            cohort['evidence'] = [dict(row, hash=digest) if row['hash'] == hashes['account'] else row
                                 for row in cohort['evidence']]
            isolated.put('discovery_cohorts', cohort['id'], cohort)
            assert saved_identity(isolated, WALLET)['state'] == 'UNKNOWN'
        finally:
            isolated.close()
    note('malformed_native_account_owner_is_unknown', owner_cases=['null', 'object', 'array', 'number'])

class NullQuotes:
    async def close(self): pass

def gap_controls(store):
    base, clock, sockets = datetime.now(timezone.utc), [0], [0]
    clockstamp = lambda: (base + timedelta(seconds=clock[0])).isoformat()
    run = create_run(store, WALLET, at=clockstamp())
    class Socket:
        async def __aenter__(self): clock[0] += 3; return self
        async def __aexit__(self, *args): pass
        async def send(self, payload): pass
        async def recv(self):
            clock[0] += 2
            return json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': 7})
        async def messages(self):
            if sockets[0] >= 2:
                for signature in ('first', 'over-limit'):
                    yield json.dumps({'jsonrpc': '2.0', 'method': 'logsNotification', 'params': {
                        'subscription': 7, 'result': {'context': {'slot': 1},
                        'value': {'signature': signature, 'err': None}}}})
        def __aiter__(self): return self.messages()
    def connect(*args, **kwargs): sockets[0] += 1; return Socket()
    async def sleep(seconds): clock[0] += seconds
    observer = ObserverService(store, quote_client=NullQuotes(), websocket_connect=connect)
    observer._update(run['id'], status='connecting', address=WALLET, notifications=0,
        transactions=0, started_at=run['started_at'], monitoring_gap_started_at=run['started_at'],
        limits={'max_notifications': 1, 'max_transactions': 1, 'max_minutes': 60})
    with patch('scanner.observer._stamp', clockstamp), patch('scanner.observer.asyncio.sleep', sleep):
        asyncio.run(observer._listen(run['id']))
    gaps = get_run(store, run['id'])['gaps']
    spans = [(datetime.fromisoformat(g['end_at']) - datetime.fromisoformat(g['start_at'])).total_seconds()
             for g in gaps]
    assert spans[:2] == [5, 7], spans
    assert observer.snapshot(run['id'])['status'] == 'budget_exhausted'
    note('initial_and_reconnect_intervals_include_waits', spans_seconds=spans[:2])

class FakeNative:
    calls = []
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def __init__(self, *args, **kwargs): pass
    async def close(self): pass
    async def rpc(self, method, params=None):
        self.calls.append((method, deepcopy(params)))
        return []

def continuation_controls(store):
    scan = {'id': 'review-scan', 'audit_addresses': ['selected', 'untouched'],
            'public_sample_targets': ['selected'],
            'limits': {'transaction_limit': 2, 'wallet_credit_limit': 2}, 'progress': {}}
    first = {**PublicSampleRPC._empty(), 'requests_used': 1, 'credits': 1,
             'tranche_request_limit': 2, 'before': 'first-cursor',
             'transactions': [{'signature': 'old', 'raw': None}]}
    second = {**PublicSampleRPC._empty(), 'requests_used': 1, 'credits': 1,
              'tranche_request_limit': 2, 'before': 'second-cursor', 'pending': ['untouched']}
    store.put('public_sample_checkpoints', 'review-scan:selected', first)
    store.put('public_sample_checkpoints', 'review-scan:untouched', second)
    rebuilt = []
    async def build(scan, address, collected): rebuilt.append(address)
    with patch('scanner.observer.PublicRPC', FakeNative):
        asyncio.run(collect_public_sample(store, scan, build, lambda: False))
    assert FakeNative.calls == [('getSignaturesForAddress', ['selected', {
        'limit': 1, 'commitment': 'finalized', 'before': 'first-cursor'}])]
    assert rebuilt == ['selected']
    assert store.get('public_sample_checkpoints', 'review-scan:untouched') == second
    assert scan['audit_addresses'] == ['selected', 'untouched']
    note('selected_continuation_preserves_other_wallet_checkpoint')

def ack_rejection_controls(store):
    run = create_run(store, WALLET)
    class Socket:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def send(self, payload): pass
        async def recv(self):
            return json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': 7,
                               'error': {'code': -32603, 'message': 'rejected'}})
        async def messages(self):
            yield json.dumps({'jsonrpc': '2.0', 'method': 'logsNotification', 'params': {
                'subscription': 7, 'result': {'context': {'slot': 1},
                'value': {'signature': 'must-not-accept', 'err': None}}}})
        def __aiter__(self): return self.messages()
    async def no_wait(seconds): pass
    observer = ObserverService(store, quote_client=NullQuotes(),
                               websocket_connect=lambda *args, **kwargs: Socket())
    observer._update(run['id'], status='connecting', address=WALLET, notifications=0,
        transactions=0, started_at=run['started_at'], monitoring_gap_started_at=run['started_at'],
        limits={'max_notifications': 1, 'max_transactions': 1, 'max_minutes': 60})
    with patch('scanner.observer.asyncio.sleep', no_wait):
        asyncio.run(observer._listen(run['id']))
    state = observer.snapshot(run['id'])
    assert not state.get('connected_at') and not state.get('subscription')
    assert state['notifications'] == 0 and state['status'] == 'paused'
    assert state['last_error']['code'] == 'subscription_rejected'
    note('mixed_result_error_ack_retains_gap_and_accepts_no_activity')

def screening_source_controls(store):
    identity_cohort(store)
    digest = store.archive({'scope': 'Independent synthetic screening dependency'})
    frozen = {'id': 'review-screen', 'address': WALLET, 'result': 'worth_observing',
              'label': 'Worth observing', 'reason': 'Synthetic sampled result',
              'evidence': [digest]}
    original = deepcopy(frozen)
    parent = screening_view(store, frozen)
    assert parent['current_result'] == 'worth_observing'
    assert parent['current_eligibility']['can_start_observation'] is True
    path = store.path / 'evidence' / (digest + '.json.gz')
    data = path.read_bytes(); path.unlink()
    missing = screening_view(store, frozen)
    assert missing['result'] == 'worth_observing'
    assert missing['current_result'] == 'insufficient_evidence'
    assert missing['current_source_availability']['state'] == 'UNKNOWN'
    assert missing['current_eligibility']['can_start_observation'] is False
    path.write_bytes(data)
    assert screening_view(store, frozen)['current_result'] == 'worth_observing'
    assert frozen == original
    note('saved_screening_source_loss_blocks_current_observation_and_restores_without_rewriting_snapshot')


def main():
    for control in (paper_controls, gap_controls, continuation_controls, identity_controls,
                    malformed_identity_controls, ack_rejection_controls, screening_source_controls):
        with TemporaryDirectory(prefix='review-final-') as path:
            store = Store(path)
            try:
                control(store)
            finally:
                store.close()
    files = ['scanner/paper.py', 'scanner/observer.py', 'scanner/screening.py',
             'scanner/screening_routes.py', 'scanner/app.py', 'scanner/discovery.py',
             'scanner/candidate_import.py', 'frontend/src/Research.tsx', 'frontend/src/Discovery.tsx',
             'scanner/asset_classification.py', 'scanner/wallet_evidence.py',
             'tools/validate.py', '.github/workflows/offline-focused.yml', 'README.md']
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}
    print(json.dumps({'scope': 'Independent read-only source review and offline synthetic deterministic controls',
                      'provider_calls': 0, 'credential_lookups': 0,
                      'independent_browser_run': False, 'full_suite_run': False,
                      'results': results, 'source_sha256': hashes}, indent=2))

if __name__ == '__main__': main()
