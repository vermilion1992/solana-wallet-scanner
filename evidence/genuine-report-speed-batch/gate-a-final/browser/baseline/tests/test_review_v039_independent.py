"""R14 representation dependencies beyond one ownership-operation spelling.

Synthetic archive/API controls only; no mainnet, profit or completeness claim.
"""
from copy import deepcopy
import json

import pytest

from scanner.decoder import SYSTEM_ID, ASSOCIATED_ID, COMPUTE_ID, MEMO_IDS
from tests.review_v039.review_helpers import builder, history, pb, rebuild, SOURCE_MODES, LOCATIONS
from tests.review_v039.review_helpers import ownership_pair


def add(case, mode, location, instruction):
    def change(raw):
        instructions = (raw['transaction']['message']['instructions'] if location == 'outer'
                        else raw['meta']['innerInstructions'][0]['instructions'])
        instructions.append(deepcopy(instruction))
    operation = case.link_raw_alternative if mode == 'alternative' else case.rearchive_raw_without_changing_pages
    return operation(1, change)


def verify(case, digest, held):
    p = case.derive()
    row = next(row for row in p['positions'] if row['account'] == pb.ACCOUNT)
    assert p['counts']['known_closed'] == int(held)
    assert row['hold_hours']['value'] == ('6' if held else None) and digest in row['sources']
    h = history(case)
    assert h['native_address_metrics']['observed']['wallet_network_fees_sol']['value'] == '0.000015'
    assert set(h['evidence_gates'].values()) == {'UNKNOWN'}
    # Transaction quantity/native facts remain independently supported. The
    # executed-operation dependency is in scoped position reconstruction.
    group = h['source_consistency']['transactions'][case.records[1]['signature']]
    assert group['accounts'][pb.ACCOUNT]['checks']['pre_quantity']['state'] == 'PASS'
    assert group['accounts'][pb.ACCOUNT]['checks']['post_quantity']['state'] == 'PASS'
    return row


@pytest.mark.parametrize('mode', SOURCE_MODES)
@pytest.mark.parametrize('location', LOCATIONS)
@pytest.mark.parametrize('kind,program', [('approve', pb.TOKEN_PROGRAM), ('closeAccount', pb.TOKEN_PROGRAM),
                                         ('transferChecked', pb.TOKEN_PROGRAM), ('transfer', SYSTEM_ID),
                                         ('createIdempotent', ASSOCIATED_ID)])
def test_mixed_shape_cannot_choose_opaque_account_list_for_any_parsed_operation(builder, mode, location, kind, program):
    instruction = {'programId': program, 'accounts': [],
                   'parsed': {'type': kind, 'info': {'account': pb.ACCOUNT, 'source': pb.ACCOUNT,
                               'wallet': pb.WALLET, 'mint': pb.MINT, 'destination': pb.POOL_TOKEN}}}
    digest = add(builder, mode, location, instruction)
    row = verify(builder, digest, False)
    paths = {path for item in row['source_paths'] if item['hash'] == digest for path in item['paths']}
    assert any(path.endswith('.accounts') for path in paths)
    assert any(path.endswith('.parsed.info') for path in paths)
    assert 'Mixed parsed and opaque' in row['stages']['source_consistency']['reason']


@pytest.mark.parametrize('mode', SOURCE_MODES)
@pytest.mark.parametrize('location', LOCATIONS)
def test_matching_mixed_shape_needs_a_reviewed_contract_too(builder, mode, location):
    digest = add(builder, mode, location, {'programId': pb.TOKEN_PROGRAM, 'accounts': [pb.ACCOUNT],
                 'parsed': {'type': 'approve', 'info': {'account': pb.ACCOUNT, 'owner': pb.WALLET}}})
    verify(builder, digest, False)


@pytest.mark.parametrize('mode', SOURCE_MODES)
@pytest.mark.parametrize('location', LOCATIONS)
@pytest.mark.parametrize('accounts', [[], [pb.POOL_TOKEN], [3]], ids=['empty', 'addresses', 'indices'])
def test_opaque_disjoint_account_lists_remain_valid_witnesses(builder, mode, location, accounts):
    digest = add(builder, mode, location, {'programId': pb.address(45), 'accounts': accounts, 'data': '1'})
    row = verify(builder, digest, True)
    assert any(item['hash'] == digest and any('.accounts' in path for path in item['paths']) for item in row['source_paths'])


@pytest.mark.parametrize('mode', SOURCE_MODES)
@pytest.mark.parametrize('location', LOCATIONS)
def test_disjoint_list_cannot_override_conflicting_program_identity(builder, mode, location):
    digest = add(builder, mode, location, {'programId': pb.address(45), 'programIdIndex': 3,
                                         'accounts': [], 'data': '1'})
    row = verify(builder, digest, False)
    paths = {path for item in row['source_paths'] if item['hash'] == digest for path in item['paths']}
    assert any(path.endswith('.programId') for path in paths) and any(path.endswith('.programIdIndex') for path in paths)


@pytest.mark.parametrize('mode', SOURCE_MODES)
@pytest.mark.parametrize('location', LOCATIONS)
def test_non_quantity_program_label_cannot_bypass_identity_reconciliation(builder, mode, location):
    digest = add(builder, mode, location, {'programId': COMPUTE_ID, 'programIdIndex': 3, 'accounts': [], 'data': '1'})
    verify(builder, digest, False)


