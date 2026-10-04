"""Raw B2 adapter development controls; no genuine population/B3 acceptance."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scanner.archive_input import canonical_bytes
from scanner.wallet_evidence import derive_wallet_evidence, raw_native_dependencies
from scanner.providers import TOKEN_PROGRAM
from test_position_evidence import (raw_exchange, transfer, address, WALLET, ACCOUNT,
                                    MINT, POOL_TOKEN, START, END, WINDOW)


def record(raw):
    transaction = raw.get('transaction')
    signature = transaction['signatures'][0] if isinstance(transaction, dict) else 'synthetic-buy'
    return {'signature': signature, 'raw': raw,
            'evidence_hash': hashlib.sha256(canonical_bytes(raw)).hexdigest()}


def derive(raws, *, alternatives=(), raw_sources=(), **overrides):
    selected = [record(raw) for raw in raws]
    return derive_wallet_evidence(selected, all_records=selected + list(alternatives), wallet=WALLET,
        window=WINDOW, source_consistency={'state': 'PASS'}, chronology={'state': 'PASS'},
        raw_sources=raw_sources, **overrides)


def base(signature='synthetic-operation', quantity=0):
    raw = raw_exchange(signature, 100, START + 3600, quantity, quantity)
    raw['transaction']['message']['instructions'] = []
    raw['meta']['innerInstructions'] = []
    raw['meta']['postTokenBalances'] = deepcopy(raw['meta']['preTokenBalances'])
    raw['meta']['postBalances'] = list(raw['meta']['preBalances'])
    raw['meta']['postBalances'][0] -= 5000
    return raw


def parsed(kind, info, program=TOKEN_PROGRAM):
    return {'programId': program, 'parsed': {'type': kind, 'info': info}}


def creation():
    raw = base()
    raw['meta']['preTokenBalances'] = [r for r in raw['meta']['preTokenBalances'] if r['accountIndex'] != 1]
    raw['meta']['preBalances'][1] = 0
    raw['meta']['postBalances'][0] -= 2_000_000
    raw['transaction']['message']['instructions'] = [
        parsed('createAccount', {'source': WALLET, 'newAccount': ACCOUNT, 'owner': TOKEN_PROGRAM,
            'lamports': 2_000_000, 'space': 165}, '11111111111111111111111111111111'),
        parsed('initializeAccount3', {'account': ACCOUNT, 'owner': WALLET, 'mint': MINT})]
    return raw


def boundary(result, signature='synthetic-operation', account=ACCOUNT):
    return result['transactions'][signature]['boundaries'][account]


def test_positive_scoped_raw_facts_and_costs_do_not_certify_wallet_population():
    raw = raw_exchange('synthetic-buy', 100, START + 3600, 0, 100)
    result = derive([raw], events=[{'kind': 'buy', 'basis_sol': '999', 'classification': 'meme'}],
        history_evidence={'account_scope': {'wallet_history_complete': True}, 'metric_decisions': {'history': {'state': 'PASS'}}},
        positions=[{'status': 'closed', 'basis_sol': '999'}])
    for key in ('event_ownership', 'observed_quantities', 'observed_acquisition_basis', 'observed_disposed_basis', 'native_fee'):
        assert result['components'][key]['state'] == 'PASS'
    assert result['acquisitions'][0]['basis_sol'] == '1.000005'
    assert result['acquisitions'][0]['classification'] == 'unknown'
    assert result['components']['historical_population']['state'] == 'UNKNOWN'
    assert result['components']['acquisition_basis']['state'] == 'UNKNOWN'
    assert all(result['interval_checks'][name]['state'] == 'UNKNOWN' for name in ('report_period', 'four_weeks', 'verification_90d'))
    assert all(check['state'] == 'UNKNOWN' for key, check in result['metric_dependencies'].items() if key != 'observed_network_fees_sol')
    assert result['provider_requests'] == result['credential_lookups'] == 0
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('variant', ['missing', 'conflicting', 'unsupported', 'malformed-operation'])
def test_linked_alternative_loss_conflict_or_unsupported_source_cannot_be_ignored(variant):
    raw = raw_exchange('synthetic-buy', 100, START + 3600, 0, 100)
    alternative = deepcopy(raw)
    if variant == 'missing':
        link = {'signature': 'synthetic-buy', 'evidence_hash': 'a' * 64, 'raw': None}
    else:
        if variant == 'conflicting':
            alternative['meta']['preTokenBalances'][0]['uiTokenAmount']['amount'] = '50'
            alternative['meta']['postTokenBalances'][0]['uiTokenAmount']['amount'] = '150'
        elif variant == 'unsupported':
            alternative['version'] = 1
        else:
            alternative['meta']['innerInstructions'][0]['instructions'][0]['parsed']['info']['destination'] = []
        link = record(alternative)
    result = derive([raw], alternatives=[link])
    assert result['components']['observed_quantities']['state'] == 'UNKNOWN'
    assert result['components']['observed_disposed_basis']['state'] == 'UNKNOWN'
    assert link['evidence_hash'] in result['components']['observed_quantities']['evidence']
    restored = derive([raw], alternatives=[record(deepcopy(raw))])
    assert restored['components']['observed_quantities']['state'] == 'PASS'
    assert restored['components']['observed_disposed_basis']['state'] == 'PASS'


@pytest.mark.parametrize('signature,digest', [('synthetic-buy', None), (None, None), ('synthetic-buy', 'bad')])
def test_malformed_or_unassignable_native_link_cannot_certify_selected_facts(signature, digest):
    raw = raw_exchange('synthetic-buy', 100, START + 3600, 0, 100)
    result = derive([raw], alternatives=[{'signature': signature, 'evidence_hash': digest, 'raw': None}])
    for key in ('selected_record_identity', 'observed_quantities', 'event_ownership', 'observed_disposed_basis', 'native_fee'):
        assert result['components'][key]['state'] == 'UNKNOWN'
    assert result['source_consistency']['source_set']['state'] == 'UNKNOWN'


def test_missing_fee_isolated_from_raw_physical_quantities_and_ownership():
    raw = raw_exchange('synthetic-buy', 100, START + 3600, 0, 100)
    raw['meta']['fee'] = None
    result = derive([raw])
    assert result['components']['observed_quantities']['state'] == 'PASS'
    assert result['components']['event_ownership']['state'] == 'PASS'
    assert result['components']['native_fee']['state'] == 'UNKNOWN'
    assert result['components']['observed_disposed_basis']['state'] == 'UNKNOWN'


def test_internal_transfer_preserves_mint_aggregate_and_does_not_create_a_purchase():
    raw = base(quantity=100)
    for name, source_units, destination_units in (('preTokenBalances', 100, 0), ('postTokenBalances', 0, 100)):
        for row in raw['meta'][name]:
            if row['accountIndex'] in (1, 3):
                row['owner'] = WALLET
                row['uiTokenAmount']['amount'] = str(source_units if row['accountIndex'] == 1 else destination_units)
    raw['transaction']['message']['instructions'] = [transfer(ACCOUNT, POOL_TOKEN, 100)]
    result = derive([raw])
    observed = result['transactions']['synthetic-operation']
    assert observed['mint_aggregates'][MINT]['pre_raw'] == observed['mint_aggregates'][MINT]['post_raw'] == '100'
    assert observed['mint_aggregates'][MINT]['check']['state'] == 'PASS'
    assert observed['mint_aggregates'][MINT]['wallet_population'] == 'UNKNOWN'
    assert len(observed['internal_transfers']) == 1
    assert observed['internal_transfers'][0]['check']['state'] == 'PASS'
    assert result['acquisitions'] == []


def test_native_create_initialize_derives_missing_zero_endpoint_from_actual_operations():
    result = derive([creation()])
    pair = boundary(result)
    assert pair['pre']['quantity'] == pair['post']['quantity'] == '0'
    assert pair['checks']['ownership']['state'] == pair['checks']['quantities']['state'] == 'PASS'
    assert pair['program'] == TOKEN_PROGRAM
    assert len(result['transactions']['synthetic-operation']['lifecycle']) == 1


@pytest.mark.parametrize('variant', ['owner-missing', 'program-conflict', 'reversed', 'ata-only'])
def test_creation_requires_correct_executed_owner_program_and_order(variant):
    raw = creation()
    instructions = raw['transaction']['message']['instructions']
    if variant == 'owner-missing':
        del instructions[1]['parsed']['info']['owner']
    elif variant == 'program-conflict':
        instructions[0]['parsed']['info']['owner'] = address(19)
    elif variant == 'reversed':
        instructions.reverse()
    else:
        raw['transaction']['message']['instructions'] = [parsed('createIdempotent', {
            'account': ACCOUNT, 'source': WALLET, 'wallet': WALLET, 'mint': MINT},
            'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')]
    result = derive([raw])
    assert result['components']['observed_quantities']['state'] == 'UNKNOWN'


def test_zero_quantity_close_uses_native_zero_endpoint_without_closing_other_mint_accounts():
    raw = base()
    raw['meta']['postTokenBalances'] = [r for r in raw['meta']['postTokenBalances'] if r['accountIndex'] != 1]
    raw['meta']['postBalances'][1] = 0
    raw['meta']['postBalances'][0] += 2_000_000
    raw['transaction']['message']['instructions'] = [parsed('closeAccount', {'account': ACCOUNT, 'destination': WALLET, 'owner': WALLET})]
    result = derive([raw])
    assert boundary(result)['post']['quantity'] == '0'
    assert boundary(result)['checks']['quantities']['state'] == 'PASS'
    assert result['components']['positions']['state'] == 'UNKNOWN'
    raw['meta']['postBalances'][1] = 1
    assert derive([raw])['components']['observed_quantities']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('inner', [False, True])
def test_account_owner_change_is_phase_specific_and_does_not_become_a_sale(inner):
    raw = base(quantity=100)
    new_owner = address(20)
    raw['meta']['postTokenBalances'][0]['owner'] = new_owner
    change = parsed('setAuthority', {'account': ACCOUNT, 'authorityType': 'accountOwner', 'authority': WALLET, 'newAuthority': new_owner})
    raw['transaction']['message']['instructions'] = [change]
    if inner:
        raw['transaction']['message']['instructions'] = [{'programId': 'ComputeBudget111111111111111111111111111111', 'accounts': [], 'data': ''}]
        raw['meta']['innerInstructions'] = [{'index': 0, 'instructions': [change]}]
    result = derive([raw])
    pair = boundary(result)
    assert pair['checks']['ownership']['state'] == 'PASS'
    assert pair['pre']['owner'] == WALLET and pair['post']['owner'] == new_owner
    assert result['transactions']['synthetic-operation']['mint_aggregates'][MINT]['delta_raw'] == '-100'
    assert result['acquisitions'] == []
    assert result['components']['valued_external_flows']['state'] == 'UNKNOWN'


def test_failed_attempted_owner_change_never_changes_committed_owner():
    raw = base(quantity=100)
    raw['meta']['err'] = {'InstructionError': [0, 'Custom']}
    raw['transaction']['message']['instructions'] = [parsed('setAuthority', {
        'account': ACCOUNT, 'authorityType': 'accountOwner', 'authority': WALLET, 'newAuthority': address(20)})]
    result = derive([raw])
    assert boundary(result)['checks']['ownership']['state'] == 'PASS'
    assert boundary(result)['post']['owner'] == WALLET
    assert result['transactions']['synthetic-operation']['lifecycle'][0]['applied'] is False
    assert result['components']['native_fee']['state'] == 'PASS'


@pytest.mark.parametrize('variant', ['missing-info', 'duplicate-inner', 'mixed-shape', 'missing-new-owner'])
def test_malformed_lifecycle_retains_dependencies_without_erasing_independent_fee(variant):
    raw = base(quantity=100)
    change = parsed('setAuthority', {'account': ACCOUNT, 'authorityType': 'accountOwner', 'authority': WALLET, 'newAuthority': address(20)})
    raw['transaction']['message']['instructions'] = [change]
    if variant == 'missing-info':
        change['parsed']['info'] = None
    elif variant == 'duplicate-inner':
        raw['meta']['innerInstructions'] = [{'index': 0, 'instructions': []}] * 2
    elif variant == 'mixed-shape':
        change['accounts'] = []
    else:
        del change['parsed']['info']['newAuthority']
    result = derive([raw])
    assert result['components']['event_ownership']['state'] == 'UNKNOWN'
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['gaps']


def test_selected_record_window_membership_is_independent_for_report_28_and_90_days():
    raw = raw_exchange('old-buy', 100, END - 40 * 86400, 0, 100)
    result = derive([raw])
    assert result['interval_checks']['four_weeks']['selected_record_membership']['old-buy']['member'] is False
    assert result['interval_checks']['verification_90d']['selected_record_membership']['old-buy']['member'] is True
    assert result['interval_checks']['report_period']['selected_record_membership']['old-buy']['member'] is False
    assert all(result['interval_checks'][key]['state'] == 'UNKNOWN' for key in result['interval_checks'])


def test_missing_relevant_clock_revokes_membership_while_disjoint_block_and_fee_remain_supported():
    raw = raw_exchange('synthetic-buy', 100, START + 3600, 0, 100)
    missing = {'hash': 'a' * 64, 'role': 'block-order', 'state': 'PASS', 'scope': {'slot': 999}}
    result = derive([raw], source_receipts=[missing])
    assert result['components']['fee_window']['state'] == 'UNKNOWN'
    assert result['components']['native_fee']['state'] == 'PASS'
    payload = {'method': 'getBlock', 'slot': 999, 'result': {'signatures': ['unrelated'], 'blockTime': START}}
    raw_source = {'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'kind': 'block-order', 'payload': payload}
    assert derive([raw], raw_sources=[raw_source])['components']['fee_window']['state'] == 'PASS'


@pytest.mark.parametrize('sponsored', [False, True])
def test_proved_zero_wallet_fee_projection_does_not_require_known_clock_placement(sponsored):
    raw = base()
    if sponsored:
        raw['transaction']['message']['accountKeys'][0], raw['transaction']['message']['accountKeys'][3] = (
            raw['transaction']['message']['accountKeys'][3], raw['transaction']['message']['accountKeys'][0])
    else:
        raw['meta']['fee'] = 0
        raw['meta']['postBalances'] = list(raw['meta']['preBalances'])
    result = derive([raw], source_receipts=[{'hash': 'a' * 64, 'role': 'block-order', 'state': 'PASS'}])
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['components']['fee_window']['state'] == 'PASS'
    assert result['transactions']['synthetic-operation']['network_fee']['lamports'] == '0'
    assert result['interval_checks']['report_period']['selected_record_membership']['synthetic-operation']['state'] == 'UNKNOWN'


def test_same_slot_raw_block_order_is_used_by_existing_fifo_not_caller_order():
    bundle = json.loads((Path(__file__).resolve().parents[1] / 'scanner/examples/archive-wallet-synthetic.json').read_text())
    records = [deepcopy(bundle['payloads'][row['hash']]) for row in bundle['manifest']['transactions'] if row['signature'] in ('development-7', 'development-8')]
    for raw in records:
        raw['slot'] = 4000; raw['blockTime'] = 1780876800
    wallet = bundle['manifest']['address']; window = bundle['manifest']['window']
    rows = [record(raw) for raw in records]
    payload = {'method': 'getBlock', 'slot': 4000, 'result': {'signatures': ['development-7', 'development-8'], 'blockTime': 1780876800}}
    source = {'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'kind': 'block-order', 'payload': payload}
    def replay(sources, supplied_indices=False):
        linked = [{**r, **({'transaction_index': 1 - i} if supplied_indices else {})} for i, r in enumerate(rows)]
        return derive_wallet_evidence(linked, all_records=linked, wallet=wallet, window=window,
            source_consistency={}, chronology={}, raw_sources=sources)
    positive = replay([source], True)
    assert positive['components']['observed_disposed_basis']['state'] == 'PASS'
    assert positive['observed_fifo_positions'][0]['matched_basis_sol'] == '2.000005'
    absent = replay([], True)
    assert absent['components']['observed_disposed_basis']['state'] == 'UNKNOWN'
    assert absent['components']['native_fee']['state'] == 'PASS'
    conflicting = deepcopy(payload); conflicting['result']['signatures'].reverse()
    second = {'hash': hashlib.sha256(canonical_bytes(conflicting)).hexdigest(), 'kind': 'block-order', 'payload': conflicting}
    assert replay([source, second])['components']['observed_disposed_basis']['state'] == 'UNKNOWN'


def test_same_slot_selected_continuity_uses_block_order_instead_of_signature_spelling():
    raws = [raw_exchange('z-purchase', 4000, START + 3600, 0, 100),
            raw_exchange('a-sale', 4000, START + 3600, 100, 50)]
    payload = {'method': 'getBlock', 'slot': 4000, 'result': {'signatures': ['z-purchase', 'a-sale'], 'blockTime': START + 3600}}
    source = {'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'kind': 'block-order', 'payload': payload}
    positive = derive(raws, raw_sources=[source])
    assert positive['components']['quantity_continuity']['state'] == 'PASS'
    assert positive['components']['observed_disposed_basis']['state'] == 'PASS'
    assert derive(raws)['components']['quantity_continuity']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('missing', [False, True])
def test_unsupported_role_cannot_hide_a_selected_transaction_dependency(missing):
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    payload = deepcopy(raw)
    payload['meta']['fee'] = 6000
    source = {'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'kind': 'unsupported-role',
              'payload': None if missing else payload, 'signature': 'buy'}
    result = derive([raw], raw_sources=[source])
    assert result['components']['native_fee']['state'] == 'UNKNOWN'
    assert result['components']['observed_quantities']['state'] == 'UNKNOWN'
    assert source['hash'] in result['components']['native_fee']['evidence']


def test_unassignable_unsupported_source_blocks_certification_but_proved_disjoint_raw_identity_does_not():
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    source = {'hash': 'a' * 64, 'kind': 'unsupported-role', 'payload': None}
    assert derive([raw], raw_sources=[source])['components']['native_fee']['state'] == 'UNKNOWN'
    unrelated = raw_exchange('unrelated', 999, END + 3600, 0, 100)
    source = {'hash': hashlib.sha256(canonical_bytes(unrelated)).hexdigest(), 'kind': 'unsupported-role', 'payload': unrelated}
    result = derive([raw], raw_sources=[source])
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['source_dependencies'][0]['state'] == 'UNKNOWN'


def test_available_disjoint_source_bytes_are_not_lost_when_its_receipt_lacks_payload():
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    unrelated = raw_exchange('unrelated', 999, END + 3600, 0, 100)
    source = {'hash': hashlib.sha256(canonical_bytes(unrelated)).hexdigest(), 'kind': 'unsupported-role', 'payload': unrelated}
    receipt = {'hash': source['hash'], 'role': source['kind'], 'state': 'UNKNOWN', 'reason': 'No role adapter'}
    result = derive([raw], raw_sources=[source], source_receipts=[receipt])
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['components']['observed_quantities']['state'] == 'PASS'
    missing = derive([raw], source_receipts=[receipt])
    assert missing['components']['native_fee']['state'] == 'UNKNOWN'


def test_unexplained_owner_transition_cannot_certify_wallet_owned_aggregate():
    raw = base(quantity=100)
    raw['meta']['postTokenBalances'][0]['owner'] = address(20)
    result = derive([raw])
    assert boundary(result)['checks']['quantities']['state'] == 'PASS'
    assert boundary(result)['checks']['ownership']['state'] == 'UNKNOWN'
    assert result['transactions']['synthetic-operation']['mint_aggregates'][MINT]['check']['state'] == 'UNKNOWN'


def test_linked_chronology_conflict_revokes_ordered_basis_without_erasing_purchase_cost():
    raws = [raw_exchange('buy', 100, START + 3600, 0, 100), raw_exchange('sale', 101, START + 7200, 100, 0)]
    alternative = deepcopy(raws[0]); alternative['blockTime'] = START + 3 * 3600
    result = derive(raws, alternatives=[record(alternative)])
    assert result['components']['observed_acquisition_basis']['state'] == 'PASS'
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['components']['chronology']['state'] == 'UNKNOWN'
    assert result['components']['observed_disposed_basis']['state'] == 'UNKNOWN'
    assert result['components']['observed_positions']['state'] == 'UNKNOWN'


def test_existing_fifo_retains_losing_and_breakeven_episodes_with_unresolved_real_population():
    bundle = json.loads((Path(__file__).resolve().parents[1] / 'scanner/examples/archive-wallet-synthetic.json').read_text())
    rows = [{'signature': row['signature'], 'raw': bundle['payloads'][row['hash']], 'evidence_hash': row['hash']}
            for row in bundle['manifest']['transactions']]
    result = derive_wallet_evidence(rows, all_records=rows, wallet=bundle['manifest']['address'], window=bundle['manifest']['window'],
        source_consistency={}, chronology={})
    assert len(result['observed_fifo_positions']) == 5
    assert sorted(p['pnl_sol'] for p in result['observed_fifo_positions']) == sorted(['1.999985', '-1.00001', '-1.00001', '0', '0.49999'])
    assert result['components']['observed_disposed_basis']['state'] == 'PASS'
    assert result['components']['positions']['state'] == 'UNKNOWN'


def test_unaccepted_classification_valuation_sources_remain_dependencies_and_do_not_erase_fees():
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    sources = []
    for kind in ('classification', 'valuation'):
        payload = {'kind': kind, 'classification': 'meme', 'complete': True}
        sources.append({'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'kind': kind, 'payload': payload})
    result = derive([raw], raw_sources=sources)
    assert result['components']['native_fee']['state'] == 'PASS'
    assert sources[0]['hash'] in result['components']['classification']['evidence']
    assert sources[1]['hash'] in result['components']['historical_marks']['evidence']
    assert result['components']['classification']['state'] == result['components']['historical_marks']['state'] == 'UNKNOWN'
    assert len(result['source_dependencies']) == 2


def test_validated_disjoint_lifecycle_target_does_not_erase_observed_named_account_quantities():
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    raw['transaction']['message']['instructions'].append(parsed('initializeAccount3', {'account': POOL_TOKEN, 'mint': MINT}))
    result = derive([raw])
    assert result['components']['observed_quantities']['state'] == 'PASS'
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['transactions']['buy']['disjoint_operations']
    assert result['components']['historical_population']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('authority_type', ['mintTokens', 'freezeAccount'])
@pytest.mark.parametrize('inner', [False, True])
def test_mint_target_authority_changes_keep_account_owner_and_quantity_observations(authority_type, inner):
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    instruction = parsed('setAuthority', {'mint': MINT, 'authorityType': authority_type, 'authority': POOL_TOKEN, 'newAuthority': WALLET})
    if inner:
        raw['meta']['innerInstructions'][0]['instructions'].append(instruction)
    else:
        raw['transaction']['message']['instructions'].append(instruction)
    result = derive([raw])
    assert result['components']['observed_quantities']['state'] == 'PASS'
    assert result['components']['event_ownership']['state'] == 'PASS'
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['components']['classification']['state'] == 'UNKNOWN'
    assert result['transactions']['buy']['disjoint_operations']


def mint_metadata():
    return {'method': 'getAccountInfo', 'address': MINT, 'commitment': 'finalized',
            'result': {'context': {'slot': 1000}, 'value': {'owner': TOKEN_PROGRAM, 'lamports': 1, 'executable': False,
                'data': {'parsed': {'type': 'mint', 'info': {}}}}}}


@pytest.mark.parametrize('kind', ['current-mint-controls', 'other-report-metadata'])
def test_supported_current_mint_metadata_is_semantically_disjoint_from_selected_native_fees(kind):
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    payload = mint_metadata()
    source = {'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'kind': kind, 'payload': payload}
    result = derive([raw], raw_sources=[source], source_receipts=[{'hash': source['hash'], 'role': kind, 'state': 'UNKNOWN'}])
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['components']['event_ownership']['state'] == 'PASS'
    assert result['components']['classification']['state'] == 'UNKNOWN'
    assert result['components']['historical_population']['state'] == 'UNKNOWN'
    assert source['hash'] in result['source_dependencies'][0]['evidence']


def test_missing_current_mint_metadata_is_its_own_dependency_without_erasing_fees():
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    receipt = {'hash': 'a' * 64, 'role': 'current-mint-controls', 'state': 'PASS'}
    result = derive([raw], source_receipts=[receipt])
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['components']['event_ownership']['state'] == 'PASS'
    assert result['components']['classification']['state'] == 'UNKNOWN'
    assert result['source_dependencies'][0]['state'] == 'UNKNOWN'


def test_current_mint_label_cannot_hide_selected_transaction_alternative():
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    alternative = deepcopy(raw); alternative['meta']['fee'] = 6000
    source = {'hash': hashlib.sha256(canonical_bytes(alternative)).hexdigest(), 'kind': 'current-mint-controls', 'payload': alternative}
    result = derive([raw], raw_sources=[source])
    assert result['components']['native_fee']['state'] == 'UNKNOWN'
    assert result['components']['observed_quantities']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('variant', ['wrong-method', 'missing-context', 'nonfinalized', 'hidden-transaction'])
def test_present_malformed_current_metadata_does_not_gain_exemption_from_label(variant):
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    payload = mint_metadata()
    if variant == 'wrong-method':
        payload['method'] = 'getTransaction'
    elif variant == 'missing-context':
        payload['result']['context'] = None
    elif variant == 'nonfinalized':
        payload['commitment'] = 'processed'
    else:
        payload['result']['transaction'] = {'signatures': ['buy']}
    source = {'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'kind': 'current-mint-controls', 'payload': payload}
    assert derive([raw], raw_sources=[source])['components']['native_fee']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('role', ['classification', 'valuation', 'current-mint-controls'])
@pytest.mark.parametrize('location', ['root', 'result', 'value'])
def test_native_shaped_unassignable_evidence_keeps_negative_affinity_for_every_role(role, location):
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    alternative = deepcopy(raw); alternative['transaction']['signatures'] = []
    payload = alternative
    if location == 'result':
        payload = {'result': alternative}
    elif location == 'value':
        payload = mint_metadata(); payload['result']['value'] = alternative
    source = {'kind': role, 'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'payload': payload}
    dependencies = raw_native_dependencies([source], (), {'buy'})
    assert dependencies == [{'signature': None, 'evidence_hash': source['hash'], 'raw': None}]
    result = derive([raw], raw_sources=[source])
    assert result['components']['native_fee']['state'] == 'UNKNOWN'
    # The importing/report caller freezes the negative links. Raw source loss
    # then cannot remove the original unassignable native dependency.
    assert derive([raw], alternatives=dependencies)['components']['native_fee']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('location', ['root', 'result', 'value'])
def test_raw_native_dependency_helper_binds_selected_signature_under_wrappers(location):
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    alternative = deepcopy(raw); alternative['meta']['fee'] = 6000
    payload = alternative
    if location == 'result':
        payload = {'result': alternative}
    elif location == 'value':
        payload = mint_metadata(); payload['result']['value'] = alternative
    source = {'kind': 'current-mint-controls', 'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(), 'payload': payload}
    dependencies = raw_native_dependencies([source], (), {'buy'})
    assert dependencies == [{'signature': 'buy', 'evidence_hash': source['hash'], 'raw': None}]
    assert derive([raw], raw_sources=[source])['components']['native_fee']['state'] == 'UNKNOWN'
    assert derive([raw], alternatives=dependencies)['components']['native_fee']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('bad_hints', [1, None, {'buy': True}, ['buy', 1]])
def test_invalid_signature_hint_container_is_negative_ambiguity_without_runtime_exception(bad_hints):
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    payload = {'arbitrary': 'unsupported'}
    source = {'kind': 'unsupported-role', 'hash': hashlib.sha256(canonical_bytes(payload)).hexdigest(),
              'payload': payload, 'signature_hints': bad_hints}
    assert derive([raw], raw_sources=[source])['components']['native_fee']['state'] == 'UNKNOWN'


def test_account_union_version_budget_is_graceful_and_preserves_independent_native_fees(monkeypatch):
    # Exercise the same Cartesian limit as 512 distinct account alternatives,
    # with a smaller bound so this regression stays fast and meaningful.
    import scanner.wallet_evidence as module
    raw = base('same-signature')
    alternatives = []
    for i in range(10):
        variant = deepcopy(raw)
        variant['transaction']['message']['accountKeys'][1] = address(30 + i)
        alternatives.append(record(variant))
    monkeypatch.setattr(module, 'MAX_ACCOUNT_STEPS', 100)
    result = derive([raw], alternatives=alternatives)
    assert result['inspection_budget']['account_steps'] <= 100
    assert result['inspection_budget']['account_version_steps'] > 100
    assert result['inspection_budget']['quantity_state'] == 'UNKNOWN'
    assert result['components']['observed_quantities']['state'] == 'UNKNOWN'
    assert result['components']['observed_economic_roles']['state'] == 'UNKNOWN'
    assert result['components']['native_fee']['state'] == 'PASS'


def test_unexplained_native_flow_revokes_economic_role_but_preserves_actual_fee():
    raw = base()
    positive = derive([raw])
    assert positive['components']['observed_economic_roles']['state'] == 'PASS'
    raw['meta']['postBalances'][0] -= 1_000_000_000
    raw['meta']['postBalances'][3] += 1_000_000_000
    result = derive([raw])
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['components']['observed_economic_roles']['state'] == 'UNKNOWN'
    assert result['native_role_checks'][0]['actual_lamports'] == '-1000005000'
    assert result['native_role_checks'][0]['expected_lamports'] == '-5000'


def test_budget_loss_cannot_drop_a_negative_cost_role_or_disposed_basis_dependency(monkeypatch):
    import scanner.wallet_evidence as module
    raw = raw_exchange('buy', 100, START + 3600, 0, 100)
    variant = deepcopy(raw)
    variant['meta']['innerInstructions'][0]['instructions'][1]['parsed']['info']['tokenAmount']['amount'] = '2000000000'
    alternatives = [record(variant)]
    before = derive([raw], alternatives=alternatives)
    assert before['components']['observed_economic_roles']['state'] == 'UNKNOWN'
    monkeypatch.setattr(module, 'MAX_ACCOUNT_STEPS', 1)
    after = derive([raw], alternatives=alternatives)
    assert after['components']['observed_economic_roles']['state'] == 'UNKNOWN'
    assert after['components']['observed_disposed_basis']['state'] == 'UNKNOWN'
    assert after['components']['native_fee']['state'] == 'PASS'


def test_permutation_duplicate_sources_and_caller_pass_flags_do_not_change_results():
    raws = [raw_exchange('buy', 100, START + 3600, 0, 100), raw_exchange('sale', 101, START + 7200, 100, 0)]
    rows = [record(raw) for raw in raws]
    before = deepcopy(rows)
    def replay(selected, all_records):
        return derive_wallet_evidence(selected, all_records=all_records, wallet=WALLET, window=WINDOW,
            source_consistency={'state': 'PASS', 'source_set': {'state': 'PASS'}},
            chronology={'state': 'PASS', 'transactions': {'buy': {'time_state': 'PASS'}}})
    first = replay(rows, rows)
    second = replay(list(reversed(rows * 2)), list(reversed(rows * 2)))
    assert first == second
    assert rows == before


@pytest.mark.parametrize('field,bad', [('meta', []), ('transaction', None), ('version', 1), ('blockTime', []), ('preTokenBalances', [None])])
def test_malformed_raw_shapes_remain_explicit_without_runtime_failure(field, bad):
    raw = raw_exchange('synthetic-buy', 100, START + 3600, 0, 100)
    if field == 'preTokenBalances':
        raw['meta'][field] = bad
    else:
        raw[field] = bad
    result = derive([raw])
    assert result['components']['historical_population']['state'] == 'UNKNOWN'
    assert result['components']['observed_disposed_basis']['state'] == 'UNKNOWN'
    assert result['gaps']
