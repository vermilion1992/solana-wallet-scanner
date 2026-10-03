"""Isolated runner checks, NOT application/backend/browser acceptance.

Run against the unchanged uploaded validator or the project's tools/validate.py:
  VALIDATOR_UNDER_REVIEW=/path/to/tools/validate.py python -m pytest -q this_file.py

Subprocesses, source snapshots and lock reads are stubbed. main(), result parsing,
required_record() and gate_decision() execute from the selected file unchanged.
The same engineer should integrate these into the existing gate-test module,
using the real browser receipt shape. No provider calls or credentials are used.
"""
from __future__ import annotations
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import pytest

TARGET = Path(os.environ.get('VALIDATOR_UNDER_REVIEW', '/mnt/data/validate.py'))
SPEC = importlib.util.spec_from_file_location('reviewed_validate', TARGET)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
RESULTS: list[dict[str, Any]] = []
LOCKS = {'requirements.txt': 'test-lock-digest'}
SOURCE = {'sha256': 'test-source-digest', 'files': {}, 'modes': {}}
RUNTIME = {'python': '3.12.14', 'platform': sys.platform, 'node': '24.19.0'}

@pytest.fixture(scope='session', autouse=True)
def save_scenarios():
    yield
    output = os.environ.get('REVIEW_RUNNER_RESULTS')
    if output:
        Path(output).write_text(json.dumps({
            'scope': 'Isolated validator control flow; all external commands stubbed.',
            'target': str(TARGET), 'scenarios': RESULTS,
        }, indent=2) + '\n')


def execute_main(tmp_path, monkeypatch, *, receipt='{"state":"PASS"}',
                 browser_exit=0, backend_exit=0, profile='candidate', stable=True,
                 omit_record=None):
    root = tmp_path / 'repo'
    root.mkdir()
    output = root / 'evidence' / 'run'
    records = root / 'records'
    records.mkdir()
    install = records / 'install.json'
    review = records / 'review.json'
    install.write_text(json.dumps({'kind': 'clean-locked-install', 'state': 'PASS',
        'disposable_install': True, 'commands': [{'exit_code': 0}],
        'locks': LOCKS, 'runtime': RUNTIME}))
    review.write_text(json.dumps({'kind': 'consolidated-review', 'state': 'PASS',
        'source_sha256': SOURCE['sha256'], 'matrix_review_complete': True,
        'findings': []}))
    if omit_record:
        {'install': install, 'review': review}[omit_record].unlink()
    monkeypatch.setattr(VALIDATOR, 'ROOT', root)
    snapshots = iter([SOURCE, SOURCE if stable else {**SOURCE, 'sha256': 'changed'}])
    monkeypatch.setattr(VALIDATOR, 'source_manifest', lambda: next(snapshots))
    monkeypatch.setattr(VALIDATOR, 'lock_hashes', lambda: LOCKS)

    def fake_output(command, **kwargs):
        if command[:2] == ['git', 'rev-parse']:
            return 'isolated-test-commit\n'
        if 'import platform;print(platform.python_version())' in command:
            return RUNTIME['python'] + '\n'
        raise AssertionError(f'Unexpected subprocess.check_output: {command}')

    def fake_run(command, **kwargs):
        stream = kwargs['stdout']
        stream.write('v24.19.0\n' if command == ['node', '--version'] else 'STUB: not an actual command execution\n')
        if any(str(arg).endswith('browser_acceptance.py') for arg in command):
            browser_dir = Path(command[command.index('--output') + 1])
            browser_dir.mkdir(parents=True, exist_ok=True)
            if receipt is not None:
                (browser_dir / 'result.json').write_text(receipt)
            return subprocess.CompletedProcess(command, browser_exit)
        if 'pytest' in command:
            return subprocess.CompletedProcess(command, backend_exit)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(VALIDATOR.subprocess, 'check_output', fake_output)
    monkeypatch.setattr(VALIDATOR.subprocess, 'run', fake_run)
    error = None
    code = None
    try:
        code = VALIDATOR.main(['--profile', profile, '--python', sys.executable,
            '--browser-python', sys.executable, '--output', str(output),
            '--install-record', str(install), '--review-record', str(review)])
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    report = json.loads((output / 'result.json').read_text())
    outcome = {'receipt': receipt, 'browser_exit': browser_exit, 'backend_exit': backend_exit,
        'profile': profile, 'stable': stable, 'omit_record': omit_record,
        'return_code': code, 'state': report.get('state'), 'exception': error,
        'browser_gate': next((g['state'] for g in report['gates'] if g['name'] == 'launcher-browser-rebuild'), None)}
    RESULTS.append(outcome)
    return outcome


