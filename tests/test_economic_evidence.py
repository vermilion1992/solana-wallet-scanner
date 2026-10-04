"""Small raw economic-observation controls; no synthetic B3 acceptance."""
from copy import deepcopy
from pathlib import Path

from scanner.archive_input import import_archive, load_archive
from scanner.economic_evidence import derive_economic_evidence
from scanner.investigation import WSOL
from scanner.providers import TOKEN_PROGRAM
from scanner.storage import Store
from scanner.wallet_evidence import derive_wallet_evidence
from test_position_evidence import ACCOUNT, END, START, WALLET, WINDOW, address
from test_wallet_evidence import base, derive, record


def economic(raws, *, alternatives=()):
    original = deepcopy(raws)
    rows = [record(raw) for raw in raws]
    evidence = derive(raws, alternatives=alternatives)
    result = derive_economic_evidence(rows, all_records=rows + list(alternatives),
        wallet=WALLET, window=WINDOW, wallet_evidence=evidence)
    assert raws == original
    assert result['economic_inputs'] == {}
    assert result['qualification'] is False
    assert result['provider_requests'] == result['credential_lookups'] == 0
    return result, evidence


def wrapped_phase():
    raw = base(quantity=1_000_000_000)
    for name in ('preTokenBalances', 'postTokenBalances'):
        for row in raw['meta'][name]:
            if row['accountIndex'] == 1:
                row['mint'] = WSOL
                row['programId'] = TOKEN_PROGRAM
                row['uiTokenAmount']['decimals'] = 9
    raw['meta']['preBalances'][1] = raw['meta']['postBalances'][1] = 1_002_039_280
    return raw


def test_protocol_wrapped_sol_mark_and_native_phase_survive_missing_unrelated_fee():
    raw = wrapped_phase()
    raw['meta']['fee'] = None
    result, evidence = economic([raw])
    native = result['observed_native_phases']['synthetic-operation']
    assert native['check']['state'] == 'PASS'
    assert native['pre'] == str(raw['meta']['preBalances'][0])
    assert native['post'] == str(raw['meta']['postBalances'][0])
    token = next(row for row in result['observed_token_phases']['synthetic-operation']['pre'] if row['account'] == ACCOUNT)
    assert token['mark_sol_per_token'] == '1' and token['observed_token_value_sol'] == '1'
    assert token['account_lamports_value_state'] == 'UNKNOWN'
    assert evidence['components']['native_fee']['state'] == 'UNKNOWN'
    assert result['component_checks']['boundary_inventory']['state'] == 'UNKNOWN'
    assert result['component_checks']['historical_marks']['state'] == 'UNKNOWN'


def test_absolute_native_conflict_does_not_erase_independent_protocol_unit_mark():
    raw, alternative = wrapped_phase(), wrapped_phase()
    alternative['meta']['preBalances'][0] += 100
    alternative['meta']['postBalances'][0] += 100
    result, evidence = economic([raw], alternatives=[record(alternative)])
    native = result['observed_native_phases']['synthetic-operation']
    assert native['check']['state'] == 'UNKNOWN' and native['pre'] is None
    assert record(alternative)['evidence_hash'] in native['check']['evidence']
    assert result['protocol_settlement_marks']
    assert all(row['check']['state'] == 'PASS' for row in result['protocol_settlement_marks'])
    assert evidence['components']['native_fee']['state'] == 'PASS'


def test_equivalent_native_phase_array_locations_are_not_conflicting_facts():
    raw = base()
    raw['transaction']['message']['accountKeys'].insert(0, address(98))
    raw['meta']['postBalances'][0] = raw['meta']['preBalances'][0]
    raw['meta']['preBalances'].insert(0, 1_000_000_000)
    raw['meta']['postBalances'].insert(0, 999_995_000)
    for name in ('preTokenBalances', 'postTokenBalances'):
        for row in raw['meta'][name]:
            row['accountIndex'] += 1
    alternative = deepcopy(raw)
    ordering = [0, 2, 1, 3, 4, 5]
    alternative['transaction']['message']['accountKeys'] = [
        alternative['transaction']['message']['accountKeys'][index] for index in ordering]
    for name in ('preBalances', 'postBalances'):
        alternative['meta'][name] = [alternative['meta'][name][index] for index in ordering]
    for name in ('preTokenBalances', 'postTokenBalances'):
        for row in alternative['meta'][name]:
            row['accountIndex'] = ordering.index(row['accountIndex'])
    result, _ = economic([raw], alternatives=[record(alternative)])
    native = result['observed_native_phases']['synthetic-operation']
    assert native['check']['state'] == 'PASS'
    assert native['pre'] == native['post'] == '10000000000'
    assert native['raw_paths'] == ['meta.postBalances.1', 'meta.postBalances.2',
                                  'meta.preBalances.1', 'meta.preBalances.2']


