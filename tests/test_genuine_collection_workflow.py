"""Offline checker contracts using development bytes; never genuine B3 proof."""
from copy import deepcopy
import gzip
import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest

from scanner.indexed_input import pack_indexed_bytes
from scanner.accounting import analyze
from scanner.metric_evidence import METRIC_REQUIREMENTS, compose_metric_decisions
from tools.check_genuine_collection import (freeze_expectations, load_input_freeze, pack_collection, real_acceptance,
                                           run, selected_lot_controls, verify_worked_expectations, verify_selected_lots,
                                           verify_selected_lot_revoked)

WALLET = '2QfBNK2WDwSLoUQRb1zAnp3KM12N9hQ8q6ApwUMnWW2T'
WINDOW = {'start': '2026-01-01T00:00:00+00:00', 'end': '2026-01-31T00:00:00+00:00'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def record(signature='selected-a', fee=5000, payer=WALLET, when=1767571200):
    return {'version': 0, 'slot': 10, 'transactionIndex': 0, 'blockTime': when,
        'transaction': {'signatures': [signature], 'message': {'accountKeys': [payer], 'instructions': []}},
        'meta': {'err': {'InstructionError': [0, 'Custom']}, 'fee': fee,
                 'preBalances': [10000000], 'postBalances': [10000000-fee],
                 'preTokenBalances': [], 'postTokenBalances': [], 'innerInstructions': [],
                 'loadedAddresses': {'writable': [], 'readonly': []}}}


def page(rows, ident=1):
    request = {'jsonrpc': '2.0', 'id': ident, 'method': 'getTransactionsForAddress', 'params': [WALLET,
        {'transactionDetails': 'full', 'limit': 100, 'sortOrder': 'asc', 'commitment': 'finalized',
         'maxSupportedTransactionVersion': 1, 'filters': {'status': 'any', 'tokenAccounts': 'all',
          'blockTime': {'gte': 1767225600, 'lt': 1769817600}}}]}
    response = {'jsonrpc': '2.0', 'id': ident, 'result': {'data': rows, 'paginationToken': None}}
    return json.dumps(request, indent=2).encode(), json.dumps(response, indent=1).encode()


def archive(pages):
    manifest = {'version': 'indexed-wallet-input-v1', 'address': WALLET, 'window': WINDOW,
                'pages': [], 'transactions': []}
    raw = {}
    for request, response in pages:
        manifest['pages'].append({'request_hash': sha(request), 'response_hash': sha(response)})
        raw[sha(request)] = request
        raw[sha(response)] = response
    return pack_indexed_bytes(manifest, raw)


def collection(directory, rows):
    directory.mkdir()
    request, response = page(rows)
    request_path, response_path = '01-history-request.json', '01-history-response.raw.gz'
    compressed = gzip.compress(response, mtime=0)
    (directory/request_path).write_bytes(request)
    (directory/response_path).write_bytes(compressed)
    receipt = {'kind': 'authorised-bounded-native-collection', 'state': 'COLLECTED_IN_SCOPE',
        'provider_requests': 1, 'plan_sha256': 'a'*64,
        'requests': [{'id': 'history', 'method': 'getTransactionsForAddress', 'state': 'OBSERVED',
            'request_path': request_path, 'response_path': response_path,
            'request_sha256': sha(request), 'response_sha256': sha(response),
            'response_bytes': len(response), 'credential_redaction_applied': False}],
        'artifacts': {request_path: {'sha256': sha(request), 'bytes': len(request)},
                      response_path: {'sha256': sha(compressed), 'bytes': len(compressed)}}}
    (directory/'result.json').write_text(json.dumps(receipt))
    return receipt


def test_independent_oracle_adds_integer_fees_once_without_metric_helpers(monkeypatch):
    import scanner.accounting
    monkeypatch.setattr(scanner.accounting, 'analyze', lambda *a, **k: pytest.fail('Oracle called production accounting'))
    rows = [record(), record('selected-b', 140394), record('sponsored', 10000, '11111111111111111111111111111111')]
    content = archive([page(rows), page(rows, 2)])
    expected = freeze_expectations(content)
    assert expected['observed_network_fees_sol']['value'] == '0.000145394'
    assert expected['observed_network_fees_sol']['lamports'] == 145394
    assert expected['unique_signatures'] == 3 and expected['raw_records'] == 6
    assert expected['wallet_profit_expectation'].startswith('Not inferred')


def test_conflicting_fee_alternative_stays_unknown():
    content = archive([page([record()]), page([record(fee=6000)], 2)])
    expected = freeze_expectations(content)
    assert expected['observed_network_fees_sol']['status'] == 'unknown'
    assert expected['observed_network_fees_sol']['value'] is None


def test_checksum_loss_cannot_be_replaced_by_caller_expected_fee():
    content = archive([page([record()])])
    with zipfile.ZipFile(io.BytesIO(content)) as source:
        files = {name: source.read(name) for name in source.namelist()}
    response_name = next(name for name, raw in files.items() if name.startswith('raw/') and b'paginationToken' in raw)
    files[response_name] += b' '
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w') as packed:
        for name, raw in files.items():
            packed.writestr(name, raw)
    with pytest.raises(ValueError, match='checksum'):
        freeze_expectations(target.getvalue())


def test_collection_packing_preserves_original_noncanonical_bytes_and_receipt(tmp_path):
    source = tmp_path/'collection'
    receipt = collection(source, [record()])
    content, acquisition = pack_collection([source], WALLET, WINDOW)
    with zipfile.ZipFile(io.BytesIO(content)) as packed:
        request_hash = receipt['requests'][0]['request_sha256']
        response_hash = receipt['requests'][0]['response_sha256']
        assert packed.read(f'raw/{request_hash}.json') == (source/'01-history-request.json').read_bytes()
        assert packed.read(f'raw/{response_hash}.json') == gzip.decompress((source/'01-history-response.raw.gz').read_bytes())
    assert acquisition[0]['provider_requests'] == 1
    assert 'does not prove historical population' in acquisition[0]['scope']


def test_existing_zip_identity_retains_bound_acquisition_without_repacking(tmp_path):
    source = tmp_path/'collection'
    collection(source, [record()])
    content, acquisition = pack_collection([source], WALLET, WINDOW)
    value = {'kind': 'offline-genuine-checker-input-freeze', 'archive_sha256': sha(content),
             'bytes': len(content), 'acquisition': acquisition}
    path = tmp_path/'freeze.json'
    path.write_text(json.dumps(value))
    assert load_input_freeze(path, content) == acquisition
    value['archive_sha256'] = '0'*64
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='identity'):
        load_input_freeze(path, content)


