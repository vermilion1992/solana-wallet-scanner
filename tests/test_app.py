"""Local HTTP security, offline controls and durable worker integration."""
import asyncio
import csv
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
import io
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from scanner.app import allowed_request_host, create_app
from scanner.config import LIMITS, STRICT
from scanner.storage import Store

BASE_URL = "http://127.0.0.1:8765"
LAUNCH_TOKEN = "test-private-launch-token"
ADDRESS = "11111111111111111111111111111111"
KEY = "test_api_key_must_stay_backend_123456"


@pytest.fixture(autouse=True)
def no_keyring_or_network(monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    # An unapproved credential backend must cause a session-only fallback.
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_keyring=lambda: object()))
    import httpx
    async def forbidden_post(*args, **kwargs):
        raise AssertionError("Integration tests must not contact a live provider")
    monkeypatch.setattr(httpx.AsyncClient, "post", forbidden_post)


@pytest.fixture
def session(tmp_path):
    app = create_app(tmp_path / "data", LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as client:
        response = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        assert response.status_code == 200
        client.headers["x-csrf-token"] = response.json()["csrf"]
        yield client, app, tmp_path / "data"


def provider_payload(**extra):
    return {"api_key": KEY, "free_plan_confirmed": True,
            "cycle_start": date.today().isoformat(), "cycle_end": (date.today() + timedelta(days=30)).isoformat(), **extra}


def await_status(client, identifier, expected, timeout=3):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        state = client.get("/api/state").json()
        latest = next(s for s in state["scans"] if s["id"] == identifier)
        if latest["status"] in expected:
            return latest
        time.sleep(0.01)
    raise AssertionError(f"Scan never reached {expected}: {latest}")


def test_launch_token_bootstrap_and_private_http_only_cookie(tmp_path):
    app = create_app(tmp_path / "data", LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as client:
        assert client.get("/api/state").status_code == 401
        assert client.get("/api/bootstrap").status_code == 401
        assert client.get("/api/bootstrap?token=" + LAUNCH_TOKEN).status_code == 401
        assert client.get("/api/bootstrap", headers={"x-launch-token": "wrong"}).status_code == 401
        response = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        assert response.status_code == 200
        assert LAUNCH_TOKEN not in response.text
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        assert client.get("/api/state").status_code == 200
        assert client.get("/api/bootstrap").json()["csrf"] == response.json()["csrf"]
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["x-frame-options"] == "DENY"
        assert "connect-src 'self'" in response.headers["content-security-policy"]
        assert response.json()["PRODUCT_READY"] is False


def test_every_api_route_requires_the_session(tmp_path):
    import re
    app = create_app(tmp_path / "data", LAUNCH_TOKEN)
    checked = []
    with TestClient(app, base_url=BASE_URL) as client:
        assert client.get("/api/health").status_code == 401
        for route in app.routes:
            path = getattr(route, "path", "")
            methods = getattr(route, "methods", None) or set()
            if not path.startswith("/api/") or path == "/api/bootstrap":
                continue
            sample = re.sub(r"\{[^}]+\}", "0" * 32, path)
            for method in sorted(methods - {"HEAD", "OPTIONS"}):
                response = client.request(method, sample)
                assert response.status_code == 401, (method, sample, response.status_code)
                checked.append(f"{method} {sample}")
    assert any(item.startswith("GET /api/mass-search/") for item in checked)
    assert any("export" in item.lower() for item in checked)
    assert len(checked) >= 40


def test_lan_host_is_opt_in_and_still_requires_the_session(tmp_path):
    lan = "172.30.0.2"
    app = create_app(tmp_path / "data", LAUNCH_TOKEN, allowed_hosts=("127.0.0.1", "localhost", lan))
    with TestClient(app, base_url=f"http://{lan}:8765") as client:
        assert client.get("/api/state").status_code == 401
        bootstrap = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        assert bootstrap.status_code == 200
        client.headers["x-csrf-token"] = bootstrap.json()["csrf"]
        assert client.get("/api/state").status_code == 200
        assert client.get("/api/state", headers={"host": "127.0.0.1:8765"}).status_code == 200
        assert client.get("/api/state", headers={"host": "8.8.8.8:8765"}).status_code == 403
    assert allowed_request_host("172.30.0.2:8765", (lan,)) is True
    assert allowed_request_host("8.8.8.8:8765", (lan,)) is False


@pytest.mark.parametrize("host", ["attacker.invalid", "127.0.0.1.attacker.invalid:8765", "127.1:8765",
                                 "localhost:99999", "evil@localhost:8765", "127.0.0.1?evil",
                                 "localhost:8765#evil", "localhost/evil", "[::1]:8765"])
def test_dns_rebinding_and_malformed_hosts_are_blocked(session, host):
    client, app, _ = session
    response = client.get("/api/state", headers={"host": host})
    assert response.status_code == 403
    assert app.state.store.list("scans") == []


@pytest.mark.parametrize("origin", ["https://attacker.invalid", "http://localhost:8765", "http://127.0.0.1:8766", "null"])
def test_origin_must_match_exact_local_origin(session, origin):
    client, _, _ = session
    assert client.get("/api/state", headers={"origin": origin}).status_code == 403
    assert client.post("/api/demo", headers={"origin": origin}).status_code == 403
    assert client.options("/api/state", headers={"origin": BASE_URL}).status_code == 403


def test_mutations_require_csrf_and_rejection_leaves_state_unchanged(session):
    client, app, _ = session
    payload = {"address": ADDRESS, "label": "research"}
    original = client.headers.pop("x-csrf-token")
    assert client.post("/api/watchlist", json=payload).status_code == 403
    assert client.post("/api/watchlist", json=payload, headers={"x-csrf-token": "wrong"}).status_code == 403
    assert app.state.store.list("watchlist") == []
    client.headers["x-csrf-token"] = original
    assert client.post("/api/watchlist", json=payload, headers={"origin": BASE_URL}).status_code == 200
    client.headers.pop("x-csrf-token")
    assert client.delete(f"/api/watchlist/{ADDRESS}").status_code == 403
    assert len(app.state.store.list("watchlist")) == 1
    client.headers["x-csrf-token"] = original
    assert client.delete(f"/api/watchlist/{ADDRESS}").status_code == 200


def test_request_validation_and_free_caps_are_atomic(session):
    client, _, _ = session
    baseline = client.get("/api/state").json()
    assert client.put("/api/settings", json={"preset": {"min_profit_sol": "1"}, "limits": {"helius_cap": 1000000}}).status_code == 422
    after = client.get("/api/state").json()
    assert after["preset"] == baseline["preset"]
    assert after["settings"] == baseline["settings"]
    assert client.put("/api/settings", json={"refresh_minutes": 1}).status_code == 422
    assert client.put("/api/settings", json={"limits": {"transaction_limit": True}}).status_code == 422
    assert client.put("/api/settings", json={"preset": {"min_win_rate_pct": "101"}}).status_code == 422
    assert client.put("/api/settings", json={"api_key": KEY}).status_code == 422
    assert client.put("/api/settings", content="not JSON").status_code == 422
    assert client.put("/api/settings", json=[]).status_code == 422
    assert client.put("/api/settings", content="x" * 65537).status_code == 413
    assert client.post("/api/watchlist", json={"address": "0" * 32}).status_code == 422
    assert client.get("/api/unrecognized").status_code == 404
    assert client.get("/api/reports/missing").status_code == 404


def test_credentials_never_enter_responses_evidence_database_or_backup(session):
    client, app, directory = session
    response = client.post("/api/provider", json=provider_payload())
    assert response.status_code == 200
    assert response.json()["provider"]["storage"] == "session-only"
    assert KEY not in response.text
    state = client.get("/api/state")
    assert state.json()["provider"]["configured"] is True
    assert KEY not in state.text
    assert KEY not in client.get("/api/usage").text
    assert client.post("/api/backup").status_code == 200
    for path in directory.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert KEY.encode() not in data, path
            assert LAUNCH_TOKEN.encode() not in data, path
            assert app.state.csrf.encode() not in data, path


@pytest.mark.parametrize("unknown", [{"rpc_url": "https://attacker.invalid"}, {"private_key": "do-not-store"}, {"auto_upgrade": True}])
def test_provider_destination_and_signing_fields_are_not_configurable(session, unknown):
    client, app, _ = session
    assert client.post("/api/provider", json=provider_payload(**unknown)).status_code == 422
    assert app.state.store.get("configuration", "provider") is None


def test_active_provider_cycle_cannot_reset_charged_usage(session):
    client, app, _ = session
    assert client.post("/api/provider", json=provider_payload()).status_code == 200
    cycle = date.today().isoformat()
    reservation = app.state.store.reserve("helius", "getSlot", 1, cycle, 800000)
    app.state.store.dispatch(reservation)
    app.state.store.settle(reservation)
    shifted = provider_payload(cycle_start=(date.today() - timedelta(days=1)).isoformat(), cycle_end=(date.today() + timedelta(days=29)).isoformat())
    assert client.post("/api/provider", json=shifted).status_code == 422
    assert client.get("/api/usage").json()["used"] == 1
    assert client.post("/api/provider", json=provider_payload()).status_code == 200
    assert client.get("/api/usage").json()["used"] == 1


def test_offline_demo_has_independent_exact_expectations_and_no_credits(session):
    client, app, _ = session
    response = client.post("/api/demo")
    assert response.status_code == 200
    state = client.get("/api/state").json()
    reports = {r["label"]: r for r in state["reports"]}
    assert set(reports) == {"Patient accumulator", "Rapid rotation", "Unresolved allocation"}
    patient = reports["Patient accumulator"]
    assert patient["policy"] == "MATCH"
    assert reports["Rapid rotation"]["policy"] == "MISS"
    assert reports["Unresolved allocation"]["policy"] == "UNRESOLVED"
    expected = {"profit_sol": "8.7493", "completed_positions": "70", "completed_positions_90d": "110",
                "traded_mints": "20", "win_rate_pct": "70", "median_hold_hours": "6", "rapid_sale_pct": "0",
                "avg_buys": "1", "avg_sells": "1", "positive_weeks": "4", "economic_pnl_sol": "8.7493"}
    for name, value in expected.items():
        assert patient["metrics"][name]["value"] == value
    with localcontext() as context:
        context.prec = 192
        assert Decimal(patient["metrics"]["realised_roi_pct"]["value"]) == Decimal("8.7493") / Decimal("70.00035") * Decimal(100)
        assert Decimal(patient["metrics"]["median_roi_pct"]["value"]) == Decimal("0.19999") / Decimal("1.000005") * Decimal(100)
    assert patient["counts"]["closed"] == 70
    for report in reports.values():
        assert report["source"] == "demo"
        assert any("OFFLINE DEMO" in note for note in report["notes"])
        for evidence in report["evidence"]:
            fixture = app.state.store.evidence(evidence["hash"])
            assert fixture["kind"] == "synthetic-control"
            assert len(fixture["events"]) == (222 if report["label"] == "Unresolved allocation" else 220)
    assert state["usage"]["used"] == state["usage"]["reserved"] == 0


def test_cached_preview_and_settings_never_construct_a_provider(session, monkeypatch):
    client, app, _ = session
    assert client.post("/api/demo").status_code == 200
    before = app.state.store.list("reports")
    def forbidden_gateway(*args, **kwargs):
        raise AssertionError("Cached evaluation must not create a provider client")
    monkeypatch.setattr("scanner.providers.Gateway", forbidden_gateway)
    response = client.post("/api/presets/preview", json={"preset": {"min_profit_sol": "1000"}})
    assert response.status_code == 200
    preview = {r["label"]: r for r in response.json()["reports"]}
    assert preview["Patient accumulator"]["policy"] == "MISS"
    assert app.state.store.list("reports") == before
    assert client.put("/api/settings", json={"preset": {"min_profit_sol": "7"}, "limits": {"candidate_cap": 10}}).status_code == 200
    assert client.get("/api/state").json()["preset"]["min_profit_sol"] == "7"
    assert app.state.store.list("reports") == before
    assert client.get("/api/usage").json()["used"] == 0


@pytest.mark.parametrize("noncanonical", ["1E2", "1e2", "01", "01.5", "+1", ".5", " 1"])
def test_noncanonical_preset_decimals_are_rejected_atomically(session, monkeypatch, noncanonical):
    client, app, _ = session
    def forbidden_gateway(*args, **kwargs):
        raise AssertionError("Preset validation must not construct a provider")
    monkeypatch.setattr("scanner.providers.Gateway", forbidden_gateway)
    before = client.get("/api/state").json()["preset"]
    update = {"preset": {"min_profit_sol": noncanonical}}
    assert client.put("/api/settings", json=update).status_code == 422
    assert client.post("/api/presets/preview", json=update).status_code == 422
    assert client.get("/api/state").json()["preset"] == before
    assert app.state.store.list("presets") == []
    assert client.put("/api/settings", json={"preset": {"min_profit_sol": "1.50"}}).status_code == 200
    assert client.get("/api/state").json()["preset"]["min_profit_sol"] == "1.50"


@pytest.mark.parametrize("changed_scope", [{"window_days": 60}, {"window_days": 15}, {"verification_days": 120}])
def test_cached_preview_requires_rebuild_when_reporting_or_verification_scope_changes(session, monkeypatch, changed_scope):
    client, app, _ = session
    assert client.post("/api/demo").status_code == 200
    before = app.state.store.list("reports")
    usage_before = client.get("/api/usage").json()
    def forbidden_gateway(*args, **kwargs):
        raise AssertionError("A changed cached period must not request provider data")
    monkeypatch.setattr("scanner.providers.Gateway", forbidden_gateway)
    response = client.post("/api/presets/preview", json={"preset": changed_scope})
    assert response.status_code == 200
    reports = response.json()["reports"]
    assert len(reports) == 3
    for report in reports:
        assert report["preview"] is True
        assert "Collect/rebuild" in report["preview_reason"]
        assert report["policy"] == "UNRESOLVED"
        assert all(metric["value"] is None and metric["status"] == "unknown" for metric in report["metrics"].values())
        assert all(check["state"] == "UNKNOWN" for check in report["checks"])
        original = next(saved for saved in before if saved["id"] == report["id"])
        assert report["window"] == original["window"]
    assert app.state.store.list("reports") == before
    assert client.get("/api/usage").json() == usage_before


def test_demo_preserves_fixed_30_90_day_calibration_scope_after_live_preset_changes(session):
    client, app, _ = session
    assert client.put("/api/settings", json={"preset": {"window_days": 60, "verification_days": 120}}).status_code == 200
    assert client.post("/api/demo").status_code == 200
    reports = {report["label"]: report for report in app.state.store.list("reports")}
    assert reports["Patient accumulator"]["policy"] == "MATCH"
    assert reports["Rapid rotation"]["policy"] == "MISS"
    assert reports["Unresolved allocation"]["policy"] == "UNRESOLVED"
    for report in reports.values():
        assert report["preset"]["window_days"] == 30
        assert report["preset"]["verification_days"] == 90
        assert datetime.fromisoformat(report["window"]["end"]) - datetime.fromisoformat(report["window"]["start"]) == timedelta(days=30)
    patient = reports["Patient accumulator"]
    assert patient["metrics"]["completed_positions"]["value"] == "70"
    assert patient["metrics"]["completed_positions_90d"]["value"] == "110"
    assert patient["counts"]["closed"] == 70
    settings = client.get("/api/state").json()["preset"]
    assert settings["window_days"] == 60 and settings["verification_days"] == 120
    assert all(report["policy"] == "UNRESOLVED" for report in client.post("/api/presets/preview", json={}).json()["reports"])
    restored_scope = client.post("/api/presets/preview", json={"preset": {"window_days": 30, "verification_days": 90}}).json()["reports"]
    assert next(report for report in restored_scope if report["label"] == "Patient accumulator")["policy"] == "MATCH"


def test_old_cookies_and_tokens_do_not_authorize_new_launch(tmp_path):
    path = tmp_path / "data"
    first = create_app(path, LAUNCH_TOKEN)
    with TestClient(first, base_url=BASE_URL) as old:
        bootstrap = old.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        cookie = old.cookies.get("scanner_session")
        old_csrf = bootstrap.json()["csrf"]
    new = create_app(path, "new-launch-token")
    with TestClient(new, base_url=BASE_URL) as client:
        client.cookies.set("scanner_session", cookie)
        assert client.get("/api/state").status_code == 401
        assert client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN}).status_code == 401
        response = client.get("/api/bootstrap", headers={"x-launch-token": "new-launch-token"})
        assert response.status_code == 200
        assert response.json()["csrf"] != old_csrf
        assert client.post("/api/demo", headers={"x-csrf-token": old_csrf}).status_code == 403


