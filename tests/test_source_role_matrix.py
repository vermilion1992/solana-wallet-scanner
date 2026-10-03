"""Declared source roles, loss/recovery and deterministic source-set invariants."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import random
import pytest
from scanner.source_consistency import index_source_links, source_archive_receipts, source_index_receipt, SOURCE_HASH_LIMIT
from scanner.storage import EvidenceError
from tests.review_v0310.review_helpers import builder,pb,history

ROLES=('transaction','signature-page','block-order','snapshot-slot','owned-accounts','native-balance')


def role_payload(role):
    if role=='transaction':return pb.raw_exchange('role-tx',100,pb.START+3600,0,100)
    if role=='signature-page':return {'method':'getSignaturesForAddress','address':pb.ACCOUNT,'params':{'commitment':'finalized','minContextSlot':200,'limit':1000},'result':[{'signature':'role-tx','slot':100,'blockTime':pb.START+3600,'err':None,'confirmationStatus':'finalized'}]}
    if role=='block-order':return {'method':'getBlock','slot':100,'result':{'signatures':['role-tx'],'blockTime':pb.START+3600}}
    if role=='snapshot-slot':return {'method':'getSlot','commitment':'finalized','result':200}
    if role=='owned-accounts':return {'method':'getTokenAccountsByOwner','owner':pb.WALLET,'program':pb.TOKEN_PROGRAM,'result':{'context':{'slot':200},'value':[]}}
    if role=='native-balance':return {'method':'getBalance','address':pb.WALLET,'result':{'context':{'slot':200},'value':5000000}}
    raise AssertionError(role)


def receipt(case,role,digest):
    ref={'kind':role,'hash':digest,**({'signature':'role-tx'} if role=='transaction' else {})}
    index=index_source_links([ref],authenticated_references=[ref]);payload={};outcomes={digest:'readable'}
    try:payload[digest]=case.store.evidence(digest)
    except EvidenceError:outcomes[digest]='unavailable-or-corrupt'
    result=source_archive_receipts(index,payload,outcomes,snapshot_slot=200,wallet=pb.WALLET)
    assert source_index_receipt(index,[digest])['complete'] is True
    return result['receipts'][0]


@pytest.mark.parametrize('role',ROLES)
def test_role_positive_missing_corrupt_and_exact_restoration(builder,role):
    digest=builder.store.archive(role_payload(role));path=builder.store.path/'evidence'/f'{digest}.json.gz';data=path.read_bytes()
    assert receipt(builder,role,digest)['state']=='PASS'
    path.unlink();r=receipt(builder,role,digest);assert r['state']=='UNKNOWN' and digest in r['evidence']
    path.write_bytes(b'corrupt gzip');assert receipt(builder,role,digest)['state']=='UNKNOWN'
    # Structurally valid gzip with different canonical JSON still fails checksum.
    path.write_bytes(gzip.compress(b'{"not":"the original contents"}'));assert receipt(builder,role,digest)['state']=='UNKNOWN'
    path.write_bytes(data);assert receipt(builder,role,digest)['state']=='PASS'


@pytest.mark.parametrize('role',ROLES)
@pytest.mark.parametrize('shape',[None,[],{'method':'unsupported-role-shape'}],ids=['null','array','wrong-method'])
def test_each_role_retains_a_malformed_archive_as_unknown(builder,role,shape):
    digest=builder.store.archive(shape);r=receipt(builder,role,digest)
    assert r['state']=='UNKNOWN' and r['hash']==digest and r['read_state']=='readable'


@pytest.mark.parametrize('role',['unknown','current-mint-controls','saved-rebuild-inputs'])
def test_unknown_native_declarations_do_not_gain_trusted_roles(builder,role):
    digest=builder.store.archive(role_payload('snapshot-slot'));ref={'kind':role,'hash':digest}
    index=index_source_links([ref],authenticated_references=[ref]);r=source_archive_receipts(index,{}, {},snapshot_slot=200,wallet=pb.WALLET)
    assert not source_index_receipt(index,[])['complete']
    assert r['receipts'][0]['state']=='UNKNOWN' and r['receipts'][0]['hash']==digest


@pytest.mark.parametrize('count',[SOURCE_HASH_LIMIT-1,SOURCE_HASH_LIMIT,SOURCE_HASH_LIMIT+1])
def test_real_source_hash_budget_boundary(count):
    refs=[{'kind':'snapshot-slot','hash':f'{i:064x}'} for i in range(count)]
    index=index_source_links(refs,authenticated_references=refs)
    assert index['unique_hash_count']==count
    assert len(index['hashes_to_inspect'])==(count if count<=SOURCE_HASH_LIMIT else 0)
    assert source_index_receipt(index,index['hashes_to_inspect'])['complete']==(count<=SOURCE_HASH_LIMIT)


@pytest.mark.parametrize('axis',['quantity','clock','instruction'])
def test_two_agreeing_sources_do_not_outvote_or_lose_a_third_conflict(builder,axis):
    builder.link_raw_alternative(1,lambda raw:raw.update(synthetic_agreeing_note='same required facts'))
    def mutate(raw):
        if axis=='quantity':
            for name in ('preTokenBalances','postTokenBalances'):
                row=raw['meta'][name][0]['uiTokenAmount'];row['amount']=str(int(row['amount'])+100)
        elif axis=='clock':raw['blockTime']+=1
        else:raw['transaction']['message']['instructions'].append({'programId':pb.TOKEN_PROGRAM,'parsed':{'type':'setAuthority','info':{'account':pb.ACCOUNT,'authorityType':'accountOwner','authority':pb.WALLET,'newAuthority':pb.POOL}}})
    digest=builder.link_raw_alternative(1,mutate);frozen=deepcopy(builder.cp['evidence'])
    assert builder.derive()['counts']['known_closed']==0
    path=builder.store.path/'evidence'/f'{digest}.json.gz';data=path.read_bytes();path.unlink()
    p=builder.derive();assert p['counts']['known_closed']==0 and digest in p['positions'][0]['sources']
    path.write_bytes(data);assert builder.derive()['counts']['known_closed']==0 and builder.cp['evidence']==frozen
    assert history(builder)['native_address_metrics']['observed']['wallet_network_fees_sol']['value']=='0.000015'


@pytest.mark.parametrize('seed',[17,41,91])
def test_permutations_and_exact_repeats_preserve_semantics_and_fee_count(builder,seed):
    digest=builder.link_raw_alternative(1,lambda raw:raw.update(synthetic_note='same facts, different bytes'))
    refs=deepcopy(builder.cp['evidence']);random.Random(seed).shuffle(refs);builder.cp['evidence']=refs+[deepcopy(refs[0])];builder.persist()
    p=builder.derive();h=history(builder)
    assert p['counts']['known_closed']==1 and p['known_account_hold_median_hours']['value']=='6'
    assert h['native_address_metrics']['observed']['wallet_network_fees_sol']['value']=='0.000015'
    assert h['source_set']['complete'] is True and digest in p['positions'][0]['sources']
