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
