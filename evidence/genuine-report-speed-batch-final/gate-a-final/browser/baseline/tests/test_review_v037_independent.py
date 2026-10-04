"""Generalized offline role/availability controls for R12; never mainnet inputs."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from scanner.app import create_app
from scanner.config import STRICT
from scanner.history_evidence import derive_history_evidence
from scanner.position_evidence import derive_position_evidence
from scanner.providers import TOKEN_PROGRAM
from scanner.report_rebuild import freeze_report_inputs
from tests.review_v037.review_helpers import builder, damage, evidence_file, history, pb
from tests.test_discovery_integration_review import isolate_credentials_and_transport

ROLES = ('transaction', 'signature-page', 'block-order', 'snapshot-slot', 'owned-accounts', 'native-balance')
STATES = ('agreeing', 'conflicting', 'missing', 'corrupt', 'malformed', 'unsupported', 'over-budget', 'restored')


def role_source(case, role, state):
    # Independent endpoint projection is intentionally execution-dependent.
    case.raws[0]['meta']['postBalances'][0] -= 1000
    case.raws[0]['meta']['postBalances'][3] += 1000
    case.seed()
    signature = case.records[0]['signature']
    if role == 'transaction':
        payload = deepcopy(case.raws[0])
        payload['synthetic_annotation'] = 'independent R12 role matrix'
    elif role == 'signature-page':
        payload = {'method': 'getSignaturesForAddress', 'address': pb.WSOL_ACCOUNT,
                   'params': {'limit': 100, 'commitment': 'finalized', 'minContextSlot': 1000},
                   'result': [pb.entry(signature, case.raws[0])]}
    elif role == 'block-order':
        payload = {'method': 'getBlock', 'slot': 100,
                   'result': {'signatures': [signature], 'blockTime': pb.START + 3600}}
    elif role == 'snapshot-slot':
        payload = {'method': 'getSlot', 'commitment': 'finalized', 'result': 1000,
                   'synthetic_annotation': 'additional snapshot receipt'}
    elif role == 'owned-accounts':
        payload = {'method': 'getTokenAccountsByOwner', 'owner': pb.WALLET, 'program': TOKEN_PROGRAM,
                   'result': {'context': {'slot': 1000}, 'value': []}}
    else:
        payload = {'method': 'getBalance', 'address': pb.WALLET,
                   'result': {'context': {'slot': 1000}, 'value': 42}}
    if state == 'conflicting':
        if role == 'transaction':
            payload['meta']['preTokenBalances'][0]['uiTokenAmount']['amount'] = '200'
            payload['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '300'
        elif role == 'signature-page':
            payload['result'][0]['err'] = {'InstructionError': [0, 'InvalidArgument']}
        elif role == 'block-order':
            payload['result']['blockTime'] += 1
        elif role == 'snapshot-slot':
            payload['result'] = 999
        elif role == 'owned-accounts':
            payload['owner'] = pb.address(70)
        else:
            payload['address'] = pb.address(70)
    elif state == 'malformed':
        payload = None
    elif state == 'unsupported':
        if role == 'transaction':
            payload['transaction'] = {'signatures': ['different-synthetic-signature']}
        else:
            payload['method'] = 'unsupportedSyntheticMethod'
    digest = case.store.archive(payload)
    ref = {'kind': role, 'hash': digest}
    if role == 'transaction':
        ref['signature'] = signature
    case.cp['evidence'].append(ref)
    if state == 'over-budget':
        # These are declared unavailable local links, never fabricated archives.
        # The actual fixed distinct-hash budget admits no archive prefix.
        case.cp['evidence'].extend({'kind': 'transaction', 'hash': hashlib.sha256(f'R12-unavailable-{i}'.encode()).hexdigest(),
                                   'signature': 'synthetic-unavailable'} for i in range(40_000))
    case.persist()
    return ref


def mutate_available_archive(store, digest, state):
    path = store.path / 'evidence' / f'{digest}.json.gz'
    if state in ('missing', 'corrupt'):
        damage(path, state)
    elif state == 'restored':
        original = path.read_bytes()
        damage(path, 'corrupt')
        path.write_bytes(original)
        assert path.read_bytes() == original


def verify_result(role, state, ref, position, h):
    holds = state in ('agreeing', 'restored') or role in ('owned-accounts', 'native-balance') and state != 'over-budget'
    assert position['counts']['known_closed'] == int(holds), (role, state, position)
    assert position['positions'][0]['hold_hours']['value'] == ('6' if holds else None)
    assert set(h['evidence_gates'].values()) == {'UNKNOWN'}
    index = h['source_consistency']['source_set']
    assert index['complete'] is (state != 'over-budget')
    contents = h['source_consistency']['archive_contents']
    row = next(row for row in contents['receipts'] if row['kind'] == role and row['hash'] == ref['hash'])
    if state in ('missing', 'corrupt', 'malformed', 'unsupported', 'over-budget') or role in ('snapshot-slot', 'owned-accounts', 'native-balance') and state == 'conflicting':
        assert row['state'] == 'UNKNOWN'
        assert row['hash'] in row['evidence']
        assert row['recovery']['provider_requests'] == 0
        assert contents['state'] == 'UNKNOWN'
    else:
        assert row['state'] == 'PASS'
    native = h['native_address_metrics']['observed']
    fees = not (state == 'over-budget' or role == 'transaction' and state in ('missing', 'corrupt', 'malformed', 'unsupported'))
    delta = fees and not (role == 'signature-page' and state not in ('agreeing', 'restored'))
    assert native['wallet_network_fees_sol']['value'] == ('0.000015' if fees else None), (role, state, native)
    assert native['native_wallet_delta_sol']['value'] == ('-0.000016' if delta else None), (role, state, native)
    if role in ('signature-page', 'block-order', 'snapshot-slot') and state in ('missing', 'corrupt', 'malformed', 'unsupported'):
        assert ref['hash'] in position['positions'][0]['sources']
    if state == 'over-budget':
        assert index['inspected_hash_count'] == 0
        assert index['unique_hash_count'] > 40_000
        assert index['omitted_hash_count'] == index['unique_hash_count']


@pytest.mark.parametrize('role', ROLES)
@pytest.mark.parametrize('state', STATES)
def test_role_source_state_matrix_direct(builder, role, state):
    ref = role_source(builder, role, state)
    mutate_available_archive(builder.store, ref['hash'], state)
    verify_result(role, state, ref, builder.derive(), history(builder))
    assert ref in builder.cp['evidence']


def seed_actual_report(case, store, role, state):
    checkpoint = deepcopy(case.cp)
    for ref in checkpoint['evidence']:
        path = evidence_file(case, ref['hash'])
        if path.is_file():
            assert store.archive(case.store.evidence(ref['hash'])) == ref['hash']
    key = hashlib.sha256(f'{pb.WALLET}:{pb.START}:{pb.END}'.encode()).hexdigest()
    store.put('collector_checkpoints', key, checkpoint)
    window = {key: datetime.fromtimestamp(value, timezone.utc).isoformat() for key, value in pb.WINDOW.items()}
    collected = {'transactions': case.records, 'checkpoint': checkpoint, 'evidence': checkpoint['evidence'],
                 'snapshot': checkpoint['snapshot'], 'coverage': {'status': 'partial'}}
    original = {'id': f'synthetic-R12-{role}-{state}', 'scan_id': 'synthetic-R12-scan', 'source': 'live', 'address': pb.WALLET,
                'created_at': '2026-10-03T00:00:00+00:00', 'window': window, 'preset': dict(STRICT),
                'methodology': 'fifo-v3', 'metrics': {}, 'checks': [], 'policy': 'UNRESOLVED',
                'evidence_status': 'partial', 'coverage': {}, 'token_risk': [], 'evidence': checkpoint['evidence'],
                'collection_input_hash': freeze_report_inputs(store, pb.WALLET, window, collected)}
    store.put('reports', original['id'], original)
    store.put('scans', original['scan_id'], {'id': original['scan_id'], 'status': 'paused',
              'audit_addresses': [pb.WALLET], 'window': window, 'preset': dict(STRICT), 'budget_mode': 'setup-pilot'})
    return original, checkpoint


@pytest.mark.parametrize('role', ROLES)
@pytest.mark.parametrize('state', STATES)
def test_role_source_state_matrix_actual_rebuild(builder, role, state, tmp_path, monkeypatch):
    ref = role_source(builder, role, state)
    calls = {'provider': 0, 'credential': 0}
    monkeypatch.delenv('HELIUS_API_KEY', raising=False)
    def deny_credential(*args, **kwargs):
        calls['credential'] += 1
        raise AssertionError('No credential reads in R12 acceptance')
    async def deny_provider(*args, **kwargs):
        calls['provider'] += 1
        raise AssertionError('No provider requests in R12 acceptance')
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(get_keyring=lambda: object(), get_password=deny_credential))
    monkeypatch.setattr(httpx.AsyncClient, 'request', deny_provider)
    app = create_app(tmp_path / 'app', 'synthetic-local-token')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        bootstrap = client.get('/api/bootstrap', headers={'x-launch-token': 'synthetic-local-token'})
        client.headers['x-csrf-token'] = bootstrap.json()['csrf']
        store = app.state.store
        original, checkpoint = seed_actual_report(builder, store, role, state)
        usage = client.get('/api/state').json()['usage']
        mutate_available_archive(store, ref['hash'], state)
        response = client.post('/api/reports/' + original['id'] + '/rebuild')
        if role == 'block-order' and state in ('missing', 'corrupt', 'malformed', 'unsupported'):
            # Preserve the existing safe loader policy for invalid block order.
            assert response.status_code == 409
            assert response.json()['detail'] == 'Archived block ordering is invalid'
            assert store.get('reports', original['id']) == original
            assert len(store.list('reports')) == 1
            assert client.get('/api/state').json()['usage'] == usage
            assert calls == {'provider': 0, 'credential': 0}
            return
        assert response.status_code == 200, response.text
        child = client.get('/api/reports/' + response.json()['report_id']).json()
        assert child['id'] != original['id']
        assert store.get('reports', original['id']) == original
        assert client.get('/api/state').json()['usage'] == usage
        frozen = store.evidence(child['collection_input_hash'])
        assert frozen['evidence'] == frozen['checkpoint']['evidence'] == checkpoint['evidence']
        assert child['qualification']['qualified'] is False and child['policy'] == 'UNRESOLVED'
        verify_result(role, state, ref, child['coverage']['position_evidence'], child['coverage']['history_evidence'])
    assert calls == {'provider': 0, 'credential': 0}


@pytest.mark.parametrize('field', ['err', 'blockTime', 'confirmationStatus'])
def test_partial_page_retains_validated_signature_scope_and_failed_hash(builder, field):
    ref = role_source(builder, 'signature-page', 'agreeing')
    payload = builder.store.evidence(ref['hash'])
    del payload['result'][0][field]
    digest = builder.store.archive(payload)
    builder.cp['evidence'][-1]['hash'] = digest
    builder.persist()
    h = history(builder)
    row = next(row for row in h['source_consistency']['archive_contents']['receipts'] if row['hash'] == digest)
    assert row['state'] == 'UNKNOWN'
    assert row['scope']['signatures'] == ['synthetic-buy']
    assert builder.derive()['counts']['known_closed'] == 0
    assert digest in builder.derive()['positions'][0]['sources']


def test_role_valid_disjoint_block_preserves_unrelated_hold_when_order_contents_fail(builder):
    payload = {'method': 'getBlock', 'slot': 900, 'result': None}
    digest = builder.store.archive(payload)
    builder.cp['evidence'].append({'kind': 'block-order', 'hash': digest})
    builder.persist()
    h = history(builder)
    assert h['source_consistency']['archive_contents']['state'] == 'UNKNOWN'
    assert builder.derive()['positions'][0]['hold_hours']['value'] == '6'


def test_untrusted_reference_account_hint_cannot_exclude_missing_page(builder):
    payload = {'method': 'getSignaturesForAddress', 'address': pb.WSOL_ACCOUNT,
               'params': {'limit': 100, 'commitment': 'finalized', 'minContextSlot': 1000}, 'result': []}
    digest = builder.store.archive(payload)
    builder.cp['evidence'].append({'kind': 'signature-page', 'hash': digest, 'account': pb.address(70)})
    builder.persist()
    evidence_file(builder, digest).unlink()
    h = history(builder)
    row = next(row for row in h['source_consistency']['archive_contents']['receipts'] if row['hash'] == digest)
    assert row['scope']['account'] is None and row['scope']['signatures'] is None
    assert builder.derive()['counts']['known_closed'] == 0


def test_missing_wallet_page_scope_requires_matching_canonical_request_preimage(builder):
    digest = builder.pages[pb.WALLET][0]
    evidence_file(builder, digest).unlink()
    h = history(builder)
    row = next(row for row in h['source_consistency']['archive_contents']['receipts'] if row['hash'] == digest)
    assert row['state'] == 'UNKNOWN' and row['read_state'] == 'missing'
    assert row['scope']['account'] == pb.WALLET
    assert row['scope_proof']['source_hash'] == builder.pages[pb.ACCOUNT][0]
    candidate = {**builder.store.evidence(row['scope_proof']['source_hash']), 'address': pb.WALLET}
    import json
    assert hashlib.sha256(json.dumps(candidate, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()).hexdigest() == digest
    assert builder.derive()['positions'][0]['hold_hours']['value'] == '6'
    wallet_chain = next(row for row in h['paging']['accounts'] if row['address'] == pb.WALLET)
    assert wallet_chain['chain']['state'] == 'UNKNOWN'
    assert h['paging']['wallet_address_intervals']['report_period']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('digest', [None, 'not-a-digest'])
def test_unassignable_page_digest_retains_typed_unknown_without_crashing(builder, digest):
    builder.cp['evidence'].append({'kind': 'signature-page', 'hash': digest})
    builder.persist()
    h = history(builder)
    assert h['source_consistency']['source_set']['invalid_authenticated_link_count'] == 1
    assert h['source_consistency']['source_set']['complete'] is False
    assert builder.derive()['counts']['known_closed'] == 0
    rows = h['source_consistency']['archive_contents']['receipts']
    assert any(row['kind'] == 'signature-page' and row['hash'] is None and row['validation_state'] == 'unsupported' for row in rows)


@pytest.mark.parametrize('digest', [None, 'not-a-digest'])
def test_unassignable_page_digest_actual_rebuild_is_unknown(builder, digest, tmp_path, isolate_credentials_and_transport):
    builder.cp['evidence'].append({'kind': 'signature-page', 'hash': digest})
    builder.persist()
    app = create_app(tmp_path / 'app', 'synthetic-local-token')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        bootstrap = client.get('/api/bootstrap', headers={'x-launch-token': 'synthetic-local-token'})
        client.headers['x-csrf-token'] = bootstrap.json()['csrf']
        original, checkpoint = seed_actual_report(builder, app.state.store, 'invalid-page', str(digest))
        response = client.post('/api/reports/' + original['id'] + '/rebuild')
        assert response.status_code == 200, response.text
        child = client.get('/api/reports/' + response.json()['report_id']).json()
        assert child['coverage']['position_evidence']['counts']['known_closed'] == 0
        assert child['coverage']['history_evidence']['source_set']['complete'] is False
        assert child['qualification']['qualified'] is False
        assert app.state.store.get('reports', original['id']) == original
        assert app.state.store.evidence(child['collection_input_hash'])['checkpoint']['evidence'] == checkpoint['evidence']


@pytest.mark.parametrize('variant', ['missing', 'corrupt'])
def test_lost_page_keeps_proved_fee_only_wallet_projection(builder, variant):
    from tests.review_v037.review_helpers import conflict_page
    ref = conflict_page(builder, 'opening', beyond_fee=False)
    damage(evidence_file(builder, ref['hash']), variant)
    h = history(builder)
    assert builder.derive()['counts']['known_closed'] == 0
    assert h['native_address_metrics']['observed']['native_wallet_delta_sol']['value'] == '-0.000015'
    assert h['native_address_metrics']['observed']['wallet_network_fees_sol']['value'] == '0.000015'
