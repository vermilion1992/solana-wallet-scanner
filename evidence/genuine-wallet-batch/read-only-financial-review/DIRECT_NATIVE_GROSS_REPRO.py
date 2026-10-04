"""Unsigned development native-Pump ABI example; no genuine-chain assertion."""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_retained_protocol_funding import b58, wrapped
from scanner.investigation import PUMP, decode_supported_swaps
from scanner.wallet_evidence import derive_wallet_evidence

key = lambda value: b58(bytes([value]) * 32)
wallet, own, curve, pool, fee, foreign, mint = (key(v) for v in range(1, 8))
token, system = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA', '11111111111111111111111111111111'
keys = [wallet, foreign, own, curve, pool, fee, mint, PUMP, token, system]
at = 1791079700
window = {'start': '2026-09-04T06:00:00+00:00', 'end': '2026-10-04T06:00:00+00:00'}
def transfer(source, destination, lamports):
    return {'programId': system, 'parsed': {'type': 'transfer',
        'info': {'source': source, 'destination': destination, 'lamports': lamports}}}
def balance(index, amount, owner):
    return {'accountIndex': index, 'mint': mint, 'owner': owner, 'programId': token,
        'uiTokenAmount': {'amount': str(amount), 'decimals': 6}}
def native(sell=False):
    name = 'sell' if sell else 'buy'
    data = hashlib.sha256(('global:' + name).encode()).digest()[:8] + bytes(16)
    before = [10_000_000_000, 1000, 2_039_280, 2_000_000_000, 2_039_280, 1000, 0, 1, 1, 1]
    after = list(before)
    quote = 900_000_000 if sell else 1_000_000_000
    after[0] += quote - 5000 if sell else -quote - 5000
    after[3] += -quote if sell else quote
    src, dst = (own, pool) if sell else (pool, own)
    cash = transfer(curve, wallet, quote) if sell else transfer(wallet, curve, quote)
    flow = {'programId': token, 'parsed': {'type': 'transferChecked', 'info': {
        'source': src, 'destination': dst, 'mint': mint,
        'tokenAmount': {'amount': '100', 'decimals': 6}}}}
    return {'version': 'legacy', 'slot': 10 + int(sell), 'blockTime': at + 529 * int(sell),
        'transaction': {'signatures': ['unsigned-native-development-' + name, 'unsigned-foreign-development-' + name], 'message': {
            'header': {'numRequiredSignatures': 2, 'numReadonlySignedAccounts': 0, 'numReadonlyUnsignedAccounts': 4},
            'accountKeys': keys, 'instructions': [{'programId': PUMP,
                'accounts': [fee, fee, mint, curve, pool, own, wallet, system, token],
                'data': [base64.b64encode(data).decode(), 'base64']}]}},
        'meta': {'err': None, 'fee': 5000, 'preBalances': before, 'postBalances': after,
            'preTokenBalances': [balance(2, 100 if sell else 0, wallet), balance(4, 0 if sell else 100, curve)],
            'postTokenBalances': [balance(2, 0 if sell else 100, wallet), balance(4, 100 if sell else 0, curve)],
            'innerInstructions': [{'index': 0, 'instructions': [cash, flow]}]}}

buy, sale = native(), native(True)
def assess(raw):
    rows = [wrapped(raw), wrapped(sale)]
    result = derive_wallet_evidence(rows, all_records=rows, wallet=wallet, window=window,
        source_consistency={}, chronology={})
    return decode_supported_swaps([rows[0]], wallet), result
positive, parent = assess(buy)
assert parent['query_accounting']['supported_selected_lots'][0]['monetary_state'] == 'PASS'
mutation = deepcopy(buy)
mutation['meta']['innerInstructions'][0]['instructions'].extend([
    transfer(wallet, foreign, 1), transfer(foreign, wallet, 1)])
decoded, result = assess(mutation)
print(json.dumps({'scope': 'Unsigned development native-Pump accepted ABI control; no signed/authentic/genuine-history assertion',
    'source_sha256': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
        for p in ('scanner/investigation.py', 'scanner/wallet_evidence.py')},
    'positive_input': buy, 'mutated_input': mutation, 'selected_sell': sale,
    'positive_events': positive['events'], 'positive_lots': parent['query_accounting']['supported_selected_lots'],
    'mutated_events': decoded['events'], 'mutated_unresolved': decoded['unresolved'],
    'mutated_lots': result['query_accounting']['supported_selected_lots'],
    'whole_wallet_profit_state': result['metric_dependencies']['profit_sol']['state']}, indent=2))
