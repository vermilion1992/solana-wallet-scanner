"""Evidence loss cannot bypass a proved impossible prior source balance."""
from copy import deepcopy
import json
import sys
from reproduce import controls, OUT
from test_wallet_evidence import derive

raw, _ = controls()['system-topup-close']
raw['meta']['preBalances'][0] = 0
raw['meta']['postBalances'][0] = 1_995_000
results = {}
for fee in (5_000, None):
    current = deepcopy(raw)
    current['meta']['fee'] = fee
    evidence = derive([current])
    results[str(fee)] = evidence['cost_flow_evidence']['transactions'][current['transaction']['signatures'][0]]
output = {'control': 'First 1000lamport Systemtransfer from walletopening0 cannot execute for any fee>=0 before laterrefund',
    'expected': {'known_fee': 'UNKNOWN', 'fee_removed': 'UNKNOWN'}, 'actual': results}
(OUT / sys.argv[1]).write_text(json.dumps(output, indent=2) + '\n')
print(json.dumps({key: row['check']['state'] for key, row in results.items()}))
