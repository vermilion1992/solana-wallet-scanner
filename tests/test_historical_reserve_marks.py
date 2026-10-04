"""Pinned raw genuine reserve observations; no complete-wallet/B3 claim."""
from copy import deepcopy
from contextlib import closing
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path

import pytest

from scanner.historical_reserve_marks import project_historical_reserve_marks
from scanner.json_boundary import canonical_bytes
from scanner.wallet_evidence import derive_wallet_evidence
from scanner.transaction_format import instruction_view

ROOT = Path(__file__).resolve().parents[1]


def fixture(name='mainnet-pumpswap-buy-exact-quote.json'):
    return json.loads((ROOT / 'tests/fixtures' / name).read_text())


def bind(raw):
    return {'signature': raw['transaction']['signatures'][0], 'raw': raw,
            'evidence_hash': hashlib.sha256(canonical_bytes(raw)).hexdigest()}


def project(row, *, alternatives=(), raw_sources=(), source_receipts=()):
    original = deepcopy(row)
    raw = row['raw']
    from scanner.investigation import _keys, _accounts, _program
    semantic = instruction_view(raw)
    keys = _keys(semantic['transaction']['message'], semantic['meta'])
    route = next(ix for ix in semantic['transaction']['message']['instructions']
                 if _program(ix, keys) == 'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA')
    wallet = _accounts(route, keys)[1]
    from datetime import datetime, timezone, timedelta
    clock = raw['blockTime'] if type(raw.get('blockTime')) is int else fixture()['raw']['blockTime']
    end = datetime.fromtimestamp(clock, timezone.utc) + timedelta(days=1)
    window = {'start': (end - timedelta(days=30)).isoformat(), 'end': end.isoformat()}
    evidence = derive_wallet_evidence([row], all_records=[row, *alternatives], wallet=wallet,
        window=window, source_consistency={}, chronology={}, raw_sources=raw_sources,
        source_receipts=source_receipts)
    result = project_historical_reserve_marks([row], all_records=[row, *alternatives], raw_sources=raw_sources,
        consistency=evidence['source_consistency'], chronology=evidence['chronology'])
    assert row == original and result['provider_requests'] == result['credential_lookups'] == 0
    assert result['qualification'] is False and result['historical_boundary_completeness'] == 'UNKNOWN'
    return result, evidence


def genuine_mixed_buy(tmp_path):
    """Load originals only; no large report, provider request or B3 acceptance."""
    from scanner.archive_input import import_archive, load_archive
    from scanner.storage import Store
    source = ROOT / 'evidence/genuine-report-speed-batch/checker-inputs/genuine87-inventory-input.zip'
    signature = 'bJUHFDZ1vZ3hMYBN6CDquGvJe7VLst1WPq2VjrgAC8uaSRYPzuwTe22Yv6zMhMLsr2mmoFaxCYEoaDHyvM29QSH'
    with closing(Store(tmp_path)) as store:
        loaded = load_archive(store, import_archive(store, source.read_bytes()))
        row = next(row for row in loaded['records'] if row['signature'] == signature)
        return row, loaded['raw_sources'], loaded['receipts']


def test_pinned_primary_vault_contract_and_genuine_exact_phase_prices():
    schema_path = ROOT / 'tests/fixtures/retained_protocol_funding/pump_amm.json'
    assert hashlib.sha256(schema_path.read_bytes()).hexdigest() == '2091433899b07d003d98118ae6cd3c628960fd393b40710b6e15bce6d0e7f2d1'
    schema = json.loads(schema_path.read_text())
    for route in schema['instructions']:
        if route['name'] in ('buy', 'buy_exact_quote_in', 'sell'):
            assert [route['accounts'][n]['name'] for n in (0, 3, 4, 7, 8, 11, 12)] == [
                'pool', 'base_mint', 'quote_mint', 'pool_base_token_account', 'pool_quote_token_account',
                'base_token_program', 'quote_token_program']
    # Independently transcribed original u64 reserve quantities and decimals;
    # the oracle does not call production reserve/price projection functions.
    cases = [
        ('mainnet-pumpswap-buy-exact-quote.json', 452635473,
         ((36405553047293, 828473559360), (36394889435237, 828721948055))),
        ('mainnet-pumpswap-sell-durable-nonce.json', 452638051,
         ((104372559209647, 211967949375), (104377777837607, 211956495282)))]
    for name, slot, values in cases:
        original = fixture(name)
        result, evidence = project(original)
        assert len(result['marks']) == 2
        for phase, (base, quote) in zip(('pre', 'post'), values):
            mark = next(m for m in result['marks'] if m['phase'] == phase)
            assert mark['check']['state'] == 'PASS' and mark['slot'] == slot
            assert mark['base_reserve_raw'] == str(base) and mark['quote_reserve_raw'] == str(quote)
            assert mark['price_ratio_numerator'] == str(quote * 10**6)
            assert mark['price_ratio_denominator'] == str(base * 10**9)
            with localcontext() as context:
                context.prec = 100
                assert Decimal(mark['mark_sol_per_token']) == Decimal(quote) * 10**6 / (Decimal(base) * 10**9)
            assert mark['boundary_eligibility'] == 'EXACT_SIGNATURE_PHASE_ONLY'
            assert mark['executable_liquidation_state'] == 'UNKNOWN'
            economic = evidence['economic_evidence']
            held = next(point for point in economic['observed_token_phases'][original['signature']][phase]
                        if point['mint'] == mark['mint'])
            assert held['check']['state'] == 'PASS' and held['reserve_mark_indexes']
            assert held['valuation_method'] == result['method']
            assert held['mark_ratio'] == {'numerator': str(quote * 10**6), 'denominator': str(base * 10**9)}
            with localcontext() as context:
                context.prec = 100
                assert Decimal(held['observed_token_value_sol']) == Decimal(held['quantity_raw']) * Decimal(quote) / (Decimal(base) * 10**9)
            assert economic['economic_inputs'] == {}
            assert economic['component_checks']['boundary_inventory']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('kind', ['missing', 'reserve-conflict', 'unsupported', 'malformed-index', 'wrong-vault-owner'])
