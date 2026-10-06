"""Phone-usable ranked-100 product path: batch, filters, auth gate, analytics."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from decimal import Decimal
from pathlib import Path

import pytest

from scanner.mass_search.acquisition_gate import (
    DRAFT_ID,
    attempt_history_acquisition,
    evaluate_authorization,
    hold_inflight_for_test,
    simulate_consume_for_test,
)
from scanner.mass_search.batch import HISTORY_REQUIRED, cancel_batch, create_and_run, create_batch, run_batch, step_batch
from scanner.mass_search.capture_catalog import (
    EXPECTED_CAPTURE_SHA,
    G1_ADDRESS,
    G1_HOLD_SECONDS,
    G1_PNL,
    catalog_by_address,
)
from scanner.mass_search.g3_reacquire import ALLOWED_WALLET
from scanner.mass_search.instrumentation import provider_call_count, reset_provider_calls
from scanner.mass_search.research_profile import load_filters, save_filters
from scanner.mass_search.workflow import (
    apply_local_filters,
    approval_proposal,
    compare_reports,
    load_ranked_universe,
    phone_access_status,
    ranked_workflow_view,
    replay_captured_wallet,
    set_user_shortlist,
)
from fastapi.testclient import TestClient

from scanner.app import create_app
from scanner.storage import Store

LAUNCH_TOKEN = "test-private-launch-token"
BASE_URL = "http://127.0.0.1:8765"

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "evidence/mass-wallet-funnel/ranked100-anchored-validation-live/SOURCE_RESPONSE_page0.json"
DRAFT = ROOT / "config/live_authorization.ranked100-next-candidates-draft.json"
SYNTH_USDC = "SynthEngUSDC11111111111111111111111111112"
SYNTH_SOL = "SynthEngSOL111111111111111111111111111111"
SYNTH_BAD = "SynthEngBAD111111111111111111111111111111"


@pytest.fixture
def store(tmp_path):
    reset_provider_calls()
    instance = Store(tmp_path / "data")
    yield instance
    instance.close()


def test_draft_grant_stays_disabled():
    payload = json.loads(DRAFT.read_text(encoding="utf-8"))
    assert payload["enabled"] is False
    assert payload["authorization_id"] == DRAFT_ID
    assert payload["acquisition_policy"]["do_not_dispatch"] is True
    assert payload["max_wallet_investigations"] == 5
    assert payload["stop_once_one_completed_position_reconciled"] is True


def test_catalog_is_not_rank1_only():
    catalog = catalog_by_address()
    assert ALLOWED_WALLET in catalog
    assert catalog[ALLOWED_WALLET]["sha256"] == EXPECTED_CAPTURE_SHA
    assert SYNTH_USDC in catalog
    assert catalog[SYNTH_USDC]["not_proof"] is True
    assert SYNTH_SOL in catalog
    assert SYNTH_BAD in catalog
    assert hashlib.sha256(CAPTURE.read_bytes()).hexdigest() == EXPECTED_CAPTURE_SHA


def test_genuine_g1_archive_replays_through_production_pipeline(store):
    result = replay_captured_wallet(store, G1_ADDRESS)
    report = result["report"]
    trades = [row for row in report.get("events") or [] if row.get("kind") in ("buy", "sell")]
    assert result["external_requests"] == 0
    assert [row["kind"] for row in trades] == ["buy", "buy", "buy", "buy", "sell"]
    assert Decimal(report["worksheet"]["total_profit_sol"]) == Decimal(G1_PNL)
    assert Decimal(report["independent_worksheet"]["total_profit_sol"]) == Decimal(G1_PNL)
    assert report["worksheet_reconciliation"]["status"] == "AGREE"
    assert report["material_exit"]["method_version"] == "material-exit-v2"
    assert report["material_exit"]["final_hold_seconds"] == G1_HOLD_SECONDS
    assert report["material_exit"]["exit_90_seconds"] == G1_HOLD_SECONDS
    assert report["corpus_kind"] == "GENUINE_REPLAY"
    assert report["address"] == G1_ADDRESS


def test_no_history_wallet_is_not_analysed(store):
    universe = load_ranked_universe()
    empty = next(row["address"] for row in universe["rows"] if not row["capture_available"])
    with pytest.raises(ValueError, match="History required — not analysed"):
        replay_captured_wallet(store, empty)
    assert store.list("reports") == []


def test_batch_analyses_genuine_and_labelled_fixtures_and_flags_no_history(store):
    universe = load_ranked_universe()
    no_history = next(row["address"] for row in universe["rows"] if not row["capture_available"])
    started = time.perf_counter()
    batch = create_and_run(store, [ALLOWED_WALLET, SYNTH_USDC, SYNTH_SOL, SYNTH_BAD, no_history])
    elapsed = time.perf_counter() - started
    by_address = {row["address"]: row for row in batch["outcomes"]}
    assert by_address[ALLOWED_WALLET]["status"] == "analysed"
    genuine = store.get("reports", by_address[ALLOWED_WALLET]["report_id"])
    assert genuine["worksheet"]["total_profit_usdc"] == "376.028087"
    assert genuine["funnel"]["A"]["state"] == "YES"
    assert genuine["funnel"]["B"]["state"] == "PARTIAL"
    assert genuine["funnel"]["C"]["state"] == "NOT_EVALUATED"
    assert genuine["analytics"]["median_hold"]["n_equals_one_disclosed"] is True
    assert genuine["analytics"]["median_hold"]["seconds"] == 852
    assert genuine["analytics"]["unresolved_basis_sales"] == 1
    assert genuine["analytics"]["known_cost_realised_pnl"]["usdc_excludes_sol_fees"] is True
    assert genuine["analytics"]["safe_to_copy"] is False
    assert by_address[SYNTH_USDC]["status"] == "analysed"
    assert by_address[SYNTH_USDC]["not_proof"] is True
    synth = store.get("reports", by_address[SYNTH_USDC]["report_id"])
    assert synth["corpus_kind"] == "SYNTHETIC"
    assert synth["worksheet"]["total_profit_usdc"] == "30"
    assert by_address[SYNTH_SOL]["status"] == "analysed"
    assert by_address[SYNTH_BAD]["status"] == "error"
    assert "synthetic engineering failure" in (by_address[SYNTH_BAD]["detail"] or "")
    assert by_address[no_history]["status"] == "history_required"
    assert by_address[no_history]["detail"] == HISTORY_REQUIRED
    assert batch["status"] == "completed"
    assert batch["external_requests"] == 0
    assert provider_call_count() == 0
    store.put("mass_search_perf", "batch-local", {
        "dataset": "ranked100-page0 + 3 labelled synthetic engineering fixtures + 1 no-history ranked row",
        "environment": "linux local Store, no provider network",
        "seconds": elapsed,
        "wallets": 5,
        "no_throughput_extrapolation": True,
    })


def test_batch_cache_and_cancel_do_not_call_providers(store):
    first = create_and_run(store, [ALLOWED_WALLET, SYNTH_USDC])
    assert first["outcomes"][0]["status"] == "analysed"
    second = create_and_run(store, [ALLOWED_WALLET])
    assert second["outcomes"][0]["status"] == "cached"
    pending = create_batch(store, [ALLOWED_WALLET, SYNTH_SOL])
    cancel_batch(store, pending["batch_id"])
    stopped = run_batch(store, pending["batch_id"])
    assert stopped["status"] == "cancelled"
    assert provider_call_count() == 0


def test_one_bad_wallet_does_not_prevent_later_success(store):
    batch = create_and_run(store, [SYNTH_BAD, SYNTH_SOL])
    assert batch["outcomes"][0]["status"] == "error"
    assert batch["outcomes"][1]["status"] == "analysed"
    assert batch["status"] == "completed"


def test_filters_and_shortlist_persist_and_stay_separated(store):
    universe = load_ranked_universe()
    started = time.perf_counter()
    filtered = apply_local_filters(universe["rows"], {
        "provider_proxy": {"min_provider_trade_count": "500", "only_shortlist": False},
        "thresholds": {},
    })
    elapsed = time.perf_counter() - started
    assert filtered
    assert all(int(row.get("trade_count") or 0) >= 500 for row in filtered)
    save_filters(store, {
        "provider_proxy": {"min_provider_trade_count": "20", "only_user_shortlist": True},
        "thresholds": {"min_completed_known_cost": "1"},
    })
    loaded = load_filters(store)
    assert loaded["provider_proxy"]["min_provider_trade_count"] == "20"
    assert loaded["thresholds"]["min_completed_known_cost"] == "1"
    assert loaded["reconstructed"]["thresholds"]["min_completed_known_cost"] == "1"
    target = universe["rows"][1]["address"]
    set_user_shortlist(store, target, True)
    view = ranked_workflow_view(store)
    assert target in view["user_shortlist"]
    assert view["filters"]["provider_proxy"]["only_user_shortlist"] is True
    assert len(view["rows"]) == 1
    assert view["rows"][0]["history_required_label"] == "History required — not analysed"
    assert view["phone_access"]["preview_available"] is False
    assert "No permitted remote preview" in view["phone_access"]["blocker"]
    store.put("mass_search_perf", "filter-local", {
        "dataset": "saved ranked-100 discovery page (100 wallets)",
        "environment": "linux local in-process filter",
        "seconds": elapsed,
        "no_throughput_extrapolation": True,
    })


def test_auth_gate_blocks_before_provider_and_under_concurrency(store):
    missing = evaluate_authorization(None)
    assert missing["code"] == "missing"
    assert missing["would_contact_provider"] is False
    disabled = evaluate_authorization(json.loads(DRAFT.read_text(encoding="utf-8")))
    assert disabled["code"] == "disabled"
    expired = evaluate_authorization({
        "schema_version": "live-research-authorization-v1",
        "enabled": True,
        "authorization_id": "test-expired",
        "expires_at": "2020-01-01T00:00:00Z",
        "do_not_dispatch": False,
        "providers": [{"provider_id": "helius", "max_requests": 2, "max_units": 20}],
    })
    assert expired["code"] == "expired"
    simulate_consume_for_test(store, requests=10, units=100)
    consumed = evaluate_authorization({
        "schema_version": "live-research-authorization-v1",
        "enabled": True,
        "authorization_id": "test-consumed",
        "expires_at": "2099-01-01T00:00:00Z",
        "do_not_dispatch": False,
        "providers": [{"provider_id": "helius", "max_requests": 10, "max_units": 100}],
    }, ledger=store.get("acquisition_gate", "live-dispatch-ledger"))
    assert consumed["code"] == "consumed"
    store.put("acquisition_gate", "live-dispatch-ledger", {"used_requests": 0, "used_units": 0, "in_flight": False})
    insufficient = evaluate_authorization({
        "schema_version": "live-research-authorization-v1",
        "enabled": True,
        "authorization_id": "test-insufficient",
        "expires_at": "2099-01-01T00:00:00Z",
        "do_not_dispatch": False,
        "providers": [{"provider_id": "helius", "max_requests": 1, "max_units": 1}],
    }, requested_requests=5, requested_units=50)
    assert insufficient["code"] == "insufficient"
    hold_inflight_for_test(store, True)
    concurrent = attempt_history_acquisition(store, {
        "schema_version": "live-research-authorization-v1",
        "enabled": True,
        "authorization_id": "test-concurrent",
        "expires_at": "2099-01-01T00:00:00Z",
        "do_not_dispatch": False,
        "providers": [{"provider_id": "helius", "max_requests": 2, "max_units": 20}],
    })
    assert concurrent["code"] == "concurrent"
    hold_inflight_for_test(store, False)
    first = attempt_history_acquisition(
        store,
        {
            "schema_version": "live-research-authorization-v1",
            "enabled": True,
            "authorization_id": "test-hold",
            "expires_at": "2099-01-01T00:00:00Z",
            "do_not_dispatch": False,
            "providers": [{"provider_id": "helius", "max_requests": 2, "max_units": 20}],
        },
        hold_reservation=True,
    )
    second = {}
    def other():
        second.update(attempt_history_acquisition(store, {
            "schema_version": "live-research-authorization-v1",
            "enabled": True,
            "authorization_id": "test-hold",
            "expires_at": "2099-01-01T00:00:00Z",
            "do_not_dispatch": False,
            "providers": [{"provider_id": "helius", "max_requests": 2, "max_units": 20}],
        }))
    thread = threading.Thread(target=other)
    thread.start()
    thread.join()
    assert first["would_contact_provider"] is False
    assert second["code"] == "concurrent"
    assert provider_call_count() == 0
    proposal = approval_proposal()
    assert proposal["do_not_dispatch"] is True
    assert proposal["do_not_enable"] is True
    assert proposal["authorization_id"] == DRAFT_ID
    assert proposal["history_boundaries"]["optional_rank1_earlier_page_for_unbacked_sale"] is False
    assert len(proposal["selected_candidates"]) == 5
    assert all(len(row["address"]) >= 32 for row in proposal["selected_candidates"])
    assert {row["provider_rank"] for row in proposal["selected_candidates"]} == {4, 2, 15, 17, 90}
    access = phone_access_status()
    assert access["preview_available"] is False


@pytest.fixture
def session(tmp_path):
    reset_provider_calls()
    app = create_app(tmp_path / "data", LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as client:
        response = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        assert response.status_code == 200
        client.headers["x-csrf-token"] = response.json()["csrf"]
        yield client


def test_ranked_workflow_routes_cover_filters_shortlist_batch_and_gate(session):
    client = session
    view = client.get("/api/mass-search/ranked-workflow").json()
    assert view["ranked_count"] == 100
    assert view["snapshot_id"] == "ranked100-discovery-pilot-2026-10-05"
    assert view["snapshot_raw_sha256"]
    assert view["phone_access"]["preview_available"] is False
    assert view["funnel_counts"]["history_required"] >= 99
    no_history = next(row["address"] for row in view["rows"] if row.get("history_required"))
    saved = client.put("/api/mass-search/research-filters", json={
        "provider_proxy": {"min_provider_trade_count": "10"},
        "thresholds": {"min_completed_known_cost": None},
    }).json()
    assert saved["provider_proxy"]["min_provider_trade_count"] == "10"
    short = client.post("/api/mass-search/ranked-workflow/shortlist", json={"address": no_history, "selected": True}).json()
    assert no_history in short["shortlist"]
    batch = client.post("/api/mass-search/ranked-workflow/batch", json={
        "addresses": [ALLOWED_WALLET, SYNTH_USDC, SYNTH_BAD, no_history],
    }).json()
    statuses = {row["address"]: row["status"] for row in batch["outcomes"]}
    assert statuses[ALLOWED_WALLET] == "analysed"
    assert statuses[SYNTH_USDC] == "analysed"
    assert statuses[SYNTH_BAD] == "error"
    assert statuses[no_history] == "history_required"
    report_id = next(row["report_id"] for row in batch["outcomes"] if row["address"] == ALLOWED_WALLET)
    report = client.get(f"/api/reports/{report_id}").json()
    assert report["worksheet"]["total_profit_usdc"] == "376.028087"
    assert report["analytics"]["median_hold"]["n_equals_one_disclosed"] is True
    gate = client.get("/api/mass-search/acquisition-gate").json()
    assert gate["attempt"]["allowed"] is False
    assert gate["attempt"]["would_contact_provider"] is False
    inst = client.get("/api/mass-search/instrumentation").json()
    assert inst["backend_provider_calls"] == 0
    phone = client.get("/api/mass-search/phone-access").json()
    assert phone["preview_available"] is False
    proposal = client.get("/api/mass-search/approval-proposal").json()
    assert proposal["do_not_dispatch"] is True
    assert client.get("/api/mass-search/ranked-workflow").json()["live_enabled"] is False
    assert provider_call_count() == 0


def test_step_batch_persists_progress(store):
    payload = create_batch(store, [SYNTH_USDC, SYNTH_SOL])
    mid = step_batch(store, payload["batch_id"])
    assert mid["completed"] == 1
    assert mid["status"] == "running"
    done = run_batch(store, payload["batch_id"])
    assert done["status"] == "completed"
    assert done["completed"] == 2


def test_second_inflight_batch_is_refused(store):
    first = create_batch(store, [SYNTH_USDC])
    with pytest.raises(ValueError, match="already in progress"):
        create_batch(store, [SYNTH_SOL])
    cancel_batch(store, first["batch_id"])
    second = create_batch(store, [SYNTH_SOL])
    assert second["batch_id"] != first["batch_id"]


def test_compare_flags_currency_window_and_incomplete_evidence(store):
    replay_captured_wallet(store, ALLOWED_WALLET)
    replay_captured_wallet(store, SYNTH_SOL)
    reports = {row["address"]: row for row in store.list("reports") if row.get("source") == "mass-search"}
    compared = compare_reports(store, reports[ALLOWED_WALLET]["id"], reports[SYNTH_SOL]["id"])
    kinds = {item["kind"] for item in compared["mismatches"]}
    assert "currency" in kinds
    assert "corpus" in kinds
    assert compared["comparable"] is False


def test_universe_exposes_stable_snapshot_identity():
    universe = load_ranked_universe()
    assert universe["ranked_count"] == 100
    assert universe["snapshot_id"] == "ranked100-discovery-pilot-2026-10-05"
    assert len(universe["snapshot_raw_sha256"]) == 64
    assert universe["capture_count"] == 1
