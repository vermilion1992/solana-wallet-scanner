"""Raw query/ordinary accounting development controls; never genuine B3 proof."""
from copy import deepcopy
from datetime import timedelta
import hashlib

import pytest

from scanner.accounting import utc
from scanner.archive_input import (VERSION as ARCHIVE_VERSION, canonical_bytes, pack_bytes,
    import_archive, load_archive, decode_archive, analyze_archive, _dependency_links)
from scanner.real_coverage import derive_indexed_coverage, query_source_dependencies
from scanner.storage import Store
from scanner.wallet_evidence import derive_wallet_evidence, raw_native_dependencies
from test_indexed_source_dependencies import native, source, derive
from test_position_evidence import raw_exchange, WALLET, START, END, WINDOW
from test_wallet_evidence import record


def query(result, interval='report_period'):
    return result['query_coverage']['intervals'][interval]


def change_bounds(request, *, begin=START, end=END):
    request['params'][1]['filters']['blockTime'] = {'gte': begin, 'lt': end}


def closing_raws():
    buy = raw_exchange('development-query-buy', 111_491_820, START + 3600, 0, 100)
    sell = raw_exchange('development-query-sell', 111_491_821, START + 7200, 100, 0)
    buy['transactionIndex'], sell['transactionIndex'] = 1, 2
    return [buy, sell]


def test_terminal_original_query_derives_coverage_without_promoting_wallet_population():
    raw = native(slot=111_491_820)
    page = source([raw])
    original = deepcopy(page)
    result = derive([raw], [page])
    for name in ('report_period', 'four_weeks'):
        assert query(result, name)['state'] == 'PASS'
        assert query(result, name)['supported_record_state'] == 'PASS'
        assert query(result, name)['signatures'] == ['indexed-dev-buy']
        assert result['intervals'][name]['state'] == 'UNKNOWN'
        assert result['intervals'][name]['query_records_state'] == 'PASS'
    assert query(result, 'verification_90d')['state'] == 'UNKNOWN'
    assert result['query_coverage']['provider_contract']['historical_membership_state'] == 'UNKNOWN'
    assert query(result)['format_population_state'] == 'UNKNOWN'
    assert result['components']['historical_population']['state'] == 'UNKNOWN'
    assert result['metric_dependencies']['profit_sol']['state'] == 'UNKNOWN'
    assert result['components']['native_fee']['state'] == 'PASS'
    assert page == original
    assert result['provider_requests'] == result['credential_lookups'] == 0


@pytest.mark.parametrize('kind', ['nonterminal', 'missing-predecessor', 'selective-status', 'current-accounts', 'unsupported-record'])
def test_query_rejects_incomplete_or_filtered_inputs_without_erasing_independent_fee(kind):
    raw = native(slot=111_491_820)
    request_change = response_change = None
    if kind == 'nonterminal':
        response_change = lambda response: response['result'].update(paginationToken='111491820:2')
    elif kind == 'missing-predecessor':
        request_change = lambda request: request['params'][1].update(paginationToken='111491819:1')
    elif kind == 'selective-status':
        request_change = lambda request: request['params'][1]['filters'].update(status='succeeded')
    elif kind == 'current-accounts':
        request_change = lambda request: request['params'][1]['filters'].update(tokenAccounts='none')
    else:
        raw['version'] = 1
    page = source([raw], request_change=request_change, response_change=response_change)
    result = derive([raw], [page])
    if kind == 'unsupported-record':
        assert query(result)['query_records_state'] == 'PASS'
        assert query(result)['supported_record_state'] == 'UNKNOWN'
    else:
        assert query(result)['state'] == 'UNKNOWN'
    assert result['components']['historical_population']['state'] == 'UNKNOWN'
    if kind != 'unsupported-record':
        assert result['components']['native_fee']['state'] == 'PASS'


