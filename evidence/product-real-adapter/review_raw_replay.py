"""Distinct read-only raw-input replays. No provider or credential access."""
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from copy import deepcopy

ROOT = Path('/workspace/solana-wallet-scanner')
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
import httpx
import keyring
calls = {'provider': 0, 'credentials': 0}
def denied_provider(*args, **kwargs):
    calls['provider'] += 1
    raise AssertionError('Forbidden provider/network dispatch during review')
def denied_credential(*args, **kwargs):
    calls['credentials'] += 1
    raise AssertionError('Forbidden credential lookup during review')
httpx.Client.request = denied_provider
httpx.AsyncClient.request = denied_provider
keyring.get_password = denied_credential
from scanner.archive_input import canonical_bytes, pack_bytes, import_archive, load_archive, decode_archive, analyze_archive
from scanner.wallet_evidence import derive_wallet_evidence
from scanner.storage import Store
from scanner.app import _wallet_adapter_inputs
from scanner.accounting import utc
from tools.validate import source_manifest

EVIDENCE = ROOT / 'evidence/product-real-adapter'
before = source_manifest(ROOT)
bundle = json.loads((ROOT / 'scanner/examples/archive-wallet-synthetic.json').read_text())
wallet, window = bundle['manifest']['address'], bundle['manifest']['window']
cases = []

def receipt(name):
    return json.loads((EVIDENCE / f'REVIEW_REPRO_{name}.json').read_text())
def digest(payload):
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()
def derive(records, *, linked=None, sources=(), receipts=()):
    return derive_wallet_evidence(records, all_records=records if linked is None else linked,
        wallet=wallet, window=window, source_consistency={'state':'PASS'}, chronology={'state':'PASS'},
        raw_sources=sources, source_receipts=receipts)
def state(value, key):
    return value['components'][key]['state']
def case(name, actual, expected, reproduction):
    result = {'case':name, 'actual':actual, 'expected':expected,
        'state':'PASS' if actual == expected else 'FAILED', 'reproduction':reproduction}
    cases.append(result)
    print(name, result['state'], actual, flush=True)
def archive_result(store, manifest_hash):
    loaded = load_archive(store, manifest_hash)
    events, _ = decode_archive(loaded)
    return analyze_archive(loaded, events)
def populate(store, collected, extra=()):
    for payload in bundle['payloads'].values():
        store.archive(payload)
    for row in collected.get('transactions', []):
        if isinstance(row,dict) and isinstance(row.get('raw'),dict):
            store.archive(row['raw'])
    for payload in extra:
        store.archive(payload)

v=receipt('SAME_SLOT')
src={'kind':'block-order','hash':digest(v['block_order']),'payload':v['block_order']}
d=derive(v['inputs'],sources=[src])
case('raw-block-indices-reach-FIFO', [state(d,'observed_disposed_basis'), d['observed_fifo_positions'][0]['matched_basis_sol']],
     ['PASS','2.000005'], 'REVIEW_REPRO_SAME_SLOT.json')
v=receipt('OWNERSHIP_AGGREGATE'); row=v['input'];raw=row['raw'];d=derive([row])
tx=next(iter(d['transactions'].values())); pair=tx['boundaries'][raw['transaction']['message']['accountKeys'][1]]; agg=tx['mint_aggregates'][raw['meta']['preTokenBalances'][0]['mint']]
case('ownership-required-for-wallet-owned-aggregate', [pair['checks']['ownership']['state'],pair['checks']['quantities']['state'],agg['check']['state']],
     ['UNKNOWN','PASS','UNKNOWN'],'REVIEW_REPRO_OWNERSHIP_AGGREGATE.json')
v=receipt('FIFO_CHRONOLOGY');d=derive(v['inputs'][:2],linked=v['inputs'])
case('alternative-order-conflict-revokes-FIFO-basis-episodes',[state(d,key) for key in ('chronology','observed_disposed_basis','observed_positions','native_fee')],
     ['UNKNOWN','UNKNOWN','UNKNOWN','PASS'],'REVIEW_REPRO_FIFO_CHRONOLOGY.json')
v=receipt('CONTINUITY_ORDER');d=derive(v['inputs'],sources=v['raw_sources'])
case('proved-block-order-controls-partial-sale-continuity',[state(d,key) for key in ('chronology','quantity_continuity','observed_quantities')],
     ['PASS','PASS','PASS'],'REVIEW_REPRO_CONTINUITY_ORDER.json')
