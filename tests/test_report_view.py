"""Presentation views preserve conclusions and immutable full evidence offline."""
from copy import deepcopy
import hashlib
import json

import pytest

from scanner.archive_input import METHOD
from scanner.report_view import VERSION, display_view, summary_inputs, summary_view
from tests.test_copy_review_api import store_linked_cohort, store_report
from tests.test_discovery_integration_review import isolate_credentials_and_transport, session


def saved_payload(store, identifier):
    return store.db.execute("SELECT payload FROM records WHERE kind='reports' AND id=?", (identifier,)).fetchone()[0].encode()


def rich_report(store, identifier='view-report', **changes):
    digest = store.archive({'native': 'immutable source'})
    report = store_report(store, identifier, **changes)
    report['scan_id'] = 'scan-' + identifier
    report['label'] = 'Review candidate'
    report['evidence'] = [{'kind': 'transaction', 'hash': digest, 'signature': 'native-signature'}]
    report['coverage'].update(history_scope_complete=True, historical_ownership_verified=True)
    report['coverage']['history_evidence']['source_consistency'] = {'sources': [{'hash': digest}], 'checks': [{'state': 'UNKNOWN', 'reason': 'Ownership remains scoped'}], 'raw_paths': ['source.transaction.meta']}
    report['coverage']['position_evidence'].update({'positions': [{'account': 'account', 'state': 'UNKNOWN'}], 'dependencies': [digest]})
    report['coverage']['wallet_evidence'] = {'version': 'wallet-test', 'scope': {'complete': False}, 'gaps': ['missing population'], 'metric_dependencies': {'profit': [digest]}, 'components': {'fees': 'PASS'}, 'accounts': [{'bulk': 'accounts'}], 'transactions': [{'bulk': 'transactions'}], 'acquisitions': [{'bulk': 'acquisitions'}], 'observed_fifo_positions': [{'bulk': 'fifo'}], 'source_consistency': {'bulk': 'facts'}, 'chronology': {'bulk': 'clock'}}
    report['archive_input_hash'] = 'a' * 64
    report['archive_accounting'] = {'version': METHOD, 'dataset': 'real', 'scope': {'complete': False}, 'gaps': ['missing basis'], 'metric_requirements': {'profit': {'state': 'UNKNOWN', 'sources': [digest]}}, 'source_receipts': [{'hash': digest}], 'wallet_evidence': {'bulk': 'wallet'}, 'source_consistency': {'bulk': 'facts'}, 'chronology': {'bulk': 'clock'}}
    report['positions'] = [{'id': 'episode', 'mint': 'mint', 'status': 'closed', 'in_window': True, 'hold_hours': '2', 'sold_90_pct_hours': '0.01', 'first_sale_hours': '0.005', 'evidence': [digest]}]
    report['events'] = [{'kind': 'transfer_in', 'mint': 'mint', 'basis_sol': None, 'evidence': [digest]}]
    report['research'] = {'episodes': deepcopy(report['positions']), 'unresolved_basis_sales': 1, 'observed_unmatched_sales': 0, 'evidence': [digest]}
    report['reviewed_copy_checks'] = {'creator_links': {'state': 'PASS', 'reviewed': True, 'primary_evidence': True, 'evidence': [digest]}}
    for metric in report['metrics'].values():
        metric.update(unit='SOL', population='Supported scope', reason='Independent evidence', evidence=[digest], evidence_decision={'state': 'PASS', 'dependencies': [digest]})
    store.put('reports', identifier, report)
    return report


def assert_summary_equal(summary, full):
    for key in ('id', 'address', 'source', 'preset', 'window', 'methodology', 'policy', 'checks', 'qualification', 'copy_review', 'evidence', 'history_assessment', 'position_assessment', 'archive_assessment'):
        assert summary.get(key) == full.get(key), key
    for name, metric in full['metrics'].items():
        assert summary['metrics'][name] == {key: value for key, value in metric.items() if key not in ('evidence', 'evidence_decision')}


