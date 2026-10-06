import json, re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
log = Path('/workspace/research-search-b-live/run-ui.log').read_text()
url = re.search(r'(http://127\.0\.0\.1:\d+/#session=\S+)', log).group(1)
base = url.split('/#')[0]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else '/workspace/research-search-b-live/screens')
OUT.mkdir(parents=True, exist_ok=True)
ing = json.load(open('/workspace/research-search-b-live/INGEST_RESULT.json'))
res = {'errors': [], 'external': [], 'shots': []}
def shot(page, name):
    p = OUT / f'{name}.png'; page.screenshot(path=str(p)); res['shots'].append(str(p))
def nav(page, name):
    page.get_by_role('button', name='Search', exact=True).wait_for()
    op = page.get_by_role('button', name='Open navigation')
    if op.count(): op.click()
    page.get_by_label('Main navigation').get_by_role('button', name=name, exact=True).click()
    cl = page.get_by_role('button', name='Close navigation')
    if cl.count() and cl.is_visible(): cl.click()
with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, args=['--no-sandbox'])
    page = b.new_page(viewport={'width': 390, 'height': 844})
    page.on('pageerror', lambda e: res['errors'].append(str(e)))
    page.on('request', lambda r: res['external'].append(r.url) if not r.url.startswith(('http://127.0.0.1', 'http://localhost')) else None)
    res['unauth_state_status'] = page.request.get(f'{base}/api/state').status
    page.goto(url)
    nav(page, 'Search')
    expect(page.get_by_text('Ranked-100 cached shortlist')).to_be_visible()
    page.wait_for_timeout(1500)
    shot(page, '01-search-top-phone')
    rs = page.locator('[data-research-screen]')
    if rs.count():
        rs.first.scroll_into_view_if_needed(); page.wait_for_timeout(300); shot(page, '02-research-screen-phone')
        res['research_screen_text'] = rs.first.inner_text()[:1500]
    cards = page.locator('[data-ranked-cards]')
    res['ranked_cards'] = cards.count()
    # find the card for CccSh2 / A6PSQF
    for short in ('CccSh2', 'A6PSQF', 'gtfoTE'):
        loc = page.get_by_text(re.compile(short)).first
        if loc.count():
            loc.scroll_into_view_if_needed(); page.wait_for_timeout(300); shot(page, f'03-ranked-row-{short}-phone')
    # open report for A6PSQF via Saved subset reports / Open report
    ids = {a[:6]: r.get('report_id') for a, r in ing['results'].items()}
    left, right = ids['CccSh2'], ids['A6PSQF']
    try:
        page.get_by_label('Compare left report').select_option(left)
        page.get_by_label('Compare right report').select_option(right)
        page.get_by_role('button', name='Compare saved reports').click()
        cmp_ = page.locator('[data-research-compare]'); expect(cmp_).to_be_visible()
        cmp_.scroll_into_view_if_needed(); page.wait_for_timeout(400); shot(page, '04-compare-CccSh2-vs-A6PSQF-phone')
        res['compare_text'] = cmp_.inner_text()[:2500]
    except Exception as e:
        res['compare_error'] = repr(e)[:500]
    try:
        page.get_by_text('Saved subset reports').scroll_into_view_if_needed()
        shot(page, '05-saved-reports-phone')
        btns = page.get_by_role('button', name=re.compile('Open report|Reopen report'))
        res['open_report_buttons'] = btns.count()
    except Exception as e:
        res['saved_error'] = repr(e)[:300]
    # open A6PSQF report via API-driven route: click the row's Open report button
    try:
        row = page.locator('[data-ranked-cards]').filter(has_text=re.compile('A6PSQF')).first
        row.get_by_role('button', name=re.compile('Open report')).click()
        page.get_by_text('Research profile').first.wait_for(timeout=15000)
        page.wait_for_timeout(800); shot(page, '06-report-A6PSQF-top-phone')
        ws = page.locator('[data-subset-worksheet], [data-wallet-analytics]').first
        if ws.count():
            ws.scroll_into_view_if_needed(); page.wait_for_timeout(300); shot(page, '07-report-A6PSQF-worksheet-phone')
    except Exception as e:
        res['report_error'] = repr(e)[:500]
    b.close()
(OUT / 'SCREENSHOT_RUN.json').write_text(json.dumps(res, indent=2))
print(json.dumps({k: (v if k not in ('research_screen_text', 'compare_text') else v[:600]) for k, v in res.items()}, indent=1))
