"""Synthetic CLI dispatch probe; application worker is replaced, not executed."""
from pathlib import Path
import hashlib,json,sys,tempfile
import tools.benchmark_report as benchmark
out=Path('/workspace/outputs/genuine-wallet-report-review')
fixture=Path(tempfile.mkdtemp(prefix='worker-context-control-',dir=out));archive=fixture/'input.zip';runtime=fixture/'existing-output';runtime.mkdir();archive.write_bytes(b'not-executed')
context={'version':'offline-benchmark-worker-v1','archive':str(archive),'timeout':300,'profile':False,'full_details':False}
(runtime/'worker-context.json').write_text(json.dumps(context))
(runtime/'previous-run-marker.txt').write_text('An existing output already has unrelated content.\n')
called=[]
benchmark.worker=lambda args:called.append(str(args.output)) or 0
sys.argv=['benchmark_report.py','--worker','--archive',str(archive),'--output',str(runtime)]
code=benchmark.main()
obj={'kind':'independent-synthetic-benchmark-internal-worker-dispatch-probe','draft_tool_sha256':hashlib.sha256(Path(benchmark.__file__).read_bytes()).hexdigest(),'fixture':str(fixture),'manually_constructed_matching_context_accepted':code==0 and bool(called),'existing_output_accepted':(runtime/'previous-run-marker.txt').is_file(),'synthetic_worker_dispatched':bool(called),'actual_application_worker_executed':False,'provider_requests':0,'credential_lookups':0,'network_requests':0,'source_or_Git_mutations':False}
p=out/'WORKER_CONTEXT_LIFECYCLE_PROBE.json';p.write_text(json.dumps(obj,indent=2)+'\n');print(json.dumps({'manual_context_accepted':obj['manually_constructed_matching_context_accepted'],'existing_output_accepted':obj['existing_output_accepted'],'actual_worker_executed':False,'report':str(p)}))
