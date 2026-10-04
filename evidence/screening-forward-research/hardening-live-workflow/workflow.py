from pathlib import Path
import json,os,sys,time,traceback,shutil,re
sys.path.insert(0,'/workspace/solana-wallet-scanner')
from tools.screening_browser import Launcher
from playwright.sync_api import sync_playwright
out=Path('/workspace/solana-wallet-scanner/evidence/screening-forward-research/hardening-live-workflow');out.mkdir(exist_ok=False)
source=Path('/workspace/scratch/live-product-workflow-20261004')
shutil.copytree(source/'data',out/'data')
launcher=Launcher(out,os.environ.copy())
from tools.validate import source_manifest
import subprocess
source_before=source_manifest()
result={'application_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd='/workspace/solana-wallet-scanner',text=True).strip(),'source_sha256':source_before['sha256'],'kind':'genuine-address-subscription-and-saved-research-workflow','state':'INCOMPLETE', 'provider_collection':'No new historical collection; retained genuine sources from preceding live pass', 'screening':'Separately named transport-validation preset; control exclusions disabled explicitly, original default exclusion retained', 'PRODUCT_READY':False}
def save():(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
save()
try:
 launcher.start()
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
  page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
  page.on('pageerror',lambda error:errors.append(str(error)))
  page.goto(launcher.url);page.get_by_role('button',name='Research',exact=True).click()
  csrf=page.request.get(launcher.base+'/api/bootstrap').json()['csrf']
  def get(path):
   r=page.request.get(launcher.base+path);assert r.status==200,r.text();return r.json()
  def post(path,data=None):
   r=page.request.post(launcher.base+path,data=data or {},headers={'X-CSRF-Token':csrf},timeout=120000);assert r.status==200,r.text();return r.json()
  old=json.loads((source/'result.json').read_text())
  original=get('/api/screenings/'+old['screening_id'])
  preset=dict(original['preset_snapshot'])
  preset.update(name='Transport-validation preset: token control exclusions disabled',exclude_active_mint_authority=False,exclude_active_freeze_authority=False,exclude_restrictive_extensions=False,max_rapid_sale_pct='100')
  screening=post('/api/screenings',{'report_id':old['report_id'],'preset':preset})
  result.update(screening_result=screening['result'],strict_qualified=screening['strict_qualification']['qualified'],screening_id=screening['id'])
  assert screening['result']=='insufficient_evidence',screening['result']
  post('/api/watchlist',{'address':screening['address'],'label':'Read-only live transport validation; default preset excluded'})
  page.reload();page.get_by_role('button',name='Research',exact=True).click();page.get_by_label('Saved screening assessment',exact=True).select_option(screening['id'])
  page.get_by_role('button',name='Reopen saved assessment',exact=True).click()
  page.get_by_role('spinbutton',name=re.compile(r'^Observation duration')).fill('2')
  with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/observations')) as response:
   page.get_by_role('button',name='Start quote-only observation',exact=True).click()
  assert response.value.status==200,response.value.text()
  run=response.value.json();result['run_id']=run['id'];save()
  deadline=time.monotonic()+40
  while time.monotonic()<deadline:
   run=get('/api/observations/'+run['id'])
   if run.get('observer',{}).get('status')=='listening' or run['status']!='running':break
   page.wait_for_timeout(500)
  result['observer']=run.get('observer');result['subscription']='PASS' if run.get('observer',{}).get('status')=='listening' else 'UNAVAILABLE'
  page.get_by_role('button',name='Reopen saved observation',exact=True).click()
  page.screenshot(path=str(out/'01-live-observer.png'),full_page=True)
  with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/stop')) as response:
   page.get_by_role('button',name='Stop observation',exact=True).click()
  assert response.value.status==200,response.value.text()
  with page.expect_download() as download:
   page.get_by_role('link',name='Export paper observation',exact=False).click()
  shutil.copyfile(download.value.path(),out/'observation-export.json')
  saved=get('/api/observations/'+run['id'])
  result['summary']=saved['summary'];result['javascript_errors']=errors
  assert not errors,errors
  launcher.stop();launcher.start();page.goto(launcher.url);page.get_by_role('button',name='Research',exact=True).wait_for()
  reopened=get('/api/observations/'+run['id']);assert reopened['settings']==saved['settings'];assert reopened['status']=='stopped'
  result['restart_persistence']='PASS'
  result['state']='PASS' if result['subscription']=='PASS' else 'SUBSCRIPTION_UNAVAILABLE'
  browser.close()
except Exception as error:
 result.update(state='FAILED',reason=type(error).__name__+': '+str(error));(out/'traceback.txt').write_text(traceback.format_exc())
finally:
 launcher.stop();result['source_unchanged']=source_manifest()['sha256']==source_before['sha256'];save();print(json.dumps(result,indent=2))
