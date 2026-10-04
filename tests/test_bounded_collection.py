"""Mock HTTP controls for acquisition only; never genuine wallet acceptance."""
import asyncio
from copy import deepcopy
from datetime import date, timedelta
import gzip
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

MODULE = Path(__file__).resolve().parents[1] / 'tools/bounded_collection.py'
SPEC = importlib.util.spec_from_file_location('bounded_collection', MODULE)
collect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collect)
WALLET = '4drEkXDZhjun3vjZmz1g7pQGM7kxANQbDuD9jtPZwzJZ'
SIGNATURE = '2' * 88
OFFLINE_KEY = 'synthetic-collection-key'


@pytest.fixture
def confirmation():
    today = date.today()
    return {'plan': 'Free', 'cycle_start': (today - timedelta(days=1)).isoformat(),
            'cycle_end': (today + timedelta(days=29)).isoformat(), 'remaining_credits': 10000,
            'autoscaling': False, 'confirmed_by': 'user-dashboard'}


@pytest.fixture
def store(tmp_path):
    value = collect.Store(tmp_path / 'private-runtime')
    yield value
    value.close()


def plan(rows=None, *, requests=30, credits=1000):
    return {'kind': 'bounded-native-collection-plan-v1', 'budget_id': collect.APPROVED_BUDGET_ID,
            'request_cap': requests, 'credit_cap': credits, 'retries': 0,
            'purpose': 'Offline acquisition control, not real acceptance.',
            'requests': rows or [{'id': 'slot', 'method': 'getSlot', 'params': [{'commitment': 'finalized'}]}]}


def indexed(identifier='screen', *, detail='signatures', limit=1000, previous=None):
    row = {'id': identifier, 'method': 'getTransactionsForAddress', 'params': [WALLET,
        {'transactionDetails': detail, 'limit': limit, 'sortOrder': 'asc', 'commitment': 'finalized',
         'maxSupportedTransactionVersion': 1,
         'filters': {'status': 'any', 'tokenAccounts': 'all', 'blockTime': {'gte': 1000, 'lt': 2000}}}]}
    if previous: row['pagination_from'] = previous
    return row


def indexed_body(request_id=1, *, cursor=None, signature=SIGNATURE, slot=10, position=0, time=1000):
    # Independent manually spelled fields from retained Helius index-guide
    # signatures example lines239–261; not generated from the runner validator.
    return {'jsonrpc': '2.0', 'id': request_id, 'result': {'data': [
        {'signature': signature, 'slot': slot, 'transactionIndex': position,
         'err': None, 'memo': None, 'blockTime': time, 'confirmationStatus': 'finalized'}],
        'paginationToken': cursor}}


def run(value, confirmation, store, tmp_path, handler, *, output='phase', key=OFFLINE_KEY):
    return asyncio.run(collect.execute(value, confirmation, key, tmp_path / output, store,
        transport=httpx.MockTransport(handler)))


def success(request):
    body = json.loads(request.content)
    return httpx.Response(200, json={'jsonrpc': '2.0', 'id': body['id'], 'result': 99})


@pytest.mark.parametrize('field,value', [('request_cap',31),('credit_cap',1001),('retries',1),
    ('budget_id','reset-the-budget'),('request_cap',True),('credit_cap',True)])
def test_changed_authorised_profile_rejected_before_dispatch(field, value, confirmation, store, tmp_path):
    candidate = plan(); candidate[field] = value; calls = []
    with pytest.raises(ValueError): run(candidate, confirmation, store, tmp_path, lambda r: calls.append(r))
    assert calls == [] and not (tmp_path / 'phase').exists()


@pytest.mark.parametrize('method', ['sendTransaction','simulateTransaction','signTransaction','createWallet'])
def test_signing_submission_and_unreviewed_methods_are_not_admitted(method):
    candidate = plan(); candidate['requests'][0]['method'] = method
    with pytest.raises(ValueError): collect.validate_plan(candidate)


@pytest.mark.parametrize('field,value', [('plan','Developer'),('autoscaling',True),
    ('remaining_credits',999),('remaining_credits',True),('confirmed_by','inferred from endpoint')])
