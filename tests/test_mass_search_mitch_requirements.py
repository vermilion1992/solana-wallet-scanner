"""A–D requirement tests. Zero live calls. Do not weaken assertions."""
from __future__ import annotations

import threading
import time
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scanner.app import create_app
from scanner.mass_search.batch import (
    IN_FLIGHT,
    PROCESS_MODEL,
    BatchBusy,
    cancel_batch,
    create_batch,
    hold_admission_barrier_for_test,
    hold_step_for_test,
    step_batch,
)
from scanner.mass_search.capture_catalog import ANALYSIS_VERSION, catalog_by_address, evidence_cache_key
from scanner.mass_search.g3_reacquire import ALLOWED_WALLET
from scanner.mass_search.instrumentation import reset_provider_calls
from scanner.mass_search.settlement import isolate_known_cost_events, usdc_fifo_worksheet
from scanner.mass_search.visible_report import hydrate_visible_report, persist_visible_report, visible_report_passes
from scanner.mass_search.workflow import (
    compare_reports,
    load_ranked_universe,
    ranked_workflow_view,
    replay_captured_wallet,
    research_search_proposal,
)
from scanner.storage import Store
from tools.independent_capture_reconciliation import reconcile_g1, reconcile_rank1, reconcile_synthetic

LAUNCH_TOKEN = "test-private-launch-token"
BASE_URL = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parents[1]
SYNTH_USDC = "SynthEngUSDC11111111111111111111111111112"
SYNTH_SOL = "SynthEngSOL111111111111111111111111111111"
SYNTH_EMPTY = "SynthEngEMPTY111111111111111111111111111"
SYNTH_FEEFREE = "SynthEngFEEFREE1111111111111111111111111"
SYNTH_UNBACKED = "SynthEngUNBACKED111111111111111111111111"
SYNTH_MULTI = "SynthEngMULTI111111111111111111111111111"
SYNTH_EARLY = "SynthEngWINDEARLY11111111111111111111111"
SYNTH_LATE = "SynthEngWINDLATE111111111111111111111111"
SYNTH_OVLEFT = "SynthEngWINDOVLEFT111111111111111111111"
SYNTH_OVRIGHT = "SynthEngWINDOVRIGHT11111111111111111111"
FIXTURE_DIR = ROOT / "tests/fixtures/synthetic_engineering"


@pytest.fixture
def store(tmp_path):
    reset_provider_calls()
    hold_admission_barrier_for_test(None)
    hold_step_for_test(None)
    instance = Store(tmp_path / "data")
    yield instance
    hold_admission_barrier_for_test(None)
    hold_step_for_test(None)
    instance.close()


@pytest.fixture
def session(tmp_path):
    reset_provider_calls()
    hold_admission_barrier_for_test(None)
    hold_step_for_test(None)
    app = create_app(tmp_path / "data", LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as client:
        response = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        assert response.status_code == 200
        client.headers["x-csrf-token"] = response.json()["csrf"]
        yield client
    hold_admission_barrier_for_test(None)
    hold_step_for_test(None)


def test_http_batch_admission_is_atomic_and_returns_409(session, tmp_path):
    barrier = threading.Barrier(2, timeout=5)
    hold_admission_barrier_for_test(barrier)
    created = []
    refused = []

    def worker(address):
        response = session.post(
            "/api/mass-search/ranked-workflow/batch",
            json={"addresses": [address], "run": False},
        )
        if response.status_code == 200:
            created.append(response.json())
        else:
            refused.append((response.status_code, response.json()))

    first = threading.Thread(target=worker, args=(SYNTH_USDC,))
    second = threading.Thread(target=worker, args=(SYNTH_SOL,))
    first.start()
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)
    hold_admission_barrier_for_test(None)
    assert not first.is_alive() and not second.is_alive()
    assert len(created) == 1
    assert len(refused) == 1
    assert refused[0][0] == 409
    assert IN_FLIGHT in str(refused[0][1])
    payload = created[0]
    assert payload["process_model"] == PROCESS_MODEL
    assert payload["status"] in ("pending", "running")
    assert payload["total"] == 1
    assert payload["outcomes"][0]["status"] == "pending"
    assert payload["outcomes"][0]["address"] in (SYNTH_USDC, SYNTH_SOL)
    assert payload["acquisition_independent"] is True
    persisted = session.get(f"/api/mass-search/ranked-workflow/batch/{payload['batch_id']}").json()
    assert persisted["batch_id"] == payload["batch_id"]
    assert persisted["status"] in ("pending", "running")
    assert persisted["total"] == 1
    assert persisted["executing"] is not True
    assert [row["status"] for row in persisted["outcomes"]] == ["pending"]
    other = session.post(
        "/api/mass-search/ranked-workflow/batch",
        json={"addresses": [SYNTH_EMPTY], "run": False},
    )
    assert other.status_code == 409
    assert IN_FLIGHT in str(other.json())
    listed = session.get("/api/mass-search/ranked-workflow").json()
    assert listed["PRODUCT_READY"] is False


