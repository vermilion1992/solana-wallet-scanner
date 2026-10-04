"""Pinned raw genuine reserve observations; no complete-wallet/B3 claim."""
from copy import deepcopy
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path

import pytest

from scanner.historical_reserve_marks import project_historical_reserve_marks
from scanner.json_boundary import canonical_bytes
from scanner.wallet_evidence import derive_wallet_evidence

ROOT = Path(__file__).resolve().parents[1]


def fixture(name='mainnet-pumpswap-buy-exact-quote.json'):
    return json.loads((ROOT / 'tests/fixtures' / name).read_text())


def bind(raw):
    return {'signature': raw['transaction']['signatures'][0], 'raw': raw,
            'evidence_hash': hashlib.sha256(canonical_bytes(raw)).hexdigest()}


def project(row, *, alternatives=()):
    original = deepcopy(row)
    raw = row['raw']
    route = next(ix for ix in raw['transaction']['message']['instructions']
                 if ix.get('programId') == 'pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA')
    wallet = route['accounts'][1]
    from datetime import datetime, timezone, timedelta
    clock = raw['blockTime'] if type(raw.get('blockTime')) is int else fixture()['raw']['blockTime']
    end = datetime.fromtimestamp(clock, timezone.utc) + timedelta(days=1)
    window = {'start': (end - timedelta(days=30)).isoformat(), 'end': end.isoformat()}
    evidence = derive_wallet_evidence([row], all_records=[row, *alternatives], wallet=wallet,
        window=window, source_consistency={}, chronology={})
    result = project_historical_reserve_marks([row], all_records=[row, *alternatives], raw_sources=[],
        consistency=evidence['source_consistency'], chronology=evidence['chronology'])
    assert row == original and result['provider_requests'] == result['credential_lookups'] == 0
    assert result['qualification'] is False and result['historical_boundary_completeness'] == 'UNKNOWN'
    return result, evidence


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