def test_unconfirmed_dashboard_blocks(field, value, confirmation, store, tmp_path):
    confirmation[field] = value; calls = []
    with pytest.raises(ValueError): run(plan(), confirmation, store, tmp_path, lambda r: calls.append(r))
    assert calls == []


def test_exact_plan_hash_checked_before_credential_input(tmp_path):
    p = tmp_path / 'plan.json'; p.write_text(json.dumps(plan()))
    loaded, digest = collect.load_plan(p, collect.sha(p.read_bytes()))
    assert loaded == plan() and digest == collect.sha(p.read_bytes())
    p.write_text(p.read_text() + ' ')
    with pytest.raises(ValueError, match='hash'): collect.load_plan(p, digest)


@pytest.mark.parametrize('value', ['1'*64, '2'*88])
def test_signature_accepts_decoded64bytes_including_leading_zeroes(value):
    collect.signature(value)


@pytest.mark.parametrize('value', ['1'*63, '1'*65, 'z'*88, '2'*90])
def test_signature_rejects_wrong_decoded_byte_width(value):
    with pytest.raises(ValueError): collect.signature(value)


@pytest.mark.parametrize('change', ['status','version','endpoint','api-key','duplicates','pagination-query'])
def test_invalid_sibling_parameters_rejected_before_network(change):
    first = indexed()
    if change == 'status': first['params'][1]['filters']['status'] = 'succeeded'
    elif change == 'version': first['params'][1].pop('maxSupportedTransactionVersion')
    elif change == 'endpoint': first['endpoint'] = 'https://example.invalid'
    elif change == 'api-key': first['params'][1]['api-key'] = OFFLINE_KEY
    candidate = plan([first])
    if change == 'duplicates': candidate['requests'].append(deepcopy(first))
    if change == 'pagination-query':
        second = indexed('second', previous='screen'); second['params'][1]['filters']['tokenAccounts'] = 'none'; candidate['requests'].append(second)
    with pytest.raises(ValueError): collect.validate_plan(candidate)


def test_credit_bounds_come_from_detail_and_limit_not_caller_flags():
    assert collect.credit_bound(indexed(detail='signatures', limit=1000)) == 10
    assert collect.credit_bound(indexed(detail='full', limit=100)) == 10
    assert collect.credit_bound(indexed(detail='full', limit=101)) == 20
    assert collect.credit_bound(indexed(detail='full', limit=1000)) == 100
    value = indexed(); value['credit_upper_bound'] = 1
    with pytest.raises(ValueError): collect.validate_plan(plan([value]))


def test_success_receipts_bind_original_bytes_and_independent_ledgers(confirmation, store, tmp_path):
    calls = []
    def handler(request): calls.append(request); return httpx.Response(200, json=indexed_body())
    result = run(plan([indexed()]), confirmation, store, tmp_path, handler)
    assert result['state'] == 'COLLECTED_IN_SCOPE' and result['provider_requests'] == 1
    assert result['conservative_credits'] == 10 and result['B3'] == 'BLOCKED'
    assert result['quota_after']['credits']['used'] == 10 and result['quota_after']['requests']['used'] == 1
    assert result['quota_after']['credits']['reserved'] == result['quota_after']['requests']['reserved'] == 0
    row = result['requests'][0]; raw = gzip.decompress((tmp_path/'phase'/row['response_path']).read_bytes())
    assert collect.sha(raw) == row['response_sha256'] and len(raw) == row['response_bytes']
    assert row['byte_exact_response_retained'] is True and 'api-key' not in (tmp_path/'phase'/row['request_path']).read_text()
    assert OFFLINE_KEY not in json.dumps(result)
    assert len(calls) == 1


def test_durable_request_cap_survives_new_phase_and_releases_unused_credit(confirmation, store, tmp_path):
    first = plan([{'id':'one','method':'getSlot','params':[{'commitment':'finalized'}]}], requests=1)
    run(first, confirmation, store, tmp_path, success)
    second = deepcopy(first); second['requests'][0]['id'] = 'two'; calls = []
    result = run(second, confirmation, store, tmp_path, lambda r:calls.append(r) or success(r), output='second')
    assert calls == [] and result['state'] == 'BLOCKED'
    assert result['quota_after']['requests']['used'] == 1 and result['quota_after']['credits']['used'] == 10
    assert result['quota_after']['credits']['reserved'] == 0


