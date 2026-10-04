"""Unsigned interface controls, never genuine wallet/population acceptance.

Outer signer/header/loaded-key shapes use the already pinned Solana RPC schema
in tests/fixtures/compiled_instructions. Account-info requests use the actual
JSON-RPC request/context/value contract; expected identity is worked separately
from the existing swap decoder's amount calculations.
"""
from copy import deepcopy
import base64
import hashlib
import json

import pytest

from scanner.decoder import SYSTEM_ID
from scanner.json_boundary import canonical_bytes
from scanner.wallet_identity import (
    ACCOUNT_SOURCE_VERSION, account_info_source, account_source_bytes, derive_wallet_identity,
    wallet_identity_dependencies,
)
from test_position_evidence import raw_exchange, address, WALLET, MINT, START


def unsigned_signature(seed=11):
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    number = int.from_bytes(bytes([seed]) * 64, 'big')
    encoded = ''
    while number:
        number, digit = divmod(number, 58)
        encoded = alphabet[digit] + encoded
    return encoded


def record(*, version='legacy', signature=None):
    raw = raw_exchange(signature or unsigned_signature(), 100, START + 1, 0, 100)
    raw['version'] = version
    raw['transaction']['message']['header'] = {
        'numRequiredSignatures': 1, 'numReadonlySignedAccounts': 0,
        'numReadonlyUnsignedAccounts': 0,
    }
    return wrapped(raw)


def wrapped(raw):
    return {'signature': raw['transaction']['signatures'][0], 'raw': raw,
            'evidence_hash': hashlib.sha256(canonical_bytes(raw)).hexdigest()}


def account(*, wallet=WALLET, slot=1000, owner=SYSTEM_ID, **fields):
    value = {'owner': owner, 'executable': False, 'lamports': 1000,
             'data': ['', 'base64'], 'rentEpoch': 18446744073709551615}
    value.update(fields)
    return {'method': 'getAccountInfo', 'address': wallet, 'commitment': 'finalized',
            'result': {'context': {'slot': slot}, 'value': value}}


def source(payload, kind='current-account'):
    return {'kind': kind, 'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(),
            'payload': payload}


def paired(*, wallet=WALLET, commitment='finalized', request_id=7, response_id=7,
           minimum=999, slot=1000):
    # Deliberate whitespace makes exact byte preservation observable.
    request = json.dumps({'jsonrpc': '2.0', 'id': request_id, 'method': 'getAccountInfo',
        'params': [wallet, {'encoding': 'jsonParsed', 'commitment': commitment,
                            'minContextSlot': minimum}]}, indent=2).encode() + b'\n'
    response = json.dumps({'jsonrpc': '2.0', 'id': response_id,
                           'result': account(slot=slot)['result']}, indent=1).encode() + b'\n'
    return account_info_source(request, response), request, response


def derive(*, selected=None, alternatives=(), sources=None, dependencies=()):
    selected = [record()] if selected is None else selected
    sources = [source(account())] if sources is None else sources
    return derive_wallet_identity(selected, all_records=selected + list(alternatives),
        raw_sources=sources, wallet=WALLET, identity_dependencies=dependencies)


@pytest.mark.parametrize('version', ['legacy', 0])
def test_positive_current_account_and_literal_outer_header_do_not_prove_history(version):
    result = derive(selected=[record(version=version)])
    assert result['state'] == result['current_account']['state'] == result['economic_signer']['state'] == 'PASS'
    assert result['historical_population_state'] == 'UNKNOWN'
    assert result['provider_requests'] == result['credential_lookups'] == 0


def test_parsed_outer_signer_flags_and_loaded_key_contract_are_shared():
    row = record(version=0)
    raw = row['raw']
    message = raw['transaction']['message']
    keys = message['accountKeys']
    message.pop('header')
    message['accountKeys'] = [{'pubkey': key, 'signer': index == 0, 'writable': True,
                               'source': 'transaction' if index < 4 else 'lookupTable'}
                              for index, key in enumerate(keys)]
    raw['meta']['loadedAddresses'] = {'writable': [keys[-1]], 'readonly': []}
    assert derive(selected=[wrapped(raw)])['economic_signer']['state'] == 'PASS'


