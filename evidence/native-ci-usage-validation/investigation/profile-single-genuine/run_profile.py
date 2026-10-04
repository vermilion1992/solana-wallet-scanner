from __future__ import annotations
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path('/workspace/solana-wallet-scanner')
OUT = Path(__file__).resolve().parent
NODE = 'tests/test_indexed_report_integration.py::test_genuine_authorized_two_pages_reach_normal_report_with_exact_independent_fee_sum_and_no_profit_claim'
sys.path.insert(0, str(ROOT))
from tools.validate import source_manifest, lock_hashes


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def snapshot(label):
    source = source_manifest(ROOT)
    inputs = {}
    probe = ROOT / 'evidence/source-probe-2026-10-04/live'
    for stem in ('02-all-index', '03-all-continuation'):
        for suffix in ('-request.json', '-response.raw.gz'):
            path = probe / (stem + suffix)
            raw = path.read_bytes()
            inputs[str(path.relative_to(ROOT))] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'mode': path.stat().st_mode & 0o777}
            if suffix.endswith('.gz'):
                inputs[str(path.relative_to(ROOT))]['uncompressed_sha256'] = hashlib.sha256(gzip.decompress(raw)).hexdigest()
    value = {'source': source, 'locks': lock_hashes(ROOT), 'commit': git('rev-parse', 'HEAD'),
             'branch': git('branch', '--show-current'), 'git_status': git('status', '--porcelain=v1', '-z'),
             'tracked_diff_sha256': hashlib.sha256(subprocess.check_output(['git', 'diff', 'HEAD', '--binary'], cwd=ROOT)).hexdigest(), 'original_inputs': inputs}
    (OUT / (label + '.json')).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    return value


def proc_sample(pid):
    try:
        raw = Path(f'/proc/{pid}/status').read_text()
    except FileNotFoundError:
        return None
    selected = {}
    for line in raw.splitlines():
        key, _, value = line.partition(':')
        if key in ('State', 'VmRSS', 'VmHWM', 'VmSize', 'Threads'):
            selected[key] = value.strip()
    return selected

before = snapshot('before')
if before['source']['sha256'] != '05143c96aea6afd96ede6006fb27b99bf26e648611cf161fe620306154284e96':
    raise SystemExit('Frozen source manifest mismatch; test not run.')
env = {key: value for key, value in os.environ.items() if key != 'HELIUS_API_KEY'}
env['PYTHONDONTWRITEBYTECODE'] = '1'
env['PYTHONUNBUFFERED'] = '1'
env['PYTHONPATH'] = str(OUT) + os.pathsep + str(ROOT)
command = [str(ROOT / '.venv/bin/python'), '-m', 'pytest', '-vv', '-s', '--durations=0',
           '-p', 'native_profile_plugin', '-o', 'cache_dir=' + str(OUT / 'pytest-cache'),
           '--basetemp=' + str(OUT / 'pytest-temp'), NODE]
receipt = {'kind': 'bounded-read-only-current-source-performance-investigation', 'command': command,
           'cwd': str(ROOT), 'started_at_utc': datetime.now(timezone.utc).isoformat(), 'timeout_seconds': 600,
           'scope': 'one original genuine two-page test; original offline fixtures/assertions unchanged',
           'instrumentation': str(OUT / 'native_profile_plugin.py'), 'resource_method': 'os.wait4 rusage + /proc sampled per-process RSS; /usr/bin/time unavailable',
           'before_source_sha256': before['source']['sha256'], 'source_file_count': len(before['source']['files'])}
(OUT / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
start = time.monotonic()
timed_out = False
killed = False
last_notice = start
max_sample_rss = 0
with (OUT / 'stdout.log').open('w') as stdout, (OUT / 'process-samples.jsonl').open('w') as samples:
    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stdout, stderr=subprocess.STDOUT, start_new_session=True)
    receipt['pid'] = process.pid
    receipt['process_group'] = process.pid
    print('Started bounded single-node pytest, pid', process.pid, flush=True)
    while True:
        sample = proc_sample(process.pid)
        elapsed = time.monotonic() - start
        if sample:
            if 'VmRSS' in sample:
                max_sample_rss = max(max_sample_rss, int(sample['VmRSS'].split()[0]))
            samples.write(json.dumps({'elapsed_seconds': round(elapsed, 6), 'pid': process.pid, **sample}) + '\n')
            samples.flush()
        waited_pid, status, usage = os.wait4(process.pid, os.WNOHANG)
        if waited_pid:
            process.returncode = os.waitstatus_to_exitcode(status)
            break
        if elapsed >= 600 and not timed_out:
            timed_out = True
            receipt['termination'] = 'private child process group SIGTERM at 600s; SIGKILL after 5s if needed'
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            stdout.write('\nPROFILE_COMMAND_TIMEOUT: limit=600s; private child process group signalled\n')
            stdout.flush()
        if timed_out and elapsed >= 605 and not killed:
            killed = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if time.monotonic() - last_notice >= 30:
            print(f'Bounded pytest active: {elapsed:.1f}s, sampled peak RSS {max_sample_rss} KiB', flush=True)
            last_notice = time.monotonic()
        time.sleep(.5)
    if timed_out:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
receipt.update(exit_code=process.returncode, timed_out=timed_out, duration_seconds=time.monotonic() - start,
               child_resource_usage={'user_seconds': usage.ru_utime, 'system_seconds': usage.ru_stime,
               'max_rss_kib': usage.ru_maxrss, 'minor_page_faults': usage.ru_minflt, 'major_page_faults': usage.ru_majflt,
               'voluntary_context_switches': usage.ru_nvcsw, 'involuntary_context_switches': usage.ru_nivcsw},
               sampled_peak_rss_kib=max_sample_rss)
after = snapshot('after')
receipt.update(after_source_sha256=after['source']['sha256'], source_unchanged=before['source'] == after['source'],
               git_unchanged=all(before[key] == after[key] for key in ('commit', 'branch', 'git_status', 'tracked_diff_sha256')),
               original_inputs_unchanged=before['original_inputs'] == after['original_inputs'], locks_unchanged=before['locks'] == after['locks'])
for name in ('stdout.log', 'checkpoints.jsonl', 'function-totals.json', 'process-samples.jsonl', 'native_profile_plugin.py', 'run_profile.py'):
    path = OUT / name
    if path.exists():
        receipt.setdefault('artifacts', {})[name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
(OUT / 'receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
print(json.dumps({key: receipt[key] for key in ('exit_code', 'timed_out', 'duration_seconds', 'child_resource_usage', 'source_unchanged', 'git_unchanged', 'original_inputs_unchanged')}, indent=2), flush=True)
