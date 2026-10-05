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
