"""Normal indexed import/report/rebuild controls; genuine sample stays partial.

Low-volume native records are unsigned development fixtures. The one genuine
case reads exact authorized archived request/response bytes without network I/O.
"""
import base64
from copy import deepcopy
import csv
import gzip
import hashlib
import io
import json
import sys
from types import SimpleNamespace
import zipfile

import httpx
import pytest

from scanner.archive_input import canonical_bytes, load_archive
from scanner.indexed_input import source_bytes
from tests.test_discovery_integration_review import session, isolate_credentials_and_transport
from tests.test_indexed_input import WALLET, WINDOW, PROBE, native, page, upload, digest


@pytest.fixture
def guarded(session, monkeypatch):
    client, app, directory = session
    calls = {'provider': 0, 'credential': 0, 'transport': 0}

    async def no_provider(*args, **kwargs):
        calls['provider'] += 1
        raise AssertionError('Indexed import/rebuild must not call a provider')

    async def no_transport(*args, **kwargs):
        calls['transport'] += 1
        raise AssertionError('Indexed import/rebuild must not use external HTTP transport')

    def no_credential(*args, **kwargs):
        calls['credential'] += 1
        raise AssertionError('Indexed import/rebuild must not retrieve a credential')

    monkeypatch.setattr('scanner.providers.Gateway.rpc', no_provider)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', no_transport)
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(get_keyring=lambda: object(), get_password=no_credential))
    usage = deepcopy(client.get('/api/usage').json())
    yield client, app, directory, calls
    assert calls == {'provider': 0, 'credential': 0, 'transport': 0}
    assert client.get('/api/usage').json() == usage


def import_report(client, content):
    response = client.post('/api/archives/import', content=content, headers={'Content-Type': 'application/zip'})
    assert response.status_code == 200, response.text
    imported = response.json()
    assert imported['dataset'] == 'real' and imported['provider_requests'] == 0
    report = client.get('/api/reports/' + imported['report_id'])
    assert report.status_code == 200, report.text
    return report.json()


def rebuild(client, report):
    response = client.post('/api/reports/' + report['id'] + '/rebuild')
    assert response.status_code == 200, response.text
    child = client.get('/api/reports/' + response.json()['report_id']).json()
    assert child['id'] != report['id'] and child['rebuilt_from'] == report['id']
    assert child['window'] == report['window'] and child['preset'] == report['preset']
    assert child['rebuild']['provider_requests'] == 0
    return child


def fee(report):
    return report['metrics']['observed_network_fees_sol']


def assert_partial(report):
    assert report['metrics']['profit_sol']['status'] == 'unknown'
    assert report['metrics']['profit_sol']['value'] is None
    assert report['qualification']['qualified'] is False
    assert report['coverage']['indexed_sources']['historical_population'] == 'UNKNOWN'


def page_hashes(store, report):
    manifest = store.evidence(report['archive_input_hash'])
    return [row['hash'] for row in manifest['evidence'] if row['kind'] == 'indexed-page']


def alternate(signature, *, fee_value=5000, malformed=False):
    record = native(signature, fee=fee_value)
    if malformed:
        record['meta'] = []
    request = json.dumps({'jsonrpc': '2.0', 'id': 45, 'method': 'getTransaction',
                         'params': [signature, {'encoding': 'json', 'commitment': 'finalized',
                                                'maxSupportedTransactionVersion': 0}]}, indent=1).encode()
    response = json.dumps({'jsonrpc': '2.0', 'id': 45, 'result': record}, indent=1).encode()
    return signature, request, response


def test_normal_indexed_import_source_inspection_exports_and_immutable_offline_rebuild(guarded):
    client, app, _, _ = guarded
    request, response = page()
    _, _, content = upload([(request, response)])
    report = import_report(client, content)
    parent = deepcopy(app.state.store.get('reports', report['id']))
    assert_partial(report)
    assert fee(report)['status'] == 'known' and fee(report)['value'] == '0.000005'
    selected = app.state.store.evidence(report['archive_input_hash'])['transactions']
    assert {(row['signature'], row['hash']) for row in selected} <= {
        (row['signature'], row['evidence_hash']) for row in report['coverage']['indexed_record_sources']}
    source = client.get('/api/evidence/' + page_hashes(app.state.store, report)[0])
    assert source.status_code == 200
    assert source_bytes(source.json()) == {'request': request, 'response': response}
    json_export = client.get('/api/export/reports/' + report['id'] + '.json')
    csv_export = client.get('/api/export/reports/' + report['id'] + '.csv')
    assert json_export.status_code == csv_export.status_code == 200
    assert json_export.json()['metrics'] == report['metrics']
    csv_rows = {row['metric']: row for row in csv.DictReader(io.StringIO(csv_export.text))}
    assert csv_rows['observed_network_fees_sol']['value'] == '0.000005'
    assert csv_rows['profit_sol']['status'] == 'unknown'
    child = rebuild(client, report)
    assert child['metrics'] == report['metrics']
    assert app.state.store.get('reports', report['id']) == parent


