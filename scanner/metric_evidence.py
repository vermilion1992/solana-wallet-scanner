"""Compose metric gates from internally derived, source-linked dependencies.

This module does not validate provider records or accept imported certificates.
Callers must derive component checks from the shared raw-evidence interpreters.
A passing dependency gate is also not a numerical result: applying gates only
revokes unsupported observations and never manufactures a known value.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import re
from types import MappingProxyType

from .accounting import METHODOLOGY, decimal, utc

VERSION = 'metric-evidence-v1'
PRODUCTION_VERSION = 'production-evidence-v1'
INTERVALS = ('report_period', 'four_weeks', 'verification_90d')
_HASH = re.compile(r'^[a-f0-9]{64}$')

_EVENTS = ('historical_population', 'interval_records', 'event_ownership',
           'quantity_continuity', 'chronology', 'classification')
_FINANCIAL = _EVENTS + ('acquisition_basis', 'economic_costs')
_POSITIONS = _EVENTS + ('positions',)

# This is the single metric-to-dependency map. Interval selection is part of
# each requirement, so a report-period receipt cannot certify 28/90-day history.
METRIC_REQUIREMENTS = MappingProxyType({
    'profit_sol': ('report_period', _FINANCIAL),
    'realised_roi_pct': ('report_period', _FINANCIAL),
    'median_roi_pct': ('report_period', _FINANCIAL + ('positions',)),
    'win_rate_pct': ('report_period', _FINANCIAL + ('positions',)),
    'median_hold_hours': ('report_period', _POSITIONS),
    'completed_positions': ('report_period', _POSITIONS),
    'completed_positions_90d': ('verification_90d', _POSITIONS),
    'traded_mints': ('report_period', _EVENTS),
    'rapid_sale_pct': ('report_period', _POSITIONS),
    'avg_buys': ('report_period', _POSITIONS),
    'avg_sells': ('report_period', _POSITIONS),
    'positive_weeks': ('four_weeks', _FINANCIAL),
    'largest_contribution_pct': ('report_period', _FINANCIAL),
    'economic_pnl_sol': ('report_period', (
        'historical_population', 'interval_records', 'event_ownership',
        'quantity_continuity', 'chronology', 'boundary_inventory', 'historical_marks',
        'valued_external_flows', 'economic_costs')),
    'observed_network_fees_sol': ('report_period', (
        'selected_record_identity', 'native_fee', 'fee_window')),
})


def _check(value, interval):
    """Require an explicit usable check; empty/malformed evidence never passes."""
    if not isinstance(value, dict):
        return {'state': 'UNKNOWN', 'reason': 'Derived dependency check is missing or malformed.', 'evidence': []}
    hashes = value.get('evidence')
    evidence = sorted({item for item in hashes if isinstance(item, str) and _HASH.fullmatch(item)}) if isinstance(hashes, list) else []
    valid_hashes = (isinstance(hashes, list) and bool(hashes)
                    and all(isinstance(item, str) and _HASH.fullmatch(item) for item in hashes))
    reason = value.get('reason')
    valid_reason = reason is None or isinstance(reason, str)
    supported = (('unsupported' not in value or value['unsupported'] is False)
                 and ('supported' not in value or value['supported'] is True))
    matches_interval = value.get('interval') in (None, interval)
    usable = value.get('state') == 'PASS' and valid_hashes and valid_reason and supported and matches_interval
    if usable:
        return {'state': 'PASS', 'reason': reason, 'evidence': evidence, 'scope': deepcopy(value.get('scope'))}
    if not valid_hashes:
        reason = 'Derived dependency needs nonempty valid SHA-256 source references.'
    elif not supported:
        reason = 'Derived dependency uses an unsupported evidence contract.'
    elif not matches_interval:
        reason = 'Derived dependency belongs to a different independent interval.'
    elif not valid_reason:
        reason = 'Derived dependency reason is malformed.'
    elif not reason:
        reason = 'Derived dependency is not explicitly PASS.'
    return {'state': 'UNKNOWN', 'reason': reason, 'evidence': evidence, 'scope': deepcopy(value.get('scope'))}


def _component(components, name, interval):
    value = components.get(name) if isinstance(components, dict) else None
    if isinstance(value, dict) and 'state' not in value:
        value = value.get(interval)
    return _check(value, interval)


def _known_observation(value):
    if not isinstance(value, dict) or value.get('status') != 'known':
        return False
    number = value.get('value')
    if type(number) is int:
        return True
    if not isinstance(number, str):
        return False
    try:
        decimal(number, signed=True, max_length=512)
        return True
    except ValueError:
        return False


def accounting_intervals(interval_checks, window):
    """Bind fresh internal interval checks to the exact independent FIFO bounds.

    This function accepts derived checks, not an importable coverage declaration.
    PASS without usable original hashes and explicit covering bounds stays
    unknown. A report receipt cannot be borrowed for the 28/90-day intervals.
    """
    start, end = utc(window['start']), utc(window['end'])
    if end <= start:
        raise ValueError('A positive reporting interval is required')
    output = {}
    for name, beginning in (('report_period', start), ('four_weeks', end - timedelta(days=28)),
                            ('verification_90d', end - timedelta(days=90))):
        source = interval_checks.get(name) if isinstance(interval_checks, dict) else None
        checked = _check(source, name)
        spans = False
        try:
            spans = (isinstance(source, dict) and utc(source.get('start')) <= beginning
                     and utc(source.get('end')) >= end)
        except (ValueError, TypeError, OverflowError, OSError):
            pass
        complete = checked['state'] == 'PASS' and spans
        reason = checked['reason'] if checked['state'] != 'PASS' else (
            None if complete else 'Derived receipt has no explicit bounds spanning this independent interval.')
        output[name] = {'interval': name, 'start': beginning.isoformat(), 'end': end.isoformat(),
                        'status': 'complete' if complete else 'unknown',
                        'source': PRODUCTION_VERSION, 'evidence': checked['evidence'], 'reason': reason,
                        'scope': checked.get('scope')}
    return output


def selected_fee_checks(wallet_evidence, *, memberships=None):
    """Project fresh fee prerequisites over relevant selected records only.

    Proved outside-window records need no fee amount. Missing/boundary-crossing
    placement stays required unless an independent native check proves zero.
    These checks are internally derived, never imported trust declarations.
    """
    transactions = wallet_evidence.get('transactions', {})
    transactions = transactions if isinstance(transactions, dict) else {}
    if memberships is None:
        intervals = wallet_evidence.get('intervals', {})
        report = intervals.get('report_period', {}) if isinstance(intervals, dict) else {}
        memberships = report.get('selected_record_membership', {}) if isinstance(report, dict) else {}
    memberships = memberships if isinstance(memberships, dict) else {}
    signatures = set(transactions) | set(memberships)
    selected, window_checks = [], []
    for signature in sorted(signatures):
        member = memberships.get(signature)
        clock = _check(member, 'report_period')
        placement = isinstance(member, dict) and clock['state'] == 'PASS' and type(member.get('member')) is bool
        row = transactions.get(signature, {})
        row = row if isinstance(row, dict) else {}
        fee = row.get('network_fee', {})
        fee = fee if isinstance(fee, dict) else {}
        native = _check(fee.get('check'), 'report_period')
        zero = native['state'] == 'PASS' and fee.get('lamports') == '0'
        window_checks.append({'state': 'PASS' if placement or zero else 'UNKNOWN',
            'evidence': sorted(set(clock['evidence'] + (native['evidence'] if zero else []))),
            'reason': None if placement or zero else 'Selected nonzero fee placement remains unresolved.'})
        if not (placement and member['member'] is False):
            checks = row.get('checks', {})
            selected.append((native, _check(checks.get('identity') if isinstance(checks, dict) else None, 'report_period')))
    window_refs = sorted({digest for row in window_checks for digest in row['evidence']})
    output = {}
    for name, index in (('native_fee', 0), ('selected_record_identity', 1)):
        rows = [row[index] for row in selected]
        hashes = sorted(set(window_refs) | {digest for row in rows for digest in row['evidence']})
        known = bool(signatures) and bool(hashes) and all(row['state'] == 'PASS' for row in rows)
        output[name] = {'state': 'PASS' if known else 'UNKNOWN', 'evidence': hashes,
            'scope': 'Selected fee contributors; proved outside-window records are excluded',
            'reason': None if known else 'A relevant selected native fee or identity dependency is unresolved.'}
    window_known = bool(signatures) and bool(window_refs) and all(row['state'] == 'PASS' for row in window_checks)
    output['fee_window'] = {'state': 'PASS' if window_known else 'UNKNOWN', 'evidence': window_refs,
        'scope': 'Selected wallet-paid fee membership in the reporting window',
        'reason': None if window_known else 'A required selected nonzero fee lacks proved interval membership.'}
    return output


def compose_metric_decisions(component_checks, interval_checks, *, metric_observations=None):
    """Combine source-derived checks using independent per-metric requirements.

