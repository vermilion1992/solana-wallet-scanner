"""All declared target contracts against pinned primary examples, plus parity."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from scanner.instruction_scope import inspect_instruction, InstructionEvidenceError
from scanner.decoder import TOKEN_IDS
from tests.review_v0310.review_helpers import builder, pb, rebuild
from tests.review_v0310.schema_helpers import add

DATA=json.loads((Path(__file__).parent/'fixtures/instruction_family_schema.json').read_text())
EXAMPLES=DATA['examples']
FIELDS=[(e,f) for e in EXAMPLES for f in e['required_scope_fields']]

def instruction(example):
    return deepcopy(example['instruction'])

@pytest.mark.parametrize('example',EXAMPLES,ids=lambda e:e['id'])
def test_every_primary_schema_contract_has_the_required_reference_paths(example):
    ins=instruction(example);view=inspect_instruction(ins,[],path='ix')
    for field in example['required_scope_fields']:
        assert ins['parsed']['info'][field] in view['references']
        assert 'ix.parsed.info.'+field in view['paths']

@pytest.mark.parametrize('example,field',FIELDS,ids=[e['id']+'-'+f for e,f in FIELDS])
def test_each_required_scope_field_is_a_dependency(example,field):
    ins=instruction(example);ins['parsed']['info'].pop(field)
    with pytest.raises(InstructionEvidenceError) as error:
        inspect_instruction(ins,[],path='ix')
    assert 'ix.parsed.info.'+field in error.value.paths or 'ix.parsed.info' in error.value.paths or 'ix.parsed' in error.value.paths

@pytest.mark.parametrize('example',[e for e in EXAMPLES if e['family']=='token'],ids=lambda e:e['id'])
def test_standard_token_2022_targets_use_the_same_declared_schema(example):
    ins=instruction(example);ins['programId']=next(p for p in TOKEN_IDS if p!=ins['programId'])
    view=inspect_instruction(ins,[],path='ix')
    assert all(ins['parsed']['info'][f] in view['references'] for f in example['required_scope_fields'])

@pytest.mark.parametrize('example',EXAMPLES,ids=lambda e:e['id'])
def test_canonical_disjoint_operations_preserve_named_account_timing(builder,example):
    digest=add(builder,'alternative','inner',instruction(example));p=builder.derive()
    assert p['counts']['known_closed']==1
    row=next(r for r in p['positions'] if r['account']==pb.ACCOUNT)
    assert row['hold_hours']['value']=='6' and digest in row['sources']

@pytest.mark.parametrize('mode',['selected','alternative'])
@pytest.mark.parametrize('location',['outer','inner'])
def test_canonical_nonce_withdrawal_through_frozen_api(builder,mode,location,tmp_path,monkeypatch):
    e=next(e for e in EXAMPLES if e['kind']=='withdrawFromNonce')
    digest=add(builder,mode,location,instruction(e))
    r=rebuild(builder,tmp_path,monkeypatch,digest,'canonical-nonce-'+mode+'-'+location)
    assert r['known_closed']==1 and r['hold']['value']=='6'

@pytest.mark.parametrize('example',EXAMPLES,ids=lambda e:e['id'])
def test_mixed_representations_cannot_bypass_any_declared_target_contract(example):
    ins=instruction(example);ins['accounts']=[]
    with pytest.raises(InstructionEvidenceError,match='Mixed parsed'):
        inspect_instruction(ins,[],path='ix')

def test_declared_contract_population_matches_reviewed_examples():
    # Only compares population, never generates expected fields from production.
    from scanner.instruction_scope import _TOKEN_REFERENCES,_SYSTEM_REFERENCES,_ASSOCIATED_REFERENCES,_AUTHORITY_TARGETS
    assert {e['kind'] for e in EXAMPLES if e['family']=='token'}==set(_TOKEN_REFERENCES)|{'setAuthority'}
    assert {e['kind'] for e in EXAMPLES if e['family']=='system'}==set(_SYSTEM_REFERENCES)
    assert {e['kind'] for e in EXAMPLES if e['family']=='associated'}==set(_ASSOCIATED_REFERENCES)
    assert {e['instruction']['parsed']['info']['authorityType'] for e in EXAMPLES if e['kind']=='setAuthority'}==set(_AUTHORITY_TARGETS)

@pytest.mark.parametrize('program,kind',[
 ('11111111111111111111111111111111','withdrawNonce'),
 ('11111111111111111111111111111111','upgradeNonce'),
 ('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL','recoverNested'),
 ('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA','initializeMultisig'),
])
def test_unclaimed_operations_and_the_old_noncanonical_spelling_stay_unknown(program,kind):
    with pytest.raises(InstructionEvidenceError):
        inspect_instruction({'programId':program,'parsed':{'type':kind,'info':{'nonceAccount':pb.POOL,'destination':pb.POOL_TOKEN,'account':pb.POOL_TOKEN}}},[],path='ix')
