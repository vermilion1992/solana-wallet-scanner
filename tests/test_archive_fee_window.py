"""Fee-window projections have clock dependencies, unlike unordered native fees."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
import pytest

import scanner.app as application
from scanner.archive_input import (analyze_archive, canonical_bytes, decode_archive,
                                  import_archive, load_archive, pack_bytes)
from scanner.storage import Store

FIXTURE = Path(__file__).resolve().parents[1] / 'scanner/examples/archive-wallet-synthetic.json'
START = 1780272000
END = 1782864000


def bundle():
    return json.loads(FIXTURE.read_text())


def source(value, role, timestamp, *, disjoint=False):
    selected = value['manifest']['transactions'][1]
    raw = deepcopy(value['payloads'][selected['hash']])
    if role in ('transaction', 'getTransaction'):
        raw['blockTime'] = timestamp
        payload = raw
        link = {'kind': role, 'signature': selected['signature']}
    elif role == 'signature-page':
        payload = {'method': 'getSignaturesForAddress', 'address': value['manifest']['address'],
                   'params': {'commitment': 'finalized', 'minContextSlot': raw['slot'] + 100, 'limit': 1000},
                   'result': [{'signature': 'disjoint-clock' if disjoint else selected['signature'],
                               'slot': raw['slot'] + 10000 if disjoint else raw['slot'],
                               'blockTime': timestamp, 'err': raw['meta']['err'], 'confirmationStatus': 'finalized'}]}
        link = {'kind': role}
    else:
        payload = {'method': 'getBlock', 'slot': raw['slot'] + 10000 if disjoint else raw['slot'],
                   'result': {'signatures': ['disjoint-clock' if disjoint else selected['signature']], 'blockTime': timestamp}}
        link = {'kind': role}
    digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    value['payloads'][digest] = payload
    value['manifest']['evidence'].append({**link, 'hash': digest})
    return digest


def derive(store, value):
    digest = import_archive(store, pack_bytes(value))
    loaded = load_archive(store, digest)
    events, _ = decode_archive(loaded)
    result, _, coverage = analyze_archive(loaded, events)
    return result, coverage, digest


def malformed_page(value, signature):
    digest = source(value, 'signature-page', START)
    payload = deepcopy(value['payloads'][digest])
    payload['result'].append(dict(payload['result'][0], signature=signature))
    replacement = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    value['payloads'][replacement] = payload
    value['manifest']['evidence'][0]['hash'] = replacement
    return replacement


@pytest.mark.parametrize('signature', [{'malformed': True}, ['malformed'], True, None])
def test_malformed_page_signature_remains_dependency_without_crashing(tmp_path, signature):
    value = bundle()
    digest = malformed_page(value, signature)
    result, coverage, _ = derive(Store(tmp_path), value)
    assert result['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    assert digest in result['metrics']['observed_network_fees_sol']['evidence']
    assert coverage['provider_requests'] == coverage['credential_lookups'] == 0


def test_malformed_clock_page_normal_api_import_and_rebuild_remain_supported(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Offline import/rebuild may not dispatch a provider')
    monkeypatch.setattr(application, 'Credentials', lambda _: SimpleNamespace(key=None, storage='none', backend=None))
    monkeypatch.setattr(httpx.AsyncClient, 'request', denied)
    value = bundle()
    value['manifest']['dataset'] = 'real'
    malformed_page(value, {'malformed': True})
    app = application.create_app(tmp_path, 'isolated-malformed-clock-test')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        csrf = client.get('/api/bootstrap', headers={'X-Launch-Token': 'isolated-malformed-clock-test'}).json()['csrf']
        client.headers['X-CSRF-Token'] = csrf
        usage = client.get('/api/state').json()['usage']
        response = client.post('/api/archives/import', content=pack_bytes(value))
        assert response.status_code == 200, response.text
        parent_id = response.json()['report_id']
        saved = deepcopy(app.state.store.get('reports', parent_id))
        child_id = client.post('/api/reports/' + parent_id + '/rebuild').json()['report_id']
        assert client.get('/api/reports/' + child_id).json()['metrics']['observed_network_fees_sol']['status'] == 'unknown'
        assert app.state.store.get('reports', parent_id) == saved
        assert client.get('/api/state').json()['usage'] == usage


@pytest.mark.parametrize('role,timestamp', [(role, timestamp)
    for role in ('transaction', 'getTransaction', 'signature-page', 'block-order')
    for timestamp in (START - 1, END, None, True)
    if not (role == 'block-order' and timestamp is None)])
def test_cross_boundary_or_missing_linked_clocks_revoke_window_fee_certainty(tmp_path, role, timestamp):
    value = bundle()
    source(value, role, timestamp)
    result, _, _ = derive(Store(tmp_path), value)
    assert result['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    assert result['metrics']['observed_network_fees_sol']['value'] is None


@pytest.mark.parametrize('role', ['transaction', 'getTransaction', 'signature-page', 'block-order'])
@pytest.mark.parametrize('timestamp', [START, END - 1])
def test_bounded_clocks_inside_same_window_preserve_independent_fees(tmp_path, role, timestamp):
    value = bundle()
    source(value, role, timestamp)
    result, _, _ = derive(Store(tmp_path), value)
    assert result['metrics']['observed_network_fees_sol']['value'] == '0.000055'
    assert result['metrics']['observed_network_fees_sol']['status'] == 'known'


@pytest.mark.parametrize('role', ['signature-page', 'block-order'])
def test_available_disjoint_clock_records_do_not_erase_selected_fee_observations(tmp_path, role):
    value = bundle()
    source(value, role, END, disjoint=True)
    result, _, _ = derive(Store(tmp_path), value)
    assert result['metrics']['observed_network_fees_sol']['value'] == '0.000055'


def test_optional_null_block_time_does_not_replace_supported_raw_time(tmp_path):
    value = bundle()
    source(value, 'block-order', None)
    result, _, _ = derive(Store(tmp_path), value)
    assert result['metrics']['observed_network_fees_sol']['value'] == '0.000055'


@pytest.mark.parametrize('loss', ['missing', 'corrupt', 'unsupported'])
def test_required_clock_loss_never_strengthens_fees_and_restoration_recovers(tmp_path, loss):
    value = bundle()
    digest = source(value, 'signature-page', END)
    store = Store(tmp_path)
    result, _, manifest = derive(store, value)
    assert result['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    original_metrics = deepcopy(result['metrics'])
    path = store.path / 'evidence' / f'{digest}.json.gz'
    original = path.read_bytes()
    if loss == 'missing':
        path.unlink()
    elif loss == 'corrupt':
        path.write_bytes(b'corrupt')
    else:
        altered = deepcopy(value)
        bad = deepcopy(altered['payloads'][digest])
        bad['method'] = 'unsupported-clock-method'
        new = hashlib.sha256(canonical_bytes(bad)).hexdigest()
        altered['payloads'][new] = bad
        altered['manifest']['evidence'][0]['hash'] = new
        result, _, _ = derive(store, altered)
        assert result['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    loaded = load_archive(store, manifest)
    events, _ = decode_archive(loaded)
    changed, _, _ = analyze_archive(loaded, events)
    assert changed['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    path.write_bytes(original)
    loaded = load_archive(store, manifest)
    events, _ = decode_archive(loaded)
    restored, _, _ = analyze_archive(loaded, events)
    assert restored['metrics'] == original_metrics


def test_fee_membership_is_independent_of_same_slot_ordering(tmp_path):
    value = bundle()
    second = value['manifest']['transactions'][2]
    first_raw = value['payloads'][value['manifest']['transactions'][1]['hash']]
    changed = deepcopy(value['payloads'][second['hash']])
    changed['slot'] = first_raw['slot']
    changed['blockTime'] = first_raw['blockTime']
    digest = hashlib.sha256(canonical_bytes(changed)).hexdigest()
    value['payloads'][digest] = changed
    second['hash'] = digest
    result, coverage, _ = derive(Store(tmp_path), value)
    assert coverage['chronology']['state'] == 'UNKNOWN'
    assert result['metrics']['observed_network_fees_sol']['value'] == '0.000055'


def test_zero_wallet_paid_fee_is_independent_of_ambiguous_interval_placement(tmp_path):
    value = bundle()
    selected = value['manifest']['transactions'][1]
    raw = deepcopy(value['payloads'][selected['hash']])
    raw['transaction']['message']['accountKeys'][0] = '11111111111111111111111111111111'
    raw['transaction']['message']['accountKeys'].append(value['manifest']['address'])
    raw['meta']['preBalances'].append(10000000000)
    raw['meta']['postBalances'].append(10000000000)
    digest = hashlib.sha256(canonical_bytes(raw)).hexdigest()
    selected['hash'] = digest
    value['payloads'][digest] = raw
    value['manifest']['dataset'] = 'real'
    source(value, 'signature-page', END)
    value['manifest']['transactions'] = [selected]
    result, coverage, _ = derive(Store(tmp_path), value)
    assert result['metrics']['observed_network_fees_sol']['value'] == '0'
    assert coverage['fee_interval_membership'][selected['signature']]['state'] == 'UNKNOWN'
    assert coverage['proved_zero_fee_exclusions'] == [selected['signature']]


def test_permutations_and_redundant_clock_links_do_not_change_metric_semantics(tmp_path):
    value = bundle()
    source(value, 'signature-page', END)
    source(value, 'block-order', END - 1)
    store = Store(tmp_path)
    first, _, _ = derive(store, value)
    value['manifest']['transactions'].reverse()
    value['manifest']['evidence'] = list(reversed(value['manifest']['evidence'] * 2))
    second, _, _ = derive(store, value)
    assert first['metrics'] == second['metrics']


@pytest.mark.parametrize('dataset', ['real', 'synthetic'])
def test_normal_api_rebuild_export_preserves_parent_and_restores_clock_dependency(tmp_path, monkeypatch, dataset):
    def denied(*args, **kwargs):
        raise AssertionError('Offline operations may not request credentials or dispatch a provider')
    monkeypatch.setattr(application, 'Credentials', lambda _: SimpleNamespace(key=None, storage='none', backend=None))
    monkeypatch.setattr(httpx.AsyncClient, 'request', denied)
    value = bundle()
    value['manifest']['dataset'] = dataset
    raw = value['payloads'][value['manifest']['transactions'][1]['hash']]
    clock = source(value, 'signature-page', raw['blockTime'])
    app = application.create_app(tmp_path, 'isolated-archive-clock-test')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        csrf = client.get('/api/bootstrap', headers={'X-Launch-Token': 'isolated-archive-clock-test'}).json()['csrf']
        client.headers['X-CSRF-Token'] = csrf
        usage = client.get('/api/state').json()['usage']
        response = client.post('/api/archives/import', content=pack_bytes(value))
        assert response.status_code == 200, response.text
        pid = response.json()['report_id']
        parent = client.get('/api/reports/' + pid).json()
        saved = deepcopy(app.state.store.get('reports', pid))
        assert parent['metrics']['observed_network_fees_sol']['value'] == '0.000055'
        path = app.state.store.path / 'evidence' / f'{clock}.json.gz'
        before = path.read_bytes()
        path.unlink()
        child_id = client.post('/api/reports/' + pid + '/rebuild').json()['report_id']
        child = client.get('/api/reports/' + child_id).json()
        assert child['metrics']['observed_network_fees_sol']['status'] == 'unknown'
        assert child['window'] == parent['window'] and child['preset'] == parent['preset']
        assert child['archive_input_hash'] == parent['archive_input_hash']
        assert client.get('/api/export/reports/' + child_id + '.json').json()['metrics'] == child['metrics']
        assert client.get('/api/export/reports/' + child_id + '.csv').status_code == 200
        path.write_bytes(before)
        restored_id = client.post('/api/reports/' + pid + '/rebuild').json()['report_id']
        restored = client.get('/api/reports/' + restored_id).json()
        assert restored['metrics'] == parent['metrics']
        assert app.state.store.get('reports', pid) == saved
        assert client.get('/api/state').json()['usage'] == usage
        assert not app.state.store.list('collector_checkpoints')


@pytest.mark.parametrize('dataset', ['real', 'synthetic'])
def test_old_archive_interpretation_requires_rebuild_without_rewriting_saved_values(tmp_path, monkeypatch, dataset):
    monkeypatch.setattr(application, 'Credentials', lambda _: SimpleNamespace(key=None, storage='none', backend=None))
    app = application.create_app(tmp_path, 'isolated-archive-freshness-test')
    value = bundle()
    value['manifest']['dataset'] = dataset
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        csrf = client.get('/api/bootstrap', headers={'X-Launch-Token': 'isolated-archive-freshness-test'}).json()['csrf']
        client.headers['X-CSRF-Token'] = csrf
        pid = client.post('/api/archives/import', content=pack_bytes(value)).json()['report_id']
        saved = app.state.store.get('reports', pid)
        saved['archive_accounting']['version'] = 'archive-ledger-v1'
        app.state.store.put('reports', pid, saved)
        old = client.get('/api/reports/' + pid).json()
        assert old['archive_assessment']['state'] == 'rebuild_required'
        assert any(x['key'] == 'archive_methodology' for x in old['qualification']['unknown_checks'])
        assert old['metrics'] == saved['metrics']
        child_id = client.post('/api/reports/' + pid + '/rebuild').json()['report_id']
        child = client.get('/api/reports/' + child_id).json()
        assert child['archive_assessment']['state'] == 'current'
        assert child['metrics'] == old['metrics']
        assert app.state.store.get('reports', pid) == saved
