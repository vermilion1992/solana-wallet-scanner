"""Pinned primary-schema examples, independent of application contract tables.

All fixtures are unsigned synthetic evidence. The pinned Rust parser establishes
field conventions, not chain provenance or full token-extension semantics.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scanner.instruction_scope import inspect_instruction, InstructionEvidenceError
from tests.review_v0310.review_helpers import builder, pb, history, rebuild
from tests.review_v0310.schema_helpers import add

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/token_instruction_schema.json').read_text())
EXAMPLES = FIXTURE['examples']
PERMISSIONS = EXAMPLES[:3]
AUTHORITIES = EXAMPLES[3:]


@pytest.mark.parametrize('example', EXAMPLES, ids=lambda e: e['id'])
def test_primary_parser_target_fields(example):
    instruction = example['instruction']
    view = inspect_instruction(instruction, [], path='instruction')
    target = example['target_field']
    assert instruction['parsed']['info'][target] in view['references']
    assert 'instruction.parsed.info.' + target in view['paths']
    if instruction['parsed']['type'] == 'setAuthority':
        assert 'instruction.parsed.info.authorityType' in view['paths']


@pytest.mark.parametrize('example', EXAMPLES + PERMISSIONS, ids=[e['id'] for e in EXAMPLES] + [e['id']+'-disjoint' for e in PERMISSIONS])
def test_primary_schema_examples_through_actual_report_api(builder, example, tmp_path, monkeypatch, request):
    instruction = deepcopy(example['instruction'])
    disjoint = request.node.callspec.id.endswith('-disjoint')
    if disjoint:
        instruction['parsed']['info']['source'] = pb.POOL_TOKEN
    digest = add(builder, 'alternative', 'inner', instruction)
    result = rebuild(builder, tmp_path, monkeypatch, digest, 'schema-' + request.node.callspec.id)
    held = example['expect_hold']
    assert result['known_closed'] == int(held)
    assert result['hold']['value'] == ('6' if held else None)
    assert result['native_observed']['wallet_network_fees_sol']['value'] == '0.000015'
    row = next(r for r in builder.derive()['positions'] if r['account'] == pb.ACCOUNT)
    paths = {p for r in row['source_paths'] if r['hash'] == digest for p in r['paths']}
    assert any(p.endswith('.parsed.info.' + example['target_field']) for p in paths)


@pytest.mark.parametrize('authority', ['absent', None, [], 'unreviewed', 'transferFeeConfig', 1])
def test_authority_type_must_have_an_explicit_supported_mapping(builder, authority):
    instruction = deepcopy(AUTHORITIES[0]['instruction'])
    info = instruction['parsed']['info']
    if authority == 'absent':
        info.pop('authorityType')
    else:
        info['authorityType'] = authority
    digest = add(builder, 'alternative', 'outer', instruction)
    position = builder.derive()
    assert position['counts']['known_closed'] == 0
    row = position['positions'][0]
    assert digest in row['sources']
    assert any(p.endswith('.parsed.info.authorityType') for r in row['source_paths'] if r['hash'] == digest for p in r['paths'])
    assert history(builder)['native_address_metrics']['observed']['wallet_network_fees_sol']['value'] == '0.000015'


@pytest.mark.parametrize('example', AUTHORITIES, ids=lambda e: e['id'])
@pytest.mark.parametrize('state', ['absent', 'null', 'array', 'empty', 'wrong-field', 'both-fields'])
def test_authority_branch_needs_the_correct_unambiguous_target(example, state):
    instruction = deepcopy(example['instruction'])
    info = instruction['parsed']['info']
    target = example['target_field']
    other = 'account' if target == 'mint' else 'mint'
    if state == 'absent':
        info.pop(target)
    elif state == 'wrong-field':
        info[other] = info.pop(target)
    elif state == 'both-fields':
        info[other] = info[target]
    else:
        info[target] = {'null': None, 'array': [pb.ACCOUNT], 'empty': ''}[state]
    with pytest.raises(InstructionEvidenceError) as error:
        inspect_instruction(instruction, [], path='instruction')
    assert 'instruction.parsed.info.' + target in error.value.paths


@pytest.mark.parametrize('example', PERMISSIONS, ids=lambda e: e['id'])
@pytest.mark.parametrize('state', ['alias-only', 'same-alias', 'different-alias'])
def test_account_is_not_an_alternative_permission_target(example, state):
    instruction = deepcopy(example['instruction'])
    info = instruction['parsed']['info']
    info['account'] = pb.POOL_TOKEN if state == 'different-alias' else info['source']
    if state == 'alias-only':
        info.pop('source')
    with pytest.raises(InstructionEvidenceError) as error:
        inspect_instruction(instruction, [], path='instruction')
    assert {'instruction.parsed.info.source', 'instruction.parsed.info.account'} <= set(error.value.paths)


@pytest.mark.parametrize('example', [PERMISSIONS[0], AUTHORITIES[0]], ids=lambda e: e['id'])
def test_removing_a_required_canonical_source_revokes_hold_and_restoring_recovers(builder, example):
    digest = add(builder, 'alternative', 'inner', example['instruction'])
    frozen = deepcopy(builder.cp['evidence'])
    path = builder.store.path / 'evidence' / f'{digest}.json.gz'
    data = path.read_bytes()
    assert builder.derive()['counts']['known_closed'] == 1
    path.unlink()
    assert builder.derive()['counts']['known_closed'] == 0
    path.write_bytes(data)
    assert builder.derive()['counts']['known_closed'] == 1
    assert builder.cp['evidence'] == frozen
