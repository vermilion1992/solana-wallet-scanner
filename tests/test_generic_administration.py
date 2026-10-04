"""Primary-schema administration controls; unsigned controls cannot close B3.

The generic decoder already uses instruction_view's shared compiled bridge.
These controls exercise its semantic consumer and original evidence references.
"""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from scanner.decoder import decode_transactions
from tests.test_compiled_instructions import KEYS, SCHEMA, binary_base58

ROOT = Path(__file__).resolve().parents[1]
TABLE = [KEYS[name] for name in ('authority', 'source', 'destination', 'mint', 'token', 'token2022', 'system')]


def instruction(*, kind='initializeImmutableOwner', program='token', representation='compiled'):
    target = KEYS['source'] if kind == 'initializeImmutableOwner' else KEYS['mint']
    if representation == 'parsed':
        return {'program': 'spl-token' if program == 'token' else 'spl-token-2022',
                'programId': KEYS[program], 'parsed': {'type': kind, 'info': {
                    'account' if kind == 'initializeImmutableOwner' else 'mint': target}}}
    return {'programIdIndex': TABLE.index(KEYS[program]), 'accounts': [TABLE.index(target)],
            'data': binary_base58('16' if kind == 'initializeImmutableOwner' else '15')}


def record(ix=None, *, inner=False):
    ix = instruction() if ix is None else ix
    outer = ([{'programId': KEYS['system'], 'program': 'system',
               'parsed': {'type': 'allocate', 'info': {'account': KEYS['source'], 'space': 165}}}] if inner else [ix])
    return {'signature': 'unsigned-administration-control', 'evidence_hash': 'a' * 64,
            'raw': {'version': 'legacy', 'slot': 30, 'blockTime': 1700000000,
                    'transaction': {'signatures': ['unsigned-administration-control'], 'message': {
                        'accountKeys': list(TABLE), 'header': {'numRequiredSignatures': 1,
                            'numReadonlySignedAccounts': 0, 'numReadonlyUnsignedAccounts': 3},
                        'instructions': outer}},
                    'meta': {'err': None, 'fee': 5000, 'preTokenBalances': [], 'postTokenBalances': [],
                             'innerInstructions': [{'index': 0, 'instructions': [ix]}] if inner else []}}}


def decode(entry):
    return decode_transactions([entry], KEYS['authority'])


def fee(result):
    return next(event for event in result['events'] if event['kind'] == 'fee')


def test_immutable_owner_binary_and_rpc_field_oracle_is_primary_pinned():
    primary = next(case for case in SCHEMA['examples'] if case['id'] == 'token-immutable')
    assert primary['hex'] == '16'
    assert primary['kind'] == 'initializeImmutableOwner'
    assert primary['accounts'] == ['source']
    assert primary['info'] == {'account': 'source'}
    for reference in SCHEMA['references']:
        assert hashlib.sha256((ROOT / reference['local_path']).read_bytes()).hexdigest() == reference['sha256']


@pytest.mark.parametrize('program', ['token', 'token2022'])
@pytest.mark.parametrize('kind', ['initializeImmutableOwner', 'getAccountDataSize'])
@pytest.mark.parametrize('representation', ['compiled', 'parsed'])
@pytest.mark.parametrize('inner', [False, True], ids=['outer', 'inner'])
def test_supported_administration_retains_original_source_paths_without_ledger_changes(program, kind, representation, inner):
    entry = record(instruction(kind=kind, program=program, representation=representation), inner=inner)
    before = deepcopy(entry)
    result = decode(entry)
    assert result['unresolved'] == []
    receipt, = result['administration']
    path = 'meta.innerInstructions.0.instructions.0' if inner else 'transaction.message.instructions.0'
    assert receipt['source_path'] == path
    assert receipt['path'] == ('innerInstructions.0.0' if inner else 'instructions.0')
    assert receipt['instruction'] == kind
    assert receipt['program_id'] == KEYS[program]
    assert receipt['evidence'] == ['a' * 64]
    assert receipt['representation'] == ('derived-compiled' if representation == 'compiled' else 'parsed')
    if representation == 'compiled':
        assert path + '.data' in receipt['raw_paths']
        assert path + '.accounts' in receipt['raw_paths']
        assert not any('.parsed.' in field for field in receipt['raw_paths'])
    else:
        assert path + '.parsed.info.' + ('account' if kind == 'initializeImmutableOwner' else 'mint') in receipt['raw_paths']
    assert [event['kind'] for event in result['events']] == (['fee', 'rent'] if inner else ['fee'])
    assert fee(result)['amount_sol'] == '0.000005'
    assert not any(event.get('basis_sol') is not None or event['kind'] in ('buy', 'sell') for event in result['events'])
    assert result.get('history_complete') is not True
    assert entry == before


