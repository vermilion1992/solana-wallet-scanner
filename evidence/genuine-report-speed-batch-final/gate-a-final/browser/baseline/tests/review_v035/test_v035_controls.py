"""Additional positive, source-removal and bounded placement controls.
All fixtures are synthetic. Reused fixture builders do not supply assertions.
"""
from copy import deepcopy
from itertools import product
import json
import os
from pathlib import Path
import pytest
from tests import test_position_evidence as pb
from tests.review_v033.review_helpers import position_builder, failed_middle, assert_unknown_hold
from tests.test_review_v034_independent import raw_only, page_only, conserve_failed_endpoints
from scanner.history_evidence import derive_history_evidence
from scanner.position_evidence import _quantity_point
from tests.review_v035.test_v035_regressions import alternate_balance


def six_hours(builder):
    result = builder.derive()
    assert result['counts'] == {'known_closed': 1, 'open': 0, 'unresolved': 0}
    assert result['positions'][0]['hold_hours']['value'] == '6'
    history = derive_history_evidence(builder.store, pb.WALLET, pb.WINDOW,
        checkpoint=builder.cp, collected={'transactions': builder.records})
    assert set(history['evidence_gates'].values()) == {'UNKNOWN'}
    return result


@pytest.mark.parametrize('index', [0, 2])
@pytest.mark.parametrize('kind', ['optional_logs', 'balance_array_order'])
@pytest.mark.parametrize('reverse', [False, True])
def test_semantically_agreeing_distinct_archive_keeps_known_hold(position_builder, index, kind, reverse):
    b = position_builder
    alt = deepcopy(b.raws[index])
    if kind == 'optional_logs':
        alt['meta']['logMessages'] = []
    else:
        alt['meta']['preTokenBalances'].reverse()
        alt['meta']['postTokenBalances'].reverse()
    digest = b.store.archive(alt)
    assert digest != b.records[index]['evidence_hash']
    b.cp['evidence'].append({'kind': 'transaction', 'hash': digest,
                            'signature': b.records[index]['signature']})
    if reverse:
        b.cp['evidence'].reverse()
    b.persist()
    six_hours(b)


@pytest.mark.parametrize('boundary', ['opening', 'closing'])
@pytest.mark.parametrize('reverse', [False, True])
def test_missing_linked_alternative_does_not_certify_hold(position_builder, boundary, reverse):
    details = alternate_balance(position_builder, boundary, reverse)
    position_builder.remove_archive(details['alternative_hash'])
    assert_unknown_hold(position_builder.derive())


@pytest.mark.parametrize('source', ['opening_raw', 'partial_raw', 'closing_raw', 'account_page', 'anchor'])
def test_required_primary_archive_removal_revokes_hold(position_builder, source):
    b = position_builder
    sources = {'opening_raw': b.records[0]['evidence_hash'], 'partial_raw': b.records[1]['evidence_hash'],
        'closing_raw': b.records[2]['evidence_hash'], 'native_page': b.pages[pb.WALLET][0],
        'account_page': b.pages[pb.ACCOUNT][0], 'anchor': b.anchor}
    b.remove_archive(sources[source])
    assert_unknown_hold(b.derive())


def test_caller_pass_certificate_cannot_replace_missing_source(position_builder):
    b = position_builder
    b.remove_archive(b.records[0]['evidence_hash'])
    assert_unknown_hold(b.derive(history_evidence={'state': 'PASS', 'evidence_gates': {'history': 'PASS'}}))


@pytest.mark.parametrize('boundary', ['opening', 'closing'])
def test_token_balance_dispute_does_not_double_count_unchanged_native_fees(position_builder, boundary):
    b = position_builder
    details = alternate_balance(b, boundary)
    history = derive_history_evidence(b.store, pb.WALLET, pb.WINDOW,
        checkpoint=b.cp, collected={'transactions': b.records})
    observed = history['native_address_metrics']['observed']['wallet_network_fees_sol']
    assert observed['status'] == 'known'
    assert observed['record_count'] == 3
    assert observed['value'] == '0.000015'
    assert set(history['evidence_gates'].values()) == {'UNKNOWN'}
    # Both alternatives retain identical transferred units, but disagree about
    # the absolute opening/closing quantities used by the strict-zero proof.
    left = _quantity_point(details['original'], pb.WALLET, pb.ACCOUNT)
    right = _quantity_point(details['alternative'], pb.WALLET, pb.ACCOUNT)
    assert left['post'] - left['pre'] == right['post'] - right['pre']
    assert (left['pre'], left['post']) != (right['pre'], right['post'])


@pytest.mark.parametrize('reverse', [False, True])
def test_identical_duplicate_receipts_are_idempotent(position_builder, reverse):
    b = position_builder
    b.cp['evidence'] += deepcopy(b.cp['evidence'])
    if reverse:
        b.cp['evidence'].reverse()
    b.persist()
    six_hours(b)


def test_125_case_three_source_placement_matrix():
    results = []
    for native_slot, native_page_slot, token_page_slot in product([98, 99, 101, 103, 104], repeat=3):
        b = pb.PositionEvidenceTests(methodName='runTest')
        b.setUp()
        try:
            lower, upper = min(native_slot, native_page_slot, token_page_slot), max(native_slot, native_page_slot, token_page_slot)
            outside = upper < 100 or lower > 102
            timestamp = pb.START + (600 if upper < 100 else 8 * 3600 if lower > 102 else 3 * 3600)
            failed_middle(b, timestamp=timestamp)
            conserve_failed_endpoints(b, 'synthetic-review-failed')
            raw_only(b, 'synthetic-review-failed', slot=native_slot)
            page_only(b, pb.WALLET, 'synthetic-review-failed', native_page_slot)
            page_only(b, pb.ACCOUNT, 'synthetic-review-failed', token_page_slot)
            result = b.derive()
            # Completely consistent slot 101 is a valid intervening failed tx.
            expected_known = outside or native_slot == native_page_slot == token_page_slot == 101
            actual_known = result['counts']['known_closed'] == 1
            results.append({'raw_slot': native_slot, 'wallet_page_slot': native_page_slot,
                'token_page_slot': token_page_slot, 'expected_known': expected_known, 'actual_known': actual_known})
            assert actual_known == expected_known, results[-1]
            if actual_known:
                assert result['positions'][0]['hold_hours']['value'] == '6'
        finally:
            b.doCleanups()
    output = os.environ.get('REVIEW_OUTPUT')
    if output:
        Path(output).mkdir(parents=True, exist_ok=True)
        (Path(output) / 'placement-matrix.json').write_text(json.dumps(results, indent=2))


def test_native_wallet_page_not_required_for_separately_proven_named_account_hold(position_builder):
    b = position_builder
    b.remove_archive(b.pages[pb.WALLET][0])
    # The token account's own chain, exact quantities and raw ownership remain.
    # Missing native-address coverage must not become a blanket timing veto.
    six_hours(b)
