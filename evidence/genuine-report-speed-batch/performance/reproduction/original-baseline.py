#!/usr/bin/env python3
"""Read-only, bounded exact-candidate offline proof-size/timing benchmark.
Never changes application source, raw corpus, parent report, or public semantics.
Experimental pooling is measurement-only and never enters application storage.
"""
from __future__ import annotations
import argparse, base64, collections, cProfile, csv, gc, gzip, hashlib, io, json, os
from pathlib import Path
import pstats, resource, signal, socket, subprocess, sys, time, traceback
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path('/workspace/solana-wallet-scanner')
sys.path.insert(0,str(ROOT))
from tools.validate import source_manifest
from tests.test_indexed_input import WALLET,WINDOW,PROBE,upload
from scanner.indexed_input import source_bytes
from tools.check_genuine_collection import freeze_expectations

EXPECTED='ab62858dca7eccbdb18b3365a83dedd9b2e8f413'
def sha(raw): return hashlib.sha256(raw).hexdigest()
def git(): return subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
def bind():
    manifest=source_manifest(ROOT)
    return {'commit':git(),'source_sha256':manifest['sha256'],'source_files':len(manifest['files'])}
def inputs():
    result={}
    for stem in ('02-all-index','03-all-continuation'):
        for suffix in ('-request.json','-response.raw.gz'):
            path=PROBE/(stem+suffix); raw=path.read_bytes()
            result[str(path.relative_to(ROOT))]={'bytes':len(raw),'sha256':sha(raw)}
    return result

