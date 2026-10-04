"""Regression checks for invalid credential headers and snapshot ordering."""
import sys
import asyncio
from datetime import date, timedelta
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from scanner.app import create_app


def test_non_ascii_secret_headers_are_denied_without_server_error(tmp_path, monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_keyring=lambda: object()))
    with TestClient(create_app(tmp_path, "launch-token"), base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/bootstrap", headers={"x-launch-token": b"\xff"}).status_code == 401
        response = client.get("/api/bootstrap", headers={"x-launch-token": "launch-token"})
        assert response.status_code == 200
        assert client.post("/api/demo", headers={"x-csrf-token": b"\xff"}).status_code == 403
        assert client.get("/api/state").json()["reports"] == []


def test_old_report_enrichment_cannot_replace_latest_snapshot(tmp_path, monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_keyring=lambda: object()))
    app = create_app(tmp_path, "launch-token")
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        client.get("/api/bootstrap", headers={"x-launch-token": "launch-token"})
        older = {"id": "older", "address": "same-wallet", "created_at": "2026-09-01T00:00:00+00:00"}
        newer = {"id": "newer", "address": "same-wallet", "created_at": "2026-09-02T00:00:00+00:00"}
        app.state.store.put("reports", "older", older)
        app.state.store.put("reports", "newer", newer)
        # Current enrichment changes updated_at while keeping the saved window.
        older["market_observations"] = [{"symbol": "TOKEN", "price_usd": "0.1"}]
        app.state.store.put("reports", "older", older)
        assert [r["id"] for r in client.get("/api/state").json()["reports"]] == ["newer", "older"]


def test_batch_progress_preserves_completed_wallet_totals(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY", "offline_test_key")
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_keyring=lambda: object()))
    from scanner import providers, collector
    class OfflineGateway:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
    calls = []
    async def collect(*args, progress=None, **kwargs):
        index = len(calls)
        calls.append(args[2])
        update = {"stage": "collected", "pages": 2 + 3 * index, "transactions": 3 + 2 * index, "credits": 4 + 3 * index, "checkpoint": {"transactions": {}}}
        progress(update)
        await asyncio.sleep(0)
        return {"transactions": [], "coverage": {}, "evidence": []}
    monkeypatch.setattr(providers, "Gateway", OfflineGateway)
    monkeypatch.setattr(collector, "collect_wallet", collect)
    app = create_app(tmp_path, "launch-token")
    app.state.store.put("configuration", "provider", {"free_plan_confirmed": True, "capability_status": "passed",
        "calibration_address": "11111111111111111111111111111111", "cycle_start": date.today().isoformat(), "cycle_end": (date.today() + timedelta(days=30)).isoformat()})
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        bootstrap = client.get("/api/bootstrap", headers={"x-launch-token": "launch-token"})
        client.headers["x-csrf-token"] = bootstrap.json()["csrf"]
        response = client.post("/api/scans", json={"addresses": ["11111111111111111111111111111111", "So11111111111111111111111111111111111111112"]})
        assert response.status_code == 200
        identifier = response.json()["scan_id"]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            scan = next(s for s in client.get("/api/state").json()["scans"] if s["id"] == identifier)
            if scan["status"] == "completed":
                break
            time.sleep(0.01)
        assert scan["status"] == "completed"
        assert scan["progress"]["pages"] == 7
        assert scan["progress"]["transactions"] == 8
        assert scan["progress"]["credits"] == 11
        assert scan["checkpoint"]["completed_totals"] == {"pages": 7, "transactions": 8, "credits": 11}