def add_public_collection(directory, *, url=None, query=None, logical_method='publicTrendingPools'):
    path = directory/'result.json'
    receipt = json.loads(path.read_text())
    url = url or 'https://api.geckoterminal.com/api/v2/networks/solana/trending_pools'
    request = json.dumps({'method': 'GET', 'url': url, 'query': {'page': 1} if query is None else query}).encode()
    response = json.dumps({'data': []}).encode()
    compressed = gzip.compress(response, mtime=0)
    request_path, response_path = '02-public-request.json', '02-public-response.raw.gz'
    (directory/request_path).write_bytes(request)
    (directory/response_path).write_bytes(compressed)
    receipt['requests'].append({'method': logical_method, 'state': 'OBSERVED', 'source_url': url,
        'request_path': request_path, 'response_path': response_path,
        'request_sha256': sha(request), 'response_sha256': sha(response),
        'response_bytes': len(response), 'credential_redaction_applied': False})
    receipt['artifacts'][request_path] = {'sha256': sha(request), 'bytes': len(request)}
    receipt['artifacts'][response_path] = {'sha256': sha(compressed), 'bytes': len(compressed)}
    path.write_text(json.dumps(receipt))


def test_mixed_public_and_native_acquisitions_preserve_auxiliary_hashes_without_admission(tmp_path):
    source = tmp_path/'collection'
    collection(source, [record()])
    add_public_collection(source)
    original_public = (source/'02-public-response.raw.gz').read_bytes()
    content, acquisition = pack_collection([source], WALLET, WINDOW)
    assert freeze_expectations(content)['observed_network_fees_sol']['value'] == '0.000005'
    auxiliary = acquisition[0]['auxiliary_raw_sources']
    assert auxiliary[0]['method'] == 'publicTrendingPools'
    assert auxiliary[0]['response_hash'] == sha(gzip.decompress(original_public))
    assert (source/'02-public-response.raw.gz').read_bytes() == original_public
    with zipfile.ZipFile(io.BytesIO(content)) as packed:
        manifest = json.loads(packed.read('manifest.json'))
        assert len(manifest['pages']) == 1
        assert auxiliary[0]['response_hash'] not in packed.namelist()


