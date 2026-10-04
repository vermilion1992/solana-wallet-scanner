"""Development raw-account/FIFO admission controls, never genuine B3 proof."""
from copy import deepcopy
from itertools import permutations
import base64
import hashlib
import json

import pytest

from scanner.json_boundary import canonical_bytes
from scanner.wallet_positions import derive_wallet_positions, VERSION
from test_wallet_evidence import record, base, derive
from test_selected_cohort_observations import exchange
from test_indexed_report_integration import guarded, session, import_report, rebuild
from test_position_evidence import (address, transfer, ACCOUNT, POOL_TOKEN,
                                    MINT, WALLET, START, END, WINDOW)


def positions(raws, *, alternatives=(), raw_sources=(), window=WINDOW, **advisory):
    selected = [record(raw) for raw in raws]
    return derive_wallet_positions(selected, all_records=selected + list(alternatives),
        wallet=WALLET, window=window, raw_sources=raw_sources, **advisory)


def mixed():
    return [exchange('buy-loss', 100, START + 3600, 0, 100),
            exchange('close-loss', 101, START + 7200, 100, 0),
            exchange('buy-even', 102, START + 10800, 0, 100),
            exchange('close-even', 103, START + 14400, 100, 0, cash=1_000_010_000),
            exchange('reentry-open', 104, START + 18000, 0, 100)]


def replace_strings(value, before, after):
    if isinstance(value, dict):
        return {key: replace_strings(item, before, after) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_strings(item, before, after) for item in value]
    return after if value == before else value


def owned_transfer(signature, slot, at, destination, *, moved=100):
    raw = base(quantity=100)
    raw['transaction']['signatures'] = [signature]
    raw['slot'], raw['blockTime'] = slot, at
    raw = replace_strings(raw, POOL_TOKEN, destination)
    for name, source, target in (('preTokenBalances', 100, 0), ('postTokenBalances', 100 - moved, moved)):
        for row in raw['meta'][name]:
            if row['accountIndex'] in (1, 3):
                row['owner'] = WALLET
                row['uiTokenAmount']['amount'] = str(source if row['accountIndex'] == 1 else target)
    raw['transaction']['message']['instructions'] = [transfer(ACCOUNT, destination, moved)]
    return raw


def test_mixed_closed_open_loss_and_breakeven_are_admitted_without_wallet_qualification():
    raws = mixed()
    frozen = deepcopy(raws)
    result = positions(raws)
    aggregate = result['mints'][MINT]
    assert result['version'] == VERSION
    assert result['checks']['observed_population']['state'] == aggregate['position_state'] == 'PASS'
    assert aggregate['quantity_state'] == 'PASS'
    assert aggregate['selected_opening_raw'] == '0'
    assert aggregate['selected_remaining_raw'] == aggregate['fifo_remaining_raw'] == '100'
    assert aggregate['candidate_closed_count'] == 2 and aggregate['candidate_open_count'] == 1
    closed = result['intervals']['report_period']['closed_cohort']
    assert closed['candidate_count'] == 2 and closed['population_state'] == 'PASS'
    assert closed['conditional_profit_sol'] == '-0.00001' and closed['conditional_win_rate_pct'] == '0'
    assert [row['conditional_profit_sol'] for row in aggregate['episodes'][:2]] == ['-0.00001', '0']
    assert aggregate['episodes'][-1]['remaining_cost_basis_state'] == 'PASS'
    assert aggregate['episodes'][-1]['conditional_remaining_basis_sol'] == '1.000005'
    assert result['wallet_population_state'] == result['classification_state'] == result['valuation_state'] == 'UNKNOWN'
    assert result['checks']['historical_population']['state'] == 'UNKNOWN'
    assert result['qualification'] is False and raws == frozen
    query = derive(raws)['query_accounting']
    assert query['timing_state'] == 'PASS'
    assert query['conditional_median_hold_hours'] == query['conditional_first_sale_hours'] == '1'
    json.dumps(result, allow_nan=False)


