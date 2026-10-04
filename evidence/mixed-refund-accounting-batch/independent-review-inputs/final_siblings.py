"""Final bounded independent shared valuation/refund controls."""
from copy import deepcopy
import json
import sys
from reproduce import controls, OUT
from test_wallet_evidence import derive, record, parsed, WALLET
from test_position_evidence import address
from scanner.investigation import WSOL

def check():
    raw, _ = controls()['system-topup-close']
    raw['meta']['fee'] = None
    missing_fee = derive([raw])
    signature = raw['transaction']['signatures'][0]
    roles = missing_fee['cost_flow_evidence']['transactions'][signature]
    refunds = [r for r in roles['admitted_internal_roles'] if r['role'] == 'wallet_owned_account_refund']
    assert roles['check']['state'] == 'PASS'
    assert len(refunds) == 1 and refunds[0]['lamports'] == '2001000'
    assert missing_fee['components']['native_fee']['state'] == 'UNKNOWN'
    assert missing_fee['components']['observed_economic_roles']['state'] == 'UNKNOWN'

    raw, _ = controls()['native-incoming-close']
    for phase in ('preTokenBalances', 'postTokenBalances'):
        next(p for p in raw['meta'][phase] if p['accountIndex'] == 1)['owner'] = address(40)
    foreign = derive([raw])
    signature = raw['transaction']['signatures'][0]
    roles = foreign['cost_flow_evidence']['transactions'][signature]
    refunds = [r for r in roles['admitted_internal_roles'] if r['role'] == 'wallet_owned_account_refund']
    assert roles['check']['state'] == 'PASS'
    assert len(refunds) == 1 and refunds[0]['lamports'] == '1002000100'
    assert any(event['kind'] == 'transfer_in' for event in foreign['accounting_events'])
    assert foreign['components']['observed_economic_roles']['state'] == 'UNKNOWN'
    assert foreign['components']['native_fee']['state'] == 'PASS'
    alternative = deepcopy(raw)
    alternative['meta']['logMessages'] = ['Independent optional linked original']
    link = record(alternative)
    parent = derive([raw], alternatives=[link])
    assert derive([raw], alternatives=[{**link, 'raw': None}])['cost_flow_evidence']['transactions'][signature]['check']['state'] == 'UNKNOWN'
    assert derive([raw], alternatives=[link]) == parent

    raw, _ = controls()['native-incoming-close']
    target = raw['transaction']['message']['accountKeys'][2]
    raw['transaction']['message']['instructions'] = [parsed('closeAccount', {
        'account': target, 'destination': WALLET, 'owner': WALLET})]
    for point in raw['meta']['preTokenBalances']:
        if point['accountIndex'] == 1:
            point['uiTokenAmount']['amount'] = '0'
    raw['meta']['preBalances'][1] = 2_000_000
    raw['meta']['preBalances'][2] = 999_999_999
    raw['meta']['postBalances'][0] = raw['meta']['preBalances'][0] - 5_000 + 999_999_999
    impossible = derive([raw])
    signature = raw['transaction']['signatures'][0]
    pair = impossible['transactions'][signature]['boundaries'][target]
    phase = next(p for p in impossible['economic_evidence']['observed_token_phases'][signature]['pre'] if p['account'] == target)
    assert pair['checks']['quantities']['state'] == 'UNKNOWN'
    assert phase['check']['state'] == 'UNKNOWN' and phase['observed_token_value_sol'] is None
    assert impossible['components']['observed_economic_roles']['state'] == 'UNKNOWN'
    assert impossible['components']['native_fee']['state'] == 'PASS'
    return {'state': 'PASS',
        'missing_unrelated_fee': {'exact_target_refund_lamports': '2001000', 'refund_role': 'PASS', 'fee': 'UNKNOWN', 'economic_roles': 'UNKNOWN'},
        'foreign_peer': {'exact_target_refund_lamports': '1002000100', 'cash_role': 'PASS', 'external_transfer_retained': True, 'economic_roles': 'UNKNOWN', 'fees': 'PASS', 'alt_loss_restore': True},
        'contradictory_owned_native_backing': {'quantities': 'UNKNOWN', 'phase_value': None, 'economic_roles': 'UNKNOWN', 'fees': 'PASS'}}

if __name__ == '__main__':
    result = check()
    (OUT / sys.argv[1]).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
