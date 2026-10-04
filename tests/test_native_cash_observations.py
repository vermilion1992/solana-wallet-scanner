"""Focused raw-transfer controls; selected movement is not capital or B3 proof."""
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path

from scanner.json_boundary import canonical_bytes
from scanner.native_cash_observations import derive_native_cash_observations
from scanner.decoder import SYSTEM_ID
from test_position_evidence import WALLET, address, START, END, WINDOW

OTHER = address(60)


def record(raw):
    return {'signature': raw['transaction']['signatures'][0], 'raw': raw,
            'evidence_hash': hashlib.sha256(canonical_bytes(raw, string_keys=True)).hexdigest()}


def transfer(source, destination, lamports):
    return {'programId': SYSTEM_ID, 'parsed': {'type': 'transfer', 'info': {
        'source': source, 'destination': destination, 'lamports': lamports}}}


def raw(signature='cash-development', *, incoming=0, outgoing=100, sponsored=False,
        at=START + 100, slot=100, inner=False):
    keys = [OTHER, WALLET, SYSTEM_ID] if sponsored else [WALLET, OTHER, SYSTEM_ID]
    wallet_index, other_index = keys.index(WALLET), keys.index(OTHER)
    before = [10_000_000_000, 10_000_000_000, 1]
    after = list(before)
    after[0] -= 5000
    after[wallet_index] += incoming - outgoing
    after[other_index] += outgoing - incoming
    instructions = ([transfer(OTHER, WALLET, incoming)] if incoming else []) + (
                    [transfer(WALLET, OTHER, outgoing)] if outgoing else [])
    return {'version': 0, 'slot': slot, 'blockTime': at,
        'transaction': {'signatures': [signature], 'message': {
            'accountKeys': keys,
            'header': {'numRequiredSignatures': 2, 'numReadonlySignedAccounts': 0,
                       'numReadonlyUnsignedAccounts': 1},
            'instructions': ([{'programId': OTHER, 'accounts': [], 'data': ''}] if inner else instructions)}},
        'meta': {'err': None, 'fee': 5000, 'preBalances': before, 'postBalances': after,
                 'preTokenBalances': [], 'postTokenBalances': [],
                 'innerInstructions': [{'index': 0, 'instructions': instructions}] if inner else []}}


def derive(raws, *, alternatives=(), **kwargs):
    selected = [record(value) for value in raws]
    return derive_native_cash_observations(selected, all_records=selected + list(alternatives),
        wallet=WALLET, window=WINDOW, **kwargs)


def test_sponsored_outer_and_inner_transfers_have_original_paths_and_unknown_economic_roles():
    original = raw(sponsored=True)
    parent = deepcopy(original)
    result = derive([original], alternatives=[record(raw(sponsored=True, inner=True))])
    row = result['transactions']['cash-development']
    assert row['transfer_check']['state'] == 'PASS'
    assert row['gross_out_lamports'] == '100' and row['gross_in_lamports'] == '0'
    assert row['network_fee']['check']['state'] == 'PASS' and row['network_fee']['lamports'] == '0'
    assert row['economic_role']['state'] == result['economic_roles_state'] == 'UNKNOWN'
    assert 'transaction.message.instructions.0.parsed.info.lamports' in row['transfer_check']['raw_paths']
    assert 'meta.innerInstructions.0.instructions.0.parsed.info.lamports' in row['transfer_check']['raw_paths']
    assert result['wallet_population_state'] == 'UNKNOWN' and result['qualification'] is False
    assert original == parent and result['provider_requests'] == result['credential_lookups'] == 0


def test_equal_gross_movements_survive_net_cancellation_and_failed_attempts_move_zero():
    success = raw(incoming=100, outgoing=100)
    result = derive([success])
    row = result['transactions']['cash-development']
    assert row['transfer_check']['state'] == 'PASS'
    assert row['gross_in_lamports'] == row['gross_out_lamports'] == '100'
    assert row['transfer_net_lamports'] == '0' and len(row['movements']) == 2
    failed = raw(incoming=900, outgoing=100)
    failed['meta']['err'] = {'InstructionError': [0, 'Custom']}
    failed['meta']['postBalances'] = list(failed['meta']['preBalances'])
    failed['meta']['postBalances'][0] -= 5000
    row = derive([failed])['transactions']['cash-development']
    assert row['failed'] is True and row['gross_in_lamports'] == row['gross_out_lamports'] == '0'
    assert row['movements'] == [] and row['network_fee']['lamports'] == '5000'