def test_returned_unselected_record_cannot_be_discarded_to_complete_the_query():
    selected = native(slot=111_491_820)
    omitted = native('development-query-omitted', slot=111_491_821, at=START + 4000)
    page = source([selected, omitted])
    result = derive([selected], [page])
    assert query(result)['state'] == 'UNKNOWN'
    assert any('not selected' in reason for reason in query(result)['gaps'])
    assert result['components']['native_fee']['state'] == 'PASS'
    restored = derive([selected, omitted], [page])
    assert query(restored)['state'] == 'PASS'
    assert restored['components']['historical_population']['state'] == 'UNKNOWN'


def test_selected_native_variant_can_use_the_retained_original_linked_accounting_path():
    raw = native(slot=111_491_820)
    selected_raw = deepcopy(raw)
    selected_raw['meta']['logMessages'] = ['Optional retained native representation metadata']
    page = source([raw])
    result = derive([selected_raw], [page], alternatives=[record(raw)])
    assert query(result)['state'] == 'PASS'
    assert query(result)['supported_record_state'] == 'PASS'
    assert result['components']['native_fee']['state'] == 'PASS'
    assert result['metric_dependencies']['profit_sol']['state'] == 'UNKNOWN'
    assert result['components']['historical_population']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('negative', ['missing', 'malformed', 'unsupported', 'fee-conflict', 'clock-conflict'])
def test_alternative_selection_keeps_linked_negative_facts_and_exact_restoration(negative):
    raw = native(slot=111_491_820)
    alternative = deepcopy(raw)
    alternative['meta']['logMessages'] = ['Optional native metadata']
    page = source([raw])
    original = record(raw)
    parent = derive([alternative], [page], alternatives=[original])
    bad = deepcopy(raw)
    if negative == 'missing':
        broken = {**original, 'raw': None}
    elif negative == 'malformed':
        bad['meta'] = []
        broken = {**original, 'raw': bad}
    elif negative == 'unsupported':
        bad['version'] = 1
        broken = record(bad)
    elif negative == 'fee-conflict':
        bad['meta']['fee'] += 1
        bad['meta']['postBalances'][0] -= 1
        broken = record(bad)
    else:
        bad['blockTime'] += 1
        broken = record(bad)
    child = derive([alternative], [page], alternatives=[original, broken])
    if negative in ('missing', 'malformed', 'unsupported', 'clock-conflict'):
        assert query(child)['supported_record_state'] == 'UNKNOWN'
    if negative == 'fee-conflict':
        assert child['components']['native_fee']['state'] == 'UNKNOWN'
    assert child['metric_dependencies']['profit_sol']['state'] == 'UNKNOWN'
    assert parent == derive([alternative], [page], alternatives=[original])
    assert child == derive([alternative], [page], alternatives=[broken, original])


@pytest.mark.parametrize('failure', ['original-absent', 'original-missing', 'original-hash',
                                     'selected-unlinked', 'selected-hash', 'selected-missing', 'selected-wrong-signature'])
def test_alternative_selection_needs_exact_original_and_selected_frozen_links(failure):
    from scanner.chronology_evidence import assess_chronology
    from scanner.source_consistency import assess_source_consistency
    raw = native(slot=111_491_820)
    alternative = deepcopy(raw)
    alternative['meta']['logMessages'] = ['A native alternative, not a completion declaration']
    selected = [record(alternative)]
    original = record(raw)
    linked = selected + [original]
    if failure == 'original-absent':
        linked = selected
    elif failure == 'original-missing':
        linked[-1] = {**original, 'raw': None}
    elif failure == 'original-hash':
        linked[-1] = {**original, 'evidence_hash': '0' * 64}
    elif failure == 'selected-unlinked':
        linked = [original]
    elif failure == 'selected-hash':
        selected = [{**selected[0], 'evidence_hash': '0' * 64}]
        linked = selected + [original]
    elif failure == 'selected-wrong-signature':
        alternative['transaction']['signatures'] = ['another-development-query-signature']
        chosen = record(alternative)
        selected = [{**chosen, 'signature': raw['transaction']['signatures'][0]}]
        linked = selected + [original]
    else:
        selected = [{**selected[0], 'raw': None}]
        linked = selected + [original]
    page = source([raw])
    result = derive_indexed_coverage(selected, all_records=linked, raw_sources=[page],
        wallet=WALLET, window=WINDOW,
        source_consistency=assess_source_consistency(linked, wallet=WALLET, indexed_receipts=[page]),
        chronology=assess_chronology(linked, indexed_receipts=[page]))
    assert result['intervals']['report_period']['query_records_state'] == 'UNKNOWN'
    assert result['historical_population']['state'] == 'UNKNOWN'


