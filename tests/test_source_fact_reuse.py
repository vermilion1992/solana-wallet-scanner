"""Invocation-local reuse controls; all inputs are unsigned development data.

Literal opcode 3 plus a little-endian u64 is the pinned SPL Transfer schema in
tests/fixtures/compiled_instructions/spl-token-interface-instruction.rs. These
records test the existing semantic assessor, not genuine history completeness.
"""
from copy import deepcopy
import hashlib
import json
from unittest.mock import patch

import pytest

import scanner.compiled_instructions as compiled
import scanner.source_consistency as consistency
from scanner.providers import TOKEN_PROGRAM, TOKEN_2022_PROGRAM


WALLET = '4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi'
POOL = '8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR'
MINT = 'GgBaCs3NCBuZN12kCJgAW63ydqohFkHEdfdEXBPzLHq'
SIGNATURE = 'unsigned-source-reuse-development-case'


def base58(payload):
    alphabet, value, encoded = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz', int.from_bytes(payload, 'big'), ''
    while value:
        value, remainder = divmod(value, 58)
        encoded = alphabet[remainder] + encoded
    return '1' * (len(payload) - len(payload.lstrip(b'\x00'))) + encoded


def development_record(count=8, *, binary=True):
    accounts = [base58((100 + index).to_bytes(32, 'big')) for index in range(count)]
    keys = [WALLET, POOL, *accounts, TOKEN_PROGRAM, TOKEN_2022_PROGRAM]
    instructions = []
    for index, account in enumerate(accounts):
        program = TOKEN_PROGRAM if index % 2 == 0 else TOKEN_2022_PROGRAM
        if binary:
            instruction = {'programIdIndex': len(keys) - 2 + index % 2,
                           'accounts': [1, index + 2, 0],
                           'data': base58(b'\x03' + (100).to_bytes(8, 'little'))}
        else:
            instruction = {'programId': program, 'parsed': {'type': 'transfer', 'info': {
                'source': POOL, 'destination': account, 'authority': WALLET, 'amount': '100'}}}
        instructions.append(instruction)
    def balances(amount):
        return [{'accountIndex': index + 2, 'owner': WALLET, 'mint': MINT,
                 'uiTokenAmount': {'amount': str(amount), 'decimals': 6}}
                for index in range(count)]
    before = [1_000_000] + [2000] * (len(keys) - 1)
    after = [995_000] + [2000] * (len(keys) - 1)
    split = max(1, count // 2)
    return {'version': 0, 'slot': 100, 'blockTime': 1000,
            'transaction': {'signatures': [SIGNATURE], 'message': {
                'accountKeys': keys, 'header': {'numRequiredSignatures': 1,
                'numReadonlySignedAccounts': 0, 'numReadonlyUnsignedAccounts': 2},
                'instructions': instructions[:split]}},
            'meta': {'err': None, 'fee': 5000, 'preBalances': before,
                     'postBalances': after, 'preTokenBalances': balances(0),
                     'postTokenBalances': balances(100),
                     'innerInstructions': [{'index': 0, 'instructions': instructions[split:]}]}}, accounts


def linked(raw):
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'signature': SIGNATURE, 'evidence_hash': digest, 'raw': raw}


def assess(records, accounts):
    return consistency.assess_source_consistency(records, accounts={SIGNATURE: accounts}, wallet=WALLET)


def scenario(name):
    raw, accounts = development_record()
    if name == 'parsed':
        raw, accounts = development_record(binary=False)
    elif name == 'unsupported-format':
        raw['version'] = 1
    elif name == 'failed-compiled':
        raw['meta']['err'] = {'InstructionError': [0, 'Custom']}
        raw['meta']['postTokenBalances'] = deepcopy(raw['meta']['preTokenBalances'])
    elif name == 'failed-parsed':
        raw, accounts = development_record(binary=False)
        raw['meta']['err'] = {'InstructionError': [0, 'Custom']}
        raw['meta']['postTokenBalances'] = deepcopy(raw['meta']['preTokenBalances'])
    elif name == 'malformed-instruction':
        raw['transaction']['message']['instructions'][0]['data'] = '0'
    elif name == 'conflicting-program-identity':
        raw['transaction']['message']['instructions'][0]['programId'] = TOKEN_2022_PROGRAM
    elif name == 'duplicate-balance':
        raw['meta']['preTokenBalances'].append(deepcopy(raw['meta']['preTokenBalances'][0]))
    elif name == 'invalid-balance-index':
        raw['meta']['preTokenBalances'].append({'accountIndex': 999})
    elif name == 'missing-quantity':
        raw['meta']['preTokenBalances'][0]['uiTokenAmount'].pop('amount')
    elif name == 'duplicate-keys':
        raw['transaction']['message']['accountKeys'][1] = accounts[0]
    elif name == 'malformed-inner-association':
        raw['meta']['innerInstructions'][0]['index'] = 999
    elif name == 'malformed-participants':
        raw, accounts = development_record(binary=False)
        raw['transaction']['message']['instructions'][0]['parsed']['info']['source'] = ['unassignable']
        raw['transaction']['message']['instructions'][0]['parsed']['info']['account'] = {'unassignable': True}
    elif name == 'instruction-budget':
        raw['transaction']['message']['instructions'] += [
            {'programId': 'unreviewed-program', 'parsed': {'info': {}}} for _ in range(10001)]
    elif name != 'compiled':
        raise ValueError(name)
    return raw, accounts


