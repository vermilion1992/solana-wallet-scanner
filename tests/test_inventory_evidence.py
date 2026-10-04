"""Current inventory admission; development controls cannot establish B3.

Three genuine retained requests independently establish actual archived
balances/enumerations at distinct context slots. The separately authored same-
slot unsigned controls test implementation only, never historical completeness.
"""
from copy import deepcopy
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest

from scanner.archive_input import pack_bytes, validate_manifest
from scanner.accounting import utc
from scanner.decoder import SYSTEM_ID
from scanner.inventory_evidence import (AFFINITY_VERSION, SOURCE_VERSION, VERSION,
    derive_inventory_evidence, inventory_request_affinities, inventory_source, inventory_source_bytes)
from scanner.json_boundary import canonical_bytes
from scanner.providers import TOKEN_PROGRAM, TOKEN_2022_PROGRAM
from tests.test_position_evidence import address
from tests.test_indexed_report_integration import guarded
from tests.test_discovery_integration_review import session, isolate_credentials_and_transport

WALLET = '2Bj3dZTSSc14hFR9fCLN9CQ1TiaYyszCKX8fuVG7pyAY'
WINDOW = {'start': '2026-09-04T06:00:00+00:00', 'end': '2026-10-04T06:00:00+00:00'}
GENUINE = Path(__file__).resolve().parents[1] / 'evidence/genuine-wallet-batch/collection/phase6'
PROGRAMS = (TOKEN_PROGRAM, TOKEN_2022_PROGRAM)
INPUTS = (
    ('01-current-wallet-account', '9663e32ba0a8d1dea45b79bcc872999ca5a52977e7bfe5d7712df8eb036d85dd',
     'feabb86540e5c606f765d034aa523643e4c469744e4d2ef684e2b1e04c673ebd'),
    ('02-current-legacy-accounts', 'ed44f19d919499ac45424e0f40d47ace46bb373d278983e766119b994f341704',
     '0842531d6a0f6d49937d9b314bd13096320d52543ff13839861640ade28728e4'),
    ('03-current-token2022-accounts', '91a6efe9c3137ca8a8d1f805d3ecafe4447ef1bb16ec7ad9c5f968940780ab90',
     '6497a39b1f7f34f1c054ef140473300762dd9f5c3fd2017b4318d755ffae0d3e'),
)


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def source(payload, kind='inventory-source'):
    return {'kind': kind, 'hash': digest(payload), 'payload': payload}


def frozen(sources):
    return list(sources) + [source(value, 'inventory-affinity')
        for value in inventory_request_affinities(sources, wallet=WALLET)]


def derive(sources):
    return derive_inventory_evidence(sources, wallet=WALLET, window=WINDOW)


def genuine_sources():
    rows = []
    for name, request_hash, response_hash in INPUTS:
        request = (GENUINE / (name + '-request.json')).read_bytes()
        response = gzip.decompress((GENUINE / (name + '-response.raw.gz')).read_bytes())
        assert hashlib.sha256(request).hexdigest() == request_hash
        assert hashlib.sha256(response).hexdigest() == response_hash
        payload = inventory_source(request, response)
        assert inventory_source_bytes(payload) == {'request': request, 'response': response}
        rows.append(source(payload))
    return rows


