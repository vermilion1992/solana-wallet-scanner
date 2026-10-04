"""Synthetic evidence helpers only. No mainnet authentication or provider IO."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
from tests import test_position_evidence as pb
from scanner.history_evidence import MAX_REFERENCES

@pytest.fixture
def builder():
    case = pb.PositionEvidenceTests(methodName='runTest')
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()

def add_alternative(case, boundary, *, offset=True):
    index = 0 if boundary == 'opening' else 2
    raw = deepcopy(case.raws[index])
    if offset:
        for name in ('preTokenBalances', 'postTokenBalances'):
            row = next(row for row in raw['meta'][name] if row['accountIndex'] == 1)
            row['uiTokenAmount']['amount'] = str(int(row['uiTokenAmount']['amount']) + (200 if index == 0 else 1))
    else:
        raw['meta']['logMessages'] = []
    digest = case.store.archive(raw)
    ref = {'kind': 'transaction', 'hash': digest, 'signature': case.records[index]['signature']}
    case.cp['evidence'].append(ref)
    case.persist()
    return ref

def capped_alternative(case, boundary, *, total=MAX_REFERENCES + 1, placement='tail'):
    ref = add_alternative(case, boundary)
    originals = deepcopy(case.cp['evidence'][:-1])
    duplicate = next(row for row in originals if row.get('kind') == 'transaction')
    padding = [deepcopy(duplicate) for _ in range(total - len(originals) - 1)]
    case.cp['evidence'] = originals + padding + [ref]
    if placement == 'prefix':
        # Same multiset, only exchange the first padding reference and final one.
        k = len(originals)
        case.cp['evidence'][k], case.cp['evidence'][-1] = case.cp['evidence'][-1], case.cp['evidence'][k]
    case.persist()
    return ref

def record(name, data):
    root = os.environ.get('REVIEW_OUTPUT')
    if root:
        path = Path(root); path.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(json.dumps(data, indent=2))

def rebuild_api(case, tmp_path, monkeypatch):
    """Freeze ALL references, copying unique blobs once; exercise actual API."""
    import httpx
    from fastapi.testclient import TestClient
    from scanner.app import create_app
    from scanner.config import STRICT
    from scanner.report_rebuild import freeze_report_inputs
    monkeypatch.delenv('HELIUS_API_KEY', raising=False)
    calls = {'provider': 0, 'credential': 0}
    def deny_credential(*args, **kwargs):
        calls['credential'] += 1
        raise AssertionError('No credentials permitted in review')
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(get_keyring=lambda: object(), get_password=deny_credential))
    async def deny_network(*args, **kwargs):
        calls['provider'] += 1
        raise AssertionError('No provider requests permitted in review')
    monkeypatch.setattr(httpx.AsyncClient, 'request', deny_network)
    app = create_app(tmp_path / 'app', 'review-v036-synthetic-launch-token')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        bootstrap = client.get('/api/bootstrap', headers={'x-launch-token': 'review-v036-synthetic-launch-token'})
        assert bootstrap.status_code == 200
        client.headers['x-csrf-token'] = bootstrap.json()['csrf']
        store = app.state.store
        checkpoint = deepcopy(case.cp)
        for digest in {ref['hash'] for ref in checkpoint['evidence']}:
            assert store.archive(case.store.evidence(digest)) == digest
        key = hashlib.sha256(f'{pb.WALLET}:{pb.START}:{pb.END}'.encode()).hexdigest()
        store.put('collector_checkpoints', key, checkpoint)
        window = {k: datetime.fromtimestamp(v, timezone.utc).isoformat() for k, v in pb.WINDOW.items()}
        collected = {'transactions': list(checkpoint['transactions'].values()), 'checkpoint': checkpoint,
                     'evidence': checkpoint['evidence'], 'snapshot': checkpoint['snapshot'], 'coverage': {'status': 'partial'}}
        original = {'id': 'review-v036-original', 'scan_id': 'review-v036-scan', 'source': 'live',
                    'address': pb.WALLET, 'created_at': '2026-10-03T00:00:00+00:00', 'window': window,
                    'preset': dict(STRICT), 'methodology': 'fifo-v3', 'metrics': {}, 'checks': [],
                    'policy': 'UNRESOLVED', 'evidence_status': 'partial', 'coverage': {}, 'token_risk': [],
                    'evidence': checkpoint['evidence'],
                    'collection_input_hash': freeze_report_inputs(store, pb.WALLET, window, collected)}
        store.put('reports', original['id'], original)
        store.put('scans', original['scan_id'], {'id': original['scan_id'], 'status': 'paused',
                  'audit_addresses': [pb.WALLET], 'window': window, 'preset': dict(STRICT), 'budget_mode': 'setup-pilot'})
        usage = client.get('/api/state').json()['usage']
        response = client.post('/api/reports/' + original['id'] + '/rebuild')
        assert response.status_code == 200, response.text
        child = client.get('/api/reports/' + response.json()['report_id']).json()
        assert child['id'] != original['id']
        assert store.get('reports', original['id']) == original
        assert client.get('/api/state').json()['usage'] == usage
        assert child['policy'] == 'UNRESOLVED' and child['qualification']['qualified'] is False
        assert child['rebuild']['provider_requests'] == 0
        assert set(child['coverage']['history_evidence']['evidence_gates'].values()) == {'UNKNOWN'}
        assert calls == {'provider': 0, 'credential': 0}
        manifest = store.evidence(child['collection_input_hash'])
        assert manifest['checkpoint']['evidence'] == checkpoint['evidence']
        assert len(manifest['evidence']) == len(checkpoint['evidence'])
        boundary = {'parent_unchanged': True, 'usage_unchanged': True, 'calls': calls,
                    'frozen_reference_count': len(manifest['checkpoint']['evidence']),
                    'policy': child['policy'], 'qualified': child['qualification']['qualified'],
                    'provider_requests': child['rebuild']['provider_requests']}
        return child, boundary
