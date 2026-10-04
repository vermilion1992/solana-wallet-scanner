"""Small role-to-existing-ledger checks; no synthetic genuine-wallet acceptance."""
from copy import deepcopy
from contextlib import closing
from pathlib import Path

from scanner.cost_flow_evidence import project_cost_flow_evidence
from scanner.decoder import SYSTEM_ID, decode_transactions
from scanner.wallet_evidence import _decoded_native_movement, _native_role_check
from scanner.providers import TOKEN_PROGRAM
from scanner.investigation import WSOL
from test_wallet_evidence import ACCOUNT, WALLET, base, creation, derive, parsed, record
from test_position_evidence import address


def wrapped_funding():
    raw = primary(base('wrapped-principal'))
    account = raw['transaction']['message']['accountKeys'][2]
    for phase, quantity in (('preTokenBalances', 1_000_000_000), ('postTokenBalances', 1_000_001_000)):
        row = next(row for row in raw['meta'][phase] if row['accountIndex'] == 2)
        row['uiTokenAmount']['amount'] = str(quantity)
    raw['meta']['preBalances'][2] = 1_002_000_000
    raw['meta']['postBalances'][2] = 1_002_001_000
    raw['meta']['postBalances'][0] -= 1000
    raw['transaction']['message']['instructions'] = [
        parsed('transfer', {'source': WALLET, 'destination': account, 'lamports': 1000}, SYSTEM_ID),
        parsed('syncNative', {'account': account})]
    return raw, account


def encode(data):
    """Independent test conversion; byte layouts below are pinned literals."""
    value = int.from_bytes(data, 'big')
    output = ''
    while value:
        value, remainder = divmod(value, 58)
        output = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'[remainder] + output
    return '1' * (len(data) - len(data.lstrip(b'\0'))) + output


def primary(raw):
    keys = raw['transaction']['message']['accountKeys']
    for key in (SYSTEM_ID, TOKEN_PROGRAM):
        if key not in keys:
            keys.append(key)
            raw['meta']['preBalances'].append(1)
            raw['meta']['postBalances'].append(1)
    raw['transaction']['message']['header'] = {
        'numRequiredSignatures': 1, 'numReadonlySignedAccounts': 0, 'numReadonlyUnsignedAccounts': 2}
    return raw


def project(raw, alternatives=()):
    parent = deepcopy(raw)
    selected = record(raw)
    evidence = derive([raw], alternatives=alternatives)
    generic = decode_transactions([selected], WALLET)['events']
    result = project_cost_flow_evidence(selected={selected['signature']: selected},
        raw_versions={selected['signature']: [selected] + list(alternatives)},
        transactions=evidence['transactions'], consistency=evidence['source_consistency'],
        ledger_events=generic, wallet=WALLET)
    assert raw == parent
    assert result['provider_requests'] == result['credential_lookups'] == 0
    assert result['qualification'] is False
    return result, selected


def test_wallet_owned_creation_enters_existing_ledger_as_internal_movement_and_fee_once():
    result, selected = project(primary(creation()))
    row = result['transactions']['synthetic-operation']
    assert row['check']['state'] == 'PASS'
    assert row['admitted_internal_roles'][0]['role'] == 'wallet_owned_account_funding'
    assert row['admitted_internal_roles'][0]['lamports'] == '2000000'
    assert [event['kind'] for event in result['ledger_events']] == ['fee', 'internal_transfer']
    expected = _decoded_native_movement(result['ledger_events'])
    assert expected == -5000
    assert _native_role_check(selected, WALLET, expected)['state'] == 'PASS'
    assert row['wallet_population_state'] == 'UNKNOWN'


def test_wallet_owned_zero_token_closure_is_refund_not_income_or_fee():
    raw = primary(base())
    raw['meta']['postTokenBalances'] = [r for r in raw['meta']['postTokenBalances'] if r['accountIndex'] != 1]
    raw['meta']['postBalances'][1] = 0
    raw['meta']['postBalances'][0] += 2_000_000
    raw['transaction']['message']['instructions'] = [parsed('closeAccount', {
        'account': ACCOUNT, 'destination': WALLET, 'owner': WALLET})]
    result, selected = project(raw)
    assert result['transactions']['synthetic-operation']['admitted_internal_roles'][0]['role'] == 'wallet_owned_account_refund'
    assert [event['kind'] for event in result['ledger_events']] == ['fee', 'internal_transfer']
    assert _native_role_check(selected, WALLET, _decoded_native_movement(result['ledger_events']))['state'] == 'PASS'


