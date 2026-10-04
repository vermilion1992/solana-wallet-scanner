#!/usr/bin/env python3
"""Measure an archived report offline; this is observability, not acceptance.

The default measures display/CSV/source inspection and one immutable rebuild.
--full-details also measures the default full API and JSON export, which can be
hundreds of MB. Private runtime databases/exports stay under the output folder.
No provider, credential, billing, signing or wallet-network operation is allowed.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import cProfile
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import pstats
try:
    import resource
except ImportError:  # Optional Linux process observation, never an app prerequisite.
    resource = None
import socket
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def file_identity(path):
    hasher, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for raw in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(raw)
            size += len(raw)
    return {'path': str(path), 'bytes': size, 'sha256': hasher.hexdigest()}


def source_identity():
    from tools.validate import source_manifest
    manifest = source_manifest(ROOT)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    return {'commit': commit, 'source_sha256': manifest['sha256'],
            'source_file_count': len(manifest['files'])}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n')


def worker_context(args):
    return {'version': 'offline-benchmark-worker-v1', 'archive': str(args.archive),
            'timeout': args.timeout, 'profile': args.profile, 'full_details': args.full_details}


def output_inside_worktree(path):
    if path.is_relative_to(ROOT):
        return True
    ancestor = path
    while not ancestor.exists():
        ancestor = ancestor.parent
    result = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], cwd=ancestor,
                            capture_output=True, text=True)
    return result.returncode == 0 and result.stdout.strip() == 'true'


def saved_identity(store, identifier):
    with store.lock:
        row = store.db.execute("SELECT payload FROM records WHERE kind='reports' AND id=?", (identifier,)).fetchone()
    if row is None:
        raise AssertionError('Saved report is missing')
    raw = row[0].encode()
    return {'bytes': len(raw), 'sha256': digest(raw)}


def worker(args):
    if not __debug__:
        raise RuntimeError('Python optimization disables benchmark guards; use normal Python.')
    output = args.output
    calls = {'provider': 0, 'credential': 0, 'transport': 0, 'socket': 0}
    record = {'kind': 'offline-report-performance-observations-v1', 'state': 'INCOMPLETE',
              'acceptance_run': False, 'product_readiness_claim': False,
              'scope': 'Timing and equivalence for the supplied archive only; source history and wallet qualification remain separate.',
              'profile_enabled': args.profile, 'full_details_enabled': args.full_details,
              'source_before': source_identity(), 'input_before': file_identity(args.archive),
              'python': sys.version, 'interpreter': sys.executable, 'phases': [], 'calls': calls,
              'private_runtime': 'private-runtime', 'timeout_seconds': args.timeout}
    started = time.perf_counter()

    def save():
        write_json(output / 'observations.json', record)

    def denied(name):
        def reject(*_args, **_kwargs):
            calls[name] += 1
            raise AssertionError('Offline benchmark blocked a ' + name + ' attempt')
        return reject

    def phase(name, operation):
        print('START ' + name, flush=True)
        clock = time.perf_counter()
        profile = cProfile.Profile() if args.profile else None
        if profile:
            profile.enable()
        try:
            result = operation()
        except BaseException as error:
            record['phases'].append({'name': name, 'seconds': time.perf_counter() - clock,
                                    'outcome': 'ERROR', 'error_type': type(error).__name__})
            save()
            raise
        finally:
            if profile:
                profile.disable()
                profile.dump_stats(str(output / (name + '.profile')))
                with (output / (name + '-profile.txt')).open('w') as stream:
                    pstats.Stats(profile, stream=stream).sort_stats('cumulative').print_stats(40)
        observation = {'name': name, 'seconds': time.perf_counter() - clock, 'outcome': 'RETURNED'}
        if hasattr(result, 'status_code'):
            observation.update(status_code=result.status_code, response_bytes=len(result.content),
                               response_sha256=digest(result.content))
            if result.status_code != 200:
                raise AssertionError(name + ' returned HTTP ' + str(result.status_code))
        record['phases'].append(observation)
        save()
        print('END ' + name + ' ' + str(round(observation['seconds'], 6)), flush=True)
        return result

    save()
    try:
        from scanner.archive_input import MAX_UPLOAD
        if record['input_before']['bytes'] > MAX_UPLOAD:
            raise ValueError('Archive exceeds the application upload limit')
        content = args.archive.read_bytes()
        assert digest(content) == record['input_before']['sha256']
        (output / 'input.zip').write_bytes(content)
        import httpx
        from fastapi.testclient import TestClient
        import scanner.app as application
        from scanner.providers import Gateway
        original_send = httpx.Client.send

        def local_send(client, *call_args, **call_kwargs):
            if isinstance(client, TestClient):
                return original_send(client, *call_args, **call_kwargs)
            return denied('transport')(client, *call_args, **call_kwargs)

        environment = dict(os.environ)
        environment.pop('HELIUS_API_KEY', None)
        with patch.object(application, 'Credentials', lambda _: SimpleNamespace(key=None, storage='none', backend=None)), \
             patch.object(Gateway, 'rpc', denied('provider')), \
             patch.object(httpx.AsyncClient, 'request', denied('transport')), \
             patch.object(httpx.AsyncClient, 'send', denied('transport')), \
             patch.object(httpx.AsyncHTTPTransport, 'handle_async_request', denied('transport')), \
             patch.object(httpx.Client, 'send', local_send), \
             patch.object(socket, 'create_connection', denied('socket')), \
             patch.object(socket.socket, 'connect', denied('socket')), \
             patch.object(socket.socket, 'connect_ex', denied('socket')), \
             patch.dict(os.environ, environment, clear=True), \
             patch.dict(sys.modules, {'keyring': SimpleNamespace(get_keyring=denied('credential'),
                 get_password=denied('credential'), set_password=denied('credential'))}):
            app = application.create_app(output / 'private-runtime', 'offline-report-benchmark')
            with TestClient(app, base_url='http://127.0.0.1:8765') as client:
                assert client.get('/api/state').status_code == 401
                bootstrap = client.get('/api/bootstrap', headers={'X-Launch-Token': 'offline-report-benchmark'})
                assert bootstrap.status_code == 200
                client.headers['X-CSRF-Token'] = bootstrap.json()['csrf']
                usage = deepcopy(client.get('/api/usage').json())
                imported = phase('archive-import', lambda: client.post('/api/archives/import', content=content,
                    headers={'Content-Type': 'application/zip'})).json()
                assert imported['provider_requests'] == 0
                identifier = imported['report_id']
                before = saved_identity(app.state.store, identifier)
                parent = phase('report-display', lambda: client.get('/api/reports/' + identifier + '?view=display')).json()
                metrics = deepcopy(parent['metrics'])
                record['parent'] = {'report_id': identifier, 'saved_payload': before,
                    'dataset': imported['dataset'], 'window': parent['window'],
                    'preset': deepcopy(parent['preset']), 'archive_input_hash': parent['archive_input_hash'],
                    'evidence_status': parent.get('evidence_status'),
                    'qualification': parent.get('qualification'),
                    'fee_observation': metrics.get('observed_network_fees_sol'),
                    'population_scope': parent.get('coverage', {}).get('indexed_sources', {}).get('historical_population')}
                inspected = []
                for kind in ('indexed-page', 'indexed-native-source', 'transaction'):
                    for ref in parent.get('evidence', []):
                        if (isinstance(ref, dict) and ref.get('kind') == kind
                                and isinstance(ref.get('hash'), str) and ref['hash'] not in inspected
                                and len(inspected) < 4):
                            inspected.append(ref['hash'])
                for index, identifier_hash in enumerate(inspected):
                    response = phase('source-inspection-' + str(index + 1),
                        lambda h=identifier_hash: client.get('/api/evidence/' + h))
                    payload = response.json()
                    canonical = json.dumps(payload, ensure_ascii=False, allow_nan=False,
                                           sort_keys=True, separators=(',', ':')).encode()
                    assert digest(canonical) == identifier_hash
                record['source_inspection'] = {'hashes': inspected, 'canonical_checksums_matched': True,
                    'scope': 'Up to four selected original archive sources; not historical-population acceptance.'}
                csv_response = phase('csv-export', lambda: client.get('/api/export/reports/' + identifier + '.csv'))
                csv_rows = {row['metric']: row for row in csv.DictReader(io.StringIO(csv_response.text))}
                assert set(csv_rows) == set(metrics)
                for name, metric in metrics.items():
                    assert csv_rows[name]['status'] == metric.get('status', '')
                if args.full_details:
                    full = phase('report-default-full', lambda: client.get('/api/reports/' + identifier)).json()
                    exported = phase('json-export', lambda: client.get('/api/export/reports/' + identifier + '.json')).json()
                    assert exported == full and full['metrics'] == metrics
                    record['full_export_equivalence'] = True
                    del full, exported
                else:
                    record['not_measured'] = ['default full GET', 'full JSON export']
                phase('state-summary', lambda: client.get('/api/state?report_view=summary'))
                del parent
                rebuilt = phase('same-input-rebuild', lambda: client.post('/api/reports/' + identifier + '/rebuild')).json()
                child = phase('child-display', lambda: client.get('/api/reports/' + rebuilt['report_id'] + '?view=display')).json()
                assert child['id'] != identifier and child['rebuilt_from'] == identifier
                assert child['window'] == record['parent']['window'] and child['metrics'] == metrics
                assert child['preset'] == record['parent']['preset']
                assert child['archive_input_hash'] == record['parent']['archive_input_hash']
                assert child['rebuild']['provider_requests'] == 0
                assert saved_identity(app.state.store, identifier) == before
                assert client.get('/api/usage').json() == usage
                assert not app.state.store.list('collector_checkpoints')
                assert all(count == 0 for count in calls.values())
                record['invariants'] = {'immutable_parent_payload': True, 'rebuilt_metrics_equal': True,
                    'same_window': True, 'same_preset': True, 'same_archive_input': True,
                    'usage_unchanged': True, 'zero_provider_credential_transport_socket': True,
                    'no_collector_ancestry': True}
        record['source_after'] = source_identity()
        record['input_after'] = file_identity(args.archive)
        assert record['source_before'] == record['source_after']
        assert record['input_before'] == record['input_after']
        assert digest(content) == digest((output / 'input.zip').read_bytes())
        record['state'] = 'OBSERVED'
        return 0
    except BaseException as error:
        record['state'] = 'FAILED'
        record['error'] = {'type': type(error).__name__, 'message': str(error)}
        traceback.print_exc()
        return 1
    finally:
        record['seconds'] = time.perf_counter() - started
        record['peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if resource is not None and sys.platform == 'linux' else None
        record['rss_scope'] = 'Linux peak resident set in KiB' if record['peak_rss_kib'] is not None else 'Unavailable; RSS is an optional Linux observation.'
        save()
        print('FINAL ' + record['state'], flush=True)


def main(*, _worker=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True, help='Existing local archive; no live collection')
    parser.add_argument('--output', type=Path, required=True, help='Fresh directory; contains private generated runtime state')
    parser.add_argument('--full-details', action='store_true', help='Also measure full GET/JSON export; large responses can be hundreds of MB')
    parser.add_argument('--profile', action='store_true', help='Enable cProfile; profiled timings include instrumentation overhead')
    parser.add_argument('--timeout', type=int, default=300, help='Whole worker watchdog, 1–300 seconds')
    args = parser.parse_args()
    if not __debug__:
        parser.error('Python -O disables benchmark guards; use normal Python.')
    args.archive = args.archive.expanduser().resolve(strict=True)
    args.output = args.output.expanduser().resolve()
    if not 1 <= args.timeout <= 300:
        parser.error('--timeout must be between 1 and 300 seconds')
    if output_inside_worktree(args.output):
        parser.error('--output must be outside every Git worktree; it contains private runtime state.')
    from scanner.archive_input import MAX_UPLOAD
    if args.archive.stat().st_size > MAX_UPLOAD:
        parser.error('Archive exceeds the application upload limit')
    if _worker:
        marker = args.output / 'worker-context.json'
        try:
            valid_context = (json.loads(marker.read_text()) == worker_context(args)
                             and {path.name for path in args.output.iterdir()}
                             == {'worker-context.json', 'benchmark.log'})
        except (OSError, ValueError):
            valid_context = False
        if not valid_context:
            parser.error('Internal worker needs a fresh parent-created output context.')
        return worker(args)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / 'worker-context.json', worker_context(args))
    # All public CLI invocations take the watchdog path. This import/call is a
    # private child entry, not a user-selectable flag that can bypass the parent.
    child_entry = 'from tools.benchmark_report import main; raise SystemExit(main(_worker=True))'
    command = [sys.executable, '-c', child_entry, '--archive', str(args.archive),
               '--output', str(args.output), '--timeout', str(args.timeout)]
    for enabled, flag in ((args.profile, '--profile'), (args.full_details, '--full-details')):
        if enabled:
            command.append(flag)
    clock = time.perf_counter()
    outer = {'kind': 'offline-report-performance-command-v1', 'acceptance_run': False,
             'command': command, 'cwd': str(ROOT), 'timeout_seconds': args.timeout}
    log = args.output / 'benchmark.log'
    with log.open('wb') as stream:
        try:
            completed = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=args.timeout)
            outer.update(exit_code=completed.returncode, timed_out=False)
        except subprocess.TimeoutExpired:
            outer.update(exit_code=None, timed_out=True)
    outer['seconds'] = time.perf_counter() - clock
    outer['raw_log'] = file_identity(log)
    outer['observations'] = file_identity(args.output / 'observations.json') if (args.output / 'observations.json').exists() else None
    write_json(args.output / 'command.json', outer)
    print(json.dumps(outer, indent=2))
    return 124 if outer['timed_out'] else outer['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