def test_genuine_compiled_and_native_parsed_selection_retains_every_original_query_record(tmp_path):
    from pathlib import Path
    from scanner.indexed_input import convert_indexed_archive
    content = (Path(__file__).resolve().parents[1] /
        'evidence/genuine-wallet-batch/checker-inputs/final-indexed-input.zip').read_bytes()
    store = Store(tmp_path)
    archive = import_archive(store, convert_indexed_archive(content))
    loaded = load_archive(store, archive)
    selected = loaded['records']
    linked = loaded['all_records']
    kwargs = dict(raw_sources=loaded['raw_sources'], wallet=loaded['manifest']['address'],
        window=loaded['manifest']['window'], source_consistency=loaded['consistency'],
        chronology=loaded['chronology'])
    result = derive_indexed_coverage(selected, all_records=linked, **kwargs)
    for receipt in result['intervals'].values():
        assert receipt['state'] == receipt['query_records_state'] == 'PASS'
        assert receipt['record_count'] == len(selected) == 87
        assert receipt['historical_population_state'] == 'UNKNOWN'
    assert result == derive_indexed_coverage(list(reversed(selected)),
        all_records=list(reversed(linked)), **kwargs)
    signatures = [
        '4MWN4RLXRkyN2b4rkmPPxUMzuMjCdVKzGax5gDFa7AWjudXZKUfxus5f9LLMXzfxHWtQk1CzGCrBdMtaPrMojd4U',
        '4q9Q7YB8A1ebBcyEigY4g5vPHY7B5X4qYs83epqrYsVtfZLUABxaenJYNogb69ZVPz5QGLFKQsCudg3HDep67UV7',
    ]
    for signature in signatures:
        primary = next(row for row in selected if row['signature'] == signature)
        originals = [row for row in linked if row['signature'] == signature and row['raw'] != primary['raw']]
        assert originals and all(row['raw'] is not None for row in originals)
        compiled_primary = [originals[0] if row is primary else row for row in selected]
        assert result == derive_indexed_coverage(compiled_primary, all_records=linked, **kwargs)
        missing = [{**row, 'raw': None} if row is primary else row for row in linked]
        child = derive_indexed_coverage([{**row, 'raw': None} if row is primary else row for row in selected],
            all_records=missing, **kwargs)
        assert child['intervals']['report_period']['state'] == 'UNKNOWN'
    assert result == derive_indexed_coverage(selected, all_records=linked, **kwargs)


@pytest.mark.parametrize('loss', ['missing', 'checksum-mismatch', 'unassignable-record'])
def test_linked_page_loss_or_malformed_record_revokes_query_and_exact_restoration_recovers(loss):
    raw = native(slot=111_491_820)
    page = source([raw])
    parent = derive([raw], [page])
    if loss == 'missing':
        bad = {**page, 'payload': None}
    elif loss == 'checksum-mismatch':
        bad = {**page, 'hash': 'a' * 64}
    else:
        bad = source([raw, {'transaction': {'signatures': []}}])
    child = derive([raw], [bad])
    assert query(child)['state'] == 'UNKNOWN'
    assert parent == derive([raw], [page])


def test_complete_independent_narrow_query_survives_broken_older_wide_query():
    raw = native(slot=111_491_820, at=END - 7 * 86400)
    wide = source([raw], request_change=lambda request: change_bounds(request, begin=END - 90 * 86400))
    narrow = source([raw], request_change=lambda request: change_bounds(request, begin=END - 28 * 86400))
    parent = derive([raw], [wide, narrow])
    assert all(query(parent, name)['state'] == 'PASS' for name in ('report_period', 'four_weeks', 'verification_90d'))
    broken = source([raw], request_change=lambda request: change_bounds(request, begin=END - 90 * 86400),
        response_change=lambda response: response['result'].update(paginationToken='111491820:2'))
    child = derive([raw], [broken, narrow])
    assert query(child, 'four_weeks')['state'] == 'PASS'
    assert query(child, 'report_period')['state'] == 'UNKNOWN'
    assert query(child, 'verification_90d')['state'] == 'UNKNOWN'
    assert parent == derive([raw], [narrow, wide])


