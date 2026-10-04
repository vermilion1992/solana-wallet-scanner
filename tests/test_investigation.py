"""Adversarial synthetic cases do not establish live decoder completeness."""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import pytest

from scanner.investigation import (decode_supported_swaps, inspect_token_risk,
                                  PUMP_SWAP, PUMP, JUPITER, WSOL)
from scanner.decoder import TOKEN_IDS, SYSTEM_ID

WALLET, TOKEN = 'synthetic-wallet', 'synthetic-mint'
TOKEN_PROGRAM = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN_2022 = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'


def encoded(name, tail=b'\0' * 16):
    data = hashlib.sha256(('global:' + name).encode()).digest()[:8] + tail
    return [base64.b64encode(data).decode(), 'base64']


def balance(index, amount, mint=TOKEN, owner=WALLET):
    return {'accountIndex': index, 'mint': mint, 'owner': owner,
            'uiTokenAmount': {'amount': str(amount), 'decimals': 9 if mint == WSOL else 6,
                              'uiAmount': float('nan')}}


def transfer(source, destination, amount, mint):
    return {'programId': TOKEN_PROGRAM, 'program': 'spl-token', 'parsed': {'type': 'transferChecked',
            'info': {'source': source, 'destination': destination, 'mint': mint,
                     'tokenAmount': {'amount': str(amount), 'decimals': 9 if mint == WSOL else 6}}}}


def record(*, sell=False, sponsored=False):
    keys = [WALLET, 'wallet-token', 'wallet-wsol', 'pool-token', 'pool-wsol']
    if sponsored:
        keys.append('sponsor')
        keys[0], keys[-1] = keys[-1], keys[0]
    account_owner = WALLET
    before = [balance(1, 100 if sell else 0), balance(2, 0 if sell else 1_000_000_000, WSOL),
              balance(3, 0 if sell else 100, owner='pool'), balance(4, 1_000_000_000 if sell else 0, WSOL, 'pool')]
    after = [balance(1, 0 if sell else 100), balance(2, 1_000_000_000 if sell else 0, WSOL),
             balance(3, 100 if sell else 0, owner='pool'), balance(4, 0 if sell else 1_000_000_000, WSOL, 'pool')]
    route_accounts = ['pool', account_owner, 'global', TOKEN, WSOL, 'wallet-token', 'wallet-wsol',
                      'pool-token', 'pool-wsol', 'fee-recipient', 'fee-account', TOKEN_PROGRAM,
                      TOKEN_PROGRAM, SYSTEM_ID]
    pre = [10_000_000_000, 2_039_280, 2_039_280 + (0 if sell else 1_000_000_000), 2_039_280,
           2_039_280 + (1_000_000_000 if sell else 0)]
    post = [10_000_000_000 - 5000, 2_039_280, 2_039_280 + (1_000_000_000 if sell else 0),
            2_039_280, 2_039_280 + (0 if sell else 1_000_000_000)]
    if sponsored:
        pre.append(10_000_000_000)
        post.append(10_000_000_000)
    inner = [transfer('wallet-token', 'pool-token', 100, TOKEN),
             transfer('pool-wsol', 'wallet-wsol', 1_000_000_000, WSOL)] if sell else [
             transfer('wallet-wsol', 'pool-wsol', 1_000_000_000, WSOL),
             transfer('pool-token', 'wallet-token', 100, TOKEN)]
    return {'signature': 'synthetic-signature', 'evidence_hash': 'synthetic-hash', 'raw': {
        'slot': 100, 'blockTime': 1_780_000_000, 'version': 0,
        'transaction': {'signatures': ['synthetic-signature'], 'message': {'accountKeys': keys,
            'instructions': [{'programId': PUMP_SWAP, 'accounts': route_accounts,
                              'data': encoded('sell' if sell else 'buy')}]}},
        'meta': {'err': None, 'fee': 5000, 'preBalances': pre, 'postBalances': post,
                 'preTokenBalances': before, 'postTokenBalances': after,
                 'innerInstructions': [{'index': 0, 'instructions': inner}]}}}


def decode(entry):
    return decode_supported_swaps([entry], WALLET)


