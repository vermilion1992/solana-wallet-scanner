#!/usr/bin/env python3
"""Execute only the separately approved bounded source plan; never scan a wallet."""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timezone
import getpass
import gzip
import hashlib
import json
import logging
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import httpx
from scanner.config import validate_cycle
from scanner.storage import Store, QuotaExceeded
from scanner.transaction_format import supported_transaction_format

PLAN_SHA256 = 'c3b78e505e9052da901af9e29c6556a993ff147affad4b735083954182ee432f'
ENDPOINT = 'https://mainnet.helius-rpc.com/'
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
SAFE_HEADERS = {'content-type', 'content-length', 'date', 'retry-after', 'x-ratelimit-limit',
                'x-ratelimit-remaining', 'x-ratelimit-reset', 'x-credit-cost'}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_plan(path):
    raw = path.read_bytes()
    if sha(raw) != PLAN_SHA256:
        raise ValueError('Plan differs from the exact separately approved plan')
    plan = json.loads(raw)
    if plan['request_cap'] != 10 or plan['credit_cap'] != 100 or plan['retries'] != 0:
        raise ValueError('Approved request/credit/retry caps changed')
    if sum(r['credit_upper_bound'] for r in plan['requests']) != 73:
        raise ValueError('Approved conservative cost bound changed')
    return plan


def validate_confirmation(value):
    expected = {'plan', 'cycle_start', 'cycle_end', 'remaining_credits', 'autoscaling', 'confirmed_by'}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('Dashboard confirmation requires plan, dates, balance, autoscaling and provenance')
    if value['plan'] != 'Free' or value['autoscaling'] is not False or value['confirmed_by'] != 'user-dashboard':
        raise ValueError('User dashboard must confirm Free plan with autoscaling off')
    if type(value['remaining_credits']) is not int or value['remaining_credits'] < 100:
        raise ValueError('At least 100 remaining dashboard credits are required')
    validate_cycle(value['cycle_start'], value['cycle_end'])
    return value


def row_signature(raw):
    tx = raw.get('transaction') if isinstance(raw, dict) else None
    signatures = tx.get('signatures') if isinstance(tx, dict) else None
    if not isinstance(signatures, list) or not signatures or not isinstance(signatures[0], str):
        raise ValueError('Full transaction signature is missing')
    return signatures[0]


def validate_response(body, request, request_id, plan, previous_cursor=None):
    if (not isinstance(body, dict) or body.get('jsonrpc') != '2.0'
        or type(body.get('id')) is not type(request_id) or body.get('id') != request_id):
        raise ValueError('RPC response identity/format does not match the request')
    if body.get('error') is not None:
        return {'state': 'RPC_ERROR', 'error': body['error']}
    if 'result' not in body:
        raise ValueError('RPC response has no result')
    result = body['result']; method = request['method']
    if method == 'getTransactionsForAddress':
        if not isinstance(result, dict) or not isinstance(result.get('data'), list) or 'paginationToken' not in result:
            raise ValueError('Indexed response lacks a full page or explicit cursor state')
        rows = result['data']; cursor = result['paginationToken']
        if len(rows) > 100:
            raise ValueError('Indexed response exceeds the approved 100-row request bound')
        if cursor is not None and (not isinstance(cursor, str) or not re.fullmatch(r'[0-9]+:[0-9]+', cursor)):
            raise ValueError('Unsupported indexed cursor')
        if cursor is not None and cursor == previous_cursor:
            raise ValueError('Indexed cursor repeated')
        signatures = []; positions = []
        bounds = request['params'][1]['filters']['blockTime']
        for raw in rows:
            signatures.append(row_signature(raw))
            if not supported_transaction_format(raw):
                raise ValueError('Unsupported transaction version remains a coverage gap')
            if type(raw.get('slot')) is not int or type(raw.get('transactionIndex')) is not int:
                raise ValueError('Indexed transaction ordering fields are missing')
            if raw['slot'] < 0 or raw['transactionIndex'] < 0:
                raise ValueError('Invalid indexed ordering fields')
            if type(raw.get('blockTime')) is not int or not bounds['gte'] <= raw['blockTime'] < bounds['lt']:
                raise ValueError('Indexed record is outside the exact approved interval')
            if not isinstance(raw.get('meta'), dict) or 'err' not in raw['meta']:
                raise ValueError('Indexed full transaction execution metadata is missing')
            positions.append((raw['slot'], raw['transactionIndex']))
        if len(signatures) != len(set(signatures)) or positions != sorted(positions) or len(set(positions)) != len(positions):
            raise ValueError('Indexed page duplicates or chronology conflict')
        if previous_cursor is not None and positions and positions[0] <= tuple(map(int, previous_cursor.split(':'))):
            raise ValueError('Continuation did not advance past the previous position')
        if cursor is not None and not rows:
            raise ValueError('Nonterminal empty page cannot support continuation')
        return {'state': 'OBSERVED', 'rows': len(rows), 'signatures': signatures,
                'cursor': cursor, 'terminal_claim': cursor is None,
                'coverage': 'Provider page observation only; not an independent historical population proof'}
    if method == 'getTransaction':
        if result is None or row_signature(result) != request['params'][0]:
            raise ValueError('Primary transaction is absent or has a mismatched signature')
        if not supported_transaction_format(result) or type(result.get('slot')) is not int or type(result.get('blockTime')) is not int:
            raise ValueError('Primary transaction format/time is unsupported')
        expected = json.loads(gzip.decompress((ROOT / 'evidence/runs/real-cache/archives' / (request['archived_control_hash'] + '.json.gz')).read_bytes()))
        expected = expected.get('result', expected)
        for field in ('slot', 'blockTime'):
            if result[field] != expected[field]:
                raise ValueError('Primary archived identity/time control disagrees')
        meta = result.get('meta'); prior = expected.get('meta')
        if not isinstance(meta, dict) or not isinstance(prior, dict):
            raise ValueError('Primary execution/native metadata is missing')
        for field in ('err', 'fee', 'preBalances', 'postBalances'):
            if field not in meta or meta[field] != prior.get(field):
                raise ValueError('Primary archived execution/native control disagrees')
        return {'state': 'OBSERVED', 'signature': request['params'][0], 'archived_control': 'Identity, time, execution and native endpoint facts match; not independent complete history'}
    if method == 'getTokenAccountsByOwner':
        if not isinstance(result, dict) or not isinstance(result.get('value'), list) or not isinstance(result.get('context'), dict) or type(result['context'].get('slot')) is not int:
            raise ValueError('Current-owner snapshot response is incomplete')
        for entry in result['value']:
            try:
                owner = entry['account']['data']['parsed']['info']['owner']
            except (KeyError, TypeError):
                raise ValueError('Current account owner fields are unavailable') from None
            if owner != plan['wallet']:
                raise ValueError('Current account owner does not match the requested wallet')
        return {'state': 'OBSERVED', 'accounts': len(result['value']), 'context_slot': result['context']['slot'], 'coverage': 'Current ownership only'}
    if method == 'getSlot':
        if type(result) is not int or result < 0:
            raise ValueError('Finalized slot response is unsupported')
        return {'state': 'OBSERVED', 'finalized_slot': result}
    raise ValueError('Method is outside the approved plan')