SCENARIOS = ('compiled', 'parsed', 'unsupported-format', 'failed-compiled', 'failed-parsed',
             'malformed-instruction', 'conflicting-program-identity', 'duplicate-balance',
             'invalid-balance-index', 'missing-quantity', 'duplicate-keys',
             'malformed-inner-association', 'malformed-participants', 'instruction-budget')


@pytest.mark.parametrize('name', SCENARIOS)
def test_reuse_retains_complete_unindexed_semantic_result(name):
    raw, accounts = scenario(name)
    records, before = [linked(raw)], deepcopy(raw)
    reused = assess(records, accounts)
    # The standalone account path deliberately remains available. Disabling
    # only preparation compares every fact, raw path, dependency and status.
    with patch.object(consistency, '_prepare_record_facts', return_value=None):
        unindexed = assess(records, accounts)
    assert reused == unindexed
    assert raw == before


@pytest.mark.parametrize('count', (1, 8, 32, 96))
def test_compiled_normalization_and_key_resolution_are_bounded_per_variant(count):
    raw, accounts = development_record(count)
    with patch.object(compiled, 'normalize_transaction', wraps=compiled.normalize_transaction) as normalize:
        with patch.object(consistency, '_keys', wraps=consistency._keys) as keys:
            result = assess([linked(raw)], accounts)
    assert result['state'] == 'PASS'
    assert normalize.call_count == 1
    assert keys.call_count == 2  # Account scope and independent native projection.
    assert len(result['transactions'][SIGNATURE]['accounts']) == count
    for index, account in enumerate(accounts):
        checks = result['transactions'][SIGNATURE]['accounts'][account]['checks']
        assert checks['pre_quantity']['facts'][0]['value'] == '0'
        assert checks['post_quantity']['facts'][0]['value'] == '100'
        program = TOKEN_PROGRAM if index % 2 == 0 else TOKEN_2022_PROGRAM
        assert {fact['value'] for fact in checks['program']['facts']} == {program}
        assert any(fact['path'].endswith('.data') for fact in checks['program']['facts'])
        assert all('.parsed.' not in fact['path'] for fact in checks['program']['facts'])


def test_parsed_records_use_original_paths_without_normalization():
    raw, accounts = development_record(32, binary=False)
    with patch.object(compiled, 'normalize_transaction', wraps=compiled.normalize_transaction) as normalize:
        result = assess([linked(raw)], accounts)
    assert result['state'] == 'PASS'
    assert normalize.call_count == 0
    facts = [fact for account in result['transactions'][SIGNATURE]['accounts'].values()
             for fact in account['checks']['program']['facts']]
    assert all(fact['path'].endswith('.programId') for fact in facts)
    assert any(fact['path'].startswith('meta.innerInstructions.') for fact in facts)


def test_selected_and_alternative_variants_are_separate_and_permutation_invariant():
    raw, accounts = development_record(32)
    alternative = deepcopy(raw)
    alternative['meta']['optionalProviderField'] = {'not-a-semantic-fact': True}
    records = [linked(raw), linked(alternative)]
    with patch.object(compiled, 'normalize_transaction', wraps=compiled.normalize_transaction) as normalize:
        result = assess(records, accounts)
    assert normalize.call_count == 2
    assert result['state'] == 'PASS'
    assert result == assess(records[::-1], accounts[::-1])
    repeated = assess(records + records, accounts)
    assert repeated['state'] == 'PASS'
    assert repeated['source_set']['raw_reference_count'] == 4
    assert result['source_set']['raw_reference_count'] == 2
    for account in accounts:
        ordinary = result['transactions'][SIGNATURE]['accounts'][account]
        duplicate = repeated['transactions'][SIGNATURE]['accounts'][account]
        assert ordinary['native_hashes'] == duplicate['native_hashes']
        assert {field: row for field, row in ordinary['checks'].items() if field != 'source_set'} == {
            field: row for field, row in duplicate['checks'].items() if field != 'source_set'}
    account = result['transactions'][SIGNATURE]['accounts'][accounts[0]]
    assert account['native_hashes'] == sorted(record['evidence_hash'] for record in records)
    assert {fact['hash'] for fact in account['checks']['program']['facts']} == set(account['native_hashes'])


