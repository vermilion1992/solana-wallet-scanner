"""Read-only direct/native sibling reproduction; development raw records only."""
from copy import deepcopy
import json,sys
from pathlib import Path
sys.path[:0]=[str(Path.cwd()),str(Path.cwd()/'tests')]
from scanner.wallet_evidence import derive_wallet_evidence
from scanner.wallet_positions import derive_wallet_positions
from test_wallet_position_population import mixed
from test_wallet_evidence import record
from test_position_evidence import MINT,WALLET,WINDOW
rows=[]
for shape in ('outer-signature-mismatch','unsupported-version','missing-meta'):
    raws=mixed()
    if shape=='unsupported-version':raws[-1]['version']=1
    elif shape=='missing-meta':raws[-1].pop('meta')
    selected=[record(raw) for raw in raws]
    if shape=='outer-signature-mismatch': selected[-1]['signature']='wrong-identity'
    for route in ('public-wrapper','normal-raw-adapter'):
        if route=='public-wrapper':
            result=derive_wallet_positions(selected,all_records=selected,wallet=WALLET,window=WINDOW)
        else:
            result=derive_wallet_evidence(selected,all_records=selected,wallet=WALLET,window=WINDOW,
                source_consistency={},chronology={})['query_accounting']['position_population']
        mint=result['mints'][MINT]
        passed=(result['checks']['observed_population']['state']=='UNKNOWN' and mint['quantity_state']=='UNKNOWN' and mint['selected_remaining_raw'] is None)
        rows.append({'case':shape,'route':route,'state':'PASS' if passed else 'FAILED',
            'expectation':{'population':'UNKNOWN','quantity':'UNKNOWN','remaining':None},
            'actual':{'population':result['checks']['observed_population']['state'],
                'quantity':mint['quantity_state'],'remaining':mint['selected_remaining_raw']}})
print(json.dumps({'state':'PASS' if all(row['state']=='PASS' for row in rows) else 'FAILED',
    'scope':'selected raw-invalid dependencies must not disappear from mint quantities; no historical population claim',
    'cases':rows},indent=2))
sys.exit(0 if all(row['state']=='PASS' for row in rows) else 1)
