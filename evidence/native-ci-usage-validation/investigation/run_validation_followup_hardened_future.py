"""Bound actual validation-only commands; preserve the accepted app separately."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

if sys.flags.optimize:
    raise RuntimeError('Validation-only procedural guards require unoptimized Python; no calls or writes performed')

ROOT = Path('/workspace/solana-wallet-scanner')
sys.path.insert(0, str(ROOT))
from tools.validate import execute_command, source_manifest, lock_hashes

mode, expected_commit = sys.argv[1:]
assert mode in ('fixture', 'backend')
out = ROOT / 'evidence/native-ci-usage-validation' / mode
out.mkdir(parents=True, exist_ok=False)
before = source_manifest(ROOT)
assert before['sha256'] == '0fad6d9bd6647b2663724d4bae2e280a02ed499f03f730eeff58f057ac98d365'
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == expected_commit
assert not subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT)
locks = lock_hashes(ROOT)
def runtime():
    return {'python':subprocess.check_output([str(ROOT / '.venv/bin/python'), '-c', 'import platform; print(platform.python_version())'], text=True).strip(),
            'platform':sys.platform, 'node':subprocess.check_output(['node', '--version'], text=True).strip().removeprefix('v')}
current_runtime = runtime()
command = [str(ROOT / '.venv/bin/python'), '-m', 'pytest']
command += ['-v', '--durations=10', 'tests/test_indexed_report_integration.py'] if mode == 'fixture' else ['-q']
timeout = 600 if mode == 'fixture' else 1800
log = out / 'RAW.log'
receipt = {'kind': 'actual-validation-only-command', 'state': 'RUNNING',
           'started_at_utc': datetime.now(timezone.utc).isoformat(),
           'command': command, 'cwd': str(ROOT), 'validation_commit': expected_commit,
           'current_source_sha256': before['sha256'], 'source_file_count': len(before['files']),
           'tested_application_commit': '8aee62e50297d6773f347b77cecc3e8794f233cf',
           'tested_application_source_sha256': '05143c96aea6afd96ede6006fb27b99bf26e648611cf161fe620306154284e96',
           'new_application_acceptance': False, 'locks': locks, 'runtime': current_runtime,
           'timeout_seconds': timeout,
           'zero_live_calls_scope': 'retained indexed fixture assertions, offline input sources; mocked provider tests are not live calls',
           'PRODUCT_READY': False}
path = out / 'COMMAND.json'
path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
start = time.monotonic()
failure = None
code = None
env = {key: value for key, value in os.environ.items() if key != 'HELIUS_API_KEY'}
env['PYTHONDONTWRITEBYTECODE'] = '1'
env['PYTHONUNBUFFERED'] = '1'
try:
    with log.open('w') as stream:
        result = execute_command(command, cwd=ROOT, env=env, stdout=stream, timeout=timeout)
        code = result.returncode
except (OSError, subprocess.TimeoutExpired) as exc:
    failure = type(exc).__name__ + ': ' + str(exc)
raw = log.read_bytes()
after = source_manifest(ROOT)
same_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == expected_commit
runtime_stable = current_runtime == runtime()
stable = before == after and same_commit and locks == lock_hashes(ROOT) and runtime_stable
text = raw.decode('utf-8', errors='replace')
summaries = re.findall(r'(\d+) passed\b([^\n]*)\bin [0-9.]+s', text)
passed = int(summaries[-1][0]) if summaries else None
subtest_match = re.search(r'(\d+) subtests passed', summaries[-1][1]) if summaries else None
subtests = int(subtest_match[1]) if subtest_match else 0 if summaries else None
expected_nodes = 15 if mode == 'fixture' else 3167
terminal = passed == expected_nodes and subtests == (0 if mode == 'fixture' else 440)
receipt.update(exit_code=code, timed_out=isinstance(failure, str) and failure.startswith('TimeoutExpired:'),
               seconds=round(time.monotonic() - start, 3), source_unchanged=stable, runtime_unchanged=runtime_stable,
               actual_terminal_summary_matches=terminal, unique_nodes=passed, separately_reported_subtests=subtests,
               raw_log={'path':str(log.relative_to(ROOT)), 'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()},
               state='PASS' if code == 0 and stable and terminal else 'NONPASSING')
if failure:
    receipt['reason'] = failure
if mode == 'fixture' and receipt['state'] == 'PASS':
    receipt.update(provider_requests=0, credential_lookups=0, external_transport_calls=0,
                   guard_assertions='all fifteen retained guarded fixture finalizers completed')
path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
print(json.dumps({key: receipt[key] for key in ('state', 'exit_code', 'seconds', 'source_unchanged', 'unique_nodes', 'separately_reported_subtests')}, indent=2), flush=True)
raise SystemExit(0 if receipt['state'] == 'PASS' else 2)