def test_multiple_cursor_pages_and_input_permutations_use_every_original_record():
    buy, sell = closing_raws()
    first = source([buy], response_change=lambda response: response['result'].update(paginationToken='111491820:1'))
    last = source([sell], request_change=lambda request: request['params'][1].update(paginationToken='111491820:1'))
    forward = derive([buy, sell], [first, last])
    backward = derive([sell, buy], [last, first])
    assert query(forward)['state'] == 'PASS'
    assert query(forward)['record_count'] == 2
    assert forward == backward


def test_caller_passing_assessments_and_completion_flags_cannot_promote_raw_scope():
    raw = native(slot=111_491_820)
    page = source([raw], response_change=lambda response: response['result'].update(paginationToken='111491820:2'))
    page.update(complete=True, state='PASS', historical_owner_population=True)
    selected = [record(raw)]
    result = derive_indexed_coverage(selected, all_records=selected, raw_sources=[page], wallet=WALLET,
        window=WINDOW, source_consistency={'state': 'PASS'}, chronology={'state': 'PASS'})
    assert result['intervals']['report_period']['state'] == 'UNKNOWN'
    assert result['historical_population']['state'] == 'UNKNOWN'


def test_losing_selected_lots_use_existing_fifo_and_do_not_become_wallet_profit():
    raws = closing_raws()
    page = source(raws)
    result = derive(raws, [page])
    accounting = result['query_accounting']
    # Independent integer expectation: purchase1SOL+5000lamports, sale1SOL
    # minus5000lamports => -10000lamports.  Neither route amount is generated
    # from a production opcode/metric lookup table.
    assert accounting['conditional_observed_lot_profit_sol'] == '-0.00001'
    assert accounting['monetary_state'] == 'PASS'
    assert accounting['closed_episodes'] == 1
    assert accounting['timing_state'] == 'PASS'
    assert accounting['conditional_median_hold_hours'] == '1'
    assert accounting['qualification'] is False
    assert accounting['wallet_population_state'] == 'UNKNOWN'
    assert result['metric_dependencies']['profit_sol']['state'] == 'UNKNOWN'


def test_missing_acquisition_cost_blocks_conditional_money_while_native_fee_remains_usable():
    raws = closing_raws()
    positive = derive(raws, [source(raws)])
    assert positive['query_accounting']['monetary_state'] == 'PASS'
    sale = raws[1]
    lost = derive([sale], [source([sale])])
    assert lost['query_accounting']['conditional_observed_lot_profit_sol'] is None
    assert lost['query_accounting']['monetary_state'] == 'UNKNOWN'
    assert lost['query_accounting']['unresolved_basis_sales'] == 1
    assert lost['components']['native_fee']['state'] == 'PASS'
    assert positive == derive(raws, [source(raws)])


def test_known_fee_conflict_only_revokes_supported_record_fields_that_depend_on_it():
    raw = native(slot=111_491_820)
    alternative = deepcopy(raw)
    alternative['meta']['fee'] += 1
    alternative['meta']['postBalances'][0] -= 1
    result = derive([raw], [source([raw])], alternatives=[record(alternative)])
    assert query(result)['query_records_state'] == 'PASS'
    assert result['components']['native_fee']['state'] == 'UNKNOWN'
    assert result['query_accounting']['monetary_state'] == 'UNKNOWN'


