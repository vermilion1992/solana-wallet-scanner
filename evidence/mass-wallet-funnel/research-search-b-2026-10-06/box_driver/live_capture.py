#!/usr/bin/env python3
"""Secure-box research-search capture driver (LOCAL, UNCOMMITTED).

Grant: live-ranked100-research-search-2026-10-06-mitch (local armed copy).
Raw response bodies are written byte-for-byte (response.content) with a sha256
of those exact bytes. The API key is only ever placed in the httpx query params;
it is never written to disk. Request provenance stores the endpoint WITHOUT key.
No retries. Concurrency 1. Stops on auth/quota/payment/rate-limit errors.
"""
import hashlib, json, math, os, subprocess, sys, time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
ADL = ZoneInfo('Australia/Adelaide')
from pathlib import Path

REPO = Path('/workspace/research-search-b')
sys.path.insert(0, str(REPO))
import httpx
from scanner.mass_search.capability import validate_live_authorization
from scanner.mass_search.history_ingest import (EXACT_HELIUS_OPTIONS, HELIUS_ENDPOINT, HELIUS_METHOD,
    assert_gta_options_not_widened, build_historical_gta_options)
from scanner.mass_search.workflow import research_search_proposal

LIVE = Path(os.environ.get('RSB_SELFTEST_DIR') or '/workspace/research-search-b-live')
if os.environ.get('RSB_SELFTEST_ENDPOINT'):
    HELIUS_ENDPOINT = os.environ['RSB_SELFTEST_ENDPOINT']
GRANT = Path('/workspace/research-search-b-live') / 'live_authorization.ranked100-research-search-armed.json'
CUM = LIVE / 'LEDGER_CUMULATIVE.json'
MANIFEST = LIVE / 'CAPTURE_MANIFEST.json'   # cross-attempt: cleanly captured pages
TOTAL_REQ, TOTAL_CRED, MAX_ATTEMPTS = 100, 1000, 5
EXPECTED = [
 'CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU','gtfoTELAeEZHUgHetA6umfsCETiBMzJCN4tB2sqCgFL',
 'A6PSQFRfv93hoAn1LhQGRT2dYQtjDKX6SE2vN9MEvbot','An9sREpLnAXVi4KMaTGuGvgET51CyaukLUTMtxzmLYSB',
 'CRXomDFunLoRm5N54TyxCxAzn6NJtvnjKvuxudHSV68U','BVZtNYBjivojQnJhocggTVqkbFDYNr2R61c6BZLkY9n9',
 'AW6Pddy72jXDbMUPoSaTB7joJVvMmEMXaYPJhpRqMzD6','58PWvekDbHVPFB9FXGQrpumHD16NRajahkYLHiTvxvDL',
 'DQ7nsa6RPG9F6QjqDUa7LEN5CEvs9sPssXyRYVRb9Cys','BSN5bh8At4BkTGMoysA76fvsvoTsVpjaXRatNJYJBtCM']
STOP_HTTP = {401: 'auth', 402: 'payment', 403: 'auth', 429: 'rate_limit_or_quota'}

def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def local_now():
    return datetime.now(ADL).isoformat()

def jdump(path, obj):
    tmp = Path(str(path) + '.tmp')
    with open(tmp, 'w') as fh:
        fh.write(json.dumps(obj, indent=2, default=str) + '\n'); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp, path)

def load(path, default):
    return json.loads(Path(path).read_text()) if Path(path).exists() else default

def documented_credits(n_records):
    return max(10, 10 * math.ceil(n_records / 100)) if n_records else 10

