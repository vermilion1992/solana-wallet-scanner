"""HTTP screening workflow and durable bounded continuation, synthetic controls."""
import asyncio
from copy import deepcopy
import json
import sys
import time
from types import SimpleNamespace
import pytest

from fastapi.testclient import TestClient

from scanner.app import create_app
from scanner.providers import CapturedRPC
from scanner.storage import Store
from scanner.screening_routes import collect_public_sample, saved_identity
from tests.test_discovery import WALLET, SIGNATURE, transaction, SYSTEM_PROGRAM


class Native:
    def __init__(self, store, **kwargs):
        self.calls = []
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        pass
    async def rpc(self, method, params):
        if method == 'getSignaturesForAddress':
            return [] if params[1].get('before') else [{'signature': SIGNATURE}]
        if method == 'getTransaction':
            raw = transaction()
            raw['meta'].update(fee=5000, preBalances=[1000000, 2000], postBalances=[995000, 2000], innerInstructions=[], logMessages=[])
            return raw
        if method == 'getAccountInfo':
            return {'context': {'slot': 11}, 'value': {'owner': SYSTEM_PROGRAM, 'executable': False}}
        raise AssertionError(method)
    async def rpc_capture(self, method, params):
        result = await self.rpc(method, params)
        request = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}
        return CapturedRPC(result, json.dumps(request).encode(), json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': result}).encode())


def test_import_identity_sample_screen_is_saved_without_strict_promotion(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(get_keyring=lambda: object()))
    monkeypatch.setattr('scanner.observer.PublicRPC', Native)
    app = create_app(tmp_path, 'private-token')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        assert client.post('/api/screenings', json={'report_id': 'anything'}).status_code == 401
        csrf = client.get('/api/bootstrap', headers={'x-launch-token': 'private-token'}).json()['csrf']
        client.headers['x-csrf-token'] = csrf
        imported = client.post('/api/discovery/import', json={'addresses': [WALLET]}).json()
        cohort = imported['cohort_id']
        assert client.post(f'/api/discovery/{cohort}/audit', json={'addresses': [WALLET]}).status_code == 422
        assert client.post(f'/api/discovery/{cohort}/identity', json={'addresses': [WALLET], 'identity_verified': True}).status_code == 422
        checked = client.post(f'/api/discovery/{cohort}/identity', json={'addresses': [WALLET]})
        assert checked.status_code == 200, checked.text
        assert checked.json()['checked'][0]['status'] == 'candidate'
        assert saved_identity(app.state.store, WALLET)['state'] == 'PASS'
        audited = client.post(f'/api/discovery/{cohort}/audit', json={'addresses': [WALLET]})
        assert audited.status_code == 200, audited.text
        assert audited.json()['budget_mode'] == 'public-sample'
        reports = []
        for _ in range(100):
            reports = client.get('/api/state?report_view=summary').json()['reports']
            if reports:
                break
            time.sleep(.05)
        assert reports, app.state.store.list('scans')
        report = reports[0]
        result = client.post('/api/screenings', json={'report_id': report['id']})
        assert result.status_code == 200, result.text
        assessment = result.json()
        assert assessment['result'] == 'insufficient_evidence'
        assert assessment['strict_qualification']['qualified'] is False
        exported = client.get(f"/api/screenings/{assessment['id']}/export")
        assert exported.json() == assessment
        assert app.state.store.get('reports', report['id'])['id'] == report['id']
        old = deepcopy(assessment)
        client.put('/api/settings', json={'preset': {'min_profit_sol': '6'}})
        assert client.get(f"/api/screenings/{assessment['id']}").json() == old
        evidence = saved_identity(app.state.store, WALLET)['evidence'][0]
        (app.state.store.path / 'evidence' / f'{evidence}.json.gz').unlink()
        assert saved_identity(app.state.store, WALLET)['state'] == 'UNKNOWN'
        assert client.post('/api/observations', json={'screening_id': assessment['id']}).status_code == 409


def test_public_sample_continuation_retains_cursor_sources_and_limits(tmp_path, monkeypatch):
    monkeypatch.setattr('scanner.observer.PublicRPC', Native)
    store = Store(tmp_path)
    scan = {'id': 'sample', 'audit_addresses': [WALLET], 'limits': {'transaction_limit': 1, 'wallet_credit_limit': 5},
            'progress': {}, 'window': {'start': '2026-01-01T00:00:00+00:00', 'end': '2026-12-01T00:00:00+00:00'}}
    built = []
    async def build(scan, address, collected):
        built.append(deepcopy(collected))
    asyncio.run(collect_public_sample(store, scan, build, lambda: False))
    assert scan['status'] == 'paused'
    assert len(built[0]['transactions']) == 1
    original = deepcopy(built[0]['transactions'])
    scan['limits']['transaction_limit'] = 2
    asyncio.run(collect_public_sample(store, scan, build, lambda: False))
    assert scan['status'] == 'completed'
    assert built[-1]['transactions'] == original
    assert built[-1]['coverage']['historical_ownership_verified'] is False
    assert built[-1]['coverage']['collection_stop_reason'].startswith('Public wallet-address query ended')
    store.close()


def test_public_discovery_recheck_preserves_sampled_signature_association(tmp_path, monkeypatch):
    from tests.test_discovery_plan_views import identity_cohort
    from scanner.screening_routes import check_cohort_identity
    monkeypatch.setattr('scanner.observer.PublicRPC', Native)
    store = Store(tmp_path)
    cohort, _ = identity_cohort(store)
    assert saved_identity(store, WALLET)['state'] == 'PASS'
    checked = asyncio.run(check_cohort_identity(store, cohort, [WALLET]))
    assert checked[0]['status'] == 'candidate'
    assert saved_identity(store, WALLET)['state'] == 'PASS'
    assert store.get('discovery_cohorts', cohort['id'])['candidates'][0]['validation']['signature'] == SIGNATURE
    store.close()


def test_cross_cohort_same_slot_account_conflict_revokes_identity(tmp_path):
    from tests.test_discovery_plan_views import identity_cohort
    from tests.test_discovery import MINT
    store = Store(tmp_path)
    cohort, hashes = identity_cohort(store)
    assert saved_identity(store, WALLET)['state'] == 'PASS'
    conflict = deepcopy(cohort)
    conflict['id'] = 'c' * 32
    payload = store.evidence(hashes['account'])
    payload['result']['value']['owner'] = MINT
    digest = store.archive(payload)
    conflict['candidates'][0]['validation']['account_evidence_hash'] = digest
    conflict['candidates'][0]['evidence'] = [digest if h == hashes['account'] else h for h in conflict['candidates'][0]['evidence']]
    conflict['evidence'] = [{**row, 'hash': digest} if row['hash'] == hashes['account'] else row for row in conflict['evidence']]
    store.put('discovery_cohorts', conflict['id'], conflict)
    assert saved_identity(store, WALLET)['state'] == 'UNKNOWN'
    latest = deepcopy(cohort)
    latest['id'] = 'd' * 32
    fresh = store.evidence(hashes['account'])
    fresh['result']['context']['slot'] = 12
    newest = store.archive(fresh)
    latest['candidates'][0]['validation']['account_evidence_hash'] = newest
    latest['candidates'][0]['evidence'].append(newest)
    latest['evidence'].append({'kind': 'wallet-account-info', 'hash': newest})
    store.put('discovery_cohorts', latest['id'], latest)
    assert saved_identity(store, WALLET)['state'] == 'PASS'
    path = store.path / 'evidence' / (digest + '.json.gz')
    path.unlink()
    assert saved_identity(store, WALLET)['state'] == 'UNKNOWN'
    store.close()


def test_still_linked_older_account_is_dated_fact_after_same_cohort_recheck(tmp_path):
    from tests.test_discovery_plan_views import identity_cohort
    from tests.test_discovery import MINT
    store = Store(tmp_path)
    cohort, hashes = identity_cohort(store)
    older = store.evidence(hashes['account'])
    older['result']['value']['owner'] = MINT
    old_hash = store.archive(older)
    newer = store.evidence(hashes['account'])
    newer['result']['context']['slot'] = 12
    new_hash = store.archive(newer)
    cohort['candidates'][0]['validation']['account_evidence_hash'] = new_hash
    cohort['candidates'][0]['evidence'] += [old_hash, new_hash]
    cohort['evidence'] += [{'kind': 'wallet-account-info', 'hash': h} for h in [old_hash, new_hash]]
    store.put('discovery_cohorts', cohort['id'], cohort)
    identity = saved_identity(store, WALLET)
    assert identity['state'] == 'PASS'
    assert old_hash in identity['evidence'] and new_hash in identity['evidence']
    store.close()


@pytest.mark.parametrize('owner', [None, {}, [], 123])
def test_malformed_account_owner_remains_unknown(tmp_path, owner):
    from tests.test_discovery_plan_views import identity_cohort
    store = Store(tmp_path)
    cohort, hashes = identity_cohort(store)
    account = store.evidence(hashes['account'])
    account['result']['value']['owner'] = owner
    digest = store.archive(account)
    cohort['candidates'][0]['validation']['account_evidence_hash'] = digest
    cohort['candidates'][0]['evidence'].append(digest)
    cohort['evidence'].append({'kind': 'wallet-account-info', 'hash': digest})
    store.put('discovery_cohorts', cohort['id'], cohort)
    assert saved_identity(store, WALLET)['state'] == 'UNKNOWN'
    store.close()


def test_provider_429_recheck_keeps_dated_identity_proofs_without_claiming_new_success(tmp_path, monkeypatch):
    from scanner.providers import ProviderError
    from scanner.screening_routes import check_cohort_identity
    from tests.test_discovery_plan_views import identity_cohort
    class RateLimited(Native):
        async def rpc_capture(self, method, params):
            raise ProviderError('Public RPC request unavailable', 429)
    monkeypatch.setattr('scanner.observer.PublicRPC', RateLimited)
    store = Store(tmp_path)
    cohort, _ = identity_cohort(store)
    original = deepcopy(cohort['candidates'][0]['validation'])
    checked = asyncio.run(check_cohort_identity(store, cohort, [WALLET]))
    assert checked[0]['status'] == 'candidate'
    candidate = store.get('discovery_cohorts', cohort['id'])['candidates'][0]
    assert candidate['validation'] == original
    assert candidate['identity_recheck']['state'] == 'interrupted'
    assert candidate['identity_recheck']['prior_evidence_retained'] is True
    assert candidate['identity_recheck']['provider_stop']['http_status'] == 429
    assert 'Prior dated identity evidence' in candidate['reason']
    assert saved_identity(store, WALLET)['state'] == 'PASS'
    store.close()


def test_recheck_failure_cannot_hide_new_native_contradiction(tmp_path, monkeypatch):
    from scanner.providers import ProviderError
    from scanner.screening_routes import check_cohort_identity
    from tests.test_discovery_plan_views import identity_cohort
    class ChangedNative(Native):
        async def rpc(self, method, params):
            if method == 'getAccountInfo':
                raise ProviderError('Public RPC request unavailable', 429)
            raw = await super().rpc(method, params)
            if method == 'getTransaction':
                raw['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '25'
            return raw
    monkeypatch.setattr('scanner.observer.PublicRPC', ChangedNative)
    store = Store(tmp_path)
    cohort, hashes = identity_cohort(store)
    asyncio.run(check_cohort_identity(store, cohort, [WALLET]))
    assert saved_identity(store, WALLET)['state'] == 'UNKNOWN'
    candidate = store.get('discovery_cohorts', cohort['id'])['candidates'][0]
    assert candidate['validation']['transaction_evidence_hash'] == hashes['native']
    alternatives = [link['hash'] for link in cohort['evidence'] if link.get('kind') == 'transaction']
    assert len(set(alternatives)) == 2
    assert candidate['identity_recheck']['state'] == 'interrupted'
    store.close()


@pytest.mark.parametrize('account, expected', [
    ({'context': {'slot': 11}, 'value': None}, 'unresolved'),
    ({'context': {'slot': 11}, 'value': {'owner': SYSTEM_PROGRAM, 'executable': 'false'}}, 'unresolved'),
    ({'context': {'slot': 11}, 'value': {'owner': SYSTEM_PROGRAM, 'executable': True}}, 'rejected'),
])
def test_identity_unavailable_account_is_unknown_and_observed_executable_account_is_excluded(tmp_path, monkeypatch, account, expected):
    from scanner.candidate_import import import_candidate_cohort
    from scanner.screening_routes import check_cohort_identity
    class CurrentAccount(Native):
        async def rpc(self, method, params):
            return deepcopy(account) if method == 'getAccountInfo' else await super().rpc(method, params)
    monkeypatch.setattr('scanner.observer.PublicRPC', CurrentAccount)
    store = Store(tmp_path)
    cohort = import_candidate_cohort([WALLET])
    checked = asyncio.run(check_cohort_identity(store, cohort, [WALLET]))
    assert checked[0]['status'] == expected
    assert cohort['candidates'][0]['validation']['identity_verified'] is False
    assert saved_identity(store, WALLET)['state'] != 'PASS'
    store.close()


@pytest.mark.parametrize('source', ['financial', 'identity', 'collection-stop'])
def test_current_screening_view_rechecks_all_citations_consistently_without_rewriting_saved_snapshot(tmp_path, monkeypatch, source):
    from tests.test_discovery_plan_views import identity_cohort
    from tests.test_screening import sample, HASH
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(get_keyring=lambda: object()))
    app = create_app(tmp_path, 'source-view-token')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        client.headers['x-csrf-token'] = client.get('/api/bootstrap', headers={'x-launch-token': 'source-view-token'}).json()['csrf']
        cohort, hashes = identity_cohort(app.state.store)
        report = sample()
        digest = app.state.store.archive({'kind': 'synthetic-screening-mechanics-source', 'events': report['events']})
        report = json.loads(json.dumps(report).replace(HASH, digest))
        report['address'] = WALLET
        stop_hash = app.state.store.archive({'kind': 'synthetic-provider-stop', 'http_status': 429})
        report['coverage']['provider_stop'] = {'code': 429, 'http_status': 429, 'evidence_hash': stop_hash}
        app.state.store.put('reports', report['id'], report)
        created = client.post('/api/screenings', json={'report_id': report['id']}).json()
        identifier = created['id']
        original = deepcopy(app.state.store.get('screenings', identifier))
        assert created['result'] == created['current_result'] == 'worth_observing'
        assert created['current_eligibility']['can_start_observation'] is True
        removed = digest if source == 'financial' else hashes['native'] if source == 'identity' else stop_hash
        path = app.state.store.path / 'evidence' / (removed + '.json.gz')
        raw_bytes = path.read_bytes()
        path.unlink()

        direct = client.get('/api/screenings/' + identifier).json()
        listed = client.get('/api/screenings').json()[0]
        state = client.get('/api/state?report_view=summary').json()['screenings'][0]
        exported = client.get('/api/screenings/' + identifier + '/export').json()
        assert direct == listed == state == exported
        assert direct['result'] == original['result'] == 'worth_observing'
        assert direct['preset_snapshot'] == original['preset_snapshot']
        assert direct['source_availability']['state'] == 'PASS'
        assert direct['current_source_availability'] == {'state': 'UNKNOWN', 'missing': [removed]}
        assert direct['current_result'] == 'insufficient_evidence'
        assert direct['current_eligibility']['can_start_observation'] is False
        assert app.state.store.get('screenings', identifier) == original
        assert client.post('/api/observations', json={'screening_id': identifier}).status_code == 409
        path.write_bytes(raw_bytes)
        assert client.get('/api/screenings/' + identifier).json() == created
        assert app.state.store.get('screenings', identifier) == original


def test_current_identity_contradiction_revokes_current_screening_eligibility_with_readable_sources(tmp_path, monkeypatch):
    from tests.test_discovery import MINT
    from tests.test_discovery_plan_views import identity_cohort
    from tests.test_screening import sample, HASH
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(get_keyring=lambda: object()))
    app = create_app(tmp_path, 'identity-view-token')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        client.headers['x-csrf-token'] = client.get('/api/bootstrap', headers={'x-launch-token': 'identity-view-token'}).json()['csrf']
        cohort, hashes = identity_cohort(app.state.store)
        report = sample()
        digest = app.state.store.archive({'kind': 'synthetic-current-identity-screening-source', 'events': report['events']})
        report = json.loads(json.dumps(report).replace(HASH, digest))
        report['address'] = WALLET
        app.state.store.put('reports', report['id'], report)
        frozen = client.post('/api/screenings', json={'report_id': report['id']}).json()
        account = app.state.store.evidence(hashes['account'])
        account['result']['value']['owner'] = MINT
        alternative = app.state.store.archive(account)
        cohort['evidence'].append({'kind': 'wallet-account', 'hash': alternative})
        app.state.store.put('discovery_cohorts', cohort['id'], cohort)
        current = client.get('/api/screenings/' + frozen['id']).json()
        assert current['result'] == frozen['result'] == 'worth_observing'
        assert current['current_source_availability']['state'] == 'PASS'
        assert current['current_identity']['state'] == 'UNKNOWN'
        assert current['current_result'] == 'insufficient_evidence'
        assert current['current_eligibility']['can_start_observation'] is False
        assert client.post('/api/observations', json={'screening_id': frozen['id']}).status_code == 409
