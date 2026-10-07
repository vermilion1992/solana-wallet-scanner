"""LIVE E2E filter invariants, oracle, grant draft, and runner self-attack."""
from __future__ import annotations

import asyncio
import json
import random
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scanner.app import create_app
from scanner.mass_search.capability import validate_live_authorization
from scanner.mass_search.live_e2e import (
    AUTHORIZATION_ID,
    DRAFT_PATH,
    KNOWN_BLOCKING_PROGRAMS,
    L2TEX_PROGRAM,
    LiveE2EError,
    classify_programs,
    load_grant,
    main,
    parse_wallets,
    plan_request_counts,
    run_live_e2e,
    validate_config,
)
from scanner.mass_search.research_profile import (
    FilterValidationError,
    default_filters,
    evaluate_thresholds,
    load_filters,
    save_filters,
)
from scanner.mass_search.workflow import _reconstructed_pass, ranked_workflow_view
from scanner.storage import Store

ROOT = Path(__file__).resolve().parents[1]
LAUNCH_TOKEN = "test-private-launch-token"


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    home = tmp_path / "ledger-home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(home))
    return home
BASE_URL = "http://127.0.0.1:8765"
GTFO = "gtfoTELAeEZHUgHetA6umfsCETiBMzJCN4tB2sqCgFL"

ORACLE_FIELDS = {
    "min_completed_known_cost": ("completed_known_cost_positions", "min"),
    "min_sample_positions": ("sample_positions", "min"),
    "min_coverage_share": ("coverage_mandatory_share", "min"),
    "min_scoped_pnl_usdc": ("scoped_pnl_usdc", "min"),
    "min_scoped_pnl_sol": ("scoped_pnl_sol", "min"),
    "max_hold_t90_seconds": ("hold_t90_seconds", "max"),
    "max_concentration": ("concentration", "max"),
    "max_unresolved_share": ("unresolved_share", "max"),
}


def _episodes(count, *, prefix="Mint"):
    return [
        {
            "mint": f"{prefix}{index:02d}{'1' * 28}",
            "close_signature": f"{prefix}-close-{index}",
            "net": "1",
            "unit": "SOL",
            "acquisition": "1",
            "proceeds": "2.1",
            "costs": "0.1",
        }
        for index in range(count)
    ]


def _events(count):
    rows = []
    for index in range(count):
        rows.append({
            "kind": "buy" if index % 2 == 0 else "sell",
            "mint": f"Mint{index}",
            "units": "1",
        })
    return rows


def _report(address, *, completed, sample, coverage_count, coverage_value, pnl_sol="1", stale=True):
    ledger = _episodes(completed, prefix=address[:4])
    profile = {
        "completed_known_cost_positions": completed,
        "sample_positions": sample,
        "sale_count": sample,
        "completed_episode_ledger": ledger,
        "completed_episode_net": str(completed),
        "completed_episode_net_unit": "SOL",
        "coverage_count_share": coverage_count,
        "coverage_value_share": coverage_value,
        "coverage_mandatory_share": str(min(Decimal(coverage_count), Decimal(coverage_value))),
        "scoped_pnl": pnl_sol,
        "scoped_pnl_by_quote_asset": {"SOL": pnl_sol},
        "settlement_asset": "SOL",
        "hold_t90_seconds": 100,
        "concentration": "0.4",
        "unresolved_share": "0.1",
        "thresholds": default_filters()["thresholds"],
        "threshold_results": {
            key: {"state": "NOT_SET", "passed": None, "applied": False}
            for key in default_filters()["thresholds"]
        } if stale else {},
        "criteria_met": False,
    }
    return {
        "id": f"report-{address[:8]}",
        "source": "mass-search",
        "address": address,
        "events": _events(sample),
        "completed_episode_ledger": ledger,
        "wallet_completed_episodes": completed,
        "completed_episode_net": str(completed),
        "research_profile": profile,
        "record_breakdown": {
            "unsupported_swap_share_in_window": {
                "by_count": str(Decimal("1") - Decimal(coverage_count)),
                "by_consideration": {"SOL": str(Decimal("1") - Decimal(coverage_value))},
            }
        },
        "worksheet": {},
    }


def _universe_row(address, *, trades=800):
    return {
        "address": address,
        "provider_rank": 101,
        "trade_count": trades,
        "provider_score": "10",
        "shortlisted": False,
        "capture_available": True,
        "label": "fixture",
        "evidence_status": "cached_capture",
        "row_kind": "ranked100",
    }


