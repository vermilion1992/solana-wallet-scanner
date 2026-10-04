"""Historical membership admission controls; synthetic development evidence only."""
from copy import deepcopy
import hashlib
import json

import pytest

from scanner.archive_input import canonical_bytes
from scanner.historical_membership import VERSION, derive_historical_membership
from scanner.indexed_input import VERSION as INDEXED_VERSION, convert_indexed_archive, pack_indexed_bytes
from scanner.providers import TOKEN_PROGRAM, TOKEN_2022_PROGRAM
from test_indexed_input import unpack
from test_compiled_instructions import binary_base58
from test_wallet_evidence import base, creation, parsed, record, derive
from test_position_evidence import WALLET, ACCOUNT, MINT, POOL_TOKEN, START, address, transfer


def run(raws, *, alternatives=(), sources=()):
    records = [record(raw) for raw in raws]
    frozen = deepcopy((records, alternatives, sources))
    result = derive_historical_membership(records, all_records=records + list(alternatives),
        wallet=WALLET, raw_sources=sources)
    assert (records, alternatives, sources) == frozen
    assert result['provider_requests'] == result['credential_lookups'] == 0
    assert result['historical_population']['state'] == 'UNKNOWN'
    assert result['version'] == VERSION
    json.dumps(result, allow_nan=False)
    return result


def membership(result, signature='synthetic-operation'):
    return result['transactions'][signature]['accounts'][ACCOUNT]


def change(before=WALLET, after=None, *, inner=False, program=TOKEN_PROGRAM):
    after = after or address(20)
    raw = base(quantity=100)
    for phase, owner in (('preTokenBalances', before), ('postTokenBalances', after)):
        raw['meta'][phase][0]['owner'] = owner
        raw['meta'][phase][0]['programId'] = program
    operation = parsed('setAuthority', {'account': ACCOUNT, 'authorityType': 'accountOwner',
        'authority': before, 'newAuthority': after}, program)
    raw['transaction']['message']['instructions'] = [operation]
    if inner:
        raw['transaction']['message']['instructions'] = [{'programId': 'ComputeBudget111111111111111111111111111111',
                                                         'accounts': [], 'data': ''}]
        raw['meta']['innerInstructions'] = [{'index': 0, 'instructions': [operation]}]
    return raw


@pytest.mark.parametrize('program', [TOKEN_PROGRAM, TOKEN_2022_PROGRAM])
@pytest.mark.parametrize('inner', [False, True])
def test_both_token_programs_outer_and_inner_owner_changes_are_operation_specific(program, inner):
    row = membership(run([change(program=program, inner=inner)]))
    assert row['pre']['wallet_member'] is True and row['post']['wallet_member'] is False
    assert row['endpoint_check']['state'] == row['event_time_check']['state'] == 'PASS'
    assert row['operations'][0]['before']['owner'] == WALLET
    assert row['operations'][0]['after']['owner'] == address(20)
    assert row['operations'][0]['program'] == program
    assert row['operations'][0]['raw_paths'] == [
        'meta.innerInstructions.0.instructions.0' if inner else 'transaction.message.instructions.0']


@pytest.mark.parametrize('program', [TOKEN_PROGRAM, TOKEN_2022_PROGRAM])
@pytest.mark.parametrize('inner', [False, True])
def test_creation_zero_is_not_owned_token_membership_before_initialization(program, inner):
    raw = creation()
    raw['meta']['postTokenBalances'][0]['programId'] = program
    operations = raw['transaction']['message']['instructions']
    operations[0]['parsed']['info']['owner'] = program
    operations[1]['programId'] = program
    if inner:
        raw['transaction']['message']['instructions'] = [{'programId': 'ComputeBudget111111111111111111111111111111',
                                                         'accounts': [], 'data': ''}]
        raw['meta']['innerInstructions'] = [{'index': 0, 'instructions': operations}]
    row = membership(run([raw]))
    assert row['pre']['present'] is False and row['pre']['wallet_member'] is False
    assert row['pre']['owner'] is None and row['post']['owner'] == WALLET
    assert row['operations'][0]['kind'] == 'initializeAccount3'
    assert row['operations'][0]['before']['present'] is False
    assert row['operations'][0]['after']['wallet_member'] is True
    assert row['event_time_check']['state'] == 'PASS'