def swaps(result):
    return [event for event in result['events'] if event['kind'] in ('buy', 'sell')]


def test_verified_spot_route_collapses_exact_owned_exchange():
    result = decode(record())
    assert not result['unresolved']
    event = swaps(result)[0]
    assert event['kind'] == 'buy'
    assert event['quantity_raw'] == '100'
    assert event['amount_sol'] == '1'
    assert event['classification'] == 'unknown'
    assert event['fee_sol'] == '0.000005'
    assert event['evidence'] == ['synthetic-hash']
    assert event['path'] == 'instructions.0'
    assert result['events'][0]['amount_sol'] == '0.000005'
    assert result['events'][0]['paid_by_wallet'] is True
    assert result['events'][0]['allocation'] == 'buy_basis'
    assert result['events'][0]['allocated_trade_path'] == event['path']
    assert result['events'][0]['signature'] == event['signature']
    assert result['coverage']['decoder_version'] == 'spot-v6-real-query-instructions'
    assert result['coverage']['complete'] is False
    assert result['coverage']['history_complete'] is False


def test_sale_and_sponsored_fee_accounting():
    result = decode(record(sell=True, sponsored=True))
    assert not result['unresolved']
    assert swaps(result)[0]['kind'] == 'sell'
    assert swaps(result)[0]['amount_sol'] == '1'
    assert result['events'][0]['paid_by_wallet'] is False
    assert result['events'][0]['allocation'] == 'unallocated'
    assert 'allocated_trade_path' not in result['events'][0]
    assert swaps(result)[0]['fee_sol'] == '0'


def test_single_wallet_paid_sale_allocates_exact_network_fee_to_exit():
    result = decode(record(sell=True))
    event = swaps(result)[0]
    fee = result['events'][0]
    assert event['kind'] == 'sell'
    assert event['amount_sol'] == '1'
    assert event['fee_sol'] == fee['amount_sol'] == '0.000005'
    assert fee['allocation'] == 'sell_exit'
    assert fee['allocated_trade_path'] == event['path']
    assert fee['signature'] == event['signature']


def test_meta_fee_includes_priority_fee_exactly_once():
    entry = record()
    raw = entry['raw']
    raw['meta']['fee'] = 15000
    raw['meta']['postBalances'][0] -= 10000
    raw['transaction']['message']['instructions'].insert(0, {
        'programId': 'ComputeBudget111111111111111111111111111111',
        'accounts': [], 'data': [base64.b64encode(b'\x03' + (5000000).to_bytes(8, 'little')).decode(), 'base64']})
    raw['meta']['innerInstructions'][0]['index'] = 1
    result = decode(entry)
    assert not result['unresolved']
    fees = [event for event in result['events'] if event['kind'] == 'fee']
    assert len(fees) == 1
    assert fees[0]['amount_sol'] == '0.000015'
    assert fees[0]['allocation'] == 'buy_basis'
    assert swaps(result)[0]['fee_sol'] == '0.000015'
    assert swaps(result)[0]['amount_sol'] == '1'
    assert fees[0]['allocated_trade_path'] == 'instructions.1'


def test_arbitrary_balances_or_spoofed_program_never_prove_swap():
    entry = record()
    entry['raw']['transaction']['message']['instructions'][0]['programId'] = 'unreviewed-program'
    result = decode(entry)
    assert not swaps(result)
    assert result['unresolved']
    assert result['events'][0]['allocation'] == 'unallocated'
    assert 'allocated_trade_path' not in result['events'][0]
    entry['raw']['transaction']['message']['instructions'][0]['program'] = 'PumpSwap'
    assert not swaps(decode(entry))


def test_known_program_wrong_discriminator_rejected():
    entry = record()
    entry['raw']['transaction']['message']['instructions'][0]['data'] = encoded('deposit')
    assert not swaps(decode(entry))


def test_user_authority_and_event_owner_are_required():
    entry = record()
    entry['raw']['transaction']['message']['instructions'][0]['accounts'][1] = 'other-user'
    assert not swaps(decode(entry))
    entry = record()
    entry['raw']['meta']['preTokenBalances'][0].pop('owner')
    assert not swaps(decode(entry))


