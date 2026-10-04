#!/usr/bin/env python3
"""Read-only corrected frozen source/provenance review. No application execution."""
import ast,hashlib,json,os,re,subprocess
from pathlib import Path
ROOT=Path('/workspace/solana-wallet-scanner'); OUT=Path('/workspace/outputs/genuine-wallet-report-correction-review')
PREVIOUS=Path('/workspace/outputs/genuine-wallet-report-review')
BASE='ab62858dca7eccbdb18b3365a83dedd9b2e8f413';FAILED='eea37dc95b5a012a62d36f4b300f1097fc311f87';HEAD='0db4125e8c1ab6b2df5bb1e79e807c80e3d195bd'
SOURCE='babd86cab36e5674d286b8b59f4692e8f2f0109e0c2375a36ab7a86ad1185b3c';PREFIX=ROOT/'evidence/genuine-report-speed-batch-final'
def identity(raw): return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def enc(x): return (json.dumps(x,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def desc(p): return {'path':str(p),**identity(p.read_bytes())}
def git(*args): return subprocess.check_output(['git','--no-optional-locks',*args],cwd=ROOT)
def committed(ref,n):return git('cat-file','blob',ref+':'+n)
def source():
 names=[n for n in git('ls-files','-z').decode().split('\0') if n and not n.startswith('evidence/')]
 names += [n for n in git('ls-files','--others','--exclude-standard','-z').decode().split('\0') if n and not n.startswith('evidence/')]
 files,modes={},{}
 for n in sorted(set(names)):
  p=ROOT/n;assert p.is_file() and not p.is_symlink();files[n]=identity(p.read_bytes())['sha256'];modes[n]=p.stat().st_mode&0o777
 data={'files':files,'modes':modes};return {'sha256':hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest(),**data}
manifest=json.loads((PREFIX/'SOURCE_MANIFEST.json').read_bytes());frozen=json.loads((PREFIX/'FROZEN_CANDIDATE.json').read_bytes())
assert source()==manifest and manifest['sha256']==SOURCE and len(manifest['files'])==246
assert git('rev-parse','HEAD').decode().strip()==HEAD==frozen['application_commit']
assert frozen['source_sha256']==SOURCE and frozen['source_files']==246 and frozen['product_ready'] is False
assert len(git('rev-list','HEAD').decode().splitlines())==45
assert git('rev-list',BASE+'..'+HEAD).decode().splitlines()==[HEAD,FAILED]
assert git('diff','--name-only','HEAD','--','.',' :(exclude)evidence/').decode().strip()==''
for n,h in manifest['files'].items():
 assert identity(committed(HEAD,n))['sha256']==h
 tree=git('ls-tree',HEAD,'--',n).decode().split();assert tree and (tree[0]=='100755')==bool(manifest['modes'][n]&0o111)
locks={n:identity((ROOT/n).read_bytes())['sha256'] for n in frozen['locks']};assert locks==frozen['locks']
assert all(identity(committed(BASE,n))['sha256']==h for n,h in locks.items())
prior_manifest=json.loads((ROOT/'evidence/genuine-report-speed-batch/SOURCE_MANIFEST.json').read_bytes())
assert prior_manifest['sha256']=='c6476e7ea65bc12e42c70488dab6b5a4b9c6170fa9a81f5f333e38546e528cd6'
assert set(prior_manifest['files'])==set(manifest['files']) and prior_manifest['modes']==manifest['modes']
changed=sorted(n for n in manifest['files'] if manifest['files'][n]!=prior_manifest['files'][n])
assert changed==['CODEX_TASK.md','ISSUES.md','docs/CONTRACT.md','scanner/app.py','tests/test_inventory_evidence.py']
for n,h in prior_manifest['files'].items(): assert identity(committed(FAILED,n))['sha256']==h
same=sorted(set(manifest['files'])-set(changed));assert len(same)==241
assert identity((PREVIOUS/'CONSOLIDATED_FROZEN_SOURCE_REVIEW.json').read_bytes())['sha256']=='b1665e7cca4d678cf8dc19c1b3b336133154fcb3c095dbbb90f5f9a1142f9ddc'
assert identity((PREVIOUS/'CONSOLIDATED_FROZEN_FINAL_REVIEW.json').read_bytes())['sha256']=='a76d1dd19438596adde2f99c95a15d2c2c175064d361bf252bc4d3a62f5cccdb'
def function(raw,name):
 tree=ast.parse(raw);f=next(s for s in tree.body if isinstance(s,(ast.FunctionDef,ast.AsyncFunctionDef)) and s.name==name)
 return ast.dump(f,include_attributes=False)
assert function(committed(BASE,'scanner/app.py'),'_freeze_native_dependencies')==function((ROOT/'scanner/app.py').read_bytes(),'_freeze_native_dependencies')
sibling_names=['scanner/report_rebuild.py','scanner/source_consistency.py','scanner/collector.py','tests/test_review_v037_independent.py','tests/review_v037/test_v037_regressions.py','tests/review_v037/test_v037_controls.py']
for n in sibling_names: assert committed(BASE,n)==committed(FAILED,n)==(ROOT/n).read_bytes()
for n in ['scanner/archive_input.py','scanner/inventory_evidence.py','scanner/wallet_evidence.py','scanner/indexed_input.py','tools/benchmark_report.py','frontend/src/InventoryObservations.tsx','frontend/src/report.tsx','tools/product_browser.py','tools/validate.py','docs/ACCEPTANCE_MATRIX.json']:
 assert (ROOT/n).read_bytes()==committed(FAILED,n)
extract=json.loads((PREFIX/'FRESH_SOURCE_EXTRACTION.json').read_bytes());assert extract['application_commit']==HEAD and extract['source_manifest_sha256']==SOURCE and extract['application_source_count']==246
assert extract['state']=='PASS' and extract['all_committed_source_bytes_match'] is True
fresh=Path(extract['extracted_source'])
for n,h in manifest['files'].items():
 p=fresh/n;assert p.is_file() and not p.is_symlink() and identity(p.read_bytes())['sha256']==h and p.stat().st_mode&0o777==manifest['modes'][n]
inputs=[]
for n,row in frozen['preserved_genuine_inputs'].items():
 assert identity((ROOT/n).read_bytes())==row==identity(committed(BASE,n));inputs.append(desc(ROOT/n))
input_path=ROOT/frozen['browser_indexed_input']['path'];assert identity(input_path.read_bytes())=={k:frozen['browser_indexed_input'][k] for k in ('bytes','sha256')}
prior_input_review=json.loads((PREVIOUS/'CURATED_INPUT_REVIEW.json').read_bytes())
assert prior_input_review['curated_input']==desc(input_path)
for key in ['raw_original_binding','worked_expectations','curation_index']:
 row=prior_input_review[key];p=Path(row['path']);assert desc(p)==row
# Preserve and inspect actual producer evidence; do not infer full source/run binding absent from it.
N=PREFIX/'native-correction';owner=json.loads((N/'NATIVE_AFFINITY_CORRECTION_OWNER.json').read_bytes())
assert owner['state']=='PASS' and owner['accepted_regression_tests_unchanged'] is True and owner['provider_requests']==owner['credential_lookups']==0
for row in owner['source_freeze']: assert identity((ROOT/row['path']).read_bytes())=={k:row[k] for k in ('bytes','sha256')}
for row in owner['log_descriptors']:
 p=Path(row['path']);assert identity(p.read_bytes())=={k:row[k] for k in ('bytes','sha256')}
 if (N/p.name).exists(): assert p.read_bytes()==(N/p.name).read_bytes()
for name,terminal in [('NATIVE_AFFINITY_CORRECTION_FOCUSED.log','253 passed, 1 warning in 98.07s'),('NATIVE_AFFINITY_CORRECTION_SIBLINGS.log','51 passed, 1 warning, 22 subtests passed in 3.41s')]:
 assert terminal in (N/name).read_text()
assert '4 passed, 1 warning in 1.96s' in Path(owner['log_descriptors'][-1]['path']).read_text()
for name in ['ACTUAL_REBUILD_AFFINITY_CURRENT.json','ACTUAL_REBUILD_AFFINITY_FIXED.json','ACTUAL_REBUILD_AFFINITY_REPLAY.py','ACTUAL_REBUILD_ROLE_FIRST_FAILURE.log']:
 assert (N/name).read_bytes()==(Path('/workspace/outputs/genuine-wallet-inventory')/name).read_bytes()
old=json.loads((N/'ACTUAL_REBUILD_AFFINITY_CURRENT.json').read_bytes());new=json.loads((N/'ACTUAL_REBUILD_AFFINITY_FIXED.json').read_bytes())
assert old['calls']==new['calls']=={'provider':0,'credential':0} and old['parent_unchanged'] is new['parent_unchanged'] is True
assert old['results'][0]['source_set']['state']=='PASS' and old['results'][1]['source_set']['state']=='UNKNOWN' and old['results'][1]['wallet_fee']['status']=='unknown'
assert len(new['results'])==3
for i,row in enumerate(new['results'],1):
 assert row['generation']==i and row['status_code']==200 and row['native_references_preserved'] is row['frozen_evidence_equal_original'] is True and row['new_refs']==[]
 assert row['source_set']['state']=='PASS' and row['source_set']['complete'] is True and row['known_closed']==1
 assert row['hold']['status']=='known' and row['hold']['value']=='6' and row['wallet_fee']['status']=='known' and row['wallet_fee']['value']=='0.000015' and row['native_delta']['value']=='-0.000016'
assert identity((N/'ACTUAL_REBUILD_AFFINITY_FIXED.json').read_bytes())['sha256']==owner['actual_three_generation_replay']['sha256']
failed_command=json.loads((ROOT/frozen['prior_failed_gate']).read_bytes());assert failed_command['state']=='FAILED' and failed_command['exit_code']==1 and failed_command['timed_out'] is False
assert failed_command['application_commit']==FAILED and failed_command['source_sha256']==prior_manifest['sha256']
rawrow=failed_command['raw_command_log'];assert identity((ROOT/rawrow['path']).read_bytes())=={k:rawrow[k] for k in ('bytes','sha256')}
failed_log=ROOT/'evidence/genuine-report-speed-batch/gate-a-final/backend.log';assert '22 failed, 3220 passed, 1 warning, 440 subtests passed in 357.35s' in failed_log.read_text()
patch=OUT/'CORRECTION_DIFF.patch';patch.write_bytes(git('diff','--binary',FAILED,HEAD))
fullpatch=OUT/'FULL_BATCH_DIFF.patch';fullpatch.write_bytes(git('diff','--binary',BASE,HEAD))
report={'kind':'independent-corrected-frozen-source-review','state':'PASS','application_commit':HEAD,'source_sha256':SOURCE,'source_files':246,'locks':locks,
'baseline':BASE,'reachable_commits':45,'new_linear_application_commits':[FAILED,HEAD],
'prior_failed_candidate':{'application_commit':FAILED,'source_sha256':prior_manifest['sha256'],'source_review_missed_native_reference_regression':True,'full_backend':'22 failed, 3220 passed;440 subtests separately','relabelled_as_current':False,'command':desc(ROOT/frozen['prior_failed_gate']),'backend_raw_log':desc(failed_log)},
'current_source_manifest':desc(PREFIX/'SOURCE_MANIFEST.json'),'current_frozen_candidate':desc(PREFIX/'FROZEN_CANDIDATE.json'),'correction_diff':desc(patch),'full_batch_diff':desc(fullpatch),
'reused_prior_review_scope':{'prior_source_review':desc(PREVIOUS/'CONSOLIDATED_FROZEN_SOURCE_REVIEW.json'),'prior_final_review':desc(PREVIOUS/'CONSOLIDATED_FROZEN_FINAL_REVIEW.json'),'unchanged_file_count':241,'unchanged_files':same,'proof':'Each current byte hash/mode equals prior246 manifest and failed committed source; reuse is limited to those exact bytes and earlier explicitly declared scopes. The missed native reference regression is separately corrected and reviewed here. Prior acceptance is not inherited.'},
'newly_reviewed_correction_files':[desc(ROOT/n) for n in changed],
'baseline_native_freezer_AST_restored':True,'unchanged_accepted_sibling_paths':[desc(ROOT/n) for n in sibling_names],
'archive_v4_internal_selector_path_unchanged':True,'native_exact_byte_capture_and_selector_contract':'IMPLEMENTATION_OPEN',
'owner_actual_evidence':{'owner':desc(N/'NATIVE_AFFINITY_CORRECTION_OWNER.json'),'fixed_three_generation_replay':desc(N/'ACTUAL_REBUILD_AFFINITY_FIXED.json'),'failed_three_generation_replay':desc(N/'ACTUAL_REBUILD_AFFINITY_CURRENT.json'),'script':desc(N/'ACTUAL_REBUILD_AFFINITY_REPLAY.py'),'terminal_logs':[desc(Path(row['path'])) for row in owner['log_descriptors']],
'producer_binding_limit':'Owner records owned file hashes after focused commands; replay JSON has no independent before/after whole-source command receipt. Current reviewer verifies copied bytes, raw terminal summaries, assertions and current owned file hashes; root exact-candidate gates remain required.',
'overlap_not_inflated':True,'reviewer_test_bodies_executed':0},
'preserved_inputs':inputs,'curated_input':desc(input_path),'prior_input_review_unchanged':desc(PREVIOUS/'CURATED_INPUT_REVIEW.json'),
'fresh_committed_source_files_rechecked':246,'fresh_source_extraction_receipt':desc(PREFIX/'FRESH_SOURCE_EXTRACTION.json'),
'findings':[],'B1':'HISTORICAL_SUFFICIENCY_UNRESOLVED','B2':'COMPLETE_REAL_ACCOUNTING_OPEN','B3':'COMPLETE_GENUINE_ACCEPTANCE_BLOCKED','PRODUCT_READY':False,
'scope':'Exact current source, five-file correction, explicitly byte-identical previous scope, accepted native sibling preservation, actual owner raw terminal receipts/provenance. No new full application, browser, native CI or complete-wallet acceptance claim.',
'network_requests':0,'provider_requests':0,'credential_lookups':0,'source_or_Git_mutations':False,'actual_application_tests_run_by_reviewer':0}
assert source()==manifest and git('rev-parse','HEAD').decode().strip()==HEAD
path=OUT/'CORRECTED_FROZEN_SOURCE_REVIEW.json';path.write_bytes(enc(report));print(json.dumps({'state':'PASS','review':desc(path),'unchanged_files':len(same),'newly_reviewed_correction_files':changed}))