for name,expected in [('CHECKPOINT_SOURCE_SET','UNKNOWN'),('MALFORMED_TRANSACTION_LINK','UNKNOWN'),('UNASSIGNED_TRANSACTION','UNKNOWN'),('UNSUPPORTED_TRANSACTION_ROLE','UNKNOWN'),('DISJOINT_ROLE_RECEIPT','PASS')]:
    v=receipt(name); collected=v['collected']
    extras=[v[k] for k in ('alternative_input','alternative') if k in v]
    with TemporaryDirectory() as temp:
        store=Store(Path(temp));populate(store,collected,extras)
        primary,linked,sources,receipts=_wallet_adapter_inputs(store,collected,address=wallet,window=window)
        d=derive(primary,linked=linked,sources=sources,receipts=receipts)
        case(name.lower().replace('_','-'),state(d,'native_fee'),expected,f'REVIEW_REPRO_{name}.json')
v=receipt('FROZEN_INPUTS')
with TemporaryDirectory() as temp:
    store=Store(Path(temp));populate(store,v['collected'],[receipt('CHECKPOINT_SOURCE_SET')['alternative_input']])
    identifier=hashlib.sha256(f"{wallet}:{int(utc(window['start']).timestamp())}:{int(utc(window['end']).timestamp())}".encode()).hexdigest()
    store.put('collector_checkpoints',identifier,{'evidence':[{'kind':'transaction','signature':'development-1','hash':v['later_persisted_hash']}]})
    primary,linked,sources,receipts=_wallet_adapter_inputs(store,v['collected'],address=wallet,window=window)
    case('later-checkpoint-does-not-expand-frozen-universe',len(linked),1,'REVIEW_REPRO_FROZEN_INPUTS.json')
for name,expected in [('MINT_AUTHORITY_TARGET','PASS'),('HASH_DISJOINTNESS','UNKNOWN'),('METADATA_VALUE_TRANSACTION','UNKNOWN')]:
    v=receipt(name);given=v['input'];raw=given.get('raw',given);row=given if 'raw' in given else {'signature':raw['transaction']['signatures'][0],'evidence_hash':digest(raw),'raw':raw}
    d=derive([row],sources=[v['raw_source']] if 'raw_source' in v else [])
    keys=('native_fee','event_ownership','observed_quantities') if name=='MINT_AUTHORITY_TARGET' else ('native_fee',)
    case(name.lower().replace('_','-'),[state(d,k) for k in keys],[expected]*len(keys),f'REVIEW_REPRO_{name}.json')
v=receipt('OUTSIDE_FEE');outside=deepcopy(bundle);outside['manifest']=v['manifest'];outside['payloads'][digest(v['changed_input'])]=v['changed_input']
with TemporaryDirectory() as temp:
    store=Store(Path(temp));h=import_archive(store,pack_bytes(outside));result,events,cov=archive_result(store,h)
    case('proved-outside-window-unknown-fee-preserves-total',[result['metrics']['observed_network_fees_sol']['status'],result['metrics']['observed_network_fees_sol']['value']],
         ['known','0.000055'],'REVIEW_REPRO_OUTSIDE_FEE.json')
v=receipt('RECORD_BUDGET');template=v['generation_template'];payloads={};refs=[]
for index in range(10_001):
    raw={**template,'development_variant':index};h=digest(raw);payloads[h]=raw;refs.append({'signature':raw['transaction']['signatures'][0],'hash':h})
big={'manifest':{'version':bundle['manifest']['version'],'address':wallet,'window':window,'dataset':'real','transactions':refs[:1],
                'evidence':[{'kind':'getTransaction',**row} for row in refs[1:]]},'payloads':payloads}
with TemporaryDirectory() as temp:
    store=Store(Path(temp));h=import_archive(store,pack_bytes(big));result,events,cov=archive_result(store,h)
    case('valid-10001-alternative-capacity-preserves-native-fee',[cov['wallet_evidence']['inspection_budget']['linked_records'],result['metrics']['observed_network_fees_sol']['value']],
         [10_001,'0.000005'],'REVIEW_REPRO_RECORD_BUDGET.json')
# Product-sized account union case; the independent raw endpoint sum stays below the global budget.
v=receipt('ACCOUNT_UNION_BUDGET');raw=v['generator']['input'];rows=[]
alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
for index in range(512):
    n=int.from_bytes(b'\x10'*30+index.to_bytes(2,'big'),'big');key=''
    while n:n,p=divmod(n,58);key=alphabet[p]+key
    alternative=deepcopy(raw);alternative['transaction']['message']['accountKeys'][1]=key
    rows.append({'signature':raw['transaction']['signatures'][0],'evidence_hash':digest(alternative),'raw':alternative})
