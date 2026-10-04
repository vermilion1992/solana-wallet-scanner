"""Synthetic archive fixtures. No mainnet authenticity, credentials or RPC calls.
Reuses the release's fixture builder, not its assertions or evidence decisions.
"""
import pytest
from tests import test_position_evidence as pb
from tests import test_review_v032_independent as hb

@pytest.fixture
def position_builder():
    builder = pb.PositionEvidenceTests(methodName='runTest')
    builder.setUp()
    try:
        yield builder
    finally:
        builder.doCleanups()

@pytest.fixture
def history_builder():
    builder = hb.SyntheticHistory()
    try:
        yield builder
    finally:
        builder.close()

def add_block(builder, slot, signatures, *, block_time=None):
    result = {'signatures': signatures}
    if block_time is not None:
        result['blockTime'] = block_time
    digest = builder.store.archive({'method': 'getBlock', 'slot': slot, 'result': result})
    builder.cp['evidence'].append({'hash': digest, 'kind': 'block-order'})
    builder.cp['ordering'].update({signature: index for index, signature in enumerate(signatures)})
    builder.persist()
    return digest

def all_same_slot(builder, *, consistent_time):
    for raw in builder.raws:
        raw['slot'] = 100
        if consistent_time:
            raw['blockTime'] = pb.START + 3600
    builder.seed()
    return [raw['transaction']['signatures'][0] for raw in builder.raws]

def failed_middle(builder, *, timestamp):
    failed = pb.raw_exchange('synthetic-review-failed', 101, timestamp, 100, 100)
    failed['meta'].update(err={'InstructionError': [0, 'Custom']},
                          preTokenBalances=[], postTokenBalances=[])
    builder.raws = [builder.raws[0], failed,
                   pb.raw_exchange('synthetic-final-sale', 102, pb.START + 7 * 3600, 100, 0)]
    builder.seed()

def assert_unknown_hold(result):
    assert result['counts']['known_closed'] == 0, result['counts']
    assert result['known_account_hold_median_hours']['status'] == 'unknown'
    assert result['known_account_hold_median_hours']['value'] is None
    assert all(position['hold_hours']['value'] is None for position in result['positions'])