def test_compiled_v0_loaded_key_counts_are_checked_without_inventing_signers():
    row = record(version=0)
    raw = row['raw']
    message = raw['transaction']['message']
    last = message['accountKeys'].pop()
    message['addressTableLookups'] = [{'accountKey': address(90), 'writableIndexes': [1], 'readonlyIndexes': []}]
    raw['meta']['loadedAddresses'] = {'writable': [last], 'readonly': []}
    assert derive(selected=[wrapped(raw)])['state'] == 'PASS'
    missing = deepcopy(raw)
    missing['meta'].pop('loadedAddresses')
    assert derive(selected=[wrapped(missing)])['economic_signer']['state'] == 'UNKNOWN'


def test_original_request_response_bytes_are_retained_separately_from_native_schema():
    payload, request, response = paired()
    assert payload['version'] == ACCOUNT_SOURCE_VERSION
    assert base64.b64decode(payload['request_base64']) == request
    assert base64.b64decode(payload['response_base64']) == response
    assert account_source_bytes(payload) == {'request': request, 'response': response}
    result = derive(sources=[source(payload)])
    assert result['state'] == 'PASS'
    assert result['current_account']['versions'][0]['observations'][0]['slot'] == 1000


@pytest.mark.parametrize('variant', ['missing', 'corrupt', 'wrong-owner', 'executable',
    'null-account', 'unfinalized', 'malformed-slot', 'malformed-lamports', 'caller-pass'])
def test_required_account_failures_remain_dependencies_and_restore(variant):
    valid = source(account())
    dependency = valid['hash']
    bad = deepcopy(valid)
    if variant == 'missing':
        bad['payload'] = None
    elif variant == 'corrupt':
        bad['payload']['result']['value']['lamports'] += 1
    else:
        payload = deepcopy(valid['payload'])
        if variant == 'wrong-owner':
            payload['result']['value']['owner'] = address(30)
        elif variant == 'executable':
            payload['result']['value']['executable'] = True
        elif variant == 'null-account':
            payload['result']['value'] = None
        elif variant == 'unfinalized':
            payload['commitment'] = 'confirmed'
        elif variant == 'malformed-slot':
            payload['result']['context']['slot'] = True
        elif variant == 'malformed-lamports':
            payload['result']['value']['lamports'] = '1000'
        else:
            payload = {'method': 'getAccountInfo', 'address': WALLET, 'commitment': 'finalized',
                       'state': 'PASS', 'identity_verified': True, 'result': {}}
        bad = source(payload)
        dependency = bad['hash']
    result = derive(sources=[bad], dependencies=[dependency])
    assert result['state'] == result['current_account']['state'] == 'UNKNOWN'
    assert result['economic_signer']['state'] == 'PASS'
    assert dependency in result['dependencies']
    assert derive(sources=[valid])['state'] == 'PASS'


@pytest.mark.parametrize('kwargs', [
    {'commitment': 'confirmed'}, {'request_id': 7, 'response_id': '7'},
    {'minimum': 1001, 'slot': 1000}, {'minimum': True},
])
def test_paired_request_contract_and_context_are_not_caller_declarations(kwargs):
    payload, _, _ = paired(**kwargs)
    assert derive(sources=[source(payload)])['current_account']['state'] == 'UNKNOWN'


def test_native_indexed_source_version_cannot_be_repurposed_for_account_info():
    payload, _, _ = paired()
    payload['version'] = 'indexed-native-source-v1'
    linked = source(payload, 'wallet-identity-affinity')
    assert derive(sources=[linked])['state'] == 'UNKNOWN'


@pytest.mark.parametrize('variant', ['missing', 'not-signer', 'unsupported-version',
    'malformed-header', 'signature-count', 'economic-conflict', 'malformed-loaded'])
def test_every_linked_economic_version_must_agree_and_remain_linked(variant):
    selected = record(version=0)
    raw = deepcopy(selected['raw'])
    if variant == 'missing':
        alternative = {'signature': selected['signature'], 'evidence_hash': 'a' * 64, 'raw': None}
    else:
        if variant == 'not-signer':
            keys = raw['transaction']['message']['accountKeys']
            raw['transaction']['message'].pop('header')
            raw['transaction']['message']['accountKeys'] = [
                {'pubkey': key, 'signer': False, 'writable': True} for key in keys]
        elif variant == 'unsupported-version':
            raw['version'] = 1
        elif variant == 'malformed-header':
            raw['transaction']['message']['header']['numRequiredSignatures'] = True
        elif variant == 'signature-count':
            raw['transaction']['signatures'].append(unsigned_signature(12))
        elif variant == 'economic-conflict':
            raw = raw_exchange(selected['signature'], 100, START + 1, 100, 0)
            raw['transaction']['message']['header'] = deepcopy(selected['raw']['transaction']['message']['header'])
        else:
            raw['meta']['loadedAddresses'] = {'writable': [address(80)], 'readonly': []}
        alternative = wrapped(raw)
    result = derive(selected=[selected], alternatives=[alternative])
    assert result['state'] == result['economic_signer']['state'] == 'UNKNOWN'
    assert result['current_account']['state'] == 'PASS'
    assert alternative['evidence_hash'] in result['dependencies']
    missing = {**alternative, 'raw': None}
    assert derive(selected=[selected], alternatives=[missing])['state'] == 'UNKNOWN'
    assert derive(selected=[selected], alternatives=[selected])['state'] == 'PASS'