def test_owner_change_missing_integer_transfer_and_reconciliation_fail_closed():
    entry = record()
    entry['raw']['meta']['postTokenBalances'][0]['owner'] = 'other-user'
    assert not swaps(decode(entry))
    entry = record()
    entry['raw']['meta']['innerInstructions'][0]['instructions'][1]['parsed']['info']['tokenAmount']['amount'] = 100.0
    assert not swaps(decode(entry))
    entry = record()
    entry['raw']['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '101'
    assert not swaps(decode(entry))


def test_explicit_outside_native_transfers_are_isolated_with_unknown_economic_role():
    entry = record()
    entry['raw']['transaction']['message']['instructions'].append({'programId': SYSTEM_ID,
        'parsed': {'type': 'transfer', 'info': {'source': WALLET, 'destination': 'external', 'lamports': 10}}})
    entry['raw']['meta']['postBalances'][0] -= 10
    result = decode(entry)
    assert swaps(result)[0]['amount_sol'] == '1'
    movement = next(event for event in result['events'] if event['kind'] == 'capital')
    assert movement['amount_sol'] == '0.00000001'
    assert movement['economic_role'] == 'unknown'
    assert result['unresolved']
    assert swaps(result)[0]['fee_sol'] == '0'
    assert result['events'][0]['allocation'] == 'unallocated'
    assert 'allocated_trade_path' not in result['events'][0]
    entry['raw']['transaction']['message']['instructions'][-1]['parsed']['info']['lamports'] = 11
    assert not swaps(decode(entry))


def test_multiple_outer_routes_and_unknown_wrappers_remain_unresolved():
    entry = record()
    entry['raw']['transaction']['message']['instructions'].append(deepcopy(entry['raw']['transaction']['message']['instructions'][0]))
    assert not swaps(decode(entry))
    entry = record()
    route = entry['raw']['transaction']['message']['instructions'][0]
    entry['raw']['transaction']['message']['instructions'][0] = {'programId': 'unknown-wrapper', 'accounts': [WALLET], 'data': '1'}
    entry['raw']['meta']['innerInstructions'][0]['instructions'].insert(0, route)
    assert not swaps(decode(entry))


def test_crossquote_and_multiple_assets_not_invented_sol_prices():
    entry = record()
    stable = 'synthetic-stable'
    for field in ('preTokenBalances', 'postTokenBalances'):
        for item in entry['raw']['meta'][field]:
            if item['mint'] == WSOL:
                item['mint'] = stable
    result = decode(entry)
    assert not swaps(result)


def test_failed_transaction_retains_only_exact_fee():
    entry = record()
    entry['raw']['meta']['err'] = {'InstructionError': [0, {'Custom': 1}]}
    result = decode(entry)
    assert [event['kind'] for event in result['events']] == ['fee']
    assert result['coverage']['failed_transactions'] == 1
    assert result['events'][0]['allocation'] == 'unallocated'
    assert result['events'][0]['amount_sol'] == '0.000005'
    assert 'allocated_trade_path' not in result['events'][0]


def test_missing_time_signature_success_or_native_evidence_cannot_emit_swap():
    for field in ('blockTime', 'slot', 'meta'):
        entry = record()
        entry['raw'][field] = None
        assert not swaps(decode(entry))
    entry = record()
    entry['signature'] = 'mismatched'
    assert not swaps(decode(entry))
    entry = record()
    entry['raw']['meta'].pop('err')
    assert not swaps(decode(entry))
    entry = record()
    entry['raw']['meta']['preBalances'] = []
    assert not swaps(decode(entry))


def test_same_slot_order_needs_block_evidence():
    first, second = record(), record()
    second['signature'] = second['raw']['transaction']['signatures'][0] = 'second'
    assert not swaps(decode_supported_swaps([first, second], WALLET))
    first['transaction_index'], second['transaction_index'] = 0, 1
    assert len(swaps(decode_supported_swaps([first, second], WALLET))) == 2


def test_malformed_records_do_not_abort_batch():
    damaged = []
    for value in (None, [], 'bad'):
        entry = record()
        entry['raw']['transaction'] = value
        damaged.append(entry)
    entry = record()
    entry['raw']['slot'] = []
    damaged.append(entry)
    entry = record()
    entry['raw']['transaction']['message']['accountKeys'] = [WALLET]
    entry['raw']['meta']['loadedAddresses'] = {'writable': None}
    damaged.append(entry)
    valid = record()
    valid['raw']['slot'] = 101
    result = decode_supported_swaps(damaged + [valid], WALLET)
    assert len(swaps(result)) == 1
    assert len(result['unresolved']) == len(damaged)


def test_refundable_wallet_funded_new_token_rent_excluded_from_buy_cost():
    entry = record()
    raw = entry['raw']
    raw['meta']['preTokenBalances'] = [balance for balance in raw['meta']['preTokenBalances'] if balance['accountIndex'] != 1]
    raw['meta']['preBalances'][1] = 0
    raw['meta']['postBalances'][0] -= 2_039_280
    raw['transaction']['message']['instructions'].insert(0, {
        'programId': 'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL',
        'parsed': {'type': 'createIdempotent', 'info': {'source': WALLET, 'wallet': WALLET,
                    'account': 'wallet-token', 'mint': TOKEN}}})
    raw['meta']['innerInstructions'][0]['index'] = 1
    result = decode(entry)
    assert not result['unresolved']
    assert swaps(result)[0]['amount_sol'] == '1'
    raw['transaction']['message']['instructions'][0]['parsed']['info']['source'] = 'sponsor'
    assert not swaps(decode(entry))


def test_unwrap_returns_rent_without_manufacturing_sale_profit():
    entry = record(sell=True)
    raw = entry['raw']
    raw['meta']['postTokenBalances'] = [balance for balance in raw['meta']['postTokenBalances'] if balance['accountIndex'] != 2]
    raw['meta']['postBalances'][2] = 0
    raw['meta']['postBalances'][0] += 1_000_000_000 + 2_039_280
    raw['transaction']['message']['instructions'].append({'programId': TOKEN_PROGRAM,
        'parsed': {'type': 'closeAccount', 'info': {'account': 'wallet-wsol', 'destination': WALLET, 'owner': WALLET}}})
    result = decode(entry)
    assert not result['unresolved']
    assert swaps(result)[0]['amount_sol'] == '1'


def test_real_mainnet_wrappers_and_sponsored_router_are_explicit_gaps():
    for index in range(4):
        path = Path(__file__).parent / 'fixtures' / f'mainnet-wrapper-{index}.json'
        entry = json.loads(path.read_text())
        raw = entry['raw']
        entries = raw['transaction']['message']['accountKeys']
        signers = [item['pubkey'] for item in entries if item.get('signer')]
        for signer in signers:
            result = decode_supported_swaps([entry], signer)
            assert not swaps(result)
            assert 'No reviewed outer spot swap' in result['unresolved'][0]['reason']
            assert result['events'][0]['paid_by_wallet'] == (signer == entries[0]['pubkey'])
            assert result['events'][0]['amount_sol'] == {
                0: '0.000055688', 1: '0.00041', 2: '0.000080001', 3: '0.00041'}[index]


def test_actual_mainnet_pumpswap_buy_with_proven_net_amount_and_outside_flows():
    path = Path(__file__).parent / 'fixtures' / 'mainnet-pumpswap-buy-exact-quote.json'
    entry = json.loads(path.read_text())
    wallet = '4drEkXDZhjun3vjZmz1g7pQGM7kxANQbDuD9jtPZwzJZ'
    result = decode_supported_swaps([entry], wallet)
    event = swaps(result)[0]
    assert event['kind'] == 'buy'
    assert event['amount_sol'] == '0.25'
    assert event['quantity_raw'] == '10663612056'
    assert event['observed_pre_quantity_raw'] == '44824210540'
    assert event['observed_post_quantity_raw'] == '55487822596'
    assert event['instruction'] == 'buy_exact_quote_in'
    assert event['path'] == 'instructions.6'
    assert result['events'][0]['amount_sol'] == '0.000141389'
    assert result['events'][0]['allocation'] == 'unallocated'
    assert 'allocated_trade_path' not in result['events'][0]
    assert event['fee_sol'] == '0'
    movements = [event for event in result['events'] if event['kind'] == 'capital']
    assert [event['amount_sol'] for event in movements] == ['0.0025', '0.001']
    assert all(event['economic_role'] == 'unknown' for event in movements)
    assert len(result['unresolved']) == 2
    assert result['coverage']['decoded_swaps'] == 1
    assert result['coverage']['complete'] is False
    assert result['coverage']['fixture_validation'][0]['state'] == 'RAW_MAINNET_GOLDEN'
    # Expectations above independently come from four explicit owned wSOL CPI
    # transfers (not a price API or the decoder's native delta arithmetic).
    raw = entry['raw']
    quote_debits = [int(ix['parsed']['info']['tokenAmount']['amount'])
                   for group in raw['meta']['innerInstructions'] if group['index'] == 6
                   for ix in group['instructions'] if ix.get('parsed', {}).get('type') == 'transferChecked'
                   and ix['parsed']['info'].get('source') == '8XeSQHdLxqhcFAegjUpYvaJu516GUPQttfPgen4eXFiG']
    assert quote_debits == [248388695, 61974, 1487358, 61973]
    assert sum(quote_debits) == 250000000
    raw['transaction']['message']['instructions'][8]['parsed']['info']['lamports'] += 1
    assert not swaps(decode_supported_swaps([entry], wallet))


@pytest.mark.parametrize('damage', [
    'creation', 'initialization', 'closure', 'sync', 'funding',
    'sponsored_creation', 'creation_program', 'creation_space', 'creation_rent',
    'initialization_owner', 'initialization_mint', 'closure_owner', 'closure_beneficiary',
    'opening_native', 'closing_native', 'native_total',
])
def test_real_temporary_wsol_requires_primary_lifecycle_and_exact_native_proofs(damage):
    entry = json.loads((Path(__file__).parent / 'fixtures' / 'mainnet-pumpswap-buy-exact-quote.json').read_text())
    raw = entry['raw']
    instructions = raw['transaction']['message']['instructions']
    initialization = raw['meta']['innerInstructions'][0]['instructions']
    creation_info = initialization[1]['parsed']['info']
    initialization_info = initialization[3]['parsed']['info']
    closure_info = instructions[7]['parsed']['info']
    noop = {'programId': 'ComputeBudget111111111111111111111111111111',
            'accounts': [], 'data': 'KoQE31'}
    if damage == 'creation':
        initialization.pop(1)
    elif damage == 'initialization':
        initialization.pop(3)
    elif damage == 'closure':
        instructions[7] = noop
    elif damage == 'sync':
        instructions[5] = noop
    elif damage == 'funding':
        instructions[4] = noop
    elif damage == 'sponsored_creation':
        creation_info['source'] = 'unproven-sponsor'
    elif damage == 'creation_program':
        creation_info['owner'] = TOKEN_2022
    elif damage == 'creation_space':
        creation_info['space'] = 0
    elif damage == 'creation_rent':
        creation_info['lamports'] = 0
    elif damage == 'initialization_owner':
        initialization_info['owner'] = 'another-wallet'
    elif damage == 'initialization_mint':
        initialization_info['mint'] = 'another-mint'
    elif damage == 'closure_owner':
        closure_info['owner'] = 'another-wallet'
    elif damage == 'closure_beneficiary':
        closure_info['destination'] = 'another-wallet'
    elif damage == 'opening_native':
        raw['meta']['preBalances'][5] = 1
        raw['meta']['preBalances'][0] -= 1  # Preserve total: test the zero endpoint proof itself.
    elif damage == 'closing_native':
        raw['meta']['postBalances'][5] = 1
        raw['meta']['postBalances'][0] -= 1
    elif damage == 'native_total':
        raw['meta']['postBalances'][1] += 1
    original_hash = entry['evidence_hash']
    entry['evidence_hash'] = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(',', ':')).encode()).hexdigest()
    assert entry['evidence_hash'] != original_hash
    result = decode_supported_swaps([entry], '4drEkXDZhjun3vjZmz1g7pQGM7kxANQbDuD9jtPZwzJZ')
    assert not swaps(result)
    assert result['coverage']['decoded_swaps'] == 0
    assert result['coverage']['history_complete'] is False
    assert result['unresolved']
    assert all(item['evidence'] == [entry['evidence_hash']] for item in result['unresolved'])
    fee = next(event for event in result['events'] if event['kind'] == 'fee')
    assert fee['amount_sol'] == '0.000141389'
    assert fee['allocation'] == 'unallocated'