def test_identical_http_batch_attaches_idempotently(session):
    first = session.post(
        "/api/mass-search/ranked-workflow/batch",
        json={"addresses": [SYNTH_USDC], "run": False},
    )
    assert first.status_code == 200
    second = session.post(
        "/api/mass-search/ranked-workflow/batch",
        json={"addresses": [SYNTH_USDC], "run": False},
    )
    assert second.status_code == 200
    assert second.json()["batch_id"] == first.json()["batch_id"]
    assert second.json()["attached"] is True
    assert second.json()["outcomes"][0]["address"] == SYNTH_USDC
    persisted = session.get(f"/api/mass-search/ranked-workflow/batch/{first.json()['batch_id']}").json()
    assert persisted["status"] == "pending"
    assert persisted["completed"] == 0
    assert persisted["outcomes"][0]["status"] == "pending"


def test_identical_create_and_run_attaches_without_rerunning(session):
    """An attached HTTP create_and_run must not start a second runner."""
    created = session.post(
        "/api/mass-search/ranked-workflow/batch",
        json={"addresses": [SYNTH_USDC], "run": False},
    )
    assert created.status_code == 200
    batch_id = created.json()["batch_id"]
    hold = threading.Event()
    hold_step_for_test(hold)
    stepper = threading.Thread(
        target=session.post,
        args=(f"/api/mass-search/ranked-workflow/batch/{batch_id}/step",),
    )
    stepper.start()
    for _ in range(200):
        current = session.get(f"/api/mass-search/ranked-workflow/batch/{batch_id}").json()
        if current.get("executing") is True:
            break
        time.sleep(0.01)
    else:
        hold.set()
        stepper.join(timeout=5)
        hold_step_for_test(None)
        raise AssertionError("HTTP step never marked executing")
    attached = session.post(
        "/api/mass-search/ranked-workflow/batch",
        json={"addresses": [SYNTH_USDC]},
    )
    assert attached.status_code == 200
    body = attached.json()
    assert body["attached"] is True
    assert body["batch_id"] == batch_id
    persisted = session.get(f"/api/mass-search/ranked-workflow/batch/{batch_id}").json()
    assert persisted["executing"] is True
    assert persisted["completed"] == 0
    assert persisted["outcomes"][0]["status"] == "pending"
    hold.set()
    stepper.join(timeout=10)
    hold_step_for_test(None)
    finished = session.get(f"/api/mass-search/ranked-workflow/batch/{batch_id}").json()
    assert finished["executing"] is False
    assert finished["completed"] == 1
    assert finished["status"] == "completed"
    assert finished["outcomes"][0]["status"] in ("analysed", "cached")
    reports = [row for row in session.get("/api/state?report_view=summary").json()["reports"] if row.get("address") == SYNTH_USDC]
    assert len(reports) == 1


