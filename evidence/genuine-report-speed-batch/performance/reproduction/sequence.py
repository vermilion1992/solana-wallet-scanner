from pathlib import Path
import hashlib,json,subprocess,sys,time
root=Path('/workspace/solana-wallet-scanner');sys.path.insert(0,str(root))
from tools.validate import source_manifest
base=Path('/workspace/outputs/report-proof-profile');output=base/'candidate-eea37dc';output.mkdir(exist_ok=False)
expected={'commit':'eea37dc95b5a012a62d36f4b300f1097fc311f87','source_sha256':'c6476e7ea65bc12e42c70488dab6b5a4b9c6170fa9a81f5f333e38546e528cd6','source_files':246}
def sha(raw):return hashlib.sha256(raw).hexdigest()
def source():
 m=source_manifest(root);return {'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'source_sha256':m['sha256'],'source_files':len(m['files'])}
def files():
 names=['evidence/source-probe-2026-10-04/live/02-all-index-request.json','evidence/source-probe-2026-10-04/live/02-all-index-response.raw.gz','evidence/source-probe-2026-10-04/live/03-all-continuation-request.json','evidence/source-probe-2026-10-04/live/03-all-continuation-response.raw.gz','requirements.txt','requirements-build.in','pyproject.toml','frontend/package-lock.json']
 return {n:sha((root/n).read_bytes()) for n in names}
assert source()==expected
original=base/'benchmark.py';adapted=base/'benchmark-eea37dc.py'
old=original.read_text();oldbinding="EXPECTED='ab62858dca7eccbdb18b3365a83dedd9b2e8f413'";newbinding="EXPECTED='"+expected['commit']+"'"
assert old.count(oldbinding)==1;new=old.replace(oldbinding,newbinding);assert new.replace(newbinding,oldbinding)==old;adapted.write_text(new)
record={'kind':'frozen-offline-performance-sequence','acceptance_run':False,'source_before':source(),'input_lock_hashes_before':files(),'original_script_sha256':sha(original.read_bytes()),'adapted_script_sha256':sha(adapted.read_bytes()),'adaptation':'Only expected HEAD constant changed; original script unchanged. Same profiling/tree/normal routes as original baseline.','commands':[]}
def save():(output/'INDEX.json').write_text(json.dumps(record,indent=2)+'\n')
save()
python=str(root/'.venv/bin/python');cli=str(root/'tools/benchmark_report.py')
archive200=base/'baseline-ab62858/input.zip';archive87=Path('/workspace/outputs/genuine-wallet-inventory/genuine87-inventory-input.zip')
steps=[('synthetic-smoke',[python,cli,'--archive',str(base/'synthetic-benchmark-input.zip'),'--output',str(output/'synthetic-smoke'),'--full-details'],0),('genuine200-normal',[python,cli,'--archive',str(archive200),'--output',str(output/'genuine200-normal'),'--full-details'],0),('genuine200-profile-like-for-like',[python,str(adapted),'--output',str(output/'genuine200-profile-like-for-like')],0),('genuine87-augmented-normal',[python,cli,'--archive',str(archive87),'--output',str(output/'genuine87-augmented-normal'),'--full-details'],0),('watchdog-one-second',[python,cli,'--archive',str(archive200),'--output',str(output/'watchdog-one-second'),'--timeout','1'],124)]
for name,cmd,expectedexit in steps:
 assert source()==expected
 log=output/(name+'-outer.log');clock=time.perf_counter();print('START '+name,flush=True)
 with log.open('wb') as stream:
  try:
   completed=subprocess.run(cmd,cwd=root,stdout=stream,stderr=subprocess.STDOUT,timeout=300);exitcode=completed.returncode;timedout=False
  except subprocess.TimeoutExpired:exitcode=None;timedout=True
 raw=log.read_bytes();row={'name':name,'command':cmd,'seconds':time.perf_counter()-clock,'exit_code':exitcode,'expected_exit_code':expectedexit,'outer_timed_out':timedout,'timeout_seconds':300,'log':str(log),'log_bytes':len(raw),'log_sha256':sha(raw)}
 receipt=output/name/('result.json' if name.endswith('like-for-like') else 'observations.json')
 row['receipt']=str(receipt)
 if receipt.exists():row['receipt_sha256']=sha(receipt.read_bytes());row['state']=json.loads(receipt.read_text())['state']
 row['source_after']=source();record['commands'].append(row);save();print('END '+name+' '+str(exitcode)+' '+str(round(row['seconds'],3)),flush=True)
 assert exitcode==expectedexit and not timedout,(name,row,raw.decode()[-3000:])
 assert row['source_after']==expected
record['source_after']=source();record['input_lock_hashes_after']=files();assert record['input_lock_hashes_after']==record['input_lock_hashes_before']
assert sha(original.read_bytes())==record['original_script_sha256']
record['state']='OBSERVED_ALL_REQUESTED_OPERATIONS';save();print('FINAL '+record['state'],flush=True)
