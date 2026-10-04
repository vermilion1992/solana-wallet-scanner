"""Additional independent R7/R8 controls, using synthetic local archives only.

The supplied review's 30 assertions are retained separately in tests/review_v033.
These controls cover compatible observations, exact selected populations, both
report boundaries, and unrelated episodes. They make no mainnet authenticity claim.
"""
from copy import deepcopy

import pytest

from scanner.history_evidence import derive_history_evidence
from scanner.position_evidence import derive_position_evidence
from tests.review_v033.review_helpers import (position_builder, history_builder,
                                             pb, hb, add_block, all_same_slot,
                                             failed_middle, assert_unknown_hold)


def native_history(builder, records=None):
    return derive_history_evidence(builder.store, pb.WALLET, pb.WINDOW,
                                    checkpoint=builder.cp,
                                    collected={'transactions': builder.records if records is None else records})


def archive_block(builder, slot, signatures, **result_fields):
    digest = builder.store.archive({'method': 'getBlock', 'slot': slot,
                                    'result': {'signatures': signatures, **result_fields}})
    builder.cp['evidence'].append({'hash': digest, 'kind': 'block-order'})
    builder.cp['ordering'].update({signature: index for index, signature in enumerate(signatures)})
    builder.persist()
    return digest


def add_upper_marker(builder):
    """Supply a connected raw-less finalized UTC upper boundary on both accounts."""
    marker = {'signature': 'synthetic-upper-marker', 'slot': 999, 'blockTime': pb.END,
              'err': None, 'confirmationStatus': 'finalized'}
    for account, (initial, terminal) in list(builder.pages.items()):
        page = builder.store.evidence(initial)
        page['result'].insert(0, deepcopy(marker))
        digest = builder.store.archive(page)
        for reference in builder.cp['evidence']:
            if reference['kind'] == 'signature-page' and reference['hash'] == initial:
                reference['hash'] = digest
        builder.pages[account] = (digest, terminal)
    builder.persist()


def test_distinct_archive_hashes_with_identical_block_facts_are_compatible(position_builder):
    signatures = all_same_slot(position_builder, consistent_time=True)
    first = add_block(position_builder, 100, signatures, block_time=pb.START + 3600)
    envelope = position_builder.store.evidence(first)
    envelope['observed_at'] = '2026-10-03T01:00:00+00:00'
    second = position_builder.store.archive(envelope)
    assert second != first
    position_builder.cp['evidence'].append({'hash': second, 'kind': 'block-order'})
    position_builder.persist()
    result = position_builder.derive()
    assert result['counts']['known_closed'] == 1
    assert result['positions'][0]['hold_hours']['value'] == '0'


@pytest.mark.parametrize('missing_time', ['absent', 'null'])
def test_optional_unavailable_block_time_does_not_conflict_with_consistent_observation(position_builder, missing_time):
    signatures = all_same_slot(position_builder, consistent_time=True)
    if missing_time == 'absent':
        archive_block(position_builder, 100, signatures)
    else:
        archive_block(position_builder, 100, signatures, blockTime=None)
    add_block(position_builder, 100, signatures, block_time=pb.START + 3600)
    result = position_builder.derive()
    assert result['counts']['known_closed'] == 1
    assert result['positions'][0]['hold_hours']['value'] == '0'


@pytest.mark.parametrize('reverse_references', [False, True])
def test_conflicting_block_times_do_not_depend_on_reference_order(position_builder, reverse_references):
    signatures = all_same_slot(position_builder, consistent_time=True)
    times = [pb.START + 3600, pb.START + 7200]
    if reverse_references:
        times.reverse()
    for timestamp in times:
        add_block(position_builder, 100, signatures, block_time=timestamp)
    assert_unknown_hold(position_builder.derive())
    observed = native_history(position_builder)['native_address_metrics']['observed']['wallet_network_fees_sol']
    assert observed['status'] == 'known' and observed['value'] == '0.000015'


def test_single_transaction_slot_clock_conflict_revokes_period_but_not_observed_fees(position_builder):
    add_upper_marker(position_builder)
    baseline = native_history(position_builder)
    assert baseline['paging']['wallet_address_intervals']['report_period']['state'] == 'PASS'
    add_block(position_builder, 100, ['synthetic-buy'], block_time=pb.END)
    assert_unknown_hold(position_builder.derive())
    result = native_history(position_builder)
    assert result['paging']['wallet_address_intervals']['report_period']['state'] == 'UNKNOWN'
    assert result['native_address_metrics']['periods']['report_period']['wallet_network_fees_sol']['value'] is None
    observed = result['native_address_metrics']['observed']['wallet_network_fees_sol']
    assert observed['status'] == 'known' and observed['value'] == '0.000015'


