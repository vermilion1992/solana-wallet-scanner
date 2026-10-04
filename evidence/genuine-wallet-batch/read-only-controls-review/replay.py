#!/usr/bin/env python3
"""Read-only standard-library reconciliation of the six frozen acquisitions.

No provider imports, credential imports, dispatch or runtime mutation. This is
an acquisition-integrity check, not a historical completeness or product gate.
"""
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[3]
COLLECTION = ROOT / 'evidence/genuine-wallet-batch/collection'
RUNTIME = Path('/workspace/outputs/genuine-wallet-collection-runtime/scanner.sqlite')
BUDGET = 'genuine-wallet-2026-10-04'
PUBLIC_ROOT = 'https://api.geckoterminal.com/api/v2/'
PUBLIC = {'publicTrendingPools', 'publicPoolTrades'}
CAPS = {'requests': 30, 'credits': 1000, 'public_requests': 4}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    assert not path.is_symlink() and path.is_file(), 'Nonregular/symlink artifact'
    return path.read_bytes()


def parse(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result, 'Duplicate JSON member'
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(AssertionError('Nonfinite JSON')))


def decoded(value, width):
    assert isinstance(value, str), 'Missing base58 identity'
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number = 0
    for char in value:
        assert char in alphabet, 'Malformed base58 identity'
        number = number * 58 + alphabet.index(char)
    zeros = len(value) - len(value.lstrip('1'))
    assert zeros + (number.bit_length() + 7) // 8 == width, 'Wrong identity byte width'


def quota_value(quota, name):
    return quota.get(name, {'used': 0, 'reserved': 0, 'cap': CAPS[name],
                            'remaining': CAPS[name], 'cycle_start': '2026-10-02'})