@pytest.mark.parametrize('url,query', [
    ('https://api.geckoterminal.com.evil.example/api/v2/networks/solana/trending_pools', {'page': 1}),
    ('https://api.geckoterminal.com/api/v2/networks/ethereum/trending_pools', {'page': 1}),
    ('https://api.geckoterminal.com/api/v2/networks/solana/trending_pools', {'page': True}),
])
def test_public_route_exception_does_not_admit_wrong_origin_network_or_shape(tmp_path, url, query):
    source = tmp_path/'collection'
    collection(source, [record()])
    add_public_collection(source, url=url, query=query)
    with pytest.raises(ValueError):
        pack_collection([source], WALLET, WINDOW)


@pytest.mark.parametrize('change', ['compressed-bytes', 'path-traversal', 'redacted-original'])
def test_collection_input_hash_path_and_original_byte_guards(tmp_path, change):
    source = tmp_path/'collection'
    receipt = collection(source, [record()])
    if change == 'compressed-bytes':
        (source/'01-history-response.raw.gz').write_bytes(b'wrong')
    elif change == 'path-traversal':
        receipt['requests'][0]['response_path'] = '../outside.raw.gz'
    else:
        receipt['requests'][0]['credential_redaction_applied'] = True
    (source/'result.json').write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        pack_collection([source], WALLET, WINDOW)


