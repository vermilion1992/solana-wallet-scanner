"""Read-only unsigned review controls; no source edits, provider or credential access."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scanner import compiled_instructions as ci
from scanner import transaction_format as tf
from scanner.decoder import decode_transactions
from scanner.source_consistency import _program_facts

helpers = runpy.run_path(str(ROOT / 'tests/test_compiled_instructions.py'))
keys = helpers['KEYS']
transaction = helpers['transaction']
b58 = helpers['binary_base58']
subset = ['scanner/compiled_instructions.py', 'scanner/transaction_format.py',
          'scanner/source_consistency.py', 'scanner/decoder.py']
def source_hashes():
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in subset}
started = source_hashes()
transfer = {'programIdIndex': 4, 'accounts': [1, 2, 0], 'data': b58('030100000000000000')}
raw = transaction(transfer, version=0.0)
output = ci.normalize_transaction(raw)
print(json.dumps({'case': 'float-version', 'supported_transaction_format': tf.supported_transaction_format(raw),
                  'normalization_count': len(output['normalizations']), 'issues': output['issues']}))
raw = transaction(transfer, version=0)
raw['transaction']['message']['addressTableLookups'] = [{
    'accountKey': keys['mint'], 'writableIndexes': [0], 'readonlyIndexes': [0]}]
raw['meta']['loadedAddresses'] = {'writable': [keys['rent']], 'readonly': [keys['recent']]}
output = ci.normalize_transaction(raw)
print(json.dumps({'case': 'cross-group-duplicate-lookup-index',
                  'normalization_count': len(output['normalizations']), 'issues': output['issues'],
                  'resolved_keys': ci.resolve_account_keys(raw)['keys'],
                  'expectation_basis': 'One table index cannot identify two distinct keys in writable and readonly groups.'}))
for count in (8, 32, 128):
    raw = transaction(transfer)
    raw['transaction']['message']['instructions'] = [deepcopy(transfer) for _ in range(count)]
    before = deepcopy(raw)
    original = ci.normalize_transaction
    begin = time.perf_counter()
    with patch.object(ci, 'normalize_transaction', wraps=original) as calls:
        facts = _program_facts(raw, raw['transaction']['message']['accountKeys'], keys['source'], 'a'*64)
    elapsed = time.perf_counter()-begin
    assert raw == before
    print(json.dumps({'case': 'repeated-program-path-normalization', 'instruction_count': count,
                      'whole_transaction_normalizations': calls.call_count, 'fact_count': len(facts),
                      'elapsed_seconds': elapsed, 'source_unchanged': True}))
raw = transaction({'programId': keys['system'], 'program': 'system', 'accounts': [0, 2],
                   'data': '0', 'parsed': {'type': 'transfer', 'info': {
                       'source': keys['authority'], 'destination': keys['destination'], 'lamports': 25}}})
raw['meta'].update(preBalances=[10000,0,0,0,0], postBalances=[4975,0,25,0,0],
                   preTokenBalances=[], postTokenBalances=[])
output = ci.normalize_transaction(raw)
record = {'signature': raw['transaction']['signatures'][0], 'raw': raw, 'evidence_hash': 'a'*64}
result = decode_transactions([record], keys['authority'])
print(json.dumps({'case': 'generic-mixed-representation', 'adapter_issues': output['issues'],
                  'instruction_view_called': tf._needs_instruction_view(raw),
                  'events': result['events'], 'unresolved': result['unresolved'],
                  'qualification_claimed': False}))
ended = source_hashes()
print(json.dumps({'source_subset_before': started, 'source_subset_after': ended,
                  'subset_unchanged': started == ended,
                  'fixture_scope': 'Unsigned development review controls, not genuine-chain or whole-wallet acceptance',
                  'provider_requests': 0, 'credential_lookups': 0}))