def test_inner_paths_use_group_position_not_outer_instruction_index():
    entry = record(instruction(), inner=True)
    message = entry['raw']['transaction']['message']
    message['instructions'].insert(0, deepcopy(message['instructions'][0]))
    entry['raw']['meta']['innerInstructions'][0]['index'] = 1
    receipt, = decode(entry)['administration']
    assert receipt['path'] == 'innerInstructions.1.0'
    assert receipt['source_path'] == 'meta.innerInstructions.0.instructions.0'
    assert 'meta.innerInstructions.0.instructions.0.data' in receipt['raw_paths']


@pytest.mark.parametrize('mutation', ['header-boolean', 'header-outside-range', 'invalid-unrelated-key',
    'parsed-flags', 'parsed-flag-header-conflict', 'loaded-key-conflict'])
def test_parsed_administration_requires_consistent_native_key_context(mutation):
    entry = record(instruction(representation='parsed'))
    message = entry['raw']['transaction']['message']
    if mutation == 'header-boolean': message['header']['numRequiredSignatures'] = True
    elif mutation == 'header-outside-range': message['header']['numRequiredSignatures'] = 99
    elif mutation == 'invalid-unrelated-key': message['accountKeys'][2] = 'not-a-native-public-key'
    elif mutation in ('parsed-flags', 'parsed-flag-header-conflict'):
        message['accountKeys'] = [{'pubkey': key, 'signer': index == 0, 'writable': index < 4}
                                  for index, key in enumerate(TABLE)]
        message['accountKeys'][2]['signer'] = 0 if mutation == 'parsed-flags' else True
    elif mutation == 'loaded-key-conflict':
        entry['raw']['meta']['loadedAddresses'] = {'writable': [KEYS['destination']], 'readonly': []}
    result = decode(entry)
    assert result['administration'] == []
    assert result['unresolved']
    assert fee(result)['amount_sol'] == '0.000005'


@pytest.mark.parametrize('loaded', [{'writable': None, 'readonly': []}, True,
    {'writable': [], 'readonly': False}, {}, []])
@pytest.mark.parametrize('failed', [False, True], ids=['successful', 'failed'])
def test_malformed_loaded_container_never_raises_or_erases_independently_proved_static_payer_fee(loaded, failed):
    entry = record()
    entry['raw']['version'] = 0
    entry['raw']['meta']['loadedAddresses'] = loaded
    if failed: entry['raw']['meta']['err'] = {'InstructionError': [0, 'Custom']}
    before = deepcopy(entry)
    result = decode(entry)
    assert result['administration'] == []
    assert fee(result)['amount_sol'] == '0.000005'
    assert fee(result)['paid_by_wallet'] is True
    assert [event['kind'] for event in result['events']] == (['fee'] if failed else ['fee', 'unsupported'])
    assert entry == before


@pytest.mark.parametrize('mutation', ['missing-target', 'wrong-target-field', 'nonstring-target', 'invalid-key',
    'absent-target', 'duplicate-target', 'absent-program', 'conflicting-program-index', 'mixed-data',
    'mixed-accounts', 'extra-field', 'wrong-program-name', 'malformed-info', 'malformed-type'])
