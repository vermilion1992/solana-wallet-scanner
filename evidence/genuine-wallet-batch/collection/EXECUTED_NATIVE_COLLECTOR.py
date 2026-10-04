#!/usr/bin/env python3
"""Acquire explicitly planned raw evidence under one durable bounded budget.

This separate operator tool does not enable methods in the production gateway,
interpret financial records, or certify historical population. No retries.
"""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from scanner.config import validate_address, validate_cycle
from scanner.discovery import _signature as supported_signature
from scanner.storage import Store, QuotaExceeded

ENDPOINT = 'https://mainnet.helius-rpc.com/'
APPROVED_BUDGET_ID = 'genuine-wallet-2026-10-04'
MAX_REQUESTS, MAX_CREDITS = 30, 1000
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
READ_ONLY_METHODS = frozenset({'getTransactionsForAddress', 'getTransaction',
    'getSignaturesForAddress', 'getTokenAccountsByOwner', 'getAccountInfo',
    'getBalance', 'getSlot', 'getBlock'})
TOKEN_PROGRAMS = frozenset({'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
    'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'})
SAFE_HEADERS = frozenset({'content-type', 'content-length', 'date', 'retry-after',
    'x-ratelimit-limit', 'x-ratelimit-remaining', 'x-ratelimit-reset', 'x-credit-cost'})
BASE58 = re.compile(r'[1-9A-HJ-NP-Za-km-z]+')


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def signature(value):
    require(supported_signature(value), 'A base58 signature decoding to exactly64bytes is required')


def integer(value, lower=0, upper=None):
    require(type(value) is int and value >= lower and (upper is None or value <= upper),
            'Integer field is outside its approved bounds')


def finalized(options, allowed):
    require(type(options) is dict and set(options) <= allowed and options.get('commitment') == 'finalized',
            'Exact finalized read-only options are required')