def test_unverified_page_variant_cannot_claim_disjoint_scope_to_hide_a_linked_loss():
    raw = native(slot=111_491_820)
    good = source([raw])
    changed = source([], request_change=lambda request: change_bounds(request, begin=END + 1, end=END + 100))
    changed['hash'] = good['hash']
    selected = [record(raw)]
    result = derive_indexed_coverage(selected, all_records=selected, raw_sources=[good, changed], wallet=WALLET,
        window=WINDOW, source_consistency={'transactions': {'indexed-dev-buy': {'identity': {'state': 'PASS'}}}},
        chronology={'transactions': {'indexed-dev-buy': {'state': 'PASS', 'time_state': 'PASS'}}})
    assert result['intervals']['report_period']['state'] == 'UNKNOWN'
    assert result['historical_population']['state'] == 'UNKNOWN'


def test_empty_terminal_query_is_a_query_observation_not_a_wallet_certificate():
    page = source([])
    result = derive_indexed_coverage([], all_records=[], raw_sources=[page], wallet=WALLET,
        window=WINDOW, source_consistency={}, chronology={})
    assert result['intervals']['report_period']['state'] == 'PASS'
    assert result['intervals']['report_period']['record_count'] == 0
    assert result['historical_population']['state'] == 'UNKNOWN'


def test_fractional_end_requires_the_integer_boundary_transaction_in_query_scope():
    raw = native(slot=111_491_820, at=END)
    interior = native('fractional-interior', slot=111_491_819, at=START + 3600)
    window = {'start': (utc(START) + timedelta(microseconds=500000)).isoformat(),
              'end': (utc(END) + timedelta(microseconds=500000)).isoformat()}
    rows = [record(interior), record(raw)]
    excluding = source([interior])  # lt END excludes a required tx at END.
    bad = derive_wallet_evidence(rows, all_records=rows, wallet=WALLET, window=window,
        source_consistency={}, chronology={}, raw_sources=[excluding])
    assert query(bad)['state'] == 'UNKNOWN'
    including = source([interior, raw], request_change=lambda request: change_bounds(request, begin=START + 1, end=END + 1))
    good = derive_wallet_evidence(rows, all_records=rows, wallet=WALLET, window=window,
        source_consistency={}, chronology={}, raw_sources=[including])
    assert query(good)['state'] == 'PASS'
    assert query(good)['signatures'] == ['fractional-interior', 'indexed-dev-buy']
    assert good['components']['historical_population']['state'] == 'UNKNOWN'


def test_integer_end_proves_boundary_transaction_is_outside_even_with_wider_query():
    interior = native(slot=111_491_820, at=START + 3600)
    boundary = native('end-exclusive', slot=111_491_821, at=END)
    page = source([interior, boundary], request_change=lambda request: change_bounds(request, end=END + 1))
    result = derive([interior, boundary], [page])
    assert query(result)['state'] == 'PASS'
    assert result['intervals']['report_period']['selected_record_membership']['end-exclusive']['member'] is False


def test_duplicate_selected_records_are_idempotent_but_conflicting_versions_are_permutation_independent():
    raw = native(slot=111_491_820)
    page = source([raw])
    original = record(raw)
    kwargs = dict(raw_sources=[page], wallet=WALLET, window=WINDOW,
        source_consistency={'transactions': {'indexed-dev-buy': {'identity': {'state': 'PASS'}}}},
        chronology={'transactions': {'indexed-dev-buy': {'state': 'PASS', 'time_state': 'PASS'}}})
    once = derive_indexed_coverage([original], all_records=[original], **kwargs)
    duplicate = derive_indexed_coverage([original, deepcopy(original)], all_records=[original], **kwargs)
    assert once == duplicate
    changed = deepcopy(raw)
    changed['meta']['fee'] += 1
    alternative = record(changed)
    forward = derive_indexed_coverage([original, alternative], all_records=[original, alternative], **kwargs)
    backward = derive_indexed_coverage([alternative, original], all_records=[alternative, original], **kwargs)
    assert forward == backward
    assert forward['intervals']['report_period']['state'] == 'UNKNOWN'


