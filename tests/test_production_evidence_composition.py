"""Internal development contracts only; fabricated checks cannot close B3."""
from copy import deepcopy
from datetime import timedelta

import pytest

from scanner.accounting import METHODOLOGY, analyze, evaluate_policy, utc
from scanner.chronology_evidence import VERSION as CLOCK_VERSION
from scanner.metric_evidence import (INTERVALS, METRIC_REQUIREMENTS,
    accounting_intervals, apply_metric_decisions, compose_metric_decisions,
    compose_production_evidence, selected_fee_checks)
from scanner.config import STRICT
from scanner.source_consistency import VERSION as SOURCE_VERSION
from scanner.wallet_evidence import VERSION as WALLET_VERSION
from tests.test_discovery_integration_review import session, isolate_credentials_and_transport

WINDOW = {'start': '2026-01-01T00:00:00Z', 'end': '2026-01-31T00:00:00Z'}
HASH = 'a' * 64


def passing(**extra):
    return {'state': 'PASS', 'evidence': [HASH], 'scope': 'Synthetic internal interface test only', **extra}


def internal_wallet():
    names = {n for _, requirements in METRIC_REQUIREMENTS.values() for n in requirements}
    names |= {'wallet_identity', 'observed_economic_roles'}
    names.discard('interval_records')
    end = utc(WINDOW['end'])
    intervals = {name: passing(interval=name, start=begin.isoformat(), end=end.isoformat())
        for name, begin in [('report_period', utc(WINDOW['start'])),
                            ('four_weeks', end-timedelta(days=28)),
                            ('verification_90d', end-timedelta(days=90))]}
    return {'version': WALLET_VERSION, 'components': {n: passing() for n in names},
            'intervals': intervals, 'provider_requests': 0, 'credential_lookups': 0,
            'source_consistency': {'version': SOURCE_VERSION, 'state': 'PASS'},
            'chronology': {'version': CLOCK_VERSION, 'state': 'PASS'}}


def calculation(proceeds='2', cost='1'):
    common = {'mint': 'development', 'quantity_raw': '100', 'decimals': 0,
              'classification': 'meme', 'fee_sol': '0', 'paid_by_wallet': True,
              'evidence': [HASH], 'path': 'synthetic/swap'}
    events = [{**common, 'kind': 'buy', 'timestamp': '2026-01-05T00:00:00Z', 'order': 1,
               'signature': 'development-buy', 'amount_sol': cost},
              {**common, 'kind': 'sell', 'timestamp': '2026-01-05T06:00:00Z', 'order': 2,
               'signature': 'development-sell', 'amount_sol': proceeds}]
    result = analyze(events, **{'start': WINDOW['start'], 'end': WINDOW['end']},
        opening_equity='10', closing_equity='11', external_deposits='0', external_withdrawals='0')
    result['metrics']['observed_network_fees_sol'] = {'status': 'known', 'value': '0', 'evidence': [HASH]}
    return result


def compose(wallet=None, result=None, **kwargs):
    return compose_production_evidence(internal_wallet() if wallet is None else wallet,
        calculation() if result is None else result, WINDOW, source_input_hash=kwargs.pop('source_input_hash', HASH), **kwargs)


def test_positive_internal_gate_composition_is_numerically_bound_and_nonmutating():
    wallet, result = internal_wallet(), calculation()
    before = deepcopy((wallet, result))
    receipt = compose(wallet, result)
    assert receipt['state'] == 'PASS'
    assert receipt['evidence_status'] == 'verified'
    assert set(receipt['evidence_gates'].values()) == {'PASS'}
    assert all(v['state'] == 'known' for v in receipt['metric_observations'].values())
    assert (wallet, result) == before