def validate_request(row, previous):
    require(type(row) is dict and {'id', 'method', 'params'} <= set(row)
            and set(row) <= {'id', 'method', 'params', 'pagination_from'}, 'Unsupported request declaration')
    require(isinstance(row['id'], str) and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', row['id'])
            and row['id'] not in previous, 'Distinct safe request IDs are required')
    method, params = row['method'], row['params']
    require(isinstance(method, str) and method in READ_ONLY_METHODS and type(params) is list, 'Method is outside the separate read-only collection allowlist')
    if method == 'getTransactionsForAddress':
        require(len(params) == 2, 'Indexed request requires address and exact options')
        validate_address(params[0]); opts = params[1]
        finalized(opts, {'transactionDetails', 'limit', 'sortOrder', 'commitment', 'maxSupportedTransactionVersion', 'filters', 'encoding'})
        require(opts.get('transactionDetails') in ('full', 'signatures') and opts.get('sortOrder') in ('asc', 'desc'), 'Indexed detail/order must be explicit')
        integer(opts.get('limit'), 1, 1000)
        require(type(opts.get('maxSupportedTransactionVersion')) is int and opts['maxSupportedTransactionVersion'] == 1,
                'Explicit version1 retrieval bound avoids silent legacy-only requests')
        if 'encoding' in opts:
            require(opts['transactionDetails'] == 'full' and opts['encoding'] in ('json', 'jsonParsed'), 'Only JSON transaction encoding is supported')
        filters = opts.get('filters')
        require(type(filters) is dict and {'status', 'tokenAccounts'} <= set(filters)
                and set(filters) <= {'status', 'tokenAccounts', 'blockTime'}, 'Unfiltered status/owner scope is required')
        require(filters['status'] == 'any' and filters['tokenAccounts'] in ('all', 'none'), 'Failed records must not be filtered away')
        if 'blockTime' in filters:
            bounds = filters['blockTime']
            require(type(bounds) is dict and set(bounds) == {'gte', 'lt'}, 'Exact half-open indexed time bounds are required')
            integer(bounds['gte']); integer(bounds['lt']); require(bounds['gte'] < bounds['lt'], 'Positive indexed interval required')
    elif method == 'getSignaturesForAddress':
        require(len(params) == 2, 'Signature request requires address and options')
        validate_address(params[0]); opts = params[1]
        finalized(opts, {'limit', 'commitment', 'before', 'until'})
        integer(opts.get('limit'), 1, 1000)
        for field in ('before', 'until'):
            if field in opts: signature(opts[field])
    elif method == 'getTransaction':
        require(len(params) == 2, 'Primary request requires signature and options')
        signature(params[0]); opts = params[1]
        finalized(opts, {'encoding', 'commitment', 'maxSupportedTransactionVersion'})
        require(opts.get('encoding') in ('json', 'jsonParsed') and type(opts.get('maxSupportedTransactionVersion')) is int
                and opts['maxSupportedTransactionVersion'] == 1, 'Exact supported primary JSON/version options required')
    elif method == 'getTokenAccountsByOwner':
        require(len(params) == 3, 'Owner request requires wallet/program/options')
        validate_address(params[0]); require(type(params[1]) is dict and set(params[1]) == {'programId'}
                and params[1]['programId'] in TOKEN_PROGRAMS, 'Only the two token programs are admitted')
        finalized(params[2], {'encoding', 'commitment'})
        require(params[2].get('encoding') == 'jsonParsed', 'Parsed current-owner snapshot required')
    elif method in ('getAccountInfo', 'getBalance'):
        require(len(params) == 2, 'Account request requires address/options'); validate_address(params[0])
        finalized(params[1], {'commitment', 'encoding'} if method == 'getAccountInfo' else {'commitment'})
        if method == 'getAccountInfo': require(params[1].get('encoding') in ('jsonParsed', 'base64'), 'Explicit account encoding required')
    elif method == 'getSlot':
        require(len(params) == 1, 'Slot request requires one option object'); finalized(params[0], {'commitment'})
    elif method == 'getBlock':
        require(len(params) == 2, 'Block request requires slot/options'); integer(params[0])
        finalized(params[1], {'encoding', 'commitment', 'transactionDetails', 'rewards', 'maxSupportedTransactionVersion'})
        require(params[1].get('encoding') in ('json', 'jsonParsed') and params[1].get('transactionDetails') == 'full'
                and params[1].get('rewards') is False and type(params[1].get('maxSupportedTransactionVersion')) is int
                and params[1]['maxSupportedTransactionVersion'] == 1, 'Bounded full block JSON options required')
    if 'pagination_from' in row:
        ancestor = previous.get(row['pagination_from'])
        require(method == 'getTransactionsForAddress' and ancestor is not None
                and ancestor['method'] == method and ancestor['params'] == params,
                'Pagination must continue an identical earlier indexed query')


