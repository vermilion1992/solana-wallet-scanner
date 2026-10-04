"""Indexed byte ingestion controls: local conformance, not genuine B3 acceptance."""
import base64
from copy import deepcopy
import gzip
import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest

from scanner.archive_input import canonical_bytes, import_archive
from scanner.indexed_input import (VERSION, PAGE_VERSION, RECORD_VERSION, MANIFEST_VERSION,
    IndexedResolver, archive_version, convert_indexed_archive, describe_pages, manifest_bytes, pack_indexed_bytes,
    resolve_record, source_bytes, source_records, validate_manifest, validate_page_envelope)
from scanner.storage import Store

WALLET = '2QfBNK2WDwSLoUQRb1zAnp3KM12N9hQ8q6ApwUMnWW2T'
WINDOW = {'start': '2026-07-04T00:00:00+00:00', 'end': '2026-10-02T00:00:00+00:00'}
PROBE = Path(__file__).resolve().parents[1] / 'evidence/source-probe-2026-10-04/live'
INDEX_REFERENCE = Path(__file__).resolve().parents[1] / 'evidence/references/product-milestone/helius-index-markdown.txt'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def native(signature='indexed-a', *, fee=5000, slot=1, index=0, when=1783175556):
    return {'transaction': {'signatures': [signature], 'message': {'accountKeys': [WALLET], 'instructions': []}},
            'meta': {'err': {'InstructionError': [0, 'Custom']}, 'fee': fee, 'preBalances': [10000000],
                     'postBalances': [10000000-fee], 'preTokenBalances': [], 'postTokenBalances': [],
                     'innerInstructions': [], 'loadedAddresses': {'writable': [], 'readonly': []}},
            'version': 0, 'slot': slot, 'transactionIndex': index, 'blockTime': when}


def page(records=None, *, incoming=None, outgoing=None, ident=1, options=None):
    opts = {'transactionDetails': 'full', 'limit': 100, 'sortOrder': 'asc', 'commitment': 'finalized',
            'maxSupportedTransactionVersion': 1, 'filters': {'status': 'any', 'tokenAccounts': 'all',
            'blockTime': {'gte': 1783175556, 'lt': 1790951556}}}
    opts.update(options or {})
    if incoming is not None:
        opts['paginationToken'] = incoming
    request = {'jsonrpc': '2.0', 'id': ident, 'method': 'getTransactionsForAddress', 'params': [WALLET, opts]}
    response = {'jsonrpc': '2.0', 'id': ident, 'result': {'data': records if records is not None else [native()], 'paginationToken': outgoing}}
    # Deliberately noncanonical serialization demonstrates exact byte retention.
    return json.dumps(request, indent=2).encode()+b'\n', json.dumps(response, indent=1).encode()+b'\n'


def upload(pages, *, alternatives=(), omit=()):
    manifest = {'version': VERSION, 'address': WALLET, 'window': WINDOW, 'pages': [], 'transactions': []}
    raw_inputs = {}
    for request, response in pages:
        manifest['pages'].append({'request_hash': digest(request), 'response_hash': digest(response)})
        raw_inputs[digest(request)] = request
        raw_inputs[digest(response)] = response
    for signature, request, response in alternatives:
        manifest['transactions'].append({'signature': signature, 'request_hash': digest(request), 'response_hash': digest(response)})
        raw_inputs[digest(request)] = request
        raw_inputs[digest(response)] = response
    for identifier in omit:
        raw_inputs.pop(identifier, None)
    return manifest, raw_inputs, pack_indexed_bytes(manifest, raw_inputs)