def test_restart_pauses_interrupted_scan_and_retains_checkpoint(tmp_path):
    path = tmp_path / "data"
    store = Store(path)
    checkpoint = {"wallet_index": 0, "collector": {"pages": 3, "credits": 7}}
    store.put("scans", "interrupted", {"id": "interrupted", "status": "running", "checkpoint": checkpoint})
    store.close()
    app = create_app(path, LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as client:
        client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        scan = client.get("/api/state").json()["scans"][0]
        assert scan["status"] == "paused"
        assert scan["checkpoint"] == checkpoint
        assert "restarted" in scan["reason"]


def test_live_worker_receives_whole_seconds_and_closes_gateway(session, monkeypatch):
    client, app, _ = session
    instances = []
    class FakeGateway:
        def __init__(self, *args):
            self.closed = False
            instances.append(self)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            self.closed = True
        async def capability_test(self, address):
            assert address == ADDRESS
            return {"status": "passed", "capability_status": "passed"}
    async def collected(gateway, store, address, start, end, limits, **kwargs):
        assert datetime.fromisoformat(start).microsecond == 0
        assert datetime.fromisoformat(end).microsecond == 0
        return {"transactions": [], "coverage": {"history_scope_complete": False}, "evidence": []}
    monkeypatch.setattr("scanner.providers.Gateway", FakeGateway)
    monkeypatch.setattr("scanner.collector.collect_wallet", collected)
    assert client.post("/api/provider", json=provider_payload()).status_code == 200
    assert client.post("/api/scans", json={"addresses": [ADDRESS]}).status_code == 409
    assert instances == []  # Readiness checking itself never opens a client.
    assert client.post("/api/provider/test", json={"address": ADDRESS}).status_code == 200
    response = client.post("/api/scans", json={"addresses": [ADDRESS, ADDRESS]})
    assert response.status_code == 200
    scan = await_status(client, response.json()["scan_id"], {"completed", "paused"})
    assert scan["status"] == "completed"
    assert scan["audit_addresses"] == [ADDRESS]
    assert all(gateway.closed for gateway in instances)
    report = app.state.store.list("reports")[0]
    assert report["source"] == "live" and report["policy"] == "UNRESOLVED"
    assert report["evidence_status"] == "partial"


def test_deliberate_resume_adds_bounded_transaction_and_credit_tranches(session, monkeypatch):
    client, app, _ = session
    from scanner.collector import CollectionPaused
    recorded = []
    class FakeGateway:
        def __init__(self, *args):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
    async def paused(gateway, store, address, start, end, limits, checkpoint, **kwargs):
        recorded.append(limits)
        raise CollectionPaused("paused fixture", checkpoint)
    monkeypatch.setattr("scanner.providers.Gateway", FakeGateway)
    monkeypatch.setattr("scanner.collector.collect_wallet", paused)
    assert client.post("/api/provider", json=provider_payload()).status_code == 200
    assert client.put("/api/settings", json={"limits": {"transaction_limit": 5, "wallet_credit_limit": 7}}).status_code == 200
    limits = {**LIMITS, "transaction_limit": 10, "wallet_credit_limit": 20}
    checkpoint = {"transactions": {f"sig{i}": {} for i in range(10)}, "transactions_collected": 10, "credits": 20}
    app.state.store.put("scans", "paused", {"id": "paused", "status": "paused", "audit_addresses": [ADDRESS],
        "window": {"start": "2026-01-01T00:00:00+00:00", "end": "2026-01-31T00:00:00+00:00"},
        "preset": dict(STRICT), "limits": limits, "checkpoint": {"wallet_index": 0, "collector": checkpoint}})
    before = client.get("/api/usage").json()
    assert client.post("/api/scans/paused/resume").status_code == 200
    await_status(client, "paused", {"paused"})
    assert len(recorded) == 1
    assert recorded[0]["transaction_limit"] == 15
    assert recorded[0]["wallet_credit_limit"] == 27
    assert recorded[0]["helius_cap"] == 800000
    assert client.get("/api/usage").json() == before


def test_evidence_corruption_returns_409_and_csv_is_spreadsheet_safe(session):
    client, app, _ = session
    digest = app.state.store.archive({"signature": "fixture"})
    assert client.get(f"/api/evidence/{digest}").json() == {"signature": "fixture"}
    (app.state.store.path / "evidence" / f"{digest}.json.gz").write_bytes(b"broken")
    assert client.get(f"/api/evidence/{digest}").status_code == 409
    app.state.store.put("reports", "exportfixture", {"id": "exportfixture", "metrics": {
        "=formula": {"value": "@SUM(A1)", "unit": "SOL", "status": "known", "population": "\t=1+2", "reason": "-3"}}})
    response = client.get("/api/export/reports/exportfixture.csv")
    assert response.status_code == 200
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[1] == ["'=formula", "'@SUM(A1)", "SOL", "known", "'\t=1+2", "'-3"]
    assert "attachment" in response.headers["content-disposition"]


def accelerate_scheduler(monkeypatch):
    original_sleep = asyncio.sleep
    ticks = []
    async def sleep(delay, *args, **kwargs):
        if delay == 15:
            ticks.append(True)
            return await original_sleep(0.005)
        return await original_sleep(delay, *args, **kwargs)
    monkeypatch.setattr("scanner.app.asyncio.sleep", sleep)
    return ticks


def make_scheduler_due(app):
    app.state.store.put("configuration", "schedule", {
        "last_run": "2000-01-01T00:00:00+00:00", "offset": 0})


@pytest.fixture
def fast_session(tmp_path, monkeypatch):
    ticks = accelerate_scheduler(monkeypatch)
    app = create_app(tmp_path / "data", LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as client:
        response = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        client.headers["x-csrf-token"] = response.json()["csrf"]
        yield client, app, ticks


def test_scheduler_rotates_bounded_live_watchlist_and_skips_synthetic(fast_session, monkeypatch):
    client, app, ticks = fast_session
    from scanner.demo import _base58
    captured = []
    class FakeGateway:
        def __init__(self, *args):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
    async def collected(gateway, store, address, *args, **kwargs):
        captured.append(address)
        return {"transactions": [], "evidence": [], "coverage": {"history_scope_complete": False}}
    monkeypatch.setattr("scanner.providers.Gateway", FakeGateway)
    monkeypatch.setattr("scanner.collector.collect_wallet", collected)
    assert client.post("/api/provider", json=provider_payload()).status_code == 200
    provider = app.state.store.get("configuration", "provider")
    provider.update(capability_status="passed", calibration_address=ADDRESS)
    app.state.store.put("configuration", "provider", provider)
    assert client.put("/api/settings", json={"refresh_minutes": 15}).status_code == 200
    addresses = [_base58(bytes([i + 31]) * 32) for i in range(7)]
    for index, address in enumerate(addresses):
        app.state.store.put("watchlist", address, {"address": address, "source": "live", "label": str(index)})
    synthetic = _base58(bytes([200]) * 32)
    mass_search = _base58(bytes([201]) * 32)
    app.state.store.put("watchlist", synthetic, {"address": synthetic, "source": "demo"})
    app.state.store.put("watchlist", mass_search, {"address": mass_search, "source": "mass-search", "label": "Research shortlist"})
    make_scheduler_due(app)
    deadline = time.monotonic() + 3
    scans = []
    while time.monotonic() < deadline:
        scans = client.get("/api/state").json()["scans"]
        if scans and scans[0]["status"] == "completed":
            break
        time.sleep(0.01)
    assert ticks and len(scans) == 1
    first = scans[0]
    assert first["status"] == "completed"
    assert first["discovery_source"] == "watchlist-schedule"
    assert len(first["audit_addresses"]) == 5
    assert synthetic not in first["addresses"]
    assert mass_search not in first["addresses"]
    status = app.state.store.get("configuration", "schedule")
    assert status["offset"] == 5
    status["last_run"] = "2000-01-01T00:00:00+00:00"
    app.state.store.put("configuration", "schedule", status)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        scans = client.get("/api/state").json()["scans"]
        if len(scans) == 2 and all(s["status"] == "completed" for s in scans):
            break
        time.sleep(0.01)
    assert len(scans) == 2
    assert all(s["status"] == "completed" for s in scans)
    assert set(captured) == set(addresses)
    assert len(captured) == 10
    assert synthetic not in captured
    assert mass_search not in captured


@pytest.mark.parametrize("blocker", ["unconfigured", "paused", "headroom", "synthetic-only"])
def test_scheduler_respects_readiness_pause_quota_and_demo_gates(fast_session, monkeypatch, blocker):
    client, app, ticks = fast_session
    def forbidden_gateway(*args):
        raise AssertionError("A gated scheduler must never construct a provider")
    monkeypatch.setattr("scanner.providers.Gateway", forbidden_gateway)
    if blocker != "unconfigured":
        assert client.post("/api/provider", json=provider_payload()).status_code == 200
        info = app.state.store.get("configuration", "provider")
        info.update(capability_status="passed", calibration_address=ADDRESS)
        app.state.store.put("configuration", "provider", info)
    app.state.store.put("watchlist", ADDRESS, {"address": ADDRESS, "source": "demo" if blocker == "synthetic-only" else "live"})
    if blocker == "paused":
        app.state.store.put("scans", "owner-paused", {"id": "owner-paused", "source": "live", "status": "paused"})
    if blocker == "headroom":
        reservation = app.state.store.reserve("helius", "getSlot", 600000, date.today().isoformat(), 800000)
        app.state.store.dispatch(reservation)
        app.state.store.settle(reservation)
    assert client.put("/api/settings", json={"refresh_minutes": 15}).status_code == 200
    make_scheduler_due(app)
    deadline = time.monotonic() + 1
    while len(ticks) < 3 and time.monotonic() < deadline:
        time.sleep(0.005)
    assert len(ticks) >= 3
    scans = client.get("/api/state").json()["scans"]
    assert len(scans) == (1 if blocker == "paused" else 0)


def test_synthetic_watchlist_and_enrichment_cannot_contact_market_provider(session, monkeypatch):
    client, app, _ = session
    assert client.post("/api/demo").status_code == 200
    report = app.state.store.list("reports")[0]
    assert client.post("/api/watchlist", json={"address": report["address"], "label": "control"}).status_code == 200
    assert app.state.store.get("watchlist", report["address"])["source"] == "demo"
    def forbidden_market(*args, **kwargs):
        raise AssertionError("Synthetic controls must stay offline")
    monkeypatch.setattr("scanner.providers.GeckoTerminal", forbidden_market)
    assert client.post(f"/api/reports/{report['id']}/enrich").status_code == 409


def test_market_observations_are_bounded_and_do_not_change_historical_metrics(session, monkeypatch):
    client, app, _ = session
    observations = []
    clients = []
    class FakeMarket:
        def __init__(self, store):
            self.closed = False
            clients.append(self)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            self.closed = True
        async def get_token(self, mint):
            observations.append(mint)
            return {"mint": mint, "price_usd": "0.1", "scope": "current-only"}
    monkeypatch.setattr("scanner.providers.GeckoTerminal", FakeMarket)
    report = {"id": "live-observation", "source": "live", "policy": "UNRESOLVED", "evidence_status": "partial",
              "metrics": {"economic_pnl_sol": {"value": None, "status": "unknown"}},
              "positions": [{"mint": f"mint{i % 7}"} for i in range(12)]}
    app.state.store.put("reports", report["id"], report)
    response = client.post(f"/api/reports/{report['id']}/enrich")
    assert response.status_code == 200
    enriched = response.json()
    assert observations == ["mint0", "mint1", "mint2", "mint3", "mint4"]
    assert enriched["metrics"] == report["metrics"]
    assert enriched["policy"] == report["policy"]
    assert enriched["evidence_status"] == report["evidence_status"]
    assert len(enriched["market_observations"]) == 5
    assert all(client.closed for client in clients)


def test_resume_waits_for_active_collector_to_acknowledge_pause(session, monkeypatch):
    client, app, _ = session
    from scanner.collector import CollectionPaused
    entered, release = threading.Event(), threading.Event()
    calls = []
    class FakeGateway:
        def __init__(self, *args):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
    async def collected(gateway, store, address, start, end, limits, **kwargs):
        calls.append(address)
        if len(calls) == 1:
            checkpoint = {"transactions": {}, "credits": 7}
            kwargs["progress"]({"checkpoint": checkpoint, "credits": 7})
            entered.set()
            await asyncio.to_thread(release.wait, 2)
            assert kwargs["should_pause"]()
            raise CollectionPaused("Owner pause acknowledged", checkpoint)
        return {"transactions": [], "coverage": {}, "evidence": []}
    monkeypatch.setattr("scanner.providers.Gateway", FakeGateway)
    monkeypatch.setattr("scanner.collector.collect_wallet", collected)
    assert client.post("/api/provider", json=provider_payload()).status_code == 200
    info = app.state.store.get("configuration", "provider")
    info.update(capability_status="passed", calibration_address=ADDRESS)
    app.state.store.put("configuration", "provider", info)
    response = client.post("/api/scans", json={"addresses": [ADDRESS]})
    identifier = response.json()["scan_id"]
    assert entered.wait(1)
    assert client.post(f"/api/scans/{identifier}/pause").status_code == 200
    assert client.post(f"/api/scans/{identifier}/resume").status_code == 409
    assert len(calls) == 1
    release.set()
    deadline = time.monotonic() + 2
    response = None
    while time.monotonic() < deadline:
        response = client.post(f"/api/scans/{identifier}/resume")
        if response.status_code == 200:
            break
        time.sleep(0.005)
    assert response.status_code == 200
    scan = await_status(client, identifier, {"completed"})
    assert scan["progress"]["wallets_completed"] == 1
    assert calls == [ADDRESS, ADDRESS]


def test_paused_queued_scan_is_not_started_from_stale_worker_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY", KEY)
    entered, release = threading.Event(), threading.Event()
    calls = []
    class FakeGateway:
        def __init__(self, *args):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
    async def collected(gateway, store, address, *args, **kwargs):
        calls.append(address)
        entered.set()
        await asyncio.to_thread(release.wait, 2)
        return {"transactions": [], "coverage": {}, "evidence": []}
    monkeypatch.setattr("scanner.providers.Gateway", FakeGateway)
    monkeypatch.setattr("scanner.collector.collect_wallet", collected)
    app = create_app(tmp_path / "data", LAUNCH_TOKEN)
    app.state.store.put("configuration", "provider", {"free_plan_confirmed": True, "capability_status": "passed",
        "calibration_address": ADDRESS, "cycle_start": date.today().isoformat(), "cycle_end": (date.today() + timedelta(days=30)).isoformat()})
    base_scan = {"source": "live", "status": "queued", "audit_addresses": [ADDRESS],
        "window": {"start": "2026-01-01T00:00:00+00:00", "end": "2026-01-31T00:00:00+00:00"},
        "preset": dict(STRICT), "limits": dict(LIMITS), "checkpoint": {"wallet_index": 0},
        "progress": {"wallets_completed": 0, "wallets_total": 1, "unresolved": 0}}
    app.state.store.put("scans", "first", {**base_scan, "id": "first"})
    app.state.store.put("scans", "second", {**base_scan, "id": "second"})
    with TestClient(app, base_url=BASE_URL) as client:
        bootstrap = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        client.headers["x-csrf-token"] = bootstrap.json()["csrf"]
        assert entered.wait(1)
        assert client.post("/api/scans/second/pause").status_code == 200
        release.set()
        await_status(client, "first", {"completed"})
        second = next(s for s in client.get("/api/state").json()["scans"] if s["id"] == "second")
        assert second["status"] == "paused"
        assert calls == [ADDRESS]
