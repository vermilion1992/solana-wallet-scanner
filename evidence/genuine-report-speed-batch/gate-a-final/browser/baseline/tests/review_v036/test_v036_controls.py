"""Additional bounded controls; these do not establish mainnet provenance."""
from copy import deepcopy
from itertools import permutations
import pytest
from tests.review_v036.review_helpers import builder, pb, add_alternative, capped_alternative, rebuild_api, record
from scanner.history_evidence import derive_history_evidence, MAX_REFERENCES


def history(case):
    result = derive_history_evidence(case.store, pb.WALLET, pb.WINDOW,
        checkpoint=case.cp, collected={'transactions': case.records})
    assert set(result['evidence_gates'].values()) == {'UNKNOWN'}
    return result


def known(case):
    result = case.derive()
    assert result['counts'] == {'known_closed': 1, 'open': 0, 'unresolved': 0}
    assert result['positions'][0]['hold_hours']['value'] == '6'
    return result


@pytest.mark.parametrize('boundary', ['opening', 'closing'])
def test_last_reference_inside_actual_cap_is_checked(builder, boundary):
    ref = capped_alternative(builder, boundary, total=MAX_REFERENCES)
    result = builder.derive()
    assert result['counts']['known_closed'] == 0
    assert ref['hash'] in result['positions'][0]['sources']
    assert result['positions'][0]['stages']['source_consistency']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('boundary', ['opening', 'closing'])
def test_same_oversized_multiset_with_conflict_in_prefix_is_unknown(builder, boundary):
    ref = capped_alternative(builder, boundary, placement='prefix')
    result = builder.derive()
    assert result['counts']['known_closed'] == 0
    assert ref['hash'] in result['positions'][0]['sources']
    record(f'R11_{boundary}_prefix_control.json', {'count': len(builder.cp['evidence']), 'result': result})


@pytest.mark.parametrize('boundary', ['opening', 'closing'])
def test_native_metric_and_wallet_gates_already_fail_closed_at_cap(builder, boundary):
    capped_alternative(builder, boundary)
    evidence = history(builder)
    assert any('reference inspection cap' in item for item in evidence['limitations'])
    for metric in evidence['native_address_metrics']['observed'].values():
        assert metric['status'] == 'unknown' and metric['value'] is None
    for interval in evidence['native_address_metrics']['periods'].values():
        for metric in interval.values():
            assert metric['status'] == 'unknown' and metric['value'] is None


@pytest.mark.parametrize('total', [MAX_REFERENCES - 1, MAX_REFERENCES])
def test_repeated_identical_refs_at_supported_limit_preserve_valid_fact(builder, total):
    duplicate = next(row for row in builder.cp['evidence'] if row.get('kind') == 'transaction')
    builder.cp['evidence'].extend(deepcopy(duplicate) for _ in range(total - len(builder.cp['evidence'])))
    builder.persist()
    known(builder)
    assert history(builder)['native_address_metrics']['observed']['wallet_network_fees_sol']['value'] == '0.000015'


@pytest.mark.parametrize('index', [0, 1, 2])
def test_three_sources_are_not_a_majority_vote_under_six_permutations(builder, index):
    original_refs = deepcopy(builder.cp['evidence'])
    signature = builder.records[index]['signature']
    good, bad = deepcopy(builder.raws[index]), deepcopy(builder.raws[index])
    good['meta']['logMessages'] = []
    for field in ('preTokenBalances', 'postTokenBalances'):
        row = next(row for row in bad['meta'][field] if row['accountIndex'] == 1)
        row['uiTokenAmount']['amount'] = str(int(row['uiTokenAmount']['amount']) + 10)
    primary = next(row for row in original_refs if row.get('signature') == signature)
    sources = [primary] + [{'kind': 'transaction', 'signature': signature, 'hash': builder.store.archive(raw)} for raw in (good, bad)]
    rest = [row for row in original_refs if row != primary]
    expected = None
    for ordering in permutations(sources):
        builder.cp['evidence'] = rest + list(ordering); builder.persist()
        result = builder.derive()
        assert result['counts']['known_closed'] == 0
        assert {row['hash'] for row in sources} <= set(result['positions'][0]['sources'])
        h = history(builder)
        check = h['source_consistency']['transactions'][signature]['accounts'][pb.ACCOUNT]
        assert check['checks']['pre_quantity']['status'] == 'conflict'
        assert check['checks']['post_quantity']['status'] == 'conflict'
        assert h['native_address_metrics']['observed']['wallet_network_fees_sol']['value'] == '0.000015'
        if expected is None:
            expected = check
        else:
            assert check == expected


