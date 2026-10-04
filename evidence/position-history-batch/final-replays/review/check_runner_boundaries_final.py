#!/usr/bin/env python3
import contextlib, gzip, hashlib, importlib.util, json, os, tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
BASE=Path('/workspace/outputs/position-history-publication/replay-review');SCRIPT=BASE.parent/'run_final_replays.py'
spec=importlib.util.spec_from_file_location('boundary_review_final',SCRIPT);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
before=m.sha(SCRIPT);rows=[]
def add(name,ok,**data):rows.append({'control':name,'state':'PASS' if ok else 'FAILED','fixture_only':True,**data})
def rejects(call):
    try:call();return False
    except (ValueError,OSError):return True
with tempfile.TemporaryDirectory(prefix='boundaries-final-',dir=BASE) as temp:
    root=Path(temp)/'input-fixture';root.mkdir()
    for name in m.INPUTS:
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);os.link(m.ROOT/name,target)
    corpus=root/'evidence/runs/real-cache';corpus.mkdir(parents=True)
    manifest=corpus/'manifest.json.gz';raw=b'original isolated corpus bytes';manifest.write_bytes(raw)
    name=str(manifest.relative_to(root));inventory={'state':'PASS','all_equal_preserved_baseline_bytes':True,'baseline_commit':'1040215f498b1317b1b942838994127f43a822bd','file_count':1,'files':[{'path':name,**m.facts(manifest)}]}
    inventory_path=Path(temp)/'fixture-inventory.json';m.write(inventory_path,inventory);inventory_sha=m.sha(inventory_path)
    with patch.object(m,'ROOT',root),patch.object(m,'PRODUCT_INPUT_BEFORE',inventory_path),patch.object(m,'PRODUCT_INPUT_BEFORE_SHA',inventory_sha):
        original=m.inputs();add('isolated-corpus-positive',original[name]==m.facts(manifest),bound_files=len(original))
        manifest.write_bytes(b'changed fixture');add('product-manifest-mutation-rejected',rejects(m.inputs));manifest.write_bytes(raw);add('product-manifest-exact-restoration',m.inputs()==original)
        manifest.unlink();add('product-file-loss-rejected',rejects(m.inputs));manifest.write_bytes(raw)
        extra=corpus/'unexpected';extra.write_bytes(b'extra');add('product-file-addition-rejected',rejects(m.inputs));extra.unlink()
        target=Path(temp)/'symlink-target';target.write_bytes(raw);manifest.unlink();manifest.symlink_to(target);add('product-required-symlink-rejected',rejects(m.inputs));manifest.unlink();manifest.write_bytes(raw)
        saved=inventory_path.read_bytes();inventory_path.write_bytes(b'corrupt inventory');add('pinned-inventory-byte-mutation-rejected',rejects(m.inputs));inventory_path.write_bytes(saved);add('pinned-inventory-exact-restoration',m.inputs()==original)
    for scenario in ('retained-positive','removed-positive','tracked-preflight','changed-preflight','changed-before-remove','second-unlink-failure','protected-files','overwrite-refusal','output-confinement'):
        root=Path(temp)/scenario;root.mkdir();output=root/'evidence/position-history-batch/storage';output.mkdir(parents=True);child=output/'product-development';child.mkdir()
        expected={'commit':'a'*40,'source_sha256':'b'*64};m.write(output/'INDEX.json',{'state':'PASS',**expected})
        payload=b' '+b'0'*(2*1024*1024)
        a=child/'a-export.json';z=child/'z-export.json';a.write_bytes(payload);z.write_bytes(payload+b'1')
        oldsha={x.name:m.sha(x) for x in (a,z)};args=SimpleNamespace(output=output,application_commit=expected['commit'],source_sha=expected['source_sha256'],remove_verified_flat=scenario!='retained-positive')
        protected=[]
        if scenario=='protected-files':
            for filename in ('EXPECTED_RAW.json','EXPECTED_WORKED.json','result.json','OFFLINE_GUARD.json'):
                p=child/filename;p.write_bytes(payload);protected.append((p,m.sha(p)))
            data=child/'data';data.mkdir();private=data/'runtime.json';private.write_bytes(payload);protected.append((private,m.sha(private)))
        if scenario=='overwrite-refusal':a.with_name(a.name+'.gz').write_bytes(b'existing protected file')
        if scenario=='output-confinement':args.output=Path(temp)/'outside-confined-output'
        realfacts=m.facts;fact_count={};realunlink=Path.unlink
        def observed_facts(path):
            p=Path(path);fact_count[p]=fact_count.get(p,0)+1
            if scenario=='changed-before-remove' and p==a and fact_count[p]==4:p.write_bytes(b'mutated after preflight')
            return realfacts(p)
        def git_lookup(argv,**kwargs):
            if scenario=='tracked-preflight' and argv[-1].endswith(z.name):return b'tracked\n'
            if scenario=='changed-preflight' and argv[-1].endswith(a.name):a.write_bytes(b'mutated before preflight')
            return b''
        def unlink(path,*args,**kwargs):
            if scenario=='second-unlink-failure' and path==z:raise OSError('isolated fixture unlink refusal')
            return realunlink(path,*args,**kwargs)
        error=None
        with patch.object(m,'ROOT',root),patch.object(m,'check_identity',lambda _:expected),patch.object(m.subprocess,'check_output',git_lookup),patch.object(m,'facts',observed_facts),patch.object(Path,'unlink',unlink):
            try:m.store_exports(args)
            except Exception as exc:error=type(exc).__name__+': '+str(exc)
        storage_path=output/'STORAGE_INDEX.json';storage=m.strict_json(storage_path) if storage_path.exists() else None
        if scenario=='retained-positive':ok=not error and storage['state']=='PASS' and all(r['original_retained'] for r in storage['records']) and a.exists() and z.exists()
        elif scenario in ('removed-positive','protected-files'):
            ok=not error and storage['state']=='PASS' and not a.exists() and not z.exists() and not any(r['original_retained'] for r in storage['records'])
            for filename,expected_sha in oldsha.items():ok=ok and hashlib.sha256(gzip.decompress((child/(filename+'.gz')).read_bytes())).hexdigest()==expected_sha
            ok=ok and all(p.exists() and m.sha(p)==h and not p.with_name(p.name+'.gz').exists() for p,h in protected)
        elif scenario=='second-unlink-failure':ok=bool(error) and storage['state']=='BLOCKED' and not a.exists() and z.exists() and [r['original_retained'] for r in storage['records']]==[False,True]
        elif scenario in ('overwrite-refusal','output-confinement'):ok=bool(error) and a.exists() and z.exists() and storage is None
        else:ok=bool(error) and storage['state']=='BLOCKED' and a.exists() and z.exists() and all(r['original_retained'] for r in storage['records'])
        add('storage-'+scenario,ok,error=error,storage_state=storage.get('state') if storage else None,actual_flats_retained=[a.exists(),z.exists()],receipt_flats_retained=[r['original_retained'] for r in storage['records']] if storage else None)
result={'kind':'distinct-read-only-repaired-runner-boundary-controls','state':'PASS' if all(x['state']=='PASS' for x in rows) else 'FAILED','runner_sha256_before':before,'runner_sha256_after':m.sha(SCRIPT),'runner_unchanged':before==m.sha(SCRIPT),'controls':len(rows),'records':rows,'application_files_changed':False,'workflows_executed':False,'provider_calls':0,'credential_calls':0,'network_calls':0}
m.write(BASE/'BOUNDARY_CONTROL_REVIEW_FINAL.json',result);print(json.dumps(result,indent=2))
