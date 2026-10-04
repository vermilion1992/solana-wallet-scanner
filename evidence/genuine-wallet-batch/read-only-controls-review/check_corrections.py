#!/usr/bin/env python3
"""Offline read-only replays of the two reported checker control defects."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import zipfile
import io

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import scanner.app as application
from tools.check_genuine_collection import digest, pack_collection, run


def main():
    collection = ROOT / 'evidence/genuine-wallet-batch/collection'
    directories = [collection / 'phase2', collection / 'phase3', collection / 'phase5']
    wallet = '2Bj3dZTSSc14hFR9fCLN9CQ1TiaYyszCKX8fuVG7pyAY'
    window = {'start': '2026-07-06T00:00:00+00:00', 'end': '2026-10-04T00:00:00+00:00'}
    before = {str(p.relative_to(ROOT)): digest(p.read_bytes())
              for directory in directories for p in directory.iterdir() if p.is_file()}
    content, acquisition = pack_collection(directories, wallet, window)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        for item in acquisition:
            for source in item['included_raw_sources']:
                for kind in ('request', 'response'):
                    raw = archive.read('raw/' + source[kind + '_hash'] + '.json')
                    assert digest(raw) == source[kind + '_hash']
            for source in item['auxiliary_raw_sources']:
                assert 'raw/' + source['response_hash'] + '.json' not in archive.namelist()
        assert len(manifest['pages']) == 2
    assert before == {str(p.relative_to(ROOT)): digest(p.read_bytes())
                      for directory in directories for p in directory.iterdir() if p.is_file()}
    mixed = {'case': 'mixed-public-and-native-frozen-phases', 'state': 'PASS',
             'financial_pages': len(manifest['pages']),
             'public_auxiliary_sources': sum(len(x['auxiliary_raw_sources']) for x in acquisition),
             'financial_admission_of_public_sources': False, 'original_files_unchanged': True}
    spec = importlib.util.spec_from_file_location('review_development_cases', ROOT / 'tests/test_genuine_collection_workflow.py')
    development = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(development)
    content = development.archive([development.page([development.record()])])
    cases = [mixed]
    original = application.create_app
    for kind in ('provider', 'credential'):
        def hook(*args, **kwargs):
            import httpx
            import keyring
            try:
                if kind == 'provider':
                    httpx.Client().get('https://example.invalid/blocked-offline-review')
                else:
                    keyring.get_password('review-development-only', 'denied')
            except AssertionError:
                pass
            return original(*args, **kwargs)
        with tempfile.TemporaryDirectory(prefix='checker-read-only-controls-') as temporary:
            output = Path(temporary) / 'run'
            with patch.object(application, 'create_app', hook):
                try:
                    run(content, output)
                except AssertionError:
                    rejected = True
                else:
                    rejected = False
            receipt = json.loads((output / 'result.json').read_bytes())
            assert rejected and receipt['state'] == 'FAILED' and receipt['PRODUCT_READY'] is False
            assert receipt['provider_requests'] == (1 if kind == 'provider' else 0)
            assert receipt['credential_lookups'] == (1 if kind == 'credential' else 0)
            cases.append({'case': 'swallowed-' + kind + '-guard-rejects-workflow', 'state': 'PASS',
                          'workflow_state': receipt['state'], 'provider_attempts': receipt['provider_requests'],
                          'credential_attempts': receipt['credential_lookups'],
                          'actual_external_requests': 0, 'actual_credential_reads': 0})
    result = {'kind': 'read-only-checker-correction-replay-v1', 'state': 'PASS',
              'checker_sha256': digest((ROOT / 'tools/check_genuine_collection.py').read_bytes()),
              'collector_sha256': digest((ROOT / 'tools/bounded_collection.py').read_bytes()),
              'cases': cases, 'dispatches_in_review': 0, 'credential_reads_in_review': 0,
              'scope': 'Acquisition packaging and offline validator controls; no new genuine application acceptance.',
              'PRODUCT_READY': False}
    output = Path(__file__).with_name('CORRECTION_REPLAY.json')
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'state': result['state'], 'cases': len(cases),
                      'receipt': str(output.relative_to(ROOT)), 'sha256': digest(output.read_bytes())}))


if __name__ == '__main__':
    main()
