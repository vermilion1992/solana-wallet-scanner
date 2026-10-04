#!/usr/bin/env python3
"""Read-only current collection/coverage/input review; no test bodies execute."""
import ast
import base64
from copy import deepcopy
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from types import SimpleNamespace
import zipfile

sys.dont_write_bytecode=True
ROOT=Path('/workspace/solana-wallet-scanner')
OUT=Path('/workspace/outputs/genuine-wallet-report-review')
DEST=ROOT/'evidence/genuine-report-speed-batch/integrated-review'
HEAD='eea37dc95b5a012a62d36f4b300f1097fc311f87'
SOURCE='c6476e7ea65bc12e42c70488dab6b5a4b9c6170fa9a81f5f333e38546e528cd6'
BASE='ab62858dca7eccbdb18b3365a83dedd9b2e8f413'
def identity(raw):return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def enc(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def descriptor(path):return {'path':str(path),**identity(path.read_bytes())}
def git(*args):return subprocess.check_output(['git','--no-optional-locks',*args],cwd=ROOT)
def check_source():
    manifest=json.loads((ROOT/'evidence/genuine-report-speed-batch/SOURCE_MANIFEST.json').read_bytes())
    assert manifest['sha256']==SOURCE and len(manifest['files'])==246
    assert git('rev-parse','HEAD').decode().strip()==HEAD
    assert all(identity((ROOT/n).read_bytes())['sha256']==h and (ROOT/n).stat().st_mode&0o777==manifest['modes'][n] for n,h in manifest['files'].items())
    return manifest
manifest=check_source()
matrix_path=ROOT/'docs/ACCEPTANCE_MATRIX.json';schema_path=ROOT/'tests/fixtures/instruction_family_schema.json'
matrix=json.loads(matrix_path.read_bytes());schema=json.loads(schema_path.read_bytes())
assert len(matrix['requirements'])==54 and len(schema['examples'])==38
assert len({r['id'] for r in matrix['requirements']})==54 and len({r['id'] for r in schema['examples']})==38
old_matrix=json.loads(git('cat-file','blob',BASE+':docs/ACCEPTANCE_MATRIX.json'))
assert matrix['requirements'][:-2]==old_matrix['requirements'] and matrix['browser_required']==old_matrix['browser_required']
assert schema_path.read_bytes()==git('cat-file','blob',BASE+':tests/fixtures/instruction_family_schema.json')
assert all(r['id'] and r['axis'] and r['selectors'] for r in matrix['requirements'])
for ex in schema['examples']:
    assert ex['family'] in ('token','system','associated') and ex['instruction']['parsed']['type']==ex['kind']
    assert ex['required_scope_fields'] and all(f in ex['instruction']['parsed']['info'] for f in ex['required_scope_fields'])

command=[str(ROOT/'.venv/bin/python'),'-m','pytest','--collect-only','-q']
started=time.perf_counter()
raw_log=OUT/'FROZEN_MATRIX_COLLECT_ONLY.log'
prior_matrix_path=OUT/'FROZEN_MATRIX_REVIEW.json'
if prior_matrix_path.exists():
    prior=json.loads(prior_matrix_path.read_bytes())
    assert prior['state']=='PASS' and prior['application_commit']==HEAD and prior['source_sha256']==SOURCE
    assert prior['collection_command']==command and prior['actual_exit_code']==0 and prior['raw_log']==descriptor(raw_log)
    observed=SimpleNamespace(returncode=0,stdout=raw_log.read_bytes(),stderr=b'')
    collection_seconds=prior['seconds']
else:
    observed=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=180)
    raw_log.write_bytes(observed.stdout+observed.stderr)
    collection_seconds=time.perf_counter()-started
assert observed.returncode==0
nodes=[line for line in observed.stdout.decode().splitlines() if line.startswith('tests/') and '::' in line]
assert nodes and len(nodes)==len(set(nodes))
node_set=set(nodes);rows=[]
for item in matrix['requirements']:
    matches={s:sorted(n for n in node_set if re.fullmatch(''.join('.*' if c=='*' else '.' if c=='?' else re.escape(c) for c in s),n)) for s in item['selectors']}
    assert all(matches.values()),item['id']
    rows.append({'id':item['id'],'axis':item['axis'],'state':'MAPPED','selectors':matches,'test_execution_claim':False})
