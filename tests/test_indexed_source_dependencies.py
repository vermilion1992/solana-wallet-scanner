"""Offline indexed dependency controls; development bytes do not close B3."""
from copy import deepcopy
import base64
import hashlib
import json

import pytest

from scanner.archive_input import canonical_bytes
from scanner.indexed_input import PAGE_VERSION, NATIVE_VERSION, MANIFEST_VERSION
from scanner.source_consistency import source_archive_receipts, assess_source_consistency
from scanner.wallet_evidence import derive_wallet_evidence, raw_native_dependencies
from test_wallet_evidence import record
from test_position_evidence import raw_exchange, WALLET, ACCOUNT, START, END, WINDOW


def source(raws, *, request_change=None, response_change=None, native=False):
    request = {'jsonrpc': '2.0', 'id': 41, 'method': 'getTransactionsForAddress',
        'params': [WALLET, {'transactionDetails': 'full', 'limit': 100, 'sortOrder': 'asc',
            'commitment': 'finalized', 'maxSupportedTransactionVersion': 0,
            'filters': {'status': 'any', 'tokenAccounts': 'all',
                'blockTime': {'gte': START, 'lt': END}}}]}
    response = {'jsonrpc': '2.0', 'id': 41, 'result': {'data': deepcopy(raws), 'paginationToken': None}}
    if native:
        request.update(method='getTransaction', params=[raws[0]['transaction']['signatures'][0],
            {'encoding': 'json', 'commitment': 'finalized', 'maxSupportedTransactionVersion': 0}])
        response['result'] = deepcopy(raws[0])
    if request_change:
        request_change(request)
    if response_change:
        response_change(response)
    payload = {'version': NATIVE_VERSION if native else PAGE_VERSION}
    for name, value in [('request', request), ('response', response)]:
        raw = canonical_bytes(value)
        payload[name + '_hash'] = hashlib.sha256(raw).hexdigest()
        payload[name + '_base64'] = base64.b64encode(raw).decode('ascii')
    return {'kind': 'indexed-native-source' if native else 'indexed-page',
            'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'payload': payload}


def native(signature='indexed-dev-buy', slot=100, index=2, at=START + 3600):
    raw = raw_exchange(signature, slot, at, 0, 100)
    raw['transactionIndex'] = index
    return raw


def typed(row):
    return source_archive_receipts({'links': [{'kind': row['kind'], 'hash': row['hash']}]},
        {row['hash']: row['payload']}, {row['hash']: 'readable' if row['payload'] is not None else 'missing'},
        wallet=WALLET)['receipts'][0]


def derive(raws, sources, *, alternatives=()):
    selected = [record(raw) for raw in raws]
    return derive_wallet_evidence(selected, all_records=selected + list(alternatives), wallet=WALLET,
        window=WINDOW, source_consistency={'state': 'PASS'}, chronology={'state': 'PASS'},
        raw_sources=sources)


@pytest.mark.parametrize('native_source', [False, True])
def test_original_byte_wrappers_validate_roles_without_population_claim(native_source):
    row = source([native()], native=native_source)
    receipt = typed(row)
    assert receipt['state'] == 'PASS'
    assert receipt['scope']['signatures'] == ['indexed-dev-buy']
    assert receipt['scope']['account'] == (None if native_source else WALLET)
    changed = deepcopy(row)
    changed['payload']['response_base64'] = base64.b64encode(b'{}').decode('ascii')
    changed['hash'] = hashlib.sha256(canonical_bytes(changed['payload'])).hexdigest()
    assert typed(changed)['state'] == 'UNKNOWN'


def test_frozen_original_manifest_validates_bytes_but_not_native_scope():
    raw = canonical_bytes({'version': 'indexed-wallet-input-v1', 'address': WALLET, 'window': WINDOW,
        'pages': [{'request_hash': 'a' * 64, 'response_hash': 'b' * 64}]})
    payload = {'version': MANIFEST_VERSION, 'sha256': hashlib.sha256(raw).hexdigest(),
               'bytes_base64': base64.b64encode(raw).decode('ascii')}
    row = {'kind': 'indexed-input-manifest', 'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'payload': payload}
    assert typed(row)['state'] == 'PASS'
    assert typed(row)['scope']['signatures'] is None
    assert raw_native_dependencies([row], [], ['indexed-dev-buy']) == []
    bad = deepcopy(row)
    bad['payload']['sha256'] = '0' * 64
    bad['hash'] = hashlib.sha256(canonical_bytes(bad['payload'])).hexdigest()
    assert typed(bad)['state'] == 'UNKNOWN'


def test_positive_page_recomputed_native_facts_and_order_reach_same_wallet_path():
    raw = native()
    row = source([raw])
    original = deepcopy(row)
    result = derive([raw], [row])
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['components']['fee_window']['state'] == 'PASS'
    assert result['components']['observed_quantities']['state'] == 'PASS'
    assert result['transactions']['indexed-dev-buy']['network_fee']['lamports'] == '5000'
    assert result['components']['historical_population']['state'] == 'UNKNOWN'
    assert result['provider_requests'] == result['credential_lookups'] == 0
    assert row == original


@pytest.mark.parametrize('role', ['indexed-page', 'classification', 'valuation', 'current-mint-controls'])
def test_negative_native_affinity_ignores_label_and_conflict_cannot_disappear(role):
    raw = native()
    alternative = deepcopy(raw)
    alternative['meta']['fee'] += 1
    alternative['meta']['postBalances'][0] -= 1
    row = source([alternative])
    row['kind'] = role
    frozen = raw_native_dependencies([row], [], ['indexed-dev-buy'])
    assert frozen[0]['signature'] == 'indexed-dev-buy'
    assert frozen[0]['raw'] == alternative
    conflicting = derive([raw], [row])
    assert conflicting['components']['native_fee']['state'] == 'UNKNOWN'
    lost = derive([raw], [{**row, 'payload': None}],
        alternatives=[{**entry, 'raw': None} for entry in frozen])
    assert lost['components']['native_fee']['state'] == 'UNKNOWN'
    assert row['hash'] in lost['components']['native_fee']['evidence']
    restored = derive([raw], [row])
    assert restored['components'] == conflicting['components']


def test_bad_cursor_preserves_raw_fee_while_rejecting_dependent_clock_result():
    raw = native()
    def wrong_request(request):
        request['params'][1]['paginationToken'] = '101:2'
    row = source([raw], request_change=wrong_request)
    receipt = typed(row)
    assert receipt['state'] == 'UNKNOWN'
    assert receipt['scope']['signatures'] == ['indexed-dev-buy']
    result = derive([raw], [row])
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['components']['fee_window']['state'] == 'UNKNOWN'
    assert result['transactions']['indexed-dev-buy']['network_fee']['lamports'] == '5000'


def test_execution_conflict_compares_exact_page_facts_without_caller_receipts():
    raw = native()
    failed = deepcopy(raw)
    failed['meta']['err'] = {'InstructionError': [0, 'Custom']}
    row = source([failed])
    result = assess_source_consistency([record(raw)], wallet=WALLET,
        indexed_receipts=[{**row, 'state': 'PASS', 'positions': []}])
    account = result['transactions']['indexed-dev-buy']['accounts'][ACCOUNT]
    assert account['checks']['execution']['state'] == 'UNKNOWN'
    assert row['hash'] in account['checks']['execution']['evidence']
    assert result['transactions']['indexed-dev-buy']['native']['wallet_network_fees_sol']['state'] == 'PASS'


def test_unassignable_record_remains_unscoped_negative_dependency():
    raw = native()
    def add_unassignable(response):
        response['result']['data'].append({'meta': {'err': None}, 'transaction': {'signatures': []}})
    row = source([raw], response_change=add_unassignable)
    assert typed(row)['scope']['signatures'] is None
    dependencies = raw_native_dependencies([row], [], ['indexed-dev-buy'])
    assert any(entry['signature'] is None for entry in dependencies)
    result = derive([raw], [row])
    assert result['components']['selected_record_identity']['state'] == 'UNKNOWN'


def test_proven_disjoint_page_cannot_erase_selected_fee_or_quantity_observations():
    raw = native()
    disjoint = source([native('disjoint-indexed-record', 110, 2, START + 4000)])
    assert raw_native_dependencies([disjoint], [], ['indexed-dev-buy']) == []
    result = derive([raw], [disjoint])
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['components']['fee_window']['state'] == 'PASS'
    assert result['components']['observed_quantities']['state'] == 'PASS'


def test_missing_required_page_loses_only_dependent_and_restores_exact_results():
    raw = native()
    row = source([raw])
    parent = derive([raw], [row])
    frozen = raw_native_dependencies([row], [], ['indexed-dev-buy'])
    child = derive([raw], [{**row, 'payload': None}], alternatives=[{**entry, 'raw': None} for entry in frozen])
    assert child['components']['native_fee']['state'] == 'UNKNOWN'
    assert child['components']['fee_window']['state'] == 'UNKNOWN'
    restored = derive([raw], [row])
    assert restored == parent


def test_bodyless_reader_role_alias_is_not_another_missing_source():
    raw = native()
    row = source([raw])
    parent = derive([raw], [row])
    selected = [record(raw)]
    child = derive_wallet_evidence(selected, all_records=selected, wallet=WALLET, window=WINDOW,
        source_consistency={}, chronology={}, raw_sources=[row],
        source_receipts=[{'role': 'indexed-native-source', 'hash': row['hash'], 'state': 'PASS'}])
    assert child == parent


def test_indexed_inspection_budget_cannot_certify_a_convenient_page_prefix(monkeypatch):
    import scanner.wallet_evidence as module
    monkeypatch.setattr(module, 'MAX_INDEXED_RECORDS', 1)
    raw = native()
    rows = [source([raw]), source([native('later-disjoint', 110, 0, START + 4000)])]
    dependencies = raw_native_dependencies(rows, [], ['indexed-dev-buy'])
    assert {row['evidence_hash'] for row in dependencies if row['signature'] is None} == {row['hash'] for row in rows}
    assert derive([raw], rows)['components']['selected_record_identity']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('count', [8, 32])
def test_program_inference_normalizes_once_and_retains_original_compiled_paths(monkeypatch, count):
    import scanner.compiled_instructions as compiled
    from scanner.source_consistency import _program_facts
    from scanner.investigation import _keys
    from test_compiled_report_integration import compiled_development_copy, asset_account, BUY
    fixture = compiled_development_copy(BUY)
    raw, account = fixture['raw'], asset_account(fixture)
    keys = _keys(raw['transaction']['message'], raw['meta'])
    transfer = next(instruction for group in raw['meta']['innerInstructions'] for instruction in group['instructions']
        if instruction.get('programIdIndex') is not None and account in [keys[index] for index in instruction['accounts']]
        and len(instruction['accounts']) == 4)
    outer_index = next(group['index'] for group in raw['meta']['innerInstructions']
                       if transfer in group['instructions'])
    # Repeated schema examples exercise inference cost, not executed quantities
    # or a genuine transaction/accounting acceptance claim.
    raw['meta']['innerInstructions'] = [{'index': outer_index,
                                       'instructions': [deepcopy(transfer) for _ in range(count)]}]
    original, calls = deepcopy(raw), []
    implementation = compiled.normalize_transaction
    def counted(value):
        calls.append(value)
        return implementation(value)
    monkeypatch.setattr(compiled, 'normalize_transaction', counted)
    facts = _program_facts(raw, keys, account, 'a' * 64)
    assert len(calls) == 1
    assert len({row['path'] for row in facts if row['path'].endswith('.data')}) == count
    assert all('.parsed.' not in row['path'] for row in facts)
    assert any(row['path'].endswith('.data') for row in facts)
    assert raw == original


def navigate_original(raw, path):
    value = raw
    for component in path.split('.'):
        value = value[int(component)] if isinstance(value, list) else value[component]
    return value


def observed_paths(observed):
    paths = []
    for pair in observed['boundaries'].values():
        for check in pair['checks'].values():
            paths += check['raw_paths']
    for name in ('lifecycle', 'transfers', 'disjoint_operations'):
        for item in observed[name]:
            paths += item.get('raw_paths', []) + item.get('paths', [])
    return paths + observed.get('error_raw_paths', [])


@pytest.mark.parametrize('name', ['mainnet-pumpswap-buy-exact-quote.json', 'mainnet-pumpswap-sell-durable-nonce.json'])
def test_compiled_wallet_observation_coordinates_navigate_immutable_source(name):
    from scanner.wallet_evidence import _observe
    from test_compiled_report_integration import compiled_development_copy, asset_account, wallet
    fixture = compiled_development_copy(name)
    original = deepcopy(fixture)
    observed = _observe(fixture, wallet(fixture))
    asset = observed['boundaries'][asset_account(fixture)]
    assert asset['checks']['quantities']['state'] == 'PASS'
    paths = observed_paths(observed)
    assert paths and any(path.endswith('.data') for path in paths)
    assert any(path.endswith('.accounts') for path in paths)
    assert any(path.endswith('.programIdIndex') for path in paths)
    for path in paths:
        navigate_original(original['raw'], path)
    assert fixture == original


@pytest.mark.parametrize('variant', ['malformed-required', 'valid-disjoint'])
def test_required_and_disjoint_compiled_operation_paths_are_actual_original_nodes(variant):
    from scanner.wallet_evidence import _observe
    from scanner.investigation import _keys
    from test_compiled_report_integration import (compiled_development_copy, asset_account, wallet,
                                                 SELL, b58_text, rehash)
    fixture = compiled_development_copy(SELL)
    raw, account = fixture['raw'], asset_account(fixture)
    keys = _keys(raw['transaction']['message'], raw['meta'])
    group = raw['meta']['innerInstructions'][0]['instructions']
    if variant == 'malformed-required':
        required = next(instruction for instruction in group
            if 'programIdIndex' in instruction and account in [keys[index] for index in instruction['accounts']])
        required['data'] = '0'
    else:
        owned = {keys[row['accountIndex']] for name in ('preTokenBalances', 'postTokenBalances') for row in raw['meta'][name]
                 if row.get('owner') == wallet(fixture)}
        disjoint_account = next(key for key in keys if key not in owned and key != wallet(fixture))
        token_index = keys.index('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')
        # This executed lifecycle target and authority are explicitly outside
        # the observed owned account population. It supplies no wallet history
        # or classification claim.
        group.append({'programIdIndex': token_index,
                      'accounts': [keys.index(disjoint_account)] * 3, 'data': b58_text(b'\x09')})
    rehash(fixture)
    original = deepcopy(fixture)
    observed = _observe(fixture, wallet(fixture))
    if variant == 'malformed-required':
        assert observed['gaps'] or observed['boundaries'][account]['checks']['quantities']['state'] == 'UNKNOWN'
    else:
        assert observed['boundaries'][account]['checks']['quantities']['state'] == 'PASS'
        assert observed['disjoint_operations']
    paths = observed_paths(observed)
    assert paths and any(path.endswith('.data') or path.endswith('.accounts') for path in paths)
    for path in paths:
        navigate_original(original['raw'], path)
    assert fixture == original