def test_close_removes_membership_and_does_not_confuse_close_authority_with_owner():
    raw = base()
    raw['meta']['postTokenBalances'] = [row for row in raw['meta']['postTokenBalances'] if row['accountIndex'] != 1]
    raw['meta']['postBalances'][1] = 0
    raw['meta']['postBalances'][0] += 2_000_000
    raw['transaction']['message']['instructions'] = [parsed('closeAccount', {
        'account': ACCOUNT, 'destination': WALLET, 'owner': address(20)})]
    row = membership(run([raw]))
    assert row['pre']['wallet_member'] is True
    assert row['post']['present'] is row['post']['wallet_member'] is False
    assert row['post']['owner'] is None and row['event_time_check']['state'] == 'PASS'


def test_close_authority_change_does_not_change_token_owner_membership():
    raw = base(quantity=100)
    raw['transaction']['message']['instructions'] = [parsed('setAuthority', {
        'account': ACCOUNT, 'authorityType': 'closeAccount', 'authority': WALLET, 'newAuthority': address(20)})]
    row = membership(run([raw]))
    assert row['pre']['owner'] == row['post']['owner'] == WALLET
    assert row['operations'][0]['before']['wallet_member'] is row['operations'][0]['after']['wallet_member'] is True
    assert row['event_time_check']['state'] == 'PASS'


def test_failed_owner_change_is_only_an_attempt_and_keeps_committed_membership():
    raw = change()
    raw['meta']['err'] = {'InstructionError': [0, 'Custom']}
    raw['meta']['postTokenBalances'][0]['owner'] = WALLET
    result = run([raw]); row = membership(result)
    assert row['pre']['owner'] == row['post']['owner'] == WALLET
    assert row['event_time_check']['state'] == 'PASS' and row['operations'] == []
    assert result['transactions']['synthetic-operation']['attempts'][0]['kind'] == 'setAuthority'


@pytest.mark.parametrize('program', [TOKEN_PROGRAM, TOKEN_2022_PROGRAM])
@pytest.mark.parametrize('inner', [False, True])
def test_transient_wallet_ownership_neither_endpoint_is_not_disjoint(program, inner):
    raw = change(address(20), WALLET, program=program)
    raw['meta']['postTokenBalances'][0]['owner'] = address(20)
    raw['transaction']['message']['instructions'].append(parsed('setAuthority', {
        'account': ACCOUNT, 'authorityType': 'accountOwner', 'authority': WALLET, 'newAuthority': address(20)}, program))
    if inner:
        steps = raw['transaction']['message']['instructions']
        raw['transaction']['message']['instructions'] = [{'programId': 'ComputeBudget111111111111111111111111111111',
                                                         'accounts': [], 'data': ''}]
        raw['meta']['innerInstructions'] = [{'index': 0, 'instructions': steps}]
    row = membership(run([raw]))
    assert row['pre']['wallet_member'] is row['post']['wallet_member'] is False
    assert [event['after']['wallet_member'] for event in row['operations']] == [True, False]
    assert row['event_time_check']['state'] == 'PASS'


@pytest.mark.parametrize('variant', ['missing', 'checksum', 'unsupported', 'owner-conflict', 'operation-conflict', 'malformed'])
def test_linked_alternative_gaps_and_restoration_revoke_dependent_membership(variant):
    raw = change(); other = deepcopy(raw)
    if variant == 'missing':
        linked = {'signature': 'synthetic-operation', 'evidence_hash': 'a' * 64, 'raw': None}
    else:
        if variant == 'unsupported':
            other['version'] = 1
        elif variant == 'owner-conflict':
            other['meta']['postTokenBalances'][0]['owner'] = address(21)
            other['transaction']['message']['instructions'][0]['parsed']['info']['newAuthority'] = address(21)
        elif variant == 'operation-conflict':
            other['transaction']['message']['instructions'][0]['parsed']['info']['authority'] = address(21)
        elif variant == 'malformed':
            other['meta']['innerInstructions'] = 'unsupported-shape'
        linked = record(other)
        if variant == 'checksum':
            linked['evidence_hash'] = 'a' * 64
    row = membership(run([raw], alternatives=[linked]))
    assert row['event_time_check']['state'] == 'UNKNOWN'
    assert linked['evidence_hash'] in row['event_time_check']['evidence']
    restored = membership(run([raw], alternatives=[record(deepcopy(raw))]))
    assert restored['event_time_check']['state'] == 'PASS'


