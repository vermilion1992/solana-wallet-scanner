"""Spend-safety and filter-grammar invariants for the LIVE E2E runner."""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient

from scanner.app import create_app
from scanner.mass_search.adapters import SourceError
from scanner.mass_search.evidence_integrity import redact_text
from scanner.mass_search.live_e2e import (
    DRAFT_PATH,
    DRAFT_REL_11,
    PINNED_LEDGER_REL,
    LiveE2EError,
    parse_wallets,
    run_live_e2e,
    validate_config,
)
from scanner.mass_search.live_e2e_ledger import committed_draft_hash, spend_from_ledger
from scanner.mass_search.research_profile import FilterValidationError, save_filters
from scanner.mass_search.workflow import ranked_workflow_view
from scanner.storage import Store

LAUNCH_TOKEN = "test-private-launch-token"
BASE_URL = "http://127.0.0.1:8765"
FAKE_HELIUS = "FAKEHELIUS-spend-safety-key-1055"
FAKE_BIRDEYE = "FAKEBIRDEYE-spend-safety-key-1055"
WALLETS = [
    "W000000000000000000000000000000000000000001",
    "W000000000000000000000000000000000000000002",
    "W000000000000000000000000000000000000000003",
    "W000000000000000000000000000000000000000004",
    "W000000000000000000000000000000000000000005",
    "W000000000000000000000000000000000000000006",
]


def _empty_helius(*_args, **_kwargs):
    raw = b'{"jsonrpc":"2.0","result":{"data":[],"paginationToken":null}}'
    return {
        "records": [],
        "pagination_token": None,
        "http_status": 200,
        "raw_bytes": raw,
        "evidence_sha256": "a" * 64,
        "units": 10,
        "external_requests": 1,
    }


def _empty_birdeye(*_args, **_kwargs):
    body = {"data": {"items": []}}
    raw = json.dumps(body).encode()
    return {"status": 200, "body": body, "fetched_at": "2026-10-07T00:00:00Z", "raw_bytes": raw}


def _arm_grant(tmp_path, *, helius_req=500, helius_units=5000, birdeye_req=3, birdeye_units=91,
               phase_caps=None, extra=None, bind_hash=True):
    import os
    from pathlib import Path
    draft_path = DRAFT_PATH.parents[1] / DRAFT_REL_11
    raw = json.loads(draft_path.read_text(encoding="utf-8"))
    raw["enabled"] = True
    raw["authorized_by_user_at"] = "2026-10-07T00:00:00Z"
    raw["expires_at"] = "2099-01-01T00:00:00Z"
    raw["armed_home"] = str(Path.home())
    raw["ledger_home"] = str(Path.home() / PINNED_LEDGER_REL)
    if bind_hash:
        raw["draft_artifact_hash"] = committed_draft_hash(
            DRAFT_REL_11,
            repo_root=DRAFT_PATH.parents[1],
        )
    for entry in raw["providers"]:
        entry["existing_plan_confirmed"] = True
        entry["remaining_quota_confirmed_at"] = "2026-10-07T00:00:00Z"
        if entry["provider_id"] == "helius":
            entry["max_requests"] = helius_req
            entry["max_units"] = helius_units
        if entry["provider_id"] == "birdeye":
            entry["max_requests"] = birdeye_req
            entry["max_units"] = birdeye_units
    if phase_caps is not None:
        raw["phase_caps"] = phase_caps
    if extra:
        raw.update(extra)
    path = tmp_path / "armed.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def _live_kwargs(tmp_path, grant, output, wallets, **extra):
    payload = {
        "mode": "live",
        "grant_path": str(grant),
        "output_dir": str(output),
        "ledger_dir": extra.pop("ledger_dir", None) or str(Path.home() / PINNED_LEDGER_REL),
        "wallets": wallets,
        "phases": extra.pop("phases", "2"),
        "window_days": 30,
        "earlier_history_days": 60,
        "resume": extra.pop("resume", False),
    }
    payload.update(extra)
    return payload


def pin_test_ledger(tmp_path, monkeypatch):
    """Pin --live ledger identity to a tmp absolute path. Does not use HOME."""
    from scanner.mass_search import live_e2e
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    pin = home / PINNED_LEDGER_REL
    pin.mkdir(parents=True)
    monkeypatch.setattr(live_e2e, "PINNED_LEDGER_ABSOLUTE", str(pin))
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(pin))
    return pin


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    return pin_test_ledger(tmp_path, monkeypatch)


