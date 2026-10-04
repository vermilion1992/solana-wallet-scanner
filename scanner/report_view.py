"""Optional transient report views; immutable reports/exports retain full proof trees."""
from __future__ import annotations

import json
from urllib.parse import quote

VERSION = 'report-view-v1'

# These exact inputs are sufficient for the existing qualification/copy-review
# and candidate-progress functions. They are extracted before decoration; the
# transient summary never substitutes for saved reconstruction evidence.
_SUMMARY_TOP = (
    'id', 'scan_id', 'discovery_cohort_id', 'address', 'label', 'source', 'created_at',
    'window', 'methodology', 'policy', 'evidence_status', 'preset', 'preview', 'preview_reason',
    'metrics', 'metric_intervals', 'metric_coverage', 'checks', 'counts', 'counts_population',
    'notes', 'findings', 'evidence', 'positions', 'events', 'research', 'token_risk',
    'reviewed_copy_checks', 'archive_input_hash', 'archive_dependency_input_hash',
    'collection_input_hash', 'rebuilt_from', 'previous_methodology', 'previous_history_methodology',
    'previous_position_methodology', 'rebuild', 'market_observation_scope', 'market_observation_note',
    'history_assessment', 'position_assessment', 'archive_assessment', 'wallet_assessment',
)
_SUMMARY_NESTED = (
    ('coverage', 'history_evidence', 'version'),
    ('coverage', 'position_evidence', 'version'),
    ('coverage', 'wallet_evidence', 'version'),
    ('coverage', 'history_scope_complete'),
    ('coverage', 'historical_ownership_verified'),
    ('archive_accounting', 'version'),
)
_SUMMARY_PATHS = tuple((key,) for key in _SUMMARY_TOP) + _SUMMARY_NESTED
_SUMMARY_OMIT = ('positions', 'events', 'research', 'token_risk', 'reviewed_copy_checks', 'archive_accounting')
_WALLET_DETAIL = ('accounts', 'transactions', 'acquisitions', 'observed_fifo_positions', 'source_consistency', 'chronology', 'accounting_events')
_ARCHIVE_DUPLICATES = ('wallet_evidence', 'source_consistency', 'chronology')


def _assign(value, path, item):
    for key in path[:-1]:
        value = value.setdefault(key, {})
    value[path[-1]] = item


def summary_inputs(store):
    """Read fixed JSON paths without loading each full report into Python.

    Missing values remain missing, explicit null remains null, and booleans
    retain their type. This is a read-only query against immutable saved rows.
    """
    fields, parameters = [], []
    for path in _SUMMARY_PATHS:
        json_path = '$.' + '.'.join(path)
        fields.extend(('json_extract(payload, ?)', 'json_type(payload, ?)'))
        parameters.extend((json_path, json_path))
    query = ('SELECT ' + ','.join(fields) + " FROM records WHERE kind='reports' "
             "ORDER BY json_extract(payload, '$.created_at') DESC,updated_at DESC,id")
    with store.lock:
        rows = store.db.execute(query, parameters).fetchall()
    reports = []
    for row in rows:
        result = {}
        for index, path in enumerate(_SUMMARY_PATHS):
            value, kind = row[index*2], row[index*2+1]
            if kind is None:
                continue
            if kind in ('object', 'array'):
                value = json.loads(value)
            elif kind in ('true', 'false'):
                value = kind == 'true'
            _assign(result, path, value)
        reports.append(result)
    return reports


def _metadata(report, view, omitted):
    identifier = str(report.get('id', ''))
    escaped = quote(identifier, safe='')
    return {'version': VERSION, 'view': view, 'source_report_id': report.get('id'),
            'omitted_paths': sorted(set(omitted)),
            'full_report_url': f'/api/reports/{escaped}',
            'full_export_url': f'/api/export/reports/{escaped}.json',
            'scope': 'Transient presentation projection; saved report and source evidence remain unchanged. '
                     'Omitted proof trees remain available in the full report and JSON export.'}


def summary_view(decorated):
    """Keep list/compare/qualification semantics; omit explicitly labelled detail."""
    result, omitted = dict(decorated), ['coverage.detail']
    for key in _SUMMARY_OMIT:
        if key in result:
            result.pop(key)
            omitted.append(key)
    coverage = result.get('coverage')
    if isinstance(coverage, dict):
        compact_coverage = {}
        for path in _SUMMARY_NESTED:
            if path[0] != 'coverage' or path[1] == 'wallet_evidence':
                continue
            current = coverage
            for key in path[1:]:
                if not isinstance(current, dict) or key not in current:
                    break
                current = current[key]
            else:
                _assign(compact_coverage, path[1:], current)
        result['coverage'] = compact_coverage
    metrics = result.get('metrics')
    if isinstance(metrics, dict):
        compact = {}
        for name, metric in metrics.items():
            if isinstance(metric, dict):
                compact[name] = {key: value for key, value in metric.items() if key not in ('evidence', 'evidence_decision')}
                omitted.extend(f'metrics.{name}.{key}' for key in ('evidence', 'evidence_decision') if key in metric)
            else:
                compact[name] = metric
        result['metrics'] = compact
    result['report_view'] = _metadata(result, 'summary', omitted)
    return result


def display_view(decorated):
    """Retain every structured UI metric/check/source receipt and dependency.

    Only repeated adapter trees are removed from the transport. Historical
    source consistency and account-position UI evidence remain exact.
    """
    result, omitted = dict(decorated), []
    archive = result.get('archive_accounting')
    if isinstance(archive, dict):
        result['archive_accounting'] = {key: value for key, value in archive.items() if key not in _ARCHIVE_DUPLICATES}
        omitted.extend(f'archive_accounting.{key}' for key in _ARCHIVE_DUPLICATES if key in archive)
    coverage = result.get('coverage')
    if isinstance(coverage, dict):
        coverage = dict(coverage)
        wallet = coverage.get('wallet_evidence')
        if isinstance(wallet, dict):
            coverage['wallet_evidence'] = {key: value for key, value in wallet.items() if key not in _WALLET_DETAIL}
            omitted.extend(f'coverage.wallet_evidence.{key}' for key in _WALLET_DETAIL if key in wallet)
        result['coverage'] = coverage
    result['report_view'] = _metadata(result, 'display', omitted)
    return result


def validate_view(value, supported):
    if value not in supported:
        raise ValueError('Unsupported report view; select ' + ' or '.join(supported))
    return value
