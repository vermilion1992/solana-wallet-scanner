"""Contradictory native-token state, not genuine financial acceptance."""
import json
import sys
from reproduce import controls, OUT
from test_wallet_evidence import derive, parsed, WALLET

raw, _ = controls()['native-incoming-close']
account = raw['transaction']['message']['accountKeys'][2]
raw['transaction']['message']['instructions'] = [parsed('closeAccount', {
    'account': account, 'destination': WALLET, 'owner': WALLET})]
for point in raw['meta']['preTokenBalances']:
    if point['accountIndex'] == 1:
        point['uiTokenAmount']['amount'] = '0'
raw['meta']['preBalances'][1] = 2_000_000
raw['meta']['preBalances'][2] = 999_999_999
raw['meta']['postBalances'][0] = raw['meta']['preBalances'][0] - 5_000 + 999_999_999
evidence = derive([raw])
signature = raw['transaction']['signatures'][0]
result = {'control': 'Canonical legacyWSOL units exceed account lamports; exact native conservation still holds',
    'input': raw, 'expected': {'dependent_quantities_or_roles': 'UNKNOWN', 'independent_network_fee': 'PASS'},
    'actual': {'economic_roles': evidence['components']['observed_economic_roles'],
        'native_fee': evidence['components']['native_fee'],
        'pair': evidence['transactions'][signature]['boundaries'][account],
        'roles': evidence['cost_flow_evidence']['transactions'][signature]}}
(OUT / sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({'economic_roles': result['actual']['economic_roles']['state'],
    'quantities': result['actual']['pair']['checks']['quantities']['state'],
    'fee': result['actual']['native_fee']['state']}))
