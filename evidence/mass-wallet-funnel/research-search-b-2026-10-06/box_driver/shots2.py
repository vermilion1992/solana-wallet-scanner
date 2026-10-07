import json, re, sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
log = Path('/workspace/research-search-b-live/run-ui.log').read_text()
url = re.search(r'(http://127\.0\.0\.1:\d+/#session=\S+)', log).group(1)
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else '/workspace/research-search-b-live/screens')
targets = sys.argv[2:] or ['A6PSQF…MEvbot', 'CccSh2…tHy1eU']
res = {'errors': [], 'shots': [], 'texts': {}}
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
    page.goto(url)
    for t in targets:
        nav(page, 'Search'); expect(page.get_by_text('Ranked-100 cached shortlist')).to_be_visible(); page.wait_for_timeout(800)
        label = page.get_by_text(t, exact=True).first
        card = label.locator('xpath=ancestor::*[.//button[normalize-space()="Open report"]][1]')
        card.get_by_role('button', name='Open report').first.click()
        page.get_by_text('Research profile').first.wait_for(timeout=15000)
        page.wait_for_timeout(800)
        short = t.split('…')[0]
        p = OUT / f'06-report-{short}-top-phone.png'; page.screenshot(path=str(p)); res['shots'].append(str(p))
        for sel, nm in (('[data-subset-worksheet]', 'worksheet'), ('[data-wallet-analytics]', 'analytics')):
            loc = page.locator(sel).first
            if loc.count():
                loc.scroll_into_view_if_needed(); page.wait_for_timeout(300)
                p = OUT / f'07-report-{short}-{nm}-phone.png'; page.screenshot(path=str(p)); res['shots'].append(str(p))
                res['texts'][f'{short}-{nm}'] = loc.inner_text()[:1200]
    b.close()
(OUT / 'SCREENSHOT_RUN_REPORTS.json').write_text(json.dumps(res, indent=2))
print(json.dumps(res, indent=1)[:3500])
