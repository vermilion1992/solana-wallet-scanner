"""Original genuine quote/lot controls; no complete-wallet acceptance claim."""
from copy import deepcopy
from decimal import Decimal, localcontext
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from scanner.archive_input import import_archive, load_archive, decode_archive, analyze_archive
from scanner.indexed_input import convert_indexed_archive
from scanner.investigation import decode_supported_swaps, _canonical_user_volume_address, _data, PUMP_SWAP
from scanner.storage import Store
from scanner.wallet_evidence import derive_wallet_evidence

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / 'evidence/genuine-wallet-batch/collection/phase5/02-lifetime-page-1-response.raw.gz'
PAGE_HASH = '7517110b5b3825584ec24a6e48aad3c23fbcc4c475056f7708d56b87a999fe7a'
WALLET = '2Bj3dZTSSc14hFR9fCLN9CQ1TiaYyszCKX8fuVG7pyAY'
MINT = 'BQJfL1yiHbJQ8AciHLcKxaCbQrWP2ws8oZHHYgbBpump'
WINDOW = {'start': '2026-09-04T06:00:00+00:00', 'end': '2026-10-04T06:00:00+00:00'}


def originals():
    body = gzip.decompress(PAGE.read_bytes())
    assert hashlib.sha256(body).hexdigest() == PAGE_HASH
    return json.loads(body)['result']['data']


def wrapped(raw):
    body = json.dumps(raw, sort_keys=True, separators=(',', ':')).encode()
    return {'signature': raw['transaction']['signatures'][0], 'evidence_hash': hashlib.sha256(body).hexdigest(), 'raw': raw}


def decode(raw):
    return decode_supported_swaps([wrapped(raw)], WALLET)


def b58(value):
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number, result = int.from_bytes(value, 'big'), ''
    while number:
        number, remainder = divmod(number, 58)
        result = alphabet[remainder] + result
    return '1' * (len(value) - len(value.lstrip(b'\0'))) + result


def creation(raw, *, lamports=None, space=None):
    op = raw['meta']['innerInstructions'][1]['instructions'][0]
    data = bytearray(_data(op['data']))
    if lamports is not None:
        data[4:12] = lamports.to_bytes(8, 'little')
    if space is not None:
        data[12:20] = space.to_bytes(8, 'little')
    op['data'] = b58(data)


def lot(receipt):
    return next(row for row in receipt['query_accounting']['supported_selected_lots'] if row['mint'] == MINT)


def assess(store, digest, inventory=None):
    options = {'dependency_input_hash': inventory} if inventory else {}
    loaded = load_archive(store, digest, **options)
    events, _ = decode_archive(loaded)
    result, _, receipt = analyze_archive(loaded, events)
    return loaded, result, receipt


def test_primary_idl_seed_and_original_native_quote_have_independent_integer_expectations():
    fixture = ROOT / 'tests/fixtures/retained_protocol_funding/pump_amm.json'
    body = fixture.read_bytes()
    assert hashlib.sha256(body).hexdigest() == '2091433899b07d003d98118ae6cd3c628960fd393b40710b6e15bce6d0e7f2d1'
    idl = json.loads(body)
    for instruction in idl['instructions']:
        if instruction['name'] in ('buy', 'buy_exact_quote_in'):
            assert instruction['accounts'][20]['name'] == 'user_volume_accumulator'
    address, bump = _canonical_user_volume_address(WALLET)
    assert address.hex() == '7a104e96253650fec72955994114750274e7877aba0aeb4e8659848e9265e939'
    assert bump == 255
    raw = originals()[83]
    event = next(e for e in decode(raw)['events'] if e['kind'] == 'buy')
    assert event['amount_sol'] == '0.5651351'  # 559550761+139609+5305122+139608
    assert event['fee_sol'] == '0.000058918'
    funding = event['retained_account_funding'][0]
    assert funding['lamports'] == 1346200
    assert funding['space'] == 137
    assert funding['recovery_state'] == funding['valuation_state'] == 'UNKNOWN'
    for path in funding['raw_paths']:
        value = raw
        for key in path.split('.'):
            value = value[int(key)] if isinstance(value, list) else value[key]