def test_required_alternative_loss_conflict_or_malformed_original_revokes_and_restores(kind):
    row = fixture()
    alternative = deepcopy(row['raw'])
    alternative['meta']['logMessages'] = ['irrelevant genuine original changes are development controls']
    good = bind(alternative)
    parent, parent_evidence = project(row, alternatives=[good])
    assert len(parent['marks']) == 2
    bad = deepcopy(good)
    if kind == 'missing':
        bad['raw'] = None
    elif kind == 'reserve-conflict':
        bad['raw']['meta']['preTokenBalances'][0]['uiTokenAmount']['amount'] = '100'
        bad = bind(bad['raw'])
    elif kind == 'unsupported':
        bad['raw']['version'] = 1
        bad = bind(bad['raw'])
    elif kind == 'malformed-index':
        bad['raw']['meta']['preTokenBalances'][0]['accountIndex'] = -1
        bad = bind(bad['raw'])
    else:
        bad['raw']['meta']['preTokenBalances'][0]['owner'] = '11111111111111111111111111111111'
        bad = bind(bad['raw'])
    missing, missing_evidence = project(row, alternatives=[bad])
    assert missing['marks'] == []
    receipt = missing['records'][row['signature']]
    assert receipt['state'] == 'UNKNOWN' and bad['evidence_hash'] in receipt['evidence']
    for phase in ('pre', 'post'):
        valued_parent = [point for point in parent_evidence['economic_evidence']['observed_token_phases'][row['signature']][phase]
                        if point.get('valuation_method') == parent['method']]
        assert valued_parent
        assert not any(point.get('valuation_method') == parent['method'] for point in
                       missing_evidence['economic_evidence']['observed_token_phases'][row['signature']][phase])
    restored, restored_evidence = project(row, alternatives=[good])
    assert restored == parent
    assert restored_evidence['economic_evidence'] == parent_evidence['economic_evidence']


def test_network_fee_loss_is_independent_but_clock_or_original_byte_loss_is_required():
    raw = fixture()['raw']
    raw['meta']['fee'] = None
    result, evidence = project(bind(raw))
    assert len(result['marks']) == 2
    assert evidence['components']['native_fee']['state'] == 'UNKNOWN'
    assert any(point.get('valuation_method') == result['method'] and point['check']['state'] == 'PASS'
               for point in evidence['economic_evidence']['observed_token_phases'][bind(raw)['signature']]['post'])
    missing_clock = deepcopy(raw)
    missing_clock['blockTime'] = None
    result, _ = project(bind(missing_clock))
    assert result['marks'] == []
    unbound = bind(raw)
    unbound['raw']['meta']['preTokenBalances'][0]['uiTokenAmount']['amount'] = '42'
    result, _ = project(unbound)
    assert result['marks'] == []


