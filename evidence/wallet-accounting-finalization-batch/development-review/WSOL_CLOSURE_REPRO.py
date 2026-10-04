from pathlib import Path
import sys, json
sys.path.insert(0, str(Path('/workspace/solana-wallet-scanner/tests')))
from test_cost_flow_evidence import primary, base, parsed, project, ACCOUNT, WALLET
from scanner.investigation import WSOL
raw = primary(base(quantity=100))
for row in raw['meta']['preTokenBalances'] + raw['meta']['postTokenBalances']:
    if row['accountIndex'] == 1:
        row['mint'] = WSOL
        row['uiTokenAmount']['decimals'] = 9
raw['meta']['preBalances'][1] = 2_000_100
raw['meta']['postTokenBalances'] = [row for row in raw['meta']['postTokenBalances'] if row['accountIndex'] != 1]
raw['meta']['postBalances'][1] = 0
raw['meta']['postBalances'][0] += 2_000_100
raw['transaction']['message']['instructions'] = [parsed('closeAccount', {'account': ACCOUNT, 'destination': WALLET, 'owner': WALLET})]
result, selected = project(raw)
row = result['transactions'][selected['signature']]
print(json.dumps({'input_kind':'synthetic interface control, not B3', 'quantity_raw':'100', 'explicit_wallet_refund_lamports':'2000100', 'role_receipt':row, 'ledger_kinds':[e['kind'] for e in result['ledger_events']]}))