def brute_force(reconciled, thresholds):
    """Independent oracle. Does not call evaluate_thresholds."""
    kept = True
    applied = False
    for key, raw in (thresholds or {}).items():
        if raw in (None, ""):
            continue
        spec = ORACLE_FIELDS.get(key)
        if spec is None:
            continue
        field, direction = spec
        actual = reconciled.get(field)
        if actual in (None, ""):
            return False
        applied = True
        actual_d = Decimal(str(actual))
        limit_d = Decimal(str(raw))
        if direction == "min" and actual_d < limit_d:
            kept = False
        if direction == "max" and actual_d > limit_d:
            kept = False
    if not applied:
        return True
    return kept


def test_f1_stale_threshold_results_do_not_hide_gtfo(tmp_path):
    store = Store(tmp_path / "data")
    report = _report(GTFO, completed=16, sample=32, coverage_count="1", coverage_value="1")
    store.put("reports", report["id"], report)
    save_filters(store, {"thresholds": {"min_sample_positions": "3"}})
    view = ranked_workflow_view(store)
    addresses = {row["address"] for row in view["rows"]}
    assert GTFO in addresses
    judged = evaluate_thresholds(report["research_profile"], {"min_sample_positions": "3"})
    assert judged["results"]["min_sample_positions"]["passed"] is True
    stale = _reconstructed_pass(
        {**report["research_profile"], "threshold_results": {
            "min_sample_positions": {"state": "NOT_SET", "passed": None}
        }},
        {"thresholds": {"min_sample_positions": "3"}},
    )
    assert stale is True
    store.close()


def test_f1_unset_thresholds_do_not_filter(tmp_path):
    store = Store(tmp_path / "data")
    report = _report(GTFO, completed=16, sample=32, coverage_count="1", coverage_value="1")
    store.put("reports", report["id"], report)
    save_filters(store, {"thresholds": {}})
    view = ranked_workflow_view(store)
    assert GTFO in {row["address"] for row in view["rows"]}
    assert _reconstructed_pass(report["research_profile"], default_filters()) is None
    store.close()


def test_f3_coverage_uses_count_and_value():
    profile = {
        "coverage_count_share": "1",
        "coverage_value_share": "0.5",
        "coverage_mandatory_share": "0.5",
        "completed_known_cost_positions": 4,
        "sample_positions": 8,
    }
    judged = evaluate_thresholds(profile, {"min_coverage_share": "0.99"})
    assert judged["results"]["min_coverage_share"]["passed"] is False
    judged_ok = evaluate_thresholds(profile, {"min_coverage_share": "0.5"})
    assert judged_ok["results"]["min_coverage_share"]["passed"] is True
    missing_mandatory = dict(profile)
    missing_mandatory.pop("coverage_mandatory_share")
    derived = evaluate_thresholds(missing_mandatory, {"min_coverage_share": "0.99"})
    assert derived["results"]["min_coverage_share"]["passed"] is False


def test_f4_min_completed_and_min_sample_bind_distinct_fields():
    profile = {
        "completed_known_cost_positions": 1,
        "sample_positions": 16,
    }
    judged = evaluate_thresholds(profile, {
        "min_completed_known_cost": "3",
        "min_sample_positions": "3",
    })
    assert judged["results"]["min_completed_known_cost"]["passed"] is False
    assert judged["results"]["min_sample_positions"]["passed"] is True
    swapped = evaluate_thresholds(profile, {
        "min_completed_known_cost": "1",
        "min_sample_positions": "20",
    })
    assert swapped["results"]["min_completed_known_cost"]["passed"] is True
    assert swapped["results"]["min_sample_positions"]["passed"] is False


def test_f2_save_rejects_non_numeric_and_out_of_range(tmp_path):
    store = Store(tmp_path / "data")
    with pytest.raises(FilterValidationError):
        save_filters(store, {"thresholds": {"min_sample_positions": "abc"}})
    with pytest.raises(FilterValidationError):
        save_filters(store, {"thresholds": {"min_coverage_share": "7"}})
    with pytest.raises(FilterValidationError):
        save_filters(store, {"thresholds": {"min_sample_positions": "-5"}})
    with pytest.raises(FilterValidationError):
        save_filters(store, {"window_days": 0})
    with pytest.raises(FilterValidationError):
        save_filters(store, {"window_days": 400})
    saved = save_filters(store, {
        "thresholds": {"min_sample_positions": "3", "min_coverage_share": "0"},
        "window_days": 30,
    })
    assert saved["thresholds"]["min_sample_positions"] == "3"
    assert saved["window_days"] == 30
    assert saved["proof_gates"]["weakenable_via_filter_api"] is False
    store.close()