for example in schema['examples']:
    node='tests/test_instruction_contract_matrix.py::test_every_primary_schema_contract_has_the_required_reference_paths['+example['id']+']'
    assert node in node_set
    rows.append({'id':'schema-'+example['id'],'axis':'Representation','state':'MAPPED','node':node,
                 'required_scope_fields':example['required_scope_fields'],'unsigned_schema_fixture_only':True})
assert len(rows)==92
validate_ast=ast.parse((ROOT/'tools/validate.py').read_bytes())
values={}
for stmt in validate_ast.body:
    if isinstance(stmt,ast.Assign) and len(stmt.targets)==1 and isinstance(stmt.targets[0],ast.Name) and stmt.targets[0].id in ('FOCUSED','FOCUSED_GROUPS'):
        values[stmt.targets[0].id]=ast.literal_eval(stmt.value)
focused,groups=values['FOCUSED'],values['FOCUSED_GROUPS']
flat=[s for sels in groups.values() for s in sels]
assert len(groups)==10 and len(flat)==len(set(flat))==41 and set(flat)==set(focused)
old_ast=ast.parse(git('cat-file','blob',BASE+':tools/validate.py'))
old_focused=next(ast.literal_eval(s.value) for s in old_ast.body if isinstance(s,ast.Assign) and len(s.targets)==1 and isinstance(s.targets[0],ast.Name) and s.targets[0].id=='FOCUSED')
assert set(old_focused)<=set(focused) and set(focused)-set(old_focused)=={'tests/test_inventory_evidence.py','tests/test_report_benchmark.py'}
group_nodes={name:sorted(n for n in node_set if any(n.split('::',1)[0]==s or n.startswith(s.rstrip('/')+'/') for s in selectors)) for name,selectors in groups.items()}
assert all(group_nodes.values())
assert sum(map(len,group_nodes.values()))==len(set(n for ns in group_nodes.values() for n in ns))
matrix_report={'kind':'independent-current-matrix-review','state':'PASS','matrix_review_complete':True,
 'application_commit':HEAD,'source_sha256':SOURCE,'matrix':descriptor(matrix_path),'schema_fixture':descriptor(schema_path),
 'requirements_reviewed':54,'schema_examples_reviewed':38,'required_items':92,'rows':rows,
 'collection_command':command,'cwd':str(ROOT),'actual_exit_code':observed.returncode,'seconds':collection_seconds,
 'raw_log':descriptor(raw_log),'collected_unique_nodes':len(node_set),'test_bodies_executed':0,
 'focused_groups':{name:{'selectors':groups[name],'mapped_unique_nodes':len(group_nodes[name])} for name in groups},
 'focused_unique_selectors':41,'disjoint_focused_node_collection':True,
 'scope':'Read-only selector/schema and disjoint-partition review. Collected nodes are not passing test executions and are not added to acceptance counts.',
 'findings':[],'PRODUCT_READY':False}
matrix_report_path=OUT/'FROZEN_MATRIX_REVIEW_FINAL.json';matrix_report_path.write_bytes(enc(matrix_report))

frozen=json.loads((ROOT/'evidence/genuine-report-speed-batch/FROZEN_CANDIDATE.json').read_bytes())
input_path=ROOT/frozen['browser_indexed_input']['path']
assert identity(input_path.read_bytes())=={k:frozen['browser_indexed_input'][k] for k in ('bytes','sha256')}
binding_path=input_path.parent/'INPUT_BINDING.json';binding=json.loads(binding_path.read_bytes())
expected_path=input_path.parent/'INVENTORY_EXPECTATIONS.json';expected=json.loads(expected_path.read_bytes())
curation_path=ROOT/'evidence/genuine-report-speed-batch/implementation-inventory/CURATION_INDEX.json';curation=json.loads(curation_path.read_bytes())
assert expected['input_path']==str(input_path.relative_to(ROOT)) and expected['input_sha256']==binding['sha256']==identity(input_path.read_bytes())['sha256']
assert expected['input_bytes']==binding['bytes']==input_path.stat().st_size
for row in curation['files']:
    original=Path(row['original_path']);original=original if original.is_absolute() else ROOT/original
    curated=ROOT/row['curated_path'];assert original.read_bytes()==curated.read_bytes()
    assert identity(curated.read_bytes())=={k:row[k] for k in ('bytes','sha256')}
