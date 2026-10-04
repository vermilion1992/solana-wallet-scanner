"""Positive, unsupported-operation, removal and metric-isolation controls."""
from copy import deepcopy
import pytest
from tests.review_v039.review_helpers import (builder, history, rebuild, add_ownership_source, ownership_pair,
                            SOURCE_MODES, LOCATIONS, pb)

def assert_hold(case):
    result = case.derive()
    assert result['counts']['known_closed'] == 1
    assert result['positions'][0]['hold_hours']['value'] == '6'
    assert set(history(case)['evidence_gates'].values()) == {'UNKNOWN'}
    return result

@pytest.mark.parametrize('mode', SOURCE_MODES)
@pytest.mark.parametrize('location', LOCATIONS)
@pytest.mark.parametrize('mask', ['absent', 'matching-address', 'matching-index'])
def test_visible_owner_changes_already_revoke_hold(builder, mode, location, mask):
    digest = add_ownership_source(builder, mode, location, mask)
    p = builder.derive()
    assert p['counts']['known_closed'] == 0
    assert p['positions'][0]['hold_hours']['value'] is None
    assert digest in p['positions'][0]['sources']
    assert history(builder)['native_address_metrics']['observed']['wallet_network_fees_sol']['value'] == '0.000015'

@pytest.mark.parametrize('mode', SOURCE_MODES)
@pytest.mark.parametrize('location', LOCATIONS)
@pytest.mark.parametrize('mask', ['null', 'bool-index', 'string'])
def test_malformed_reference_shapes_already_revoke_hold(builder, mode, location, mask):
    digest = add_ownership_source(builder, mode, location, mask)
    p = builder.derive()
    assert p['counts']['known_closed'] == 0
    assert digest in p['positions'][0]['sources']

@pytest.mark.parametrize('mode', SOURCE_MODES)
@pytest.mark.parametrize('location', LOCATIONS)
def test_genuinely_disjoint_parsed_operations_preserve_hold(builder, mode, location):
    add_ownership_source(builder, mode, location, 'absent', target=pb.POOL_TOKEN)
    assert_hold(builder)

@pytest.mark.parametrize('location', LOCATIONS)
def test_genuinely_disjoint_opaque_operations_preserve_hold(builder, location):
    def change(raw):
        instruction = {'programId': pb.address(45), 'accounts': [pb.POOL_TOKEN], 'data': '1'}
        if location == 'outer':
            raw['transaction']['message']['instructions'].append(instruction)
        else:
            raw['meta']['innerInstructions'][0]['instructions'].append(instruction)
    builder.link_raw_alternative(1, change)
    assert_hold(builder)

@pytest.mark.parametrize('mode', SOURCE_MODES)
def test_missing_fees_do_not_erase_independent_timing(builder, mode):
    operation = builder.link_raw_alternative if mode == 'alternative' else builder.rearchive_raw_without_changing_pages
    operation(1, lambda raw: raw['meta'].pop('fee'))
    assert_hold(builder)
    assert history(builder)['native_address_metrics']['observed']['wallet_network_fees_sol']['status'] == 'unknown'

@pytest.mark.parametrize('location', LOCATIONS)
def test_missing_alternative_remains_required_until_restored(builder, location):
    digest = add_ownership_source(builder, 'alternative', location, 'absent', target=pb.POOL_TOKEN)
    assert_hold(builder)
    path = builder.store.path/'evidence'/f'{digest}.json.gz'
    data = path.read_bytes()
    references = deepcopy(builder.cp['evidence'])
    path.unlink()
    p = builder.derive()
    assert p['counts']['known_closed'] == 0 and digest in p['positions'][0]['sources']
    path.write_bytes(data)
    assert_hold(builder)
    assert builder.cp['evidence'] == references

@pytest.mark.parametrize('location', LOCATIONS)
def test_failed_atomic_owner_instructions_do_not_change_token_ownership(builder, location):
    raw = builder.raws[1]
    raw['meta']['err'] = {'InstructionError': [0, 'InvalidArgument']}
    raw['meta']['postTokenBalances'] = deepcopy(raw['meta']['preTokenBalances'])
    raw['meta']['postBalances'] = deepcopy(raw['meta']['preBalances'])
    raw['meta']['postBalances'][0] -= raw['meta']['fee']
    ownership_pair(raw, location, 'absent')
    builder.raws[2] = pb.raw_exchange('synthetic-final-sale', 102, pb.START+7*3600, 100, 0)
    builder.seed()
    assert_hold(builder)

@pytest.mark.parametrize('mode', SOURCE_MODES)
def test_visible_owner_changes_revoke_actual_rebuild(builder, mode, tmp_path, monkeypatch):
    digest = add_ownership_source(builder, mode, 'inner', 'absent')
    result = rebuild(builder, tmp_path, monkeypatch, digest, f'control_visible_{mode}')
    assert result['known_closed'] == 0 and result['hold']['value'] is None
    assert result['native_observed']['wallet_network_fees_sol']['value'] == '0.000015'

@pytest.mark.parametrize('mode', SOURCE_MODES)
def test_genuinely_disjoint_operations_preserve_actual_rebuild(builder, mode, tmp_path, monkeypatch):
    digest = add_ownership_source(builder, mode, 'inner', 'absent', target=pb.POOL_TOKEN)
    result = rebuild(builder, tmp_path, monkeypatch, digest, f'control_disjoint_{mode}')
    assert result['known_closed'] == 1 and result['hold']['value'] == '6'


def test_unmodified_six_hour_episode_remains_supported(builder):
    assert_hold(builder)
