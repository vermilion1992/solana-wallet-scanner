#!/usr/bin/env python3
"""Independent frozen raw mainnet expectations; no scanner imports or networking.

This is an arithmetic oracle over retained bytes, not a historical enumeration
certificate or a production decoder. Explicit BQJ instruction paths are manually
selected from the primary record. All other rows remain in the raw inventory.
"""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
import gzip
import hashlib
import json
from pathlib import Path

WALLET = '2Bj3dZTSSc14hFR9fCLN9CQ1TiaYyszCKX8fuVG7pyAY'
PAGE_HASH = '7517110b5b3825584ec24a6e48aad3c23fbcc4c475056f7708d56b87a999fe7a'
ARCHIVE_HASH = '3c409ce6c1bec579f852616ada235e99e3063810c7a841cf4544751ba6c0c481'
MINT = 'BQJfL1yiHbJQ8AciHLcKxaCbQrWP2ws8oZHHYgbBpump'
TOKEN = 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
TOKEN22 = 'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb'
SYSTEM = '11111111111111111111111111111111'
ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
HERE = Path(__file__).resolve().parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def decode58(value):
    integer = 0
    for character in value:
        integer = integer * 58 + ALPHABET.index(character)
    return b'\0' * (len(value) - len(value.lstrip('1'))) + integer.to_bytes((integer.bit_length() + 7) // 8, 'big')


def sol(lamports):
    sign = '-' if lamports < 0 else ''
    digits = str(abs(lamports)).rjust(10, '0')
    value = sign + digits[:-9] + '.' + digits[-9:]
    return value.rstrip('0').rstrip('.')


def rational(value):
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}


def decimal_display(value):
    with localcontext() as context:
        context.prec = 192
        return format(Decimal(value.numerator) / Decimal(value.denominator), 'f')


def account_keys(record):
    meta = record['meta']
    return record['transaction']['message']['accountKeys'] + meta['loadedAddresses']['writable'] + meta['loadedAddresses']['readonly']


def inner(record, parent_index, instruction_index):
    return next(group['instructions'][instruction_index] for group in record['meta']['innerInstructions'] if group['index'] == parent_index)


def instruction_fact(record, instruction, path):
    keys = account_keys(record)
    raw = decode58(instruction['data'])
    program = keys[instruction['programIdIndex']]
    accounts = [keys[index] for index in instruction['accounts']]
    result = {'path': path, 'program': program, 'accounts': accounts, 'data_hex': raw.hex()}
    if program in (TOKEN, TOKEN22):
        result['tag'] = raw[0]
        if raw[0] in (3, 7, 8, 12):
            result['amount_raw'] = int.from_bytes(raw[1:9], 'little')
        if raw[0] == 12:
            assert len(raw) == 10
            result['decimals'] = raw[9]
    elif program == SYSTEM:
        result['tag'] = int.from_bytes(raw[:4], 'little')
        if result['tag'] in (0, 2):
            result['lamports'] = int.from_bytes(raw[4:12], 'little')
    return result


def owned_balances(record, field):
    keys = account_keys(record)
    return [{'account': keys[b['accountIndex']], 'account_index': b['accountIndex'],
             'mint': b['mint'], 'owner': b['owner'], 'program': b.get('programId'),
             'quantity_raw': b['uiTokenAmount']['amount'], 'decimals': b['uiTokenAmount']['decimals']}
            for b in record['meta'][field] if b.get('owner') == WALLET]


def native_delta(record):
    keys = account_keys(record)
    if WALLET not in keys:
        return 0
    index = keys.index(WALLET)
    return record['meta']['postBalances'][index] - record['meta']['preBalances'][index]


