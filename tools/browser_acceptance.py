#!/usr/bin/env python3
"""Real Chromium checks on new QA storage, old parents and frozen sources."""
import argparse,gzip,hashlib,json,os,queue,re,shutil,signal,socket,sqlite3,subprocess,sys,tarfile,threading,time,io
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class BrowserEnvironmentUnavailable(Exception):
    """A browser launch failure is an environment gate, not an app finding."""

def run(args):
    args.python=os.path.abspath(shutil.which(args.python) or args.python)
    args.output=args.output.absolute()
    if args.real_corpus:
        args.real_corpus=args.real_corpus.absolute()
    out=args.output;out.mkdir(parents=True,exist_ok=False);data=out/'data';data.mkdir()
    env={k:v for k,v in os.environ.items() if k!='HELIUS_API_KEY'}
    try:
        from playwright.sync_api import sync_playwright,expect
    except ImportError:
        (out/'result.json').write_text(json.dumps({'state':'BLOCKED','reason':'Configured browser interpreter has no Playwright; no dependency substituted or installed.'})+'\n');return 2
    if not shutil.which(args.chromium):
        (out/'result.json').write_text(json.dumps({'state':'BLOCKED','reason':'Configured Chromium executable is unavailable: '+args.chromium})+'\n');return 2
    # Extract original committed source locally; no archive is exported.
    commit=json.loads((ROOT/'evidence/BASELINE.json').read_text())['baseline_commit'];baseline=out/'baseline';baseline.mkdir()
    tar=subprocess.check_output(['git','archive','--format=tar',commit],cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(tar)) as archive:
        for m in archive.getmembers():assert not Path(m.name).is_absolute() and '..' not in Path(m.name).parts and not m.issym() and not m.islnk()
        archive.extractall(baseline,filter='data')
    seed='import sys;sys.path.insert(0,'+repr(str(ROOT/'tools'))+');from browser_seed import seed;from pathlib import Path;seed(Path('+repr(str(data))+'),Path('+repr(str(out))+'),Path('+repr(str(args.real_corpus))+'))'
    subprocess.run([args.python,'-c',seed],cwd=ROOT,env=env,check=True)
    cases=json.loads((out/'cases.json').read_text())
    old='''import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from scanner.storage import Store
from scanner.report_rebuild import load_report_inputs
from scanner.history_evidence import derive_history_evidence
from scanner.position_evidence import derive_position_evidence
store=Store(sys.argv[2]);cases=json.loads(Path(sys.argv[3]).read_text())
for case in cases['synthetic']:
 r=store.get('reports',case['id']);c=load_report_inputs(store,r)
 h=derive_history_evidence(store,r['address'],r['window'],checkpoint=c['checkpoint'],collected=c)
 p=derive_position_evidence(store,r['address'],r['window'],checkpoint=c['checkpoint'],collected=c)
 assert p['version']=='account-position-evidence-v9'
 r['coverage']={'history_evidence':h,'position_evidence':p};store.put('reports',r['id'],r)
 case['baseline_known_closed']=p['counts']['known_closed']
Path(sys.argv[3]).write_text(json.dumps(cases,indent=2)+'\\n');store.close()
'''
    subprocess.run([args.python,'-c',old,str(baseline),str(data),str(out/'cases.json')],cwd=baseline,env=env,check=True)
    cases=json.loads((out/'cases.json').read_text())
    with sqlite3.connect(data/'scanner.sqlite') as db:original={i:v for i,v in db.execute("SELECT id,payload FROM records WHERE kind='reports'")}
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=subprocess.Popen([args.python,str(ROOT/'tools/guarded_launcher.py'),'--data',str(data),'--port',str(port),'--guard',str(out/'guards.json')],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    lines=queue.Queue()
    def drain():
        for line in server.stdout:lines.put(line)
    threading.Thread(target=drain,daemon=True).start();result={'state':'FAILED'}
    try:
        deadline=time.monotonic()+30;url=None
        while time.monotonic()<deadline:
            if server.poll() is not None:raise AssertionError('Guarded CLI exited before readiness')
            try:line=lines.get(timeout=1)
            except queue.Empty:continue
            m=re.search(r'http://127\.0\.0\.1:\d+/#session=[A-Za-z0-9_-]+',line)
            if m:url=m.group(0);break
        assert url,'Guarded CLI startup timeout'
        base=url.split('/#')[0];results=[];captures=0
        with sync_playwright() as playwright:
            try:
                browser=playwright.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
            except Exception as exc:
                raise BrowserEnvironmentUnavailable(str(exc)) from exc
            page=browser.new_page(viewport={'width':1440,'height':900});errors=[];external=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:external.append(r.url) if not r.url.startswith(base+'/') else None)
            assert page.request.get(base+'/api/state').status==401
            page.goto(url);page.get_by_role('button',name='Find wallet candidates',exact=True).first.wait_for()
            state=page.request.get(base+'/api/state').json();usage=state['usage']
            assert not state['provider']['configured'] and state['settings']['refresh_minutes']==0
            assert state['position_evidence_methodology']=='account-position-evidence-v13'
            def capture(name):
                nonlocal captures
                for width,height,label in ((1440,900,'desktop'),(390,844,'mobile')):
                    page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(150)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth&&scrollX===0')
                    assert page.evaluate("""() => [...document.querySelectorAll('.report-metric > small, .all-metrics-grid > div > small, .metric-interval-detail p')]
                        .filter(element => element.getClientRects().length)
                        .every(element => element.scrollWidth <= element.clientWidth + 1 && element.scrollHeight <= element.clientHeight + 1)"""), 'Metric dependency text is clipped inside its field'
                    page.screenshot(path=str(out/(name+'-'+label+'.png')),full_page=True);captures+=1
                page.set_viewport_size({'width':1440,'height':900})
            # Settings are exercised through actual UI, with the original strict preset saved.
            page.get_by_role('button',name='Settings',exact=True).click()
            page.get_by_label('Minimum profit (SOL)',exact=True).fill('5')
            with page.expect_response(lambda r:r.request.method=='PUT' and r.url.endswith('/api/settings')) as saved:
                page.get_by_role('button',name='Save preset',exact=True).click()
            assert saved.value.status==200
            saved_preset=page.request.get(base+'/api/state').json()['preset']
            assert {k:v for k,v in saved_preset.items() if k!='version'}=={k:v for k,v in state['preset'].items() if k!='version'};capture('settings')
            # Offline address import loads a candidate without upgrading its identity or history.
            page.get_by_role('button',name='Discover',exact=True).click()
            page.get_by_text('Import a public candidate list',exact=True).click()
            page.get_by_label('Public Solana addresses',exact=True).fill('4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi')
            with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/discovery/import')) as imported:
                page.get_by_role('button',name='Save public list',exact=True).click()
            assert imported.value.status==200
            expect(page.get_by_text('Imported list',exact=False).first).to_be_visible();capture('candidate-import')
            def open_parent(identifier):
                back=page.get_by_role('button',name='Back to results',exact=True)
                if back.count():back.click()
                else:page.get_by_role('button',name='Results',exact=False).first.click()
                parent=page.request.get(base+'/api/reports/'+identifier).json()
                descriptors=page.request.get(base+'/api/state').json()['reports'];name='Open '+(parent.get('label') or parent['address'])
                matches=[r for r in descriptors if 'Open '+(r.get('label') or r['address'])==name]
                index=next(i for i,r in enumerate(matches) if r['id']==identifier)
                page.get_by_role('button',name=name,exact=True).nth(index).click();return parent
            def rebuild(identifier,held,label,expected_fees=None):
                parent=open_parent(identifier);export=page.request.get(base+'/api/export/reports/'+identifier+'.json').body()
                assert parent['position_assessment']['state']=='rebuild_required'
                with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/reports/'+identifier+'/rebuild')) as pending:
                    page.get_by_role('button',name='Rebuild from saved records',exact=True).click()
                assert pending.value.status==200
                child=page.request.get(base+'/api/reports/'+pending.value.json()['report_id']).json()
                expect(page.locator('[data-position-assessment="current"]')).to_be_visible()
                page.get_by_role('tab',name='Summary',exact=True).click()
                pos=child['coverage']['position_evidence'];assert pos['counts']['known_closed']==int(held)
                assert child['policy']=='UNRESOLVED' and not child['qualification']['qualified']
                assert child['metrics']['profit_sol']['status']=='unknown' and child['rebuild']['provider_requests']==0
                h=child['coverage']['history_evidence'];assert set(h['evidence_gates'].values())=={'UNKNOWN'}
                if expected_fees is not None:assert h['native_address_metrics']['observed']['wallet_network_fees_sol']['value']==expected_fees
                if not held:
                    row=page.locator('[data-position-source-consistency="UNKNOWN"]').first
                    if row.count():
                        row.get_by_text('Inspect episode stages',exact=True).click()
                        row.get_by_text(re.compile('^Inspect quantity source paths')).click()
                old=json.loads(gzip.decompress((data/'evidence'/(parent['collection_input_hash']+'.json.gz')).read_bytes()))
                new=json.loads(gzip.decompress((data/'evidence'/(child['collection_input_hash']+'.json.gz')).read_bytes()))
                assert old['evidence']==new['evidence'] and old['checkpoint']['evidence']==new['checkpoint']['evidence']
                assert page.request.get(base+'/api/reports/'+identifier).json()==parent
                assert page.request.get(base+'/api/export/reports/'+identifier+'.json').body()==export
                assert page.request.get(base+'/api/state').json()['usage']==usage
                # Exercise the actual UI JSON download as well as the export endpoint.
                capture(label)
                page.get_by_role('tab',name=re.compile('^Source evidence')).click()
                page.get_by_role('button',name='Inspect record',exact=True).first.click()
                expect(page.get_by_role('button',name='Close evidence',exact=True)).to_be_visible()
                page.get_by_role('button',name='Close evidence',exact=True).click()
                with page.expect_download() as download:page.get_by_role('link',name='Export report JSON',exact=False).click()
                downloaded=Path(download.value.path()).read_bytes();assert json.loads(downloaded)['id']==child['id']
                results.append({'case':label,'child':child['id'],'known_closed':int(held),'frozen_references_preserved':True,'parent_export_unchanged':True})
            for case in cases['synthetic']:
                rebuild(case['id'],case['held'],case['kind'],'0.000015')
                if case['kind']=='loss-restoration':
                    path=data/'evidence'/(case['hash']+'.json.gz');content=path.read_bytes()
                    try:path.unlink();rebuild(case['id'],False,'required-source-missing')
                    finally:path.write_bytes(content)
                    rebuild(case['id'],True,'required-source-restored','0.000015')
            if cases['real']:
                real=cases['real'];rebuild(real['id'],False,'cached-real',real['fees'])
            assert not errors and not external,(errors,external)
            browser.close()
            result={'state':'PASS','offline_children':len(results),'cases':results,'captures':captures,'desktop_width':1440,'mobile_width':390,'no_overflow':True,'javascript_errors':errors,'external_browser_requests':external,'anonymous_state':401,'settings_saved_without_threshold_change':True,'offline_candidate_import':True,'source_loss_and_exact_restoration':True,'actual_UI_json_exports':True,'evidence_inspection':True,'usage_before':usage,'usage_after':usage,'real_case_executed':bool(cases['real']),'historical_parents':'actual committed v0.3.11 position-v9 source'}
    except BrowserEnvironmentUnavailable as exc:
        result={'state':'BLOCKED','reason':str(exc)}
    except Exception as exc:
        result={'state':'FAILED','reason':type(exc).__name__+': '+str(exc)}
        raise
    finally:
        server.send_signal(signal.SIGTERM)
        try:server.wait(timeout=20)
        except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
        result['server_stopped']=True
        result['offline_guards']=json.loads((out/'guards.json').read_text())
        with sqlite3.connect(data/'scanner.sqlite') as db:final={i:v for i,v in db.execute("SELECT id,payload FROM records WHERE kind='reports'")}
        result['parents_unchanged']=all(final[i]==v for i,v in original.items())
        if not result['parents_unchanged'] or any(result['offline_guards'].values()):result['state']='FAILED'
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('cases','usage_before','usage_after')}))
    return 0 if result['state']=='PASS' else 2 if result['state']=='BLOCKED' else 1

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--python',required=True);p.add_argument('--chromium',default='/usr/bin/chromium');p.add_argument('--output',type=Path,required=True);p.add_argument('--real-corpus',type=Path,default=ROOT/'evidence/runs/real-cache');a=p.parse_args()
    raise SystemExit(run(a))