async def execute(plan, confirmation, key, output, store, transport=None):
    validate_confirmation(confirmation)
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,200}', key):
        raise ValueError('Provider key format is invalid')
    output.mkdir(parents=True, exist_ok=False)
    cycle = confirmation['cycle_start']; cap = 100
    result = {'kind': 'authorised-bounded-source-probe', 'started_utc': now(), 'state': 'RUNNING',
              'approved_plan_sha256': PLAN_SHA256, 'endpoint': ENDPOINT, 'confirmation': confirmation,
              'request_cap': 10, 'credit_cap': cap, 'conservative_credits': 0, 'provider_requests': 0,
              'retries': 0, 'purchases': False, 'quota_reset': False, 'requests': [],
              'quota_before': store.usage('helius', cycle, cap), 'B3': 'BLOCKED',
              'historical_owner_completeness': 'INCONCLUSIVE; no independently known closed/reassigned control',
              'billing_actual_credits': None, 'billing_scope': 'Conservative reservation bound; actual provider invoice/usage delta is not asserted'}
    def save():
        result['quota_after'] = store.usage('helius', cycle, cap)
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    save(); observations = {}; all_signatures = set()
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    async with httpx.AsyncClient(transport=transport, follow_redirects=False, verify=True,
                                trust_env=True, timeout=httpx.Timeout(25, connect=10)) as client:
        for planned in plan['requests']:
            request = json.loads(json.dumps(planned)); previous_cursor = None
            if 'conditional' in request:
                previous_cursor = observations.get('all-index', {}).get('cursor')
                if previous_cursor is None:
                    result['requests'].append({'id': request['id'], 'state': 'NOT_RUN', 'reason': 'Previous indexed response was explicitly terminal'})
                    continue
                request['params'][1]['paginationToken'] = previous_cursor
            if result['provider_requests'] >= 10 or result['conservative_credits'] + request['credit_upper_bound'] > cap:
                result.update(state='BLOCKED', reason='Approved request/credit cap reached'); break
            number = result['provider_requests'] + 1
            body = json.dumps({'jsonrpc': '2.0', 'id': number, 'method': request['method'], 'params': request['params']}, separators=(',', ':'), allow_nan=False).encode()
            prefix = f"{number:02d}-{request['id']}"
            (output / (prefix + '-request.json')).write_bytes(body)
            try:
                reservation = store.reserve('helius', request['method'], request['credit_upper_bound'], cycle, cap)
            except QuotaExceeded:
                result.update(state='BLOCKED', reason='Durable approved credit cap reached; no request dispatched'); break
            row = {'id': request['id'], 'method': request['method'], 'request_id': number,
                   'reservation': reservation, 'conservative_credits': request['credit_upper_bound'],
                   'request_path': prefix + '-request.json', 'request_sha256': sha(body), 'started_utc': now()}
            result['requests'].append(row); save()
            store.dispatch(reservation); result['provider_requests'] += 1
            result['conservative_credits'] += request['credit_upper_bound']; wire = bytearray()
            try:
                async with client.stream('POST', ENDPOINT, params={'api-key': key}, content=body,
                                         headers={'Content-Type': 'application/json', 'Accept': 'application/json'}) as response:
                    row['http_status'] = response.status_code
                    row['response_headers'] = {k: v.replace(key, '[REDACTED]') for k, v in response.headers.items() if k.lower() in SAFE_HEADERS}
                    async for chunk in response.aiter_bytes():
                        if len(wire) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise ValueError('Response exceeds bounded retained-byte limit')
                        wire.extend(chunk)
                safe = bytes(wire).replace(key.encode(), b'[REDACTED]')
                response_path = prefix + '-response.raw.gz'
                (output / response_path).write_bytes(gzip.compress(safe, mtime=0))
                row.update(response_path=response_path, response_sha256=sha(safe), response_bytes=len(safe),
                           credential_redaction_applied=safe != bytes(wire))
                if response.status_code != 200:
                    try:
                        parsed = json.loads(safe)
                    except ValueError:
                        parsed = {'body_type': 'non-JSON', 'retained_response': response_path}
                    row.update(state='DENIED' if response.status_code in (401, 403) else 'HTTP_ERROR', upstream=parsed)
                    result.update(state='STOPPED', reason='HTTP failure; approved no-retry stop condition'); break
                parsed = json.loads(safe)
                assessment = validate_response(parsed, request, number, plan, previous_cursor)
                row['assessment'] = assessment; row['state'] = assessment['state']
                if assessment['state'] != 'OBSERVED':
                    result.update(state='STOPPED', reason='RPC denial/error; approved stop condition'); break
                if request['id'] == 'all-continuation' and all_signatures.intersection(assessment['signatures']):
                    raise ValueError('Continuation repeated a previously retained signature')
                if request['id'] in ('all-index', 'all-continuation'):
                    all_signatures.update(assessment['signatures'])
                observations[request['id']] = assessment
            except Exception as exc:
                safe = bytes(wire).replace(key.encode(), b'[REDACTED]')
                if safe and 'response_path' not in row:
                    response_path = prefix + '-partial-response.raw.gz'
                    (output / response_path).write_bytes(gzip.compress(safe, mtime=0))
                    row.update(response_path=response_path, response_sha256=sha(safe), response_bytes=len(safe))
                reason = str(exc) if isinstance(exc, ValueError) else 'Provider transport/storage failure (' + type(exc).__name__ + ')'
                row.update(state='UNSUPPORTED_OR_FAILED', reason=reason.replace(key, '[REDACTED]'))
                result.update(state='STOPPED', reason=row['reason']); break
            finally:
                store.settle(reservation, charge=True)
                row['finished_utc'] = now(); save()
            await asyncio.sleep(1 / 3)
        else:
            result['state'] = 'OBSERVED_IN_SCOPE'
    result['finished_utc'] = now()
    result['source_access_observed'] = observations
    result['unexecuted_request_ids'] = [r['id'] for r in plan['requests'] if r['id'] not in {x['id'] for x in result['requests']}]
    result['artifacts'] = {p.name: {'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size} for p in output.iterdir() if p.is_file() and p.name != 'result.json'}
    save()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=ROOT / 'evidence/product-milestone/SOURCE_PROBE_PLAN.json')
    parser.add_argument('--confirmation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--quota-data', type=Path, required=True)
    args = parser.parse_args()
    plan = load_plan(args.plan)
    confirmation = validate_confirmation(json.loads(args.confirmation.read_text()))
    # Session input, no file/environment write, and no key value in logs/receipts.
    if not sys.stdin.isatty():
        raise ValueError('Provider key input requires a terminal with echo disabled')
    key = getpass.getpass('Previously supplied Helius key (session only): ')
    with_store = Store(args.quota_data)
    try:
        result = asyncio.run(execute(plan, confirmation, key, args.output, with_store))
    finally:
        with_store.close()
    print(json.dumps({k: result[k] for k in ('state', 'provider_requests', 'conservative_credits', 'B3', 'historical_owner_completeness')}))
    return 0 if result['state'] == 'OBSERVED_IN_SCOPE' else 2


if __name__ == '__main__':
    raise SystemExit(main())