Components may be shared checks or maps of interval names to checks. An explicit
per-interval map never falls back to another interval. ``interval_records`` comes
only from interval_checks. Each PASS needs nonempty SHA-256 evidence references.
When supplied, numerical observations must also be known and usable. Omitting
observations produces dependency decisions only, suitable before FIFO execution.
"""
    decisions = {}
    for metric, (interval, requirements) in METRIC_REQUIREMENTS.items():
        checks = {}
        for dependency in requirements:
            if dependency == 'interval_records':
                value = interval_checks.get(interval) if isinstance(interval_checks, dict) else None
                checks[dependency] = _check(value, interval)
            else:
                checks[dependency] = _component(component_checks, dependency, interval)
        unresolved = [name for name, check in checks.items() if check['state'] != 'PASS']
        reasons = [f'{name}: {checks[name]["reason"]}' for name in unresolved]
        if metric_observations is not None:
            observation = metric_observations.get(metric) if isinstance(metric_observations, dict) else None
            if not _known_observation(observation):
                unresolved.append('metric_observation')
                reason = observation.get('reason') if isinstance(observation, dict) else None
                reasons.append('metric_observation: ' + (reason if isinstance(reason, str) and reason else 'The numerical observation remains unknown or malformed.'))
        decisions[metric] = {
            'version': VERSION, 'state': 'UNKNOWN' if unresolved else 'PASS',
            'interval': interval, 'scope': interval,
            'dependencies': list(requirements), 'unresolved_dependencies': unresolved,
            'reason': '; '.join(reasons) if reasons else 'Every required derived dependency explicitly passes.',
            'evidence': sorted({digest for check in checks.values() for digest in check['evidence']}),
            'component_scopes': {name: check.get('scope') for name, check in checks.items()},
            'checks': checks,
        }
    return decisions


def apply_metric_decisions(result, decisions):
    """Return a child calculation with dependent certainty revoked as necessary.

