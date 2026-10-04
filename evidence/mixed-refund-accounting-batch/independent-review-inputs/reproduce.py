"""Independent exact-lamport oracle for current mixed administration seam.

These records are synthetic interface controls, never genuine B3 acceptance.
Expected cash is calculated from explicit integer movements, not implementation
receipts. Fixtures are built from independently pinned RPC literal operations.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path('/workspace/solana-wallet-scanner')
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from scanner.archive_input import canonical_bytes
from scanner.investigation import WSOL
from scanner.providers import TOKEN_PROGRAM
from test_cost_flow_evidence import primary, wrapped_funding
from test_wallet_evidence import ACCOUNT, WALLET, base, derive, parsed
from scanner.decoder import SYSTEM_ID

OUT = Path(__file__).parent


def controls():
    raw, account = wrapped_funding()
    raw['transaction']['signatures'] = ['mixed-native-incoming-close']
    # A checked transfer names the mint as a primary account too. The shared
    # development helper omits it until an instruction actually needs it.
    keys = raw['transaction']['message']['accountKeys']
    if WSOL not in keys:
        keys.append(WSOL)
        raw['meta']['preBalances'].append(1_461_600)
        raw['meta']['postBalances'].append(1_461_600)
        raw['transaction']['message']['header']['numReadonlyUnsignedAccounts'] += 1
    # Two existing wallet-owned native accounts; move 100 lamports worth of
    # canonical wrapped units between them, then close the receiving account.
    for phase, quantity in [('preTokenBalances', '100'), ('postTokenBalances', '0')]:
        point = next(p for p in raw['meta'][phase] if p['accountIndex'] == 1)
        point['mint'] = WSOL
        point['uiTokenAmount'] = {'amount': quantity, 'decimals': 9}
    raw['meta']['preBalances'][1] = 2_000_100
    raw['meta']['postBalances'][1] = 2_000_000
    raw['meta']['preBalances'][2] = 1_002_000_000
    raw['meta']['postBalances'][2] = 0
    raw['meta']['postTokenBalances'] = [p for p in raw['meta']['postTokenBalances'] if p['accountIndex'] != 2]
    raw['transaction']['message']['instructions'] = [
        parsed('transferChecked', {'source': ACCOUNT, 'destination': account, 'mint': WSOL,
            'authority': WALLET, 'tokenAmount': {'amount': '100', 'decimals': 9}}),
        parsed('closeAccount', {'account': account, 'destination': WALLET, 'owner': WALLET})]
    refund = 1_002_000_000 + 100
    raw['meta']['postBalances'][0] = raw['meta']['preBalances'][0] - 5_000 + refund
    native = (raw, {'opening_account_lamports': 1_002_000_000,
        'earlier_incoming_native_token_units': 100, 'refund_lamports': refund,
        'network_fee_lamports': 5_000,
        'wallet_native_delta_lamports': refund - 5_000,
        'all_observed_wallet_owned_native_delta_lamports': -5_000})

    raw = primary(base('mixed-system-topup-close'))
    raw['meta']['postTokenBalances'] = [p for p in raw['meta']['postTokenBalances'] if p['accountIndex'] != 1]
    raw['meta']['postBalances'][1] = 0
    raw['transaction']['message']['instructions'] = [
        parsed('transfer', {'source': WALLET, 'destination': ACCOUNT, 'lamports': 1000}, SYSTEM_ID),
        parsed('closeAccount', {'account': ACCOUNT, 'destination': WALLET, 'owner': WALLET})]
    refund = 2_000_000 + 1_000
    raw['meta']['postBalances'][0] = raw['meta']['preBalances'][0] - 5_000 - 1_000 + refund
    zero = (raw, {'opening_account_lamports': 2_000_000,
        'earlier_system_topup_lamports': 1_000, 'refund_lamports': refund,
        'network_fee_lamports': 5_000,
        'wallet_native_delta_lamports': -5_000 - 1_000 + refund,
        'all_observed_wallet_owned_native_delta_lamports': -5_000})
    return {'native-incoming-close': native, 'system-topup-close': zero}


def summarize(raw):
    evidence = derive([deepcopy(raw)])
    row = evidence['cost_flow_evidence']['transactions'][raw['transaction']['signatures'][0]]
    return {'roles': row['admitted_internal_roles'], 'check': row['check'],
        'unresolved_paths': row['unresolved_economic_paths'],
        'observed_economic_roles': evidence['components']['observed_economic_roles'],
        'native_fee': evidence['components']['native_fee'],
        'ledger_kinds': [e['kind'] for e in evidence['accounting_events']],
        'wallet_population': evidence['components']['historical_population']['state']}


def main():
    outputs = {}
    for name, (raw, worked) in controls().items():
        content = canonical_bytes(raw)
        (OUT / (name + '-input.json')).write_bytes(content)
        outputs[name] = {'input_sha256': hashlib.sha256(content).hexdigest(),
            'independently_worked': worked, 'actual': summarize(raw)}
    target = OUT / sys.argv[1]
    target.write_text(json.dumps(outputs, indent=2) + '\n')
    print(json.dumps({name: {'worked': row['independently_worked'],
         'check': row['actual']['check']['state'],
         'economic_roles': row['actual']['observed_economic_roles']['state'],
         'reason': row['actual']['check']['reason'],
         'ledger_kinds': row['actual']['ledger_kinds']} for name, row in outputs.items()}, indent=2))

if __name__ == '__main__':
    main()