def unpack(content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        payloads = {Path(name).name.removesuffix('.json.gz'): json.loads(gzip.decompress(archive.read(name)))
                    for name in archive.namelist() if name.startswith('archives/')}
    return manifest, payloads


def resolve_all(manifest, payloads):
    links = manifest['transactions'] + [ref for ref in manifest['evidence'] if ref['kind'] == 'transaction']
    resolver = IndexedResolver(lambda identifier, role: payloads.get(identifier), address=WALLET)
    return [resolver.resolve(payloads[row['hash']]) for row in links]


def sources(manifest, payloads):
    return [{'hash': row['hash'], 'payload': payloads.get(row['hash'])}
            for row in manifest['evidence'] if row['kind'] == 'indexed-page']


@pytest.mark.parametrize('encoding', ['json', 'jsonParsed'])
def test_pinned_provider_json_encodings_accept_archived_compiled_and_parsed_shapes_exactly(encoding):
    # Independent API reference downloaded 3 October, including JSON default;
    # the accepted values are not copied from the implementation's allowlist.
    reference = INDEX_REFERENCE.read_bytes()
    assert digest(reference) == '9dbb7415eb7389752ed7f0a0601983bd73bd0d32ff14f0d4e3b61a1e2aa6acec'
    excerpt = reference.decode().split('                          encoding:', 1)[1].split('                          maxSupportedTransactionVersion:', 1)[0]
    assert '- json\n' in excerpt and '- jsonParsed\n' in excerpt and 'default: json' in excerpt
    if encoding == 'json':
        request = json.loads((PROBE / '02-all-index-request.json').read_bytes())
        response_bytes = gzip.decompress((PROBE / '02-all-index-response.raw.gz').read_bytes())
        wallet = request['params'][0]
        request['params'][1]['encoding'] = encoding
    else:
        # Genuine archived parsed buy proves accountKeys/instruction shape. Its
        # added indexed ordinal is a development envelope, never chain coverage.
        fixture_path = Path(__file__).resolve().parent / 'fixtures/mainnet-pumpswap-buy-exact-quote.json'
        fixture = json.loads(fixture_path.read_bytes())
        raw = deepcopy(fixture['raw'])
        wallet = raw['transaction']['message']['accountKeys'][0]['pubkey']
        raw['transactionIndex'] = 0
        request = {'jsonrpc': '2.0', 'id': 'parsed-schema-control', 'method': 'getTransactionsForAddress', 'params': [wallet, {'transactionDetails': 'full', 'encoding': encoding, 'limit': 100, 'sortOrder': 'asc', 'commitment': 'finalized', 'maxSupportedTransactionVersion': 1, 'filters': {'status': 'any', 'tokenAccounts': 'all', 'blockTime': {'gte': 1783175556, 'lt': 1791072000}}}]}
        response_bytes = json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': {'data': [raw], 'paginationToken': None}}, indent=2).encode() + b'\n'
    request_bytes = json.dumps(request, indent=2).encode() + b'\n'
    manifest = {'version': VERSION, 'address': wallet, 'window': {'start': '2026-07-04T00:00:00Z', 'end': '2026-10-04T00:00:00Z'}, 'pages': [{'request_hash': digest(request_bytes), 'response_hash': digest(response_bytes)}], 'transactions': []}
    content = pack_indexed_bytes(manifest, {digest(request_bytes): request_bytes, digest(response_bytes): response_bytes})
    ordinary, payloads = unpack(convert_indexed_archive(content))
    source = sources(ordinary, payloads)[0]
    assert source_bytes(source['payload']) == {'request': request_bytes, 'response': response_bytes}
    receipt = validate_page_envelope(source['payload'], wallet)
    assert receipt['state'] == 'PASS' and receipt['request_scope']['encoding'] == encoding
    resolver = IndexedResolver(lambda h, role: payloads.get(h), address=wallet)
    pointer = payloads[ordinary['transactions'][0]['hash']]
    selected = resolver.resolve(pointer)
    assert selected['state'] == 'PASS' and selected['raw'] == json.loads(response_bytes)['result']['data'][pointer['ordinal']]
    assert describe_pages([source], wallet, manifest['window'])['historical_population'] == 'UNKNOWN'


@pytest.mark.parametrize('encoding', ['base64', 'base58', None, False, {}])
def test_unimplemented_binary_or_malformed_encoding_keeps_exact_bytes_and_negative_record_dependencies(encoding):
    request, response = page(options={'encoding': encoding})
    ordinary, payloads = unpack(convert_indexed_archive(upload([(request, response)])[2]))
    source = sources(ordinary, payloads)[0]
    rejected = validate_page_envelope(source['payload'], WALLET)
    assert rejected['state'] == 'UNKNOWN' and 'encoding is unsupported' in rejected['reason']
    assert source_bytes(source['payload']) == {'request': request, 'response': response}
    assert resolve_all(ordinary, payloads)[0]['state'] == 'UNKNOWN'
    assert describe_pages([source], WALLET, WINDOW)['state'] == 'UNKNOWN'


def test_default_and_explicit_json_share_cursor_scope_but_parsed_encoding_remains_separate():
    first = page(outgoing='1:0')
    second = page([native('indexed-b', slot=2)], incoming='1:0', ident=2, options={'encoding': 'json'})
    ordinary, payloads = unpack(convert_indexed_archive(upload([first, second])[2]))
    described = describe_pages(sources(ordinary, payloads), WALLET, WINDOW)
    assert described['state'] == 'PASS'
    assert all(row['request_scope']['encoding'] == 'json' for row in described['pages'])
    parsed_second = page([native('indexed-b', slot=2)], incoming='1:0', ident=2, options={'encoding': 'jsonParsed'})
    ordinary, payloads = unpack(convert_indexed_archive(upload([first, parsed_second])[2]))
    described = describe_pages(sources(ordinary, payloads), WALLET, WINDOW)
    assert described['state'] == 'UNKNOWN' and described['historical_population'] == 'UNKNOWN'
    assert all(record['state'] == 'PASS' for record in resolve_all(ordinary, payloads))


def test_exact_request_response_and_uploaded_manifest_bytes_survive_normal_archive_import(tmp_path):
    request, response = page()
    _, _, content = upload([(request, response)])
    ordinary, payloads = unpack(convert_indexed_archive(content))
    source = payloads[sources(ordinary, payloads)[0]['hash']]
    assert source_bytes(source) == {'request': request, 'response': response}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        original = archive.read('manifest.json')
    frozen = next(p for p in payloads.values() if p['version'] == MANIFEST_VERSION)
    assert manifest_bytes(frozen) == original
    assert ordinary['dataset'] == 'real' and 'world_hash' not in ordinary
    store = Store(tmp_path)
    identifier = import_archive(store, convert_indexed_archive(content))
    assert store.evidence(identifier) == ordinary
    for h, payload in payloads.items():
        assert store.evidence(h) == payload
    record = resolve_all(ordinary, payloads)[0]
    assert record['state'] == 'PASS' and record['raw'] == native()
    assert record['raw']['transactionIndex'] == 0 and 'transaction_index' not in record
    assert record['raw_paths'] == ['result.data.0']


def test_pagination_topology_pass_is_not_historical_population_or_wallet_completion():
    _, _, content = upload([page(outgoing='1:0'), page([native('indexed-b', slot=2)], incoming='1:0', ident=2)])
    manifest, payloads = unpack(convert_indexed_archive(content))
    described = describe_pages(sources(manifest, payloads), WALLET, WINDOW)
    assert described['state'] == 'PASS' and described['historical_population'] == 'UNKNOWN'
    assert all(r['state'] == 'PASS' for r in resolve_all(manifest, payloads))
    assert len(manifest['transactions']) == 2


@pytest.mark.parametrize('variant', ['nonterminal', 'missing-predecessor', 'cursor-cycle', 'disconnected-cycle', 'conflicting-cursor'])
def test_cursor_gaps_and_conflicts_are_explicit_without_invented_collector_ancestry(variant):
    pages = [page()]
    if variant == 'nonterminal': pages = [page(outgoing='1:0')]
    if variant == 'missing-predecessor': pages = [page(incoming='9:0')]
    if variant == 'cursor-cycle': pages = [page(outgoing='1:0'), page([native('indexed-b')], incoming='1:0', outgoing='1:0', ident=2)]
    if variant == 'disconnected-cycle': pages += [page([native('indexed-b')], incoming='10:0', outgoing='11:0', ident=2), page([native('indexed-c')], incoming='11:0', outgoing='10:0', ident=3)]
    if variant == 'conflicting-cursor': pages += [page([native('indexed-b')], ident=2)]
    _, _, content = upload(pages)
    manifest, payloads = unpack(convert_indexed_archive(content))
    described = describe_pages(sources(manifest, payloads), WALLET, WINDOW)
    assert described['state'] == 'UNKNOWN' and described['gaps']
    assert described['historical_population'] == 'UNKNOWN'
    assert all(ref['kind'] not in ('signature-page', 'block-order') for ref in manifest['evidence'])


def test_duplicate_records_link_alternatives_but_selected_population_is_not_doubled():
    _, _, content = upload([page(), page(ident=2)])
    manifest, payloads = unpack(convert_indexed_archive(content))
    assert len(manifest['transactions']) == 1
    alternatives = [r for r in manifest['evidence'] if r['kind'] == 'transaction']
    assert len(alternatives) == 1
    resolved = resolve_all(manifest, payloads)
    assert len(resolved) == 2 and all(r['raw'] == native() for r in resolved)


def test_page_order_permutation_does_not_choose_a_different_selected_record():
    pages = [page(), page([native(fee=6000)], ident=2)]
    manifests = [unpack(convert_indexed_archive(upload(rows)[2]))[0] for rows in (pages, list(reversed(pages)))]
    assert manifests[0]['transactions'] == manifests[1]['transactions']
    assert [r for r in manifests[0]['evidence'] if r['kind'] == 'transaction'] == [r for r in manifests[1]['evidence'] if r['kind'] == 'transaction']


@pytest.mark.parametrize('loss', ['missing', 'corrupt', 'substitute', 'pointer-extra-field', 'ordinal', 'signature', 'native-hash'])
def test_frozen_source_loss_or_pointer_tampering_revokes_native_record_and_exact_restoration_recovers(loss):
    _, _, content = upload([page()])
    manifest, payloads = unpack(convert_indexed_archive(content))
    pointer = deepcopy(payloads[manifest['transactions'][0]['hash']])
    original = deepcopy(payloads)
    source_hash = pointer['source_hash']
    if loss == 'missing': payloads.pop(source_hash)
    if loss == 'corrupt': payloads[source_hash]['response_base64'] = base64.b64encode(b'{}').decode()
    if loss == 'substitute': payloads[source_hash]['response_hash'] = 'a'*64
    if loss == 'pointer-extra-field': pointer['history_complete'] = True
    if loss == 'ordinal': pointer['ordinal'] = True
    if loss == 'signature': pointer['signature'] = 'other-signature'
    if loss == 'native-hash': pointer['native_hash'] = 'a'*64
    broken = resolve_record(pointer, lambda h, role: payloads.get(h), address=WALLET)
    assert broken['state'] == 'UNKNOWN' and broken['raw'] is None
    assert resolve_all(manifest, original)[0]['raw'] == native()


def test_missing_linked_page_bytes_stay_in_the_manifest_and_receipt():
    first, second = page(), page([native('indexed-b')], incoming='1:0', ident=2)
    _, _, content = upload([first, second], omit=[digest(second[1])])
    manifest, payloads = unpack(convert_indexed_archive(content))
    assert len(sources(manifest, payloads)) == 2 and len(manifest['transactions']) == 1
    described = describe_pages(sources(manifest, payloads), WALLET, WINDOW)
    assert described['state'] == 'UNKNOWN' and any('missing' in gap for gap in described['gaps'])
    assert resolve_all(manifest, payloads)[0]['state'] == 'PASS'


@pytest.mark.parametrize('variant', ['unassignable', 'bad-meta', 'bad-cursor', 'extra-result', 'duplicate-signature', 'bad-request'])
def test_malformed_sibling_entries_and_page_metadata_remain_visible_dependencies(variant):
    request, response = page()
    parsed = json.loads(response)
    if variant == 'unassignable': parsed['result']['data'].append({'transaction': {'signatures': []}})
    if variant == 'bad-meta': parsed['result']['data'].append(native('indexed-b')); parsed['result']['data'][1]['meta'] = []
    if variant == 'bad-cursor': parsed['result']['paginationToken'] = []
    if variant == 'extra-result': parsed['result']['caller_complete'] = True
    if variant == 'duplicate-signature': parsed['result']['data'].append(native(fee=6000))
    if variant == 'bad-request': req = json.loads(request); req['params'][1]['transactionDetails'] = 'signatures'; request = json.dumps(req).encode()
    response = json.dumps(parsed).encode()
    _, _, content = upload([(request, response)])
    manifest, payloads = unpack(convert_indexed_archive(content))
    page_receipt = validate_page_envelope(sources(manifest, payloads)[0]['payload'], WALLET)
    assert page_receipt['state'] == 'UNKNOWN' and page_receipt['records']
    assert describe_pages(sources(manifest, payloads), WALLET, WINDOW)['state'] == 'UNKNOWN'
    if variant == 'unassignable': assert page_receipt['unassignable_records'] == [1]
    if variant == 'bad-meta': assert len(manifest['transactions']) == 2
    if variant == 'duplicate-signature': assert any(r['kind'] == 'transaction' for r in manifest['evidence'])
    if variant == 'bad-request': assert resolve_all(manifest, payloads)[0]['raw'] is None


def test_native_gettransaction_alternative_is_exact_preserved_and_compared_as_a_link():
    request = json.dumps({'jsonrpc': '2.0', 'id': 4, 'method': 'getTransaction',
        'params': ['indexed-a', {'encoding': 'jsonParsed', 'commitment': 'finalized', 'maxSupportedTransactionVersion': 1}]}).encode()
    response = json.dumps({'jsonrpc': '2.0', 'id': 4, 'result': native(fee=6000)}).encode()
    _, _, content = upload([page()], alternatives=[('indexed-a', request, response)])
    manifest, payloads = unpack(convert_indexed_archive(content))
    rows = resolve_all(manifest, payloads)
    assert {r['raw']['meta']['fee'] for r in rows} == {5000, 6000}
    assert len(manifest['transactions']) == 1 and len([r for r in manifest['evidence'] if r['kind'] == 'transaction']) == 1


@pytest.mark.parametrize('field', ['complete', 'history_complete', 'positions', 'events', 'coverage', 'world_hash'])
def test_caller_trusted_completion_or_normalized_financial_declarations_are_rejected(field):
    manifest, _, _ = upload([page()])
    manifest[field] = True
    with pytest.raises(ValueError, match='strict'): validate_manifest(manifest)


@pytest.mark.parametrize('name', ['../outside.json', '/absolute.json', 'raw/../outside.json', 'raw/not-a-hash.json'])
def test_archive_paths_are_validated_before_any_input_is_converted(name):
    manifest, _, _ = upload([page()])
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('manifest.json', canonical_bytes(manifest))
        archive.writestr(name, b'{}')
    with pytest.raises(ValueError, match='hash-named'): convert_indexed_archive(stream.getvalue())


def test_duplicate_json_keys_and_wrong_raw_hash_and_unlinked_inputs_rejected():
    manifest, raw_inputs, _ = upload([page()])
    for bad in ('duplicate-json', 'hash', 'unlinked'):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            raw_manifest = canonical_bytes(manifest)
            if bad == 'duplicate-json': raw_manifest = raw_manifest[:-1]+b',"version":"indexed-wallet-input-v1"}'
            archive.writestr('manifest.json', raw_manifest)
            for h, raw in raw_inputs.items(): archive.writestr(f'raw/{h}.json', b'{}' if bad == 'hash' else raw)
            if bad == 'unlinked': archive.writestr(f'raw/{digest(b"{}")}'+'.json', b'{}')
        with pytest.raises(ValueError): convert_indexed_archive(stream.getvalue())


def test_compressed_expansion_and_record_inspection_budgets_are_enforced(monkeypatch):
    import scanner.indexed_input as module
    _, _, content = upload([page()])
    monkeypatch.setattr(module, 'MAX_RAW', 10)
    with pytest.raises(ValueError, match='oversized'): convert_indexed_archive(content)
    monkeypatch.setattr(module, 'MAX_RAW', 24*1024*1024)
    monkeypatch.setattr(module, 'MAX_LINKS', 1)
    _, _, content = upload([page([native(), native('indexed-b')])])
    with pytest.raises(ValueError, match='budget'): convert_indexed_archive(content)


def test_genuine_two_pages_preserved_and_200_selected_records_resolve_without_live_io(monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('offline input conversion attempted network'))
    pages = [(PROBE.joinpath(name+'-request.json').read_bytes(), gzip.decompress(PROBE.joinpath(name+'-response.raw.gz').read_bytes()))
             for name in ('02-all-index', '03-all-continuation')]
    _, _, content = upload(pages)
    manifest, payloads = unpack(convert_indexed_archive(content))
    rows = resolve_all(manifest, payloads)
    assert len(rows) == len(manifest['transactions']) == 200
    assert all(r['state'] == 'PASS' for r in rows)
    assert sum(r['raw']['meta']['err'] is not None for r in rows) == 184
    # Independent direct sum of raw integer fee fields from the preserved pages:
    # page 02 = 4,841,430 lamports; page 03 = 4,063,303 lamports.
    assert sum(r['raw']['meta']['fee'] for r in rows if r['raw']['transaction']['message']['accountKeys'][0] == WALLET) == 8_904_733
    described = describe_pages(sources(manifest, payloads), WALLET, WINDOW)
    assert described['state'] == 'UNKNOWN' and described['historical_population'] == 'UNKNOWN'
    assert any('nonterminal' in gap for gap in described['gaps'])


@pytest.mark.parametrize('variant', ['boolean-request-id', 'boolean-response-id', 'null-id', 'float-id',
                                    'wrong-time', 'status-filter', 'row-order', 'same-placement', 'repeated-cursor', 'empty-nonterminal'])
def test_rpc_identity_and_native_indexed_contract_cannot_supply_false_typed_chronology(variant):
    request, response = page([native(), native('indexed-b', slot=2)])
    req, res = json.loads(request), json.loads(response)
    if variant == 'boolean-request-id': req['id'] = True
    if variant == 'boolean-response-id': res['id'] = True
    if variant == 'null-id': req['id'] = res['id'] = None
    if variant == 'float-id': req['id'] = res['id'] = 1.0
    if variant == 'wrong-time': res['result']['data'][1]['blockTime'] = 1
    if variant == 'status-filter': req['params'][1]['filters']['status'] = 'succeeded'
    if variant == 'row-order': res['result']['data'].reverse()
    if variant == 'same-placement': res['result']['data'][1]['slot'] = 1
    if variant == 'repeated-cursor': req['params'][1]['paginationToken'] = res['result']['paginationToken'] = '1:0'
    if variant == 'empty-nonterminal': res['result']['data'] = []; res['result']['paginationToken'] = '1:0'
    _, _, content = upload([(json.dumps(req).encode(), json.dumps(res).encode())])
    if variant == 'empty-nonterminal':
        with pytest.raises(ValueError, match='identifiable'): convert_indexed_archive(content)
        return
    manifest, payloads = unpack(convert_indexed_archive(content))
    src = sources(manifest, payloads)[0]['payload']
    assert validate_page_envelope(src, WALLET)['state'] == 'UNKNOWN'
    native_sources = source_records(src, address=WALLET)
    assert native_sources['state'] == 'UNKNOWN' and native_sources['records'] == [] and native_sources['gaps']
    assert native_sources['signatures']  # Rejected alternative leads remain linked.


def test_source_records_derive_native_association_without_caller_role_declarations():
    _, _, content = upload([page([native(), native('indexed-b', slot=2)])])
    manifest, payloads = unpack(convert_indexed_archive(content))
    src = sources(manifest, payloads)[0]['payload']
    assert source_records(src, signature='indexed-b', address=WALLET)['records'] == [native('indexed-b', slot=2)]
    assert source_records(src, signature='unrelated', address=WALLET)['records'] == []


def test_per_load_resolver_parses_each_source_once_and_returned_records_cannot_mutate_snapshot():
    _, _, content = upload([page([native(), native('indexed-b', slot=2)])])
    manifest, payloads = unpack(convert_indexed_archive(content))
    reads = []
    def read(identifier, role):
        reads.append(identifier)
        return payloads.get(identifier)
    resolver = IndexedResolver(read, address=WALLET)
    pointers = [payloads[r['hash']] for r in manifest['transactions']]
    first = resolver.resolve(pointers[0]); first['raw']['meta']['fee'] = 999999
    assert resolver.resolve(pointers[0])['raw']['meta']['fee'] == 5000
    assert resolver.resolve(pointers[1])['state'] == 'PASS' and len(reads) == 1
    payloads.pop(pointers[0]['source_hash'])
    assert IndexedResolver(read, address=WALLET).resolve(pointers[0])['state'] == 'UNKNOWN'


def test_version_dispatch_checks_zip_bytes_duplicate_names_and_unsafe_paths():
    _, _, content = upload([page()])
    assert archive_version(content) == VERSION
    assert archive_version(convert_indexed_archive(content)) == 'archived-wallet-input-v1'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('manifest.json', canonical_bytes({'version': VERSION}))
        archive.writestr('../manifest.json', b'{}')
    with pytest.raises(ValueError, match='Unsupported'): archive_version(stream.getvalue())


def test_malformed_native_alternative_keeps_raw_and_request_signature_leads_as_negative_dependencies():
    request = json.dumps({'jsonrpc': '2.0', 'id': True, 'method': 'getTransaction',
        'params': ['indexed-a', {'encoding': 'jsonParsed', 'commitment': 'finalized', 'maxSupportedTransactionVersion': 1}]}).encode()
    response = json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': native('indexed-b')}).encode()
    _, _, content = upload([page()], alternatives=[('indexed-a', request, response)])
    manifest, payloads = unpack(convert_indexed_archive(content))
    ref = next(r for r in manifest['evidence'] if r['kind'] == 'indexed-native-source')
    negatives = source_records(payloads[ref['hash']], address=WALLET)
    assert negatives['state'] == 'UNKNOWN' and negatives['records'] == []
    assert negatives['signatures'] == ['indexed-a', 'indexed-b']


def test_record_receipt_does_not_duplicate_whole_page_populations():
    _, _, content = upload([page([native(), native('indexed-b', slot=2)])])
    manifest, payloads = unpack(convert_indexed_archive(content))
    summary = resolve_all(manifest, payloads)[0]['page_summary']
    assert summary['record_count'] == 2
    assert not {'records', 'signatures', 'record_hashes', 'positions', 'request', 'response'} & set(summary)


@pytest.mark.parametrize('role,depth', [('request', 80), ('response', 80), ('request', 2000), ('response', 2000)])
def test_deep_raw_rpc_json_retains_exact_bytes_as_rejecting_dependency_without_parser_crash(role, depth):
    good = page()
    request, response = page([native('indexed-b', slot=2)], ident=2)
    raw = request if role == 'request' else response
    # Construct bytes independently of Python's serializer recursion limit.
    deep = b'['*depth+b'0'+b']'*depth
    changed = raw.rstrip()[:-1]+b',"nested":'+deep+b'}'
    bad = (changed, response) if role == 'request' else (request, changed)
    _, _, content = upload([good, bad])
    manifest, payloads = unpack(convert_indexed_archive(content))
    bad_source = next(source['payload'] for source in sources(manifest, payloads)
                      if source['payload'][role+'_hash'] == digest(changed))
    assert source_bytes(bad_source)[role] == changed
    rejected = validate_page_envelope(bad_source, WALLET)
    assert rejected['state'] == 'UNKNOWN' and ('depth' in rejected['reason'] or 'inspection' in rejected['reason'])
    assert describe_pages(sources(manifest, payloads), WALLET, WINDOW)['state'] == 'UNKNOWN'
    assert any(row['state'] == 'PASS' for row in resolve_all(manifest, payloads))


@pytest.mark.parametrize('depth', [80, 2000])
def test_deep_upload_manifest_rejected_as_valueerror_by_dispatch_and_conversion(depth):
    manifest, raw_inputs, _ = upload([page()])
    raw_manifest = canonical_bytes(manifest)[:-1]+b',"nested":'+b'['*depth+b'0'+b']'*depth+b'}'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('manifest.json', raw_manifest)
        for h, raw in raw_inputs.items(): archive.writestr(f'raw/{h}.json', raw)
    for operation in (archive_version, convert_indexed_archive):
        with pytest.raises(ValueError, match='depth|inspection'): operation(stream.getvalue())


@pytest.mark.parametrize('variant', ['deep', 'cycle'])
def test_canonical_serialization_rejects_recursive_objects_and_retains_negative_source_receipt(variant):
    import scanner.indexed_input as module
    nested = []
    if variant == 'cycle': nested.append(nested)
    else:
        for _ in range(80): nested = [nested]
    with pytest.raises(ValueError, match='depth|Cyclic'): module.canonical_bytes(nested)
    _, _, content = upload([page()])
    manifest, payloads = unpack(convert_indexed_archive(content))
    source = deepcopy(sources(manifest, payloads)[0])
    source['payload']['nested'] = nested
    # No caller-object canonicalization exception escapes the resolver.
    pointer = payloads[manifest['transactions'][0]['hash']]
    rejected = resolve_record(pointer, lambda h, role: source['payload'], address=WALLET)
    assert rejected['state'] == 'UNKNOWN' and rejected['raw'] is None
    assert source['hash'] in [r['hash'] for r in describe_pages([source], WALLET, WINDOW)['pages']]


def test_deep_manifest_normal_api_import_returns_422_without_evidence_or_report_mutation(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    import scanner.app as application
    import httpx
    import keyring
    def denied(*args, **kwargs): pytest.fail('Offline malformed input attempted provider/credential IO')
    monkeypatch.setattr(application, 'Credentials', lambda _: SimpleNamespace(key=None, storage='none', backend=None))
    monkeypatch.setattr(httpx.AsyncClient, 'request', denied)
    monkeypatch.setattr(keyring, 'get_password', denied)
    manifest, raw_inputs, _ = upload([page()])
    raw_manifest = canonical_bytes(manifest)[:-1]+b',"nested":'+b'['*2000+b'0'+b']'*2000+b'}'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('manifest.json', raw_manifest)
        for h, raw in raw_inputs.items(): archive.writestr(f'raw/{h}.json', raw)
    app = application.create_app(tmp_path, 'bounded-indexed-depth-test')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        csrf = client.get('/api/bootstrap', headers={'X-Launch-Token': 'bounded-indexed-depth-test'}).json()['csrf']
        client.headers['X-CSRF-Token'] = csrf
        before = {kind: deepcopy(app.state.store.list(kind)) for kind in ('artifacts', 'reports', 'scans')}
        response = client.post('/api/archives/import', content=stream.getvalue())
        assert response.status_code == 422 and 'depth' in response.json()['detail']
        assert {kind: app.state.store.list(kind) for kind in before} == before


@pytest.mark.parametrize('substitution', ['missing', 'corrupt'])
def test_same_hash_payload_substitution_never_hides_dependency_under_permutation(substitution):
    _, _, content = upload([page()])
    manifest, payloads = unpack(convert_indexed_archive(content))
    good = sources(manifest, payloads)[0]
    bad = deepcopy(good)
    if substitution == 'missing': bad['payload'] = None
    else: bad['payload']['response_hash'] = 'a'*64
    results = [describe_pages(rows, WALLET, WINDOW) for rows in ([good, bad], [bad, good], [good, bad, good])]
    assert results[0] == results[1] == results[2]
    assert results[0]['state'] == 'UNKNOWN'
    assert results[0]['pages'][0]['state'] == 'UNKNOWN'
    assert len(results[0]['pages'][0]['source_variants']) == 2


def test_exact_duplicate_page_bodies_are_idempotent():
    _, _, content = upload([page()])
    manifest, payloads = unpack(convert_indexed_archive(content))
    good = sources(manifest, payloads)[0]
    single = describe_pages([good], WALLET, WINDOW)
    assert single['state'] == 'PASS'
    assert describe_pages([good, deepcopy(good)], WALLET, WINDOW) == single


def test_shared_json_boundary_keeps_canonical_bytes_duplicate_key_and_nonfinite_contract():
    from scanner.json_boundary import canonical_bytes as shared_canonical, parse_json
    assert shared_canonical({'z': 0, 'a': [1, 'é']}) == '{"a":[1,"é"],"z":0}'.encode()
    assert shared_canonical({1: 'value'}) == b'{"1":"value"}'  # Existing generic JSON encoder convention.
    for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
        with pytest.raises(ValueError): parse_json(raw)
    assert parse_json(b'{"a":[1,2,3,4]}') == {'a': [1,2,3,4]}
    with pytest.raises(ValueError, match='inspection'): parse_json(b'{"a":[1,2,3,4]}', max_nodes=3)


def test_shared_json_boundary_rejects_deep_parse_and_cyclic_serialization_without_adapter_imports():
    from scanner.json_boundary import canonical_bytes as shared_canonical, parse_json
    valid = b'['*20+b'0'+b']'*20
    assert shared_canonical(parse_json(valid)) == valid
    for depth in (80, 2000):
        with pytest.raises(ValueError, match='depth|inspection'): parse_json(b'['*depth+b'0'+b']'*depth)
    cyclic = {}; cyclic['self'] = cyclic
    with pytest.raises(ValueError, match='Cyclic'): shared_canonical(cyclic)
    nested = ()
    for _ in range(80): nested = (nested,)
    with pytest.raises(ValueError, match='depth|inspection'): shared_canonical(nested)


@pytest.mark.parametrize('depth', [80, 2000])
def test_legacy_archive_deep_raw_payload_normal_api_returns_422_before_any_source_mutation(tmp_path, monkeypatch, depth):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    import scanner.app as application
    import httpx
    import keyring
    def denied(*args, **kwargs): pytest.fail('Offline malformed legacy input attempted provider/credential IO')
    monkeypatch.setattr(application, 'Credentials', lambda _: SimpleNamespace(key=None, storage='none', backend=None))
    monkeypatch.setattr(httpx.AsyncClient, 'request', denied)
    monkeypatch.setattr(keyring, 'get_password', denied)
    # Adversarial bytes are independently constructed, without the bounded
    # serializer under test, and checksum-named exactly as a real upload.
    raw_payload = json.dumps(native(), sort_keys=True, separators=(',', ':')).encode()
    raw_payload = raw_payload[:-1]+b',"nested":'+b'['*depth+b'0'+b']'*depth+b'}'
    h = hashlib.sha256(raw_payload).hexdigest()
    manifest = {'version': 'archived-wallet-input-v1', 'address': WALLET, 'window': WINDOW, 'dataset': 'real',
                'transactions': [{'signature': 'indexed-a', 'hash': h}], 'evidence': []}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode())
        archive.writestr(f'archives/{h}.json.gz', gzip.compress(raw_payload, mtime=0))
    app = application.create_app(tmp_path, 'bounded-legacy-depth-test')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        csrf = client.get('/api/bootstrap', headers={'X-Launch-Token': 'bounded-legacy-depth-test'}).json()['csrf']
        client.headers['X-CSRF-Token'] = csrf
        before = {kind: deepcopy(app.state.store.list(kind)) for kind in ('artifacts', 'reports', 'scans')}
        response = client.post('/api/archives/import', content=stream.getvalue())
        assert response.status_code == 422 and 'depth' in response.json()['detail']
        assert {kind: app.state.store.list(kind) for kind in before} == before