def test_display_preserves_all_visible_conclusions_sources_and_dependency_warnings_without_mutation(session):
    client, app, _ = session
    original = rich_report(app.state.store)
    before = saved_payload(app.state.store, original['id'])
    full = client.get('/api/reports/' + original['id']).json()
    display = client.get('/api/reports/' + original['id'] + '?view=display').json()
    assert display == display_view(full)
    for key in ('metrics', 'checks', 'qualification', 'copy_review', 'positions', 'events', 'evidence', 'research', 'findings', 'notes'):
        assert display.get(key) == full.get(key), key
    assert display['coverage']['history_evidence'] == full['coverage']['history_evidence']
    assert display['coverage']['position_evidence'] == full['coverage']['position_evidence']
    wallet = display['coverage']['wallet_evidence']
    assert wallet['gaps'] == full['coverage']['wallet_evidence']['gaps']
    assert wallet['metric_dependencies'] == full['coverage']['wallet_evidence']['metric_dependencies']
    assert 'transactions' not in wallet and 'source_consistency' not in display['archive_accounting']
    assert display['archive_accounting']['metric_requirements'] == full['archive_accounting']['metric_requirements']
    assert display['report_view']['view'] == 'display' and display['report_view']['version'] == VERSION
    assert 'coverage.wallet_evidence.transactions' in display['report_view']['omitted_paths']
    assert saved_payload(app.state.store, original['id']) == before
    assert app.state.store.get('reports', original['id']) == original
    assert client.get(display['report_view']['full_report_url']).json() == full
    assert client.get(display['report_view']['full_export_url']).json() == full
    assert client.get('/api/evidence/' + original['evidence'][0]['hash']).json() == {'native': 'immutable source'}
    assert client.get('/api/usage').json()['used'] == 0


@pytest.mark.parametrize('changes', [{}, {'methodology': 'fifo-v1'}, {'evidence_status': 'partial'}, {'preview': True}, {'preview': None}, {'preview': 0}])
def test_state_summary_recomputes_exact_full_qualification_review_and_candidate_progress(session, changes):
    client, app, _ = session
    original = rich_report(app.state.store, **changes)
    store_linked_cohort(app.state.store, [original])
    before = saved_payload(app.state.store, original['id'])
    full = client.get('/api/state').json()
    summary = client.get('/api/state?report_view=summary').json()
    assert_summary_equal(summary['reports'][0], full['reports'][0])
    for key in ('discovery_cohorts', 'candidate_universe', 'scans', 'usage'):
        assert summary[key] == full[key], key
    assert summary['reports'][0]['report_view']['view'] == 'summary'
    assert 'positions' not in summary['reports'][0] and 'wallet_evidence' not in summary['reports'][0]['coverage']
    assert saved_payload(app.state.store, original['id']) == before


def test_summary_sql_preserves_missing_null_and_boolean_types_and_avoids_full_list(session, monkeypatch):
    client, app, _ = session
    missing = rich_report(app.state.store, 'missing')
    missing.pop('preview', None)
    app.state.store.put('reports', missing['id'], missing)
    rich_report(app.state.store, 'false', preview=False)
    rich_report(app.state.store, 'null', preview=None)
    rich_report(app.state.store, 'true', preview=True)
    inputs = {report['id']: report for report in summary_inputs(app.state.store)}
    assert 'preview' not in inputs['missing']
    assert 'worksheet' not in inputs['missing']
    assert 'material_exit' not in inputs['missing']
    assert 'corpus_kind' not in inputs['missing']
    assert inputs['false']['preview'] is False
    assert inputs['null']['preview'] is None
    assert inputs['true']['preview'] is True
    assert [r['id'] for r in summary_inputs(app.state.store)] == [r['id'] for r in sorted(app.state.store.list('reports'), key=lambda r: r['created_at'], reverse=True)]
    original_list = app.state.store.list
    def no_full_reports(kind):
        assert kind != 'reports', 'Summary must not decode full saved reports'
        return original_list(kind)
    monkeypatch.setattr(app.state.store, 'list', no_full_reports)
    assert client.get('/api/state?report_view=summary').status_code == 200
    assert client.post('/api/presets/preview?view=summary', json={'preset': {}}).status_code == 200


@pytest.mark.parametrize('preset', [{}, {'window_days': 28}, {'verification_days': 60}])
def test_preview_full_and_summary_preserve_existing_banners_and_conditional_semantics(session, preset):
    client, app, _ = session
    original = rich_report(app.state.store)
    before = saved_payload(app.state.store, original['id'])
    saved_display = client.get('/api/reports/' + original['id']).json()
    full_response = client.post('/api/presets/preview', json={'preset': preset})
    summary_response = client.post('/api/presets/preview?view=summary', json={'preset': preset})
    assert full_response.status_code == summary_response.status_code == 200
    full, summary = full_response.json()['reports'][0], summary_response.json()['reports'][0]
    assert_summary_equal(summary, full)
    assert full['preview'] is True and full['qualification']['qualified'] is False
    for name in ('archive_assessment', 'history_assessment', 'position_assessment'):
        assert full[name] == saved_display[name]
    assert saved_payload(app.state.store, original['id']) == before