def test_concurrent_http_step_does_not_double_analyse(session):
    created = session.post(
        "/api/mass-search/ranked-workflow/batch",
        json={"addresses": [SYNTH_USDC], "run": False},
    )
    batch_id = created.json()["batch_id"]
    hold = threading.Event()
    hold_step_for_test(hold)
    first_body = []
    second_body = []

    def step_into(bucket):
        response = session.post(f"/api/mass-search/ranked-workflow/batch/{batch_id}/step")
        bucket.append((response.status_code, response.json()))

    first = threading.Thread(target=step_into, args=(first_body,))
    first.start()
    for _ in range(200):
        current = session.get(f"/api/mass-search/ranked-workflow/batch/{batch_id}").json()
        if current.get("executing") is True:
            break
        time.sleep(0.01)
    else:
        hold.set()
        first.join(timeout=5)
        hold_step_for_test(None)
        raise AssertionError("HTTP step never marked executing")
    second = threading.Thread(target=step_into, args=(second_body,))
    second.start()
    second.join(timeout=5)
    assert second_body and second_body[0][0] == 200
    ignored = second_body[0][1]
    assert ignored["attached"] is True
    assert ignored["step_ignored"] == "already_executing"
    mid = session.get(f"/api/mass-search/ranked-workflow/batch/{batch_id}").json()
    assert mid["executing"] is True
    assert mid["step_ignored"] == "already_executing"
    assert mid["completed"] == 0
    assert mid["index"] == 0
    assert mid["outcomes"][0]["status"] == "pending"
    hold.set()
    first.join(timeout=10)
    hold_step_for_test(None)
    finished = session.get(f"/api/mass-search/ranked-workflow/batch/{batch_id}").json()
    assert finished["executing"] is False
    assert finished["completed"] == 1
    assert finished["index"] == 1
    assert finished["status"] == "completed"
    assert finished["outcomes"][0]["status"] in ("analysed", "cached")
    reports = [row for row in session.get("/api/state?report_view=summary").json()["reports"] if row.get("address") == SYNTH_USDC]
    assert len(reports) == 1


def test_cancel_releases_admission_only_after_executing_stops(store):
    hold = threading.Event()
    hold_step_for_test(hold)
    payload = create_batch(store, [SYNTH_USDC, SYNTH_SOL])
    stepper = threading.Thread(target=step_batch, args=(store, payload["batch_id"]))
    stepper.start()
    for _ in range(200):
        current = store.get("ranked_batch", payload["batch_id"])
        if current and current.get("executing") is True:
            break
        time.sleep(0.01)
    else:
        hold.set()
        stepper.join(timeout=5)
        raise AssertionError("step_batch never marked executing")
    cancelled = cancel_batch(store, payload["batch_id"])
    assert cancelled["cancel_requested"] is True
    assert cancelled["executing"] is True
    assert cancelled["status"] == "running"
    with pytest.raises(BatchBusy, match="already in progress"):
        create_batch(store, [SYNTH_SOL])
    hold.set()
    stepper.join()
    finished = store.get("ranked_batch", payload["batch_id"])
    assert finished["executing"] is False
    assert finished["status"] == "cancelled"
    hold_step_for_test(None)
    nxt = create_batch(store, [SYNTH_SOL])
    assert nxt["batch_id"] != payload["batch_id"]


def test_batch_admission_does_not_consult_acquisition(store):
    from scanner.mass_search.acquisition_gate import attempt_history_acquisition, hold_inflight_for_test
    hold_inflight_for_test(store, True)
    blocked = attempt_history_acquisition(store)
    assert blocked["allowed"] is False
    payload = create_batch(store, [SYNTH_USDC])
    assert payload["batch_id"]
    assert payload["acquisition_independent"] is True