def test_parsed_administration_rejects_malformed_or_conflicting_primary_evidence_and_restores(mutation):
    entry = record(instruction(representation='parsed'))
    original = deepcopy(entry)
    ix = entry['raw']['transaction']['message']['instructions'][0]
    info = ix['parsed']['info']
    keys = entry['raw']['transaction']['message']['accountKeys']
    if mutation == 'missing-target': info.clear()
    elif mutation == 'wrong-target-field': ix['parsed']['info'] = {'mint': KEYS['source']}
    elif mutation == 'nonstring-target': info['account'] = [KEYS['source']]
    elif mutation == 'invalid-key': info['account'] = 'invalid-public-key'
    elif mutation == 'absent-target': keys.remove(KEYS['source'])
    elif mutation == 'duplicate-target': keys.append(KEYS['source'])
    elif mutation == 'absent-program': keys.remove(KEYS['token'])
    elif mutation == 'conflicting-program-index': ix['programIdIndex'] = TABLE.index(KEYS['system'])
    elif mutation == 'mixed-data': ix['data'] = binary_base58('16')
    elif mutation == 'mixed-accounts': ix['accounts'] = [KEYS['source']]
    elif mutation == 'extra-field': info['complete'] = True
    elif mutation == 'wrong-program-name': ix['program'] = 'system'
    elif mutation == 'malformed-info': ix['parsed']['info'] = []
    elif mutation == 'malformed-type': ix['parsed']['type'] = ['initializeImmutableOwner']
    broken = deepcopy(entry)
    result = decode(entry)
    assert result['administration'] == []
    assert result['unresolved']
    assert fee(result)['amount_sol'] == '0.000005'
    assert entry == broken
    restored = decode(original)
    assert len(restored['administration']) == 1
    assert restored['unresolved'] == []
    assert original == record(instruction(representation='parsed'))


@pytest.mark.parametrize('hexadecimal,accounts', [('1600', [1]), ('16', []), ('16', [1, 2]),
    ('16', [True]), ('16', [256]), ('ff', [1]), ('1a', [1])])
def test_compiled_unknown_or_malformed_layout_remains_unsupported_with_independent_fee(hexadecimal, accounts):
    ix = instruction()
    ix.update(data=binary_base58(hexadecimal), accounts=accounts)
    entry = record(ix)
    before = deepcopy(entry)
    result = decode(entry)
    assert result['administration'] == []
    assert result['unresolved']
    assert fee(result)['amount_sol'] == '0.000005'
    assert entry == before


@pytest.mark.parametrize('extensions', [[], ['immutableOwner'], ['confidentialTransferMint', 'immutableOwner'],
    ['immutableOwner', 'immutableOwner']])
def test_parsed_size_query_accepts_only_pinned_descriptor_without_balance_or_size_claim(extensions):
    ix = instruction(kind='getAccountDataSize', program='token2022', representation='parsed')
    ix['parsed']['info']['extensionTypes'] = extensions
    result = decode(record(ix))
    assert result['unresolved'] == []
    assert len(result['administration']) == 1
    assert [event['kind'] for event in result['events']] == ['fee']
    assert 'account_size' not in result['administration'][0]


@pytest.mark.parametrize('extensions', [None, 'immutableOwner', [1], ['unknownExtension'], [{}]])
def test_size_query_unknown_descriptors_retain_dependency_and_valid_fee(extensions):
    ix = instruction(kind='getAccountDataSize', program='token2022', representation='parsed')
    ix['parsed']['info']['extensionTypes'] = extensions
    result = decode(record(ix))
    assert result['administration'] == []
    assert result['unresolved']
    assert fee(result)['amount_sol'] == '0.000005'


def test_compiled_native_transfer_still_has_capital_role_not_trading_profit():
    ix = {'programIdIndex': TABLE.index(KEYS['system']), 'accounts': [0, 2],
          'data': binary_base58('020000000a00000000000000')}
    result = decode(record(ix))
    assert result['unresolved'] == []
    assert [(event['kind'], event.get('amount_sol')) for event in result['events']] == [
        ('fee', '0.000005'), ('capital', '0.00000001')]
    assert result['administration'] == []


@pytest.mark.parametrize('program', ['token', 'token2022'])
def test_compiled_initialize_immutable_transfer_close_preserves_original_ledger_semantics(program):
    pid = TABLE.index(KEYS[program])
    entry = record()
    entry['raw']['transaction']['message']['instructions'] = [
        instruction(program=program),
        {'programIdIndex': pid, 'accounts': [1, 3], 'data': binary_base58('12' + '04' * 32)},
        {'programIdIndex': pid, 'accounts': [1, 3, 2, 0], 'data': binary_base58('0c050000000000000000')},
        {'programIdIndex': pid, 'accounts': [1, 0, 0], 'data': binary_base58('09')}]
    def balance(index, quantity, owner):
        return {'accountIndex': index, 'mint': KEYS['mint'], 'owner': owner,
                'uiTokenAmount': {'amount': str(quantity), 'decimals': 0}}
    entry['raw']['meta']['preTokenBalances'] = [balance(1, 5, KEYS['authority']), balance(2, 0, KEYS['destination'])]
    entry['raw']['meta']['postTokenBalances'] = [balance(2, 5, KEYS['destination'])]
    before = deepcopy(entry)
    result = decode(entry)
    assert result['unresolved'] == []
    assert [event['kind'] for event in result['events']] == ['fee', 'transfer_out', 'rent']
    assert result['events'][1]['quantity_raw'] == '5'
    assert result['events'][1]['classification'] == 'unknown'
    assert len(result['administration']) == 1
    assert entry == before


