"""Pure final replay of earlier internal findings; no provider or credentials."""
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from test_compiled_instructions import transaction, KEYS, binary_base58
from scanner import compiled_instructions as module
from scanner.decoder import decode_transactions
from scanner.source_consistency import _program_facts


def main():
    checks = []
    transfer = {'programIdIndex': 4, 'accounts': [1, 2, 0],
                'data': binary_base58('030100000000000000')}
    raw = transaction(transfer, version=0.0)
    result = module.normalize_transaction(raw)
    checks.append({'id': 'float-v0-rejection', 'passing': not result['normalizations'] and
                   any(r['code'] == 'unsupported-version' for r in result['issues'])})
    raw = transaction(transfer, version=0)
    raw['transaction']['message']['addressTableLookups'] = [
        {'accountKey': KEYS['mint'], 'writableIndexes': [0], 'readonlyIndexes': [0]}]
    raw['meta']['loadedAddresses'] = {'writable': [KEYS['rent']], 'readonly': [KEYS['recent']]}
    result = module.normalize_transaction(raw)
    checks.append({'id': 'cross-role-lookup-position-rejection', 'passing': not result['normalizations'] and
                   any(r['code'] == 'conflicting-lookups' for r in result['issues'])})
    raw = transaction({'programId': KEYS['token'],
                       'accounts': [KEYS['rent'], KEYS['destination'], KEYS['authority']],
                       'data': transfer['data']})
    result = module.normalize_transaction(raw)
    checks.append({'id': 'opaque-absent-account-rejection', 'passing': not result['normalizations'] and
                   any(r['code'] == 'invalid-account-membership' for r in result['issues'])})
    raw = transaction({'programId': KEYS['system'], 'accounts': [0, 2],
                       'data': binary_base58('020000000100000000000000')})
    result = module.normalize_transaction(raw)
    checks.append({'id': 'opaque-absent-program-rejection', 'passing': not result['normalizations'] and
                   any(r['code'] == 'invalid-program-membership' for r in result['issues'])})
    for count in (8, 32):
        raw = transaction(transfer)
        raw['transaction']['message']['instructions'] = [deepcopy(transfer) for _ in range(count)]
        before = deepcopy(raw)
        with patch.object(module, 'normalize_transaction', wraps=module.normalize_transaction) as calls:
            facts = _program_facts(raw, raw['transaction']['message']['accountKeys'], KEYS['source'], 'a' * 64)
        checks.append({'id': 'one-normalization-per-projection-' + str(count),
                       'passing': calls.call_count == 1 and raw == before,
                       'whole_transaction_normalizations': calls.call_count,
                       'source_unchanged': raw == before, 'facts': len(facts)})
    raw = transaction(transfer, version=0)
    raw['meta']['loadedAddresses'] = {'writable': [KEYS['rent']] * 2048, 'readonly': []}
    raw['transaction']['message']['addressTableLookups'] = [
        {'accountKey': KEYS['mint'], 'writableIndexes': [0], 'readonlyIndexes': []}]
    with patch.object(module, '_pubkey', wraps=module._pubkey) as calls:
        result = module.normalize_transaction(raw)
    checks.append({'id': 'loaded-length-before-expensive-decode',
                   'passing': not result['normalizations'] and calls.call_count <= 5,
                   'pubkey_decodes': calls.call_count})
    raw = transaction({'programId': KEYS['system'], 'program': 'system', 'accounts': [0, 2],
                       'data': '0', 'parsed': {'type': 'transfer', 'info': {
                           'source': KEYS['authority'], 'destination': KEYS['destination'], 'lamports': 25}}})
    raw['meta'].update(preBalances=[10000, 0, 0, 0, 0], postBalances=[4975, 0, 25, 0, 0],
                       preTokenBalances=[], postTokenBalances=[])
    result = decode_transactions([{'signature': raw['transaction']['signatures'][0], 'raw': raw,
                                   'evidence_hash': 'a' * 64}], KEYS['authority'])
    kinds = [e['kind'] for e in result['events']]
    # Explicit unsupported diagnostic events are correct and must remain visible.
    checks.append({'id': 'generic-mixed-representation-retains-fee',
                   'passing': kinds.count('fee') == 1 and not set(kinds) & {'capital', 'buy', 'sell', 'transfer'}
                   and bool(result['unresolved']), 'event_kinds': kinds,
                   'unresolved': result['unresolved']})
    for check in checks:
        print(json.dumps(check, sort_keys=True))
    receipt = {'kind': 'read-only-final-previous-sibling-findings-replay',
               'state': 'PASS_IN_SCOPE' if all(c['passing'] for c in checks) else 'FAILED',
               'engineering_controls': len(checks), 'checks': checks,
               'provider_requests': 0, 'credential_lookups': 0, 'new_application_acceptance': False,
               'scope': 'Unsigned development controls; not unique acceptance tests or B3 proof.'}
    Path(sys.argv[1]).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'state': receipt['state'], 'engineering_controls': len(checks)}))
    return 0 if receipt['state'] == 'PASS_IN_SCOPE' else 1


if __name__ == '__main__':
    raise SystemExit(main())
