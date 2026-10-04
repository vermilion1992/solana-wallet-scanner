#!/usr/bin/env python3
"""Read actual four terminal workflows and raw oracles without app/test execution."""
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal,localcontext
from fractions import Fraction
import gc,gzip,hashlib,json,math,re,subprocess,zipfile
from pathlib import Path
ROOT=Path('/workspace/solana-wallet-scanner');OUT=Path('/workspace/outputs/genuine-wallet-report-correction-review');PREFIX=ROOT/'evidence/genuine-report-speed-batch-final';BODY=PREFIX/'environment-retry/final-replays'
HEAD='0db4125e8c1ab6b2df5bb1e79e807c80e3d195bd';SOURCE='babd86cab36e5674d286b8b59f4692e8f2f0109e0c2375a36ab7a86ad1185b3c'
def enc(x):return (json.dumps(x,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def hashraw(raw):return hashlib.sha256(raw).hexdigest()
def desc(p):
 h=hashlib.sha256();size=0
 with p.open('rb') as f:
  for raw in iter(lambda:f.read(1024*1024),b''):h.update(raw);size+=len(raw)
 return {'path':str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),'bytes':size,'sha256':h.hexdigest()}
def load(p):return json.loads(p.read_bytes())
def ts(x):return x if type(x) is int else int(datetime.fromisoformat(x.replace('Z','+00:00')).timestamp())
def caseid(c):return tuple(c.get(k) for k in ('case','report_role','lot_index','role'))
def keynames(r):
 m=r['transaction']['message'];k=[v['pubkey'] if isinstance(v,dict) else v for v in m['accountKeys']];loaded=r['meta'].get('loadedAddresses') or {};return k+loaded.get('writable',[])+loaded.get('readonly',[])
def b58(s):
 alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';number=0
 for c in s:number=number*58+alphabet.index(c)
 return b'\0'*(len(s)-len(s.lstrip('1')))+(number.to_bytes((number.bit_length()+7)//8,'big') if number else b'')
index_path=BODY/'INDEX.json';index=load(index_path);manifest=load(PREFIX/'SOURCE_MANIFEST.json');frozen=load(PREFIX/'FROZEN_CANDIDATE.json')
assert index['kind']=='four-frozen-offline-entrypoints' and index['state']=='PASS' and index['PRODUCT_READY'] is False
assert index['application_commit']==index['commit']==HEAD and index['source_sha256']==SOURCE and index['source_file_count']==246
assert index['source_unchanged'] is index['commit_unchanged'] is index['original_inputs_unchanged'] is True and index['source_after']=={'commit':HEAD,'source_sha256':SOURCE,'source_file_count':246}
assert index['command_timeout_seconds']==300 and index['total_timeout_seconds']==600
assert index['inputs_before']==index['inputs_after']
for n,row in index['inputs_before'].items():assert {k:desc(ROOT/n)[k] for k in ('bytes','sha256')}==row
oldindex=load(ROOT/'evidence/metric-completion-batch/final-replays-accepted/INDEX.json');assert oldindex['state']=='PASS'
names=['genuine-development','genuine-real-acceptance','product-development','product-real-acceptance'];assert [c['name'] for c in index['commands']]==names
input_path=ROOT/'evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip';input_hash=desc(input_path)['sha256'];assert input_hash=='eec702fdd821066897710d2085bf5c39380e303e8426249e22fb6379b7ccf1b4'
freeze=load(ROOT/'evidence/genuine-wallet-batch/checker-inputs/FINAL_INPUT_FREEZE.json');worked_original=load(ROOT/'evidence/genuine-wallet-batch/WORKED_REAL_EXPECTATIONS_FINAL.json')
worked_text=(json.dumps(worked_original,indent=2)+'\n').encode();worked_hash=hashraw(worked_text)
with zipfile.ZipFile(input_path) as z:
 assert len(z.namelist())==len(set(z.namelist()))==15 and z.testzip() is None
 rawfiles={n:z.read(n) for n in z.namelist()};m=json.loads(rawfiles['manifest.json'])
 assert all(hashraw(raw)==Path(n).stem for n,raw in rawfiles.items() if n.startswith('raw/'))
 pages=[json.loads(rawfiles['raw/'+p['response_hash']+'.json'])['result']['data'] for p in m['pages']]
 page_raw=rawfiles['raw/'+worked_original['source_page_sha256']+'.json'];page=json.loads(page_raw)['result']['data']
 assert len(page)==87 and hashraw(page_raw)==worked_original['source_page_sha256']
 allrecords=[r for rs in pages for r in rs]+[json.loads(rawfiles['raw/'+p['response_hash']+'.json'])['result'] for p in m['transactions']]
 wallet=m['address'];start,end=ts(m['window']['start']),ts(m['window']['end']);unique={}
 for r in allrecords:
  s=r['transaction']['signatures'][0];fact=(keynames(r)[0],r['meta']['fee'],r.get('blockTime'))
  assert type(fact[1]) is int and fact[1]>=0
  if s in unique:assert fact==unique[s]
  unique[s]=fact
 fee=sum(v[1] for v in unique.values() if v[0]==wallet and type(v[2]) is int and start<=v[2]<end)
 assert len(allrecords)==92 and len(unique)==87 and fee==158868
 # Verify original raw compiled instruction facts without scanner/production arithmetic.
 lot=worked_original['supported_selected_lots'][0]
 for fact in lot['raw_instruction_facts']:
  match=re.fullmatch(r'result.data\[(\d+)\].meta.innerInstructions\[index=(\d+)\].instructions\[(\d+)\]',fact['path']);assert match
  ordinal,group,which=map(int,match.groups());r=page[ordinal];keys=keynames(r);group_row=next(g for g in r['meta']['innerInstructions'] if g['index']==group);ins=group_row['instructions'][which]
  data=b58(ins['data']);assert data.hex()==fact['data_hex'] and keys[ins['programIdIndex']]==fact['program'] and [keys[i] for i in ins['accounts']]==fact['accounts']
  if fact.get('tag')==12:assert len(data)==10 and data[0]==12 and int.from_bytes(data[1:9],'little')==fact['amount_raw'] and data[9]==fact['decimals']
 buy,sell=page[lot['buy_record_index']],page[lot['sell_record_index']]
 assert buy['meta']['fee']==lot['buy_network_fee_lamports']==58918 and sell['meta']['fee']==lot['sell_network_fee_lamports']==6849
 buyquote=sum(lot['buy_quote_components_lamports']);basis=buyquote+buy['meta']['fee'];net=lot['sell_received_quote_lamports']-sell['meta']['fee'];profit=net-basis
 assert buyquote==565135100 and basis==565194018 and net==551923094 and profit==-13270924
 assert Decimal(profit)/Decimal(10**9)==Decimal(lot['conditional_lot_profit_sol'])
 assert sell['blockTime']-buy['blockTime']==lot['hold_seconds']==529
 def quantity(r,field):
  keys=keynames(r);return sum(int(v['uiTokenAmount']['amount']) for v in r['meta'][field] if keys[v['accountIndex']]==lot['account'] and v['mint']==lot['mint'])
 acquired=quantity(buy,'postTokenBalances')-quantity(buy,'preTokenBalances');disposed=quantity(sell,'preTokenBalances')-quantity(sell,'postTokenBalances')
 assert acquired==disposed==int(lot['quantity_acquired_raw'])==int(lot['quantity_disposed_raw'])==516612982765
 assert Fraction(lot['hold_seconds'],3600)==Fraction(int(lot['hold_hours']['numerator']),int(lot['hold_hours']['denominator']))
# Independent selected23 raw native fee arithmetic from retained corpus.
corpus=ROOT/'evidence/runs/real-cache';cm=json.loads(gzip.decompress((corpus/'manifest.json.gz').read_bytes()));fr=json.loads(gzip.decompress((corpus/'archives'/(cm['report']['collection_input_hash']+'.json.gz')).read_bytes()))
fee23=0
for link in fr['transactions']:
 r=json.loads(gzip.decompress((corpus/'archives'/(link['evidence_hash']+'.json.gz')).read_bytes()));r=r.get('result',r)
 if keynames(r)[0]==cm['report']['address'] and ts(cm['report']['window']['start'])<=ts(r['blockTime'])<ts(cm['report']['window']['end']):fee23+=r['meta']['fee']
assert fee23==240394
rows=[]
for i,c in enumerate(index['commands']):
 name=c['name'];folder=BODY/name;expected_exit=2 if name.endswith('real-acceptance') else 0
 assert type(c['exit_code']) is int and c['exit_code']==c['expected_exit_code']==expected_exit and c['timed_out'] is False and c['timeout_seconds']==300
 assert type(c['seconds']) in (int,float) and math.isfinite(c['seconds']) and 0<c['seconds']<=300 and all(v is True for v in c['checks'].values())
 assert c['source_before']==c['source_after']==index['source_after'] and c['real_acceptance_state']=='BLOCKED'
 lp=ROOT/c['log'];rp=ROOT/c['receipt'];gp=ROOT/c['offline_guard']
 for p,size,sha in [(lp,c['log_bytes'],c['log_sha256']),(rp,c['receipt_bytes'],c['receipt_sha256'])]:d=desc(p);assert d['bytes']==size and d['sha256']==sha
 assert desc(gp)['sha256']==c['offline_guard_sha256']
 r=load(rp);g=load(gp)
 assert r['state']==c['receipt_state'] and r['provider_requests']==r['credential_lookups']==0 and type(r['provider_requests']) is type(r['credential_lookups']) is int
 assert r['parent_unchanged'] is True and r['collector_ancestry_created'] is False and r['real_acceptance']['state']=='BLOCKED'
 assert g['state']=='PASS' and g['kind']=='counted-offline-python-guards' and g['application_exit_code']==expected_exit
 assert type(g['socket_attempts']) is type(g['bootstrap_credential_attempts']) is int and g['socket_attempts']==g['bootstrap_credential_attempts']==0
 assert g['application_command']==c['application_command'][1:] and c['application_command'][0]==str(ROOT/'.venv/bin/python')
 assert ('--require-real-acceptance' in c['application_command'])==bool(expected_exit)
 old=oldindex['commands'][i];prior=load(ROOT/old['receipt'])
 assert Counter(map(caseid,r['cases']))==Counter(map(caseid,prior['cases'])) and all(case['state']=='PASS' for case in r['cases'])
 artifacts=[]
 for n,bound in r['artifacts'].items():
  d=desc(folder/n);assert d['sha256']==(bound['sha256'] if isinstance(bound,dict) else bound);assert not isinstance(bound,dict) or d['bytes']==bound['bytes'];artifacts.append(d)
 if name.startswith('genuine-'):
  assert r['kind']=='offline-genuine-collection-workflow' and r['oracle_frozen_before_application'] is r['usage_unchanged'] is True and r['PRODUCT_READY'] is False
  assert r['archive_sha256']==input_hash==desc(folder/'input.zip')['sha256']
  assert r['oracle_sha256']==freeze['oracle_sha256']==desc(folder/'EXPECTED_RAW.json')['sha256']
  assert (folder/'EXPECTED_WORKED.json').read_bytes()==worked_text and r['worked_expectations_sha256']==worked_hash
  oracle=load(folder/'EXPECTED_RAW.json');assert oracle['unique_signatures']==87 and oracle['raw_records']==92 and oracle['observed_network_fees_sol']['lamports']==fee
  primary=load(folder/'parent-report.json');metrics=primary['metrics']
  for metric,expected in worked_original['metrics'].items():assert {k:metrics[metric][k] for k in ('status','value')}==expected
  parentq=primary['coverage']['wallet_evidence']['query_accounting']
  for key,value in worked_original['query_accounting'].items():assert parentq[key]==value
  target=next(v for v in parentq['supported_selected_lots'] if v['mint']==lot['mint'] and lot['account'] in v['accounts'])
  assert target['monetary_state']==target['timing_state']==target['quantity_state']=='PASS' and target['conditional_lot_profit_sol']==lot['conditional_lot_profit_sol']
  assert target['qualification'] is False and target['classification_state']==target['wallet_population_state']=='UNKNOWN'
  assert target['acquired_raw']==target['disposed_raw']==str(acquired) and target['remaining_raw']=='0'
  with localcontext() as ctx:
   ctx.prec=220;assert abs(Decimal(target['conditional_hold_hours'])-Decimal(529)/Decimal(3600))<Decimal('1e-185')
  primarysmall={'metrics':{k:{key:v[key] for key in ('status','value')} for k,v in metrics.items()},'window':primary['window'],'preset':primary['preset'],'archive_input_hash':primary['archive_input_hash']};del primary;gc.collect()
  losses=[]
  for label in ['source','lot-0-buy','lot-0-sell']:
   absent=load(folder/(label+'-missing-child.json'));present=load(folder/(label+'-restored-child.json'))
   assert absent['metrics']['observed_network_fees_sol']['status']=='unknown' and present['metrics']['observed_network_fees_sol']['value']=='0.000158868'
   for key in ('window','preset','archive_input_hash'):assert absent[key]==present[key]==primarysmall[key]
   assert {k:{key:v[key] for key in ('status','value')} for k,v in present['metrics'].items()}==primarysmall['metrics']
   pq=present['coverage']['wallet_evidence']['query_accounting'];aq=absent['coverage']['wallet_evidence']['query_accounting']
   restored=next(v for v in pq['supported_selected_lots'] if v['mint']==lot['mint'] and lot['account'] in v['accounts'])
   assert restored['monetary_state']=='PASS' and restored['conditional_lot_profit_sol']=='-0.013270924' and pq['qualification'] is False and pq['wallet_population_state']=='UNKNOWN'
   if label!='source':
    counterparts=[v for v in aq['supported_selected_lots'] if v['mint']==lot['mint'] and lot['account'] in v['accounts']]
    assert counterparts and all(v['monetary_state']!='PASS' for v in counterparts)
   losses.append({'role':label,'missing_fee':'UNKNOWN','restored_fee':'0.000158868','restored_selected_loss_sol':'-0.013270924','wallet_qualification':False});del absent,present;gc.collect()
  assert len(r['cases'])==7 and all(case.get('parent_unchanged') is True for case in r['cases'] if case['case']=='selected-lot-required-source-loss-exact-restoration')
  details={'genuine_case_entries':7,'actual_selected_records':87,'raw_records_including_duplicate_native_alternatives':92,'observed_wallet_fee_lamports':fee,'conditional_named_lot_loss_lamports':profit,'hold_seconds':529,'loss_restoration':losses,'all15_original_metric_expectations_checked':True,'complete_wallet_qualification':False}
 else:
  assert r['kind']=='offline-product-check' and r['development']['state']=='PASS' and r['usage_before']==r['usage_after'] and r['real_acceptance_required']==bool(expected_exit)
  synthetic=load(folder/'synthetic-parent.json');expected=r['cases'][0]['expected'];assert {k:synthetic['metrics'][k]['value'] for k in expected}==expected
  for role,metric in [('valuation_hash','economic_pnl_sol'),('world_hash','profit_sol')]:
   absent=load(folder/(role+'-missing-child.json'));assert absent['metrics'][metric]['status']=='unknown' and absent['metrics']['observed_network_fees_sol']['value']=='0.000055';del absent
  real=load(folder/'partial-real-report.json');assert real['metrics']['observed_network_fees_sol']['value']==str(Decimal(fee23)/Decimal(10**9)) and real['qualification']['qualified'] is False
  assert len(r['cases'])==4
  details={'original_product_case_entries':4,'partial_genuine_records':23,'independent_raw_fee_lamports':fee23,'source_loss_cases':2,'source_restoration':'PASS in retained actual producer assertions; product checker does not persist restored child JSON','complete_wallet_qualification':False};del synthetic,real;gc.collect()
 rows.append({'name':name,'producer_exit_code':expected_exit,'producer_seconds':c['seconds'],'producer_state':r['state'],'review_state':'PASS' if expected_exit==0 else 'PASS_EXPECTED_REAL_BLOCK','case_identities':[list(caseid(v)) for v in r['cases']],'command_receipt':desc(rp),'raw_log':desc(lp),'offline_guard':desc(gp),'artifacts_verified':artifacts,'scope_details':details})
assert sum(c['seconds'] for c in index['commands'])<=600
for n,h in manifest['files'].items():assert desc(ROOT/n)['sha256']==h and (ROOT/n).stat().st_mode&0o777==manifest['modes'][n]
for n,h in frozen['locks'].items():assert desc(ROOT/n)['sha256']==h
assert subprocess.check_output(['git','--no-optional-locks','rev-parse','HEAD'],cwd=ROOT).decode().strip()==HEAD
assert desc(PREFIX/'REVIEW_ACCEPTANCE.json')['sha256']=='73e4abbb86fef741681770315f2c7cc5304c7beaa053203a25e0ba53e94bdd34'
gate=load(PREFIX/'gate-a-final/result.json');assert gate['state']=='ACCEPTED_IN_SCOPE' and gate['source']==manifest and gate['source_unchanged'] is True and len(gate['gates'])==13 and all(v['state']=='PASS' for v in gate['gates'])
report={'kind':'independent-actual-four-offline-workflow-receipt-review','state':'PASS','application_commit':HEAD,'source_sha256':SOURCE,'source_files':246,'locks':frozen['locks'],'actual_terminal_index':desc(index_path),'workflow_invocations':rows,
'independent_raw_oracle_scope':{'original_request_response_hashes_verified':14,'original_page_records':87,'native_alternative_duplicates':5,'unique_selected_signatures':87,'selected_report_fee_lamports':158868,'quote_instruction_byte_facts_verified':len(lot['raw_instruction_facts']),'named_lot_quantity_raw':'516612982765','basis_lamports':565194018,'sell_net_proceeds_lamports':551923094,'conditional_named_lot_loss_lamports':-13270924,'hold_fraction_hours':'529/3600','partial23_fee_lamports':240394,'production_arithmetic_imports':0,'whole_wallet_population_or_financial_promotion':False},
'full_candidate_gate_consistency':{'receipt':desc(PREFIX/'gate-a-final/result.json'),'state':'ACCEPTED_IN_SCOPE','same246_file_mode_map_and_locks':True,'required_gates':13,'prior_distinct_gate_review':desc(OUT/'FINAL_GATE_READONLY_REVIEW.json')},
'original_inputs_rechecked':len(index['inputs_before']),'original_inputs_unchanged':True,'all_producer_artifact_bytes_checked':True,'parent_immutability':'Actual producer assertions retained for original and loss/restoration parents; all frozen original input hashes rechecked. No rerun or separately reconstructed runtime store.',
'counts_scope':'Four invocations repeat the original workflow/case set in development and real-required modes; none is added to3246 unique backend node counts. Named partial genuine losing lot remains scoped; both real-required entrypoints correctly return2/BLOCKED.',
'findings':[],'source_unchanged_rechecked':True,'provider_requests':0,'credential_lookups':0,'guard_socket_attempts':0,'guard_bootstrap_credential_attempts':0,'new_tests_or_application_workflows_run_by_reviewer':0,'source_or_Git_mutations':False,
'B1':'HISTORICAL_SUFFICIENCY_UNRESOLVED','B2':'COMPLETE_REAL_ACCOUNTING_OPEN','B3':'COMPLETE_GENUINE_ACCEPTANCE_BLOCKED','PRODUCT_READY':False,'scope':'Read-only terminal actual four producer commands, raw/typed receipts/artifact hashes, independently recomputed original-byte fee/selected-lot arithmetic, source-loss restoration and exact candidate/gate source consistency. No synthetic B3 requirement, product-ready claim or new full-history throughput claim.'}
p=OUT/'ACTUAL_FOUR_REPLAYS_READONLY_REVIEW.json';p.write_bytes(enc(report));dest=PREFIX/'integrated-review'
for original in (p,Path(__file__)):
 target=dest/original.name
 if target.exists():assert target.read_bytes()==original.read_bytes()
 else:target.write_bytes(original.read_bytes())
print(json.dumps({'state':'PASS','review':desc(p),'four_actual_exit_codes':[r['producer_exit_code'] for r in rows],'genuine_fee_lamports':fee,'genuine_named_loss_lamports':profit,'PRODUCT_READY':False}))
