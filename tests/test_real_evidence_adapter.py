"""Integration controls use development raw inputs; these are not B3 evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
import pytest

import scanner.app as application
from scanner.archive_input import pack_bytes
from scanner.archive_input import import_archive, load_archive, decode_archive, analyze_archive, canonical_bytes
from scanner.storage import Store
from scanner.accounting import utc


def development_inputs():
    value = json.loads((Path(__file__).resolve().parents[1] /
                       'scanner/examples/archive-wallet-synthetic.json').read_text())
    # Exercise the production adapter using dev bytes. This relabelling is
    # intentionally insufficient for authenticity or real-wallet completion.
    value['manifest']['dataset'] = 'real'
    return value


@pytest.mark.parametrize('role', ['classification', 'valuation', 'current-mint-controls'])
def test_wrong_role_native_dependency_is_frozen_across_loss_restoration_and_pointer_change(tmp_path, monkeypatch, role):
    value = development_inputs()
    row = value['manifest']['transactions'][1]
    alternate = deepcopy(value['payloads'][row['hash']])
    alternate['meta']['fee'] += 1
    other = hashlib.sha256(canonical_bytes(alternate)).hexdigest()
    value['payloads'][other] = alternate
    if role == 'classification':
        value['manifest']['classification_hashes'].append(other)
    elif role == 'valuation':
        value['manifest']['valuation_hash'] = other
    else:
        value['manifest'].setdefault('evidence', []).append({'kind': role, 'hash': other})
    calls = {'provider': 0, 'credentials': 0}
    def forbidden_provider(*args, **kwargs):
        calls['provider'] += 1
        raise AssertionError('Offline operation attempted provider dispatch')
    def forbidden_credentials(*args, **kwargs):
        calls['credentials'] += 1
        raise AssertionError('Offline operation attempted credential lookup')
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden_provider)
    monkeypatch.setattr(application, 'Credentials', lambda _: SimpleNamespace(key=None, storage='none', backend=None))
    import keyring
    monkeypatch.setattr(keyring, 'get_password', forbidden_credentials)
    app = application.create_app(tmp_path, 'negative-role-session')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        csrf = client.get('/api/bootstrap', headers={'X-Launch-Token': 'negative-role-session'}).json()['csrf']
        client.headers['X-CSRF-Token'] = csrf
        response = client.post('/api/archives/import', content=pack_bytes(value), headers={'Content-Type': 'application/zip'})
        assert response.status_code == 200, response.text
        parent_id = response.json()['report_id']
        parent = client.get('/api/reports/' + parent_id).json()
        assert parent['metrics']['observed_network_fees_sol']['status'] == 'unknown'
        assert app.state.store.evidence(parent['archive_input_hash']) == value['manifest']
        dependency_hash = parent['archive_dependency_input_hash']
        assert {'signature': row['signature'], 'hash': other} in app.state.store.evidence(dependency_hash)['links']
        original_export = client.get(f'/api/export/reports/{parent_id}.json').content
        path = app.state.store.path / 'evidence' / f'{other}.json.gz'
        original_bytes = path.read_bytes()
        path.unlink()
        # A later index cannot expand or replace this parent's frozen input.
        empty = app.state.store.archive({'version': 'archive-native-dependencies-v1',
            'manifest_hash': parent['archive_input_hash'], 'links': []})
        app.state.store.put('archive_dependency_inputs', parent['archive_input_hash'], {'hash': empty})
        child_response = client.post(f'/api/reports/{parent_id}/rebuild')
        assert child_response.status_code == 200, child_response.text
        child = client.get('/api/reports/' + child_response.json()['report_id']).json()
        assert child['archive_dependency_input_hash'] == dependency_hash
        assert child['metrics']['observed_network_fees_sol']['status'] == 'unknown'
        assert other in child['coverage']['wallet_evidence']['components']['native_fee']['evidence']
        path.write_bytes(original_bytes)
        restored_response = client.post(f'/api/reports/{parent_id}/rebuild')
        assert restored_response.status_code == 200, restored_response.text
        restored = client.get('/api/reports/' + restored_response.json()['report_id']).json()
        assert restored['metrics'] == parent['metrics']
        assert client.get(f'/api/export/reports/{parent_id}.json').content == original_export
    assert calls == {'provider': 0, 'credentials': 0}


@pytest.mark.parametrize('loss', ['missing', 'corrupt'])
def test_auxiliary_dependency_inventory_loss_blocks_its_projection_and_restores(tmp_path, loss):
    value = development_inputs()
    store = Store(tmp_path)
    digest = import_archive(store, pack_bytes(value))
    parent = load_archive(store, digest)
    events, _ = decode_archive(parent)
    original, _, _ = analyze_archive(parent, events)
    dependency_hash = parent['dependency_input_hash']
    path = store.path / 'evidence' / f'{dependency_hash}.json.gz'
    raw = path.read_bytes()
    path.unlink() if loss == 'missing' else path.write_bytes(b'corrupt')
    child = load_archive(store, digest, dependency_input_hash=dependency_hash)
    events, _ = decode_archive(child)
    missing, _, _ = analyze_archive(child, events)
    assert missing['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    path.write_bytes(raw)
    restored = load_archive(store, digest, dependency_input_hash=dependency_hash)
    events, _ = decode_archive(restored)
    recovered, _, _ = analyze_archive(restored, events)
    assert recovered['metrics'] == original['metrics']


def test_legacy_archive_parent_does_not_adopt_a_later_import_inventory(tmp_path):
    value = development_inputs()
    store = Store(tmp_path)
    digest = import_archive(store, pack_bytes(value))
    loaded = load_archive(store, digest, dependency_input_hash=None)
    assert loaded['dependency_input_hash'] is None
    events, _ = decode_archive(loaded)
    result, _, _ = analyze_archive(loaded, events)
    assert result['metrics']['observed_network_fees_sol']['status'] == 'unknown'


def test_native_saved_inputs_retain_content_derived_negative_links(tmp_path):
    from scanner.report_rebuild import freeze_report_inputs
    from scanner.wallet_evidence import derive_wallet_evidence
    value = development_inputs(); store = Store(tmp_path)
    row = value['manifest']['transactions'][1]
    original = value['payloads'][row['hash']]; store.archive(original)
    changed = deepcopy(original); changed['meta']['fee'] += 1
    other = store.archive(changed)
    collected = {'transactions': [{'signature': row['signature'], 'evidence_hash': row['hash']}],
                 'evidence': [{'kind': 'classification', 'hash': other}]}
    address, window = value['manifest']['address'], value['manifest']['window']
    frozen, *_ = application._freeze_native_dependencies(store, collected, address=address, window=window)
    assert collected['evidence'] == [{'kind': 'classification', 'hash': other}]
    digest = freeze_report_inputs(store, address, window, frozen)
    before = store.evidence(digest)
    path = store.path / 'evidence' / f'{other}.json.gz'; raw = path.read_bytes()
    path.unlink()
    selected, linked, sources, receipts = application._wallet_adapter_inputs(store,
        {**store.evidence(digest), 'frozen_input_hash': digest}, address=address, window=window)
    result = derive_wallet_evidence(selected, all_records=linked, wallet=address, window=window,
        source_consistency={}, chronology={}, raw_sources=sources, source_receipts=receipts)
    assert result['components']['native_fee']['state'] == 'UNKNOWN'
    path.write_bytes(raw)
    assert store.evidence(digest) == before


def test_native_adapter_reads_original_bytes_and_every_linked_alternative(tmp_path):
    value = development_inputs()
    store = Store(tmp_path)
    selected = value['manifest']['transactions'][0]
    payload = value['payloads'][selected['hash']]
    assert store.archive(payload) == selected['hash']
    alternative = deepcopy(payload)
    alternative['meta']['fee'] += 1
    other_hash = store.archive(alternative)
    collected = {'transactions': [{'signature': selected['signature'],
        'evidence_hash': selected['hash'], 'raw': {'caller_interpretation': True}}],
        'evidence': [{'kind': 'getTransaction', 'hash': other_hash, 'signature': selected['signature']}]}
    primary, linked, sources, receipts = application._wallet_adapter_inputs(store, collected)
    assert primary[0]['raw'] == payload
    assert {row['evidence_hash'] for row in linked} == {selected['hash'], other_hash}
    assert sources == [] and all(row['state'] == 'PASS' for row in receipts)
    path = store.path / 'evidence' / f'{other_hash}.json.gz'
    raw = path.read_bytes()
    path.unlink()
    _, linked, _, receipts = application._wallet_adapter_inputs(store, collected)
    assert next(row for row in linked if row['evidence_hash'] == other_hash)['raw'] is None
    assert any(row.get('hash') == other_hash and row['state'] == 'UNKNOWN' for row in receipts)
    path.write_bytes(raw)
    assert application._wallet_adapter_inputs(store, collected)[1][1]['raw'] == alternative


@pytest.mark.parametrize('source', ['frozen-checkpoint', 'persisted-checkpoint'])
def test_native_adapter_retains_checkpoint_alternatives_when_current_manifest_omits_them(tmp_path, source):
    from scanner.wallet_evidence import derive_wallet_evidence
    value = development_inputs()
    store = Store(tmp_path)
    row = value['manifest']['transactions'][0]
    raw = value['payloads'][row['hash']]
    store.archive(raw)
    alternative = deepcopy(raw)
    alternative['meta']['fee'] += 1
    other = store.archive(alternative)
    refs = [{'kind': 'transaction', 'signature': row['signature'], 'hash': other}]
    collected = {'transactions': [{'signature': row['signature'], 'evidence_hash': row['hash'], 'raw': raw}],
                 'evidence': []}
    address, window = value['manifest']['address'], value['manifest']['window']
    if source == 'frozen-checkpoint':
        collected['checkpoint'] = {'evidence': refs}
    else:
        identifier = hashlib.sha256(f"{address}:{int(utc(window['start']).timestamp())}:{int(utc(window['end']).timestamp())}".encode()).hexdigest()
        store.put('collector_checkpoints', identifier, {'evidence': refs})
    primary, linked, raw_sources, receipts = application._wallet_adapter_inputs(store, collected, address=address, window=window)
    assert {r['evidence_hash'] for r in linked} == {row['hash'], other}
    derived = derive_wallet_evidence(primary, all_records=linked, wallet=address, window=window,
        source_consistency={}, chronology={}, source_receipts=receipts, raw_sources=raw_sources)
    assert derived['components']['native_fee']['state'] == 'UNKNOWN'
    assert other in derived['components']['native_fee']['evidence']


def test_frozen_adapter_references_do_not_expand_with_later_collector_state(tmp_path):
    value = development_inputs()
    store = Store(tmp_path)
    row = value['manifest']['transactions'][0]
    store.archive(value['payloads'][row['hash']])
    collected = {'transactions': [{'signature': row['signature'], 'evidence_hash': row['hash']}],
        'checkpoint': {'evidence': []}, 'evidence': [], 'frozen_input_hash': 'a' * 64, 'frozen_report_id': 'saved-parent'}
    address, window = value['manifest']['address'], value['manifest']['window']
    before = application._wallet_adapter_inputs(store, collected, address=address, window=window)
    altered = deepcopy(value['payloads'][row['hash']])
    altered['meta']['fee'] += 1
    other = store.archive(altered)
    identifier = hashlib.sha256(f"{address}:{int(utc(window['start']).timestamp())}:{int(utc(window['end']).timestamp())}".encode()).hexdigest()
    store.put('collector_checkpoints', identifier, {'evidence': [{'kind': 'transaction', 'signature': row['signature'], 'hash': other}]})
    assert application._wallet_adapter_inputs(store, collected, address=address, window=window) == before


@pytest.mark.parametrize('malformed', ['hash', 'kind', 'signature'])
def test_malformed_link_cannot_disappear_or_crash_native_adapter(tmp_path, malformed):
    from scanner.wallet_evidence import derive_wallet_evidence
    value = development_inputs()
    store = Store(tmp_path)
    row = value['manifest']['transactions'][0]
    raw = value['payloads'][row['hash']]
    store.archive(raw)
    bad = {'kind': 'transaction', 'signature': row['signature'], 'hash': row['hash']}
    bad[malformed] = [] if malformed in ('kind', 'signature') else 'bad'
    collected = {'transactions': [{'signature': row['signature'], 'evidence_hash': row['hash']}], 'evidence': [bad]}
    primary, linked, sources, receipts = application._wallet_adapter_inputs(store, collected)
    assert any(receipt['state'] == 'UNKNOWN' for receipt in receipts)
    derived = derive_wallet_evidence(primary, all_records=linked, wallet=value['manifest']['address'],
        window=value['manifest']['window'], source_consistency={}, chronology={}, source_receipts=receipts, raw_sources=sources)
    assert derived['components']['native_fee']['state'] == 'UNKNOWN'
    assert derived['components']['selected_record_identity']['state'] == 'UNKNOWN'


def test_proved_outside_window_unknown_fee_preserves_in_window_total(tmp_path):
    value = development_inputs()
    row = value['manifest']['transactions'][0]
    raw = deepcopy(value['payloads'][row['hash']])
    assert utc(raw['blockTime']) < utc(value['manifest']['window']['start'])
    raw['meta']['fee'] = None
    digest = hashlib.sha256(canonical_bytes(raw)).hexdigest()
    value['payloads'][digest] = raw
    row['hash'] = digest
    store = Store(tmp_path)
    manifest_hash = import_archive(store, pack_bytes(value))
    loaded = load_archive(store, manifest_hash)
    events, _ = decode_archive(loaded)
    result, _, coverage = analyze_archive(loaded, events)
    assert coverage['fee_interval_membership'][row['signature']]['member'] is False
    assert result['metrics']['observed_network_fees_sol']['value'] == '0.000055'
    assert coverage['metric_requirements']['observed_network_fees_sol']['state'] == 'PASS'
    # A linked clock crossing the boundary removes the supported exclusion.
    alternative = deepcopy(raw)
    alternative['blockTime'] = int(utc(value['manifest']['window']['start']).timestamp()) + 60
    other = hashlib.sha256(canonical_bytes(alternative)).hexdigest()
    value['payloads'][other] = alternative
    value['manifest'].setdefault('evidence', []).append({'kind': 'getTransaction', 'signature': row['signature'], 'hash': other})
    changed_manifest = import_archive(store, pack_bytes(value))
    changed = load_archive(store, changed_manifest)
    events, _ = decode_archive(changed)
    blocked, _, _ = analyze_archive(changed, events)
    assert blocked['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    # Returning to the exact original frozen reference universe recovers it.
    restored = load_archive(store, manifest_hash)
    events, _ = decode_archive(restored)
    recovered, _, _ = analyze_archive(restored, events)
    assert recovered['metrics'] == result['metrics']


def test_physical_inspection_budget_loss_preserves_independent_native_fees(tmp_path, monkeypatch):
    import scanner.wallet_evidence as adapter
    value = development_inputs()
    store = Store(tmp_path)
    digest = import_archive(store, pack_bytes(value))
    monkeypatch.setattr(adapter, 'MAX_ACCOUNT_STEPS', 1)
    loaded = load_archive(store, digest)
    events, _ = decode_archive(loaded)
    result, _, coverage = analyze_archive(loaded, events)
    raw_evidence = coverage['wallet_evidence']
    assert raw_evidence['inspection_budget']['quantity_state'] == 'UNKNOWN'
    assert raw_evidence['components']['observed_quantities']['state'] == 'UNKNOWN'
    assert result['metrics']['observed_network_fees_sol']['value'] == '0.000055'
    assert result['metrics']['profit_sol']['status'] == 'unknown'


def test_existing_archive_alternative_capacity_is_preserved(tmp_path):
    # One engineering case, not 10,001 tests or a wallet population witness.
    value = development_inputs()
    address = value['manifest']['address']
    at = int(utc(value['manifest']['window']['start']).timestamp())
    template = {'version': 0, 'slot': 1000, 'blockTime': at,
        'transaction': {'signatures': ['dev-bulk-fee'], 'message': {'accountKeys': [address], 'instructions': []}},
        'meta': {'err': None, 'fee': 5000, 'preBalances': [1000000000], 'postBalances': [999995000],
                 'preTokenBalances': [], 'postTokenBalances': [], 'innerInstructions': []}}
    payloads, refs = {}, []
    for variant in range(10_001):
        raw = {**template, 'development_variant': variant}
        digest = hashlib.sha256(canonical_bytes(raw)).hexdigest()
        payloads[digest] = raw
        refs.append({'signature': 'dev-bulk-fee', 'hash': digest})
    value = {'manifest': {'version': value['manifest']['version'], 'address': address,
        'window': value['manifest']['window'], 'dataset': 'real', 'transactions': refs[:1],
        'evidence': [{'kind': 'getTransaction', **row} for row in refs[1:]]}, 'payloads': payloads}
    store = Store(tmp_path)
    digest = import_archive(store, pack_bytes(value))
    loaded = load_archive(store, digest)
    events, _ = decode_archive(loaded)
    result, _, coverage = analyze_archive(loaded, events)
    assert coverage['wallet_evidence']['inspection_budget']['linked_records'] == 10_001
    assert result['metrics']['observed_network_fees_sol']['value'] == '0.000005'
    assert coverage['real_acceptance'] == 'BLOCKED'


@pytest.mark.parametrize('loss', ['selected', 'classification', 'valuation'])
def test_real_adapter_is_saved_exported_and_rebuilt_offline_without_parent_mutation(tmp_path, monkeypatch, loss):
    calls = {'provider': 0, 'credentials': 0}
    def denied(*args, **kwargs):
        calls['provider'] += 1
        raise AssertionError('Provider dispatch during offline adapter workflow')
    def credential_lookup(*args, **kwargs):
        calls['credentials'] += 1
        raise AssertionError('Credential lookup during offline adapter workflow')
    monkeypatch.setattr(application, 'Credentials', lambda _: SimpleNamespace(key=None, storage='none', backend=None))
    monkeypatch.setattr(httpx.AsyncClient, 'request', denied)
    monkeypatch.setattr('keyring.get_password', credential_lookup)
    value = development_inputs()
    app = application.create_app(tmp_path, 'offline-adapter-session')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        csrf = client.get('/api/bootstrap', headers={'X-Launch-Token': 'offline-adapter-session'}).json()['csrf']
        headers = {'X-CSRF-Token': csrf}
        imported = client.post('/api/archives/import', content=pack_bytes(value), headers=headers)
        assert imported.status_code == 200, imported.text
        parent_id = imported.json()['report_id']
        parent = client.get('/api/reports/' + parent_id).json()
        adapter = parent['coverage']['wallet_evidence']
        assert adapter == parent['archive_accounting']['wallet_evidence']
        assert adapter['components']['historical_population']['state'] == 'UNKNOWN'
        assert adapter['transactions'] and adapter['accounts']
        assert parent['metrics']['observed_network_fees_sol']['value'] == '0.000055'
        assert parent['metrics']['profit_sol']['status'] == 'unknown'
        assert parent['qualification']['qualified'] is False
        assert set(adapter['intervals']) == {'report_period', 'four_weeks', 'verification_90d'}
        assert parent['coverage']['metric_dependencies'] == parent['archive_accounting']['metric_requirements']
        export = client.get(f'/api/export/reports/{parent_id}.json').content
        assert json.loads(export)['coverage']['wallet_evidence'] == adapter
        digest = {'selected': value['manifest']['transactions'][0]['hash'],
                  'classification': value['manifest']['classification_hashes'][0],
                  'valuation': value['manifest']['valuation_hash']}[loss]
        path = app.state.store.path / 'evidence' / f'{digest}.json.gz'
        original = path.read_bytes()
        path.unlink()
        rebuilt = client.post(f'/api/reports/{parent_id}/rebuild', headers=headers)
        assert rebuilt.status_code == 200, rebuilt.text
        child = client.get('/api/reports/' + rebuilt.json()['report_id']).json()
        assert child['id'] != parent_id and child['rebuilt_from'] == parent_id
        assert child['metrics']['profit_sol']['status'] == 'unknown'
        assert child['metrics']['observed_network_fees_sol']['status'] == ('unknown' if loss == 'selected' else 'known')
        assert child['coverage']['wallet_evidence']['components']['historical_population']['state'] == 'UNKNOWN'
        assert client.get(f'/api/export/reports/{parent_id}.json').content == export
        path.write_bytes(original)
        restored = client.post(f'/api/reports/{parent_id}/rebuild', headers=headers)
        assert restored.status_code == 200, restored.text
        recovered = client.get('/api/reports/' + restored.json()['report_id']).json()
        assert recovered['metrics'] == parent['metrics']
        assert recovered['coverage']['wallet_evidence'] == adapter
        assert client.get(f'/api/export/reports/{parent_id}.json').content == export
        assert client.get(f'/api/export/reports/{recovered["id"]}.csv').status_code == 200
        assert not app.state.store.list('collector_checkpoints')
    assert calls == {'provider': 0, 'credentials': 0}
