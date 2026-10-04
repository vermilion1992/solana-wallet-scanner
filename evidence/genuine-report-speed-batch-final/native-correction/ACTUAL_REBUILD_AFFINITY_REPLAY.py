from pathlib import Path
import json,tempfile,sys
from types import SimpleNamespace
import httpx
from unittest.mock import patch
from fastapi.testclient import TestClient
from scanner.app import create_app
from tests.test_position_evidence import PositionEvidenceTests
from tests.test_review_v037_independent import role_source,seed_actual_report
case=PositionEvidenceTests(methodName='runTest'); case.setUp(); role_source(case,'owned-accounts','agreeing')
calls={'provider':0,'credential':0}
async def denied_provider(*args,**kwargs):
 calls['provider']+=1; raise AssertionError('offline provider forbidden')
def denied_key(*args,**kwargs):
 calls['credential']+=1; raise AssertionError('offline key forbidden')
results=[]
try:
 with tempfile.TemporaryDirectory(prefix='inventory-frozen-rebuild-review-') as scratch, patch.dict(sys.modules,{'keyring':SimpleNamespace(get_keyring=lambda:object(),get_password=denied_key)}), patch.object(httpx.AsyncClient,'request',denied_provider):
  app=create_app(Path(scratch),'role-affinity-local-token')
  with TestClient(app,base_url='http://127.0.0.1:8765') as client:
   client.headers['X-CSRF-Token']=client.get('/api/bootstrap',headers={'X-Launch-Token':'role-affinity-local-token'}).json()['csrf']
   parent,checkpoint=seed_actual_report(case,app.state.store,'owned-accounts','agreeing')
   identifier=parent['id']
   for level in range(1,4):
    response=client.post('/api/reports/'+identifier+'/rebuild')
    if response.status_code!=200:
     results.append({'generation':level,'status_code':response.status_code,'response':response.json()});break
    identifier=response.json()['report_id']; child=client.get('/api/reports/'+identifier).json()
    frozen=app.state.store.evidence(child['collection_input_hash']); history=child['coverage']['history_evidence']; position=child['coverage']['position_evidence']
    results.append({'generation':level,'status_code':200,'native_references_preserved':frozen['checkpoint']['evidence']==checkpoint['evidence'],
     'frozen_evidence_equal_original':frozen['evidence']==checkpoint['evidence'],
     'new_refs':[r for r in frozen['evidence'] if r not in checkpoint['evidence']],
     'source_set':history['source_consistency']['source_set'],
     'known_closed':position['counts']['known_closed'],'hold':position['positions'][0]['hold_hours'],
     'wallet_fee':history['native_address_metrics']['observed']['wallet_network_fees_sol'],
     'native_delta':history['native_address_metrics']['observed']['native_wallet_delta_sol']})
   assert app.state.store.get('reports',parent['id'])==parent
 print(json.dumps({'kind':'read-only-current-source-native-rebuild-inventory-affinity-replay','results':results,'calls':calls,'parent_unchanged':True},indent=2))
finally: case.doCleanups()