def compact(raw): return json.dumps(raw,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
def streamed_identity(value):
    h=hashlib.sha256(); n=0
    for chunk in json.JSONEncoder(ensure_ascii=False,allow_nan=False,separators=(',',':')).iterencode(value):
        raw=chunk.encode();h.update(raw);n+=len(raw)
    return {'bytes':n,'sha256':h.hexdigest()}

def profile_tree(value):
    """Linear bottom-up size/content registry. Paths sampled, no quadratic dumps."""
    containers={}; strings={}; paths={}; scalar_cache={}; nodes=collections.Counter()
    def scalar(item):
        key=(type(item).__name__,item)
        row=scalar_cache.get(key)
        if row is None:
            raw=compact(item);row=(sha(b'S'+raw),len(raw));scalar_cache[key]=row
        return row
    def walk(item,path):
        if not isinstance(item,(dict,list)):
            digest,n=scalar(item);nodes[type(item).__name__]+=1
            if isinstance(item,str):
                row=strings.setdefault(digest,{'characters':len(item),'encoded_bytes':n,'count':0,'paths':[]})
                row['count']+=1
                if len(row['paths'])<6:row['paths'].append(path)
            return digest,n,item
        nodes[type(item).__name__]+=1
        entries=list(item.items()) if isinstance(item,dict) else list(enumerate(item))
        size=2+max(0,len(entries)-1); structure=[]; pooled=[]
        for key,child in entries:
            childhash,childsize,packed=walk(child,path+'.'+str(key))
            if isinstance(item,dict):
                keyraw=compact(key);size+=len(keyraw)+1;structure.append([key,childhash]);pooled.append([key,packed])
            else: structure.append(childhash);pooled.append(packed)
            size+=childsize
        kind='dict' if isinstance(item,dict) else 'list'
        digest=sha(compact([kind,structure]))
        row=containers.setdefault(digest,{'kind':kind,'compact_bytes':size,'count':0,'paths':[],
            'node':{'kind':kind,'entries':pooled}})
        row['count']+=1
        if len(row['paths'])<8:row['paths'].append(path)
        if path.count('.')<=4 or size>1000000 and path.count('.')<=8:paths[path]=size
        return digest,size,{'ref':digest}
    started=time.perf_counter();digest,size,_=walk(value,'$')
    graph={'version':'measurement-only-order-preserving-pool-v1','root':digest,
           'nodes':{key:row['node'] for key,row in containers.items()}}
    graph_id=streamed_identity(graph)
    duplicate=sorted(({'hash':h,**{k:v for k,v in row.items() if k!='node'},
        'overlap_warning':'Nested duplicate sizes overlap; do not sum.'} for h,row in containers.items() if row['count']>1),
        key=lambda row:row['compact_bytes']*(row['count']-1),reverse=True)[:40]
    stringrows=sorted(strings.values(),key=lambda row:row['encoded_bytes']*row['count'],reverse=True)[:25]
    return {'algorithm':'Order-sensitive structural digest; exact compact UTF-8 length; scalar/string and container counts are separate.',
        'seconds':time.perf_counter()-started,'compact_bytes':size,'measurement_pool':graph_id,
        'container_occurrences':sum(nodes[k] for k in ('dict','list')),'unique_container_values':len(containers),
        'value_occurrences':dict(nodes),'path_compact_bytes':dict(sorted(paths.items(),key=lambda row:row[1],reverse=True)),
        'largest_repeated_subtrees':duplicate,'largest_string_contributions':stringrows}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter();calls={'provider':0,'credential':0,'transport':0,'socket':0}
    result={'kind':'read-only-offline-genuine200-performance-baseline','state':'INCOMPLETE','PRODUCT_READY':False,
        'timeout_seconds':300,'python':sys.version,'executable':sys.executable,'source_before':bind(),
        'inputs_before':inputs(),'operations':[],'calls':calls,'source_changed':None}
    assert result['source_before']['commit']==EXPECTED
    def save(): (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    def denied(name):
        def fail(*a,**k):calls[name]+=1;raise AssertionError('Blocked offline '+name+' attempt')
        return fail
    def phase(name, fn, *, profile=False):
        print('START '+name,flush=True);clock=time.perf_counter();prof=cProfile.Profile() if profile else None
        if prof:prof.enable()
        try: value=fn()
        finally:
            if prof:
                prof.disable();prof.dump_stats(str(output/(name+'.profile')))
                with (output/(name+'-profile.txt')).open('w') as stream:
                    pstats.Stats(prof,stream=stream).sort_stats('cumulative').print_stats(45)
        seconds=time.perf_counter()-clock
        result['operations'].append({'name':name,'seconds':seconds});save();print('END '+name+' '+str(round(seconds,3)),flush=True)
        return value
    def timeout(_s,_f):raise TimeoutError('Bounded 300s offline benchmark expired')
    signal.signal(signal.SIGALRM,timeout);signal.alarm(300)
    save()
    try:
        pages=[((PROBE/(stem+'-request.json')).read_bytes(),gzip.decompress((PROBE/(stem+'-response.raw.gz')).read_bytes()))
               for stem in ('02-all-index','03-all-continuation')]
        rawrecords=[raw for _,body in pages for raw in json.loads(body)['result']['data']]
        assert len(rawrecords)==200 and len({r['transaction']['signatures'][0] for r in rawrecords})==200
        assert sum(r['meta']['err'] is not None for r in rawrecords)==184
        direct_fee=sum(r['meta']['fee'] for r in rawrecords if r['transaction']['message']['accountKeys'][0]==WALLET)
        assert direct_fee==8904733
        manifest,rawinputs,content=upload(pages);input_sha=sha(content)
        (output/'input.zip').write_bytes(content)
        oracle=freeze_expectations(content)
        assert oracle['observed_network_fees_sol']['value']=='0.008904733'
        (output/'EXPECTED_RAW.json').write_text(json.dumps(oracle,indent=2)+'\n')
        result['oracle']={'frozen_before_application':True,'records':200,'failed_records':184,
            'wallet_paid_fee_lamports':direct_fee,'wallet_paid_fee_sol':'0.008904733',
            'archive_bytes':len(content),'archive_sha256':input_sha,'window':WINDOW,'wallet':WALLET}
        import httpx
        from fastapi.testclient import TestClient
        import scanner.app as application
        from scanner.providers import Gateway
        original_send=httpx.Client.send
        def local_send(client,*a,**k):
            return original_send(client,*a,**k) if isinstance(client,TestClient) else denied('transport')(client,*a,**k)
        env=dict(os.environ);env.pop('HELIUS_API_KEY',None)
        with patch.object(application,'Credentials',lambda _:SimpleNamespace(key=None,storage='none',backend=None)), \
             patch.object(Gateway,'rpc',denied('provider')), \
             patch.object(httpx.AsyncClient,'request',denied('transport')), \
             patch.object(httpx.AsyncClient,'send',denied('transport')), \
             patch.object(httpx.AsyncHTTPTransport,'handle_async_request',denied('transport')), \
             patch.object(httpx.Client,'send',local_send), \
             patch.object(socket,'create_connection',denied('socket')), \
             patch.dict(os.environ,env,clear=True), \
             patch.dict(sys.modules,{'keyring':SimpleNamespace(get_keyring=denied('credential'),get_password=denied('credential'),set_password=denied('credential'))}):
            app=application.create_app(output/'private-runtime','offline-performance-baseline')
            with TestClient(app,base_url='http://127.0.0.1:8765') as client:
                assert client.get('/api/state').status_code==401
                token=client.get('/api/bootstrap',headers={'X-Launch-Token':'offline-performance-baseline'}).json()['csrf']
                client.headers['X-CSRF-Token']=token;usage=client.get('/api/usage').json()
                response=phase('archive-import',lambda:client.post('/api/archives/import',content=content,headers={'Content-Type':'application/zip'}),profile=True)
                assert response.status_code==200,response.text[:2000]
                identifier=response.json()['report_id'];del response
                response=phase('default-full-get',lambda:client.get('/api/reports/'+identifier))
                assert response.status_code==200
                result['full_response']={'bytes':len(response.content),'sha256':sha(response.content),
                    'gzip_level1_bytes':len(gzip.compress(response.content,compresslevel=1,mtime=0))}
                parent=phase('full-response-json-parse',response.json);del response;gc.collect()
                assert parent['metrics']['observed_network_fees_sol']['value']=='0.008904733'
                assert parent['metrics']['profit_sol']['status']=='unknown' and parent['qualification']['qualified'] is False
                assert parent['coverage']['indexed_sources']['historical_population']=='UNKNOWN'
                assert len([e for e in parent['events'] if e['kind']=='fee'])==200
                metrics=parent['metrics'];parent_semantics=streamed_identity(parent)
                result['parent_semantic_identity']=parent_semantics
                result['tree_profile']=phase('derived-proof-tree-profile',lambda:profile_tree(parent))
                row=app.state.store.db.execute("SELECT payload FROM records WHERE kind='reports' AND id=?",(identifier,)).fetchone()[0]
                saved_sha=sha(row.encode());result['saved_report_json']={'bytes':len(row.encode()),'sha256':saved_sha};del row
                original_manifest=app.state.store.evidence(parent['archive_input_hash'])
                pagehashes=[r['hash'] for r in original_manifest['evidence'] if r['kind']=='indexed-page']
                inspected=[]
                for h in pagehashes:
                    response=phase('source-inspection-'+h[:8],lambda h=h:client.get('/api/evidence/'+h))
                    assert response.status_code==200
                    recovered=source_bytes(response.json());assert (recovered['request'],recovered['response']) in pages
                    inspected.append({'hash':h,'request_sha256':sha(recovered['request']),'response_sha256':sha(recovered['response'])})
                    del response,recovered
                result['inspected_original_bytes']=inspected
                response=phase('json-export',lambda:client.get('/api/export/reports/'+identifier+'.json'))
                assert response.status_code==200
                result['json_export']={'bytes':len(response.content),'sha256':sha(response.content)}
                exported=phase('json-export-parse',response.json);del response
                assert exported==parent;del exported;gc.collect()
                response=phase('csv-export',lambda:client.get('/api/export/reports/'+identifier+'.csv'))
                assert response.status_code==200
                rows={r['metric']:r for r in csv.DictReader(io.StringIO(response.text))}
                assert rows['observed_network_fees_sol']['value']=='0.008904733' and rows['profit_sol']['status']=='unknown'
                result['csv_export']={'bytes':len(response.content),'sha256':sha(response.content)};del response
                display=phase('display-get',lambda:client.get('/api/reports/'+identifier+'?view=display'))
                assert display.status_code==200;result['display_response_bytes']=len(display.content);del display
                summary=phase('state-summary',lambda:client.get('/api/state?report_view=summary'))
                assert summary.status_code==200;result['summary_response_bytes']=len(summary.content);del summary
                del parent;gc.collect()
                response=phase('same-input-rebuild',lambda:client.post('/api/reports/'+identifier+'/rebuild'),profile=True)
                assert response.status_code==200,response.text[:2000]
                childid=response.json()['report_id'];del response
                response=phase('rebuilt-full-get',lambda:client.get('/api/reports/'+childid))
                assert response.status_code==200;child=response.json();del response
                assert child['rebuilt_from']==identifier and child['metrics']==metrics
                assert child['window']==WINDOW and child['qualification']['qualified'] is False
                assert child['rebuild']['provider_requests']==0
                result['child_result']={'report_id':childid,'fee':child['metrics']['observed_network_fees_sol']['value'],'real_acceptance':'BLOCKED'}
                del child;gc.collect()
                afterrow=app.state.store.db.execute("SELECT payload FROM records WHERE kind='reports' AND id=?",(identifier,)).fetchone()[0]
                assert sha(afterrow.encode())==saved_sha;del afterrow
                assert client.get('/api/usage').json()==usage
                assert not app.state.store.list('collector_checkpoints')
                assert calls=={'provider':0,'credential':0,'transport':0,'socket':0}
                result['invariants']={'parent_bytes_unchanged':True,'provider_calls_zero':True,'credential_lookups_zero':True,
                    'transport_attempts_zero':True,'socket_attempts_zero':True,'usage_unchanged':True,
                    'original_page_bytes_recovered':True,'export_exact_full_semantics':True,'rebuilt_metrics_exact':True,
                    'no_collector_ancestry':True,'profit_unknown':True,'wallet_qualified':False}
        assert sha(content)==input_sha
        result['source_after']=bind();result['inputs_after']=inputs()
        result['source_changed']=result['source_before']!=result['source_after']
        assert not result['source_changed'] and result['inputs_after']==result['inputs_before']
        result['state']='BASELINE_PASS_REAL_ACCEPTANCE_BLOCKED';return 0
    except BaseException as error:
        result['state']='FAILED';result['error']={'type':type(error).__name__,'message':str(error)}
        traceback.print_exc();return 1
    finally:
        signal.alarm(0);result['total_seconds']=time.perf_counter()-started
        result['peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        save();print('FINAL '+result['state'],flush=True)

if __name__=='__main__':raise SystemExit(main())
