"""Evidence-only exact-source read-only affected review commands."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.validate import source_manifest
OUT = Path(__file__).resolve().parent
expected = 'e9380f167804e860d05fd4e3293dc51d5609910ddfbe4c1a8644a08b6151bd09'
commands = [
    ('AFFECTED_SUBSET', ['.venv/bin/python', '-m', 'pytest', '-q', 'tests/test_report_view.py',
        'tests/test_copy_review_api.py', 'tests/test_candidate_import.py', 'tests/test_report_rebuild.py']),
    ('FRONTEND_VIEW', ['node', 'scripts/check-discovery.mjs']),
    ('RUNNER_PREPARATION', ['python3', str(OUT/'replay_browser_preparation.py'), str(OUT/'RUNNER_PREPARATION_RESULT.json')]),
]
entry = sys.argv[1]
name, command = next(c for c in commands if c[0] == entry)
before = source_manifest()
assert before['sha256'] == expected, 'Review requires the frozen final source'
started = time.monotonic()
process = subprocess.run(command, cwd=ROOT/'frontend' if entry == 'FRONTEND_VIEW' else ROOT,
    env={**{k:v for k,v in os.environ.items() if k != 'HELIUS_API_KEY'}, 'PYTHONDONTWRITEBYTECODE':'1'},
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
log = OUT/(entry+'.log'); log.write_bytes(process.stdout)
after = source_manifest()
receipt = {'kind':'distinct-read-only-followup-review-command', 'state': 'PASS_IN_SCOPE' if process.returncode == 0 and before['sha256'] == after['sha256'] else 'FAILED',
    'command': command, 'cwd': str(ROOT/'frontend' if entry == 'FRONTEND_VIEW' else ROOT), 'exit_code':process.returncode,
    'seconds':time.monotonic()-started, 'source_before_sha256': before['sha256'], 'source_after_sha256':after['sha256'],
    'source_unchanged':before == after, 'application_candidate':'73c9eb5a6fb1cabf7eca8126f029da3aff20f774',
    'raw_log':str(log.relative_to(ROOT)), 'raw_log_sha256':hashlib.sha256(process.stdout).hexdigest(),
    'provider_requests':0, 'credential_lookups':0, 'scope':'Affected offline review only; root candidate gates and genuine B3 are separate.'}
if entry == 'AFFECTED_SUBSET':
    output = process.stdout.decode('utf-8', 'replace')
    passed = re.search(r'(\d+) passed', output)
    subtests = re.search(r'(\d+) subtests passed', output)
    receipt.update(ordinary_tests_passed=int(passed.group(1)) if passed else None,
        subtests_passed=int(subtests.group(1)) if subtests else 0)
else:
    receipt['not_unique_tests'] = True
(OUT/(entry+'.json')).write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,sort_keys=True))
raise SystemExit(0 if receipt['state'] == 'PASS_IN_SCOPE' else 1)
