"""Positive, removal, R6 and wallet-gate controls expected to pass v0.3.3."""
from copy import deepcopy
import pytest
from scanner.history_evidence import derive_history_evidence
from scanner.report_rebuild import freeze_report_inputs, load_report_inputs
from scanner.storage import EvidenceError
from tests.review_v033.review_helpers import (position_builder, history_builder, pb, hb,
                            add_block, all_same_slot, failed_middle, assert_unknown_hold)


def test_valid_separate_slot_hold_is_six_hours(position_builder):
    result = position_builder.derive()
    assert result['counts'] == {'known_closed': 1, 'open': 0, 'unresolved': 0}
    assert result['positions'][0]['hold_hours']['value'] == '6'
    for field in ('basis', 'fees', 'classification', 'valuation'):
        assert result['positions'][0]['stages'][field]['state'] == 'UNKNOWN'
    history = derive_history_evidence(position_builder.store, pb.WALLET, pb.WINDOW,
                                      checkpoint=position_builder.cp)
    assert set(history['evidence_gates'].values()) == {'UNKNOWN'}
    assert history['metric_decisions']['profit_sol']['state'] == 'UNKNOWN'


def test_valid_same_slot_timestamps_give_zero_hold(position_builder):
    signatures = all_same_slot(position_builder, consistent_time=True)
    add_block(position_builder, 100, signatures, block_time=pb.START + 3600)
    result = position_builder.derive()
    assert result['counts']['known_closed'] == 1
    assert result['positions'][0]['hold_hours']['value'] == '0'


def test_later_sales_in_one_consistent_block_give_six_hours(position_builder):
    position_builder.raws[1]['slot'] = position_builder.raws[2]['slot'] = 101
    position_builder.raws[1]['blockTime'] = position_builder.raws[2]['blockTime'] = pb.START + 7 * 3600
    position_builder.seed()
    add_block(position_builder, 101, ['synthetic-partial-sale', 'synthetic-final-sale'],
              block_time=pb.START + 7 * 3600)
    assert position_builder.derive()['positions'][0]['hold_hours']['value'] == '6'


def test_identical_repeated_block_reference_is_harmless(position_builder):
    signatures = all_same_slot(position_builder, consistent_time=True)
    digest = add_block(position_builder, 100, signatures, block_time=pb.START + 3600)
    position_builder.cp['evidence'].append({'hash': digest, 'kind': 'block-order'})
    position_builder.persist()
    assert position_builder.derive()['counts']['known_closed'] == 1


@pytest.mark.parametrize('kind', ['opening_raw', 'middle_raw', 'closing_raw',
                                 'anchor', 'account_page', 'terminal_page'])
def test_removed_required_source_revokes_normal_hold(position_builder, kind):
    digest = {'opening_raw': position_builder.records[0]['evidence_hash'],
              'middle_raw': position_builder.records[1]['evidence_hash'],
              'closing_raw': position_builder.records[2]['evidence_hash'],
              'anchor': position_builder.anchor,
              'account_page': position_builder.pages[pb.ACCOUNT][0],
              'terminal_page': position_builder.pages[pb.ACCOUNT][1]}[kind]
    position_builder.remove_archive(digest)
    assert_unknown_hold(position_builder.derive())


def test_removed_same_slot_order_receipt_revokes_hold(position_builder):
    signatures = all_same_slot(position_builder, consistent_time=True)
    digest = add_block(position_builder, 100, signatures, block_time=pb.START + 3600)
    position_builder.remove_archive(digest)
    assert_unknown_hold(position_builder.derive())


def test_in_window_failed_time_reversal_is_already_rejected(position_builder):
    failed_middle(position_builder, timestamp=pb.START + 8 * 3600)
    assert_unknown_hold(position_builder.derive())


def test_correcting_failed_middle_time_recovers_hold(position_builder):
    failed_middle(position_builder, timestamp=pb.START + 2 * 3600)
    assert position_builder.derive()['positions'][0]['hold_hours']['value'] == '6'


def test_financial_costs_not_required_for_quantity_only_hold(position_builder):
    for raw in position_builder.raws:
        for key in ('fee', 'preBalances', 'postBalances'):
            raw['meta'].pop(key)
    position_builder.seed()
    assert position_builder.derive()['positions'][0]['hold_hours']['value'] == '6'


@pytest.mark.parametrize('field,value', [('blockTime', hb.START), ('slot', 1101),
                                       ('err', {'InstructionError': [0, 'Custom']}),
                                       ('confirmationStatus', 'confirmed')])
def test_r6_contradictory_boundary_remains_unknown(history_builder, field, value):
    history_builder.mutate_entry(hb.WALLET, 'boundary', **{field: value})
    result = history_builder.derive()
    assert result['paging']['wallet_address_intervals']['report_period']['state'] == 'UNKNOWN'
    metrics = result['native_address_metrics']
    assert metrics['periods']['report_period']['wallet_network_fees_sol']['value'] is None
    assert metrics['observed']['wallet_network_fees_sol']['value'] == '0.00001'
    assert result['metric_decisions']['profit_sol']['state'] == 'UNKNOWN'


def test_r6_consistent_boundary_counts_only_one_period_fee(history_builder):
    result = history_builder.derive()
    assert result['paging']['wallet_address_intervals']['report_period']['state'] == 'PASS'
    assert result['native_address_metrics']['periods']['report_period']['wallet_network_fees_sol']['value'] == '0.000005'


def test_rebuild_loader_already_rejects_conflicting_order(position_builder):
    signatures = all_same_slot(position_builder, consistent_time=True)
    add_block(position_builder, 100, list(reversed(signatures)), block_time=pb.START + 3600)
    add_block(position_builder, 100, signatures, block_time=pb.START + 3600)
    collected = {'transactions': position_builder.records, 'checkpoint': position_builder.cp,
                 'evidence': position_builder.cp['evidence']}
    report = {'source': 'live', 'address': pb.WALLET, 'window': deepcopy(pb.WINDOW)}
    report['collection_input_hash'] = freeze_report_inputs(position_builder.store, pb.WALLET, pb.WINDOW, collected)
    with pytest.raises(EvidenceError, match='ordering conflicts'):
        load_report_inputs(position_builder.store, report)
