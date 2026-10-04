"""Distinct source-bound research review; unsigned mutations are not B3 evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from scanner.investigation import decode_supported_swaps
from scanner.research import summarize_research
from scanner.wallet_evidence import derive_wallet_evidence
from scanner.accounting import utc
from test_retained_protocol_funding import wrapped, originals, WALLET, MINT, WINDOW

here = ROOT / 'evidence/genuine-wallet-batch/read-only-financial-review'
original = json.loads((ROOT/'tests/fixtures/mainnet-pumpswap-buy-exact-quote.json').read_text())
wallet = '4drEkXDZhjun3vjZmz1g7pQGM7kxANQbDuD9jtPZwzJZ'
original['evidence_hash'] = hashlib.sha256(json.dumps(original['raw'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
observed = decode_supported_swaps([original], wallet)
clock = original['raw']['blockTime']
start, end = utc(clock-3600).isoformat(), utc(clock+3600).isoformat()
research = summarize_research(observed['events'], start, end)

frozen = json.loads((here/'NET_ZERO_ROUTE_FLOW_FIRST.json').read_text())
mutated_buy = frozen['mutated_buy']
clean = originals()
clean_rows = [wrapped(clean[83]), wrapped(clean[85])]
bad_rows = [wrapped(mutated_buy), wrapped(clean[85])]
anchor = {MINT: {'quantity_raw': '0', 'timestamp': utc(mutated_buy['blockTime']-1).isoformat(),
    'scope': 'wallet_owned_mint', 'verified': True, 'intervening_flows_complete': True,
    'evidence': ['d'*64]}}
def replay(rows, *, add_orphan=False):
    decoded = decode_supported_swaps(rows, WALLET)
    events = deepcopy(decoded['events'])
    if add_orphan:
        buy = next(e for e in events if e['kind']=='buy')
        events.append({'kind':'capital','timestamp':buy['timestamp'],'order':buy['order']+1,
            'amount_sol':'0.000000001','economic_role':'unknown','direction':'withdrawal',
            'signature':buy['signature'],'path':'development-independent-cash-role',
            'reason':'Unsigned development capital role control','evidence':['c'*64]})
    result = summarize_research(events, WINDOW['start'], WINDOW['end'], opening_inventory=anchor)
    adapter = derive_wallet_evidence(rows, all_records=rows, wallet=WALLET, window=WINDOW,
        source_consistency={}, chronology={})
    return {'decoded':decoded,'research':result,'typed_lots':adapter['query_accounting']['supported_selected_lots']}

cases={'clean-positive':replay(clean_rows),'marked-unknown-native-cash':replay(bad_rows),
       'separate-unknown-capital-event':replay(clean_rows,add_orphan=True)}
print(json.dumps({'scope':'Distinct source-bound research sibling review; synthetic anchor and unsigned cash-loop mutation are development controls only.',
    'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
        ('scanner/research.py','scanner/investigation.py','scanner/wallet_evidence.py','scanner/app.py')},
    'production_fixture_diagnostic':{'decoder':observed,'research':research},
    'synthetic_opening_anchor':anchor,'exact_mutated_buy':mutated_buy,'exact_clean_sale':clean[85],
    'cases':cases},indent=2))
