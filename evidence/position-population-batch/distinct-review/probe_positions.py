from __future__ import annotations
import hashlib,json,sys
from copy import deepcopy
from pathlib import Path
sys.path[:0] = [str(Path.cwd()), str(Path.cwd()/'tests')]
from scanner.wallet_positions import derive_wallet_positions
from scanner.json_boundary import canonical_bytes
import scanner.wallet_evidence as we
from test_wallet_position_population import mixed, positions, replace_strings
from test_selected_cohort_observations import exchange
from test_wallet_evidence import record
from test_position_evidence import address, ACCOUNT,MINT,WALLET,START,END,WINDOW

def states(result):
    return {'population':result['checks']['observed_population']['state'],
        'mints':{mint:{'quantity':r['quantity_state'],'positions':r['position_state'],'remaining':r['selected_remaining_raw'],'episodes':[(e['quantity_state'],e['monetary_state']) for e in r['episodes']]} for mint,r in result['mints'].items()}}
rows=[]
def case(name,fn,assertion):
    try:
        result=fn(); assertion(result)
        rows.append({'case':name,'state':'PASS','observed':states(result)})
    except Exception as e:
        rows.append({'case':name,'state':'FAILED','error':repr(e)})

def known(r):
    assert r['checks']['observed_population']['state']=='PASS',states(r)
def unknown(r):
    assert r['checks']['observed_population']['state']=='UNKNOWN',states(r)

def empty(r):
    assert r['mints']=={} and r['checks']['observed_population']['state']=='UNKNOWN'
case('empty-selected-domain', lambda: positions([]),empty)
second=address(18)
case('same-mint-two-accounts-open',lambda:positions([exchange('one-buy',100,START+3600,0,100),replace_strings(exchange('two-buy',101,START+7200,0,40),ACCOUNT,second)]),known)
case('same-mint-two-accounts-close-one',lambda:positions([exchange('one-buy',100,START+3600,0,100),replace_strings(exchange('two-buy',101,START+7200,0,40),ACCOUNT,second),exchange('one-sale',102,START+10800,100,0)]),known)

wrong=[record(raw) for raw in mixed()]
wrong[-1]['signature']='wrong-identity'
case('caller-selected-signature-mismatch',lambda:derive_wallet_positions(wrong,all_records=wrong,wallet=WALLET,window=WINDOW),unknown)
conflict=deepcopy(mixed()[-1]);conflict['blockTime']=END
case('alternative-crosses-exact-end',lambda:positions(mixed(),alternatives=[record(conflict)]),unknown)
case('post-end-account-quantity-gap-excluded',lambda:positions(mixed()+[exchange('after-end',105,END,500,600)]),known)
original=we.MAX_ACCOUNT_STEPS
try:
    we.MAX_ACCOUNT_STEPS=0
    case('zero-physical-inspection-budget',lambda:positions(mixed()),unknown)
finally:
    we.MAX_ACCOUNT_STEPS=original

raw=mixed(); corrupt=deepcopy(raw[-1]);corrupt['meta']['fee']=None
case('linked-missing-fee-retains-physical-population',lambda:positions(raw,alternatives=[record(corrupt)]),known)
other=replace_strings(exchange('disjoint-mint',105,START+21600,0,40),ACCOUNT,address(19))
other=replace_strings(other,MINT,address(20))
other['meta']['fee']=None
case('readable-disjoint-mint-fee-gap-isolated',lambda:positions(mixed()+[other]),known)
print(json.dumps({'scope':'read-only development source controls; not Gate A or genuine B3 acceptance','cases':rows,'state':'PASS' if all(r['state']=='PASS' for r in rows) else 'FAILED'},indent=2))
sys.exit(0 if all(r['state']=='PASS' for r in rows) else 1)
