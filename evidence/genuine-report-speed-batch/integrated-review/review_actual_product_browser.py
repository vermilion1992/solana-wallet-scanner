#!/usr/bin/env python3
"""Read-only actual browser receipts/captures; no browser or app is launched."""
import hashlib
import json
from pathlib import Path
import struct

ROOT=Path('/workspace/solana-wallet-scanner')
OUT=Path('/workspace/outputs/genuine-wallet-report-review')
PREFIX=ROOT/'evidence/genuine-report-speed-batch'
BODY=PREFIX/'product-browser-final'
def ident(path):
    digest=hashlib.sha256();size=0
    with path.open('rb') as stream:
        for raw in iter(lambda:stream.read(1024*1024),b''):digest.update(raw);size+=len(raw)
    return {'path':str(path),'bytes':size,'sha256':digest.hexdigest()}
def enc(v):return (json.dumps(v,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
command_path=PREFIX/'product-browser-command/COMMAND.json';log_path=PREFIX/'product-browser-command/RAW.log';result_path=BODY/'result.json'
command=json.loads(command_path.read_bytes());result=json.loads(result_path.read_bytes())
frozen=json.loads((PREFIX/'FROZEN_CANDIDATE.json').read_bytes());manifest=json.loads((PREFIX/'SOURCE_MANIFEST.json').read_bytes())
assert command['kind']=='actual-offline-product-browser-candidate-replay' and command['state']=='PASS'
assert command['commit']==frozen['application_commit']=='eea37dc95b5a012a62d36f4b300f1097fc311f87'
assert command['source_sha256']==manifest['sha256']==frozen['source_sha256']=='c6476e7ea65bc12e42c70488dab6b5a4b9c6170fa9a81f5f333e38546e528cd6'
assert command['source_files']==len(manifest['files'])==246 and command['locks']==frozen['locks']
assert all(ident(ROOT/n)['sha256']==sha for n,sha in frozen['locks'].items())
assert type(command['exit_code']) is int and command['exit_code']==0 and command['timed_out'] is False
assert type(command['timeout_seconds']) is int and command['timeout_seconds']==300 and 0<command['seconds']<=300
assert command['source_unchanged'] is True and command['commit_unchanged'] is True
assert ident(log_path)['sha256']==command['raw_log_sha256'] and ident(log_path)['bytes']==command['raw_log_bytes']
assert ident(result_path)['sha256']==command['browser_receipt_sha256']
raw_rows=[json.loads(line) for line in log_path.read_bytes().splitlines() if line]
assert len(raw_rows)==3
assert raw_rows[-1]=={k:v for k,v in result.items() if k not in ('cases','usage_before','usage_after','artifacts')}
for row in raw_rows[:-1]:
    assert row['provider_requests']==0 and Path(row['output']).parent==BODY
    assert row['sha256']==result['artifacts'][Path(row['output']).name]
args=command['command']
assert args[args.index('--indexed-archive')+1]==str(ROOT/frozen['browser_indexed_input']['path'])
assert args[args.index('--indexed-expected-fees')+1]=='0.000158868' and '--inventory-snapshots' in args
assert args[args.index('--output')+1]==str(BODY) and args[args.index('--python')+1]==str(ROOT/'.venv/bin/python')
assert result['kind']=='offline-product-browser' and result['state']=='PASS' and result['real_acceptance']=='BLOCKED'
assert len(result['cases'])==command['case_count']==7 and all(r['state']=='PASS' for r in result['cases'])
assert len(result['selected_cohort_ui_assertions'])==len(command['selected_cohort_ui_cases'])==8
assert result['selected_cohort_ui_assertions']==command['selected_cohort_ui_cases']
assert all(r['state']=='PASS' and r['wallet_qualification'] is False for r in result['selected_cohort_ui_assertions'])
assert result['inventory_ui_assertions']==command['inventory_ui_assertions']
assert [r['case'] for r in result['inventory_ui_assertions']]==['indexed-inventory-import','indexed-inventory-rebuilt']
for row in result['inventory_ui_assertions']:
    assert row['state']=='PASS' and row['source_inspection'] is True and row['native_lamports']=='650240'
    assert row['legacy_accounts']==0 and row['token2022_accounts']==1 and row['context_slots']==[453173211,453173213,453173215]
    assert row['combined_inventory']==row['report_boundaries']=='UNKNOWN' and row['wallet_qualification'] is False
assert command['contract']=={'state':'PASS','cases':7,'cohort_ui_sets':8,'captures':16,'inventory_ui_observations':2,'unique_test_nodes_added':0,'real_acceptance':'BLOCKED'}
for name in ('actual_UI_json_exports','evidence_inspection','source_loss_and_exact_restoration','parent_unchanged','server_stopped','no_overflow'):
    assert result[name] is True
assert command['parent_unchanged'] is True and result['anonymous_state']==401
assert result['usage_before']==result['usage_after'] and result['javascript_errors']==result['external_browser_requests']==[]
assert result['offline_guards']==command['offline_guards']=={'provider_requests':0,'credential_lookups':0}
artifacts=[];captures=[]
for n,sha in result['artifacts'].items():
    p=BODY/n;row=ident(p);assert row['sha256']==sha;artifacts.append(row)
    if n.endswith('.png'):
        with p.open('rb') as stream:header=stream.read(24)
        assert header[:8]==b'\x89PNG\r\n\x1a\n'
        width,height=struct.unpack('>II',header[16:24]);assert width in (1440,390) and height>0
        captures.append({**row,'width':width,'height':height})
assert len(captures)==result['captures']==command['captures']==16
assert len([r for r in captures if r['width']==1440])==len([r for r in captures if r['width']==390])==8
assert all(ident(ROOT/n)['sha256']==sha and (ROOT/n).stat().st_mode&0o777==manifest['modes'][n] for n,sha in manifest['files'].items())
review={'kind':'independent-actual-product-browser-receipt-review','state':'PASS','application_commit':command['commit'],
 'source_sha256':command['source_sha256'],'source_files':246,'locks':command['locks'],
 'actual_command':ident(command_path),'raw_producer_stdout':ident(log_path),'actual_result':ident(result_path),
 'actual_seconds':command['seconds'],'actual_exit_code':0,'source_unchanged_rechecked':True,
 'actual_original_cases':7,'cohort_UI_groups':8,'inventory_UI_import_and_rebuild_assertions':2,
 'digest_verified_artifacts':artifacts,'digest_verified_captures':captures,
 'visual_sampling':{'files':['indexed-partial-desktop.png','indexed-partial-rebuilt-mobile.png'],
   'scope':'Full-page previews inspected for layout. The captures are extremely tall; exact inventory text is verified by retained DOM assertions, not independently read from these scaled previews.'},
 'provider_requests':0,'credential_lookups':0,'external_browser_requests':0,
 'browser_executed_by_reviewer':False,'unique_backend_test_nodes_added':0,
 'source_only_review_rewritten':False,'B3':'COMPLETE_GENUINE_ACCEPTANCE_BLOCKED','PRODUCT_READY':False,
 'scope':'Actual root-produced browser command, raw stdout, result, artifact/capture binding and scoped DOM assertions; no test or browser rerun, complete-wallet acceptance or throughput claim.'}
path=OUT/'ACTUAL_PRODUCT_BROWSER_REVIEW.json';path.write_bytes(enc(review))
dest=PREFIX/'integrated-review'
for p in (path,Path(__file__)):
    d=dest/p.name
    if d.exists():assert d.read_bytes()==p.read_bytes()
    else:d.write_bytes(p.read_bytes())
index={'kind':'actual-browser-review-relocation-supplement','state':'PASS',
       'files':[{'original_path':str(p),'curated_path':str((dest/p.name).relative_to(ROOT)),
                 **{k:ident(p)[k] for k in ('bytes','sha256')}} for p in (path,Path(__file__))],
       'actual_browser_outputs_already_in_repository_prefix':True,'producer_receipts_rewritten':False,'source_or_Git_mutations':False}
index_path=dest/'BROWSER_REVIEW_RELOCATION.json';index_path.write_bytes(enc(index))
print(json.dumps({'state':'PASS','review':ident(path),'relocation':ident(index_path),'cases':7,'captures':16,'inventory_assertions':2}))
