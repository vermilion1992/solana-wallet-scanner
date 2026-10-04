from pathlib import Path
from copy import deepcopy
import sys,json
sys.path.insert(0,'tests')
from test_selected_cohort_observations import exchange,START
from test_wallet_evidence import derive,base
buy=exchange('known-buy',100,START+3600,0,100)
bad=base('bad-selected',quantity=0);bad['slot']=101;bad['blockTime']=START+7200;bad['version']=1
rows=[]
for variant in ['unsupported','missing-meta','malformed-account-operation']:
 r=deepcopy(bad)
 if variant=='missing-meta':r['version']=0;r['meta']=None
 if variant=='malformed-account-operation':
  r['version']=0;r['meta']['preTokenBalances']=[];r['meta']['postTokenBalances']=[]
  r['transaction']['message']['instructions']=[{'programId':'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA','parsed':{'type':'setAuthority','info':{'account':[],'authorityType':'accountOwner','authority':'invalid','newAuthority':'invalid'}}}]
 result=derive([buy,r]);membership=result['query_accounting']['historical_membership']
 rows.append({'variant':variant,'observed_membership_state':membership['observed_event_membership']['state'], 'bad_transaction_state':membership['transactions']['bad-selected']['check']['state'],'independent_buy_accounts':{a:v['event_time_check']['state'] for a,v in membership['transactions']['known-buy']['accounts'].items()},'wallet_population':membership['historical_population']['state'],'reasons':result['transactions']['bad-selected']['gaps']})
print(json.dumps(rows,indent=2))
assert all(row['observed_membership_state']=='UNKNOWN' for row in rows),'Unassignable/unsupported selected activity must remain in overall membership dependency census'
