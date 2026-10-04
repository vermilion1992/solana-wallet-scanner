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
OUT=Path('/workspace/outputs/genuine-wallet-report-correction-review')
DEST=ROOT/'evidence/genuine-report-speed-batch-final/integrated-review'
HEAD='0db4125e8c1ab6b2df5bb1e79e807c80e3d195bd'
SOURCE='babd86cab36e5674d286b8b59f4692e8f2f0109e0c2375a36ab7a86ad1185b3c'
BASE='ab62858dca7eccbdb18b3365a83dedd9b2e8f413'
def identity(raw):return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def enc(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def descriptor(path):return {'path':str(path),**identity(path.read_bytes())}
def git(*args):return subprocess.check_output(['git','--no-optional-locks',*args],cwd=ROOT)
def check_source():
    manifest=json.loads((ROOT/'evidence/genuine-report-speed-batch-final/SOURCE_MANIFEST.json').read_bytes())
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


assert check_source()==manifest
print(json.dumps({'state':matrix_report['state'],'collected_unique_nodes':len(node_set),'focused_unique_nodes':sum(map(len,group_nodes.values())),'requirements_reviewed':54,'schema_examples_reviewed':38,'required_items':92,'selectors':41,'report':descriptor(matrix_report_path)}))