@pytest.mark.parametrize('sell', [False, True])
def test_existing_owned_wsol_ata_idempotence_does_not_require_ephemeral_creation(sell):
    entry = record(sell=sell)
    raw = entry['raw']
    raw['transaction']['message']['instructions'].insert(0, {
        'programId': 'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL',
        'parsed': {'type': 'createIdempotent', 'info': {'source': WALLET, 'wallet': WALLET,
                    'account': 'wallet-wsol', 'mint': WSOL}}})
    raw['meta']['innerInstructions'][0]['index'] = 1
    result = decode(entry)
    assert not result['unresolved']
    assert swaps(result)[0]['kind'] == ('sell' if sell else 'buy')
    assert swaps(result)[0]['amount_sol'] == '1'
    assert swaps(result)[0]['fee_sol'] == '0.000005'


@pytest.mark.parametrize('side', ['pre', 'post'])
def test_persistent_wsol_missing_endpoint_is_not_inferred_zero_without_primary_proof(side):
    entry = record(sell=side == 'pre')
    field = f'{side}TokenBalances'
    entry['raw']['meta'][field] = [item for item in entry['raw']['meta'][field]
                                 if item['accountIndex'] != 2]
    result = decode(entry)
    assert not swaps(result)
    assert any('Missing wrapped SOL' in issue['reason'] for issue in result['unresolved'])
    assert result['events'][0]['allocation'] == 'unallocated'