def test_partial_exit_uses_existing_fifo_remainder_without_requiring_closure():
    result = positions([exchange('buy', 100, START + 3600, 0, 100),
                        exchange('partial', 101, START + 7200, 100, 40)])
    aggregate = result['mints'][MINT]
    assert aggregate['position_state'] == 'PASS'
    assert aggregate['candidate_open_count'] == 1 and aggregate['candidate_closed_count'] == 0
    assert aggregate['selected_remaining_raw'] == aggregate['fifo_remaining_raw'] == '40'
    assert aggregate['episodes'][0]['conditional_remaining_basis_sol'] == '0.400002'
    assert result['intervals']['report_period']['closed_cohort']['candidate_count'] == 0


def test_full_owned_account_transfer_carries_aggregate_and_keeps_single_episode():
    second_account = address(18)
    raws = [exchange('buy', 100, START + 3600, 0, 100),
            owned_transfer('move-owned', 101, START + 7200, second_account),
            replace_strings(exchange('sell', 102, START + 10800, 100, 0), ACCOUNT, second_account)]
    result = positions(raws)
    aggregate = result['mints'][MINT]
    assert aggregate['position_state'] == aggregate['quantity_state'] == 'PASS'
    assert aggregate['selected_remaining_raw'] == '0' and len(aggregate['accounts']) == 2
    assert aggregate['candidate_closed_count'] == 1 and aggregate['candidate_open_count'] == 0
    assert aggregate['episodes'][0]['conditional_profit_sol'] == '-0.00001'
    assert aggregate['episodes'][0]['conditional_hold_hours'] == '2'
    assert aggregate['required_signatures'] == ['buy', 'move-owned', 'sell']


def test_partial_owned_account_transfer_carries_two_surviving_account_quantities():
    second_account = address(18)
    result = positions([exchange('buy', 100, START + 3600, 0, 100),
                        owned_transfer('move-half', 101, START + 7200, second_account, moved=40)])
    aggregate = result['mints'][MINT]
    assert aggregate['position_state'] == aggregate['quantity_state'] == 'PASS'
    assert aggregate['selected_remaining_raw'] == aggregate['fifo_remaining_raw'] == '100'
    assert {row['account']: row['remaining_raw'] for row in aggregate['accounts']} == {ACCOUNT: '60', second_account: '40'}
    assert aggregate['episodes'][0]['conditional_remaining_basis_sol'] == '1.000005'


@pytest.mark.parametrize('fee_signature', ['buy-loss', 'close-loss', 'reentry-open'])
def test_missing_fee_blocks_dependent_money_without_revoking_quantity_population(fee_signature):
    raws = mixed()
    parent = positions(raws)
    target = next(raw for raw in raws if raw['transaction']['signatures'][0] == fee_signature)
    original_fee = target['meta']['fee']
    target['meta']['fee'] = None
    child = positions(raws)
    aggregate = child['mints'][MINT]
    assert child['checks']['observed_population']['state'] == aggregate['quantity_state'] == aggregate['position_state'] == 'PASS'
    assert aggregate['selected_remaining_raw'] == '100'
    assert aggregate['episodes'][1]['monetary_state'] == 'PASS'
    if fee_signature == 'reentry-open':
        assert aggregate['episodes'][-1]['remaining_cost_basis_state'] == 'UNKNOWN'
        assert aggregate['episodes'][-1]['conditional_remaining_basis_sol'] is None
        assert child['intervals']['report_period']['closed_cohort']['monetary_state'] == 'PASS'
    else:
        assert aggregate['episodes'][0]['monetary_state'] == 'UNKNOWN'
        assert aggregate['episodes'][0]['conditional_profit_sol'] is None
        assert aggregate['episodes'][0]['timing_state'] == 'PASS'
        assert aggregate['episodes'][-1]['remaining_cost_basis_state'] == 'PASS'
    target['meta']['fee'] = original_fee
    assert positions(raws) == parent


