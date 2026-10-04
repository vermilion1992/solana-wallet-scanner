"""Independent R10 metric-specific controls; every archived record is synthetic.

No RPC, keys, signed mainnet provenance, or wallet-wide completeness is supplied.
The uploaded 32 tests are retained separately in tests/review_v035.
"""
from copy import deepcopy

import pytest

from scanner.history_evidence import derive_history_evidence
from scanner.providers import TOKEN_2022_PROGRAM
from scanner.source_consistency import assess_source_consistency
from scanner.report_rebuild import freeze_report_inputs, load_report_inputs
from scanner.storage import EvidenceError
from tests.review_v033.review_helpers import position_builder, assert_unknown_hold, pb
from tests.review_v033.review_helpers import all_same_slot, add_block
from tests.review_v033.test_v033_regressions import _rebuild_via_api
from tests.test_review_v034_independent import write_account_page, remap_account


def link_alternative(builder, index, change, *, reverse=False):
    alternative = deepcopy(builder.raws[index])
    change(alternative)
    digest = builder.store.archive(alternative)
    assert digest != builder.records[index]['evidence_hash']
    builder.cp['evidence'].append({'kind': 'transaction', 'hash': digest,
                                 'signature': builder.records[index]['signature']})
    if reverse:
        builder.cp['evidence'].reverse()
    builder.persist()
    return digest


def target_rows(raw):
    return [row for name in ('preTokenBalances', 'postTokenBalances')
            for row in raw['meta'][name] if row['accountIndex'] == 1]


def alter_fact(raw, field):
    rows = target_rows(raw)
    if field in ('owner', 'mint', 'decimals', 'program'):
        key, value = {'owner': ('owner', pb.address(40)), 'mint': ('mint', pb.address(41)),
                      'decimals': ('decimals', 7), 'program': ('programId', TOKEN_2022_PROGRAM)}[field]
        for row in rows:
            if field == 'decimals':
                row['uiTokenAmount'][key] = value
            else:
                row[key] = value
    elif field in ('pre_quantity', 'post_quantity'):
        row = rows[0 if field == 'pre_quantity' else 1]
        row['uiTokenAmount']['amount'] = str(int(row['uiTokenAmount']['amount']) + 1)
    elif field == 'execution':
        raw['meta']['err'] = {'InstructionError': [0, 'Custom']}
    elif field == 'missing_owner':
        rows[0].pop('owner')
    elif field == 'missing_quantity':
        rows[0]['uiTokenAmount'].pop('amount')
    elif field == 'duplicate_boundary':
        raw['meta']['preTokenBalances'].append(deepcopy(rows[0]))
    elif field == 'boolean_index':
        rows[0]['accountIndex'] = True
    elif field == 'duplicate_account_key':
        raw['transaction']['message']['accountKeys'].append(pb.ACCOUNT)
    elif field == 'missing_cpi':
        raw['meta'].pop('innerInstructions')
    elif field == 'duplicate_cpi_group':
        raw['meta']['innerInstructions'].append(deepcopy(raw['meta']['innerInstructions'][0]))
    elif field == 'parsed_quantity':
        instruction = raw['meta']['innerInstructions'][0]['instructions'][0]
        token = instruction['parsed']['info']['tokenAmount']
        token['amount'] = str(int(token['amount']) + 1)
    elif field == 'opaque_operation':
        raw['meta']['innerInstructions'][0]['instructions'][0] = {
            'programId': pb.address(43), 'accounts': [pb.ACCOUNT], 'data': '1111'}
    elif field == 'malformed_cpi_groups':
        raw['meta']['innerInstructions'] = 1
    elif field == 'malformed_program_annotation':
        rows[0]['programId'] = [pb.TOKEN_PROGRAM]
    elif field == 'malformed_instruction_program':
        raw['meta']['innerInstructions'][0]['instructions'][0]['programId'] = [pb.TOKEN_PROGRAM]
    else:
        raise AssertionError(field)


