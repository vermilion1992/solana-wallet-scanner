"""Small development controls for native exact-byte snapshot collection/rebuild."""
from copy import deepcopy
from datetime import datetime, timezone
import asyncio
import inspect
import hashlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from scanner.app import create_app
from scanner.collector import collect_wallet
from scanner.config import STRICT
from scanner.inventory_evidence import (NATIVE_SOURCE_VERSION, native_inventory_source,
                                        inventory_source_bytes, derive_inventory_evidence)
from scanner.json_boundary import canonical_bytes
from scanner.providers import Gateway, MethodDenied, TOKEN_PROGRAM, TOKEN_2022_PROGRAM
from tests.test_providers import MemoryStore

WALLET = '11111111111111111111111111111111'
SIGNATURE = '1' * 64
START, END = 200_000, 300_000
WINDOW = {name: datetime.fromtimestamp(value, timezone.utc).isoformat()
          for name, value in (('start', START), ('end', END))}


def test_capture_keeps_exact_success_bodies_and_existing_allowlist():
    seen = []
    async def exercise():
        def handler(request):
            body = json.loads(request.content)
            raw = (' { "jsonrpc": "2.0", "id": %d, "result": '
                   '{"context":{"slot":100},"value":1000000} }\n' % body['id']).encode()
            seen.append((request.content, raw))
            return httpx.Response(200, content=raw)
        async with Gateway(MemoryStore(), 'offline-test-secret', '2026-10-01',
                           transport=httpx.MockTransport(handler)) as gateway:
            gateway._throttle = AsyncMock()
            observed = await gateway.rpc_capture('getBalance', [WALLET, {'commitment': 'finalized'}])
            assert (observed.request_bytes, observed.response_bytes) == seen[0]
            assert b'offline-test-secret' not in observed.request_bytes + observed.response_bytes
            assert observed.result == {'context': {'slot': 100}, 'value': 1000000}
            with pytest.raises(MethodDenied):
                await gateway.rpc_capture('sendTransaction', ['unsupported'])
            assert gateway.requests == gateway.credits == 1
    asyncio.run(exercise())


def test_captured_projection_cannot_disagree_with_original_request_or_result():
    request = json.dumps({'jsonrpc': '2.0', 'id': 8, 'method': 'getBalance',
                          'params': [WALLET, {'commitment': 'finalized'}]}).encode()
    result = {'context': {'slot': 100}, 'value': 1000000}
    response = json.dumps({'jsonrpc': '2.0', 'id': 8, 'result': result}).encode()
    payload = native_inventory_source(request, response, method='getBalance', result=result, address=WALLET)
    assert inventory_source_bytes(payload) == {'request': request, 'response': response}
    for field, value in [('address', 'So11111111111111111111111111111111111111112'),
                         ('result', {'context': {'slot': 100}, 'value': 2})]:
        changed = {**payload, field: value}
        with pytest.raises(ValueError, match='disagrees'):
            inventory_source_bytes(changed)
    conflicting_result = {'context': {'slot': 100}, 'value': 2}
    conflicting = native_inventory_source(request,
        json.dumps({'jsonrpc': '2.0', 'id': 8, 'result': conflicting_result}).encode(),
        method='getBalance', result=conflicting_result, address=WALLET)
    def row(value):
        return {'kind': 'native-balance', 'hash': hashlib.sha256(canonical_bytes(value)).hexdigest(),
                'payload': value}
    assert derive_inventory_evidence([row(payload)], wallet=WALLET)['components']['native_balance']['state'] == 'PASS'
    disputed = derive_inventory_evidence([row(payload), row(conflicting)], wallet=WALLET)['components']
    assert disputed['native_balance']['state'] == disputed['native_lamports']['state'] == 'UNKNOWN'


