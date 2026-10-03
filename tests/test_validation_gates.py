"""Acceptance records must bind their gates; backend green alone is insufficient."""
import json
from pathlib import Path
import pytest
from tools.validate import gate_decision,required_record

@pytest.mark.parametrize('state,expected',[('FAILED',1),('BLOCKED',2),('INCOMPLETE',2)])
def test_one_unclosed_required_gate_prevents_acceptance(state,expected):
    result,code=gate_decision([{'state':'PASS'},{'state':state}],stable=True)
    assert code==expected and result!='ACCEPTED_IN_SCOPE'

def test_changed_candidate_cannot_use_old_results():
    assert gate_decision([{'state':'PASS'}],stable=False)==('INCOMPLETE',2)

def test_missing_review_prevents_acceptance(tmp_path):
    assert required_record(tmp_path/'missing.json',kind='consolidated-review',locks={},source_hash='a')['state']=='INCOMPLETE'

def test_stale_review_and_live_blocker_are_not_accepted(tmp_path):
    p=tmp_path/'review.json';r={'kind':'consolidated-review','state':'PASS','source_sha256':'old','matrix_review_complete':True,'findings':[]};p.write_text(json.dumps(r))
    assert required_record(p,kind='consolidated-review',locks={},source_hash='new')['state']=='INCOMPLETE'
    r.update(source_sha256='new',findings=[{'blocking':True,'status':'OPEN'}]);p.write_text(json.dumps(r))
    assert required_record(p,kind='consolidated-review',locks={},source_hash='new')['state']=='FAILED'
    r['findings'][0]['status']='VERIFIED_IN_SCOPE';p.write_text(json.dumps(r))
    assert required_record(p,kind='consolidated-review',locks={},source_hash='new')['state']=='PASS'

@pytest.mark.parametrize('change',['locks','command'])
def test_install_record_needs_current_locks_and_successful_command(tmp_path,change):
    p=tmp_path/'install.json';r={'kind':'clean-locked-install','state':'PASS','disposable_install':True,'locks':{'r':'a'},'commands':[{'exit_code':0}]}
    if change=='locks':r['locks']={'r':'b'}
    else:r['commands'][0]['exit_code']=1
    p.write_text(json.dumps(r));assert required_record(p,kind='clean-locked-install',locks={'r':'a'})['state']!='PASS'

def test_install_cache_is_bound_to_the_runtime_as_well_as_locks(tmp_path):
    p=tmp_path/'install.json';p.write_text(json.dumps({'kind':'clean-locked-install','state':'PASS','disposable_install':True,'locks':{'r':'a'},'commands':[{'exit_code':0}],'runtime':{'python':'old'}}))
    assert required_record(p,kind='clean-locked-install',locks={'r':'a'},runtime={'python':'new'})['state']=='INCOMPLETE'


# External PROC-03 reproducers: only positive fixtures use actual producer schemas.
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any
import pytest

from tools import validate as VALIDATOR
TARGET = Path(VALIDATOR.__file__)
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


def execute_main(tmp_path, monkeypatch, *, receipt='producer-pass', matrix_receipt='producer-pass',
                 browser_exit=0, backend_exit=0, profile='candidate', stable=True,
                 omit_record=None):
    fixture = json.loads((Path(__file__).parent / 'fixtures/validation_receipts.json').read_text())
    if receipt == 'producer-pass':
        receipt = json.dumps(fixture['browser'])
    if matrix_receipt == 'producer-pass':
        matrix_receipt = json.dumps(fixture['matrix'])
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
        if any(str(arg).endswith('check_matrix.py') for arg in command):
            if matrix_receipt is not None:
                Path(command[command.index('--output') + 1]).write_text(matrix_receipt)
            return subprocess.CompletedProcess(command, 0)
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


@pytest.mark.parametrize('receipt', [None, '{}', '[]', '{invalid', '{"state":"FAILED"}', '{"state":"PASS"}'])
def test_matrix_receipt_has_the_same_required_boundary(tmp_path, monkeypatch, receipt):
    result = execute_main(tmp_path, monkeypatch, matrix_receipt=receipt)
    assert result['exception'] is None and result['return_code'] != 0

@pytest.mark.parametrize('kind', ['clean-locked-install', 'consolidated-review'])
@pytest.mark.parametrize('value', [[], None, 1, {'state':'PASS','kind':'irrelevant'}])
def test_attestations_are_structured_incomplete_on_invalid_shapes(tmp_path, kind, value):
    path = tmp_path / 'receipt.json'; path.write_text(json.dumps(value))
    assert required_record(path, kind=kind, locks={}, source_hash='a')['state'] == 'INCOMPLETE'


def test_passing_receipt_bytes_are_hashed_and_false_guards_fail(tmp_path):
    from tools.validate import structured_evidence_gate
    path = tmp_path/'receipt.json'
    fixture = json.loads((Path(__file__).parent/'fixtures/validation_receipts.json').read_text())['browser']
    path.write_text(json.dumps(fixture))
    gate = structured_evidence_gate({'state':'PASS'}, path, kind='browser')
    assert gate['state'] == 'PASS' and len(gate['evidence_receipt']['sha256']) == 64
    fixture['offline_guards']['credential_lookups'] = 1; path.write_text(json.dumps(fixture))
    assert structured_evidence_gate({'state':'PASS'}, path, kind='browser')['state'] == 'FAILED'