def observed_native(builder, *, records=None):
    history = derive_history_evidence(builder.store, pb.WALLET, pb.WINDOW,
                                     checkpoint=builder.cp,
                                     collected={'transactions': builder.records if records is None else records})
    assert set(history['evidence_gates'].values()) == {'UNKNOWN'}
    return history['native_address_metrics']['observed']


def observed_fees(builder, *, records=None):
    return observed_native(builder, records=records)['wallet_network_fees_sol']


def known_hold(builder):
    result = builder.derive()
    assert result['counts'] == {'known_closed': 1, 'open': 0, 'unresolved': 0}
    assert result['positions'][0]['hold_hours']['value'] == '6'
    return result


@pytest.mark.parametrize('index', [0, 2])
@pytest.mark.parametrize('field', [
    'owner', 'mint', 'decimals', 'program', 'pre_quantity', 'post_quantity', 'execution',
    'missing_owner', 'missing_quantity', 'duplicate_boundary', 'boolean_index',
    'duplicate_account_key', 'missing_cpi', 'duplicate_cpi_group', 'parsed_quantity', 'opaque_operation',
    'malformed_cpi_groups', 'malformed_program_annotation', 'malformed_instruction_program',
])
def test_each_required_alternative_fact_revokes_the_dependent_hold(position_builder, index, field):
    builder = position_builder
    digest = link_alternative(builder, index, lambda raw: alter_fact(raw, field))
    result = builder.derive()
    assert_unknown_hold(result)
    position = result['positions'][0]
    assert digest in position['sources']
    assert position['stages']['hold']['state'] == 'UNKNOWN'
    for stage in ('source_consistency', 'quantities', 'continuity'):
        assert position['stages'][stage]['state'] == 'UNKNOWN'
        assert digest in position['stages'][stage]['evidence']
    assert position['stages']['opening_zero' if index == 0 else 'strict_zero']['state'] == 'UNKNOWN'
    if field in ('owner', 'mint', 'decimals', 'program', 'pre_quantity', 'post_quantity',
                 'missing_owner', 'missing_quantity', 'duplicate_boundary', 'boolean_index',
                 'missing_cpi', 'duplicate_cpi_group', 'parsed_quantity', 'opaque_operation'):
        # Inventory/route ambiguity does not change the exact three selected
        # native fee endpoints or create a fourth fee-bearing transaction.
        observed = observed_fees(builder)
        assert observed['status'] == 'known'
        assert observed['record_count'] == 3 and observed['value'] == '0.000015'


@pytest.mark.parametrize('reverse', [False, True])
def test_middle_absolute_inventory_offset_revokes_continuity_despite_same_transfer(position_builder, reverse):
    builder = position_builder
    def offset(raw):
        for row in target_rows(raw):
            row['uiTokenAmount']['amount'] = str(int(row['uiTokenAmount']['amount']) + 200)
    digest = link_alternative(builder, 1, offset, reverse=reverse)
    result = builder.derive()
    assert_unknown_hold(result)
    assert digest in result['positions'][0]['hold_hours']['evidence']
    assert result['positions'][0]['stages']['continuity']['state'] == 'UNKNOWN'
    assert observed_fees(builder)['value'] == '0.000015'


def agreeing_rendering(raw, kind):
    if kind == 'ui_metadata':
        for row in target_rows(raw):
            row['uiTokenAmount'].update(uiAmount=None, uiAmountString='0.00000000000000000001')
    elif kind == 'program_inferred':
        for row in target_rows(raw):
            row.pop('programId')
    elif kind == 'account_key_order':
        message, meta = raw['transaction']['message'], raw['meta']
        order = [0, 3, 4, 1, 2]  # payer stays first; rendered addresses and units agree.
        message['accountKeys'] = [message['accountKeys'][index] for index in order]
        for name in ('preBalances', 'postBalances'):
            meta[name] = [meta[name][index] for index in order]
        for name in ('preTokenBalances', 'postTokenBalances'):
            for row in meta[name]:
                row['accountIndex'] = order.index(row['accountIndex'])
            meta[name].reverse()
    elif kind == 'another_accounts_inventory':
        for name in ('preTokenBalances', 'postTokenBalances'):
            row = next(row for row in raw['meta'][name] if row['accountIndex'] == 3)
            row['uiTokenAmount']['amount'] = str(int(row['uiTokenAmount']['amount']) + 7)
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize('index', [0, 2])
@pytest.mark.parametrize('kind', ['ui_metadata', 'program_inferred', 'account_key_order', 'another_accounts_inventory'])
def test_metric_equivalent_distinct_archives_preserve_the_named_account_fact(position_builder, index, kind):
    builder = position_builder
    digest = link_alternative(builder, index, lambda raw: agreeing_rendering(raw, kind), reverse=True)
    result = known_hold(builder)
    assert digest in result['positions'][0]['sources']
    assert observed_fees(builder)['value'] == '0.000015'