def test_native_selector_union_is_bounded_before_archiving_and_replays_at_exact_cap(tmp_path, monkeypatch):
    import scanner.app as application
    from scanner.storage import Store, EvidenceError
    from scanner.report_rebuild import freeze_report_inputs
    import scanner.source_consistency as consistency
    store = Store(tmp_path / 'bounded-native')
    request = json.dumps({'jsonrpc': '2.0', 'id': 8, 'method': 'getBalance',
                          'params': [WALLET, {'commitment': 'finalized'}]}).encode()
    result = {'context': {'slot': 100}, 'value': 1000000}
    response = json.dumps({'jsonrpc': '2.0', 'id': 8, 'result': result}).encode()
    payload = native_inventory_source(request, response, method='getBalance', result=result, address=WALLET)
    digest = store.archive(payload)
    refs = [{'kind': 'native-balance', 'hash': digest}]
    collected = {'transactions': [], 'evidence': refs, 'checkpoint': {'evidence': refs}}
    before = {path.name: path.read_bytes() for path in (store.path / 'evidence').iterdir()}
    monkeypatch.setattr(consistency, 'SOURCE_HASH_LIMIT', 1)
    with pytest.raises(EvidenceError, match='inventory.*budget'):
        application._freeze_native_dependencies(store, collected, address=WALLET, window=WINDOW)
    assert {path.name: path.read_bytes() for path in (store.path / 'evidence').iterdir()} == before
    assert collected['evidence'] == refs and 'native_inventory_dependencies' not in collected
    monkeypatch.setattr(consistency, 'SOURCE_HASH_LIMIT', 2)
    frozen, primary, linked, sources, receipts = application._freeze_native_dependencies(
        store, collected, address=WALLET, window=WINDOW)
    identifier = freeze_report_inputs(store, WALLET, WINDOW, frozen)
    parent = {'id': 'bounded-native-parent', 'source': 'live', 'address': WALLET,
              'window': WINDOW, 'collection_input_hash': identifier}
    store.put('reports', parent['id'], parent)
    restored = {**store.evidence(identifier), 'frozen_input_hash': identifier,
                'frozen_report_id': parent['id']}
    replayed_primary, replayed_linked, replayed_sources, replayed_receipts = application._wallet_adapter_inputs(
        store, restored, address=WALLET, window=WINDOW)
    assert primary == linked == replayed_primary == replayed_linked == []
    assert frozen['evidence'] == restored['checkpoint']['evidence'] == refs
    assert derive_inventory_evidence(sources, wallet=WALLET, source_receipts=receipts) == derive_inventory_evidence(
        replayed_sources, wallet=WALLET, source_receipts=replayed_receipts)
    assert store.get('reports', parent['id']) == parent


