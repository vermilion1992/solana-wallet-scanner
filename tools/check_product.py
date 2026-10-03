#!/usr/bin/env python3
"""Execute offline archive accounting through the app; real Gate B stays separate."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from scanner.archive_input import pack_bytes
import scanner.app as application
from tools.archive_input import pack_cache


def run(output, corpus, *, require_real=False):
    output.mkdir(parents=True,exist_ok=False)
    result={'kind':'offline-product-check','development':{'state':'INCOMPLETE'},
            'real_acceptance':{'state':'BLOCKED','reason':'No independently supported genuine complete-wallet population/basis/classification/valuation corpus is present.'},
            'cases':[],'provider_requests':0,'credential_lookups':0}
    def save(): (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    save()
    def denied_request(*args,**kwargs):
        result['provider_requests']+=1
        raise AssertionError('Offline product check attempted a provider dispatch')
    def denied_credentials(*args,**kwargs):
        result['credential_lookups']+=1
        raise AssertionError('Offline product check attempted credential lookup')
    fixture=json.loads((ROOT/'scanner/examples/archive-wallet-synthetic.json').read_text())
    import httpx
    with patch.object(application,'Credentials',lambda _:SimpleNamespace(key=None,storage='none',backend=None)), \
         patch.dict(sys.modules, {'keyring': SimpleNamespace(get_keyring=lambda:object(),get_password=denied_credentials,set_password=denied_credentials)}), \
         patch.object(httpx.AsyncClient,'request',denied_request):
        app=application.create_app(output/'data','isolated-product-check-session')
        with TestClient(app,base_url='http://127.0.0.1:8765') as client:
            try:
                assert client.get('/api/state').status_code==401
                csrf=client.get('/api/bootstrap',headers={'X-Launch-Token':'isolated-product-check-session'}).json()['csrf']
                client.headers['X-CSRF-Token']=csrf
                usage=client.get('/api/state').json()['usage']
                def import_case(content):
                    response=client.post('/api/archives/import',content=content,headers={'Content-Type':'application/zip'})
                    assert response.status_code==200,response.text
                    return client.get('/api/reports/'+response.json()['report_id']).json()
                parent=import_case(pack_bytes(fixture));pid=parent['id']
                original=client.get(f'/api/export/reports/{pid}.json').content
                expected={'profit_sol':'0.49995','economic_pnl_sol':'0.499955','completed_positions':'5',
                          'median_roi_pct':'0','win_rate_pct':'40','positive_weeks':'2','observed_network_fees_sol':'0.000055'}
                assert {k:parent['metrics'][k]['value'] for k in expected}==expected
                assert parent['source']=='demo' and parent['qualification']['qualified'] is False
                (output/'synthetic-parent.json').write_bytes(original)
                assert client.get('/api/evidence/'+parent['archive_input_hash']).json()==fixture['manifest']
                result['cases'].append({'case':'synthetic-positive-normal-report','state':'PASS','expected':expected,'report_id':pid})
                for role in ('valuation_hash','world_hash'):
                    digest=fixture['manifest'][role];path=app.state.store.path/'evidence'/f'{digest}.json.gz';raw=path.read_bytes()
                    try:
                        path.unlink()
                        response=client.post(f'/api/reports/{pid}/rebuild');assert response.status_code==200,response.text
                        child=client.get('/api/reports/'+response.json()['report_id']).json()
                        metric='economic_pnl_sol' if role=='valuation_hash' else 'profit_sol'
                        assert child['metrics'][metric]['status']=='unknown'
                        assert child['metrics']['observed_network_fees_sol']['value']=='0.000055'
                        if role=='valuation_hash':assert child['metrics']['profit_sol']['value']=='0.49995'
                        assert child['archive_input_hash']==parent['archive_input_hash'] and child['preset']==parent['preset'] and child['window']==parent['window']
                        (output/(role+'-missing-child.json')).write_text(json.dumps(child,indent=2)+'\n')
                    finally:path.write_bytes(raw)
                    response=client.post(f'/api/reports/{pid}/rebuild');assert response.status_code==200,response.text
                    child=client.get('/api/reports/'+response.json()['report_id']).json()
                    assert child['metrics']==parent['metrics']
                    assert client.get(f'/api/export/reports/{pid}.json').content==original
                    result['cases'].append({'case':role+'-loss-and-exact-restoration','state':'PASS','parent_unchanged':True})
                csv=client.get(f'/api/export/reports/{pid}.csv');assert csv.status_code==200 and '0.49995' in csv.text
                (output/'synthetic-export.csv').write_bytes(csv.content)
                if (corpus/'manifest.json.gz').is_file():
                    zip_path=output/'partial-real-input.zip';pack_cache(corpus,zip_path)
                    real=import_case(zip_path.read_bytes())
                    original_manifest=json.loads(gzip.decompress((corpus/'manifest.json.gz').read_bytes()))
                    frozen=json.loads(gzip.decompress((corpus/'archives'/f"{original_manifest['report']['collection_input_hash']}.json.gz").read_bytes()))
                    fees=0
                    from scanner.accounting import utc
                    for record in frozen['transactions']:
                        raw=json.loads(gzip.decompress((corpus/'archives'/f"{record['evidence_hash']}.json.gz").read_bytes()))
                        raw=raw.get('result',raw);keys=raw['transaction']['message']['accountKeys']
                        payer=keys[0].get('pubkey') if isinstance(keys[0],dict) else keys[0]
                        if payer==real['address'] and utc(real['window']['start'])<=utc(raw['blockTime'])<utc(real['window']['end']):fees+=raw['meta']['fee']
                    from decimal import Decimal
                    expected_fee=format(Decimal(fees)/Decimal(10**9),'f')
                    assert expected_fee=='0.000240394'
                    assert real['metrics']['observed_network_fees_sol']['value']==expected_fee
                    assert real['metrics']['profit_sol']['status']=='unknown' and real['qualification']['qualified'] is False
                    assert real['archive_accounting']['real_acceptance']=='BLOCKED'
                    (output/'partial-real-report.json').write_text(json.dumps(real,indent=2)+'\n')
                    result['cases'].append({'case':'genuine-selected-23-records','state':'PASS','scope':'Partial sample only; no B3 proof',
                                            'expected_fee_sol':expected_fee,'oracle':'Direct integer payer-matched meta.fee addition without production metric functions'})
                else:
                    result['cases'].append({'case':'genuine-partial-input','state':'BLOCKED','reason':'Authorised portable partial corpus absent.'})
                assert client.get('/api/state').json()['usage']==usage
                assert not app.state.store.list('collector_checkpoints')
                result['development']={'state':'PASS','scope':'Executed normal offline app workflow with synthetic development and separately labelled partial real input'}
                result.update(parent_unchanged=True,usage_before=usage,usage_after=usage,collector_ancestry_created=False)
            except Exception as exc:
                result['development']={'state':'FAILED','reason':type(exc).__name__+': '+str(exc)}
                result['state']='FAILED';save();raise
    result['state']='BLOCKED' if require_real else 'DEVELOPMENT_PASS'
    result['real_acceptance_required']=require_real
    result['artifacts']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file() and p.name!='result.json'}
    save();print(json.dumps({k:result[k] for k in ('state','development','real_acceptance','provider_requests','credential_lookups')}))
    return 2 if require_real else 0


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--real-corpus',type=Path,default=ROOT/'evidence/runs/real-cache');p.add_argument('--require-real-acceptance',action='store_true')
    a=p.parse_args();raise SystemExit(run(a.output.absolute(),a.real_corpus.absolute(),require_real=a.require_real_acceptance))