@pytest.mark.parametrize('reverse', [False, True])
def test_semantic_conflict_is_independent_of_which_raw_hash_was_selected(position_builder, reverse):
    builder = position_builder
    digest = link_alternative(builder, 0, lambda raw: alter_fact(raw, 'owner'), reverse=reverse)
    # Select the contradictory record while retaining both native source links;
    # changing the preferred source cannot resolve disagreement.
    builder.records[0]['evidence_hash'] = digest
    builder.cp['transactions'][builder.records[0]['signature']]['evidence_hash'] = digest
    builder.persist()
    assert_unknown_hold(builder.derive())


@pytest.mark.parametrize('index', [0, 2])
def test_removing_semantically_agreeing_alternative_revokes_its_required_verification(position_builder, index):
    builder = position_builder
    digest = link_alternative(builder, index, lambda raw: raw['meta'].update(logMessages=[]))
    known_hold(builder)
    builder.remove_archive(digest)
    assert_unknown_hold(builder.derive())
    # A linked missing native archive also leaves its payer/endpoints unverifiable.
    # Removing it cannot choose the preferred native facts either.
    observed = observed_native(builder)
    assert all(metric['status'] == 'unknown' and metric['value'] is None for metric in observed.values())


def alter_native(raw, kind):
    meta = raw['meta']
    if kind == 'fee_and_endpoint':
        meta['fee'] += 5000
        meta['postBalances'][0] -= 5000
    elif kind == 'fee_only':
        meta['fee'] += 5000
        meta['postBalances'][3] -= 5000  # keep the wallet endpoint unchanged.
    elif kind == 'endpoint_only':
        meta['postBalances'][0] -= 1000
        meta['postBalances'][3] += 1000
    elif kind == 'payer_only':
        message = raw['transaction']['message']
        order = [3, 1, 2, 0, 4]
        message['accountKeys'] = [message['accountKeys'][index] for index in order]
        for name in ('preBalances', 'postBalances'):
            meta[name] = [meta[name][index] for index in order]
        for name in ('preTokenBalances', 'postTokenBalances'):
            for row in meta[name]:
                row['accountIndex'] = order.index(row['accountIndex'])
    elif kind == 'invalid_fee':
        meta['fee'] = False
    elif kind == 'invalid_conservation':
        meta['fee'] += 5000
    elif kind == 'unrelated_endpoint':
        meta['preBalances'][3] += 7
        meta['postBalances'][3] += 7
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize('index', [0, 2])
@pytest.mark.parametrize('kind,fee_known,endpoint_known', [
    ('fee_and_endpoint', False, False), ('fee_only', False, True),
    ('endpoint_only', True, False), ('payer_only', False, True),
    ('invalid_fee', False, False), ('invalid_conservation', False, False),
    ('unrelated_endpoint', True, True),
])
def test_native_alternative_facts_revoke_only_the_dependent_observed_group(
        position_builder, index, kind, fee_known, endpoint_known):
    builder = position_builder
    digest = link_alternative(builder, index, lambda raw: alter_native(raw, kind), reverse=True)
    # No native price/fee/payer role is a dependency of this quantity-only hold.
    known_hold(builder)
    observed = observed_native(builder)
    for metric, known, value in [('wallet_network_fees_sol', fee_known, '0.000015'),
                                 ('native_wallet_delta_sol', endpoint_known, '-0.000015')]:
        assert observed[metric]['record_count'] == 3
        assert observed[metric]['status'] == ('known' if known else 'unknown')
        assert observed[metric]['value'] == (value if known else None)
        assert digest in observed[metric]['evidence']