Passing gates retain existing supported values; they cannot promote an unknown
FIFO result. Unknown independent observations without a supplied gate are kept.
No mutation of a saved parent, source records or numerical ledger occurs.
"""
    updated = deepcopy(result)
    metrics = updated.get('metrics')
    if not isinstance(metrics, dict):
        return updated
    supplied = decisions if isinstance(decisions, dict) else {}
    coverage = updated.get('metric_coverage')
    for metric, observation in metrics.items():
        if not isinstance(observation, dict):
            continue
        # Independent observations outside the authoritative map have their own
        # source contracts and must not inherit wallet-population uncertainty.
        if metric not in METRIC_REQUIREMENTS and metric not in supplied:
            continue
        decision = supplied.get(metric)
        valid = _passing_decision(metric, decision)
        if not valid:
            previous_reason = observation.get('reason')
            reason = decision.get('reason') if isinstance(decision, dict) else None
            reason = reason if isinstance(reason, str) and reason else 'Required metric dependency decision is missing or unresolved.'
            if isinstance(previous_reason, str) and previous_reason and previous_reason != reason:
                reason += ' ' + previous_reason
            observation.update(value=None, status='unknown', reason=reason)
        elif not _known_observation(observation):
            # A malformed "known" numerical observation is not made trustworthy
            # by passing dependency receipts; preserve prior valid unknowns.
            if observation.get('status') == 'known':
                observation.update(value=None, status='unknown', reason='Numerical observation is missing or malformed.')
        if isinstance(decision, dict):
            hashes = decision.get('evidence')
            hashes = hashes if isinstance(hashes, list) else []
            prior = observation.get('evidence')
            prior = prior if isinstance(prior, list) else []
            observation['evidence'] = sorted({digest for digest in prior + hashes if isinstance(digest, str)})
            observation['evidence_decision'] = deepcopy(decision)
        if isinstance(coverage, dict) and isinstance(coverage.get(metric), dict):
            coverage[metric]['metric_status'] = observation.get('status', 'unknown')
    weekly = updated.get('weekly')
    weekly_decision = supplied.get('positive_weeks')
    if isinstance(weekly, list) and not _passing_dependencies('positive_weeks', weekly_decision):
        reason = weekly_decision.get('reason') if isinstance(weekly_decision, dict) else None
        reason = reason if isinstance(reason, str) and reason else 'Independent four-week metric dependencies remain unresolved.'
        for week in weekly:
            if isinstance(week, dict):
                week.update(profit_sol=None, status='unknown', reason=reason)
    return updated


def _passing_decision(metric, decision):
    if not isinstance(decision, dict) or decision.get('state') != 'PASS':
        return False
    return _passing_dependencies(metric, decision) and decision.get('unresolved_dependencies') == []


def _passing_dependencies(metric, decision):
    if not isinstance(decision, dict):
        return False
    if metric not in METRIC_REQUIREMENTS:
        return False
    interval, requirements = METRIC_REQUIREMENTS[metric]
    checks = decision.get('checks')
    return (decision.get('interval') == interval
            and decision.get('dependencies') == list(requirements)
            and isinstance(checks, dict)
            and all(_check(checks.get(name), interval)['state'] == 'PASS' for name in requirements))


def _gate_receipt(requirements, components, intervals, binding):
    """Combine named internally derived dependencies without boolean defaults."""
    checks = {}
    for name, interval in requirements:
        value = (intervals.get(interval) if isinstance(intervals, dict) else None) if name == 'interval_records' else None
        checks[f'{interval}:{name}'] = _check(value, interval) if name == 'interval_records' else _component(components, name, interval)
    checks['source_binding'] = binding
    unresolved = [name for name, checked in checks.items() if checked['state'] != 'PASS']
    return {'state': 'UNKNOWN' if unresolved else 'PASS', 'dependencies': list(checks),
            'unresolved_dependencies': unresolved,
            'reason': '; '.join(f'{name}: {checks[name]["reason"]}' for name in unresolved)
                if unresolved else 'Every current source-derived gate dependency explicitly passes.',
            'evidence': sorted({digest for checked in checks.values() for digest in checked['evidence']}),
            'checks': checks}


def compose_production_evidence(wallet_evidence, result, window, *, source_input_hash,
                                component_checks=None, interval_checks=None, dataset='real'):
    """Compose saved policy evidence from fresh internal raw/FIFO derivations.

    This is not an accepted source or imported certificate schema. Production
    callers recompute the wallet and FIFO receipts from frozen original bytes
    on every import/rebuild. Supplied saved PASS decisions are ignored, and a
    synthetic corpus always remains ineligible for verified real evidence.
    A gate may pass while a policy misses: a proved loss remains a loss.
    """
    from .wallet_evidence import VERSION as WALLET_METHOD
    from .source_consistency import VERSION as SOURCE_METHOD
    from .chronology_evidence import VERSION as CLOCK_METHOD
    wallet = wallet_evidence if isinstance(wallet_evidence, dict) else {}
    components = component_checks if isinstance(component_checks, dict) else wallet.get('components', {})
    supplied_intervals = interval_checks if isinstance(interval_checks, dict) else wallet.get('intervals', {})
    structured = accounting_intervals(supplied_intervals, window)
    bounded_checks = {name: {'state': 'PASS' if row['status'] == 'complete' else 'UNKNOWN',
        'interval': name, 'start': row['start'], 'end': row['end'],
        'reason': row['reason'], 'scope': row.get('scope'), 'evidence': row['evidence']}
        for name, row in structured.items()}
    methods = {'accounting': METHODOLOGY, 'wallet': WALLET_METHOD,
               'source_consistency': SOURCE_METHOD, 'chronology': CLOCK_METHOD,
               'metric': VERSION, 'production': PRODUCTION_VERSION}
    source = wallet.get('source_consistency')
    clock = wallet.get('chronology')
    reasons = []
    if dataset != 'real':
        reasons.append('Synthetic finite-world checks are development evidence and cannot qualify a real wallet.')
    if not isinstance(source_input_hash, str) or not _HASH.fullmatch(source_input_hash):
        reasons.append('A current frozen source input SHA-256 is required.')
    for label, receipt, expected in (('wallet', wallet, WALLET_METHOD),
            ('source consistency', source, SOURCE_METHOD), ('chronology', clock, CLOCK_METHOD)):
        if not isinstance(receipt, dict) or receipt.get('version') != expected:
            reasons.append(f'The {label} receipt is missing or belongs to an older interpretation.')
    if not isinstance(result, dict) or result.get('metric_domain_methodology') != METHODOLOGY:
        reasons.append('The result is not bound to the current FIFO engine interpretation.')
    if (type(wallet.get('provider_requests')) is not int or wallet.get('provider_requests') != 0
            or type(wallet.get('credential_lookups')) is not int or wallet.get('credential_lookups') != 0):
        reasons.append('The offline raw derivation needs explicit zero provider and credential calls.')
    evidence = [source_input_hash] if isinstance(source_input_hash, str) and _HASH.fullmatch(source_input_hash) else []
    binding = {'state': 'UNKNOWN' if reasons else 'PASS', 'reason': '; '.join(reasons) if reasons else
        'Fresh raw interpreters and the current FIFO result are bound to this frozen input.',
        'evidence': evidence, 'scope': 'Current in-process derivation; archive hashes alone do not authenticate mainnet'}
    per_interval = lambda dependencies, names: [(dependency, interval) for interval in names for dependency in dependencies]
    gate_requirements = {
        'history': per_interval(('historical_population', 'interval_records', 'event_ownership',
                                'quantity_continuity', 'chronology'), INTERVALS),
        'identity': [('wallet_identity', 'report_period'), ('selected_record_identity', 'report_period'),
                     ('event_ownership', 'report_period')],
        'basis': per_interval(('acquisition_basis',), ('report_period', 'four_weeks')),
        'positions': per_interval(('positions', 'event_ownership', 'quantity_continuity', 'chronology'),
                                 ('report_period', 'verification_90d')),
        'fees': per_interval(('economic_costs',), ('report_period', 'four_weeks'))
                + [('native_fee', 'report_period'), ('fee_window', 'report_period')],
        'classification': per_interval(('classification',), INTERVALS),
        'valuation': per_interval(('boundary_inventory', 'historical_marks', 'valued_external_flows',
                                  'economic_costs'), ('report_period',)),
        'findings': [('observed_economic_roles', 'report_period'), ('chronology', 'report_period'),
                     ('selected_record_identity', 'report_period')],
    }
    gates = {name: _gate_receipt(requirements, components, bounded_checks, binding)
             for name, requirements in gate_requirements.items()}
    # Source consistency/clock admission is an additional review prerequisite;
    # passing fee/identity components cannot silently clear other conflicts.
    review_known = (isinstance(source, dict) and source.get('state') == 'PASS'
                    and isinstance(clock, dict) and clock.get('state') == 'PASS')
    if not review_known:
        gates['findings']['state'] = 'UNKNOWN'
        gates['findings']['unresolved_dependencies'].append('current_source_review')
        gates['findings']['reason'] += ' Current linked-source consistency or chronology review remains unresolved.'
    metrics = result.get('metrics') if isinstance(result, dict) else None
    decisions = compose_metric_decisions(components, bounded_checks, metric_observations=metrics)
    dependency_decisions = compose_metric_decisions(components, bounded_checks)
    observation_states = {}
    for metric in METRIC_REQUIREMENTS:
        if metric == 'observed_network_fees_sol':
            continue  # Independent selected observations do not certify a wallet.
        observation = metrics.get(metric) if isinstance(metrics, dict) else None
        domain = _undefined_domain(metric, result)
        supported = dependency_decisions[metric]['state'] == 'PASS'
        observation_states[metric] = {'state': 'known' if supported and _known_observation(observation) else
            'undefined' if supported and domain else 'unknown',
            'reason': None if supported and _known_observation(observation) else
                domain if supported and domain else decisions[metric]['reason']}
    all_gates = all(row['state'] == 'PASS' for row in gates.values())
    observations_supported = all(row['state'] in ('known', 'undefined') for row in observation_states.values())
    verified = all_gates and observations_supported
    return {'version': PRODUCTION_VERSION, 'state': 'PASS' if verified else 'UNKNOWN',
        'evidence_status': 'verified' if verified else 'partial',
        'source_input_hash': source_input_hash, 'source_binding': binding, 'methods': methods,
        'gate_receipts': gates, 'evidence_gates': {name: row['state'] for name, row in gates.items()},
        'metric_observations': observation_states, 'metric_decisions': decisions,
        'interval_checks': bounded_checks, 'accounting_intervals': structured,
        'unresolved_gates': [name for name, row in gates.items() if row['state'] != 'PASS'],
        'unresolved_metrics': [name for name, row in observation_states.items() if row['state'] == 'unknown'],
        'scope': 'Current source-supported accounting and saved policy evidence; no copy-trading safety certification',
        'provider_requests': 0, 'credential_lookups': 0}


def _undefined_domain(metric, result):
    """Accept only explicit current-engine arithmetic domains, never free zeroes."""
    if not isinstance(result, dict) or result.get('metric_domain_methodology') != METHODOLOGY:
        return None
    domains, metrics = result.get('metric_domains'), result.get('metrics')
    domain = domains.get(metric) if isinstance(domains, dict) else None
    observation = metrics.get(metric) if isinstance(metrics, dict) else None
    if (not isinstance(domain, dict) or domain.get('status') != 'undefined'
            or not isinstance(observation, dict) or observation.get('status') != 'unknown'
            or observation.get('value') is not None or not isinstance(domain.get('witness'), dict)):
        return None
    reason, witness = domain.get('reason_code'), domain['witness']
    profit = metrics.get('profit_sol')
    count = metrics.get('completed_positions')
    if metric == 'largest_contribution_pct' and reason == 'nonpositive_period_profit':
        if (_known_observation(profit) and witness.get('profit_sol') == profit['value']
                and decimal(str(profit['value']), signed=True, max_length=512) <= 0):
            return reason
    if metric == 'realised_roi_pct' and reason == 'zero_disposed_basis':
        if (_known_observation(profit) and witness.get('profit_sol') == profit['value']
                and witness.get('disposed_basis_sol') == '0'):
            return reason
    if metric in ('median_roi_pct', 'win_rate_pct', 'median_hold_hours', 'rapid_sale_pct', 'avg_buys', 'avg_sells'):
        if reason == 'empty_completed_cohort' and _known_observation(count) and str(count['value']) == '0' and witness.get('completed_positions') == '0':
            return reason
    if metric == 'median_roi_pct' and reason == 'zero_episode_basis':
        positions = result.get('positions')
        ids = witness.get('zero_basis_episode_ids')
        if not isinstance(ids, list) or not ids or not isinstance(positions, list):
            return None
        zero = {row.get('id') for row in positions if isinstance(row, dict) and row.get('status') == 'closed'
                and row.get('in_window') is True and row.get('matched_basis_sol') == '0'}
        if all(isinstance(identifier, str) for identifier in ids) and set(ids) == zero:
            return reason
    return None
