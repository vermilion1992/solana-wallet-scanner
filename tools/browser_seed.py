"""Disposable native-archive parents for guarded browser acceptance."""
from copy import deepcopy
from datetime import datetime,timezone
import gzip,hashlib,json,shutil
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scanner.storage import Store
from scanner.config import STRICT,LIMITS
from scanner.report_rebuild import freeze_report_inputs
from tests.review_v0310.review_helpers import pb
from tests.test_position_evidence import PositionEvidenceTests
from tests.review_v0310.schema_helpers import add


def seed(data,output,real_corpus):
    store=Store(data);cases=[]
    definitions=[('canonical-nonce',{'programId':'11111111111111111111111111111111','parsed':{'type':'withdrawFromNonce','info':{'nonceAccount':pb.address(40),'destination':pb.address(41),'nonceAuthority':pb.address(42),'recentBlockhashesSysvar':pb.address(43),'rentSysvar':pb.address(44),'lamports':25}}},True),
      ('loss-restoration',{'programId':pb.TOKEN_PROGRAM,'parsed':{'type':'revoke','info':{'source':pb.POOL_TOKEN,'owner':pb.POOL}}},True),
      ('owner-change',{'programId':pb.TOKEN_PROGRAM,'parsed':{'type':'setAuthority','info':{'account':pb.ACCOUNT,'authorityType':'accountOwner','authority':pb.WALLET,'newAuthority':pb.POOL}}},False)]
    for name,ins,held in definitions:
        case=PositionEvidenceTests(methodName='runTest');case.setUp()
        try:
            digest=add(case,'alternative','inner',ins);cp=deepcopy(case.cp);offset=len(cases)+1
            for field in ('start','end','basis_floor'):cp[field]+=offset
            for h in {r['hash'] for r in cp['evidence']}:assert store.archive(case.store.evidence(h))==h
            key=hashlib.sha256(f'{pb.WALLET}:{cp["start"]}:{cp["end"]}'.encode()).hexdigest();store.put('collector_checkpoints',key,cp)
            window={k:datetime.fromtimestamp(v+offset,timezone.utc).isoformat() for k,v in pb.WINDOW.items()}
            collected={'transactions':case.records,'checkpoint':cp,'evidence':cp['evidence'],'snapshot':cp['snapshot'],'coverage':{'status':'partial'}}
            identifier='synthetic-batch-'+name
            parent={'id':identifier,'scan_id':identifier+'-scan','label':'Synthetic '+name,'source':'live','address':pb.WALLET,'created_at':f'2026-10-03T00:00:0{offset}+00:00','window':window,'preset':dict(STRICT),'methodology':'fifo-v3','metrics':{},'positions':[],'events':[],'findings':[],'counts':{'closed':0,'open':0,'interrupted':0,'unresolved':0},'checks':[],'policy':'UNRESOLVED','evidence_status':'partial','coverage':{},'token_risk':[],'evidence':cp['evidence'],'collection_input_hash':freeze_report_inputs(store,pb.WALLET,window,collected),'notes':['Synthetic schema/availability control; no real-chain or complete-wallet claim. Historical interpretation derived from original baseline source.']}
            store.put('reports',identifier,parent)
            store.put('scans',parent['scan_id'],{'id':parent['scan_id'],'status':'paused','source':'live','created_at':parent['created_at'],'addresses':[pb.WALLET],'audit_addresses':[pb.WALLET],'window':window,'preset':dict(STRICT),'limits':dict(LIMITS),'budget_mode':'setup-pilot','stage':'Offline acceptance','progress':{'wallets_total':1,'wallets_completed':1,'unresolved':1,'pages':4,'transactions':3,'credits':0}})
            cases.append({'id':identifier,'hash':digest,'held':held,'kind':name})
        finally:case.doCleanups()
    real=None
    if real_corpus and (real_corpus/'manifest.json.gz').is_file():
        m=json.loads(gzip.decompress((real_corpus/'manifest.json.gz').read_bytes()))
        for h in m['archive_hashes']:
            src=real_corpus/'archives'/(h+'.json.gz');dst=data/'evidence'/(h+'.json.gz')
            shutil.copyfile(src,dst);store.evidence(h)
        store.put('collector_checkpoints',m['checkpoint_id'],m['collector_checkpoint'])
        parent=m['report'];job=m['scan'];job['status']='paused'
        store.put('reports',parent['id'],parent);store.put('scans',job['id'],job)
        real={'id':parent['id'],'fees':m['expected_observed_wallet_fees_sol'],'scope':m['scope']}
    settings=store.get('configuration','settings',{});settings.setdefault('limits',dict(LIMITS));settings['refresh_minutes']=0;store.put('configuration','settings',settings)
    store.close();(output/'cases.json').write_text(json.dumps({'synthetic':cases,'real':real},indent=2)+'\n')
    return cases