def test_jupiter_v6_route_and_shared_route_use_official_authority_accounts():
    for shared in (False, True):
        entry = record()
        ix = entry['raw']['transaction']['message']['instructions'][0]
        name = 'shared_accounts_route' if shared else 'route'
        route_plan = b'\1\0\0\0' + b'\0\x64\0\1'
        tail = (b'\0' if shared else b'') + route_plan + b'\0' * 19
        ix['programId'] = JUPITER
        ix['data'] = encoded(name, tail)
        ix['accounts'] = [TOKEN_PROGRAM, 'program-authority', WALLET, 'wallet-wsol',
                          'program-source', 'program-destination', 'wallet-token', WSOL, TOKEN,
                          'optional-platform-fee', TOKEN_PROGRAM] if shared else [
                          TOKEN_PROGRAM, WALLET, 'wallet-wsol', 'wallet-token',
                          'optional-destination', TOKEN, 'optional-platform-fee']
        result = decode(entry)
        assert not result['unresolved']
        assert swaps(result)[0]['amount_sol'] == '1'
        assert swaps(result)[0]['source'] == JUPITER
        assert result['coverage']['fixture_validation'][0]['state'] == 'SYNTHETIC_ONLY'
        ix['accounts'][2 if shared else 1] = 'other-wallet'
        assert not swaps(decode(entry))


