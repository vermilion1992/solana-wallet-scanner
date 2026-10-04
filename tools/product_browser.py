#!/usr/bin/env python3
"""Actual guarded CLI/Chromium archive workflow; synthetic and partial real only."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]


def run(args):
    out=args.output.absolute();out.mkdir(parents=True,exist_ok=False)
    result={'kind':'offline-product-browser','state':'INCOMPLETE','cases':[],
            'real_acceptance':'BLOCKED','reason':'Synthetic development and partial genuine inputs cannot close B3.'}
    def save(): (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    save()
    try:
        from playwright.sync_api import sync_playwright,expect
    except ImportError:
        result.update(state='BLOCKED',reason='Configured browser interpreter lacks Playwright.');save();return 2
    data=out/'data';env={k:v for k,v in os.environ.items() if k!='HELIUS_API_KEY'}
    import shutil
    python=os.path.abspath(shutil.which(args.python) or args.python)
    subprocess.run([python,str(ROOT/'tools/archive_input.py'),'--bundle',str(ROOT/'scanner/examples/archive-wallet-synthetic.json'),
                    '--output',str(out/'synthetic-input.zip')],cwd=ROOT,env=env,check=True)
    corpus=args.real_corpus.absolute()
    if (corpus/'manifest.json.gz').is_file():
        subprocess.run([python,str(ROOT/'tools/archive_input.py'),'--partial-cache',str(corpus),'--output',str(out/'partial-real-input.zip')],cwd=ROOT,env=env,check=True)
    indexed = getattr(args, 'indexed_archive', None)
    if getattr(args, 'inventory_snapshots', False) and indexed is None:
        raise ValueError('Inventory snapshot checks require the genuine indexed archive')
    if indexed is not None:
        if not getattr(args, 'indexed_expected_fees', None):
            raise ValueError('Indexed browser replay requires independently worked expected fees')
        shutil.copyfile(indexed, out/'indexed-input.zip')
        expect.set_options(timeout=120000)
        result['assertion_timeout_ms'] = 120000
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=subprocess.Popen([python,str(ROOT/'tools/guarded_launcher.py'),'--data',str(data),'--port',str(port),
                             '--guard',str(out/'guards.json')],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    lines=queue.Queue()
    def drain():
        for line in server.stdout:lines.put(line)
    threading.Thread(target=drain,daemon=True).start()
    try:
        deadline=time.monotonic()+30;url=None
        while time.monotonic()<deadline:
            if server.poll() is not None:raise AssertionError('Guarded CLI exited before readiness')
            try:line=lines.get(timeout=1)
            except queue.Empty:continue
            match=re.search(r'http://127\.0\.0\.1:\d+/#session=[A-Za-z0-9_-]+',line)
            if match:url=match.group(0);break
        assert url,'Guarded CLI did not become ready'
        base=url.split('/#')[0];captures=0
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--no-sandbox'])
            page=browser.new_page(viewport={'width':1440,'height':900});errors=[];external=[];view_transport=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('request',lambda r:external.append(r.url) if not r.url.startswith(base+'/') else None)
            def record_view(response):
                path=response.url.removeprefix(base)
                if response.status==200 and response.request.method=='GET' and (path.startswith('/api/state') or re.fullmatch(r'/api/reports/[a-f0-9]{32}(?:\?.*)?',path)):
                    view_transport.append({'path':path,'status':response.status,
                                           'bytes':int(response.headers.get('content-length','0'))})
            page.on('response',record_view)
            assert page.request.get(base+'/api/state').status==401
            page.goto(url);page.get_by_role('button',name='Find wallet candidates',exact=True).first.wait_for()
            usage=page.request.get(base+'/api/state?report_view=summary').json()['usage']
            def export_download(identifier, destination):
                # Browser downloads stream full immutable bytes without routing a
                # potentially huge base64 APIResponse through Playwright's pipe.
                page.get_by_role('tab',name=re.compile('^Source evidence')).click()
                with page.expect_download() as downloaded:
                    page.get_by_role('link',name='Export report JSON',exact=False).click()
                shutil.copyfile(downloaded.value.path(), destination)
                page.get_by_role('tab',name='Summary',exact=True).click()
                assert page.locator('[data-archive-report-id]').get_attribute('data-archive-report-id') == identifier
            def export_hash(identifier):
                # Independent loopback HTTP read, with the same browser session;
                # never expose cookies or copy the report through the JS protocol.
                from urllib.request import Request, urlopen
                cookies=page.context.cookies(base)
                cookie='; '.join(item['name']+'='+item['value'] for item in cookies)
                digest=hashlib.sha256()
                with urlopen(Request(base+f'/api/export/reports/{identifier}.json',
                                     headers={'Cookie':cookie}), timeout=120) as response:
                    assert response.status == 200
                    for chunk in iter(lambda:response.read(1024*1024),b''):
                        digest.update(chunk)
                return digest.hexdigest()
            def capture(name):
                nonlocal captures
                for width,height,device in ((1440,900,'desktop'),(390,844,'mobile')):
                    page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(120)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth&&scrollX===0')
                    assert page.evaluate("""() => [...document.querySelectorAll('.report-metric > small, .all-metrics-grid > div > small, .metric-interval-detail p, .selected-cohort-values > div, .selected-open-lot > span, .selected-cohort-window .small-note')]
                        .filter(element => element.getClientRects().length)
                        .every(element => element.scrollWidth <= element.clientWidth + 1 && element.scrollHeight <= element.clientHeight + 1)"""), 'Metric dependency text is clipped inside its field'
                    page.screenshot(path=str(out/f'{name}-{device}.png'),full_page=True);captures+=1
                page.set_viewport_size({'width':1440,'height':900})
            def selected_cohort_ui(report, label):
                observations=report.get('coverage',{}).get('wallet_evidence',{}).get('query_accounting',{}).get('selected_cohort_observations')
                panel=page.locator('[data-selected-cohort-freshness]')
                assert isinstance(observations,dict), 'Current archive report must retain its selected-cohort observations'
                if report.get('archive_accounting',{}).get('dataset')=='synthetic':
                    assert report.get('source')=='demo' and report['qualification']['qualified'] is False
                    expect(panel).to_have_count(0)
                    result.setdefault('selected_cohort_ui_assertions',[]).append({'case':label,'state':'PASS',
                        'dataset':'synthetic','source':'demo','panel_absent':True,
                        'scope':'Synthetic demonstration does not render the live selected-record panel',
                        'wallet_qualification':False})
                    return
                assert report.get('source')=='live' and report.get('archive_accounting',{}).get('dataset')=='real'
                expect(panel).to_have_attribute('data-selected-cohort-freshness','current')
                expect(panel).to_contain_text('selected records only')
                expect(panel).to_contain_text('wallet-wide profit or a copy-trading recommendation')
                # Open the real UI rather than relying on hidden DOM strings.
                outer=panel.locator('details.selected-cohort-details')
                if outer.get_attribute('open') is None:
                    outer.locator(':scope > summary').click()
                expected_windows=(('report_period','Reporting period'),('four_weeks','Independent 28 days'),('verification_90d','Independent 90 days'))
                for key,name in expected_windows:
                    window=panel.locator('[data-selected-cohort-window="'+name+'"]')
                    if window.get_attribute('open') is None:
                        window.locator(':scope > summary').click()
                    expect(window).to_be_visible()
                    interval=observations.get('intervals',{}).get(key)
                    assert isinstance(interval,dict) and isinstance(interval.get('closed_cohort'),dict) and isinstance(interval.get('disposed_units'),dict)
                    expect(window).to_contain_text('Completed holdings in selected records')
                    expect(window).to_contain_text('Disposed units in selected records')
                    closed=interval['closed_cohort'];disposed=interval['disposed_units']
                    values=window.locator('.selected-cohort-values').first
                    closed_money=(closed.get('population_state')=='PASS' and closed.get('monetary_state')=='PASS'
                                  and type(closed.get('candidate_count')) is int and closed['candidate_count']>0)
                    profit=values.locator('div').filter(has=page.get_by_text('Conditional closed-holding P&L',exact=True)).locator('strong')
                    if closed_money and isinstance(closed.get('conditional_profit_sol'),str):
                        expect(profit).to_have_attribute('title',closed['conditional_profit_sol'])
                    else:
                        expect(profit).to_have_text('Unknown')
                    timing_known=(closed.get('population_state')=='PASS' and closed.get('timing_state')=='PASS'
                                  and type(closed.get('candidate_count')) is int and closed['candidate_count']>0)
                    hold=values.locator('div').filter(has=page.get_by_text('Median completed hold',exact=True)).locator('strong')
                    if timing_known and isinstance(closed.get('conditional_median_hold_hours'),str):
                        expect(hold).to_have_attribute('title',closed['conditional_median_hold_hours'])
                    else:
                        expect(hold).to_have_text('Unknown')
                    disposed_money=(disposed.get('quantity_state')=='PASS' and disposed.get('monetary_state')=='PASS'
                                    and type(disposed.get('candidate_sale_count')) is int and disposed['candidate_sale_count']>0)
                    disposal=window.locator('.selected-cohort-values').nth(1).locator('div').filter(has=page.get_by_text('Conditional disposal P&L',exact=True)).locator('strong')
                    if disposed_money and isinstance(disposed.get('conditional_profit_sol'),str):
                        expect(disposal).to_have_attribute('title',disposed['conditional_profit_sol'])
                    else:
                        expect(disposal).to_have_text('Unknown')
                    assert closed.get('qualification') is False and disposed.get('qualification') is False
                stock=panel.locator('[data-selected-open-stock]')
                if stock.get_attribute('open') is None:
                    stock.locator(':scope > summary').click()
                expect(stock).to_be_visible()
                expect(stock).to_contain_text('Acquisition cost and market value are separate')
                assert observations.get('qualification') is False and observations.get('wallet_population_state')=='UNKNOWN'
                result.setdefault('selected_cohort_ui_assertions',[]).append({'case':label,'state':'PASS',
                    'freshness':'current','independent_intervals':3,'open_stock_visible':True,'wallet_qualification':False})
            def import_ui(file, dataset):
                page.get_by_role('button',name='Discover',exact=True).click()
                page.get_by_role('button',name='Advanced manual scan',exact=True).click()
                with page.expect_response(lambda r:r.url.endswith('/api/archives/import') and r.request.method=='POST') as pending:
                    page.get_by_label('Wallet evidence ZIP (up to 20 MiB)',exact=True).set_input_files(str(file))
                assert pending.value.status==200,pending.value.text()
                panel=page.locator(f'[data-archive-accounting="{dataset}"]')
                expect(panel).to_be_visible()
                identifier=panel.get_attribute('data-archive-report-id')
                report=page.request.get(base+'/api/reports/'+identifier+'?view=display').json()
                assert report['qualification']['qualified'] is False
                selected_cohort_ui(report,'import-'+file.stem)
                return report
            def inventory_ui(report, label):
                # Expectations were worked from three retained RPC responses,
                # not from the application's component implementation. Different
                # context slots cannot establish one aggregate/boundary balance.
                inventory=report['coverage']['wallet_evidence']['inventory_observations']
                components=inventory['components']
                legacy=components['token_programs']['TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA']
                token2022=components['token_programs']['TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb']
                assert inventory['version']=='current-inventory-evidence-v1'
                assert inventory['historical_population_state']=='UNKNOWN' and inventory['qualification'] is False
                assert components['same_slot_inventory']['state']=='UNKNOWN'
                assert components['report_boundaries']['state']=='UNKNOWN'
                native=components['native_lamports']
                assert native['state']=='PASS' and legacy['state']=='PASS' and token2022['state']=='PASS'
                assert [(p['slot'],p['lamports']) for p in native['observations']]==[(453173211,'650240')]
                assert [(p['slot'],p['account_count']) for p in legacy['observations']]==[(453173213,0)]
                assert [(p['slot'],p['account_count']) for p in token2022['observations']]==[(453173215,1)]
                panel=page.locator('[data-inventory-observations]')
                expect(panel).to_have_attribute('data-inventory-observations','current')
                expect(panel).to_contain_text('These observations do not establish one combined wallet balance')
                for name,amount,slot in (('Native SOL','0.00065024 SOL','453,173,211'),
                                        ('Legacy token accounts','0 accounts','453,173,213'),
                                        ('Token2022 accounts','1 account','453,173,215')):
                    row=panel.locator('[data-inventory-component="'+name+'"]')
                    expect(row).to_contain_text(amount)
                    expect(row).to_contain_text('Slot '+slot)
                    expect(row).to_contain_text('Observed')
                panel.locator('[data-inventory-component="Native SOL"]').get_by_role('button').first.click()
                expect(page.get_by_role('button',name='Close evidence',exact=True)).to_be_visible()
                page.get_by_role('button',name='Close evidence',exact=True).click()
                result.setdefault('inventory_ui_assertions',[]).append({'case':label,'state':'PASS',
                    'native_lamports':'650240','legacy_accounts':0,'token2022_accounts':1,
                    'context_slots':[453173211,453173213,453173215],
                    'source_inspection':True,'combined_inventory':'UNKNOWN',
                    'report_boundaries':'UNKNOWN','wallet_qualification':False})
            parent=import_ui(out/'synthetic-input.zip','synthetic');pid=parent['id']
            assert parent['metrics']['profit_sol']['value']=='0.49995' and parent['metrics']['completed_positions']['value']=='5'
            original=page.request.get(base+f'/api/export/reports/{pid}.json').body()
            (out/'synthetic-parent.json').write_bytes(original);capture('synthetic-positive')
            page.get_by_text('Inspect metric evidence requirements',exact=True).click()
            expect(page.locator('[data-archive-metric="profit_sol"]')).to_contain_text('PASS')
            page.get_by_role('tab',name=re.compile('^Source evidence')).click()
            page.get_by_role('button',name='Inspect record',exact=True).first.click()
            expect(page.get_by_role('button',name='Close evidence',exact=True)).to_be_visible()
            page.get_by_role('button',name='Close evidence',exact=True).click()
            with page.expect_download() as downloaded:page.get_by_role('link',name='Export report JSON',exact=False).click()
            raw=Path(downloaded.value.path()).read_bytes();assert json.loads(raw)['id']==pid
            (out/'synthetic-ui-export.json').write_bytes(raw)
            page.get_by_role('tab',name='Summary',exact=True).click()
            result['cases'].append({'case':'synthetic-positive-ui-import-accounting-source-inspection-export','state':'PASS','report_id':pid})
            def rebuild_ui(expected_profit, expected_economic, label):
                prior=page.locator('[data-archive-accounting="synthetic"]').get_attribute('data-archive-report-id')
                with page.expect_response(lambda r:r.request.method=='POST' and '/reports/' in r.url and r.url.endswith('/rebuild')) as pending:
                    page.get_by_role('button',name='Rebuild from saved records',exact=True).click()
                assert pending.value.status==200,pending.value.text()
                panel=page.locator('[data-archive-accounting="synthetic"]')
                expect(panel).to_have_attribute('data-archive-report-id',re.compile('^(?!'+prior+'$)[a-f0-9]{32}$'))
                child=page.request.get(base+'/api/reports/'+panel.get_attribute('data-archive-report-id')+'?view=display').json()
                assert child['metrics']['profit_sol']['value']==expected_profit
                assert child['metrics']['economic_pnl_sol']['value']==expected_economic
                assert child['metrics']['observed_network_fees_sol']['value']=='0.000055'
                assert child['archive_input_hash']==parent['archive_input_hash'] and child['preset']==parent['preset'] and child['window']==parent['window']
                assert page.request.get(base+f'/api/export/reports/{pid}.json').body()==original
                assert page.request.get(base+'/api/state?report_view=summary').json()['usage']==usage
                selected_cohort_ui(child,label)
                (out/(label+'-report.json')).write_text(json.dumps(child,indent=2)+'\n')
                capture(label);result['cases'].append({'case':label,'state':'PASS','parent_unchanged':True})
            fixture=json.loads((ROOT/'scanner/examples/archive-wallet-synthetic.json').read_text())
            for name in ('valuation_hash','world_hash'):
                digest=fixture['manifest'][name];file=data/'evidence'/f'{digest}.json.gz';raw=file.read_bytes()
                try:
                    file.unlink()
                    rebuild_ui('0.49995' if name=='valuation_hash' else None,None,name+'-missing')
                finally:file.write_bytes(raw)
                rebuild_ui('0.49995','0.499955',name+'-restored')
            if (out/'partial-real-input.zip').is_file():
                real=import_ui(out/'partial-real-input.zip','real')
                assert real['metrics']['observed_network_fees_sol']['value']=='0.000240394'
                assert real['metrics']['profit_sol']['status']=='unknown'
                expect(page.locator('[data-archive-accounting="real"]')).to_contain_text('0.000240394')
                capture('genuine-partial');(out/'genuine-partial-report.json').write_text(json.dumps(real,indent=2)+'\n')
                result['cases'].append({'case':'genuine-23-record-partial-ui-import','state':'PASS','real_acceptance':'BLOCKED'})
            if indexed is not None:
                page.set_default_timeout(120000)
                real=import_ui(out/'indexed-input.zip','real')
                expect(page.locator('[data-archive-accounting="real"]')).to_have_attribute('data-archive-report-id',real['id'])
                assert real['metrics']['observed_network_fees_sol']['value']==args.indexed_expected_fees
                assert real['metrics']['profit_sol']['status']=='unknown'
                assert real['coverage']['indexed_sources']['historical_population']=='UNKNOWN'
                if getattr(args, 'inventory_snapshots', False):
                    inventory_ui(real,'indexed-inventory-import')
                export_download(real['id'], out/'indexed-partial-parent.json')
                original_indexed_hash=hashlib.sha256((out/'indexed-partial-parent.json').read_bytes()).hexdigest()
                full_indexed=json.loads((out/'indexed-partial-parent.json').read_bytes())
                assert full_indexed['id']==real['id'] and full_indexed['metrics']==real['metrics']
                assert full_indexed['coverage']['indexed_sources']['historical_population']=='UNKNOWN'
                del full_indexed
                capture('indexed-partial')
                page.get_by_role('tab',name=re.compile('^Source evidence')).click()
                page.get_by_role('button',name='Inspect record',exact=True).first.click()
                expect(page.get_by_role('button',name='Close evidence',exact=True)).to_be_visible()
                page.get_by_role('button',name='Close evidence',exact=True).click()
                page.get_by_role('tab',name='Summary',exact=True).click()
                with page.expect_response(lambda r:r.request.method=='POST' and '/reports/' in r.url and r.url.endswith('/rebuild')) as pending:
                    page.get_by_role('button',name='Rebuild from saved records',exact=True).click()
                assert pending.value.status==200,pending.value.text()
                child_id=pending.value.json()['report_id']
                expect(page.locator('[data-archive-accounting="real"]')).to_have_attribute('data-archive-report-id',child_id)
                child=page.request.get(base+'/api/reports/'+child_id+'?view=display').json()
                assert child['metrics']==real['metrics'] and child['rebuilt_from']==real['id']
                selected_cohort_ui(child,'indexed-partial-rebuilt')
                if getattr(args, 'inventory_snapshots', False):
                    inventory_ui(child,'indexed-inventory-rebuilt')
                assert export_hash(real['id'])==original_indexed_hash
                export_download(child_id, out/'indexed-partial-child.json')
                capture('indexed-partial-rebuilt')
                result['cases'].append({'case':'indexed-partial-ui-import-inspection-immutable-rebuild','state':'PASS',
                    'source_archive_sha256':hashlib.sha256(indexed.read_bytes()).hexdigest(),
                    'expected_selected_fees_sol':args.indexed_expected_fees,'parent_unchanged':True,'real_acceptance':'BLOCKED'})
            assert page.request.get(base+'/api/state?report_view=summary').json()['usage']==usage
            assert not errors and not external,(errors,external)
            assert view_transport and all(
                item['path'].endswith('?report_view=summary') if item['path'].startswith('/api/state')
                else item['path'].endswith('?view=display') for item in view_transport)
            browser.close()
            result.update(state='PASS',scope='Development archive workflow; genuine partial input is not B3',
                          captures=captures,desktop_width=1440,mobile_width=390,no_overflow=True,javascript_errors=errors,
                          external_browser_requests=external,anonymous_state=401,usage_before=usage,usage_after=usage,
                          actual_UI_json_exports=True,evidence_inspection=True,source_loss_and_exact_restoration=True,parent_unchanged=True)
            result['browser_report_transfers']=view_transport
    except Exception as exc:
        result.update(state='FAILED',reason=type(exc).__name__+': '+str(exc));raise
    finally:
        server.send_signal(signal.SIGTERM)
        try:server.wait(timeout=20)
        except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
        result['server_stopped']=True
        result['offline_guards']=json.loads((out/'guards.json').read_text())
        if any(result['offline_guards'].values()):result['state']='FAILED'
        result['artifacts']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file() and p.name!='result.json'}
        save()
    print(json.dumps({k:v for k,v in result.items() if k not in ('cases','artifacts','usage_before','usage_after')}))
    return 0 if result['state']=='PASS' else 2 if result['state']=='BLOCKED' else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--python',required=True);p.add_argument('--chromium',default='/usr/bin/chromium')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--real-corpus',type=Path,default=ROOT/'evidence/runs/real-cache')
    p.add_argument('--indexed-archive',type=Path);p.add_argument('--indexed-expected-fees')
    p.add_argument('--inventory-snapshots',action='store_true',
                   help='Check the three genuine archived inventory snapshots separately from historical completeness')
    raise SystemExit(run(p.parse_args()))
