"""Small offline classification contract controls; development inputs, not B3."""
from copy import deepcopy
import hashlib
import json

import pytest

from scanner.asset_classification import project_asset_classification, derive_mint_snapshots
from scanner.json_boundary import canonical_bytes
from scanner.wallet_identity import account_info_source
from scanner.providers import TOKEN_PROGRAM, TOKEN_2022_PROGRAM
from test_wallet_evidence import base, record, derive, parsed
from test_position_evidence import ACCOUNT, POOL_TOKEN, MINT, WALLET, WINDOW, START, END, transfer

# Protocol identity is the literal mainnet legacy wrapped-native address. The
# existing pinned SPL instruction/schema suite supplies the transfer contract;
# these tests do not derive their oracle from a production classification table.
WRAPPED_NATIVE = 'So11111111111111111111111111111111111111112'


def wrapped_transfer(*, program=TOKEN_PROGRAM, at=START + 3600):
    raw = base('wrapped-transfer', 100)
    raw['blockTime'] = at
    for name in ('preTokenBalances', 'postTokenBalances'):
        for row in raw['meta'][name]:
            if row['mint'] == MINT:
                row['mint'] = WRAPPED_NATIVE
                row['uiTokenAmount']['decimals'] = 9
            row['programId'] = program
    for row in raw['meta']['postTokenBalances']:
        if row['accountIndex'] == 1:
            row['uiTokenAmount']['amount'] = '60'
        elif row['accountIndex'] == 3:
            row['uiTokenAmount']['amount'] = '40'
    instruction = transfer(ACCOUNT, POOL_TOKEN, 40, mint=WRAPPED_NATIVE)
    instruction['programId'] = program
    raw['transaction']['message']['instructions'] = [instruction]
    return raw


def classification(raws, *, alternatives=(), sources=(), window=WINDOW):
    selected = [record(raw) for raw in raws]
    evidence = derive(raws, alternatives=alternatives, raw_sources=sources)
    versions = {row['signature']: [] for row in selected}
    for row in selected + list(alternatives):
        versions.setdefault(row.get('signature'), []).append(row)
    return project_asset_classification(selected={row['signature']: row for row in selected},
        raw_versions=versions, transactions=evidence['transactions'], clocks=evidence['chronology'],
        consistency=evidence['source_consistency'], raw_sources=sources, wallet=WALLET, window=window)


def test_literal_wrapped_native_is_excluded_without_claiming_a_complete_meme_population():
    raw = wrapped_transfer()
    frozen = deepcopy(raw)
    result = classification([raw])
    asset = result['records']['wrapped-transfer']['assets'][WRAPPED_NATIVE]
    assert asset['classification'] == 'settlement'
    assert asset['eligibility'] == 'excluded_settlement' and asset['check']['state'] == 'PASS'
    assert result['classification_by_interval']['report_period']['state'] == 'PASS'
    assert result['wallet_population_state'] == result['historical_eligibility_state'] == 'UNKNOWN'
    assert result['qualification'] is False and result['provider_requests'] == result['credential_lookups'] == 0
    assert raw == frozen


@pytest.mark.parametrize('program', [TOKEN_PROGRAM, TOKEN_2022_PROGRAM])
def test_real_token_program_or_authority_metadata_cannot_manufacture_meme_eligibility(program):
    raw = wrapped_transfer(program=program)
    for name in ('preTokenBalances', 'postTokenBalances'):
        for row in raw['meta'][name]:
            row['mint'] = MINT
    raw['transaction']['message']['instructions'][0]['parsed']['info']['mint'] = MINT
    result = classification([raw], sources=[mint_source(program=program)])
    asset = result['records']['wrapped-transfer']['assets'][MINT]
    assert asset['classification'] == asset['eligibility'] == 'unknown'
    assert result['classification_by_interval']['report_period']['state'] == 'UNKNOWN'
    assert 'accepted_time_relevant_meme_identity' in asset['check']['dependencies']
    assert 'accepted_time_relevant_spam_exclusion' in asset['check']['dependencies']
    assert result['mint_snapshots'][0]['controls']['mintAuthority']['state'] == 'PASS'