@pytest.mark.parametrize('name', ['report_period', 'four_weeks', 'verification_90d'])
@pytest.mark.parametrize('variant', ['absent', 'wrong-name', 'short', 'missing-bounds', 'bad-hash'])
def test_independent_interval_checks_cannot_borrow_bounds_or_evidence(name, variant):
    wallet = internal_wallet()
    row = wallet['intervals'][name]
    if variant == 'absent':
        del wallet['intervals'][name]
    elif variant == 'wrong-name':
        row['interval'] = next(n for n in INTERVALS if n != name)
    elif variant == 'short':
        row['start'] = '2026-01-30T00:00:00Z'
    elif variant == 'missing-bounds':
        del row['end']
    else:
        row['evidence'] = ['not-a-hash']
    intervals = accounting_intervals(wallet['intervals'], WINDOW)
    assert intervals[name]['status'] == 'unknown'
    assert all(intervals[n]['status'] == 'complete' for n in INTERVALS if n != name)
    receipt = compose(wallet)
    assert receipt['state'] == 'UNKNOWN'
    expected = {'report_period': 'profit_sol', 'four_weeks': 'positive_weeks',
                'verification_90d': 'completed_positions_90d'}[name]
    assert receipt['metric_observations'][expected]['state'] == 'unknown'


@pytest.mark.parametrize('component,gate', [('wallet_identity','identity'), ('acquisition_basis','basis'),
    ('economic_costs','fees'), ('historical_population','history'), ('positions','positions'),
    ('classification','classification'), ('historical_marks','valuation'), ('observed_economic_roles','findings')])
def test_required_component_loss_restoration_revokes_only_dependencies(component, gate):
    wallet, result = internal_wallet(), calculation()
    baseline = compose(wallet, result)
    old = wallet['components'].pop(component)
    lost = compose(wallet, result)
    assert lost['state'] == 'UNKNOWN'
    assert lost['evidence_gates'][gate] == 'UNKNOWN'
    if component == 'historical_marks':
        assert lost['metric_observations']['profit_sol']['state'] == 'known'
        assert lost['metric_observations']['economic_pnl_sol']['state'] == 'unknown'
    if component == 'acquisition_basis':
        assert lost['metric_observations']['median_hold_hours']['state'] == 'known'
        assert lost['metric_observations']['completed_positions']['state'] == 'known'
        assert lost['metric_observations']['profit_sol']['state'] == 'unknown'
    wallet['components'][component] = old
    assert compose(wallet, result) == baseline


@pytest.mark.parametrize('variant', ['synthetic', 'old-wallet', 'old-source', 'old-clock', 'old-fifo',
                                  'bool-provider', 'missing-calls', 'bad-binding'])
def test_stale_synthetic_or_malformed_binding_cannot_verify(variant):
    wallet, result = internal_wallet(), calculation()
    kwargs = {}
    if variant == 'synthetic': kwargs['dataset'] = 'synthetic'
    elif variant == 'old-wallet': wallet['version'] = 'wallet-raw-evidence-v6'
    elif variant == 'old-source': wallet['source_consistency']['version'] = 'old'
    elif variant == 'old-clock': wallet['chronology']['version'] = 'old'
    elif variant == 'old-fifo': result['metric_domain_methodology'] = 'fifo-v3'
    elif variant == 'bool-provider': wallet['provider_requests'] = False
    elif variant == 'missing-calls': del wallet['credential_lookups']
    else: kwargs['source_input_hash'] = 'unbound'
    receipt = compose(wallet, result, **kwargs)
    assert receipt['state'] == 'UNKNOWN'
    assert receipt['source_binding']['state'] == 'UNKNOWN'
    assert set(receipt['evidence_gates'].values()) == {'UNKNOWN'}


@pytest.mark.parametrize('proceeds', ['0', '1'])
def test_known_loss_or_breakeven_can_be_evidence_supported_without_invented_percentage(proceeds):
    result = calculation(proceeds)
    receipt = compose(result=result)
    assert receipt['state'] == 'PASS'
    assert receipt['metric_observations']['largest_contribution_pct']['state'] == 'undefined'
    assert result['metrics']['largest_contribution_pct']['value'] is None
    assert evaluate_policy(result['metrics'], STRICT, evidence_verified=receipt['evidence_gates'])['policy'] == 'MISS'