def test_normal_app_replay_freezes_oracle_exports_and_immutable_source_controls(tmp_path):
    content = archive([page([record()])])
    output = tmp_path/'check'
    assert run(content, output) == 0
    result = json.loads((output/'result.json').read_text())
    assert result['state'] == 'WORKFLOW_PASS_REAL_ACCEPTANCE_BLOCKED'
    assert result['oracle_frozen_before_application'] is True
    assert result['provider_requests'] == result['credential_lookups'] == 0
    assert result['parent_unchanged'] and result['usage_unchanged']
    assert result['real_acceptance']['state'] == 'BLOCKED' and result['PRODUCT_READY'] is False
    expected = json.loads((output/'EXPECTED_RAW.json').read_text())
    parent = json.loads((output/'parent-report.json').read_text())
    child = json.loads((output/'source-missing-child.json').read_text())
    assert expected['observed_network_fees_sol']['value'] == '0.000005'
    assert parent['metrics']['observed_network_fees_sol']['value'] == '0.000005'
    assert child['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    assert (output/'parent-report.csv').exists()
    assert len(json.loads((output/'inspected-selected-sources.json').read_text())) >= 2


def test_frozen_expectations_are_checked_on_parent_baseline_and_restored_children(tmp_path):
    content = archive([page([record()])])
    oracle = freeze_expectations(content)
    worked = {'version': 'genuine-wallet-worked-expectations-v1', 'archive_sha256': sha(content),
              'metrics': {'observed_network_fees_sol': {'status': 'known', 'value': '0.000005'}},
              'calculations': [{'description': 'Raw fee integer 5000 divided by 1000000000.',
                                'source_hashes': [next(iter(oracle['raw_input_hashes']))]}]}
    output = tmp_path/'rechecked'
    assert run(content, output, worked_expectations=worked) == 0
    receipt = json.loads((output/'result.json').read_text())
    comparisons = [case for case in receipt['cases'] if case['case'] == 'separately-worked-supported-results']
    assert {case['report_role'] for case in comparisons} == {'parent', 'baseline-child', 'fee-source-restored-child'}
    restored = json.loads((output/'source-restored-child.json').read_text())
    parent = json.loads((output/'parent-report.json').read_text())
    assert restored['metrics'] == parent['metrics']


def test_real_acceptance_requirement_returns_blocked_even_with_relabelled_acquisition(tmp_path):
    content = archive([page([record()])])
    # This fixture imitates acquisition metadata only for the interface test;
    # it does not supply an accepted historical population or B3 evidence.
    acquisition = [{'kind': 'authorised-bounded-native-collection', 'receipt_sha256': 'a'*64}]
    output = tmp_path/'required'
    assert run(content, output, acquisition=acquisition, require_real=True) == 2
    result = json.loads((output/'result.json').read_text())
    assert result['state'] == 'BLOCKED'
    assert any('historical' in reason for reason in result['real_acceptance']['missing'])
    assert result['PRODUCT_READY'] is False


@pytest.mark.parametrize('attempt', ['provider', 'credentials'])
def test_swallowed_offline_guard_attempt_cannot_produce_passing_receipt(tmp_path, monkeypatch, attempt):
    import httpx
    import scanner.app as application
    original = application.create_app
    def swallowed(*args, **kwargs):
        try:
            if attempt == 'provider':
                httpx.Client().get('https://example.invalid/offline-guard-control')
            else:
                import keyring
                keyring.get_password('offline-control', 'unavailable')
        except AssertionError:
            pass
        return original(*args, **kwargs)
    monkeypatch.setattr(application, 'create_app', swallowed)
    output = tmp_path/'guard-check'
    with pytest.raises(AssertionError, match='zero provider and credential'):
        run(archive([page([record()])]), output)
    receipt = json.loads((output/'result.json').read_text())
    assert receipt['state'] == 'FAILED'
    assert receipt['provider_requests' if attempt == 'provider' else 'credential_lookups'] == 1
    assert receipt['PRODUCT_READY'] is False


def test_future_acceptance_checks_actual_dependencies_and_worked_input_binding():
    partial = {'source': 'live', 'coverage': {'wallet_evidence': {'components': {
        'historical_population': {'state': 'UNKNOWN'}}}}, 'metrics': {}}
    worked = {'version': 'genuine-wallet-worked-expectations-v1', 'archive_sha256': 'a'*64,
              'calculations': [{'formula': 'Not a completeness proof'}], 'metrics': {}}
    result = real_acceptance(partial, [{'receipt_sha256': 'b'*64}], worked, 'c'*64)
    assert result['state'] == 'BLOCKED'
    assert any('exact raw inputs' in reason for reason in result['missing'])
    assert any('historical' in reason for reason in result['missing'])


def mathematical_acceptance_contract(*, cost='1', proceeds='0.5', empty=False):
    """Pure synthetic predicate diagnostic with explicit assumed dependencies.

    This does not import an archive, authenticate source population, or close B3.
    It isolates undefined mathematical formulas after source sufficiency passes.
    """
    common = {'mint': 'development-acceptance', 'quantity_raw': '100', 'decimals': 0,
              'classification': 'meme', 'paid_by_wallet': True, 'fee_sol': '0', 'evidence': ['a'*64]}
    rows = [] if empty else [
        {**common, 'kind': 'buy', 'timestamp': '2026-01-05T00:00:00+00:00', 'amount_sol': cost},
        {**common, 'kind': 'sell', 'timestamp': '2026-01-05T06:00:00+00:00', 'amount_sol': proceeds}]
    calculated = analyze(rows, WINDOW['start'], WINDOW['end'], history_complete=True,
                         opening_equity='1', closing_equity='1', external_deposits='0', external_withdrawals='0')
    names = {name for _, requirements in METRIC_REQUIREMENTS.values() for name in requirements if name != 'interval_records'}
    components = {name: {'state': 'PASS', 'evidence': ['a'*64], 'scope': 'Assumed development interface only'} for name in names}
    intervals = {scope: {'state': 'PASS', 'evidence': ['a'*64]} for scope in ('report_period', 'four_weeks', 'verification_90d')}
    decisions = compose_metric_decisions(components, intervals, metric_observations=calculated['metrics'])
    report = {'source': 'live', **calculated, 'window': WINDOW,
              'coverage': {'wallet_evidence': {'components': components}, 'metric_dependencies': decisions},
              'qualification': {'state': 'UNRESOLVED'}}
    worked = {'version': 'genuine-wallet-worked-expectations-v1', 'archive_sha256': 'b'*64,
              'calculations': [{'description': 'Explicit development mathematical predicate assumptions.'}],
              'metrics': deepcopy(report['metrics'])}
    return report, worked, components, intervals


@pytest.mark.parametrize('proceeds', ['0.5', '1', '2'])
def test_supported_losing_breakeven_and_profitable_reports_can_meet_engineering_contract(proceeds):
    report, worked, _, _ = mathematical_acceptance_contract(proceeds=proceeds)
    original = deepcopy(report)
    result = real_acceptance(report, [{'scope': 'Pure development predicate diagnostic'}], worked, 'b'*64)
    assert result['state'] == 'PASS'
    if proceeds in ('0.5', '1'):
        assert [row['metric'] for row in result['mathematically_inapplicable']] == ['largest_contribution_pct']
        assert report['metrics']['largest_contribution_pct'] == worked['metrics']['largest_contribution_pct']
        assert report['metrics']['largest_contribution_pct']['status'] == 'unknown'
    else:
        assert result['mathematically_inapplicable'] == []
    assert report == original and report['qualification']['state'] == 'UNRESOLVED'


def test_nonpositive_net_does_not_excuse_missing_basis_population_or_incorrect_formula():
    report, worked, components, intervals = mathematical_acceptance_contract()
    components['acquisition_basis']['state'] = 'UNKNOWN'
    report['coverage']['metric_dependencies'] = compose_metric_decisions(components, intervals, metric_observations=report['metrics'])
    result = real_acceptance(report, [{'scope': 'Development only'}], worked, 'b'*64)
    assert result['state'] == 'BLOCKED' and result['mathematically_inapplicable'] == []
    assert any('largest_contribution_pct' in reason for reason in result['missing'])
    report, worked, _, _ = mathematical_acceptance_contract()
    report['metrics']['largest_contribution_pct']['population'] = 'An unrelated caller-defined ratio'
    worked['metrics']['largest_contribution_pct']['population'] = 'An unrelated caller-defined ratio'
    result = real_acceptance(report, [{'scope': 'Development only'}], worked, 'b'*64)
    assert result['state'] == 'BLOCKED' and result['mathematically_inapplicable'] == []
    report, worked, components, intervals = mathematical_acceptance_contract()
    components['historical_population']['state'] = 'UNKNOWN'
    report['coverage']['metric_dependencies'] = compose_metric_decisions(components, intervals, metric_observations=report['metrics'])
    assert real_acceptance(report, [{'scope': 'Development only'}], worked, 'b'*64)['state'] == 'BLOCKED'


def test_proved_empty_cohort_and_zero_basis_are_distinct_from_missing_evidence():
    report, worked, _, _ = mathematical_acceptance_contract(empty=True)
    result = real_acceptance(report, [{'scope': 'Development only'}], worked, 'b'*64)
    assert result['state'] == 'PASS'
    assert {row['metric'] for row in result['mathematically_inapplicable']} == {
        'largest_contribution_pct', 'realised_roi_pct', 'median_roi_pct', 'win_rate_pct',
        'median_hold_hours', 'rapid_sale_pct', 'avg_buys', 'avg_sells'}
    assert report['metrics']['completed_positions']['value'] == '0'
    report, worked, components, intervals = mathematical_acceptance_contract(cost='0', proceeds='1')
    result = real_acceptance(report, [{'scope': 'Development only'}], worked, 'b'*64)
    assert result['state'] == 'PASS'
    assert {row['metric'] for row in result['mathematically_inapplicable']} == {'realised_roi_pct', 'median_roi_pct'}
    report['positions'][0]['matched_basis_sol'] = None
    result = real_acceptance(report, [{'scope': 'Development only'}], worked, 'b'*64)
    assert result['state'] == 'BLOCKED' and result['mathematically_inapplicable'] == []


@pytest.mark.parametrize('value', [True, 0, 0.0, None, 'NaN', 'Infinity', '-0', '1e0', '01', '1.0'])
def test_mathematical_exception_needs_canonical_known_supporting_number(value):
    report, worked, _, _ = mathematical_acceptance_contract()
    report['metrics']['profit_sol']['value'] = value
    worked['metrics']['profit_sol']['value'] = value
    result = real_acceptance(report, [{'scope': 'Development only'}], worked, 'b'*64)
    assert result['state'] == 'BLOCKED' and result['mathematically_inapplicable'] == []


def test_empty_cohort_exception_rejects_fractional_count_and_unproved_positions():
    report, worked, components, intervals = mathematical_acceptance_contract(empty=True)
    report['metrics']['completed_positions']['value'] = '0.5'
    worked['metrics']['completed_positions']['value'] = '0.5'
    result = real_acceptance(report, [{'scope': 'Development only'}], worked, 'b'*64)
    assert result['state'] == 'BLOCKED'
    assert not any(row['metric'] in ('median_roi_pct', 'win_rate_pct', 'median_hold_hours', 'rapid_sale_pct', 'avg_buys', 'avg_sells', 'realised_roi_pct')
                   for row in result['mathematically_inapplicable'])
    report, worked, components, intervals = mathematical_acceptance_contract(empty=True)
    components['positions']['state'] = 'UNKNOWN'
    report['coverage']['metric_dependencies'] = compose_metric_decisions(components, intervals, metric_observations=report['metrics'])
    result = real_acceptance(report, [{'scope': 'Development only'}], worked, 'b'*64)
    assert result['state'] == 'BLOCKED'
    assert not any(row['metric'] == 'win_rate_pct' for row in result['mathematically_inapplicable'])


@pytest.mark.parametrize('value', [False, 0, 0.0, [], {}, None, 'NaN', 'Infinity', '0.0', '-0'])
def test_zero_cost_denominator_proof_rejects_coerced_or_malformed_basis(value):
    report, worked, _, _ = mathematical_acceptance_contract(cost='0', proceeds='1')
    report['positions'][0]['matched_basis_sol'] = value
    result = real_acceptance(report, [{'scope': 'Development only'}], worked, 'b'*64)
    assert result['state'] == 'BLOCKED' and result['mathematically_inapplicable'] == []


def test_worked_conditional_query_results_are_compared_without_wallet_promotion():
    oracle = freeze_expectations(archive([page([record()])]))
    source = next(iter(oracle['raw_input_hashes']))
    report = {'source': 'live', 'metrics': {'profit_sol': {'status': 'unknown', 'value': None}},
              'coverage': {'wallet_evidence': {'query_accounting': {
                  'conditional_observed_lot_profit_sol': '-0.00001', 'monetary_state': 'PASS'}}}}
    worked = {'version': 'genuine-wallet-worked-expectations-v1',
              'archive_sha256': oracle['archive_sha256'], 'query_accounting': {
                  'conditional_observed_lot_profit_sol': '-0.00001', 'monetary_state': 'PASS'},
              'calculations': [{'description': 'Separately added integer acquisition/exit fees for a development query lot.',
                                'source_hashes': [source]}]}
    case = verify_worked_expectations(report, worked, oracle)
    assert case['state'] == 'PASS'
    assert report['metrics']['profit_sol']['status'] == 'unknown'
    assert real_acceptance(report, [], worked, oracle['archive_sha256'])['state'] == 'BLOCKED'
    mismatch = deepcopy(worked)
    mismatch['query_accounting']['conditional_observed_lot_profit_sol'] = '10'
    with pytest.raises(AssertionError, match='conditional query result'):
        verify_worked_expectations(report, mismatch, oracle)


def selected_lot_interface():
    """Explicit normalized development events exercise the existing FIFO API.

    Separately worked integer oracle: 565135100+58918 basis, 551929943-6849
    net exit; difference -13270924 lamports. These are interface test events,
    not an authenticated raw population or an execution of the genuine corpus.
    """
    common = {'mint': 'development-lot', 'quantity_raw': '516612982765', 'decimals': 6,
              'classification': 'unknown', 'paid_by_wallet': True, 'evidence': ['a'*64]}
    rows = [{**common, 'kind': 'buy', 'timestamp': '2026-10-04T02:08:20+00:00',
             'amount_sol': '0.5651351', 'fee_sol': '0.000058918'},
            {**common, 'kind': 'sell', 'timestamp': '2026-10-04T02:17:09+00:00',
             'amount_sol': '0.551929943', 'fee_sol': '0.000006849'}]
    calculated = analyze(rows, '2026-09-04T06:00:00+00:00', '2026-10-04T06:00:00+00:00', history_complete=False)
    position = calculated['positions'][0]
    proof = {'id': position['id'], 'mint': position['mint'], 'accounts': ['development-account'],
             'monetary_state': 'PASS', 'timing_state': 'PASS', 'quantity_state': 'PASS',
             'classification_state': 'UNKNOWN', 'wallet_population_state': 'UNKNOWN', 'qualification': False,
             'acquired_raw': position['acquired_raw'], 'disposed_raw': position['sold_raw'],
             'remaining_raw': position['quantity_raw'], 'buy_count': position['buy_count'], 'sell_count': position['sell_count'],
             'conditional_basis_sol': position['basis_sol'], 'conditional_matched_basis_sol': position['matched_basis_sol'],
             'conditional_proceeds_sol': position['proceeds_sol'], 'conditional_exit_fees_sol': position['exit_fees_sol'],
             'conditional_lot_profit_sol': position['pnl_sol'], 'conditional_lot_roi_pct': position['roi_pct'],
             'observed_start': position['start'], 'observed_end': position['end'], 'conditional_hold_hours': position['hold_hours']}
    report = {'metrics': calculated['metrics'], 'coverage': {'wallet_evidence': {
        'observed_fifo_positions': calculated['positions'], 'query_accounting': {'supported_selected_lots': [proof]}}}}
    expected = {'mint': 'development-lot', 'quantity_acquired_raw': '516612982765',
                'quantity_disposed_raw': '516612982765', 'remaining_raw': '0', 'decimals': 6,
                'buy_basis_lamports': {'numerator': '565194018', 'denominator': '1'},
                'matched_disposed_basis_lamports': {'numerator': '565194018', 'denominator': '1'},
                'sell_received_quote_lamports': 551929943, 'sell_network_fee_lamports': 6849,
                'sell_net_proceeds_lamports': 551923094,
                'conditional_lot_profit_lamports': {'numerator': '-13270924', 'denominator': '1'},
                'conditional_lot_profit_sol': '-0.013270924', 'hold_seconds': 529,
                'hold_hours': {'numerator': '529', 'denominator': '3600'},
                'buy_count': 1, 'sell_count': 1, 'source_hashes': ['a'*64],
                'account': 'development-account', 'scope': 'Conditional selected lot; complete population unproved'}
    return report, expected, {'raw_input_hashes': {'a'*64: 1}}


def test_selected_loss_lot_checks_basis_net_exit_and_exact_seconds_with_unknown_wallet():
    report, expected, oracle = selected_lot_interface()
    checked = verify_selected_lots(report, [expected], oracle)
    assert checked[0]['state'] == 'PASS'
    assert checked[0]['classification'] == 'unknown'
    assert checked[0]['position_status'] == 'unresolved'
    assert checked[0]['wallet_population_promoted'] is False
    assert report['metrics']['profit_sol']['status'] == 'unknown'


@pytest.mark.parametrize('field,value', [('basis_sol', '0.5651351'), ('pnl_sol', '0.013270924'),
                                        ('exit_fees_sol', '0'), ('end', '2026-10-04T02:17:10+00:00')])
def test_selected_lot_sibling_basis_fee_sign_and_timing_mismatches_are_rejected(field, value):
    report, expected, oracle = selected_lot_interface()
    report['coverage']['wallet_evidence']['observed_fifo_positions'][0][field] = value
    with pytest.raises(AssertionError):
        verify_selected_lots(report, [expected], oracle)


def test_selected_lot_ambiguous_duplicate_is_not_silently_selected():
    report, expected, oracle = selected_lot_interface()
    positions = report['coverage']['wallet_evidence']['observed_fifo_positions']
    positions.append(deepcopy(positions[0]))
    with pytest.raises(AssertionError, match='ambiguous'):
        verify_selected_lots(report, [expected], oracle)


@pytest.mark.parametrize('field', ['monetary_state', 'timing_state', 'quantity_state'])
def test_matching_fifo_numbers_do_not_pass_with_missing_typed_dependency(field):
    report, expected, oracle = selected_lot_interface()
    proof = report['coverage']['wallet_evidence']['query_accounting']['supported_selected_lots'][0]
    proof[field] = 'UNKNOWN'
    with pytest.raises(AssertionError, match='dependency proof is incomplete'):
        verify_selected_lots(report, [expected], oracle)


def test_supported_lot_cannot_contradict_fifo_or_promote_wallet_population():
    report, expected, oracle = selected_lot_interface()
    proof = report['coverage']['wallet_evidence']['query_accounting']['supported_selected_lots'][0]
    proof['conditional_basis_sol'] = '0.5651351'
    with pytest.raises(AssertionError, match='differs from its FIFO counterpart'):
        verify_selected_lots(report, [expected], oracle)
    proof['conditional_basis_sol'] = '0.565194018'
    proof['qualification'] = True
    with pytest.raises(AssertionError, match='promotes population'):
        verify_selected_lots(report, [expected], oracle)


def test_lot_source_loss_controls_use_exact_independent_page_positions():
    lot = {'mint': 'development-lot', 'account': 'development-account', 'source_hashes': ['a'*64],
           'buy_record_index': 83, 'sell_record_index': 85}
    oracle = {'raw_observations': [{'signature': 'buy', 'response_hash': 'a'*64, 'ordinal': 83},
                                   {'signature': 'sell', 'response_hash': 'a'*64, 'ordinal': 85},
                                   {'signature': 'unrelated', 'response_hash': 'b'*64, 'ordinal': 83}]}
    manifest = {'transactions': [{'signature': 'buy', 'hash': 'c'*64}, {'signature': 'sell', 'hash': 'd'*64}]}
    controls = selected_lot_controls([lot], oracle, manifest)
    assert [(row['role'], row['signature'], row['hash']) for row in controls] == [('buy', 'buy', 'c'*64), ('sell', 'sell', 'd'*64)]
    oracle['raw_observations'].append({'signature': 'conflicting-buy', 'response_hash': 'a'*64, 'ordinal': 83})
    with pytest.raises(AssertionError, match='source identity is missing or ambiguous'):
        selected_lot_controls([lot], oracle, manifest)


def test_required_lot_source_removal_must_revoke_money_despite_unknown_global_profit():
    report, expected, oracle = selected_lot_interface()
    control = {'mint': expected['mint'], 'account': expected['account'], 'role': 'buy'}
    assert report['metrics']['profit_sol']['status'] == 'unknown'
    with pytest.raises(AssertionError, match='retained supported selected lot money'):
        verify_selected_lot_revoked(report, control)
    proof = report['coverage']['wallet_evidence']['query_accounting']['supported_selected_lots'][0]
    proof['monetary_state'] = 'UNKNOWN'
    with pytest.raises(AssertionError, match='retained a known monetary result'):
        verify_selected_lot_revoked(report, control)
    for field in ('conditional_basis_sol', 'conditional_matched_basis_sol', 'conditional_proceeds_sol',
                  'conditional_exit_fees_sol', 'conditional_lot_profit_sol', 'conditional_lot_roi_pct'):
        proof[field] = None
    assert verify_selected_lot_revoked(report, control)['missing_monetary_state'] == 'UNKNOWN'
    restored, _, _ = selected_lot_interface()
    assert verify_selected_lots(restored, [expected], oracle)[0]['state'] == 'PASS'
    report['coverage']['wallet_evidence']['query_accounting']['supported_selected_lots'] = []
    assert verify_selected_lot_revoked(report, control)['missing_monetary_state'] == 'ABSENT'
