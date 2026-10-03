"""Independent R9 placement propagation controls; all archives are synthetic.

Supplied review assertions live unchanged in tests/review_v034. These controls
exercise affected-account/episode scope, justified exclusions, missing sources,
and evidence-order invariance. No RPC, credentials or mainnet provenance claims.
"""
from copy import deepcopy

import pytest

from scanner.history_evidence import derive_history_evidence
from scanner.position_evidence import derive_position_evidence
from tests.review_v033.review_helpers import position_builder, failed_middle, assert_unknown_hold, pb
from tests.review_v034.test_v034_regressions import conflicting_slot


FAILED = 'synthetic-review-failed'


def raw_only(builder, signature, **changes):
    old = builder.cp['transactions'][signature]['evidence_hash']
    raw = builder.store.evidence(old)
    raw.update(changes)
    digest = builder.store.archive(raw)
    builder.cp['transactions'][signature]['evidence_hash'] = digest
    for record in builder.records:
        if record['signature'] == signature:
            record['evidence_hash'] = digest
    for reference in builder.cp['evidence']:
        if reference.get('kind') == 'transaction' and reference.get('signature') == signature:
            reference['hash'] = digest
    builder.persist()
    return digest


def write_account_page(builder, account, entries):
    """Keep both cursor-chain pages structurally valid after changing placement."""
    initial, terminal = builder.pages[account]
    first = builder.store.evidence(initial)
    last = builder.store.evidence(terminal)
    entries = sorted(deepcopy(entries), key=lambda row: (row['slot'], row['signature']), reverse=True)
    first['result'] = entries
    last['params']['before'] = entries[-1]['signature']
    initial_hash, terminal_hash = builder.store.archive(first), builder.store.archive(last)
    for reference in builder.cp['evidence']:
        if reference.get('kind') == 'signature-page':
            if reference['hash'] == initial:
                reference['hash'] = initial_hash
            elif reference['hash'] == terminal:
                reference['hash'] = terminal_hash
    builder.cp['accounts'][account].update(cursor=entries[-1]['signature'], terminal_evidence=terminal_hash)
    builder.pages[account] = (initial_hash, terminal_hash)
    builder.persist()


def page_only(builder, account, signature, slot):
    page = builder.store.evidence(builder.pages[account][0])
    next(row for row in page['result'] if row['signature'] == signature)['slot'] = slot
    write_account_page(builder, account, page['result'])


def selected_result(builder, records):
    return derive_position_evidence(builder.store, pb.WALLET, pb.WINDOW,
                                     checkpoint=builder.cp, collected={'transactions': records})


def observed_fees(builder, records):
    history = derive_history_evidence(builder.store, pb.WALLET, pb.WINDOW,
                                      checkpoint=builder.cp, collected={'transactions': records})
    return history['native_address_metrics']['observed']['wallet_network_fees_sol']


def exclusions(position, signature):
    return [item for item in position['dependency_exclusions'] if item['signature'] == signature]


def conserve_failed_endpoints(builder, signature):
    """An atomic failure changes only the payer's fee, never wrapped-SOL stock."""
    raw = builder.store.evidence(builder.cp['transactions'][signature]['evidence_hash'])
    meta = deepcopy(raw['meta'])
    assert meta['err'] is not None
    meta['postBalances'] = list(meta['preBalances'])
    meta['postBalances'][0] -= meta['fee']
    meta['innerInstructions'] = []
    raw_only(builder, signature, meta=meta)


@pytest.mark.parametrize('matching_account', [pb.WALLET, pb.ACCOUNT])
@pytest.mark.parametrize('native_slot', [99, 103])
@pytest.mark.parametrize('select_failed', [False, True])
def test_matching_outside_page_cannot_mask_other_account_intervening_placement(
        position_builder, matching_account, native_slot, select_failed):
    builder = position_builder
    conflicting_slot(builder, native_slot)
    conserve_failed_endpoints(builder, FAILED)
    page_only(builder, matching_account, FAILED, native_slot)
    records = builder.records if select_failed else [builder.records[0], builder.records[2]]
    result = selected_result(builder, records)
    assert_unknown_hold(result)
    assert result['positions'][0]['stages']['placement']['state'] == 'UNKNOWN'
    observed = observed_fees(builder, records)
    # The exact observed set has a matching native receipt and conserved fee
    # endpoints; placement ambiguity cannot turn that additive sum into profit.
    assert observed['status'] == 'known'
    assert observed['record_count'] == (3 if select_failed else 2)
    assert observed['value'] == ('0.000015' if select_failed else '0.00001')