def test_unknown_numbers_do_not_become_known_from_passing_components_or_caller_domain():
    wallet, result = internal_wallet(), calculation()
    result['metrics']['profit_sol'].update(status='unknown', value=None)
    result['metric_domains']['profit_sol'] = {'status':'undefined', 'reason_code':'nonpositive_period_profit',
                                             'witness': {'profit_sol':'0'}}
    receipt = compose(wallet, result)
    assert receipt['state'] == 'UNKNOWN'
    assert receipt['metric_observations']['profit_sol']['state'] == 'unknown'
    gated = apply_metric_decisions(result, compose_metric_decisions(wallet['components'], wallet['intervals']))
    assert gated['metrics']['profit_sol']['value'] is None


def test_wallet_freshness_annotation_survives_summary_and_display_without_parent_mutation(session):
    from tests.test_report_view import rich_report, saved_payload
    client, app, _ = session
    store = app.state.store
    parent = rich_report(store)
    parent['coverage']['wallet_evidence']['version'] = WALLET_VERSION
    store.put('reports', parent['id'], parent)
    original = saved_payload(store, parent['id'])
    full = client.get('/api/state').json()
    compact = client.get('/api/state?report_view=summary').json()
    display = client.get('/api/reports/'+parent['id']+'?view=display').json()
    assert full['wallet_evidence_methodology'] == compact['wallet_evidence_methodology'] == WALLET_VERSION
    assert full['reports'][0]['wallet_assessment'] == compact['reports'][0]['wallet_assessment'] == display['wallet_assessment']
    assert 'wallet_evidence' not in compact['reports'][0]['coverage']
    assert saved_payload(store, parent['id']) == original


def test_real_adapter_partial_interval_with_null_passing_population_reason_stays_structured(tmp_path, monkeypatch):
    from scanner.archive_input import (VERSION, canonical_bytes, pack_bytes,
        import_archive, load_archive, analyze_archive)
    from scanner.storage import Store
    import scanner.wallet_evidence as adapter
    from test_selected_cohort_observations import exchange
    from test_position_evidence import START, WINDOW as RAW_WINDOW, WALLET
    import hashlib
    raw = exchange('development-partial', 100, START+3600, 0, 100)
    digest = hashlib.sha256(canonical_bytes(raw)).hexdigest()
    manifest = {'version':VERSION, 'address':WALLET, 'window':RAW_WINDOW, 'dataset':'real',
                'transactions':[{'signature':'development-partial', 'hash':digest}], 'evidence':[]}
    store = Store(tmp_path/'data')
    identifier = import_archive(store, pack_bytes({'manifest':manifest, 'payloads':{digest:raw}}), reserve_bytes=0)
    loaded = load_archive(store, identifier)
    original = adapter.derive_wallet_evidence
    def partial(*args, **kwargs):
        receipt = original(*args, **kwargs)
        receipt['components']['historical_population'] = passing(reason=None)
        receipt['query_coverage']['intervals']['report_period']['gaps'].append(None)
        return receipt
    monkeypatch.setattr(adapter, 'derive_wallet_evidence', partial)
    result, _, receipt = analyze_archive(loaded, [])
    assert receipt['quantity_population_state'] == 'UNKNOWN'
    assert receipt['production_evidence']['evidence_status'] == 'partial'
    assert receipt['gaps'] and all(isinstance(reason, str) for reason in receipt['gaps'])
    assert result['metrics']['profit_sol']['status'] == 'unknown'


