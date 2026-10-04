#!/usr/bin/env python3
"""Read-only equality/profiling proof for the checksum-bound indexed parser.

This procedural check compares the entire output against preserved Git source;
its altered wrappers are development controls, never genuine acceptance data.
No provider calls or credentials are needed. Run from the repository root.
"""
from __future__ import annotations

import base64
from copy import deepcopy
import cProfile
import gzip
import hashlib
import io
import json
from pathlib import Path
import pstats
import socket
import statistics
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent
BASELINE = '1040215f498b1317b1b942838994127f43a822bd'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def wrapped(request, response, version):
    return {'version': version, 'request_hash': digest(request), 'response_hash': digest(response),
            'request_base64': base64.b64encode(request).decode(),
            'response_base64': base64.b64encode(response).decode()}


def mutated(payload, *, request=None, response=None):
    original = {name: base64.b64decode(payload[name + '_base64']) for name in ('request', 'response')}
    return wrapped(encoded(request) if request is not None else original['request'],
                   encoded(response) if response is not None else original['response'], payload['version'])


def first_difference(a, b, path='$'):
    if type(a) is not type(b):
        return path + ': type'
    if isinstance(a, dict):
        if set(a) != set(b):
            return path + ': keys'
        for key in a:
            if a[key] != b[key]:
                return first_difference(a[key], b[key], path + '.' + str(key))
    elif isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return path + ': length'
        for index, (left, right) in enumerate(zip(a, b)):
            if left != right:
                return first_difference(left, right, path + '[' + str(index) + ']')
    return path + ': value'


def outcome(function, *args):
    try:
        return {'kind': 'returned', 'value': function(*args)}
    except Exception as exc:
        return {'kind': 'raised', 'exception': type(exc).__name__, 'message': str(exc)}