@pytest.mark.parametrize('page_slot,native_slot,timestamp', [
    (99, 98, pb.START + 600),
    (103, 104, pb.START + 8 * 3600),
])
def test_conflicting_but_disjoint_same_side_placements_have_explicit_exclusion_proof(
        position_builder, page_slot, native_slot, timestamp):
    builder = position_builder
    failed_middle(builder, timestamp=timestamp)
    builder.raws[1]['slot'] = page_slot
    builder.seed()
    digest = raw_only(builder, FAILED, slot=native_slot)
    result = builder.derive()
    assert result['counts']['known_closed'] == 1
    position = result['positions'][0]
    assert position['hold_hours']['value'] == '6'
    assert position['stages']['placement']['state'] == 'PASS'
    proof = exclusions(position, FAILED)
    assert proof and proof[0]['reason'] and proof[0]['evidence']
    assert set(proof[0]['evidence']).issubset(position['sources'])
    assert digest in position['hold_hours']['evidence']
    assert position['signatures'] == ['synthetic-buy', 'synthetic-final-sale']


def test_claims_on_opposite_sides_cannot_prove_an_episode_exclusion(position_builder):
    builder = position_builder
    failed_middle(builder, timestamp=pb.START + 3 * 3600)
    builder.raws[1]['slot'] = 103
    builder.seed()
    raw_only(builder, FAILED, slot=99)
    assert_unknown_hold(builder.derive())


@pytest.mark.parametrize('native_slot', [None, False, '99', -1])
def test_unknown_native_placement_cannot_be_preferred_outside_a_valid_episode(position_builder, native_slot):
    builder = position_builder
    failed_middle(builder, timestamp=pb.START + 600)
    builder.raws[1]['slot'] = 99
    builder.seed()
    raw_only(builder, FAILED, slot=native_slot)
    assert_unknown_hold(builder.derive())


@pytest.mark.parametrize('outside_account', [pb.WALLET, pb.ACCOUNT])
def test_missing_raw_with_conflicting_account_page_placements_remains_a_dependency(position_builder, outside_account):
    builder = position_builder
    conflicting_slot(builder, 99)
    page_only(builder, outside_account, FAILED, 103)
    builder.remove_archive(builder.cp['transactions'][FAILED]['evidence_hash'])
    records = [builder.records[0], builder.records[2]]
    assert_unknown_hold(selected_result(builder, records))
    assert observed_fees(builder, records)['value'] == '0.00001'


@pytest.mark.parametrize('slot,timestamp', [(99, pb.START + 600), (103, pb.START + 8 * 3600)])
def test_missing_raw_with_consistent_outside_pages_preserves_independent_episode(position_builder, slot, timestamp):
    builder = position_builder
    failed_middle(builder, timestamp=timestamp)
    builder.raws[1]['slot'] = slot
    builder.seed()
    builder.remove_archive(builder.cp['transactions'][FAILED]['evidence_hash'])
    records = [builder.records[0], builder.records[2]]
    result = selected_result(builder, records)
    assert result['counts']['known_closed'] == 1
    assert result['positions'][0]['hold_hours']['value'] == '6'
    assert exclusions(result['positions'][0], FAILED)
    assert observed_fees(builder, records)['value'] == '0.00001'


@pytest.mark.parametrize('native_slot', [199, 203])
@pytest.mark.parametrize('reverse_references', [False, True])
def test_placement_ambiguity_revokes_only_the_intersected_episode(position_builder, native_slot, reverse_references):
    builder = position_builder
    failed = pb.raw_exchange('episode-two-failed', 201, pb.START + 12 * 3600, 100, 100)
    failed['meta'].update(err={'InstructionError': [0, 'Custom']}, preTokenBalances=[], postTokenBalances=[])
    builder.raws = [
        pb.raw_exchange('episode-one-open', 100, pb.START + 3600, 0, 100),
        pb.raw_exchange('episode-one-close', 102, pb.START + 7 * 3600, 100, 0),
        pb.raw_exchange('episode-two-open', 200, pb.START + 10 * 3600, 0, 100), failed,
        pb.raw_exchange('episode-two-close', 202, pb.START + 16 * 3600, 100, 0),
        pb.raw_exchange('episode-three-open', 300, pb.START + 20 * 3600, 0, 100),
        pb.raw_exchange('episode-three-close', 302, pb.START + 26 * 3600, 100, 0),
    ]
    builder.seed()
    raw_only(builder, 'episode-two-failed', slot=native_slot)
    if reverse_references:
        builder.cp['evidence'].reverse()
        builder.records.reverse()
        builder.cp['accounts'] = dict(reversed(list(builder.cp['accounts'].items())))
        builder.persist()
    result = builder.derive()
    assert result['counts']['known_closed'] == 2
    by_opening = {position['id'].split(':')[-1]: position for position in result['positions']}
    affected = by_opening['episode-two-open']
    assert affected['hold_hours']['value'] is None
    assert affected['stages']['placement']['state'] == 'UNKNOWN'
    for opening in ('episode-one-open', 'episode-three-open'):
        assert by_opening[opening]['hold_hours']['value'] == '6'
        assert by_opening[opening]['stages']['placement']['state'] == 'PASS'
    records = [record for record in builder.records if record['signature'] != 'episode-two-failed']
    observed = observed_fees(builder, records)
    assert observed['status'] == 'known' and observed['value'] == '0.00003'


