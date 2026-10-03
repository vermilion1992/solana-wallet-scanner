"""Offline controls for the one-off authorised probe, not financial acceptance."""
import asyncio
from datetime import date, timedelta
import gzip
import importlib.util
import json
from pathlib import Path
import sys

import httpx
import pytest

MODULE = Path(__file__).with_name('execute_probe.py')
spec = importlib.util.spec_from_file_location('bounded_probe', MODULE)
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


@pytest.fixture
def plan():
    return probe.load_plan(probe.ROOT / 'evidence/product-milestone/SOURCE_PROBE_PLAN.json')


@pytest.fixture
def confirmation():
    today = date.today()
    return {'plan': 'Free', 'cycle_start': (today - timedelta(days=1)).isoformat(),
            'cycle_end': (today + timedelta(days=29)).isoformat(), 'remaining_credits': 100,
            'autoscaling': False, 'confirmed_by': 'user-dashboard'}


@pytest.fixture
def store(tmp_path):
    result = probe.Store(tmp_path / 'quota-data')
    yield result
    result.close()


@pytest.mark.parametrize('field,value', [
    ('plan', 'Developer'), ('plan', None), ('autoscaling', True), ('autoscaling', 0),
    ('remaining_credits', True), ('remaining_credits', 99), ('remaining_credits', '100'),
    ('cycle_start', '2020-01-01'), ('cycle_end', '2020-02-01'),
    ('confirmed_by', 'inferred from successful RPC'),
])
def test_missing_or_unconfirmed_dashboard_details_block(confirmation, field, value):
    confirmation[field] = value
    with pytest.raises(ValueError):
        probe.validate_confirmation(confirmation)


def test_dashboard_confirmation_is_explicit_not_provider_proof(confirmation):
    assert probe.validate_confirmation(confirmation) is confirmation


def test_changed_plan_is_rejected_before_network(plan, tmp_path):
    path = tmp_path / 'changed-plan.json'
    plan['credit_cap'] = 1000
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match='exact separately approved'):
        probe.load_plan(path)


def run(plan, confirmation, store, tmp_path, handler):
    return asyncio.run(probe.execute(plan, confirmation, 'synthetic-offline-key',
                                    tmp_path / 'receipts', store, httpx.MockTransport(handler)))


@pytest.mark.parametrize('status,body', [
    (403, {'jsonrpc': '2.0', 'id': 1, 'error': {'code': -32004, 'message': 'Method requires upgraded plan'}}),
    (401, 'Access denied'), (429, 'Rate limit'), (503, 'Temporary outage'),
    (302, 'Redirect'),
])
def test_http_failure_stops_after_one_charged_attempt(plan, confirmation, store, tmp_path, status, body):
    calls = []
    def handler(request):
        calls.append(request)
        if isinstance(body, dict):
            return httpx.Response(status, json=body)
        return httpx.Response(status, text=body, headers={'Location': 'https://example.invalid/forbidden'})
    result = run(plan, confirmation, store, tmp_path, handler)
    assert len(calls) == result['provider_requests'] == 1
    assert result['conservative_credits'] == 10
    assert result['state'] == 'STOPPED' and result['retries'] == 0
    assert result['quota_after']['used'] == 10 and result['quota_after']['reserved'] == 0
    assert result['B3'] == 'BLOCKED' and len(result['unexecuted_request_ids']) == 9


def test_rpc_denial_stops_no_fallback_or_purchase(plan, confirmation, store, tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': 1,
                                        'error': {'code': -32601, 'message': 'Method not permitted'}})
    result = run(plan, confirmation, store, tmp_path, handler)
    assert len(calls) == 1 and result['requests'][0]['state'] == 'RPC_ERROR'
    assert result['purchases'] is False and result['quota_reset'] is False