def main():
    raw = gzip.decompress((HERE/'collection/phase5/02-lifetime-page-1-response.raw.gz').read_bytes())
    assert sha(raw) == PAGE_HASH
    payload = json.loads(raw)
    records = payload['result']['data']
    assert len(records) == 87
    assert len({r['transaction']['signatures'][0] for r in records}) == 87
    assert all(r['version'] == 'legacy' or type(r['version']) is int and r['version'] == 0 for r in records)
    scopes = json.loads((HERE/'collection/CURRENT_REPORT_SCOPES.json').read_text())
    inventory = []
    for index, record in enumerate(records):
        keys = account_keys(record)
        fee = record['meta']['fee']
        assert type(fee) is int and fee >= 0
        inventory.append({'record_pointer': f'result.data[{index}]', 'signature': record['transaction']['signatures'][0],
                          'slot': record['slot'], 'transaction_index': record['transactionIndex'],
                          'block_time': record['blockTime'],
                          'timestamp': datetime.fromtimestamp(record['blockTime'], timezone.utc).isoformat(),
                          'version': record['version'], 'error': record['meta']['err'],
                          'payer': keys[0], 'provider_reported_network_fee_lamports': fee,
                          'wallet_paid_network_fee_lamports': fee if keys[0] == WALLET else 0,
                          'wallet_in_account_keys': WALLET in keys,
                          'selected_record_native_wallet_delta_lamports': native_delta(record),
                          'pre_wallet_owned_balances': owned_balances(record, 'preTokenBalances'),
                          'post_wallet_owned_balances': owned_balances(record, 'postTokenBalances'),
                          'outer_programs': [keys[x['programIdIndex']] for x in record['transaction']['message']['instructions']],
                          'economic_scope': 'Retained raw observation; unreviewed instruction/cost/flow/eligibility roles are unresolved, never silently omitted.'})
    fees = {}
    for name, scope in scopes.items():
        if not isinstance(scope, dict) or 'start' not in scope:
            continue
        lower = int(datetime.fromisoformat(scope['start']).timestamp())
        upper = int(datetime.fromisoformat(scope['end']).timestamp())
        selected = [i for i, r in enumerate(records) if lower <= r['blockTime'] < upper]
        lamports = sum(inventory[i]['wallet_paid_network_fee_lamports'] for i in selected)
        fees[name] = {'start': scope['start'], 'end': scope['end'], 'record_indices': selected,
                      'selected_records': len(selected), 'wallet_payer_indices': [i for i in selected if inventory[i]['payer'] == WALLET],
                      'network_fee_lamports': lamports, 'network_fee_sol': sol(lamports),
                      'selected_native_wallet_delta_lamports': sum(native_delta(records[i]) for i in selected),
                      'scope': 'Selected 87-record provider query population in this independent half-open interval; never whole-wallet profit.'}
    assert fees['report']['network_fee_lamports'] == 158868
    buy, sell = records[83], records[85]
    assert buy['meta']['err'] is None and sell['meta']['err'] is None
    assert account_keys(buy)[0] == WALLET and account_keys(sell)[0] == WALLET
    assert buy['slot'] < sell['slot']
    quote_paths = [instruction_fact(buy, inner(buy, 3, i), f'result.data[83].meta.innerInstructions[index=3].instructions[{i}]') for i in (3, 4, 5, 6)]
    assert all(f['program'] == TOKEN and f['tag'] == 12 and f['decimals'] == 9 and f['accounts'][0] == 'FnSHTxNGXTA1f8EWKWKLKHeps8w8ArBQ3p7Emnr66jxV' and f['accounts'][3] == WALLET for f in quote_paths)
    quote = sum(f['amount_raw'] for f in quote_paths)
    assert quote == 565135100
    acquisition = instruction_fact(buy, inner(buy, 3, 2), 'result.data[83].meta.innerInstructions[index=3].instructions[2]')
    disposal = instruction_fact(sell, inner(sell, 1, 1), 'result.data[85].meta.innerInstructions[index=1].instructions[1]')
    proceeds = instruction_fact(sell, inner(sell, 1, 2), 'result.data[85].meta.innerInstructions[index=1].instructions[2]')
    assert acquisition['program'] == TOKEN22 and acquisition['tag'] == 12 and acquisition['accounts'][1] == MINT
    assert disposal['program'] == TOKEN22 and disposal['tag'] == 12 and disposal['accounts'][1] == MINT
    assert acquisition['amount_raw'] == disposal['amount_raw'] == 516612982765
    assert proceeds['program'] == TOKEN and proceeds['tag'] == 12 and proceeds['amount_raw'] == 551929943
    assert owned_balances(buy,'preTokenBalances')[0]['quantity_raw'] == '0'
    assert owned_balances(buy,'postTokenBalances')[0]['quantity_raw'] == '516612982765'
    assert owned_balances(sell,'preTokenBalances')[0]['quantity_raw'] == '516612982765'
    assert owned_balances(sell,'postTokenBalances')[0]['quantity_raw'] == '0'
    rent = instruction_fact(buy, inner(buy,3,0), 'result.data[83].meta.innerInstructions[index=3].instructions[0]')
    assert rent['program'] == SYSTEM and rent['tag'] == 0 and rent['lamports'] == 1346200
    assert rent['accounts'][0] == WALLET and rent['accounts'][1] == '9DVALworRmwiFeFgqqRGYkrsQxCJsQ9u1VCQiG5Fk8kg'
    basis = Fraction(quote + buy['meta']['fee'])
    matched_basis = basis * Fraction(disposal['amount_raw'], acquisition['amount_raw'])
    exit_net = proceeds['amount_raw'] - sell['meta']['fee']
    loss = Fraction(exit_net) - matched_basis
    assert loss == -13270924
    assert native_delta(buy) == -(quote + buy['meta']['fee'] + rent['lamports'])
    assert native_delta(sell) == proceeds['amount_raw'] - sell['meta']['fee']
    hold_seconds = sell['blockTime'] - buy['blockTime']
    lot = {'mint': MINT, 'account': acquisition['accounts'][2], 'decimals': 6,
           'scope': 'Selected named-account 0→purchase→full-sale→0; assumes no hidden same-mint holdings/intervening activity. Does not establish whole-wallet eligibility or population.',
           'buy_record_index': 83, 'sell_record_index': 85, 'quantity_acquired_raw': str(acquisition['amount_raw']),
           'quantity_disposed_raw': str(disposal['amount_raw']), 'remaining_raw': '0',
           'buy_quote_components_lamports': [f['amount_raw'] for f in quote_paths],
           'buy_quote_lamports': quote, 'buy_network_fee_lamports': buy['meta']['fee'],
           'buy_basis_lamports': rational(basis), 'matched_disposed_basis_lamports': rational(matched_basis),
           'sell_received_quote_lamports': proceeds['amount_raw'], 'sell_network_fee_lamports': sell['meta']['fee'],
           'sell_net_proceeds_lamports': exit_net, 'conditional_lot_profit_lamports': rational(loss),
           'conditional_lot_profit_sol': sol(int(loss)), 'conditional_lot_roi_pct': rational(loss/basis*100),
           'conditional_lot_roi_pct_display_192_digit': decimal_display(loss/basis*100),
           'hold_seconds': hold_seconds, 'hold_hours': rational(Fraction(hold_seconds,3600)),
           'first_positive_sale_within_5_minutes': hold_seconds <= 300,
           'buy_count': 1, 'sell_count': 1, 'persisted_user_volume_accumulator_lamports': rent['lamports'],
           'temporary_wsol_rent_lamports': 1488440,
           'cost_treatment': 'wSOL outgoing transfers include embedded venue fees. Actual network fee once in basis/exit. Persisted accumulator account funding remains a separately located/refundable balance, not automatic expense. Temporary wSOL rent cancels on same-record closure.',
           'source_hashes': [PAGE_HASH], 'raw_instruction_facts': quote_paths+[acquisition,disposal,proceeds,rent]}
    unknown_metrics = ('profit_sol','realised_roi_pct','median_roi_pct','win_rate_pct','median_hold_hours','completed_positions','completed_positions_90d','traded_mints','rapid_sale_pct','avg_buys','avg_sells','positive_weeks','largest_contribution_pct','economic_pnl_sol')
    metrics = {m:{'status':'unknown','value':None} for m in unknown_metrics}
    metrics['observed_network_fees_sol'] = {'status':'known','value':sol(fees['report']['network_fee_lamports'])}
    calculations = [
        {'description':'Sum integer meta.fee only where the native first account key equals this wallet; keep sponsors and the genuine failed record separately. Report-window payer indices are independently selected from raw Unix timestamps.', 'source_hashes':[PAGE_HASH], 'formula':'sum(meta.fee for selected records with first_key==wallet and report_start<=blockTime<report_end)', 'result_lamports':fees['report']['network_fee_lamports']},
        {'description':'Independently scope the same selected raw records over report30, trailing28 and verification90 days, never reusing a report receipt as another interval certificate.', 'source_hashes':[PAGE_HASH], 'results':fees},
        {'description':'BQJ purchase quote is the sum of four actual wSOL TransferChecked amounts, including embedded venue fees, not the System wrap maximum or wallet native debit.', 'source_hashes':[PAGE_HASH], 'formula':'559550761+139609+5305122+139608', 'result_lamports':quote},
        {'description':'One selected FIFO lot: acquired and disposed 516612982765 integer units. Matched basis=(565135100+58918)*(516612982765/516612982765)=565194018. Separate persisted accumulator funding1346200 from purchase costs; temporary wSOL rent1488440 is returned.', 'source_hashes':[PAGE_HASH], 'result_lamports':rational(matched_basis)},
        {'description':'Sell received wSOL551929943 less actual wallet-paid network fee6849=551923094. Matched selected-lot loss=551923094−565194018=−13270924lamports. This preserves a genuine losing lot without inventing wallet qualification.', 'source_hashes':[PAGE_HASH], 'result_sol':sol(int(loss))},
        {'description':'Named-account first purchase at1791079700 and final full sale at1791080229 gives529seconds=529/3600hours; full zero observed. No hidden-account population certificate or meme classification follows from this.', 'source_hashes':[PAGE_HASH], 'result_hours':rational(Fraction(hold_seconds,3600))},
        {'description':'Whole-wallet metric expectations remain UNKNOWN because historical membership, complete economic roles/origins, eligibility and economic boundary marks/flows are not established. Native fee observation retains its independent requirements.', 'source_hashes':[PAGE_HASH], 'not_b3':True},
        {'description':'Genuine owner-not-key Token2022 lifecycle: rows56/57 retain10,000,000 units for a wallet absent from both message key lists, then burn and close; this observes provider support for one such case, not universal enumeration.', 'source_hashes':[PAGE_HASH], 'records':[56,57]},
        {'description':'Do not reinterpret residual-token cleanup as a sale: GJ row73 leaves1raw unit; row76 transfers1 and closes. F1z row79 acquires131200547457units; row81 transfers them out and closes. Transfer-interrupted and unresolved routes stay visible.', 'source_hashes':[PAGE_HASH], 'records':[72,73,76,79,81]}
    ]
    result = {'version':'genuine-wallet-worked-expectations-v1', 'archive_sha256':ARCHIVE_HASH,
              'archive_binding_scope':'Initial phase5 indexed archive; parent may reseal only archive binding after checksum-identical native controls/current snapshots are added. Calculated raw-page identity and arithmetic must remain unchanged.',
              'address':WALLET,'source_page_sha256':PAGE_HASH,'source_page_bytes':len(raw),
              'oracle':'Independent raw integer/base58/Fraction arithmetic; no scanner imports or production calculation functions; frozen before application report run.',
              'metrics':metrics,
              'query_accounting':{'monetary_state':'UNKNOWN','conditional_observed_lot_profit_sol':None,'wallet_population_state':'UNKNOWN','qualification':False},
              'calculations':calculations,'supported_selected_lots':[lot],
              'network_fee_totals':{'all_provider_reported_lamports':sum(x['provider_reported_network_fee_lamports'] for x in inventory),
                                    'all_selected_wallet_paid_lamports':sum(x['wallet_paid_network_fee_lamports'] for x in inventory),
                                    'all_selected_wallet_paid_sol':sol(sum(x['wallet_paid_network_fee_lamports'] for x in inventory)),
                                    'all_selected_sponsored_fee_lamports':sum(x['provider_reported_network_fee_lamports'] for x in inventory if x['payer']!=WALLET),
                                    'failed_records':[{'index':i,'payer':x['payer'],'fee_lamports':x['provider_reported_network_fee_lamports'],'wallet_fee_lamports':x['wallet_paid_network_fee_lamports']} for i,x in enumerate(inventory) if x['error'] is not None], 'independent_intervals':fees},
              'raw_record_inventory':inventory,
              'native_control_choices':[{'row':i,'signature':records[i]['transaction']['signatures'][0],'slot':records[i]['slot'],'transaction_index':records[i]['transactionIndex']} for i in (83,85,76,56,57)],
              'unresolved_dependencies':['Exhaustive historical owned-account population for both programs, including all hidden accounts','Complete incoming origins and event-time acquisition basis across every relevant record','Unreviewed multi-user/forwarder, authority, mint/burn/freeze and non-SOL routes and economic roles','Time-relevant meme/settlement/spam classification','Exact all-asset report-boundary inventory, historical marks and valued external flows'],
              'B3':'BLOCKED','PRODUCT_READY':False}
    out=HERE/'WORKED_REAL_EXPECTATIONS.json'
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'path':str(out),'bytes':out.stat().st_size,'sha256':sha(out.read_bytes()),
                      'report_fee_sol':metrics['observed_network_fees_sol']['value'],
                      'selected_lot_loss_sol':lot['conditional_lot_profit_sol'], 'hold_seconds':hold_seconds,
                      'all_wallet_fee_lamports':result['network_fee_totals']['all_selected_wallet_paid_lamports'],
                      'provider_calls':0,'production_imports':0}))


if __name__ == '__main__':
    main()