def test_conflicting_clock_rejects_external_placement_without_erasing_instruction_membership_or_fees():
    raw = change(); other = deepcopy(raw); other['blockTime'] += 1
    result = run([raw], alternatives=[record(other)])
    assert membership(result)['event_time_check']['state'] == 'PASS'
    assert result['transactions']['synthetic-operation']['clock']['check']['state'] == 'UNKNOWN'
    assert derive([raw], alternatives=[record(other)])['components']['native_fee']['state'] == 'PASS'


def test_missing_fee_does_not_revoke_valid_owner_and_lifecycle_facts():
    raw = change(); raw['meta']['fee'] = None
    assert membership(run([raw]))['event_time_check']['state'] == 'PASS'
    result = derive([raw])
    assert result['components']['native_fee']['state'] == 'UNKNOWN'


def test_malformed_lifecycle_does_not_erase_independently_proved_network_fee():
    raw = change(); del raw['transaction']['message']['instructions'][0]['parsed']['info']['newAuthority']
    assert run([raw])['observed_event_membership']['state'] == 'UNKNOWN'
    assert derive([raw])['components']['native_fee']['state'] == 'PASS'


def test_sibling_disjoint_lifecycle_and_raw_record_permutations_preserve_supported_account():
    raw = change()
    raw['transaction']['message']['instructions'].append(parsed('setAuthority', {
        'account': address(30), 'authorityType': 'accountOwner', 'authority': address(31), 'newAuthority': address(32)}))
    row = membership(run([raw]))
    assert row['event_time_check']['state'] == 'PASS' and len(row['operations']) == 1
    first, second = base('first'), base('second')
    second['slot'] += 1; second['blockTime'] += 1
    left = run([first, second], alternatives=[record(deepcopy(first))])
    right = run([second, first], alternatives=[record(deepcopy(first))])
    assert left == right


def test_matching_sparse_checkpoints_never_certify_intervening_owner_interval():
    first, second = base('first', 100), base('second', 100)
    second['slot'] += 100; second['blockTime'] += 100
    result = run([first, second]); account = result['accounts'][ACCOUNT]
    link = account['checkpoint_links'][0]
    assert link['checkpoint_agreement']['state'] == 'PASS'
    assert link['interval_membership']['state'] == 'UNKNOWN'
    assert account['lifecycle_complete'] is False and account['historical_interval_state'] == 'UNKNOWN'


def test_same_slot_without_archived_order_cannot_make_ordered_checkpoint_link():
    first, second = base('first', 100), base('second', 100)
    result = run([first, second])
    assert result['accounts'][ACCOUNT]['checkpoint_links'][0]['checkpoint_agreement']['state'] == 'UNKNOWN'
    assert membership(result, 'first')['event_time_check']['state'] == 'PASS'


def indexed_archive(raws):
    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'getTransactionsForAddress', 'params': [WALLET, {
        'transactionDetails': 'full', 'encoding': 'jsonParsed', 'sortOrder': 'asc', 'limit': 100,
        'commitment': 'finalized', 'maxSupportedTransactionVersion': 1,
        'filters': {'status': 'any', 'tokenAccounts': 'all', 'blockTime': {'gte': START, 'lt': START + 10000}}}]}
    response = {'jsonrpc': '2.0', 'id': 1, 'result': {'data': raws, 'paginationToken': None}}
    req, res = json.dumps(request, indent=2).encode(), json.dumps(response, indent=2).encode()
    a, b = hashlib.sha256(req).hexdigest(), hashlib.sha256(res).hexdigest()
    manifest = {'version': INDEXED_VERSION, 'address': WALLET,
        'window': {'start': START, 'end': START + 10000},
        'pages': [{'request_hash': a, 'response_hash': b}], 'transactions': []}
    return unpack(convert_indexed_archive(pack_indexed_bytes(manifest, {a: req, b: res})))


