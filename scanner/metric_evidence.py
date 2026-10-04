"""Compose metric gates from internally derived, source-linked dependencies.

This module does not validate provider records or accept imported certificates.
Callers must derive component checks from the shared raw-evidence interpreters.
A passing dependency gate is also not a numerical result: applying gates only
revokes unsupported observations and never manufactures a known value.
"""
from __future__ import annotations

from copy import deepcopy
import re
from types import MappingProxyType

from .accounting import decimal

VERSION = 'metric-evidence-v1'
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