def test_transport_failure_conservatively_settles_no_retry(plan, confirmation, store, tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ConnectError('Request URL must not leak synthetic-offline-key', request=request)
    result = run(plan, confirmation, store, tmp_path, handler)
    assert len(calls) == 1 and result['quota_after']['used'] == 10
    assert 'synthetic-offline-key' not in json.dumps(result)
    assert result['state'] == 'STOPPED'


def test_reflected_credential_is_removed_from_all_receipts(plan, confirmation, store, tmp_path):
    def handler(request):
        return httpx.Response(403, text='api-key=synthetic-offline-key',
                              headers={'Date': 'synthetic-offline-key', 'Set-Cookie': 'sensitive-cookie'})
    result = run(plan, confirmation, store, tmp_path, handler)
    row = result['requests'][0]
    assert row['credential_redaction_applied'] is True
    assert 'set-cookie' not in row['response_headers']
    assert 'synthetic-offline-key' not in json.dumps(result)
    for path in (tmp_path / 'receipts').iterdir():
        raw = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
        assert b'synthetic-offline-key' not in raw


def test_successful_capped_plan_is_observation_not_b3(plan, confirmation, store, tmp_path):
    calls = []
    def handler(request):
        body = json.loads(request.content); calls.append(body)
        method = body['method']
        if method == 'getTransactionsForAddress':
            result = {'data': [], 'paginationToken': None}
        elif method == 'getTransaction':
            item = next(r for r in plan['requests'] if r['params'][0] == body['params'][0])
            path = probe.ROOT / 'evidence/runs/real-cache/archives' / (item['archived_control_hash'] + '.json.gz')
            archived = json.loads(gzip.decompress(path.read_bytes())); result = archived.get('result', archived)
        elif method == 'getTokenAccountsByOwner':
            result = {'context': {'slot': 999}, 'value': []}
        else:
            result = 1000
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': result})
    result = run(plan, confirmation, store, tmp_path, handler)
    assert len(calls) == result['provider_requests'] == 9
    assert result['conservative_credits'] == 63
    assert result['quota_after']['used'] == 63 and result['quota_after']['reserved'] == 0
    assert result['state'] == 'OBSERVED_IN_SCOPE' and result['B3'] == 'BLOCKED'
    assert result['requests'][2]['state'] == 'NOT_RUN'
    assert result['historical_owner_completeness'].startswith('INCONCLUSIVE')


def test_existing_probe_usage_is_not_reset_to_allow_more_calls(plan, confirmation, store, tmp_path):
    reserved = store.reserve('helius', 'prior-approved-probe', 95, confirmation['cycle_start'], 100)
    store.dispatch(reserved); store.settle(reserved)
    calls = []
    result = run(plan, confirmation, store, tmp_path,
                 lambda request: calls.append(request) or httpx.Response(200, json={}))
    assert not calls and result['provider_requests'] == 0 and result['state'] == 'BLOCKED'
    assert result['quota_before'] == result['quota_after']
    assert result['quota_after']['used'] == 95


def test_failed_pending_confirmation_does_not_dispatch(plan, confirmation, store, tmp_path):
    confirmation['remaining_credits'] = 0
    calls = []
    with pytest.raises(ValueError):
        run(plan, confirmation, store, tmp_path,
            lambda request: calls.append(request) or httpx.Response(200, json={}))
    assert not calls and not (tmp_path / 'receipts').exists()


def index_request(plan):
    return plan['requests'][0]


def test_index_cursor_must_be_explicit_not_inferred_from_empty_list(plan):
    with pytest.raises(ValueError, match='explicit cursor'):
        probe.validate_response({'jsonrpc': '2.0', 'id': 1, 'result': {'data': []}}, index_request(plan), 1, plan)


def test_boolean_response_id_cannot_match_integer_one(plan):
    with pytest.raises(ValueError, match='identity'):
        probe.validate_response({'jsonrpc': '2.0', 'id': True, 'result': {'data': [], 'paginationToken': None}}, index_request(plan), 1, plan)


def test_repeated_cursor_remains_a_gap(plan):
    with pytest.raises(ValueError, match='repeated'):
        probe.validate_response({'jsonrpc': '2.0', 'id': 1, 'result': {'data': [], 'paginationToken': '100:0'}}, index_request(plan), 1, plan, '100:0')


def test_unsupported_version_is_not_dropped_from_index_page(plan):
    request = index_request(plan)
    row = {'transaction': {'signatures': ['retained-signature']}, 'slot': 10,
           'transactionIndex': 0, 'blockTime': request['params'][1]['filters']['blockTime']['gte'],
           'version': 1, 'meta': {'err': None}}
    with pytest.raises(ValueError, match='version'):
        probe.validate_response({'jsonrpc': '2.0', 'id': 1, 'result': {'data': [row], 'paginationToken': None}}, request, 1, plan)


def test_response_bound_is_enforced_before_allocation_or_acceptance(plan):
    with pytest.raises(ValueError, match='100-row'):
        probe.validate_response({'jsonrpc': '2.0', 'id': 1, 'result': {'data': [{}] * 101, 'paginationToken': None}}, index_request(plan), 1, plan)
