#!/usr/bin/env python3
from datetime import datetime, timezone
import hashlib,importlib.util,json,subprocess
from pathlib import Path
BASE=Path('/workspace/outputs/position-history-publication/replay-review');SCRIPT=BASE.parent/'run_final_replays.py'
spec=importlib.util.spec_from_file_location('actual_replay_receipt_review',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
expected={'commit':'8aee62e50297d6773f347b77cecc3e8794f233cf','source_sha256':'05143c96aea6afd96ede6006fb27b99bf26e648611cf161fe620306154284e96','source_file_count':241}
output=m.DEFAULT_OUTPUT;index_path=output/'INDEX.json';index=m.strict_json(index_path);identity_before=m.identity();inputs_before=m.inputs();runner_before=m.facts(SCRIPT)
executed=BASE.parent/'RUN_FINAL_REPLAYS_EXECUTED.py';executed_facts=m.facts(executed)
original=m.strict_json(m.PRODUCT_INPUT_BEFORE);product_git=[]
for entry in original['files']:
    content=subprocess.check_output(['git','show',original['baseline_commit']+':'+entry['path']],cwd=m.ROOT)
    digest=hashlib.sha256(content).hexdigest()
    blob=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
    product_git.append({'path':entry['path'],'bytes':len(content),'sha256':digest,'git_blob':blob,'match':digest==entry['sha256'] and len(content)==entry['bytes'] and blob==entry['baseline_git_blob']})
plans=m.plans(output);rows=[]
for plan,row in zip(plans,index['commands']):
    receipt_path=m.ROOT/row['receipt'];guard_path=m.ROOT/row['offline_guard'];log_path=m.ROOT/row['log']
    receipt=m.strict_json(receipt_path);guard=m.strict_json(guard_path);checks=m.receipt_checks(receipt,plan,receipt_path.parent,guard)
    expected_wrapper=[plan['application_command'][0],str(SCRIPT),'--offline-child',*plan['application_command'][1:]]
    checks.update(actual_application_command=row['application_command']==plan['application_command'],actual_wrapper_command=row['command']==expected_wrapper,
      expected_exit=type(row['exit_code']) is int and row['exit_code']==plan['expected_exit_code'],not_timed_out=row.get('timed_out') is False,
      receipt_hash=m.facts(receipt_path)=={'bytes':row['receipt_bytes'],'sha256':row['receipt_sha256']},guard_hash=m.sha(guard_path)==row['offline_guard_sha256'],
      raw_log_hash=m.facts(log_path)=={'bytes':row['log_bytes'],'sha256':row['log_sha256']},source_before_exact=row['source_before']==expected,source_after_exact=row['source_after']==expected,
      command_timeout_enforced=0<row['timeout_seconds']<=300 and row['seconds']<row['timeout_seconds'],raw_receipt_state=row['receipt_state']==receipt['state'])
    artifacts=[]
    for name,fact in receipt['artifacts'].items():
      path=receipt_path.parent/name
      observed=m.facts(path)
      want={'sha256':fact,'bytes':observed['bytes']} if isinstance(fact,str) else fact
      artifacts.append({'path':str(path.relative_to(m.ROOT)),**observed,'match':observed==want})
    checks['all_producer_artifact_hashes_match']=all(x['match'] for x in artifacts)
    rows.append({'name':plan['name'],'state':'PASS' if all(checks.values()) else 'FAILED','application_exit_code':row['exit_code'],'receipt_state':receipt['state'],'actual_case_count':len(receipt['cases']),'cases_preserved_once':checks['all_original_cases_preserved_once'],'checks':checks,'artifacts':artifacts,'artifact_bytes':sum(x['bytes'] for x in artifacts)})
elapsed=(datetime.fromisoformat(index['finished_at'])-datetime.fromisoformat(index['started_at'])).total_seconds()
identity_after=m.identity();inputs_after=m.inputs();runner_after=m.facts(SCRIPT)
checks={'four_expected_names_and_no_extra':len(index['commands'])==len(rows)==4 and [r['name'] for r in index['commands']]==[p['name'] for p in plans],
 'recorded_index_passing':index['state']=='PASS','actual_receipts_passing_revised_strict_guard':all(r['state']=='PASS' for r in rows),
 'current_exact_source_identity':identity_before==identity_after==expected,'current_source_and_commit_unchanged':identity_before==identity_after,
 'recorded_original_runner_preserved':executed_facts['sha256']==index['runner']['sha256']=='b2dbe8bffa87f53935e81ad84b36586dfa97b5210724cd44721d28295fa35068' and executed_facts['bytes']==index['runner']['bytes'],
 'revised_runner_unchanged_during_review':runner_before==runner_after,'original_product_git_bytes_match':len(product_git)==64 and all(r['match'] for r in product_git),
 'all_current_67_input_files_unchanged':len(inputs_before)==67 and inputs_before==inputs_after,'product_inventory_pinned':m.sha(m.PRODUCT_INPUT_BEFORE)==m.PRODUCT_INPUT_BEFORE_SHA,
 'independent_total_cap_observed':index['total_timeout_seconds']==600 and 0<elapsed<600,'independent_command_cap_observed':index['command_timeout_seconds']==300,
 'no_product_readiness_claim':index['PRODUCT_READY'] is False and all(r['receipt_state']!='PASS' for r in rows)}
result={'kind':'distinct-read-only-actual-four-receipt-revalidation','state':'PASS' if all(checks.values()) else 'FAILED','reviewed_at':datetime.now(timezone.utc).isoformat(),'checks':checks,'exact_application_identity':expected,
 'index':{'path':str(index_path),**m.facts(index_path)},'executed_runner':{'path':str(executed),**executed_facts},'revised_guard_runner':{'path':str(SCRIPT),**runner_after},'actual_wall_seconds':elapsed,'commands':rows,
 'product_source_git_bindings':product_git,'input_files':len(inputs_before),'product_files':len(product_git),'product_bytes':sum(r['bytes'] for r in product_git),
 'application_workflows_executed_by_reviewer':False,'application_files_changed':False,'provider_calls_by_reviewer':0,'credential_calls_by_reviewer':0,'network_calls_by_reviewer':0,
 'scope':'Independent read of already completed commands and current strict receipt helpers; revalidation is not a new workflow execution or full product acceptance.'}
m.write(BASE/'ACTUAL_FOUR_RECEIPTS_REVIEW.json',result)
print(json.dumps({k:v for k,v in result.items() if k not in ('commands','product_source_git_bindings')},indent=2))
