"""Audit planning uses source inputs, never presentation summaries or flags."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from scanner.archive_input import METHOD
from tests.test_discovery import MINT, POOL, SIGNATURE, STAMP, SYSTEM_PROGRAM, WALLET, pool, trade, transaction
from tests.test_discovery_integration_review import isolate_credentials_and_transport, session
from tests.test_pdf_alignment import passing_report


def identity_cohort(store):
    native = store.archive(transaction())
    account = store.archive({'method': 'getAccountInfo', 'address': WALLET, 'result': {'context': {'slot': 11}, 'value': {'owner': SYSTEM_PROGRAM, 'executable': False}}})
    pools = store.archive({'provider': 'geckoterminal', 'network': 'solana', 'kind': 'trending-pools', 'pool_address': None, 'result': {'data': [pool()]}})
    trades = store.archive({'provider': 'geckoterminal', 'network': 'solana', 'kind': 'pool-trades', 'pool_address': POOL, 'result': {'data': [trade()]}})
    candidate = {'address': WALLET, 'source': 'pool-trades', 'status': 'candidate', 'signatures': [SIGNATURE], 'pools': [POOL], 'evidence': [native, account, trades], 'validation': {'identity_verified': True, 'account_type': 'system-owned signer', 'economic_signers': [WALLET], 'signature': SIGNATURE, 'transaction_evidence_hash': native, 'account_evidence_hash': account}, 'sampled_activity': [{'signature': SIGNATURE, 'kind': 'buy', 'pool_address': POOL, 'block_time': STAMP}]}
    cohort = {'id': 'a' * 32, 'status': 'completed', 'created_at': '2026-10-04T00:00:00Z', 'source': 'public-pool-discovery', 'candidates': [candidate], 'universe': [{'pool_address': POOL, 'base_token_address': MINT, 'evidence_hash': pools, 'trade_evidence_hash': trades}], 'evidence': [{'kind': 'transaction', 'signature': SIGNATURE, 'hash': native}, {'kind': 'wallet-account', 'address': WALLET, 'hash': account}, {'kind': 'trending-pools', 'hash': pools}, {'kind': 'pool-trades', 'hash': trades}], 'sample': {'window_start': datetime.fromtimestamp(STAMP - 60, timezone.utc).isoformat(), 'window_end': datetime.fromtimestamp(STAMP + 60, timezone.utc).isoformat()}, 'counts': {}, 'limitations': []}
    store.put('discovery_cohorts', cohort['id'], cohort)
    return cohort, {'native': native, 'account': account, 'pools': pools, 'trades': trades}


def saved_report(store, digest, **changes):
    report = {**passing_report(), 'id': 'archived-plan-report', 'address': WALLET, 'created_at': '2026-10-04T00:00:00Z', 'archive_input_hash': 'b' * 64, 'archive_accounting': {'version': METHOD}, 'positions': [{'id': 'episode', 'status': 'closed', 'in_window': True, 'hold_hours': '2', 'sold_90_pct_hours': '0.01', 'first_sale_hours': '0.005', 'evidence': [digest]}], 'events': [{'kind': 'transfer_in', 'mint': MINT, 'basis_sol': None, 'evidence': [digest]}], 'evidence': [{'kind': 'transaction', 'signature': SIGNATURE, 'hash': digest}], 'research': {'episodes': [], 'unresolved_basis_sales': 1, 'observed_unmatched_sales': 0, 'evidence': [digest]}, 'reviewed_copy_checks': {'creator_links': {'state': 'PASS', 'reviewed': True, 'primary_evidence': True, 'evidence': [digest]}}, **changes}
    store.put('reports', report['id'], report)
    return report


@pytest.mark.parametrize('changes', [{}, {'evidence_status': 'partial'}, {'methodology': 'fifo-v1'}])
def test_full_summary_and_cohort_get_plan_decisions_use_same_preprojection_source_inputs(session, changes):
    client, app, _ = session
    cohort, hashes = identity_cohort(app.state.store)
    original = saved_report(app.state.store, hashes['native'], **changes)
    before = json.dumps(app.state.store.get('reports', original['id']), sort_keys=True)
    full = client.get('/api/state').json()
    summary = client.get('/api/state?report_view=summary').json()
    direct = client.get('/api/discovery/' + cohort['id']).json()
    plans = [state['discovery_cohorts'][0]['audit_plan'] for state in (full, summary)] + [direct['audit_plan']]
    assert plans[0] == plans[1] == plans[2]
    row = plans[0]['research_order'][0]
    displayed = client.get('/api/reports/' + original['id']).json()
    assert row['saved_qualification']['qualified'] == displayed['qualification']['qualified']
    assert row['saved_qualification']['unknown_checks'] == displayed['qualification']['unknown_checks']
    assert row['copy_review'] == displayed['copy_review']
    assert row['identity_state'] == 'PASS'
    assert plans[0]['selected_addresses'] == []  # Saved results do not trigger automatic re-collection.
    assert json.dumps(app.state.store.get('reports', original['id']), sort_keys=True) == before
    assert app.state.store.get('discovery_cohorts', cohort['id']) == cohort


@pytest.mark.parametrize('role', ['native', 'account', 'pools', 'trades'])
def test_required_identity_source_loss_revokes_plan_and_explicit_audit_then_restores_offline(session, role):
    client, app, directory = session
    cohort, hashes = identity_cohort(app.state.store)
    initial = client.get('/api/state?report_view=summary').json()
    assert initial['discovery_cohorts'][0]['audit_plan']['selected_addresses'] == [WALLET]
    path = directory / 'evidence' / (hashes[role] + '.json.gz')
    frozen = path.read_bytes()
    path.unlink()
    lost = client.get('/api/state?report_view=summary').json()
    plan = lost['discovery_cohorts'][0]['audit_plan']
    assert plan['selected_addresses'] == [] and plan['excluded'][0]['identity_state'] == 'UNKNOWN'
    assert client.post('/api/discovery/' + cohort['id'] + '/audit', json={'addresses': [WALLET]}).status_code == 422
    assert app.state.store.list('scans') == []
    path.write_bytes(frozen)
    restored = client.get('/api/state?report_view=summary').json()
    assert restored['discovery_cohorts'][0]['audit_plan'] == initial['discovery_cohorts'][0]['audit_plan']
    assert restored['usage'] == initial['usage'] == lost['usage']
    assert app.state.store.get('discovery_cohorts', cohort['id']) == cohort


def test_positive_cohort_flags_do_not_replace_sources_and_default_partial_audits_remain_deferred(session):
    client, app, _ = session
    cohort, hashes = identity_cohort(app.state.store)
    saved_report(app.state.store, hashes['native'], evidence_status='partial')
    plan = client.get('/api/state?report_view=summary').json()['discovery_cohorts'][0]['audit_plan']
    assert plan['selected_addresses'] == [] and plan['deferred'][0]['action'] == 'resolve_report_dependencies'
    assert client.post('/api/discovery/' + cohort['id'] + '/audit', json={}).status_code == 422
    # Explicit deferred selection passes evidence eligibility and reaches the independent key prerequisite.
    explicit = client.post('/api/discovery/' + cohort['id'] + '/audit', json={'addresses': [WALLET]})
    assert explicit.status_code == 409 and 'Helius key' in explicit.json()['detail']
    forged = deepcopy(cohort)
    forged['evidence'] = []
    forged['candidates'][0]['evidence'] = []
    app.state.store.put('discovery_cohorts', forged['id'], forged)
    rejected = client.get('/api/state?report_view=summary').json()['discovery_cohorts'][0]['audit_plan']
    assert rejected['selected_addresses'] == [] and rejected['excluded'][0]['identity_state'] == 'UNKNOWN'
    assert client.post('/api/discovery/' + cohort['id'] + '/audit', json={'addresses': [WALLET]}).status_code == 422
    assert app.state.store.list('scans') == []
    assert client.get('/api/usage').json()['used'] == 0


@pytest.mark.parametrize('field,malformed', [('transaction_evidence_hash', []), ('transaction_evidence_hash', {}), ('account_evidence_hash', []), ('account_evidence_hash', {})])
def test_malformed_saved_identity_reference_is_unknown_and_get_views_remain_usable(session, field, malformed):
    client, app, _ = session
    cohort, _ = identity_cohort(app.state.store)
    cohort['candidates'][0]['validation'][field] = malformed
    app.state.store.put('discovery_cohorts', cohort['id'], cohort)
    for path in ('/api/state', '/api/state?report_view=summary', '/api/discovery/' + cohort['id']):
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        plan = body['audit_plan'] if 'audit_plan' in body else body['discovery_cohorts'][0]['audit_plan']
        assert plan['selected_addresses'] == [] and plan['excluded'][0]['identity_state'] == 'UNKNOWN'
    assert client.post('/api/discovery/' + cohort['id'] + '/audit', json={'addresses': [WALLET]}).status_code == 422
    assert app.state.store.list('scans') == []
    assert app.state.store.get('discovery_cohorts', cohort['id']) == cohort


def test_malformed_saved_unknown_check_key_does_not_crash_current_report_planning(session):
    client, app, _ = session
    cohort, hashes = identity_cohort(app.state.store)
    report = saved_report(app.state.store, hashes['native'])
    report['checks'].append({'key': {}, 'state': 'UNKNOWN', 'reason': 'Malformed saved check'})
    app.state.store.put('reports', report['id'], report)
    plans = []
    for path in ('/api/state', '/api/state?report_view=summary'):
        response = client.get(path)
        assert response.status_code == 200
        plan = response.json()['discovery_cohorts'][0]['audit_plan']
        row = plan['research_order'][0]
        assert row['action'] == 'resolve_report_dependencies' and row['saved_qualification']['qualified'] is False
        assert plan['selected_addresses'] == []
        plans.append(plan)
    assert plans[0] == plans[1]
    assert app.state.store.get('reports', report['id']) == report