def test_visible_report_true_and_false_survive_http_reopen(session, tmp_path):
    true_run = session.post("/api/mass-search/ranked-workflow/replay", json={"address": SYNTH_USDC}).json()
    assert true_run["visible_report"] is True
    true_id = true_run["report_id"]
    saved = session.get(f"/api/reports/{true_id}").json()
    assert saved["visible_report"] is True
    exported = session.get(f"/api/export/reports/{true_id}.json").json()
    assert exported["visible_report"] is True
    assert exported["mass_search_interpretation"]["visible_report"] is True
    assert exported["mass_search_interpretation"]["visible_report_stored"] is True

    false_run = session.post("/api/mass-search/ranked-workflow/replay", json={"address": SYNTH_EMPTY}).json()
    assert false_run["visible_report"] is False
    false_id = false_run["report_id"]
    saved_false = session.get(f"/api/reports/{false_id}").json()
    assert saved_false["visible_report"] is False
    exported_false = session.get(f"/api/export/reports/{false_id}.json").json()
    assert exported_false["visible_report"] is False
    assert exported_false["mass_search_interpretation"]["visible_report"] is False
    assert exported_false["mass_search_interpretation"]["visible_report_stored"] is False

    # Restart: new app on the same data dir.
    app = create_app(tmp_path / "data", LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as restarted:
        boot = restarted.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        restarted.headers["x-csrf-token"] = boot.json()["csrf"]
        again_true = restarted.get(f"/api/reports/{true_id}").json()
        again_false = restarted.get(f"/api/reports/{false_id}").json()
        assert again_true["visible_report"] is True
        assert again_false["visible_report"] is False
        cache = restarted.post("/api/mass-search/ranked-workflow/replay", json={"address": SYNTH_EMPTY}).json()
        assert cache["cache_hit"] is True
        assert cache["visible_report"] is False
        assert cache["report"]["visible_report"] is False


def test_absent_visible_report_never_defaults_true():
    assert hydrate_visible_report({}, cache_hit=True) is False
    assert visible_report_passes({}) is False
    payload = {}
    persist_visible_report(payload, False)
    assert payload["visible_report"] is False


def test_fee_free_partial_match_is_fully_accounted(store):
    fixture = FIXTURE_DIR / "partial-match-fee-free.json"
    app = replay_captured_wallet(store, SYNTH_FEEFREE)
    report = app["report"]
    assert report["result_scope"] == "conditional_on_captured_inventory"
    assert report["worksheet"]["total_profit_usdc"] == "24"
    assert report["worksheet"]["unresolved_basis_sales"] == 1
    independent = reconcile_synthetic(fixture)
    assert Decimal(independent["fifo"]["total_profit"]) == Decimal("24")
    matched = independent["fifo"]["known_cost_sells"][0]
    unresolved = independent["fifo"]["unresolved_basis_sales"][0]
    assert Decimal(matched["proceeds"]) == Decimal("60")
    assert Decimal(matched["basis"]) == Decimal("36")
    assert Decimal(matched["net_profit"]) == Decimal("24")
    assert Decimal(unresolved["gross_proceeds"]) == Decimal("40")
    assert unresolved["unmatched_quantity_raw"] == "4"
    assert Decimal(matched["proceeds"]) + Decimal(unresolved["gross_proceeds"]) == Decimal("100")
    assert matched["whole_sale_pnl_resolved"] is False
    trades = (app["analytics"] or {}).get("trades") or []
    sells = [row for row in trades if row.get("side") == "sell"]
    assert len(sells) == 2
    known = next(row for row in sells if row.get("reconciliation_or_exclusion") != "unresolved_basis")
    unknown = next(row for row in sells if row.get("reconciliation_or_exclusion") == "unresolved_basis")
    assert known["tx_ref"] == unknown["tx_ref"] == "synth-eng-feefree-sell-1"
    assert Decimal(known["quantity"]) == Decimal("6")
    assert Decimal(known["proceeds_or_cost"]) == Decimal("60")
    assert Decimal(known["allocated_basis"]) == Decimal("36")
    assert Decimal(known["known_cost_pnl"]) == Decimal("24")
    assert known["whole_sale_pnl_resolved"] is False
    assert known["result_scope"] == "conditional_on_captured_inventory"
    assert Decimal(unknown["quantity"]) == Decimal("4")
    assert Decimal(unknown["proceeds_or_cost"]) == Decimal("40")
    assert Decimal(unknown["unmatched_quantity"]) == Decimal("4")
    assert unknown["allocated_basis"] is None
    assert unknown["known_cost_pnl"] is None
    assert unknown["whole_sale_pnl_resolved"] is False
    assert Decimal(known["proceeds_or_cost"]) + Decimal(unknown["proceeds_or_cost"]) == Decimal("100")
    saved = store.get("reports", report["id"])
    saved_sells = [row for row in (saved.get("analytics") or {}).get("trades") or [] if row.get("side") == "sell"]
    assert len(saved_sells) == 2
    assert Decimal(saved_sells[0]["proceeds_or_cost"]) + Decimal(saved_sells[1]["proceeds_or_cost"]) == Decimal("100")


def test_partial_match_cases_agree_with_independent_tool(store):
    cases = [
        (SYNTH_USDC, "usdc-closed-position.json", Decimal("30"), 0),
        (SYNTH_UNBACKED, "fully-unbacked-sell.json", None, 1),
        (SYNTH_MULTI, "multi-lot-partial.json", Decimal("19"), 1),
    ]
    for address, name, profit, unresolved in cases:
        app = replay_captured_wallet(store, address)
        independent = reconcile_synthetic(FIXTURE_DIR / name)
        app_profit = (app["report"].get("worksheet") or {}).get("total_profit_usdc")
        if profit is None:
            assert app_profit in (None, "")
            assert independent["fifo"]["total_profit"] is None
        else:
            assert Decimal(app_profit) == profit
            assert Decimal(independent["fifo"]["total_profit"]) == profit
        assert (app["report"].get("worksheet") or {}).get("unresolved_basis_sales", 0) == unresolved
        assert len(independent["fifo"]["unresolved_basis_sales"]) == unresolved


def test_rank1_and_g1_unchanged_after_partial_match_and_research_screen():
    rank1 = reconcile_rank1()
    assert rank1["market_trades"] == 6
    assert Decimal(rank1["fifo"]["total_profit"]) == Decimal("376.028087")
    assert len(rank1["fifo"]["open_lots"]) == 3
    assert len(rank1["fifo"]["unresolved_basis_sales"]) == 1
    g1 = reconcile_g1()
    assert Decimal(g1["fifo"]["total_profit"]) == Decimal("-0.167725526")


def test_compare_same_window_control_and_differing_included_trades(store):
    replay_captured_wallet(store, SYNTH_USDC)
    replay_captured_wallet(store, SYNTH_FEEFREE)
    reports = {row["address"]: row for row in store.list("reports") if row.get("source") == "mass-search"}
    same = compare_reports(store, reports[SYNTH_USDC]["id"], reports[SYNTH_FEEFREE]["id"])
    assert (reports[SYNTH_USDC].get("window") or {}) == (reports[SYNTH_FEEFREE].get("window") or {})
    assert "window" not in {item["kind"] for item in same["mismatches"]}
    assert same["window_policy"]["kind"] == "own_windows_shown_mismatch_blocks"
    assert same["comparable"] is True or "currency" not in {item["kind"] for item in same["mismatches"]}
    assert set(same["window_policy"]["left_included_tx"]) != set(same["window_policy"]["right_included_tx"])
    assert same["window_policy"]["left_sample_size"] == 1
    # Fee-free fixture is buy 6 / sell 10: matched fragment is kept, but item 6
    # says a partly backed sale is not a clean flat-to-flat episode.
    assert same["window_policy"]["right_sample_size"] == 0
    assert Decimal(str(same["window_policy"]["left_scoped_pnl"])) == Decimal("30")
    assert Decimal(str(same["window_policy"]["right_scoped_pnl"])) == Decimal("24")

    replay_captured_wallet(store, SYNTH_EARLY)
    replay_captured_wallet(store, SYNTH_LATE)
    reports = {row["address"]: row for row in store.list("reports") if row.get("source") == "mass-search"}
    early = reports[SYNTH_EARLY]
    late = reports[SYNTH_LATE]
    differing = compare_reports(store, early["id"], late["id"])
    assert "window" in {item["kind"] for item in differing["mismatches"]}
    assert differing["comparable"] is False
    policy = differing["window_policy"]
    assert policy["left_window"] != policy["right_window"]
    assert policy["left_included_trades"] == 2
    assert policy["right_included_trades"] == 2
    assert policy["left_included_tx"] == ["synth-eng-wind-early-buy-1", "synth-eng-wind-early-sell-1"]
    assert policy["right_included_tx"] == ["synth-eng-wind-late-buy-1", "synth-eng-wind-late-sell-1"]
    assert set(policy["left_included_tx"]).isdisjoint(policy["right_included_tx"])
    assert policy["left_sample_size"] == 1
    assert policy["right_sample_size"] == 1
    assert Decimal(str(policy["left_scoped_pnl"])) == Decimal("8")
    assert Decimal(str(policy["right_scoped_pnl"])) == Decimal("2")
    assert policy["left_window"]["end"] == "2026-09-20T00:00:00Z"
    assert policy["right_window"]["start"] == "2026-09-25T00:00:00Z"
    # Non-overlap: early ends before late starts.
    assert policy["left_window"]["end"] <= policy["right_window"]["start"]


def test_compare_partial_overlap_one_corpus_keeps_own_windows(store):
    replay_captured_wallet(store, SYNTH_OVLEFT)
    replay_captured_wallet(store, SYNTH_OVRIGHT)
    reports = {row["address"]: row for row in store.list("reports") if row.get("source") == "mass-search"}
    left = reports[SYNTH_OVLEFT]
    right = reports[SYNTH_OVRIGHT]
    compared = compare_reports(store, left["id"], right["id"])
    assert compared["comparable"] is False
    assert "window" in {item["kind"] for item in compared["mismatches"]}
    policy = compared["window_policy"]
    assert policy["kind"] == "own_windows_shown_mismatch_blocks"
    assert policy["left_window"]["start"] == "2026-09-05T13:29:27Z"
    assert policy["left_window"]["end"] == "2026-09-25T00:00:00Z"
    assert policy["right_window"]["start"] == "2026-09-20T00:00:00Z"
    assert policy["right_window"]["end"] == "2026-10-05T13:29:27Z"
    left_tx = set(policy["left_included_tx"])
    right_tx = set(policy["right_included_tx"])
    overlap = {"synth-eng-wind-overlap-buy-1", "synth-eng-wind-overlap-sell-1"}
    assert left_tx & right_tx == overlap
    assert "synth-eng-wind-ovleft-buy-1" in left_tx
    assert "synth-eng-wind-ovleft-sell-1" in left_tx
    assert "synth-eng-wind-ovright-buy-1" in right_tx
    assert "synth-eng-wind-ovright-sell-1" in right_tx
    assert policy["left_included_trades"] == 4
    assert policy["right_included_trades"] == 4
    assert policy["left_sample_size"] == 2
    assert policy["right_sample_size"] == 2
    assert Decimal(str(policy["left_scoped_pnl"])) == Decimal("11")
    assert Decimal(str(policy["right_scoped_pnl"])) == Decimal("10")
    assert policy["result_scope"] == "conditional_on_captured_inventory"


def test_cache_key_includes_window():
    entry = catalog_by_address()[ALLOWED_WALLET]
    key1 = evidence_cache_key(entry)
    shifted = dict(entry)
    shifted["windows"] = dict(entry["windows"])
    shifted["windows"]["report_end_exclusive"] = "2026-09-01T00:00:00Z"
    key2 = evidence_cache_key(shifted)
    assert key1 != key2
    assert ANALYSIS_VERSION == (
        "analysis-v6-research-screen-v2+sol-isolate-v1+mixed-quote-v1+"
        "sig-keyed-v1+quote-conversion-v1+fees-tips-v1+coverage-v1+mitch-review-v1"
    )


def test_research_screen_is_inconclusive_for_99_without_history(store):
    view = ranked_workflow_view(store)
    screen = view["research_screen"]
    assert screen["unknown_never_passes"] is True
    assert screen["counts"]["inconclusive"] == 89
    assert screen["counts"]["not_executed"] == 11
    assert screen["outcome"] == "inconclusive"
    assert screen["counts"]["qualification"]["not_evaluated"] == 100
    assert all(row["qualification_category"]["category"] == "not_evaluated" for row in view["rows"])
    replay_captured_wallet(store, ALLOWED_WALLET)
    after = ranked_workflow_view(store)
    screen_after = after["research_screen"]
    assert screen_after["counts"]["completed_qualified"] == 0
    assert screen_after["counts"]["not_executed"] == 10
    # Item 12: a missing FIFO basis blocks coverage regardless of percentage.
    # Rank-1 may be zero-qualified or coverage-pending/inconclusive.
    assert screen_after["counts"]["inconclusive"] + screen_after["counts"]["zero_qualified"] == 90
    assert screen_after["counts"]["inconclusive"] >= 89
    profile = store.list("reports")[0]["research_profile"]
    assert profile["evidence_class"]["account"]["class"] == 5
    assert profile["evidence_class"]["position"]["class"] in (1, 2)
    assert profile["candidate_assessment"]["net_realised"] is None
    assert profile["qualification_category"]["category"] == "analysed_incomplete"
    assert profile["qualification_category"]["screening_separate"] is True
    assert profile["criteria_met"] is False
    rank1 = next(row for row in after["rows"] if row["address"] == ALLOWED_WALLET)
    assert rank1["qualification_category"]["category"] == "analysed_incomplete"
    assert screen_after["counts"]["qualification"]["analysed_incomplete"] == 1
    assert screen_after["counts"]["qualification"]["not_evaluated"] == 99
    assert screen_after["counts"]["qualification"]["profitable_account_performance"] == 0


def test_research_search_proposal_is_separate_and_disabled():
    existing = (ROOT / "config/live_authorization.ranked100-next-candidates-draft.json").read_text()
    proposal = research_search_proposal()
    assert proposal["enabled"] is False
    assert proposal["do_not_dispatch"] is True
    assert proposal["authorization_id"] == "live-ranked100-research-search-2026-10-06-mitch"
    assert "never_until_a_winner" in proposal["stop_conditions"]
    assert proposal["documented_credits"] == 200
    assert "unconfirmed" in proposal["credits_needed_versus_balance"]
    assert "stop_once_one_completed_position_reconciled" not in proposal["stop_conditions"]
    after = (ROOT / "config/live_authorization.ranked100-next-candidates-draft.json").read_text()
    assert after == existing


def test_multi_lot_integer_totals_preserved():
    rows = [
        {"kind": "buy", "units": "3", "consideration_usdc": "15", "seconds_from_start": 1, "mint": "a", "signature": "b1"},
        {"kind": "buy", "units": "5", "consideration_usdc": "30", "seconds_from_start": 2, "mint": "a", "signature": "b2"},
        {"kind": "sell", "units": "12", "consideration_usdc": "96", "seconds_from_start": 3, "mint": "a", "signature": "s1"},
    ]
    known, unresolved = isolate_known_cost_events(rows)
    assert Decimal(known[-1]["consideration_usdc"]) + Decimal(unresolved[0]["consideration_usdc"]) == Decimal("96")
    worksheet = usdc_fifo_worksheet(known)
    # FIFO: 3@5 + 5@6 = 15+30=45 basis on 8 units; proceeds 96*8/12=64; profit 19
    assert worksheet["total_profit_usdc"] == "19"
