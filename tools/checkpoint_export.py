#!/usr/bin/env python3
"""Export one portable candidate with actual receipts/logs; exclude QA databases."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.validate import source_manifest


def export(output, gates, blueprint=None):
    outcome=json.loads(gates.read_text());snapshot=source_manifest()
    if outcome['source']['sha256']!=snapshot['sha256']:
        raise ValueError('Checkpoint evidence does not bind the current complete software manifest')
    if outcome['gate_A']['state']!='ACCEPTED_IN_SCOPE':
        raise ValueError('Cannot export this accepted checkpoint with an unclosed scoped gate')
    files={name:ROOT/name for name in snapshot['files']}
    # Tracked original/reference records, plus actual archived raw input bytes.
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    for name in tracked:
        if name.startswith('evidence/') and (ROOT/name).is_file():files[name]=ROOT/name
    for directory in (ROOT/'evidence/references', ROOT/'evidence/runs', ROOT/'evidence/product-milestone'):
        for path in directory.rglob('*'):
            relative=path.relative_to(ROOT)
            if (not path.is_file() or any(part in ('data','baseline','.venv','node_modules','__pycache__','.pytest_cache') for part in relative.parts)
                or path.suffix in ('.sqlite','.db','.wal','.shm') or path.name in ('.runtime.lock','.env')):
                continue
            if path.suffix in ('.json','.log','.png','.gz','.txt','.zip','.csv','.md','.patch','.py'):
                files[relative.as_posix()]=path
    # No symlink, credential/configuration export or dependency directory is copied.
    if any(path.is_symlink() for path in files.values()):raise ValueError('Symlink in checkpoint inputs')
    reference_map={};missing=[]
    def walk(value, owner):
        if isinstance(value,dict):
            for item in value.values():walk(item,owner)
        elif isinstance(value,list):
            for item in value:walk(item,owner)
        elif isinstance(value,str) and value.startswith(str(ROOT/'evidence')+'/'):
            name=Path(value).relative_to(ROOT).as_posix()
            if name in files:reference_map[value]={'path':name,'sha256':hashlib.sha256(files[name].read_bytes()).hexdigest()}
            elif Path(value).suffix in ('.log','.json','.png') and not any(p in ('data','baseline') for p in Path(name).parts):
                missing.append({'record':owner,'reference':value})
    # Validate authoritative current and historical gate/review/install receipts.
    authoritative=[gates,ROOT/'evidence/FINAL_GATES.json',ROOT/'evidence/CLEAN_INSTALL.json',ROOT/'evidence/REVIEW.json']
    authoritative += [p for p in (ROOT/'evidence/product-milestone').glob('*.json') if p.name!='SOURCE_PROBE_PLAN.json']
    for path in authoritative:walk(json.loads(path.read_text()),str(path.relative_to(ROOT)))
    if missing:raise ValueError('Missing referenced raw evidence: '+json.dumps(missing))
    for name,path in files.items():
        if name.startswith('evidence/') and path.suffix=='.json':
            try:walk(json.loads(path.read_text()),name)
            except (ValueError,UnicodeError):pass
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    with tempfile.TemporaryDirectory(prefix='scanner-checkpoint-export-') as scratch:
        bundle=Path(scratch)/'CANDIDATE.gitbundle'
        subprocess.run(['git','bundle','create',str(bundle),branch],cwd=ROOT,check=True,capture_output=True)
        files['CANDIDATE.gitbundle']=bundle
        if blueprint:files['references/original-wallet-scanner-blueprint.pdf']=blueprint
        hashes={name:{'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'bytes':path.stat().st_size,'mode':path.stat().st_mode&0o777} for name,path in sorted(files.items())}
        restore='''#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -e .git ]]; then echo "Use a fresh extracted checkpoint; .git already exists." >&2; exit 2; fi
python3 - <<'PY'
import hashlib,json
from pathlib import Path
manifest=json.loads(Path('CHECKPOINT_MANIFEST.json').read_text())
for name,row in manifest['files'].items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==row['sha256'], name
    Path(name).chmod(row['mode'])
print('All checkpoint file hashes verified')
PY
git init -q
git fetch -q ./CANDIDATE.gitbundle '''+branch+'''
git update-ref refs/heads/'''+branch+''' FETCH_HEAD
git symbolic-ref HEAD refs/heads/'''+branch+'''
git reset --mixed -q HEAD
cat >> .git/info/exclude <<'EOF'
/CANDIDATE.gitbundle
/CHECKPOINT_MANIFEST.json
/CHECKPOINT_README.txt
/EXPORT_PATHS.json
/restore-checkout.sh
/references/
EOF
echo "Candidate Git history restored. Run ./setup.sh in this fresh checkout."
'''
        notes=('Portable unreleased product checkpoint\n\n'
               'Software source manifest: '+snapshot['sha256']+'\nExport commit: '+commit+'\nBranch: '+branch+'\n\n'
               'Extract into a fresh directory, run bash restore-checkout.sh, then ./setup.sh and ./run.sh.\n'
               'The Git bundle retains the original baseline needed by browser_acceptance.py.\n'
               'All referenced raw logs/browser receipts/captures are included. EXPORT_PATHS.json maps original absolute workspace references to portable paths without altering raw receipts.\n'
               'Original FINAL_GATES is historical Gate A; evidence/product-milestone/FINAL_GATES.json is this checkpoint.\n'
               'B1 live entitlement/coverage untested; B2 executable development slice, complete real B2 OPEN; B3 BLOCKED.\n'
               'The genuine 23-record archive is an authorised partial sample, not independent complete-wallet acceptance.\n'
               'QA databases, launcher tokens, secrets, credentials, environments and node_modules are excluded. Windows/macOS checks and independent third-party review were not executed.\n')
        generated={'restore-checkout.sh':restore.encode(),'CHECKPOINT_README.txt':notes.encode(),
                   'EXPORT_PATHS.json':(json.dumps({'scope':'Portable mapping; original receipt bytes unchanged','references':reference_map},indent=2)+'\n').encode()}
        for name,raw in generated.items():hashes[name]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'mode':0o755 if name.endswith('.sh') else 0o644}
        manifest={'kind':'portable-product-checkpoint','commit':commit,'branch':branch,'software':snapshot,'files':hashes,
                  'gate_A':'ACCEPTED_IN_SCOPE','real_gate_B':'OPEN','excluded':'QA/private databases, dependencies, secrets and runtime environments'}
        output.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for name,path in sorted(files.items()):archive.write(path,name)
            for name,raw in generated.items():
                entry=zipfile.ZipInfo(name);entry.external_attr=(hashes[name]['mode']|0o100000)<<16
                archive.writestr(entry,raw)
            archive.writestr('CHECKPOINT_MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
    # Read back every delivered byte, not just the central directory arithmetic.
    with zipfile.ZipFile(output) as archive:
        assert len(archive.namelist())==len(set(archive.namelist()))
        for name,row in hashes.items():assert hashlib.sha256(archive.read(name)).hexdigest()==row['sha256'],name
    return {'state':'PASS','path':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'bytes':output.stat().st_size,'files':len(hashes)+1,'software_sha256':snapshot['sha256'],
            'all_delivered_bytes_verified':True,'raw_receipts_unchanged':True}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--gates',type=Path,default=ROOT/'evidence/product-milestone/FINAL_GATES.json');p.add_argument('--blueprint',type=Path)
    args=p.parse_args();print(json.dumps(export(args.output.absolute(),args.gates.absolute(),args.blueprint)))
