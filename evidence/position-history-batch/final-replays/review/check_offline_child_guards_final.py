#!/usr/bin/env python3
import importlib.util,json,socket,sys,tempfile
from pathlib import Path
from unittest.mock import patch
BASE=Path('/workspace/outputs/position-history-publication/replay-review')
spec=importlib.util.spec_from_file_location('child_guard_review',BASE.parent/'run_final_replays.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
rows=[]
with tempfile.TemporaryDirectory(prefix='denied-guard-controls-',dir=BASE) as temp:
    for name,action,expected_state,expected_count,expected_exit in [
        ('empty-entrypoint',lambda:None,'PASS',(0,0),0),
        ('denied-socket-swallowed',lambda:socket.create_connection(('127.0.0.1',9)),'FAILED',(1,0),0),
        ('denied-name-lookup-swallowed',lambda:socket.getaddrinfo('example.invalid',443),'FAILED',(1,0),0),
        ('denied-bootstrap-credential-swallowed',lambda:sys.modules['keyring'].get_password('fixture','fixture'),'FAILED',(0,1),0),
        ('explicit-expected-real-block',lambda:(_ for _ in ()).throw(SystemExit(2)),'PASS',(0,0),2)]:
        output=Path(temp)/name;output.mkdir()
        def fake_run(*args,**kwargs):
            try:action()
            except AssertionError:pass
        attrs={k:getattr(socket.socket,k) for k in ('connect','connect_ex')}
        funcs={k:getattr(socket,k) for k in ('create_connection','getaddrinfo')}
        old_keyring=sys.modules.get('keyring');old_argv=sys.argv.copy();old_path=sys.path.copy()
        try:
            with patch.object(m.runpy,'run_path',fake_run):
                code=m.offline_child([str(m.ROOT/'tools/check_product.py'),'--output',str(output)])
            receipt=m.strict_json(output/'OFFLINE_GUARD.json')
            ok=(code==expected_exit and receipt['state']==expected_state and (receipt['socket_attempts'],receipt['bootstrap_credential_attempts'])==expected_count and type(receipt['application_exit_code']) is int)
            rows.append({'control':name,'state':'PASS' if ok else 'FAILED','actual_exit':code,'expected_exit':expected_exit,'offline_guard':receipt})
        finally:
            for key,value in attrs.items():setattr(socket.socket,key,value)
            for key,value in funcs.items():setattr(socket,key,value)
            if old_keyring is None:sys.modules.pop('keyring',None)
            else:sys.modules['keyring']=old_keyring
            sys.argv=old_argv;sys.path[:]=old_path
result={'kind':'offline-child-denied-guard-controls','state':'PASS' if all(x['state']=='PASS' for x in rows) else 'FAILED','controls':len(rows),'application_entrypoints_executed':False,'actual_socket_connections':0,'actual_name_lookups':0,'actual_keyring_calls':0,'records':rows}
m.write(BASE/'OFFLINE_CHILD_GUARD_REVIEW_FINAL.json',result);print(json.dumps(result,indent=2))