def test_durable_credit_cap_independent_of_request_cap(confirmation, store, tmp_path):
    first = plan(credits=10); run(first, confirmation, store, tmp_path, success)
    second = deepcopy(first); second['requests'][0]['id'] = 'next'; calls = []
    result = run(second, confirmation, store, tmp_path, lambda r:calls.append(r) or success(r), output='next')
    assert calls == [] and result['state'] == 'BLOCKED'
    assert result['quota_after']['credits']['used'] == 10 and result['quota_after']['requests']['used'] == 1


def test_budget_cannot_increase_or_change_cycle_between_phases(confirmation, store, tmp_path):
    run(plan(credits=10), confirmation, store, tmp_path, success)
    with pytest.raises(ValueError, match='binding'): run(plan(), confirmation, store, tmp_path, success, output='new')
    confirmation['cycle_start'] = (date.today() - timedelta(days=2)).isoformat()
    with pytest.raises(ValueError, match='binding'): run(plan(credits=10), confirmation, store, tmp_path, success, output='cycle')


def test_exact_phase_cannot_retry_with_different_output(confirmation, store, tmp_path):
    run(plan(), confirmation, store, tmp_path, success)
    calls = []
    with pytest.raises(ValueError, match='already claimed'):
        run(plan(), confirmation, store, tmp_path, lambda r:calls.append(r), output='retry')
    assert calls == []


def test_completed_probe_and_setup_ledger_are_preserved(confirmation, store, tmp_path):
    old = store.reserve('helius','old-probe',73,confirmation['cycle_start'],100); store.dispatch(old); store.settle(old)
    before = store.usage('helius',confirmation['cycle_start'],100)
    run(plan(), confirmation, store, tmp_path, success)
    assert store.usage('helius',confirmation['cycle_start'],100) == before


@pytest.mark.parametrize('status', [401,403,429,302,503])
def test_http_failure_charges_both_once_and_does_not_follow_or_retry(status, confirmation, store, tmp_path):
    calls = []
    def handler(request): calls.append(request); return httpx.Response(status, text='Unavailable', headers={'Location':'https://example.invalid/never'})
    result = run(plan(),confirmation,store,tmp_path,handler)
    assert len(calls) == result['provider_requests'] == 1 and result['state'] == 'STOPPED'
    assert result['quota_after']['requests']['used'] == 1 and result['quota_after']['credits']['used'] == 10


def test_transport_error_never_exposes_exception_url_or_key(confirmation, store, tmp_path):
    def handler(request): raise httpx.ConnectError('sensitive URL '+OFFLINE_KEY,request=request)
    result = run(plan(),confirmation,store,tmp_path,handler)
    assert result['state'] == 'STOPPED' and result['provider_requests'] == 1
    assert OFFLINE_KEY not in json.dumps(result) and 'sensitive URL' not in json.dumps(result)


def test_reflected_secret_response_is_omitted_and_stops(confirmation, store, tmp_path):
    original = ('credential='+OFFLINE_KEY).encode()
    result = run(plan(),confirmation,store,tmp_path,lambda r:httpx.Response(200,content=original))
    row = result['requests'][0]
    assert row['state'] == 'SECRET_BEARING_RESPONSE_OMITTED' and row['raw_response_omitted'] is True
    assert row['response_original_sha256'] == collect.sha(original) and row['byte_exact_response_retained'] is False
    assert 'response_path' not in row and result['provider_requests'] == 1
    for p in (tmp_path/'phase').iterdir(): assert OFFLINE_KEY.encode() not in p.read_bytes()


def test_reflected_secret_header_omits_body_and_stops(confirmation,store,tmp_path):
    result=run(plan(),confirmation,store,tmp_path,lambda r:httpx.Response(200,json={'jsonrpc':'2.0','id':1,'result':99},headers={'Date':OFFLINE_KEY}))
    row=result['requests'][0]
    assert row['secret_reflected_in_response_headers'] is True and row['raw_response_omitted'] is True
    assert row['response_headers']['date']=='[REDACTED]' and 'response_path' not in row
    assert OFFLINE_KEY not in json.dumps(result)