def main():
    attempt = int(sys.argv[1]); mode = sys.argv[2] if len(sys.argv) > 2 else 'preflight'
    expected_head = sys.argv[3] if len(sys.argv) > 3 else None
    assert 1 <= attempt <= MAX_ATTEMPTS
    grant = json.loads(GRANT.read_text())
    checked = validate_live_authorization(grant)
    assert checked['enabled'] is True, checked.get('reason')
    repo_tpl = json.loads((REPO / 'config/live_authorization.ranked100-research-search-draft.json').read_text())
    assert repo_tpl['enabled'] is False
    helius = next(p for p in grant['providers'] if p['provider_id'] == 'helius')
    bird = next(p for p in grant['providers'] if p['provider_id'] == 'birdeye')
    assert bird['max_requests'] == 0 and bird['max_units'] == 0
    per_req, per_cred = helius['max_requests'], helius['max_units']
    assert (per_req, per_cred) == (20, 200)
    head = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip()
    dirty = subprocess.check_output(['git', '-C', str(REPO), 'status', '--porcelain', '--untracked-files=no'], text=True).strip()
    cands = research_search_proposal()['selected_candidates']
    addrs = [c['address'] for c in cands]
    assert addrs == EXPECTED, 'app candidate selection drifted'
    cum = load(CUM, {'attempts': [], 'total_requests': 0, 'total_documented_credits': 0, 'total_usd': '0', 'birdeye_requests': 0})
    manifest = load(MANIFEST, {'pages': {}})
    done_attempts = {a['attempt'] for a in cum['attempts']}
    plan = []
    for c in cands:
        for page in (0, 1):
            key = f"{c['address']}:page:{page}"
            plan.append({'key': key, 'address': c['address'], 'page_index': page, 'provider_rank': c['provider_rank'],
                         'trade_count': c['trade_count'], 'already_captured': key in manifest['pages']})
    pre = {'attempt': attempt, 'mode': mode, 'checked_at': now(), 'checked_at_local': local_now(),
           'application_commit': head, 'repo_dirty_tracked': bool(dirty), 'grant_id': grant['authorization_id'],
           'repo_template_enabled': repo_tpl['enabled'], 'per_attempt_ceiling': [per_req, per_cred],
           'cumulative_before': {k: cum[k] for k in ('total_requests', 'total_documented_credits')},
           'exact_options_page0': build_historical_gta_options(page_index=0),
           'pages_to_fetch': sum(1 for p in plan if not p['already_captured']),
           'pages_skipped_already_captured': sum(1 for p in plan if p['already_captured']),
           'key_present': bool(os.environ.get('HELIUS_API_KEY'))}
    print(json.dumps(pre, indent=2))
    if mode != 'live':
        return 0
    assert attempt not in done_attempts, 'attempt number already used'
    assert len(done_attempts) < MAX_ATTEMPTS
    assert not dirty and (expected_head is None or head == expected_head), 'repo must be clean at the expected commit'
    key = os.environ.get('HELIUS_API_KEY')
    assert key, 'HELIUS_API_KEY missing'
    adir = LIVE / f'attempt-{attempt}'
    assert not adir.exists(), 'fresh attempt dir required'
    (adir / 'raw').mkdir(parents=True)
    ledger = {'attempt': attempt, 'grant_id': grant['authorization_id'], 'application_commit': head,
              'started_at': now(), 'started_at_local': local_now(), 'entries': [], 'requests': 0,
              'documented_credits': 0, 'usd': '0', 'birdeye_requests': 0, 'stop_reason': None,
              'credits_basis': 'documented estimate: 10 credits per 100 returned full txs (min 10); failed responses documented free but counted 10 for ceiling enforcement',
              'retries': 0, 'concurrency': 1}
    jdump(adir / 'LEDGER.json', ledger)
    cum['attempts'].append({'attempt': attempt, 'application_commit': head, 'started_at': ledger['started_at'], 'requests': 0, 'documented_credits': 0, 'status': 'running'})
    jdump(CUM, cum)
    t0 = time.time()
    tokens = {}
    exhausted = set()
    stop = None
    for item in plan:
        addr, page = item['address'], item['page_index']
        if item['already_captured']:
            if page == 0:
                tokens[addr] = manifest['pages'][item['key']].get('response_pagination_token')
                if manifest['pages'][item['key']].get('record_count', 0) < 100:
                    exhausted.add(addr)
            continue
        if addr in exhausted:
            ledger['entries'].append({'key': item['key'], 'skipped': 'history_exhausted_or_page0_failed'}); continue
        token = None
        if page == 1:
            token = tokens.get(addr)
            if not token:
                ledger['entries'].append({'key': item['key'], 'skipped': 'no_pagination_token_from_page0'}); continue
        # hard ceilings, checked BEFORE dispatch (count a worst-case 10 credits per request)
        if ledger['requests'] + 1 > per_req or ledger['documented_credits'] + 10 > per_cred:
            stop = 'per_attempt_budget_exhausted'; break
        if cum['total_requests'] + 1 > TOTAL_REQ or cum['total_documented_credits'] + 10 > TOTAL_CRED:
            stop = 'cumulative_budget_exhausted'; break
        if time.time() - t0 > helius['max_duration_seconds']:
            stop = 'max_duration_seconds'; break
        options = build_historical_gta_options(page_index=page, pagination_token=token)
        assert_gta_options_not_widened(options)
        base = {k: v for k, v in options.items() if k != 'paginationToken'}
        assert base == EXACT_HELIUS_OPTIONS
        payload = {'jsonrpc': '2.0', 'id': 1, 'method': HELIUS_METHOD, 'params': [addr, options]}
        entry = {'key': item['key'], 'address': addr, 'provider_rank': item['provider_rank'], 'page_index': page,
                 'request': {'endpoint': HELIUS_ENDPOINT, 'query_string_credentials': 'OMITTED', 'http_method': 'POST',
                             'json_body': payload}, 'request_pagination_token': token,
                 'dispatched_at': now(), 'dispatched_at_local': local_now()}
        # write-ahead: count the request before it leaves the box
        ledger['requests'] += 1; ledger['documented_credits'] += 10
        cum['total_requests'] += 1; cum['total_documented_credits'] += 10
        ledger['entries'].append(entry); jdump(adir / 'LEDGER.json', ledger); jdump(CUM, cum)
        try:
            with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(40, connect=10)) as client:
                resp = client.post(HELIUS_ENDPOINT, params={'api-key': key}, json=payload)
            raw = resp.content
        except httpx.HTTPError as err:
            entry.update({'completed_at': now(), 'outcome': 'transport_error', 'error_type': type(err).__name__})
            exhausted.add(addr); jdump(adir / 'LEDGER.json', ledger); continue
        entry['completed_at'] = now(); entry['completed_at_local'] = local_now()
        entry['http_status'] = resp.status_code
        entry['response_headers'] = {k: v for k, v in resp.headers.items() if k.lower() not in ('set-cookie',)}
        sha = hashlib.sha256(raw).hexdigest()
        fname = f"{addr}_page{page}.json"
        (adir / 'raw' / fname).write_bytes(raw)
        assert hashlib.sha256((adir / 'raw' / fname).read_bytes()).hexdigest() == sha
        entry.update({'raw_file': f'raw/{fname}', 'raw_sha256': sha, 'raw_bytes': len(raw)})
        if key.encode() in raw:
            entry['key_material_in_body'] = True
        if resp.status_code in STOP_HTTP:
            entry['outcome'] = f'stop_{STOP_HTTP[resp.status_code]}'; stop = entry['outcome']
            ledger['documented_credits'] -= 10; cum['total_documented_credits'] -= 10
            jdump(adir / 'LEDGER.json', ledger); jdump(CUM, cum); break
        try:
            body = json.loads(raw)
        except ValueError:
            entry['outcome'] = 'non_json'; stop = 'non_json_response'; jdump(adir / 'LEDGER.json', ledger); break
        if resp.status_code != 200 or not isinstance(body, dict) or body.get('error'):
            err = body.get('error') if isinstance(body, dict) else None
            entry['outcome'] = 'provider_error'; entry['provider_error'] = err
            ledger['documented_credits'] -= 10; cum['total_documented_credits'] -= 10
            stop = 'provider_error_stop_no_retry'; jdump(adir / 'LEDGER.json', ledger); jdump(CUM, cum); break
        result = body.get('result') or {}
        data = result.get('data') if isinstance(result, dict) else None
        if not isinstance(data, list):
            entry['outcome'] = 'unexpected_schema'; stop = 'unexpected_schema'; jdump(adir / 'LEDGER.json', ledger); break
        n = len(data); credits = documented_credits(n)
        ledger['documented_credits'] += credits - 10; cum['total_documented_credits'] += credits - 10
        ptoken = result.get('paginationToken')
        sigs = []
        for rec in data:
            s = (rec.get('transaction') or {}).get('signatures') or []
            sigs.append(s[0] if s else None)
        times = [rec.get('blockTime') for rec in data if isinstance(rec.get('blockTime'), int)]
        entry.update({'outcome': 'ok', 'record_count': n, 'documented_credits': credits,
                      'response_pagination_token': ptoken, 'first_signature': sigs[0] if sigs else None,
                      'last_signature': sigs[-1] if sigs else None,
                      'newest_block_time': datetime.fromtimestamp(max(times), timezone.utc).isoformat() if times else None,
                      'oldest_block_time': datetime.fromtimestamp(min(times), timezone.utc).isoformat() if times else None})
        tokens[addr] = ptoken
        if page == 0 and (n < 100 or not ptoken):
            exhausted.add(addr)
        manifest['pages'][item['key']] = {k: entry.get(k) for k in ('address', 'page_index', 'provider_rank', 'raw_sha256', 'raw_bytes', 'record_count', 'request_pagination_token', 'response_pagination_token', 'dispatched_at', 'completed_at', 'first_signature', 'last_signature', 'newest_block_time', 'oldest_block_time')}
        manifest['pages'][item['key']]['raw_path'] = str(adir / 'raw' / fname)
        manifest['pages'][item['key']]['attempt'] = attempt
        jdump(adir / 'LEDGER.json', ledger); jdump(CUM, cum); jdump(MANIFEST, manifest)
    ledger['stop_reason'] = stop or 'coverage_objective_reached'
    ledger['finished_at'] = now(); ledger['finished_at_local'] = local_now(); ledger['wall_seconds'] = round(time.time() - t0, 2)
    jdump(adir / 'LEDGER.json', ledger)
    for a in cum['attempts']:
        if a['attempt'] == attempt:
            a.update({'requests': ledger['requests'], 'documented_credits': ledger['documented_credits'], 'status': ledger['stop_reason'], 'finished_at': ledger['finished_at']})
    jdump(CUM, cum)
    print(json.dumps({k: ledger[k] for k in ('attempt', 'requests', 'documented_credits', 'stop_reason', 'wall_seconds')}, indent=2))
    print(json.dumps([{k: e.get(k) for k in ('key', 'outcome', 'skipped', 'http_status', 'record_count', 'raw_sha256')} for e in ledger['entries']], indent=1))
    return 0

if __name__ == '__main__':
    sys.exit(main())