def test_malformed_quantity_or_inner_association_cannot_supply_known_gross_transfer_set():
    original = raw()
    for malformed in ('boolean-quantity', 'duplicate-inner', 'program-conflict', 'missing-source-signer'):
        broken = deepcopy(original)
        if malformed == 'boolean-quantity':
            broken['transaction']['message']['instructions'][0]['parsed']['info']['lamports'] = True
        elif malformed == 'duplicate-inner':
            inner = raw(inner=True)
            broken = deepcopy(inner)
            broken['meta']['innerInstructions'].append(deepcopy(broken['meta']['innerInstructions'][0]))
        elif malformed == 'program-conflict':
            broken['transaction']['message']['instructions'][0]['program'] = 'spl-token'
        else:
            broken = raw(sponsored=True)
            broken['transaction']['message']['header']['numRequiredSignatures'] = 1
        row = derive([broken])['transactions']['cash-development']
        assert row['transfer_check']['state'] == 'UNKNOWN' and row['gross_out_lamports'] is None
        assert row['network_fee']['check']['state'] == 'PASS'


def test_linked_source_loss_conflict_and_restoration_revoke_cash_but_keep_parent_immutable():
    original = raw()
    alternative = deepcopy(original)
    alternative['meta']['logMessages'] = ['Optional original metadata']
    link = record(alternative)
    parent = derive([original], alternatives=[link])
    frozen = deepcopy(parent)
    lost = derive([original], alternatives=[{**link, 'raw': None}])
    assert lost['transactions']['cash-development']['transfer_check']['state'] == 'UNKNOWN'
    assert lost['transactions']['cash-development']['movements'][0]['check']['state'] == 'UNKNOWN'
    conflict = raw(outgoing=101)
    assert derive([original], alternatives=[record(conflict)])['intervals']['report_period']['check']['state'] == 'UNKNOWN'
    assert derive([original], alternatives=[link]) == parent == frozen


def test_independent_intervals_and_missing_fee_do_not_erase_supported_transfer_facts():
    old = raw('old-cash', incoming=200, outgoing=0, at=END - 35 * 86400, slot=99)
    current = raw('new-cash', outgoing=100, at=END - 86400, slot=100)
    current['meta']['fee'] = None
    result = derive([old, current])
    assert result['transactions']['new-cash']['transfer_check']['state'] == 'PASS'
    assert result['transactions']['new-cash']['network_fee']['check']['state'] == 'UNKNOWN'
    assert result['intervals']['report_period']['gross_in_lamports'] == '0'
    assert result['intervals']['four_weeks']['gross_in_lamports'] == '0'
    assert result['intervals']['verification_90d']['gross_in_lamports'] == '200'
    assert derive([current, old]) == result


def test_hash_substitution_cannot_become_a_trusted_transfer_declaration():
    original = raw()
    selected = record(original)
    selected['evidence_hash'] = 'a' * 64
    result = derive_native_cash_observations([selected], all_records=[selected], wallet=WALLET, window=WINDOW)
    assert result['transactions']['cash-development']['transfer_check']['state'] == 'UNKNOWN'
    assert result['intervals']['report_period']['gross_out_lamports'] is None