@pytest.mark.parametrize('loss', ['missing-page', 'corrupt-page', 'missing-pointer'])
def test_required_byte_source_or_selected_pointer_loss_revokes_fee_then_exact_restore_recovers(guarded, loss):
    client, app, directory, _ = guarded
    _, _, content = upload([page()])
    report = import_report(client, content)
    parent = deepcopy(app.state.store.get('reports', report['id']))
    manifest = app.state.store.evidence(report['archive_input_hash'])
    identifier = manifest['transactions'][0]['hash'] if loss == 'missing-pointer' else page_hashes(app.state.store, report)[0]
    path = directory / 'evidence' / f'{identifier}.json.gz'
    original = path.read_bytes()
    if loss == 'corrupt-page':
        path.write_bytes(b'corrupt gzip byte envelope')
    else:
        path.unlink()
    child = rebuild(client, report)
    assert fee(child)['status'] == 'unknown' and fee(child)['value'] is None
    assert_partial(child)
    assert app.state.store.get('reports', report['id']) == parent
    # Restoring exact bytes must recover a fresh child, without editing either
    # the accepted parent or the dependency-loss report.
    loss_child = deepcopy(app.state.store.get('reports', child['id']))
    path.write_bytes(original)
    restored = rebuild(client, child)
    assert restored['metrics'] == report['metrics']
    assert app.state.store.get('reports', report['id']) == parent
    assert app.state.store.get('reports', child['id']) == loss_child


@pytest.mark.parametrize('variant', ['fee-conflict', 'malformed-native', 'missing-native-bytes'])
def test_linked_native_alternative_cannot_disappear_from_required_fee_dependencies(guarded, variant):
    client, app, _, _ = guarded
    signature = native()['transaction']['signatures'][0]
    alternative = alternate(signature, fee_value=6000 if variant == 'fee-conflict' else 5000,
                            malformed=variant == 'malformed-native')
    omitted = [digest(alternative[2])] if variant == 'missing-native-bytes' else []
    _, _, content = upload([page()], alternatives=[alternative], omit=omitted)
    report = import_report(client, content)
    assert_partial(report)
    assert fee(report)['status'] == 'unknown' and fee(report)['value'] is None
    before = deepcopy(app.state.store.get('reports', report['id']))
    child = rebuild(client, report)
    assert fee(child)['status'] == 'unknown'
    assert app.state.store.get('reports', report['id']) == before


def test_manifest_page_permutation_duplicate_links_and_independent_source_bytes_do_not_change_narrow_results(guarded):
    client, _, _, _ = guarded
    pages = [page(outgoing='1:0'), page([native('indexed-b', slot=2)], incoming='1:0', ident=2)]
    _, _, first = upload(pages)
    _, _, reversed_content = upload(list(reversed(pages)))
    _, _, duplicate = upload(pages + [pages[0]])
    reports = [import_report(client, content) for content in (first, reversed_content, duplicate)]
    assert all(fee(report)['value'] == '0.00001' and fee(report)['status'] == 'known' for report in reports)
    assert all(report['metrics'] == reports[0]['metrics'] for report in reports)
    assert all(report['coverage']['indexed_sources']['historical_population'] == 'UNKNOWN' for report in reports)


@pytest.mark.parametrize('field', ['history_complete', 'positions', 'events', 'transaction_index'])
def test_caller_completion_and_canonical_index_declarations_are_rejected_at_normal_api(guarded, field):
    client, app, _, _ = guarded
    manifest, inputs, _ = upload([page()])
    manifest[field] = True
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('manifest.json', canonical_bytes(manifest))
        for identifier, raw in inputs.items():
            archive.writestr(f'raw/{identifier}.json', raw)
    before = deepcopy(app.state.store.list('reports'))
    response = client.post('/api/archives/import', content=stream.getvalue(), headers={'Content-Type': 'application/zip'})
    assert response.status_code == 422, response.text
    assert app.state.store.list('reports') == before


