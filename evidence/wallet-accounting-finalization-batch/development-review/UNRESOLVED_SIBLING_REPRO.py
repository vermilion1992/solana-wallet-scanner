import sys,json
sys.path.insert(0,'/workspace/solana-wallet-scanner/tests')
from test_cost_flow_evidence import wrapped_funding,derive
from scanner.investigation import WSOL
raw,_=wrapped_funding()
pre=next(t for t in raw['meta']['preTokenBalances'] if t['accountIndex']==1)
pre['mint']=WSOL;pre['uiTokenAmount']['decimals']=9;pre['uiTokenAmount']['amount']='100'
raw['meta']['postTokenBalances']=[t for t in raw['meta']['postTokenBalances'] if t['accountIndex']!=1]
e=derive([raw]);s=e['transactions']['wrapped-principal']
account=raw['transaction']['message']['accountKeys'][1]
print(json.dumps({'control':'synthetic missing sibling phase, not B3','sibling_quantity_state':s['boundaries'][account]['checks']['quantities']['state'],'roles':e['cost_flow_evidence']['transactions']['wrapped-principal'],'events':[{'kind':v['kind'],'path':v['path'],'economic_role':v.get('economic_role')} for v in e['accounting_events']]}))