def test_jupiter_route_instruction_does_not_establish_stable_sol_conversion():
    entry = record()
    ix = entry['raw']['transaction']['message']['instructions'][0]
    ix['programId'] = JUPITER
    ix['data'] = encoded('route', b'\1\0\0\0' + b'\0\x64\0\1' + b'\0' * 19)
    ix['accounts'] = [TOKEN_PROGRAM, WALLET, 'wallet-wsol', 'wallet-token',
                      'optional-destination', TOKEN, 'optional-platform-fee']
    for field in ('preTokenBalances', 'postTokenBalances'):
        for balance in entry['raw']['meta'][field]:
            if balance['mint'] == WSOL:
                balance['mint'] = 'synthetic-usdc'
    for transfer in entry['raw']['meta']['innerInstructions'][0]['instructions']:
        if transfer['parsed']['info'].get('mint') == WSOL:
            transfer['parsed']['info']['mint'] = 'synthetic-usdc'
    for field in ('preBalances', 'postBalances'):
        entry['raw']['meta'][field][2] = entry['raw']['meta'][field][4] = 2_039_280
    assert not swaps(decode(entry))
    ix['data'] = encoded('route', b'\0' * 27)
    assert not swaps(decode(entry))


def test_current_mint_authorities_and_unknown_safety_gates():
    mint = {'owner': TOKEN_PROGRAM, 'data': {'parsed': {'type': 'mint',
            'info': {'mintAuthority': None, 'freezeAuthority': None, 'supply': '1000'}}}}
    result = inspect_token_risk({'result': {'value': mint}})
    assert result['gates']['mint_authority']['state'] == 'PASS'
    assert result['gates']['freeze_authority']['state'] == 'PASS'
    assert result['gates']['token_extensions']['state'] == 'PASS'
    assert result['gates']['historical_sellability']['state'] == 'UNKNOWN'
    assert result['status'] == 'UNRESOLVED'
    assert result['safe'] is None
    mint['data']['parsed']['info']['freezeAuthority'] = 'authority'
    assert inspect_token_risk(mint)['gates']['freeze_authority']['state'] == 'FAIL'