def test_existing_token_owner_alone_cannot_prove_refund_rights_for_top_up():
    raw = primary(base(quantity=100))
    raw['meta']['postBalances'][0] -= 1000
    raw['meta']['postBalances'][1] += 1000
    raw['transaction']['message']['instructions'] = [parsed('transfer', {
        'source': WALLET, 'destination': ACCOUNT, 'lamports': 1000}, SYSTEM_ID)]
    result, selected = project(raw)
    assert result['ledger_events'][-1]['kind'] == 'capital'
    assert not result['transactions']['synthetic-operation']['admitted_internal_roles']
    assert _decoded_native_movement(result['ledger_events']) is None
    assert raw['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] == '100'


def test_external_transfers_keep_unknown_role_even_when_gross_sides_cancel():
    raw = primary(base())
    other = raw['transaction']['message']['accountKeys'][3]
    raw['transaction']['message']['header']['numRequiredSignatures'] = 4
    raw['transaction']['message']['instructions'] = [
        parsed('transfer', {'source': WALLET, 'destination': other, 'lamports': 1000}, SYSTEM_ID),
        parsed('transfer', {'source': other, 'destination': WALLET, 'lamports': 1000}, SYSTEM_ID)]
    result, _ = project(raw)
    assert [event['kind'] for event in result['ledger_events']] == ['fee', 'capital', 'capital']
    assert _decoded_native_movement(result['ledger_events']) is None
    assert result['transactions']['synthetic-operation']['admitted_internal_roles'] == []


def test_required_alternative_loss_conflict_and_exact_restoration_do_not_mutate_parent():
    raw = primary(creation())
    alternative = deepcopy(raw)
    alternative['meta']['logMessages'] = ['Independent optional receipt field']
    link = record(alternative)
    parent, _ = project(raw, [link])
    frozen = deepcopy(parent)
    lost, _ = project(raw, [{**link, 'raw': None}])
    assert lost['transactions']['synthetic-operation']['check']['state'] == 'UNKNOWN'
    assert lost['ledger_events'][-1]['kind'] == 'rent'
    conflict = deepcopy(raw)
    conflict['transaction']['message']['instructions'][0]['parsed']['info']['lamports'] += 1
    conflicting, _ = project(raw, [record(conflict)])
    assert conflicting['transactions']['synthetic-operation']['check']['state'] == 'UNKNOWN'
    assert conflicting['ledger_events'][-1]['kind'] == 'rent'
    restored, _ = project(raw, [link])
    assert restored == parent == frozen


def test_foreign_owner_missing_signer_or_malformed_admin_preserves_independent_fee():
    raw = primary(creation())
    for variant in ('foreign-owner', 'missing-signers', 'boolean-lamports', 'close-authority-override'):
        broken = deepcopy(raw)
        if variant == 'foreign-owner':
            broken['meta']['postTokenBalances'][0]['owner'] = address(40)
        elif variant == 'missing-signers':
            broken['transaction']['message'].pop('header')
        elif variant == 'boolean-lamports':
            broken['transaction']['message']['instructions'][0]['parsed']['info']['lamports'] = True
        else:
            broken['transaction']['message']['instructions'].append(parsed('setAuthority', {
                'account': ACCOUNT, 'authorityType': 'closeAccount', 'authority': WALLET,
                'newAuthority': address(40)}))
        result, _ = project(broken)
        assert result['transactions']['synthetic-operation']['check']['state'] == 'UNKNOWN'
        assert any(event['kind'] == 'rent' for event in result['ledger_events'])
        assert result['ledger_events'][0]['kind'] == 'fee' and result['ledger_events'][0]['amount_sol'] == '0.000005'


def test_failed_administration_adds_no_roles_and_keeps_only_actual_fee():
    raw = primary(creation())
    raw['meta']['err'] = {'InstructionError': [0, 'Custom']}
    raw['meta']['postBalances'] = list(raw['meta']['preBalances'])
    raw['meta']['postBalances'][0] -= 5000
    raw['meta']['postTokenBalances'] = deepcopy(raw['meta']['preTokenBalances'])
    result, _ = project(raw)
    assert [event['kind'] for event in result['ledger_events']] == ['fee']
    assert result['transactions']['synthetic-operation']['admitted_internal_roles'] == []
    assert _decoded_native_movement(result['ledger_events']) == -5000


def test_retained_genuine_compiled_account_creation_admits_exact_funding_without_completeness(tmp_path):
    from scanner.archive_input import import_archive, load_archive
    from scanner.storage import Store
    from scanner.wallet_evidence import derive_wallet_evidence

    root = Path(__file__).resolve().parents[1]
    source = root / 'evidence/genuine-report-speed-batch/checker-inputs/genuine87-inventory-input.zip'
    signature = '5aQQmDSXeVhmReZuDuHHthRkdjPgDmCSEty8FJLByX7hKaeB9NEo1SjsYbcGs9Fq82maTQNsSG56NbfdkjYePWDV'
    with closing(Store(tmp_path)) as store:
        loaded = load_archive(store, import_archive(store, source.read_bytes()))
        manifest = loaded['manifest']
        selected = [row for row in loaded['records'] if row['signature'] == signature]
        originals = [row for row in loaded['all_records'] if row['signature'] == signature]
        wallet = manifest['address']
        evidence = derive_wallet_evidence(selected, all_records=originals, wallet=wallet,
            window=manifest['window'], source_consistency={}, chronology={},
            raw_sources=loaded['raw_sources'], source_receipts=loaded['receipts'])
        result = project_cost_flow_evidence(selected={signature: selected[0]}, raw_versions={signature: originals},
            transactions=evidence['transactions'], consistency=evidence['source_consistency'],
            ledger_events=decode_transactions(selected, wallet)['events'], wallet=wallet)
        row = result['transactions'][signature]
        assert row['check']['state'] == 'PASS'
        assert [(item['role'], item['lamports']) for item in row['admitted_internal_roles']] == [
            ('wallet_owned_account_creation', '0'), ('wallet_owned_account_funding', '1513840')]
        assert row['admitted_internal_roles'][1]['account'] == 'Bd42jNQErVaj4EgribKywKPvTbgSNMjhkwMJCseGoDed'
        assert 'meta.innerInstructions.1.instructions.1.data' in row['check']['raw_paths']
        assert len(row['check']['evidence']) == 2
        assert row['unresolved_economic_paths'] and row['wallet_population_state'] == 'UNKNOWN'
        assert _decoded_native_movement(result['ledger_events']) is None
        assert result['provider_requests'] == result['credential_lookups'] == 0


def test_internal_creation_normal_saved_report_offline_rebuild_and_source_loss(tmp_path, monkeypatch):
    """Synthetic interface input exercises the ordinary real adapter, not B3."""
    import hashlib
    import json
    import httpx
    from fastapi.testclient import TestClient
    import scanner.app as app_module
    from scanner.archive_input import canonical_bytes, pack_bytes, VERSION as INPUT_VERSION
    from test_position_evidence import WINDOW

    calls = {'provider': 0, 'credential': 0}
    active = [False]

    class EmptyCredentials:
        storage = 'none'
        backend = None

        def __init__(self, *_):
            pass

        @property
        def key(self):
            if active[0]:
                calls['credential'] += 1
                raise AssertionError('Offline report workflow cannot look up a credential')
            return None

    async def denied(*_args, **_kwargs):
        calls['provider'] += 1
        raise AssertionError('Offline report workflow cannot call a provider')

    monkeypatch.setattr(app_module, 'Credentials', EmptyCredentials)
    monkeypatch.setattr(httpx.AsyncClient, 'post', denied)
    raw = primary(creation())
    digest = hashlib.sha256(canonical_bytes(raw)).hexdigest()
    manifest = {'version': INPUT_VERSION, 'address': WALLET, 'window': WINDOW, 'dataset': 'real',
                'transactions': [{'signature': 'synthetic-operation', 'hash': digest}], 'evidence': []}
    content = pack_bytes({'manifest': manifest, 'payloads': {digest: raw}})
    app = app_module.create_app(tmp_path, 'cost-flow-local-session')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        active[0] = True
        csrf = client.get('/api/bootstrap', headers={'X-Launch-Token': 'cost-flow-local-session'}).json()['csrf']
        client.headers['X-CSRF-Token'] = csrf
        response = client.post('/api/archives/import', content=content, headers={'content-type': 'application/zip'})
        assert response.status_code == 200, response.text
        identifier = response.json()['report_id']
        original = client.get(f'/api/export/reports/{identifier}.json').content
        parent = json.loads(original)
        adapter = parent['coverage']['wallet_evidence']
        assert [event['kind'] for event in adapter['accounting_events']] == ['fee', 'internal_transfer']
        assert adapter['components']['observed_economic_roles']['state'] == 'PASS'
        assert parent['metrics']['observed_network_fees_sol']['value'] == '0.000005'
        assert parent['metrics']['profit_sol']['status'] == 'unknown'
        assert parent['qualification']['qualified'] is False
        source_path = app.state.store.path / 'evidence' / f'{digest}.json.gz'
        retained = source_path.read_bytes()
        source_path.unlink()
        missing = client.post(f'/api/reports/{identifier}/rebuild')
        assert missing.status_code == 200, missing.text
        child = client.get('/api/reports/' + missing.json()['report_id']).json()
        assert child['coverage']['wallet_evidence']['cost_flow_evidence']['transactions']['synthetic-operation']['check']['state'] == 'UNKNOWN'
        source_path.write_bytes(retained)
        restored = client.post(f'/api/reports/{identifier}/rebuild')
        assert restored.status_code == 200, restored.text
        child_id = restored.json()['report_id']
        child = client.get('/api/reports/' + child_id).json()
        assert child['metrics'] == parent['metrics']
        assert child['coverage']['wallet_evidence']['components']['observed_economic_roles']['state'] == 'PASS'
        assert client.get(f'/api/export/reports/{identifier}.json').content == original
        assert '0.000005' in client.get(f'/api/export/reports/{child_id}.csv').text
        assert calls == {'provider': 0, 'credential': 0}
        active[0] = False


def test_existing_legacy_wsol_funding_sync_reaches_shared_quantities_and_fee_roles_parsed_and_compiled():
    raw, account = wrapped_funding()
    for compiled in (False, True):
        original = deepcopy(raw)
        if compiled:
            keys = original['transaction']['message']['accountKeys']
            original['transaction']['message']['instructions'] = [
                {'programIdIndex': keys.index(SYSTEM_ID), 'accounts': [0, 2],
                 'data': encode(bytes.fromhex('02000000e803000000000000'))},
                {'programIdIndex': keys.index(TOKEN_PROGRAM), 'accounts': [2], 'data': encode(bytes.fromhex('11'))}]
        evidence = derive([original])
        pair = evidence['transactions']['wrapped-principal']['boundaries'][account]
        assert pair['checks']['quantities']['state'] == pair['checks']['ownership']['state'] == 'PASS'
        assert pair['flow_raw'] == '1000'
        assert evidence['components']['observed_economic_roles']['state'] == 'PASS'
        assert [event['kind'] for event in evidence['accounting_events']] == ['fee', 'internal_transfer', 'internal_transfer', 'internal_transfer']
        receipts = evidence['cost_flow_evidence']['transactions']['wrapped-principal']['admitted_internal_roles']
        assert receipts[0]['role'] == 'wallet_owned_native_principal' and receipts[0]['lamports'] == '1000'
        assert evidence['components']['native_fee']['state'] == 'PASS'
        assert evidence['components']['historical_population']['state'] == 'UNKNOWN'
        assert _native_role_check(record(original), WALLET, _decoded_native_movement(evidence['accounting_events']))['state'] == 'PASS'
    for second_phase in ('missing', 'foreign-owner'):
        incomplete = deepcopy(raw)
        for phase in ('preTokenBalances', 'postTokenBalances'):
            other = next(row for row in incomplete['meta'][phase] if row['accountIndex'] == 1)
            other['mint'] = WSOL
            other['uiTokenAmount'] = {'amount': '100', 'decimals': 9}
        if second_phase == 'missing':
            incomplete['meta']['postTokenBalances'] = [row for row in incomplete['meta']['postTokenBalances'] if row['accountIndex'] != 1]
        else:
            next(row for row in incomplete['meta']['postTokenBalances'] if row['accountIndex'] == 1)['owner'] = address(40)
        unsupported = derive([incomplete])
        assert any(event['kind'] == 'wrap' and event['path'] == 'meta.tokenBalances' for event in unsupported['accounting_events'])
        assert unsupported['components']['observed_economic_roles']['state'] == 'UNKNOWN'
        assert 'meta.tokenBalances' in unsupported['cost_flow_evidence']['transactions']['wrapped-principal']['unresolved_economic_paths']


def test_legacy_wsol_sync_dependency_loss_conflicts_wrong_reserve_and_authority_keep_fee_isolated():
    raw, account = wrapped_funding()
    link_raw = deepcopy(raw)
    link_raw['meta']['logMessages'] = ['Optional alternative original field']
    link = record(link_raw)
    parent = derive([raw], alternatives=[link])
    frozen = deepcopy(parent)
    missing = derive([raw], alternatives=[{**link, 'raw': None}])
    assert missing['components']['observed_economic_roles']['state'] == 'UNKNOWN'
    assert missing['transactions']['wrapped-principal']['boundaries'][account]['checks']['quantities']['state'] == 'UNKNOWN'
    for variant in ('wrong-funding', 'reserve-conflict', 'wrong-authority', 'non-wsol', 'missing-sync'):
        broken = deepcopy(raw)
        if variant == 'wrong-funding':
            broken['transaction']['message']['instructions'][0]['parsed']['info']['lamports'] += 1
        elif variant == 'reserve-conflict':
            broken['meta']['preBalances'][2] += 1
            broken['meta']['postBalances'][2] += 2
            broken['meta']['postBalances'][0] -= 1
        elif variant == 'wrong-authority':
            broken['transaction']['message']['instructions'].append(parsed('setAuthority', {
                'account': account, 'authorityType': 'closeAccount', 'authority': WALLET,
                'newAuthority': address(40)}))
        elif variant == 'non-wsol':
            for phase in ('preTokenBalances', 'postTokenBalances'):
                next(row for row in broken['meta'][phase] if row['accountIndex'] == 2)['mint'] = address(70)
        else:
            broken['transaction']['message']['instructions'].pop()
        result = derive([broken])
        assert result['components']['observed_economic_roles']['state'] == 'UNKNOWN'
        assert result['components']['native_fee']['state'] == 'PASS'
    conflict = derive([raw], alternatives=[record(broken)])
    assert conflict['components']['observed_economic_roles']['state'] == 'UNKNOWN'
    assert derive([raw], alternatives=[link]) == parent == frozen


def test_nonzero_legacy_wsol_close_returns_principal_and_rent_once_with_loss_restoration():
    raw, account = wrapped_funding()
    raw['transaction']['message']['instructions'] = [parsed('closeAccount', {
        'account': account, 'destination': WALLET, 'owner': WALLET})]
    raw['meta']['postTokenBalances'] = [row for row in raw['meta']['postTokenBalances'] if row['accountIndex'] != 2]
    raw['meta']['postBalances'][2] = 0
    raw['meta']['postBalances'][0] = raw['meta']['preBalances'][0] - 5000 + raw['meta']['preBalances'][2]
    parent = derive([raw])
    pair = parent['transactions']['wrapped-principal']['boundaries'][account]
    assert pair['post']['quantity'] == '0' and pair['flow_raw'] == '-1000000000'
    assert pair['checks']['quantities']['state'] == 'PASS'
    assert parent['components']['observed_economic_roles']['state'] == 'PASS'
    assert [event['kind'] for event in parent['accounting_events']] == ['fee', 'internal_transfer', 'internal_transfer']
    assert parent['cost_flow_evidence']['transactions']['wrapped-principal']['admitted_internal_roles'][0]['lamports'] == '1002000000'
    lost = derive([raw], alternatives=[{'signature': 'wrapped-principal', 'evidence_hash': 'a' * 64, 'raw': None}])
    assert lost['components']['observed_economic_roles']['state'] == 'UNKNOWN'
    wrong = deepcopy(raw)
    wrong['transaction']['message']['instructions'].insert(0, parsed('setAuthority', {
        'account': account, 'authorityType': 'closeAccount', 'authority': WALLET,
        'newAuthority': address(40)}))
    assert derive([wrong])['components']['observed_economic_roles']['state'] == 'UNKNOWN'
    # Prior native-affecting instructions make the opening endpoint an
    # inexact refund. Retain that dependency instead of publishing its number.
    preceded = deepcopy(raw)
    preceded['transaction']['message']['instructions'].insert(0, parsed('transfer', {
        'source': WALLET, 'destination': account, 'lamports': 1000}, SYSTEM_ID))
    preceded['meta']['postBalances'][0] = raw['meta']['postBalances'][0]
    unsupported = derive([preceded])
    receipt = unsupported['cost_flow_evidence']['transactions']['wrapped-principal']
    assert receipt['check']['state'] == 'UNKNOWN'
    assert receipt['admitted_internal_roles'] == []
    assert 'exact refund' in receipt['check']['reason']
    assert derive([raw]) == parent