def main():
    totals = {key: 0 for key in CAPS}
    phases, artifacts, raw_bytes, reservation_ids = [], [], 0, set()
    final = parse(read(COLLECTION / 'FINAL_BUDGET.json'))
    for phase in range(1, 7):
        plan_raw = read(COLLECTION / f'PHASE{phase}_PLAN.json')
        receipt_raw = read(COLLECTION / f'phase{phase}/result.json')
        plan, receipt = parse(plan_raw), parse(receipt_raw)
        assert plan['budget_id'] == receipt['budget_id'] == BUDGET
        assert plan['request_cap'] == receipt['request_cap'] == 30
        assert plan['credit_cap'] == receipt['credit_cap'] == 1000
        assert plan['retries'] == receipt['retries'] == 0
        assert receipt['state'] == 'COLLECTED_IN_SCOPE'
        assert receipt['purchases'] is False and receipt['quota_reset'] is False
        assert receipt['PRODUCT_READY'] is False and receipt['B3'] == 'BLOCKED'
        assert receipt['billing_actual_credits'] is None
        assert digest(plan_raw) == receipt['plan_sha256']
        assert digest(receipt_raw) == final['phases'][phase - 1]['result_sha256']
        for name in CAPS:
            q = quota_value(receipt['quota_before'], name)
            assert q['used'] == totals[name] and q['reserved'] == 0 and q['cap'] == CAPS[name]
            assert q['remaining'] == CAPS[name] - totals[name] and q['cycle_start'] == '2026-10-02'
        planned = {row['id']: row for row in plan['requests']}
        assert len(planned) == len(plan['requests'])
        observations, seen_ids, native, public, credit = {}, set(), 0, 0, 0
        for row in receipt['requests']:
            identifier = row['id']
            assert identifier in planned and identifier not in seen_ids
            seen_ids.add(identifier)
            item = deepcopy(planned[identifier])
            ancestor = observations.get(item.get('pagination_from'))
            if row['state'] == 'NOT_RUN':
                assert ancestor is not None and ancestor['result']['paginationToken'] is None
                assert set(row) == {'id', 'state', 'reason'}
                continue
            assert row['state'] == 'OBSERVED' and row['http_status'] == 200
            assert row['method'] == item['method']
            assert row['byte_exact_response_retained'] is True
            assert row['credential_redaction_applied'] is False
            assert row.get('secret_reflected_in_response_headers') is False
            if ancestor is not None:
                cursor = ancestor['result']['paginationToken']
                assert isinstance(cursor, str)
                item['params'][1]['paginationToken'] = cursor
            raws = []
            for field in ('request_path', 'response_path'):
                name = row[field]
                assert isinstance(name, str) and Path(name).name == name
                raw = read(COLLECTION / f'phase{phase}' / name)
                bound = receipt['artifacts'][name]
                assert bound['bytes'] == len(raw) and bound['sha256'] == digest(raw)
                artifacts.append({'path': f'phase{phase}/{name}', **bound})
                raws.append(raw)
            request_raw, compressed = raws
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
                response_raw = stream.read(32 * 1024 * 1024 + 1)
            is_public = item['method'] in PUBLIC
            assert len(response_raw) <= (2_000_000 if is_public else 32 * 1024 * 1024)
            assert len(response_raw) == row['response_bytes']
            assert digest(request_raw) == row['request_sha256']
            assert digest(response_raw) == row['response_sha256']
            raw_bytes += len(request_raw) + len(response_raw)
            request, response = parse(request_raw), parse(response_raw)
            expected_cost = 0 if is_public else 10
            if is_public:
                url = PUBLIC_ROOT + 'networks/solana/'
                if item['method'] == 'publicTrendingPools':
                    assert item['params'] == []
                    url += 'trending_pools'
                    query = {'page': 1}
                else:
                    decoded(item['params'][0], 32)
                    url += 'pools/' + item['params'][0] + '/trades'
                    query = {}
                assert request == {'method': 'GET', 'url': url, 'query': query}
                assert row['source_url'] == url
                assert isinstance(response['data'], list)
                assert row['credit_reservation'] is None
                public += 1
            else:
                number = native + public + 1
                assert request == {'jsonrpc': '2.0', 'id': number,
                                   'method': item['method'], 'params': item['params']}
                assert response['jsonrpc'] == '2.0'
                assert type(response['id']) is int and response['id'] == number
                assert response.get('error') is None and 'result' in response
                value = response['result']
                if item['method'] == 'getTransactionsForAddress':
                    options = item['params'][1]
                    assert options['filters']['status'] == 'any'
                    assert options['filters']['tokenAccounts'] in ('all', 'none')
                    records = value['data']
                    assert isinstance(records, list) and len(records) <= options['limit']
                    assert 'paginationToken' in value
                    positions, signatures = [], []
                    for record in records:
                        assert type(record['slot']) is int and type(record['transactionIndex']) is int
                        assert type(record['blockTime']) is int
                        positions.append((record['slot'], record['transactionIndex']))
                        sig = record['signature'] if options['transactionDetails'] == 'signatures' else record['transaction']['signatures'][0]
                        decoded(sig, 64)
                        signatures.append(sig)
                        if 'blockTime' in options['filters']:
                            bounds = options['filters']['blockTime']
                            assert bounds['gte'] <= record['blockTime'] < bounds['lt']
                    assert positions == sorted(positions, reverse=options['sortOrder'] == 'desc')
                    assert len(set(positions)) == len(positions) and len(set(signatures)) == len(signatures)
                    if options['transactionDetails'] == 'full':
                        expected_cost = 10 * ((options['limit'] + 99) // 100)
                    if ancestor is not None:
                        previous = ancestor['result']['data']
                        prior_signatures = {r['transaction']['signatures'][0] for r in previous}
                        assert not set(signatures).intersection(prior_signatures)
                        if previous and positions:
                            tail = (previous[-1]['slot'], previous[-1]['transactionIndex'])
                            assert positions[0] > tail if options['sortOrder'] == 'asc' else positions[0] < tail
                        assert value['paginationToken'] is None or value['paginationToken'] != ancestor['result']['paginationToken']
                elif item['method'] == 'getTransaction':
                    assert value['transaction']['signatures'][0] == item['params'][0]
                    assert type(value['meta']['fee']) is int and value['meta']['fee'] >= 0
                observations[identifier] = response
                assert row['credit_reservation'] is not None
                native += 1
            assert row['conservative_credits'] == expected_cost
            for field in ('request_reservation', 'credit_reservation', 'public_request_reservation'):
                reservation = row.get(field)
                if reservation is not None:
                    assert reservation not in reservation_ids
                    reservation_ids.add(reservation)
            credit += expected_cost
        assert len(seen_ids) == len(planned)
        assert receipt['provider_requests'] == native + public
        assert receipt['conservative_credits'] == credit
        assert receipt.get('native_provider_requests', native) == native
        assert receipt.get('public_provider_requests', public) == public
        totals['requests'] += native + public
        totals['credits'] += credit
        totals['public_requests'] += public
        for name in CAPS:
            q = quota_value(receipt['quota_after'], name)
            assert q['used'] == totals[name] and q['reserved'] == 0 and q['cap'] == CAPS[name]
            assert q['remaining'] == CAPS[name] - totals[name]
        phases.append({'phase': phase, 'plan_sha256': digest(plan_raw), 'receipt_sha256': digest(receipt_raw),
                       'actual_requests': native + public, 'native_requests': native,
                       'public_requests': public, 'conservative_credits': credit})
    assert totals == {'requests': 19, 'credits': 170, 'public_requests': 2}
    assert final['requests'] == 19 and final['conservative_credits'] == 170 and final['public_requests'] == 2
    connection = sqlite3.connect('file:' + str(RUNTIME) + '?mode=ro', uri=True)
    try:
        reservations = connection.execute('SELECT id,provider,method,cost,state,charged FROM reservations').fetchall()
        assert {r[0] for r in reservations} == reservation_ids
        ledger = []
        for namespace, expected_cost, expected_count in (
                ('helius-collection-requests/' + BUDGET, 19, 19),
                ('helius-collection-credits/' + BUDGET, 170, 17),
                ('geckoterminal-collection-public/' + BUDGET, 2, 2)):
            rows = [r for r in reservations if r[1] == namespace]
            assert len(rows) == expected_count and sum(r[3] for r in rows) == expected_cost
            assert all(r[4] == 'settled' and r[5] == 1 for r in rows)
            ledger.append({'namespace': namespace, 'settled_reservations': len(rows),
                           'charged_units': sum(r[3] for r in rows if r[5] == 1), 'pending_reservations': 0})
        claims = connection.execute("SELECT id,payload FROM records WHERE kind='bounded_collection_phase'").fetchall()
        assert len(claims) == 6
        assert {parse(r[1])['plan_sha256'] for r in claims} == {p['plan_sha256'] for p in phases}
        binding = connection.execute("SELECT payload FROM records WHERE kind='bounded_collection_budget' AND id=?", (BUDGET,)).fetchone()
        assert parse(binding[0]) == {'budget_id': BUDGET, 'request_cap': 30, 'credit_cap': 1000,
                                     'cycle_start': '2026-10-02', 'cycle_end': '2026-11-02',
                                     'endpoint': 'https://mainnet.helius-rpc.com/'}
    finally:
        connection.close()
    files = ['tools/bounded_collection.py', 'tools/check_genuine_collection.py',
             'tests/test_bounded_collection.py', 'tests/test_genuine_collection_workflow.py']
    snapshots = {name: digest(read(COLLECTION / name)) for name in (
        'EXECUTED_NATIVE_COLLECTOR.py', 'EXECUTED_PUBLIC_COLLECTOR.py', 'EXECUTED_FINAL_COLLECTOR.py')}
    assert snapshots['EXECUTED_FINAL_COLLECTOR.py'] == digest(read(ROOT / 'tools/bounded_collection.py'))
    result = {'kind': 'read-only-collection-integrity-reconciliation-v1', 'state': 'PASS',
              'reviewed_utc': datetime.now(timezone.utc).isoformat(), 'dispatches_in_review': 0,
              'credential_accesses_in_review': 0, 'runtime_open_mode': 'SQLite read-only',
              'source_files': {name: digest(read(ROOT / name)) for name in files},
              'executed_snapshots': snapshots, 'phases': phases, 'totals': totals,
              'caps': CAPS, 'ledger': ledger, 'phase_claims': 6,
              'artifact_files': len(artifacts), 'raw_request_response_bytes': raw_bytes,
              'artifact_bindings': artifacts, 'billing_actual_credits': None,
              'execution_source_binding': {'phase1': 'EXECUTED_NATIVE_COLLECTOR.py',
                   'phase2': 'EXECUTED_PUBLIC_COLLECTOR.py', 'phase3': 'EXECUTED_PUBLIC_COLLECTOR.py',
                   'phase4': 'NOT_BOUND: exact dispatch-source snapshot was not captured',
                   'phase5': 'EXECUTED_FINAL_COLLECTOR.py', 'phase6': 'EXECUTED_FINAL_COLLECTOR.py'},
              'limitations': ['Same-engineer read-only review; collector author is reviewer.',
                   'Phase4 exact executed source hash remains unbound; plans/raw bytes/ledger reconcile independently.',
                   'Phase2/3 retain legacy top-level Helius endpoint field; exact GET descriptors and row source_url identify Gecko.',
                   'Provider billing delta, exhaustive historical owner population and genuine wallet acceptance are not established.'],
              'PRODUCT_READY': False}
    path = Path(__file__).with_name('RAW_RECONCILIATION.json')
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'state': result['state'], 'totals': totals, 'artifact_files': len(artifacts),
                      'receipt': str(path.relative_to(ROOT)), 'receipt_sha256': digest(read(path))}))


if __name__ == '__main__':
    main()
