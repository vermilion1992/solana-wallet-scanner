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
           'tests/test_instruction_contract_matrix.py', 'tests/test_source_role_matrix.py', 'tests/test_validation_gates.py']


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


def required_record(path, *, kind, locks, source_hash=None, runtime=None):
    if path is None or not path.is_file():
        return {'state': 'INCOMPLETE', 'reason': f'Missing {kind} evidence record.'}
    try:
        record = json.loads(path.read_text())
        if record.get('kind') != kind or record.get('state') != 'PASS':
            return {'state': 'INCOMPLETE', 'reason': f'{kind} record does not declare completed passing checks.'}
        if kind == 'clean-locked-install':
            if record.get('locks') != locks or not record.get('disposable_install') or not record.get('commands'):
                return {'state': 'INCOMPLETE', 'reason': 'Install record does not bind the current locks and disposable setup.'}
            if runtime is not None and record.get('runtime') != runtime:
                return {'state':'INCOMPLETE','reason':'Install record belongs to a different interpreter/Node/platform environment.'}
            if any(c.get('exit_code') != 0 for c in record['commands']):
                return {'state': 'FAILED', 'reason': 'An install command failed.'}
        else:
            if record.get('source_sha256') != source_hash or not record.get('matrix_review_complete'):
                return {'state': 'INCOMPLETE', 'reason': 'Review does not bind the exact candidate and complete matrix.'}
            if any(f.get('blocking') and f.get('status') != 'VERIFIED_IN_SCOPE' for f in record.get('findings', [])):
                return {'state': 'FAILED', 'reason': 'Review retains an unresolved in-scope blocker.'}
        return {'state': 'PASS', 'path': str(path), 'record': record}
    except (ValueError, OSError, AttributeError, TypeError) as exc:
        return {'state': 'INCOMPLETE', 'reason': f'Invalid {kind} evidence: {exc}'}


def browser_evidence_gate(command_gate, path):
    """Require command success and a readable, explicitly passing browser result.

    This checks receipt availability/state, not the truth of the browser assertions.
    Preserve command failures and blocked execution even when a receipt says PASS.
    """
    gate = dict(command_gate)
    gate['evidence_path'] = str(path)
    evidence_state = 'INCOMPLETE'
    try:
        raw = path.read_bytes()
        gate['evidence_sha256'] = hashlib.sha256(raw).hexdigest()
        record = json.loads(raw.decode('utf-8'))
        if not isinstance(record, dict):
            raise ValueError('Browser evidence must be a JSON object.')
        state = record.get('state')
        if not isinstance(state, str) or state not in ('PASS', 'FAILED', 'BLOCKED', 'INCOMPLETE'):
            raise ValueError('Browser evidence has a missing or unsupported state.')
        evidence_state = state
        gate['record'] = record
    except (OSError, ValueError, UnicodeError) as exc:
        gate['evidence_reason'] = f'Unavailable or invalid browser evidence: {exc}'
    gate['evidence_state'] = evidence_state
    command_state = command_gate.get('state', 'INCOMPLETE')
    if command_state == 'FAILED' or evidence_state == 'FAILED':
        gate['state'] = 'FAILED'
    elif command_state == 'BLOCKED' or evidence_state == 'BLOCKED':
        gate['state'] = 'BLOCKED'
    elif command_state == 'PASS' and evidence_state == 'PASS':
        gate['state'] = 'PASS'
    else:
        gate['state'] = 'INCOMPLETE'
    return gate


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
        run('matrix', [args.python, str(ROOT / 'tools/check_matrix.py'), '--output', str(output / 'matrix.json')])
        run('frontend-locked-install', ['npm', 'ci', '--prefer-offline', '--no-audit', '--no-fund'], ROOT / 'frontend')
        for name in ('check:format', 'check:discovery', 'build'):
            run('frontend-' + name.replace(':', '-'), ['npm', 'run', name], ROOT / 'frontend')
        install = required_record(args.install_record, kind='clean-locked-install', locks=report['locks'],runtime=report['runtime'])
        install['name'] = 'clean-locked-install'; report['gates'].append(install); save()
        run('launcher-browser-rebuild', [args.browser_python or args.python, str(ROOT / 'tools/browser_acceptance.py'),
            '--python', args.python, '--chromium', args.chromium, '--output', str(output / 'browser')])
        browser_result = output / 'browser/result.json'
        report['gates'][-1] = browser_evidence_gate(report['gates'][-1], browser_result)
        save()
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