def test_sponsored_economic_signer_is_supported_without_payer_identity_shortcut():
    raw = record()['raw']
    sponsor = address(21)
    raw['transaction']['message']['accountKeys'].insert(0, sponsor)
    raw['transaction']['message']['header']['numRequiredSignatures'] = 2
    raw['transaction']['signatures'].append(unsigned_signature(13))
    for field in ('preBalances', 'postBalances'):
        raw['meta'][field].insert(0, 10_000_000)
    raw['meta']['postBalances'][0] -= 5000
    raw['meta']['postBalances'][1] += 5000
    for field in ('preTokenBalances', 'postTokenBalances'):
        for balance in raw['meta'][field]:
            balance['accountIndex'] += 1
    assert derive(selected=[wrapped(raw)])['economic_signer']['state'] == 'PASS'


def test_payer_only_or_current_owner_only_cannot_prove_economic_signer():
    raw = record()['raw']
    raw['transaction']['message']['instructions'] = []
    raw['meta']['innerInstructions'] = []
    assert derive(selected=[wrapped(raw)])['economic_signer']['state'] == 'UNKNOWN'
    assert derive(selected=[], sources=[source(account())])['state'] == 'UNKNOWN'


def test_account_conflict_loss_cannot_become_favorable_vote_and_disjoint_metadata_is_irrelevant():
    good, conflict = source(account()), source(account(owner=address(31)))
    frozen = wallet_identity_dependencies([good, conflict], wallet=WALLET)
    assert derive(sources=[good, conflict], dependencies=frozen)['state'] == 'UNKNOWN'
    assert derive(sources=[good], dependencies=frozen)['state'] == 'UNKNOWN'
    assert derive(sources=[good, {**conflict, 'payload': None}], dependencies=frozen)['state'] == 'UNKNOWN'
    assert derive(sources=[good, good], dependencies=[good['hash']])['state'] == 'PASS'
    disjoint = source(account(wallet=MINT, owner=address(32)))
    assert wallet_identity_dependencies([disjoint], wallet=WALLET) == []
    assert derive(sources=[good, disjoint])['state'] == 'PASS'


def test_order_independence_source_annotations_and_input_immutability():
    row = record()
    other = record(signature=unsigned_signature(14))
    first, second = source(account()), source(account(slot=1001), 'classification')
    before = deepcopy((row, other, first, second))
    a = derive(selected=[row, other], alternatives=[other, row], sources=[first, second])
    b = derive(selected=[other, row], alternatives=[row, other], sources=[second, first])
    assert a == b
    assert (row, other, first, second) == before
    assert a['state'] == 'PASS'


def test_forged_pass_affinity_can_only_reduce_certainty():
    negative = source({'state': 'PASS', 'wallet': WALLET, 'economic_signer': True}, 'wallet-identity-affinity')
    result = derive(sources=[source(account()), negative])
    assert result['state'] == 'UNKNOWN'
    assert negative['hash'] in result['dependencies']


@pytest.mark.parametrize('variant', ['wrong-version', 'nested-wrapper', 'typed-malformed', 'typed-missing'])
def test_account_source_affinity_cannot_be_erased_with_role_or_wrapper_changes(variant):
    good = source(account())
    if variant == 'wrong-version':
        payload, _, _ = paired()
        payload['version'] = 'indexed-native-source-v1'
        linked = source(payload, 'classification')
    elif variant == 'nested-wrapper':
        linked = source({'data': [account(owner=address(32))]}, 'valuation')
    elif variant == 'typed-malformed':
        linked = source({'state': 'PASS'}, 'wallet-account-source')
    else:
        linked = {'hash': 'c' * 64, 'kind': 'wallet-account-info', 'payload': None}
    frozen = wallet_identity_dependencies([good, linked], wallet=WALLET)
    assert linked['hash'] in frozen
    assert derive(sources=[good, linked], dependencies=frozen)['state'] == 'UNKNOWN'
    assert derive(sources=[good], dependencies=frozen)['state'] == 'UNKNOWN'


