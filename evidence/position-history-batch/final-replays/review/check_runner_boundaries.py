#!/usr/bin/env python3
import hashlib, importlib.util, json, os, tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
BASE=Path('/workspace/outputs/position-history-publication/replay-review')
SCRIPT=BASE.parent/'run_final_replays.py'
spec=importlib.util.spec_from_file_location('replay_boundary_review',SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
before=hashlib.sha256(SCRIPT.read_bytes()).hexdigest();records=[]
with tempfile.TemporaryDirectory(prefix='boundary-controls-',dir=BASE) as temp:
    root=Path(temp)/'repo';root.mkdir()
    for name in m.INPUTS:
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);os.link(m.ROOT/name,target)
    original=m.ROOT
    with patch.object(m,'ROOT',root):
        inventory_before=m.inputs()
        corpus=root/'evidence/runs/real-cache';corpus.mkdir(parents=True)
        manifest=corpus/'manifest.json.gz';manifest.write_bytes(b'first small fixture')
        inventory_fixture=m.inputs()
        manifest.write_bytes(b'mutated small fixture')
        inventory_mutated=m.inputs()
        records.append({'control':'product-corpus-manifest-mutation-input-binding','fixture_only':True,'application_inputs_unchanged':True,'mutation_detected':inventory_fixture!=inventory_mutated,'genuine_three_file_inventory_unchanged':inventory_before==inventory_fixture==inventory_mutated,'state':'FINDING' if inventory_fixture==inventory_mutated else 'PASS'})
        output=root/'evidence/position-history-batch/storage-fixture';output.mkdir(parents=True)
        child=output/'product-development';child.mkdir()
        exported=child/'fixture-export.json';exported.write_bytes(b' '+b'0'*(2*1024*1024))
        expected={'commit':'a'*40,'source_sha256':'b'*64}
        m.write(output/'INDEX.json',{'state':'PASS',**expected})
        args=SimpleNamespace(output=output,application_commit=expected['commit'],source_sha=expected['source_sha256'],remove_verified_flat=True)
        error=None
        with patch.object(m,'check_identity',lambda expected:expected),patch.object(m.subprocess,'check_output',lambda *args,**kwargs:b'evidence/position-history-batch/storage-fixture/product-development/fixture-export.json\n'):
            try:m.store_exports(args)
            except Exception as exc:error=type(exc).__name__+': '+str(exc)
        stored=m.strict_json(output/'STORAGE_INDEX.json')
        records.append({'control':'tracked-flat-removal-refusal-receipt','fixture_only':True,'application_inputs_unchanged':True,'raises_error':error,'flat_preserved':exported.is_file(),'gzip_verified':stored['records'][0]['roundtrip_verified'],'storage_state':stored['state'],'claimed_original_retained':stored['records'][0]['original_retained'],'actual_original_retained':exported.exists(),'state':'FINDING' if error and stored['state']=='PASS' and not stored['records'][0]['original_retained'] and exported.exists() else 'PASS'})
after=hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
result={'kind':'distinct-read-only-replay-runner-boundary-controls','state':'FINDINGS' if any(x['state']=='FINDING' for x in records) else 'PASS','runner_unchanged':before==after,'runner_sha256_before':before,'runner_sha256_after':after,'records':records,'application_files_changed':False,'workflows_executed':False,'provider_calls':0,'credential_calls':0,'network_calls':0}
m.write(BASE/'BOUNDARY_CONTROL_REVIEW.json',result);print(json.dumps(result,indent=2))
