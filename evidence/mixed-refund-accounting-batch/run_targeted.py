from pathlib import Path
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time

ROOT = Path('/workspace/solana-wallet-scanner')
OUT = ROOT / 'evidence/mixed-refund-accounting-batch'
sys.path.insert(0, str(ROOT))
from tools.validate import source_manifest, LOCKS

def artifact(path):
    raw = path.read_bytes()
    return {'path': str(path.relative_to(ROOT)), 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}

before = source_manifest(ROOT)
assert before == json.loads((OUT / 'SOURCE_MANIFEST.json').read_text())
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
selectors = ['tests/test_cost_flow_evidence.py', 'tests/test_historical_reserve_marks.py', 'tests/test_economic_evidence.py', 'tests/test_wallet_evidence.py::test_missing_fee_isolated_from_raw_physical_quantities_and_ownership', 'tests/test_wallet_evidence.py::test_internal_transfer_preserves_mint_aggregate_and_does_not_create_a_purchase', 'tests/test_wallet_evidence.py::test_unexplained_native_flow_revokes_economic_role_but_preserves_actual_fee', 'tests/test_wallet_evidence.py::test_existing_fifo_retains_losing_and_breakeven_episodes_with_unresolved_real_population', 'tests/test_archive_input.py::test_raw_inputs_reach_fifo_with_partial_sales_loss_breakeven_reentry_and_failed_fee', 'tests/test_archive_input.py::test_claimed_real_world_or_completion_boolean_cannot_certify_a_wallet', 'tests/test_selected_cohort_observations.py::test_missing_exit_fee_retains_quantity_timing_and_independent_remaining_basis', 'tests/test_validation_gates.py::test_focused_batches_preserve_the_exact_existing_union']
commands = [('backend-targeted', [str(ROOT / '.venv/bin/python'), '-m', 'pytest', '-v'] + selectors, ROOT)]
record = {'kind': 'actual-focused-wallet-report-checks', 'state': 'RUNNING',
    'scope': 'focused-checks-only', 'application_commit': head,
    'baseline_head': 'bad28e11d7a281aa201eb08761e2a17161a9180a',
    'source_before': before, 'source_unchanged': False, 'commands': [],
    'locks': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in LOCKS},
    'runtime': {'python': sys.version, 'platform': platform.platform(),
                'node': subprocess.check_output(['node', '--version'], text=True).strip()},
    'new_full_application_acceptance': False, 'PRODUCT_READY': False,
    'full_Gate_A': 'HISTORICAL_BASELINE_ONLY',
    'live_provider_requests': 0, 'live_provider_probe_executed': False,
    'credential_access': 'No runtime credential lookup; gateway tests use explicit synthetic keys and MockTransport',
    'omitted_checks': ['full backend suite', 'fresh dependency install', 'full browser matrix', 'live source collection', 'frontend rebuild'],
    'omission_reason': 'User requested small necessary checks; focused shared source families and normal offline saved-report workflow cover this backend-only iteration. Frontend source, built assets and locks are unchanged from the preceding bound checks.',
}
receipt = OUT / 'TARGETED_CHECKS.json'
def save():
    receipt.write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
save()
env = {name: value for name, value in os.environ.items()
       if name not in ('HELIUS_API_KEY', 'GH_DEBUG', 'GIT_TRACE', 'GIT_TRACE_CURL', 'GIT_CURL_VERBOSE')}
for name, argv, cwd in commands:
    assert source_manifest(ROOT) == before
    log = OUT / (name + '.log')
    started = time.monotonic()
    timed_out = False
    with log.open('wb') as stream:
        try:
            code = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=stream, stderr=subprocess.STDOUT, timeout=120).returncode
        except subprocess.TimeoutExpired:
            code, timed_out = 124, True
    stable = source_manifest(ROOT) == before
    passed = code == 0 and not timed_out and stable
    row = {'name': name, 'argv': argv, 'cwd': str(cwd), 'exit_code': code,
        'timed_out': timed_out, 'timeout_seconds': 120, 'seconds': round(time.monotonic() - started, 3),
        'state': 'PASS' if passed else 'FAILED', 'source_unchanged': stable, 'raw_log': artifact(log)}
    if name == 'backend-targeted':
        text = log.read_text()
        nodes = re.findall(r'^(tests/\S+) PASSED', text, re.MULTILINE)
        counts = re.findall(r'(\d+) passed', text)
        assert counts and len(nodes) == len(set(nodes)) == int(counts[-1])
        row['unique_backend_nodes'] = nodes
        row['unique_backend_node_count'] = len(nodes)
    record['commands'].append(row)
    save()
    print(json.dumps({'name': name, 'state': row['state'], 'seconds': row['seconds'],
        'unique_backend_nodes': row.get('unique_backend_node_count')}), flush=True)
    if not passed:
        record['state'] = 'FAILED'
        record['source_after'] = source_manifest(ROOT)
        save()
        raise SystemExit(1)
check = subprocess.run(['git', 'diff', '--check', head], cwd=ROOT, capture_output=True, text=True)
assert check.returncode == 0
record['diff_check'] = {'argv': ['git', 'diff', '--check', head], 'exit_code': check.returncode}
record['source_after'] = source_manifest(ROOT)
record['source_unchanged'] = record['source_after'] == before
assert record['source_unchanged']
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == head
record['state'] = 'PASS'
save()
print(json.dumps({'state': 'PASS', 'source_sha256': before['sha256'], 'application_commit': head}), flush=True)
