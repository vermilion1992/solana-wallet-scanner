#!/usr/bin/env python3
"""Resolve the declared acceptance coverage to actual pytest node IDs."""
import argparse,json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=subprocess.run([sys.executable,'-m','pytest','--collect-only','-q'],cwd=ROOT,capture_output=True,text=True)
    nodes=[line for line in result.stdout.splitlines() if line.startswith('tests/') and '::' in line]
    spec=json.loads((ROOT/'docs/ACCEPTANCE_MATRIX.json').read_text());rows=[]
    for item in spec['requirements']:
        matches={selector:sorted(n for n in nodes if re.fullmatch(''.join('.*' if c=='*' else '.' if c=='?' else re.escape(c) for c in selector),n)) for selector in item['selectors']}
        rows.append({'id':item['id'],'axis':item['axis'],'state':'PASS' if all(matches.values()) else 'INCOMPLETE','nodes':matches})
    examples=json.loads((ROOT/'tests/fixtures/instruction_family_schema.json').read_text())['examples']
    for example in examples:
        n='tests/test_instruction_contract_matrix.py::test_every_primary_schema_contract_has_the_required_reference_paths['+example['id']+']'
        rows.append({'id':'schema-'+example['id'],'axis':'Representation','state':'PASS' if n in nodes else 'INCOMPLETE','nodes':[n]})
    report={'state':'PASS' if result.returncode==0 and all(r['state']=='PASS' for r in rows) else 'INCOMPLETE','collected_unique_nodes':len(set(nodes)),'required_items':len(rows),'requirements':rows,'purpose':'Coverage mapping, not a second test execution or proof of arbitrary combinations.'}
    a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='requirements'}))
    return 0 if report['state']=='PASS' else 2
if __name__=='__main__':raise SystemExit(main())
