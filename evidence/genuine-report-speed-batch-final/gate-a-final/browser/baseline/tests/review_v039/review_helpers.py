"""Independent, synthetic local controls. No network, signing or mainnet claim."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
from tests import test_position_evidence as pb
from scanner.history_evidence import derive_history_evidence

@pytest.fixture
def builder():
    case = pb.PositionEvidenceTests(methodName='runTest')
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()

def history(case):
    return derive_history_evidence(case.store, pb.WALLET, pb.WINDOW, checkpoint=case.cp,
        collected={'transactions':case.records, 'checkpoint':case.cp})

def record_result(name, value):
    root = os.environ.get('REVIEW_OUTPUT')
    if root:
        path = Path(root); path.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(json.dumps(value, indent=2)+'\n')

def summarize(position, h, digest):
    account = next(row for row in position['positions'] if row['account']==pb.ACCOUNT)
    contents = h.get('source_consistency',{}).get('archive_contents',{})
    receipt = next((row for row in contents.get('receipts',[]) if row['hash']==digest), None)
    return {'known_closed':position['counts']['known_closed'],'hold':account['hold_hours'],
        'stages':account['stages'], 'sources':account['sources'], 'mutated_source_cited':digest in account['sources'],
        'source_set':h['source_consistency'].get('source_set'), 'archive_receipt':receipt,
        'native_observed':h['native_address_metrics']['observed'], 'evidence_gates':h['evidence_gates']}

def rebuild(case, tmp_path, monkeypatch, digest, label):
    import httpx
    from fastapi.testclient import TestClient
    from scanner.app import create_app
    from scanner.config import STRICT
    from scanner.report_rebuild import freeze_report_inputs
    monkeypatch.delenv('HELIUS_API_KEY', raising=False)
    calls={'provider':0,'credential':0}
    def deny_credential(*args, **kwargs):
        calls['credential']+=1
        raise AssertionError('No credentials are used by independent review')
    async def deny_provider(*args, **kwargs):
        calls['provider']+=1
        raise AssertionError('No provider calls are used by independent review')
    monkeypatch.setitem(sys.modules,'keyring',SimpleNamespace(get_keyring=lambda:object(),get_password=deny_credential))
    monkeypatch.setattr(httpx.AsyncClient,'request',deny_provider)
    token='independent-v039-local-test'
    app=create_app(tmp_path/'app',token)
    with TestClient(app,base_url='http://127.0.0.1:8765') as client:
        bootstrap=client.get('/api/bootstrap',headers={'x-launch-token':token})
        assert bootstrap.status_code==200
        client.headers['x-csrf-token']=bootstrap.json()['csrf']
        store=app.state.store
        cp=deepcopy(case.cp)
        for hash_ in {ref['hash'] for ref in cp['evidence']}:
            assert store.archive(case.store.evidence(hash_))==hash_
        key=hashlib.sha256(f'{pb.WALLET}:{pb.START}:{pb.END}'.encode()).hexdigest()
        store.put('collector_checkpoints',key,cp)
        window={name:datetime.fromtimestamp(value,timezone.utc).isoformat() for name,value in pb.WINDOW.items()}
        collected={'transactions':case.records,'checkpoint':cp,'evidence':cp['evidence'],'snapshot':cp['snapshot'],'coverage':{'status':'partial'}}
        original={'id':'review-v039-original','scan_id':'review-v039-scan','source':'live','address':pb.WALLET,
            'created_at':'2026-10-03T00:00:00+00:00','window':window,'preset':dict(STRICT),'methodology':'fifo-v3',
            'metrics':{},'checks':[],'policy':'UNRESOLVED','evidence_status':'partial','coverage':{},'token_risk':[],
            'evidence':cp['evidence'],'collection_input_hash':freeze_report_inputs(store,pb.WALLET,window,collected)}
        store.put('reports',original['id'],original)
        store.put('scans',original['scan_id'],{'id':original['scan_id'],'status':'paused','audit_addresses':[pb.WALLET],
            'window':window,'preset':dict(STRICT),'budget_mode':'setup-pilot'})
        usage=client.get('/api/state').json()['usage']
        response=client.post('/api/reports/'+original['id']+'/rebuild')
        assert response.status_code==200,response.text
        child=client.get('/api/reports/'+response.json()['report_id']).json()
        assert child['id']!=original['id']
        assert store.get('reports',original['id'])==original
        assert client.get('/api/state').json()['usage']==usage
        assert child['qualification']['qualified'] is False and child['policy']=='UNRESOLVED'
        assert child['metrics']['profit_sol']['status']=='unknown' and child['metrics']['profit_sol']['value'] is None
        assert child['rebuild']['provider_requests']==0
        frozen=store.evidence(child['collection_input_hash'])
        assert frozen['checkpoint']['evidence']==cp['evidence'] and frozen['evidence']==cp['evidence']
        h=child['coverage']['history_evidence']
        assert set(h['evidence_gates'].values())=={'UNKNOWN'}
        assert calls=={'provider':0,'credential':0}
        result=summarize(child['coverage']['position_evidence'],h,digest)
        result['boundary_checks']={'parent_unchanged':True,'frozen_references_preserved':True,
            'usage_unchanged':True,'provider_calls':0,'credential_lookups':0,'policy':'UNRESOLVED','qualified':False,'profit_unknown':True,
            'reference_count':len(cp['evidence']),'unique_hashes':len({r['hash'] for r in cp['evidence']}),'child_created':True}
        record_result(label+'_child.json',child)
        return result

SOURCE_MODES = ('selected', 'alternative')
LOCATIONS = ('outer', 'inner')
MASKS = ('empty', 'disjoint-address', 'disjoint-index')

def ownership_pair(raw, location, mask='absent', target=None):
    """Contradictory local parsed instruction evidence, not a signed transaction.

    Endpoint ownership is unchanged; two explicitly recorded owner changes must
    not be silently skipped when claiming continuous ownership through a hold.
    """
    target = pb.ACCOUNT if target is None else target
    instructions = [
        {'programId': pb.TOKEN_PROGRAM, 'parsed': {'type': 'setAuthority', 'info': {
            'account': target, 'authority': old, 'authorityType': 'accountOwner', 'newAuthority': new}}}
        for old, new in ((pb.WALLET, pb.POOL), (pb.POOL, pb.WALLET))
    ]
    references = {'empty': [], 'disjoint-address': [pb.POOL_TOKEN], 'disjoint-index': [3],
                  'matching-address': [target], 'matching-index': [1], 'null': None,
                  'bool-index': [False], 'string': 'invalid'}
    if mask != 'absent':
        for instruction in instructions:
            instruction['accounts'] = deepcopy(references[mask])
    if location == 'outer':
        raw['transaction']['message']['instructions'].extend(instructions)
    else:
        raw['meta']['innerInstructions'][0]['instructions'].extend(instructions)
    raw['synthetic_review_note'] = 'Independent R14 instruction-representation test; not mainnet evidence.'


def add_ownership_source(case, mode, location, mask='empty', target=None, index=1):
    operation = case.link_raw_alternative if mode == 'alternative' else case.rearchive_raw_without_changing_pages
    return operation(index, lambda raw: ownership_pair(raw, location, mask, target))