@pytest.fixture
def fake_keys(monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY", FAKE_HELIUS)
    monkeypatch.setenv("BIRDEYE_API_KEY", FAKE_BIRDEYE)
    monkeypatch.delenv("HELIUS_KEY", raising=False)


def test_ss1_grant_cap_is_shared_across_output_dirs(tmp_path, monkeypatch, fake_keys):
    calls = []

    async def helius(*args, **kwargs):
        calls.append((args, kwargs))
        return _empty_helius()

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path, helius_req=6, helius_units=60)
    wallets = WALLETS[:3]
    spends = []
    for index in range(3):
        result = asyncio.run(run_live_e2e(_live_kwargs(
            tmp_path, grant, tmp_path / f"out{index}", wallets, phases="2",
        )))
        spends.append(result["spend"]["helius_requests"])
    assert len(calls) == 6
    assert spends[0] == 6
    assert spends[1] == 6
    assert spends[2] == 6


def test_ss2_live_refuses_armed_caps_above_draft(tmp_path, fake_keys):
    grant = _arm_grant(tmp_path, helius_req=50000, helius_units=5_000_000, birdeye_units=99999)
    with pytest.raises(LiveE2EError, match="hard ceiling|exceeds committed draft"):
        validate_config(_live_kwargs(tmp_path, grant, tmp_path / "out", WALLETS[:1]))


def test_ss2_wrong_draft_hash_refused(tmp_path, fake_keys):
    grant = _arm_grant(tmp_path, extra={"draft_artifact_hash": "0" * 64})
    with pytest.raises(LiveE2EError, match="not bound to the (pinned|committed) draft"):
        validate_config(_live_kwargs(tmp_path, grant, tmp_path / "out", WALLETS[:1]))


@pytest.mark.parametrize("factory", [
    lambda: RuntimeError("injected crash"),
    lambda: httpx.ReadTimeout("read timeout"),
    lambda: httpx.ConnectError("connect failed"),
])
def test_ss3_crash_persists_and_resume_does_not_resend(tmp_path, monkeypatch, fake_keys, factory):
    calls = []

    async def helius(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise factory()
        return _empty_helius()

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path, helius_req=20, helius_units=200)
    out = tmp_path / "crash"
    first = asyncio.run(run_live_e2e(_live_kwargs(tmp_path, grant, out, WALLETS[:1], phases="2")))
    assert first["status"] == "blocked"
    assert (out / "RUN_STATE.json").is_file()
    assert first["spend"]["helius_requests"] == 2
    assert first["spend"]["helius_units"] == 20
    assert FAKE_HELIUS not in json.dumps(first)
    resumed = asyncio.run(run_live_e2e(_live_kwargs(
        tmp_path, grant, out, WALLETS[:1], phases="2", resume=True,
    )))
    assert len(calls) == 2
    assert resumed["spend"]["helius_requests"] == 2
    assert "receipt already consumed" not in str(resumed.get("detail") or "")


def test_ss4_sourceerror_does_not_resend_paid_request(tmp_path, monkeypatch, fake_keys):
    calls = []

    async def helius(address, *, options, page_index=0):
        calls.append((address, options.get("transactionDetails"), page_index))
        if options.get("transactionDetails") == "full":
            raise SourceError("UNSUPPORTED_SCHEMA", "injected source error")
        return _empty_helius()

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path, helius_req=20, helius_units=200)
    out = tmp_path / "src"
    first = asyncio.run(run_live_e2e(_live_kwargs(tmp_path, grant, out, WALLETS[:1], phases="2")))
    assert first["status"] == "blocked"
    assert first["spend"]["helius_requests"] == 2
    asyncio.run(run_live_e2e(_live_kwargs(
        tmp_path, grant, out, WALLETS[:1], phases="2", resume=True,
    )))
    assert len(calls) == 2
    assert [item[1] for item in calls] == ["signatures", "full"]


def test_ss5_concurrent_resume_refused(tmp_path, monkeypatch, fake_keys):
    calls = []
    started = threading.Event()
    release = threading.Event()

    async def helius(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            started.set()
            release.wait(timeout=5)
        return _empty_helius()

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path, helius_req=20, helius_units=200)
    out = tmp_path / "conc"
    kwargs = _live_kwargs(tmp_path, grant, out, WALLETS[:4], phases="2")
    errors = []
    results = []

    def first():
        results.append(asyncio.run(run_live_e2e(kwargs)))

    def second():
        started.wait(timeout=5)
        try:
            results.append(asyncio.run(run_live_e2e({**kwargs, "resume": True})))
        except LiveE2EError as error:
            errors.append(error)
        finally:
            release.set()

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert errors
    assert any("exclusive lock" in str(error) for error in errors)
    assert len(calls) == 8


