"""Intentionally ordinary failing regressions on unmodified v0.3.3.
They assert required fail-closed behaviour. No xfail/skip marker conceals the defects.
All records are synthetic; none are evidence of actual mainnet wallet activity.
"""
import pytest
from tests.review_v033.review_helpers import (position_builder, pb, add_block, all_same_slot,
                            failed_middle, assert_unknown_hold)


@pytest.mark.parametrize('with_block_time', [False, True])
def test_r7_conflicting_same_slot_transaction_times_cannot_certify_hold(position_builder, with_block_time):
    signatures = all_same_slot(position_builder, consistent_time=False)
    add_block(position_builder, 100, signatures,
              block_time=pb.START + 3600 if with_block_time else None)
    # Same slot, but transaction blockTime values are separated by six hours.
    # Signature ordering alone cannot resolve contradictory time evidence.
    assert_unknown_hold(position_builder.derive())


def test_r7_contradictory_block_order_receipts_cannot_be_last_write_wins(position_builder):
    signatures = all_same_slot(position_builder, consistent_time=True)
    add_block(position_builder, 100, list(reversed(signatures)), block_time=pb.START + 3600)
    add_block(position_builder, 100, signatures, block_time=pb.START + 3600)
    assert_unknown_hold(position_builder.derive())


def test_r7_archived_block_time_must_agree_with_transaction_times(position_builder):
    signatures = all_same_slot(position_builder, consistent_time=True)
    add_block(position_builder, 100, signatures, block_time=pb.START + 100 * 3600)
    assert_unknown_hold(position_builder.derive())


@pytest.mark.parametrize('timestamp', [pb.END, pb.END + 3600])
@pytest.mark.parametrize('remove_raw', [False, True])
def test_r8_out_of_window_time_cannot_hide_slot_intervening_record(position_builder, timestamp, remove_raw):
    failed_middle(position_builder, timestamp=timestamp)
    if remove_raw:
        position_builder.remove_archive(position_builder.records[1]['evidence_hash'])
    # Slot 101 lies between the opening (100) and closing (102). Its contradictory
    # time or missing source cannot make it disappear before dependency checking.
    assert_unknown_hold(position_builder.derive())


def _rebuild_via_api(builder, tmp_path, monkeypatch):
    """Drive the real local API with synthetic frozen evidence and no network."""
    from copy import deepcopy
    from datetime import datetime, timezone
    import hashlib
    import sys
    from types import SimpleNamespace
    import httpx
    from fastapi.testclient import TestClient
    from scanner.app import create_app
    from scanner.config import STRICT
    from scanner.report_rebuild import freeze_report_inputs

    monkeypatch.delenv('HELIUS_API_KEY', raising=False)
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(get_keyring=lambda: object()))
    async def deny_network(*args, **kwargs):
        raise AssertionError('Independent review must not use a live provider')
    monkeypatch.setattr(httpx.AsyncClient, 'post', deny_network)
    app = create_app(tmp_path / 'app', 'synthetic-review-launch-token')
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        bootstrap = client.get('/api/bootstrap', headers={'x-launch-token': 'synthetic-review-launch-token'})
        assert bootstrap.status_code == 200
        client.headers['x-csrf-token'] = bootstrap.json()['csrf']
        store = app.state.store
        checkpoint = deepcopy(builder.cp)
        for ref in checkpoint['evidence']:
            assert store.archive(builder.store.evidence(ref['hash'])) == ref['hash']
        identifier = hashlib.sha256(f'{pb.WALLET}:{pb.START}:{pb.END}'.encode()).hexdigest()
        store.put('collector_checkpoints', identifier, checkpoint)
        window = {key: datetime.fromtimestamp(value, timezone.utc).isoformat() for key, value in pb.WINDOW.items()}
        collected = {'transactions': list(checkpoint['transactions'].values()), 'checkpoint': checkpoint,
                     'evidence': checkpoint['evidence'], 'snapshot': checkpoint['snapshot'],
                     'coverage': {'status': 'partial'}}
        original = {'id': 'synthetic-review-original', 'scan_id': 'synthetic-review-scan', 'source': 'live',
                    'address': pb.WALLET, 'created_at': '2026-10-03T00:00:00+00:00',
                    'window': window, 'preset': dict(STRICT), 'methodology': 'fifo-v3',
                    'metrics': {}, 'checks': [], 'policy': 'UNRESOLVED', 'evidence_status': 'partial',
                    'coverage': {}, 'token_risk': [], 'evidence': checkpoint['evidence'],
                    'collection_input_hash': freeze_report_inputs(store, pb.WALLET, window, collected)}
        store.put('reports', original['id'], original)
        store.put('scans', original['scan_id'], {'id': original['scan_id'], 'status': 'paused',
                  'audit_addresses': [pb.WALLET], 'window': window, 'preset': dict(STRICT), 'budget_mode': 'setup-pilot'})
        usage = client.get('/api/state').json()['usage']
        response = client.post('/api/reports/' + original['id'] + '/rebuild')
        assert response.status_code == 200, response.text
        report = client.get('/api/reports/' + response.json()['report_id']).json()
        assert store.get('reports', original['id']) == original
        assert client.get('/api/state').json()['usage'] == usage
        assert report['policy'] == 'UNRESOLVED'
        assert report['qualification']['qualified'] is False
        assert report['rebuild']['provider_requests'] == 0
        assert set(report['coverage']['history_evidence']['evidence_gates'].values()) == {'UNKNOWN'}
        return report


def test_r7_same_slot_time_conflict_must_not_survive_real_rebuild_api(position_builder, tmp_path, monkeypatch):
    signatures = all_same_slot(position_builder, consistent_time=False)
    add_block(position_builder, 100, signatures, block_time=pb.START + 3600)
    report = _rebuild_via_api(position_builder, tmp_path, monkeypatch)
    assert_unknown_hold(report['coverage']['position_evidence'])


def test_r8_future_failed_record_must_not_be_skipped_by_real_rebuild_api(position_builder, tmp_path, monkeypatch):
    failed_middle(position_builder, timestamp=pb.END)
    report = _rebuild_via_api(position_builder, tmp_path, monkeypatch)
    assert_unknown_hold(report['coverage']['position_evidence'])