@pytest.mark.parametrize('failure', ['payer', 'owner', 'account', 'allocation-zero', 'native-endpoint', 'extra-movement', 'unrelated-tip', 'outside-create'])
def test_retained_funding_role_does_not_accept_arbitrary_create_or_native_tips(failure):
    raw = deepcopy(originals()[83])
    op = raw['meta']['innerInstructions'][1]['instructions'][0]
    if failure == 'payer':
        op['accounts'][0] = raw['transaction']['message']['instructions'][3]['accounts'][0]
    elif failure == 'owner':
        data = bytearray(_data(op['data'])); data[-32:] = _data(WALLET); op['data'] = b58(data)
    elif failure == 'account':
        raw['transaction']['message']['instructions'][3]['accounts'][20] = 0
    elif failure == 'allocation-zero':
        creation(raw, space=0)
    elif failure == 'native-endpoint':
        raw['meta']['postBalances'][op['accounts'][1]] += 1
    elif failure == 'extra-movement':
        extra = {'programId': '11111111111111111111111111111111', 'parsed': {'type': 'transfer',
            'info': {'source': WALLET, 'destination': '9DVALworRmwiFeFgqqRGYkrsQxCJsQ9u1VCQiG5Fk8kg', 'lamports': 1}}}
        raw['meta']['innerInstructions'][1]['instructions'].append(extra)
    elif failure == 'unrelated-tip':
        destination = raw['transaction']['message']['accountKeys'][1]
        raw['meta']['innerInstructions'][1]['instructions'].append({'programId': '11111111111111111111111111111111',
            'parsed': {'type': 'transfer', 'info': {'source': WALLET, 'destination': destination, 'lamports': 1}}})
        raw['meta']['postBalances'][0] -= 1
        raw['meta']['postBalances'][1] += 1
    else:
        destination = raw['transaction']['message']['accountKeys'][1]
        raw['transaction']['message']['instructions'].append({'programId': '11111111111111111111111111111111',
            'parsed': {'type': 'createAccount', 'info': {'source': WALLET, 'newAccount': destination,
                'owner': WALLET, 'lamports': 1, 'space': 137}}})
        raw['meta']['postBalances'][0] -= 1
        raw['meta']['postBalances'][1] += 1
    result = decode(raw)
    assert not any(event['kind'] == 'buy' for event in result['events'])
    assert result['unresolved']
    assert next(event for event in result['events'] if event['kind'] == 'fee')['amount_sol'] == '0.000058918'


def test_observed_allocation_size_is_not_mistaken_for_a_universal_protocol_constant():
    raw = deepcopy(originals()[83])
    creation(raw, space=138)
    event = next(e for e in decode(raw)['events'] if e['kind'] == 'buy')
    assert event['amount_sol'] == '0.5651351'
    assert event['retained_account_funding'][0]['space'] == 138


def test_genuine_pair_uses_existing_fifo_for_quote_basis_loss_and_timing():
    raws = originals()
    records = [wrapped(raws[i]) for i in (83, 85)]
    result = derive_wallet_evidence(records, all_records=records, wallet=WALLET, window=WINDOW,
        source_consistency={}, chronology={})
    selected = result['query_accounting']['supported_selected_lots'][0]
    assert selected['monetary_state'] == selected['timing_state'] == selected['quantity_state'] == 'PASS'
    assert selected['conditional_basis_sol'] == '0.565194018'
    assert selected['conditional_proceeds_sol'] == '0.551929943'
    assert selected['conditional_exit_fees_sol'] == '0.000006849'
    assert selected['conditional_lot_profit_sol'] == '-0.013270924'
    with localcontext() as context:
        context.prec = 192
        assert Decimal(selected['conditional_hold_hours']) == Decimal(529) / Decimal(3600)
    assert selected['classification_state'] == selected['wallet_population_state'] == 'UNKNOWN'
    assert selected['qualification'] is False
    assert result['metric_dependencies']['profit_sol']['state'] == 'UNKNOWN'


def test_sale_without_supported_origin_cannot_invent_a_zero_hour_named_holding_period():
    sale = wrapped(originals()[85])
    result = derive_wallet_evidence([sale], all_records=[sale], wallet=WALLET, window=WINDOW,
        source_consistency={}, chronology={})
    selected = result['query_accounting']['supported_selected_lots'][0]
    assert selected['monetary_state'] == selected['timing_state'] == 'UNKNOWN'
    assert selected['conditional_lot_profit_sol'] is selected['conditional_hold_hours'] is None


def test_named_lot_inspection_budget_does_not_certify_a_convenient_prefix(monkeypatch):
    import scanner.wallet_evidence as module
    monkeypatch.setattr(module, 'MAX_ACCOUNT_STEPS', 1)
    raws = originals()
    records = [wrapped(raws[i]) for i in (83, 85)]
    result = derive_wallet_evidence(records, all_records=records, wallet=WALLET, window=WINDOW,
        source_consistency={}, chronology={})
    assert result['query_accounting']['selected_lot_inspection']['state'] == 'UNKNOWN'
    assert result['query_accounting']['supported_selected_lots'] == []