def indexed_source(raws):
    ordinary, payloads = indexed_archive(raws)
    link = next(row for row in ordinary['evidence'] if row['kind'] == 'indexed-page')
    return {'kind': 'indexed-page', 'hash': link['hash'], 'payload': payloads[link['hash']]}


def test_exact_indexed_native_alternative_and_preserved_negative_affinity_loss():
    raw = change(); raw['transactionIndex'] = 2
    source = indexed_source([raw])
    assert membership(run([raw], sources=[source]))['event_time_check']['state'] == 'PASS'
    other = deepcopy(raw); other['meta']['postTokenBalances'][0]['owner'] = address(21)
    other['transaction']['message']['instructions'][0]['parsed']['info']['newAuthority'] = address(21)
    alternative = indexed_source([other])
    assert membership(run([raw], sources=[source, alternative]))['event_time_check']['state'] == 'UNKNOWN'
    lost = {'kind': 'query-affinity', 'hash': alternative['hash'], 'signature_hints': ['synthetic-operation'], 'payload': None}
    assert membership(run([raw], sources=[source, lost]))['event_time_check']['state'] == 'UNKNOWN'
    assert membership(run([raw], sources=[source]))['event_time_check']['state'] == 'PASS'


def test_completed_query_and_caller_complete_flags_do_not_prove_historical_population():
    raw = change(); raw['transactionIndex'] = 2
    source = indexed_source([raw]); source['state'] = 'PASS'; source['complete'] = True
    source['historical_population'] = {'state': 'PASS', 'all_accounts': True}
    result = run([raw], sources=[source])
    assert membership(result)['event_time_check']['state'] == 'PASS'
    assert 'accepted_exhaustive_historical_owner_enumeration' in result['historical_population']['dependencies']


def test_invalid_wallet_or_unassignable_selected_record_is_rejected():
    with pytest.raises(ValueError, match='valid public wallet'):
        derive_historical_membership([], all_records=[], wallet='invalid')
    with pytest.raises(ValueError, match='signature identities'):
        derive_historical_membership([{'signature': None}], all_records=[], wallet=WALLET)


def test_checksum_boundaries_are_immutable_and_cited_in_accepted_membership():
    raw = change(); before = canonical_bytes(raw)
    row = membership(run([raw]))
    assert hashlib.sha256(before).hexdigest() in row['event_time_check']['evidence']
    assert canonical_bytes(raw) == before
    assert 'meta.preTokenBalances.0' in row['event_time_check']['raw_paths']
    assert 'transaction.message.instructions.0' in row['event_time_check']['raw_paths']