def test_unselected_same_slot_record_still_reconciles_clock_without_expanding_observed_population(history_builder):
    raw = history_builder.store.evidence(history_builder.cp['transactions']['boundary']['evidence_hash'])
    raw['slot'] = 1200
    history_builder.replace_transaction('boundary', raw)
    digest = history_builder.store.archive({'method': 'getBlock', 'slot': 1200,
                                           'result': {'signatures': ['boundary', 'inside']}})
    history_builder.cp['evidence'].append({'kind': 'block-order', 'hash': digest})
    history_builder.cp['ordering'] = {'boundary': 0, 'inside': 1}
    history_builder.save()
    result = history_builder.derive(selected=['inside'])
    assert result['record_provenance']['counts']['inspected'] == 1
    selected_receipt = result['record_provenance']['records'][0]
    assert selected_receipt['ordering']['state'] == 'UNKNOWN'
    assert result['paging']['wallet_address_intervals']['report_period']['state'] == 'UNKNOWN'
    observed = result['native_address_metrics']['observed']['wallet_network_fees_sol']
    assert observed['status'] == 'known' and observed['record_count'] == 1
    assert observed['value'] == '0.000005'


def test_correcting_same_slot_times_recovers_zero_hold_and_preserves_native_sum(position_builder):
    signatures = all_same_slot(position_builder, consistent_time=False)
    add_block(position_builder, 100, signatures)
    assert_unknown_hold(position_builder.derive())
    for raw in position_builder.raws:
        raw['blockTime'] = pb.START + 3600
    position_builder.seed()
    add_block(position_builder, 100, signatures, block_time=pb.START + 3600)
    result = position_builder.derive()
    assert result['counts']['known_closed'] == 1
    assert result['positions'][0]['hold_hours']['value'] == '0'
    assert native_history(position_builder)['native_address_metrics']['observed']['wallet_network_fees_sol']['value'] == '0.000015'


@pytest.mark.parametrize('timestamp', [pb.START - 1, None])
@pytest.mark.parametrize('remove_raw', [False, True])
def test_lower_or_unknown_time_cannot_remove_intermediate_dependency(position_builder, timestamp, remove_raw):
    failed_middle(position_builder, timestamp=timestamp)
    if remove_raw:
        position_builder.remove_archive(position_builder.records[1]['evidence_hash'])
    assert_unknown_hold(position_builder.derive())


@pytest.mark.parametrize('timestamp', [pb.END + 3600, pb.START - 1])
@pytest.mark.parametrize('remove_raw', [False, True])
def test_later_distinct_slot_record_does_not_revoke_earlier_episode_or_selected_native_sum(
        position_builder, timestamp, remove_raw):
    later = pb.raw_exchange('synthetic-unrelated-later', 103, timestamp, 0, 0)
    later['meta'].update(err={'InstructionError': [0, 'Custom']},
                         preTokenBalances=[], postTokenBalances=[])
    position_builder.raws.append(later)
    position_builder.seed()
    earlier_records = position_builder.records[:3]
    if remove_raw:
        position_builder.remove_archive(position_builder.records[3]['evidence_hash'])
    result = derive_position_evidence(position_builder.store, pb.WALLET, pb.WINDOW,
                                      checkpoint=position_builder.cp,
                                      collected={'transactions': earlier_records})
    assert result['counts']['known_closed'] == 1
    assert result['positions'][0]['hold_hours']['value'] == '6'
    assert result['positions'][0]['signatures'] == ['synthetic-buy', 'synthetic-partial-sale', 'synthetic-final-sale']
    observed = native_history(position_builder, earlier_records)['native_address_metrics']['observed']['wallet_network_fees_sol']
    assert observed['status'] == 'known' and observed['record_count'] == 3
    assert observed['value'] == '0.000015'


@pytest.mark.parametrize('close_time', [pb.END, pb.END + 1])
def test_legitimate_close_at_or_after_upper_boundary_is_not_an_in_period_known_close(position_builder, close_time):
    position_builder.raws[2]['blockTime'] = close_time
    position_builder.seed()
    result = position_builder.derive()
    assert result['counts']['known_closed'] == 0
    assert result['known_account_hold_median_hours']['status'] == 'unknown'


def test_exact_lower_boundary_close_is_included_with_preperiod_opening(position_builder):
    for raw, timestamp in zip(position_builder.raws, [pb.START - 6 * 3600, pb.START - 5 * 3600, pb.START]):
        raw['blockTime'] = timestamp
    position_builder.seed()
    result = position_builder.derive()
    assert result['counts']['known_closed'] == 1
    assert result['positions'][0]['hold_hours']['value'] == '6'


def test_legitimate_completed_episode_before_lower_boundary_is_omitted(position_builder):
    for raw, timestamp in zip(position_builder.raws, [pb.START - 7 * 3600, pb.START - 6 * 3600, pb.START - 1]):
        raw['blockTime'] = timestamp
    position_builder.seed()
    result = position_builder.derive()
    assert result['positions'] == [] and result['counts']['known_closed'] == 0
