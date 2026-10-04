#!/usr/bin/env python3
"""Actual launcher/Chromium screening workflow using an explicit offline test transport.

No browser routes are mocked. Only public provider transports receive synthetic
schema fixtures, in disposable storage. This cannot authenticate a real wallet,
close full historical acceptance, or demonstrate profitable following.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
BANNER = 'OFFLINE SYNTHETIC TEST TRANSPORT · No genuine wallet collection or fills'

# This temporary hook is loaded by the real run.sh Python process. Unknown
# transport dispatch and credential access are blocked before network access.
GUARD_SOURCE = r'''
import atexit, asyncio, json, os, socket, sys
from pathlib import Path
from types import SimpleNamespace
import httpx
fixture_path = Path(os.environ['SCREENING_BROWSER_FIXTURES'])
fixture = json.loads(fixture_path.read_text())
guard_path = Path(os.environ['SCREENING_BROWSER_GUARD'])
counts = {'synthetic_provider_requests': 0, 'external_provider_requests': 0,
          'credential_lookups': 0, 'blocked_requests': 0, 'synthetic_subscriptions': 0,
          'transport': 'explicit offline synthetic test, no genuine provider collection', 'requests': []}
if guard_path.exists(): counts = json.loads(guard_path.read_text())
def save(): guard_path.write_text(json.dumps(counts, indent=2)+'\n')
def credential(*a, **k):
    counts['credential_lookups'] += 1; save()
    raise AssertionError('Offline browser verification forbids credential lookup')
sys.modules['keyring'] = SimpleNamespace(get_keyring=lambda: object(), get_password=credential, set_password=credential)
def event(kind, method, path):
    counts[kind] += 1
    counts['requests'].append({'kind':kind, 'method':method, 'path':path})
    save()
async def transport(self, request):
    host, path = request.url.host, request.url.path
    if host == 'api.jup.ag' and path == '/swap/v2/order' and request.method == 'GET':
        params = dict(request.url.params)
        if set(params) - {'inputMint','outputMint','amount','swapMode','slippageBps'} or 'taker' in params:
            raise AssertionError('Paper quote must never include taker or execution parameters')
        event('synthetic_provider_requests', 'quote-only', path)
        amount = int(params['amount']); entering = params['inputMint'] == fixture['wsol']
        output = amount * 100 if entering else amount // 125
        return httpx.Response(200, request=request, json={'inputMint': params['inputMint'], 'outputMint': params['outputMint'],
            'inAmount': str(amount), 'outAmount': str(output), 'otherAmountThreshold': str(output),
            'swapMode':'ExactIn', 'slippageBps': int(params.get('slippageBps',0)), 'transaction':None,
            'taker':None, 'router':'metis', 'requestId':'synthetic-browser-quote-'+str(counts['synthetic_provider_requests']),
            'feeMint':fixture['wsol'], 'feeBps':10, 'platformFee':{'feeBps':10, 'feeMint':fixture['wsol']},
            'priceImpact':-0.1, 'priceImpactPct':'-0.001',
            'signatureFeeLamports':0, 'prioritizationFeeLamports':0, 'rentFeeLamports':0,
            'routePlan':[{'percent':100, 'bps':10000, 'swapInfo':{'label':'Synthetic schema route'}}],
            'synthetic_test_note':'Explicit offline transport fixture; no real quote or execution'})
    if host in ('api.mainnet-beta.solana.com','api.devnet.solana.com') and request.method == 'POST':
        body = json.loads(request.content)
        method, params = body.get('method'), body.get('params',[])
        event('synthetic_provider_requests', method, path)
        if method == 'getTransaction': result = deepcopy_json(fixture['transactions'].get(params[0]))
        elif method == 'getSignaturesForAddress':
            options = params[1] if len(params)>1 else {}
            result = [] if options.get('before') else fixture['entries'][:options.get('limit',1000)]
        elif method == 'getAccountInfo':
            if params[0] == fixture['wallet']:
                result = {'context':{'slot':fixture['slot']}, 'value':{'owner':'11111111111111111111111111111111','executable':False,'lamports':10_000_000_000,'data':['','base64'],'space':0}}
            else: result = {'context':{'slot':fixture['slot']},'value':None}
        elif method == 'getSlot': result = fixture['slot']
        elif method == 'getBalance': result = {'context':{'slot':fixture['slot']},'value':10_000_000_000}
        elif method == 'getTokenAccountsByOwner': result = {'context':{'slot':fixture['slot']},'value':[]}
        else:
            event('blocked_requests', method or 'unknown-rpc', path)
            raise AssertionError('Unsupported offline fixture RPC: '+str(method))
        return httpx.Response(200, request=request, json={'jsonrpc':'2.0','id':body.get('id'), 'result':result})
    event('blocked_requests', request.method, host+path)
    raise AssertionError('Offline browser verification blocked external dispatch: '+host+path)
def deepcopy_json(value): return json.loads(json.dumps(value))
httpx.AsyncHTTPTransport.handle_async_request = transport
# A separate socket guard prevents accidental transport substitutions.
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex
def connect(self, address):
    if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1','localhost'):
        event('blocked_requests','socket-connect',str(address[0]))
        raise OSError('Offline verification prohibits external sockets')
    return original_connect(self,address)
def connect_ex(self,address):
    if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1','localhost'):
        event('blocked_requests','socket-connect',str(address[0]))
        return 111
    return original_connect_ex(self,address)
socket.socket.connect = connect
socket.socket.connect_ex = connect_ex
# Supply a synthetic provider WebSocket, not application or browser route mocks.
class SyntheticSocket:
    def __init__(self): self.index = 0; self.request = None
    async def __aenter__(self):
        event('synthetic_subscriptions','connect','address-specific logsSubscribe')
        return self
    async def __aexit__(self,*args): return None
    async def send(self,raw):
        self.request = json.loads(raw)
        assert self.request['method'] == 'logsSubscribe'
        assert self.request['params'][0]['mentions'] == [fixture['wallet']]
    async def recv(self): return json.dumps({'jsonrpc':'2.0','id':self.request['id'],'result':5})
    def __aiter__(self): return self
    async def __anext__(self):
        sequence = fixture['forward_signatures']
        if self.index >= 3:
            await asyncio.Future()
        index = self.index; self.index += 1
        await asyncio.sleep(.3 if index == 0 else .05 if index == 1 else 10)
        signature = sequence[0] if index < 2 else sequence[1]
        raw = fixture['transactions'][signature]
        return json.dumps({'jsonrpc':'2.0','method':'logsNotification','params':{'subscription':5,
            'result':{'context':{'slot':raw['slot']},'value':{'signature':signature,'err':None,'logs':['Synthetic offline browser notification']}}}})
def synthetic_connect(url,**kwargs):
    assert url == 'wss://api.mainnet-beta.solana.com'
    return SyntheticSocket()
import scanner.observer
scanner.observer.connect = synthetic_connect
save(); atexit.register(save)
'''


def synthetic_fixture(out: Path):
    """Independent pre-existing synthetic schema builder; not real-chain evidence."""
    sys.path.insert(0, str(ROOT))
    from tests.test_position_evidence import WALLET, MINT, raw_exchange
    from tests.test_discovery import base58
    stamp = int(time.time())
    signatures = [base58(i,64) for i in (6001,6002,6003,6004)]
    raws = [raw_exchange(signatures[0], 100, stamp - 3600, 0, 100_000_000),
            raw_exchange(signatures[1], 101, stamp - 1800, 100_000_000, 0),
            raw_exchange(signatures[2], 102, stamp, 0, 100_000_000),
            raw_exchange(signatures[3], 103, stamp+10, 100_000_000, 0)]
    for raw in raws:
        raw['transaction']['message']['header'] = {'numRequiredSignatures':1,'numReadonlySignedAccounts':0,'numReadonlyUnsignedAccounts':0}
        raw['synthetic_test_note'] = BANNER
    fixture = {'kind':'offline-synthetic-browser-fixture','wallet':WALLET,'mint':MINT,
        'wsol':'So11111111111111111111111111111111111111112','slot':1000,
        'transactions':dict(zip(signatures,raws)), 'forward_signatures':signatures[2:], 'entries':[
            {'signature':s,'slot':r['slot'],'blockTime':r['blockTime'],'err':None,'confirmationStatus':'confirmed'}
            for s,r in reversed(list(zip(signatures[:2],raws[:2])))]}
    (out/'fixtures.json').write_text(json.dumps(fixture,indent=2)+'\n')
    return fixture


class Launcher:
    def __init__(self, out: Path, env: dict[str,str]):
        self.out, self.env, self.server = out, env, None
        self.log = []

    def start(self):
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1',0)); port = reserved.getsockname()[1]
        self.server = subprocess.Popen([str(ROOT/'run.sh'),'--data-dir',str(self.out/'data'),
            '--port',str(port),'--no-browser'], cwd=ROOT, env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        lines = queue.Queue()
        def drain():
            for line in self.server.stdout:
                self.log.append(re.sub(r'#session=[A-Za-z0-9_-]+','#session=[redacted]',line.rstrip()))
                (self.out/'launcher.log').write_text('\n'.join(self.log)+'\n')
                lines.put(line)
        threading.Thread(target=drain, daemon=True).start()
        deadline = time.monotonic()+30
        while time.monotonic()<deadline:
            if self.server.poll() is not None:
                raise AssertionError('Actual run.sh exited before readiness: '+'; '.join(self.log[-8:]))
            try: line = lines.get(timeout=.5)
            except queue.Empty: continue
            match = re.search(r'http://127\.0\.0\.1:\d+/#session=[A-Za-z0-9_-]+',line)
            if match:
                self.url = match.group(0); self.base = self.url.split('/#')[0]
                return self.url
        raise AssertionError('Actual run.sh startup timed out')

    def stop(self):
        if self.server and self.server.poll() is None:
            self.server.send_signal(signal.SIGTERM)
            try: self.server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.server.kill(); self.server.wait(timeout=5)
        (self.out/'launcher.log').write_text('\n'.join(self.log)+'\n')


def run(args):
    from playwright.sync_api import sync_playwright, expect
    out = args.output.absolute(); out.mkdir(parents=True,exist_ok=False)
    result = {'kind':'actual-launcher-offline-synthetic-screening-browser','state':'INCOMPLETE',
        'software_functionality':'INCOMPLETE','genuine_live_evidence':'NOT_RUN_IN_OFFLINE_BROWSER',
        'full_historical_acceptance':'BLOCKED','PRODUCT_READY':False,'cases':[],
        'limitations':['Synthetic provider fixtures validate software mechanics, not chain authenticity or actual copied fills.']}
    def save(): (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    save()
    fixture = synthetic_fixture(out)
    hooks = out/'hooks'; hooks.mkdir(); (hooks/'sitecustomize.py').write_text(GUARD_SOURCE)
    env = {k:v for k,v in os.environ.items() if k not in ('HELIUS_API_KEY','JUPITER_API_KEY','JUP_API_KEY')}
    env.update(PYTHONPATH=str(hooks)+os.pathsep+str(ROOT), SCREENING_BROWSER_FIXTURES=str(out/'fixtures.json'),
        SCREENING_BROWSER_GUARD=str(out/'guards.json'))
    from scanner.storage import Store
    from scanner.config import LIMITS
    store = Store(out/'data'); settings = store.get('configuration','settings',{'limits':dict(LIMITS)})
    settings['refresh_minutes'] = 0; store.put('configuration','settings',settings); store.close()
    launcher = Launcher(out,env)
    try:
        launcher.start()
        pw = sync_playwright().start()
        browser = pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
        page = browser.new_page(viewport={'width':1440,'height':1000}); errors=[]; external=[]; api_trace=[]
        page.on('pageerror',lambda err:errors.append(str(err)))
        page.on('request',lambda req:external.append(req.url) if not req.url.startswith(launcher.base+'/') else None)
        def trace(response):
            if response.url.startswith(launcher.base+'/api/'):
                api_trace.append({'method':response.request.method,'path':response.url.removeprefix(launcher.base),'status':response.status})
        page.on('response',trace)
        assert page.request.get(launcher.base+'/api/state').status == 401
        page.goto(launcher.url)
        page.get_by_role('button',name='Discover',exact=True).wait_for()
        def capture(name):
            page.evaluate('''message => {let b=document.getElementById('synthetic-browser-test-banner');if(!b){b=document.createElement('div');b.id='synthetic-browser-test-banner';b.style.cssText='position:sticky;top:0;z-index:9999;padding:12px;background:#571a21;color:#fff;text-align:center;font:700 14px sans-serif';document.body.prepend(b)}b.textContent=message}''',BANNER)
            for width,height,label in ((1440,1000,'desktop'),(390,844,'mobile')):
                page.set_viewport_size({'width':width,'height':height});page.evaluate('scrollTo(0,0)');page.wait_for_timeout(100)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth&&scrollX===0'),name+' has horizontal overflow'
                page.screenshot(path=str(out/(name+'-'+label+'.png')),full_page=True)
            page.set_viewport_size({'width':1440,'height':1000})
        # The actual frontend initiates every workflow mutation.
        page.get_by_text('Import a public candidate list',exact=True).click()
        page.get_by_label('Public Solana addresses',exact=True).fill(fixture['wallet'])
        with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/discovery/import')) as imported:
            page.get_by_role('button',name='Save public list',exact=True).click()
        assert imported.value.status==200,imported.value.text()
        cohort_id = imported.value.json()['cohort_id']
        imported_candidate = page.request.get(launcher.base+'/api/discovery/'+cohort_id).json()['candidates'][0]
        assert not imported_candidate.get('validation',{}).get('identity_verified')
        result['cases'].append({'case':'import-address-is-not-identity','state':'PASS','cohort_id':cohort_id})
        capture('01-import')
        # Remaining selectors follow the screening/observation API and UI.
        workflow(page,launcher,out,fixture,cohort_id,capture,result,expect)
        assert not errors,errors
        assert not external,external
        result.update(state='PASS',software_functionality='PASS_IN_SYNTHETIC_BROWSER_SCOPE',
            javascript_errors=errors,external_browser_requests=external,api_trace=api_trace,
            actual_launcher=str(ROOT/'run.sh'),browser='Chromium '+browser.version)
        browser.close()
    except Exception as error:
        safe_error = re.sub(r'scanner_session=[^\s]+', 'scanner_session=[redacted]', str(error))
        safe_error = re.sub(r'#session=[A-Za-z0-9_-]+', '#session=[redacted]', safe_error)
        result.update(state='FAILED',reason=type(error).__name__+': '+safe_error)
        if 'page' in locals():
            try:
                page.screenshot(path=str(out/'failure.png'),full_page=True)
                (out/'failure-dom.html').write_text(page.content())
            except Exception: pass
        print(result['reason'],file=sys.stderr)
    finally:
        if 'pw' in locals(): pw.stop()
        launcher.stop()
        result['launcher_stopped'] = True
        if (out/'guards.json').exists():
            guards = json.loads((out/'guards.json').read_text());result['offline_guards']=guards
            if guards['external_provider_requests'] or guards['credential_lookups'] or guards['blocked_requests']:
                result['state']='FAILED'
        save()
    return 0 if result['state']=='PASS' else 1


def workflow(page,launcher,out,fixture,cohort_id,capture,result,expect):
    from decimal import Decimal
    base = launcher.base
    def get(path):
        response = page.request.get(launcher.base+path)
        assert response.status==200,response.text()
        return response.json()
    def until(callback,description,seconds=30):
        deadline = time.monotonic()+seconds
        latest = None
        while time.monotonic()<deadline:
            latest = callback()
            if latest: return latest
            page.wait_for_timeout(150)
        raise AssertionError(description+' timed out')
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/discovery/'+cohort_id+'/identity')) as identity:
        page.get_by_role('button',name='Check native identity',exact=True).click()
    assert identity.value.status==200,identity.value.text()
    cohort = get('/api/discovery/'+cohort_id)
    assert cohort['candidates'][0]['validation']['identity_verified'] is True
    assert cohort['audit_plan']['research_order'][0]['identity_state']=='PASS'
    expect(page.get_by_text('Signer verified',exact=True).first).to_be_visible()
    capture('02-native-identity')
    result['cases'].append({'case':'source-backed-native-identity-with-test-fixtures','state':'PASS'})
    page.get_by_label('Select '+fixture['wallet']+' for audit',exact=True).check()
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/discovery/'+cohort_id+'/audit')) as audit:
        page.get_by_role('button',name='Audit candidates (1)',exact=True).click()
    assert audit.value.status==200,audit.value.text()
    scan_id = audit.value.json()['scan_id']
    report = until(lambda:next((r for r in get('/api/state?report_view=summary')['reports'] if r.get('scan_id')==scan_id),None),'Public sample report')
    report = get('/api/reports/'+report['id'])
    assert report['qualification']['qualified'] is False
    assert report['coverage'].get('history_scope_complete') is not True
    result['cases'].append({'case':'bounded-native-sample-report','state':'PASS','report_id':report['id'],'strict_qualified':False})
    page.get_by_role('button',name='Research',exact=True).click()
    page.get_by_label('Report to screen',exact=True).select_option(report['id'])
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/screenings')) as screened:
        page.get_by_role('button',name='Screen and save assessment',exact=True).click()
    assert screened.value.status==200,screened.value.text()
    screening = screened.value.json();screening_id=screening['id']
    assert screening['identity']['state']=='PASS'
    assert screening['strict_qualification']['qualified'] is False
    assert screening['result'] in ('insufficient_evidence','worth_observing')
    expect(page.get_by_text('Strict financial qualification',exact=True)).to_be_visible()
    expect(page.get_by_text('Collection scope and stop reason',exact=True)).to_be_visible()
    capture('03-screening')
    with page.expect_download() as download:
        page.get_by_role('link',name='Export screening',exact=False).click()
    shutil.copyfile(download.value.path(),out/'screening-export.json')
    assert json.loads((out/'screening-export.json').read_text())==screening
    page.get_by_role('button',name='Inspect original report',exact=True).click()
    page.get_by_role('tab',name=re.compile('^Source evidence')).click()
    page.get_by_role('button',name='Inspect record',exact=True).first.click()
    expect(page.get_by_role('button',name='Close evidence',exact=True)).to_be_visible()
    capture('04-source-inspection')
    page.get_by_role('button',name='Close evidence',exact=True).click()
    page.get_by_role('button',name='Research',exact=True).click()
    page.get_by_role('button',name='Reopen saved assessment',exact=True).click()
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/watchlist')) as shortlisted:
        page.get_by_role('button',name='Save to shortlist',exact=True).click()
    assert shortlisted.value.status==200,shortlisted.value.text()
    expect(page.get_by_role('button',name='Shortlisted',exact=True)).to_be_visible()
    assert any(item['address']==fixture['wallet'] for item in get('/api/state?report_view=summary')['watchlist'])
    result['cases'].append({'case':'saved-screening-inspect-shortlist-export','state':'PASS','screening_id':screening_id,'result':screening['result']})
    for name,value in (('Simulated capital (SOL)','2'),('Fixed entry (SOL)','0.1'),
                       ('Reaction delay (seconds)','1'),('Signal budget','5'),('Quote budget','5'),
                       ('Observation duration (minutes)','2')):
        page.get_by_role('spinbutton',name=re.compile('^'+re.escape(name))).fill(value)
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/observations')) as started:
        page.get_by_role('button',name='Start quote-only observation',exact=True).click()
    assert started.value.status==200,started.value.text()
    initial = started.value.json();run_id=initial['id'];original_settings=deepcopy(initial['settings'])
    assert initial['settings']['reaction_delay_seconds']==1
    assert initial['summary']['open_positions']==0
    observed = until(lambda:(lambda r:r if r['summary']['open_positions']==1 else None)(get('/api/observations/'+run_id)),'Delayed first paper entry')
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/observations/'+run_id+'/mark')) as marked:
        page.get_by_role('button',name='Request current open-position quotes',exact=True).click()
    assert marked.value.status==200,marked.value.text()
    open_mark = marked.value.json()
    assert open_mark['summary']['open_positions']==1
    assert Decimal(open_mark['summary']['economic_pnl_sol'])<0
    capture('05-open-paper-loss')
    observed = until(lambda:(lambda r:r if r['summary']['closed_positions']==1 else None)(get('/api/observations/'+run_id)),'First-sale paper exit')
    assert observed['summary']['signal_count']==2,'Duplicate notifications created duplicate signals'
    assert observed['summary']['quote_count']==3
    assert Decimal(observed['summary']['realised_pnl_sol'])<0
    assert observed['settings']==original_settings
    for request in observed['quote_requests']:
        if request.get('signal_id'):
            assert datetime.fromisoformat(request['quote']['request_started_at']) >= datetime.fromisoformat(request['due_at'])
    page.get_by_role('button',name='Reopen saved observation',exact=True).click()
    capture('06-closed-paper-loss')
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/observations/'+run_id+'/stop')) as stopped:
        page.get_by_role('button',name='Stop observation',exact=True).click()
    assert stopped.value.status==200,stopped.value.text()
    final = stopped.value.json();assert final['status']=='stopped'
    page.get_by_role('spinbutton',name=re.compile('^Simulated capital')).fill('3')
    page.get_by_role('button',name='Reopen saved observation',exact=True).click()
    assert get('/api/observations/'+run_id)['settings']==original_settings
    with page.expect_download() as download:
        page.get_by_role('link',name='Export paper observation',exact=False).click()
    shutil.copyfile(download.value.path(),out/'observation-export.json')
    exported = json.loads((out/'observation-export.json').read_text())
    assert exported['run']['id']==run_id and exported['run']['settings']==original_settings
    assert exported['run']['summary']['closed_positions']==1
    assert exported['settings_evidence']['settings']==original_settings
    result['cases'].append({'case':'delayed-quotes-open-loss-first-sale-exit-stop-reopen-export','state':'PASS',
        'run_id':run_id,'signal_count':2,'quote_count':3,'realised_pnl_sol':final['summary']['realised_pnl_sol'],
        'frozen_settings':True,'duplicate_events_deduped':True})
    # Stop and reopen the real launcher with the same disposable durable store.
    launcher.stop();launcher.start();page.goto(launcher.url)
    page.get_by_role('button',name='Research',exact=True).click()
    page.get_by_label('Saved screening assessment',exact=True).select_option(screening_id)
    page.get_by_role('button',name='Reopen saved assessment',exact=True).click()
    page.get_by_label('Saved paper observation',exact=True).select_option(run_id)
    page.get_by_role('button',name='Reopen saved observation',exact=True).click()
    recovered = get('/api/observations/'+run_id)
    assert recovered['status']=='stopped' and recovered['settings']==original_settings
    assert recovered['summary']['closed_positions']==1
    assert get('/api/screenings/'+screening_id)==screening
    capture('07-restarted-persistent-observation')
    result['cases'].append({'case':'actual-launcher-restart-persistence','state':'PASS','settings_frozen':True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--chromium',default='/usr/bin/chromium')
    return run(parser.parse_args())


if __name__=='__main__':
    raise SystemExit(main())