def test_native_collection_and_two_offline_generations_keep_snapshot_dependencies(tmp_path, monkeypatch):
    import scanner.app as application
    captures = {}
    raw = {'slot': 99, 'blockTime': START + 1, 'version': 'legacy',
           'transaction': {'signatures': [SIGNATURE], 'message': {'accountKeys': [WALLET], 'instructions': []}},
           'meta': {'err': None, 'fee': 5000, 'preBalances': [1005000], 'postBalances': [1000000],
                    'preTokenBalances': [], 'postTokenBalances': [], 'innerInstructions': []}}
    def handler(request):
        body = json.loads(request.content)
        method, params = body['method'], body['params']
        if method == 'getSlot':
            result = 100
        elif method == 'getBalance':
            result = {'context': {'slot': 100}, 'value': 1000000}
        elif method == 'getTokenAccountsByOwner':
            result = {'context': {'slot': 100}, 'value': []}
        elif method == 'getSignaturesForAddress':
            result = [] if params[1].get('before') else [
                {'signature': SIGNATURE, 'slot': 99, 'blockTime': START + 1,
                 'err': None, 'confirmationStatus': 'finalized'}]
        elif method == 'getTransaction':
            result = raw
        else:
            raise AssertionError(method)
        response = (json.dumps({'jsonrpc': '2.0', 'id': body['id'], 'result': result},
                               indent=1) + '\n').encode()
        if method in ('getBalance', 'getTokenAccountsByOwner'):
            captures[(method, params[1].get('programId') if method == 'getTokenAccountsByOwner' else None)] = (
                request.content, response)
        return httpx.Response(200, content=response)
    calls = {'provider': 0, 'credential': 0, 'external_transport': 0}
    def denied_credentials(*args, **kwargs):
        calls['credential'] += 1
        raise AssertionError('offline replay must not read credentials')
    monkeypatch.delenv('HELIUS_API_KEY', raising=False)
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(get_keyring=lambda: object(),
                                                            get_password=denied_credentials))
    app = create_app(tmp_path / 'app', 'native-capture-test')
    store = app.state.store
    async def collect():
        async with Gateway(store, 'offline-test-secret', '2026-10-01', transport=httpx.MockTransport(handler)) as gateway:
            gateway._throttle = AsyncMock()
            return await collect_wallet(gateway, store, WALLET, START, END,
                {'basis_lookback_days': 1, 'transaction_limit': 10, 'wallet_credit_limit': 20,
                 'min_free_disk_mb': 1})
    collected = asyncio.run(collect())
    refs = deepcopy(collected['evidence'])
    snapshot_refs = [ref for ref in refs if ref['kind'] in ('native-balance', 'owned-accounts')]
    assert len(snapshot_refs) == 3
    for ref in snapshot_refs:
        payload = store.evidence(ref['hash'])
        assert payload['version'] == NATIVE_SOURCE_VERSION
        key = (payload['method'], payload.get('program'))
        assert tuple(inventory_source_bytes(payload).values()) == captures[key]
    scan = {'id': 'native-capture-scan', 'window': WINDOW, 'preset': deepcopy(STRICT),
            'status': 'paused', 'audit_addresses': [WALLET]}
    store.put('scans', scan['id'], scan)
    async def denied_provider(*args, **kwargs):
        calls['provider'] += 1
        raise AssertionError('offline replay must not dispatch provider')
    async def denied_transport(*args, **kwargs):
        calls['external_transport'] += 1
        raise AssertionError('offline replay must not use external transport')
    monkeypatch.setattr(Gateway, 'rpc', denied_provider)
    monkeypatch.setattr(Gateway, 'rpc_capture', denied_provider)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', denied_transport)
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        client.headers['X-CSRF-Token'] = client.get('/api/bootstrap',
            headers={'X-Launch-Token': 'native-capture-test'}).json()['csrf']
        endpoint = next(route.endpoint for route in app.routes
                        if getattr(route, 'path', None) == '/api/reports/{identifier}/rebuild')
        implementation = inspect.getclosurevars(endpoint).nonlocals['_rebuild_report']
        build = inspect.getclosurevars(implementation).nonlocals['build_report']
        parent = client.portal.call(build, scan, WALLET, collected)
        parent_bytes = deepcopy(store.get('reports', parent['id']))
        usage = deepcopy(client.get('/api/usage').json())
        inventory = parent['coverage']['wallet_evidence']['inventory_observations']
        assert inventory['components']['native_balance']['state'] == 'PASS'
        assert inventory['components']['native_lamports']['observations'][0]['lamports'] == '1000000'
        assert inventory['components']['same_slot_inventory']['state'] == 'PASS'
        assert inventory['components']['report_boundaries']['state'] == 'UNKNOWN'
        frozen = store.evidence(parent['collection_input_hash'])
        assert frozen['evidence'] == frozen['checkpoint']['evidence'] == refs
        assert len(frozen['native_inventory_dependencies']['affinity_hashes']) == 3
        current = parent
        for _ in range(2):
            before = deepcopy(store.get('reports', current['id']))
            response = client.post('/api/reports/' + current['id'] + '/rebuild')
            assert response.status_code == 200, response.text
            current = client.get('/api/reports/' + response.json()['report_id']).json()
            saved = store.evidence(current['collection_input_hash'])
            assert saved['evidence'] == saved['checkpoint']['evidence'] == refs
            assert saved['native_inventory_dependencies'] == frozen['native_inventory_dependencies']
            assert current['coverage']['wallet_evidence']['inventory_observations'] == inventory
            assert store.get('reports', before['id']) == before
        target = next(ref for ref in snapshot_refs
                      if store.evidence(ref['hash']).get('program') == TOKEN_2022_PROGRAM)
        path = store.path / 'evidence' / (target['hash'] + '.json.gz')
        original = path.read_bytes()
        for state in ('missing', 'corrupt', 'restored'):
            if state == 'missing':
                path.unlink()
            else:
                path.write_bytes(b'corrupt' if state == 'corrupt' else original)
            response = client.post('/api/reports/' + current['id'] + '/rebuild')
            assert response.status_code == 200, response.text
            child = client.get('/api/reports/' + response.json()['report_id']).json()
            components = child['coverage']['wallet_evidence']['inventory_observations']['components']
            assert components['native_balance']['state'] == components['token_programs'][TOKEN_PROGRAM]['state'] == 'PASS'
            assert components['token_programs'][TOKEN_2022_PROGRAM]['state'] == ('PASS' if state == 'restored' else 'UNKNOWN')
            assert components['same_slot_inventory']['state'] == ('PASS' if state == 'restored' else 'UNKNOWN')
            assert components['report_boundaries']['state'] == 'UNKNOWN'
            assert child['metrics']['observed_network_fees_sol']['value'] == '0.000005'
            assert store.get('reports', parent['id']) == parent_bytes
            assert client.get('/api/usage').json() == usage
        assert calls == {'provider': 0, 'credential': 0, 'external_transport': 0}