@pytest.mark.parametrize('variant', ['missing', 'quantity-conflict', 'malformed', 'unsupported'])
def test_linked_required_source_loss_remains_dependency_and_restore_recovers(variant):
    raws = mixed()
    parent = positions(raws)
    alternative = deepcopy(raws[-1])
    if variant == 'missing':
        link = {'signature': 'reentry-open', 'evidence_hash': 'a' * 64, 'raw': None}
    else:
        if variant == 'quantity-conflict':
            alternative['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '101'
        elif variant == 'malformed':
            alternative['meta']['preTokenBalances'][0]['uiTokenAmount']['amount'] = []
        else:
            alternative['version'] = 1
        link = record(alternative)
    child = positions(raws, alternatives=[link])
    aggregate = child['mints'][MINT]
    assert aggregate['quantity_state'] == aggregate['position_state'] == child['checks']['observed_population']['state'] == 'UNKNOWN'
    assert aggregate['selected_remaining_raw'] is None
    assert link['evidence_hash'] in aggregate['checks']['quantity']['evidence']
    # Readable bounded alternatives can be excluded from the earlier episode.
    # A missing/unsupported clock has no independent bound and cannot be
    # declared later merely from the preferred selected version's timestamp.
    earlier = aggregate['episodes'][0]
    if variant in ('missing', 'unsupported'):
        assert earlier['quantity_state'] == earlier['monetary_state'] == 'UNKNOWN'
        assert earlier['conditional_profit_sol'] is None
    else:
        assert earlier['quantity_state'] == earlier['monetary_state'] == 'PASS'
        assert earlier['conditional_profit_sol'] == '-0.00001'
    assert positions(raws, alternatives=[record(deepcopy(raws[-1]))]) == parent


def test_source_canonical_hash_mismatch_is_rejected_even_when_supplied_receipts_claim_pass():
    raws = mixed()
    selected = [record(raw) for raw in raws]
    original = deepcopy(selected)
    selected[-1]['evidence_hash'] = 'b' * 64
    result = derive_wallet_positions(selected, all_records=selected, wallet=WALLET, window=WINDOW,
        positions=[{'status': 'closed', 'quantity_raw': '0'}], events=[{'kind': 'buy', 'amount_sol': '0'}],
        history_evidence={'wallet_history_complete': True}, source_consistency={'state': 'PASS'}, chronology={'state': 'PASS'})
    assert result['checks']['observed_population']['state'] == 'UNKNOWN'
    assert result['wallet_population_state'] == 'UNKNOWN' and result['qualification'] is False
    assert positions(raws)['checks']['observed_population']['state'] == 'PASS'
    assert original == [record(raw) for raw in raws]


@pytest.mark.parametrize('path', ['public-wrapper', 'normal-adapter'])
@pytest.mark.parametrize('variant', ['wrong-identity', 'unsupported-format', 'missing-meta'])
def test_readable_unassignable_selected_body_cannot_disappear_from_known_mint_quantity(path, variant):
    from scanner.wallet_evidence import derive_wallet_evidence
    raws = mixed()
    selected = [record(raw) for raw in raws]
    if variant == 'wrong-identity':
        selected[-1]['signature'] = 'wrong-identity'
    else:
        changed = deepcopy(raws[-1])
        if variant == 'unsupported-format':
            changed['version'] = 1
        else:
            changed.pop('meta')
        selected[-1] = record(changed)
    if path == 'public-wrapper':
        result = derive_wallet_positions(selected, all_records=selected, wallet=WALLET, window=WINDOW)
    else:
        result = derive_wallet_evidence(selected, all_records=selected, wallet=WALLET, window=WINDOW,
            source_consistency={'state': 'PASS'}, chronology={'state': 'PASS'})['query_accounting']['position_population']
    aggregate = result['mints'][MINT]
    assert aggregate['quantity_state'] == aggregate['position_state'] == 'UNKNOWN'
    assert aggregate['selected_remaining_raw'] is None
    assert result['checks']['observed_population']['state'] == 'UNKNOWN'
    restored = positions(raws)
    assert restored['mints'][MINT]['quantity_state'] == 'PASS'
    assert restored['mints'][MINT]['selected_remaining_raw'] == '100'


def test_readable_wrong_identity_alternative_cannot_be_ignored_in_known_quantity():
    raws = mixed()
    parent = positions(raws)
    malformed = record(deepcopy(raws[-1]))
    malformed['signature'] = 'wrong-identity'
    child = positions(raws, alternatives=[malformed])
    assert child['mints'][MINT]['quantity_state'] == 'UNKNOWN'
    assert child['mints'][MINT]['selected_remaining_raw'] is None
    assert positions(raws, alternatives=[record(deepcopy(raws[-1]))]) == parent


def test_caller_flags_classification_and_valuation_do_not_promote_population():
    payload = {'complete': True, 'positions': [{'mint': MINT, 'quantity_raw': '0'}], 'classification': 'meme', 'value_sol': '999'}
    source = {'kind': 'classification', 'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'payload': payload}
    result = positions(mixed(), raw_sources=[source],
        positions=payload['positions'], events=[{'kind': 'sell', 'amount_sol': '999'}],
        history_evidence={'wallet_history_complete': True})
    assert result['checks']['observed_population']['state'] == 'PASS'
    assert result['wallet_population_state'] == result['classification_state'] == result['valuation_state'] == 'UNKNOWN'
    assert result['qualification'] is False


def test_input_and_alternative_order_do_not_change_position_admission():
    raws = mixed()[:3]
    parent = positions(raws)
    for permuted in permutations(raws):
        assert positions(permuted, alternatives=[record(deepcopy(raws[1])), record(deepcopy(raws[0]))]) == parent


def test_preexisting_inventory_has_known_endpoint_quantity_without_invented_fifo_origin():
    result = positions([exchange('unknown-origin-sale', 100, START + 3600, 100, 40)])
    aggregate = result['mints'][MINT]
    assert aggregate['quantity_state'] == 'PASS'
    assert aggregate['selected_opening_raw'] == '100' and aggregate['selected_remaining_raw'] == '40'
    assert aggregate['position_state'] == 'UNKNOWN'
    assert aggregate['episodes'][0]['conditional_profit_sol'] is None
    assert result['checks']['observed_population']['state'] == 'UNKNOWN'


def test_account_endpoint_gap_revokes_aggregate_but_does_not_erase_completed_earlier_episode():
    raws = mixed()
    raws[-1] = exchange('reentry-open', 104, START + 18000, 50, 150)
    result = positions(raws)
    aggregate = result['mints'][MINT]
    assert aggregate['quantity_state'] == aggregate['position_state'] == 'UNKNOWN'
    assert aggregate['selected_remaining_raw'] is None
    assert aggregate['episodes'][0]['quantity_state'] == aggregate['episodes'][0]['monetary_state'] == 'PASS'
    assert aggregate['episodes'][0]['conditional_profit_sol'] == '-0.00001'


def test_report_28_day_and_90_day_closed_cohorts_have_independent_boundaries():
    day = 86400
    raws = [exchange('old-buy', 100, END - 60 * day, 0, 100),
            exchange('old-sale', 101, END - 59 * day, 100, 0),
            exchange('month-buy', 102, END - 20 * day, 0, 100),
            exchange('month-sale', 103, END - 19 * day, 100, 0),
            exchange('week-buy', 104, END - 6 * day, 0, 100),
            exchange('week-sale', 105, END - 5 * day, 100, 0),
            exchange('open-buy', 106, END - day, 0, 100)]
    result = positions(raws, window={'start': END - 7 * day, 'end': END})
    assert result['checks']['observed_population']['state'] == 'PASS'
    counts = {name: interval['closed_cohort']['candidate_count'] for name, interval in result['intervals'].items()}
    assert counts == {'report_period': 1, 'four_weeks': 2, 'verification_90d': 3}
    assert all(interval['closed_cohort']['population_state'] == 'PASS' for interval in result['intervals'].values())


def test_post_boundary_buy_does_not_enter_ending_position_quantity():
    raws = [exchange('buy', 100, END - 3600, 0, 100),
            exchange('future-buy', 101, END, 100, 150)]
    result = positions(raws)
    aggregate = result['mints'][MINT]
    assert aggregate['selected_remaining_raw'] == aggregate['fifo_remaining_raw'] == '100'
    assert aggregate['quantity_state'] == aggregate['position_state'] == 'PASS'
    assert aggregate['required_signatures'] == ['buy']


def test_readable_disjoint_mint_does_not_revoke_supported_quantity_or_closed_episode():
    raws = mixed()
    other_account, other_mint = address(19), address(20)
    other = replace_strings(exchange('other-buy', 105, START + 21600, 0, 40), ACCOUNT, other_account)
    other = replace_strings(other, MINT, other_mint)
    result = positions(raws + [other])
    assert result['mints'][MINT]['quantity_state'] == result['mints'][other_mint]['quantity_state'] == 'PASS'
    assert result['mints'][MINT]['selected_remaining_raw'] == '100'
    assert result['mints'][other_mint]['selected_remaining_raw'] == '40'
    assert result['mints'][MINT]['episodes'][0]['conditional_profit_sol'] == '-0.00001'


def test_no_network_or_credential_access_in_raw_position_derivation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Offline position admission must never access a provider or credential')
    from scanner.providers import Gateway
    monkeypatch.setattr(Gateway, 'rpc', forbidden)
    result = positions(mixed())
    assert result['checks']['observed_population']['state'] == 'PASS'
    assert result['provider_requests'] == result['credential_lookups'] == 0


def test_future_disjoint_mint_is_not_admitted_to_the_report_end_population():
    other = replace_strings(exchange('future-other-buy', 105, END, 0, 40), ACCOUNT, address(19))
    other = replace_strings(other, MINT, address(20))
    result = positions(mixed() + [other])
    assert set(result['mints']) == {MINT}
    assert result['checks']['observed_population']['state'] == 'PASS'
    assert result['mints'][MINT]['selected_remaining_raw'] == '100'


def test_same_second_unknown_order_is_not_a_position_population_certificate():
    raws = [exchange('buy', 100, START + 3600, 0, 100),
            exchange('topup', 100, START + 3600, 100, 150)]
    result = positions(raws)
    assert result['mints'][MINT]['quantity_state'] == result['checks']['observed_population']['state'] == 'UNKNOWN'
    assert result['mints'][MINT]['selected_remaining_raw'] is None
    # Distinct evidenced slots restore ordering even within the same second.
    raws[-1]['slot'] = 101
    restored = positions(raws)
    assert restored['checks']['observed_population']['state'] == 'PASS'
    assert restored['mints'][MINT]['selected_remaining_raw'] == '150'


def test_original_native_byte_envelopes_bind_indexed_pointer_hashes_without_body_hash_substitution():
    from scanner.indexed_input import NATIVE_VERSION, RECORD_VERSION
    selected, sources = [], []
    raws = mixed()
    for raw in raws:
        signature = raw['transaction']['signatures'][0]
        request = json.dumps({'jsonrpc': '2.0', 'id': 31, 'method': 'getTransaction',
            'params': [signature, {'encoding': 'jsonParsed', 'commitment': 'finalized',
                                    'maxSupportedTransactionVersion': 0}]}, indent=1).encode()
        response = json.dumps({'jsonrpc': '2.0', 'id': 31, 'result': raw}, indent=1).encode()
        payload = {'version': NATIVE_VERSION,
            'request_hash': hashlib.sha256(request).hexdigest(), 'response_hash': hashlib.sha256(response).hexdigest(),
            'request_base64': base64.b64encode(request).decode(), 'response_base64': base64.b64encode(response).decode()}
        source_hash = hashlib.sha256(canonical_bytes(payload)).hexdigest()
        pointer = {'version': RECORD_VERSION, 'source_hash': source_hash, 'ordinal': 0,
                   'signature': signature, 'native_hash': record(raw)['evidence_hash']}
        pointer_hash = hashlib.sha256(canonical_bytes(pointer)).hexdigest()
        assert pointer_hash != record(raw)['evidence_hash']
        selected.append({'signature': signature, 'evidence_hash': pointer_hash, 'raw': raw})
        sources.append({'hash': source_hash, 'kind': 'indexed-native-source', 'payload': payload})
    parent = derive_wallet_positions(selected, all_records=selected, wallet=WALLET, window=WINDOW, raw_sources=sources)
    assert parent['checks']['observed_population']['state'] == 'PASS'
    assert parent['mints'][MINT]['selected_remaining_raw'] == '100'
    frozen = deepcopy(sources)
    sources[-1]['payload']['response_base64'] = base64.b64encode(b'{}').decode()
    lost = derive_wallet_positions(selected, all_records=selected, wallet=WALLET, window=WINDOW, raw_sources=sources)
    assert lost['checks']['observed_population']['state'] == 'UNKNOWN'
    restored = derive_wallet_positions(selected, all_records=selected, wallet=WALLET, window=WINDOW, raw_sources=frozen)
    assert restored == parent


@pytest.mark.parametrize('linked', [False, True], ids=['selected', 'alternative'])
def test_failed_transaction_fee_gap_does_not_create_an_episode_or_erase_remaining_basis(linked):
    failed = base(quantity=100)
    failed['transaction']['signatures'] = ['failed-attempt']
    failed['slot'], failed['blockTime'] = 101, START + 7200
    failed['meta']['err'] = {'InstructionError': [0, 'InvalidAccountData']}
    broken = deepcopy(failed)
    broken['meta']['fee'] = None
    result = positions([exchange('buy', 100, START + 3600, 0, 100), failed if linked else broken],
                       alternatives=[record(broken)] if linked else [])
    aggregate = result['mints'][MINT]
    assert aggregate['quantity_state'] == aggregate['position_state'] == 'PASS'
    assert aggregate['candidate_open_count'] == 1 and aggregate['candidate_closed_count'] == 0
    assert aggregate['selected_remaining_raw'] == '100'
    assert aggregate['episodes'][0]['conditional_remaining_basis_sol'] == '1.000005'
    assert aggregate['episodes'][0]['remaining_cost_basis_state'] == 'PASS'


def test_failed_record_with_conflicting_token_endpoints_cannot_supply_position_certainty():
    failed = base(quantity=100)
    failed['transaction']['signatures'] = ['failed-attempt']
    failed['slot'], failed['blockTime'] = 101, START + 7200
    failed['meta']['err'] = {'InstructionError': [0, 'InvalidAccountData']}
    failed['meta']['fee'] = None
    failed['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '101'
    result = positions([exchange('buy', 100, START + 3600, 0, 100), failed])
    aggregate = result['mints'][MINT]
    assert aggregate['quantity_state'] == aggregate['position_state'] == 'UNKNOWN'
    assert aggregate['selected_remaining_raw'] is None


def test_normal_archive_position_admission_rebuild_source_loss_restore_and_export_are_offline(guarded):
    """Unsigned development records exercise production APIs; not genuine B3."""
    from test_selected_cohort_observations import archive
    client, app, _, calls = guarded
    raws = mixed()
    parent = import_report(client, archive(raws))
    stored = deepcopy(app.state.store.get('reports', parent['id']))
    population = parent['coverage']['wallet_evidence']['query_accounting']['position_population']
    assert population['checks']['observed_population']['state'] == 'PASS'
    assert parent['coverage']['wallet_evidence']['components']['observed_positions']['state'] == 'PASS'
    assert parent['coverage']['wallet_evidence']['components']['positions']['state'] == 'UNKNOWN'
    assert parent['metrics']['profit_sol']['status'] == 'unknown' and parent['qualification']['qualified'] is False
    child = rebuild(client, parent)
    assert child['coverage']['wallet_evidence']['query_accounting']['position_population'] == population
    source = client.get('/api/evidence/' + record(raws[-1])['evidence_hash'])
    assert source.status_code == 200 and source.json() == raws[-1]
    path = app.state.store.path / 'evidence' / (record(raws[-1])['evidence_hash'] + '.json.gz')
    original = path.read_bytes()
    path.unlink()
    lost = rebuild(client, parent)
    lost_stored = deepcopy(app.state.store.get('reports', lost['id']))
    assert lost['coverage']['wallet_evidence']['query_accounting']['position_population']['checks']['observed_population']['state'] == 'UNKNOWN'
    path.write_bytes(original)
    restored = rebuild(client, lost)
    assert restored['coverage']['wallet_evidence']['query_accounting']['position_population'] == population
    exported = client.get('/api/export/reports/' + restored['id'] + '.json')
    assert exported.status_code == 200
    assert exported.json()['coverage']['wallet_evidence']['query_accounting']['position_population'] == population
    csv_export = client.get('/api/export/reports/' + restored['id'] + '.csv')
    assert csv_export.status_code == 200 and 'observed_network_fees_sol' in csv_export.text
    assert app.state.store.get('reports', parent['id']) == stored
    assert app.state.store.get('reports', lost['id']) == lost_stored
    assert calls == {'provider': 0, 'credential': 0, 'transport': 0}