def main():
    started = time.time()
    current_path = ROOT / 'scanner/indexed_input.py'
    source_before = current_path.read_bytes()
    baseline_source = subprocess.check_output(['git', 'show', BASELINE + ':scanner/indexed_input.py'], cwd=ROOT)
    baseline = types.ModuleType('scanner._preserved_indexed_input')
    baseline.__package__ = 'scanner'
    baseline.__file__ = 'git:' + BASELINE + ':scanner/indexed_input.py'
    sys.modules[baseline.__name__] = baseline
    exec(compile(baseline_source, baseline.__file__, 'exec'), baseline.__dict__)
    import scanner.indexed_input as current
    from scanner.providers import Gateway
    from tests.test_indexed_input import PROBE, WALLET, WINDOW, native, page

    calls = {'provider': 0, 'credential': 0, 'network': 0}
    def no_network(*args, **kwargs):
        calls['network'] += 1
        raise AssertionError('Network forbidden in parser comparison')
    async def no_provider(*args, **kwargs):
        calls['provider'] += 1
        raise AssertionError('Provider forbidden in parser comparison')
    def no_credential(*args, **kwargs):
        calls['credential'] += 1
        raise AssertionError('Credential lookup forbidden in parser comparison')
    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    socket.create_connection = no_network
    socket.getaddrinfo = no_network
    Gateway.rpc = no_provider
    sys.modules['keyring'] = types.SimpleNamespace(get_password=no_credential,
        get_keyring=no_credential, set_password=no_credential)

    originals = []
    genuine = []
    for stem in ('02-all-index', '03-all-continuation'):
        request_path, response_path = PROBE / (stem + '-request.json'), PROBE / (stem + '-response.raw.gz')
        request, compressed = request_path.read_bytes(), response_path.read_bytes()
        response = gzip.decompress(compressed)
        payload = wrapped(request, response, current.PAGE_VERSION)
        genuine.append(payload)
        originals.append({'request_path': str(request_path.relative_to(ROOT)), 'request_sha256': digest(request),
            'request_bytes': len(request), 'response_path': str(response_path.relative_to(ROOT)),
            'response_gzip_sha256': digest(compressed), 'response_raw_sha256': digest(response),
            'response_raw_bytes': len(response), 'wrapper_sha256': digest(encoded(payload))})

    request, response = page([native('comparison-a', slot=1), native('comparison-b', slot=2)])
    development = wrapped(request, response, current.PAGE_VERSION)
    cases = [('genuine-initial', genuine[0], WALLET), ('genuine-continuation', genuine[1], WALLET),
             ('genuine-wallet-mismatch', genuine[0], '11111111111111111111111111111111'),
             ('genuine-address-unspecified', genuine[0], None), ('development-supported', development, WALLET)]
    genuine_request = json.loads(base64.b64decode(genuine[0]['request_base64']))
    genuine_response = json.loads(base64.b64decode(genuine[0]['response_base64']))
    for label, change, target in (
        ('genuine-reject-header-retain-leads', lambda value: value.update(id=True), 'response'),
        ('genuine-reject-cursor-retain-leads', lambda value: value['result'].update(paginationToken='bad-cursor'), 'response'),
        ('genuine-reject-method-retain-leads', lambda value: value.update(method='sendTransaction'), 'request'),
    ):
        value = deepcopy(genuine_response if target == 'response' else genuine_request)
        change(value)
        rejected = mutated(genuine[0], **{target: value})
        for module in (baseline, current):
            retained = module.validate_page_envelope(rejected, WALLET)
            assert retained['state'] == 'UNKNOWN'
            assert len(retained['records']) == len(retained['signatures']) == len(retained['record_hashes']) == 100
        cases.append((label, rejected, WALLET))
    for label, change in (
        ('header-id-type', lambda r: r.update(id=True)),
        ('header-id-mismatch', lambda r: r.update(id='does-not-match')),
        ('header-jsonrpc', lambda r: r.update(jsonrpc='1.0')),
        ('header-error', lambda r: r.update(error={'code': -1, 'message': 'development control'})),
        ('header-missing-result', lambda r: r.pop('result')),
        ('page-extra-field', lambda r: r['result'].update(complete=True)),
        ('page-bad-cursor', lambda r: r['result'].update(paginationToken='bad-cursor')),
        ('page-duplicate-record', lambda r: r['result']['data'].append(deepcopy(r['result']['data'][0]))),
        ('page-row-permutation', lambda r: r['result']['data'].reverse()),
        ('page-malformed-record', lambda r: r['result']['data'].append({'malformed': True})),
        ('page-missing-placement', lambda r: r['result']['data'][0].pop('transactionIndex')),
        ('page-missing-meta', lambda r: r['result']['data'][0].pop('meta')),
        ('page-time-outside', lambda r: r['result']['data'][0].update(blockTime=1)),
        ('page-empty-nonterminal', lambda r: r['result'].update(data=[], paginationToken='1:0')),
        ('page-not-list', lambda r: r['result'].update(data={})),
        ('page-result-null', lambda r: r.update(result=None)),
    ):
        value = json.loads(response)
        change(value)
        cases.append((label, mutated(development, response=value), WALLET))
    for label, change in (
        ('request-extra-trusted-completion', lambda r: r.update(complete=True)),
        ('request-method', lambda r: r.update(method='sendTransaction')),
        ('request-jsonrpc', lambda r: r.update(jsonrpc='1.0')),
        ('request-id-null', lambda r: r.update(id=None)),
        ('request-params-null', lambda r: r.update(params=None)),
        ('request-limit', lambda r: r['params'][1].update(limit=1)),
        ('request-sort', lambda r: r['params'][1].update(sortOrder='unknown')),
        ('request-cursor', lambda r: r['params'][1].update(paginationToken='bad-cursor')),
        ('request-binary-encoding', lambda r: r['params'][1].update(encoding='base64')),
        ('request-filter-status', lambda r: r['params'][1]['filters'].update(status='succeeded')),
        ('request-filter-tokenaccounts', lambda r: r['params'][1]['filters'].update(tokenAccounts='unsupported')),
        ('request-filter-extra', lambda r: r['params'][1]['filters'].update(complete=True)),
        ('request-filter-bounds', lambda r: r['params'][1]['filters'].update(blockTime={'gte': 9, 'lt': 1})),
    ):
        value = json.loads(request)
        change(value)
        cases.append((label, mutated(development, request=value), WALLET))
    for name in ('request', 'response'):
        value = deepcopy(development)
        value[name + '_base64'] = None
        cases.append((name + '-missing', value, WALLET))
        value = deepcopy(development)
        value[name + '_base64'] = 'not-base64!'
        cases.append((name + '-invalid-base64', value, WALLET))
        value = deepcopy(development)
        value[name + '_hash'] = '0' * 64
        cases.append((name + '-checksum-corrupt', value, WALLET))
        value = deepcopy(development)
        bad = b'{"broken":'
        value[name + '_hash'], value[name + '_base64'] = digest(bad), base64.b64encode(bad).decode()
        cases.append((name + '-malformed-json', value, WALLET))
    oversized = b' ' * (current.MAX_RAW + 1)
    cases.append(('response-oversize', wrapped(request, oversized, current.PAGE_VERSION), WALLET))
    row_overrun = json.loads(response)
    row_overrun['result']['data'] = [native('overrun-' + str(index), slot=index + 1)
                                   for index in range(current.MAX_PAGE_RECORDS + 1)]
    cases.append(('page-record-count-overrun', mutated(development, response=row_overrun), WALLET))
    cases.append(('response-depth-overrun', wrapped(request, b'[' * 66 + b'0' + b']' * 66, current.PAGE_VERSION), WALLET))
    cases.append(('response-nonfinite', wrapped(request, b'{"jsonrpc":"2.0","id":1,"result":NaN}', current.PAGE_VERSION), WALLET))
    cases.append(('response-duplicate-json-key', wrapped(request, b'{"id":1,"id":1}', current.PAGE_VERSION), WALLET))
    cases.append(('request-null', wrapped(b'null', response, current.PAGE_VERSION), WALLET))
    cases.append(('response-null', wrapped(request, b'null', current.PAGE_VERSION), WALLET))
    cases.append(('wrapper-extra-trusted-completion', {**development, 'complete': True}, WALLET))
    cases.append(('wrapper-missing', None, WALLET))
    cases.append(('wrapper-restored', deepcopy(development), WALLET))
    record = native('native-comparison')
    native_request = encoded({'jsonrpc': '2.0', 'id': 45, 'method': 'getTransaction',
        'params': ['native-comparison', {'encoding': 'json', 'commitment': 'finalized', 'maxSupportedTransactionVersion': 0}]})
    native_response = encoded({'jsonrpc': '2.0', 'id': 45, 'result': record})
    native_payload = wrapped(native_request, native_response, current.NATIVE_VERSION)
    cases.append(('native-supported-request', native_payload, WALLET))
    native_wrong = json.loads(native_request)
    native_wrong['params'][1]['commitment'] = 'confirmed'
    cases.append(('native-unreviewed-request', mutated(native_payload, request=native_wrong), WALLET))

    outputs = []
    for label, payload, address in cases:
        input_before = digest(encoded(payload))
        for function_name in ('validate_page_envelope', '_request', 'source_records'):
            args = (payload, None, address) if function_name == 'source_records' else (payload, address)
            left = outcome(getattr(baseline, function_name), *args)
            right = outcome(getattr(current, function_name), *args)
            if left != right:
                raise AssertionError(label + '/' + function_name + ': ' + first_difference(left, right))
            assert digest(encoded(payload)) == input_before, 'Input mutated: ' + label
            row = {'case': label, 'entrypoint': function_name, 'complete_output_sha256': digest(encoded(left)),
                   'output_equal': True, 'input_sha256': input_before, 'input_unchanged': True, 'kind': left['kind']}
            if left['kind'] == 'raised':
                row.update(exception=left['exception'], reason=left['message'])
            elif isinstance(left['value'], dict):
                row.update(state=left['value'].get('state'), reason=left['value'].get('reason'))
            outputs.append(row)
    rows = [{'hash': digest(encoded(p)), 'payload': p} for p in genuine]
    topo = [('original', rows), ('permutation', list(reversed(rows))), ('duplicates', rows + deepcopy(rows)),
            ('missing', [rows[0], {'hash': rows[1]['hash'], 'payload': None}]),
            ('conflicting-linked-content', rows + [{'hash': rows[0]['hash'], 'payload': development}]),
            ('restored', deepcopy(rows))]
    for label, values in topo:
        before = digest(encoded(values))
        left, right = outcome(baseline.describe_pages, values, WALLET, WINDOW), outcome(current.describe_pages, values, WALLET, WINDOW)
        if left != right:
            raise AssertionError('topology/' + label + ': ' + first_difference(left, right))
        assert before == digest(encoded(values))
        outputs.append({'case': 'topology-' + label, 'entrypoint': 'describe_pages',
            'complete_output_sha256': digest(encoded(left)), 'output_equal': True,
            'input_sha256': before, 'input_unchanged': True, 'kind': left['kind'], 'state': left['value']['state']})

    measurements = {'baseline': [], 'current': []}
    modules = {'baseline': baseline, 'current': current}
    for round_number in range(5):
        for name in ('baseline', 'current') if round_number % 2 == 0 else ('current', 'baseline'):
            started_run = time.perf_counter()
            for payload in genuine:
                assert modules[name].validate_page_envelope(payload, WALLET)['state'] == 'PASS'
            measurements[name].append(time.perf_counter() - started_run)
    counts = {}
    profiles = []
    for name, module in modules.items():
        measured = {}
        originals_functions = {}
        for function_name in ('source_bytes', '_json', 'canonical_bytes'):
            original = getattr(module, function_name)
            originals_functions[function_name] = original
            measured[function_name] = 0
            def counting(*args, _name=function_name, _original=original, **kwargs):
                measured[_name] += 1
                return _original(*args, **kwargs)
            setattr(module, function_name, counting)
        try:
            for payload in genuine:
                assert module.validate_page_envelope(payload, WALLET)['state'] == 'PASS'
        finally:
            for function_name, original in originals_functions.items():
                setattr(module, function_name, original)
        counts[name] = measured
        profile = cProfile.Profile()
        profile.enable()
        for payload in genuine:
            assert module.validate_page_envelope(payload, WALLET)['state'] == 'PASS'
        profile.disable()
        profile_path = OUT / ('indexed-parser-' + name + '.profile')
        profile.dump_stats(profile_path)
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(40)
        text_path = OUT / ('indexed-parser-' + name + '-profile.txt')
        text_path.write_text(stream.getvalue())
        profiles.extend({'path': str(path.relative_to(ROOT)), 'sha256': digest(path.read_bytes()), 'bytes': path.stat().st_size}
                        for path in (profile_path, text_path))
    assert counts['baseline'] == {'source_bytes': 4, '_json': 6, 'canonical_bytes': 400}
    assert counts['current'] == {'source_bytes': 2, '_json': 4, 'canonical_bytes': 200}
    assert calls == {'provider': 0, 'credential': 0, 'network': 0}
    assert current_path.read_bytes() == source_before, 'Parser source changed during proof'
    assert subprocess.check_output(['git', 'show', BASELINE + ':scanner/indexed_input.py'], cwd=ROOT) == baseline_source
    receipt = {'state': 'PASS', 'scope': 'Complete preserved-source output equivalence and local envelope performance only; not wallet qualification or B3 acceptance',
        'baseline_commit': BASELINE, 'baseline_module_sha256': digest(baseline_source),
        'current_module_sha256': digest(source_before), 'source_unchanged': True,
        'current_git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
        'baseline_import_note': 'Preserved indexed module loaded in scanner namespace against current unchanged dependency APIs; this isolates indexed parser changes, not full application equivalence',
        'complete_outputs_compared': len(outputs), 'page_wrapper_cases': len(cases), 'topology_cases': len(topo),
        'genuine_inputs': originals, 'outputs': outputs, 'provider_requests': 0, 'credential_lookups': 0, 'network_calls': 0,
        'measurements': {'method': 'Five alternating-order samples; each parses both genuine 100-record pages once; wall times are local observations',
            'samples_seconds': measurements, 'median_seconds': {k: statistics.median(v) for k, v in measurements.items()},
            'call_counts_same_two_pages': counts, 'profiles': profiles}, 'elapsed_seconds': time.time() - started}
    receipt_path = OUT / 'INDEXED_PARSER_REUSE_PROOF.json'
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': receipt['state'], 'complete_outputs_compared': len(outputs), 'source_unchanged': True,
        'call_counts_same_two_pages': counts, 'median_seconds': receipt['measurements']['median_seconds'],
        'receipt': str(receipt_path.relative_to(ROOT)), 'receipt_sha256': digest(receipt_path.read_bytes()),
        'provider_requests': 0, 'credential_lookups': 0, 'network_calls': 0}, sort_keys=True))


if __name__ == '__main__':
    main()