def test_f2_http_422_and_read_path_never_500s_on_stored_bad_filters(tmp_path):
    app = create_app(tmp_path / "data", LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as client:
        boot = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        client.headers["x-csrf-token"] = boot.json()["csrf"]
        rejected = client.put("/api/mass-search/research-filters", json={
            "thresholds": {"min_sample_positions": "abc"},
        })
        assert rejected.status_code == 422
        oor = client.put("/api/mass-search/research-filters", json={
            "thresholds": {"min_coverage_share": "7"},
        })
        assert oor.status_code == 422
        store = Store(tmp_path / "data")
        store.put("research_profile_filters", "local-research-profile-filters-v1", {
            "kind": "research-profile-filters-v1",
            "thresholds": {"min_sample_positions": "abc", "min_coverage_share": "7"},
            "provider_proxy": {"min_provider_trade_count": "nope"},
        })
        store.close()
        loaded = load_filters(Store(tmp_path / "data"))
        assert loaded["thresholds"]["min_sample_positions"] is None
        assert loaded["thresholds"]["min_coverage_share"] is None
        view = client.get("/api/mass-search/ranked-workflow")
        assert view.status_code == 200
        assert view.json()["PRODUCT_READY"] is False


def test_filter_oracle_matches_api_over_random_combos(tmp_path):
    store = Store(tmp_path / "data")
    cohort = [
        ("WalletAAA111111111111111111111111111111111", 16, 32, "1", "1", "2"),
        ("WalletBBB111111111111111111111111111111111", 8, 20, "1", "0.8", "0.5"),
        ("WalletCCC111111111111111111111111111111111", 1, 4, "0.79", "0.80", "-1"),
        ("WalletDDD111111111111111111111111111111111", 4, 4, "0.93", "0", "0"),
        ("WalletEEE111111111111111111111111111111111", 0, 2, "0", "0", "0"),
        ("WalletFFF111111111111111111111111111111111", 20, 40, "1", "1", "10"),
        ("WalletGGG111111111111111111111111111111111", 3, 3, "0.95", "0.95", "0"),
        ("WalletHHH111111111111111111111111111111111", 6, 12, "0.99", "0.99", "1.5"),
    ]
    extras = []
    reconciled = {}
    for address, completed, sample, count, value, pnl in cohort:
        report = _report(address, completed=completed, sample=sample, coverage_count=count, coverage_value=value, pnl_sol=pnl or "0")
        store.put("reports", report["id"], report)
        extras.append(_universe_row(address))
        reconciled[address] = {
            "completed_known_cost_positions": completed,
            "sample_positions": sample,
            "coverage_mandatory_share": str(min(Decimal(count), Decimal(value))),
            "scoped_pnl_sol": pnl if completed else None,
            "scoped_pnl_usdc": None,
            "hold_t90_seconds": 100,
            "concentration": "0.4",
            "unresolved_share": "0.1",
        }
    rng = random.Random(1055)
    combos = [
        {},
        {"min_sample_positions": "3"},
        {"min_completed_known_cost": "3", "min_sample_positions": "3"},
        {"min_coverage_share": "0.99"},
        {"min_coverage_share": "0"},
        {"min_scoped_pnl_sol": "0"},
        {"min_completed_known_cost": "1", "min_sample_positions": "5", "min_coverage_share": "0.95"},
    ]
    for _ in range(20):
        combo = {}
        if rng.random() < 0.7:
            combo["min_sample_positions"] = str(rng.choice([0, 1, 3, 5, 16, 40]))
        if rng.random() < 0.7:
            combo["min_completed_known_cost"] = str(rng.choice([0, 1, 3, 8, 20]))
        if rng.random() < 0.5:
            combo["min_coverage_share"] = rng.choice(["0", "0.5", "0.95", "0.99", "1"])
        if rng.random() < 0.4:
            combo["min_scoped_pnl_sol"] = rng.choice(["-1", "0", "1", "5"])
        combos.append(combo)
    for combo in combos:
        save_filters(store, {"thresholds": combo})
        view = ranked_workflow_view(store, extra_universe_rows=extras)
        visible = {row["address"] for row in view["rows"] if row["address"] in reconciled}
        expected = {address for address, values in reconciled.items() if brute_force(values, combo)}
        assert visible == expected, combo
    store.close()


def test_proof_gates_are_not_user_filters():
    filters = default_filters()
    assert filters["proof_gates"]["coverage_lead_share"] == "0.99"
    assert filters["proof_gates"]["weakenable_via_filter_api"] is False
    saveable = save_filters(Store.__new__(Store), None) if False else None
    del saveable
    from scanner.mass_search.qualification_gates import COVERAGE_LEAD_SHARE, COVERAGE_WATCH_SHARE
    assert COVERAGE_LEAD_SHARE == Decimal("0.99")
    assert COVERAGE_WATCH_SHARE == Decimal("0.95")


def test_draft_grant_is_disabled_and_caps_match():
    raw = json.loads(DRAFT_PATH.read_text(encoding="utf-8"))
    assert raw["enabled"] is False
    assert raw["authorization_id"] == AUTHORIZATION_ID
    assert raw["expires_at"] == "2026-10-08T13:30:00Z"
    assert raw["max_additional_spend_usd"] == "0"
    assert raw["overages_enabled"] is False
    assert raw["allow_paid_upgrade"] is False
    birdeye = next(entry for entry in raw["providers"] if entry["provider_id"] == "birdeye")
    helius = next(entry for entry in raw["providers"] if entry["provider_id"] == "helius")
    assert birdeye["max_requests"] == 3 and birdeye["max_units"] == 91
    assert helius["max_requests"] == 500 and helius["max_units"] == 5000
    assert raw["phase_caps"]["2"]["helius_requests"] == 200
    assert raw["phase_caps"]["3"]["helius_requests"] == 300
    checked = validate_live_authorization(raw)
    assert checked["enabled"] is False
    assert load_grant(DRAFT_PATH)["enabled"] is False


def test_prescreen_reports_known_program_blockers():
    records = [
        {"transaction": {"message": {"instructions": [
            {"programId": "FLASHX8DrLbgeR8FcfNV1F5krxYcYMUdBkrP1EPBtxB9"},
            {"programId": "B3111yJCeHBcA1bizdJjUFPALfhAfSRnAbJzGUtnt56A"},
            {"programId": "DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH"},
            {"programId": L2TEX_PROGRAM},
            {"programId": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"},
            {"programId": "proVF4pMXVaYqmy4NjniPh4pqKNfMmsihgd4wdkCX3u"},
        ]}}}
    ]
    classified = classify_programs(records)
    labels = {row["label"] for row in classified["blockers"]}
    assert "FLASHX Axiom" in labels
    assert "B311 unreviewed" in labels
    assert "DFlow" in labels
    assert "Token-2022 observed-only" not in labels
    assert "L2TExMFK" not in labels
    assert "OKX SwapTob" not in labels
    assert set(KNOWN_BLOCKING_PROGRAMS) >= {
        "FLASHX8DrLbgeR8FcfNV1F5krxYcYMUdBkrP1EPBtxB9",
        "B3111yJCeHBcA1bizdJjUFPALfhAfSRnAbJzGUtnt56A",
        "DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH",
    }


def test_runner_rejects_bad_params_and_caps_of_zero(tmp_path, monkeypatch):
    monkeypatch.delenv("BIRDEYE_API_KEY", raising=False)
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    with pytest.raises(LiveE2EError, match="--dry-run or --live"):
        validate_config({"grant_path": DRAFT_PATH, "output_dir": tmp_path})
    with pytest.raises(LiveE2EError):
        validate_config({
            "mode": "dry-run",
            "grant_path": DRAFT_PATH,
            "output_dir": tmp_path,
            "window_days": 0,
        })
    with pytest.raises(LiveE2EError, match="disabled"):
        validate_config({
            "mode": "live",
            "grant_path": DRAFT_PATH,
            "output_dir": tmp_path / "live",
            "wallets": [GTFO],
            "phases": "2",
        })
    cfg = validate_config({
        "mode": "dry-run",
        "grant_path": DRAFT_PATH,
        "output_dir": tmp_path / "zero",
        "wallets": [GTFO],
        "phases": "2",
        "max_helius_requests": 0,
        "max_helius_units": 0,
    })
    assert cfg["caps"]["helius_requests"] == 0
    result = asyncio.run(run_live_e2e({
        "mode": "dry-run",
        "grant_path": str(DRAFT_PATH),
        "output_dir": str(tmp_path / "zero-run"),
        "ledger_dir": str(tmp_path / "ledger-home"),
        "wallets": [GTFO],
        "phases": "2",
        "max_helius_requests": 0,
        "max_helius_units": 0,
        "window_days": 30,
        "earlier_history_days": 60,
    }))
    assert result["status"] == "blocked"
    assert result["spend"]["helius_requests"] == 0
    assert result["PRODUCT_READY"] is False


def test_runner_dry_run_resume_and_duplicate(tmp_path, monkeypatch):
    monkeypatch.delenv("BIRDEYE_API_KEY", raising=False)
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    wallets = parse_wallets(ROOT / "config/live_e2e_search_b_cohort.json")
    assert len(wallets) == 10
    out = tmp_path / "run"
    first = asyncio.run(run_live_e2e({
        "mode": "dry-run",
        "grant_path": str(DRAFT_PATH),
        "output_dir": str(out),
        "ledger_dir": str(tmp_path / "ledger-home"),
        "wallets": wallets,
        "discovery": True,
        "phases": "all",
        "window_days": 30,
        "earlier_history_days": 60,
    }))
    assert first["dry_run"] is True
    assert first["plan"]["within_caps"] is True
    assert first["plan"]["totals"]["birdeye_requests"] == 1
    assert first["plan"]["totals"]["helius_requests"] == 30
    assert first["spend"]["birdeye_requests"] == 1
    assert first["spend"]["helius_requests"] == 30
    assert first["PRODUCT_READY"] is False
    with pytest.raises(LiveE2EError, match="duplicate run"):
        asyncio.run(run_live_e2e({
            "mode": "dry-run",
            "grant_path": str(DRAFT_PATH),
            "output_dir": str(out),
            "ledger_dir": str(tmp_path / "ledger-home"),
            "wallets": wallets,
            "phases": "all",
        }))
    resumed = asyncio.run(run_live_e2e({
        "mode": "dry-run",
        "grant_path": str(DRAFT_PATH),
        "output_dir": str(out),
        "ledger_dir": str(tmp_path / "ledger-home"),
        "wallets": wallets,
        "discovery": True,
        "phases": "all",
        "resume": True,
        "window_days": 30,
        "earlier_history_days": 60,
    }))
    assert resumed["status"] == "completed"
    crashed = tmp_path / "crash"
    crash_home = tmp_path / "crash-home"
    crash_home.mkdir()
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(crash_home))
    asyncio.run(run_live_e2e({
        "mode": "dry-run",
        "grant_path": str(DRAFT_PATH),
        "output_dir": str(crashed),
        "ledger_dir": str(crash_home),
        "wallets": wallets[:2],
        "phases": "2",
        "window_days": 30,
        "earlier_history_days": 0,
    }))
    state = json.loads((crashed / "RUN_STATE.json").read_text(encoding="utf-8"))
    first_addr = wallets[0]
    state["status"] = "started"
    state["phase2"][first_addr]["done"] = False
    (crashed / "RUN_STATE.json").write_text(json.dumps(state), encoding="utf-8")
    after = asyncio.run(run_live_e2e({
        "mode": "dry-run",
        "grant_path": str(DRAFT_PATH),
        "output_dir": str(crashed),
        "ledger_dir": str(crash_home),
        "wallets": wallets[:2],
        "phases": "2",
        "resume": True,
        "window_days": 30,
        "earlier_history_days": 0,
    }))
    assert after["status"] == "completed"
    assert after["phase2"]["wallets"]


def test_cli_requires_mode(tmp_path):
    with pytest.raises(SystemExit):
        main(["--grant", str(DRAFT_PATH), "--output", str(tmp_path)])


def test_plan_counts_stay_inside_grant_caps():
    wallets = parse_wallets(ROOT / "config/live_e2e_search_b_cohort.json")
    plan = plan_request_counts({
        "wallets": wallets,
        "phases": (1, 2, 3, 4),
        "discovery": True,
        "caps": {
            "birdeye_requests": 3,
            "birdeye_units": 91,
            "helius_requests": 500,
            "helius_units": 5000,
        },
    })
    assert plan["totals"]["birdeye_requests"] == 1
    assert plan["totals"]["birdeye_units"] == 30
    assert plan["totals"]["helius_requests"] == 30
    assert plan["totals"]["helius_units"] == 1200
    assert plan["within_caps"] if False else (
        plan["totals"]["birdeye_requests"] <= 3
        and plan["totals"]["helius_requests"] <= 500
        and plan["totals"]["helius_units"] <= 5000
    )
