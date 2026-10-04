"""Public sample budgets include failed attempts, restarts and token-control reads."""
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json

import httpx
import pytest

from scanner.providers import CapturedRPC, ProviderError
from scanner.screening_routes import PublicSampleRPC, collect_public_sample
from scanner.storage import Store, QuotaExceeded


class Native:
    calls = []
    fail = False

    def __init__(self, store, **kwargs):
        self.store = store

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def close(self):
        pass

    async def rpc(self, method, params):
        self.calls.append((method, deepcopy(params)))
        if self.fail:
            raise ProviderError('Development request failed after dispatch')
        if method == 'getSignaturesForAddress':
            return []
        return {'context': {'slot': 1}, 'value': None}

    async def rpc_capture(self, method, params):
        result = await self.rpc(method, params)
        return CapturedRPC(result, json.dumps({'method': method, 'params': params}).encode(), json.dumps(result).encode())


@pytest.fixture
def native(monkeypatch):
    Native.calls, Native.fail = [], False
    monkeypatch.setattr('scanner.observer.PublicRPC', Native)
    return Native


def scan(limit=2, addresses=None):
    return {'id': 'sample-budget', 'audit_addresses': addresses or ['first-wallet'],
            'limits': {'transaction_limit': 2, 'wallet_credit_limit': limit}, 'progress': {}, 'status': 'running'}


def test_failed_attempts_and_process_restart_preserve_exhausted_sample_budget(tmp_path, native):
    native.fail = True
    store = Store(tmp_path)
    selected = scan()

    async def never_build(*_):
        pytest.fail('No source transactions were collected')

    asyncio.run(collect_public_sample(store, selected, never_build, lambda: False))
    cp = store.get('public_sample_checkpoints', 'sample-budget:first-wallet')
    assert cp['requests_used'] == cp['credits'] == 1
    assert cp['tranche_request_limit'] == 2
    store.close()
    store = Store(tmp_path)
    asyncio.run(collect_public_sample(store, selected, never_build, lambda: False))
    asyncio.run(collect_public_sample(store, selected, never_build, lambda: False))
    cp = store.get('public_sample_checkpoints', 'sample-budget:first-wallet')
    assert cp['requests_used'] == 2 and len(native.calls) == 2
    assert 'explicit budgeted continuation' in cp['stop_reason']
    assert selected['progress']['credits'] == 2
    # A new client or merely increasing its constructor limit is not approval.
    async def blocked():
        async with PublicSampleRPC(store, 'sample-budget', 'first-wallet', max_requests=100) as rpc:
            with pytest.raises(QuotaExceeded):
                await rpc.rpc('getAccountInfo', ['mint', {}])
    asyncio.run(blocked())
    assert len(native.calls) == 2
    store.close()


def test_provider_failure_status_and_capture_stay_with_stopped_sample_without_entering_chain_records(tmp_path, native, monkeypatch):
    store = Store(tmp_path)
    selected = scan()

    async def limited(self, method, params):
        self.calls.append((method, deepcopy(params)))
        error = ProviderError('Public RPC rate limit (HTTP 429); collection paused without retry.', 429)
        error.evidence_hash = self.store.archive({'kind': 'development-http-failure', 'status': 429})
        raise error
    monkeypatch.setattr(native, 'rpc', limited)

    async def never_build(*_):
        pytest.fail('Failed reads cannot establish native source records')
    asyncio.run(collect_public_sample(store, selected, never_build, lambda: False))
    cp = store.get('public_sample_checkpoints', 'sample-budget:first-wallet')
    assert cp['provider_stop']['http_status'] == cp['provider_stop']['code'] == 429
    assert store.evidence(cp['provider_stop']['evidence_hash'])['status'] == 429
    assert cp['transactions'] == [] and cp['evidence'] == []
    assert cp['requests_used'] == 1 and len(cp['interruptions']) == 1
    assert 'HTTP 429' in cp['stop_reason']
    store.close()


def test_explicit_continuation_adds_only_its_persisted_allowance_and_mint_reads_share_it(tmp_path, native):
    store = Store(tmp_path)

    async def first():
        async with PublicSampleRPC(store, 'sample', 'wallet', max_requests=1) as rpc:
            await rpc.rpc('getSignaturesForAddress', ['wallet', {'limit': 1}])
        async with PublicSampleRPC(store, 'sample', 'wallet', max_requests=50) as mint:
            with pytest.raises(QuotaExceeded):
                await mint.rpc('getAccountInfo', ['mint', {}])
    asyncio.run(first())
    cp = store.get('public_sample_checkpoints', 'sample:wallet')
    cp['tranche_request_limit'] += 1
    store.put('public_sample_checkpoints', 'sample:wallet', cp)

    async def continued():
        async with PublicSampleRPC(store, 'sample', 'wallet') as mint:
            captured = await mint.rpc_capture('getAccountInfo', ['mint', {}])
            assert captured.result['value'] is None
            with pytest.raises(QuotaExceeded):
                await mint.rpc('getAccountInfo', ['second-mint', {}])
    asyncio.run(continued())
    cp = store.get('public_sample_checkpoints', 'sample:wallet')
    assert cp['requests_used'] == cp['credits'] == cp['tranche_request_limit'] == 2
    assert [method for method, _ in native.calls] == ['getSignaturesForAddress', 'getAccountInfo']
    store.close()


