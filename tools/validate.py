#!/usr/bin/env python3
"""Repeatable local Gate A checks; full wallet capability is a separate gate."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
LOCKS = ('requirements.txt', 'requirements-build.in', 'pyproject.toml', 'frontend/package-lock.json')
SCREENING_FORWARD = [
    'tests/test_screening.py', 'tests/test_screening_routes.py', 'tests/test_public_sample_budget.py',
    'tests/test_paper.py', 'tests/test_observer.py', 'tests/test_discovery_audit_plan.py',
    'tests/test_discovery_plan_views.py', 'tests/test_discovery_native_identity.py',
    'tests/test_candidate_import.py', 'tests/test_copy_review.py', 'tests/test_app.py',
    'tests/test_storage.py', 'tests/test_launcher.py', 'tests/test_validation_gates.py',
    'tests/test_cost_flow_evidence.py', 'tests/test_historical_reserve_marks.py',
    'tests/test_asset_classification.py', 'tests/test_wallet_evidence.py',
    'tests/test_real_evidence_adapter.py',
    'tests/test_inventory_evidence.py',
]
FOCUSED = ['tests/review_v039', 'tests/review_v0310', 'tests/test_token_instruction_schema.py',
           'tests/test_instruction_contract_matrix.py', 'tests/test_source_role_matrix.py', 'tests/test_validation_gates.py',
           'tests/test_archive_input.py', 'tests/test_archive_fee_window.py', 'tests/test_report_rebuild.py',
           'tests/test_wallet_evidence.py', 'tests/test_metric_evidence.py', 'tests/test_real_evidence_adapter.py',
           'tests/test_compiled_instructions.py', 'tests/test_compiled_getter.py', 'tests/test_compiled_report_integration.py',
           'tests/test_indexed_input.py', 'tests/test_indexed_chronology.py',
           'tests/test_indexed_source_dependencies.py', 'tests/test_indexed_report_integration.py', 'tests/test_report_view.py',
           'tests/test_real_coverage.py', 'tests/test_research.py', 'tests/test_research_source_roles.py', 'tests/test_generic_administration.py', 'tests/test_retained_protocol_funding.py', 'tests/test_discovery_audit_plan.py', 'tests/test_discovery_plan_views.py', 'tests/test_discovery_native_identity.py',
           'tests/test_bounded_collection.py', 'tests/test_genuine_collection_workflow.py',
           'tests/test_accounting_metric_isolation.py', 'tests/test_selected_cohort_observations.py',
           'tests/test_production_evidence_composition.py', 'tests/test_wallet_identity.py',
           'tests/test_research_disposal_scopes.py',
           'tests/test_historical_membership.py', 'tests/test_wallet_position_population.py',
           'tests/test_source_fact_reuse.py', 'tests/test_disposed_origin_scopes.py',
           'tests/test_inventory_evidence.py', 'tests/test_report_benchmark.py',
           'tests/test_native_inventory_capture.py', 'tests/test_asset_classification.py',
           'tests/test_native_cash_observations.py', 'tests/test_economic_evidence.py',
           'tests/test_cost_flow_evidence.py', 'tests/test_historical_reserve_marks.py',
           'tests/test_screening.py', 'tests/test_screening_routes.py',
           'tests/test_public_sample_budget.py', 'tests/test_paper.py',
           'tests/test_observer.py', 'tests/test_candidate_import.py']

# Retain all 35 baseline selectors (original 30 plus five metric regressions) and
# include the retained development-contract/performance modules, inventory admission
# and offline benchmark controls.
# Every selector appears exactly once. These are execution batches of one
# focused suite, not additional suites or additional acceptance counts.
FOCUSED_GROUPS = {
    'historical': ['tests/review_v039', 'tests/review_v0310'],
    'schemas': ['tests/test_token_instruction_schema.py', 'tests/test_instruction_contract_matrix.py',
                'tests/test_source_role_matrix.py', 'tests/test_validation_gates.py',
                'tests/test_compiled_instructions.py', 'tests/test_compiled_getter.py',
                'tests/test_compiled_report_integration.py', 'tests/test_generic_administration.py',
                'tests/test_retained_protocol_funding.py'],
    'archives': ['tests/test_archive_input.py', 'tests/test_archive_fee_window.py',
                 'tests/test_report_rebuild.py', 'tests/test_wallet_evidence.py',
                 'tests/test_metric_evidence.py', 'tests/test_real_evidence_adapter.py',
                 'tests/test_selected_cohort_observations.py',
                 'tests/test_production_evidence_composition.py', 'tests/test_wallet_identity.py',
                 'tests/test_wallet_position_population.py', 'tests/test_asset_classification.py',
                 'tests/test_native_cash_observations.py', 'tests/test_economic_evidence.py',
                 'tests/test_cost_flow_evidence.py', 'tests/test_historical_reserve_marks.py'],
    'indexed-input': ['tests/test_indexed_input.py'],
    'indexed-chronology': ['tests/test_indexed_chronology.py'],
    'indexed-dependencies': ['tests/test_indexed_source_dependencies.py', 'tests/test_source_fact_reuse.py'],
    'indexed-integration': ['tests/test_indexed_report_integration.py'],
    'indexed-coverage': ['tests/test_real_coverage.py', 'tests/test_historical_membership.py',
                         'tests/test_inventory_evidence.py', 'tests/test_native_inventory_capture.py'],
    'research': ['tests/test_report_view.py', 'tests/test_research.py', 'tests/test_research_source_roles.py',
                 'tests/test_accounting_metric_isolation.py', 'tests/test_research_disposal_scopes.py',
                 'tests/test_disposed_origin_scopes.py', 'tests/test_report_benchmark.py'],
    'discovery': ['tests/test_discovery_audit_plan.py', 'tests/test_discovery_plan_views.py',
                  'tests/test_discovery_native_identity.py', 'tests/test_bounded_collection.py',
                  'tests/test_genuine_collection_workflow.py'],
    'screening': ['tests/test_screening.py', 'tests/test_screening_routes.py',
                  'tests/test_public_sample_budget.py', 'tests/test_paper.py',
                  'tests/test_observer.py', 'tests/test_candidate_import.py'],
}


def focused_groups():
    selectors = [path for group in FOCUSED_GROUPS.values() for path in group]
    if len(selectors) != len(set(selectors)) or set(selectors) != set(FOCUSED):
        raise ValueError('Focused groups must be an exact nonoverlapping partition of FOCUSED.')
    if any(a != b and b.startswith(a.rstrip('/') + '/') for a in selectors for b in selectors):
        raise ValueError('Focused selectors cannot overlap through a parent directory.')
    return {name: list(paths) for name, paths in FOCUSED_GROUPS.items()}


def focused_group_records(paths, *, source, locks, runtime, commit):
    """Verify the complete focused union without trusting a green job alone."""
    expected = focused_groups()
    result = {'name': 'focused-group-receipts', 'state': 'INCOMPLETE', 'receipts': []}
    seen = set()
    if not isinstance(commit, str) or not commit:
        result['reason'] = 'Current Git identity is unavailable.'
        return result
    for path in paths:
        receipt = read_receipt(path)
        result['receipts'].append(receipt)
        record = receipt.get('record', {})
        name = record.get('focused_group')
        if not isinstance(name, str) or name not in expected or name in seen:
            result['reason'] = 'Missing, unsupported or repeated focused group identity.'
            return result
        seen.add(name)
        if (record.get('profile') != 'focused' or record.get('state') != 'FOCUSED_GROUP_PASS'
            or record.get('source_unchanged') is not True or 'running_gate' in record or 'timeout_abort' in record or record.get('selection') != expected[name]
            or record.get('source') != source or record.get('locks') != locks
            or record.get('runtime') != runtime or record.get('commit') != commit):
            result['reason'] = 'Focused receipt is nonpassing or does not bind the exact selection, source, locks and runtime.'
            return result
        gates = record.get('gates')
        if (not isinstance(gates, list) or len(gates) != 3
            or not all(isinstance(gate, dict) and isinstance(gate.get('name'), str) for gate in gates)
            or {gate.get('name') for gate in gates} != {'runtime', 'node-runtime', 'backend'}
            or any(gate.get('state') != 'PASS' or type(gate.get('exit_code')) is not int
                   or gate['exit_code'] != 0 or gate.get('timed_out') is not False
                   or type(gate.get('timeout_seconds')) is not int or gate['timeout_seconds'] != 600 for gate in gates)):
            result['reason'] = 'Focused receipt lacks explicitly passing command gates.'
            return result
        backend = next(gate for gate in gates if gate['name'] == 'backend')
        interpreter, source_root = record.get('interpreter'), record.get('source_root')
        if not all(isinstance(value, str) and value and '\x00' not in value and Path(value).is_absolute()
                   for value in (interpreter, source_root)):
            result['reason'] = 'Focused command paths are missing or malformed.'
            return result
        if (not isinstance(interpreter, str) or not interpreter
            or backend.get('command') != [interpreter, '-m', 'pytest', '-v', '--durations=10', *expected[name]]
            or type(backend.get('timeout_seconds')) is not int or backend['timeout_seconds'] != 600
            or backend.get('timed_out') is not False):
            result['reason'] = 'Backend command does not execute the declared exact group.'
            return result
        expected_commands = {
            'runtime': [interpreter, '-c', 'import sys, pathlib, scanner; assert sys.version_info >= (3,11); assert pathlib.Path(scanner.__file__).resolve().parent == pathlib.Path.cwd()/"scanner"; print(sys.version)'],
            'node-runtime': ['node', '--version'],
            'backend': [interpreter, '-m', 'pytest', '-v', '--durations=10', *expected[name]],
        }
        for gate in gates:
            if gate.get('command') != expected_commands[gate['name']] or gate.get('cwd') != source_root:
                result['reason'] = 'Focused command or working directory does not execute the declared checkout.'
                return result
            # Original absolute runner paths are informational. Read only the
            # allowlisted sibling logs that were transferred with this receipt.
            try:
                raw = (path.parent / (gate['name'] + '.log')).read_bytes()
            except OSError:
                result['reason'] = 'A required focused command log is missing.'
                return result
            if (type(gate.get('log_bytes')) is not int or gate['log_bytes'] != len(raw)
                or gate.get('log_sha256') != hashlib.sha256(raw).hexdigest()):
                result['reason'] = 'A required focused command log is unbound or changed.'
                return result
        receipt['state'] = 'PASS'
    if seen != set(expected):
        result['reason'] = 'The focused union is incomplete.'
        return result
    return {**result, 'state': 'PASS', 'groups': list(expected),
            'selectors': FOCUSED, 'count_policy': 'One partition of the existing focused suite; no additional test counts.'}


def offline_development_record(path, *, source, locks, runtime, commit):
    receipt = read_receipt(path) if path else {'state': 'INCOMPLETE'}
    record = receipt.get('record', {})
    receipt.update(name='offline-development-receipt', state='INCOMPLETE')
    names = {'runtime', 'node-runtime', 'pip-check', 'shell-syntax', 'product',
             'frontend-check-format', 'frontend-check-discovery', 'frontend-build'}
    if (record.get('profile') != 'offline-development' or record.get('state') != 'DEVELOPMENT_CHECK_PASS'
        or record.get('source_unchanged') is not True or 'running_gate' in record or 'timeout_abort' in record or record.get('source') != source
        or record.get('locks') != locks or record.get('runtime') != runtime or record.get('commit') != commit):
        receipt['reason'] = 'Missing or nonpassing offline development receipt, or stale source/locks/runtime/Git identity.'
        return receipt
    gates = record.get('gates')
    if (not isinstance(gates, list) or len(gates) != len(names)
        or not all(isinstance(g, dict) and isinstance(g.get('name'), str) for g in gates)
        or {g['name'] for g in gates} != names
        or any(g.get('state') != 'PASS' or type(g.get('exit_code')) is not int or g['exit_code'] != 0
               or g.get('timed_out') is not False or type(g.get('timeout_seconds')) is not int
               or g['timeout_seconds'] != 600 for g in gates)):
        receipt['reason'] = 'Development receipt lacks explicitly passing command gates.'
        return receipt
    interpreter, source_root, output = (record.get(key) for key in ('interpreter', 'source_root', 'output'))
    if not all(isinstance(value, str) and value and '\x00' not in value and Path(value).is_absolute()
               for value in (interpreter, source_root, output)):
        receipt['reason'] = 'Development command paths are missing or malformed.'
        return receipt
    # Absolute producer paths are preserved for command/cwd binding. The logs
    # are still read only from the transferred fixed-name siblings, never from
    # these paths or the private product directory.
    expected_commands = {
        'runtime': [interpreter, '-c', 'import sys, pathlib, scanner; assert sys.version_info >= (3,11); assert pathlib.Path(scanner.__file__).resolve().parent == pathlib.Path.cwd()/"scanner"; print(sys.version)'],
        'node-runtime': ['node', '--version'],
        'pip-check': [interpreter, '-m', 'pip', 'check'],
        'shell-syntax': ['bash', '-n', 'run.sh', 'setup.sh'],
        'product': [interpreter, str(Path(source_root) / 'tools/check_product.py'), '--output', str(Path(output) / 'private-product')],
        'frontend-check-format': ['npm', 'run', 'check:format'],
        'frontend-check-discovery': ['npm', 'run', 'check:discovery'],
        'frontend-build': ['npm', 'run', 'build'],
    }
    for gate in gates:
        expected_cwd = str(Path(source_root) / 'frontend') if gate['name'].startswith('frontend-') else source_root
        if gate.get('command') != expected_commands[gate['name']] or gate.get('cwd') != expected_cwd:
            receipt['reason'] = 'Development command or working directory does not execute the declared checkout workflow.'
            return receipt
    product = next(g for g in gates if g['name'] == 'product')
    assertions = product.get('product_assertions')
    expected_assertions = {'development_pass': True, 'real_acceptance_blocked': True,
        'zero_provider_requests': True, 'zero_credential_lookups': True,
        'parent_unchanged': True, 'usage_unchanged': True, 'no_collector_ancestry': True}
    if (not isinstance(assertions, dict) or assertions != expected_assertions
        or not all(value is True for value in assertions.values())):
        receipt['reason'] = 'Development receipt lacks explicitly passing offline product assertions.'
        return receipt
    for gate in gates:
        try:
            raw = (path.parent / (gate['name'] + '.log')).read_bytes()
        except OSError:
            receipt['reason'] = 'A required development command log is missing.'
            return receipt
        if (type(gate.get('log_bytes')) is not int or gate['log_bytes'] != len(raw)
            or gate.get('log_sha256') != hashlib.sha256(raw).hexdigest()):
            receipt['reason'] = 'A required development command log is unbound or changed.'
            return receipt
    receipt['state'] = 'PASS'
    return receipt


def offline_product_gate(command_gate, path):
    """Consume the real producer receipt, retaining only safe assertions in CI."""
    receipt = read_receipt(path)
    record = receipt.get('record', {})
    cases = record.get('cases')
    required_cases = {'synthetic-positive-normal-report', 'valuation_hash-loss-and-exact-restoration',
                      'world_hash-loss-and-exact-restoration'}
    valid_cases = (isinstance(cases, list) and all(isinstance(c, dict) and isinstance(c.get('case'), str) for c in cases)
                   and len({c['case'] for c in cases}) == len(cases)
                   and required_cases <= {c['case'] for c in cases if c.get('state') == 'PASS'})
    checks = {'development_pass': record.get('kind') == 'offline-product-check'
              and record.get('real_acceptance_required') is False and valid_cases and record.get('state') == 'DEVELOPMENT_PASS'
              and isinstance(record.get('development'), dict) and record['development'].get('state') == 'PASS',
              'real_acceptance_blocked': isinstance(record.get('real_acceptance'), dict)
              and record['real_acceptance'].get('state') == 'BLOCKED',
              'zero_provider_requests': type(record.get('provider_requests')) is int and record['provider_requests'] == 0,
              'zero_credential_lookups': type(record.get('credential_lookups')) is int and record['credential_lookups'] == 0,
              'parent_unchanged': record.get('parent_unchanged') is True,
              'usage_unchanged': isinstance(record.get('usage_before'), dict) and record.get('usage_after') == record['usage_before'],
              'no_collector_ancestry': record.get('collector_ancestry_created') is False}
    passing = all(checks.values())
    # Never copy the producer's report identifiers, cases, archive paths or
    # application state into the transferable validation receipt.
    command_gate.update(product_assertions=checks, product_receipt_sha256=receipt.get('sha256'))
    if command_gate['state'] == 'PASS' and not passing:
        command_gate.update(state='FAILED' if record.get('state') == 'FAILED' else 'BLOCKED' if record.get('state') == 'BLOCKED' else 'INCOMPLETE',
                            reason='Product command lacks a usable explicitly passing offline receipt.')
    return command_gate


def lock_hashes(root=ROOT):
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in LOCKS}


def source_manifest(root=ROOT):
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, check=True)
    names = [n for n in result.stdout.decode().split('\0') if n and not n.startswith('evidence/')]
    # Include untracked implementation files so an unstaged addition cannot disappear.
    extra = subprocess.run(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=root, capture_output=True, check=True)
    names += [n for n in extra.stdout.decode().split('\0') if n and not n.startswith('evidence/')]
    hashes = {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in sorted(set(names)) if (root / n).is_file()}
    modes = {n: (root / n).stat().st_mode & 0o777 for n in hashes}
    digest = hashlib.sha256(json.dumps({'files':hashes,'modes':modes}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'sha256': digest, 'files': hashes, 'modes': modes}


def read_receipt(path):
    result = {'path': str(path), 'state': 'INCOMPLETE'}
    try:
        raw = path.read_bytes()
        result['sha256'] = hashlib.sha256(raw).hexdigest()
        record = json.loads(raw)
        if not isinstance(record, dict):
            raise ValueError('Receipt must be a JSON object')
        result['record'] = record
    except (ValueError, OSError, TypeError) as exc:
        result['reason'] = f'Unusable evidence receipt: {exc}'
    return result


def required_record(path, *, kind, locks, source_hash=None, runtime=None):
    if path is None:
        return {'state': 'INCOMPLETE', 'reason': f'Missing {kind} evidence record.'}
    result = read_receipt(path)
    record = result.get('record')
    if record is None:
        return result
    def reject(reason, state='INCOMPLETE'):
        return {**result, 'state': state, 'reason': reason}
    if record.get('kind') != kind or record.get('state') != 'PASS':
        return reject(f'{kind} record does not declare completed passing checks.')
    if kind == 'clean-locked-install':
        commands = record.get('commands')
        if (record.get('locks') != locks or record.get('disposable_install') is not True
            or not isinstance(commands, list) or not commands or not all(isinstance(c, dict) for c in commands)):
            return reject('Install record does not bind the current locks and disposable setup.')
        if runtime is not None and record.get('runtime') != runtime:
            return reject('Install record belongs to a different interpreter/Node/platform environment.')
        if any(type(c.get('exit_code')) is not int for c in commands):
            return reject('Install command exit codes must be explicit integers.')
        if any(c['exit_code'] != 0 for c in commands):
            return reject('An install command failed.', 'FAILED')
    elif kind == 'consolidated-review':
        findings = record.get('findings')
        if (record.get('source_sha256') != source_hash or record.get('matrix_review_complete') is not True
            or not isinstance(findings, list) or not all(isinstance(f, dict) for f in findings)):
            return reject('Review does not bind the exact candidate and complete matrix/findings.')
        if any(f.get('blocking') and f.get('status') != 'VERIFIED_IN_SCOPE' for f in findings):
            return reject('Review retains an unresolved in-scope blocker.', 'FAILED')
    else:
        return reject('Unsupported evidence record kind.')
    return {**result, 'state': 'PASS'}


def structured_evidence_gate(command_gate, path, *, kind):
    """A successful process and a usable passing producer receipt are both required."""
    receipt = read_receipt(path)
    record = receipt.get('record')
    state = record.get('state') if record else None
    receipt['state'] = state if state in ('PASS', 'FAILED', 'BLOCKED', 'INCOMPLETE') else 'INCOMPLETE'
    if state == 'PASS':
        if kind == 'browser':
            flags = ('no_overflow', 'settings_saved_without_threshold_change', 'offline_candidate_import',
                     'source_loss_and_exact_restoration', 'actual_UI_json_exports', 'evidence_inspection',
                     'server_stopped', 'parents_unchanged')
            ints = ('offline_children', 'captures', 'desktop_width', 'mobile_width')
            guards = record.get('offline_guards')
            cases = record.get('cases')
            usable = (all(type(record.get(k)) is bool for k in flags)
                and all(type(record.get(k)) is int and record[k] > 0 for k in ints)
                and isinstance(cases, list) and bool(cases) and all(isinstance(c, dict) for c in cases)
                and type(record.get('anonymous_state')) is int
                and isinstance(record.get('usage_before'), dict) and isinstance(record.get('usage_after'), dict)
                and isinstance(record.get('javascript_errors'), list) and isinstance(record.get('external_browser_requests'), list)
                and isinstance(guards, dict) and all(type(guards.get(k)) is int for k in ('provider_requests', 'credential_lookups')))
            passing = usable and (all(record[k] for k in flags) and record['anonymous_state'] == 401
                and not record['javascript_errors'] and not record['external_browser_requests']
                and record['usage_before'] == record['usage_after']
                and all(guards[k] == 0 for k in ('provider_requests', 'credential_lookups'))
                and len(cases) == record['offline_children']
                and all(c.get('frozen_references_preserved') is True and c.get('parent_export_unchanged') is True for c in cases))
        elif kind == 'matrix':
            rows = record.get('requirements')
            usable = (type(record.get('collected_unique_nodes')) is int and record['collected_unique_nodes'] > 0
                and type(record.get('required_items')) is int and record['required_items'] > 0
                and isinstance(rows, list) and len(rows) == record['required_items']
                and all(isinstance(r, dict) and isinstance(r.get('nodes'), (dict, list)) for r in rows))
            passing = usable and all(r.get('state') == 'PASS' and bool(r['nodes']) and
                (all(isinstance(v, list) and bool(v) and all(isinstance(n, str) and n for n in v) for v in r['nodes'].values())
                 if isinstance(r['nodes'], dict) else all(isinstance(n, str) and n for n in r['nodes'])) for r in rows)
        else:
            usable = passing = False
        receipt['state'] = 'PASS' if passing else 'FAILED' if usable else 'INCOMPLETE'
        if not passing:
            receipt['reason'] = f'{kind} PASS receipt lacks usable required producer assertions or contradicts them.'
    states = (command_gate['state'], receipt['state'])
    merged = 'FAILED' if 'FAILED' in states else 'BLOCKED' if 'BLOCKED' in states else 'PASS' if states == ('PASS', 'PASS') else 'INCOMPLETE'
    command_gate.update(state=merged, evidence_receipt=receipt)
    return command_gate


def gate_decision(gates, *, stable):
    if not stable:
        return 'INCOMPLETE', 2
    if any(g['state'] == 'FAILED' for g in gates):
        return 'FAILED', 1
    if any(g['state'] != 'PASS' for g in gates):
        return 'INCOMPLETE', 2
    return 'ACCEPTED_IN_SCOPE', 0


def execute_command(command, *, cwd, env, stdout, timeout):
    """Bound a command and its POSIX descendants, while exposing liveness.

    A focused command expires before the hosted step/job deadlines, giving the
    validator time to save a nonpassing receipt and upload its original log.
    The new session is private to this child; unrelated worker processes are
    never signalled. Candidate full-suite timeout remains separately configured.
    """
    start = time.monotonic()
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout,
                               stderr=subprocess.STDOUT, start_new_session=(os.name == 'posix'))
    try:
        while True:
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                return subprocess.CompletedProcess(command, process.wait(timeout=min(30, remaining)))
            except subprocess.TimeoutExpired:
                if time.monotonic() - start >= timeout:
                    raise subprocess.TimeoutExpired(command, timeout)
                print(f'command active: {round(time.monotonic() - start)}s / {timeout}s limit', flush=True)
    except subprocess.TimeoutExpired:
        # Stop descendants as well as pytest itself, retaining the partial raw
        # output. A timed-out child can never become PASS through its final code.
        if os.name == 'posix':
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == 'posix':
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                stdout.write('VALIDATION_CLEANUP_TIMEOUT: killed command was not reaped within5s\n')
        if os.name == 'posix':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        stdout.write(f'\nVALIDATION_COMMAND_TIMEOUT: limit={timeout}s; command and supported descendant scope stopped\n')
        stdout.flush()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('focused', 'focused-summary', 'offline-development', 'candidate', 'screening-forward'), default='focused')
    parser.add_argument('--focused-group', choices=tuple(FOCUSED_GROUPS))
    parser.add_argument('--group-record', type=Path, action='append', default=[])
    parser.add_argument('--development-record', type=Path)
    parser.add_argument('--python', default=str(ROOT / '.venv/bin/python') if (ROOT / '.venv/bin/python').exists() else sys.executable)
    parser.add_argument('--browser-python', default=shutil.which('python3'))
    parser.add_argument('--chromium', default='/usr/bin/chromium')
    parser.add_argument('--install-record', type=Path, default=ROOT / 'evidence/CLEAN_INSTALL.json')
    parser.add_argument('--review-record', type=Path, default=ROOT / 'evidence/REVIEW.json')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.focused_group and args.profile != 'focused':
        parser.error('--focused-group requires --profile focused')
    if args.group_record and args.profile != 'focused-summary':
        parser.error('--group-record requires --profile focused-summary')
    if args.development_record and args.profile != 'focused-summary':
        parser.error('--development-record requires --profile focused-summary')
    groups = focused_groups()
    # Keep virtualenv paths absolute without resolving their interpreter symlink.
    # Browser baseline derivation runs from a different working directory.
    args.python = os.path.abspath(shutil.which(args.python) or args.python)
    if args.browser_python:
        args.browser_python = os.path.abspath(shutil.which(args.browser_python) or args.browser_python)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    output = (args.output or ROOT / 'evidence/runs' / (args.profile + '-' + stamp)).absolute()
    output.mkdir(parents=True, exist_ok=False)
    before = source_manifest()
    env = {k: v for k, v in os.environ.items() if k != 'HELIUS_API_KEY'}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    report = {'profile': args.profile, 'source': before, 'locks': lock_hashes(),
              'interpreter': args.python, 'gates': [], 'gate_B': {'state': 'OPEN', 'reason': 'Source, implementation and independent real-wallet acceptance remain separate.'}}
    if args.profile == 'offline-development':
        report.update(source_root=str(ROOT), output=str(output))
    if args.focused_group:
        report.update(focused_group=args.focused_group, selection=groups[args.focused_group], source_root=str(ROOT))
    try:
        report['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    except subprocess.CalledProcessError:
        report['commit'] = None
    def save():
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    save()
    def run(name, command, cwd=ROOT):
        start = time.monotonic(); log = output / (name + '.log')
        timeout = 60 if args.profile == 'focused-summary' else 600 if args.focused_group or args.profile == 'offline-development' else 1800
        if args.profile != 'candidate':
            # Keep an interruption diagnosable even when a runner disappears
            # before the command returns. RUNNING is never passing evidence.
            report['running_gate'] = {'name': name, 'command': command, 'log': str(log), 'timeout_seconds': timeout}
            save()
        print(f'{name}: running', flush=True)
        failure = None
        try:
            with log.open('w') as stream:
                if args.profile != 'candidate' and report.get('timeout_abort') is True:
                    stream.write('NOT_EXECUTED_AFTER_PRIOR_COMMAND_TIMEOUT: retained as a required nonpassing gate\n')
                    gate = {'name': name, 'command': command, 'cwd': str(cwd), 'state': 'BLOCKED',
                            'attempted': False, 'reason': 'Prior CI command timed out; this required command was not executed.', 'log': str(log)}
                else:
                    proc = execute_command(command, cwd=cwd, env=env, stdout=stream, timeout=timeout)
                    gate = {'name': name, 'command': command, 'cwd': str(cwd), 'exit_code': proc.returncode,
                            'state': 'PASS' if proc.returncode == 0 else 'FAILED', 'attempted': True, 'log': str(log)}
        except (OSError, subprocess.TimeoutExpired) as exc:
            failure = exc
            if args.profile != 'candidate' and isinstance(exc, subprocess.TimeoutExpired):
                report['timeout_abort'] = True
            gate = {'name': name, 'command': command, 'state': 'BLOCKED', 'reason': str(exc), 'log': str(log)}
        gate.update(timeout_seconds=timeout, timed_out=isinstance(failure, subprocess.TimeoutExpired))
        gate['seconds'] = round(time.monotonic() - start, 2)
        if (args.focused_group or args.profile == 'offline-development') and log.is_file():
            raw = log.read_bytes()
            gate.update(log_bytes=len(raw), log_sha256=hashlib.sha256(raw).hexdigest())
        report.pop('running_gate', None)
        report['gates'].append(gate); save(); print(f'{name}: {gate["state"]}', flush=True)
        return gate
    runtime = run('runtime', [args.python, '-c', 'import sys, pathlib, scanner; assert sys.version_info >= (3,11); assert pathlib.Path(scanner.__file__).resolve().parent == pathlib.Path.cwd()/"scanner"; print(sys.version)'])
    if runtime['state'] != 'PASS':
        report['state'] = 'INCOMPLETE'; save(); return 2
    report['runtime'] = {'python':subprocess.check_output([args.python,'-c','import platform;print(platform.python_version())'],text=True).strip(),'platform':sys.platform}
    if args.profile != 'focused' or args.focused_group:
        node_gate=run('node-runtime',['node','--version'])
        report['runtime']['node']=Path(node_gate['log']).read_text().strip().removeprefix('v') if node_gate['state']=='PASS' else 'unavailable'
    if args.profile == 'focused-summary':
        report['gates'].append(focused_group_records(args.group_record, source=before,
            locks=report['locks'], runtime=report['runtime'], commit=report['commit']))
        report['gates'].append(offline_development_record(args.development_record, source=before,
            locks=report['locks'], runtime=report['runtime'], commit=report['commit']))
        save()
    elif args.profile == 'screening-forward':
        report.update(scope='Sampled screening and quote-only forward research; historical full-wallet acceptance unchanged',
                      PRODUCT_READY=False, selection=SCREENING_FORWARD)
        run('backend-screening-forward', [args.python, '-m', 'pytest', '-q', *SCREENING_FORWARD])
        run('pip-check', [args.python, '-m', 'pip', 'check'])
        run('shell-syntax', ['bash', '-n', 'run.sh', 'setup.sh'])
        for name in ('check:format', 'check:discovery', 'build'):
            run('frontend-' + name.replace(':', '-'), ['npm', 'run', name], ROOT / 'frontend')
        browser = run('screening-launcher-browser', [args.browser_python or args.python, str(ROOT / 'tools/screening_browser.py'),
            '--chromium', args.chromium, '--output', str(output / 'browser')])
        receipt = read_receipt(output / 'browser/result.json')
        browser['receipt'] = receipt
        if browser['state'] != 'PASS' or receipt.get('record', {}).get('state') != 'PASS':
            browser.update(state='INCOMPLETE', reason='The actual launcher workflow did not produce a passing browser receipt.')
        save()
    elif args.profile == 'offline-development':
        run('pip-check', [args.python, '-m', 'pip', 'check'])
        run('shell-syntax', ['bash', '-n', 'run.sh', 'setup.sh'])
        product = run('product', [args.python, str(ROOT / 'tools/check_product.py'), '--output', str(output / 'private-product')])
        offline_product_gate(product, output / 'private-product/result.json'); save()
        for name in ('check:format', 'check:discovery', 'build'):
            run('frontend-' + name.replace(':', '-'), ['npm', 'run', name], ROOT / 'frontend')
    else:
        selected = groups[args.focused_group] if args.focused_group else FOCUSED
        run('backend', [args.python, '-m', 'pytest', '-v', '--durations=10', *selected] if args.focused_group else [args.python, '-m', 'pytest', '-q', *selected] if args.profile == 'focused' else [args.python, '-m', 'pytest', '-q'])
    if args.profile == 'candidate':
        run('pip-check', [args.python, '-m', 'pip', 'check'])
        run('shell-syntax', ['bash', '-n', 'run.sh', 'setup.sh'])
        matrix = run('matrix', [args.python, str(ROOT / 'tools/check_matrix.py'), '--output', str(output / 'matrix.json')])
        structured_evidence_gate(matrix, output / 'matrix.json', kind='matrix'); save()
        run('frontend-locked-install', ['npm', 'ci', '--prefer-offline', '--no-audit', '--no-fund'], ROOT / 'frontend')
        for name in ('check:format', 'check:discovery', 'build'):
            run('frontend-' + name.replace(':', '-'), ['npm', 'run', name], ROOT / 'frontend')
        install = required_record(args.install_record, kind='clean-locked-install', locks=report['locks'],runtime=report['runtime'])
        install['name'] = 'clean-locked-install'; report['gates'].append(install); save()
        browser = run('launcher-browser-rebuild', [args.browser_python or args.python, str(ROOT / 'tools/browser_acceptance.py'),
            '--python', args.python, '--chromium', args.chromium, '--output', str(output / 'browser')])
        browser_result = output / 'browser/result.json'
        structured_evidence_gate(browser, browser_result, kind='browser'); save()
        review = required_record(args.review_record, kind='consolidated-review', locks=report['locks'], source_hash=before['sha256'])
        review['name'] = 'consolidated-review'; report['gates'].append(review); save()
    stable = source_manifest()['sha256'] == before['sha256']
    report['source_unchanged'] = stable
    report['state'], code = gate_decision(report['gates'], stable=stable)
    if args.profile in ('focused', 'focused-summary') and code == 0:
        report['state'] = 'FOCUSED_GROUP_PASS' if args.focused_group else 'FOCUSED_PASS'
    elif args.profile == 'offline-development' and code == 0:
        report['state'] = 'DEVELOPMENT_CHECK_PASS'
    elif args.profile == 'screening-forward' and code == 0:
        report['state'] = 'SCREENING_FORWARD_SOFTWARE_PASS'
    save()
    print(f'{report["state"]}; Gate B remains OPEN. Evidence: {output}', flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