assert identity(expected_path.read_bytes())=={k:curation['independent_expectations'][k] for k in ('bytes','sha256')}
old_zip=ROOT/'evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip'
with zipfile.ZipFile(old_zip) as z:
    original_manifest_raw=z.read('manifest.json');original_manifest=json.loads(original_manifest_raw)
    original_raw={n.removeprefix('raw/').removesuffix('.json'):z.read(n) for n in z.namelist() if n.startswith('raw/')}
    assert all(identity(raw)['sha256']==sha for sha,raw in original_raw.items())
with zipfile.ZipFile(input_path) as z:
    names=z.namelist();assert len(names)==len(set(names))==104 and z.testzip() is None
    assert {r['path'] for r in binding['extracted_files']}==set(names)
    for row in binding['extracted_files']:assert identity(z.read(row['path']))=={k:row[k] for k in ('bytes','sha256')}
    m=json.loads(z.read('manifest.json'))
    payloads={Path(n).name.removesuffix('.json.gz'):json.loads(gzip.decompress(z.read(n))) for n in names if n.startswith('archives/')}
    assert all(identity(canonical(p))['sha256']==sha for sha,p in payloads.items())
assert m['address']==original_manifest['address']==expected['wallet'] and m['window']==original_manifest['window']
assert m['dataset']=='real' and len(m['transactions'])==len({r['signature'] for r in m['transactions']})==87
refs=m['transactions']+m['evidence'];assert set(payloads)=={r['hash'] for r in refs}
for r in m['evidence']:
    p=payloads[r['hash']]
    if r['kind']=='indexed-input-manifest':assert base64.b64decode(p['bytes_base64'],validate=True)==original_manifest_raw
    if r['kind'] in ('indexed-native-source','indexed-page'):
        for key in ('request','response'):
            raw=base64.b64decode(p[key+'_base64'],validate=True)
            assert identity(raw)['sha256']==p[key+'_hash'] and original_raw[p[key+'_hash']]==raw
for r in m['transactions']:
    p=payloads[r['hash']];assert p['version']=='indexed-transaction-v1' and p['signature']==r['signature']
    src=payloads[p['source_hash']];body=json.loads(base64.b64decode(src['response_base64'],validate=True))['result']
    page=body['data'] if src['version']=='indexed-page-source-v1' else [body]
    assert page[p['ordinal']]['transaction']['signatures'][0]==r['signature']
    assert identity(canonical(page[p['ordinal']]))['sha256']==p['native_hash']
