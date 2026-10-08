"""Live-run 8b regressions. Offline only: no live calls, no secrets."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scanner.mass_search.adapters import BIRDEYE_TOKEN_TXS_PATH, SourceError
from scanner.mass_search.live_e2e import (
    AUTHORIZATION_ID_13,
    DRAFT_REL_13,
    HARD_CEILINGS,
    RecorderTransport,
    ROOT,
    discovered_seed_pool,
    empty_phase_spend,
    empty_spend,
    load_grant,
    phase1_discovery,
    phase2_prescreen,
    phase3_history,
    phase3_planned_pages,
    plan_request_counts,
    run_live_e2e,
    validate_config,
)
from scanner.mass_search.live_e2e_ledger import open_grant_store
from scanner.mass_search.qualification_gates import (
    BOT_RULE_DEFINITION,
    economic_trades_by_utc_day,
    independent_economic_trade_keys,
)
from scanner.mass_search.seed_sources import (
    NANSEN_LEADERBOARD_PATH,
    NANSEN_PNL_SUMMARY_PATH,
    SEED_NANSEN,
    SEED_TOKEN_INTERSECT,
    cost_per_audit_worthy,
    densest_utc_day_bounds,
    estimate_seed_plan,
    record_seed_metadata,
    select_nansen_wallets,
)
from tools.independent_episode_audit import (
    BOT_RULE_DEFINITION as AUDITOR_BOT_RULE,
    economic_trades_by_utc_day as auditor_economic_trades_by_utc_day,
    independent_economic_trade_keys as auditor_keys,
)

JXT = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
GYG = "Gygj9QQby4j2jryqyqBHvLP7ctv2SaANgh4sCb69BUpA"
JUP = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN_X = "TokenX1111111111111111111111111111111111111"
FIXTURE_DIR = ROOT / "tests/fixtures/seed_sources"
A = "EnaatNfHKJHifA6VsiZBm1dKKwY8z2aaqW8BhDYwvYJm"


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    home = tmp_path / "ledger-home"
    home.mkdir()
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(home))
    monkeypatch.setenv("SCANNER_BIRDEYE_BACKOFF_SEC", "0")
    monkeypatch.setenv("SCANNER_BIRDEYE_MIN_INTERVAL_SEC", "0")
    monkeypatch.delenv("NANSEN_API_KEY", raising=False)
    return home


def _fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _phase1_config(tmp_path, seed_source, tokens=None, **extra):
    raw = {
        "mode": "dry-run",
        "grant_path": str(ROOT / DRAFT_REL_13),
        "output_dir": str(tmp_path / "out"),
        "phases": "1",
        "discovery": True,
        "seed_source": seed_source,
        "birdeye_tokens": tokens or [],
        "wallets": "",
    }
    raw.update(extra)
    return validate_config(raw)


def test_seen_set_dedupes_across_timeframes():
    seen = set()
    first = select_nansen_wallets([{"address": A}], timeframe=90, seen=seen)
    second = select_nansen_wallets([{"address": A}], timeframe=180, seen=seen)
    assert len(first) == 1
    assert first[0].get("already_seen") is False
    assert len(second) == 1
    assert second[0]["already_seen"] is True
    assert second[0]["timeframe"] == 180
    assert A in seen


def test_nansen_keeps_per_timeframe_rank_metadata():
    state = {}
    record_seed_metadata(state, A, SEED_NANSEN, {
        "rank": 1, "timeframe": 90, "selection_reason": "nansen_pnl_leaderboard_90d",
        "vendor_metrics": {"realized_pnl_usd": 10},
    })
    record_seed_metadata(state, A, SEED_NANSEN, {
        "rank": 7, "timeframe": 180, "selection_reason": "nansen_pnl_leaderboard_180d",
        "vendor_metrics": {"realized_pnl_usd": 20},
    })
    meta = state["seed_metadata"][A]
    assert meta["rank"] == 1
    assert meta["timeframe"] == 90
    assert meta["timeframes"]["90"]["rank"] == 1
    assert meta["timeframes"]["180"]["rank"] == 7
    assert meta["timeframes"]["90"]["vendor_metrics"]["realized_pnl_usd"] == 10
    assert meta["timeframes"]["180"]["vendor_metrics"]["realized_pnl_usd"] == 20


def test_nansen_plan_equals_runtime_on_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", "offline-fixture-not-a-live-secret")
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "nansen", nansen_profile_cap=2)
    assert config["nansen_profile_cap"] == 2
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    recorder.fixtures = {
        NANSEN_LEADERBOARD_PATH: _fixture("nansen_leaderboard.json"),
        NANSEN_PNL_SUMMARY_PATH: {"data": {"realized_pnl_usd": 1}},
    }
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    plan = plan_request_counts(config, state)
    asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    assert plan["totals"]["nansen_requests"] >= state["spend"]["nansen_requests"]
    assert plan["totals"]["nansen_units"] >= state["spend"]["nansen_units"]
    assert plan["totals"]["nansen_requests"] == 4
    assert plan["totals"]["nansen_units"] == 12
    assert plan["seed_plan"]["per_source"][SEED_NANSEN]["profiler_requests"] == 2


def test_nansen_plan_is_upper_bound_of_live_8b_spend():
    plan = estimate_seed_plan(
        [SEED_NANSEN],
        discovery=True,
        nansen_enabled=True,
        nansen_request_cap=18,
        nansen_unit_cap=90,
    )
    assert plan["totals"]["nansen_requests"] == 18
    assert plan["totals"]["nansen_units"] == 26


def test_phase3_plan_subtracts_triage_from_per_wallet_cap():
    config = {
        "wallets": [JXT, GYG],
        "wallets_supplied": True,
        "phases": (3,),
        "window_days": 30,
        "earlier_history_days": 60,
        "per_wallet_cap": 6,
        "seed_sources": [SEED_NANSEN],
        "caps": dict(HARD_CEILINGS),
    }
    state = {
        "phase2": {
            JXT: {"address": JXT, "dropped": False, "requests": 3, "triage": True, "in_window_tx_count": 1000},
            GYG: {"address": GYG, "dropped": False, "requests": 3, "triage": True, "in_window_tx_count": 1000},
        }
    }
    plan = plan_request_counts(config, state)
    worst = sum(max(0, 6 - 3) for _ in plan["phase3_page_estimates"])
    assert plan["totals"]["helius_requests"] <= worst
    assert plan["phase3_page_estimates"][JXT] == 3
    assert phase3_planned_pages(config, state, JXT, 9, triage=True) == 3


def test_token_intersect_keeps_paid_pages_on_final_429(tmp_path):
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "token_intersect", [JUP, BONK, USDC])
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    recorder.fixtures = {BIRDEYE_TOKEN_TXS_PATH: _fixture("token_txs_seek.json")}
    recorder.fail_at = {BIRDEYE_TOKEN_TXS_PATH: {"after": 8}}
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    result = asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    fail = (state.get("seed_source_failures") or {}).get(SEED_TOKEN_INTERSECT) or {}
    assert fail.get("state") == "RATE_LIMITED"
    assert fail.get("stop_after_failure") is False
    assert int(fail.get("retained_pages") or 0) >= 7
    assert JXT in result["addresses"]
    assert result["count"] >= 1
    paid = ((state.get("source_spend") or {}).get(SEED_TOKEN_INTERSECT) or {}).get("requests") or 0
    assert paid >= 7
    seeds = sum(
        int(row.get("count") or 0)
        for key, row in (state.get("discoveries") or {}).items()
        if str(key).endswith("|token_intersect")
    )
    assert not (paid >= 8 and seeds == 0)


def test_token_intersect_retries_429_then_keeps_going(tmp_path):
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "token_intersect", [JUP, BONK, USDC])
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    recorder.fixtures = {BIRDEYE_TOKEN_TXS_PATH: _fixture("token_txs_seek.json")}
    recorder.fail_at = {BIRDEYE_TOKEN_TXS_PATH: {"after": 4, "times": 1}}
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    result = asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    assert JXT in result["addresses"]
    assert not (state.get("seed_source_failures") or {}).get(SEED_TOKEN_INTERSECT)
    tx_calls = [call for call in recorder.calls if call["path"] == BIRDEYE_TOKEN_TXS_PATH]
    assert len(tx_calls) == 10  # 9 pages + 1 retried 429


def test_resume_uses_retained_token_intersect_pages(tmp_path):
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "token_intersect", [JUP, BONK, USDC])
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    recorder.fixtures = {BIRDEYE_TOKEN_TXS_PATH: _fixture("token_txs_seek.json")}
    recorder.fail_at = {BIRDEYE_TOKEN_TXS_PATH: {"after": 8}}
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    first = asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    first_calls = len(recorder.calls)
    second = asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    assert second.get("per_source", {}).get(SEED_TOKEN_INTERSECT, {}).get("replayed_from_receipt") or JXT in second["addresses"]
    assert len(recorder.calls) == first_calls
    assert JXT in first["addresses"]


def test_resume_phase2_loads_phase1_pool(tmp_path):
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "token_intersect", [JUP, BONK, USDC])
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    recorder.fixtures = {BIRDEYE_TOKEN_TXS_PATH: _fixture("token_txs_seek.json")}
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    assert JXT in state["wallets"]
    resume = validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / DRAFT_REL_13),
        "output_dir": config["output_dir"],
        "phases": "2",
        "discovery": False,
        "seed_source": "token_intersect",
        "wallets": "",
        "resume": True,
    })
    assert resume["wallets"] == []
    loaded = discovered_seed_pool(resume, state)
    assert JXT in loaded
    resume["wallets"] = loaded
    store, _ = open_grant_store(resume["authorization_id"])
    result = asyncio.run(phase2_prescreen(store, grant, resume, state, RecorderTransport()))
    store.close()
    assert result["wallets"]
    assert 2 not in (state.get("phases_done") or []) or len(state.get("phase2") or {}) == len(state["wallets"])


def test_empty_pool_after_phase1_seeds_is_error_not_done(tmp_path):
    from scanner.mass_search.live_e2e import save_state, STATE_NAME

    out = tmp_path / "out"
    out.mkdir()
    state = {
        "wallets": [],
        "discoveries": {"id|nansen": {"count": 53, "addresses": [], "seed_source": SEED_NANSEN}},
        "phases_done": [1],
        "spend": empty_spend(),
        "phase_spend": empty_phase_spend(),
        "status": "completed",
        "bounds": validate_config({
            "mode": "dry-run",
            "grant_path": str(ROOT / DRAFT_REL_13),
            "output_dir": str(out),
            "phases": "1",
            "discovery": True,
            "seed_source": "nansen",
            "wallets": "",
        })["bounds"],
        "PRODUCT_READY": False,
    }
    save_state(out, state)
    result = asyncio.run(run_live_e2e({
        "mode": "dry-run",
        "grant_path": str(ROOT / DRAFT_REL_13),
        "output_dir": str(out),
        "phases": "2",
        "discovery": False,
        "seed_source": "nansen",
        "wallets": "",
        "resume": True,
    }))
    persisted = json.loads((out / STATE_NAME).read_text(encoding="utf-8"))
    assert result["status"] == "blocked"
    assert result["blocker"] == "EMPTY_SEED_POOL"
    assert 2 not in (persisted.get("phases_done") or [])


def test_triage_third_sample_uses_densest_day():
    day = datetime(2026, 9, 10, tzinfo=timezone.utc)
    start = int(day.timestamp())
    samples = [{
        "events": [
            {"kind": "buy", "signature": f"s{i}", "mint": "M", "timestamp": start + i}
            for i in range(12)
        ]
    }]
    densest = densest_utc_day_bounds(samples)
    assert densest["day"] == "2026-09-10"
    assert densest["trades"] == 12


def test_phase3_early_stops_after_gt25_page(tmp_path, monkeypatch):
    day = int(datetime(2026, 9, 10, tzinfo=timezone.utc).timestamp())
    events = [
        {"kind": "buy", "signature": f"hot{i}", "mint": f"M{i}", "timestamp": day + i}
        for i in range(26)
    ]
    monkeypatch.setattr(
        "scanner.mass_search.live_e2e.decode_supported_swaps",
        lambda records, address: {"events": events},
    )

    async def fake_dispatch(store, grant, config, state, transport, address, options, *, phase, page_index):
        return {
            "records": [{"signature": f"hot{i}", "blockTime": day + i} for i in range(26)],
            "pagination_token": "more",
            "evidence_sha256": "abc",
        }

    monkeypatch.setattr("scanner.mass_search.live_e2e._dispatch_helius", fake_dispatch)
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / DRAFT_REL_13),
        "output_dir": str(tmp_path / "out"),
        "phases": "3",
        "discovery": False,
        "seed_source": "nansen",
        "wallets": JXT,
        "per_wallet_cap": 6,
    })
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    state = {
        "spend": empty_spend(),
        "phase_spend": empty_phase_spend(),
        "wallets": [JXT],
        "phase2": {JXT: {"address": JXT, "dropped": False, "requests": 3, "triage": True}},
        "seed_metadata": {JXT: {"seed_sources": [SEED_NANSEN], "primary_seed_source": SEED_NANSEN}},
    }
    result = asyncio.run(phase3_history(store, grant, config, state, RecorderTransport()))
    store.close()
    cursor = result["pages"][JXT]
    assert cursor["pages"] == 1
    assert cursor["early_stop_bot_rate"] is True
    assert cursor["history_complete_reason"] == "gt_15_economic_trades_in_one_day"


def test_phase3_resume_deepens_capped_history_without_refetch(tmp_path, monkeypatch):
    calls = []

    async def fake_dispatch(store, grant, config, state, transport, address, options, *, phase, page_index):
        calls.append(page_index)
        return {
            "records": [{"signature": f"p{page_index}", "blockTime": 1_800_000_000 - page_index}],
            "pagination_token": f"tok{page_index}",
            "evidence_sha256": f"sha{page_index}",
        }

    monkeypatch.setattr("scanner.mass_search.live_e2e._dispatch_helius", fake_dispatch)
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / DRAFT_REL_13),
        "output_dir": str(tmp_path / "out"),
        "phases": "3",
        "discovery": False,
        "seed_source": "nansen",
        "wallets": JXT,
        "per_wallet_cap": 4,
        "history_to_first": True,
    })
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    config["dry_run"] = False
    store, _ = open_grant_store(config["authorization_id"])
    state = {
        "spend": empty_spend(),
        "phase_spend": empty_phase_spend(),
        "wallets": [JXT],
        "phase2": {JXT: {"address": JXT, "dropped": False, "requests": 3, "triage": True}},
    }
    first = asyncio.run(phase3_history(store, grant, config, state, RecorderTransport()))
    assert first["pages"][JXT]["pages"] == 1
    assert first["pages"][JXT]["history_complete_reason"] == "per_wallet_cap"
    assert calls == [0]
    config["per_wallet_cap"] = 6
    second = asyncio.run(phase3_history(store, grant, config, state, RecorderTransport()))
    store.close()
    assert calls == [0, 1, 2]
    assert second["pages"][JXT]["pages"] == 3
    assert second["pages"][JXT]["history_complete_reason"] == "per_wallet_cap"
    assert second["pages"][JXT]["leftover_pagination_token"] is True


def test_bot_rule_counts_token_to_token_and_not_hops():
    assert BOT_RULE_DEFINITION == AUDITOR_BOT_RULE
    hop_sig = "multi-hop-1"
    events = [
        {"kind": "route_leg", "signature": hop_sig, "mint": "A", "timestamp": 1_775_000_000},
        {"kind": "route_leg", "signature": hop_sig, "mint": "B", "timestamp": 1_775_000_000},
        {"kind": "buy", "signature": hop_sig, "mint": TOKEN_X, "timestamp": 1_775_000_000},
        {"kind": "sell", "signature": hop_sig, "mint": "So11111111111111111111111111111111111111112", "timestamp": 1_775_000_000},
        {"kind": "buy", "signature": hop_sig, "mint": TOKEN_X, "timestamp": 1_775_000_000},
        {"kind": "buy", "signature": "t2t", "mint": TOKEN_X, "timestamp": 1_775_000_100},
        {"kind": "sell", "signature": "t2t", "mint": BONK, "timestamp": 1_775_000_100},
    ]
    by_day = economic_trades_by_utc_day(events)
    assert sum(by_day.values()) == 4
    assert len(independent_economic_trade_keys(events)) == 4
    assert auditor_economic_trades_by_utc_day(events) == by_day
    assert auditor_keys(events) == independent_economic_trade_keys(events)


def test_cost_per_audit_includes_helius_phase3():
    out = cost_per_audit_worthy(
        {
            SEED_NANSEN: {
                "units": 26 + 13790,
                "requests": 18 + 281,
                "provider": "nansen",
                "by_provider": {
                    "nansen": {"requests": 18, "units": 26},
                    "helius": {"requests": 281, "units": 13790},
                },
            }
        },
        {SEED_NANSEN: 1},
    )
    row = out[SEED_NANSEN]
    assert row["by_provider"]["helius"]["units"] == 13790
    assert row["all_providers_units"] == 26 + 13790
    assert row["cost_per_audit_worthy_all_providers"] == "13816.0000"


def test_arg_parser_has_nansen_profile_cap():
    from scanner.mass_search.live_e2e import build_arg_parser

    args = build_arg_parser().parse_args([
        "--dry-run", "--grant", "config/x.json", "--output", "/tmp/out",
        "--nansen-profile-cap", "16",
    ])
    assert args.nansen_profile_cap == 16