def test_genuine_mixed_buy_retains_only_disjoint_reserve_marks_and_required_sources(tmp_path):
    row, sources, receipts = genuine_mixed_buy(tmp_path)
    frozen = deepcopy(row)
    schema = json.loads((ROOT / 'tests/fixtures/retained_protocol_funding/pump_amm.json').read_text())
    expected_layouts = {
        'sync_user_volume_accumulator': ([86, 31, 192, 87, 163, 87, 79, 238],
            ['user', 'global_volume_accumulator', 'user_volume_accumulator', 'event_authority', 'program']),
        'close_user_volume_accumulator': ([249, 69, 164, 218, 150, 103, 84, 138],
            ['user', 'user_volume_accumulator', 'event_authority', 'program'])}
    for name, (discriminator, accounts) in expected_layouts.items():
        contract = next(ix for ix in schema['instructions'] if ix['name'] == name)
        assert contract['discriminator'] == discriminator
        assert [account['name'] for account in contract['accounts']] == accounts
        assert contract['args'] == []
    result, evidence = project(row, raw_sources=sources, source_receipts=receipts)
    assert result['version'] == 'historical-pumpswap-reserve-marks-v2'
    assert len(result['marks']) == 2
    # Independently transcribed original vault balances, not decoder tables or
    # the marked output. The bought units subsequently leave this wallet.
    for phase, base, quote in [('pre', 102735740968698, 189354435726),
                               ('post', 102692365334928, 189434576012)]:
        point = next(point for point in result['marks'] if point['phase'] == phase)
        assert point['check']['state'] == 'PASS' and point['slot'] == 411087612
        assert point['base_reserve_raw'] == str(base) and point['quote_reserve_raw'] == str(quote)
        assert point['price_ratio_numerator'] == str(quote * 10**6)
        assert point['price_ratio_denominator'] == str(base * 10**9)
        for index in (1, 2):
            assert f'transaction.message.instructions.{index}.data' in point['raw_paths']
            assert f'transaction.message.instructions.{index}.programIdIndex' in point['raw_paths']
    from scanner.investigation import decode_supported_swaps
    wallet = '2Bj3dZTSSc14hFR9fCLN9CQ1TiaYyszCKX8fuVG7pyAY'
    assert not any(event['kind'] in ('buy', 'sell') for event in
                   decode_supported_swaps([row], wallet)['events'])
    assert evidence['economic_evidence']['economic_inputs'] == {} and row == frozen
    alternative = deepcopy(row['raw'])
    alternative['meta']['logMessages'] = ['Development duplicate control; original retained unchanged']
    good = bind(alternative)
    parent, _ = project(row, alternatives=[good], raw_sources=sources, source_receipts=receipts)
    missing = {**good, 'raw': None}
    lost, lost_evidence = project(row, alternatives=[missing], raw_sources=sources, source_receipts=receipts)
    assert lost['marks'] == [] and lost['records'][row['signature']]['state'] == 'UNKNOWN'
    assert lost_evidence['components']['native_fee']['state'] == 'UNKNOWN'
    restored, _ = project(row, alternatives=[good], raw_sources=sources, source_receipts=receipts)
    assert restored == parent and row == frozen


def test_disjoint_admin_requires_exact_layout_and_all_pool_reference_roles(tmp_path):
    from scanner.historical_reserve_marks import _points
    row, _, _ = genuine_mixed_buy(tmp_path)
    original = row['raw']
    assert len(_points(original)) == 2
    for control in ('trailing-bytes', 'wrong-arity', 'unknown-opcode', 'program-conflict',
                    'mixed-representation', 'pool-overlap', 'later-route-overlap',
                    'inner-pool-overlap', 'duplicate-inner-association', 'malformed-inner-association',
                    'quote-underbacked', 'quote-cash-missing', 'quote-cash-bool'):
        raw = deepcopy(original)
        instructions = raw['transaction']['message']['instructions']
        admin = instructions[1]
        if control == 'trailing-bytes':
            # This known fixed no-argument opcode cannot accept trailing data.
            from test_investigation import encoded
            admin['data'] = encoded('sync_user_volume_accumulator', b'\0')
        elif control == 'wrong-arity':
            admin['accounts'].append(admin['accounts'][0])
        elif control == 'unknown-opcode':
            from test_investigation import encoded
            admin['data'] = encoded('unreviewed_admin', b'')
        elif control == 'program-conflict':
            admin['programId'] = '11111111111111111111111111111111'
        elif control == 'mixed-representation':
            admin['parsed'] = {'type': 'sync_user_volume_accumulator', 'info': {'account': 'ignored'}}
        elif control == 'pool-overlap':
            admin['accounts'][1] = instructions[0]['accounts'][7]
        elif control == 'later-route-overlap':
            # A guard against only the first pool would miss this later route.
            later = deepcopy(instructions[0])
            later['accounts'][7] = admin['accounts'][1]
            instructions.append(later)
        elif control == 'inner-pool-overlap':
            group = next(group for group in raw['meta']['innerInstructions'] if group['index'] == 2)
            group['instructions'][0]['accounts'].append(instructions[0]['accounts'][7])
        elif control == 'duplicate-inner-association':
            raw['meta']['innerInstructions'].append(deepcopy(raw['meta']['innerInstructions'][-1]))
        elif control == 'malformed-inner-association':
            raw['meta']['innerInstructions'][-1]['index'] = True
        else:
            quote_index = instructions[0]['accounts'][8]
            if control == 'quote-underbacked':
                raw['meta']['preBalances'][quote_index] = 189354435725
            elif control == 'quote-cash-missing':
                raw['meta']['preBalances'] = None
            else:
                raw['meta']['preBalances'][quote_index] = True
        with pytest.raises(ValueError):
            _points(raw)
        rejected, _ = project(bind(raw))
        assert rejected['marks'] == []
    unrelated = deepcopy(original)
    # Keep the original RPC schema/conservation valid while changing unrelated
    # cash facts. A malformed unsigned wallet cash value would independently
    # fail the shared native-record admission, beyond this price projection.
    unrelated['meta']['preBalances'][0] += 1
    unrelated['meta']['preBalances'][5] -= 1
    unrelated['meta']['fee'] = None
    retained, _ = project(bind(unrelated))
    assert len(retained['marks']) == 2
    assert len(_points(original)) == 2