def test_genuine_authorized_two_pages_reach_normal_report_with_exact_independent_fee_sum_and_no_profit_claim(guarded):
    client, app, _, _ = guarded
    pages = [(PROBE.joinpath(stem + '-request.json').read_bytes(),
              gzip.decompress(PROBE.joinpath(stem + '-response.raw.gz').read_bytes()))
             for stem in ('02-all-index', '03-all-continuation')]
    byte_hashes = [(hashlib.sha256(request).hexdigest(), hashlib.sha256(response).hexdigest()) for request, response in pages]
    # Independently worked from original raw inputs, before production import.
    raw_records = [raw for _, response in pages for raw in json.loads(response)['result']['data']]
    assert len(raw_records) == len({raw['transaction']['signatures'][0] for raw in raw_records}) == 200
    assert sum(raw['meta']['err'] is not None for raw in raw_records) == 184
    direct_fee_sum = sum(raw['meta']['fee'] for raw in raw_records
                         if raw['transaction']['message']['accountKeys'][0] == WALLET)
    assert direct_fee_sum == 8_904_733
    _, _, content = upload(pages)
    report = import_report(client, content)
    assert_partial(report)
    assert fee(report)['status'] == 'known' and fee(report)['value'] == '0.008904733'
    assert report['coverage']['indexed_sources']['state'] == 'UNKNOWN'
    manifest = app.state.store.evidence(report['archive_input_hash'])
    selected = {(row['signature'], row['hash']) for row in manifest['transactions']}
    assert len(selected) == 200
    assert selected <= {(row['signature'], row['evidence_hash'])
                        for row in report['coverage']['indexed_record_sources']}
    assert not any(event['kind'] in ('buy', 'sell') for event in report['events'])
    assert len([event for event in report['events'] if event['kind'] == 'fee']) == 200
    loaded = load_archive(app.state.store, report['archive_input_hash'],
                          dependency_input_hash=report['archive_dependency_input_hash'])
    assert len(loaded['records']) == 200
    assert {row['signature']: row['raw'] for row in loaded['records']} == {
        raw['transaction']['signatures'][0]: raw for raw in raw_records}
    saved_bytes = [source_bytes(app.state.store.evidence(identifier)) for identifier in page_hashes(app.state.store, report)]
    assert {(hashlib.sha256(raw['request']).hexdigest(), hashlib.sha256(raw['response']).hexdigest())
            for raw in saved_bytes} == set(byte_hashes)
    before = deepcopy(app.state.store.get('reports', report['id']))
    child = rebuild(client, report)
    assert child['metrics'] == report['metrics']
    assert_partial(child)
    assert app.state.store.get('reports', report['id']) == before


def test_indexed_cli_packs_exact_raw_bytes_and_preserves_missing_links(tmp_path):
    from tools.archive_input import pack_indexed
    manifest, inputs, _ = upload([page()])
    manifest_path = tmp_path / 'manifest.json'
    raw_dir = tmp_path / 'raw'
    raw_dir.mkdir()
    manifest_path.write_bytes(json.dumps(manifest, indent=1).encode())
    for identifier, payload in inputs.items():
        (raw_dir / f'{identifier}.json').write_bytes(payload)
    full_output = tmp_path / 'full.zip'
    pack_indexed(manifest_path, raw_dir, full_output)
    with zipfile.ZipFile(full_output) as archive:
        assert json.loads(archive.read('manifest.json')) == manifest
        assert {identifier: archive.read(f'raw/{identifier}.json') for identifier in inputs} == inputs
    missing = manifest['pages'][0]['response_hash']
    (raw_dir / f'{missing}.json').unlink()
    partial_output = tmp_path / 'missing.zip'
    pack_indexed(manifest_path, raw_dir, partial_output)
    with zipfile.ZipFile(partial_output) as archive:
        assert json.loads(archive.read('manifest.json')) == manifest
        assert f'raw/{missing}.json' not in archive.namelist()
        assert manifest['pages'][0]['response_hash'] == missing


def test_indexed_cli_rejects_symlink_escape_before_writing_output(tmp_path):
    from tools.archive_input import pack_indexed
    manifest, inputs, _ = upload([page()])
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_bytes(canonical_bytes(manifest))
    raw_dir = tmp_path / 'raw'
    raw_dir.mkdir()
    identifier = manifest['pages'][0]['request_hash']
    outside = tmp_path / 'outside.json'
    outside.write_bytes(inputs[identifier])
    (raw_dir / f'{identifier}.json').symlink_to(outside)
    output = tmp_path / 'escaped.zip'
    with pytest.raises(ValueError, match='regular file'):
        pack_indexed(manifest_path, raw_dir, output)
    assert not output.exists()
    assert outside.read_bytes() == inputs[identifier]