def test_ss6_phase3_honours_wallets(tmp_path, monkeypatch, fake_keys):
    calls = []

    async def helius(address, *, options, page_index=0):
        calls.append((address, options.get("transactionDetails")))
        return _empty_helius()

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path)
    out = tmp_path / "p3"
    asyncio.run(run_live_e2e(_live_kwargs(tmp_path, grant, out, WALLETS[:6], phases="2")))
    assert len(calls) == 12
    one = tmp_path / "one.json"
    one.write_text(json.dumps([WALLETS[0]]), encoding="utf-8")
    result = asyncio.run(run_live_e2e(_live_kwargs(
        tmp_path, grant, out, str(one), phases="3", resume=True,
    )))
    phase3_calls = [item for item in calls[12:] if item[1] == "full"]
    assert len(phase3_calls) == 1
    assert phase3_calls[0][0] == WALLETS[0]
    assert result["plan"]["totals"]["helius_requests"] == 2
    assert result["plan"]["within_caps"] is True


def test_ss7_per_phase_caps_enforced(tmp_path, monkeypatch, fake_keys):
    calls = []

    async def helius(*args, **kwargs):
        calls.append(1)
        return _empty_helius()

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path, phase_caps={
        "1": {"birdeye_requests": 3, "birdeye_units": 91},
        "2": {"helius_requests": 1, "helius_units": 10},
        "3": {"helius_requests": 1, "helius_units": 100},
        "4": {},
    })
    result = asyncio.run(run_live_e2e(_live_kwargs(
        tmp_path, grant, tmp_path / "phasecap", WALLETS[:1], phases="2",
    )))
    assert result["status"] == "blocked"
    assert len(calls) == 1
    assert result["spend"]["helius_requests"] == 1


def test_ss8_birdeye_is_one_documented_30_cu(tmp_path, monkeypatch, fake_keys):
    calls = []

    async def birdeye(*args, **kwargs):
        calls.append(1)
        return _empty_birdeye()

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_birdeye", birdeye)
    grant = _arm_grant(tmp_path)
    result = asyncio.run(run_live_e2e(_live_kwargs(
        tmp_path, grant, tmp_path / "be", [], phases="1", discovery=True,
    )))
    assert len(calls) == 1
    assert result["spend"]["birdeye_requests"] == 1
    assert result["spend"]["birdeye_units"] == 30
    store = Store(Path.home() / PINNED_LEDGER_REL / result["authorization_id"])
    usage = store.usage("birdeye", "2026-10-07T00:00:00Z", 91)
    assert usage["used"] == 30
    store.close()


def test_ss9_failed_request_is_in_state_spend(tmp_path, monkeypatch, fake_keys):
    async def helius(*args, **kwargs):
        raise SourceError("UNSUPPORTED_SCHEMA", "HTTP 500", http_status=500)

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path)
    result = asyncio.run(run_live_e2e(_live_kwargs(
        tmp_path, grant, tmp_path / "fail", WALLETS[:1], phases="2",
    )))
    assert result["spend"]["helius_requests"] == 1
    assert result["spend"]["helius_units"] == 10
    store = Store(Path.home() / PINNED_LEDGER_REL / result["authorization_id"])
    ledger, _ = spend_from_ledger(store)
    assert ledger["helius_requests"] == 1
    store.close()


def test_ss10_key_in_error_is_redacted(tmp_path, monkeypatch, fake_keys):
    async def helius(*args, **kwargs):
        raise ConnectionError(f"failed https://mainnet.helius-rpc.com/?api-key={FAKE_HELIUS}")

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path)
    result = asyncio.run(run_live_e2e(_live_kwargs(
        tmp_path, grant, tmp_path / "leak", WALLETS[:1], phases="2",
    )))
    blob = json.dumps(result) + (tmp_path / "leak" / "RUN_STATE.json").read_text(encoding="utf-8")
    blob += (tmp_path / "leak" / "RESULTS.json").read_text(encoding="utf-8")
    assert FAKE_HELIUS not in blob
    assert "?api-key=" not in blob or "[REDACTED]" in blob
    assert FAKE_HELIUS not in redact_text(f"?api-key={FAKE_HELIUS}")


