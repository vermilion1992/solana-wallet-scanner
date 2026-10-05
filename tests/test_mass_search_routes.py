"""Mass-search HTTP routes preserve session, CSRF and quota guards."""
from datetime import date, timedelta
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from scanner.app import create_app
from scanner.config import LIMITS
from scanner.mass_search.universe import synthetic_address
from scanner.storage import Store

BASE_URL = "http://127.0.0.1:8765"
LAUNCH_TOKEN = "test-private-launch-token"


@pytest.fixture(autouse=True)
def no_keyring_or_network(monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_keyring=lambda: object()))
    import httpx

    async def forbidden(*args, **kwargs):
        raise AssertionError("Mass-search route tests must not contact a live provider")

    monkeypatch.setattr(httpx.AsyncClient, "post", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "get", forbidden)


@pytest.fixture
def session(tmp_path):
    app = create_app(tmp_path / "data", LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as client:
        response = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        assert response.status_code == 200
        client.headers["x-csrf-token"] = response.json()["csrf"]
        yield client, app, tmp_path / "data"


def test_anonymous_and_csrf_guards_cover_new_endpoints(session):
    client, app, _ = session
    raw = TestClient(app, base_url=BASE_URL)
    assert raw.get("/api/mass-search/runs").status_code == 401
    assert raw.post("/api/mass-search/runs", json={}).status_code == 401
    client.headers["x-csrf-token"] = "wrong"
    assert client.post("/api/mass-search/vertical-slice", json={}).status_code == 403


def test_state_does_not_embed_bulk_rows_and_preserves_legacy_caps(session):
    client, _, data_dir = session
    state = client.get("/api/state").json()
    assert state["mass_search"]["legacy_candidate_cap"] == LIMITS["candidate_cap"]
    assert state["mass_search"]["bulk_capacity"] == 10000
    assert "candidates" not in state["mass_search"]
    created = client.post("/api/mass-search/runs", json={"corpus_kind": "SYNTHETIC"}).json()
    pages = [[{"address": synthetic_address(i), "realized_pnl": str(i), "trade_count": 21} for i in range(30)]]
    acquired = client.post(f"/api/mass-search/runs/{created['run_id']}/acquire", json={"pages": pages, "target_unique": 30})
    assert acquired.status_code == 200
    assert acquired.json()["unique_candidates"] == 30
    refreshed = client.get("/api/state").json()
    universe = refreshed.get("candidate_universe") or {}
    listed = universe.get("candidates") or universe.get("rows") or []
    assert len(listed) <= LIMITS["candidate_cap"]
    store = Store(data_dir)
    try:
        assert store.usage("helius", "setup-pilot", 200)["used"] == 0
    finally:
        store.close()


def test_vertical_slice_export_and_cached_refilter(session):
    client, _, _ = session
    slice_result = client.post("/api/mass-search/vertical-slice", json={"corpus_kind": "SYNTHETIC"})
    assert slice_result.status_code == 200
    body = slice_result.json()
    assert body["run"]["corpus_kind"] == "SYNTHETIC"
    assert body["reconstruction"]["worksheet"]["total_profit_sol"] == "0.575"
    run_id = body["run"]["run_id"]
    exported = client.get(f"/api/mass-search/runs/{run_id}/export")
    assert exported.status_code == 200
    assert exported.json()["run"]["run_id"] == run_id
    assert exported.json()["reports"][0]["worksheet"]["total_profit_sol"] == "0.575"
    refiltered = client.post(f"/api/mass-search/runs/{run_id}/refilter", json={})
    assert refiltered.status_code == 200
    assert refiltered.json()["parent_run_id"] == run_id
    live = client.post(f"/api/mass-search/runs/{run_id}/acquire", json={"live": True, "pages": [[]]})
    assert live.status_code == 409


def test_live_run_without_authorization_is_blocked(session):
    client, _, _ = session
    response = client.post("/api/mass-search/runs", json={"corpus_kind": "GENUINE_LIVE", "plan": {"live_enabled": True}})
    assert response.status_code == 409
    capability = client.get("/api/mass-search/capability").json()
    assert capability["sources"]["birdeye-traders"]["role_decision"] == "NO_GO"
    assert capability["setup_pilot"]["cap"] == 200


def test_slice_report_can_be_reopened_and_exported(session):
    client, _, data_dir = session
    body = client.post("/api/mass-search/vertical-slice", json={"corpus_kind": "SYNTHETIC"}).json()
    run_id = body["run"]["run_id"]
    report_id = body["reconstruction"]["report"]["id"]
    listed = client.get("/api/state?report_view=summary").json()["reports"]
    assert any(row["id"] == report_id and row["source"] == "mass-search" for row in listed)
    opened = client.get(f"/api/reports/{report_id}?view=display")
    assert opened.status_code == 200
    assert opened.json()["id"] == report_id
    assert opened.json()["source"] == "mass-search"
    assert opened.json()["policy"] == "UNRESOLVED"
    assert opened.json()["worksheet"]["total_profit_sol"] == "0.575"
    assert opened.json()["material_exit"]["exit_90_seconds"] == 30
    assert opened.json()["material_exit"]["final_hold_seconds"] == 172800
    assert opened.json()["metrics"].get("profit_sol", {}).get("status") != "known"
    linked = client.get(f"/api/mass-search/runs/{run_id}/reports").json()["reports"]
    assert linked[0]["id"] == report_id
    page = client.get(f"/api/mass-search/runs/{run_id}/candidates?stage=triage&limit=50").json()
    assert page["items"][0]["report_id"] == report_id
    assert page["items"][0]["subset_pnl"]["value"] == "0.575"
    assert page["items"][0]["material_exit_t90"]["value"] == "30"
    exported = client.get(f"/api/mass-search/runs/{run_id}/export")
    assert 'attachment; filename="mass-search-' in exported.headers["content-disposition"]
    exported_body = exported.json()
    assert exported_body["reports"][0]["id"] == report_id
    assert exported_body["reports"][0]["worksheet"]["total_profit_sol"] == "0.575"
    assert exported_body["reports"][0]["material_exit"]["exit_90_seconds"] == 30
    assert exported_body["reports"][0]["material_exit"]["final_hold_seconds"] == 172800
    assert exported_body["reports"][0]["policy"] == "UNRESOLVED"
    report_export = client.get(f"/api/export/reports/{report_id}.json")
    assert report_export.status_code == 200
    assert report_export.json()["id"] == report_id
    assert report_export.json()["worksheet"]["total_profit_sol"] == "0.575"
    assert report_export.json()["policy"] == "UNRESOLVED"
    restarted = Store(data_dir)
    try:
        saved = restarted.get("reports", report_id)
        assert saved["id"] == report_id
        assert saved["worksheet"]["total_profit_sol"] == "0.575"
        assert saved["material_exit"]["final_hold_seconds"] == 172800
        assert saved["policy"] == "UNRESOLVED"
        assert restarted.usage("helius", "setup-pilot", 200)["used"] == 0
    finally:
        restarted.close()


def test_display_reopen_after_process_restart_keeps_independent_worksheet(tmp_path):
    data_dir = tmp_path / "data"
    first = create_app(data_dir, LAUNCH_TOKEN)
    with TestClient(first, base_url=BASE_URL) as client:
        boot = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        client.headers["x-csrf-token"] = boot.json()["csrf"]
        body = client.post("/api/mass-search/vertical-slice", json={"corpus_kind": "SYNTHETIC"}).json()
        report_id = body["reconstruction"]["report"]["id"]
        run_id = body["run"]["run_id"]
    second = create_app(data_dir, LAUNCH_TOKEN)
    with TestClient(second, base_url=BASE_URL) as client:
        boot = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        client.headers["x-csrf-token"] = boot.json()["csrf"]
        listed = next(row for row in client.get("/api/state?report_view=summary").json()["reports"] if row["id"] == report_id)
        assert listed["source"] == "mass-search"
        assert listed["policy"] == "UNRESOLVED"
        assert listed.get("worksheet") is None
        opened = client.get(f"/api/reports/{report_id}?view=display").json()
        assert opened["worksheet"]["total_profit_sol"] == "0.575"
        assert opened["material_exit"]["exit_90_seconds"] == 30
        assert opened["material_exit"]["final_hold_seconds"] == 172800
        assert opened["policy"] == "UNRESOLVED"
        assert opened["metrics"].get("profit_sol", {}).get("status") != "known"
        assert client.get(f"/api/mass-search/runs/{run_id}/reports").json()["reports"][0]["worksheet"]["total_profit_sol"] == "0.575"


def test_pause_resume_cancel_and_offline_acquire_guards(session):
    client, _, _ = session
    created = client.post("/api/mass-search/runs", json={"corpus_kind": "SYNTHETIC"}).json()
    run_id = created["run_id"]
    assert client.post(f"/api/mass-search/runs/{run_id}/acquire", json={}).status_code == 400
    pages = [[{"address": synthetic_address(3), "realized_pnl": "4", "trade_count": 22}]]
    assert client.post(f"/api/mass-search/runs/{run_id}/acquire", json={"pages": pages, "target_unique": 1}).status_code == 200
    paused = client.post(f"/api/mass-search/runs/{run_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED"
    resumed = client.post(f"/api/mass-search/runs/{run_id}/resume")
    assert resumed.json()["status"] == "RUNNING"
    cancelled = client.post(f"/api/mass-search/runs/{run_id}/cancel")
    assert cancelled.json()["status"] == "CANCELLED"
    assert client.get("/api/mass-search/access-blocker").json()["birdeye"]["max_additional_spend_usd"] == "0"


def test_empty_run_pages_and_stage_filter_stay_local(session):
    client, _, _ = session
    created = client.post("/api/mass-search/runs", json={"corpus_kind": "SYNTHETIC"}).json()
    run_id = created["run_id"]
    empty = client.get(f"/api/mass-search/runs/{run_id}/candidates?stage=triage&limit=50")
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert client.get(f"/api/mass-search/runs/{run_id}/reports").json()["reports"] == []
    pages = [[{"address": synthetic_address(i), "realized_pnl": str(100 - i), "trade_count": 22} for i in range(60)]]
    acquired = client.post(f"/api/mass-search/runs/{run_id}/acquire", json={"pages": pages, "target_unique": 60})
    assert acquired.status_code == 200
    assert client.post(f"/api/mass-search/runs/{run_id}/stages/triage").status_code == 200
    first = client.get(f"/api/mass-search/runs/{run_id}/candidates?stage=triage&limit=50").json()
    assert len(first["items"]) == 50
    assert first["next_cursor"]
    second = client.get(
        f"/api/mass-search/runs/{run_id}/candidates?stage=triage&limit=50&cursor={first['next_cursor']}"
    ).json()
    assert len(second["items"]) == 10
    reconstruct = client.get(f"/api/mass-search/runs/{run_id}/candidates?stage=reconstruct&limit=50").json()
    assert reconstruct["items"] == []
    assert client.get(f"/api/mass-search/runs/{run_id}/reports").json()["reports"] == []