@pytest.mark.parametrize('shape', ['bad-version', 'nested-wrapper', 'malformed-version'])
def test_query_affinity_is_derived_from_exact_original_bytes_under_misleading_roles(shape):
    page = source([native(slot=111_491_820)])
    if shape == 'bad-version':
        page['payload']['version'] = 'unsupported-page-version'
    elif shape == 'nested-wrapper':
        page['payload'] = {'kind': 'not-a-provider-receipt', 'data': {'nested': page['payload']}}
    else:
        page['payload']['version'] = []
    page['kind'] = 'classification'
    page['hash'] = hashlib.sha256(canonical_bytes(page['payload'])).hexdigest()
    assert query_source_dependencies([page]) == [page['hash']]


def test_affinity_inspection_budget_retains_an_uninspected_source_as_negative(monkeypatch):
    import scanner.real_coverage as module
    page = source([native(slot=111_491_820)])
    nested = {'kind': 'classification', 'payload': {'data': {'child': {'page': page['payload']}}}}
    nested['hash'] = hashlib.sha256(canonical_bytes(nested['payload'])).hexdigest()
    monkeypatch.setattr(module, 'MAX_AFFINITY_NODES', 1)
    assert query_source_dependencies([nested]) == [nested['hash']]


def archived_query_bundle(raw, sources):
    primary = record(raw)
    manifest = {'version': ARCHIVE_VERSION, 'address': WALLET, 'window': WINDOW, 'dataset': 'real',
        'transactions': [{'signature': primary['signature'], 'hash': primary['evidence_hash']}],
        'evidence': [{'kind': row['kind'], 'hash': row['hash']} for row in sources]}
    return {'manifest': manifest, 'payloads': {primary['evidence_hash']: raw,
        **{row['hash']: row['payload'] for row in sources}}}


def archive_assessment(store, manifest_hash, *, dependency_input_hash=None):
    kwargs = {'dependency_input_hash': dependency_input_hash} if dependency_input_hash else {}
    loaded = load_archive(store, manifest_hash, **kwargs)
    events, _ = decode_archive(loaded)
    result, _, receipt = analyze_archive(loaded, events)
    return loaded, result, receipt


def test_frozen_query_affinity_loss_and_restoration_preserve_original_manifest_and_independent_fees(tmp_path):
    raw = native(slot=111_491_820)
    good = source([raw])
    unrelated = native('disjoint-query-clock', slot=111_491_850, at=START + 4000)
    malformed = source([unrelated], response_change=lambda response: response['result'].update(paginationToken='malformed'))
    malformed['kind'] = 'classification'
    value = archived_query_bundle(raw, [good, malformed])
    store = Store(tmp_path)
    manifest_hash = import_archive(store, pack_bytes(value))
    original_manifest = store.evidence(manifest_hash)
    loaded, parent, receipt = archive_assessment(store, manifest_hash)
    dependency_hash = loaded['dependency_input_hash']
    inventory = store.evidence(dependency_hash)
    assert inventory['version'] == 'archive-native-dependencies-v2'
    assert inventory['query_source_hashes'] == sorted([good['hash'], malformed['hash']])
    assert receipt['query_coverage']['intervals']['report_period']['state'] == 'UNKNOWN'
    assert parent['metrics']['observed_network_fees_sol']['value'] == '0.000005'
    path = store.path / 'evidence' / f'{malformed["hash"]}.json.gz'
    original = path.read_bytes()
    path.unlink()
    _, lost, lost_receipt = archive_assessment(store, manifest_hash, dependency_input_hash=dependency_hash)
    assert lost_receipt['query_coverage']['intervals']['report_period']['state'] == 'UNKNOWN'
    assert lost['metrics']['observed_network_fees_sol']['value'] == '0.000005'
    assert store.evidence(manifest_hash) == original_manifest == value['manifest']
    path.write_bytes(original)
    _, restored, restored_receipt = archive_assessment(store, manifest_hash, dependency_input_hash=dependency_hash)
    assert restored == parent
    assert restored_receipt == receipt


