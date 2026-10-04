#!/usr/bin/env python3
"""Distinct frozen-source review/probes. Writes only outside application Git."""
import base64
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

sys.dont_write_bytecode=True
ROOT=Path('/workspace/solana-wallet-scanner')
OUT=Path('/workspace/outputs/genuine-wallet-report-review')
BASE='ab62858dca7eccbdb18b3365a83dedd9b2e8f413'
HEAD='eea37dc95b5a012a62d36f4b300f1097fc311f87'
SOURCE='c6476e7ea65bc12e42c70488dab6b5a4b9c6170fa9a81f5f333e38546e528cd6'
ACCEPTED_APP='8aee62e50297d6773f347b77cecc3e8794f233cf'
ACCEPTED_SOURCE='05143c96aea6afd96ede6006fb27b99bf26e648611cf161fe620306154284e96'
def identity(raw):return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def enc(v):return (json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def git(*args):return subprocess.check_output(['git','--no-optional-locks',*args],cwd=ROOT)
def record(path):return {'path':str(path),**identity(path.read_bytes())}
sys.path.insert(0,str(ROOT))
from scanner.inventory_evidence import inventory_source,derive_inventory_evidence,inventory_request_affinities,inventory_source_bytes
from scanner.json_boundary import canonical_bytes
import scanner.indexed_input as indexed

manifest_path=ROOT/'evidence/genuine-report-speed-batch/SOURCE_MANIFEST.json'
frozen_path=ROOT/'evidence/genuine-report-speed-batch/FROZEN_CANDIDATE.json'
manifest=json.loads(manifest_path.read_bytes());frozen=json.loads(frozen_path.read_bytes())
assert git('rev-parse','HEAD').decode().strip()==HEAD
assert frozen['application_commit']==HEAD and frozen['source_sha256']==SOURCE and frozen['source_files']==246
assert manifest['sha256']==SOURCE and len(manifest['files'])==246
def actual_source():
    names=[n for n in git('ls-files','-z').decode().split('\0') if n and not n.startswith('evidence/')]
    names += [n for n in git('ls-files','--others','--exclude-standard','-z').decode().split('\0') if n and not n.startswith('evidence/')]
    files,modes={},{}
    for n in sorted(set(names)):
        p=ROOT/n
        assert p.is_file() and not p.is_symlink()
        files[n]=identity(p.read_bytes())['sha256'];modes[n]=p.stat().st_mode&0o777
    sha=hashlib.sha256(json.dumps({'files':files,'modes':modes},sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'sha256':sha,'files':files,'modes':modes}
assert actual_source()==manifest
for n,sha in manifest['files'].items():
    assert identity(git('cat-file','blob',HEAD+':'+n))['sha256']==sha
    mode=git('ls-tree',HEAD,'--',n).decode().split()[0]
    assert (mode=='100755')==bool(manifest['modes'][n]&0o111)
locks={n:identity((ROOT/n).read_bytes())['sha256'] for n in frozen['locks']}
assert locks==frozen['locks']
assert all(identity(git('cat-file','blob',BASE+':'+n))['sha256']==sha for n,sha in locks.items())
inputs=[]
for n,row in frozen['preserved_genuine_inputs'].items():
    p=ROOT/n;assert identity(p.read_bytes())==row
    assert identity(git('cat-file','blob',BASE+':'+n))==row
    inputs.append(record(p))

WALLET='2Bj3dZTSSc14hFR9fCLN9CQ1TiaYyszCKX8fuVG7pyAY'
OTHER='11111111111111111111111111111111'
TOKEN='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN2022='TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
def source_row(method,params,value):
    req=json.dumps({'jsonrpc':'2.0','id':7,'method':method,'params':params}).encode()
    res=json.dumps({'jsonrpc':'2.0','id':7,'result':{'context':{'slot':1000},'value':value}}).encode()
    payload=inventory_source(req,res)
    return {'kind':'inventory-source','hash':identity(canonical_bytes(payload))['sha256'],'payload':payload}
def rows_with_affinities(rows):
    return rows+[{'kind':'inventory-affinity','hash':identity(canonical_bytes(p))['sha256'],'payload':p}
                 for p in inventory_request_affinities(rows,wallet=WALLET)]
base=[source_row('getAccountInfo',[WALLET,{'encoding':'base64','commitment':'finalized'}],
                 {'owner':OTHER,'executable':False,'lamports':1000,'data':['','base64']}),
      source_row('getBalance',[WALLET,{'commitment':'finalized'}],1000)]
base += [source_row('getTokenAccountsByOwner',[WALLET,{'programId':p},{'encoding':'jsonParsed','commitment':'finalized'}],[])
         for p in (TOKEN,TOKEN2022)]
foreign=source_row('getBalance',[OTHER,{'commitment':'finalized'}],1000)
invalid={**foreign,'hash':'0'*64}
probes=[]
for label,rows,expected in [('positive_same_slot',base,'PASS'),('valid_disjoint_source',base+[foreign],'PASS'),
                           ('invalid_checksum_disjoint_source',base+[invalid],'UNKNOWN')]:
    result=derive_inventory_evidence(rows_with_affinities(rows),wallet=WALLET)
    assert result['components']['same_slot_inventory']['state']==expected
    assert result['components']['report_boundaries']['state']=='UNKNOWN'
    if label=='invalid_checksum_disjoint_source':assert '0'*64 in result['source_dependencies']
    probes.append({'case':label,'state':'PASS','observed_inventory':result['components']['same_slot_inventory']['state'],
                   'report_boundaries':result['components']['report_boundaries']['state'],'unsigned_fixture_only':True})
linked=rows_with_affinities(deepcopy(base));target=base[-1]['hash']
for row in linked:
    if row['hash']==target:row['payload']=None
    if row['kind']=='inventory-affinity' and row['payload']['source_hash']==target:
        forged=source_row('getTokenAccountsByOwner',[OTHER,{'programId':TOKEN2022},{'encoding':'jsonParsed','commitment':'finalized'}],[])
        row['payload']['source_preimage_base64']=base64.b64encode(canonical_bytes(forged['payload'])).decode()
        row['hash']=identity(canonical_bytes(row['payload']))['sha256']
assert derive_inventory_evidence(linked,wallet=WALLET)['components']['same_slot_inventory']['state']=='UNKNOWN'
probes.append({'case':'forged_foreign_preimage_cannot_hide_missing_original','state':'PASS','unsigned_fixture_only':True})
affinities=[row for row in rows_with_affinities(base) if row['kind']=='inventory-affinity']
assert derive_inventory_evidence(affinities,wallet=WALLET)['components']['same_slot_inventory']['state']=='UNKNOWN'
probes.append({'case':'affinity_cannot_restore_positive_observations','state':'PASS','unsigned_fixture_only':True})

genuine_dir=ROOT/'evidence/genuine-wallet-batch/collection/phase6'
genuine_specs=[('01-current-wallet-account','9663e32ba0a8d1dea45b79bcc872999ca5a52977e7bfe5d7712df8eb036d85dd','feabb86540e5c606f765d034aa523643e4c469744e4d2ef684e2b1e04c673ebd'),
 ('02-current-legacy-accounts','ed44f19d919499ac45424e0f40d47ace46bb373d278983e766119b994f341704','0842531d6a0f6d49937d9b314bd13096320d52543ff13839861640ade28728e4'),
 ('03-current-token2022-accounts','91a6efe9c3137ca8a8d1f805d3ecafe4447ef1bb16ec7ad9c5f968940780ab90','6497a39b1f7f34f1c054ef140473300762dd9f5c3fd2017b4318d755ffae0d3e')]
genuine=[];raw_genuine=[]
for n,request_hash,response_hash in genuine_specs:
    req_path=genuine_dir/(n+'-request.json');res_path=genuine_dir/(n+'-response.raw.gz')
    req=req_path.read_bytes();res=gzip.decompress(res_path.read_bytes())
    assert identity(req)['sha256']==request_hash
    assert identity(res)['sha256']==response_hash
    payload=inventory_source(req,res);assert inventory_source_bytes(payload)=={'request':req,'response':res}
    genuine.append({'kind':'inventory-source','hash':identity(canonical_bytes(payload))['sha256'],'payload':payload})
    raw_genuine.append({'request':record(req_path),'compressed_response':record(res_path),'raw_response':identity(res)})
genuine_receipt=derive_inventory_evidence(rows_with_affinities(genuine),wallet=WALLET)
c=genuine_receipt['components']
assert c['native_account']['state']=='PASS' and [(p['slot'],p['lamports']) for p in c['native_account']['observations']]==[(453173211,'650240')]
assert c['token_programs'][TOKEN]['state']=='PASS' and c['token_programs'][TOKEN]['observations'][0]['account_count']==0
assert c['token_programs'][TOKEN2022]['state']=='PASS' and c['token_programs'][TOKEN2022]['observations'][0]['account_count']==1
assert c['token_programs'][TOKEN2022]['observations'][0]['accounts'][0]['quantity_raw']=='0'
assert c['token_programs'][TOKEN2022]['observations'][0]['accounts'][0]['account_lamports']=='1513840'
assert c['same_slot_inventory']['state']==c['report_boundaries']['state']=='UNKNOWN'
genuine_path=OUT/'FROZEN_GENUINE_COMPONENT_REPLAY.json';genuine_path.write_bytes(enc({'raw_inputs':raw_genuine,'receipt':genuine_receipt}))
probes.append({'case':'three_actual_original_RPC_components_remain_different_slots','state':'PASS','evidence':record(genuine_path),
               'complete_genuine_acceptance':False})

with zipfile.ZipFile(ROOT/'evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip') as z:
    old_index=json.loads(z.read('manifest.json'));page=old_index['pages'][0]
    request=z.read('raw/'+page['request_hash']+'.json');response=z.read('raw/'+page['response_hash']+'.json')
payload={'version':indexed.PAGE_VERSION,**{field:value for name,raw in [('request',request),('response',response)]
         for field,value in [(name+'_hash',identity(raw)['sha256']),(name+'_base64',base64.b64encode(raw).decode())]}}
expected=indexed.validate_page_envelope(payload,WALLET);expected_bytes=canonical_bytes(expected)
with indexed.validated_page_context():
    left=indexed.validate_page_envelope(payload,WALLET);left['reason']='caller change'
    assert canonical_bytes(indexed.validate_page_envelope(deepcopy(payload),WALLET))==expected_bytes
    corrupt={**payload,'response_base64':base64.b64encode(b'{"changed":true}').decode()}
    assert indexed.validate_page_envelope(corrupt,WALLET)['state']=='UNKNOWN'
    assert canonical_bytes(indexed.validate_page_envelope(payload,WALLET))==expected_bytes
    stats=indexed.validated_page_cache_stats()
assert not indexed.validated_page_cache_stats()['active']
probes.append({'case':'actual_indexed_page_reuse_bytes_mutation_loss_and_cleanup','state':'PASS','cache_stats':stats,
               'expected_fact_bytes':identity(expected_bytes),'current_source_revalidated':True,'complete_history_claim':False})

context_dir=OUT/'frozen-public-worker-rejection'
context_dir.mkdir(exist_ok=False)
archive=context_dir/'not-executed.zip';archive.write_bytes(b'negative-control-not-executed')
out=context_dir/'output';out.mkdir()
(out/'worker-context.json').write_bytes(enc({'version':'offline-benchmark-worker-v1','archive':str(archive),'timeout':300,'profile':False,'full_details':False}))
command=[str(ROOT/'.venv/bin/python'),str(ROOT/'tools/benchmark_report.py'),'--worker','--archive',str(archive),'--output',str(out)]
observed=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=10)
assert observed.returncode==2 and b'unrecognized arguments: --worker' in observed.stderr
assert not (out/'private-runtime').exists()
log=context_dir/'raw.log';log.write_bytes(observed.stdout+observed.stderr)
probes.append({'case':'public_worker_flag_rejected_before_private_state','state':'PASS','command':command,'exit_code':observed.returncode,'raw_log':record(log),
               'application_API_executed':False})

assert actual_source()==manifest and git('rev-parse','HEAD').decode().strip()==HEAD
assert {n:identity((ROOT/n).read_bytes())['sha256'] for n in locks}==locks
diff=git('diff','--binary',BASE,HEAD)
diff_path=OUT/'FROZEN_SOURCE_DIFF.patch';diff_path.write_bytes(diff)
changes=git('diff','--name-status',BASE,HEAD).decode().splitlines()
assert not any(line.split('\t')[-1].startswith('evidence/') for line in changes)
front_index=(ROOT/'frontend/dist/index.html').read_text()
assert 'index-DLyxdI99.js' in front_index and (ROOT/'frontend/dist/assets/index-DLyxdI99.js').is_file()
bundle=(ROOT/'frontend/dist/assets/index-DLyxdI99.js').read_text()
assert 'Archived balance snapshots' in bundle and 'data-inventory-observations' in bundle

review={'kind':'consolidated-review','state':'PASS','application_commit':HEAD,'current_head':HEAD,
 'source_sha256':SOURCE,'source_files':246,'locks':locks,'source_unchanged_during_review':True,
 'baseline':BASE,'accepted_application_commit_separate':ACCEPTED_APP,'accepted_application_source_sha256_separate':ACCEPTED_SOURCE,
 'scope':'Distinct read-only exact frozen source/diff/interface review and bounded direct probes; application gate/native CI execution, final evidence/publication and complete genuine accounting remain separately required.',
 'evidence':[record(manifest_path),record(frozen_path),record(diff_path),record(genuine_path),record(log)],
 'preserved_original_inputs':inputs,'changed_paths':changes,'findings':[],
 'resolved_findings':[{'id':'INV-01','scope':'unsigned direct interface, not a demonstrated Store/API exploit','state':'RESOLVED','control':'invalid_checksum_disjoint_source'},
                     {'id':'OBS-WORKER-CLI','scope':'public benchmark CLI lifecycle','state':'RESOLVED','control':'public_worker_flag_rejected_before_private_state'}],
 'reviewed_interfaces':[
   'Original request/response checksums, method/id/finalized/context/u64/program/eventowner/raw-unit/duplicate contracts and internally frozen negative-only affinity.',
   'Same-slot native congruence and both token programs; current components cannot produce historical boundaries, valuation, flow roles or profit qualification.',
   'Archive v1/v2/v3/v4 dependency compatibility, public affinity rejection, ordinary loss/restoration and native disguised transaction sibling paths.',
   'Context ownership/nesting/child-task/cancellation cleanup, fresh whole-envelope/original-byte hashing, private deep copies, bounded overflow and rejecting-input equivalence.',
   'Direct JSONResponse retains view/auth/CSRF/error/decoration/save ordering; ordinary full/export and existing financial interpretation are distinct from additive inventory metadata.',
   'Archived UI guards current version/live/history interpretation and shows original-slot component observations without combined balance or historical profit promotion.',
   'Benchmark public watchdog and fresh output, Python-O/Git-worktree rejection, credential/provider/HTTP/socket fences, parent/source/input invariants and nonacceptance timing scope.',
   'Optional two browser inventory assertions add to existing import/rebuild cases without duplicate backend counts; ten focused groups contain41 unique retained+new selectors.',
   'Source decision and active docs preserve unresolved historical sufficiency, complete B2 OPEN, B3 BLOCKED and PRODUCT_READY=false.'
 ],'direct_controls':probes,'actual_application_tests_run_by_reviewer':0,'actual_API_workflows_run_by_reviewer':0,
 'network_requests':0,'provider_requests':0,'credential_lookups':0,'source_or_Git_mutations':False,
 'B1':'HISTORICAL_SUFFICIENCY_UNRESOLVED','B2':'COMPLETE_REAL_ACCOUNTING_OPEN','B3':'COMPLETE_GENUINE_ACCEPTANCE_BLOCKED','PRODUCT_READY':False,
 'new_full_gate_A_claim':False,'timing_or_complete_scan_SLA_claim':False}
path=OUT/'CONSOLIDATED_FROZEN_SOURCE_REVIEW.json';path.write_bytes(enc(review))
print(json.dumps({'state':review['state'],'source_sha256':SOURCE,'source_files':246,'controls':len(probes),'review':record(path)}))