def test_pre_dispatch_ledger_retains_attempt_across_cancellation_and_checkpoint_loss(tmp_path, native):
    store = Store(tmp_path)
    original = native.rpc

    async def interrupted(self, method, params):
        self.calls.append((method, deepcopy(params)))
        raise asyncio.CancelledError()
    native.rpc = interrupted
    try:
        async def request():
            async with PublicSampleRPC(store, 'interrupted', 'wallet', max_requests=1) as rpc:
                await rpc.rpc('getAccountInfo', ['mint', {}])
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(request())
    finally:
        native.rpc = original
    store.delete('public_sample_checkpoints', 'interrupted:wallet')
    store.close()
    store = Store(tmp_path)

    async def restored():
        async with PublicSampleRPC(store, 'interrupted', 'wallet', max_requests=1) as rpc:
            with pytest.raises(QuotaExceeded):
                await rpc.rpc('getAccountInfo', ['mint', {}])
    asyncio.run(restored())
    assert store.get('public_sample_checkpoints', 'interrupted:wallet')['requests_used'] == 1
    assert len(native.calls) == 1
    store.close()


def test_multiwallet_sample_finishes_each_wallet_before_publishing_paused_status(tmp_path, native):
    store = Store(tmp_path)
    selected = scan(addresses=['first-wallet', 'second-wallet'])
    store.put('scans', selected['id'], selected)

    async def build(*_):
        pass
    asyncio.run(collect_public_sample(store, selected, build,
        lambda: store.get('scans', selected['id'])['status'] == 'paused'))
    assert selected['status'] == 'completed'
    assert len(native.calls) == 2
    assert selected['progress']['credits'] == 2
    assert all(store.get('public_sample_checkpoints', 'sample-budget:' + address)['terminal']
               for address in selected['audit_addresses'])
    store.close()


def test_owner_pause_during_report_build_is_preserved_before_next_wallet(tmp_path, native, monkeypatch):
    store = Store(tmp_path)
    selected = scan(addresses=['first-wallet', 'second-wallet'])
    selected['limits']['transaction_limit'] = 1
    store.put('scans', selected['id'], selected)

    async def response(self, method, params):
        self.calls.append((method, deepcopy(params)))
        return [{'signature': 'development-signature'}] if method == 'getSignaturesForAddress' else {'slot': 1}
    monkeypatch.setattr(native, 'rpc', response)

    async def build(*_):
        current = store.get('scans', selected['id'])
        current['status'] = 'paused'
        store.put('scans', selected['id'], current)
    asyncio.run(collect_public_sample(store, selected, build,
        lambda: store.get('scans', selected['id'])['status'] == 'paused'))
    assert selected['status'] == 'paused'
    assert selected['reason'].startswith('Paused by owner')
    assert selected['progress']['wallets_completed'] == 1
    assert store.get('public_sample_checkpoints', 'sample-budget:second-wallet') is None
    store.close()


def test_multiwallet_continuation_only_spends_selected_wallet_checkpoint(tmp_path, native):
    store = Store(tmp_path)
    selected = scan(limit=2, addresses=['first-wallet', 'second-wallet'])
    selected['public_sample_targets'] = ['first-wallet']
    first = {**PublicSampleRPC._empty(), 'requests_used': 1, 'credits': 1, 'tranche_request_limit': 2,
             'before': 'first-cursor', 'transactions': [{'signature': 'first-record', 'raw': {'slot': 1},
                                                        'evidence_hash': store.archive({'slot': 1})}]}
    second = {**PublicSampleRPC._empty(), 'requests_used': 3, 'credits': 3, 'tranche_request_limit': 3,
              'before': 'second-cursor', 'pending': ['untouched-signature'],
              'evidence': [{'kind': 'preserved-source', 'hash': store.archive({'untouched': True})}]}
    store.put('public_sample_checkpoints', 'sample-budget:first-wallet', first)
    store.put('public_sample_checkpoints', 'sample-budget:second-wallet', second)
    built = []

    async def build(_, address, collected):
        built.append((address, deepcopy(collected)))
    asyncio.run(collect_public_sample(store, selected, build, lambda: False))
    assert native.calls == [('getSignaturesForAddress', ['first-wallet', {'limit': 1, 'commitment': 'finalized', 'before': 'first-cursor'}])]
    assert [address for address, _ in built] == ['first-wallet']
    assert selected['audit_addresses'] == ['first-wallet', 'second-wallet']
    assert store.get('public_sample_checkpoints', 'sample-budget:second-wallet') == second
    assert store.get('public_sample_checkpoints', 'sample-budget:first-wallet')['requests_used'] == 2
    assert store.usage('public-wallet-sample', 'sample-budget:second-wallet', 3)['used'] == 0
    store.close()


def test_shared_public_daily_cap_is_still_enforced_without_network_dispatch(tmp_path, monkeypatch):
    store = Store(tmp_path)
    cycle = datetime.now(timezone.utc).date().isoformat()
    reservation = store.reserve('solana-public', 'retained-day-usage', 1000, cycle, 1000)
    store.dispatch(reservation)
    store.settle(reservation, charge=True)
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': 1, 'result': {}})

    async def read():
        async with PublicSampleRPC(store, 'daily-capped', 'wallet', max_requests=10,
                                   transport=httpx.MockTransport(response)) as rpc:
            with pytest.raises(QuotaExceeded):
                await rpc.rpc('getAccountInfo', ['mint', {}])
    asyncio.run(read())
    assert requests == []
    assert store.usage('solana-public', cycle, 1000)['used'] == 1000
    assert store.get('public_sample_checkpoints', 'daily-capped:wallet')['requests_used'] == 1
    store.close()