@pytest.mark.parametrize('field,value', (('quantity', '101'), ('mint', POOL), ('program', TOKEN_2022_PROGRAM)))
def test_alternative_conflicts_keep_exact_hash_dependencies(field, value):
    raw, accounts = development_record()
    alternative = deepcopy(raw)
    if field == 'quantity':
        alternative['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = value
        check_name = 'post_quantity'
    elif field == 'mint':
        alternative['meta']['preTokenBalances'][0]['mint'] = value
        check_name = 'mint'
    else:
        alternative['transaction']['message']['instructions'][0]['programIdIndex'] += 1
        check_name = 'program'
    records = [linked(raw), linked(alternative)]
    result = assess(records, accounts)
    scoped = result['transactions'][SIGNATURE]['accounts'][accounts[0]]
    assert scoped['checks'][check_name]['status'] == 'conflict'
    assert scoped['checks'][check_name]['evidence'] == sorted(record['evidence_hash'] for record in records)
    assert result['transactions'][SIGNATURE]['accounts'][accounts[1]]['state'] == 'PASS'
    assert result['transactions'][SIGNATURE]['native']['wallet_network_fees_sol']['state'] == 'PASS'


def test_source_loss_revokes_dependent_results_and_restore_is_exact():
    raw, accounts = development_record()
    alternative = deepcopy(raw)
    alternative['meta']['optionalProviderField'] = 'independent-original-bytes'
    original = [linked(raw), linked(alternative)]
    parent = assess(original, accounts)
    parent_bytes = json.dumps(parent, sort_keys=True)
    unavailable = [original[0], {**original[1], 'raw': None}]
    child = assess(unavailable, accounts)
    assert child['state'] == 'UNKNOWN'
    assert child['transactions'][SIGNATURE]['accounts'][accounts[0]]['state'] == 'UNKNOWN'
    assert child['transactions'][SIGNATURE]['native']['wallet_network_fees_sol']['state'] == 'UNKNOWN'
    assert original[1]['evidence_hash'] in child['transactions'][SIGNATURE]['evidence']
    assert assess(original, accounts) == parent
    assert json.dumps(parent, sort_keys=True) == parent_bytes


def test_mutation_between_assessments_never_reuses_an_object_identity_cache():
    raw, accounts = development_record()
    record = linked(raw)
    first = assess([record], accounts)
    raw['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '999'
    raw['transaction']['message']['instructions'][0]['programIdIndex'] += 1
    second = assess([record], accounts)
    # Retaining the same caller link and Python object is an adversarial cache
    # control, not a claim that altered bytes validate an immutable archive.
    first_checks = first['transactions'][SIGNATURE]['accounts'][accounts[0]]['checks']
    second_checks = second['transactions'][SIGNATURE]['accounts'][accounts[0]]['checks']
    assert first_checks['post_quantity']['facts'][0]['value'] == '100'
    assert second_checks['post_quantity']['facts'][0]['value'] == '999'
    assert {fact['value'] for fact in first_checks['program']['facts']} == {TOKEN_PROGRAM}
    assert {fact['value'] for fact in second_checks['program']['facts']} == {TOKEN_2022_PROGRAM}


def test_no_account_scope_does_not_create_an_instruction_view():
    raw, _accounts = development_record()
    raw['meta']['preTokenBalances'] = []
    raw['meta']['postTokenBalances'] = []
    with patch.object(compiled, 'normalize_transaction', wraps=compiled.normalize_transaction) as normalize:
        result = consistency.assess_source_consistency([linked(raw)], wallet=WALLET)
    assert normalize.call_count == 0
    assert result['state'] == 'PASS'
    assert result['transactions'][SIGNATURE]['accounts'] == {}


def test_reused_program_facts_remain_independent_mutable_output_rows():
    raw, accounts = development_record(binary=False)
    raw['transaction']['message']['instructions'][0]['parsed']['info']['source'] = accounts[1]
    before = deepcopy(raw)
    result = assess([linked(raw)], accounts)
    scopes = result['transactions'][SIGNATURE]['accounts']
    left = scopes[accounts[0]]['checks']['program']['facts'][0]
    right = next(fact for fact in scopes[accounts[1]]['checks']['program']['facts'] if fact['path'] == left['path'])
    assert left == right
    assert left is not right
    left['value'] = 'caller-modified-output'
    assert right['value'] == TOKEN_PROGRAM
    assert raw == before
