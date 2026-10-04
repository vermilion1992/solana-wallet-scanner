#!/usr/bin/env python3
"""Execute the four preserved offline workflows on an explicitly frozen source.

Default invocation prepares/checks the exact plan without executing application
workflows. Add --execute only after the application commit and source are frozen.
The separate --storage-only action losslessly stores this runner's completed
public JSON exports; it never changes original archives, oracles or runtime data.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import signal
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path('/workspace/solana-wallet-scanner')
SCRIPT = Path(__file__).resolve()
DEFAULT_OUTPUT = ROOT / 'evidence/position-history-batch/final-replays'
BASELINE_INDEX = ROOT / 'evidence/metric-completion-batch/final-replays-accepted/INDEX.json'
PRODUCT_INPUT_BEFORE = SCRIPT.parent / 'PRODUCT_CORPUS_BEFORE.json'
PRODUCT_INPUT_BEFORE_SHA = 'ab9637585f48f415ffa76e86be89b4e0c7a9124167afe7d6d879f28bb786ff1c'
INPUTS = {
    'evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip':
        {'bytes': 156832, 'sha256': 'eec702fdd821066897710d2085bf5c39380e303e8426249e22fb6379b7ccf1b4'},
    'evidence/genuine-wallet-batch/checker-inputs/FINAL_INPUT_FREEZE.json':
        {'bytes': 2783, 'sha256': '25f752be59154d13e8d57a15b7afcc2191582a4665f4c886ef12e22d7d0284f7'},
    'evidence/genuine-wallet-batch/WORKED_REAL_EXPECTATIONS_FINAL.json':
        {'bytes': 177454, 'sha256': '97c9f92202398aef69ef0e2ce78f3d81ef67814187ca233ce5c36f8363cde9ba'},
}
CASE_KEYS = ('case', 'report_role', 'lot_index', 'role')
MAX_COMMAND_SECONDS = 300
MAX_TOTAL_SECONDS = 600


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def facts(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected regular local file: ' + str(path))
    return {'bytes': path.stat().st_size, 'sha256': sha(path)}


def strict_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON value')))


def write(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def identity():
    sys.path.insert(0, str(ROOT))
    from tools.validate import source_manifest
    manifest = source_manifest(ROOT)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    return {'commit': commit, 'source_sha256': manifest['sha256'], 'source_file_count': len(manifest['files'])}


def product_expected_inputs():
    if sha(PRODUCT_INPUT_BEFORE) != PRODUCT_INPUT_BEFORE_SHA:
        raise ValueError('Preserved product input inventory identity changed')
    inventory = strict_json(PRODUCT_INPUT_BEFORE)
    if (inventory.get('state') != 'PASS' or inventory.get('all_equal_preserved_baseline_bytes') is not True
        or inventory.get('baseline_commit') != '1040215f498b1317b1b942838994127f43a822bd'):
        raise ValueError('Product input inventory lacks original byte bindings')
    result = {row['path']: {'bytes': row['bytes'], 'sha256': row['sha256']} for row in inventory['files']}
    names = {str(p.relative_to(ROOT)) for p in (ROOT / 'evidence/runs/real-cache').rglob('*') if p.is_file()}
    if set(result) != names or len(result) != inventory['file_count']:
        raise ValueError('Original product input corpus file population changed')
    return result


def inputs():
    result = {name: facts(ROOT / name) for name in INPUTS}
    if result != INPUTS:
        raise ValueError('An original archive, freeze or worked oracle changed')
    freeze = strict_json(ROOT / list(INPUTS)[1])
    worked = strict_json(ROOT / list(INPUTS)[2])
    if (freeze.get('kind') != 'offline-genuine-checker-input-freeze'
        or freeze.get('archive_sha256') != INPUTS[list(INPUTS)[0]]['sha256']
        or worked.get('archive_sha256') != freeze['archive_sha256']
        or worked.get('PRODUCT_READY') is not False):
        raise ValueError('Frozen input and original independently worked oracle identities disagree')
    product_expected = product_expected_inputs()
    product_observed = {name: facts(ROOT / name) for name in product_expected}
    if product_expected != product_observed:
        raise ValueError('Original product partial-corpus bytes changed')
    return {**result, **product_observed}


def check_identity(expected):
    observed = identity()
    if observed['commit'] != expected['commit'] or observed['source_sha256'] != expected['source_sha256']:
        raise ValueError('Exact frozen candidate identity mismatch: ' + json.dumps(observed, sort_keys=True))
    inputs()
    return observed


def case_identity(case):
    return tuple(case.get(key) for key in CASE_KEYS)


def plans(output):
    baseline = strict_json(BASELINE_INDEX)
    if baseline.get('state') != 'PASS' or baseline.get('kind') != 'four-frozen-offline-entrypoints':
        raise ValueError('Preserved four-workflow command index is unusable')
    rows = []
    for old in baseline['commands']:
        name = old['name']
        if name not in ('genuine-development', 'genuine-real-acceptance', 'product-development', 'product-real-acceptance'):
            raise ValueError('Unexpected original workflow command')
        original = list(old['command'])
        original[0] = str(ROOT / '.venv/bin/python')
        original[original.index('--output') + 1] = str(output / name)
        prior = strict_json(ROOT / old['receipt'])
        cases = prior.get('cases')
        if not isinstance(cases, list) or not cases or not all(c.get('state') == 'PASS' for c in cases):
            raise ValueError('Preserved explicit case evidence is unusable')
        rows.append({'name': name, 'application_command': original, 'expected_exit_code': old['expected_exit_code'],
            'expected_state': old['receipt_state'], 'expected_kind': prior['kind'],
            'required_case_identities': [case_identity(case) for case in cases]})
    if [row['name'] for row in rows] != ['genuine-development', 'genuine-real-acceptance', 'product-development', 'product-real-acceptance']:
        raise ValueError('Exact four-command sequential plan required')
    return rows


def offline_child(argv):
    """Run the original application entry point with counted denied sockets."""
    target = Path(argv[0]).resolve(strict=True)
    if target not in (ROOT / 'tools/check_genuine_collection.py', ROOT / 'tools/check_product.py'):
        raise ValueError('Unsupported offline entry point')
    args = argv[1:]
    output = Path(args[args.index('--output') + 1])
    counts = {'socket_attempts': 0, 'bootstrap_credential_attempts': 0}
    def denied_socket(*args, **kwargs):
        counts['socket_attempts'] += 1
        raise AssertionError('Offline replay attempted a socket or name lookup')
    def denied_credential(*args, **kwargs):
        counts['bootstrap_credential_attempts'] += 1
        raise AssertionError('Offline replay attempted credentials before checker guards')
    socket.socket.connect = denied_socket
    socket.socket.connect_ex = denied_socket
    socket.create_connection = denied_socket
    socket.getaddrinfo = denied_socket
    sys.modules['keyring'] = SimpleNamespace(get_keyring=denied_credential,
        get_password=denied_credential, set_password=denied_credential)
    sys.path.insert(0, str(ROOT))
    sys.argv = [str(target), *args]
    exit_code = 1
    try:
        runpy.run_path(str(target), run_name='__main__')
        exit_code = 0
    except SystemExit as exc:
        exit_code = exc.code if type(exc.code) is int else 0 if exc.code is None else 1
    finally:
        if output.is_dir():
            write(output / 'OFFLINE_GUARD.json', {'kind': 'counted-offline-python-guards',
                'state': 'PASS' if counts == {'socket_attempts': 0, 'bootstrap_credential_attempts': 0} else 'FAILED',
                **counts, 'application_command': [str(target), *args], 'application_exit_code': exit_code})
    return exit_code


def receipt_checks(record, plan, output, guard):
    obj = isinstance(record, dict)
    record = record if obj else {}
    cases = record.get('cases')
    valid_cases = isinstance(cases, list) and bool(cases) and all(isinstance(c, dict) and c.get('state') == 'PASS' for c in cases)
    expected_cases = [tuple(case) for case in plan['required_case_identities']]
    ids = [case_identity(c) for c in cases] if valid_cases else []
    checks = {'receipt_object': obj, 'kind': record.get('kind') == plan['expected_kind'],
        'state': record.get('state') == plan['expected_state'], 'cases_explicitly_passing': valid_cases,
        'all_original_cases_preserved_once': sorted(ids, key=repr) == sorted(expected_cases, key=repr),
        'provider_requests_zero': type(record.get('provider_requests')) is int and record['provider_requests'] == 0,
        'credential_lookups_zero': type(record.get('credential_lookups')) is int and record['credential_lookups'] == 0,
        'parent_unchanged': record.get('parent_unchanged') is True,
        'real_acceptance_blocked': isinstance(record.get('real_acceptance'), dict) and record['real_acceptance'].get('state') == 'BLOCKED',
        'no_collector_ancestry': record.get('collector_ancestry_created') is False,
        'counted_offline_guard_pass': isinstance(guard, dict) and guard.get('kind') == 'counted-offline-python-guards'
            and guard.get('state') == 'PASS' and type(guard.get('socket_attempts')) is int and guard['socket_attempts'] == 0
            and type(guard.get('bootstrap_credential_attempts')) is int and guard['bootstrap_credential_attempts'] == 0
            and guard.get('application_command') == plan['application_command'][1:]
            and type(guard.get('application_exit_code')) is int
            and guard.get('application_exit_code') == plan['expected_exit_code']}
    if plan['name'].startswith('genuine-'):
        freeze = strict_json(ROOT / 'evidence/genuine-wallet-batch/checker-inputs/FINAL_INPUT_FREEZE.json')
        original_worked = strict_json(ROOT / 'evidence/genuine-wallet-batch/WORKED_REAL_EXPECTATIONS_FINAL.json')
        expected_worked = hashlib.sha256((json.dumps(original_worked, indent=2) + '\n').encode()).hexdigest()
        checks.update(usage_unchanged=record.get('usage_unchanged') is True,
            product_ready_false=record.get('PRODUCT_READY') is False,
            oracle_frozen_before_application=record.get('oracle_frozen_before_application') is True,
            original_archive_identity=record.get('archive_sha256') == freeze['archive_sha256']
                and facts(output / 'input.zip') == INPUTS['evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip'],
            exact_raw_oracle=record.get('oracle_sha256') == freeze['oracle_sha256'] and sha(output / 'EXPECTED_RAW.json') == freeze['oracle_sha256'],
            exact_worked_oracle=record.get('worked_expectations_sha256') == expected_worked and sha(output / 'EXPECTED_WORKED.json') == expected_worked,
            all_restored_lot_expectations_pass=valid_cases and all(c.get('parent_unchanged') is True
                and isinstance(c.get('restored_expectations'), dict) and c['restored_expectations'].get('state') == 'PASS'
                for c in cases if c['case'] == 'selected-lot-required-source-loss-exact-restoration'))
    else:
        checks.update(development_passing=isinstance(record.get('development'), dict) and record['development'].get('state') == 'PASS',
            usage_unchanged=isinstance(record.get('usage_before'), dict) and record.get('usage_after') == record['usage_before'],
            real_acceptance_mode=record.get('real_acceptance_required') is plan['name'].endswith('real-acceptance'),
            all_removed_case_parents_unchanged=valid_cases and all(c.get('parent_unchanged') is True
                for c in cases if c['case'] in ('valuation_hash-loss-and-exact-restoration', 'world_hash-loss-and-exact-restoration')),
            original_product_corpus_identity=all(facts(ROOT / name) == expected for name, expected in product_expected_inputs().items()))
    return checks


def confined_output(path):
    path = Path(path).absolute()
    if path.is_symlink() or path.resolve() != path or not path.is_relative_to(ROOT / 'evidence/position-history-batch'):
        raise ValueError('Output must be a confined nonsymlink path under this batch evidence directory')
    return path


def execute(args):
    output = confined_output(args.output)
    expected = {'commit': args.application_commit, 'source_sha256': args.source_sha}
    before = check_identity(expected)
    before_inputs = inputs()
    plan = plans(output)
    if not args.execute:
        print(json.dumps({'state': 'PREPARED_NOT_EXECUTED', **before, 'inputs': before_inputs,
            'commands': plan, 'command_timeout_seconds': MAX_COMMAND_SECONDS, 'total_timeout_seconds': MAX_TOTAL_SECONDS}, indent=2))
        return 0
    output.mkdir(parents=True, exist_ok=False)
    index = {'kind': 'four-frozen-offline-entrypoints', 'state': 'RUNNING', 'started_at': now(),
        **before, 'application_commit': args.application_commit, 'PRODUCT_READY': False,
        'inputs_before': before_inputs, 'commands': [], 'command_timeout_seconds': MAX_COMMAND_SECONDS,
        'total_timeout_seconds': MAX_TOTAL_SECONDS, 'runner': {'path': str(SCRIPT), **facts(SCRIPT)},
        'scope': 'Development workflow validation and explicit real-acceptance blockage; no full product-readiness claim.'}
    write(output / 'INDEX.json', index)
    deadline = time.monotonic() + MAX_TOTAL_SECONDS
    try:
        for item in plan:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Independent total replay budget exhausted')
            pre = check_identity(expected)
            log_path = output / (item['name'] + '.log')
            command = [item['application_command'][0], str(SCRIPT), '--offline-child', *item['application_command'][1:]]
            row = {'name': item['name'], 'command': command, 'application_command': item['application_command'],
                'expected_exit_code': item['expected_exit_code'], 'started_at': now(), 'state': 'RUNNING',
                'timeout_seconds': min(MAX_COMMAND_SECONDS, remaining), 'source_before': pre}
            index['commands'].append(row)
            write(output / 'INDEX.json', index)
            started = time.monotonic()
            timed_out = False
            with log_path.open('wb') as log:
                child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    exit_code = child.wait(timeout=row['timeout_seconds'])
                except subprocess.TimeoutExpired:
                    timed_out = True
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        exit_code = child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        exit_code = child.wait(timeout=5)
            row.update(exit_code=exit_code, timed_out=timed_out, seconds=time.monotonic() - started, finished_at=now(),
                log=str(log_path.relative_to(ROOT)), log_sha256=sha(log_path), log_bytes=log_path.stat().st_size)
            child_output = output / item['name']
            receipt_path = child_output / 'result.json'
            guard_path = child_output / 'OFFLINE_GUARD.json'
            try:
                record, guard = strict_json(receipt_path), strict_json(guard_path)
                checks = receipt_checks(record, item, child_output, guard)
                row.update(receipt=str(receipt_path.relative_to(ROOT)), receipt_sha256=sha(receipt_path), receipt_bytes=receipt_path.stat().st_size,
                    offline_guard=str(guard_path.relative_to(ROOT)), offline_guard_sha256=sha(guard_path),
                    receipt_state=record.get('state'), real_acceptance_state=record.get('real_acceptance', {}).get('state'))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                checks = {'usable_complete_receipt': False}
                row['receipt_error'] = type(exc).__name__ + ': ' + str(exc)
            post = check_identity(expected)
            checks.update(expected_exit=exit_code == item['expected_exit_code'], not_timed_out=not timed_out,
                exact_commit_before=pre['commit'] == expected['commit'], exact_commit_after=post['commit'] == expected['commit'],
                exact_source_before=pre['source_sha256'] == expected['source_sha256'], exact_source_after=post['source_sha256'] == expected['source_sha256'],
                original_inputs_unchanged=inputs() == before_inputs)
            row.update(checks=checks, source_after=post,
                state=('PASS_EXPECTED_REAL_BLOCK' if item['expected_exit_code'] == 2 else 'PASS') if all(checks.values()) else 'FAILED')
            write(output / 'INDEX.json', index)
            print(json.dumps({'name': item['name'], 'state': row['state'], 'exit_code': exit_code,
                'seconds': row['seconds'], 'receipt_state': row.get('receipt_state')}, sort_keys=True), flush=True)
            if row['state'] == 'FAILED':
                raise ValueError('Executed workflow failed strict command/receipt checks: ' + item['name'])
        after = check_identity(expected)
        index.update(state='PASS', finished_at=now(), inputs_after=inputs(), source_after=after,
            source_unchanged=before['source_sha256'] == after['source_sha256'], commit_unchanged=before['commit'] == after['commit'],
            original_inputs_unchanged=before_inputs == inputs())
    except Exception as exc:
        index.update(state='BLOCKED' if isinstance(exc, TimeoutError) else 'FAILED', finished_at=now(),
            error=type(exc).__name__ + ': ' + str(exc), commands_not_run=[p['name'] for p in plan[len(index['commands']):]])
        write(output / 'INDEX.json', index)
        raise
    write(output / 'INDEX.json', index)
    return 0


def store_exports(args):
    output = confined_output(args.output)
    index = strict_json(output / 'INDEX.json')
    expected = {'commit': args.application_commit, 'source_sha256': args.source_sha}
    check_identity(expected)
    if index.get('state') != 'PASS' or index.get('commit') != args.application_commit or index.get('source_sha256') != args.source_sha:
        raise ValueError('Storage requires this exact completed passing replay index')
    protected = {'EXPECTED_RAW.json', 'EXPECTED_WORKED.json', 'result.json', 'OFFLINE_GUARD.json'}
    files = [p for p in output.glob('*/*.json') if p.name not in protected
             and p.is_file() and not p.is_symlink() and p.stat().st_size > 2 * 1024 * 1024]
    records = []
    for path in sorted(files):
        before = facts(path)
        destination = path.with_name(path.name + '.gz')
        if destination.exists():
            raise ValueError('Refusing to overwrite an existing stored export')
        with path.open('rb') as source, destination.open('xb') as raw_target:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw_target, mtime=0, compresslevel=6) as target:
                while chunk := source.read(1024 * 1024):
                    target.write(chunk)
        restored, count = hashlib.sha256(), 0
        with gzip.open(destination, 'rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                restored.update(chunk)
                count += len(chunk)
        if restored.hexdigest() != before['sha256'] or count != before['bytes'] or facts(path) != before:
            raise ValueError('Export lossless roundtrip or original stability failed')
        records.append({'original': str(path.relative_to(output)), 'original_bytes': count,
            'original_sha256': before['sha256'], 'stored': str(destination.relative_to(output)),
            'stored_bytes': destination.stat().st_size, 'stored_sha256': sha(destination),
            'encoding': 'gzip', 'roundtrip_verified': True, 'original_unchanged': True,
            'original_retained': True,
            'reconstruction': 'Decompress this individual gzip to recover exact original JSON bytes.'})
    storage = {'kind': 'lossless-completed-workflow-export-storage', 'state': 'RUNNING', 'started_at': now(),
        'threshold_bytes': 2 * 1024 * 1024, 'originals_retained': True,
        'verified_flat_removal_requested': args.remove_verified_flat,
        'compressed_files': len(records), 'original_bytes': sum(r['original_bytes'] for r in records),
        'stored_bytes': sum(r['stored_bytes'] for r in records), 'records': records,
        'scope': 'Only this runner\'s completed public exports; original input archives/oracles and all runtime databases untouched.'}
    write(output / 'STORAGE_INDEX.json', storage)
    try:
        if args.remove_verified_flat:
            # Preflight every file before removing any duplicate. The fsynced
            # RUNNING receipt above records actual retained originals.
            for record in records:
                path = output / record['original']
                tracked = subprocess.check_output(['git', 'ls-files', '--', str(path.relative_to(ROOT))], cwd=ROOT)
                if tracked.strip() or facts(path) != {'bytes': record['original_bytes'], 'sha256': record['original_sha256']}:
                    raise ValueError('Flat duplicate changed or became tracked; refusing removal')
            for record in records:
                path = output / record['original']
                if facts(path) != {'bytes': record['original_bytes'], 'sha256': record['original_sha256']}:
                    raise ValueError('Flat duplicate changed after removal preflight')
                path.unlink()
                record['original_retained'] = False
                storage['originals_retained'] = all(r['original_retained'] for r in records)
                write(output / 'STORAGE_INDEX.json', storage)
        check_identity(expected)
        storage.update(state='PASS', finished_at=now(), originals_retained=all(r['original_retained'] for r in records))
        write(output / 'STORAGE_INDEX.json', storage)
    except Exception as exc:
        for record in records:
            record['original_retained'] = (output / record['original']).is_file()
        storage.update(state='BLOCKED', finished_at=now(), originals_retained=all(r['original_retained'] for r in records),
            error=type(exc).__name__ + ': ' + str(exc))
        write(output / 'STORAGE_INDEX.json', storage)
        raise
    print(json.dumps({'state': 'PASS', 'compressed_files': len(records), 'stored_bytes': storage['stored_bytes'],
        'original_bytes': storage['original_bytes'], 'originals_retained': storage['originals_retained']}, sort_keys=True))
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == '--offline-child':
        return offline_child(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application-commit', required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--execute', action='store_true')
    actions.add_argument('--storage-only', action='store_true')
    parser.add_argument('--remove-verified-flat', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{40}', args.application_commit) or not re.fullmatch('[a-f0-9]{64}', args.source_sha):
        parser.error('Require exact full application commit and source SHA-256')
    if args.remove_verified_flat and not args.storage_only:
        parser.error('--remove-verified-flat only accompanies --storage-only after gates stop')
    return store_exports(args) if args.storage_only else execute(args)


if __name__ == '__main__':
    raise SystemExit(main())
