from pathlib import Path
import argparse, importlib.util, json, re, time
root = Path('/workspace/solana-wallet-scanner')
spec=importlib.util.spec_from_file_location('browser_mechanics',root/'tools/screening_browser.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
b.GUARD_SOURCE=b.GUARD_SOURCE.replace("event('synthetic_subscriptions','connect','address-specific logsSubscribe')", "event('synthetic_subscriptions','connect','address-specific logsSubscribe')\n        raise OSError('Synthetic subscription unavailable')")
def workflow(page,launcher,out,fixture,cohort_id,capture,result,expect):
    def get(path):
        r=page.request.get(launcher.base+path);assert r.status==200,r.text();return r.json()
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/identity')) as identity:
        page.get_by_role('button',name='Check native identity',exact=True).click()
    assert identity.value.status==200
    expect(page.get_by_text('Signer verified',exact=True).first).to_be_visible()
    page.get_by_label('Select '+fixture['wallet']+' for audit',exact=True).check()
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/audit')) as audit:
        page.get_by_role('button',name='Audit candidates (1)',exact=True).click()
    scan_id=audit.value.json()['scan_id'];report=None
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        report=next((r for r in get('/api/state?report_view=summary')['reports'] if r.get('scan_id')==scan_id),None)
        if report:break
        page.wait_for_timeout(100)
    assert report
    page.get_by_role('button',name='Research',exact=True).click()
    page.get_by_label('Report to screen',exact=True).select_option(report['id'])
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/screenings')) as screened:
        page.get_by_role('button',name='Screen and save assessment',exact=True).click()
    assert screened.value.status==200
    with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/observations')) as started:
        page.get_by_role('button',name='Start quote-only observation',exact=True).click()
    assert started.value.status==200
    run_id=started.value.json()['id']
    deadline=time.monotonic()+10;run=None
    while time.monotonic()<deadline:
        run=get('/api/observations/'+run_id)
        if run['observer']['status']=='reconnecting':break
        page.wait_for_timeout(100)
    assert run['status']=='running' and run['observer']['status']=='reconnecting',run
    page.get_by_role('button',name='Reopen saved observation',exact=True).click()
    page.wait_for_timeout(300)
    visible=page.locator('body').inner_text()
    (out/'reconnecting-observation.json').write_text(json.dumps(run,indent=2))
    (out/'reconnecting-visible-text.txt').write_text(visible)
    connection_visible='Reconnecting' in visible or 'reconnecting' in visible
    capture('02-reconnecting-subscription')
    result['cases'].append({'case':'synthetic-reconnecting-provider-is-visible','state':'PASS' if connection_visible else 'CONFIRMED_UX_GAP','paper_status':run['status'],'observer_status':run['observer']['status'],'connection_visible':connection_visible})
    page.get_by_role('button',name='Stop observation',exact=True).click()
    expect(page.get_by_role('button',name='Resume observation',exact=True)).to_be_enabled()
b.workflow=workflow
raise SystemExit(b.run(argparse.Namespace(output=root/'evidence/screening-forward-research/frontend-reconnecting-fixed-20261004',chromium='/usr/bin/chromium')))