@pytest.mark.parametrize('index', [0, 2])
def test_native_conflict_on_unselected_signature_does_not_expand_or_poison_exact_observed_set(
        position_builder, index):
    builder = position_builder
    link_alternative(builder, index, lambda raw: alter_native(raw, 'fee_and_endpoint'))
    records = [record for number, record in enumerate(builder.records) if number != index]
    observed = observed_native(builder, records=records)
    assert observed['wallet_network_fees_sol']['status'] == 'known'
    assert observed['wallet_network_fees_sol']['value'] == '0.00001'
    assert observed['native_wallet_delta_sol']['status'] == 'known'
    assert observed['native_wallet_delta_sol']['value'] == '-0.00001'
    assert all(metric['record_count'] == 2 for metric in observed.values())


def add_second_account(builder):
    second = pb.address(44)
    original = deepcopy(builder.raws)
    additional = [remap_account(raw, second) for raw in [
        pb.raw_exchange('second-account-open', 200, pb.START + 10 * 3600, 0, 100),
        pb.raw_exchange('second-account-close', 202, pb.START + 16 * 3600, 100, 0),
    ]]
    builder.raws.extend(additional)
    builder.seed()
    write_account_page(builder, pb.ACCOUNT,
                       [pb.entry(raw['transaction']['signatures'][0], raw) for raw in original])
    initial = builder.store.evidence(builder.pages[pb.ACCOUNT][0])
    initial.update(address=second, result=list(reversed([
        pb.entry(raw['transaction']['signatures'][0], raw) for raw in additional])))
    terminal = builder.store.evidence(builder.pages[pb.ACCOUNT][1])
    terminal['address'] = second
    terminal['params']['before'] = 'second-account-open'
    first_hash, last_hash = builder.store.archive(initial), builder.store.archive(terminal)
    builder.cp['evidence'].extend([{'kind': 'signature-page', 'hash': first_hash},
                                  {'kind': 'signature-page', 'hash': last_hash}])
    builder.cp['accounts'][second] = {
        'address': second, 'origin': 'event-time token-balance owner',
        'ownership_evidence': builder.cp['transactions']['second-account-open']['evidence_hash'],
        'cursor': 'second-account-open', 'terminal': 'empty signature page', 'terminal_evidence': last_hash,
    }
    builder.cp['account_scope']['included_account_count'] = 3
    builder.persist()
    return second


@pytest.mark.parametrize('reverse', [False, True])
def test_another_wallet_owned_accounts_semantic_dispute_keeps_independent_episode_and_fees(
        position_builder, reverse):
    builder = position_builder
    second = add_second_account(builder)
    baseline = builder.derive()
    assert baseline['counts']['known_closed'] == 2
    def offset(raw):
        for row in target_rows(raw):
            row['uiTokenAmount']['amount'] = str(int(row['uiTokenAmount']['amount']) + 200)
    digest = link_alternative(builder, 3, offset, reverse=reverse)
    result = builder.derive()
    by_account = {position['account']: position for position in result['positions']}
    assert result['counts']['known_closed'] == 1
    assert by_account[pb.ACCOUNT]['hold_hours']['value'] == '6'
    assert by_account[second]['hold_hours']['value'] is None
    assert digest in by_account[second]['sources']
    assert digest not in by_account[pb.ACCOUNT]['sources']
    observed = observed_fees(builder)
    assert observed['status'] == 'known' and observed['value'] == '0.000025'
    assert observed['record_count'] == 5