def test_ss10_raw_page_scrubs_echoed_key(tmp_path, monkeypatch, fake_keys):
    async def helius(*args, **kwargs):
        raw = json.dumps({"echo": f"?api-key={FAKE_HELIUS}", "result": {"data": []}}).encode()
        return {
            "records": [],
            "pagination_token": None,
            "http_status": 200,
            "raw_bytes": raw,
            "evidence_sha256": "b" * 64,
            "units": 10,
            "external_requests": 1,
        }

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path)
    asyncio.run(run_live_e2e(_live_kwargs(
        tmp_path, grant, tmp_path / "raw", WALLETS[:1], phases="2",
    )))
    page = next((tmp_path / "raw" / "raw").rglob("page0.bin"))
    written = page.read_bytes()
    assert FAKE_HELIUS.encode() not in written
    integrity = json.loads(page.with_name(page.name + ".integrity.json").read_text(encoding="utf-8"))
    assert integrity["scrubbed"] is True
    assert integrity["original_sha256"]
    assert integrity["original_sha256"] != integrity["written_sha256"]


def test_ss11_window_bounds_persist_across_resume(tmp_path, monkeypatch, fake_keys):
    async def helius(*args, **kwargs):
        return _empty_helius()

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path)
    out = tmp_path / "win"
    first = asyncio.run(run_live_e2e(_live_kwargs(tmp_path, grant, out, WALLETS[:1], phases="2")))
    bounds = first["bounds"]
    state = json.loads((out / "RUN_STATE.json").read_text(encoding="utf-8"))
    assert state["bounds"] == bounds
    resumed = asyncio.run(run_live_e2e(_live_kwargs(
        tmp_path, grant, out, WALLETS[:1], phases="2", resume=True,
    )))
    assert resumed["bounds"] == bounds


def test_ss12_long_comma_wallets_do_not_crash():
    text = ",".join(WALLETS)
    assert len(text) > 200
    parsed = parse_wallets(text)
    assert parsed == WALLETS


def test_helius_query_auth_key_never_reaches_disk_logs_or_exceptions(tmp_path, monkeypatch, fake_keys):
    seen = {}

    class FakeResponse:
        status_code = 200
        content = json.dumps({
            "jsonrpc": "2.0",
            "result": {"data": [], "paginationToken": None},
            "echo": f"?api-key={FAKE_HELIUS}",
        }).encode()

        def json(self):
            return json.loads(self.content)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None, params=None):
            seen["url"] = url
            seen["headers"] = headers or {}
            seen["params"] = params or {}
            return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)
    from scanner.mass_search.live_e2e import _live_helius

    asyncio.run(_live_helius(WALLETS[0], options={"transactionDetails": "signatures", "limit": 1000}))
    assert seen["params"]["api-key"] == FAKE_HELIUS
    assert "api-key" not in (seen["headers"] or {})
    grant = _arm_grant(tmp_path)
    result = asyncio.run(run_live_e2e(_live_kwargs(
        tmp_path, grant, tmp_path / "query-auth", WALLETS[:1], phases="2",
    )))
    blob = json.dumps(result)
    blob += (tmp_path / "query-auth" / "RUN_STATE.json").read_text(encoding="utf-8")
    blob += (tmp_path / "query-auth" / "RESULTS.json").read_text(encoding="utf-8")
    for path in (tmp_path / "query-auth").rglob("*"):
        if path.is_file():
            blob += path.read_text(encoding="utf-8", errors="ignore")
    assert FAKE_HELIUS not in blob
    assert FAKE_HELIUS not in redact_text(f"?api-key={FAKE_HELIUS}")