def test_key_in_plan_blocks_without_artifact_or_dispatch(confirmation,store,tmp_path):
    candidate=plan();candidate['purpose']=OFFLINE_KEY
    with pytest.raises(ValueError,match='Credential'):run(candidate,confirmation,store,tmp_path,success)
    assert not (tmp_path/'phase').exists()


def test_supported_signature_schema_does_not_require_full_transaction_fields(confirmation,store,tmp_path):
    result=run(plan([indexed()]),confirmation,store,tmp_path,lambda r:httpx.Response(200,json=indexed_body()))
    assert result['requests'][0]['assessment']['rows']==1 and result['requests'][0]['assessment']['terminal_claim'] is True
    assert result['PRODUCT_READY'] is False and result['billing_actual_credits'] is None


@pytest.mark.parametrize('mutation',['id','missingcursor','booleanposition','missingerr','outofbounds','duplicate'])
def test_malformed_200_does_not_become_success(mutation,confirmation,store,tmp_path):
    body=indexed_body()
    if mutation=='id':body['id']=True
    elif mutation=='missingcursor':body['result'].pop('paginationToken')
    elif mutation=='booleanposition':body['result']['data'][0]['transactionIndex']=True
    elif mutation=='missingerr':body['result']['data'][0].pop('err')
    elif mutation=='outofbounds':body['result']['data'][0]['blockTime']=2000
    elif mutation=='duplicate':body['result']['data']*=2
    result=run(plan([indexed()]),confirmation,store,tmp_path,lambda r:httpx.Response(200,json=body))
    assert result['state']=='STOPPED' and result['requests'][0]['state']=='UNSUPPORTED_OR_FAILED'
    assert result['quota_after']['requests']['used']==1


def test_cursor_terminal_skips_conditional_without_request_charge(confirmation,store,tmp_path):
    calls=[]
    def handler(r):calls.append(r);return httpx.Response(200,json=indexed_body())
    result=run(plan([indexed(),indexed('second',previous='screen')]),confirmation,store,tmp_path,handler)
    assert result['state']=='COLLECTED_IN_SCOPE' and len(calls)==1
    assert result['requests'][1]['state']=='NOT_RUN' and result['quota_after']['requests']['used']==1


@pytest.mark.parametrize('failure',['repeatedcursor','repeatedsignature','order'])
def test_continuation_rejects_shared_failure_paths(failure,confirmation,store,tmp_path):
    calls=[]
    def handler(r):
        calls.append(r); n=len(calls)
        if n==1:return httpx.Response(200,json=indexed_body(cursor='10:0'))
        data=indexed_body(2,cursor='11:0',signature='3'*88,slot=11,time=1001)
        if failure=='repeatedcursor':data['result']['paginationToken']='10:0'
        elif failure=='repeatedsignature':data['result']['data'][0]['signature']=SIGNATURE
        else:data['result']['data'][0]['slot']=9
        return httpx.Response(200,json=data)
    result=run(plan([indexed(),indexed('second',previous='screen')]),confirmation,store,tmp_path,handler)
    assert len(calls)==2 and result['state']=='STOPPED'
    assert result['quota_after']['requests']['used']==2 and result['quota_after']['credits']['used']==20


def test_response_byte_budget_stops_without_retry(confirmation,store,tmp_path,monkeypatch):
    monkeypatch.setattr(collect,'MAX_RESPONSE_BYTES',16)
    result=run(plan(),confirmation,store,tmp_path,lambda r:httpx.Response(200,content=b'x'*17))
    assert result['state']=='STOPPED' and result['provider_requests']==1
    assert result['quota_after']['credits']['used']==10


def test_external_cancellation_settles_both_and_keeps_incomplete_receipt(confirmation,store,tmp_path):
    def handler(r):raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):run(plan(),confirmation,store,tmp_path,handler)
    result=json.loads((tmp_path/'phase/result.json').read_bytes())
    assert result['state']=='INTERRUPTED' and result['quota_after']['requests']['used']==1
    assert result['quota_after']['credits']['used']==10 and result['quota_after']['credits']['reserved']==0


def public_row(identifier='trending', *, pool=None):
    return {'id':identifier,'method':'publicPoolTrades' if pool else 'publicTrendingPools','params':[pool] if pool else []}