@pytest.mark.parametrize('variant', ['missing', 'mint-conflict', 'wrong-program', 'malformed'])
def test_linked_native_loss_conflict_and_unsupported_identity_revoke_then_restore(variant):
    raw = wrapped_transfer()
    alternative = deepcopy(raw)
    alternative['meta']['logMessages'] = ['different irrelevant log bytes']
    valid = record(alternative)
    parent = classification([raw], alternatives=[valid])
    assert parent['classification_by_interval']['report_period']['state'] == 'PASS'
    broken = deepcopy(valid)
    if variant == 'missing':
        broken['raw'] = None
    elif variant == 'mint-conflict':
        broken['raw']['meta']['postTokenBalances'][0]['mint'] = MINT
        broken = record(broken['raw'])
    elif variant == 'wrong-program':
        broken['raw']['meta']['postTokenBalances'][0]['programId'] = TOKEN_2022_PROGRAM
        broken = record(broken['raw'])
    else:
        broken['raw']['meta']['postTokenBalances'] = None
        broken = record(broken['raw'])
    child = classification([raw], alternatives=[broken])
    assert child['classification_by_interval']['report_period']['state'] == 'UNKNOWN'
    assert classification([raw], alternatives=[valid]) == parent


def test_independent_report_and_28_day_scopes_exclude_only_proved_old_unknown_assets():
    raw = wrapped_transfer(at=END - 29 * 86400)
    for name in ('preTokenBalances', 'postTokenBalances'):
        for row in raw['meta'][name]:
            row['mint'] = MINT
    raw['transaction']['message']['instructions'][0]['parsed']['info']['mint'] = MINT
    result = classification([raw])
    assert result['classification_by_interval']['report_period']['state'] == 'UNKNOWN'
    assert result['classification_by_interval']['verification_90d']['state'] == 'UNKNOWN'
    assert result['classification_by_interval']['four_weeks']['state'] == 'PASS'


