"""Independent controls for conservative rejection and unrelated valid facts."""
from copy import deepcopy
import pytest
from tests.review_v0310.review_helpers import builder,history,pb,rebuild,record_result,ownership_pair
from tests.review_v0310.schema_helpers import MODES,LOCATIONS,permission,add,observe
from scanner.decoder import COMPUTE_ID, MEMO_IDS

@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('location',LOCATIONS)
def test_account_owner_change_still_rejects(builder,mode,location):
    ins={'programId':pb.TOKEN_PROGRAM,'parsed':{'type':'setAuthority','info':{
        'account':pb.ACCOUNT,'authorityType':'accountOwner','authority':pb.WALLET,'newAuthority':pb.POOL}}}
    digest=add(builder,mode,location,ins)
    result=observe(builder,digest,f'control_owner_{mode}_{location}')
    assert result['known_closed']==0 and result['hold']['value'] is None

@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('location',LOCATIONS)
@pytest.mark.parametrize('field',['accounts','data'])
def test_parsed_permission_with_opaque_representation_stays_unknown(builder,mode,location,field):
    ins=permission('approve');ins[field]=[] if field=='accounts' else '1'
    digest=add(builder,mode,location,ins)
    r=observe(builder,digest,f'control_mixed_{mode}_{location}_{field}')
    assert r['known_closed']==0 and r['hold']['value'] is None

@pytest.mark.parametrize('kind',['approve','approveChecked','revoke'])
@pytest.mark.parametrize('state',['absent','null','array'])
def test_permission_without_valid_source_is_not_certified(builder,kind,state):
    ins=permission(kind)
    if state=='absent':ins['parsed']['info'].pop('source')
    else:ins['parsed']['info']['source']=None if state=='null' else [pb.ACCOUNT]
    digest=add(builder,'alternative','inner',ins)
    r=observe(builder,digest,f'control_target_{kind}_{state}')
    assert r['known_closed']==0 and r['hold']['value'] is None

@pytest.mark.parametrize('location',LOCATIONS)
@pytest.mark.parametrize('shape',['compute','memo','opaque-disjoint'])
def test_supported_metadata_and_disjoint_opaque_inputs_keep_hold(builder,location,shape):
    ins=({'programId':COMPUTE_ID,'accounts':[],'data':'1'} if shape=='compute' else
         {'programId':sorted(MEMO_IDS)[0],'parsed':'Independent synthetic memo.'} if shape=='memo' else
         {'programId':pb.address(45),'accounts':[pb.POOL_TOKEN],'data':'1'})
    digest=add(builder,'alternative',location,ins)
    r=observe(builder,digest,f'control_valid_{location}_{shape}')
    assert r['known_closed']==1 and r['hold']['value']=='6'

@pytest.mark.parametrize('mode',MODES)
def test_unmodified_episode_does_not_depend_on_fee_amount(builder,mode):
    fn=builder.link_raw_alternative if mode=='alternative' else builder.rearchive_raw_without_changing_pages
    fn(1,lambda raw:raw['meta'].pop('fee'))
    p=builder.derive();assert p['counts']['known_closed']==1
    assert history(builder)['native_address_metrics']['observed']['wallet_network_fees_sol']['status']=='unknown'

@pytest.mark.parametrize('location',LOCATIONS)
def test_unchanged_token_state_on_atomic_failure_ignores_attempted_permission(builder,location):
    raw=builder.raws[1];raw['meta']['err']={'InstructionError':[0,'InvalidArgument']}
    raw['meta']['postTokenBalances']=deepcopy(raw['meta']['preTokenBalances'])
    raw['meta']['postBalances']=deepcopy(raw['meta']['preBalances']);raw['meta']['postBalances'][0]-=raw['meta']['fee']
    listing=raw['transaction']['message']['instructions'] if location=='outer' else raw['meta']['innerInstructions'][0]['instructions']
    listing.append(permission('approve'))
    builder.raws[2]=pb.raw_exchange('synthetic-final-sale',102,pb.START+7*3600,100,0);builder.seed()
    r=observe(builder,builder.records[1]['evidence_hash'],f'control_atomic_{location}')
    assert r['known_closed']==1 and r['hold']['value']=='6'

@pytest.mark.parametrize('location',LOCATIONS)
def test_missing_required_valid_alternative_revokes_and_restoration_recovers(builder,location):
    digest=add(builder,'alternative',location,{'programId':pb.address(45),'accounts':[pb.POOL_TOKEN],'data':'1'})
    assert builder.derive()['counts']['known_closed']==1
    path=builder.store.path/'evidence'/f'{digest}.json.gz';data=path.read_bytes();refs=deepcopy(builder.cp['evidence'])
    path.unlink();assert builder.derive()['counts']['known_closed']==0
    path.write_bytes(data);assert builder.derive()['counts']['known_closed']==1
    assert builder.cp['evidence']==refs

@pytest.mark.parametrize('state',['valid','conflict'])
def test_actual_rebuild_positive_and_rejection_controls(builder,state,tmp_path,monkeypatch):
    ins=({'programId':pb.address(45),'accounts':[pb.POOL_TOKEN],'data':'1'} if state=='valid' else
         {'programId':COMPUTE_ID,'programIdIndex':3,'accounts':[],'data':'1'})
    digest=add(builder,'alternative','inner',ins);label=f'control_api_{state}'
    r=rebuild(builder,tmp_path,monkeypatch,digest,label);record_result(label+'.json',r)
    assert r['known_closed']==(1 if state=='valid' else 0)
    assert r['hold']['value']==('6' if state=='valid' else None)
