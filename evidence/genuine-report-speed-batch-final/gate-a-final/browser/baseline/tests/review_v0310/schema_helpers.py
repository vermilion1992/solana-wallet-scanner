"""RPC-shaped, synthetic local instructions; never signed/mainnet claims.

Reference: Agave transaction-status/src/parse_token.rs, Approve,
ApproveChecked, Revoke, and authority-dependent SetAuthority JSON fields.
"""
from copy import deepcopy
from tests.review_v0310.review_helpers import pb, history, summarize, record_result
PERMISSIONS=('approve','approveChecked','revoke')
MODES=('selected','alternative')
LOCATIONS=('outer','inner')

def permission(kind,target=None):
    info={'source':pb.ACCOUNT if target is None else target,'owner':pb.WALLET}
    if kind!='revoke': info['delegate']=pb.POOL
    if kind=='approve': info['amount']='25'
    if kind=='approveChecked':
        info['mint']=pb.MINT
        info['tokenAmount']={'amount':'25','decimals':6,'uiAmount':0.000025,'uiAmountString':'0.000025'}
    return {'program':'spl-token','programId':pb.TOKEN_PROGRAM,'parsed':{'type':kind,'info':info}}

def mint_authority(kind):
    return {'program':'spl-token','programId':pb.TOKEN_PROGRAM,'parsed':{'type':'setAuthority','info':{
        'mint':pb.address(24),'authorityType':kind,'newAuthority':None,'authority':pb.WALLET}}}

def add(case,mode,location,instruction,record=1):
    def change(raw):
        listing=raw['transaction']['message']['instructions'] if location=='outer' else raw['meta']['innerInstructions'][0]['instructions']
        listing.append(deepcopy(instruction))
        raw['synthetic_review_note']='Independent v0.3.10 RPC-schema compatibility control; not signed or observed on mainnet.'
    fn=case.link_raw_alternative if mode=='alternative' else case.rearchive_raw_without_changing_pages
    return fn(record,change)

def observe(case,digest,label):
    p=case.derive();h=history(case);result=summarize(p,h,digest)
    result['reference_count']=len(case.cp['evidence'])
    result['unique_hashes']=len({r['hash'] for r in case.cp['evidence']})
    assert set(h['evidence_gates'].values())=={'UNKNOWN'}
    assert result['native_observed']['wallet_network_fees_sol']['value']=='0.000015'
    assert result['mutated_source_cited']
    record_result(label+'.json',result)
    return result
