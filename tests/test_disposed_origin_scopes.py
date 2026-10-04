"""Development raw-evidence origin scopes; these cannot close genuine B3."""
from copy import deepcopy
import json

import pytest

from scanner.metric_evidence import compose_metric_decisions
from test_position_evidence import ACCOUNT, MINT, POOL_TOKEN, POOL_WSOL, WSOL_ACCOUNT, START, END, WINDOW, address
from test_selected_cohort_observations import exchange
from test_wallet_evidence import derive, record


def sales(result, interval='report_period'):
    return result['query_accounting']['selected_cohort_observations']['intervals'][interval]['disposed_units']


def unrelated_open():
    raw = exchange('unrelated-prewindow-open', 99, START - 3600, 0, 100)
    replacements = {MINT: address(40), ACCOUNT: address(41), WSOL_ACCOUNT: address(42),
                    POOL_TOKEN: address(43), POOL_WSOL: address(44)}
    def replace(value):
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        return replacements.get(value, value) if isinstance(value, str) else value
    raw = replace(raw)
    raw['meta']['fee'] = None
    return raw


def pair():
    return [exchange('supported-buy', 100, START + 4 * 86400, 0, 100),
            exchange('supported-sale', 101, START + 5 * 86400, 100, 0, cash=1_100_000_000)]


def test_unconsumed_unknown_basis_does_not_erase_interval_disposed_origin_or_period_costs():
    raws = [unrelated_open()] + pair()
    original = deepcopy(raws)
    result = derive(raws)
    assert result['components']['observed_disposed_basis']['state'] == 'UNKNOWN'
    for interval in ('report_period', 'four_weeks', 'verification_90d'):
        row = sales(result, interval)
        assert row['cost_basis_state'] == row['monetary_state'] == 'PASS'
        assert row['conditional_matched_basis_sol'] == '1.000005'
        assert row['conditional_profit_sol'] == '0.09999'
        assert result['components']['observed_disposed_basis_by_interval'][interval]['state'] == 'PASS'
    costs = result['components']['observed_economic_roles_by_interval']
    assert costs['report_period']['state'] == costs['four_weeks']['state'] == 'PASS'
    assert costs['verification_90d']['state'] == 'UNKNOWN'
    assert result['components']['acquisition_basis_by_interval']['report_period']['state'] == 'UNKNOWN'
    assert result['metric_dependencies']['profit_sol']['state'] == 'UNKNOWN'
    assert result['query_accounting']['qualification'] is False and raws == original


def test_sale_fee_loss_blocks_profit_but_preserves_consumed_purchase_basis_and_quantity():
    raws = pair()
    raws[1]['meta']['fee'] = None
    result = derive(raws)
    row = sales(result)
    assert row['cost_basis_state'] == row['quantity_state'] == 'PASS'
    assert row['conditional_matched_basis_sol'] == '1.000005'
    assert row['monetary_state'] == 'UNKNOWN' and row['conditional_profit_sol'] is None
    assert result['transactions']['supported-buy']['network_fee']['check']['state'] == 'PASS'
    assert result['components']['observed_economic_roles_by_interval']['report_period']['state'] == 'UNKNOWN'


def test_consumed_acquisition_cost_loss_blocks_basis_and_exact_restoration_recovers():
    raws = pair()
    parent = derive(raws)
    broken = deepcopy(raws[0])
    broken['meta']['fee'] = None
    lost = derive(raws, alternatives=[record(broken)])
    assert sales(lost)['cost_basis_state'] == sales(lost)['monetary_state'] == 'UNKNOWN'
    assert sales(lost)['conditional_matched_basis_sol'] is None
    assert lost['transactions']['supported-sale']['network_fee']['check']['state'] == 'PASS'
    assert derive(raws, alternatives=[record(raws[0])]) == parent


def test_old_disposal_cost_gap_cannot_certify_90_days_or_erase_newer_scopes():
    raws = [exchange('old-buy', 98, END - 40 * 86400, 0, 100),
            exchange('old-sale', 99, END - 35 * 86400, 100, 0)] + pair()
    raws[0]['meta']['fee'] = None
    result = derive(raws)
    checks = result['components']['observed_disposed_basis_by_interval']
    assert checks['report_period']['state'] == checks['four_weeks']['state'] == 'PASS'
    assert checks['verification_90d']['state'] == 'UNKNOWN'
    assert sales(result, 'verification_90d')['candidate_sale_count'] == 2
    assert sales(result, 'report_period')['candidate_sale_count'] == 1


def test_origin_scopes_are_permutation_independent_and_reports_have_no_nonfinite_numbers():
    raws = [unrelated_open()] + pair()
    result = derive(raws)
    assert derive(list(reversed(raws))) == result
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('missing', ['four_weeks', 'verification_90d'])
def test_explicit_scoped_dependency_does_not_fall_back_to_global_pass(missing):
    from scanner.metric_evidence import METRIC_REQUIREMENTS
    check = {'state': 'PASS', 'evidence': ['a' * 64], 'reason': 'Development internal proof'}
    components = {name: deepcopy(check) for _, names in METRIC_REQUIREMENTS.values() for name in names}
    components['acquisition_basis_by_interval'] = {'report_period': deepcopy(check)}
    intervals = {name: deepcopy(check) for name in ('report_period', 'four_weeks', 'verification_90d')}
    result = compose_metric_decisions(components, intervals)
    assert result['profit_sol']['state'] == 'PASS'
    assert result['positive_weeks']['state'] == 'UNKNOWN'
    assert result['completed_positions_90d']['state'] == 'PASS'
    components['acquisition_basis_by_interval']['four_weeks'] = deepcopy(check)
    if missing == 'four_weeks':
        components['acquisition_basis_by_interval']['four_weeks']['interval'] = 'report_period'
        assert compose_metric_decisions(components, intervals)['positive_weeks']['state'] == 'UNKNOWN'
    else:
        assert compose_metric_decisions(components, intervals)['positive_weeks']['state'] == 'PASS'