def test_missing_mint_and_missing_fields_remain_unknown():
    assert all(gate['state'] == 'UNKNOWN' for gate in inspect_token_risk(None)['gates'].values())
    mint = {'owner': TOKEN_PROGRAM, 'data': {'parsed': {'type': 'mint', 'info': {}}}}
    assert inspect_token_risk(mint)['gates']['mint_authority']['state'] == 'UNKNOWN'
    mint['owner'] = 'arbitrary-program'
    assert inspect_token_risk(mint)['gates']['mint_identity']['state'] == 'UNKNOWN'


def test_token2022_restrictive_controls_are_flags_not_safe_claims():
    for extension in ({'extension': 'permanentDelegate', 'state': {'delegate': 'authority'}},
                      {'extension': 'transferFeeConfig', 'state': {}},
                      {'extension': 'transferHook', 'state': {'programId': 'hook'}},
                      {'extension': 'defaultAccountState', 'state': {'accountState': 'frozen'}}):
        mint = {'owner': TOKEN_2022, 'data': {'parsed': {'type': 'mint', 'info': {
            'mintAuthority': None, 'freezeAuthority': None, 'extensions': [extension]}}}}
        result = inspect_token_risk(mint)
        assert result['gates']['token_extensions']['state'] == 'FAIL'
        assert result['status'] == 'FLAGGED'
    mint['data']['parsed']['info'].pop('extensions')
    assert inspect_token_risk(mint)['gates']['token_extensions']['state'] == 'UNKNOWN'


def test_concentration_needs_owner_aggregation_and_complete_observation():
    mint = {'owner': TOKEN_PROGRAM, 'data': {'parsed': {'type': 'mint', 'info': {
        'mintAuthority': None, 'freezeAuthority': None, 'supply': '1000'}}}}
    observations = {'pools': [{'liquidity_usd': '100000.01'}],
                    'owners': [{'owner': 'owner-a', 'amount_raw': '300'},
                               {'owner': 'owner-a', 'amount_raw': '100'}]}
    result = inspect_token_risk(mint, observations)
    assert result['gates']['holder_concentration']['state'] == 'UNKNOWN'
    assert result['gates']['current_liquidity']['actual'] == '100000.01'
    observations['owner_balances_complete'] = True
    assert inspect_token_risk(mint, observations)['gates']['holder_concentration']['state'] == 'UNKNOWN'
    observations['owners'] += [{'owner': 'owner-b', 'amount_raw': '600'}]
    result = inspect_token_risk(mint, observations)
    assert result['gates']['holder_concentration']['state'] == 'FAIL'
    assert result['gates']['holder_concentration']['actual']['largest_owner_pct'] == '60'
    assert result['gates']['liquidity_control']['state'] == 'UNKNOWN'
    observations['owners'] = [{'owner': 'impossible', 'amount_raw': '1001'}]
    assert inspect_token_risk(mint, observations)['gates']['holder_concentration']['state'] == 'UNKNOWN'
