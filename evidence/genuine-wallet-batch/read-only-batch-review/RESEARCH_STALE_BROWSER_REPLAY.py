"""Read-only candidate browser review using a disposable copy of the 7f archive.

This evidence script is outside application source. It never reads credentials,
alters the original database, or supplies trusted completion/accounting flags.
Run only after the parent announces the next frozen application identity.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.validate import source_manifest


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def payload_hash(db_path, identifier):
    with sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True) as db:
        row = db.execute("SELECT payload FROM records WHERE kind='reports' AND id=?", (identifier,)).fetchone()
    assert row, 'Expected preserved report is missing'
    return hashlib.sha256(row[0].encode()).hexdigest()


def sanitized_error(error):
    # Session fragments remain private even if a browser navigation times out.
    return re.sub(r'#session=[A-Za-z0-9_-]+', '#session=[withheld]', type(error).__name__ + ': ' + str(error))


def run(args):
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    before = source_manifest()
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    assert commit == args.commit and before['sha256'] == args.source_sha256
    old = ROOT / 'evidence/genuine-wallet-batch/genuine-workflow-verified'
    old_result = json.loads((old / 'result.json').read_bytes())
    parent_id = next(case['report_id'] for case in old_result['cases']
                     if case['case'] == 'raw-input-normal-report-source-inspection-json-csv')
    original_db = old / 'data/scanner.sqlite'
    original_export = old / 'parent-report.json'
    original_db_hash = file_hash(original_db)
    original_export_hash = file_hash(original_export)
    original_payload_hash = payload_hash(original_db, parent_id)
    private = Path('/workspace/qa-private') / ('research-stale-' + commit[:12] + '-' + uuid.uuid4().hex)
    private.mkdir(parents=True, mode=0o700)
    data = private / 'data'
    data.mkdir(mode=0o700)
    shutil.copy2(original_db, data / 'scanner.sqlite')
    shutil.copytree(old / 'data/evidence', data / 'evidence')
    # This disposable copy lists only the chosen genuine parent. Its exact
    # payload, scan ancestry and evidence bytes are retained unchanged.
    with sqlite3.connect(data / 'scanner.sqlite') as db:
        db.execute("DELETE FROM records WHERE kind='reports' AND id<>?", (parent_id,))
        address, saved_research = db.execute(
            "SELECT json_extract(payload,'$.address'),json_extract(payload,'$.research.version') "
            "FROM records WHERE kind='reports' AND id=?", (parent_id,)).fetchone()
    assert saved_research == 'supported-subset-research-v2'
    assert payload_hash(data / 'scanner.sqlite', parent_id) == original_payload_hash
    receipt = {'kind': 'distinct-stale-genuine-research-browser-review', 'state': 'INCOMPLETE',
               'candidate_commit': commit, 'source_sha256': before['sha256'], 'source_files': len(before['files']),
               'preserved_parent_id': parent_id, 'preserved_parent_method': saved_research,
               'original_database_sha256_before': original_db_hash,
               'original_export_sha256_before': original_export_hash,
               'parent_payload_sha256_before': original_payload_hash,
               'private_qa_outside_repository': True,
               'private_qa_path': str(private), 'cases': [], 'captures': 0,
               'PRODUCT_READY': False, 'real_acceptance': 'BLOCKED'}
    def save():
        (out / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    save()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {key: value for key, value in os.environ.items() if key != 'HELIUS_API_KEY'}
    server = subprocess.Popen([str(ROOT / '.venv/bin/python'), str(ROOT / 'tools/guarded_launcher.py'),
                               '--data', str(data), '--port', str(port), '--guard', str(out / 'guards.json')],
                              cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = queue.Queue()
    def drain():
        # Raw launcher output can contain a session fragment: private QA only.
        with (private / 'server-private.log').open('w') as log:
            for line in server.stdout:
                log.write(line)
                log.flush()
                lines.put(line)
    threading.Thread(target=drain, daemon=True).start()
    try:
        from playwright.sync_api import sync_playwright, expect
        expect.set_options(timeout=180000)
        deadline = time.monotonic() + 30
        url = None
        while time.monotonic() < deadline:
            assert server.poll() is None, 'Guarded launcher exited before readiness'
            try:
                line = lines.get(timeout=1)
            except queue.Empty:
                continue
            match = re.search(r'http://127\.0\.0\.1:\d+/#session=[A-Za-z0-9_-]+', line)
            if match:
                url = match.group(0)
                break
        assert url, 'Guarded launcher readiness timeout'
        base = url.split('/#')[0]
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            errors, external = [], []
            page.on('pageerror', lambda error: errors.append(sanitized_error(error)))
            def network(request):
                if not request.url.startswith(base + '/'):
                    external.append(request.url.split('?')[0].split('#')[0])
            page.on('request', network)
            assert page.request.get(base + '/api/state').status == 401
            page.goto(url)
            page.get_by_role('button', name='Find wallet candidates', exact=True).first.wait_for()
            usage = page.request.get(base + '/api/state?report_view=summary').json()['usage']
            page.get_by_role('button', name=re.compile('^Results')).first.click()
            page.get_by_role('button', name='Open ' + address, exact=True).click()
            panel = page.locator('[data-archive-report-id="' + parent_id + '"]')
            expect(panel).to_be_visible()
            page.get_by_role('tab', name='Summary', exact=True).click()
            parent_view = page.request.get(base + '/api/reports/' + parent_id + '?view=display').json()
            assessment = parent_view['research_assessment']
            assert assessment['state'] == 'rebuild_required' and assessment['saved_methodology'] == saved_research
            stale = page.locator('.observed-research [role="status"]')
            expect(stale).to_have_text(assessment['reason'])
            def capture(label, warning):
                for width, height, device in ((1440, 900, 'desktop'), (390, 844, 'mobile')):
                    page.set_viewport_size({'width': width, 'height': height})
                    page.wait_for_timeout(150)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth&&scrollX===0')
                    if warning:
                        expect(stale).to_be_visible()
                        assert stale.inner_text() == assessment['reason']
                        geometry = stale.evaluate("""element => {
                            const box=element.getBoundingClientRect(),style=getComputedStyle(element);
                            return {visible:box.width>0&&box.height>0,
                                hidden:!!element.closest('[hidden],[aria-hidden=true]'),
                                width:element.clientWidth,scrollWidth:element.scrollWidth,
                                height:element.clientHeight,scrollHeight:element.scrollHeight,
                                text:element.innerText,sourceText:element.textContent,
                                maxHeight:style.maxHeight,lineClamp:style.webkitLineClamp};
                        }""")
                        assert geometry['visible'] and not geometry['hidden']
                        assert geometry['scrollWidth'] <= geometry['width'] + 1
                        assert geometry['scrollHeight'] <= geometry['height'] + 1
                        assert geometry['maxHeight'] == 'none' and geometry['lineClamp'] in ('none', '0', '')
                        assert geometry['text'].strip() == geometry['sourceText'].strip()
                        receipt.setdefault('stale_warning_geometry', []).append({'viewport': width, **geometry})
                    page.screenshot(path=str(out / (label + '-' + device + '.png')), full_page=True)
                    receipt['captures'] += 1
                page.set_viewport_size({'width': 1440, 'height': 900})
            capture('stale-7f-parent', True)
            summary = next(report for report in page.request.get(base + '/api/state?report_view=summary').json()['reports']
                           if report['id'] == parent_id)
            assert summary['research_assessment'] == assessment
            assert summary['copy_review'] == parent_view['copy_review']
            def download_report(identifier, name):
                page.get_by_role('tab', name=re.compile('^Source evidence')).click()
                with page.expect_download() as pending:
                    page.get_by_role('link', name='Export report JSON', exact=False).click()
                shutil.copyfile(pending.value.path(), out / name)
                page.get_by_role('tab', name='Summary', exact=True).click()
                with (out / name).open() as file:
                    full = json.load(file)
                assert full['id'] == identifier
                return full
            page.get_by_role('tab', name=re.compile('^Source evidence')).click()
            page.get_by_role('button', name='Inspect record', exact=True).first.click()
            expect(page.get_by_role('button', name='Close evidence', exact=True)).to_be_visible()
            page.get_by_role('button', name='Close evidence', exact=True).click()
            page.get_by_role('tab', name='Summary', exact=True).click()
            full_parent = download_report(parent_id, 'stale-parent-export.json')
            assert full_parent['research_assessment'] == assessment
            assert full_parent['research']['version'] == saved_research
            parent_export_hash = file_hash(out / 'stale-parent-export.json')
            del full_parent
            with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/rebuild')) as pending:
                page.get_by_role('button', name='Rebuild from saved records', exact=True).click()
            assert pending.value.status == 200, 'Offline rebuild failed'
            child_id = pending.value.json()['report_id']
            assert child_id != parent_id
            expect(page.locator('[data-archive-report-id]')).to_have_attribute('data-archive-report-id', child_id)
            child = page.request.get(base + '/api/reports/' + child_id + '?view=display').json()
            assert child['research_assessment']['state'] == 'current'
            assert child['research']['version'] == child['research_assessment']['current_methodology']
            assert child['rebuilt_from'] == parent_id
            assert child['metrics']['observed_network_fees_sol']['value'] == '0.000158868'
            assert child['qualification']['qualified'] is False
            assert child['rebuild']['provider_requests'] == 0
            assert page.locator('.observed-research [role="status"]').count() == 0
            capture('current-offline-child', False)
            full_child = download_report(child_id, 'current-child-export.json')
            assert full_child['research_assessment'] == child['research_assessment']
            del full_child
            # Stream loopback exports without exposing cookies/session values.
            cookies = '; '.join(item['name'] + '=' + item['value'] for item in page.context.cookies(base))
            parent_hash_after = hashlib.sha256()
            with urlopen(Request(base + '/api/export/reports/' + parent_id + '.json', headers={'Cookie': cookies}), timeout=180) as response:
                for block in iter(lambda: response.read(1024 * 1024), b''):
                    parent_hash_after.update(block)
            assert parent_hash_after.hexdigest() == parent_export_hash
            with urlopen(Request(base + '/api/export/reports/' + child_id + '.csv', headers={'Cookie': cookies}), timeout=180) as response:
                csv_bytes = response.read()
            (out / 'current-child-export.csv').write_bytes(csv_bytes)
            assert next(csv.reader(io.StringIO(csv_bytes.decode()))) == ['metric', 'value', 'unit', 'status', 'population', 'reason']
            assert payload_hash(data / 'scanner.sqlite', parent_id) == original_payload_hash
            assert page.request.get(base + '/api/state?report_view=summary').json()['usage'] == usage
            assert not errors and not external
            receipt['cases'].append({'case': 'genuine-7f-stale-research-ui-immutable-offline-child', 'state': 'PASS',
                                     'parent_id': parent_id, 'child_id': child_id, 'stale_assessment': assessment,
                                     'child_assessment': child['research_assessment'], 'source_inspection': True,
                                     'actual_UI_JSON_downloads': True, 'CSV_metric_schema_preserved': True,
                                     'parent_payload_unchanged': True, 'parent_decorated_export_unchanged': True,
                                     'usage_unchanged': True, 'child_observed_network_fees_sol': '0.000158868'})
            receipt.update(state='PASS', javascript_errors=errors, external_browser_requests=external)
            browser.close()
    except Exception as error:
        receipt.update(state='FAILED', reason=sanitized_error(error))
        save()
    finally:
        receipt['server_returncode_before_cleanup'] = server.poll()
        if server.poll() is None:
            server.send_signal(signal.SIGTERM)
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
        receipt['offline_guards_record_present'] = (out / 'guards.json').is_file()
        receipt['offline_guards'] = json.loads((out / 'guards.json').read_bytes()) if receipt['offline_guards_record_present'] else {'missing': True}
        receipt['original_database_sha256_after'] = file_hash(original_db)
        receipt['original_export_sha256_after'] = file_hash(original_export)
        receipt['original_database_and_export_unchanged'] = receipt['original_database_sha256_after'] == original_db_hash and receipt['original_export_sha256_after'] == original_export_hash
        receipt['parent_payload_sha256_after'] = payload_hash(data / 'scanner.sqlite', parent_id)
        after = source_manifest()
        receipt['source_unchanged_before_after'] = after == before
        receipt['compiled_assets'] = {name: {'bytes': (ROOT / name).stat().st_size, 'sha256': after['files'][name]}
                                      for name in after['files'] if name.startswith('frontend/dist/')}
        receipt['scope'] = 'One separately counted browser workflow/four captures, not unique backend nodes or complete-wallet acceptance. Private QA data/server logs/session fragments stay outside Git.'
        if not receipt['source_unchanged_before_after'] or not receipt['original_database_and_export_unchanged'] or any(receipt['offline_guards'].values()):
            receipt['state'] = 'FAILED'
        save()
        print(json.dumps({key: receipt[key] for key in ('state', 'candidate_commit', 'source_sha256', 'captures', 'offline_guards', 'source_unchanged_before_after', 'original_database_and_export_unchanged')}))
    return 0 if receipt['state'] == 'PASS' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