def test_native_saved_rebuild_exposes_raw_selected_fee_independently_of_wallet_profit(session):
    from tests.test_report_rebuild import seed_report
    from tests.test_indexed_report_integration import rebuild
    from scanner.accounting import canonical
    from decimal import Decimal
    client, app, _ = session
    parent, _ = seed_report(app.state.store)
    inputs = app.state.store.evidence(parent['collection_input_hash'])
    raw = app.state.store.evidence(inputs['transactions'][0]['evidence_hash'])
    at = utc(raw['blockTime'])
    keys = raw['transaction']['message']['accountKeys']
    payer = keys[0]['pubkey'] if isinstance(keys[0], dict) else keys[0]
    expected_lamports = raw['meta']['fee'] if payer == parent['address'] and utc(parent['window']['start']) <= at < utc(parent['window']['end']) else 0
    before = client.get('/api/export/reports/'+parent['id']+'.json').content
    child = rebuild(client, parent)
    fee = child['metrics']['observed_network_fees_sol']
    assert fee['status'] == 'known'
    assert fee['value'] == canonical(Decimal(expected_lamports)/Decimal(1_000_000_000))
    assert child['metrics']['profit_sol']['status'] == 'unknown'
    assert child['coverage']['production_evidence']['evidence_status'] == 'partial'
    assert client.get('/api/export/reports/'+parent['id']+'.json').content == before


def test_outside_window_unresolved_fee_does_not_erase_proved_current_fees(session):
    from tests.test_report_rebuild import seed_report
    from scanner.report_rebuild import freeze_report_inputs
    from tests.test_indexed_report_integration import rebuild
    client, app, _ = session
    store = app.state.store
    parent, collected = seed_report(store)
    inside = deepcopy(collected['transactions'][0])
    outside = deepcopy(inside)
    signature = 'development-older-fee-missing'
    outside['signature'] = signature
    outside['raw']['transaction']['signatures'][0] = signature
    outside['raw']['slot'] -= 1000
    outside['raw']['blockTime'] = int((utc(parent['window']['start'])-timedelta(days=1)).timestamp())
    outside['raw']['meta']['fee'] = None
    outside['evidence_hash'] = store.archive(outside['raw'])
    collected['transactions'].append(outside)
    ref = {'kind':'transaction', 'signature':signature, 'hash':outside['evidence_hash']}
    collected['evidence'].append(ref)
    collected['checkpoint']['transactions'][signature] = {'signature':signature,'evidence_hash':outside['evidence_hash']}
    collected['checkpoint']['evidence'].append(ref)
    parent['collection_input_hash'] = freeze_report_inputs(store,parent['address'],parent['window'],collected)
    store.put('reports',parent['id'],parent)
    child = rebuild(client,parent)
    current = child['research']['wallet_fees_paid_sol']
    assert current is not None, child['research']
    metric = child['metrics']['observed_network_fees_sol']
    assert metric['status'] == 'known', {'expected_from_current_raw_projection':current,'actual':metric}
    assert metric['value'] == current


@pytest.mark.parametrize('membership,lamports,expected', [
    ({'state':'PASS','member':False}, None, 'PASS'),
    ({'state':'UNKNOWN','member':None}, '5', 'UNKNOWN'),
    ({'state':'UNKNOWN','member':None}, '0', 'PASS'),
    ({'state':'PASS','member':1}, '5', 'UNKNOWN'),
    ({'state':'PASS','member':False,'evidence':[]}, '5', 'UNKNOWN'),
])
def test_fee_projection_requires_explicit_membership_or_independently_proved_zero(membership, lamports, expected):
    rows = {'one': {'network_fee': {'lamports':lamports,
                    'check':passing() if lamports is not None else passing(state='UNKNOWN')},
                    'checks':{'identity':passing()}}}
    receipt = {'transactions':rows, 'intervals':{'report_period':{
        'selected_record_membership':{'one':{'evidence':[HASH], **membership}}}}}
    before = deepcopy(receipt)
    projected = selected_fee_checks(receipt)
    assert projected['fee_window']['state'] == expected
    assert receipt == before
    if membership.get('member') is False and lamports is None:
        assert projected['native_fee']['state'] == projected['selected_record_identity']['state'] == 'PASS'


def test_empty_fee_source_population_cannot_supply_a_free_zero_or_pass():
    assert all(row['state'] == 'UNKNOWN' for row in selected_fee_checks({}).values())