def mint_source(*, program=TOKEN_PROGRAM, freeze=None):
    request = json.dumps({'jsonrpc': '2.0', 'id': 7, 'method': 'getAccountInfo',
        'params': [MINT, {'commitment': 'finalized', 'encoding': 'jsonParsed', 'minContextSlot': 100}]}).encode()
    response = json.dumps({'jsonrpc': '2.0', 'id': 7, 'result': {'context': {'slot': 101}, 'value': {
        'owner': program, 'executable': False, 'lamports': 1_000_000,
        'data': {'parsed': {'type': 'mint', 'info': {'isInitialized': True, 'mintAuthority': None,
            'freezeAuthority': freeze, 'decimals': 6, 'supply': '18446744073709551615',
            **({'extensions': [{'extension': 'transferFeeConfig', 'state': {'transferFeeBasisPoints': 100}}]}
               if program == TOKEN_2022_PROGRAM else {})}}}}}}).encode()
    payload = account_info_source(request, response)
    return {'kind': 'current-mint-controls', 'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'payload': payload}


def test_exact_byte_current_controls_remain_independent_and_never_become_historical_classification():
    source = mint_source(freeze=True)
    parent = derive_mint_snapshots([source])
    snapshot = parent[0]
    assert snapshot['slot'] == 101 and snapshot['supply_raw'] == '18446744073709551615'
    assert snapshot['controls']['mintAuthority']['state'] == 'PASS'
    assert snapshot['controls']['freezeAuthority']['state'] == 'UNKNOWN'
    assert snapshot['classification'] == snapshot['eligibility'] == 'unknown'
    assert snapshot['historical_state'] == 'UNKNOWN'
    for lost in ({**source, 'payload': None}, {**source, 'hash': 'a' * 64}):
        assert derive_mint_snapshots([lost]) == []
    assert derive_mint_snapshots([source]) == parent
    observed = classification([wrapped_transfer()], sources=[source])
    assert observed['mint_snapshot_sources'][source['hash']]['state'] == 'PASS'
    missing = classification([wrapped_transfer()], sources=[{**source, 'payload': None}])
    assert missing['mint_snapshot_sources'][source['hash']]['state'] == 'UNKNOWN'
    assert source['hash'] in missing['mint_snapshot_sources'][source['hash']]['evidence']


def test_detached_raw_object_and_caller_pass_classification_flags_are_not_admitted():
    raw = wrapped_transfer()
    alternative = record(raw)
    alternative['evidence_hash'] = 'a' * 64
    alternative.update(classification='settlement', state='PASS', complete=True)
    result = classification([raw], alternatives=[alternative])
    assert result['classification_by_interval']['report_period']['state'] == 'UNKNOWN'


def test_supported_nonsettlement_roundtrip_remains_activity_despite_zero_net_change():
    raw = base('nonsettlement-roundtrip', 100)
    movements = [
        [transfer(ACCOUNT, POOL_TOKEN, 40), transfer(POOL_TOKEN, ACCOUNT, 40)],
        [parsed('mintTo', {'account': ACCOUNT, 'mint': MINT, 'mintAuthority': WALLET, 'amount': '40'}),
         parsed('burn', {'account': ACCOUNT, 'mint': MINT, 'authority': WALLET, 'amount': '40'})]]
    for instructions in movements:
        raw['transaction']['message']['instructions'] = instructions
        result = classification([raw])
        asset = result['records']['nonsettlement-roundtrip']['assets'][MINT]
        assert asset['activity_observed'] is True
        assert asset['classification'] == 'unknown'
        assert result['records']['nonsettlement-roundtrip']['check']['state'] == 'UNKNOWN'
        assert result['classification_by_interval']['report_period']['state'] == 'UNKNOWN'
    # Identical endpoints with no executed movement are a different dependency
    # set; unknown metadata cannot manufacture activity or a meme trade.
    raw['transaction']['message']['instructions'] = []
    disjoint = classification([raw])
    assert disjoint['records']['nonsettlement-roundtrip']['assets'][MINT]['activity_observed'] is False
    assert disjoint['records']['nonsettlement-roundtrip']['check']['state'] == 'PASS'


def test_indexed_pointer_identity_is_recovered_only_from_retained_original_page_bytes(tmp_path):
    from scanner.archive_input import import_archive, load_archive
    from scanner.wallet_evidence import derive_wallet_evidence
    from scanner.storage import Store
    from scanner.indexed_input import convert_indexed_archive
    from test_indexed_input import page, upload, WALLET as INDEXED_WALLET, WINDOW as INDEXED_WINDOW
    store = Store(tmp_path)
    _, _, content = upload([page()])
    digest = import_archive(store, convert_indexed_archive(content))
    loaded = load_archive(store, digest)
    evidence = derive_wallet_evidence(loaded['records'], all_records=loaded['all_records'],
        wallet=INDEXED_WALLET, window=INDEXED_WINDOW, raw_sources=loaded['raw_sources'],
        source_consistency={}, chronology={})
    selected = {row['signature']: row for row in loaded['records']}
    versions = {signature: [row for row in loaded['all_records'] if row['signature'] == signature]
                for signature in selected}
    arguments = dict(selected=selected, raw_versions=versions, transactions=evidence['transactions'],
        clocks=evidence['chronology'], consistency=evidence['source_consistency'],
        wallet=INDEXED_WALLET, window=INDEXED_WINDOW)
    parent = project_asset_classification(**arguments, raw_sources=loaded['raw_sources'])
    assert parent['records']['indexed-a']['check']['state'] == 'PASS'
    page_hash = next(row['hash'] for row in loaded['raw_sources'] if row['kind'] == 'indexed-page')
    lost = [{**row, 'payload': None} if row['hash'] == page_hash else row for row in loaded['raw_sources']]
    assert project_asset_classification(**arguments, raw_sources=lost)['records']['indexed-a']['check']['state'] == 'UNKNOWN'
    assert project_asset_classification(**arguments, raw_sources=loaded['raw_sources']) == parent