def test_malformed_original_response_checksum_is_retained_and_rejected():
    payload, _, _ = paired()
    payload['response_base64'] = base64.b64encode(b'{"state":"PASS"}').decode()
    linked = source(payload)
    assert derive(sources=[linked])['current_account']['state'] == 'UNKNOWN'
    assert linked['hash'] in derive(sources=[linked])['dependencies']


def test_invalid_outer_signature_shape_cannot_prove_identity():
    raw = record()['raw']
    raw['transaction']['signatures'][0] = 'caller-supplied-PASS'
    result = derive(selected=[wrapped(raw)])
    assert result['economic_signer']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('variant', ['paired', 'paired-alias', 'store-wrapper', 'conflicting', 'malformed'])
def test_saved_archive_identity_loss_restore_preserves_parent_fees_and_offline_scope(tmp_path, monkeypatch, variant):
    import httpx
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    import scanner.app as app_module
    from scanner.archive_input import VERSION as ARCHIVE_VERSION, pack_bytes

    calls = []
    async def denied(*args, **kwargs):
        calls.append('provider')
        raise AssertionError('Offline identity replay cannot dispatch a provider request')
    monkeypatch.setattr(httpx.AsyncClient, 'get', denied)
    monkeypatch.setattr(httpx.AsyncClient, 'post', denied)
    monkeypatch.setattr(app_module, 'Credentials', lambda *_: SimpleNamespace(key=None, storage='none', backend=None))
    row = record()
    raw_payloads = {row['evidence_hash']: row['raw']}
    wrapper = account() if variant == 'store-wrapper' else paired()[0]
    good = source(wrapper, 'wallet-account-source' if variant == 'paired-alias' else 'wallet-account-info')
    accounts = [good]
    if variant == 'conflicting':
        accounts.append(source(account(owner=address(31)), 'wallet-account-info'))
    elif variant == 'malformed':
        accounts.append(source({'state': 'PASS'}, 'wallet-account-info'))
    raw_payloads.update({item['hash']: item['payload'] for item in accounts})
    manifest = {'version': ARCHIVE_VERSION, 'dataset': 'real', 'address': WALLET,
        'window': {'start': START, 'end': START + 86400},
        'transactions': [{'signature': row['signature'], 'hash': row['evidence_hash']}],
        'evidence': [{'kind': item['kind'], 'hash': item['hash']} for item in accounts]}
    # These are unsigned development records in the real input route. They can
    # exercise identity schema, but cannot establish genuine B3 provenance.
    app = app_module.create_app(tmp_path, 'identity-test-token')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        csrf = client.get('/api/bootstrap', headers={'X-Launch-Token': 'identity-test-token'}).json()['csrf']
        client.headers['X-CSRF-Token'] = csrf
        initial_usage = client.get('/api/usage').json()
        response = client.post('/api/archives/import', content=pack_bytes({'manifest': manifest, 'payloads': raw_payloads}),
                               headers={'content-type': 'application/zip'})
        assert response.status_code == 200, response.text
        identifier = response.json()['report_id']
        original = client.get(f'/api/export/reports/{identifier}.json').content
        report = json.loads(original)
        expected = 'UNKNOWN' if variant in ('conflicting', 'malformed') else 'PASS'
        identity = report['coverage']['wallet_evidence']['wallet_identity']
        assert identity['state'] == expected
        assert identity['historical_population_state'] == 'UNKNOWN'
        assert report['qualification']['qualified'] is False
        assert report['metrics']['profit_sol']['status'] == 'unknown'
        assert report['metrics']['observed_network_fees_sol']['value'] == '0.000005'
        lost = accounts[-1]['hash']
        assert client.get(f'/api/evidence/{lost}').status_code == 200
        file = app.state.store.path / 'evidence' / f'{lost}.json.gz'
        saved_bytes = file.read_bytes()
        file.unlink()
        response = client.post(f'/api/reports/{identifier}/rebuild')
        assert response.status_code == 200, response.text
        child_id = response.json()['report_id']
        child = client.get(f'/api/reports/{child_id}').json()
        child_identity = child['coverage']['wallet_evidence']['wallet_identity']
        assert child_identity['state'] == 'UNKNOWN'
        assert lost in child_identity['dependencies']
        assert child['metrics']['observed_network_fees_sol']['value'] == '0.000005'
        assert child['archive_input_hash'] == report['archive_input_hash']
        assert child['preset'] == report['preset']
        file.write_bytes(saved_bytes)
        response = client.post(f'/api/reports/{identifier}/rebuild')
        assert response.status_code == 200, response.text
        restored_id = response.json()['report_id']
        restored = client.get(f'/api/reports/{restored_id}').json()
        assert restored['coverage']['wallet_evidence']['wallet_identity'] == identity
        assert restored['metrics'] == report['metrics']
        assert client.get(f'/api/export/reports/{identifier}.json').content == original
        assert '0.000005' in client.get(f'/api/export/reports/{restored_id}.csv').text
        assert client.get('/api/usage').json() == initial_usage
        assert not calls


