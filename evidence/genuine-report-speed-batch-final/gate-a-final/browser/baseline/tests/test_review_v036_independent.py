"""Independent R11 completeness controls; only synthetic local archives are used.

Actual shipped reference/account limits are exercised without monkeypatching.
The original review's 25 assertions live in tests/review_v036.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace
import sys

import pytest

from scanner.history_evidence import derive_history_evidence, MAX_REFERENCES, MAX_ACCOUNTS, MAX_RECORDS
from scanner.source_consistency import index_source_links, source_index_receipt, SOURCE_HASH_LIMIT
from scanner.report_rebuild import freeze_report_inputs, load_report_inputs
from scanner.position_evidence import derive_position_evidence
from tests.review_v036.review_helpers import builder, pb, add_alternative
from tests.test_discovery_integration_review import local_session


def history(case):
    result = derive_history_evidence(case.store, pb.WALLET, pb.WINDOW,
                                     checkpoint=case.cp, collected={'transactions': case.records})
    assert set(result['evidence_gates'].values()) == {'UNKNOWN'}
    return result


def pad_to_actual_limit(case, last, *, extra=1, ordering='tail', metadata=False):
    originals = [ref for ref in deepcopy(case.cp['evidence']) if ref != last]
    duplicate = next(ref for ref in originals if ref.get('kind') == 'transaction')
    padding = [deepcopy(duplicate) for _ in range(MAX_REFERENCES + extra - len(originals) - 1)]
    if metadata:
        for index, reference in enumerate(padding):
            reference['optional_note'] = f'synthetic note {index}'
    case.cp['evidence'] = originals + padding + [last]
    if ordering == 'prefix':
        first = len(originals)
        case.cp['evidence'][first], case.cp['evidence'][-1] = case.cp['evidence'][-1], case.cp['evidence'][first]
    elif ordering == 'reverse':
        case.cp['evidence'].reverse()
    case.persist()


@pytest.mark.parametrize('ordering', ['tail', 'prefix', 'reverse'])
@pytest.mark.parametrize('extra', [1, 1000])
def test_agreeing_oversized_manifest_uses_complete_unique_set_but_retains_native_raw_cap(
        builder, ordering, extra):
    reference = add_alternative(builder, 'opening', offset=False)
    pad_to_actual_limit(builder, reference, ordering=ordering, extra=extra)
    result = builder.derive()
    assert result['counts']['known_closed'] == 1
    position = result['positions'][0]
    assert position['hold_hours']['value'] == '6'
    assert position['stages']['source_consistency']['state'] == 'PASS'
    assert reference['hash'] in position['sources']
    certificate = history(builder)
    source_set = certificate['source_set']
    assert source_set['state'] == 'PASS' and source_set['complete'] is True
    assert source_set['raw_reference_count'] == MAX_REFERENCES + extra
    assert source_set['unique_link_count'] == source_set['unique_hash_count'] == source_set['inspected_hash_count'] == 9
    assert source_set['omitted_hash_count'] == 0
    assert source_set['invalid_link_count'] == source_set['unauthenticated_link_count'] == 0
    for group in [certificate['native_address_metrics']['observed'],
                  *certificate['native_address_metrics']['periods'].values()]:
        assert all(metric['status'] == 'unknown' and metric['value'] is None for metric in group.values())


@pytest.mark.parametrize('boundary', ['opening', 'closing'])
@pytest.mark.parametrize('malformed', [False, True], ids=['missing-archive', 'malformed-archive'])
def test_late_unavailable_or_malformed_distinct_source_cannot_be_lost_behind_duplicate_padding(
        builder, boundary, malformed):
    reference = add_alternative(builder, boundary, offset=False)
    if malformed:
        raw = builder.store.evidence(reference['hash'])
        raw['transaction'] = None
        reference['hash'] = builder.store.archive(raw)
        builder.cp['evidence'][-1] = reference
    else:
        builder.remove_archive(reference['hash'])
    pad_to_actual_limit(builder, reference)
    result = builder.derive()
    assert result['counts']['known_closed'] == 0
    assert result['known_account_hold_median_hours']['value'] is None
    assert reference['hash'] in result['positions'][0]['stages']['source_consistency']['evidence']
    assert result['positions'][0]['hold_hours']['value'] is None


def test_nonsemantic_reference_metadata_does_not_create_unique_archive_budget_consumption(builder):
    reference = add_alternative(builder, 'closing', offset=False)
    pad_to_actual_limit(builder, reference, metadata=True)
    result = builder.derive()
    assert result['counts']['known_closed'] == 1
    assert result['positions'][0]['hold_hours']['value'] == '6'
    assert history(builder)['native_address_metrics']['observed']['wallet_network_fees_sol']['status'] == 'unknown'


@pytest.mark.parametrize('invalid', [None, {}, {'kind': 'transaction', 'hash': 'invalid-hash', 'signature': 'synthetic-buy'}])
def test_invalid_unassignable_reference_cannot_be_replaced_by_caller_pass_flags(builder, invalid):
    builder.cp['evidence'].append(invalid)
    builder.cp['source_set'] = {'state': 'PASS', 'complete': True, 'omitted_hash_count': 0}
    builder.persist()
    result = builder.derive(history_evidence={'state': 'PASS', 'source_set': builder.cp['source_set']})
    assert result['counts']['known_closed'] == 0
    assert result['positions'][0]['hold_hours']['value'] is None
    assert result['positions'][0]['stages']['source_consistency']['state'] == 'UNKNOWN'


def synthetic_address(number):
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    payload = number.to_bytes(32, 'big')
    encoded, value = '', number
    while value:
        value, remainder = divmod(value, 58)
        encoded = alphabet[remainder] + encoded
    return '1' * (len(payload) - len(payload.lstrip(b'\0'))) + encoded


def add_wsol_page_chain(builder, account_count, placement, conflict):
    original = deepcopy(builder.cp['accounts'])
    fillers = {synthetic_address(10000 + index): {'address': synthetic_address(10000 + index)}
               for index in range(account_count - len(original) - 1)}
    entries = [pb.entry(raw['transaction']['signatures'][0], raw) for raw in reversed(builder.raws)]
    if conflict:
        entries[-1]['err'] = {'InstructionError': [0, 'InvalidArgument']}
    params = {'limit': 100, 'commitment': 'finalized', 'minContextSlot': 1000}
    first = builder.store.archive({'method': 'getSignaturesForAddress', 'address': pb.WSOL_ACCOUNT,
                                   'params': params, 'result': entries})
    terminal = builder.store.archive({'method': 'getSignaturesForAddress', 'address': pb.WSOL_ACCOUNT,
                                      'params': {**params, 'before': entries[-1]['signature']}, 'result': []})
    builder.cp['evidence'].extend([{'kind': 'signature-page', 'hash': first},
                                   {'kind': 'signature-page', 'hash': terminal}])
    account = {'address': pb.WSOL_ACCOUNT, 'origin': 'event-time token-balance owner',
               'ownership_evidence': builder.records[0]['evidence_hash'], 'cursor': entries[-1]['signature'],
               'terminal': 'empty signature page', 'terminal_evidence': terminal}
    builder.cp['accounts'] = ({**original, pb.WSOL_ACCOUNT: account, **fillers} if placement == 'prefix'
                              else {**original, **fillers, pb.WSOL_ACCOUNT: account})
    builder.cp['account_scope']['included_account_count'] = account_count
    builder.persist()


@pytest.mark.parametrize('account_count', [MAX_ACCOUNTS, MAX_ACCOUNTS + 1])
@pytest.mark.parametrize('placement', ['prefix', 'tail'])
@pytest.mark.parametrize('conflict', [False, True], ids=['agreeing-page', 'conflicting-page'])
def test_account_chain_budget_cannot_hide_linked_execution_fact_or_poison_unrelated_scoped_proof(
        builder, account_count, placement, conflict):
    add_wsol_page_chain(builder, account_count, placement, conflict)
    result = builder.derive()
    certificate = history(builder)
    assert result['counts']['known_closed'] == (0 if conflict else 1)
    assert result['positions'][0]['hold_hours']['value'] == (None if conflict else '6')
    assert any(row['account'] == pb.WSOL_ACCOUNT and row['field'] == 'err'
               for row in certificate['paging']['conflicts']) is conflict
    observed = certificate['native_address_metrics']['observed']['wallet_network_fees_sol']
    assert observed['status'] == 'known' and observed['value'] == '0.000015'
    assert observed['record_count'] == 3
    # Here both failed and successful readings imply the same proved address
    # delta: the wallet pays only its fee. The status conflict is immaterial
    # to that narrow observation, although it invalidates the token episode.
    delta = certificate['native_address_metrics']['observed']['native_wallet_delta_sol']
    assert delta['status'] == 'known' and delta['value'] == '-0.000015'


@pytest.mark.parametrize('account_count', [MAX_ACCOUNTS, MAX_ACCOUNTS + 1])
@pytest.mark.parametrize('include_conflicting', [False, True])
def test_page_execution_conflict_revokes_only_affected_native_endpoint_observation(
        builder, account_count, include_conflicting):
    # Conserving success changes the wallet by -6000 at the buy; the linked
    # failed assertion permits only the -5000 payer fee at that transaction.
    builder.raws[0]['meta']['postBalances'][0] -= 1000
    builder.raws[0]['meta']['postBalances'][3] += 1000
    builder.seed()
    add_wsol_page_chain(builder, account_count, 'tail', True)
    records = builder.records if include_conflicting else builder.records[1:]
    certificate = derive_history_evidence(builder.store, pb.WALLET, pb.WINDOW,
                                          checkpoint=builder.cp, collected={'transactions': records})
    observed = certificate['native_address_metrics']['observed']
    fees, delta = observed['wallet_network_fees_sol'], observed['native_wallet_delta_sol']
    assert fees['status'] == 'known'
    assert fees['value'] == ('0.000015' if include_conflicting else '0.00001')
    assert delta['status'] == ('unknown' if include_conflicting else 'known')
    assert delta['value'] == (None if include_conflicting else '-0.00001')
    assert fees['record_count'] == delta['record_count'] == (3 if include_conflicting else 2)


@pytest.mark.parametrize('unique_count', [SOURCE_HASH_LIMIT, SOURCE_HASH_LIMIT + 1])
def test_actual_distinct_hash_budget_is_complete_or_refuses_entire_inspection(unique_count):
    # Pure link-index accounting, with no blobs, RPC or metric proof implied.
    references = [{'kind': 'transaction', 'signature': 'synthetic-budget', 'hash': f'{number:064x}'}
                  for number in range(unique_count)]
    index = index_source_links(references, authenticated_references=references)
    receipt = source_index_receipt(index, index['hashes_to_inspect'])
    assert index['unique_hash_count'] == index['unique_link_count'] == unique_count
    assert receipt['raw_reference_count'] == unique_count
    if unique_count == SOURCE_HASH_LIMIT:
        assert receipt['state'] == 'PASS' and receipt['complete'] is True
        assert receipt['inspected_hash_count'] == unique_count and receipt['omitted_hash_count'] == 0
    else:
        assert receipt['state'] == 'UNKNOWN' and receipt['complete'] is False
        assert index['hashes_to_inspect'] == []
        assert receipt['inspected_hash_count'] == 0 and receipt['omitted_hash_count'] == unique_count


def test_link_identity_deduplicates_metadata_without_discarding_signature_roles():
    first = {'kind': 'transaction', 'signature': 'synthetic-first', 'hash': 'a' * 64}
    second = {**first, 'signature': 'synthetic-second'}
    refs = [first, {**first, 'optional_note': 'same source'}, second]
    forward = index_source_links(refs, authenticated_references=refs)
    backward = index_source_links(list(reversed(refs)), authenticated_references=list(reversed(refs)))
    assert forward == backward
    assert forward['raw_reference_count'] == 3
    assert forward['unique_link_count'] == 2 and forward['unique_hash_count'] == 1
    assert {row['signature'] for row in forward['links']} == {'synthetic-first', 'synthetic-second'}
    assert source_index_receipt(forward, forward['hashes_to_inspect'])['complete'] is True


def test_partial_attempted_archive_set_cannot_import_complete_counts():
    refs = [{'kind': 'transaction', 'signature': f'synthetic-{number}', 'hash': str(number) * 64}
            for number in (1, 2)]
    index = index_source_links(refs, authenticated_references=refs)
    receipt = source_index_receipt(index, [refs[0]['hash']])
    assert receipt['state'] == 'UNKNOWN' and receipt['complete'] is False
    assert receipt['inspected_hash_count'] == receipt['omitted_hash_count'] == 1
    assert source_index_receipt(index, index['hashes_to_inspect'])['state'] == 'PASS'


@pytest.mark.parametrize('omitted', [
    {'kind': 'transaction', 'signature': 'synthetic-first', 'hash': 'b' * 64},
    {'kind': 'transaction', 'signature': 'synthetic-second', 'hash': 'a' * 64},
    None,
], ids=['different-archive', 'same-archive-different-role', 'unassignable-authenticated-link'])
def test_candidate_subset_cannot_claim_the_authenticated_source_universe_is_complete(omitted):
    first = {'kind': 'transaction', 'signature': 'synthetic-first', 'hash': 'a' * 64}
    index = index_source_links([first], authenticated_references=[first, omitted])
    receipt = source_index_receipt(index, index['hashes_to_inspect'])
    assert receipt['state'] == 'UNKNOWN' and receipt['complete'] is False


def test_unauthenticated_link_cannot_become_a_complete_source_set():
    first = {'kind': 'transaction', 'signature': 'synthetic-first', 'hash': 'a' * 64}
    extra = {**first, 'hash': 'b' * 64}
    index = index_source_links([first, extra], authenticated_references=[first])
    receipt = source_index_receipt(index, index['hashes_to_inspect'])
    assert receipt['unauthenticated_link_count'] == 1
    assert receipt['state'] == 'UNKNOWN' and receipt['complete'] is False


def test_omitting_persisted_alternative_cannot_be_certified_by_caller_completeness_flags(builder):
    reference = add_alternative(builder, 'opening')
    # Persisted authenticated source universe retains the alternative. Only the
    # caller's candidate set drops it; no archive or native state is modified.
    builder.cp = deepcopy(builder.cp)
    builder.cp['evidence'] = [row for row in builder.cp['evidence'] if row != reference]
    fake = {'state': 'PASS', 'complete': True, 'omitted_hash_count': 0}
    builder.cp['source_set'] = fake
    result = builder.derive(history_evidence={'source_set': fake, 'state': 'PASS'})
    assert result['counts']['known_closed'] == 0
    assert result['positions'][0]['hold_hours']['value'] is None
    assert result['positions'][0]['stages']['source_consistency']['state'] == 'UNKNOWN'


class SyntheticArchiveOverlay:
    """Checksum-authenticated in-memory blobs over a disposable real Store.

    This avoids 10,000 fsyncs for synthetic cap controls. Persisted collector
    context still uses the fixture's real temporary SQLite store. No cache or
    source budget is altered; every returned payload is hashed by production.
    """
    def __init__(self, store):
        self.store, self.blobs = store, {}

    def archive(self, payload):
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                             allow_nan=False, separators=(',', ':')).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        self.blobs[digest] = deepcopy(payload)
        return digest

    def evidence(self, digest):
        if digest in self.blobs:
            return deepcopy(self.blobs[digest])
        return self.store.evidence(digest)

    def __getattr__(self, name):
        return getattr(self.store, name)


@pytest.mark.parametrize('dependency', ['unrelated', 'sale', 'opaque'],
                         ids=['unrelated-tail', 'intervening-account-sale', 'unresolved-account-operation'])
@pytest.mark.parametrize('placement', ['prefix', 'tail'])
def test_actual_selected_record_cap_cannot_hide_indexed_account_dependency(
        builder, dependency, placement):
    relevant = dependency != 'unrelated'
    builder.store = SyntheticArchiveOverlay(builder.store)
    for raw, slot in zip(builder.raws, (100, 200, 300)):
        raw['slot'] = slot
    builder.seed()
    anchor = builder.store.archive({'method': 'getSlot', 'commitment': 'finalized', 'result': 15000})
    previous_anchor = builder.cp['snapshot']['anchor_evidence']
    builder.cp['snapshot'].update(slot=15000, anchor_evidence=anchor)
    for ref in builder.cp['evidence']:
        if ref['hash'] == previous_anchor:
            ref['hash'] = anchor
    for account, (first, last) in builder.pages.items():
        replacements = []
        for digest in (first, last):
            page = builder.store.evidence(digest)
            page['params']['minContextSlot'] = 15000
            new = builder.store.archive(page)
            for ref in builder.cp['evidence']:
                if ref['hash'] == digest:
                    ref['hash'] = new
            replacements.append(new)
        builder.pages[account] = tuple(replacements)
        builder.cp['accounts'][account]['terminal_evidence'] = replacements[1]
        if builder.cp['accounts'][account]['ownership_evidence'] == previous_anchor:
            builder.cp['accounts'][account]['ownership_evidence'] = anchor

    def unrelated(signature, slot):
        return {'slot': slot, 'blockTime': pb.START + 10 * 3600, 'version': 0,
                'transaction': {'signatures': [signature], 'message': {'accountKeys': [pb.WALLET], 'instructions': []}},
                'meta': {'err': None, 'fee': 5000, 'preBalances': [100000], 'postBalances': [95000],
                         'preTokenBalances': [], 'postTokenBalances': [], 'innerInstructions': []}}

    def append_raw(raw):
        signature = raw['transaction']['signatures'][0]
        digest = builder.store.archive(raw)
        record = {'signature': signature, 'evidence_hash': digest}
        builder.records.append(record)
        builder.cp['transactions'][signature] = record
        builder.cp['evidence'].append({'kind': 'transaction', 'hash': digest, 'signature': signature})
        return record

    for number in range(MAX_RECORDS - len(builder.records)):
        append_raw(unrelated(f'synthetic-outside-{number}', 400 + number))
    extra = (pb.raw_exchange('synthetic-indexed-intervening-sale', 150, pb.START + 5400, 100, 75)
             if relevant else unrelated('synthetic-indexed-unrelated-tail', 14000))
    if dependency == 'opaque':
        # The account key alone establishes possible relevance; empty balance
        # arrays cannot prove that an unsupported intervening operation is inert.
        extra['meta'].update(preTokenBalances=[], postTokenBalances=[], innerInstructions=[])
        extra['transaction']['message']['instructions'] = [
            {'programId': pb.TOKEN_PROGRAM, 'accounts': [pb.ACCOUNT],
             'parsed': {'type': 'unsupported-account-operation', 'info': {}}}]
    tail = append_raw(extra)
    if placement == 'prefix':
        builder.records.remove(tail)
        builder.records.insert(3, tail)
        builder.cp['transactions'] = {record['signature']: record for record in builder.records}
    builder.persist()
    assert len(builder.records) == MAX_RECORDS + 1
    result = builder.derive()
    assert result['counts']['known_closed'] == (0 if relevant else 1)
    position = result['positions'][0]
    assert position['hold_hours']['value'] == (None if relevant else '6')
    if relevant:
        assert tail['evidence_hash'] in position['sources']
    assert all(metric['status'] == 'unknown' and metric['value'] is None
               for metric in history(builder)['native_address_metrics']['observed'].values())


def test_unknown_source_role_cannot_certify_an_unproved_relevance_decision(builder):
    alternative = deepcopy(builder.raws[0])
    for name in ('preTokenBalances', 'postTokenBalances'):
        row = next(row for row in alternative['meta'][name] if row['accountIndex'] == 1)
        row['uiTokenAmount']['amount'] = str(int(row['uiTokenAmount']['amount']) + 200)
    digest = builder.store.archive(alternative)
    builder.cp['evidence'].append({'kind': 'unrecognized-source-role', 'hash': digest,
                                   'signature': builder.records[0]['signature']})
    builder.persist()
    result = builder.derive()
    assert result['counts']['known_closed'] == 0
    assert result['positions'][0]['stages']['source_consistency']['state'] == 'UNKNOWN'


def test_known_distinct_roles_sharing_one_archive_remain_distinct_authenticated_links():
    # Index-only role identity control; shared bytes alone prove no RPC content.
    refs = [{'kind': 'transaction', 'hash': 'a' * 64, 'signature': 'synthetic-first'},
            {'kind': 'native-balance', 'hash': 'a' * 64}]
    index = index_source_links(refs, authenticated_references=refs)
    assert index['unique_link_count'] == 2 and index['unique_hash_count'] == 1
    assert {ref['kind'] for ref in index['links']} == {'transaction', 'native-balance'}
    assert source_index_receipt(index, index['hashes_to_inspect'])['complete'] is True


@pytest.mark.parametrize('forge_frozen_claim', [False, True])
def test_trimming_only_duplicate_caller_refs_cannot_remove_authoritative_native_raw_cap(
        builder, forge_frozen_claim):
    reference = add_alternative(builder, 'opening', offset=False)
    pad_to_actual_limit(builder, reference)
    builder.cp = deepcopy(builder.cp)
    unique = {(ref['kind'], ref['hash'], ref.get('signature')): ref for ref in builder.cp['evidence']}
    builder.cp['evidence'] = list(unique.values())
    assert len(builder.cp['evidence']) == 9
    collected = {'checkpoint': builder.cp, 'transactions': builder.records}
    if forge_frozen_claim:
        collected['frozen_input_hash'] = freeze_report_inputs(builder.store, pb.WALLET, pb.WINDOW,
            {**collected, 'evidence': builder.cp['evidence'], 'snapshot': builder.cp['snapshot']})
        collected['frozen_report_id'] = 'synthetic-never-saved-parent'
    certificate = derive_history_evidence(builder.store, pb.WALLET, pb.WINDOW,
                                          checkpoint=builder.cp, collected=collected)
    # Dedup preserves the complete unique set, so the scoped quantity fact is
    # allowed; raw multiplicity remains authoritative for native totals.
    assert certificate['source_set']['complete'] is True
    assert all(metric['status'] == 'unknown' and metric['value'] is None
               for metric in certificate['native_address_metrics']['observed'].values())
    result = derive_position_evidence(builder.store, pb.WALLET, pb.WINDOW,
                                      checkpoint=builder.cp, collected=collected)
    assert result['counts']['known_closed'] == 1


def test_legitimate_saved_earlier_manifest_keeps_its_independent_raw_reference_universe(builder):
    reference = add_alternative(builder, 'opening', offset=False)
    checkpoint = deepcopy(builder.cp)
    collected = {'checkpoint': checkpoint, 'transactions': builder.records,
                 'evidence': checkpoint['evidence'], 'snapshot': checkpoint['snapshot']}
    report = {'id': 'synthetic-v036-frozen-parent', 'source': 'live', 'address': pb.WALLET,
              'window': deepcopy(pb.WINDOW), 'collection_input_hash': freeze_report_inputs(
                  builder.store, pb.WALLET, pb.WINDOW, collected)}
    builder.store.put('reports', report['id'], report)
    pad_to_actual_limit(builder, reference)
    loaded = load_report_inputs(builder.store, report)
    assert loaded['checkpoint'] == checkpoint
    certificate = derive_history_evidence(builder.store, pb.WALLET, pb.WINDOW,
                                          checkpoint=loaded['checkpoint'], collected=loaded)
    assert certificate['source_set']['raw_reference_count'] == 9
    assert certificate['source_set']['authenticated_reference_count'] == 9
    observed = certificate['native_address_metrics']['observed']
    assert observed['wallet_network_fees_sol']['status'] == 'known'
    assert observed['wallet_network_fees_sol']['value'] == '0.000015'
    assert observed['native_wallet_delta_sol']['status'] == 'known'
    assert observed['native_wallet_delta_sol']['value'] == '-0.000015'
    assert builder.store.get('reports', report['id']) == report


@pytest.mark.parametrize('top_level_conflict', [False, True],
                         ids=['mirrored-at-actual-raw-limit', 'top-level-only-conflict'])
def test_actual_rebuild_uses_whole_saved_manifest_without_double_counting_mirrored_links(
        builder, tmp_path, monkeypatch, top_level_conflict):
    import httpx
    from fastapi.testclient import TestClient
    from scanner.app import create_app
    from scanner.accounting import METHODOLOGY
    from scanner.config import STRICT

    checkpoint = deepcopy(builder.cp)
    if top_level_conflict:
        reference = add_alternative(builder, 'opening')
        # The checkpoint list deliberately remains unchanged. Only the saved
        # top-level manifest authenticates this contradictory native archive.
        top_level = deepcopy(checkpoint['evidence']) + [deepcopy(reference)]
    else:
        duplicate = next(ref for ref in checkpoint['evidence'] if ref['kind'] == 'transaction')
        checkpoint['evidence'].extend(deepcopy(duplicate) for _ in
            range(MAX_REFERENCES - len(checkpoint['evidence'])))
        assert len(checkpoint['evidence']) == MAX_REFERENCES
        top_level = deepcopy(checkpoint['evidence'])

    monkeypatch.delenv('HELIUS_API_KEY', raising=False)
    calls = {'provider': 0, 'credential': 0}
    def deny_credential(*args, **kwargs):
        calls['credential'] += 1
        raise AssertionError('No credential reads are permitted in synthetic review')
    async def deny_provider(*args, **kwargs):
        calls['provider'] += 1
        raise AssertionError('No provider requests are permitted in synthetic review')
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(
        get_keyring=lambda: object(), get_password=deny_credential))
    monkeypatch.setattr(httpx.AsyncClient, 'request', deny_provider)
    app = create_app(tmp_path / 'app', 'synthetic-r11-manifest-launch-token')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        response = client.get('/api/bootstrap', headers={
            'x-launch-token': 'synthetic-r11-manifest-launch-token'})
        assert response.status_code == 200
        client.headers['x-csrf-token'] = response.json()['csrf']
        store = app.state.store
        for digest in {ref['hash'] for ref in checkpoint['evidence'] + top_level}:
            assert store.archive(builder.store.evidence(digest)) == digest
        identifier = hashlib.sha256(f'{pb.WALLET}:{pb.START}:{pb.END}'.encode()).hexdigest()
        store.put('collector_checkpoints', identifier, checkpoint)
        window = {key: datetime.fromtimestamp(value, timezone.utc).isoformat()
                  for key, value in pb.WINDOW.items()}
        collected = {'transactions': list(checkpoint['transactions'].values()),
                     'checkpoint': checkpoint, 'evidence': top_level,
                     'snapshot': checkpoint['snapshot'], 'coverage': {'status': 'partial'}}
        parent = {'id': 'synthetic-r11-mirrored-parent', 'scan_id': 'synthetic-r11-scan',
                  'source': 'live', 'address': pb.WALLET, 'window': window,
                  'created_at': '2026-10-03T00:00:00+00:00', 'preset': dict(STRICT),
                  'methodology': METHODOLOGY, 'metrics': {}, 'checks': [],
                  'policy': 'UNRESOLVED', 'evidence_status': 'partial', 'coverage': {},
                  'token_risk': [], 'evidence': top_level,
                  'collection_input_hash': freeze_report_inputs(store, pb.WALLET, window, collected)}
        store.put('reports', parent['id'], parent)
        store.put('scans', parent['scan_id'], {'id': parent['scan_id'], 'status': 'paused',
                  'audit_addresses': [pb.WALLET], 'window': window, 'preset': dict(STRICT),
                  'budget_mode': 'setup-pilot'})
        usage = client.get('/api/state').json()['usage']
        response = client.post('/api/reports/' + parent['id'] + '/rebuild')
        assert response.status_code == 200, response.text
        child = client.get('/api/reports/' + response.json()['report_id']).json()
        assert store.get('reports', parent['id']) == parent
        assert client.get('/api/state').json()['usage'] == usage
        assert calls == {'provider': 0, 'credential': 0}
        assert child['rebuild']['provider_requests'] == 0
        assert child['policy'] == 'UNRESOLVED' and child['qualification']['qualified'] is False
        manifest = store.evidence(child['collection_input_hash'])
        assert manifest['checkpoint']['evidence'] == checkpoint['evidence']
        assert manifest['evidence'] == top_level
        positions = child['coverage']['position_evidence']
        assert positions['counts']['known_closed'] == (0 if top_level_conflict else 1)
        assert positions['positions'][0]['hold_hours']['value'] == (None if top_level_conflict else '6')
        certificate = child['coverage']['history_evidence']
        assert set(certificate['evidence_gates'].values()) == {'UNKNOWN'}
        assert certificate['source_set']['raw_reference_count'] == len(top_level)
        assert certificate['source_set']['complete'] is True
        if top_level_conflict:
            assert reference['hash'] in positions['positions'][0]['sources']
        fees = certificate['native_address_metrics']['observed']['wallet_network_fees_sol']
        assert fees['status'] == 'known' and fees['value'] == '0.000015'


def seed_synthetic_legacy_metadata_report(builder, destination=None):
    """Mirror the legacy report-only metadata shape in a temporary Store."""
    store = destination or builder.store
    checkpoint = deepcopy(builder.cp)
    for digest in {ref['hash'] for ref in checkpoint['evidence']}:
        assert store.archive(builder.store.evidence(digest)) == digest
    identifier = hashlib.sha256(f'{pb.WALLET}:{pb.START}:{pb.END}'.encode()).hexdigest()
    store.put('collector_checkpoints', identifier, checkpoint)
    observation = {'method': 'getAccountInfo', 'address': pb.MINT, 'commitment': 'finalized',
                   'observed_at': '2026-10-03T00:00:00+00:00',
                   'result': {'context': {'slot': 1000}, 'value': None}}
    digest = store.archive(observation)
    metadata = {'kind': 'current-mint-controls', 'hash': digest, 'mint': pb.MINT}
    window = {key: datetime.fromtimestamp(value, timezone.utc).isoformat()
              for key, value in pb.WINDOW.items()}
    report = {'id': 'synthetic-r11-legacy-metadata', 'scan_id': 'synthetic-r11-legacy-scan',
              'source': 'live', 'address': pb.WALLET, 'window': window,
              'created_at': '2026-10-03T00:00:00+00:00', 'preset': {}, 'methodology': 'fifo-v3',
              'metrics': {}, 'events': [], 'checks': [], 'coverage': {}, 'policy': 'UNRESOLVED',
              'evidence_status': 'partial', 'evidence': deepcopy(checkpoint['evidence']) + [metadata],
              'token_risk': [{'mint': pb.MINT, 'observed_at': observation['observed_at'],
                              'context_slot': 1000, 'evidence': [digest]}]}
    from scanner.config import STRICT
    report['preset'] = dict(STRICT)
    store.put('reports', report['id'], report)
    store.put('scans', report['scan_id'], {'id': report['scan_id'], 'status': 'paused',
              'audit_addresses': [pb.WALLET], 'window': window, 'preset': dict(STRICT),
              'budget_mode': 'setup-pilot'})
    return report, checkpoint, metadata


@pytest.mark.parametrize('variant', ['valid', 'masqueraded-transaction', 'wrong-mint',
                                     'wrong-method', 'missing-archive', 'inside-checkpoint',
                                     'missing-risk-citation', 'hybrid-native-envelope',
                                     'missing-value'])
def test_stored_legacy_metadata_exemption_requires_its_actual_archive_and_report_role(builder, variant):
    from scanner.report_rebuild import partition_report_metadata
    report, checkpoint, metadata = seed_synthetic_legacy_metadata_report(builder)
    if variant in ('masqueraded-transaction', 'wrong-mint', 'wrong-method',
                   'hybrid-native-envelope', 'missing-value'):
        payload = (deepcopy(builder.raws[0]) if variant in ('masqueraded-transaction', 'hybrid-native-envelope')
                   else builder.store.evidence(metadata['hash']))
        if variant in ('masqueraded-transaction', 'hybrid-native-envelope'):
            for name in ('preTokenBalances', 'postTokenBalances'):
                row = next(row for row in payload['meta'][name] if row['accountIndex'] == 1)
                row['uiTokenAmount']['amount'] = str(int(row['uiTokenAmount']['amount']) + 200)
            if variant == 'hybrid-native-envelope':
                payload.update(deepcopy(builder.store.evidence(metadata['hash'])))
        elif variant == 'missing-value':
            payload['result'].pop('value')
        elif variant == 'wrong-mint':
            payload['address'] = pb.WSOL
        else:
            payload['method'] = 'getTransaction'
        metadata['hash'] = builder.store.archive(payload)
        report['token_risk'][0]['evidence'] = [metadata['hash']]
    elif variant == 'missing-archive':
        builder.remove_archive(metadata['hash'])
    elif variant == 'inside-checkpoint':
        checkpoint['evidence'].append(deepcopy(metadata))
        identifier = hashlib.sha256(f'{pb.WALLET}:{pb.START}:{pb.END}'.encode()).hexdigest()
        builder.store.put('collector_checkpoints', identifier, checkpoint)
    elif variant == 'missing-risk-citation':
        report['token_risk'] = []
    builder.store.put('reports', report['id'], report)
    original = deepcopy(report)
    # Separation is a filtered inspection view; both original manifests stay
    # exact, and a role present in the native checkpoint is never exempted.
    partition = partition_report_metadata(builder.store, report['evidence'],
        report_id=report['id'], address=pb.WALLET, window=report['window'],
        collector_references=checkpoint['evidence'])
    assert partition['excluded_reference_count'] == (1 if variant == 'valid' else 0)
    assert partition['excluded_unique_link_count'] == (1 if variant == 'valid' else 0)
    receipt = partition['receipts'][0]
    assert receipt['state'] == ('PASS' if variant == 'valid' else 'UNKNOWN')
    if variant == 'valid':
        assert receipt['classification'] == 'report-metadata'
        assert receipt['report_id'] == report['id']
        assert receipt['evidence'] == [metadata['hash']]
    loaded = load_report_inputs(builder.store, report)
    assert loaded['checkpoint'] == checkpoint
    assert loaded['evidence'] == report['evidence']
    certificate = derive_history_evidence(builder.store, pb.WALLET, report['window'],
                                          checkpoint=checkpoint, collected=loaded)
    metric = certificate['native_address_metrics']['observed']['wallet_network_fees_sol']
    assert metric['status'] == ('known' if variant == 'valid' else 'unknown')
    assert metric['value'] == ('0.000015' if variant == 'valid' else None)
    position = derive_position_evidence(builder.store, pb.WALLET, report['window'],
                                       checkpoint=checkpoint, collected=loaded)
    assert position['counts']['known_closed'] == (1 if variant == 'valid' else 0)
    assert builder.store.get('reports', report['id']) == original
    assert set(certificate['evidence_gates'].values()) == {'UNKNOWN'}


@pytest.mark.parametrize('caller_variant', ['unsaved-report', 'altered-citation'])
def test_caller_metadata_claim_does_not_replace_stored_report_authority(builder, caller_variant):
    from scanner.report_rebuild import partition_report_metadata
    report, checkpoint, metadata = seed_synthetic_legacy_metadata_report(builder)
    caller = deepcopy(report)
    if caller_variant == 'unsaved-report':
        caller['id'] = 'synthetic-never-saved-metadata-report'
    else:
        caller['evidence'][-1]['mint'] = pb.WSOL
    result = partition_report_metadata(builder.store, caller['evidence'],
        report_id=caller['id'], address=pb.WALLET, window=caller['window'],
        collector_references=checkpoint['evidence'])
    assert result['excluded_reference_count'] == 0
    assert result['references'] == caller['evidence']


def test_repeated_actual_child_rebuild_preserves_report_metadata_and_native_fee_scope(
        builder, tmp_path, monkeypatch):
    import httpx
    calls = {'provider': 0, 'credential': 0}
    monkeypatch.delenv('HELIUS_API_KEY', raising=False)
    def deny_credential(*args, **kwargs):
        calls['credential'] += 1
        raise AssertionError('No credential reads in synthetic metadata review')
    async def deny_provider(*args, **kwargs):
        calls['provider'] += 1
        raise AssertionError('No provider requests in synthetic metadata review')
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(
        get_keyring=lambda: object(), get_password=deny_credential))
    monkeypatch.setattr(httpx.AsyncClient, 'request', deny_provider)
    with local_session(tmp_path / 'app') as (client, app):
        parent, checkpoint, metadata = seed_synthetic_legacy_metadata_report(builder, app.state.store)
        usage = client.get('/api/state').json()['usage']
        previous = parent
        for _ in range(2):
            original = deepcopy(previous)
            response = client.post('/api/reports/' + previous['id'] + '/rebuild')
            assert response.status_code == 200, response.text
            child = client.get('/api/reports/' + response.json()['report_id']).json()
            assert app.state.store.get('reports', original['id']) == original
            assert client.get('/api/state').json()['usage'] == usage
            assert child['policy'] == 'UNRESOLVED' and child['qualification']['qualified'] is False
            assert child['rebuild']['provider_requests'] == 0
            manifest = app.state.store.evidence(child['collection_input_hash'])
            assert manifest['checkpoint']['evidence'] == checkpoint['evidence']
            assert manifest['evidence'] == parent['evidence']
            assert metadata in child['evidence']
            certificate = child['coverage']['history_evidence']
            fees = certificate['native_address_metrics']['observed']['wallet_network_fees_sol']
            assert fees['status'] == 'known' and fees['value'] == '0.000015'
            assert fees['record_count'] == 3
            assert certificate['source_set']['raw_reference_count'] == len(checkpoint['evidence'])
            assert child['coverage']['position_evidence']['counts']['known_closed'] == 1
            previous = child
        assert calls == {'provider': 0, 'credential': 0}


@pytest.mark.parametrize('metadata_count,native_overflow', [(64, False), (65, False), (1, True)],
                         ids=['complete-64-metadata', 'refuse-65-metadata', 'combined-40001-hashes'])
def test_report_metadata_inspection_obeys_candidate_and_combined_archive_budgets(
        builder, monkeypatch, metadata_count, native_overflow):
    from scanner.report_rebuild import partition_report_metadata
    report, checkpoint, _ = seed_synthetic_legacy_metadata_report(builder)
    report['evidence'] = deepcopy(checkpoint['evidence'])
    report['token_risk'] = []
    for number in range(metadata_count):
        mint = synthetic_address(30000 + number)
        payload = {'method': 'getAccountInfo', 'address': mint, 'commitment': 'finalized',
                   'observed_at': '2026-10-03T00:00:00+00:00',
                   'result': {'context': {'slot': 1000}, 'value': None}}
        digest = builder.store.archive(payload)
        report['evidence'].append({'kind': 'current-mint-controls', 'hash': digest, 'mint': mint})
        report['token_risk'].append({'mint': mint, 'context_slot': 1000, 'evidence': [digest]})
    if native_overflow:
        # Pure link accounting; these synthetic hashes are not asserted to
        # represent available native payloads or a supported metric population.
        hashes = {ref['hash'] for ref in report['evidence']}
        number = 0
        while len(hashes) <= SOURCE_HASH_LIMIT:
            digest = f'{number:064x}'
            number += 1
            if digest in hashes:
                continue
            hashes.add(digest)
            reference = {'kind': 'transaction', 'signature': f'synthetic-budget-{number}', 'hash': digest}
            checkpoint['evidence'].append(reference)
            report['evidence'].append(deepcopy(reference))
        assert len(hashes) == SOURCE_HASH_LIMIT + 1
    builder.store.put('reports', report['id'], report)
    original = deepcopy(report)
    reads = []
    original_read = builder.store.evidence
    def count_read(digest):
        reads.append(digest)
        return original_read(digest)
    monkeypatch.setattr(builder.store, 'evidence', count_read)
    result = partition_report_metadata(builder.store, report['evidence'],
        report_id=report['id'], address=pb.WALLET, window=report['window'],
        collector_references=checkpoint['evidence'])
    allowed = metadata_count == 64 and not native_overflow
    assert result['excluded_reference_count'] == (64 if allowed else 0)
    assert len(result['inspected_hashes']) == len(reads) == (64 if allowed else 0)
    assert len(result['receipts']) == metadata_count
    assert all(receipt['state'] == ('PASS' if allowed else 'UNKNOWN') for receipt in result['receipts'])
    assert builder.store.get('reports', report['id']) == original


@pytest.mark.parametrize('reverse', [False, True], ids=['valid-first', 'wrong-mint-first'])
def test_conflicting_metadata_mint_envelopes_are_not_hidden_by_native_link_dedup(builder, reverse):
    from scanner.report_rebuild import partition_report_metadata
    report, checkpoint, valid = seed_synthetic_legacy_metadata_report(builder)
    invalid = {**deepcopy(valid), 'mint': pb.WSOL}
    pair = [valid, invalid]
    if reverse:
        pair.reverse()
    report['evidence'] = deepcopy(checkpoint['evidence']) + pair
    builder.store.put('reports', report['id'], report)
    partition = partition_report_metadata(builder.store, report['evidence'],
        report_id=report['id'], address=pb.WALLET, window=report['window'],
        collector_references=checkpoint['evidence'])
    assert partition['excluded_reference_count'] == partition['excluded_unique_link_count'] == 1
    assert len(partition['receipts']) == 2
    assert sorted(receipt['state'] for receipt in partition['receipts']) == ['PASS', 'UNKNOWN']
    assert partition['inspected_hashes'] == [valid['hash']]
    assert invalid in partition['references'] and valid not in partition['references']
    loaded = load_report_inputs(builder.store, report)
    assert loaded['evidence'] == report['evidence']
    certificate = derive_history_evidence(builder.store, pb.WALLET, report['window'],
                                          checkpoint=checkpoint, collected=loaded)
    assert certificate['source_set']['state'] == 'UNKNOWN'
    assert certificate['source_set']['invalid_link_count'] == 1
    assert certificate['native_address_metrics']['observed']['wallet_network_fees_sol']['status'] == 'unknown'
    result = derive_position_evidence(builder.store, pb.WALLET, report['window'],
                                      checkpoint=checkpoint, collected=loaded)
    assert result['counts']['known_closed'] == 0
