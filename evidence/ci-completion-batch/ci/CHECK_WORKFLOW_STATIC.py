"""Replay syntax and fixed-scope CI checks; does not execute providers or Actions."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import yaml
from tools.validate import focused_groups, FOCUSED

root = Path(__file__).resolve().parents[3]
workflow_path = root / '.github/workflows/offline-focused.yml'
workflow = yaml.safe_load(workflow_path.read_text())
assert set(workflow['jobs']) == {'focused-group', 'offline-development', 'focused-union'}
assert workflow['jobs']['focused-group']['strategy']['matrix']['group'] == list(focused_groups())
assert workflow['jobs']['focused-group']['strategy']['fail-fast'] is False
assert workflow['jobs']['focused-union']['if'] == 'always()'
assert workflow['jobs']['focused-union']['needs'] == ['focused-group', 'offline-development']
assert len(focused_groups()) == 10
assert workflow['jobs']['focused-group']['timeout-minutes'] == 30
assert workflow['jobs']['offline-development']['timeout-minutes'] == 30
focused_step = next(s for s in workflow['jobs']['focused-group']['steps'] if s['name'] == 'Run the exact focused group without network access')
assert focused_step['timeout-minutes'] == 15
development_step = next(s for s in workflow['jobs']['offline-development']['steps'] if s['name'] == 'Run product and frontend checks without network access')
assert development_step['timeout-minutes'] == 15
assert workflow['permissions'] == {'contents': 'read'}
assert workflow['concurrency']['cancel-in-progress'] is True
start_commit = '1040215f498b1317b1b942838994127f43a822bd'
old_text = subprocess.check_output(['git', 'show', start_commit + ':tools/validate.py'], cwd=root, text=True)
old_selectors = next(ast.literal_eval(node.value) for node in ast.parse(old_text).body
                     if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'FOCUSED' for t in node.targets))
new = {'tests/test_historical_membership.py', 'tests/test_wallet_position_population.py',
       'tests/test_source_fact_reuse.py', 'tests/test_disposed_origin_scopes.py'}
assert len(old_selectors) == 35 and len(FOCUSED) == 39
assert FOCUSED[:len(old_selectors)] == old_selectors
assert set(FOCUSED) == set(old_selectors) | new
checks = []
upload_names = []
allowed_artifact_names = {'result.json', 'runtime.log', 'node-runtime.log', 'backend.log',
                         'pip-check.log', 'shell-syntax.log', 'product.log',
                         'frontend-check-format.log', 'frontend-check-discovery.log',
                         'frontend-build.log', 'DIAGNOSTIC_STATUS.json'}
for job_name, job in workflow['jobs'].items():
    for step in job['steps']:
        if 'run' in step:
            script = step['run']
            proc = subprocess.run(['bash', '-n'], input=script, text=True, capture_output=True)
            assert proc.returncode == 0, (job_name, step['name'], proc.stderr)
            check = {'job': job_name, 'step': step['name'], 'bash_syntax_exit': proc.returncode}
            if "<<'PY'" in script:
                embedded = script.split("<<'PY'", 1)[1].split('\n', 1)[1].rsplit('\nPY', 1)[0]
                ast.parse(embedded)
                check['embedded_python_syntax'] = 'PASS'
                assert '4 * 1024 * 1024' in embedded and 'path.is_symlink()' in embedded
            checks.append(check)
        if step.get('uses', '').startswith('actions/upload-artifact@'):
            assert step['uses'] == 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02'
            assert step['if'] == 'always()'
            upload_names.append(step['with']['name'])
            paths = step['with']['path'].splitlines()
            assert paths and all(path.rsplit('/', 1)[-1] in allowed_artifact_names for path in paths)
            assert all('*' not in path and 'private-product' not in path and '/data/' not in path for path in paths)
            assert step['with']['retention-days'] == 7
        if step.get('uses', '').startswith('actions/download-artifact@'):
            assert step['uses'] == 'actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093'
assert upload_names == ['focused-${{ matrix.group }}', 'offline-development-receipt', 'focused-union-receipt']
union_script = next(s['run'] for s in workflow['jobs']['focused-union']['steps'] if s['name'] == 'Require the exact complete passing focused union')
for group in focused_groups():
    assert union_script.count('focused-' + group + '/result.json') == 1
assert union_script.count('--group-record ') == 10 and union_script.count('--development-record ') == 1
for job, step_name in [('focused-group', 'Run the exact focused group without network access'), ('offline-development', 'Run product and frontend checks without network access'), ('focused-union', 'Require the exact complete passing focused union')]:
    script = next(s['run'] for s in workflow['jobs'][job]['steps'] if s['name'] == step_name)
    assert 'sudo unshare --net --' in script and 'setpriv --reuid=' in script
    for key in ('HELIUS_API_KEY', 'GH_TOKEN', 'GITHUB_TOKEN'):
        assert 'test -z "${' + key + ':-}"' in script
for job in workflow['jobs'].values():
    checkout = next(s for s in job['steps'] if s.get('uses', '').startswith('actions/checkout@'))
    assert checkout['with']['persist-credentials'] is False and checkout['with']['fetch-depth'] == 0
receipt = {'kind': 'CI-workflow-static-contract', 'state': 'PASS',
           'tested_baseline': start_commit, 'retained_selectors': len(old_selectors),
           'added_regression_selectors': sorted(new), 'focused_selectors': len(FOCUSED),
           'groups': focused_groups(), 'script_checks': checks,
           'artifact_allowlist': 'Exact validator receipt/text paths; four MiB maximum per file; private product state excluded.',
           'network_scope': 'No Actions or provider execution. Static syntax and scope review only.',
           'source_hashes': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in
                            ('.github/workflows/offline-focused.yml', 'tools/validate.py', 'tests/test_validation_gates.py')}}
output = Path(__file__).with_name('WORKFLOW_STATIC_CONTRACT.json')
output.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'state': receipt['state'], 'focused_selectors': len(FOCUSED), 'bash_steps': len(checks)}))
