"""Disposable guarded browser inspection of preserved failed-run reports."""
import hashlib,json,os,queue,re,shutil,signal,socket,subprocess,tempfile,threading,time
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path('/workspace/solana-wallet-scanner')
SOURCE=ROOT/'evidence/genuine-wallet-batch/product-browser/data'
OUT=ROOT/'evidence/genuine-wallet-batch/overflow-diagnostic/detail';OUT.mkdir(exist_ok=True)
DB=SOURCE/'scanner.sqlite'
original_db_hash=hashlib.sha256(DB.read_bytes()).hexdigest()
parent=ROOT/'evidence/genuine-wallet-batch/product-browser/indexed-partial-parent.json'
parent_hash=hashlib.sha256(parent.read_bytes()).hexdigest()
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
   receipt['cases'].append(result)
   page.screenshot(path=str(OUT/f'indexed-summary-{width}.png'),full_page=True)
  receipt.update(state='OBSERVED',javascript_errors=errors,external_browser_requests=external)
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
 receipt['source_files']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['frontend/src/styles.css','frontend/dist/index.html','frontend/src/report.tsx']}
 (OUT/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
 print(json.dumps({k:v for k,v in receipt.items() if k not in ('cases','source_files')},indent=2))