def paired(method, value, *, program=None, slot=100, minimum=99, wallet=WALLET, ident=7):
    options = {'commitment': 'finalized', 'minContextSlot': minimum}
    if method != 'getBalance':
        options['encoding'] = 'jsonParsed'
    params = [wallet, options] if method != 'getTokenAccountsByOwner' else [wallet, {'programId': program}, options]
    request = json.dumps({'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params}, indent=2).encode() + b'\n'
    response = json.dumps({'jsonrpc': '2.0', 'id': ident, 'result': {'context': {'slot': slot}, 'value': value}}, indent=1).encode() + b'\n'
    return inventory_source(request, response)


def token(seed, amount, *, program=TOKEN_PROGRAM, mint=None, decimals=6, wallet=WALLET):
    return {'pubkey': address(seed), 'account': {'owner': program, 'executable': False, 'lamports': 2039280,
        'data': {'parsed': {'type': 'account', 'info': {'mint': mint or address(61), 'owner': wallet,
            'state': 'initialized', 'isNative': False,
            'tokenAmount': {'amount': str(amount), 'decimals': decimals, 'uiAmount': None}}},
            'program': 'spl-token' if program == TOKEN_PROGRAM else 'spl-token-2022'}}}


def snapshots(*, slot=100):
    return [source(paired('getAccountInfo', {'owner': SYSTEM_ID, 'executable': False,
        'lamports': 1500, 'data': ['', 'base64']}, slot=slot)),
        source(paired('getBalance', 1500, slot=slot)),
        source(paired('getTokenAccountsByOwner', [token(62, 2), token(63, 3)], program=TOKEN_PROGRAM, slot=slot)),
        source(paired('getTokenAccountsByOwner', [token(64, 7, program=TOKEN_2022_PROGRAM, mint=address(65))],
                      program=TOKEN_2022_PROGRAM, slot=slot))]


def edit(row, *, request=None, response=None, **outer):
    raw = inventory_source_bytes(row['payload'])
    req, res = json.loads(raw['request']), json.loads(raw['response'])
    if request:
        request(req)
    if response:
        response(res)
    payload = inventory_source(json.dumps(req).encode(), json.dumps(res).encode())
    payload.update(outer)
    return source(payload, row['kind'])


def test_genuine_original_component_observations_remain_distinct_from_report_boundaries():
    result = derive(frozen(genuine_sources()))
    components = result['components']
    assert result['version'] == VERSION
    native = components['native_account']
    assert native['state'] == 'PASS'
    assert native['observations'][0]['slot'] == 453173211
    assert native['observations'][0]['lamports'] == '650240'
    legacy, token22 = (components['token_programs'][program] for program in PROGRAMS)
    assert legacy['state'] == token22['state'] == 'PASS'
    assert legacy['observations'][0]['slot'] == 453173213
    assert legacy['observations'][0]['account_count'] == 0
    account = token22['observations'][0]['accounts'][0]
    assert token22['observations'][0]['slot'] == 453173215
    assert account['account'] == '8VfvwKKWB7gUzQ5zvAyYe7qUj7Ujo1Su2XCjx1GXL6Sw'
    assert account['quantity_raw'] == '0' and account['decimals'] == 6
    assert account['account_lamports'] == '1513840'
    assert components['same_slot_inventory']['state'] == components['report_boundaries']['state'] == 'UNKNOWN'
    assert result['historical_population_state'] == result['valuation_state'] == result['external_flow_state'] == 'UNKNOWN'
    assert result['qualification'] is False
    assert result['provider_requests'] == result['credential_lookups'] == 0


def test_unsigned_same_slot_aggregate_uses_raw_multiaccount_quantities_and_never_values_account_lamports():
    result = derive(frozen(snapshots()))
    combined = result['components']['same_slot_inventory']
    assert combined['state'] == 'PASS'
    point = combined['observations'][0]
    assert point['slot'] == 100 and point['native_lamports'] == '1500' and point['account_count'] == 3
    assert {row['mint']: row['quantity_raw'] for row in point['mint_totals']} == {address(61): '5', address(65): '7'}
    assert all('price_sol' not in row for row in point['mint_totals'])
    assert result['components']['report_boundaries']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('failure', ['missing', 'corrupt-wrapper', 'malformed-row', 'wrong-program', 'wrong-owner',
    'duplicate-account', 'bad-mint', 'bad-decimals', 'bad-raw-units', 'bad-native-mode', 'bool-lamports', 'caller-pass'])
def test_required_program_failures_revoke_that_component_preserve_independent_native_and_restore(failure):
    good = snapshots()
    changed = deepcopy(good)
    target = changed[-1]
    if failure == 'missing':
        target['payload'] = None
    elif failure == 'corrupt-wrapper':
        target['payload']['response_hash'] = '0' * 64
    elif failure == 'caller-pass':
        target.update(edit(good[-1], complete=True, state='PASS', trusted_positions=[]))
    else:
        def change(response):
            rows = response['result']['value']
            row = rows[0]
            info = row['account']['data']['parsed']['info']
            if failure == 'malformed-row': rows.append(None)
            elif failure == 'wrong-program': row['account']['owner'] = TOKEN_PROGRAM
            elif failure == 'wrong-owner': info['owner'] = address(70)
            elif failure == 'duplicate-account': rows.append(deepcopy(row))
            elif failure == 'bad-mint': info['mint'] = 'unsupported'
            elif failure == 'bad-decimals': info['tokenAmount']['decimals'] = True
            elif failure == 'bad-raw-units': info['tokenAmount']['amount'] = str(2**64)
            elif failure == 'bad-native-mode': info['isNative'] = []
            elif failure == 'bool-lamports': row['account']['lamports'] = False
        target.update(edit(good[-1], response=change))
    # Preserve the actual rejected variant's request affinity. A corrupt/missing
    # original instead retains its frozen original selector.
    links = frozen(good) if failure in ('missing', 'corrupt-wrapper') else frozen(changed)
    links = [row for row in links if row['kind'] == 'inventory-affinity']
    result = derive(changed + links)['components']
    assert result['token_programs'][TOKEN_2022_PROGRAM]['state'] == 'UNKNOWN'
    assert result['token_programs'][TOKEN_PROGRAM]['state'] == 'PASS'
    assert result['native_account']['state'] == result['native_balance']['state'] == 'PASS'
    assert result['same_slot_inventory']['state'] == 'UNKNOWN'
    assert derive(frozen(good))['components']['same_slot_inventory']['state'] == 'PASS'


@pytest.mark.parametrize('failure', ['request-id', 'response-id-type', 'unfinalized', 'bool-floor', 'under-floor',
    'mint-filter', 'data-slice', 'wrong-wallet', 'caller-request-flags', 'response-error', 'duplicate-json-key'])
def test_strict_rpc_request_response_contract_rejects_flags_filters_and_context_shortcuts(failure):
    good = snapshots()
    target = good[-1]
    req, res = (json.loads(raw) for raw in inventory_source_bytes(target['payload']).values())
    if failure == 'request-id': req['id'] = True; res['id'] = True
    elif failure == 'response-id-type': res['id'] = str(req['id'])
    elif failure == 'unfinalized': req['params'][-1]['commitment'] = 'confirmed'
    elif failure == 'bool-floor': req['params'][-1]['minContextSlot'] = True
    elif failure == 'under-floor': req['params'][-1]['minContextSlot'] = 101
    elif failure == 'mint-filter': req['params'][1] = {'mint': address(65)}
    elif failure == 'data-slice': req['params'][-1]['dataSlice'] = {'offset': 0, 'length': 0}
    elif failure == 'wrong-wallet': req['params'][0] = address(70)
    elif failure == 'caller-request-flags': req['complete'] = True
    elif failure == 'response-error': res = {'jsonrpc': '2.0', 'id': req['id'], 'error': {'code': -1}}
    request = json.dumps(req).encode()
    if failure == 'duplicate-json-key': request = request.replace(b'"method":', b'"method":"getBalance","method":')
    broken = source(inventory_source(request, json.dumps(res).encode()))
    # A query for a different wallet does not fill this wallet's required census.
    result = derive(frozen(good[:-1] + [broken]))['components']
    assert result['token_programs'][TOKEN_2022_PROGRAM]['state'] == 'UNKNOWN'
    assert result['same_slot_inventory']['state'] == 'UNKNOWN'
    assert result['report_boundaries']['state'] == 'UNKNOWN'


def test_same_slot_disagreement_cannot_be_outvoted_and_required_conflict_loss_cannot_promote():
    good = snapshots()
    conflict = edit(good[-1], response=lambda res: res['result']['value'][0]['account']['data']['parsed']['info']['tokenAmount'].update(amount='8'))
    first = frozen(good + [conflict])
    for ordered in (first, list(reversed(first)), first + [good[-1], good[-1]]):
        result = derive(ordered)['components']
        assert result['token_programs'][TOKEN_2022_PROGRAM]['state'] == 'UNKNOWN'
        assert result['token_programs'][TOKEN_2022_PROGRAM]['conflicting_slots'] == [100]
        assert result['same_slot_inventory']['state'] == 'UNKNOWN'
    missing = deepcopy(first)
    next(row for row in missing if row['hash'] == conflict['hash'])['payload'] = None
    result = derive(missing)['components']
    assert result['token_programs'][TOKEN_2022_PROGRAM]['state'] == 'UNKNOWN'
    assert result['native_account']['state'] == 'PASS'
    assert derive(first)['components']['same_slot_inventory']['state'] == 'UNKNOWN'


def test_same_slot_native_disagreement_and_cross_program_identity_do_not_create_equity():
    good = snapshots()
    conflict = edit(good[1], response=lambda res: res['result'].update(value=1501))
    result = derive(frozen(good + [conflict]))['components']
    assert result['native_lamports']['state'] == result['same_slot_inventory']['state'] == 'UNKNOWN'
    # Each admitted native observation remains inspectable even when another
    # native source disagrees; the aggregate does not choose an arrival winner.
    assert result['native_account']['state'] == 'PASS'
    wrong_mint = edit(good[-1], response=lambda res: res['result']['value'][0]['account']['data']['parsed']['info'].update(mint=address(61)))
    result = derive(frozen(good[:-1] + [wrong_mint]))['components']
    assert result['token_programs'][TOKEN_2022_PROGRAM]['state'] == 'PASS'
    assert result['same_slot_inventory']['state'] == 'UNKNOWN'


def test_enumeration_permutation_and_duplicate_source_declarations_are_independent_of_amount_display_fields():
    good = snapshots()
    permuted = edit(good[2], response=lambda res: res['result']['value'].reverse())
    result = derive(frozen(good + [permuted] + good))['components']
    assert result['token_programs'][TOKEN_PROGRAM]['state'] == 'PASS'
    assert result['same_slot_inventory']['state'] == 'PASS'


def test_mislabelled_nested_inventory_dependency_is_frozen_and_remains_negative_after_loss():
    good = snapshots()
    nested = source({'advisory': {'original': good[-1]['payload']}}, 'classification')
    inputs = frozen(good + [nested])
    initial = derive(inputs)['components']
    assert initial['token_programs'][TOKEN_2022_PROGRAM]['state'] == 'UNKNOWN'
    assert initial['native_account']['state'] == 'PASS'
    next(row for row in inputs if row['hash'] == nested['hash'])['payload'] = None
    after = derive(inputs)['components']
    assert after['token_programs'][TOKEN_2022_PROGRAM]['state'] == 'UNKNOWN'
    assert after['native_account']['state'] == 'PASS'


def test_invalid_containing_checksum_cannot_supply_convenient_disjoint_wallet_scope():
    good = snapshots()
    disjoint = source(paired('getBalance', 1, wallet=address(70)))
    assert derive(frozen(good + [disjoint]))['components']['same_slot_inventory']['state'] == 'PASS'
    invalid = {**disjoint, 'hash': '0' * 64}
    result = derive(frozen(good + [invalid]))['components']
    assert result['same_slot_inventory']['state'] == 'UNKNOWN'
    assert all(result[key]['state'] == 'UNKNOWN' for key in ('native_account', 'native_balance'))
    assert '0' * 64 in result['native_account']['evidence']


def test_internal_affinity_is_only_a_negative_selector_and_public_manifest_role_is_rejected():
    good = snapshots()
    affinities = frozen(good)[len(good):]
    result = derive(affinities)['components']
    assert result['native_account']['state'] == result['same_slot_inventory']['state'] == 'UNKNOWN'
    assert result['native_account']['observations'] == []
    manifest = {'version': 'archived-wallet-input-v1', 'dataset': 'real', 'address': WALLET, 'window': WINDOW,
        'transactions': [{'signature': 'bounded-interface-signature', 'hash': '0'*64}],
        'evidence': [{'kind': 'inventory-affinity', 'hash': affinities[0]['hash']}]}
    with pytest.raises(ValueError, match='derived internally'):
        validate_manifest(manifest)


def test_forged_frozen_request_cannot_turn_missing_required_original_into_foreign_exclusion():
    good = snapshots()
    inputs = frozen(good)
    target = good[-1]['hash']
    affinity_row = next(row for row in inputs if row['kind'] == 'inventory-affinity' and row['payload']['source_hash'] == target)
    foreign = paired('getTokenAccountsByOwner', [], program=TOKEN_2022_PROGRAM, wallet=address(70))
    changed = deepcopy(affinity_row['payload'])
    changed['source_preimage_base64'] = base64.b64encode(canonical_bytes(foreign)).decode('ascii')
    # The purported negative selector has its own valid archive checksum, but
    # does not match the canonical original source preimage bound to target.
    inputs = [row for row in inputs if row is not affinity_row]
    next(row for row in inputs if row['hash'] == target)['payload'] = None
    inputs.append(source(changed, 'inventory-affinity'))
    assert derive(inputs)['components']['same_slot_inventory']['state'] == 'UNKNOWN'
    assert derive(inputs)['components']['token_programs'][TOKEN_2022_PROGRAM]['state'] == 'UNKNOWN'


def genuine_bundle():
    raw = json.loads(gzip.decompress((GENUINE / '04-selected-buy-response.raw.gz').read_bytes()))['result']
    selected = {'signature': raw['transaction']['signatures'][0], 'hash': digest(raw)}
    snapshots = genuine_sources()
    # Deliberately misleading role: the internal request affinity must route
    # Token-2022 loss accurately instead of forgetting or poisoning native SOL.
    snapshots[-1]['kind'] = 'classification'
    return {'manifest': {'version': 'archived-wallet-input-v1', 'dataset': 'real', 'address': WALLET,
        'window': WINDOW, 'transactions': [selected],
        'evidence': [{'kind': row['kind'], 'hash': row['hash']} for row in snapshots]},
        'payloads': {selected['hash']: raw, **{row['hash']: row['payload'] for row in snapshots}}}, snapshots


def genuine87_inventory_bundle():
    """Separate augmented input; no mutation of the original indexed archive."""
    from scanner.indexed_input import convert_indexed_archive
    path = GENUINE.parent.parent / 'checker-inputs/final-indexed-input.zip'
    original = path.read_bytes()
    assert hashlib.sha256(original).hexdigest() == 'eec702fdd821066897710d2085bf5c39380e303e8426249e22fb6379b7ccf1b4'
    converted = convert_indexed_archive(original)
    with zipfile.ZipFile(io.BytesIO(converted)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        payloads = {Path(name).name.removesuffix('.json.gz'): json.loads(gzip.decompress(archive.read(name)))
                    for name in archive.namelist() if name.startswith('archives/')}
    rows = genuine_sources()
    manifest['evidence'] += [{'kind': row['kind'], 'hash': row['hash']} for row in rows]
    payloads.update({row['hash']: row['payload'] for row in rows})
    assert path.read_bytes() == original
    return {'manifest': manifest, 'payloads': payloads}, rows


def test_normal_genuine_archive_inspection_exports_immutable_rebuild_loss_and_restoration(guarded):
    from tests.test_indexed_report_integration import import_report, rebuild
    client, app, directory, calls = guarded
    bundle, sources = genuine_bundle()
    report = import_report(client, pack_bytes(bundle))
    parent = deepcopy(app.state.store.get('reports', report['id']))
    inventory = report['coverage']['wallet_evidence']['inventory_observations']
    assert inventory['components']['native_account']['observations'][0]['lamports'] == '650240'
    assert inventory['components']['token_programs'][TOKEN_2022_PROGRAM]['state'] == 'PASS'
    assert inventory['components']['report_boundaries']['state'] == 'UNKNOWN'
    assert report['metrics']['profit_sol']['status'] == 'unknown'
    fee = report['metrics']['observed_network_fees_sol']
    assert fee['status'] == 'known' and fee['value'] == '0.000058918'
    identifier = sources[-1]['hash']
    inspection = client.get('/api/evidence/' + identifier)
    assert inspection.status_code == 200
    assert inventory_source_bytes(inspection.json()) == inventory_source_bytes(sources[-1]['payload'])
    exported = client.get('/api/export/reports/' + report['id'] + '.json')
    assert exported.status_code == 200
    assert exported.json()['coverage']['wallet_evidence']['inventory_observations'] == inventory
    assert client.get('/api/export/reports/' + report['id'] + '.csv').status_code == 200
    child = rebuild(client, report)
    assert child['coverage']['wallet_evidence']['inventory_observations'] == inventory
    dependency = app.state.store.evidence(report['archive_dependency_input_hash'])
    assert dependency['version'] == 'archive-native-dependencies-v4' and dependency['inventory_affinity_hashes']
    path = directory / 'evidence' / f'{identifier}.json.gz'
    original = path.read_bytes()
    path.unlink()
    missing = rebuild(client, report)
    after = missing['coverage']['wallet_evidence']['inventory_observations']['components']
    assert after['token_programs'][TOKEN_2022_PROGRAM]['state'] == 'UNKNOWN'
    assert after['native_account']['state'] == after['token_programs'][TOKEN_PROGRAM]['state'] == 'PASS'
    assert missing['metrics']['observed_network_fees_sol'] == fee
    path.write_bytes(original)
    restored = rebuild(client, missing)
    assert restored['coverage']['wallet_evidence']['inventory_observations'] == inventory
    assert app.state.store.get('reports', report['id']) == parent
    assert calls == {'provider': 0, 'credential': 0, 'transport': 0}


def test_public_internal_affinity_payload_cannot_be_smuggled_under_another_role(tmp_path):
    from scanner.archive_input import import_archive
    from scanner.storage import Store
    bundle, rows = genuine_bundle()
    affinity = inventory_request_affinities(rows, wallet=WALLET)[0]
    assert affinity['version'] == AFFINITY_VERSION
    identifier = digest(affinity)
    bundle['payloads'][identifier] = affinity
    bundle['manifest']['evidence'].append({'kind': 'classification', 'hash': identifier})
    with pytest.raises(ValueError, match='derived internally'):
        import_archive(Store(tmp_path), pack_bytes(bundle))


def test_genuine87_augmented_normal_report_preserves_exact_fee_losing_lot_and_current_only_inventory(guarded):
    from tests.test_indexed_report_integration import import_report
    client, _, _, calls = guarded
    bundle, snapshots = genuine87_inventory_bundle()
    report = import_report(client, pack_bytes(bundle))
    assert report['metrics']['observed_network_fees_sol']['status'] == 'known'
    assert report['metrics']['observed_network_fees_sol']['value'] == '0.000158868'
    wallet = report['coverage']['wallet_evidence']
    lot = next(row for row in wallet['query_accounting']['supported_selected_lots']
               if row['mint'] == 'BQJfL1yiHbJQ8AciHLcKxaCbQrWP2ws8oZHHYgbBpump' and row['monetary_state'] == 'PASS')
    assert lot['conditional_lot_profit_sol'] == '-0.013270924'
    assert lot['timing_state'] == 'PASS'
    assert (utc(lot['observed_end']) - utc(lot['observed_start'])).total_seconds() == 529
    inventory = wallet['inventory_observations']['components']
    assert inventory['native_account']['state'] == 'PASS'
    assert inventory['native_account']['observations'][0]['lamports'] == '650240'
    assert all(inventory['token_programs'][program]['state'] == 'PASS' for program in PROGRAMS)
    assert inventory['same_slot_inventory']['state'] == inventory['report_boundaries']['state'] == 'UNKNOWN'
    assert wallet['components']['boundary_inventory']['state'] == wallet['components']['historical_population']['state'] == 'UNKNOWN'
    assert report['metrics']['profit_sol']['status'] == report['metrics']['economic_pnl_sol']['status'] == 'unknown'
    for row in snapshots:
        assert inventory_source_bytes(client.get('/api/evidence/' + row['hash']).json()) == inventory_source_bytes(row['payload'])
    assert calls == {'provider': 0, 'credential': 0, 'transport': 0}


@pytest.mark.parametrize('label', ['inventory-source', 'owned-accounts', 'classification'])
def test_inventory_byte_envelope_cannot_hide_a_native_fee_alternative_by_source_label(tmp_path, label):
    from scanner.archive_input import import_archive, load_archive, decode_archive, analyze_archive
    from scanner.storage import Store
    bundle, _rows = genuine_bundle()
    selected = bundle['manifest']['transactions'][0]
    raw = deepcopy(bundle['payloads'][selected['hash']])
    raw['meta']['fee'] += 1
    request = {'jsonrpc': '2.0', 'id': 8, 'method': 'getTransaction',
               'params': [selected['signature'], {'commitment': 'finalized', 'encoding': 'jsonParsed'}]}
    response = {'jsonrpc': '2.0', 'id': 8, 'result': raw}
    alternate = source(inventory_source(json.dumps(request).encode(), json.dumps(response).encode()), label)
    assert alternate['payload']['version'] == SOURCE_VERSION
    bundle['manifest']['evidence'].append({'kind': label, 'hash': alternate['hash']})
    bundle['payloads'][alternate['hash']] = alternate['payload']
    store = Store(tmp_path)
    identifier = import_archive(store, pack_bytes(bundle))
    loaded = load_archive(store, identifier)
    events, _ = decode_archive(loaded)
    result, _, receipts = analyze_archive(loaded, events)
    assert result['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    assert receipts['wallet_evidence']['components']['native_fee']['state'] == 'UNKNOWN'
    original = (store.path / 'evidence' / f"{alternate['hash']}.json.gz").read_bytes()
    (store.path / 'evidence' / f"{alternate['hash']}.json.gz").unlink()
    loaded = load_archive(store, identifier)
    events, _ = decode_archive(loaded)
    result, _, _ = analyze_archive(loaded, events)
    assert result['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    (store.path / 'evidence' / f"{alternate['hash']}.json.gz").write_bytes(original)
    loaded = load_archive(store, identifier)
    events, _ = decode_archive(loaded)
    result, _, _ = analyze_archive(loaded, events)
    assert result['metrics']['observed_network_fees_sol']['status'] == 'unknown'


def test_native_frozen_inputs_replay_inventory_loss_without_altering_independent_fee_or_parent(tmp_path):
    import scanner.app as application
    from scanner.report_rebuild import freeze_report_inputs
    from scanner.storage import Store
    from scanner.wallet_evidence import derive_wallet_evidence
    bundle, snapshots = genuine_bundle()
    store = Store(tmp_path)
    for payload in bundle['payloads'].values():
        store.archive(payload)
    selected = bundle['manifest']['transactions'][0]
    collected = {'transactions': [{'signature': selected['signature'], 'evidence_hash': selected['hash']}],
                 'evidence': deepcopy(bundle['manifest']['evidence'])}
    frozen_inputs, *_ = application._freeze_native_dependencies(store, collected, address=WALLET, window=WINDOW)
    assert any(ref['kind'] == 'inventory-affinity' for ref in frozen_inputs['evidence'])
    identifier = freeze_report_inputs(store, WALLET, WINDOW, frozen_inputs)
    parent = deepcopy(store.evidence(identifier))
    def replay():
        primary, linked, raw_sources, receipts = application._wallet_adapter_inputs(store,
            {**store.evidence(identifier), 'frozen_input_hash': identifier}, address=WALLET, window=WINDOW)
        return derive_wallet_evidence(primary, all_records=linked, wallet=WALLET, window=WINDOW,
            raw_sources=raw_sources, source_receipts=receipts, source_consistency={}, chronology={})
    before = replay()
    assert before['inventory_observations']['components']['token_programs'][TOKEN_2022_PROGRAM]['state'] == 'PASS'
    assert before['components']['native_fee']['state'] == 'PASS'
    path = store.path / 'evidence' / f"{snapshots[-1]['hash']}.json.gz"
    original = path.read_bytes()
    path.unlink()
    missing = replay()
    assert missing['inventory_observations']['components']['token_programs'][TOKEN_2022_PROGRAM]['state'] == 'UNKNOWN'
    assert missing['inventory_observations']['components']['native_account']['state'] == 'PASS'
    assert missing['components']['native_fee']['state'] == 'PASS'
    path.write_bytes(original)
    assert replay()['inventory_observations'] == before['inventory_observations']
    assert store.evidence(identifier) == parent