@pytest.mark.parametrize('settings,expected', [
    ({}, 'ACCEPTED_IN_SCOPE'),
    ({'profile': 'focused'}, 'FOCUSED_PASS'),
    ({'receipt': '{"state":"BLOCKED"}'}, 'INCOMPLETE'),
    ({'receipt': '{"state":"FAILED"}', 'browser_exit': 1}, 'FAILED'),
    ({'browser_exit': 1}, 'FAILED'),
    ({'backend_exit': 1}, 'FAILED'),
    ({'stable': False}, 'INCOMPLETE'),
    ({'omit_record': 'install'}, 'INCOMPLETE'),
    ({'omit_record': 'review'}, 'INCOMPLETE'),
], ids=['passing-candidate','passing-focused','blocked-browser','failed-browser',
        'bad-exit-good-receipt','failed-backend','changed-source','missing-install','missing-review'])
def test_existing_runner_controls(tmp_path, monkeypatch, settings, expected):
    result = execute_main(tmp_path, monkeypatch, **settings)
    assert result['exception'] is None, result
    assert result['state'] == expected, result
    assert (result['return_code'] == 0) == (expected in {'ACCEPTED_IN_SCOPE', 'FOCUSED_PASS'})


@pytest.mark.parametrize('receipt', [None, '{"state":"FAILED"}', '{"state":"INCOMPLETE"}',
    '{"state":"UNKNOWN"}', '{}', '{invalid json', '[]'],
    ids=['missing','failed','incomplete','unknown','missing-state','malformed-json','non-object-json'])
def test_zero_exit_requires_a_usable_passing_browser_receipt(tmp_path, monkeypatch, receipt):
    result = execute_main(tmp_path, monkeypatch, receipt=receipt)
    assert result['exception'] is None, ('Must persist a structured non-passing result, not crash', result)
    assert result['return_code'] != 0 and result['state'] in {'FAILED','INCOMPLETE'}, result


@pytest.mark.parametrize('state,stable,expected,code', [
    ('PASS', True, 'ACCEPTED_IN_SCOPE', 0),
    ('FAILED', True, 'FAILED', 1),
    ('BLOCKED', True, 'INCOMPLETE', 2),
    ('INCOMPLETE', True, 'INCOMPLETE', 2),
    ('UNKNOWN', True, 'INCOMPLETE', 2),
    ('PASS', False, 'INCOMPLETE', 2),
])
def test_existing_aggregate_state_controls(state, stable, expected, code):
    assert VALIDATOR.gate_decision([{'state': state}], stable=stable) == (expected, code)


@pytest.mark.parametrize('change,expected', [
    ({'locks': {}}, 'INCOMPLETE'),
    ({'runtime': {}}, 'INCOMPLETE'),
    ({'disposable_install': False}, 'INCOMPLETE'),
    ({'commands': []}, 'INCOMPLETE'),
    ({'commands': [{'exit_code': 1}]}, 'FAILED'),
    ({'state': 'BLOCKED'}, 'INCOMPLETE'),
])
def test_existing_install_record_controls(tmp_path, change, expected):
    record = {'kind':'clean-locked-install', 'state':'PASS', 'disposable_install':True,
        'commands':[{'exit_code':0}], 'locks':LOCKS, 'runtime':RUNTIME}
    record.update(change)
    path = tmp_path / 'install.json'
    path.write_text(json.dumps(record))
    assert VALIDATOR.required_record(path, kind='clean-locked-install', locks=LOCKS, runtime=RUNTIME)['state'] == expected


@pytest.mark.parametrize('change,expected', [
    ({'source_sha256': 'wrong'}, 'INCOMPLETE'),
    ({'matrix_review_complete': False}, 'INCOMPLETE'),
    ({'findings':[{'blocking':True, 'status':'OPEN'}]}, 'FAILED'),
    ({'findings':[{'blocking':True, 'status':'VERIFIED_IN_SCOPE'}]}, 'PASS'),
])
def test_existing_review_record_controls(tmp_path, change, expected):
    record = {'kind':'consolidated-review', 'state':'PASS',
        'source_sha256':SOURCE['sha256'], 'matrix_review_complete':True, 'findings':[]}
    record.update(change)
    path = tmp_path / 'review.json'
    path.write_text(json.dumps(record))
    assert VALIDATOR.required_record(path, kind='consolidated-review', locks=LOCKS, source_hash=SOURCE['sha256'])['state'] == expected