def test_required_alternative_loss_revokes_dependent_observations_and_restoration_is_exact():
    raw = wrapped_phase()
    frozen = {'signature': 'synthetic-operation', 'evidence_hash': 'a' * 64, 'raw': None}
    parent, _ = economic([raw])
    missing, _ = economic([raw], alternatives=[frozen])
    assert missing['observed_native_phases']['synthetic-operation']['check']['state'] == 'UNKNOWN'
    assert missing['protocol_settlement_marks'] == []
    restored, _ = economic([raw], alternatives=[record(deepcopy(raw))])
    assert restored == parent


def test_independent_windows_and_absent_native_address_never_manufacture_zero_inventory():
    raw = base()
    raw['blockTime'] = END - 40 * 86400
    result, _ = economic([raw])
    boundaries = result['boundary_candidates_by_interval']
    assert boundaries['report_period']['opening_native_lamports_candidate'] is None
    assert boundaries['four_weeks']['opening_native_lamports_candidate'] is None
    assert boundaries['verification_90d']['check']['state'] == 'PASS'
    assert boundaries['verification_90d']['native_boundary_projection']['state'] == 'UNKNOWN'
    absent = base()
    absent['transaction']['message']['accountKeys'][0] = address(93)
    result, _ = economic([absent])
    native = result['observed_native_phases']['synthetic-operation']
    assert native['check']['state'] == 'PASS' and native['present'] is False
    assert native['pre'] is None and native['post'] is None
    assert result['boundary_candidates_by_interval']['report_period']['opening_native_lamports_candidate'] is None


def test_nonsettlement_units_are_not_valued_and_zero_units_need_no_price():
    raw = base(quantity=100)
    result, _ = economic([raw])
    token = next(row for row in result['observed_token_phases']['synthetic-operation']['pre'] if row['account'] == ACCOUNT)
    assert token['observed_token_value_sol'] is None and token['check']['state'] == 'UNKNOWN'
    zero = base(quantity=0)
    result, _ = economic([zero])
    token = next(row for row in result['observed_token_phases']['synthetic-operation']['pre'] if row['account'] == ACCOUNT)
    assert token['observed_token_value_sol'] == '0' and token['check']['state'] == 'PASS'
    assert token['mark_sol_per_token'] is None and token['account_lamports_value_state'] == 'UNKNOWN'


def test_partial_internal_zero_flow_result_never_supplies_equity_or_complete_economic_inputs(monkeypatch):
    import scanner.economic_evidence as module
    raw = base(quantity=0)
    rows = [record(raw)]
    adapter = derive([raw])
    original = module._combine
    # This one internal composition transition is not an imported source or a
    # population witness. Exercise a future valid role result while preserving
    # the actual absent boundary/mark adapters and their UNKNOWN decisions.
    def known_flow(rows, reason, **kwargs):
        output = original(rows, reason, **kwargs)
        if 'complete_gross_economic_roles' in kwargs.get('dependencies', ()):
            output.update(state='PASS', reason='Development-only internal zero-flow transition')
        return output
    monkeypatch.setattr(module, '_combine', known_flow)
    result = module.derive_economic_evidence(rows, all_records=rows, wallet=WALLET,
        window=WINDOW, wallet_evidence=adapter)
    assert result['zero_external_flow_inputs']['report_period'] == {
        'external_deposits': '0', 'external_withdrawals': '0'}
    assert result['economic_inputs'] == {}
    assert result['component_checks']['boundary_inventory']['state'] == 'UNKNOWN'
    assert result['component_checks']['historical_marks']['state'] == 'UNKNOWN'


def test_retained_genuine_original_native_phase_is_known_without_complete_wallet_profit(tmp_path):
    root = Path(__file__).resolve().parents[1]
    raw_zip = root / 'evidence/genuine-report-speed-batch/checker-inputs/genuine87-inventory-input.zip'
    store = Store(tmp_path)
    manifest_hash = import_archive(store, raw_zip.read_bytes())
    loaded = load_archive(store, manifest_hash)
    manifest = loaded['manifest']
    adapter = derive_wallet_evidence(loaded['records'], all_records=loaded['all_records'],
        wallet=manifest['address'], window=manifest['window'], source_consistency={}, chronology={},
        raw_sources=loaded['raw_sources'], source_receipts=loaded['receipts'])
    result = derive_economic_evidence(loaded['records'], all_records=loaded['all_records'],
        wallet=manifest['address'], window=manifest['window'], wallet_evidence=adapter)
    signature = '1K8o6wdkahjF4rThLdpcUDpLytVVEa8hYtCDf56YQZVxiFVMu9PZE3FVJzHQ6xLdSALDmoUKRZdA6RAhE4zBLU6'
    phase = result['observed_native_phases'][signature]
    assert phase['check']['state'] == 'PASS'
    assert phase['pre'] == '125740592' and phase['post'] == '125740593'
    assert phase['pre_sol'] == '0.125740592' and phase['post_sol'] == '0.125740593'
    assert result['economic_inputs'] == {}
    assert all(result['component_checks'][key]['state'] == 'UNKNOWN' for key in
        ('boundary_inventory', 'historical_marks', 'valued_external_flows'))
    assert adapter['components']['native_fee']['state'] == 'PASS'
