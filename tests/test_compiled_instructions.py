"""Independent pinned binary/schema controls; fixtures are unsigned development data."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scanner.compiled_instructions import (
    CompiledInstructionError, normalize_instruction, normalize_transaction,
    resolve_account_keys, key_roles,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / 'tests/fixtures/compiled_instructions/schema.json').read_text())
# Literal public keys corresponding to pinned Rust [1;32] / [2;32] / [4;32].
KEYS = {
    'source': '4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi',
    'destination': '8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR',
    'mint': 'CktRuQ2mttgRGkXJtyksdKHjUdc2C4TgDzyB98oEzy8',
    'authority': 'GgBaCs3NCBuZN12kCJgAW63ydqohFkHEdfdEXBPzLHq',
    'rent': 'SysvarRent111111111111111111111111111111111',
    'recent': 'SysvarRecentB1ockHashes11111111111111111111',
    'system': '11111111111111111111111111111111',
    'token': 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
    'token2022': 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb',
    'associated': 'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL',
}


def binary_base58(hexadecimal):
    """Test transport encoder, independent of production normalization/tables."""
    payload = bytes.fromhex(hexadecimal)
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number = int.from_bytes(payload, 'big')
    encoded = ''
    while number:
        number, remainder = divmod(number, 58)
        encoded = alphabet[remainder] + encoded
    return '1' * (len(payload) - len(payload.lstrip(b'\x00'))) + encoded


def expected(value):
    if isinstance(value, str):
        return KEYS.get(value, value)
    if isinstance(value, dict):
        return {key: expected(item) for key, item in value.items()}
    return value


def compiled(case):
    return {'programId': KEYS[case['program']],
            'accounts': [KEYS[item] for item in case['accounts']],
            'data': binary_base58(case['hex'])}


def transaction(instruction, *, version='legacy', inner=None):
    return {'version': version, 'slot': 30, 'blockTime': 1700000000,
            'transaction': {'signatures': ['fixture-not-a-signed-transaction'], 'message': {
                'accountKeys': [KEYS['authority'], KEYS['source'], KEYS['destination'], KEYS['mint'], KEYS['token']],
                'header': {'numRequiredSignatures': 1, 'numReadonlySignedAccounts': 0,
                           'numReadonlyUnsignedAccounts': 1}, 'instructions': [instruction]}},
            'meta': {'err': None, 'fee': 5000, 'innerInstructions': inner}}


@pytest.mark.parametrize('reference', SCHEMA['references'], ids=lambda ref: ref['name'])
def test_primary_schema_files_are_checksum_pinned(reference):
    assert hashlib.sha256((ROOT / reference['local_path']).read_bytes()).hexdigest() == reference['sha256']


@pytest.mark.parametrize('case', SCHEMA['examples'], ids=lambda case: case['id'])
def test_independent_binary_examples_match_primary_rpc_field_names(case):
    instruction = compiled(case)
    before = deepcopy(instruction)
    output = normalize_instruction(instruction, list(KEYS.values()), signers=set(KEYS.values()), path='raw.ix')
    assert output['instruction']['parsed'] == {'type': case['kind'], 'info': expected(case['info'])}
    assert output['instruction']['programId'] == KEYS[case['program']]
    assert not any(field in output['instruction'] for field in ('programIdIndex', 'accounts', 'data'))
    assert output['normalization']['path'] == 'raw.ix'
    assert 'raw.ix.data' in output['normalization']['raw_paths']
    assert instruction == before


@pytest.mark.parametrize('case', [case for case in SCHEMA['examples'] if case['program'] == 'token'], ids=lambda case: case['id'])
def test_token2022_base_payload_is_distinct_from_extension_support(case):
    instruction = compiled(case)
    instruction['programId'] = KEYS['token2022']
    output = normalize_instruction(instruction, list(KEYS.values()), signers=set(KEYS.values()))
    assert output['instruction']['program'] == 'spl-token-2022'
    assert output['instruction']['parsed'] == {'type': case['kind'], 'info': expected(case['info'])}


@pytest.mark.parametrize('hexadecimal', ['0301000000000000', '03010000000000000000', '0500', '1202', '060201', '06020000'])
def test_truncated_and_trailing_binary_payloads_remain_dependencies(hexadecimal):
    instruction = {'programId': KEYS['token'], 'accounts': [KEYS['source'], KEYS['destination'], KEYS['authority']],
                   'data': binary_base58(hexadecimal)}
    with pytest.raises(CompiledInstructionError) as caught:
        normalize_instruction(instruction, list(KEYS.values()), signers=set(KEYS.values()), path='raw.ix')
    assert caught.value.code == 'unsupported-layout'
    assert caught.value.paths == ['raw.ix.data']


@pytest.mark.parametrize('data', ['', '0', 'O', 'I', 'l', '😀', None, ['3'], 3, '1' * 3000])
def test_invalid_or_oversized_base58_is_typed(data):
    instruction = {'programId': KEYS['token'], 'accounts': [], 'data': data}
    with pytest.raises(CompiledInstructionError) as caught:
        normalize_instruction(instruction, list(KEYS.values()), signers=set(KEYS.values()), path='raw.ix')
    assert caught.value.code == 'invalid-base58'


@pytest.mark.parametrize('program,hexadecimal', [('token', 'ff'), ('token', '1a'), ('token', '07' + '00' * 8),
                                               ('token', '15'), ('system', '03000000'), ('system', 'ffffffff')])
def test_unreviewed_opcodes_do_not_fall_back_to_balance_inference(program, hexadecimal):
    with pytest.raises(CompiledInstructionError) as caught:
        normalize_instruction({'programId': KEYS[program], 'accounts': [], 'data': binary_base58(hexadecimal)},
                              list(KEYS.values()), signers=set(KEYS.values()))
    # Opcode21 now has a pinned read-only getter adapter, but this original
    # negative still supplies no required mint account and remains rejected.
    assert caught.value.code == ('unsupported-account-arity' if program == 'token' and hexadecimal == '15' else 'unsupported-opcode')


def test_standard_authority_discriminants_and_one_byte_option():
    for tag, name, target in ((0, 'mintTokens', 'mint'), (1, 'freezeAccount', 'mint'),
                              (2, 'accountOwner', 'account'), (3, 'closeAccount', 'account')):
        output = normalize_instruction({'programId': KEYS['token'], 'accounts': [KEYS['source'], KEYS['authority']],
                                        'data': binary_base58(f'06{tag:02x}00')},
                                       list(KEYS.values()), signers={KEYS['authority']})
        info = output['instruction']['parsed']['info']
        assert info[target] == KEYS['source']
        assert info['authorityType'] == name
        assert info['newAuthority'] is None
    for hexadecimal in ('060400', '060202', '060100000000'):
        with pytest.raises(CompiledInstructionError):
            normalize_instruction({'programId': KEYS['token'], 'accounts': [KEYS['source'], KEYS['authority']],
                                   'data': binary_base58(hexadecimal)}, list(KEYS.values()), signers={KEYS['authority']})


@pytest.mark.parametrize('accounts', [[1, KEYS['destination'], 0], [1, 2, True], [1, 2, -1], [1, 2, 256], [1, 2, 7], [1, 2]])
def test_malformed_mixed_out_of_bounds_and_missing_accounts(accounts):
    with pytest.raises(CompiledInstructionError):
        normalize_instruction({'programIdIndex': 4, 'accounts': accounts, 'data': binary_base58('030100000000000000')},
                              [KEYS[k] for k in ('authority', 'source', 'destination', 'mint', 'token')],
                              signers={KEYS['authority']})


def test_dual_program_identity_must_match_and_alias_cannot_override_it():
    keys = [KEYS['authority'], KEYS['source'], KEYS['destination'], KEYS['mint'], KEYS['token']]
    instruction = {'programIdIndex': 4, 'programId': KEYS['token'], 'accounts': [1, 2, 0],
                   'data': binary_base58('030100000000000000')}
    assert normalize_instruction(instruction, keys, signers={KEYS['authority']})['instruction']['parsed']['type'] == 'transfer'
    instruction['programId'] = KEYS['system']
    with pytest.raises(CompiledInstructionError) as caught:
        normalize_instruction(instruction, keys, signers={KEYS['authority']})
    assert caught.value.code == 'conflicting-program'
    instruction.pop('programId')
    instruction['program'] = 'system'
    with pytest.raises(CompiledInstructionError) as caught:
        normalize_instruction(instruction, keys, signers={KEYS['authority']})
    assert caught.value.code == 'conflicting-program'


def test_outer_required_signer_is_checked_but_cpi_pda_is_not_a_message_signer():
    instruction = {'programId': KEYS['token'], 'accounts': [KEYS['source'], KEYS['destination'], KEYS['authority']],
                   'data': binary_base58('030100000000000000')}
    with pytest.raises(CompiledInstructionError) as caught:
        normalize_instruction(instruction, list(KEYS.values()), signers={KEYS['source']})
    assert caught.value.code == 'missing-required-signer'
    output = normalize_instruction(instruction, list(KEYS.values()), signers={KEYS['source']}, inner=True)
    assert output['normalization']['signer_evidence'] == 'runtime-cpi-not-message-signers'
    assert output['normalization']['required_signer_roles'] == [KEYS['authority']]


def test_classic_multisig_rpc_names_and_independent_threshold_limitation():
    instruction = {'programId': KEYS['token'], 'accounts': [KEYS['source'], KEYS['destination'], KEYS['mint'], KEYS['authority']],
                   'data': binary_base58('030100000000000000')}
    output = normalize_instruction(instruction, list(KEYS.values()), signers={KEYS['authority']})
    assert output['instruction']['parsed']['info']['multisigAuthority'] == KEYS['mint']
    assert output['instruction']['parsed']['info']['signers'] == [KEYS['authority']]
    instruction['programId'] = KEYS['token2022']
    with pytest.raises(CompiledInstructionError) as caught:
        normalize_instruction(instruction, list(KEYS.values()), signers={KEYS['authority']})
    assert caught.value.code == 'unsupported-extension-accounts'


def test_v0_loaded_keys_are_resolved_once_in_protocol_order():
    instruction = {'programIdIndex': 4, 'accounts': [2, 5, 3, 0], 'data': binary_base58('0c010000000000000002')}
    raw = transaction(instruction, version=0)
    raw['transaction']['message']['accountKeys'] = [KEYS['authority'], KEYS['system']]
    raw['transaction']['message']['addressTableLookups'] = [{'accountKey': KEYS['mint'], 'writableIndexes': [10, 11], 'readonlyIndexes': [15, 16]}]
    raw['meta']['loadedAddresses'] = {'writable': [KEYS['source'], KEYS['destination']], 'readonly': [KEYS['token'], KEYS['mint']]}
    before = deepcopy(raw)
    output = normalize_transaction(raw)
    assert output['issues'] == []
    info = output['raw']['transaction']['message']['instructions'][0]['parsed']['info']
    assert (info['source'], info['destination'], info['mint'], info['authority']) == tuple(KEYS[k] for k in ('source', 'destination', 'mint', 'authority'))
    context = resolve_account_keys(raw)
    assert context['keys'] == [KEYS[k] for k in ('authority', 'system', 'source', 'destination', 'token', 'mint')]
    roles = key_roles(raw)['keys']
    assert [item['signer'] for item in roles] == [True, False, False, False, False, False]
    assert [item['writable'] for item in roles] == [True, False, True, True, False, False]
    assert raw == before


@pytest.mark.parametrize('mutation,code', [('missing-header', 'missing-signers'), ('bool-header', 'invalid-header'),
                                         ('wrong-program', 'invalid-program-index'), ('missing-loaded', 'missing-loaded-keys'),
                                         ('wrong-loaded-count', 'conflicting-loaded-keys'), ('duplicate-key', 'invalid-account-keys')])
def test_transaction_key_and_header_dependencies_are_typed(mutation, code):
    raw = transaction({'programIdIndex': 4, 'accounts': [1, 2, 0], 'data': binary_base58('030100000000000000')}, version=0)
    message = raw['transaction']['message']
    if mutation == 'missing-header':
        message.pop('header')
    elif mutation == 'bool-header':
        message['header']['numRequiredSignatures'] = True
    elif mutation == 'wrong-program':
        message['instructions'][0]['programIdIndex'] = True
    elif mutation in ('missing-loaded', 'wrong-loaded-count'):
        message['addressTableLookups'] = [{'accountKey': KEYS['mint'], 'writableIndexes': [0], 'readonlyIndexes': []}]
        if mutation == 'wrong-loaded-count':
            raw['meta']['loadedAddresses'] = {'writable': [], 'readonly': []}
    else:
        message['accountKeys'][2] = message['accountKeys'][1]
    before = deepcopy(raw)
    output = normalize_transaction(raw)
    assert code in [issue['code'] for issue in output['issues']]
    assert raw == before


def test_outer_and_inner_normalizations_retain_original_coordinate_paths():
    instruction = {'programIdIndex': 4, 'accounts': [1, 2, 0], 'data': binary_base58('030100000000000000')}
    raw = transaction(instruction, inner=[{'index': 0, 'instructions': [deepcopy(instruction)]}])
    output = normalize_transaction({'jsonrpc': '2.0', 'result': raw, 'id': 'fixture'})
    assert output['issues'] == []
    assert [receipt['path'] for receipt in output['normalizations']] == ['transaction.message.instructions.0', 'meta.innerInstructions.0.instructions.0']
    assert output['raw']['result']['meta']['innerInstructions'][0]['instructions'][0]['parsed']['info']['amount'] == '1'
    assert 'data' in raw['meta']['innerInstructions'][0]['instructions'][0]


@pytest.mark.parametrize('index', [True, -1, 1, [], None])
def test_malformed_inner_association_never_disappears(index):
    instruction = {'programIdIndex': 4, 'accounts': [1, 2, 0], 'data': binary_base58('030100000000000000')}
    raw = transaction(instruction, inner=[{'index': index, 'instructions': [deepcopy(instruction)]}])
    output = normalize_transaction(raw)
    assert 'invalid-inner-association' in [issue['code'] for issue in output['issues']]
    assert output['raw']['meta']['innerInstructions'][0]['instructions'][0] == instruction


def test_duplicate_inner_groups_remain_explicit_and_failed_fees_are_not_erased():
    instruction = {'programIdIndex': 4, 'accounts': [1, 2, 0], 'data': binary_base58('030100000000000000')}
    raw = transaction(instruction, inner=[{'index': 0, 'instructions': []}, {'index': 0, 'instructions': []}])
    assert normalize_transaction(raw)['issues'][0]['code'] == 'invalid-inner-association'
    raw['meta']['err'] = {'InstructionError': [0, 'Custom']}
    raw['transaction']['message']['accountKeys'] = []
    output = normalize_transaction(raw)
    assert output['issues'] == []
    assert output['normalizations'] == []
    assert output['raw'] == raw
    assert output['raw']['meta']['fee'] == 5000


def test_parsed_instruction_is_unchanged_without_new_header_requirement():
    instruction = {'program': 'spl-token', 'programId': KEYS['token'],
                   'parsed': {'type': 'transfer', 'info': {'source': KEYS['source'], 'destination': KEYS['destination'], 'amount': '1'}}}
    raw = transaction(instruction)
    raw['transaction']['message'].pop('header')
    output = normalize_transaction(raw)
    assert output['raw'] == raw
    assert output['issues'] == []
    assert output['normalizations'] == []


def test_mixed_parsed_opaque_view_is_never_admitted():
    instruction = {'programIdIndex': 4, 'accounts': [1, 2, 0], 'data': binary_base58('030100000000000000'),
                   'parsed': {'type': 'transfer', 'info': {'amount': '999'}}}
    raw = transaction(instruction)
    output = normalize_transaction(raw)
    assert output['issues'][0]['code'] == 'mixed-representation'
    assert output['raw'] == raw


def test_selected_alternative_views_are_independent_and_loss_is_not_promoted():
    selected = transaction({'programIdIndex': 4, 'accounts': [1, 2, 0], 'data': binary_base58('030100000000000000')})
    alternative = deepcopy(selected)
    alternative['transaction']['message']['instructions'][0]['data'] = binary_base58('030200000000000000')
    selected_view, alternative_view = normalize_transaction(selected), normalize_transaction(alternative)
    assert selected_view['raw']['transaction']['message']['instructions'][0]['parsed']['info']['amount'] == '1'
    assert alternative_view['raw']['transaction']['message']['instructions'][0]['parsed']['info']['amount'] == '2'
    alternative['transaction']['message']['instructions'][0]['data'] = '0'
    assert normalize_transaction(alternative)['issues'][0]['code'] == 'invalid-base58'
    assert normalize_transaction(None)['issues'][0]['code'] == 'invalid-transaction'
    assert normalize_transaction(selected) == selected_view


def test_unknown_outer_wrapper_is_not_hidden_by_supported_nested_transfers():
    wrapper = {'programId': KEYS['mint'], 'accounts': [KEYS['source']], 'data': '3'}
    transfer = {'programIdIndex': 4, 'accounts': [1, 2, 0], 'data': binary_base58('030100000000000000')}
    raw = transaction(wrapper, inner=[{'index': 0, 'instructions': [transfer]}])
    output = normalize_transaction(raw)
    assert output['issues'][0]['code'] == 'unsupported-program'
    assert output['raw']['transaction']['message']['instructions'][0] == wrapper
    assert output['raw']['meta']['innerInstructions'][0]['instructions'][0]['parsed']['type'] == 'transfer'


def test_parsed_key_roles_resolve_partial_instructions_and_conflicts_stay_unknown():
    raw = transaction({'programId': KEYS['token'], 'accounts': [KEYS['source'], KEYS['destination'], KEYS['authority']],
                       'data': binary_base58('030100000000000000')})
    message = raw['transaction']['message']
    message['accountKeys'] = [{'pubkey': key, 'signer': index == 0, 'writable': index < 4}
                              for index, key in enumerate(message['accountKeys'])]
    message.pop('header')
    assert normalize_transaction(raw)['issues'] == []
    assert len(key_roles(raw)['keys']) == 5
    raw['meta']['loadedAddresses'] = {'writable': [KEYS['source']], 'readonly': []}
    assert normalize_transaction(raw)['issues'][0]['code'] == 'conflicting-loaded-keys'


def test_empty_legacy_associated_create_is_not_empty_token_payload():
    case = next(case for case in SCHEMA['examples'] if case['id'] == 'ata-create')
    instruction = compiled(case)
    instruction['data'] = ''
    assert normalize_instruction(instruction, list(KEYS.values()), signers=set(KEYS.values()))['instruction']['parsed']['type'] == 'create'


def test_processing_bound_is_visible_not_a_partial_success():
    raw = transaction({'programIdIndex': 4, 'accounts': [], 'data': '3'})
    raw['transaction']['message']['instructions'] *= 10001
    output = normalize_transaction(raw)
    assert output['issues'][0]['code'] == 'instruction-budget'
    assert output['normalizations'] == []


def test_parsed_key_flags_cannot_override_a_conflicting_message_header():
    raw = transaction({'programIdIndex': 4, 'accounts': [1, 2, 0], 'data': binary_base58('030100000000000000')})
    message = raw['transaction']['message']
    message['accountKeys'] = [{'pubkey': key, 'signer': index == 0, 'writable': index < 4}
                              for index, key in enumerate(message['accountKeys'])]
    assert normalize_transaction(raw)['issues'] == []
    message['header']['numReadonlyUnsignedAccounts'] = 2
    output = normalize_transaction(raw)
    assert output['issues'][0]['code'] == 'conflicting-key-flags'
    assert output['normalizations'] == []
    assert output['raw'] == raw


def test_parsed_loaded_key_writable_flag_cannot_override_loaded_group_role():
    raw = transaction({'programIdIndex': 4, 'accounts': [1, 2, 0], 'data': binary_base58('030100000000000000')}, version=0)
    message = raw['transaction']['message']
    message['accountKeys'] = [{'pubkey': key, 'signer': index == 0, 'writable': index < 4,
                              'source': 'transaction' if index < 4 else 'lookupTable'}
                             for index, key in enumerate(message['accountKeys'])]
    message.pop('header')
    raw['meta']['loadedAddresses'] = {'writable': [], 'readonly': [KEYS['token']]}
    assert normalize_transaction(raw)['issues'] == []
    message['accountKeys'][-1]['writable'] = True
    assert normalize_transaction(raw)['issues'][0]['code'] == 'conflicting-loaded-keys'


def test_float_zero_is_not_the_reviewed_integer_v0_transaction_version():
    raw = transaction({'programIdIndex': 4, 'accounts': [1, 2, 0], 'data': binary_base58('030100000000000000')}, version=0)
    assert normalize_transaction(raw)['issues'] == []
    raw['version'] = 0.0
    output = normalize_transaction(raw)
    assert output['issues'][0]['code'] == 'unsupported-version'
    assert output['normalizations'] == [] and output['raw'] == raw


def test_one_lookup_table_position_cannot_resolve_to_two_distinct_loaded_roles():
    raw = transaction({'programIdIndex': 4, 'accounts': [1, 2, 0], 'data': binary_base58('030100000000000000')}, version=0)
    raw['meta']['loadedAddresses'] = {'writable': [KEYS['recent']], 'readonly': [KEYS['rent']]}
    raw['transaction']['message']['addressTableLookups'] = [
        {'accountKey': KEYS['mint'], 'writableIndexes': [0], 'readonlyIndexes': [1]}]
    assert normalize_transaction(raw)['issues'] == []
    raw['transaction']['message']['addressTableLookups'][0]['readonlyIndexes'] = [0]
    output = normalize_transaction(raw)
    assert output['issues'][0]['code'] == 'conflicting-lookups'
    assert output['normalizations'] == [] and output['raw'] == raw


def test_loaded_key_budget_and_count_reconciliation_precede_expensive_pubkey_decoding(monkeypatch):
    import scanner.compiled_instructions as module
    raw = transaction({'programIdIndex': 4, 'accounts': [1, 2, 0], 'data': binary_base58('030100000000000000')}, version=0)
    message = raw['transaction']['message']
    message['addressTableLookups'] = [{'accountKey': KEYS['mint'], 'writableIndexes': [0], 'readonlyIndexes': []}]
    raw['meta']['loadedAddresses'] = {'writable': [KEYS['rent']], 'readonly': []}
    original = module._pubkey
    loaded_calls = []

    def counted(value, path):
        if path.startswith('meta.loadedAddresses.'):
            loaded_calls.append(path)
        return original(value, path)

    monkeypatch.setattr(module, '_pubkey', counted)
    assert module.resolve_account_keys(raw)['keys'][-1] == KEYS['rent']
    assert loaded_calls == ['meta.loadedAddresses.writable.0']
    loaded_calls.clear()
    raw['meta']['loadedAddresses']['writable'] = [KEYS['rent']] * 2048
    with pytest.raises(CompiledInstructionError) as caught:
        module.resolve_account_keys(raw)
    assert caught.value.code == 'invalid-account-keys'
    assert loaded_calls == []
    raw['meta']['loadedAddresses']['writable'] = [KEYS['rent'], KEYS['recent']]
    with pytest.raises(CompiledInstructionError) as caught:
        module.resolve_account_keys(raw)
    assert caught.value.code == 'conflicting-loaded-keys'
    assert loaded_calls == []


def test_address_form_opaque_accounts_and_program_need_primary_key_membership():
    keys = [KEYS[name] for name in ('authority', 'source', 'destination', 'token')]
    instruction = {'programId': KEYS['token'], 'accounts': [KEYS['source'], KEYS['destination'], KEYS['authority']],
                   'data': binary_base58('030100000000000000')}
    assert normalize_instruction(instruction, keys, signers={KEYS['authority']})['instruction']['parsed']['type'] == 'transfer'
    instruction['accounts'][1] = KEYS['mint']
    with pytest.raises(CompiledInstructionError) as caught:
        normalize_instruction(instruction, keys, signers={KEYS['authority']})
    assert caught.value.code == 'invalid-account-membership'
    instruction['accounts'][1] = KEYS['destination']
    with pytest.raises(CompiledInstructionError) as caught:
        normalize_instruction(instruction, keys[:-1], signers={KEYS['authority']})
    assert caught.value.code == 'invalid-program-membership'
    # Preserve the old fully parsed representation contract: no account-list
    # substitution is created, and its semantic references remain inspected by
    # the existing parsed-source/account validators.
    parsed = {'programId': KEYS['token'], 'parsed': {'type': 'transfer', 'info': {
        'source': KEYS['source'], 'destination': KEYS['destination'], 'amount': '1'}}}
    assert normalize_instruction(parsed, keys[:-1])['instruction'] == parsed
