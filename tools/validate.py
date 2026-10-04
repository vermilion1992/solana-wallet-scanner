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
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
LOCKS = ('requirements.txt', 'requirements-build.in', 'pyproject.toml', 'frontend/package-lock.json')
FOCUSED = ['tests/review_v039', 'tests/review_v0310', 'tests/test_token_instruction_schema.py',
           'tests/test_instruction_contract_matrix.py', 'tests/test_source_role_matrix.py', 'tests/test_validation_gates.py',
           'tests/test_archive_input.py', 'tests/test_archive_fee_window.py', 'tests/test_report_rebuild.py',
           'tests/test_wallet_evidence.py', 'tests/test_metric_evidence.py', 'tests/test_real_evidence_adapter.py',
           'tests/test_compiled_instructions.py', 'tests/test_compiled_getter.py', 'tests/test_compiled_report_integration.py',
           'tests/test_indexed_input.py', 'tests/test_indexed_chronology.py',
           'tests/test_indexed_source_dependencies.py', 'tests/test_indexed_report_integration.py', 'tests/test_report_view.py',
           'tests/test_real_coverage.py', 'tests/test_generic_administration.py', 'tests/test_retained_protocol_funding.py', 'tests/test_discovery_audit_plan.py', 'tests/test_discovery_plan_views.py', 'tests/test_discovery_native_identity.py',
           'tests/test_bounded_collection.py', 'tests/test_genuine_collection_workflow.py']


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('focused', 'candidate'), default='focused')
    parser.add_argument('--python', default=str(ROOT / '.venv/bin/python') if (ROOT / '.venv/bin/python').exists() else sys.executable)
    parser.add_argument('--browser-python', default=shutil.which('python3'))
    parser.add_argument('--chromium', default='/usr/bin/chromium')
    parser.add_argument('--install-record', type=Path, default=ROOT / 'evidence/CLEAN_INSTALL.json')
    parser.add_argument('--review-record', type=Path, default=ROOT / 'evidence/REVIEW.json')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
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
    report = {'profile': args.profile, 'source': before, 'locks': lock_hashes(),
              'interpreter': args.python, 'gates': [], 'gate_B': {'state': 'OPEN', 'reason': 'Source, implementation and independent real-wallet acceptance remain separate.'}}
    try:
        report['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    except subprocess.CalledProcessError:
        report['commit'] = None
    def save():
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    save()
    def run(name, command, cwd=ROOT):
        start = time.monotonic(); log = output / (name + '.log')
        print(f'{name}: running', flush=True)
        try:
            with log.open('w') as stream:
                proc = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
            gate = {'name': name, 'command': command, 'cwd': str(cwd), 'exit_code': proc.returncode,
                    'state': 'PASS' if proc.returncode == 0 else 'FAILED', 'log': str(log)}
        except (OSError, subprocess.TimeoutExpired) as exc:
            gate = {'name': name, 'command': command, 'state': 'BLOCKED', 'reason': str(exc), 'log': str(log)}
        gate['seconds'] = round(time.monotonic() - start, 2)
        report['gates'].append(gate); save(); print(f'{name}: {gate["state"]}', flush=True)
        return gate
    runtime = run('runtime', [args.python, '-c', 'import sys, pathlib, scanner; assert sys.version_info >= (3,11); assert pathlib.Path(scanner.__file__).resolve().parent == pathlib.Path.cwd()/"scanner"; print(sys.version)'])
    if runtime['state'] != 'PASS':
        report['state'] = 'INCOMPLETE'; save(); return 2
    report['runtime'] = {'python':subprocess.check_output([args.python,'-c','import platform;print(platform.python_version())'],text=True).strip(),'platform':sys.platform}
    if args.profile == 'candidate':
        node_gate=run('node-runtime',['node','--version'])
        report['runtime']['node']=Path(node_gate['log']).read_text().strip().removeprefix('v') if node_gate['state']=='PASS' else 'unavailable'
    run('backend', [args.python, '-m', 'pytest', '-q', *FOCUSED] if args.profile == 'focused' else [args.python, '-m', 'pytest', '-q'])
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
    if args.profile == 'focused' and code == 0:
        report['state'] = 'FOCUSED_PASS'
    save()
    print(f'{report["state"]}; Gate B remains OPEN. Evidence: {output}', flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
