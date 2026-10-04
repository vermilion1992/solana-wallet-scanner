"""Representation-conversion controls, never genuine compiled-chain acceptance.

Existing real parsed golden records are preserved. Their development copies use
the independently pinned binary layouts in compiled_instructions/schema.json.
The authorized indexed pages are replayed unchanged and remain partial/unqualified.
"""
from copy import deepcopy
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest

from scanner.accounting import analyze
from scanner.compiled_instructions import normalize_transaction, key_roles
from scanner.decoder import decode_transactions
from scanner.investigation import decode_supported_swaps, _keys
from scanner.position_evidence import _quantity_point
from scanner.source_consistency import assess_source_consistency
from scanner.transaction_format import original_instruction_paths
from scanner.wallet_evidence import _observe


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures'
BUY = 'mainnet-pumpswap-buy-exact-quote.json'
SELL = 'mainnet-pumpswap-sell-durable-nonce.json'
_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def b58_bytes(value):
    number = 0
    for char in value:
        number = number * 58 + _ALPHABET.index(char)
    return b'\0' * (len(value) - len(value.lstrip('1'))) + number.to_bytes((number.bit_length() + 7) // 8, 'big')


def b58_text(value):
    number, result = int.from_bytes(value, 'big'), ''
    while number:
        number, remainder = divmod(number, 58)
        result = _ALPHABET[remainder] + result
    return '1' * (len(value) - len(value.lstrip(b'\0'))) + result


def rehash(record):
    encoded = json.dumps(record['raw'], sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    record['evidence_hash'] = hashlib.sha256(encoded).hexdigest()
    return record


def golden(name):
    return json.loads((FIXTURES / name).read_text())


def compiled_development_copy(name, *, nonce=True):
    """Pinned-layout encoder independent of the production opcode lookup table."""
    record = golden(name)
    raw = record['raw']
    keys = _keys(raw['transaction']['message'], raw['meta'])
    groups = [raw['transaction']['message']['instructions']] + [group['instructions'] for group in raw['meta']['innerInstructions']]
    for instructions in groups:
        for index, ix in enumerate(instructions):
            parsed = ix.get('parsed')
            if not isinstance(parsed, dict):
                continue
            kind, info = parsed['type'], parsed['info']
            payload, roles = None, None
            if kind == 'transferChecked':
                payload = b'\x0c' + struct.pack('<Q', int(info['tokenAmount']['amount'])) + bytes([info['tokenAmount']['decimals']])
                roles = [info[field] for field in ('source', 'mint', 'destination', 'authority')]
            elif kind == 'advanceNonce' and nonce:
                payload = b'\x04\0\0\0'
                roles = [info[field] for field in ('nonceAccount', 'recentBlockhashesSysvar', 'nonceAuthority')]
            elif ix.get('program') == 'system' and kind == 'transfer':
                payload = b'\x02\0\0\0' + struct.pack('<Q', info['lamports'])
                roles = [info['source'], info['destination']]
            elif kind == 'createAccount':
                payload = b'\0\0\0\0' + struct.pack('<QQ', info['lamports'], info['space']) + b58_bytes(info['owner'])
                roles = [info['source'], info['newAccount']]
            elif kind == 'initializeAccount3':
                payload = b'\x12' + b58_bytes(info['owner'])
                roles = [info['account'], info['mint']]
            elif kind == 'initializeImmutableOwner':
                payload, roles = b'\x16', [info['account']]
            elif kind == 'syncNative':
                payload, roles = b'\x11', [info['account']]
            elif kind == 'closeAccount':
                payload, roles = b'\x09', [info['account'], info['destination'], info['owner']]
            elif kind == 'createIdempotent':
                payload, roles = b'\x01', [info[field] for field in ('source', 'account', 'wallet', 'mint', 'systemProgram', 'tokenProgram')]
            if payload is not None:
                instructions[index] = {'programIdIndex': keys.index(ix['programId']),
                                       'accounts': [keys.index(account) for account in roles],
                                       'data': b58_text(payload), 'stackHeight': ix.get('stackHeight')}
    # This metadata makes conversion provenance explicit to a reader; never a
    # completion/normalization trust flag consumed by the scanner.
    record['development_representation'] = 'Unsigned pinned-layout conversion of existing parsed golden; no compiled-chain provenance'
    return rehash(record)


def wallet(record):
    raw = record['raw']
    return _keys(raw['transaction']['message'], raw['meta'])[0]


def asset_account(record):
    raw, address = record['raw'], wallet(record)
    keys = _keys(raw['transaction']['message'], raw['meta'])
    return next(keys[row['accountIndex']] for row in raw['meta']['preTokenBalances']
                if row.get('owner') == address and row['mint'] != 'So11111111111111111111111111111111111111112')


def spot(record):
    return decode_supported_swaps([record], wallet(record))


def trades(result):
    return [event for event in result['events'] if event['kind'] in ('buy', 'sell')]


@pytest.mark.parametrize('name', [BUY, SELL])
def test_reviewed_spot_arithmetic_survives_independent_compiled_representation(name):
    parsed, compiled = golden(name), compiled_development_copy(name)
    before_file = (FIXTURES / name).read_bytes()
    original = deepcopy(compiled)
    parsed_result, compiled_result = spot(parsed), spot(compiled)
    assert len(trades(parsed_result)) == len(trades(compiled_result)) == 1
    financial = ('kind', 'mint', 'quantity_raw', 'amount_sol', 'fee_sol', 'observed_pre_quantity_raw', 'observed_post_quantity_raw', 'classification')
    assert {key: trades(compiled_result)[0][key] for key in financial} == {key: trades(parsed_result)[0][key] for key in financial}
    # The genuine buy contains separate native tip-role gaps; preserving those
    # alongside its known transaction arithmetic is the correct positive case.
    assert [(row['path'], row['reason']) for row in compiled_result['unresolved']] == [
        (row['path'], row['reason']) for row in parsed_result['unresolved']]
    assert compiled_result['coverage']['complete'] is False
    assert compiled_result['coverage']['history_complete'] is False
    assert compiled == original
    assert (FIXTURES / name).read_bytes() == before_file
    assert compiled['evidence_hash'] != parsed['evidence_hash']


@pytest.mark.parametrize('name', [BUY, SELL])
def test_scoped_quantities_wallet_observations_and_raw_paths_are_preserved(name):
    parsed, compiled = golden(name), compiled_development_copy(name)
    account, address = asset_account(compiled), wallet(compiled)
    parsed_point, compiled_point = _quantity_point(parsed['raw'], address, account), _quantity_point(compiled['raw'], address, account)
    assert {key: compiled_point[key] for key in ('kind', 'pre', 'post', 'mint', 'decimals', 'program_id')} == {key: parsed_point[key] for key in ('kind', 'pre', 'post', 'mint', 'decimals', 'program_id')}
    assert any(path.endswith('.data') for path in compiled_point['paths'])
    receipts = normalize_transaction(compiled['raw'])['normalizations']
    assert not any('.parsed' in path for path in compiled_point['paths']
                   if any(path.startswith(row['path'] + '.') for row in receipts))
    observed = _observe(compiled, address)
    assert observed['boundaries'][account]['pre']['quantity'] == compiled_point['pre']
    assert observed['boundaries'][account]['post']['quantity'] == compiled_point['post']
    assert len(observed['trades']) == 1
    assert observed['instruction_normalization']['normalizations']
    normalization = normalize_transaction(compiled['raw'])
    receipt = next(row for row in normalization['normalizations'] if row['kind'] == 'transferChecked')
    raw_paths = original_instruction_paths(compiled['raw'], [receipt['path'] + '.parsed.info.source'])
    assert receipt['path'] + '.data' in raw_paths
    assert receipt['path'] + '.accounts' in raw_paths


@pytest.mark.parametrize('reverse', [False, True])
def test_parsed_selected_compiled_alternative_and_reverse_have_same_metric_facts(reverse):
    records = [golden(SELL), compiled_development_copy(SELL)]
    if reverse:
        records.reverse()
    account, address, signature = asset_account(records[0]), wallet(records[0]), records[0]['signature']
    original = deepcopy(records)
    result = assess_source_consistency(records, accounts=[account], wallet=address)
    row = result['transactions'][signature]
    assert row['accounts'][account]['state'] == 'PASS'
    assert row['native']['wallet_network_fees_sol']['state'] == 'PASS'
    assert row['accounts'][account]['checks']['program']['state'] == 'PASS'
    assert records == original


@pytest.mark.parametrize('alteration', ['missing', 'invalid-base58', 'truncated', 'wrong-decimals'])
def test_required_inner_loss_or_corruption_revokes_quantity_and_trade_but_keeps_fees(alteration):
    record = compiled_development_copy(SELL)
    group = record['raw']['meta']['innerInstructions'][0]['instructions']
    if alteration == 'missing':
        group.pop(1)
    elif alteration == 'invalid-base58':
        group[1]['data'] = '0'
    elif alteration == 'truncated':
        group[1]['data'] = b58_text(b'\x0c\x01')
    else:
        payload = b58_bytes(group[1]['data'])
        group[1]['data'] = b58_text(payload[:-1] + b'\x09')
    rehash(record)
    with pytest.raises(ValueError):
        _quantity_point(record['raw'], wallet(record), asset_account(record))
    result = spot(record)
    assert not trades(result)
    assert result['unresolved']
    fee = next(event for event in result['events'] if event['kind'] == 'fee')
    assert fee['amount_sol'] == '0.000042'
    assert fee['allocation'] == 'unallocated'


def test_malformed_disjoint_instruction_does_not_erase_scoped_token_quantity():
    record = compiled_development_copy(SELL)
    raw = record['raw']
    keys = _keys(raw['transaction']['message'], raw['meta'])
    # Pool settlement accounts are disjoint from the named wallet asset account.
    raw['meta']['innerInstructions'][0]['instructions'].append({
        'programIdIndex': keys.index('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'),
        'accounts': [5, 6, 2], 'data': '0'})
    rehash(record)
    point = _quantity_point(raw, wallet(record), asset_account(record))
    assert point['kind'] == 'sell'
    assert point['pre'] - point['post'] == 5218627960
    # Scoped account irrelevance does not claim complete economic-role coverage.
    assert normalize_transaction(raw)['issues']


def test_failed_compiled_payload_is_atomic_and_preserves_supported_fee():
    record = compiled_development_copy(SELL)
    record['raw']['meta']['err'] = {'InstructionError': [4, 'Custom']}
    record['raw']['meta']['innerInstructions'][0]['instructions'][1]['data'] = '0'
    rehash(record)
    original = deepcopy(record)
    for decoder in (decode_transactions, decode_supported_swaps):
        result = decoder([record], wallet(record))
        assert [event['kind'] for event in result['events']] == ['fee']
        assert result['events'][0]['amount_sol'] == '0.000042'
        assert result['events'][0]['failed'] is True
    assert record == original


def string_key_development_copy(record):
    """Unsigned conversion of recorded parsed key roles into a valid v0 header."""
    raw = record['raw']
    message = raw['transaction']['message']
    entries = message['accountKeys']
    static = [entry for entry in entries if entry.get('source', 'transaction') == 'transaction']
    required = sum(entry['signer'] for entry in static)
    message['header'] = {'numRequiredSignatures': required,
                         'numReadonlySignedAccounts': sum(not entry['writable'] for entry in static[:required]),
                         'numReadonlyUnsignedAccounts': sum(not entry['writable'] for entry in static[required:])}
    message['accountKeys'] = [entry['pubkey'] for entry in static]
    loaded = {name: [entry['pubkey'] for entry in entries if entry.get('source') == 'lookupTable' and entry['writable'] is writable]
              for name, writable in (('writable', True), ('readonly', False))}
    raw['meta']['loadedAddresses'] = loaded
    message['addressTableLookups'] = [{'accountKey': asset_account_from_entries(record, entries),
                                     'writableIndexes': list(range(len(loaded['writable']))),
                                     'readonlyIndexes': list(range(len(loaded['readonly'])))}]
    return rehash(record)


def asset_account_from_entries(record, entries):
    address = entries[0]['pubkey']
    return next(entries[row['accountIndex']]['pubkey'] for row in record['raw']['meta']['preTokenBalances']
                if row.get('owner') == address and row['mint'] != 'So11111111111111111111111111111111111111112')


def test_compiled_nonce_with_header_and_loaded_keys_has_parsed_role_parity():
    record = string_key_development_copy(compiled_development_copy(SELL))
    before = deepcopy(record)
    roles = key_roles(record['raw'])['keys']
    assert len(roles) == 28
    assert roles[0]['signer'] is True and roles[1]['writable'] is True
    assert roles[10]['signer'] is False and roles[10]['writable'] is False
    result = spot(record)
    assert len(trades(result)) == 1, result['unresolved']
    assert trades(result)[0]['amount_sol'] == '0.01134506'
    assert record == before


def test_authorized_genuine_indexed_pages_remain_partial_without_trade_promotion():
    paths = [ROOT / f'evidence/source-probe-2026-10-04/live/{stem}-response.raw.gz'
             for stem in ('02-all-index', '03-all-continuation')]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    records = []
    for path in paths:
        payload = json.loads(gzip.decompress(path.read_bytes()))
        for raw in payload['result']['data']:
            record = {'signature': raw['transaction']['signatures'][0], 'raw': raw}
            records.append(rehash(record))
    assert len(records) == len({row['signature'] for row in records}) == 200
    originals = deepcopy(records)
    address = wallet(records[0])
    success = [row for row in records if row['raw']['meta']['err'] is None]
    assert len(success) == 16
    for record in success:
        result = decode_supported_swaps([record], address)
        assert not trades(result)
        assert result['unresolved']
        assert result['coverage']['complete'] is False
        assert any(row['kind'] == 'transferChecked' for row in normalize_transaction(record['raw'])['normalizations'])
    expected_fee = sum(row['raw']['meta']['fee'] for row in records
                       if _keys(row['raw']['transaction']['message'], row['raw']['meta'])[0] == address)
    assert expected_fee == 8904733
    result = decode_supported_swaps(records, address)
    supported_fee = sum(Decimal(event['amount_sol']) for event in result['events']
                        if event['kind'] == 'fee' and event['paid_by_wallet'])
    assert supported_fee == Decimal('0.008904733')
    assert not trades(result)
    assert records == originals
    assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths} == before


def test_supported_cpi_roles_do_not_claim_transaction_signers_or_multisig_thresholds():
    record = compiled_development_copy(SELL)
    raw = record['raw']
    signer_keys = {entry['pubkey'] for entry in raw['transaction']['message']['accountKeys'] if entry['signer']}
    receipts = normalize_transaction(raw)['normalizations']
    cpi = [row for row in receipts if row['kind'] == 'transferChecked' and row['path'].startswith('meta.')]
    assert cpi and all(row['signer_evidence'] == 'runtime-cpi-not-message-signers' for row in cpi)
    assert any(not set(row['required_signer_roles']) <= signer_keys for row in cpi)
    # Classic-token CPI with a trailing signer has the primary parser's
    # multisigAuthority/signers shape, without proving m/n or on-chain state.
    raw['meta']['innerInstructions'][0]['instructions'][2]['accounts'].append(0)
    output = normalize_transaction(raw)
    info = output['raw']['meta']['innerInstructions'][0]['instructions'][2]['parsed']['info']
    assert info['signers'] == [wallet(record)]
    assert 'multisigAuthority' in info
    receipt = next(row for row in output['normalizations'] if row['path'] == 'meta.innerInstructions.0.instructions.2')
    assert receipt['signer_evidence'] == 'runtime-cpi-not-message-signers'


@pytest.mark.parametrize('extra', ['accounts', 'data'])
def test_mixed_parsed_opaque_economic_instruction_retains_fee_without_accepting_trades(extra):
    record = golden(SELL)
    target = record['raw']['meta']['innerInstructions'][0]['instructions'][1]
    target[extra] = [] if extra == 'accounts' else '3'
    rehash(record)
    original = deepcopy(record)
    output = spot(record)
    assert not trades(output)
    assert output['unresolved']
    assert next(row for row in output['events'] if row['kind'] == 'fee')['amount_sol'] == '0.000042'
    generic = decode_transactions([record], wallet(record))
    assert any(row['kind'] == 'unsupported' for row in generic['events'])
    assert next(row for row in generic['events'] if row['kind'] == 'fee')['amount_sol'] == '0.000042'
    assert record == original


def test_genuine_rpc_spl_token_alias_for_token2022_preserves_generic_owned_movement():
    record = golden(SELL)
    target = record['raw']['meta']['innerInstructions'][0]['instructions'][1]
    assert target['program'] == 'spl-token'
    assert target['programId'] == 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
    assert record['evidence_hash'] == '25271562a99c96879c6d5f347792340320a6f55c12497a0ba3602db86eca6b4a'
    original = deepcopy(record)
    result = decode_transactions([record], wallet(record))
    asset = [row for row in result['events'] if row['kind'] == 'transfer_out' and row.get('quantity_raw') == '5218627960']
    assert len(asset) == 1
    assert asset[0]['source'] == asset_account(record)
    assert asset[0]['classification'] == 'unknown'
    assert next(row for row in result['events'] if row['kind'] == 'fee')['amount_sol'] == '0.000042'
    assert not any(row['kind'] in ('buy', 'sell') for row in result['events'])
    assert record == original


def test_token2022_specific_alias_cannot_override_a_classic_program_identity():
    record = golden(SELL)
    target = record['raw']['meta']['innerInstructions'][0]['instructions'][2]
    assert target['programId'] == 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
    target['program'] = 'spl-token-2022'
    rehash(record)
    result = decode_transactions([record], wallet(record))
    assert any('program identity' in row['reason'] for row in result['unresolved'])
    assert not any(row['kind'] == 'transfer_in' and row.get('quantity_raw') == '11345060' for row in result['events'])
    assert next(row for row in result['events'] if row['kind'] == 'fee')['amount_sol'] == '0.000042'
