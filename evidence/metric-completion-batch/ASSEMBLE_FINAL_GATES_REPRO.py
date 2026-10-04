from pathlib import Path
import datetime, hashlib, json, re, subprocess, sys
ROOT=Path('/workspace/solana-wallet-scanner'); B=ROOT/'evidence/metric-completion-batch'
sys.path.insert(0,str(ROOT))
from tools.validate import source_manifest, lock_hashes
APP='7e4769922ad8055b8c290f7625401d8a42fd183b'
SHA='578029f5d9a608e62b1336889b52e90025831732aeec2cea087a1dd8d57d7ee2'
def read(n): return json.loads((B/n).read_text())
def record(path):
 p=ROOT/path; raw=p.read_bytes();return {'path':str(p.relative_to(ROOT)),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
f=read('FROZEN_CANDIDATE.json');assert f['application_commit']==APP and f['source_sha256']==SHA and f['source_files']==235 and f['product_ready'] is False
extraction=read('FRESH_SOURCE_EXTRACTION_7e47699.json');assert extraction['state']=='PASS' and extraction['application_commit']==APP and extraction['source_manifest_sha256']==SHA and extraction['application_source_count']==235
m=source_manifest(ROOT);assert m==read('SOURCE_MANIFEST.json') and m['sha256']==SHA and len(m['files'])==235
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip()==APP
c=read('gate-a-accepted/result.json');assert c['state']=='ACCEPTED_IN_SCOPE' and c['source_unchanged'] is True and c['commit']==APP and c['source']==m
names={'runtime','node-runtime','backend','pip-check','shell-syntax','matrix','frontend-locked-install','frontend-check-format','frontend-check-discovery','frontend-build','clean-locked-install','launcher-browser-rebuild','consolidated-review'}
assert len(c['gates'])==13 and {g['name'] for g in c['gates']}==names and all(g['state']=='PASS' for g in c['gates'])
assert c['locks']==lock_hashes(ROOT)
current_runtime=json.loads(subprocess.check_output([c['interpreter'],'-c','import json,platform,sys;print(json.dumps(dict(python=platform.python_version(),platform=sys.platform)))']).decode());current_runtime['node']=subprocess.check_output(['node','--version']).decode().strip().removeprefix('v');assert c['runtime']==current_runtime
for gate in c['gates']:
 r=gate.get('evidence_receipt') or (gate if 'record' in gate else None)
 if r:
  raw=Path(r['path']).read_bytes();assert r['state']=='PASS' and hashlib.sha256(raw).hexdigest()==r['sha256'] and json.loads(raw)==r['record']
assert all(type(g['exit_code']) is int and g['exit_code']==0 for g in c['gates'] if 'command' in g)
browser=read('product-browser-repaired/result.json');command=read('product-browser-repaired-command/COMMAND.json')
assert browser['kind']=='offline-product-browser' and browser['state']=='PASS' and browser['real_acceptance']=='BLOCKED' and browser['parent_unchanged'] is True and browser['usage_before']==browser['usage_after']
assert all(type(v) is int for v in browser['offline_guards'].values()) and browser['offline_guards']=={'provider_requests':0,'credential_lookups':0} and browser['javascript_errors']==[] and browser['external_browser_requests']==[]
assert browser['cases'] and all(x['state']=='PASS' for x in browser['cases']) and browser['selected_cohort_ui_assertions'] and all(x['state']=='PASS' for x in browser['selected_cohort_ui_assertions'])
assert all(browser[k] is True for k in ['no_overflow','actual_UI_json_exports','evidence_inspection','source_loss_and_exact_restoration','server_stopped']) and type(browser['anonymous_state']) is int and browser['anonymous_state']==401
assert hashlib.sha256((B/'product-browser-repaired-command/RAW.log').read_bytes()).hexdigest()==command['raw_log_sha256'] and command['locks']==c['locks']
assert command['state']=='PASS' and command['exit_code']==0 and command['source_unchanged'] is True and command['commit']==APP and command['source_sha256']==SHA
assert hashlib.sha256((B/'product-browser-repaired/result.json').read_bytes()).hexdigest()==command['browser_receipt_sha256']
i=read('final-replays-accepted/INDEX.json');assert i['state']=='PASS' and i['commit']==APP and i['source_sha256']==SHA and i['source_unchanged'] is True and i['commit_unchanged'] is True and i['original_inputs_unchanged'] is True and i['PRODUCT_READY'] is False
modes={'genuine-development':(0,'offline-genuine-collection-workflow','WORKFLOW_PASS_REAL_ACCEPTANCE_BLOCKED'),'genuine-real-acceptance':(2,'offline-genuine-collection-workflow','BLOCKED'),'product-development':(0,'offline-product-check','DEVELOPMENT_PASS'),'product-real-acceptance':(2,'offline-product-check','BLOCKED')}
assert len(i['commands'])==4 and {x['name'] for x in i['commands']}==set(modes)
for cmd in i['commands']:
 assert type(cmd['exit_code']) is int and type(cmd['expected_exit_code']) is int and cmd['state'] in ('PASS','PASS_EXPECTED_REAL_BLOCK') and cmd['exit_code']==cmd['expected_exit_code'] and cmd['checks'] and all(v is True for v in cmd['checks'].values())
 rc,kind,state=modes[cmd['name']];assert cmd['exit_code']==rc
 receipt=json.loads((ROOT/cmd['receipt']).read_bytes());assert receipt['kind']==kind and receipt['state']==state and receipt['parent_unchanged'] is True and receipt['real_acceptance']['state']=='BLOCKED' and receipt['cases'] and all(x['state']=='PASS' for x in receipt['cases'])
 assert all(type(receipt[k]) is int and receipt[k]==0 for k in ['provider_requests','credential_lookups'])
 if kind=='offline-genuine-collection-workflow':
  assert receipt['usage_unchanged'] is True and receipt['PRODUCT_READY'] is False and receipt['oracle_frozen_before_application'] is True and receipt['archive_sha256']==f['preserved_genuine_inputs']['evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip']['sha256']
  normalized=(ROOT/cmd['receipt']).parent/'EXPECTED_WORKED.json';original=ROOT/'evidence/genuine-wallet-batch/WORKED_REAL_EXPECTATIONS_FINAL.json'
  assert hashlib.sha256(normalized.read_bytes()).hexdigest()==receipt['worked_expectations_sha256'] and json.loads(normalized.read_bytes())==json.loads(original.read_bytes())
  raw_oracle=(ROOT/cmd['receipt']).parent/'EXPECTED_RAW.json';assert hashlib.sha256(raw_oracle.read_bytes()).hexdigest()==receipt['oracle_sha256']
 else:
  assert receipt['usage_before']==receipt['usage_after'] and receipt['development']['state']=='PASS' and receipt['real_acceptance_required'] is (rc==2)
 assert hashlib.sha256((ROOT/cmd['receipt']).read_bytes()).hexdigest()==cmd['receipt_sha256']
 assert hashlib.sha256((ROOT/cmd['log']).read_bytes()).hexdigest()==cmd['log_sha256']
review=read('REVIEW_ACCEPTANCE.json'); assert review['state']=='PASS' and review['application_commit']==APP and review['source_sha256']==SHA
for r in review['review_evidence']:assert record(r['path'])==r
for n,r in f['preserved_genuine_inputs'].items():assert record(n)['sha256']==r['sha256'] and record(n)['bytes']==r['bytes']
matrix=read('gate-a-accepted/matrix.json');assert matrix['state']=='PASS'
log=(B/'gate-a-accepted/backend.log').read_text(); t=re.search(r'(\d+) passed,.*?(\d+) subtests passed in ([0-9.]+)s',log,re.S);assert t
assert int(t[1])==matrix['collected_unique_nodes']
paths=['SOURCE_MANIFEST.json','FROZEN_CANDIDATE.json','REVIEW_ACCEPTANCE.json','gate-a-accepted/result.json','gate-a-accepted/backend.log','gate-a-accepted/matrix.json','gate-a-accepted/browser/result.json','CANDIDATE_ACCEPTED_COMMAND.log','product-browser-repaired/result.json','product-browser-repaired-command/COMMAND.json','final-replays-accepted/INDEX.json','FRESH_SOURCE_EXTRACTION_7e47699.json','distinct-review/HARNESS_READ_ONLY_REVIEW.json']
paths += [str(Path(cmd['receipt']).relative_to('evidence/metric-completion-batch')) for cmd in i['commands']]
report={'kind':'final-scoped-candidate-gates','state':'SCOPED_PASS_REAL_ACCEPTANCE_BLOCKED','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'application_commit':APP,'source_sha256':SHA,'source_files':235,'source_unchanged':True,'locks':c['locks'],'runtime':c['runtime'],'gate_A':'ACCEPTED_IN_SCOPE','gate_A_gates':{g['name']:g['state'] for g in c['gates']},'full_backend_unique_nodes':int(t[1]),'subtests_separately_reported':int(t[2]),'backend_seconds':float(t[3]),'matrix_requirements':matrix['required_items'],'product_browser_cases':len(browser['cases']),'product_browser_captures':browser['captures'],'original_inputs_unchanged':True,'provider_requests':0,'credential_lookups':0,'PRODUCT_READY':False,'B1':'HISTORICAL_COVERAGE_UNRESOLVED','B2':'COMPLETE_REAL_ACCOUNTING_OPEN','B3':'COMPLETE_GENUINE_ACCEPTANCE_BLOCKED','candidate_classification':['scoped-valid','development-functional','real-acceptance-blocked'],'remaining_missing_implementation':['CAP-HIST','CAP-ORIGIN','CAP-ROUTES','CAP-CLASS','CAP-VALUATION','CAP-POSITIONS'],'scope':'Actual final Linux candidate, browser and four workflow-mode checks. Test/subtest/browser totals are separate; targeted or earlier runs not added. Synthetic and selected genuine evidence cannot close wallet-wide readiness. Native hosted CI is separate, not claimed here.','evidence':[record('evidence/metric-completion-batch/'+n) for n in paths]}
(B/'FINAL_GATES.json').write_text(json.dumps(report,indent=2)+'\n')
h=read('READ_ME_HANDOFF.json');h['state']=report['state'];h['final_gates']='FINAL_GATES.json';h['full_backend_unique_nodes']=int(t[1]);h['subtests_separately_reported']=int(t[2]);h['matrix_requirements']=matrix['required_items'];(B/'READ_ME_HANDOFF.json').write_text(json.dumps(h,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ['evidence','gate_A_gates']}))