@pytest.mark.parametrize('kind', ['wallet-account-info', 'wallet-account-source', 'classification'])
def test_native_conflict_inside_account_byte_envelope_cannot_hide_or_disappear_on_api_rebuild(tmp_path, monkeypatch, kind):
    import httpx
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    import scanner.app as app_module
    from scanner.archive_input import VERSION as ARCHIVE_VERSION, pack_bytes

    async def denied(*args, **kwargs):
        raise AssertionError('No provider calls during archived native-alternative replay')
    monkeypatch.setattr(httpx.AsyncClient, 'post', denied)
    monkeypatch.setattr(httpx.AsyncClient, 'get', denied)
    monkeypatch.setattr(app_module, 'Credentials', lambda *_: SimpleNamespace(key=None, storage='none', backend=None))
    selected = record()
    conflicting = deepcopy(selected['raw'])
    conflicting['meta']['fee'] = 6000
    conflicting['meta']['postBalances'][0] -= 1000
    request = canonical_bytes({'jsonrpc': '2.0', 'id': 7, 'method': 'getTransaction',
        'params': [selected['signature'], {'encoding': 'json', 'commitment': 'finalized',
                                          'maxSupportedTransactionVersion': 0}]})
    response = canonical_bytes({'jsonrpc': '2.0', 'id': 7, 'result': conflicting})
    wrong_method = source(account_info_source(request, response), kind)
    good = source(account(), 'wallet-account-info')
    manifest = {'version': ARCHIVE_VERSION, 'dataset': 'real', 'address': WALLET,
        'window': {'start': START, 'end': START + 86400},
        'transactions': [{'signature': selected['signature'], 'hash': selected['evidence_hash']}],
        'evidence': [{'kind': item['kind'], 'hash': item['hash']} for item in (good, wrong_method)]}
    payloads = {selected['evidence_hash']: selected['raw'],
                good['hash']: good['payload'], wrong_method['hash']: wrong_method['payload']}
    app = app_module.create_app(tmp_path, 'identity-native-alternative-test')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        csrf = client.get('/api/bootstrap', headers={'X-Launch-Token': 'identity-native-alternative-test'}).json()['csrf']
        client.headers['X-CSRF-Token'] = csrf
        response = client.post('/api/archives/import', content=pack_bytes({'manifest': manifest, 'payloads': payloads}),
                               headers={'content-type': 'application/zip'})
        assert response.status_code == 200, response.text
        identifier = response.json()['report_id']
        original = client.get(f'/api/export/reports/{identifier}.json').content
        parent = json.loads(original)
        assert parent['metrics']['observed_network_fees_sol']['status'] == 'unknown'
        assert parent['metrics']['observed_network_fees_sol']['value'] is None
        file = app.state.store.path / 'evidence' / f"{wrong_method['hash']}.json.gz"
        bytes_before = file.read_bytes()
        file.unlink()
        response = client.post(f'/api/reports/{identifier}/rebuild')
        assert response.status_code == 200, response.text
        child = client.get(f"/api/reports/{response.json()['report_id']}").json()
        assert child['metrics']['observed_network_fees_sol']['status'] == 'unknown'
        assert child['metrics']['observed_network_fees_sol']['value'] is None
        file.write_bytes(bytes_before)
        response = client.post(f'/api/reports/{identifier}/rebuild')
        assert response.status_code == 200, response.text
        restored = client.get(f"/api/reports/{response.json()['report_id']}").json()
        assert restored['metrics'] == parent['metrics']
        assert client.get(f'/api/export/reports/{identifier}.json').content == original
