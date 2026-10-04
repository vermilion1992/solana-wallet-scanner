#!/usr/bin/env python3
import contextlib, importlib.util, json, tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
BASE=Path('/workspace/outputs/position-history-publication/replay-review')
spec=importlib.util.spec_from_file_location('timecap_review',BASE.parent/'run_final_replays.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
rows=[]
for scenario,clock_values in [('successful-command-provenance',[0,0,0,1,350,350,351]),('total-budget-exhausted',[0,0,0,1,601]),('command-timeout',[0,0,0,1])]:
    with tempfile.TemporaryDirectory(prefix='timecap-controls-',dir=BASE) as temp:
        root=Path(temp)/'repo';root.mkdir();output=root/'evidence/position-history-batch/replays';output.parent.mkdir(parents=True)
        expected={'commit':'a'*40,'source_sha256':'b'*64,'source_file_count':1};inv={'fixture':'unchanged'}
        items=[{'name':name,'application_command':['fixture-python','fixture-tool.py','--output',str(output/name)],'expected_exit_code':0,'expected_state':'FIXTURE_PASS','expected_kind':'fixture-only','required_case_identities':[]} for name in ('one','two')]
        clock=iter(clock_values);calls=[];signals=[]
        class Child:
            def __init__(self,args,**kwargs):
                self.pid=424242;self.waits=0;calls.append({'argv':args,'cwd':str(kwargs['cwd']),'start_new_session':kwargs['start_new_session'],'wait_timeouts':[]})
                child_dir=Path(args[args.index('--output')+1]);child_dir.mkdir();m.write(child_dir/'result.json',{'state':'FIXTURE_PASS','real_acceptance':{'state':'BLOCKED'}});m.write(child_dir/'OFFLINE_GUARD.json',{'fixture':True});kwargs['stdout'].write(b'fixture subprocess only\n')
            def wait(self,timeout):
                calls[-1]['wait_timeouts'].append(timeout);self.waits+=1
                if scenario=='command-timeout' and self.waits==1:raise m.subprocess.TimeoutExpired('fixture',timeout)
                return -15 if scenario=='command-timeout' else 0
        args=SimpleNamespace(output=output,application_commit=expected['commit'],source_sha=expected['source_sha256'],execute=True)
        error=None
        with contextlib.ExitStack() as stack:
            for target,name,value in [(m,'ROOT',root),(m,'check_identity',lambda _:expected),(m,'inputs',lambda:inv),(m,'plans',lambda _:items),(m,'receipt_checks',lambda *args:{'fixture_only_receipt_guard':True}),(m.time,'monotonic',lambda:next(clock)),(m.subprocess,'Popen',Child),(m.os,'killpg',lambda pid,sig:signals.append([pid,int(sig)]))]:stack.enter_context(patch.object(target,name,value))
            try:m.execute(args)
            except Exception as exc:error=type(exc).__name__+': '+str(exc)
        index=m.strict_json(output/'INDEX.json')
        if scenario=='successful-command-provenance':ok=index['state']=='PASS' and len(calls)==2 and calls[0]['wait_timeouts']==[300] and calls[1]['wait_timeouts']==[250] and all(x['start_new_session'] for x in calls) and all(row['log_sha256']==m.sha(root/row['log']) and row['receipt_sha256']==m.sha(root/row['receipt']) and row['exit_code']==0 for row in index['commands'])
        elif scenario=='total-budget-exhausted':ok=index['state']=='BLOCKED' and len(calls)==1 and index['commands_not_run']==['two'] and error.startswith('TimeoutError:')
        else:ok=index['state']=='FAILED' and len(calls)==1 and index['commands'][0]['timed_out'] is True and index['commands'][0]['checks']['not_timed_out'] is False and signals==[[424242,15]] and calls[0]['wait_timeouts']==[300,5]
        rows.append({'control':scenario,'state':'PASS' if ok else 'FAILED','fixture_subprocess_only':True,'calls':calls,'signals':signals,'index_state':index['state'],'error':error,'command_records':index['commands'],'commands_not_run':index.get('commands_not_run',[])})
result={'kind':'independent-timecap-and-command-provenance-controls','state':'PASS' if all(x['state']=='PASS' for x in rows) else 'FAILED','controls':len(rows),'application_entrypoints_executed':False,'real_subprocesses_spawned':False,'network_calls':0,'credential_calls':0,'provider_calls':0,'records':rows}
m.write(BASE/'TIMECAP_PROVENANCE_REVIEW_FINAL.json',result);print(json.dumps({k:v for k,v in result.items() if k!='records'},indent=2))