@pytest.mark.parametrize('index', [0, 1, 2])
def test_three_byte_distinct_agreeing_sources_preserve_scoped_hold(builder, index):
    hashes = {builder.records[index]['evidence_hash']}
    for flavor in ['logs', 'array_order']:
        raw = deepcopy(builder.raws[index])
        if flavor == 'logs':
            raw['meta']['logMessages'] = []
        else:
            raw['meta']['preTokenBalances'].reverse(); raw['meta']['postTokenBalances'].reverse()
        digest = builder.store.archive(raw); hashes.add(digest)
        builder.cp['evidence'].append({'kind': 'transaction', 'hash': digest, 'signature': builder.records[index]['signature']})
    builder.persist()
    assert len(hashes) == 3
    result = known(builder)
    assert hashes <= set(result['positions'][0]['sources'])
    assert history(builder)['native_address_metrics']['observed']['wallet_network_fees_sol']['record_count'] == 3


@pytest.mark.parametrize('boundary', ['opening', 'closing'])
def test_missing_agreeing_third_source_cannot_be_outvoted(builder, boundary):
    good = add_alternative(builder, boundary, offset=False)
    index = 0 if boundary == 'opening' else 2
    third = deepcopy(builder.raws[index]); third['meta']['logMessages'] = ['synthetic optional log']
    digest = builder.store.archive(third)
    builder.cp['evidence'].append({'kind': 'transaction', 'hash': digest, 'signature': builder.records[index]['signature']})
    builder.persist()
    known(builder)
    builder.remove_archive(good['hash'])
    result = builder.derive()
    assert result['counts']['known_closed'] == 0
    assert good['hash'] in result['positions'][0]['stages']['source_consistency']['evidence']


@pytest.mark.parametrize('change,fee,delta', [
    ('fee', 'unknown', 'known'), ('endpoint', 'known', 'unknown'), ('both', 'unknown', 'unknown'),
])
def test_native_conflicts_revoke_only_dependent_native_values(builder, change, fee, delta):
    raw = deepcopy(builder.raws[0])
    if change in ('fee', 'both'):
        raw['meta']['fee'] += 1000
        raw['meta']['postBalances'][3] -= 1000
    if change in ('endpoint', 'both'):
        raw['meta']['postBalances'][0] -= 100
        raw['meta']['postBalances'][3] += 100
    digest = builder.store.archive(raw)
    builder.cp['evidence'].append({'kind': 'transaction', 'hash': digest, 'signature': builder.records[0]['signature']})
    builder.persist()
    known(builder)
    observed = history(builder)['native_address_metrics']['observed']
    assert observed['wallet_network_fees_sol']['status'] == fee
    assert observed['native_wallet_delta_sol']['status'] == delta


@pytest.mark.parametrize('boundary', ['opening', 'closing'])
def test_prefix_conflict_api_preserves_inputs_and_unknown_hold(builder, boundary, tmp_path, monkeypatch):
    capped_alternative(builder, boundary, placement='prefix')
    child, checks = rebuild_api(builder, tmp_path, monkeypatch)
    assert child['coverage']['position_evidence']['counts']['known_closed'] == 0
    record(f'R11_{boundary}_prefix_api_control.json', {'boundary_checks': checks,
        'position_result': child['coverage']['position_evidence']})
