#!/usr/bin/env python3
"""Create a secret-free bounded feasibility plan. This tool cannot make requests."""
import argparse
from datetime import timedelta
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scanner.accounting import utc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=ROOT/'evidence/runs/real-cache')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    original = json.loads(gzip.decompress((args.corpus/'manifest.json.gz').read_bytes()))
    report = original['report']; address = report['address']; end = utc(report['window']['end'])
    frozen = json.loads(gzip.decompress((args.corpus/'archives'/f"{report['collection_input_hash']}.json.gz").read_bytes()))
    start = end - timedelta(days=90)
    options = {'transactionDetails':'full','limit':100,'sortOrder':'asc','commitment':'finalized',
               'maxSupportedTransactionVersion':1,'filters':{'status':'any','tokenAccounts':'none',
               'blockTime':{'gte':int(start.timestamp()),'lt':int(end.timestamp())}}}
    requests = []
    def add(name, method, params, cap, **extra):
        requests.append({'id':name,'method':method,'params':params,'credit_upper_bound':cap, **extra})
    add('direct-index','getTransactionsForAddress',[address,options],10)
    all_options=json.loads(json.dumps(options));all_options['filters']['tokenAccounts']='all'
    add('all-index','getTransactionsForAddress',[address,all_options],10)
    add('all-continuation','getTransactionsForAddress',[address,all_options],10,
        conditional='Only if all-index returns a supported nonterminal pagination token.',
        paginationToken_from='all-index.result.paginationToken')
    for i, record in enumerate(frozen['transactions'][:4]):
        add(f'primary-{i+1}','getTransaction',[record['signature'],{'encoding':'jsonParsed','commitment':'finalized','maxSupportedTransactionVersion':1}],10,
            archived_control_hash=record['evidence_hash'])
    for suffix, program in [('legacy','TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'),('2022','TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb')]:
        add('current-owned-'+suffix,'getTokenAccountsByOwner',[address,{'programId':program},{'encoding':'jsonParsed','commitment':'finalized'}],1,
            scope='Current observation only; never a historical owner witness.')
    add('finalized-slot','getSlot',[{'commitment':'finalized'}],1)
    plan={'kind':'bounded-source-probe-plan','state':'NEEDS_AUTHORISATION','executed':False,
          'scope':'Read-only source feasibility; not full-wallet collection or acceptance',
          'endpoint':'https://mainnet.helius-rpc.com/ (API key supplied privately only after approval)',
          'wallet':address,'window':{'start':start.isoformat(),'end':end.isoformat()},
          'request_cap':10,'credit_cap':100,'planned_credit_upper_bound':sum(r['credit_upper_bound'] for r in requests),
          'requests':requests,'retries':0,'purchases':False,'quota_reset':False,
          'preconditions':['Explicit permission for this exact bounded probe.',
                          'Manual current Free subscription/cycle/remaining-credit confirmation; no autoscaling.',
                          'Do not repurpose or reset the exhausted setup-pilot ledger.',
                          'Independent known closed/reassigned controls are required before historic ownership can PASS.'],
          'required_receipts':['Sanitized exact request/response bytes with source URL without key, UTC retrieval and SHA-256.',
                               'Result count, finalized context, raw signatures/versions/owners/quantities, cursors and terminal/cap reasons.',
                               'Every charged reservation/settlement bound to the existing confirmed cycle.',
                               'Comparison against retained primary controls; missing closed/reassigned controls means INCONCLUSIVE.'],
          'stop_conditions':['Method/entitlement denial, unsupported response, request/credit cap, repeated cursor or mismatched primary identity.',
                             'No permission to continue collection follows from a successful probe.'],
          'current_outcome':'UNTESTED; docs do not prove no free route exists.'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:stream.write(json.dumps(plan,indent=2)+'\n')
    print(json.dumps({'path':str(args.output),'sha256':hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      'state':plan['state'],'request_cap':10,'credit_cap':100,'executed':False}))
    return 0


if __name__=='__main__':raise SystemExit(main())
