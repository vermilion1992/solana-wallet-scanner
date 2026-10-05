"""Development discovery source contracts; synthetic snapshots never close B3.

Fixtures use the existing GeckoTerminal pool/trade and Solana JSON-parsed
transaction/account schemas. Original archived records supply the association
oracle; copied candidate flags and planner lookup tables do not.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest

from scanner.accounting import METHODOLOGY
from scanner.config import STRICT
from scanner.copy_review import EVIDENCE_KEYS, METRIC_KEYS
from scanner.discovery import SYSTEM_PROGRAM, WRAPPED_SOL, plan_candidate_audits
from scanner.history_evidence import VERSION as HISTORY_VERSION
from scanner.position_evidence import VERSION as POSITION_VERSION
from scanner.research import VERSION as RESEARCH_VERSION
from scanner.report_view import summary_inputs, summary_view
from scanner.storage import Store

ROOT = Path(__file__).resolve().parents[1]
TIME = '2026-10-04T12:00:00+00:00'
STAMP = int(datetime.fromisoformat(TIME).timestamp())


def public(number, size=32):
    raw = number.to_bytes(size, 'big')
    value, result = number, ''
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    while value:
        value, remainder = divmod(value, 58)
        result = alphabet[remainder] + result
    return '1' * (len(raw) - len(raw.lstrip(b'\0'))) + result


def development_cohort(store, addresses=None, *, two_way=()):
    cohort = {'id': 'a'*32, 'source': 'public-pool-discovery', 'status': 'completed', 'created_at': TIME,
              'sample': {'window_start': '2026-10-03T12:00:00+00:00', 'window_end': '2026-10-04T12:01:00+00:00'},
              'candidates': [], 'universe': [], 'evidence': [], 'counts': {}, 'limitations': []}
    for index, address in enumerate(addresses or [public(101)]):
        mint, token, pool = public(201+index), public(301+index), public(401+index)
        signature = public(501+index, 64)
        raw = {'slot': 10, 'blockTime': STAMP, 'version': 0,
               'transaction': {'signatures': [signature], 'message': {'accountKeys': [
                   {'pubkey': address, 'signer': True, 'writable': True, 'source': 'transaction'},
                   {'pubkey': token, 'signer': False, 'writable': True, 'source': 'transaction'}], 'instructions': []}},
               'meta': {'err': None, 'fee': 5000, 'preBalances': [1000000, 2039280], 'postBalances': [995000, 2039280],
                        'preTokenBalances': [{'accountIndex': 1, 'mint': mint, 'owner': address, 'uiTokenAmount': {'amount': '10', 'decimals': 6}}],
                        'postTokenBalances': [{'accountIndex': 1, 'mint': mint, 'owner': address, 'uiTokenAmount': {'amount': '20', 'decimals': 6}}]}}
        native_hash = store.archive(raw)
        account_hash = store.archive({'method': 'getAccountInfo', 'address': address,
                                      'result': {'context': {'slot': 11}, 'value': {'owner': SYSTEM_PROGRAM, 'executable': False}}})
        pool_row = {'id': 'solana_'+pool, 'type': 'pool', 'attributes': {'address': pool, 'name': 'DEV / SOL', 'reserve_in_usd': '10000'},
                    'relationships': {'base_token': {'data': {'id': 'solana_'+mint}}, 'quote_token': {'data': {'id': 'solana_'+WRAPPED_SOL}}}}
        pool_hash = store.archive({'provider': 'geckoterminal', 'network': 'solana', 'kind': 'trending-pools', 'pool_address': None,
                                   'observed_at': TIME, 'result': {'data': [pool_row]}})
        activity = [{'signature': signature, 'kind': 'buy', 'pool_address': pool, 'block_time': STAMP, 'provider_block_number': 10}]
        if address in two_way:
            activity.append({'signature': public(601+index, 64), 'kind': 'sell', 'pool_address': pool, 'block_time': STAMP, 'provider_block_number': 10})
        trades = [{'type': 'trade', 'attributes': {'tx_from_address': address, 'tx_hash': row['signature'], 'kind': row['kind'],
                                                'block_timestamp': TIME, 'block_number': 10}} for row in activity]
        trade_hash = store.archive({'provider': 'geckoterminal', 'network': 'solana', 'kind': 'pool-trades', 'pool_address': pool,
                                   'observed_at': TIME, 'result': {'data': trades}})
        cohort['universe'].append({'pool_address': pool, 'base_token_address': mint, 'quote_token_address': WRAPPED_SOL,
                                   'evidence_hash': pool_hash, 'trade_evidence_hash': trade_hash, 'selected': True})
        cohort['evidence'].extend([{'kind': 'transaction', 'signature': signature, 'hash': native_hash},
                                  {'kind': 'wallet-account', 'address': address, 'hash': account_hash},
                                  {'kind': 'trending-pools', 'hash': pool_hash}, {'kind': 'pool-trades', 'pool_address': pool, 'hash': trade_hash}])
        cohort['candidates'].append({'address': address, 'source': 'pool-trades', 'status': 'candidate', 'signatures': [row['signature'] for row in activity],
                                    'pools': [pool], 'sampled_activity': activity, 'evidence': [native_hash, account_hash, trade_hash],
                                    'observed_buys': 1, 'observed_sells': int(address in two_way),
                                    'validation': {'signature': signature, 'identity_verified': True, 'account_type': 'system-owned signer',
                                                   'economic_signers': [address], 'transaction_evidence_hash': native_hash,
                                                   'account_evidence_hash': account_hash, 'token_flows': [{'mint': mint, 'raw_delta': '10', 'decimals': 6}]}})
    return cohort


def imported_native_cohort(store):
    from scanner.candidate_import import import_candidate_cohort
    verified = development_cohort(store)
    candidate = verified['candidates'][0]
    cohort = import_candidate_cohort([candidate['address']], cohort_id='d'*32, created_at=TIME)
    cohort['candidates'][0].update(status='candidate', evidence=candidate['evidence'][:2],
                                   validation=deepcopy(candidate['validation']))
    cohort['evidence'] = deepcopy(verified['evidence'][:2])
    return cohort


def test_import_can_enter_common_audit_route_after_its_own_raw_native_identity_check(store):
    cohort = imported_native_cohort(store)
    before = deepcopy(cohort)
    plan = plan_candidate_audits(store, cohort)
    assert plan['selected_addresses'] == [cohort['candidates'][0]['address']]
    row = plan['research_order'][0]
    assert row['identity_state'] == 'PASS'
    assert row['activity'] == {'buys': 0, 'sells': 0, 'signatures': 1}
    assert any(check['key'] == 'imported_native_association' and check['state'] == 'PASS' for check in row['source_checks'])
    assert cohort == before


def test_imported_native_route_keeps_negative_source_loss_and_conflict_dependencies(store):
    cohort = imported_native_cohort(store)
    candidate = cohort['candidates'][0]
    digest = candidate['validation']['account_evidence_hash']
    file = store.path/'evidence'/(digest+'.json.gz')
    raw_bytes = file.read_bytes()
    file.unlink()
    assert not plan_candidate_audits(store, cohort)['selected_addresses']
    file.write_bytes(raw_bytes)
    assert plan_candidate_audits(store, cohort)['selected_addresses'] == [candidate['address']]
    native = deepcopy(store.evidence(candidate['validation']['transaction_evidence_hash']))
    native['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '25'
    alternative = store.archive(native)
    candidate['evidence'].append(alternative)
    cohort['evidence'].append({'hash': alternative, 'kind': 'transaction', 'signature': candidate['validation']['signature']})
    plan = plan_candidate_audits(store, cohort)
    assert not plan['selected_addresses']
    assert any(check['key'] == 'linked_native_identity' and check['state'] == 'UNKNOWN' for check in plan['research_order'][0]['source_checks'])


def financial_snapshot(candidate, *, partial=False, identifier='saved-report'):
    report = {'id': identifier, 'address': candidate['address'], 'source': 'live', 'methodology': METHODOLOGY, 'preset': dict(STRICT),
              'research': {'version': RESEARCH_VERSION},
              'created_at': TIME, 'window': {'start': '2026-09-04T12:00:00+00:00', 'end': TIME}, 'policy': 'MATCH',
              'evidence_status': 'verified', 'metrics': {'profit_sol': {'status': 'known', 'value': '12.5'}},
              'checks': [{'key': key, 'state': 'PASS', 'actual': '12.5' if key == 'profit_sol' else '1', 'reason': 'Development saved-policy fixture'}
                         for key in EVIDENCE_KEYS + METRIC_KEYS + ('economic_pnl_sol',)],
              'coverage': {'history_evidence': {'version': HISTORY_VERSION}, 'position_evidence': {'version': POSITION_VERSION}},
              'evidence': [{'hash': candidate['validation']['transaction_evidence_hash'], 'kind': 'transaction'}], 'events': [], 'positions': []}
    if partial:
        report.update(policy='UNRESOLVED', evidence_status='partial')
        report['metrics']['profit_sol'] = {'status': 'unknown', 'value': None, 'reason': 'Missing historical acquisition basis'}
        report['checks'][0].update(state='UNKNOWN', reason='Historical owned-account population is not established')
    return report


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.delenv('HELIUS_API_KEY', raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('Candidate planning cannot use credentials, provider calls or quota mutation')
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(get_password=forbidden, get_keyring=forbidden))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', forbidden)
    from scanner.providers import Gateway
    monkeypatch.setattr(Gateway, 'rpc', forbidden)
    value = Store(tmp_path/'data')
    monkeypatch.setattr(value, 'reserve', forbidden)
    yield value
    value.close()


def test_original_activity_not_caller_profit_or_count_claims_orders_bounded_research(store):
    first, second = public(101), public(102)
    cohort = development_cohort(store, [first, second], two_way=[second])
    cohort['candidates'][0].update(observed_buys=99999, observed_sells=99999, observed_profit_sol='1000000', qualification={'qualified': True})
    before = deepcopy(cohort)
    plan = plan_candidate_audits(store, cohort, audit_cap=1)
    assert plan['selected_addresses'] == [second]
    assert plan['deferred'][0]['address'] == first
    assert plan['selected'][0]['activity'] == {'buys': 1, 'sells': 1, 'signatures': 2}
    assert not plan['selected'][0]['qualified'] and plan['selected'][0]['financial_policy'] == 'NOT_AUDITED'
    assert plan['selected'][0]['copy_risks_unknown']
    assert plan['selected'][0]['proof_address'] == second
    assert all(check['state'] == 'PASS' for check in plan['research_order'][0]['source_checks'])
    assert len(plan['research_order'][0]['source_receipts'][0]['evidence']) == 4
    assert cohort == before and plan['provider_requests'] == 0


@pytest.mark.parametrize('source', ['native', 'account', 'pool', 'trade'])
def test_required_source_loss_and_exact_restore_revoke_selection(store, source):
    cohort = development_cohort(store)
    candidate, pool = cohort['candidates'][0], cohort['universe'][0]
    digest = {'native': candidate['validation']['transaction_evidence_hash'], 'account': candidate['validation']['account_evidence_hash'],
              'pool': pool['evidence_hash'], 'trade': pool['trade_evidence_hash']}[source]
    assert plan_candidate_audits(store, cohort)['selected_addresses'] == [candidate['address']]
    path = store.path/'evidence'/f'{digest}.json.gz'
    original = path.read_bytes(); path.unlink()
    missing = plan_candidate_audits(store, cohort)
    assert not missing['selected_addresses'] and missing['excluded'][0]['identity_state'] == 'UNKNOWN'
    path.write_bytes(original)
    assert plan_candidate_audits(store, cohort)['selected_addresses'] == [candidate['address']]


def test_corrupt_source_and_forged_caller_flags_cannot_select(store):
    cohort = development_cohort(store)
    candidate = cohort['candidates'][0]
    (store.path/'evidence'/f"{candidate['validation']['transaction_evidence_hash']}.json.gz").write_bytes(b'corrupt source')
    candidate.update(qualified=True, safe=True, states={'identity_checked': True})
    assert not plan_candidate_audits(store, cohort)['selected_addresses']
    assert not plan_candidate_audits(store, {'candidates': [{'address': candidate['address'], 'status': 'candidate', 'validation': {'identity_verified': True}}]})['selected_addresses']


@pytest.mark.parametrize('mutation', ['time', 'slot', 'mint', 'owner', 'provider', 'network', 'account'])
def test_source_association_conflict_cannot_select(store, mutation):
    cohort = development_cohort(store)
    candidate, pool = cohort['candidates'][0], cohort['universe'][0]
    if mutation == 'account':
        old = candidate['validation']['account_evidence_hash']; raw = store.evidence(old)
        raw['address'] = public(999); new = store.archive(raw); candidate['validation']['account_evidence_hash'] = new
    elif mutation in ('provider', 'network'):
        old = pool['trade_evidence_hash']; raw = store.evidence(old)
        raw[mutation] = 'unreviewed'; new = store.archive(raw); pool['trade_evidence_hash'] = new
    else:
        old = candidate['validation']['transaction_evidence_hash']; raw = store.evidence(old)
        if mutation in ('time', 'slot'):
            raw['blockTime' if mutation == 'time' else 'slot'] += 1
        else:
            for side in ('preTokenBalances', 'postTokenBalances'): raw['meta'][side][0][mutation] = public(999)
        new = store.archive(raw); candidate['validation']['transaction_evidence_hash'] = new
    candidate['evidence'].append(new)
    cohort['evidence'] = [row for row in cohort['evidence'] if row['hash'] != old]
    plan = plan_candidate_audits(store, cohort)
    assert not plan['selected_addresses'] and plan['excluded'][0]['identity_state'] != 'PASS'


def test_linked_native_alternative_loss_conflict_and_irrelevant_fee_difference(store):
    cohort = development_cohort(store); candidate = cohort['candidates'][0]
    raw = store.evidence(candidate['validation']['transaction_evidence_hash']); raw['meta']['fee'] = 6000
    alternative = store.archive(raw)
    link = {'kind': 'transaction', 'signature': candidate['validation']['signature'], 'hash': alternative}
    cohort['evidence'].append(link)
    assert plan_candidate_audits(store, cohort)['selected_addresses'] == [candidate['address']]
    path = store.path/'evidence'/f'{alternative}.json.gz'; original = path.read_bytes(); path.unlink()
    assert not plan_candidate_audits(store, cohort)['selected_addresses']
    path.write_bytes(original)
    raw['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '30'; link['hash'] = store.archive(raw)
    assert not plan_candidate_audits(store, cohort)['selected_addresses']


def test_current_partial_report_defers_repeated_collection_without_conditional_profit_upgrade(store):
    cohort = development_cohort(store); report = financial_snapshot(cohort['candidates'][0], partial=True)
    report['research']['conditional_observed_lot_profit_sol'] = '9999999'; original = deepcopy(report)
    plan = plan_candidate_audits(store, cohort, reports=[report], preset=STRICT); row = plan['deferred'][0]
    assert not plan['selected_addresses'] and row['action'] == 'resolve_report_dependencies'
    assert row['report_id'] == report['id'] and not row['qualified'] and row['saved_qualification']['profit_sol'] is None
    assert row['saved_qualification']['unknown_checks'] and report == original


def test_known_filter_failure_and_unknown_evidence_remain_separate(store):
    cohort = development_cohort(store); report = financial_snapshot(cohort['candidates'][0], partial=True); report['policy'] = 'MISS'
    next(c for c in report['checks'] if c['key'] == 'profit_sol').update(state='FAIL', reason='Below the saved filter')
    row = plan_candidate_audits(store, cohort, reports=[report])['deferred'][0]
    assert row['financial_policy'] == 'MISS' and row['action'] == 'inspect_policy_miss'
    assert row['saved_qualification']['failed_checks'] and row['saved_qualification']['unknown_checks'] and row['copy_risks_unknown']


def test_qualified_saved_match_still_requires_separate_risk_review(store):
    cohort = development_cohort(store, [public(101), public(102)]); report = financial_snapshot(cohort['candidates'][1])
    plan = plan_candidate_audits(store, cohort, reports=[report], preset=STRICT); row = plan['research_order'][0]
    assert plan['selected_addresses'] == [public(101)] and row['address'] == public(102)
    assert row['qualified'] and row['action'] == 'inspect_qualified_report' and row['copy_risks_unknown']
    assert 'follower_exploitation' in row['copy_review']['unknown_checks'] and 'safety_score' not in row


@pytest.mark.parametrize('mutation,action', [('preset', 'cached_filter_preview'), ('method', 'offline_rebuild'), ('preview', 'audit_wallet'), ('demo', 'audit_wallet')])
def test_saved_method_preset_and_source_boundaries(store, mutation, action):
    cohort = development_cohort(store); report = financial_snapshot(cohort['candidates'][0])
    if mutation == 'preset': report['preset']['min_profit_sol'] = '1'
    elif mutation == 'method': report['methodology'] = 'fifo-old'
    elif mutation == 'preview': report['preview'] = True
    else: report['source'] = 'demo'
    row = plan_candidate_audits(store, cohort, reports=[report], preset=STRICT)['research_order'][0]
    assert row['action'] == action and not row['qualified']


def test_permutations_and_disjoint_sources_preserve_identity_and_immutable_bytes(store):
    cohort = development_cohort(store, [public(103), public(102), public(101)], two_way=[public(102)])
    disjoint = store.evidence(cohort['candidates'][0]['validation']['transaction_evidence_hash'])
    disjoint['transaction']['signatures'] = [public(999, 64)]
    cohort['evidence'].append({'kind': 'transaction', 'signature': public(999, 64), 'hash': store.archive(disjoint)})
    before = deepcopy(cohort)
    archives = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (store.path/'evidence').glob('*')}
    usage = store.usage('helius', '2026-10-02', 1000000); expected = plan_candidate_audits(store, cohort, audit_cap=2)
    assert expected['selected_addresses'] == [public(102), public(101)]
    changed = deepcopy(cohort)
    for key in ('candidates', 'universe', 'evidence'): changed[key].reverse()
    assert plan_candidate_audits(store, changed, audit_cap=2) == expected and cohort == before
    assert store.usage('helius', '2026-10-02', 1000000) == usage
    assert archives == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (store.path/'evidence').glob('*')}


def test_preprojection_sql_inputs_preserve_qualification_and_projected_summaries_reject(store):
    from scanner.archive_input import METHOD
    cohort = development_cohort(store); report = financial_snapshot(cohort['candidates'][0])
    report.update(archive_input_hash='a'*64, archive_accounting={'version': METHOD}); store.put('reports', report['id'], report)
    assert plan_candidate_audits(store, cohort, reports=summary_inputs(store))['research_order'][0]['qualified']
    with pytest.raises(ValueError, match='semantic report inputs'): plan_candidate_audits(store, cohort, reports=[summary_view(report)])


def test_cli_reads_only_saved_records_and_never_changes_quota_or_sources(store, tmp_path):
    cohort = development_cohort(store); report = financial_snapshot(cohort['candidates'][0], partial=True)
    store.put('discovery_cohorts', cohort['id'], cohort); store.put('reports', report['id'], report); store.put('configuration', 'preset', dict(STRICT))
    before = [tuple(row) for row in store.db.execute('SELECT kind,id,payload,updated_at FROM records ORDER BY kind,id')]
    output = tmp_path/'plan.json'
    result = subprocess.run([sys.executable, str(ROOT/'tools/discovery_plan.py'), '--data-dir', str(store.path), '--cohort-id', cohort['id'], '--output', str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    plan = json.loads(output.read_bytes())
    assert not plan['selected_addresses'] and plan['deferred'][0]['action'] == 'resolve_report_dependencies' and plan['provider_requests'] == 0
    assert [tuple(row) for row in store.db.execute('SELECT kind,id,payload,updated_at FROM records ORDER BY kind,id')] == before
    assert store.usage('helius', '2026-10-02', 1000000)['used'] == 0


@pytest.mark.parametrize('cap', [True, 0, 6])
def test_workload_caps_cannot_be_raised(store, cap):
    with pytest.raises(ValueError, match='Audit cap'): plan_candidate_audits(store, development_cohort(store), audit_cap=cap)


@pytest.mark.parametrize('location', ['candidate_only', 'wrong_role', 'nested_wrong_role', 'null_native'])
def test_body_derived_linked_native_associations_cannot_disappear_by_role_or_source_loss(store, location):
    cohort = development_cohort(store); candidate = cohort['candidates'][0]
    raw = store.evidence(candidate['validation']['transaction_evidence_hash'])
    raw['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '30'
    payload = {'result': {'value': raw}} if location == 'nested_wrong_role' else None if location == 'null_native' else raw
    digest = store.archive(payload)
    if location == 'candidate_only': candidate['evidence'].append(digest)
    else: cohort['evidence'].append({'kind': 'transaction' if location == 'null_native' else 'pool-trades', 'signature': candidate['validation']['signature'], 'hash': digest})
    present = plan_candidate_audits(store, cohort)
    assert not present['selected_addresses'] and present['excluded'][0]['identity_state'] == 'UNKNOWN'
    path = store.path/'evidence'/f'{digest}.json.gz'; original = path.read_bytes(); path.unlink()
    missing = plan_candidate_audits(store, cohort)
    assert not missing['selected_addresses'] and missing['excluded'][0]['identity_state'] == 'UNKNOWN'
    path.write_bytes(original)
    assert plan_candidate_audits(store, cohort) == present


@pytest.mark.parametrize('field,malformed', [('transaction_evidence_hash', []), ('transaction_evidence_hash', {}), ('account_evidence_hash', []), ('account_evidence_hash', {})])
def test_malformed_primary_digest_is_a_dependency_not_a_plan_crash(store, field, malformed):
    cohort = development_cohort(store); cohort['candidates'][0]['validation'][field] = malformed
    result = plan_candidate_audits(store, cohort)
    assert not result['selected_addresses'] and result['excluded'][0]['identity_state'] == 'UNKNOWN'


def test_malformed_report_check_key_remains_unknown_without_crashing_planner(store):
    cohort = development_cohort(store); report = financial_snapshot(cohort['candidates'][0])
    report['checks'].append({'key': {}, 'state': 'UNKNOWN', 'reason': 'Malformed source check'})
    result = plan_candidate_audits(store, cohort, reports=[report])
    assert not result['selected_addresses'] and not result['deferred'][0]['qualified']
    assert any(c['reason'] == 'Malformed source check' for c in result['deferred'][0]['saved_qualification']['unknown_checks'])


@pytest.mark.parametrize('owner', [{}, [], None])
def test_malformed_token_owner_is_unknown_without_crashing_identity_replay(store, owner):
    cohort = development_cohort(store); candidate = cohort['candidates'][0]
    old = candidate['validation']['transaction_evidence_hash']; raw = store.evidence(old)
    raw['meta']['postTokenBalances'][0]['owner'] = owner
    new = store.archive(raw); candidate['validation']['transaction_evidence_hash'] = new
    candidate['evidence'] = [new if h == old else h for h in candidate['evidence']]
    for link in cohort['evidence']:
        if link['hash'] == old: link['hash'] = new
    plan = plan_candidate_audits(store, cohort)
    assert not plan['selected_addresses'] and plan['excluded'][0]['identity_state'] == 'UNKNOWN'


def test_conflicting_linked_wallet_account_cannot_be_hidden_by_role_or_source_removal(store):
    cohort = development_cohort(store); candidate = cohort['candidates'][0]
    raw = store.evidence(candidate['validation']['account_evidence_hash']); raw['result']['value']['owner'] = public(999)
    digest = store.archive(raw); cohort['evidence'].append({'kind': 'pool-trades', 'hash': digest})
    assert not plan_candidate_audits(store, cohort)['selected_addresses']
    path = store.path/'evidence'/f'{digest}.json.gz'; original = path.read_bytes(); path.unlink()
    assert not plan_candidate_audits(store, cohort)['selected_addresses']
    path.write_bytes(original)
    assert not plan_candidate_audits(store, cohort)['selected_addresses']