def test_legacy_native_inventory_does_not_rewrite_parent_or_create_new_query_completion(tmp_path):
    raw = native(slot=111_491_820)
    value = archived_query_bundle(raw, [source([raw])])
    store = Store(tmp_path)
    manifest_hash = import_archive(store, pack_bytes(value))
    loaded, current, current_receipt = archive_assessment(store, manifest_hash)
    assert current_receipt['query_coverage']['intervals']['report_period']['state'] == 'PASS'
    legacy = {'version': 'archive-native-dependencies-v1', 'manifest_hash': manifest_hash,
              'links': loaded['dependency_input']['links']}
    legacy_hash = store.archive(legacy)
    _, old, old_receipt = archive_assessment(store, manifest_hash, dependency_input_hash=legacy_hash)
    assert old_receipt['query_coverage']['intervals']['report_period']['state'] == 'UNKNOWN'
    assert old['metrics']['observed_network_fees_sol'] == current['metrics']['observed_network_fees_sol']
    assert store.evidence(legacy_hash) == legacy


@pytest.mark.parametrize('hashes', [[{}], ['bad'], ['a' * 64, 'a' * 64], 'a' * 64])
def test_malformed_frozen_query_inventory_is_rejected_without_unhashable_crashes(hashes):
    with pytest.raises(ValueError, match='query dependency'):
        _dependency_links({'version': 'archive-native-dependencies-v2', 'manifest_hash': 'b' * 64,
            'links': [], 'query_source_hashes': hashes}, 'b' * 64)


def test_native_history_query_only_role_loss_does_not_erase_independently_proved_fee_receipts():
    from test_history_evidence import HistoryEvidenceTests
    fixture = HistoryEvidenceTests()
    fixture.setUp()
    try:
        before = fixture.derive()
        fixture.cp['evidence'].append({'kind': 'query-affinity', 'hash': 'a' * 64})
        fixture.save()
        after = fixture.derive()
        assert after['native_address_metrics'] == before['native_address_metrics']
        assert after['native_address_metrics']['periods']['report_period']['wallet_network_fees_sol']['status'] == 'known'
    finally:
        fixture.doCleanups()


@pytest.mark.parametrize('role', ['classification', 'query-affinity'])
def test_negative_query_role_cannot_hide_readable_native_fee_conflicts(role):
    raws = closing_raws()
    page = source(raws)
    alternative = deepcopy(raws[1])
    alternative['meta']['fee'] += 1
    alternative['meta']['postBalances'][0] -= 1
    native_alternative = source([alternative])
    native_alternative['kind'] = role
    result = derive(raws, [page, native_alternative])
    assert result['components']['native_fee']['state'] == 'UNKNOWN'
    assert result['query_accounting']['monetary_state'] == 'UNKNOWN'
    assert result['query_accounting']['conditional_observed_lot_profit_sol'] is None
    assert result['components']['historical_population']['state'] == 'UNKNOWN'
    restored = derive(raws, [page])
    assert restored['components']['native_fee']['state'] == 'PASS'
    assert restored['query_accounting']['conditional_observed_lot_profit_sol'] == '-0.00001'


def test_missing_negative_query_only_bytes_preserve_independent_native_and_timing_facts():
    raws = closing_raws()
    page = source(raws)
    before = derive(raws, [page])
    missing_query = {'kind': 'query-affinity', 'hash': 'a' * 64, 'payload': None}
    after = derive(raws, [page, missing_query])
    assert after['components']['native_fee'] == before['components']['native_fee']
    assert after['components']['fee_window'] == before['components']['fee_window']
    assert after['query_accounting']['conditional_observed_lot_profit_sol'] == before['query_accounting']['conditional_observed_lot_profit_sol']
    assert after['query_accounting']['conditional_median_hold_hours'] == before['query_accounting']['conditional_median_hold_hours']
    assert query(after)['state'] == 'UNKNOWN'


def test_exact_duplicate_query_declarations_do_not_consume_distinct_page_budget():
    raw = native(slot=111_491_820)
    page = source([raw])
    observed = derive([raw], [page])
    selected = [record(raw)]
    repeated = derive_indexed_coverage(selected, all_records=selected,
        raw_sources=[deepcopy(page) for _ in range(257)], wallet=WALLET, window=WINDOW,
        source_consistency=observed['source_consistency'], chronology=observed['chronology'])
    assert repeated == observed['query_coverage']


