"""Independent positive/boundary controls for the v0.3.4 review.
Fixture construction is reused, but assertions and mutations are additional.
No provider traffic, credentials or mainnet claims.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib,json
from pathlib import Path
import pytest
from tests import test_position_evidence as pb
from tests.review_v033.review_helpers import position_builder,failed_middle,assert_unknown_hold,add_block,all_same_slot
from scanner.position_evidence import derive_position_evidence
from scanner.history_evidence import derive_history_evidence
from scanner.investigation import decode_supported_swaps,WSOL
from scanner.accounting import analyze


def assert_six_hours(builder):
    result=builder.derive()
    assert result['counts']=={'known_closed':1,'open':0,'unresolved':0}
    assert result['positions'][0]['hold_hours']['value']=='6'
    assert result['known_account_hold_median_hours']['value']=='6'
    return result


def test_valid_intervening_failed_receipt_is_included(position_builder):
    failed_middle(position_builder,timestamp=pb.START+3*3600)
    result=assert_six_hours(position_builder)
    assert result['positions'][0]['signatures']==['synthetic-buy','synthetic-review-failed','synthetic-final-sale']
    assert result['positions'][0]['stages']['collection']['state']=='PASS'


@pytest.mark.parametrize('selected_order',[(0,1,2),(2,1,0),(1,2,0)])
def test_valid_hold_does_not_depend_on_selected_list_order(position_builder,selected_order):
    original=deepcopy(position_builder.cp)
    records=[position_builder.records[i] for i in selected_order]
    result=derive_position_evidence(position_builder.store,pb.WALLET,pb.WINDOW,
        checkpoint=position_builder.cp,collected={'transactions':records})
    assert result['positions'][0]['hold_hours']['value']=='6'
    assert position_builder.cp==original


@pytest.mark.parametrize('slot,timestamp',[(99,pb.START+600),(103,pb.START+8*3600)])
def test_consistent_failed_record_outside_episode_does_not_poison_valid_hold(position_builder,slot,timestamp):
    failed_middle(position_builder,timestamp=timestamp)
    position_builder.raws[1]['slot']=slot
    position_builder.seed()  # raw and BOTH pages agree, unlike R9.
    result=assert_six_hours(position_builder)
    assert result['positions'][0]['signatures']==['synthetic-buy','synthetic-final-sale']
    history=derive_history_evidence(position_builder.store,pb.WALLET,pb.WINDOW,
        checkpoint=position_builder.cp,collected={'transactions':position_builder.records})
    assert history['paging']['conflicts']==[]


@pytest.mark.parametrize('signature',['synthetic-buy','synthetic-review-failed','synthetic-final-sale'])
def test_removing_any_episode_raw_receipt_revokes_known_hold(position_builder,signature):
    failed_middle(position_builder,timestamp=pb.START+3*3600)
    position_builder.remove_archive(position_builder.cp['transactions'][signature]['evidence_hash'])
    assert_unknown_hold(position_builder.derive())


@pytest.mark.parametrize('account',[pb.WALLET,pb.ACCOUNT])
def test_conflicting_page_slot_kept_inside_raw_episode_remains_unknown(position_builder,account):
    failed_middle(position_builder,timestamp=pb.START+3*3600)
    initial,terminal=position_builder.pages[account]
    page=position_builder.store.evidence(initial)
    for row in page['result']:
        if row['signature']=='synthetic-review-failed':row['slot']=100
    # Preserve valid descending slots (102,100,100); no invalid-page shortcut.
    digest=position_builder.store.archive(page)
    for ref in position_builder.cp['evidence']:
        if ref.get('kind')=='signature-page' and ref['hash']==initial:ref['hash']=digest
    position_builder.pages[account]=(digest,terminal)
    position_builder.persist()
    assert_unknown_hold(position_builder.derive())


@pytest.mark.parametrize('seconds',[0,1,21600])
def test_exact_known_hold_boundaries_without_float_conversion(position_builder,seconds):
    opening=pb.START+3600
    position_builder.raws=[pb.raw_exchange('review-open',100,opening,0,100),
                          pb.raw_exchange('review-close',101,opening+seconds,100,0)]
    position_builder.seed()
    result=position_builder.derive()
    actual=Decimal(result['positions'][0]['hold_hours']['value'])
    with __import__('decimal').localcontext() as ctx:
        ctx.prec=192
        assert actual==Decimal(seconds)/Decimal(3600)
    for stage in ['basis','fees','classification','valuation']:
        assert result['positions'][0]['stages'][stage]['state']=='UNKNOWN'


def nonce_record():
    path=Path(pb.__file__).parent/'fixtures/mainnet-pumpswap-sell-durable-nonce.json'
    return json.loads(path.read_text())


def test_archived_nonce_sale_matches_independent_integer_endpoints_and_fee():
    record=nonce_record();raw=record['raw'];original=deepcopy(raw)
    encoded=json.dumps(raw,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
    assert hashlib.sha256(encoded).hexdigest()==record['evidence_hash']=='25271562a99c96879c6d5f347792340320a6f55c12497a0ba3602db86eca6b4a'
    keys=[k['pubkey'] if isinstance(k,dict) else k for k in raw['transaction']['message']['accountKeys']]
    wallet=keys[0]
    pre={b['accountIndex']:b for b in raw['meta']['preTokenBalances'] if b['owner']==wallet}
    post={b['accountIndex']:b for b in raw['meta']['postTokenBalances'] if b['owner']==wallet}
    deltas={pre[i]['mint']:int(post[i]['uiTokenAmount']['amount'])-int(pre[i]['uiTokenAmount']['amount']) for i in pre}
    mint='HXxJdaQbrYRvwTAM8M8mUPyoRPvmyuUbPFBRkiAAMASS'
    assert deltas[mint]==-5_218_627_960 and deltas[WSOL]==11_345_060
    assert sum(raw['meta']['preBalances'])-sum(raw['meta']['postBalances'])==raw['meta']['fee']==42_000
    result=decode_supported_swaps([record],wallet)
    sale=next(e for e in result['events'] if e['kind']=='sell')
    assert sale['quantity_raw']==str(-deltas[mint])
    assert Decimal(sale['amount_sol'])==Decimal(deltas[WSOL])/10**9
    assert Decimal(sale['fee_sol'])==Decimal(42_000)/10**9
    assert raw==original
    result=analyze(result['events'],raw['blockTime']-86400,raw['blockTime']+1,history_complete=False)
    assert result['metrics']['profit_sol']['value'] is None
    assert result['positions'][0]['basis_sol'] is None


@pytest.mark.parametrize('operation',['withdrawNonce','initializeNonce','authorizeNonce','allocate','assign'])
def test_unknown_system_operation_does_not_inherit_nonce_administration_exception(operation):
    # allocate/assign stay here: this mutates the *outer* nonce instruction.
    # Inner layout-pinned allocate/assign (PumpSwap space 137 on genuine
    # Jupiter route_v2) is a separate lifecycle path; outer rewrite is not.
    record=nonce_record();raw=record['raw']
    wallet=raw['transaction']['message']['accountKeys'][0]['pubkey']
    raw['transaction']['message']['instructions'][0]['parsed']['type']=operation
    result=decode_supported_swaps([record],wallet)
    assert not any(e['kind'] in ('buy','sell') for e in result['events'])
    fee=next(e for e in result['events'] if e['kind']=='fee')
    assert fee['amount_sol']=='0.000042' and fee['allocation']=='unallocated'


def _inner_allocate_assign(account, *, space=137, owner='pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA'):
    return [
        {'parsed': {'type': 'allocate', 'info': {'account': account, 'space': space}},
         'program': 'system', 'programId': '11111111111111111111111111111111', 'stackHeight': 2},
        {'parsed': {'type': 'assign', 'info': {'account': account, 'owner': owner}},
         'program': 'system', 'programId': '11111111111111111111111111111111', 'stackHeight': 2},
    ]


def test_inner_layout_pinned_allocate_assign_does_not_block_reviewed_route():
    record=nonce_record();raw=record['raw']
    wallet=raw['transaction']['message']['accountKeys'][0]['pubkey']
    account='6XQwe38mNZbxp4UW9x9117MvDKbHoVPWbgqGRnbtaXA'
    raw['meta']['innerInstructions'][0]['instructions'].extend(_inner_allocate_assign(account))
    result=decode_supported_swaps([record],wallet)
    assert any(e['kind']=='sell' for e in result['events'])


@pytest.mark.parametrize('mutate', [
    'outer-layout-pinned',
    'inner-wallet-account',
    'inner-unreviewed-owner',
    'inner-unreviewed-space',
    'inner-nonce-fields',
])
def test_unsafe_allocate_assign_is_still_refused(mutate):
    record=nonce_record();raw=record['raw']
    wallet=raw['transaction']['message']['accountKeys'][0]['pubkey']
    account='6XQwe38mNZbxp4UW9x9117MvDKbHoVPWbgqGRnbtaXA'
    if mutate=='outer-layout-pinned':
        raw['transaction']['message']['instructions'][0]['parsed']={
            'type':'allocate','info':{'account':account,'space':137}}
    elif mutate=='inner-wallet-account':
        raw['meta']['innerInstructions'][0]['instructions'].extend(_inner_allocate_assign(wallet))
    elif mutate=='inner-unreviewed-owner':
        raw['meta']['innerInstructions'][0]['instructions'].extend(
            _inner_allocate_assign(account, owner=wallet))
    elif mutate=='inner-unreviewed-space':
        raw['meta']['innerInstructions'][0]['instructions'].extend(
            _inner_allocate_assign(account, space=80))
    else:
        raw['meta']['innerInstructions'][0]['instructions'].append({
            'parsed':{'type':'allocate','info':{
                'account':account,'space':137,
                'nonceAccount':'9oBXtqffWUPPZnqJ5YG3BVJWm8x3nvWf1txEKRhGmMBN'}},
            'program':'system','programId':'11111111111111111111111111111111','stackHeight':2})
    result=decode_supported_swaps([record],wallet)
    assert not any(e['kind'] in ('buy','sell') for e in result['events'])
    fee=next(e for e in result['events'] if e['kind']=='fee')
    assert fee['amount_sol']=='0.000042' and fee['allocation']=='unallocated'


@pytest.mark.parametrize('value',[None,False,True,0,-1,'42000'])
def test_invalid_fee_cannot_preserve_scoped_nonce_swap(value):
    record=nonce_record();raw=record['raw']
    wallet=raw['transaction']['message']['accountKeys'][0]['pubkey']
    raw['meta']['fee']=value
    result=decode_supported_swaps([record],wallet)
    assert not any(e['kind'] in ('buy','sell') for e in result['events'])