source_rows=[]
for row in expected['source_records']:
    req_path=ROOT/row['request_path'];res_path=ROOT/row['stored_response_path']
    req_raw=req_path.read_bytes();res_stored=res_path.read_bytes();res_raw=gzip.decompress(res_stored)
    assert identity(req_raw)=={'bytes':row['request_bytes'],'sha256':row['request_sha256']}
    assert identity(res_stored)=={'bytes':row['stored_response_bytes'],'sha256':row['stored_response_sha256']}
    assert identity(res_raw)=={'bytes':row['response_bytes'],'sha256':row['response_sha256']}
    req,res=json.loads(req_raw),json.loads(res_raw)
    assert req['id']==res['id']==row['rpc_id'] and req['method']==row['method'] and req['params'][0]==row['request_wallet']==expected['wallet']
    assert req['params'][-1]['commitment']==row['commitment']=='finalized' and res['result']['context']['slot']==row['context_slot']
    wrapper=payloads[row['wrapper_hash']]
    assert base64.b64decode(wrapper['request_base64'],validate=True)==req_raw and base64.b64decode(wrapper['response_base64'],validate=True)==res_raw
    actual=res['result']['value'];worked=row['expected']
    if row['method']=='getAccountInfo':
        assert type(actual['lamports']) is int and str(actual['lamports'])==worked['native_wallet_lamports']=='650240'
        assert str(Decimal(actual['lamports'])/Decimal(10**9))==worked['native_wallet_sol']=='0.00065024'
        assert actual['owner']==worked['account_owner'] and actual['executable']==worked['executable'] is False
    else:
        assert len(actual)==worked['account_count'] and req['params'][1]['programId']==worked['token_program']
        totals={}
        for raw_account,account in zip(actual,worked['accounts']):
            info=raw_account['account']['data']['parsed']['info'];amount=info['tokenAmount']
            assert raw_account['pubkey']==account['account'] and raw_account['account']['owner']==account['token_program']
            assert info['owner']==account['owner'] and info['mint']==account['mint']
            assert amount['amount']==account['quantity_raw'] and amount['decimals']==account['decimals']
            assert str(raw_account['account']['lamports'])==account['account_lamports']
            assert info['isNative']==account['is_native'] is False and info['state']==account['state']
            totals[info['mint']]=str(int(totals.get(info['mint'],'0'))+int(amount['amount']))
        assert totals==worked['mint_quantity_totals_raw']
    source_rows.append({'request':descriptor(req_path),'response_compressed':descriptor(res_path),'original_response':identity(res_raw),'context_slot':row['context_slot'],'wrapper_hash':row['wrapper_hash']})
assert [r['context_slot'] for r in source_rows]==[453173211,453173213,453173215]
assert expected['independently_worked_aggregate']['same_slot'] is False
assert expected['unsupported_conclusions']['PRODUCT_READY'] is False and expected['unsupported_conclusions']['B3_acceptance'] is False
curated_report={'kind':'independent-curated-input-and-expectation-review','state':'PASS','application_commit':HEAD,'source_sha256':SOURCE,
 'curated_input':descriptor(input_path),'raw_original_binding':descriptor(binding_path),'worked_expectations':descriptor(expected_path),
 'curation_index':descriptor(curation_path),'all_original_curated_alias_bytes_identical':True,'ZIP_original_member_bindings_verified':104,
 'selected_indexed_records_preserved':87,'original_indexed_request_response_bytes_preserved':True,'original_input_unchanged':True,
 'actual_original_inventory_components':source_rows,'independent_integer_quantity_checks':'PASS','same_slot_inventory':'UNKNOWN',
 'report_boundaries':'UNKNOWN','B3':'COMPLETE_GENUINE_ACCEPTANCE_BLOCKED','PRODUCT_READY':False,
 'network_requests':0,'provider_requests':0,'credential_lookups':0,'no_application_parser_for_worked_integer_expectations':True}
curated_report_path=OUT/'CURATED_INPUT_REVIEW.json';curated_report_path.write_bytes(enc(curated_report))
check_source()
first_path=OUT/'CONSOLIDATED_FROZEN_SOURCE_REVIEW.json';first_raw=first_path.read_bytes()
assert identity(first_raw)['sha256']=='b1665e7cca4d678cf8dc19c1b3b336133154fcb3c095dbbb90f5f9a1142f9ddc'
# Establish local evidence descriptor bytes before producing the new receipt.
DEST.mkdir(parents=True,exist_ok=True)
for src in (first_path,matrix_report_path,raw_log,curated_report_path):
    dst=DEST/src.name
    if dst.exists():assert dst.read_bytes()==src.read_bytes()
    else:dst.write_bytes(src.read_bytes())
review_evidence=[{'path':str(p.relative_to(ROOT)),**identity(p.read_bytes())} for p in
                 (DEST/first_path.name,DEST/matrix_report_path.name,DEST/raw_log.name,
                  DEST/curated_report_path.name,curation_path)]
