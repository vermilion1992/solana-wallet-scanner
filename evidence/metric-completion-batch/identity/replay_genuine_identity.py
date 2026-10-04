"""Offline genuine selected-record identity replay, never complete-wallet B3.

Retains the original 87-record indexed archive and worked arithmetic oracle.
Adds separately preserved original current-account request/response bytes to a
distinct ordinary archive; no original transaction or receipt is overwritten.
"""
from __future__ import annotations

from contextlib import ExitStack
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
import scanner.app as app_module
from scanner.archive_input import canonical_bytes, validate_manifest
from scanner.indexed_input import convert_indexed_archive
from scanner.wallet_identity import account_info_source

OUT = Path(__file__).resolve().parent
ORIGINAL = ROOT / 'evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip'
ORACLE = ROOT / 'evidence/genuine-wallet-batch/WORKED_REAL_EXPECTATIONS_FINAL.json'
ORIGINAL_SHA = 'eec702fdd821066897710d2085bf5c39380e303e8426249e22fb6379b7ccf1b4'
ORACLE_SHA = '97c9f92202398aef69ef0e2ce78f3d81ef67814187ca233ce5c36f8363cde9ba'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def derive_input():
    original = ORIGINAL.read_bytes()
    assert digest(original) == ORIGINAL_SHA
    assert digest(ORACLE.read_bytes()) == ORACLE_SHA
    ordinary = convert_indexed_archive(original)
    with zipfile.ZipFile(io.BytesIO(ordinary)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        payloads = {Path(name).name.removesuffix('.json.gz'): json.loads(gzip.decompress(archive.read(name)))
                    for name in archive.namelist() if name.startswith('archives/')}
    selected_before = canonical_bytes(manifest['transactions'])
    phase = ROOT / 'evidence/genuine-wallet-batch/collection/phase6'
    request = (phase / '01-current-wallet-account-request.json').read_bytes()
    response = gzip.decompress((phase / '01-current-wallet-account-response.raw.gz').read_bytes())
    envelope = account_info_source(request, response)
    identity_hash = digest(canonical_bytes(envelope))
    payloads[identity_hash] = envelope
    manifest['evidence'].append({'kind': 'wallet-account-info', 'hash': identity_hash})
    assert canonical_bytes(manifest['transactions']) == selected_before
    validate_manifest(manifest)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(zipfile.ZipInfo('manifest.json'), canonical_bytes(manifest))
        for key, payload in sorted(payloads.items()):
            archive.writestr(zipfile.ZipInfo(f'archives/{key}.json.gz'), gzip.compress(canonical_bytes(payload), mtime=0))
    raw = stream.getvalue()
    return raw, identity_hash, {'original_sha256': ORIGINAL_SHA, 'original_bytes': len(original),
        'oracle_sha256': ORACLE_SHA, 'selected_records': len(manifest['transactions']),
        'retained_selected_links_sha256': digest(selected_before),
        'account_request_sha256': digest(request), 'account_response_sha256': digest(response),
        'account_envelope_sha256': identity_hash, 'derived_input_sha256': digest(raw), 'derived_input_bytes': len(raw)}


def main():
    content, identity_hash, inputs = derive_input()
    (OUT / 'derived-genuine-account-input.zip').write_bytes(content)
    calls = []
    async def denied(*args, **kwargs):
        calls.append('provider-attempt')
        raise AssertionError('The genuine identity replay is offline')
    captures = {}
    with ExitStack() as stack:
        stack.enter_context(patch('httpx.AsyncClient.get', denied))
        stack.enter_context(patch('httpx.AsyncClient.post', denied))
        stack.enter_context(patch('scanner.providers.Gateway.rpc', denied))
        stack.enter_context(patch.object(app_module, 'Credentials', lambda *_: SimpleNamespace(key=None, storage='none', backend=None)))
        directory = stack.enter_context(tempfile.TemporaryDirectory(prefix='genuine-identity-api-'))
        app = app_module.create_app(directory, 'identity-genuine-replay-test')
        client = stack.enter_context(TestClient(app, base_url='http://127.0.0.1:8765'))
        csrf = client.get('/api/bootstrap', headers={'X-Launch-Token': 'identity-genuine-replay-test'}).json()['csrf']
        client.headers['X-CSRF-Token'] = csrf
        usage = client.get('/api/usage').json()
        response = client.post('/api/archives/import', content=content, headers={'content-type': 'application/zip'})
        assert response.status_code == 200, response.text
        parent_id = response.json()['report_id']
        parent_bytes = client.get(f'/api/export/reports/{parent_id}.json').content
        parent = json.loads(parent_bytes)
        parent_identity = parent['coverage']['wallet_evidence']['wallet_identity']
        assert parent_identity['state'] == parent_identity['current_account']['state'] == parent_identity['economic_signer']['state'] == 'PASS'
        assert parent_identity['historical_population_state'] == 'UNKNOWN'
        assert parent['metrics']['observed_network_fees_sol']['value'] == '0.000158868'
        assert parent['metrics']['profit_sol']['status'] == 'unknown'
        assert parent['qualification']['qualified'] is False
        assert client.get(f'/api/evidence/{identity_hash}').status_code == 200
        captures['parent'] = parent_bytes
        file = app.state.store.path / 'evidence' / f'{identity_hash}.json.gz'
        original_account = file.read_bytes()
        file.unlink()
        response = client.post(f'/api/reports/{parent_id}/rebuild')
        assert response.status_code == 200, response.text
        missing_id = response.json()['report_id']
        missing_bytes = client.get(f'/api/export/reports/{missing_id}.json').content
        missing = json.loads(missing_bytes)
        missing_identity = missing['coverage']['wallet_evidence']['wallet_identity']
        assert missing_identity['state'] == 'UNKNOWN'
        assert missing_identity['current_account']['state'] == 'UNKNOWN'
        assert missing_identity['economic_signer']['state'] == 'PASS'
        assert identity_hash in missing_identity['dependencies']
        assert missing['metrics']['observed_network_fees_sol']['value'] == '0.000158868'
        assert missing['archive_input_hash'] == parent['archive_input_hash']
        assert missing['preset'] == parent['preset'] and missing['window'] == parent['window']
        captures['missing_account_child'] = missing_bytes
        file.write_bytes(original_account)
        response = client.post(f'/api/reports/{parent_id}/rebuild')
        assert response.status_code == 200, response.text
        restored_id = response.json()['report_id']
        restored_bytes = client.get(f'/api/export/reports/{restored_id}.json').content
        restored = json.loads(restored_bytes)
        assert restored['coverage']['wallet_evidence']['wallet_identity'] == parent_identity
        assert restored['metrics'] == parent['metrics']
        assert restored['archive_input_hash'] == parent['archive_input_hash']
        assert client.get(f'/api/export/reports/{parent_id}.json').content == parent_bytes
        assert client.get('/api/usage').json() == usage
        csv = client.get(f'/api/export/reports/{restored_id}.csv').content
        assert b'0.000158868' in csv
        assert not calls
        captures['restored_account_child'] = restored_bytes
        captures['restored_export_csv'] = csv
    assert digest(ORIGINAL.read_bytes()) == ORIGINAL_SHA
    assert digest(ORACLE.read_bytes()) == ORACLE_SHA
    artifacts = {}
    for name, raw in captures.items():
        extension = '.csv' if name.endswith('_csv') else '.json'
        path = OUT / f'genuine-{name}{extension}.gz'
        path.write_bytes(gzip.compress(raw, mtime=0))
        artifacts[path.name] = {'compressed_bytes': path.stat().st_size, 'compressed_sha256': digest(path.read_bytes()),
                               'original_bytes': len(raw), 'original_sha256': digest(raw)}
    receipt = {'state': 'PASS', 'scope': 'Genuine current account and 16 selected supported economic signatures only; full wallet acceptance stays blocked.',
        'inputs': inputs, 'parent_identity_state': parent_identity['state'],
        'parent_economic_signature_count': len(parent_identity['transactions']),
        'historical_population_state': parent_identity['historical_population_state'],
        'missing_account_identity_state': missing_identity['state'], 'restoration_preserved_identity': True,
        'independent_fee_sol': '0.000158868', 'parent_unchanged': True,
        'provider_requests': 0, 'provider_attempts': len(calls), 'credential_lookups': 0,
        'credentials_adapter': 'Explicit no-key/no-backend replacement before app creation; original credential constructor never executes.',
        'product_ready': False, 'artifacts': artifacts,
        'sources': {str(path.relative_to(ROOT)): digest(path.read_bytes())
                    for path in (ROOT / 'scanner/wallet_identity.py', ROOT / 'tests/test_wallet_identity.py', Path(__file__))}}
    (OUT / 'genuine-api-replay.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': receipt['state'], 'selected': inputs['selected_records'],
        'economic_signatures': receipt['parent_economic_signature_count'], 'identity': receipt['parent_identity_state'],
        'historical_population': receipt['historical_population_state'], 'missing_account': receipt['missing_account_identity_state'],
        'independent_fee_sol': receipt['independent_fee_sol'], 'parent_unchanged': True, 'provider_requests': 0,
        'credential_lookups': 0, 'product_ready': False, 'receipt': str((OUT / 'genuine-api-replay.json').relative_to(ROOT))}))


if __name__ == '__main__':
    main()
