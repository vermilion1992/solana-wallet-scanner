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
from scanner.storage import Store
from scanner.accounting import utc


def development_inputs():
    value = json.loads((Path(__file__).resolve().parents[1] /
                       'scanner/examples/archive-wallet-synthetic.json').read_text())
    # Exercise the production adapter using dev bytes. This relabelling is
    # intentionally insufficient for authenticity or real-wallet completion.
    value['manifest']['dataset'] = 'real'
    return value


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