def remap_account(value, replacement):
    if isinstance(value, str):
        return replacement if value == pb.ACCOUNT else value
    if isinstance(value, list):
        return [remap_account(item, replacement) for item in value]
    if isinstance(value, dict):
        return {key: remap_account(item, replacement) for key, item in value.items()}
    return value


@pytest.mark.parametrize('native_slot', [199, 203])
def test_another_token_accounts_conflicting_placement_does_not_revoke_unrelated_episode(position_builder, native_slot):
    builder = position_builder
    second_account = pb.address(42)
    original_raws = deepcopy(builder.raws)
    failed = pb.raw_exchange('other-account-failed', 201, pb.START + 12 * 3600, 100, 100)
    failed['meta'].update(err={'InstructionError': [0, 'Custom']}, preTokenBalances=[], postTokenBalances=[])
    other_raws = [
        pb.raw_exchange('other-account-open', 200, pb.START + 10 * 3600, 0, 100), failed,
        pb.raw_exchange('other-account-close', 202, pb.START + 16 * 3600, 100, 0),
    ]
    other_raws = [remap_account(raw, second_account) for raw in other_raws]
    builder.raws.extend(other_raws)
    builder.seed()
    write_account_page(builder, pb.ACCOUNT, [pb.entry(raw['transaction']['signatures'][0], raw) for raw in original_raws])
    initial = builder.store.evidence(builder.pages[pb.ACCOUNT][0])
    initial['address'] = second_account
    initial['result'] = sorted([pb.entry(raw['transaction']['signatures'][0], raw) for raw in other_raws],
                               key=lambda row: row['slot'], reverse=True)
    terminal = builder.store.evidence(builder.pages[pb.ACCOUNT][1])
    terminal['address'] = second_account
    terminal['params']['before'] = 'other-account-open'
    initial_hash, terminal_hash = builder.store.archive(initial), builder.store.archive(terminal)
    builder.cp['evidence'].extend([{'kind': 'signature-page', 'hash': initial_hash},
                                  {'kind': 'signature-page', 'hash': terminal_hash}])
    builder.pages[second_account] = (initial_hash, terminal_hash)
    builder.cp['accounts'][second_account] = {
        'address': second_account, 'origin': 'event-time token-balance owner',
        'ownership_evidence': builder.cp['transactions']['other-account-open']['evidence_hash'],
        'cursor': 'other-account-open', 'terminal': 'empty signature page', 'terminal_evidence': terminal_hash,
    }
    builder.cp['account_scope']['included_account_count'] = 3
    builder.persist()
    raw_only(builder, 'other-account-failed', slot=native_slot)
    result = builder.derive()
    by_account = {position['account']: position for position in result['positions']}
    assert by_account[pb.ACCOUNT]['hold_hours']['value'] == '6'
    assert by_account[pb.ACCOUNT]['stages']['placement']['state'] == 'PASS'
    assert by_account[second_account]['hold_hours']['value'] is None
    assert by_account[second_account]['stages']['placement']['state'] == 'UNKNOWN'
    assert result['counts']['known_closed'] == 1
    records = [record for record in builder.records if not record['signature'].startswith('other-account-')]
    assert observed_fees(builder, records)['value'] == '0.000015'


@pytest.mark.parametrize('native_slot', [99, 103])
def test_reconciling_raw_slot_restores_the_supported_episode(position_builder, native_slot):
    builder = position_builder
    conflicting_slot(builder, native_slot)
    assert_unknown_hold(builder.derive())
    raw_only(builder, FAILED, slot=101)
    result = builder.derive()
    assert result['counts']['known_closed'] == 1
    assert result['positions'][0]['hold_hours']['value'] == '6'
    assert result['positions'][0]['stages']['placement']['state'] == 'PASS'
    assert result['positions'][0]['signatures'] == ['synthetic-buy', FAILED, 'synthetic-final-sale']


@pytest.mark.parametrize('outside_slot,timestamp', [(99, pb.START + 600), (103, pb.START + 8 * 3600)])
@pytest.mark.parametrize('reverse_references', [False, True])
def test_removing_alternative_raw_archive_cannot_erase_intervening_placement(
        position_builder, outside_slot, timestamp, reverse_references):
    builder = position_builder
    failed_middle(builder, timestamp=timestamp)
    builder.raws[1]['slot'] = outside_slot
    builder.seed()
    alternative = builder.store.evidence(builder.cp['transactions'][FAILED]['evidence_hash'])
    alternative['slot'] = 101
    digest = builder.store.archive(alternative)
    builder.cp['evidence'].append({'kind': 'transaction', 'signature': FAILED, 'hash': digest})
    if reverse_references:
        builder.cp['evidence'].reverse()
    builder.persist()
    assert_unknown_hold(builder.derive())
    assert digest in builder.derive()['positions'][0]['hold_hours']['evidence']
    builder.remove_archive(digest)
    # An unavailable distinct linked native source cannot be discarded while
    # the preferred raw and page agree outside. This does not revoke the
    # coherent-page-only exclusion for a signature with one missing raw source.
    assert_unknown_hold(builder.derive())
