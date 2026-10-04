#!/usr/bin/env python3
"""Read-only encoding/storage experiment over an existing exact baseline row."""
import argparse,cProfile,gc,gzip,hashlib,json,pstats,resource,signal,sqlite3,time
from pathlib import Path
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from scanner.report_view import display_view

def sha(raw):return hashlib.sha256(raw).hexdigest()
parser=argparse.ArgumentParser();parser.add_argument('--baseline',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
baseline=json.loads((args.baseline/'result.json').read_text());assert baseline['state']=='BASELINE_PASS_REAL_ACCEPTANCE_BLOCKED'
result={'kind':'read-only-expanded-report-encoding-experiment','source_binding':baseline['source_before'],'state':'INCOMPLETE','operations':[],
        'schema_change':False,'application_source_changed':False,'new_acceptance_claim':False}
clock=time.perf_counter();signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(TimeoutError('180s encoding limit')));signal.alarm(180)
def save():(args.output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
def run(name,fn):
    print('START '+name,flush=True);start=time.perf_counter();value=fn();elapsed=time.perf_counter()-start
    result['operations'].append({'name':name,'seconds':elapsed});save();print('END '+name+' '+str(round(elapsed,3)),flush=True);return value
try:
    connection=sqlite3.connect('file:'+str(args.baseline/'private-runtime/scanner.sqlite')+'?mode=ro',uri=True)
    raw=run('sqlite-existing-parent-read',lambda:connection.execute("SELECT payload FROM records WHERE kind='reports' AND json_extract(payload,'$.rebuilt_from') IS NULL").fetchone()[0].encode())
    assert sha(raw)==baseline['full_response']['sha256'];result['original_body']={'bytes':len(raw),'sha256':sha(raw)}
    report=run('existing-parent-json-parse',lambda:json.loads(raw))
    direct=run('direct-json-response',lambda:JSONResponse(report).body)
    assert direct==raw;result['direct_body']={'bytes':len(direct),'sha256':sha(direct),'exact_default_full_body':True};del direct;gc.collect()
    encoded=run('jsonable-encoder-alone',lambda:jsonable_encoder(report))
    direct=run('encoded-json-response',lambda:JSONResponse(encoded).body)
    assert direct==raw;result['existing_fastapi_encoder_semantics_exact']=True;del encoded,direct;gc.collect()
    display=display_view(report)
    direct=run('direct-display-json-response',lambda:JSONResponse(display).body)
    encoded=run('display-jsonable-encoder-alone',lambda:jsonable_encoder(display))
    assert JSONResponse(encoded).body==direct;result['display_body']={'bytes':len(direct),'sha256':sha(direct),'encoder_semantics_exact':True}
    del display,encoded,direct;gc.collect()
    for level in (1,6):
        packed=run('gzip-compress-level'+str(level),lambda level=level:gzip.compress(raw,compresslevel=level,mtime=0))
        unpacked=run('gzip-decompress-level'+str(level),lambda:gzip.decompress(packed))
        assert unpacked==raw
        result['gzip_level'+str(level)]={'bytes':len(packed),'sha256':sha(packed),'exact_roundtrip':True}
        del packed,unpacked;gc.collect()
    result['state']='EXACT_ENCODING_EQUIVALENCE_PASS';print(result['state'],flush=True)
finally:
    signal.alarm(0);result['total_seconds']=time.perf_counter()-clock;result['peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;save()
