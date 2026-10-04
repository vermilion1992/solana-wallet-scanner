#!/usr/bin/env python3
"""Distinct read-only final candidate producer/log review. No commands/tests/apps rerun."""
import hashlib,json,math,re,struct,subprocess
from pathlib import Path
ROOT=Path('/workspace/solana-wallet-scanner');OUT=Path('/workspace/outputs/genuine-wallet-report-correction-review');PREFIX=ROOT/'evidence/genuine-report-speed-batch-final';GATE=PREFIX/'gate-a-final'
HEAD='0db4125e8c1ab6b2df5bb1e79e807c80e3d195bd';SOURCE='babd86cab36e5674d286b8b59f4692e8f2f0109e0c2375a36ab7a86ad1185b3c'
def enc(x):return (json.dumps(x,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def desc(p):
 raw=p.read_bytes();return {'path':str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def checkrow(row):
 p=Path(row['path']);p=p if p.is_absolute() else ROOT/p
 d=desc(p);assert d['sha256']==row['sha256'] and d['bytes']==row['bytes'];return d
command_path=PREFIX/'CANDIDATE_COMMAND.json';result_path=GATE/'result.json';command=json.loads(command_path.read_bytes());result=json.loads(result_path.read_bytes());frozen=json.loads((PREFIX/'FROZEN_CANDIDATE.json').read_bytes());manifest=json.loads((PREFIX/'SOURCE_MANIFEST.json').read_bytes())
assert command['kind']=='actual-frozen-candidate-command' and command['state']=='PASS' and result['state']=='ACCEPTED_IN_SCOPE'
assert command['application_commit']==command['commit']==result['commit']==frozen['application_commit']==HEAD
assert command['source_sha256']==result['source']['sha256']==manifest['sha256']==SOURCE and result['source']==manifest and command['source_files']==246
assert command['source_unchanged'] is command['commit_unchanged'] is result['source_unchanged'] is True
assert command['PRODUCT_READY'] is False and result['gate_B']['state']=='OPEN' and result['profile']=='candidate'
assert type(command['exit_code']) is int and command['exit_code']==0 and type(command['timeout_seconds']) is int and command['timeout_seconds']==1800 and command['timed_out'] is False
assert type(command['seconds']) in (int,float) and math.isfinite(command['seconds']) and 0<command['seconds']<=1800
assert command['locks']==result['locks']==frozen['locks'] and command['cwd']==str(ROOT)
args=command['command'];assert args[:4]==['.venv/bin/python','tools/validate.py','--profile','candidate']
assert args[args.index('--review-record')+1]=='evidence/genuine-report-speed-batch-final/REVIEW_ACCEPTANCE.json' and args[args.index('--output')+1]=='evidence/genuine-report-speed-batch-final/gate-a-final'
assert checkrow(command['candidate_receipt'])==desc(result_path)
logrows=[checkrow(row) for row in command['gate_logs']];rawrows=[checkrow(row) for row in command['raw_receipts']];outerlog=checkrow(command['raw_command_log'])
names=['runtime','node-runtime','backend','pip-check','shell-syntax','matrix','frontend-locked-install','frontend-check-format','frontend-check-discovery','frontend-build','clean-locked-install','launcher-browser-rebuild','consolidated-review']
assert [g['name'] for g in result['gates']]==names and all(g['state']=='PASS' for g in result['gates'])
gates={g['name']:g for g in result['gates']};actual=[g for g in result['gates'] if 'command' in g];assert len(actual)==11
for g in actual:
 assert type(g['exit_code']) is int and g['exit_code']==0 and g['attempted'] is True and g['timed_out'] is False and g['timeout_seconds']==1800
 assert type(g['seconds']) in (int,float) and math.isfinite(g['seconds']) and 0<=g['seconds']<=1800
 assert str(Path(g['log']).parent)==str(GATE) and any(d['path']==str(Path(g['log']).relative_to(ROOT)) for d in logrows)
 assert g['cwd'] in (str(ROOT),str(ROOT/'frontend'))
outer=(ROOT/outerlog['path']).read_text();assert 'ACCEPTED_IN_SCOPE; Gate B remains OPEN.' in outer
for g in actual: assert outer.splitlines().count(g['name']+': running')==outer.splitlines().count(g['name']+': PASS')==1
assert 'FAILED' not in outer and 'BLOCKED' not in outer
python=str(ROOT/'.venv/bin/python')
assert gates['backend']['command']==[python,'-m','pytest','-q']
assert gates['pip-check']['command']==[python,'-m','pip','check'] and gates['shell-syntax']['command']==['bash','-n','run.sh','setup.sh']
assert gates['frontend-locked-install']['command']==['npm','ci','--prefer-offline','--no-audit','--no-fund']
assert [gates[n]['command'] for n in ['frontend-check-format','frontend-check-discovery','frontend-build']]==[['npm','run','check:format'],['npm','run','check:discovery'],['npm','run','build']]
backend=(GATE/'backend.log').read_text();summary=re.findall(r'(?m)^(\d+) passed, (\d+) warning, (\d+) subtests passed in ([\d.]+)s',backend)
assert summary==[('3246','1','440','373.12')] and not re.search(r'\b(?:failed|ERRORS|FAILURES|INTERNALERROR)\b',backend)
collected=json.loads((OUT/'FROZEN_MATRIX_REVIEW_FINAL.json').read_bytes());assert collected['application_commit']==HEAD and collected['source_sha256']==SOURCE and collected['collected_unique_nodes']==3246
assert result['runtime']=={'python':'3.12.14','platform':'linux','node':'24.19.0'}
assert (GATE/'runtime.log').read_text().startswith('3.12.14 ') and (GATE/'node-runtime.log').read_text().strip()=='v24.19.0'
assert (GATE/'pip-check.log').read_text().strip()=='No broken requirements found.'
matrix_path=GATE/'matrix.json';matrix=json.loads(matrix_path.read_bytes());assert matrix['state']=='PASS' and matrix['collected_unique_nodes']==3246 and matrix['required_items']==92 and len(matrix['requirements'])==92
assert {r['id'] for r in matrix['requirements']}=={r['id'] for r in collected['rows']} and all(r['state']=='PASS' for r in matrix['requirements'])
our={r['id']:r for r in collected['rows']}
for row in matrix['requirements']:
 actualnodes={n for nodes in row['nodes'].values() for n in nodes} if isinstance(row['nodes'],dict) else set(row['nodes']);expected=our[row['id']]
 wanted={expected['node']} if 'node' in expected else {n for nodes in expected['selectors'].values() for n in nodes}
 assert actualnodes==wanted
for name,path in [('matrix',matrix_path),('launcher-browser-rebuild',GATE/'browser/result.json')]:
 bound=gates[name]['evidence_receipt'];raw=json.loads(path.read_bytes());assert bound['record']==raw and bound['sha256']==desc(path)['sha256'] and bound['state']=='PASS'
for name in ['clean-locked-install','consolidated-review']:
 g=gates[name];p=ROOT/g['path'];raw=json.loads(p.read_bytes());assert g['record']==raw and g['sha256']==desc(p)['sha256']
install=gates['clean-locked-install']['record'];assert install['disposable_install'] is True and install['locks']==result['locks'] and install['runtime']==result['runtime']
assert all(type(c['exit_code']) is int and c['exit_code']==0 for c in install['commands'])
review_path=PREFIX/'REVIEW_ACCEPTANCE.json';assert desc(review_path)['sha256']=='73e4abbb86fef741681770315f2c7cc5304c7beaa053203a25e0ba53e94bdd34'
assert review_path.read_bytes()==(OUT/'CONSOLIDATED_CORRECTED_FINAL_REVIEW.json').read_bytes()
review=gates['consolidated-review']['record'];assert review['matrix_review_complete'] is True and review['source_sha256']==SOURCE
for row in review['review_evidence']:checkrow(row)
browser_path=GATE/'browser/result.json';browser=json.loads(browser_path.read_bytes());browserlog=json.loads((GATE/'launcher-browser-rebuild.log').read_bytes())
assert browserlog=={k:v for k,v in browser.items() if k not in ('cases','usage_before','usage_after')}
assert browser['state']=='PASS' and browser['offline_children']==6 and len(browser['cases'])==6
expectedcases=['canonical-nonce','loss-restoration','required-source-missing','required-source-restored','owner-change','cached-real']
assert [r['case'] for r in browser['cases']]==expectedcases
assert [r['known_closed'] for r in browser['cases']]==[1,1,0,1,0,0]
assert all(r['frozen_references_preserved'] is r['parent_export_unchanged'] is True for r in browser['cases'])
assert browser['offline_guards']==json.loads((GATE/'browser/guards.json').read_bytes())=={'provider_requests':0,'credential_lookups':0}
assert browser['usage_before']==browser['usage_after'] and browser['javascript_errors']==browser['external_browser_requests']==[]
for n in ['server_stopped','parents_unchanged','source_loss_and_exact_restoration','actual_UI_json_exports','evidence_inspection','no_overflow','offline_candidate_import','settings_saved_without_threshold_change']:assert browser[n] is True
assert browser['anonymous_state']==401
fixture=json.loads((GATE/'browser/cases.json').read_bytes());assert [r['kind'] for r in fixture['synthetic']]==['canonical-nonce','loss-restoration','owner-change'];assert fixture['real']['fees']=='0.000240394' and 'not complete wallet history' in fixture['real']['scope']
capfiles=sorted((GATE/'browser').glob('*.png'));assert len(capfiles)==browser['captures']==16
caps=[]
for p in capfiles:
 raw=p.read_bytes();assert raw[:8]==b'\x89PNG\r\n\x1a\n';w,h=struct.unpack('>II',raw[16:24]);assert w in (1440,390) and h>0;caps.append({**desc(p),'width':w,'height':h})
assert sum(r['width']==1440 for r in caps)==sum(r['width']==390 for r in caps)==8
# Preserve complete reviewed diff and current source; no reopening app/test execution.
full_diff=subprocess.check_output(['git','--no-optional-locks','diff','--binary','ab62858dca7eccbdb18b3365a83dedd9b2e8f413',HEAD],cwd=ROOT)
assert full_diff==(OUT/'FULL_BATCH_DIFF.patch').read_bytes()
assert subprocess.check_output(['git','--no-optional-locks','rev-parse','HEAD'],cwd=ROOT).decode().strip()==HEAD
for n,h in manifest['files'].items():
 p=ROOT/n;assert p.is_file() and not p.is_symlink() and desc(p)['sha256']==h and p.stat().st_mode&0o777==manifest['modes'][n]
for n,h in frozen['locks'].items():assert desc(ROOT/n)['sha256']==h
report={'kind':'independent-final-candidate-gate-readonly-review','state':'PASS','application_commit':HEAD,'source_sha256':SOURCE,'source_files':246,'locks':frozen['locks'],
'actual_candidate_command':desc(command_path),'actual_candidate_receipt':desc(result_path),'raw_stdout':outerlog,'producer_exit_code':0,'producer_seconds':command['seconds'],'producer_state':'ACCEPTED_IN_SCOPE',
'required_gates_verified':13,'actual_executed_commands':11,'retained_typed_records_verified':2,'gates':[{k:g[k] for k in ('name','state','exit_code','command','seconds','timed_out') if k in g} for g in result['gates']],
'raw_gate_logs_verified':logrows,'raw_structured_receipts_verified':rawrows,
'backend':{'ordinary_terminal_passes':3246,'separate_subtests':440,'pytest_seconds':373.12,'execution_seconds':gates['backend']['seconds'],'full_command_without_selection':True,'current_collect_unique_nodes':3246,'duplicate_execution_counts_added':0},
'matrix':{'required_items':92,'requirements':54,'schema_examples':38,'actual_mappings_equal_distinct_current_review':True},
'launcher_browser':{'actual_children':6,'case_names':expectedcases,'all_frozen_references_and_parents_preserved':True,'usage_unchanged':True,'provider_requests':0,'credential_lookups':0,'external_browser_requests':0,'captures':caps,
'capture_binding_limit':'Original launcher receipt has no capture digest map. These current16 files were read and SHA256-bound by this supplement; retained producer DOM/assertion results establish exact text/behaviour. No independent pixel-text inspection or visual claim.'},
'install_scope':{'retained_record':desc(ROOT/gates['clean-locked-install']['path']),'matches_current_locks_and_Linux_runtime':True,'original_source_identity':install.get('source_sha256'),'new_fresh_whole_candidate_setup_claim':False},
'full_batch_diff':desc(OUT/'FULL_BATCH_DIFF.patch'),'source_review_preserved':desc(OUT/'CONSOLIDATED_CORRECTED_FINAL_REVIEW.json'),
'neighbouring_contracts':'Previously read whole batch/JSONResponse seams/indexed-cache/strict inventory/archivev4/UI/tool plus correction static source scope retained at exact current bytes; full diff and246 file/mode map rechecked. No confirmed current regression found.',
'findings':[],'source_unchanged_rechecked':True,'B1':'HISTORICAL_SUFFICIENCY_UNRESOLVED','B2':'COMPLETE_REAL_ACCOUNTING_OPEN','B3':'COMPLETE_GENUINE_ACCEPTANCE_BLOCKED','PRODUCT_READY':False,
'pending_separate_scopes':['Product-browser environment retry','Four preserved genuine workflow environment retries','Eventual native CI'],
'scope':'Read-only actual13 candidate gates, typed exit/duration/source/lock/runtime receipts, raw logs and terminal summaries, original mapped matrix and launcher/native references. This supplements immutable source review; no app/tests/browser commands rerun and no broad whole-wallet acceptance.',
'application_or_browser_reruns_by_reviewer':0,'network_requests':0,'provider_requests':0,'credential_lookups':0,'source_or_Git_mutations':False}
p=OUT/'FINAL_GATE_READONLY_REVIEW.json';p.write_bytes(enc(report));dest=PREFIX/'integrated-review'
for original in [p,Path(__file__)]:
 target=dest/original.name
 if target.exists():assert target.read_bytes()==original.read_bytes()
 else:target.write_bytes(original.read_bytes())
print(json.dumps({'state':'PASS','review':desc(p),'gates':13,'ordinary_backend_passes':3246,'separate_subtests':440,'confirmed_current_regressions':0}))
