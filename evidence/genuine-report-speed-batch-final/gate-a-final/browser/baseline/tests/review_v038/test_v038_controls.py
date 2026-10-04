"""Independent positive, existing-guard, availability and isolation controls."""
from copy import deepcopy
import pytest
from tests.review_v038.review_helpers_v038 import builder, pb, add_version_source, history, summarize, rebuild

@pytest.mark.parametrize('boundary',['opening','closing'])
@pytest.mark.parametrize('version',[0,'legacy'])
def test_supported_same_version_alternative_keeps_hold(builder,boundary,version):
    for raw in builder.raws: raw['version']=version
    builder.seed()
    digest=add_version_source(builder,boundary,version)
    result=summarize(builder.derive(),history(builder),digest)
    assert result['archive_receipt']['state']=='PASS'
    assert result['known_closed']==1 and result['hold']['value']=='6'
    assert result['native_observed']['wallet_network_fees_sol']['value']=='0.000015'

@pytest.mark.parametrize('boundary',['opening','closing'])
@pytest.mark.parametrize('version',[0,'legacy'])
def test_supported_version_actual_api(builder,boundary,version,tmp_path,monkeypatch):
    for raw in builder.raws: raw['version']=version
    builder.seed()
    digest=add_version_source(builder,boundary,version)
    result=rebuild(builder,tmp_path,monkeypatch,digest,f'control_{boundary}_{version}')
    assert result['known_closed']==1 and result['hold']['value']=='6'

@pytest.mark.parametrize('boundary',['opening','closing'])
@pytest.mark.parametrize('version',[1,True,None],ids=['unsupported-v1','boolean','null'])
def test_existing_selected_version_guard_rejects_same_invalid_version(builder,boundary,version):
    index=0 if boundary=='opening' else 2
    builder.raws[index]['version']=version
    builder.seed()
    result=builder.derive(); h=history(builder)
    assert result['counts']['known_closed']==0
    assert h['native_address_metrics']['observed']['wallet_network_fees_sol']['status']=='unknown'

@pytest.mark.parametrize('boundary',['opening','closing'])
@pytest.mark.parametrize('mutation',['logs','balance-array-order'])
def test_nonsemantic_alternative_changes_retain_account_hold(builder,boundary,mutation):
    idx=0 if boundary=='opening' else 2
    def change(raw):
        if mutation=='logs':raw['meta']['logMessages']=['Synthetic optional note, not onchain']
        else:
            raw['meta']['preTokenBalances'].reverse()
            raw['meta']['postTokenBalances'].reverse()
    digest=builder.link_raw_alternative(idx,change)
    result=summarize(builder.derive(),history(builder),digest)
    assert result['archive_receipt']['state']=='PASS'
    assert result['known_closed']==1 and result['hold']['value']=='6'

@pytest.mark.parametrize('boundary',['opening','closing'])
@pytest.mark.parametrize('damage',['missing','corrupt'])
def test_unreadable_version_alternative_already_revokes_hold(builder,boundary,damage):
    digest=add_version_source(builder,boundary,1)
    path=builder.store.path/'evidence'/f'{digest}.json.gz'
    if damage=='missing':path.unlink()
    else:path.write_bytes(b'independent synthetic corrupt archive')
    result=summarize(builder.derive(),history(builder),digest)
    assert result['known_closed']==0 and result['hold']['value'] is None
    assert result['archive_receipt']['state']=='UNKNOWN'

@pytest.mark.parametrize('boundary',['opening','closing'])
def test_missing_fee_does_not_erase_supported_token_timing(builder,boundary):
    idx=0 if boundary=='opening' else 2
    digest=builder.link_raw_alternative(idx,lambda raw:raw['meta'].pop('fee'))
    result=summarize(builder.derive(),history(builder),digest)
    assert result['known_closed']==1 and result['hold']['value']=='6'
    assert result['native_observed']['wallet_network_fees_sol']['status']=='unknown'

@pytest.mark.parametrize('boundary',['opening','closing'])
def test_duplicate_supported_links_do_not_create_transactions(builder,boundary):
    digest=add_version_source(builder,boundary,0)
    ref=next(r for r in builder.cp['evidence'] if r['hash']==digest)
    builder.cp['evidence'] += [deepcopy(ref) for _ in range(100)]
    builder.persist()
    result=summarize(builder.derive(),history(builder),digest)
    assert result['known_closed']==1 and result['hold']['value']=='6'
    assert result['source_set']['complete'] is True
    assert result['native_observed']['wallet_network_fees_sol']['value']=='0.000015'

@pytest.mark.parametrize('boundary',['opening','closing'])
@pytest.mark.parametrize('state',['null','wrong-method','missing-err'])
def test_invalid_linked_signature_pages_retain_r12_uncertainty(builder,boundary,state):
    index=0 if boundary=='opening' else 2
    page={'method':'getSignaturesForAddress','address':pb.WSOL_ACCOUNT,
        'params':{'limit':100,'commitment':'finalized','minContextSlot':1000},
        'result':[pb.entry(builder.records[index]['signature'],builder.raws[index])]}
    if state=='null':page=None
    elif state=='wrong-method':page['method']='unsupportedSyntheticMethod'
    else:page['result'][0].pop('err')
    digest=builder.store.archive(page)
    builder.cp['evidence'].append({'hash':digest,'kind':'signature-page'});builder.persist()
    result=summarize(builder.derive(),history(builder),digest)
    assert result['known_closed']==0 and result['hold']['value'] is None
    assert result['version_source_cited'] is True
    assert result['native_observed']['wallet_network_fees_sol']['value']=='0.000015'

@pytest.mark.parametrize('slot',[99,103],ids=['before','after'])
@pytest.mark.parametrize('version',[1,None],ids=['unsupported-v1','null'])
def test_disjoint_unsupported_transaction_does_not_erase_supported_episode(builder,slot,version):
    when=pb.START+1800 if slot==99 else pb.START+8*3600
    raw=pb.raw_exchange('synthetic-disjoint-version',slot,when,60,60)
    raw['version']=version
    if slot==99:builder.raws.insert(0,raw)
    else:builder.raws.append(raw)
    builder.seed()
    result=builder.derive()
    assert result['counts']['known_closed']==1
    row=next(row for row in result['positions'] if row['hold_hours']['status']=='known')
    assert row['hold_hours']['value']=='6'
