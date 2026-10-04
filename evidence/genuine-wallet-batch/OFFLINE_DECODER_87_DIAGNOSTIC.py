#!/usr/bin/env python3
"""Read current decoder only against frozen genuine records, without saved reports.

No source mutation, provider call, caller completion/classification flag, adapted
instruction fixture, or fabricated transaction-order proof. The independently
worked oracle supplies only the frozen raw identity and explicit report window.
"""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path

from scanner.investigation import decode_supported_swaps, _keys, _route
from scanner.decoder import decode_transactions
from scanner.compiled_instructions import normalize_transaction
from scanner.accounting import analyze
from scanner.transaction_format import instruction_view

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def run():
    expectation_path = HERE/'WORKED_REAL_EXPECTATIONS.json'
    expected = json.loads(expectation_path.read_bytes())
    raw_path = HERE/'collection/phase5/02-lifetime-page-1-response.raw.gz'
    raw_bytes = gzip.decompress(raw_path.read_bytes())
    digest = sha(raw_bytes)
    assert digest == expected['source_page_sha256']
    assert len(raw_bytes) == expected['source_page_bytes']
    records = json.loads(raw_bytes)['result']['data']
    wallet = expected['address']
    window = expected['network_fee_totals']['independent_intervals']['report']
    start, end = window['start'], window['end']
    wrapped = [{'signature': raw['transaction']['signatures'][0], 'raw':raw, 'evidence_hash':digest} for raw in records]

    def decode(selected):
        swaps = decode_supported_swaps(selected, wallet)
        supported = {event['signature'] for event in swaps['events'] if event['kind'] in ('buy','sell')}
        generic = decode_transactions([row for row in selected if row['signature'] not in supported], wallet)
        events = generic['events'] + [event for event in swaps['events'] if event['signature'] in supported]
        fifo = analyze(events, start, end, history_complete=False)
        return swaps, generic, events, fifo

    swaps, generic, events, fifo = decode(wrapped)
    pair_swaps, pair_generic, pair_events, pair_fifo = decode([wrapped[i] for i in (83,85)])
    pair = {'raw_indices':[83,85], 'swaps':pair_swaps, 'generic':pair_generic,
            'merged_events':pair_events, 'fifo':pair_fifo, 'normalization':{}}
    for index in (83,85):
        normalized = normalize_transaction(records[index])
        pair['normalization'][str(index)] = {'issues':normalized['issues'],
                                           'normalizations':normalized['normalizations']}

    source_paths = ['scanner/investigation.py','scanner/decoder.py','scanner/accounting.py',
                    'scanner/wallet_evidence.py','scanner/compiled_instructions.py',
                    'tests/fixtures/compiled_instructions/spl-token-interface-instruction.rs']
    observations = []
    for index, row in enumerate(wrapped):
        signature = row['signature']
        observations.append({'index':index,'path':f'result.data[{index}]','signature':signature,
            'event_counts':dict(Counter(e['kind'] for e in events if e['signature']==signature)),
            'swap_gaps':[e for e in swaps['unresolved'] if e['signature']==signature],
            'generic_gaps':[e for e in generic['unresolved'] if e['signature']==signature]})
    begin = int(datetime.fromisoformat(start).timestamp())
    finish = int(datetime.fromisoformat(end).timestamp())
    fees = sum(raw['meta']['fee'] for raw in records if begin <= raw['blockTime'] < finish and _keys(raw['transaction']['message'],raw['meta'])[0]==wallet)
    assert fees == expected['network_fee_totals']['independent_intervals']['report']['network_fee_lamports'] == 158868
    output = {'kind':'read-only-raw-decoder-diagnostic', 'source_page_sha256':digest,
        'source_page_bytes':len(raw_bytes), 'records':len(records), 'window':{'start':start,'end':end},
        'scope':'Direct current decoder only; full retained raw page. No saved-report workflow, classification/completion flags, provider calls or caller transaction-order proofs. Raw page transactionIndex remains observational and is never injected as proof.',
        'source_binding':{str(path):sha((ROOT/path).read_bytes()) for path in source_paths},
        'expectations_sha256':sha(expectation_path.read_bytes()),
        'events_counts':dict(Counter(e['kind'] for e in events)), 'swaps_coverage':swaps['coverage'],
        'swap_gap_counts':dict(Counter(e['reason'] for e in swaps['unresolved'])), 'pair':pair,
        'independent_raw_fee_check_lamports':fees,
        'full_fifo':{'metrics':fifo['metrics'],'positions':fifo['positions'],
                     'known_realised_profit_sol':fifo['known_realised_profit_sol']},
        'records_observations':observations, 'not_b3':True, 'PRODUCT_READY':False}
    path = HERE/'OFFLINE_DECODER_87_DIAGNOSTIC.json'
    path.write_text(json.dumps(output,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'diagnostic':str(path.relative_to(ROOT)), 'bytes':path.stat().st_size,'sha256':sha(path.read_bytes()),
                     'records':len(records),'decoded_swaps':swaps['coverage']['decoded_swaps'],
                     'pair_gaps':pair_swaps['unresolved'],'pair_positions':pair_fifo['positions'],
                     'selected_window_fee_lamports':fees},indent=2))

if __name__ == '__main__':
    run()