from test_wallet_evidence import WALLET as other_wallet, WINDOW as other_window
d=derive_wallet_evidence(rows[:1],all_records=rows,wallet=other_wallet,window=other_window,source_consistency={},chronology={})
case('account-union-budget-narrows-facts-without-report-failure',[state(d,'native_fee'),state(d,'observed_quantities')],
     ['PASS','UNKNOWN'],'REVIEW_REPRO_ACCOUNT_UNION_BUDGET.json')
v=receipt('UNEXPLAINED_NATIVE_FLOW');raw=v['input'];row={'signature':raw['transaction']['signatures'][0],'evidence_hash':digest(raw),'raw':raw}
d=derive_wallet_evidence([row],all_records=[row],wallet=other_wallet,window=other_window,source_consistency={},chronology={})
case('unexplained-native-flow-revokes-roles-retains-fee',[state(d,'observed_economic_roles'),state(d,'native_fee')],
     ['UNKNOWN','PASS'],'REVIEW_REPRO_UNEXPLAINED_NATIVE_FLOW.json')
v=receipt('BUDGET_COST_ROLE');raw=v['input'];row={'signature':raw['transaction']['signatures'][0],'evidence_hash':digest(raw),'raw':raw}
import scanner.wallet_evidence as adapter
saved_budget=adapter.MAX_ACCOUNT_STEPS
adapter.MAX_ACCOUNT_STEPS=1
try:
    d=derive_wallet_evidence([row],all_records=[row,v['alternative']],wallet=other_wallet,window=other_window,source_consistency={},chronology={})
finally:
    adapter.MAX_ACCOUNT_STEPS=saved_budget
case('budget-loss-does-not-promote-cost-flow-role',[state(d,'observed_economic_roles'),state(d,'native_fee')],
     ['UNKNOWN','PASS'],'REVIEW_REPRO_BUDGET_COST_ROLE.json')
v=receipt('WRONG_ROLE_REMOVAL');wrong=deepcopy(bundle);wrong['manifest']=v['manifest']
bad_hash=digest(v['wrong_label_payload']);wrong['payloads'][bad_hash]=v['wrong_label_payload']
with TemporaryDirectory() as temp:
    store=Store(Path(temp));h=import_archive(store,pack_bytes(wrong));initial,events,initial_cov=archive_result(store,h)
    frozen=initial_cov.get('dependency_input_hash')
    if frozen is None:
        loaded=load_archive(store,h);frozen=loaded.get('dependency_input_hash')
    path=store.path/'evidence'/f'{bad_hash}.json.gz';original=path.read_bytes();path.unlink()
    lost,events,lost_cov=archive_result(store,h)
    path.write_bytes(original);restored,events,restored_cov=archive_result(store,h)
    metrics=[r['metrics']['observed_network_fees_sol']['status'] for r in (initial,lost,restored)]
    case('wrong-role-negative-native-association-survives-loss-restoration',metrics,['unknown']*3,'REVIEW_REPRO_WRONG_ROLE_REMOVAL.json')
    # Mutable import-index changes may not expand a saved parent's bound dependency inventory.
    changed=store.archive({'version':'archive-native-dependencies-v1','manifest_hash':h,'links':[]})
    store.put('archive_dependency_inputs',h,{'hash':changed})
    loaded=load_archive(store,h,dependency_input_hash=frozen);events,_=decode_archive(loaded);bound,_,_=analyze_archive(loaded,events)
    case('frozen-negative-native-inventory-survives-later-index-change',bound['metrics']['observed_network_fees_sol']['status'],'unknown','REVIEW_REPRO_WRONG_ROLE_REMOVAL.json')

after=source_manifest(ROOT)
output={'kind':'read-only-review-raw-replay','state':'PASS' if all(c['state']=='PASS' for c in cases) and calls=={'provider':0,'credentials':0} and before==after else 'FAILED',
        'source_sha256':before['sha256'],'source_unchanged':before==after,'source_files':len(before['files']),
        'cases':cases,'provider_requests':calls['provider'],'credential_lookups':calls['credentials'],'PRODUCT_READY':False,
        'scope':'Development raw records and current shared offline paths only. No genuine wallet acceptance or full Gate A acceptance claimed.',
        'input_receipts':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in EVIDENCE.glob('REVIEW_REPRO*.json')}}
(EVIDENCE/'REVIEW_REPLAY_FINAL.json').write_text(json.dumps(output,sort_keys=True,indent=2)+'\n')
raise SystemExit(0 if output['state']=='PASS' else 1)
