"""Positive, dependency-removal and metric-isolation controls for R12."""
from copy import deepcopy
import pytest
from tests.review_v037.review_helpers import builder, pb, conflict_page, evidence_file, damage, history

def assert_known(case):
    result = case.derive()
    assert result['counts']['known_closed'] == 1
    assert result['positions'][0]['hold_hours']['value'] == '6'
    assert set(history(case)['evidence_gates'].values()) == {'UNKNOWN'}
    return result

def test_unmodified_synthetic_six_hour_hold_has_separate_wallet_gates(builder):
    assert_known(builder)
    native = history(builder)['native_address_metrics']['observed']
    assert native['wallet_network_fees_sol']['value'] == '0.000015'
    assert native['native_wallet_delta_sol']['value'] == '-0.000015'

@pytest.mark.parametrize('boundary', ['opening', 'closing'])
@pytest.mark.parametrize('beyond_fee', [False, True], ids=['fee-only-wallet', 'non-fee-wallet-movement'])
def test_available_execution_conflict_keeps_independent_fees_but_revokes_dependent_facts(builder, boundary, beyond_fee):
    ref = conflict_page(builder, boundary, beyond_fee=beyond_fee)
    result = builder.derive(); h = history(builder)
    assert result['counts']['known_closed'] == 0
    assert ref['hash'] in result['positions'][0]['sources']
    native = h['native_address_metrics']['observed']
    assert native['wallet_network_fees_sol']['status'] == 'known'
    assert native['wallet_network_fees_sol']['value'] == '0.000015'
    assert native['wallet_network_fees_sol']['record_count'] == 3
    assert native['native_wallet_delta_sol']['status'] == ('unknown' if beyond_fee else 'known')
    assert native['native_wallet_delta_sol']['value'] == (None if beyond_fee else '-0.000015')
    assert set(h['evidence_gates'].values()) == {'UNKNOWN'}

@pytest.mark.parametrize('role', ['transaction', 'signature-page', 'snapshot-slot'])
def test_duplicate_identical_links_do_not_change_population_or_hold(builder, role):
    ref = next(row for row in builder.cp['evidence'] if row['kind'] == role)
    builder.cp['evidence'].extend(deepcopy(ref) for _ in range(10))
    builder.persist(); assert_known(builder)
    h = history(builder)
    assert h['source_consistency']['source_set']['complete'] is True
    assert h['native_address_metrics']['observed']['wallet_network_fees_sol']['record_count'] == 3

@pytest.mark.parametrize('index', [0, 1, 2])
@pytest.mark.parametrize('variant', ['missing', 'corrupt'])
def test_unreadable_selected_transactions_already_revoke_hold(builder, index, variant):
    damage(evidence_file(builder, builder.records[index]['evidence_hash']), variant)
    assert builder.derive()['counts']['known_closed'] == 0
    assert set(history(builder)['evidence_gates'].values()) == {'UNKNOWN'}

@pytest.mark.parametrize('page_index', [0, 1], ids=['initial', 'terminal'])
@pytest.mark.parametrize('variant', ['missing', 'corrupt'])
def test_unreadable_required_account_chain_page_already_revokes_hold(builder, page_index, variant):
    damage(evidence_file(builder, builder.pages[pb.ACCOUNT][page_index]), variant)
    assert builder.derive()['counts']['known_closed'] == 0

@pytest.mark.parametrize('index', [0, 2], ids=['opening', 'closing'])
@pytest.mark.parametrize('variant', ['missing', 'corrupt'])
def test_unreadable_linked_transaction_alternative_already_revokes_hold(builder, index, variant):
    raw = deepcopy(builder.raws[index]); raw['meta']['logMessages'] = []
    digest = builder.store.archive(raw)
    builder.cp['evidence'].append({'kind': 'transaction', 'hash': digest,
                                   'signature': builder.records[index]['signature']})
    builder.persist(); assert_known(builder)
    damage(evidence_file(builder, digest), variant)
    assert builder.derive()['counts']['known_closed'] == 0


def test_valid_empty_unrelated_account_page_does_not_erase_supported_hold(builder):
    raw = {'method': 'getSignaturesForAddress', 'address': pb.address(70),
           'params': {'limit': 100, 'commitment': 'finalized', 'minContextSlot': 1000}, 'result': []}
    digest = builder.store.archive(raw)
    builder.cp['evidence'].append({'kind': 'signature-page', 'hash': digest})
    builder.persist(); assert_known(builder)


def test_non_fee_wallet_movement_is_known_without_contradictory_sources(builder):
    builder.raws[0]['meta']['postBalances'][0] -= 1000
    builder.raws[0]['meta']['postBalances'][3] += 1000
    builder.seed(); assert_known(builder)
    native = history(builder)['native_address_metrics']['observed']
    assert native['native_wallet_delta_sol']['value'] == '-0.000016'
    assert native['wallet_network_fees_sol']['value'] == '0.000015'