def public_body(*, trades=False):
    # Independently spelled JSON:API shapes used by the existing DiscoveryProvider
    # consumer; public leads are not native ownership or financial evidence.
    return {'data':[{'id':'trade-example','type':'trade','attributes':{'tx_from_address':WALLET,'tx_hash':SIGNATURE,
        'kind':'buy','block_timestamp':'2026-10-04T00:00:00Z'}}]} if trades else \
        {'data':[{'id':'solana_'+WALLET,'type':'pool','attributes':{'address':WALLET,'name':'Development pool label'}}]}


def test_public_get_uses_fixed_host_without_credential_or_helius_charge(confirmation,store,tmp_path):
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.method=='GET' and request.url.host=='api.geckoterminal.com'
        assert request.url.path=='/api/v2/networks/solana/trending_pools' and request.url.query==b'page=1'
        assert 'api-key' not in request.url.params and 'authorization' not in request.headers and request.content==b''
        return httpx.Response(200,json=public_body())
    result=run(plan([public_row()]),confirmation,store,tmp_path,handler,key=None)
    assert result['state']=='COLLECTED_IN_SCOPE' and len(calls)==1
    assert result['conservative_credits']==0 and result['native_provider_requests']==0 and result['public_provider_requests']==1
    assert result['endpoint']==collect.PUBLIC_ENDPOINT and result['endpoints_used']==[collect.PUBLIC_ENDPOINT]
    assert result['quota_after']['credits']['used']==0 and result['quota_after']['requests']['used']==1
    assert result['quota_after']['public_requests']['used']==1 and result['requests'][0]['credit_reservation'] is None
    row=result['requests'][0]; body=gzip.decompress((tmp_path/'phase'/row['response_path']).read_bytes())
    assert collect.sha(body)==row['response_sha256'] and row['assessment']['pools']==[WALLET]


def test_public_trade_lead_is_observed_without_native_ownership_claim(confirmation,store,tmp_path):
    calls=[]
    def handler(request):
        calls.append(request);assert request.url.path=='/api/v2/networks/solana/pools/'+WALLET+'/trades'
        assert request.url.query==b'';return httpx.Response(200,json=public_body(trades=True))
    result=run(plan([public_row('trades',pool=WALLET)]),confirmation,store,tmp_path,handler,key=None)
    assert result['requests'][0]['assessment']['leads'][0]['address']==WALLET
    assert result['PRODUCT_READY'] is False and result['B3']=='BLOCKED' and len(calls)==1


@pytest.mark.parametrize('method,params',[('publicTrendingPools',['https://example.invalid']),
    ('publicPoolTrades',['../elsewhere']),('publicPoolTrades',[]),('publicTokens',[WALLET])])
def test_public_route_and_parameters_cannot_expand_allowlist(method,params):
    with pytest.raises(ValueError):collect.validate_plan(plan([{'id':'bad','method':method,'params':params}]))


def test_public_only_must_not_receive_a_private_key(confirmation,store,tmp_path):
    with pytest.raises(ValueError,match='must not load'):run(plan([public_row()]),confirmation,store,tmp_path,success)


def test_public_subset_four_cap_survives_phases_without_credit_charge(confirmation,store,tmp_path):
    value=plan([public_row('public-'+str(i)) for i in range(4)])
    run(value,confirmation,store,tmp_path,lambda r:httpx.Response(200,json=public_body()),key=None)
    calls=[]
    result=run(plan([public_row('fifth')]),confirmation,store,tmp_path,
               lambda r:calls.append(r) or httpx.Response(200,json=public_body()),output='fifth',key=None)
    assert calls==[] and result['state']=='BLOCKED'
    assert result['quota_after']['public_requests']['used']==4 and result['quota_after']['requests']['used']==4
    assert result['quota_after']['credits']['used']==0


def test_public_request_shares_native_overall_cap(confirmation,store,tmp_path):
    run(plan(requests=1),confirmation,store,tmp_path,success)
    calls=[]
    result=run(plan([public_row()],requests=1),confirmation,store,tmp_path,
        lambda r:calls.append(r),output='public',key=None)
    assert calls==[] and result['state']=='BLOCKED'
    assert result['quota_after']['requests']['used']==1 and result['quota_after']['public_requests']['reserved']==0
    assert result['quota_after']['credits']['used']==10


