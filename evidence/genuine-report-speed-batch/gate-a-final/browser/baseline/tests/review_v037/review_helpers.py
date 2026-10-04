"""Independent synthetic source-loss controls. Never mainnet or provider data."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
from tests import test_position_evidence as pb
from scanner.history_evidence import derive_history_evidence

@pytest.fixture
def builder():
    case = pb.PositionEvidenceTests(methodName='runTest')
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()

def history(case):
    return derive_history_evidence(case.store, pb.WALLET, pb.WINDOW, checkpoint=case.cp,
                                   collected={'transactions': case.records, 'checkpoint': case.cp})

def evidence_file(case, digest):
    return case.store.path / 'evidence' / f'{digest}.json.gz'

def write_result(name, value):
    root = os.environ.get('REVIEW_OUTPUT')
    if root:
        path = Path(root); path.mkdir(exist_ok=True, parents=True)
        (path / name).write_text(json.dumps(value, indent=2))

def conflict_page(case, boundary, *, beyond_fee=True):
    """A second account-page archive contradicts one selected execution result.

    Existing initial/terminal receipts and selected transactions remain present.
    A 1,000-lamport non-fee movement makes wallet delta execution-dependent.
    """
    index = 0 if boundary == 'opening' else 2
    if beyond_fee:
        case.raws[index]['meta']['postBalances'][0] -= 1000
        case.raws[index]['meta']['postBalances'][3] += 1000
        case.seed()
    entry = pb.entry(case.records[index]['signature'], case.raws[index])
    entry['err'] = {'InstructionError': [0, 'InvalidArgument']}
    payload = {'method': 'getSignaturesForAddress', 'address': pb.ACCOUNT,
               'params': {'limit': 100, 'commitment': 'finalized', 'minContextSlot': 1000},
               'result': [entry]}
    digest = case.store.archive(payload)
    reference = {'kind': 'signature-page', 'hash': digest}
    case.cp['evidence'].append(reference)
    case.persist()
    return reference

def damage(path, variant):
    if variant == 'missing':
        path.unlink()
    elif variant == 'corrupt':
        path.write_bytes(b'intentionally corrupted synthetic gzip archive')
    else:
        raise ValueError(variant)

def summary(position, h, digest):
    relevant = [row for row in position['positions'] if row.get('account') == pb.ACCOUNT]
    # Public position field is account, with fallback for older representations.
    row = relevant[0] if relevant else position['positions'][0]
    return {'known_closed': position['counts']['known_closed'], 'hold': row['hold_hours'],
            'stages': row['stages'], 'source_set': h['source_consistency'].get('source_set', {}),
            'linked_page_cited_by_position': digest in row['sources'],
            'native_observed': h['native_address_metrics']['observed'],
            'evidence_gates': h['evidence_gates']}

def api_damage_sequence(case, tmp_path, monkeypatch, digest, variant):
    """Real endpoint: intact conflict -> missing/corrupt -> exact byte restoration."""
    import httpx
    from fastapi.testclient import TestClient
    from scanner.app import create_app
    from scanner.config import STRICT
    from scanner.report_rebuild import freeze_report_inputs
    monkeypatch.delenv('HELIUS_API_KEY', raising=False)
    calls = {'provider': 0, 'credential': 0}
    def deny_credential(*args, **kwargs):
        calls['credential'] += 1
        raise AssertionError('Credential access prohibited in independent review')
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(get_keyring=lambda: object(), get_password=deny_credential))
    async def deny_network(*args, **kwargs):
        calls['provider'] += 1
        raise AssertionError('Provider IO prohibited in independent review')
    monkeypatch.setattr(httpx.AsyncClient, 'request', deny_network)
    token = 'review-v037-local-test-token'
    app = create_app(tmp_path / 'app', token)
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        bootstrap = client.get('/api/bootstrap', headers={'x-launch-token': token})
        assert bootstrap.status_code == 200
        client.headers['x-csrf-token'] = bootstrap.json()['csrf']
        store = app.state.store
        checkpoint = deepcopy(case.cp)
        for value in {ref['hash'] for ref in checkpoint['evidence']}:
            assert store.archive(case.store.evidence(value)) == value
        key = hashlib.sha256(f'{pb.WALLET}:{pb.START}:{pb.END}'.encode()).hexdigest()
        store.put('collector_checkpoints', key, checkpoint)
        window = {k: datetime.fromtimestamp(v, timezone.utc).isoformat() for k, v in pb.WINDOW.items()}
        collected = {'transactions': list(checkpoint['transactions'].values()), 'checkpoint': checkpoint,
                     'evidence': checkpoint['evidence'], 'snapshot': checkpoint['snapshot'], 'coverage': {'status': 'partial'}}
        original = {'id': 'review-v037-original', 'scan_id': 'review-v037-scan', 'source': 'live',
                    'address': pb.WALLET, 'created_at': '2026-10-03T00:00:00+00:00', 'window': window,
                    'preset': dict(STRICT), 'methodology': 'fifo-v3', 'metrics': {}, 'checks': [],
                    'policy': 'UNRESOLVED', 'evidence_status': 'partial', 'coverage': {}, 'token_risk': [],
                    'evidence': checkpoint['evidence'],
                    'collection_input_hash': freeze_report_inputs(store, pb.WALLET, window, collected)}
        store.put('reports', original['id'], original)
        store.put('scans', original['scan_id'], {'id': original['scan_id'], 'status': 'paused',
                  'audit_addresses': [pb.WALLET], 'window': window, 'preset': dict(STRICT), 'budget_mode': 'setup-pilot'})
        usage = client.get('/api/state').json()['usage']
        archive = store.path / 'evidence' / f'{digest}.json.gz'
        original_bytes = archive.read_bytes()
        children, results = [], []
        for phase in ['present_conflict', variant, 'restored_conflict']:
            if phase == variant:
                damage(archive, variant)
            elif phase == 'restored_conflict':
                archive.write_bytes(original_bytes)
            response = client.post('/api/reports/' + original['id'] + '/rebuild')
            assert response.status_code == 200, response.text
            child = client.get('/api/reports/' + response.json()['report_id']).json()
            assert child['id'] not in [original['id']] + children
            children.append(child['id'])
            assert store.get('reports', original['id']) == original
            assert client.get('/api/state').json()['usage'] == usage
            assert child['policy'] == 'UNRESOLVED' and child['qualification']['qualified'] is False
            assert child['rebuild']['provider_requests'] == 0
            h = child['coverage']['history_evidence']
            assert set(h['evidence_gates'].values()) == {'UNKNOWN'}
            frozen = store.evidence(child['collection_input_hash'])
            assert frozen['checkpoint']['evidence'] == checkpoint['evidence']
            assert frozen['evidence'] == checkpoint['evidence']
            results.append({'phase': phase, **summary(child['coverage']['position_evidence'], h, digest)})
            if phase == variant:
                write_result(f'R12_{variant}_{digest[:10]}_child.json', child)
        assert calls == {'provider': 0, 'credential': 0}
        assert archive.read_bytes() == original_bytes
        boundaries = {'parent_unchanged': True, 'usage_unchanged': True, 'unique_children': len(children),
                      'provider_calls': 0, 'credential_lookups': 0, 'policy': 'UNRESOLVED', 'qualified': False,
                      'frozen_references_preserved': True, 'frozen_reference_count': len(checkpoint['evidence']),
                      'corrupted_archive_restored_byte_exact': True}
        return results, boundaries
