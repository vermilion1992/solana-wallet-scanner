"""Execute four frozen offline workflow modes with explicit receipt checks.

Expected BLOCKED/exit 2 remains real-acceptance blockage, never product PASS.
Only new evidence directories are written. Original archived bytes, worked
expectations, source files and Git HEAD must remain unchanged throughout.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scanner.json_boundary import parse_json
from tools.validate import source_manifest

OUT = Path(__file__).resolve().parent
COMMIT = '7e4769922ad8055b8c290f7625401d8a42fd183b'
SOURCE = '578029f5d9a608e62b1336889b52e90025831732aeec2cea087a1dd8d57d7ee2'
INPUT = ROOT / 'evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip'
FREEZE = ROOT / 'evidence/genuine-wallet-batch/checker-inputs/FINAL_INPUT_FREEZE.json'
WORKED = ROOT / 'evidence/genuine-wallet-batch/WORKED_REAL_EXPECTATIONS_FINAL.json'
ORIGINALS = {INPUT: 'eec702fdd821066897710d2085bf5c39380e303e8426249e22fb6379b7ccf1b4',
             WORKED: '97c9f92202398aef69ef0e2ce78f3d81ef67814187ca233ce5c36f8363cde9ba'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def head():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def inputs():
    return {str(path.relative_to(ROOT)): {'bytes': path.stat().st_size, 'sha256': digest(path.read_bytes())}
            for path in (INPUT, FREEZE, WORKED)}


def explicit_zero(value):
    return type(value) is int and value == 0


def receipt_checks(record, *, genuine, expected_state):
    checks = {'receipt_object': isinstance(record, dict)}
    if not isinstance(record, dict):
        return checks
    checks.update(state=record.get('state') == expected_state,
        provider_requests_zero=explicit_zero(record.get('provider_requests')),
        credential_lookups_zero=explicit_zero(record.get('credential_lookups')),
        parent_unchanged=record.get('parent_unchanged') is True,
        real_acceptance_blocked=isinstance(record.get('real_acceptance'), dict)
            and record['real_acceptance'].get('state') == 'BLOCKED',
        cases_explicitly_passing=isinstance(record.get('cases'), list) and bool(record['cases'])
            and all(isinstance(case, dict) and case.get('state') == 'PASS' for case in record['cases']))
    if genuine:
        checks.update(kind=record.get('kind') == 'offline-genuine-collection-workflow',
            usage_unchanged=record.get('usage_unchanged') is True,
            original_archive_identity=record.get('archive_sha256') == ORIGINALS[INPUT],
            oracle_frozen_before_application=record.get('oracle_frozen_before_application') is True,
            product_ready_false=record.get('PRODUCT_READY') is False)
    else:
        checks.update(kind=record.get('kind') == 'offline-product-check',
            development_passing=isinstance(record.get('development'), dict) and record['development'].get('state') == 'PASS',
            usage_unchanged=record.get('usage_before') == record.get('usage_after'))
    return checks


def main():
    before = source_manifest()
    assert head() == COMMIT and before['sha256'] == SOURCE
    originals = inputs()
    assert all(originals[str(path.relative_to(ROOT))]['sha256'] == expected for path, expected in ORIGINALS.items())
    (OUT / 'SOURCE_BEFORE.json').write_text(json.dumps(before, sort_keys=True, indent=2) + '\n')
    python = str(ROOT / '.venv/bin/python')
    plans = [('genuine-development', True, False, 0, 'WORKFLOW_PASS_REAL_ACCEPTANCE_BLOCKED'),
             ('genuine-real-acceptance', True, True, 2, 'BLOCKED'),
             ('product-development', False, False, 0, 'DEVELOPMENT_PASS'),
             ('product-real-acceptance', False, True, 2, 'BLOCKED')]
    index = {'kind': 'four-frozen-offline-entrypoints', 'state': 'INCOMPLETE',
        'commit': COMMIT, 'source_sha256': SOURCE, 'source_file_count': len(before['files']),
        'started_at': now(), 'inputs_before': originals, 'commands': [],
        'PRODUCT_READY': False, 'scope': 'Development workflow validation and explicit real-acceptance blockage; no full product-readiness claim.'}
    def save():
        (OUT / 'INDEX.json').write_text(json.dumps(index, sort_keys=True, indent=2) + '\n')
    save()
    for name, genuine, require_real, expected_exit, expected_state in plans:
        output = OUT / name
        if output.exists():
            raise ValueError('Each replay requires a fresh unique output directory: ' + name)
        tool = ROOT / 'tools' / ('check_genuine_collection.py' if genuine else 'check_product.py')
        command = [python, str(tool), '--output', str(output)]
        if genuine:
            command += ['--input', str(INPUT), '--input-freeze', str(FREEZE), '--worked-expectations', str(WORKED)]
        if require_real:
            command.append('--require-real-acceptance')
        start = time.monotonic()
        started = now()
        source_before = source_manifest()['sha256']
        commit_before = head()
        log = OUT / (name + '.log')
        with log.open('wb') as stream:
            result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False)
        finished = now()
        raw_receipt = (output / 'result.json').read_bytes()
        receipt = parse_json(raw_receipt)
        checks = receipt_checks(receipt, genuine=genuine, expected_state=expected_state)
        checks.update(expected_exit=result.returncode == expected_exit,
            exact_commit_before=commit_before == COMMIT, exact_commit_after=head() == COMMIT,
            exact_source_before=source_before == SOURCE, exact_source_after=source_manifest()['sha256'] == SOURCE,
            original_inputs_unchanged=inputs() == originals)
        record = {'name': name, 'command': command, 'started_at': started, 'finished_at': finished,
            'seconds': round(time.monotonic() - start, 6), 'exit_code': result.returncode,
            'expected_exit_code': expected_exit, 'receipt_state': receipt.get('state'),
            'real_acceptance_state': receipt.get('real_acceptance', {}).get('state'),
            'state': 'PASS_EXPECTED_REAL_BLOCK' if all(checks.values()) and require_real else 'PASS' if all(checks.values()) else 'FAILED',
            'checks': checks, 'log': str(log.relative_to(ROOT)), 'log_bytes': log.stat().st_size,
            'log_sha256': digest(log.read_bytes()), 'receipt': str((output / 'result.json').relative_to(ROOT)),
            'receipt_bytes': len(raw_receipt), 'receipt_sha256': digest(raw_receipt)}
        index['commands'].append(record)
        save()
        print(json.dumps({key: record[key] for key in ('name', 'exit_code', 'receipt_state', 'real_acceptance_state', 'state', 'seconds')}), flush=True)
        if not (checks['exact_commit_after'] and checks['exact_source_after'] and checks['original_inputs_unchanged']):
            index['halted_after_identity_change'] = True
            break
    after = source_manifest()
    (OUT / 'SOURCE_AFTER.json').write_text(json.dumps(after, sort_keys=True, indent=2) + '\n')
    index.update(finished_at=now(), source_unchanged=before == after, commit_unchanged=head() == COMMIT,
        inputs_after=inputs(), original_inputs_unchanged=inputs() == originals,
        state='PASS' if before == after and head() == COMMIT and inputs() == originals
            and len(index['commands']) == len(plans)
            and all(record['state'] in ('PASS', 'PASS_EXPECTED_REAL_BLOCK') for record in index['commands']) else 'FAILED')
    save()
    print(json.dumps({'state': index['state'], 'source_unchanged': index['source_unchanged'],
        'original_inputs_unchanged': index['original_inputs_unchanged'], 'PRODUCT_READY': False,
        'index': str((OUT / 'INDEX.json').relative_to(ROOT))}), flush=True)
    return 0 if index['state'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
