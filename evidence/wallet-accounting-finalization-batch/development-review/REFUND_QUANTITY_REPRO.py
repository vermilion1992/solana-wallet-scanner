from pathlib import Path
import sys,json
sys.path.insert(0,'/workspace/solana-wallet-scanner/tests')
from test_cost_flow_evidence import wrapped_funding, parsed, derive, WALLET
from scanner.investigation import WSOL
raw,target=wrapped_funding()
source=raw['transaction']['message']['accountKeys'][1]
for phase,quantity in (('preTokenBalances','100'),('postTokenBalances','0')):
 row=next(t for t in raw['meta'][phase] if t['accountIndex']==1)
 row['mint']=WSOL;row['uiTokenAmount']['decimals']=9;row['uiTokenAmount']['amount']=quantity
raw['meta']['preBalances'][1]=2000100
raw['meta']['postBalances'][1]=2000000
raw['meta']['postBalances'][2]=0
raw['meta']['postTokenBalances']=[r for r in raw['meta']['postTokenBalances'] if r['accountIndex']!=2]
raw['meta']['postBalances'][0]=raw['meta']['preBalances'][0]-5000+raw['meta']['preBalances'][2]+100
raw['transaction']['message']['instructions']=[parsed('transfer',{'source':source,'destination':target,'amount':'100','authority':WALLET}),parsed('closeAccount',{'account':target,'destination':WALLET,'owner':WALLET})]
e=derive([raw]);r=e['cost_flow_evidence']['transactions']['wrapped-principal']
print(json.dumps({'control':'synthetic prior native-token transfer then closure, not B3','expected_refund_lamports':str(raw['meta']['preBalances'][2]+100),'receipt':r,'ledger_kinds':[v['kind'] for v in e['accounting_events']]}))