@pytest.mark.parametrize('location', LOCATIONS)
@pytest.mark.parametrize('kind', ['approve', 'revoke'])
def test_supported_parsed_permission_operations_keep_independent_timing(builder, location, kind):
    info = {'source': pb.ACCOUNT, 'owner': pb.WALLET}
    if kind == 'approve':
        info.update(delegate=pb.POOL, amount='25')
    digest = add(builder, 'alternative', location, {'programId': pb.TOKEN_PROGRAM,
                 'parsed': {'type': kind, 'info': info}})
    verify(builder, digest, True)


@pytest.mark.parametrize('location', LOCATIONS)
@pytest.mark.parametrize('instruction', [{'programId': COMPUTE_ID, 'accounts': [], 'data': '1'},
                                        {'programId': sorted(MEMO_IDS)[0], 'parsed': 'Synthetic memo text'}],
                         ids=['opaque-compute', 'parsed-memo'])
def test_supported_metadata_shapes_do_not_become_account_operations(builder, location, instruction):
    digest = add(builder, 'alternative', location, instruction)
    verify(builder, digest, True)


@pytest.mark.parametrize('mode', SOURCE_MODES)
@pytest.mark.parametrize('location', LOCATIONS)
def test_actual_frozen_children_keep_program_rejection_hash_and_paths(builder, mode, location, tmp_path, monkeypatch):
    digest = add(builder, mode, location, {'programId': COMPUTE_ID, 'programIdIndex': 3, 'accounts': [], 'data': '1'})
    evidence = tmp_path / 'results'
    monkeypatch.setenv('REVIEW_OUTPUT', str(evidence))
    label = f'R14_program_{mode}_{location}'
    result = rebuild(builder, tmp_path, monkeypatch, digest, label)
    assert result['known_closed'] == 0 and result['hold']['value'] is None
    assert result['native_observed']['wallet_network_fees_sol']['value'] == '0.000015'
    child = json.loads((evidence / (label + '_child.json')).read_text())
    row = next(row for row in child['coverage']['position_evidence']['positions'] if row['account'] == pb.ACCOUNT)
    paths = {path for item in row['source_paths'] if item['hash'] == digest for path in item['paths']}
    assert any(path.endswith('.programId') for path in paths) and any(path.endswith('.programIdIndex') for path in paths)


@pytest.mark.parametrize('location', LOCATIONS)
def test_matching_program_identity_representations_are_reconciled(builder, location):
    def change(raw):
        keys = raw['transaction']['message']['accountKeys']
        keys.append(pb.TOKEN_PROGRAM)
        raw['meta']['preBalances'].append(0)
        raw['meta']['postBalances'].append(0)
        instruction = {'programId': pb.TOKEN_PROGRAM, 'programIdIndex': len(keys) - 1,
                       'parsed': {'type': 'approve', 'info': {'source': pb.ACCOUNT, 'owner': pb.WALLET, 'delegate': pb.POOL, 'amount': '25'}}}
        instructions = (raw['transaction']['message']['instructions'] if location == 'outer'
                        else raw['meta']['innerInstructions'][0]['instructions'])
        instructions.append(instruction)
    digest = builder.link_raw_alternative(1, change)
    verify(builder, digest, True)


@pytest.mark.parametrize('location', LOCATIONS)
def test_hybrid_opaque_reference_list_is_not_an_admitted_shape(builder, location):
    digest = add(builder, 'alternative', location, {'programId': pb.address(45), 'accounts': [3, pb.POOL_TOKEN], 'data': '1'})
    verify(builder, digest, False)


@pytest.mark.parametrize('location', LOCATIONS)
def test_failed_atomic_mixed_instructions_do_not_manufacture_executed_owner_changes(builder, location):
    raw = builder.raws[1]
    raw['meta']['err'] = {'InstructionError': [0, 'InvalidArgument']}
    raw['meta']['postTokenBalances'] = deepcopy(raw['meta']['preTokenBalances'])
    raw['meta']['postBalances'] = deepcopy(raw['meta']['preBalances'])
    raw['meta']['postBalances'][0] -= raw['meta']['fee']
    ownership_pair(raw, location, 'empty')
    builder.raws[2] = pb.raw_exchange('synthetic-final-sale', 102, pb.START + 7*3600, 100, 0)
    builder.seed()
    verify(builder, builder.records[1]['evidence_hash'], True)


@pytest.mark.parametrize('mode', SOURCE_MODES)
@pytest.mark.parametrize('location', LOCATIONS)
@pytest.mark.parametrize('state', ['missing', 'null', 'array'])
def test_incomplete_parsed_account_target_cannot_prove_disjointness(builder, mode, location, state):
    info = {'authority': pb.WALLET, 'authorityType': 'accountOwner', 'newAuthority': pb.POOL}
    if state != 'missing':
        info['account'] = None if state == 'null' else [pb.ACCOUNT]
    digest = add(builder, mode, location, {'programId': pb.TOKEN_PROGRAM,
                                         'parsed': {'type': 'setAuthority', 'info': info}})
    row = verify(builder, digest, False)
    paths = {path for item in row['source_paths'] if item['hash'] == digest for path in item['paths']}
    assert any(path.endswith('.parsed.info.account') for path in paths)