def test_fl1_proxy_bools_only_true_false_null(tmp_path):
    store = Store(tmp_path / "data")
    with pytest.raises(FilterValidationError, match="true, false, or null"):
        save_filters(store, {"provider_proxy": {"only_shortlist": "false"}})
    with pytest.raises(FilterValidationError):
        save_filters(store, {"provider_proxy": {"only_captured": "0"}})
    with pytest.raises(FilterValidationError):
        save_filters(store, {"provider_proxy": {"only_user_shortlist": "no"}})
    saved = save_filters(store, {"provider_proxy": {"only_shortlist": False, "only_captured": None}})
    assert saved["provider_proxy"]["only_shortlist"] is False
    assert saved["provider_proxy"]["only_captured"] is False
    store.close()
    app = create_app(tmp_path / "http", LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as client:
        boot = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        client.headers["x-csrf-token"] = boot.json()["csrf"]
        rejected = client.put("/api/mass-search/research-filters", json={
            "provider_proxy": {"only_shortlist": "false"},
        })
        assert rejected.status_code == 422


def test_fl2_window_days_changes_episodes_and_pnl(tmp_path):
    old_ts = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())
    new_ts = int(datetime(2026, 10, 5, tzinfo=timezone.utc).timestamp())
    address = "WindowWallet11111111111111111111111111111"
    events = [
        {"kind": "buy", "mint": "MintOld", "units": "1", "timestamp": old_ts, "amount_sol": "1"},
        {"kind": "sell", "mint": "MintOld", "units": "1", "timestamp": old_ts + 10, "amount_sol": "11"},
        {"kind": "buy", "mint": "MintNew", "units": "1", "timestamp": new_ts, "amount_sol": "1"},
        {"kind": "sell", "mint": "MintNew", "units": "1", "timestamp": new_ts + 10, "amount_sol": "2"},
    ]
    ledger = [
        {"mint": "MintOld", "net": "10", "unit": "SOL", "closed_at": old_ts + 10, "timestamp": old_ts + 10},
        {"mint": "MintNew", "net": "1", "unit": "SOL", "closed_at": new_ts + 10, "timestamp": new_ts + 10},
    ]
    report = {
        "id": "report-window",
        "source": "mass-search",
        "address": address,
        "events": events,
        "completed_episode_ledger": ledger,
        "wallet_completed_episodes": 2,
        "completed_episode_net": "11",
        "window": {"start": "2026-09-07T00:00:00Z", "end": "2026-10-07T00:00:00Z"},
        "in_window_span": {"end": "2026-09-26T00:00:00Z"},
        "worksheet": {
            "settlement_asset": "SOL",
            "total_profit_sol": "11",
            "by_quote_asset": {"SOL": {"total_profit_sol": "11"}},
        },
        "research_profile": {
            "completed_known_cost_positions": 2,
            "sample_positions": 4,
            "completed_episode_ledger": ledger,
            "scoped_pnl": "11",
            "scoped_pnl_by_quote_asset": {"SOL": "11"},
            "settlement_asset": "SOL",
            "coverage_mandatory_share": "1",
        },
        "record_breakdown": {},
        "worksheet_keep": True,
    }
    extras = [{
        "address": address,
        "provider_rank": 1,
        "trade_count": 4,
        "provider_score": "1",
        "shortlisted": False,
        "capture_available": True,
        "label": "window",
        "evidence_status": "cached_capture",
        "row_kind": "ranked100",
    }]
    store = Store(tmp_path / "data")
    store.put("reports", report["id"], report)
    save_filters(store, {"window_days": 7})
    narrow = ranked_workflow_view(store, extra_universe_rows=extras)
    narrow_row = next(row for row in narrow["rows"] if row["address"] == address)
    save_filters(store, {"window_days": 365})
    wide = ranked_workflow_view(store, extra_universe_rows=extras)
    wide_row = next(row for row in wide["rows"] if row["address"] == address)
    assert narrow_row["research_profile"]["completed_known_cost_positions"] == 1
    assert narrow_row["research_profile"]["sample_positions"] == 2
    assert wide_row["research_profile"]["completed_known_cost_positions"] == 2
    assert wide_row["research_profile"]["sample_positions"] == 4
    assert str(narrow_row["research_profile"]["scoped_pnl"]) == "1"
    assert str(wide_row["research_profile"]["scoped_pnl"]) == "11"
    store.close()


def test_fl3_strict_ascii_decimal_grammar(tmp_path):
    store = Store(tmp_path / "data")
    for bad in ("1_000", "١٢", " 3 ", "1e3", "+3"):
        with pytest.raises(FilterValidationError):
            save_filters(store, {"thresholds": {"min_sample_positions": bad}})
    saved = save_filters(store, {"thresholds": {"min_sample_positions": "3", "min_coverage_share": "0.5"}})
    assert saved["thresholds"]["min_sample_positions"] == "3"
    assert saved["thresholds"]["min_coverage_share"] == "0.5"
    store.close()
