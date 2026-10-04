"""Shared RPC key/header identity boundaries, with retained source-loss controls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scanner.discovery import _native_signers
from tests.test_discovery import MINT, SIGNATURE, SIGNATURE2, TOKEN_ACCOUNT, WALLET, transaction
from tests.test_discovery_integration_review import isolate_credentials_and_transport, session
from tests.test_discovery_plan_views import identity_cohort


def compiled_raw(*, loaded=False):
    raw = transaction()
    message = raw['transaction']['message']
    message['accountKeys'] = [WALLET] if loaded else [WALLET,TOKEN_ACCOUNT]
    message['header'] = {'numRequiredSignatures':1,'numReadonlySignedAccounts':0,'numReadonlyUnsignedAccounts':0}
    if loaded:
        message['addressTableLookups'] = [{'accountKey':MINT,'writableIndexes':[0],'readonlyIndexes':[]}]
        raw['meta']['loadedAddresses'] = {'writable':[TOKEN_ACCOUNT],'readonly':[]}
    return raw


@pytest.mark.parametrize('shape', ['parsed_no_header','parsed_header','compiled_header','compiled_loader','parsed_loader'])
def test_supported_primary_key_forms_keep_same_observed_signer_flow(shape):
    raw = transaction()
    if shape == 'parsed_header':
        raw['transaction']['message']['header'] = {'numRequiredSignatures':1,'numReadonlySignedAccounts':0,'numReadonlyUnsignedAccounts':0}
    elif shape in ('compiled_header','compiled_loader'):
        raw = compiled_raw(loaded=shape=='compiled_loader')
    elif shape == 'parsed_loader':
        raw['transaction']['message']['accountKeys'][1]['source'] = 'lookupTable'
        raw['meta']['loadedAddresses'] = {'writable':[TOKEN_ACCOUNT],'readonly':[]}
    original = deepcopy(raw)
    flows, reason = _native_signers(raw,SIGNATURE)
    assert reason is None and flows[WALLET] == [{'mint':MINT,'raw_delta':'10','decimals':6}]
    assert raw == original


def test_genuine_jsonparsed_header_absence_remains_supported_with_pinned_rpc_flags():
    fixture = json.loads((Path(__file__).parent/'fixtures/mainnet-pumpswap-buy-exact-quote.json').read_bytes())
    raw = fixture['raw']
    assert hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(',',':')).encode()).hexdigest() == '9ffe9059c331907e4c8d9835e4c06fd1d258782da7b96c7bb639c00ded5001d0'
    assert 'header' not in raw['transaction']['message']
    original = deepcopy(raw)
    wallet = raw['transaction']['message']['accountKeys'][0]['pubkey']
    flows,reason = _native_signers(raw,fixture['signature'])
    assert reason is None and wallet in flows
    assert raw == original


@pytest.mark.parametrize('mutation', ['required_zero','required_two','missing_readonly','readonly_signed','readonly_unsigned','writable_mismatch','signer_mismatch','missing_writable','mixed_keys','signature_count','loaded_without_lookup','loaded_count','loaded_membership','lookup_signer','lookup_order'])
def test_conflicting_or_malformed_shared_key_roles_cannot_validate_a_discovery_identity(mutation):
    raw = transaction()
    message = raw['transaction']['message']
    if mutation in ('required_zero','required_two','missing_readonly','readonly_signed','readonly_unsigned','writable_mismatch'):
        message['header'] = {'numRequiredSignatures':1,'numReadonlySignedAccounts':0,'numReadonlyUnsignedAccounts':0}
        if mutation == 'required_zero': message['header']['numRequiredSignatures']=0
        elif mutation == 'required_two': message['header']['numRequiredSignatures']=2
        elif mutation == 'missing_readonly': message['header'].pop('numReadonlyUnsignedAccounts')
        elif mutation == 'readonly_signed': message['header']['numReadonlySignedAccounts']=1
        elif mutation == 'readonly_unsigned': message['header']['numReadonlyUnsignedAccounts']=2
        else: message['accountKeys'][1]['writable']=False
    elif mutation == 'signer_mismatch': message['accountKeys'][1]['signer']=True
    elif mutation == 'missing_writable': message['accountKeys'][0].pop('writable')
    elif mutation == 'mixed_keys': message['accountKeys'][1]=TOKEN_ACCOUNT
    elif mutation == 'signature_count': raw['transaction']['signatures'].append(SIGNATURE2)
    elif mutation in ('loaded_without_lookup','loaded_count'):
        raw = compiled_raw(loaded=True);message=raw['transaction']['message']
        if mutation == 'loaded_without_lookup': message.pop('addressTableLookups')
        else: raw['meta']['loadedAddresses']['writable']=[]
    elif mutation == 'loaded_membership':
        message['accountKeys'][1]['source']='lookupTable'
        raw['meta']['loadedAddresses']={'writable':[MINT],'readonly':[]}
    elif mutation == 'lookup_signer': message['accountKeys'][0]['source']='lookupTable'
    else:
        message['accountKeys'][0]['source']='lookupTable';message['accountKeys'][0]['signer']=False
        message['accountKeys'][1]['signer']=True
    original = deepcopy(raw)
    flows,reason = _native_signers(raw,SIGNATURE)
    assert flows == {} and reason
    assert raw == original


@pytest.mark.parametrize('location', ['primary','wrong_role_alternative'])
@pytest.mark.parametrize('required', [0,2])
def test_header_conflicts_and_alternative_source_loss_remain_unknown_through_normal_plan_api(session, location, required):
    client,app,directory = session
    cohort,hashes = identity_cohort(app.state.store)
    initial = client.get('/api/state?report_view=summary').json()['discovery_cohorts'][0]['audit_plan']
    assert initial['selected_addresses'] == [WALLET]
    raw = app.state.store.evidence(hashes['native'])
    raw['transaction']['message']['header']={'numRequiredSignatures':required,'numReadonlySignedAccounts':0,'numReadonlyUnsignedAccounts':0}
    bad = app.state.store.archive(raw)
    if location == 'primary':
        cohort['candidates'][0]['validation']['transaction_evidence_hash']=bad
        cohort['candidates'][0]['evidence'].append(bad)
        cohort['evidence'].append({'kind':'transaction','signature':SIGNATURE,'hash':bad})
    else:
        cohort['evidence'].append({'kind':'pool-trades','signature':SIGNATURE,'hash':bad})
    app.state.store.put('discovery_cohorts',cohort['id'],cohort)
    before = deepcopy(cohort)
    def plan():
        full = client.get('/api/state').json()['discovery_cohorts'][0]['audit_plan']
        compact = client.get('/api/state?report_view=summary').json()['discovery_cohorts'][0]['audit_plan']
        direct = client.get('/api/discovery/'+cohort['id']).json()['audit_plan']
        assert full == compact == direct
        assert full['selected_addresses'] == [] and full['excluded'][0]['identity_state']=='UNKNOWN'
        assert client.post('/api/discovery/'+cohort['id']+'/audit',json={'addresses':[WALLET]}).status_code==422
        return full
    present = plan()
    path = directory/'evidence'/(bad+'.json.gz');frozen = path.read_bytes();path.unlink()
    missing = plan()
    assert missing['excluded'][0]['identity_state'] == present['excluded'][0]['identity_state']
    path.write_bytes(frozen)
    assert plan() == present
    assert app.state.store.get('discovery_cohorts',cohort['id']) == before
    assert app.state.store.list('scans') == [] and client.get('/api/usage').json()['used']==0