@pytest.mark.parametrize('transfer_first', [False, True])
@pytest.mark.parametrize('inner', [False, True])
def test_transfer_membership_uses_its_instruction_position_relative_to_owner_change(transfer_first, inner):
    raw = change()
    raw['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '0'
    movement = transfer(ACCOUNT, POOL_TOKEN, 100)
    owner_change = raw['transaction']['message']['instructions'][0]
    steps = [movement, owner_change] if transfer_first else [owner_change, movement]
    if inner:
        raw['transaction']['message']['instructions'] = [{'programId': 'ComputeBudget111111111111111111111111111111',
                                                         'accounts': [], 'data': ''}]
        raw['meta']['innerInstructions'] = [{'index': 0, 'instructions': steps}]
    else:
        raw['transaction']['message']['instructions'] = steps
    row = membership(run([raw]))
    observed = next(step for step in row['instruction_membership'] if step['kind'] == 'token-transfer')
    assert row['event_time_check']['state'] == 'PASS'
    assert observed['before']['wallet_member'] is transfer_first
    assert observed['after']['wallet_member'] is transfer_first


def test_same_endpoints_with_different_transfer_owner_interleaving_are_conflicting():
    raw = change(); raw['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '0'
    raw['transaction']['message']['instructions'].insert(0, transfer(ACCOUNT, POOL_TOKEN, 100))
    other = deepcopy(raw); other['transaction']['message']['instructions'].reverse()
    row = membership(run([raw], alternatives=[record(other)]))
    assert row['endpoint_check']['state'] == 'PASS'
    assert row['event_time_check']['state'] == 'UNKNOWN'
    assert all(step['before']['wallet_member'] is None for step in row['instruction_membership'])


def test_outer_and_inner_equivalent_lifecycle_versions_do_not_conflict_merely_by_representation():
    raw, other = change(), change(inner=True)
    assert membership(run([raw], alternatives=[record(other)]))['event_time_check']['state'] == 'PASS'


def test_invalid_prior_owner_is_not_admitted_by_a_matching_caller_authority_string():
    raw = change(before='invalid-owner', after=WALLET)
    row = membership(run([raw]))
    assert row['endpoint_check']['state'] == row['event_time_check']['state'] == 'UNKNOWN'


def test_same_account_token_program_conflict_cannot_be_relabelled_as_agreeing_owner_facts():
    raw, other = change(), change(program=TOKEN_2022_PROGRAM)
    row = membership(run([raw], alternatives=[record(other)]))
    assert row['endpoint_check']['state'] == row['event_time_check']['state'] == 'UNKNOWN'


def test_indexed_pointer_requires_both_original_pointer_bytes_and_original_page_bytes():
    raw = change(); raw['transactionIndex'] = 2
    manifest, payloads = indexed_archive([raw])
    pointer = manifest['transactions'][0]
    selected = {'signature': 'synthetic-operation', 'evidence_hash': pointer['hash'], 'raw': deepcopy(raw)}
    sources = [{'kind': row['kind'], 'hash': row['hash'], 'payload': payloads[row['hash']]}
               for row in manifest['evidence']]
    if not any(row['hash'] == pointer['hash'] for row in sources):
        sources.append({'kind': 'transaction', 'hash': pointer['hash'], 'payload': payloads[pointer['hash']]})
    result = derive_historical_membership([selected], all_records=[selected], wallet=WALLET, raw_sources=sources)
    assert membership(result)['event_time_check']['state'] == 'PASS'
    assert pointer['hash'] in membership(result)['event_time_check']['evidence']
    missing = [row for row in sources if row['hash'] != pointer['hash']]
    lost = derive_historical_membership([selected], all_records=[selected], wallet=WALLET, raw_sources=missing)
    assert membership(lost)['event_time_check']['state'] == 'UNKNOWN'
    assert selected['raw'] == raw


def test_account_inspection_budget_has_no_arbitrary_certified_prefix(monkeypatch):
    import scanner.wallet_evidence as shared
    monkeypatch.setattr(shared, 'MAX_ACCOUNT_STEPS', 1)
    result = run([base()])
    assert result['observed_event_membership']['state'] == 'UNKNOWN'
    assert result['transactions']['synthetic-operation']['accounts'] == {}


def test_execution_conflict_keeps_owner_endpoints_but_revokes_committed_event_membership():
    raw = base(quantity=100); other = deepcopy(raw)
    other['meta']['err'] = {'InstructionError': [0, 'Custom']}
    row = membership(run([raw], alternatives=[record(other)]))
    assert row['endpoint_check']['state'] == 'PASS'
    assert row['event_time_check']['state'] == 'UNKNOWN'
    assert derive([raw], alternatives=[record(other)])['components']['native_fee']['state'] == 'PASS'


def test_unrelated_explicit_signature_record_does_not_erase_selected_operation_membership():
    raw = change()
    unrelated = {'signature': 'independently-linked-other-signature', 'evidence_hash': 'a' * 64, 'raw': None}
    row = membership(run([raw], alternatives=[unrelated]))
    assert row['event_time_check']['state'] == 'PASS'
    assert 'a' * 64 not in row['event_time_check']['evidence']


@pytest.mark.parametrize('program', [TOKEN_PROGRAM, TOKEN_2022_PROGRAM])
@pytest.mark.parametrize('inner', [False, True])
def test_compiled_owner_bytes_use_shared_normalizer_and_cite_original_fields(program, inner):
    # Pinned SPL/Agave schema: SetAuthority=6, AccountOwner=2, Some=1,
    # followed by the literal 32-byte [20;32] new owner. No production table
    # produces this test payload or its expected owner/address.
    raw = change(program=program)
    compiled = {'programId': program, 'accounts': [ACCOUNT, WALLET],
                'data': binary_base58('060201' + '14' * 32)}
    raw['transaction']['message']['header'] = {'numRequiredSignatures': 1,
        'numReadonlySignedAccounts': 0, 'numReadonlyUnsignedAccounts': 1}
    raw['transaction']['message']['accountKeys'].append(program)
    raw['meta']['preBalances'].append(0); raw['meta']['postBalances'].append(0)
    if inner:
        raw['transaction']['message']['accountKeys'].append('ComputeBudget111111111111111111111111111111')
        raw['transaction']['message']['header']['numReadonlyUnsignedAccounts'] = 2
        raw['meta']['preBalances'].append(0); raw['meta']['postBalances'].append(0)
        raw['transaction']['message']['instructions'] = [{'programId': 'ComputeBudget111111111111111111111111111111',
                                                         'accounts': [], 'data': ''}]
        raw['meta']['innerInstructions'] = [{'index': 0, 'instructions': [compiled]}]
        prefix = 'meta.innerInstructions.0.instructions.0'
    else:
        raw['transaction']['message']['instructions'] = [compiled]
        prefix = 'transaction.message.instructions.0'
    row = membership(run([raw]))
    assert row['event_time_check']['state'] == 'PASS'
    assert row['operations'][0]['after']['owner'] == address(20)
    assert prefix + '.data' in row['operations'][0]['raw_paths']
    assert not any('.parsed' in path for path in row['operations'][0]['raw_paths'])


def test_account_union_alternative_cartesian_budget_admits_no_prefix_and_keeps_fees(monkeypatch):
    import scanner.wallet_evidence as shared
    raws = [base() for _ in range(4)]
    for index, raw in enumerate(raws):
        raw['transaction']['message']['accountKeys'][1] = ACCOUNT if index == 0 else address(30 + index)
        for phase in ('preTokenBalances', 'postTokenBalances'):
            raw['meta'][phase] = [row for row in raw['meta'][phase] if row['accountIndex'] == 1]
    monkeypatch.setattr(shared, 'MAX_ACCOUNT_STEPS', 10)
    result = run([raws[0]], alternatives=[record(raw) for raw in raws[1:]])
    assert result['transactions']['synthetic-operation']['accounts'] == {}
    assert result['observed_event_membership']['state'] == 'UNKNOWN'
    assert 'complete_account_version_inspection' in result['transactions']['synthetic-operation']['check']['dependencies']
    assert derive([raws[0]], alternatives=[record(raw) for raw in raws[1:]])['components']['native_fee']['state'] == 'PASS'


@pytest.mark.parametrize('bad', ['unsupported-version', 'missing-meta', 'malformed-authority'])
@pytest.mark.parametrize('linked', [False, True])
def test_unassignable_source_revokes_membership_census_without_erasing_independent_accounts(bad, linked):
    known = change()
    neutral = base()
    neutral['transaction']['signatures'] = ['second-source']
    neutral['slot'], neutral['blockTime'] = 101, START + 3600
    neutral['meta']['preTokenBalances'] = neutral['meta']['postTokenBalances'] = []
    neutral['transaction']['message']['instructions'] = []
    broken = deepcopy(neutral)
    if bad == 'unsupported-version':
        broken['version'] = 1
    elif bad == 'missing-meta':
        broken['meta'] = None
    else:
        broken['transaction']['message']['instructions'] = [parsed('setAuthority', {
            'authority': WALLET, 'authorityType': 'accountOwner', 'newAuthority': address(20)})]
    parent = run([known, neutral])
    assert parent['observed_event_membership']['state'] == 'PASS'
    result = run([known, neutral if linked else broken], alternatives=[record(broken)] if linked else [])
    assert result['observed_event_membership']['state'] == 'UNKNOWN'
    assert 'complete_selected_operation_inspection' in result['observed_event_membership']['dependencies']
    assert membership(result)['event_time_check']['state'] == 'PASS'
    assert run([known, neutral]) == parent