@pytest.mark.parametrize('missing_index', [72, 83, 85])
def test_complete_original_page_preserves_scoped_lot_but_revokes_its_required_selected_source(tmp_path, missing_index):
    store = Store(tmp_path)
    archive = ROOT / 'evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip'
    digest = import_archive(store, convert_indexed_archive(archive.read_bytes()))
    loaded, parent, receipt = assess(store, digest)
    target = lot(receipt)
    assert receipt['query_accounting']['monetary_state'] == 'UNKNOWN'
    assert target['monetary_state'] == target['timing_state'] == 'PASS'
    assert target['conditional_lot_profit_sol'] == '-0.013270924'
    signature = originals()[missing_index]['transaction']['signatures'][0]
    pointer = next(row['hash'] for row in loaded['manifest']['transactions'] if row['signature'] == signature)
    path = store.path / 'evidence' / f'{pointer}.json.gz'
    original = path.read_bytes(); path.unlink()
    _, child, child_receipt = assess(store, digest, loaded['dependency_input_hash'])
    candidate = lot(child_receipt)
    if missing_index in (83, 85):
        assert candidate['monetary_state'] == 'UNKNOWN'
        assert candidate['conditional_lot_profit_sol'] is None
    else:
        assert candidate['monetary_state'] == candidate['timing_state'] == 'PASS'
        assert candidate['conditional_lot_profit_sol'] == '-0.013270924'
        assert child['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    path.write_bytes(original)
    _, restored, restored_receipt = assess(store, digest, loaded['dependency_input_hash'])
    assert restored == parent
    assert restored_receipt == receipt


def cash(source, destination, lamports):
    return {'programId': '11111111111111111111111111111111', 'parsed': {'type': 'transfer',
        'info': {'source': source, 'destination': destination, 'lamports': lamports}}}


def foreign_cash_loop(raw):
    """Unsigned schema mutation; shift every original numeric key reference."""
    from test_compiled_instructions import KEYS
    result = deepcopy(raw)
    message = result['transaction']['message']
    foreign = KEYS['source']
    assert foreign not in message['accountKeys']
    message['accountKeys'].insert(1, foreign)
    message['header']['numRequiredSignatures'] += 1
    result['transaction']['signatures'].append(result['transaction']['signatures'][0])
    for field in ('preBalances', 'postBalances'):
        result['meta'][field].insert(1, 1000)
    for field in ('preTokenBalances', 'postTokenBalances'):
        for row in result['meta'][field]:
            row['accountIndex'] += int(row['accountIndex'] >= 1)
    for operation in message['instructions'] + [item for group in result['meta']['innerInstructions'] for item in group['instructions']]:
        if 'programIdIndex' in operation:
            operation['programIdIndex'] += int(operation['programIdIndex'] >= 1)
        if 'accounts' in operation:
            operation['accounts'] = [index + int(index >= 1) for index in operation['accounts']]
    group = next(group for group in result['meta']['innerInstructions'] if group['index'] == 3)
    group['instructions'] += [cash(WALLET, foreign, 1), cash(foreign, WALLET, 1)]
    return result


@pytest.mark.parametrize('selection', ['mutated-selected', 'mutated-alternative'])
def test_gross_cash_role_loss_preserves_named_quantity_timing_and_independent_fees(selection):
    raws = originals()
    clean_buy, sale = wrapped(raws[83]), wrapped(raws[85])
    bad = wrapped(foreign_cash_loop(raws[83]))
    selected = [bad, sale] if selection == 'mutated-selected' else [clean_buy, sale]
    links = selected if selection == 'mutated-selected' else [*selected, bad]
    result = derive_wallet_evidence(selected, all_records=links, wallet=WALLET, window=WINDOW,
        source_consistency={}, chronology={})
    target = result['query_accounting']['supported_selected_lots'][0]
    assert target['monetary_state'] == 'UNKNOWN' and target['conditional_lot_profit_sol'] is None
    assert target['quantity_state'] == target['timing_state'] == 'PASS'
    assert result['components']['native_fee']['state'] == 'PASS'
    permuted = derive_wallet_evidence(list(reversed(selected)), all_records=list(reversed(links)),
        wallet=WALLET, window=WINDOW, source_consistency={}, chronology={})
    assert permuted == result
    missing = [{**row, 'raw': None} if row['evidence_hash'] == bad['evidence_hash'] else row for row in links]
    if selection == 'mutated-selected':
        selected_missing = [missing[0], sale]
    else:
        selected_missing = selected
    lost = derive_wallet_evidence(selected_missing, all_records=missing, wallet=WALLET, window=WINDOW,
        source_consistency={}, chronology={})
    assert lost['query_accounting']['supported_selected_lots'][0]['monetary_state'] == 'UNKNOWN'
    assert derive_wallet_evidence(selected, all_records=links, wallet=WALLET, window=WINDOW,
        source_consistency={}, chronology={}) == result
    restored = derive_wallet_evidence([clean_buy, sale], all_records=[clean_buy, sale], wallet=WALLET,
        window=WINDOW, source_consistency={}, chronology={})
    assert restored['query_accounting']['supported_selected_lots'][0]['conditional_lot_profit_sol'] == '-0.013270924'


def native_pair():
    """Independent unsigned ABI development input, with ordinary integer cash."""
    from scanner.investigation import PUMP
    import base64
    key = lambda value: b58(bytes([value]) * 32)
    wallet, own, curve, pool, fee, foreign, mint = (key(value) for value in range(1, 8))
    token, system = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA', '11111111111111111111111111111111'
    keys = [wallet, foreign, own, curve, pool, fee, mint, PUMP, token, system]
    result = []
    for sell in (False, True):
        name = 'sell' if sell else 'buy'
        quote = 900_000_000 if sell else 1_000_000_000
        before = [10_000_000_000, 1000, 2_039_280, 2_000_000_000, 2_039_280, 1000, 0, 1, 1, 1]
        after = list(before)
        after[0] += quote - 5000 if sell else -quote - 5000
        after[3] += -quote if sell else quote
        def balance(index, units, owner):
            return {'accountIndex': index, 'mint': mint, 'owner': owner, 'programId': token,
                'uiTokenAmount': {'amount': str(units), 'decimals': 6}}
        src, dst = (own, pool) if sell else (pool, own)
        flow = {'programId': token, 'parsed': {'type': 'transferChecked', 'info': {
            'source': src, 'destination': dst, 'mint': mint, 'tokenAmount': {'amount': '100', 'decimals': 6}}}}
        data = hashlib.sha256(('global:' + name).encode()).digest()[:8] + bytes(16)
        raw = {'version': 'legacy', 'slot': 10 + int(sell), 'blockTime': 1791079700 + 529 * int(sell),
            'transaction': {'signatures': ['unsigned-native-' + name, 'unsigned-foreign-' + name], 'message': {
                'header': {'numRequiredSignatures': 2, 'numReadonlySignedAccounts': 0, 'numReadonlyUnsignedAccounts': 4},
                'accountKeys': keys, 'instructions': [{'programId': PUMP,
                    'accounts': [fee, fee, mint, curve, pool, own, wallet, system, token],
                    'data': [base64.b64encode(data).decode(), 'base64']}]}},
            'meta': {'err': None, 'fee': 5000, 'preBalances': before, 'postBalances': after,
                'preTokenBalances': [balance(2, 100 if sell else 0, wallet), balance(4, 0 if sell else 100, curve)],
                'postTokenBalances': [balance(2, 0 if sell else 100, wallet), balance(4, 100 if sell else 0, curve)],
                'innerInstructions': [{'index': 0, 'instructions': [
                    cash(curve, wallet, quote) if sell else cash(wallet, curve, quote), flow]}]}}
        result.append(raw)
    return result, wallet, foreign


def test_primary_native_idl_roles_are_pinned_independently_from_decoder_lookup():
    fixture = ROOT / 'tests/fixtures/retained_protocol_funding/pump-native.json'
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == 'ffe966c42f1af41652ee753fe2f1e3f7cd4077d7e6f49faf3138959c8b56064b'
    idl = json.loads(fixture.read_bytes())
    by_name = {item['name']: item for item in idl['instructions']}
    for name in ('buy', 'buy_exact_sol_in', 'sell'):
        accounts = by_name[name]['accounts']
        assert [accounts[i]['name'] for i in (1, 3, 5, 6)] == ['fee_recipient', 'bonding_curve', 'associated_user', 'user']
        assert accounts[8 if name == 'sell' else 9]['name'] == 'creator_vault'
    assert 'Fees are deducted from spendable_sol_in.' in by_name['buy_exact_sol_in']['docs']
    assert any('rent' in line.lower() for line in by_name['buy_exact_sol_in']['docs'])


@pytest.mark.parametrize('sale_mutation', [False, True], ids=['buy', 'sell'])
def test_direct_native_positive_and_foreign_gross_cash_roles_use_same_named_fifo(sale_mutation):
    raws, wallet, foreign = native_pair()
    records = [wrapped(raw) for raw in raws]
    def assess(rows):
        return derive_wallet_evidence(rows, all_records=rows, wallet=wallet, window=WINDOW,
            source_consistency={}, chronology={})
    clean = assess(records)
    target = clean['query_accounting']['supported_selected_lots'][0]
    assert target['monetary_state'] == target['quantity_state'] == target['timing_state'] == 'PASS'
    assert target['conditional_lot_profit_sol'] == '-0.10001'
    raw = deepcopy(raws[int(sale_mutation)])
    raw['meta']['innerInstructions'][0]['instructions'] += [cash(wallet, foreign, 1), cash(foreign, wallet, 1)]
    mutated = list(records); mutated[int(sale_mutation)] = wrapped(raw)
    result = assess(mutated)
    target = result['query_accounting']['supported_selected_lots'][0]
    assert target['monetary_state'] == 'UNKNOWN' and target['conditional_lot_profit_sol'] is None
    assert target['quantity_state'] == target['timing_state'] == 'PASS'
    assert result['components']['native_fee']['state'] == 'PASS'
    decoded = decode_supported_swaps([wrapped(raw)], wallet)
    assert len(decoded['unresolved']) == 2
    assert next(e for e in decoded['events'] if e['kind'] in ('buy', 'sell'))['native_cash_role_state'] == 'UNKNOWN'
    assert assess(list(reversed(mutated))) == result
    assert assess(records) == clean


@pytest.mark.parametrize('sale', [False, True], ids=['buy', 'sell'])
def test_reverse_quote_counterparty_loop_does_not_inherit_a_protocol_cash_role(sale):
    raws, wallet, _ = native_pair()
    raw = deepcopy(raws[int(sale)])
    curve = raw['transaction']['message']['accountKeys'][3]
    raw['meta']['innerInstructions'][0]['instructions'] += [cash(wallet, curve, 1), cash(curve, wallet, 1)]
    decoded = decode_supported_swaps([wrapped(raw)], wallet)
    trade = next(event for event in decoded['events'] if event['kind'] in ('buy', 'sell'))
    assert trade['native_cash_role_state'] == 'UNKNOWN'
    assert decoded['events'][0]['allocation'] == 'unallocated'
    assert decoded['unresolved']


def test_absence_of_system_cpi_is_not_an_invented_native_sell_schema_requirement():
    raws, wallet, _ = native_pair()
    raw = raws[1]
    raw['meta']['innerInstructions'][0]['instructions'].pop(0)
    decoded = decode_supported_swaps([wrapped(raw)], wallet)
    assert not decoded['unresolved']
    trade = next(event for event in decoded['events'] if event['kind'] == 'sell')
    assert trade['native_cash_role_state'] == 'PASS' and trade['amount_sol'] == '0.9'


def test_native_buy_fee_and_creator_quote_legs_are_included_once_with_directional_primary_roles():
    raws, wallet, _ = native_pair()
    raw = raws[0]
    message = raw['transaction']['message']
    curve, fee = message['accountKeys'][3], message['accountKeys'][5]
    creator = b58(bytes([8]) * 32)
    message['accountKeys'].insert(7, creator)
    message['header']['numReadonlyUnsignedAccounts'] = 3
    for field in ('preBalances', 'postBalances'):
        raw['meta'][field].insert(7, 1000)
    raw['meta']['postBalances'][3] -= 10
    raw['meta']['postBalances'][5] += 5
    raw['meta']['postBalances'][7] += 5
    message['instructions'][0]['accounts'].append(creator)
    group = raw['meta']['innerInstructions'][0]['instructions']
    group[0]['parsed']['info']['lamports'] -= 10
    group += [cash(wallet, fee, 5), cash(wallet, creator, 5)]
    decoded = decode_supported_swaps([wrapped(raw)], wallet)
    assert not decoded['unresolved']
    trade = next(event for event in decoded['events'] if event['kind'] == 'buy')
    assert trade['native_cash_role_state'] == 'PASS' and trade['amount_sol'] == '1'
    assert trade['fee_sol'] == '0.000005'
    # Reverse creator return has no primary quote/capital-cost role, even when
    # another debit preserves exactly the same endpoints and net consideration.
    group += [cash(wallet, creator, 1), cash(creator, wallet, 1)]
    mutated = decode_supported_swaps([wrapped(raw)], wallet)
    assert next(event for event in mutated['events'] if event['kind'] == 'buy')['native_cash_role_state'] == 'UNKNOWN'
    assert mutated['events'][0]['allocation'] == 'unallocated'
