#!/usr/bin/env python3
import copy, hashlib, importlib.util, json, os, tempfile
from pathlib import Path
BASE=Path('/workspace/outputs/position-history-publication/replay-review')
RUNNER=BASE.parent/'run_final_replays.py'
spec=importlib.util.spec_from_file_location('reviewed_replay_runner', RUNNER)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
before=hashlib.sha256(RUNNER.read_bytes()).hexdigest()
baseline=m.strict_json(m.BASELINE_INDEX)
rows=[]

def assess(name, record, plan, output, guard, expect):
    try:
        checks=m.receipt_checks(record,plan,output,guard)
        accepted=all(checks.values()); error=None
    except (OSError,ValueError,KeyError,TypeError) as exc:
        checks={};accepted=False;error=type(exc).__name__+': '+str(exc)
    rows.append({'control':name,'expected_acceptance':expect,'actual_acceptance':accepted,'matched_expected':accepted==expect,'failed_checks':[k for k,v in checks.items() if not v],'error':error})

with tempfile.TemporaryDirectory(prefix='receipt-controls-',dir=BASE) as temp:
    output_root=Path(temp)
    for old,plan in zip(baseline['commands'],m.plans(output_root)):
        output=output_root/old['name'];output.mkdir()
        old_dir=(m.ROOT/old['receipt']).parent
        for filename in ('input.zip','EXPECTED_RAW.json','EXPECTED_WORKED.json'):
            source=old_dir/filename
            if source.is_file():os.link(source,output/filename)
        record=m.strict_json(m.ROOT/old['receipt'])
        guard={'kind':'counted-offline-python-guards','state':'PASS','socket_attempts':0,'bootstrap_credential_attempts':0,'application_command':plan['application_command'][1:],'application_exit_code':plan['expected_exit_code']}
        prefix=plan['name']+':'
        assess(prefix+'retained-known-positive',record,plan,output,guard,True)
        for value in (None, [], 'PASS'):
            assess(prefix+'nonobject-'+repr(value),value,plan,output,guard,False)
        for field,value in [('kind','wrong'),('state','PASS' if record['state']!='PASS' else 'BLOCKED'),('provider_requests',1),('provider_requests',False),('credential_lookups',1),('credential_lookups',False),('parent_unchanged',False),('collector_ancestry_created',True)]:
            changed=copy.deepcopy(record);changed[field]=value
            assess(prefix+field+'='+repr(value),changed,plan,output,guard,False)
        for tag,cases in [('missing',record['cases'][:-1]),('duplicate',record['cases']+[record['cases'][0]]),('sibling-replaced',record['cases'][:-1]+[record['cases'][0]]),('empty',[])]:
            changed=copy.deepcopy(record);changed['cases']=cases
            assess(prefix+'cases-'+tag,changed,plan,output,guard,False)
        changed=copy.deepcopy(record);changed['cases'][0]['state']='FAILED';assess(prefix+'failed-case',changed,plan,output,guard,False)
        changed=copy.deepcopy(record);changed['real_acceptance']['state']='PASS';assess(prefix+'real-acceptance-promoted',changed,plan,output,guard,False)
        for field,value in [('kind','wrong'),('state','FAILED'),('socket_attempts',1),('socket_attempts',False),('bootstrap_credential_attempts',1),('bootstrap_credential_attempts',False),('application_command',[]),('application_exit_code',1)]:
            changed=copy.deepcopy(guard);changed[field]=value
            assess(prefix+'guard-'+field+'='+repr(value),record,plan,output,changed,False)
        if plan['name'].startswith('genuine-'):
            for field,value in [('PRODUCT_READY',True),('usage_unchanged',False),('oracle_frozen_before_application',False),('archive_sha256','0'*64),('oracle_sha256','0'*64),('worked_expectations_sha256','0'*64)]:
                changed=copy.deepcopy(record);changed[field]=value;assess(prefix+field+'-broken',changed,plan,output,guard,False)
            for case_index,case in enumerate(record['cases']):
                if case['case']=='selected-lot-required-source-loss-exact-restoration':
                    changed=copy.deepcopy(record);changed['cases'][case_index]['parent_unchanged']=False;assess(prefix+'lot-'+case['role']+'-parent-mutated',changed,plan,output,guard,False)
                    changed=copy.deepcopy(record);changed['cases'][case_index]['restored_expectations']['state']='FAILED';assess(prefix+'lot-'+case['role']+'-restoration-failed',changed,plan,output,guard,False)
            for filename in ('input.zip','EXPECTED_RAW.json','EXPECTED_WORKED.json'):
                target=output/filename;saved=target.read_bytes();target.unlink()
                assess(prefix+filename+'-missing',record,plan,output,guard,False)
                target.write_bytes(b'corrupt source')
                assess(prefix+filename+'-corrupt',record,plan,output,guard,False)
                target.unlink();target.write_bytes(saved)
                assess(prefix+filename+'-restored',record,plan,output,guard,True)
        else:
            changed=copy.deepcopy(record);changed['development']['state']='UNKNOWN';assess(prefix+'development-unknown',changed,plan,output,guard,False)
            changed=copy.deepcopy(record);changed['usage_after']={'different':1};assess(prefix+'usage-changed',changed,plan,output,guard,False)
            changed=copy.deepcopy(record);changed['real_acceptance_required']=not changed['real_acceptance_required'];assess(prefix+'mode-wrong',changed,plan,output,guard,False)
            for case_index,case in enumerate(record['cases']):
                if 'parent_unchanged' in case:
                    changed=copy.deepcopy(record);changed['cases'][case_index]['parent_unchanged']=False
                    assess(prefix+case['case']+'-parent-mutated',changed,plan,output,guard,False)
    for label,payload in [('syntax',b'{'),('duplicate',b'{"state":"PASS","state":"FAILED"}'),('nonfinite',b'{"value":NaN}')]:
        path=output_root/(label+'.json');path.write_bytes(payload)
        try:m.strict_json(path);rejected=False
        except (ValueError,UnicodeError):rejected=True
        rows.append({'control':'strict-json-'+label,'expected_acceptance':False,'actual_acceptance':not rejected,'matched_expected':rejected})
after=hashlib.sha256(RUNNER.read_bytes()).hexdigest()
result={'kind':'distinct-read-only-replay-runner-receipt-controls','state':'PASS' if all(x['matched_expected'] for x in rows) and before==after else 'FINDINGS','runner_sha256_before':before,'runner_sha256_after':after,'runner_unchanged':before==after,'controls':len(rows),'passed_controls':sum(x['matched_expected'] for x in rows),'findings':[x for x in rows if not x['matched_expected']],'records':rows,'application_files_changed':False,'workflows_executed':False,'provider_calls':0,'credential_calls':0,'network_calls':0}
m.write(BASE/'RECEIPT_CONTROL_REVIEW.json',result)
print(json.dumps({k:v for k,v in result.items() if k!='records'},indent=2))
