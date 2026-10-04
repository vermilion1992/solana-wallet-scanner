"""R15: canonical RPC target fields must not be rejected as missing `account`.

All failures are ordinary assertions. Synthetic schema-conformance evidence;
no live transaction collection, signing, credentials or qualification claims.
"""
import pytest
from tests.review_v0310.review_helpers import builder, rebuild, record_result, pb
from tests.review_v0310.schema_helpers import PERMISSIONS,MODES,LOCATIONS,permission,mint_authority,add,observe

@pytest.mark.parametrize('kind',PERMISSIONS)
@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('location',LOCATIONS)
@pytest.mark.parametrize('target',['scoped','disjoint'])
def test_rpc_permission_schema_preserves_supported_hold(builder,kind,mode,location,target):
    ins=permission(kind,pb.ACCOUNT if target=='scoped' else pb.POOL_TOKEN)
    digest=add(builder,mode,location,ins)
    label=f'R15_direct_{kind}_{mode}_{location}_{target}'
    result=observe(builder,digest,label)
    assert result['known_closed']==1 and result['hold']['value']=='6',result

@pytest.mark.parametrize('kind',PERMISSIONS)
@pytest.mark.parametrize('mode',MODES)
@pytest.mark.parametrize('location',LOCATIONS)
def test_rpc_permission_schema_preserves_actual_rebuild(builder,kind,mode,location,tmp_path,monkeypatch):
    digest=add(builder,mode,location,permission(kind))
    label=f'R15_api_{kind}_{mode}_{location}'
    result=rebuild(builder,tmp_path,monkeypatch,digest,label)
    assert result['native_observed']['wallet_network_fees_sol']['value']=='0.000015'
    record_result(label+'.json',result)
    assert result['known_closed']==1 and result['hold']['value']=='6',result

@pytest.mark.parametrize('kind',['mintTokens','freezeAccount'])
@pytest.mark.parametrize('location',LOCATIONS)
def test_rpc_unrelated_mint_authority_shape_preserves_hold(builder,kind,location):
    digest=add(builder,'alternative',location,mint_authority(kind))
    result=observe(builder,digest,f'R15_mint_direct_{kind}_{location}')
    assert result['known_closed']==1 and result['hold']['value']=='6',result

@pytest.mark.parametrize('kind',['mintTokens','freezeAccount'])
@pytest.mark.parametrize('mode',MODES)
def test_rpc_unrelated_mint_authority_shape_preserves_actual_rebuild(builder,kind,mode,tmp_path,monkeypatch):
    digest=add(builder,mode,'inner',mint_authority(kind))
    label=f'R15_mint_api_{kind}_{mode}'
    result=rebuild(builder,tmp_path,monkeypatch,digest,label)
    assert result['native_observed']['wallet_network_fees_sol']['value']=='0.000015'
    record_result(label+'.json',result)
    assert result['known_closed']==1 and result['hold']['value']=='6',result