def test_unknown_outer_route_and_missing_ownership_do_not_become_known_from_inner_admin():
    entry = record(instruction(), inner=True)
    entry['raw']['transaction']['message']['instructions'][0] = {'programId': KEYS['destination'], 'accounts': [1], 'data': '2'}
    result = decode(entry)
    assert len(result['administration']) == 1
    assert result['unresolved']
    assert any('No reviewed decoder' in event.get('reason', '') for event in result['events'])
    assert not any(event['kind'] in ('buy', 'sell', 'transfer_out', 'transfer_in') for event in result['events'])


@pytest.mark.parametrize('representation', ['parsed', 'compiled'])
def test_failed_transaction_is_atomic_fee_only_even_when_admin_is_invalid(representation):
    entry = record(instruction(representation=representation))
    entry['raw']['meta']['err'] = {'InstructionError': [0, 'InvalidAccountData']}
    entry['raw']['transaction']['message']['instructions'][0]['parsed'] = {'type': 'initializeImmutableOwner', 'info': []}
    result = decode(entry)
    assert [event['kind'] for event in result['events']] == ['fee']
    assert result['administration'] == []
    assert fee(result)['failed'] is True
    assert fee(result)['amount_sol'] == '0.000005'


def test_source_loss_and_restoration_are_offline_and_do_not_mutate_parent(monkeypatch):
    import httpx
    import keyring
    calls = {'provider': 0, 'credential': 0}
    def denied_provider(*args, **kwargs):
        calls['provider'] += 1
        raise AssertionError('Offline decoder attempted a provider request')
    def denied_credential(*args, **kwargs):
        calls['credential'] += 1
        raise AssertionError('Offline decoder attempted a credential lookup')
    monkeypatch.setattr(httpx.Client, 'request', denied_provider)
    monkeypatch.setattr(httpx.AsyncClient, 'request', denied_provider)
    monkeypatch.setattr(keyring, 'get_password', denied_credential)
    original = record()
    parent = decode(original)
    parent_bytes = json.dumps(parent, sort_keys=True).encode()
    missing = decode_transactions([], KEYS['authority'])
    assert missing['administration'] == []
    corrupt = deepcopy(original)
    corrupt['raw']['transaction']['message']['instructions'][0]['data'] = '0'
    assert decode(corrupt)['administration'] == []
    assert decode(original) == parent
    assert json.dumps(parent, sort_keys=True).encode() == parent_bytes
    assert calls == {'provider': 0, 'credential': 0}


def test_genuine_raw_admin_references_preserve_frozen_bytes_and_other_unknown_routes():
    compressed = ROOT / 'evidence/genuine-wallet-batch/collection/phase5/02-lifetime-page-1-response.raw.gz'
    original_bytes = gzip.decompress(compressed.read_bytes())
    assert hashlib.sha256(original_bytes).hexdigest() == '7517110b5b3825584ec24a6e48aad3c23fbcc4c475056f7708d56b87a999fe7a'
    originals = json.loads(original_bytes)['result']['data']
    records = [{'signature': row['transaction']['signatures'][0], 'raw': row,
                'evidence_hash': hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()}
               for row in originals]
    before = deepcopy(records)
    result = decode_transactions(records, '2Bj3dZTSSc14hFR9fCLN9CQ1TiaYyszCKX8fuVG7pyAY')
    immutable = [item for item in result['administration'] if item['instruction'] == 'initializeImmutableOwner']
    # Literal count is taken from the frozen physical raw page, not the saved
    # report's smaller fallback-event population or production opcode table.
    assert len(immutable) == 109
    assert all(any(field.endswith('.data') for field in item['raw_paths']) for item in immutable)
    assert len([event for event in result['events'] if event['kind'] == 'fee']) == 87
    assert result['unresolved']  # The administrative adapter does not certify unrelated exchange paths.
    assert not any(event['kind'] in ('buy', 'sell') for event in result['events'])
    assert records == before
    assert gzip.decompress(compressed.read_bytes()) == original_bytes