def test_original_and_frozen_query_roles_share_page_budget_but_invalid_variants_remain_dependencies(monkeypatch):
    import scanner.real_coverage as module
    monkeypatch.setattr(module, 'MAX_PAGES', 2)
    buy, sell = closing_raws()
    first = source([buy], response_change=lambda response: response['result'].update(paginationToken='111491820:1'))
    last = source([sell], request_change=lambda request: request['params'][1].update(paginationToken='111491820:1'))
    sources = [first, last, {**first, 'kind': 'query-affinity'}, {**last, 'kind': 'query-affinity'}]
    result = derive([buy, sell], sources)
    assert query(result)['state'] == 'PASS'
    assert result['query_coverage']['inspection_budget']['records'] == 2
    assert result['query_coverage']['inspection_budget']['exceeded'] is False
    bad_variant = {**last, 'payload': deepcopy(first['payload']), 'kind': 'query-affinity'}
    broken = derive([buy, sell], sources + [bad_variant])
    assert query(broken)['state'] == 'UNKNOWN'


@pytest.mark.parametrize('role', ['query-affinity', 'archive-native-dependencies'])
def test_archive_manifest_rejects_caller_supplied_internal_dependency_roles(role):
    raw = native(slot=111_491_820)
    row = source([raw])
    row['kind'] = role
    with pytest.raises(ValueError, match='derived internally'):
        pack_bytes(archived_query_bundle(raw, [row]))


def test_native_alternative_loss_retains_previously_frozen_query_affinity_dependencies(tmp_path):
    raw = native(slot=111_491_820)
    good = source([raw])
    alternate = deepcopy(raw)
    alternate['meta']['fee'] += 1
    alternate['meta']['postBalances'][0] -= 1
    misleading = source([alternate])
    misleading['kind'] = 'classification'
    value = archived_query_bundle(raw, [good, misleading])
    store = Store(tmp_path)
    manifest_hash = import_archive(store, pack_bytes(value))
    loaded, before, receipt = archive_assessment(store, manifest_hash)
    assert before['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    assert any(row['hash'] == misleading['hash'] and row['signature'] == raw['transaction']['signatures'][0]
               for row in loaded['dependency_input']['links'])
    path = store.path / 'evidence' / f'{misleading["hash"]}.json.gz'
    original = path.read_bytes()
    path.unlink()
    _, lost, lost_receipt = archive_assessment(store, manifest_hash,
        dependency_input_hash=loaded['dependency_input_hash'])
    assert lost['metrics']['observed_network_fees_sol']['status'] == 'unknown'
    assert lost_receipt['wallet_evidence']['query_accounting']['monetary_state'] == 'UNKNOWN'
    path.write_bytes(original)
    _, restored, restored_receipt = archive_assessment(store, manifest_hash,
        dependency_input_hash=loaded['dependency_input_hash'])
    assert restored == before
    assert restored_receipt == receipt


def test_direct_adapter_native_loss_replays_required_frozen_links_and_negative_signature_hints():
    raws = closing_raws()
    page = source(raws)
    alternate = deepcopy(raws[1])
    alternate['meta']['fee'] += 1
    alternate['meta']['postBalances'][0] -= 1
    row = {**source([alternate]), 'kind': 'query-affinity'}
    frozen = raw_native_dependencies([row], (), [raw['transaction']['signatures'][0] for raw in raws])
    before = derive(raws, [page, row], alternatives=frozen)
    missing = {**row, 'payload': None}
    lost = derive(raws, [page, missing], alternatives=[{**link, 'raw': None} for link in frozen])
    assert before['components']['native_fee']['state'] == lost['components']['native_fee']['state'] == 'UNKNOWN'
    assert lost['query_accounting']['monetary_state'] == 'UNKNOWN'
    hinted = {**missing, 'signature': raws[1]['transaction']['signatures'][0]}
    assert derive(raws, [page, hinted])['components']['native_fee']['state'] == 'UNKNOWN'