def test_unrecorded_wallet_cpi_cannot_prove_zero_but_builtin_and_disjoint_scopes_remain_supported():
    cpi = raw(outgoing=0)
    cpi['transaction']['message']['instructions'] = [
        {'programId': OTHER, 'accounts': [WALLET], 'data': ''}]
    for omission in ('null', 'missing'):
        broken = deepcopy(cpi)
        if omission == 'null':
            broken['meta']['innerInstructions'] = None
        else:
            broken['meta'].pop('innerInstructions')
        result = derive([broken])
        row = result['transactions']['cash-development']
        assert row['transfer_check']['state'] == 'UNKNOWN' and row['gross_in_lamports'] is None
        assert 'CPI inner transfer recording' in row['transfer_check']['reason']
        assert row['network_fee']['check']['state'] == 'PASS'
        disjoint = deepcopy(broken)
        disjoint['transaction']['message']['instructions'][0]['accounts'] = []
        assert derive([disjoint])['transactions']['cash-development']['gross_out_lamports'] == '0'
        builtin = raw()
        if omission == 'null':
            builtin['meta']['innerInstructions'] = None
        else:
            builtin['meta'].pop('innerInstructions')
        assert derive([builtin])['transactions']['cash-development']['gross_out_lamports'] == '100'
    assert derive([cpi])['transactions']['cash-development']['gross_out_lamports'] == '0'


def test_all_proved_outside_records_supply_scoped_zero_with_retained_exclusion_and_loss_dependencies():
    original = raw(at=START - 100)
    parent = derive([original])
    interval = parent['intervals']['report_period']
    assert interval['check']['state'] == 'PASS'
    assert interval['gross_in_lamports'] == interval['gross_out_lamports'] == '0'
    assert record(original)['evidence_hash'] in interval['check']['evidence']
    conflicting = deepcopy(original)
    conflicting['blockTime'] = START + 100
    lost = derive([original], alternatives=[record(conflicting)])
    assert lost['intervals']['report_period']['check']['state'] == 'UNKNOWN'
    assert lost['intervals']['report_period']['gross_out_lamports'] is None
    assert lost['transactions']['cash-development']['network_fee']['check']['state'] == 'PASS'
    assert derive([original]) == parent


def test_genuine_original_sponsored_transfer_matches_independently_worked_integer_expectation():
    """One genuine operation proves a transfer, never a complete wallet report."""
    root = Path(__file__).resolve().parents[1]
    response = gzip.decompress((root / 'evidence/genuine-wallet-batch/collection/phase5/02-lifetime-page-1-response.raw.gz').read_bytes())
    assert hashlib.sha256(response).hexdigest() == '7517110b5b3825584ec24a6e48aad3c23fbcc4c475056f7708d56b87a999fe7a'
    original = json.loads(response)['result']['data'][77]
    wallet = '2Bj3dZTSSc14hFR9fCLN9CQ1TiaYyszCKX8fuVG7pyAY'
    assert original['transaction']['signatures'][0] == '2f3NcAezdhbqBYNRf6CrkAFZAs2ShV8sdACvVUxFZP5yJqExd9nDK16LqXuiBwTteVMFjNxx7vsrrux4dDM4nS94'
    # Independent literal endpoint arithmetic: wallet index1 is not fee payer.
    assert original['meta']['preBalances'][1] == 2_860_040
    assert original['meta']['postBalances'][1] == 650_240
    assert 2_860_040 - 650_240 == 2_209_800
    selected = record(original)
    window = {'start': '2026-09-04T06:00:00+00:00', 'end': '2026-10-04T06:00:00+00:00'}
    def replay(link):
        return derive_native_cash_observations([selected], all_records=[selected] + [link], wallet=wallet, window=window)
    alternative = deepcopy(original)
    alternative['unusedMetadata'] = 'Retained linked source control'
    linked = record(alternative)
    parent = replay(linked)
    row = parent['transactions'][selected['signature']]
    assert row['transfer_check']['state'] == 'PASS'
    assert row['gross_out_lamports'] == '2209800' and row['gross_in_lamports'] == '0'
    assert row['network_fee']['check']['state'] == 'PASS' and row['network_fee']['lamports'] == '0'
    assert 'transaction.message.instructions.0.data' in row['movements'][0]['raw_paths']
    lost = replay({**linked, 'raw': None})
    assert lost['transactions'][selected['signature']]['gross_out_lamports'] is None
    assert replay(linked) == parent
    assert parent['economic_roles_state'] == parent['wallet_population_state'] == 'UNKNOWN'