def test_invalid_views_fail_before_mutation_or_provider_dispatch(session, monkeypatch):
    client, app, _ = session
    original = rich_report(app.state.store)
    before = saved_payload(app.state.store, original['id'])
    def no_put(*args, **kwargs):
        raise AssertionError('Invalid presentation query must not mutate')
    monkeypatch.setattr(app.state.store, 'put', no_put)
    for path in ('/api/state?report_view=display', '/api/reports/view-report?view=summary'):
        assert client.get(path).status_code == 422
    assert client.post('/api/presets/preview?view=display', json={'preset': {}}).status_code == 422
    assert client.post('/api/reports/view-report/enrich?view=summary').status_code == 422
    assert client.get('/api/reports/missing?view=display').status_code == 404
    assert client.get('/api/reports/missing?view=bogus').status_code == 422
    assert saved_payload(app.state.store, original['id']) == before
    assert client.get('/api/usage').json()['used'] == 0


def test_summary_inputs_extracts_optional_subset_worksheet_without_inventing_it(session):
    _, app, _ = session
    report = rich_report(app.state.store, 'subset-row')
    report['source'] = 'mass-search'
    report['corpus_kind'] = 'SYNTHETIC'
    report['worksheet'] = {
        'total_profit_sol': '0.575',
        'sale_net_profit_sol': ['0.29', '0.2605', '0.0245'],
    }
    report['material_exit'] = {'exit_90_seconds': 30, 'final_hold_seconds': 172800}
    app.state.store.put('reports', report['id'], report)
    extracted = next(row for row in summary_inputs(app.state.store) if row['id'] == report['id'])
    assert extracted['source'] == 'mass-search'
    assert extracted['corpus_kind'] == 'SYNTHETIC'
    assert extracted['worksheet']['total_profit_sol'] == '0.575'
    assert extracted['worksheet']['sale_net_profit_sol'] == ['0.29', '0.2605', '0.0245']
    assert extracted['material_exit']['exit_90_seconds'] == 30
    assert extracted['material_exit']['final_hold_seconds'] == 172800
    other = rich_report(app.state.store, 'plain-row')
    plain = next(row for row in summary_inputs(app.state.store) if row['id'] == other['id'])
    assert 'worksheet' not in plain
    assert 'material_exit' not in plain
    assert 'corpus_kind' not in plain


def test_transient_helpers_never_edit_nested_original_and_summary_of_full_is_compact(session):
    _, app, _ = session
    original = rich_report(app.state.store)
    frozen = deepcopy(original)
    display = display_view(original)
    summary = summary_view(original)
    assert original == frozen
    assert 'wallet_evidence' not in summary['coverage']
    assert summary['coverage']['history_scope_complete'] is True
    assert display['metrics'] == original['metrics']
    assert hashlib.sha256(json.dumps(original, sort_keys=True).encode()).digest() == hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).digest()


@pytest.mark.parametrize('view', ['full', 'display'])
def test_enrich_optional_display_projects_only_response_after_same_saved_observation(session, monkeypatch, view):
    client, app, _ = session
    original = rich_report(app.state.store)
    from scanner import providers
    calls = []
    class OfflineMarket:
        def __init__(self, store):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get_token(self, mint):
            calls.append(mint)
            return {'mint': mint, 'scope': 'offline implementation control'}
    monkeypatch.setattr(providers, 'GeckoTerminal', OfflineMarket)
    result = client.post('/api/reports/' + original['id'] + '/enrich?view=' + view)
    assert result.status_code == 200
    saved = app.state.store.get('reports', original['id'])
    assert calls == ['mint']
    assert saved['metrics'] == original['metrics'] and saved['evidence'] == original['evidence']
    assert 'report_view' not in saved
    if view == 'full':
        assert result.json() == saved
    else:
        full = client.get('/api/reports/' + original['id']).json()
        assert result.json() == display_view(full)
    assert client.get('/api/usage').json()['used'] == 0