@pytest.mark.parametrize('field,status', [('pre_quantity', 'conflict'), ('missing_owner', 'missing')])
def test_reconciliation_exposes_exact_field_sources_and_distinguishes_missing_from_contradiction(
        position_builder, field, status):
    builder = position_builder
    digest = link_alternative(builder, 0, lambda raw: alter_fact(raw, field))
    history = derive_history_evidence(builder.store, pb.WALLET, pb.WINDOW,
                                     checkpoint=builder.cp, collected={'transactions': builder.records})
    signature = builder.records[0]['signature']
    account = history['source_consistency']['transactions'][signature]['accounts'][pb.ACCOUNT]
    check = account['checks']['pre_quantity' if field == 'pre_quantity' else 'owner']
    assert check['status'] == status and check['state'] == 'UNKNOWN'
    assert {fact['hash'] for fact in check['facts']} == {digest, builder.records[0]['evidence_hash']}
    assert any(fact['hash'] == digest and fact['path'].startswith('meta.preTokenBalances.') for fact in check['facts'])
    assert any(row['field'] == check['field'] for row in account['conflicts' if status == 'conflict' else 'missing'])
    assert account['checks']['native_identity']['state'] == 'PASS'
    assert history['source_consistency']['state'] == 'UNKNOWN'


def test_shared_reconciliation_is_deterministic_for_the_same_source_set(position_builder):
    builder = position_builder
    link_alternative(builder, 0, lambda raw: alter_fact(raw, 'pre_quantity'))
    link_alternative(builder, 2, lambda raw: raw['meta'].update(logMessages=[]))
    records = [{'signature': ref['signature'], 'evidence_hash': ref['hash'],
                'raw': builder.store.evidence(ref['hash'])}
               for ref in builder.cp['evidence'] if ref.get('kind') == 'transaction']
    forward = assess_source_consistency(records, accounts=(pb.ACCOUNT,), wallet=pb.WALLET)
    backward = assess_source_consistency(list(reversed(records)), accounts=(pb.ACCOUNT,), wallet=pb.WALLET)
    assert forward == backward


@pytest.mark.parametrize('index', [0, 2])
def test_agreeing_semantic_alternative_cannot_mask_proven_saved_index_conflict(position_builder, index):
    builder = position_builder
    signatures = all_same_slot(builder, consistent_time=True)
    add_block(builder, 100, signatures, block_time=pb.START + 3600)
    link_alternative(builder, index, lambda raw: raw['meta'].update(logMessages=[]))
    builder.records[index]['transaction_index'] = 99
    result = builder.derive()
    assert_unknown_hold(result)
    assert result['positions'][0]['stages']['source_consistency']['state'] == 'PASS'
    assert result['positions'][0]['stages']['chronology']['state'] == 'UNKNOWN'
    assert observed_fees(builder)['value'] == '0.000015'
    collected = {'transactions': builder.records, 'checkpoint': builder.cp,
                 'evidence': builder.cp['evidence'], 'snapshot': builder.cp['snapshot']}
    report = {'source': 'live', 'address': pb.WALLET, 'window': pb.WINDOW,
              'collection_input_hash': freeze_report_inputs(builder.store, pb.WALLET, pb.WINDOW, collected)}
    with pytest.raises(EvidenceError, match='ordering conflicts'):
        load_report_inputs(builder.store, report)


@pytest.mark.parametrize('transaction', [None, [], 'malformed'], ids=['null', 'list', 'string'])
@pytest.mark.parametrize('via_api', [False, True], ids=['direct', 'api'])
def test_malformed_alternative_transaction_is_retained_and_revokes_dependent_metrics(
        position_builder, transaction, via_api, tmp_path, monkeypatch):
    builder = position_builder
    digest = link_alternative(builder, 0, lambda raw: raw.update(transaction=transaction))
    if via_api:
        # The actual API helper also asserts immutable parent, unchanged usage,
        # zero provider requests, UNKNOWN wallet gates and false qualification.
        report = _rebuild_via_api(builder, tmp_path, monkeypatch)
        result = report['coverage']['position_evidence']
        native = report['coverage']['history_evidence']['native_address_metrics']['observed']
    else:
        result = builder.derive()
        native = observed_native(builder)
    assert_unknown_hold(result)
    assert digest in result['positions'][0]['sources']
    assert result['positions'][0]['stages']['source_consistency']['state'] == 'UNKNOWN'
    assert all(metric['status'] == 'unknown' and metric['value'] is None for metric in native.values())
