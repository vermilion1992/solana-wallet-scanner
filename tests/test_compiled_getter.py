"""Pinned read-only getter layouts; neither synthetic controls nor a query prove B3."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from scanner.compiled_instructions import CompiledInstructionError, METHOD, normalize_instruction, normalize_transaction
from scanner.decoder import decode_transactions
from tests.test_compiled_instructions import KEYS, binary_base58

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / 'tests/fixtures/compiled_instructions/getter-schema.json').read_bytes())


@pytest.mark.parametrize('reference', SCHEMA['references'], ids=lambda r: r['extracted_path'])
def test_new_primary_token2022_sources_match_pinned_agave_package_bytes(reference):
    assert hashlib.sha256((ROOT / reference['local_path']).read_bytes()).hexdigest() == reference['sha256']
    assert reference['package_sha256'] == '821d96d034ea31c4965d182c742153c491ae0abee531331b55771086c5030d86'
    assert reference['version'] == '3.1.1'


@pytest.mark.parametrize('case', SCHEMA['examples'], ids=lambda c: c['id'])
@pytest.mark.parametrize('inner', [False, True], ids=['outer', 'inner'])
def test_primary_getter_examples_preserve_original_bytes_paths_and_readonly_roles(case, inner):
    instruction = {'programId': KEYS[case['program']], 'accounts': [KEYS['mint']], 'data': binary_base58(case['hex'])}
    original = deepcopy(instruction)
    result = normalize_instruction(instruction, list(KEYS.values()), signers=set(), inner=inner, path='retained.ix')
    assert result['instruction']['parsed'] == {'type':'getAccountDataSize', 'info':{'mint':KEYS['mint'], **case['info']}}
    assert result['normalization']['required_signer_roles'] == []
    assert result['normalization']['method'] == METHOD == 'compiled-instructions-v2'
    assert 'retained.ix.data' in result['normalization']['raw_paths']
    assert 'retained.ix.accounts' in result['normalization']['raw_paths']
    assert instruction == original


@pytest.mark.parametrize('hexadecimal', ['1500', '15070008', '15ffff', '151d00', '15fdff'])
def test_token2022_odd_truncated_unknown_and_test_only_extension_values_are_dependencies(hexadecimal):
    instruction = {'programId':KEYS['token2022'], 'accounts':[KEYS['mint']], 'data':binary_base58(hexadecimal)}
    original = deepcopy(instruction)
    with pytest.raises(CompiledInstructionError) as caught:
        normalize_instruction(instruction,list(KEYS.values()),signers=set(),inner=True,path='retained.ix')
    assert caught.value.code in ('unsupported-layout','unsupported-extension-type')
    assert caught.value.paths == ['retained.ix.data']
    assert instruction == original


@pytest.mark.parametrize('program', ['token','token2022'])
@pytest.mark.parametrize('accounts', [[], [KEYS['mint'],KEYS['source']], [KEYS['mint'],1], [True]], ids=['missing','extra','mixed','boolean'])
def test_getter_account_roles_are_exact_and_cannot_be_forged(program, accounts):
    with pytest.raises(CompiledInstructionError) as caught:
        normalize_instruction({'programId':KEYS[program],'accounts':accounts,'data':binary_base58('15')},
                              list(KEYS.values()),signers=set(),inner=True,path='retained.ix')
    assert caught.value.code in ('unsupported-account-arity','mixed-account-list')
    assert 'retained.ix.accounts' in caught.value.paths


def test_getter_program_identity_mixed_representation_and_unknown_write_opcode_stay_negative():
    instruction = {'programId':KEYS['token'],'accounts':[KEYS['mint']],'data':binary_base58('15')}
    for mutation in ({'program':'system'}, {'parsed':{'type':'getAccountDataSize','info':{'mint':KEYS['mint']}}}, {'data':binary_base58('1a')}):
        with pytest.raises(CompiledInstructionError):
            normalize_instruction({**instruction,**mutation},list(KEYS.values()),signers=set(),inner=True)


def test_readonly_getter_does_not_create_token_movements_basis_or_history_certificate():
    raw = {'version':'legacy','slot':3,'blockTime':1700000000,
           'transaction':{'signatures':['unsigned-development-control'],'message':{
               'accountKeys':[KEYS['authority'],KEYS['mint'],KEYS['token2022']],
               'header':{'numRequiredSignatures':1,'numReadonlySignedAccounts':0,'numReadonlyUnsignedAccounts':2},
               'instructions':[{'programIdIndex':2,'accounts':[1],'data':binary_base58('1507000800')}] }},
           'meta':{'err':None,'fee':5000,'preBalances':[100,0,0],'postBalances':[100,0,0],
                   'preTokenBalances':[],'postTokenBalances':[],'innerInstructions':[]}}
    original = deepcopy(raw)
    normalized = normalize_transaction(raw)
    assert normalized['issues'] == []
    assert len(normalized['normalizations']) == 1
    decoded = decode_transactions([{'signature':'unsigned-development-control','raw':raw,'evidence_hash':'a'*64}],KEYS['authority'])
    assert [event['kind'] for event in decoded['events']] == ['fee']
    assert not any(event.get('basis_sol') is not None for event in decoded['events'])
    assert decoded.get('history_complete') is not True
    assert raw == original


def test_genuine_getter_paths_normalize_without_mutating_frozen_page_bytes():
    compressed = ROOT / 'evidence/genuine-wallet-batch/collection/phase5/02-lifetime-page-1-response.raw.gz'
    raw_bytes = gzip.decompress(compressed.read_bytes())
    assert hashlib.sha256(raw_bytes).hexdigest() == '7517110b5b3825584ec24a6e48aad3c23fbcc4c475056f7708d56b87a999fe7a'
    records = json.loads(raw_bytes)['result']['data']
    for index in (83,85):
        original = deepcopy(records[index])
        normalized = normalize_transaction(records[index])
        getter = next(group for group in normalized['raw']['meta']['innerInstructions'] if group['index']==0)['instructions'][0]
        assert getter['parsed']['type'] == 'getAccountDataSize'
        assert getter['parsed']['info'] == {'mint':'So11111111111111111111111111111111111111112'}
        assert any(receipt['kind']=='getAccountDataSize' and 'meta.innerInstructions.0.instructions.0.data' in receipt['raw_paths'] for receipt in normalized['normalizations'])
        assert records[index] == original
    assert gzip.decompress(compressed.read_bytes()) == raw_bytes
