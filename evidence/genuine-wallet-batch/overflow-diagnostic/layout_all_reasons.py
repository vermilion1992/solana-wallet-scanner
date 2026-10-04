"""Disposable guarded browser inspection of preserved failed-run reports."""
import hashlib,json,os,queue,re,shutil,signal,socket,subprocess,tempfile,threading,time
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path('/workspace/solana-wallet-scanner')
SOURCE=ROOT/'evidence/genuine-wallet-batch/product-browser/data'
OUT=ROOT/'evidence/genuine-wallet-batch/overflow-diagnostic/all-reasons';OUT.mkdir(exist_ok=True)
DB=SOURCE/'scanner.sqlite'
original_db_hash=hashlib.sha256(DB.read_bytes()).hexdigest()
parent=ROOT/'evidence/genuine-wallet-batch/product-browser/indexed-partial-parent.json'
parent_hash=hashlib.sha256(parent.read_bytes()).hexdigest()
html=(ROOT/'frontend/dist/index.html').read_text()
compiled_paths=re.findall(r'(?:src|href)="(/assets/[^"]+)"',html)
compiled_assets={p:{'sha256':hashlib.sha256((ROOT/'frontend/dist'/p.lstrip('/')).read_bytes()).hexdigest(),'bytes':(ROOT/'frontend/dist'/p.lstrip('/')).stat().st_size} for p in compiled_paths}
identity=json.loads(parent.read_bytes())
data=Path(tempfile.mkdtemp(prefix='wallet-layout-inspect-'))
shutil.copy2(DB,data/'scanner.sqlite')
shutil.copytree(SOURCE/'evidence',data/'evidence')
with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
env={k:v for k,v in os.environ.items() if k!='HELIUS_API_KEY'}
server=subprocess.Popen([str(ROOT/'.venv/bin/python'),str(ROOT/'tools/guarded_launcher.py'),'--data',str(data),'--port',str(port),'--guard',str(OUT/'guards.json')],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
lines=queue.Queue()
def drain():
 for line in server.stdout:lines.put(line)
threading.Thread(target=drain,daemon=True).start()
receipt={'kind':'offline-genuine-layout-diagnostic','report_id':identity['id'],'parent_hash_before':parent_hash,'database_hash_before':original_db_hash,'state':'INCOMPLETE','cases':[]}
try:
 deadline=time.monotonic()+30;url=None
 while time.monotonic()<deadline:
  try:line=lines.get(timeout=1)
  except queue.Empty:continue
  match=re.search(r'http://127\.0\.0\.1:\d+/#session=[A-Za-z0-9_-]+',line)
  if match:url=match.group(0);break
 assert url
 base=url.split('/#')[0]
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
  page=browser.new_page(viewport={'width':1440,'height':900})
  errors=[];external=[]
  page.on('pageerror',lambda error:errors.append(str(error)))
  page.on('request',lambda request:external.append(request.url) if not request.url.startswith(base+'/') else None)
  page.goto(url);page.get_by_role('button',name='Find wallet candidates',exact=True).first.wait_for()
  page.get_by_role('button',name=re.compile('^Results')).first.click()
  names=page.get_by_role('button').evaluate_all('(buttons)=>buttons.map(b=>({name:b.getAttribute("aria-label"),text:b.innerText})).filter(b=>b.name&&b.name.startsWith("Open"))')
  (OUT/'open-buttons.json').write_text(json.dumps(names,indent=2)+'\n')
  page.get_by_role('button',name='Open '+identity['address'],exact=True).click()
  panel=page.locator('[data-archive-report-id="'+identity['id']+'"]')
  panel.wait_for(timeout=120000)
  page.get_by_role('tab',name='Summary',exact=True).click()
  for width,height in ((1440,900),(390,844)):
   page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(500)
   result=page.evaluate('''() => {
    const viewport=innerWidth;
    const path = el => {const parts=[];while(el&&parts.length<7){parts.unshift(el.tagName.toLowerCase()+(el.id?"#"+el.id:"")+(typeof el.className==="string"&&el.className?"."+el.className.trim().split(/\\s+/).join("."):""));el=el.parentElement;}return parts.join(" > ");};
    const rows=[...document.querySelectorAll("body *")].filter(el=>{const r=el.getBoundingClientRect();return r.width&&r.height&&(r.right>viewport+1||r.left< -1||el.scrollWidth>el.clientWidth+1);}).map(el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return {tag:el.tagName,class:el.className,path:path(el),left:r.left,right:r.right,width:r.width,scrollWidth:el.scrollWidth,clientWidth:el.clientWidth,overflowX:s.overflowX,whiteSpace:s.whiteSpace,wordBreak:s.wordBreak,overflowWrap:s.overflowWrap,minWidth:s.minWidth,maxWidth:s.maxWidth,text:(el.innerText||el.textContent||"").slice(0,350),ancestors:(()=>{const a=[];for(let p=el.parentElement;p&&a.length<5;p=p.parentElement){const b=p.getBoundingClientRect(),c=getComputedStyle(p);a.push({tag:p.tagName,class:p.className,left:b.left,right:b.right,width:b.width,scrollWidth:p.scrollWidth,clientWidth:p.clientWidth,overflowX:c.overflowX,minWidth:c.minWidth});}return a;})()};});
    return {viewport,scrollWidth:document.documentElement.scrollWidth,scrollX,overflowRows:rows.sort((a,b)=>(b.left+b.scrollWidth)-(a.left+a.scrollWidth)).slice(0,100)};
   }''')
   expected_reason=identity['metrics']['profit_sol']['reason']
   actual_reason=page.locator('.report-metric > small').first.inner_text()
   assert actual_reason==expected_reason, 'Full frozen metric reason must remain visible verbatim'
   assert page.locator('.report-metric > small').first.is_visible()
   assert page.locator('.report-metric > small').first.evaluate("el => !el.closest('[aria-hidden=true]') && getComputedStyle(el).overflowWrap==='anywhere' && getComputedStyle(el).maxHeight==='none'")
   assert expected_reason in page.locator('.all-metrics-grid > div > small').all_text_contents()
   selectors=['.report-metric > small','.all-metrics-grid > div > small','.metric-interval-detail > p']
   reason_nodes=[]
   for selector in selectors:
    nodes=page.locator(selector).evaluate_all("""elements => elements.map(el=>{const style=getComputedStyle(el),rect=el.getBoundingClientRect();return {text:el.innerText,sourceText:el.textContent,left:rect.left,right:rect.right,width:rect.width,clientWidth:el.clientWidth,scrollWidth:el.scrollWidth,clientHeight:el.clientHeight,scrollHeight:el.scrollHeight,overflowWrap:style.overflowWrap,maxHeight:style.maxHeight,lineClamp:style.webkitLineClamp,visibility:style.visibility,hidden:!!el.closest('[aria-hidden=true],[hidden]'),visible:rect.width>0&&rect.height>0};})""")
    assert nodes, 'Every dependency reason selector must be exercised: '+selector
    for node in nodes:
     assert node['visible'] and node['visibility']=='visible' and not node['hidden'], (selector,'hidden',node)
     assert node['scrollWidth']<=node['clientWidth']+1, (selector,'horizontal clipping',node)
     assert node['scrollHeight']<=node['clientHeight']+1, (selector,'vertical clipping',node)
     assert node['maxHeight']=='none' and node['lineClamp'] in ('none','0',''), (selector,'truncation',node)
     assert node['text'].strip()==node['sourceText'].strip(), (selector,'changed or hidden text',node)
     assert node['overflowWrap']=='anywhere', (selector,'unwrapped reason',node)
     node['selector']=selector
     node['text_characters']=len(node['text'])
     node['text_sha256']=hashlib.sha256(node['text'].encode()).hexdigest()
     reason_nodes.append(node)
   interval_reason=(identity.get('metric_coverage',{}).get('positive_weeks') or identity.get('metric_intervals',{}).get('four_weeks'))['reason']
   assert interval_reason in page.locator('.metric-interval-detail > p').all_text_contents(), 'Independently frozen interval dependency reason must remain verbatim'
   result['all_reason_nodes']=reason_nodes
   result['all_dependency_reasons_visible_verbatim_unclipped']=True
   result['interval_reason_characters']=len(interval_reason)
   result['reason_verbatim']=True
   result['reason_characters']=len(expected_reason)
   result['reason_sha256']=hashlib.sha256(actual_reason.encode()).hexdigest()
   result['no_horizontal_overflow']=result['scrollWidth']<=width and result['scrollX']==0
   assert result['no_horizontal_overflow']
   receipt['cases'].append(result)
   page.screenshot(path=str(OUT/f'indexed-summary-{width}.png'),full_page=True)
  receipt.update(state='PASS',javascript_errors=errors,external_browser_requests=external)
  browser.close()
except Exception as error:
 receipt.update(state='FAILED',reason=type(error).__name__+': '+str(error))
 raise
finally:
 server.send_signal(signal.SIGTERM)
 try:server.wait(timeout=20)
 except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
 receipt['offline_guards']=json.loads((OUT/'guards.json').read_bytes())
 receipt['database_hash_after']=hashlib.sha256(DB.read_bytes()).hexdigest()
 receipt['parent_hash_after']=hashlib.sha256(parent.read_bytes()).hexdigest()
 receipt['preserved_original_database_and_parent']=receipt['database_hash_after']==original_db_hash and receipt['parent_hash_after']==parent_hash
 receipt['compiled_assets']=compiled_assets
 receipt['scope']='Scoped genuine report text wrapping replay only; no new application acceptance or B3 claim.'
 receipt['source_files']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['frontend/src/styles.css','frontend/dist/index.html','frontend/src/report.tsx']}
 (OUT/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
 print(json.dumps({k:v for k,v in receipt.items() if k not in ('cases','source_files')},indent=2))