def test_public_phase_does_not_modify_previous_native_budget_binding(confirmation,store,tmp_path):
    run(plan(),confirmation,store,tmp_path,success)
    before=store.get('bounded_collection_budget',collect.APPROVED_BUDGET_ID)
    run(plan([public_row()]),confirmation,store,tmp_path,lambda r:httpx.Response(200,json=public_body()),output='public',key=None)
    assert store.get('bounded_collection_budget',collect.APPROVED_BUDGET_ID)==before
    assert store.get('bounded_collection_public_budget',collect.APPROVED_BUDGET_ID)['public_request_cap']==4


@pytest.mark.parametrize('status',[302,401,429,503])
def test_public_http_error_stops_once_without_key_or_retry(status,confirmation,store,tmp_path):
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(status,text='Unavailable',headers={'Location':'https://example.invalid'})
    result=run(plan([public_row()]),confirmation,store,tmp_path,handler,key=None)
    assert len(calls)==1 and result['state']=='STOPPED' and result['conservative_credits']==0
    assert result['quota_after']['public_requests']['used']==result['quota_after']['requests']['used']==1


@pytest.mark.parametrize('body',[None,{}, {'data':'bad'}, {'data':[{'attributes':{}}]}])
def test_malformed_public_200_does_not_establish_usable_leads(body,confirmation,store,tmp_path):
    result=run(plan([public_row()]),confirmation,store,tmp_path,lambda r:httpx.Response(200,json=body),key=None)
    assert result['state']=='STOPPED' and result['requests'][0]['state']=='UNSUPPORTED_OR_FAILED'


def test_disjoint_malformed_public_row_does_not_erase_supported_lead(confirmation,store,tmp_path):
    body=public_body();body['data'].append(None)
    result=run(plan([public_row()]),confirmation,store,tmp_path,lambda r:httpx.Response(200,json=body),key=None)
    receipt=result['requests'][0]['assessment']
    assert result['state']=='COLLECTED_IN_SCOPE' and receipt['usable_rows']==1 and receipt['row_gaps'][0]['row']==1


def test_public_two_megabyte_budget_stops_before_body_acceptance(confirmation,store,tmp_path,monkeypatch):
    monkeypatch.setattr(collect,'MAX_PUBLIC_RESPONSE_BYTES',16)
    result=run(plan([public_row()]),confirmation,store,tmp_path,lambda r:httpx.Response(200,content=b'x'*17),key=None)
    assert result['state']=='STOPPED' and result['provider_requests']==1 and result['conservative_credits']==0


def test_public_only_main_never_prompts_or_looks_up_credentials(confirmation,tmp_path,monkeypatch):
    import sys
    p=tmp_path/'public-plan.json';p.write_text(json.dumps(plan([public_row()])))
    c=tmp_path/'confirmation.json';c.write_text(json.dumps(confirmation))
    monkeypatch.setattr(sys,'argv',['bounded_collection.py','--plan',str(p),'--plan-sha256',collect.sha(p.read_bytes()),
        '--confirmation',str(c),'--output',str(tmp_path/'output'),'--data',str(tmp_path/'private')])
    def forbidden(*args,**kwargs):raise AssertionError('Public execution attempted credential lookup')
    monkeypatch.setattr(collect.getpass,'getpass',forbidden)
    async def no_network(plan,confirmation,key,output,store,**kwargs):
        assert key is None
        return {'state':'COLLECTED_IN_SCOPE','budget_id':plan['budget_id'],'provider_requests':0,'conservative_credits':0,'B3':'BLOCKED'}
    monkeypatch.setattr(collect,'execute',no_network)
    assert collect.main()==0


@pytest.mark.parametrize('encoding',['json','jsonParsed'])
def test_documented_indexed_json_encoding_is_explicitly_admitted(encoding):
    row=indexed(detail='full',limit=100);row['params'][1]['encoding']=encoding
    assert collect.validate_plan(plan([row]))['requests'][0]['params'][1]['encoding']==encoding


@pytest.mark.parametrize('detail,encoding',[('full','base64'),('full','base58'),('signatures','jsonParsed')])
def test_other_indexed_encoding_choices_remain_outside_this_collection_contract(detail,encoding):
    row=indexed(detail=detail,limit=100);row['params'][1]['encoding']=encoding
    with pytest.raises(ValueError):collect.validate_plan(plan([row]))
