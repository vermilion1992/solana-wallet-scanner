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
                 omit_record=None, focused_group=None, summary_change=None, product_receipt='producer-pass', backend_timeout=False, product_timeout=False):
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
        if any(str(arg).endswith('check_product.py') for arg in command):
            if product_timeout:
                raise subprocess.TimeoutExpired(command, kwargs['timeout'])
            directory = Path(command[command.index('--output') + 1])
            directory.mkdir()
            if product_receipt is not None:
                value = product_receipt_value() if product_receipt == 'producer-pass' else product_receipt
                (directory / 'result.json').write_text(json.dumps(value))
            return subprocess.CompletedProcess(command, 0)
        if 'pytest' in command:
            if backend_timeout:
                raise subprocess.TimeoutExpired(command, kwargs['timeout'])
            return subprocess.CompletedProcess(command, backend_exit)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(VALIDATOR.subprocess, 'check_output', fake_output)
    monkeypatch.setattr(VALIDATOR, 'execute_command', fake_run)
    error = None
    code = None
    extra = ['--focused-group', focused_group] if focused_group else []
    if profile == 'focused-summary':
        paths = group_receipts(records)
        development = development_receipt(records)
        for path in [*paths, development]:
            value = json.loads(path.read_text())
            value['commit'] = 'isolated-test-commit'
            path.write_text(json.dumps(value))
        if summary_change == 'missing-group':
            paths.pop()
        elif summary_change == 'nonpassing-group':
            value = json.loads(paths[0].read_text()); value['state'] = 'INCOMPLETE'; paths[0].write_text(json.dumps(value))
        elif summary_change == 'missing-development':
            development.unlink()
        extra = [arg for path in paths for arg in ('--group-record', str(path))]
        extra += ['--development-record', str(development)]
    try:
        code = VALIDATOR.main(['--profile', profile, '--python', sys.executable,
            '--browser-python', sys.executable, '--output', str(output),
            '--install-record', str(install), '--review-record', str(review), *extra])
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    report = json.loads((output / 'result.json').read_text())
    outcome = {'receipt': receipt, 'browser_exit': browser_exit, 'backend_exit': backend_exit,
        'profile': profile, 'stable': stable, 'omit_record': omit_record,
        'return_code': code, 'state': report.get('state'), 'exception': error,
        'focused_group': report.get('focused_group'), 'selection': report.get('selection'),
        'runtime': report.get('runtime'), 'gates': report['gates'],
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


# Native CI batches are one exact partition of the existing focused selectors.
# Their raw command logs and explicit receipts travel together; a green job or
# absent diagnostics alone cannot establish this iteration's union.
import copy
import hashlib


def group_receipts(tmp_path):
    paths = []
    for name, selectors in VALIDATOR.focused_groups().items():
        directory = tmp_path / name
        directory.mkdir()
        source_root = str(VALIDATOR.ROOT)
        commands = {
            'runtime': [sys.executable, '-c', 'import sys, pathlib, scanner; assert sys.version_info >= (3,11); assert pathlib.Path(scanner.__file__).resolve().parent == pathlib.Path.cwd()/"scanner"; print(sys.version)'],
            'node-runtime': ['node', '--version'],
            'backend': [sys.executable, '-m', 'pytest', '-v', '--durations=10', *selectors],
        }
        gates = []
        for gate_name in ('runtime', 'node-runtime', 'backend'):
            raw = f'raw {name} {gate_name} output\n'.encode()
            (directory / (gate_name + '.log')).write_bytes(raw)
            gates.append({'name': gate_name, 'state': 'PASS', 'exit_code': 0,
                          'command': commands[gate_name], 'cwd': source_root,
                          'timeout_seconds': 600, 'timed_out': False,
                          'log_bytes': len(raw), 'log_sha256': hashlib.sha256(raw).hexdigest()})
        path = directory / 'result.json'
        path.write_text(json.dumps({'profile': 'focused', 'state': 'FOCUSED_GROUP_PASS',
            'focused_group': name, 'selection': selectors, 'source_unchanged': True,
            'source': SOURCE, 'locks': LOCKS, 'runtime': RUNTIME, 'commit': 'current',
            'interpreter': sys.executable, 'source_root': source_root, 'gates': gates}))
        paths.append(path)
    return paths


def read_group_records(paths):
    return VALIDATOR.focused_group_records(paths, source=SOURCE, locks=LOCKS, runtime=RUNTIME, commit='current')


def test_focused_batches_preserve_the_exact_existing_union():
    groups = VALIDATOR.focused_groups()
    selectors = [selector for paths in groups.values() for selector in paths]
    assert len(groups) == 11
    assert len(selectors) == len(set(selectors)) == len(VALIDATOR.FOCUSED)
    assert set(selectors) == set(VALIDATOR.FOCUSED)


def test_hosted_matrix_and_union_require_the_new_screening_paths():
    import re
    workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/offline-focused.yml').read_text()
    match = re.search(r'group:\s*\[([^\]]+)\]', workflow)
    assert match is not None
    hosted_groups = [value.strip() for value in match.group(1).split(',')]
    assert len(hosted_groups) == len(set(hosted_groups))
    assert set(hosted_groups) == set(VALIDATOR.focused_groups())
    receipt_groups = re.findall(r'--group-record "\$CI_RECEIPTS/focused-([^/]+)/result.json"', workflow)
    assert len(receipt_groups) == len(set(receipt_groups))
    assert set(receipt_groups) == set(hosted_groups)
    mass_search = {
        'tests/test_mass_search_funnel.py', 'tests/test_mass_search_routes.py',
        'tests/test_mass_search_scale.py', 'tests/test_mass_search_receipt.py',
        'tests/test_mass_search_g1.py',
        'tests/test_mass_search_ranked100.py',
        'tests/test_mass_search_g3.py',
    }
    assert set(VALIDATOR.FOCUSED_GROUPS['screening']) == {
        'tests/test_screening.py', 'tests/test_screening_routes.py',
        'tests/test_public_sample_budget.py', 'tests/test_paper.py',
        'tests/test_observer.py', 'tests/test_candidate_import.py',
        *mass_search,
    }
    assert mass_search <= set(VALIDATOR.SCREENING_FORWARD)
    assert mass_search <= set(VALIDATOR.FOCUSED)


@pytest.mark.parametrize('change', ['duplicate', 'missing', 'extra', 'directory-overlap'])
def test_focused_partition_rejects_selector_loss_and_overlap(monkeypatch, change):
    groups = copy.deepcopy(VALIDATOR.FOCUSED_GROUPS)
    if change == 'duplicate':
        groups['schemas'].append(groups['historical'][0])
    elif change == 'missing':
        groups['schemas'].pop()
    elif change == 'extra':
        groups['schemas'].append('tests/unreviewed.py')
    else:
        groups['schemas'].append('tests/review_v039/test_child.py')
        monkeypatch.setattr(VALIDATOR, 'FOCUSED', [*VALIDATOR.FOCUSED, 'tests/review_v039/test_child.py'])
    monkeypatch.setattr(VALIDATOR, 'FOCUSED_GROUPS', groups)
    with pytest.raises(ValueError):
        VALIDATOR.focused_groups()


def test_complete_bound_group_receipts_pass_in_any_order(tmp_path):
    paths = group_receipts(tmp_path)
    result = read_group_records(list(reversed(paths)))
    assert result['state'] == 'PASS' and len(result['receipts']) == 11
    assert all(receipt['state'] == 'PASS' and len(receipt['sha256']) == 64 for receipt in result['receipts'])
    assert result['selectors'] == VALIDATOR.FOCUSED


@pytest.mark.parametrize('change', ['missing', 'duplicate', 'unknown', 'nonpassing', 'changed-source',
    'changed-locks', 'changed-runtime', 'changed-commit', 'source-modified', 'changed-selection',
    'zero-exit-nonpassing-gate', 'false-exit-code', 'changed-command', 'missing-log', 'changed-log',
    'non-object-receipt', 'malformed-receipt', 'unhashable-gate-name',
    'timeout-even-zero-exit', 'wrong-timeout', 'boolean-timeout', 'missing-timeout', 'missing-timeout-state',
    'runtime-timeout', 'active-gate-remains', 'wrong-runtime-command', 'wrong-node-command',
    'wrong-cwd', 'bad-source-root', 'missing-source-root', 'relative-interpreter', 'timeout-abort'])
def test_focused_union_rejects_incomplete_or_stale_evidence(tmp_path, change):
    paths = group_receipts(tmp_path)
    path = paths[0]
    record = json.loads(path.read_text())
    if change == 'missing':
        paths.pop()
    elif change == 'duplicate':
        paths[-1] = paths[0]
    elif change == 'unknown':
        record['focused_group'] = 'unreviewed'
    elif change == 'nonpassing':
        record['state'] = 'INCOMPLETE'
    elif change == 'changed-source':
        record['source'] = {**SOURCE, 'sha256': 'old'}
    elif change == 'changed-locks':
        record['locks'] = {}
    elif change == 'changed-runtime':
        record['runtime'] = {**RUNTIME, 'node': 'old'}
    elif change == 'changed-commit':
        record['commit'] = 'old'
    elif change == 'source-modified':
        record['source_unchanged'] = False
    elif change == 'changed-selection':
        record['selection'] = []
    elif change == 'zero-exit-nonpassing-gate':
        record['gates'][0]['state'] = 'FAILED'
    elif change == 'false-exit-code':
        record['gates'][0]['exit_code'] = False
    elif change == 'changed-command':
        record['gates'][-1]['command'] = [sys.executable, '-m', 'pytest', '-q']
    elif change == 'missing-log':
        (path.parent / 'backend.log').unlink()
    elif change == 'changed-log':
        (path.parent / 'backend.log').write_text('replacement bytes')
    elif change == 'timeout-abort':
        record['timeout_abort'] = True
    elif change == 'wrong-runtime-command':
        record['gates'][0]['command'] = [sys.executable, '-c', 'print("fake-runtime")']
    elif change == 'wrong-node-command':
        record['gates'][1]['command'] = ['node', '-e', 'console.log("fake-runtime")']
    elif change == 'wrong-cwd':
        record['gates'][-1]['cwd'] = '/other-checkout'
    elif change == 'bad-source-root':
        record['source_root'] = []
    elif change == 'missing-source-root':
        del record['source_root']
    elif change == 'relative-interpreter':
        record['interpreter'] = 'python'
    elif change == 'runtime-timeout':
        record['gates'][0]['timed_out'] = True
    elif change == 'active-gate-remains':
        record['running_gate'] = {'name': 'backend'}
    elif change == 'timeout-even-zero-exit':
        record['gates'][-1]['timed_out'] = True
    elif change == 'wrong-timeout':
        record['gates'][-1]['timeout_seconds'] = 1800
    elif change == 'boolean-timeout':
        record['gates'][-1]['timeout_seconds'] = True
    elif change == 'missing-timeout':
        del record['gates'][-1]['timeout_seconds']
    elif change == 'missing-timeout-state':
        del record['gates'][-1]['timed_out']
    elif change == 'non-object-receipt':
        record = []
    elif change == 'malformed-receipt':
        path.write_text('{invalid')
    else:
        record['gates'][0]['name'] = []
    if change != 'malformed-receipt':
        path.write_text(json.dumps(record))
    assert read_group_records(paths)['state'] != 'PASS'


def development_receipt(tmp_path):
    directory = tmp_path / 'development'
    directory.mkdir()
    source_root = str(VALIDATOR.ROOT)
    commands = {
        'runtime': [sys.executable, '-c', 'import sys, pathlib, scanner; assert sys.version_info >= (3,11); assert pathlib.Path(scanner.__file__).resolve().parent == pathlib.Path.cwd()/"scanner"; print(sys.version)'],
        'node-runtime': ['node', '--version'],
        'pip-check': [sys.executable, '-m', 'pip', 'check'],
        'shell-syntax': ['bash', '-n', 'run.sh', 'setup.sh'],
        'product': [sys.executable, str(VALIDATOR.ROOT / 'tools/check_product.py'), '--output', str(directory / 'private-product')],
        'frontend-check-format': ['npm', 'run', 'check:format'],
        'frontend-check-discovery': ['npm', 'run', 'check:discovery'],
        'frontend-build': ['npm', 'run', 'build'],
    }
    gates = []
    for name in ('runtime', 'node-runtime', 'pip-check', 'shell-syntax', 'product',
                 'frontend-check-format', 'frontend-check-discovery', 'frontend-build'):
        raw = (name + ' command output\n').encode()
        (directory / (name + '.log')).write_bytes(raw)
        gates.append({'name': name, 'state': 'PASS', 'exit_code': 0,
                      'timeout_seconds': 600, 'timed_out': False, 'command': commands[name],
                      'cwd': str(VALIDATOR.ROOT / 'frontend') if name.startswith('frontend-') else source_root,
                      'log_bytes': len(raw), 'log_sha256': hashlib.sha256(raw).hexdigest()})
    gates[4]['product_assertions'] = {name: True for name in ('development_pass', 'real_acceptance_blocked',
        'zero_provider_requests', 'zero_credential_lookups', 'parent_unchanged', 'usage_unchanged', 'no_collector_ancestry')}
    path = directory / 'result.json'
    path.write_text(json.dumps({'profile': 'offline-development', 'state': 'DEVELOPMENT_CHECK_PASS',
        'source_unchanged': True, 'source': SOURCE, 'locks': LOCKS, 'runtime': RUNTIME,
        'commit': 'current', 'gates': gates, 'interpreter': sys.executable,
        'source_root': source_root, 'output': str(directory)}))
    return path


@pytest.mark.parametrize('change', ['positive', 'missing', 'nonpassing', 'runtime', 'changed-after-build',
                                   'product-failed', 'credential-lookup', 'integer-assertion', 'missing-log', 'changed-log',
    'active-gate', 'timed-out', 'missing-timeout', 'wrong-timeout', 'boolean-timeout', 'missing-timeout-state',
    'missing-interpreter', 'bad-source-root', 'missing-output', 'wrong-python', 'wrong-product-path',
    'wrong-private-output', 'wrong-frontend-script', 'wrong-cwd', 'timeout-abort'])
def test_development_receipt_requires_bound_passing_product_and_frontend(tmp_path, change):
    path = development_receipt(tmp_path)
    record = json.loads(path.read_text())
    if change == 'missing':
        path.unlink()
    elif change == 'nonpassing':
        record['state'] = 'INCOMPLETE'
    elif change == 'runtime':
        record['runtime'] = {}
    elif change == 'changed-after-build':
        record['source_unchanged'] = False
    elif change == 'timeout-abort':
        record['timeout_abort'] = True
    elif change == 'active-gate':
        record['running_gate'] = {'name': 'product'}
    elif change == 'timed-out':
        record['gates'][4]['timed_out'] = True
    elif change == 'missing-timeout':
        del record['gates'][4]['timeout_seconds']
    elif change == 'wrong-timeout':
        record['gates'][4]['timeout_seconds'] = 1800
    elif change == 'boolean-timeout':
        record['gates'][4]['timeout_seconds'] = True
    elif change == 'missing-timeout-state':
        del record['gates'][4]['timed_out']
    elif change == 'missing-interpreter':
        del record['interpreter']
    elif change == 'bad-source-root':
        record['source_root'] = []
    elif change == 'missing-output':
        del record['output']
    elif change == 'wrong-python':
        record['gates'][2]['command'][0] = '/different/python'
    elif change == 'wrong-product-path':
        record['gates'][4]['command'][1] = '/other/tools/check_product.py'
    elif change == 'wrong-private-output':
        record['gates'][4]['command'][-1] = '/other/private-product'
    elif change == 'wrong-frontend-script':
        record['gates'][-1]['command'] = ['npm', 'run', 'unreviewed-script']
    elif change == 'wrong-cwd':
        record['gates'][-1]['cwd'] = '/other/frontend'
    elif change == 'product-failed':
        record['gates'][4]['state'] = 'FAILED'
    elif change == 'credential-lookup':
        record['gates'][4]['product_assertions']['zero_credential_lookups'] = False
    elif change == 'integer-assertion':
        record['gates'][4]['product_assertions']['zero_credential_lookups'] = 1
    elif change == 'missing-log':
        (path.parent / 'frontend-build.log').unlink()
    elif change == 'changed-log':
        (path.parent / 'frontend-build.log').write_text('changed')
    if change != 'missing':
        path.write_text(json.dumps(record))
    result = VALIDATOR.offline_development_record(path, source=SOURCE, locks=LOCKS, runtime=RUNTIME, commit='current')
    assert (result['state'] == 'PASS') == (change == 'positive')


def product_receipt_value():
    return {'kind': 'offline-product-check', 'state': 'DEVELOPMENT_PASS', 'development': {'state': 'PASS'},
        'real_acceptance': {'state': 'BLOCKED'}, 'real_acceptance_required': False,
        'provider_requests': 0, 'credential_lookups': 0, 'parent_unchanged': True,
        'collector_ancestry_created': False, 'usage_before': {}, 'usage_after': {},
        'cases': [{'case': name, 'state': 'PASS'} for name in ('synthetic-positive-normal-report',
            'valuation_hash-loss-and-exact-restoration', 'world_hash-loss-and-exact-restoration')],
        'private_report': 'must never be copied to the validation receipt'}


@pytest.mark.parametrize('change', ['positive', 'missing', 'non-object', 'false-count', 'provider-call',
    'credential-lookup', 'changed-parent', 'missing-case', 'real-pass', 'failed-command', 'false-product-pass'])
def test_offline_product_command_requires_usable_receipt_without_copying_state(tmp_path, change):
    record = product_receipt_value()
    path = tmp_path / 'product.json'
    command = {'state': 'PASS', 'exit_code': 0}
    if change == 'non-object':
        record = []
    elif change == 'false-count':
        record['provider_requests'] = False
    elif change == 'provider-call':
        record['provider_requests'] = 1
    elif change == 'credential-lookup':
        record['credential_lookups'] = 1
    elif change == 'changed-parent':
        record['parent_unchanged'] = False
    elif change == 'missing-case':
        record['cases'].pop()
    elif change == 'real-pass':
        record['real_acceptance']['state'] = 'PASS'
    elif change == 'failed-command':
        command.update(state='FAILED', exit_code=1)
    elif change == 'false-product-pass':
        record['development']['state'] = 'FAILED'
    if change != 'missing':
        path.write_text(json.dumps(record))
    result = VALIDATOR.offline_product_gate(command, path)
    assert (result['state'] == 'PASS') == (change == 'positive')
    assert 'private_report' not in json.dumps(result) and 'must never be copied' not in json.dumps(result)


@pytest.mark.parametrize('group', tuple(VALIDATOR.FOCUSED_GROUPS))
def test_group_entrypoint_runs_only_its_exact_selection_and_writes_bound_logs(tmp_path, monkeypatch, group):
    result = execute_main(tmp_path, monkeypatch, profile='focused', focused_group=group)
    assert result['exception'] is None and result['return_code'] == 0 and result['state'] == 'FOCUSED_GROUP_PASS'
    assert result['focused_group'] == group and result['selection'] == VALIDATOR.FOCUSED_GROUPS[group]
    assert result['runtime'] == RUNTIME
    assert {gate['name'] for gate in result['gates']} == {'runtime', 'node-runtime', 'backend'}
    assert all(type(gate['log_bytes']) is int and len(gate['log_sha256']) == 64 for gate in result['gates'])
    backend = next(g for g in result['gates'] if g['name'] == 'backend')
    assert backend['command'][1:] == ['-m', 'pytest', '-v', '--durations=10', *VALIDATOR.FOCUSED_GROUPS[group]]
    assert backend['timeout_seconds'] == 600 and backend['timed_out'] is False


@pytest.mark.parametrize('change,expected', [(None, 'FOCUSED_PASS'), ('missing-group', 'INCOMPLETE'),
    ('nonpassing-group', 'INCOMPLETE'), ('missing-development', 'INCOMPLETE')])
def test_summary_entrypoint_requires_the_full_bound_union_and_development(tmp_path, monkeypatch, change, expected):
    result = execute_main(tmp_path, monkeypatch, profile='focused-summary', summary_change=change)
    assert result['exception'] is None and result['state'] == expected
    assert (result['return_code'] == 0) == (expected == 'FOCUSED_PASS')
    assert not any(gate['name'] == 'backend' for gate in result['gates'])


@pytest.mark.parametrize('missing,stable,expected', [(False, True, 'DEVELOPMENT_CHECK_PASS'),
    (True, True, 'INCOMPLETE'), (False, False, 'INCOMPLETE')])
def test_development_entrypoint_checks_product_receipt_and_final_source(tmp_path, monkeypatch, missing, stable, expected):
    result = execute_main(tmp_path, monkeypatch, profile='offline-development', stable=stable,
                          product_receipt=None if missing else 'producer-pass')
    assert result['exception'] is None and result['state'] == expected
    assert (result['return_code'] == 0) == (expected == 'DEVELOPMENT_CHECK_PASS')
    assert not any(gate['name'] == 'backend' for gate in result['gates'])
    assert len(result['gates']) == 8


def test_interrupted_focused_command_retains_bound_log_and_nonpassing_receipt(tmp_path, monkeypatch):
    result = execute_main(tmp_path, monkeypatch, profile='focused',
                          focused_group='indexed-integration', backend_timeout=True)
    assert result['exception'] is None and result['return_code'] == 2
    assert result['state'] == 'INCOMPLETE'
    backend = next(gate for gate in result['gates'] if gate['name'] == 'backend')
    assert backend['state'] == 'BLOCKED' and backend['timed_out'] is True
    assert backend['timeout_seconds'] == 600 and 'exit_code' not in backend
    assert type(backend['log_bytes']) is int and len(backend['log_sha256']) == 64
    receipt = json.loads((tmp_path / 'repo/evidence/run/result.json').read_text())
    assert receipt['source'] == SOURCE and receipt['source_unchanged'] is True
    assert 'running_gate' not in receipt


def test_candidate_command_timeout_is_preserved(tmp_path, monkeypatch):
    result = execute_main(tmp_path, monkeypatch, backend_timeout=True)
    backend = next(gate for gate in result['gates'] if gate['name'] == 'backend')
    assert result['return_code'] == 2 and backend['state'] == 'BLOCKED'
    assert backend['timeout_seconds'] == 1800 and backend['timed_out'] is True


def test_development_timeout_preserves_diagnostics_without_starting_more_commands(tmp_path, monkeypatch):
    result = execute_main(tmp_path, monkeypatch, profile='offline-development', product_timeout=True)
    assert result['exception'] is None and result['return_code'] == 2
    assert result['state'] == 'INCOMPLETE'
    receipt = json.loads((tmp_path / 'repo/evidence/run/result.json').read_text())
    assert receipt['timeout_abort'] is True and receipt['source_unchanged'] is True
    product = next(g for g in result['gates'] if g['name'] == 'product')
    assert product['state'] == 'BLOCKED' and product['timed_out'] is True
    frontend = [g for g in result['gates'] if g['name'].startswith('frontend-')]
    assert len(frontend) == 3
    for gate in frontend:
        assert gate['state'] == 'BLOCKED' and gate['attempted'] is False
        assert 'exit_code' not in gate and gate['timeout_seconds'] == 600
        assert 'NOT_EXECUTED_AFTER_PRIOR_COMMAND_TIMEOUT' in Path(gate['log']).read_text()
        assert len(gate['log_sha256']) == 64


def test_real_bounded_command_preserves_output_and_success(tmp_path):
    log = tmp_path / 'command.log'
    with log.open('w') as output:
        proc = VALIDATOR.execute_command([sys.executable, '-u', '-c', 'print("actual-child-output")'],
            cwd=tmp_path, env={**os.environ, 'PYTHONUNBUFFERED': '1'}, stdout=output, timeout=5)
    assert proc.returncode == 0 and log.read_text() == 'actual-child-output\n'


def test_real_timeout_stops_command_and_posix_descendants_without_losing_output(tmp_path):
    import time
    marker = tmp_path / 'descendant-after-timeout'
    ready = tmp_path / 'descendant-ready'
    child = 'import time,pathlib,signal; signal.signal(signal.SIGTERM, signal.SIG_IGN); pathlib.Path(' + repr(str(ready)) + ').write_text("ready"); time.sleep(2); pathlib.Path(' + repr(str(marker)) + ').write_text("should-not-run")'
    # POSIX exercises a descendant, while other platforms still exercise the
    # direct-child timeout; only the executed Linux process-group scope is claimed.
    spawn = ('import subprocess,time,pathlib\nsubprocess.Popen(' + repr([sys.executable, '-c', child]) + ')\n'
             + 'while not pathlib.Path(' + repr(str(ready)) + ').exists(): time.sleep(0.01)\n') if os.name == 'posix' else ''
    command = [sys.executable, '-u', '-c', spawn + 'import time; print("before-timeout", flush=True); time.sleep(30)']
    log = tmp_path / 'partial.log'
    with log.open('w') as output:
        with pytest.raises(subprocess.TimeoutExpired):
            VALIDATOR.execute_command(command, cwd=tmp_path,
                env={**os.environ, 'PYTHONUNBUFFERED': '1'}, stdout=output, timeout=1)
    assert 'before-timeout' in log.read_text() and 'VALIDATION_COMMAND_TIMEOUT' in log.read_text()
    if os.name == 'posix':
        assert ready.read_text() == 'ready'
        time.sleep(2)
        assert not marker.exists()