def credit_bound(row):
    if row['method'] == 'getTransactionsForAddress' and row['params'][1]['transactionDetails'] == 'full':
        return 10 * ((row['params'][1]['limit'] + 99) // 100)
    # Indexed signatures cost10flat; every native archival call conservatively
    # reserves10 despite newer billing references advertising1 for some methods.
    return 10


def validate_plan(plan):
    require(type(plan) is dict and set(plan) == {'kind', 'budget_id', 'request_cap', 'credit_cap', 'retries', 'requests', 'purpose'}, 'Exact collection plan fields required')
    require(plan['kind'] == 'bounded-native-collection-plan-v1' and plan['budget_id'] == APPROVED_BUDGET_ID,
            'Plan is outside the current explicitly approved collection budget')
    integer(plan['request_cap'], 1, MAX_REQUESTS); integer(plan['credit_cap'], 1, MAX_CREDITS)
    require(type(plan['retries']) is int and plan['retries'] == 0 and isinstance(plan['purpose'], str)
            and 1 <= len(plan['purpose']) <= 500, 'No-retry plan purpose is required')
    require(type(plan['requests']) is list and 1 <= len(plan['requests']) <= plan['request_cap'], 'Plan request count exceeds bound')
    previous = {}
    for row in plan['requests']:
        validate_request(row, previous); previous[row['id']] = row
    require(sum(credit_bound(row) for row in plan['requests']) <= plan['credit_cap'], 'Planned conservative credits exceed bound')
    return plan


def load_plan(path, expected_sha256):
    raw = path.read_bytes()
    require(isinstance(expected_sha256, str) and re.fullmatch('[a-f0-9]{64}', expected_sha256)
            and sha(raw) == expected_sha256, 'Plan hash differs from the reviewed exact bytes')
    return validate_plan(json.loads(raw)), sha(raw)


def validate_confirmation(value, cap):
    require(type(value) is dict and set(value) == {'plan', 'cycle_start', 'cycle_end', 'remaining_credits', 'autoscaling', 'confirmed_by'}, 'Exact dashboard facts and provenance required')
    require(value['plan'] == 'Free' and value['autoscaling'] is False and value['confirmed_by'] == 'user-dashboard', 'Confirmed Free plan with automatic spending disabled required')
    integer(value['remaining_credits'], cap); validate_cycle(value['cycle_start'], value['cycle_end'])
    return value


def bind_budget(store, plan, confirmation):
    binding = {'budget_id': plan['budget_id'], 'request_cap': plan['request_cap'], 'credit_cap': plan['credit_cap'],
               'cycle_start': confirmation['cycle_start'], 'cycle_end': confirmation['cycle_end'], 'endpoint': ENDPOINT}
    # Bind once under the same SQLite write lock/transaction: a second phase
    # cannot silently create higher caps or change billing-cycle identity.
    with store.lock:
        store.db.execute('BEGIN IMMEDIATE')
        try:
            prior = store.db.execute("SELECT payload FROM records WHERE kind='bounded_collection_budget' AND id=?", (plan['budget_id'],)).fetchone()
            if prior:
                require(json.loads(prior[0]) == binding, 'Existing collection budget/cycle binding cannot change')
            else:
                store.db.execute("INSERT INTO records VALUES('bounded_collection_budget',?,?,?)", (plan['budget_id'], json.dumps(binding, sort_keys=True), now()))
            store.db.commit()
        except BaseException:
            store.db.rollback(); raise
    return binding


def namespaces(plan):
    return ('helius-collection-credits/' + plan['budget_id'], 'helius-collection-requests/' + plan['budget_id'])


def usage(store, plan, confirmation):
    credits, requests = namespaces(plan); cycle = confirmation['cycle_start']
    return {'credits': store.usage(credits, cycle, plan['credit_cap']), 'requests': store.usage(requests, cycle, plan['request_cap'])}


def reserve_pair(store, plan, confirmation, row):
    credits, requests = namespaces(plan); cycle = confirmation['cycle_start']
    credit = store.reserve(credits, row['method'], credit_bound(row), cycle, plan['credit_cap'])
    try:
        request = store.reserve(requests, row['method'], 1, cycle, plan['request_cap'])
    except BaseException:
        store.release(credit); raise
    return credit, request


def dispatch_pair(store, credit, request):
    with store.lock, store.db:
        for reservation in (credit, request):
            changed = store.db.execute("UPDATE reservations SET state='dispatched',updated_at=? WHERE id=? AND state='reserved'", (now(), reservation))
            require(changed.rowcount == 1, 'Paired reservation is not undispatched')


def claim_phase(store, plan, plan_hash):
    identifier = plan['budget_id'] + '/' + plan_hash
    with store.lock:
        store.db.execute('BEGIN IMMEDIATE')
        try:
            prior = store.db.execute("SELECT 1 FROM records WHERE kind='bounded_collection_phase' AND id=?", (identifier,)).fetchone()
            require(prior is None, 'Exact phase was already claimed; no retry/restart is permitted')
            store.db.execute("INSERT INTO records VALUES('bounded_collection_phase',?,?,?)", (identifier, json.dumps({'plan_sha256': plan_hash, 'claimed_utc': now()}), now()))
            store.db.commit()
        except BaseException:
            store.db.rollback(); raise


def retain_response(output, prefix, row, wire, key, *, partial=False):
    raw = bytes(wire)
    if key.encode() in raw or row.get('secret_reflected_in_response_headers'):
        row.update(response_original_sha256=sha(raw), response_original_bytes=len(raw),
                   raw_response_omitted=True, omission_reason='Secret-bearing reflected response; original bytes excluded',
                   byte_exact_response_retained=False)
        return False
    name = prefix + ('-partial-response.raw.gz' if partial else '-response.raw.gz')
    (output / name).write_bytes(gzip.compress(raw, mtime=0))
    row.update(response_path=name, response_sha256=sha(raw), response_bytes=len(raw),
               credential_redaction_applied=False, byte_exact_response_retained=True)
    return True


def primary_fields(value):
    require(type(value) is dict and type(value.get('transaction')) is dict and type(value.get('meta')) is dict,
            'Full primary transaction/execution objects unavailable')
    tx, meta = value['transaction'], value['meta']
    sigs = tx.get('signatures'); require(type(sigs) is list and bool(sigs), 'Primary signatures unavailable')
    for sig in sigs: signature(sig)
    version = value.get('version', 'legacy')
    require(version == 'legacy' or type(version) is int and version == 0, 'Unsupported version retained as a coverage gap')
    require(type(tx.get('message')) is dict and type(tx['message'].get('accountKeys')) is list
            and bool(tx['message']['accountKeys']) and type(tx['message'].get('instructions')) is list,
            'Primary message containers unavailable')
    require('err' in meta, 'Primary execution status unavailable'); integer(meta.get('fee'))
    for name in ('preBalances', 'postBalances'):
        require(type(meta.get(name)) is list and bool(meta[name]), 'Primary native balance arrays unavailable')
        for balance in meta[name]: integer(balance)
    require(len(meta['preBalances']) == len(meta['postBalances']), 'Native endpoint lengths disagree')
    return sigs[0]


def assess_response(body, row, request_id, prior=None):
    require(type(body) is dict and body.get('jsonrpc') == '2.0' and type(body.get('id')) is int
            and body['id'] == request_id, 'RPC identity/envelope mismatch')
    if body.get('error') is not None:
        return {'state': 'RPC_ERROR', 'error': body['error']}
    require('result' in body, 'RPC result missing'); value = body['result']; method = row['method']
    if method == 'getTransactionsForAddress':
        require(type(value) is dict and type(value.get('data')) is list and 'paginationToken' in value, 'Indexed page/cursor state unavailable')
        opts = row['params'][1]; records = value['data']; cursor = value['paginationToken']
        require(len(records) <= opts['limit'], 'Indexed response exceeds requested limit')
        require(cursor is None or isinstance(cursor, str) and re.fullmatch(r'[0-9]+:[0-9]+', cursor), 'Unsupported cursor representation')
        require(cursor is None or records, 'Nonterminal empty indexed page')
        positions, signatures, times, failed, versions = [], [], [], 0, set()
        for record in records:
            require(type(record) is dict, 'Indexed record must be an object')
            integer(record.get('slot')); integer(record.get('transactionIndex'))
            require(type(record.get('blockTime')) is int, 'Missing indexed chronology remains a coverage dependency')
            if 'blockTime' in opts['filters']:
                bounds = opts['filters']['blockTime']; require(bounds['gte'] <= record['blockTime'] < bounds['lt'], 'Indexed record outside planned interval')
            if opts['transactionDetails'] == 'full':
                sig = primary_fields(record)
                version = record.get('version', 'legacy')
                require(version == 'legacy' or type(version) is int and version == 0, 'Unsupported transaction version retained as a coverage gap')
                versions.add(str(version)); meta = record.get('meta')
                require(type(meta) is dict and 'err' in meta, 'Full execution state unavailable'); err = meta['err']
            else:
                sig = record.get('signature'); require('err' in record and record.get('confirmationStatus') == 'finalized', 'Finalized signature execution state unavailable'); err = record['err']
            signature(sig); signatures.append(sig); positions.append((record['slot'], record['transactionIndex'])); times.append(record['blockTime']); failed += err is not None
        ascending = opts['sortOrder'] == 'asc'
        require(positions == sorted(positions, reverse=not ascending) and len(set(positions)) == len(positions)
                and len(set(signatures)) == len(signatures), 'Indexed order/identity duplicates or conflict')
        if prior:
            require(cursor is None or cursor not in prior['cursor_chain'], 'Repeated indexed cursor')
            require(not set(signatures).intersection(prior['signature_chain']), 'Repeated indexed signature across continuation')
            if positions and prior['last_position'] is not None:
                require(positions[0] > tuple(prior['last_position']) if ascending else positions[0] < tuple(prior['last_position']), 'Continuation ordering did not advance')
        return {'state': 'OBSERVED', 'rows': len(records), 'failed_records': failed, 'signatures': signatures,
                'cursor': cursor, 'terminal_claim': cursor is None, 'first_position': positions[0] if positions else None,
                'last_position': positions[-1] if positions else None, 'min_block_time': min(times) if times else None,
                'max_block_time': max(times) if times else None, 'versions_observed': sorted(versions),
                'cursor_chain': (prior['cursor_chain'] if prior else []) + ([cursor] if cursor is not None else []),
                'signature_chain': (prior['signature_chain'] if prior else []) + signatures,
                'coverage': 'Provider page observation; terminal cursor does not establish independent historical owner population.'}
    if method == 'getTransaction':
        require(primary_fields(value) == row['params'][0], 'Missing/mismatched primary transaction')
        integer(value.get('slot')); require(type(value.get('blockTime')) is int and type(value.get('meta')) is dict
            and 'err' in value['meta'], 'Primary execution/time fields unavailable')
        return {'state': 'OBSERVED', 'signature': row['params'][0], 'slot': value['slot'], 'block_time': value['blockTime'], 'failed': value['meta']['err'] is not None}
    if method == 'getSignaturesForAddress':
        require(type(value) is list and len(value) <= row['params'][1]['limit'], 'Signature page shape/bound unavailable')
        sigs = []
        for record in value:
            require(type(record) is dict and 'err' in record and record.get('confirmationStatus') == 'finalized', 'Finalized signature record unavailable')
            signature(record.get('signature')); integer(record.get('slot')); sigs.append(record['signature'])
        require(len(set(sigs)) == len(sigs), 'Duplicate signature record')
        return {'state': 'OBSERVED', 'rows': len(value), 'signatures': sigs, 'coverage': 'Direct address page only; no token-account population proof.'}
    if method == 'getSlot':
        integer(value); return {'state': 'OBSERVED', 'finalized_slot': value}
    if method == 'getBlock':
        require(type(value) is dict and type(value.get('transactions')) is list, 'Full block result unavailable')
        for record in value['transactions']: primary_fields(record)
        return {'state': 'OBSERVED', 'requested_slot': row['params'][0], 'transactions': len(value['transactions']), 'block_time': value.get('blockTime')}
    require(type(value) is dict and type(value.get('context')) is dict, 'Account context unavailable'); integer(value['context'].get('slot'))
    require('value' in value, 'Account value unavailable')
    if method == 'getTokenAccountsByOwner':
        require(type(value['value']) is list, 'Current-owner accounts unavailable')
        for account in value['value']:
            try:
                owner = account['account']['data']['parsed']['info']['owner']
                public = account['pubkey']; program = account['account']['owner']
            except (KeyError, TypeError): raise ValueError('Current-owner fields unavailable') from None
            validate_address(public); require(program == row['params'][1]['programId'], 'Current token program mismatch')
            require(owner == row['params'][0], 'Current owner mismatch')
        return {'state': 'OBSERVED', 'accounts': len(value['value']), 'context_slot': value['context']['slot'], 'coverage': 'Current ownership only; historical closed/reassigned lifecycle remains unproved.'}
    if method == 'getBalance': integer(value['value'])
    elif method == 'getAccountInfo' and value['value'] is not None:
        account = value['value']; require(type(account) is dict, 'Account object unavailable')
        validate_address(account.get('owner')); integer(account.get('lamports'))
        require(type(account.get('executable')) is bool and isinstance(account.get('data'), (list, dict)), 'Account execution/data fields unavailable')
    return {'state': 'OBSERVED', 'context_slot': value['context']['slot'], 'account_present': value['value'] is not None}


async def execute(plan, confirmation, key, output, store, *, plan_sha256=None, transport=None):
    validate_plan(plan); validate_confirmation(confirmation, plan['credit_cap'])
    require(isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9_-]{8,200}', key), 'Provider key format invalid')
    require(key not in json.dumps(plan), 'Credential appears in input plan; no dispatch permitted')
    plan = json.loads(json.dumps(plan))
    bind_budget(store, plan, confirmation)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    plan_sha256 = plan_sha256 or sha(json.dumps(plan, sort_keys=True, separators=(',', ':')).encode())
    claim_phase(store, plan, plan_sha256)
    result = {'kind': 'authorised-bounded-native-collection', 'started_utc': now(), 'state': 'RUNNING',
        'budget_id': plan['budget_id'], 'plan_sha256': plan_sha256, 'endpoint': ENDPOINT, 'confirmation': confirmation,
        'request_cap': plan['request_cap'], 'credit_cap': plan['credit_cap'], 'provider_requests': 0, 'conservative_credits': 0,
        'retries': 0, 'purchases': False, 'quota_reset': False, 'quota_before': usage(store, plan, confirmation),
        'billing_actual_credits': None, 'billing_scope': 'Conservative reservations; dashboard snapshot is operator supplied and provider invoice delta is unverified.',
        'requests': [], 'B3': 'BLOCKED', 'PRODUCT_READY': False,
        'scope': 'Raw acquisition only; neither endpoint success nor terminal paging certifies historical population, accounting or wallet qualification.'}
    def save():
        result['quota_after'] = usage(store, plan, confirmation)
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    save(); observations = {}
    logging.getLogger('httpx').setLevel(logging.WARNING); logging.getLogger('httpcore').setLevel(logging.WARNING)
    try:
        async with httpx.AsyncClient(transport=transport, follow_redirects=False, verify=True,
                trust_env=True, timeout=httpx.Timeout(30, connect=10)) as client:
            for planned in plan['requests']:
                row_plan = json.loads(json.dumps(planned)); prior = None
                if 'pagination_from' in row_plan:
                    prior = observations[row_plan['pagination_from']]
                    if prior['cursor'] is None:
                        result['requests'].append({'id': row_plan['id'], 'state': 'NOT_RUN', 'reason': 'Prior indexed response explicitly terminal'}); save(); continue
                    row_plan['params'][1]['paginationToken'] = prior['cursor']
                try: credit, request_reservation = reserve_pair(store, plan, confirmation, row_plan)
                except QuotaExceeded:
                    result.update(state='BLOCKED', reason='Durable independent request/credit cap reached; no dispatch'); break
                number = result['provider_requests'] + 1; prefix = f"{number:02d}-{row_plan['id']}"
                body = json.dumps({'jsonrpc': '2.0', 'id': number, 'method': row_plan['method'], 'params': row_plan['params']}, separators=(',', ':'), allow_nan=False).encode()
                request_path = prefix + '-request.json'
                try: (output / request_path).write_bytes(body)
                except BaseException:
                    store.release(credit); store.release(request_reservation); raise
                row = {'id': row_plan['id'], 'method': row_plan['method'], 'request_id': number,
                    'request_reservation': request_reservation, 'credit_reservation': credit,
                    'conservative_credits': credit_bound(row_plan), 'request_path': request_path, 'request_sha256': sha(body), 'started_utc': now()}
                try:
                    result['requests'].append(row); save(); dispatch_pair(store, credit, request_reservation)
                except BaseException:
                    store.release(credit); store.release(request_reservation); raise
                result['provider_requests'] += 1; result['conservative_credits'] += credit_bound(row_plan); wire = bytearray()
                try:
                    async with client.stream('POST', ENDPOINT, params={'api-key': key}, content=body,
                            headers={'Content-Type': 'application/json', 'Accept': 'application/json'}) as response:
                        row['http_status'] = response.status_code
                        row['secret_reflected_in_response_headers'] = any(key in value for value in response.headers.values())
                        row['response_headers'] = {k: v.replace(key, '[REDACTED]') for k, v in response.headers.items() if k.lower() in SAFE_HEADERS}
                        async for chunk in response.aiter_bytes():
                            require(len(wire) + len(chunk) <= MAX_RESPONSE_BYTES, 'Response exceeds retained-byte bound')
                            wire.extend(chunk)
                    if not retain_response(output, prefix, row, wire, key):
                        row.update(state='SECRET_BEARING_RESPONSE_OMITTED'); result.update(state='STOPPED', reason='Secret-bearing response omitted; no retry'); break
                    if response.status_code != 200:
                        row.update(state='HTTP_ERROR'); result.update(state='STOPPED', reason='HTTP failure; no retry/fallback'); break
                    assessment = assess_response(json.loads(wire), row_plan, number, prior)
                    row['assessment'] = assessment; row['state'] = assessment['state']
                    if assessment['state'] != 'OBSERVED':
                        result.update(state='STOPPED', reason='RPC error/denial; no retry/fallback'); break
                    observations[row_plan['id']] = assessment
                except Exception as exc:
                    if wire and 'response_path' not in row and not row.get('raw_response_omitted'):
                        retain_response(output, prefix, row, wire, key, partial=True)
                    reason = str(exc) if isinstance(exc, ValueError) else 'Provider transport/storage failure (' + type(exc).__name__ + ')'
                    row.update(state='UNSUPPORTED_OR_FAILED', reason=reason.replace(key, '[REDACTED]'))
                    result.update(state='STOPPED', reason=row['reason']); break
                finally:
                    store.settle(credit, charge=True); store.settle(request_reservation, charge=True)
                    row['finished_utc'] = now(); save()
                await asyncio.sleep(1 / 3)
            else: result['state'] = 'COLLECTED_IN_SCOPE'
    except BaseException:
        result.update(state='INTERRUPTED', reason='External interruption; dispatched attempts remain charged'); raise
    finally:
        result['finished_utc'] = now()
        result['artifacts'] = {p.name: {'sha256': sha(p.read_bytes()), 'bytes': p.stat().st_size}
                               for p in output.iterdir() if p.is_file() and p.name != 'result.json'}
        result['unexecuted_request_ids'] = [r['id'] for r in plan['requests'] if r['id'] not in {x['id'] for x in result['requests']}]
        save()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True); parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--confirmation', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    args = parser.parse_args(); plan, plan_hash = load_plan(args.plan, args.plan_sha256)
    confirmation = validate_confirmation(json.loads(args.confirmation.read_bytes()), plan['credit_cap'])
    require(sys.stdin.isatty(), 'Credential input requires an echo-disabled terminal')
    key = getpass.getpass('Previously supplied Helius key (session only): ')
    store = Store(args.data)
    try: result = asyncio.run(execute(plan, confirmation, key, args.output, store, plan_sha256=plan_hash))
    finally: store.close()
    print(json.dumps({k: result[k] for k in ('state', 'budget_id', 'provider_requests', 'conservative_credits', 'B3')}))
    return 0 if result['state'] == 'COLLECTED_IN_SCOPE' else 2


if __name__ == '__main__': raise SystemExit(main())
