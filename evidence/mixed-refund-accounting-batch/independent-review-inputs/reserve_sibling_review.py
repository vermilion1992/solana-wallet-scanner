"""Independent exact original-phase reserve and disjointness review controls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import sys
from reproduce import ROOT, OUT
from test_historical_reserve_marks import fixture, bind, project, genuine_mixed_buy
from scanner.historical_reserve_marks import _points
from scanner.investigation import _keys, _accounts, _program, PUMP_SWAP
from scanner.providers import TOKEN_PROGRAM

def check():
    primary = ROOT / 'tests/fixtures/retained_protocol_funding/pump_amm.json'
    assert hashlib.sha256(primary.read_bytes()).hexdigest() == '2091433899b07d003d98118ae6cd3c628960fd393b40710b6e15bce6d0e7f2d1'
    with tempfile.TemporaryDirectory(prefix='reserve-admin-review-') as runtime:
        row, sources, receipts = genuine_mixed_buy(Path(runtime))
        original = deepcopy(row)
        positive, _ = project(row, raw_sources=sources, source_receipts=receipts)
        assert len(positive['marks']) == 2
        expected = {'pre': (102735740968698, 189354435726), 'post': (102692365334928, 189434576012)}
        for mark in positive['marks']:
            base, quote = expected[mark['phase']]
            assert mark['price_ratio_numerator'] == str(quote * 10**6)
            assert mark['price_ratio_denominator'] == str(base * 10**9)
        assert row == original
        raw = deepcopy(row['raw'])
        msg = raw['transaction']['message']
        vault = msg['instructions'][0]['accounts'][7]
        groups = raw['meta']['innerInstructions']
        group = next((g for g in groups if g['index'] == 1), None)
        if group is None:
            group = {'index': 1, 'instructions': []}
            groups.append(group)
        group['instructions'].append({'programIdIndex': msg['accountKeys'].index(TOKEN_PROGRAM), 'accounts': [vault], 'data': '1'})
        rejected, _ = project(bind(raw))
        assert rejected['marks'] == [] and rejected['records'][row['signature']]['state'] == 'UNKNOWN'
        assert len(_points(original['raw'])) == 2

    raw = deepcopy(fixture()['raw'])
    keys = _keys(raw['transaction']['message'], raw['meta'])
    route = next(ix for ix in raw['transaction']['message']['instructions'] if _program(ix, keys) == PUMP_SWAP)
    index = keys.index(_accounts(route, keys)[8])
    quote = int(next(r for r in raw['meta']['preTokenBalances'] if r['accountIndex'] == index)['uiTokenAmount']['amount'])
    old = raw['meta']['preBalances'][index]
    raw['meta']['preBalances'][index] = quote - 1
    raw['meta']['preBalances'][0] += old - (quote - 1)
    rejected, evidence = project(bind(raw))
    assert rejected['marks'] == [] and rejected['records'][raw['transaction']['signatures'][0]]['state'] == 'UNKNOWN'
    independent = deepcopy(fixture()['raw'])
    independent['meta']['fee'] = None
    known, _ = project(bind(independent))
    assert len(known['marks']) == 2
    return {'state': 'PASS', 'method': 'historical-pumpswap-reserve-marks-v2',
        'genuine_disjoint_admin_positive': {'phases': 2, 'original_immutable': True, 'independent_integer_reserve_ratios': True},
        'protected_inner_cpi_contradiction': 'UNKNOWN', 'quote_collateral_contradiction': 'UNKNOWN',
        'missing_unrelated_network_fee': 'PASS', 'provider_calls': 0, 'credential_lookups': 0,
        'full_wallet_qualification': False}

if __name__ == '__main__':
    result = check()
    (OUT / sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