final=deepcopy(json.loads(first_raw));final.update(matrix_review_complete=True,
    matrix_review={'requirements':54,'schema_examples':38,'required_items':92,'matrix':descriptor(matrix_path),'schema':descriptor(schema_path),
                  'review':descriptor(matrix_report_path),'read_only_collection_only':True,'test_bodies_executed':0},
    curated_input_review=descriptor(curated_report_path),supersedes_in_producer_contract=descriptor(first_path),review_evidence=review_evidence)
final['evidence'] += [descriptor(matrix_report_path),descriptor(raw_log),descriptor(curated_report_path)]
final_path=OUT/'CONSOLIDATED_FROZEN_FINAL_REVIEW.json';final_path.write_bytes(enc(final))

# Root explicitly authorized copying exact independent evidence into this new
# prefix. Preserve every producer byte; the index supplies relocation aliases.
DEST.mkdir(parents=True,exist_ok=True)
copies=[]
for name in ('review_frozen_candidate.py','review_matrix_and_curation.py','FROZEN_SOURCE_DIFF.patch',
             'FROZEN_GENUINE_COMPONENT_REPLAY.json','CONSOLIDATED_FROZEN_FINAL_REVIEW.json','FROZEN_MATRIX_REVIEW.json','FROZEN_MATRIX_REVIEW_FINAL.json',
             'FROZEN_MATRIX_COLLECT_ONLY.log','CURATED_INPUT_REVIEW.json','WORKER_CONTEXT_LIFECYCLE_PROBE.json'):
    src=OUT/name;dst=DEST/name;raw=src.read_bytes()
    if dst.exists():assert dst.read_bytes()==raw
    else:dst.write_bytes(raw)
    copies.append({'original_path':str(src),'curated_path':str(dst.relative_to(ROOT)),**identity(raw)})
src=OUT/'frozen-public-worker-rejection/raw.log';dst=DEST/'FROZEN_WORKER_CLI_REJECTION.log';raw=src.read_bytes()
if dst.exists():assert dst.read_bytes()==raw
else:dst.write_bytes(raw)
copies.append({'original_path':str(src),'curated_path':str(dst.relative_to(ROOT)),**identity(raw)})
for dst in DEST.iterdir():
    src=OUT/dst.name
    if dst.is_file() and src.is_file() and str(dst.relative_to(ROOT)) not in {r['curated_path'] for r in copies}:
        assert dst.read_bytes()==src.read_bytes()
        copies.append({'original_path':str(src),'curated_path':str(dst.relative_to(ROOT)),**identity(dst.read_bytes())})
index={'kind':'independent-review-relocation-index','state':'PASS','application_commit':HEAD,'source_sha256':SOURCE,
 'producer_receipts_rewritten':False,'files':copies,'retained_repository_dependencies':[str(matrix_path.relative_to(ROOT)),str(schema_path.relative_to(ROOT)),
 'evidence/genuine-report-speed-batch/SOURCE_MANIFEST.json','evidence/genuine-report-speed-batch/FROZEN_CANDIDATE.json',
 'evidence/genuine-report-speed-batch/checker-inputs/genuine87-inventory-input.zip','evidence/genuine-report-speed-batch/checker-inputs/INPUT_BINDING.json',
 'evidence/genuine-report-speed-batch/checker-inputs/INVENTORY_EXPECTATIONS.json'],
 'original_absolute_paths_preserved':True,'runtime_databases_or_credentials_copied':False,'Git_staging_performed':False,
 'scope':'Exact review bytes relocated only. Prior failed draft probes and current fixed controls remain separately identified; collection mapping does not count as completed tests.'}
index_path=DEST/'RELOCATION_INDEX.json';index_path.write_bytes(enc(index))
assert first_path.read_bytes()==first_raw;check_source()
print(json.dumps({'state':'PASS','final_review':descriptor(final_path),'matrix_review':descriptor(matrix_report_path),
 'curated_review':descriptor(curated_report_path),'relocation_index':descriptor(index_path),'collected_nodes':len(node_set),'matrix_items':92}))
