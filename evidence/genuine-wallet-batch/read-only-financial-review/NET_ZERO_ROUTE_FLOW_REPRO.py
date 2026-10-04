"""Unsigned development mutation; never genuine source or wallet acceptance."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_retained_protocol_funding import originals, decode, wrapped, WALLET, WINDOW
from test_compiled_instructions import KEYS
from scanner.wallet_evidence import derive_wallet_evidence

raws = originals()
buy = deepcopy(raws[83])
message = buy['transaction']['message']
foreign = KEYS['source']
assert foreign not in message['accountKeys']
message['accountKeys'].insert(1, foreign)
message['header']['numRequiredSignatures'] += 1
# An unsigned schema control, not a signed/mainnet transaction. Keep the
# required signature array arity; no signature is produced or authenticated.
buy['transaction']['signatures'].append(buy['transaction']['signatures'][0])
for name in ('preBalances', 'postBalances'):
    buy['meta'][name].insert(1, 1000)
for name in ('preTokenBalances', 'postTokenBalances'):
    for balance in buy['meta'][name]:
        balance['accountIndex'] += int(balance['accountIndex'] >= 1)
for operation in message['instructions'] + [
        op for group in buy['meta']['innerInstructions'] for op in group['instructions']]:
    if 'programIdIndex' in operation:
        operation['programIdIndex'] += int(operation['programIdIndex'] >= 1)
    if 'accounts' in operation:
        operation['accounts'] = [index + int(index >= 1) for index in operation['accounts']]
group = next(group for group in buy['meta']['innerInstructions'] if group['index'] == 3)
for source, destination in ((WALLET, foreign), (foreign, WALLET)):
    group['instructions'].append({
        'programId': '11111111111111111111111111111111',
        'parsed': {'type': 'transfer', 'info': {
            'source': source, 'destination': destination, 'lamports': 1}}})
decoded = decode(buy)
records = [wrapped(buy), wrapped(raws[85])]
receipt = derive_wallet_evidence(records, all_records=records, wallet=WALLET,
    window=WINDOW, source_consistency={}, chronology={})
print(json.dumps({
    'scope': 'Unsigned development mutation of retained genuine83, not new genuine-chain evidence.',
    'source_sha256': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in ('scanner/investigation.py', 'scanner/wallet_evidence.py')},
    'mutation': 'Add foreign signer/static key, shift all indices, then same-route wallet->foreign and foreign->wallet System transfers of1lamport each; retain all native endpoints and swap token quantities.',
    'original_page_reference': 'evidence/genuine-wallet-batch/collection/phase5/02-lifetime-page-1-response.raw.gz',
    'original_page_sha256': '7517110b5b3825584ec24a6e48aad3c23fbcc4c475056f7708d56b87a999fe7a',
    'mutated_buy': buy,
    'selected_sell': raws[85],
    'decoded_events': decoded['events'],
    'decoder_unresolved': decoded['unresolved'],
    'native_roles': receipt['native_role_checks'],
    'supported_lots': receipt['query_accounting']['supported_selected_lots'],
    'whole_wallet_profit_state': receipt['metric_dependencies']['profit_sol']['state'],
}, indent=2))
