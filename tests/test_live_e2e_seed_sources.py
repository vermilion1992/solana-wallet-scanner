"""Offline seed-source tests. No live calls, no secrets."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from scanner.mass_search.adapters import (
    BIRDEYE_FIRST_BUYERS_PATH,
    BIRDEYE_TOKEN_LIST_PATH,
)
from scanner.mass_search.live_e2e import (
    AUTHORIZATION_ID_13,
    DRAFT_REL_13,
    HARD_CEILINGS,
    PINNED_DRAFT_HASHES,
    RecorderTransport,
    ROOT,
    apply_cheap_prescreen_phase1,
    build_arg_parser,
    discovery_identity,
    empty_phase_spend,
    empty_spend,
    load_grant,
    phase1_discovery,
    plan_request_counts,
    validate_config,
)
from scanner.mass_search.live_e2e_ledger import open_grant_store
from scanner.mass_search.seed_sources import (
    LEADERBOARD_VIABILITY,
    SEED_EARLY_BUYERS,
    SEED_PRESCREEN_FILTER,
    SEED_SMART_MONEY,
    SeedSourceError,
    cheap_prescreen_decision,
    estimate_seed_plan,
    first_buyer_rows,
    history_span_days,
    leaderboard_not_viable_reason,
    parse_seed_sources,
    resolve_seed_sources,
    select_durable_tokens,
    select_early_buyers_sold_well,
    token_list_items,
)

FIXTURE_DIR = ROOT / "tests/fixtures/seed_sources"
JXT = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
JUP = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    home = tmp_path / "ledger-home"
    home.mkdir()
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(home))
    return home


def _fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_leaderboards_are_not_viable_without_a_key():
    assert LEADERBOARD_VIABILITY["gmgn"]["viable"] is False
    assert LEADERBOARD_VIABILITY["cielo"]["requires_key"] is True
    assert LEADERBOARD_VIABILITY["kolscan"]["official_api"] is False
    reason = leaderboard_not_viable_reason()
    assert "GMGN" in reason and "Cielo" in reason and "Kolscan" in reason


def test_parse_seed_source_cli_and_combinations():
    assert parse_seed_sources("") == []
    assert parse_seed_sources("early-buyers-durable,prescreen-filter") == [
        SEED_EARLY_BUYERS, SEED_PRESCREEN_FILTER,
    ]
    with pytest.raises(SeedSourceError):
        parse_seed_sources("early-buyers-durable,top-traders")
    with pytest.raises(SeedSourceError):
        parse_seed_sources("nansen")
    sources = resolve_seed_sources(["prescreen-filter"], "gainers-losers")
    assert sources == ["gainers-losers", "prescreen-filter"]


def test_arg_parser_has_seed_source():
    parser = build_arg_parser()
    args = parser.parse_args([
        "--dry-run",
        "--grant", "config/x.json",
        "--output", "/tmp/out",
        "--seed-source", "early-buyers-durable,prescreen-filter",
    ])
    assert args.seed_source == "early-buyers-durable,prescreen-filter"


def test_new_draft_grant_is_disabled_and_hashed():
    path = ROOT / DRAFT_REL_13
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["enabled"] is False
    assert raw["PRODUCT_READY"] is False
    assert raw["authorization_id"] == AUTHORIZATION_ID_13
    assert raw["providers"][0]["allowed_operations"] == [
        "trader_gainers_losers", "token_top_traders", "token_list", "token_first_buyers",
    ]
    leaderboard = next(row for row in raw["providers"] if row["provider_id"] == "leaderboard")
    assert leaderboard["max_requests"] == 0
    assert leaderboard["max_units"] == 0
    assert leaderboard["allowed_operations"] == []
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert PINNED_DRAFT_HASHES[AUTHORIZATION_ID_13] == digest
    assert HARD_CEILINGS["leaderboard_requests"] == 0
    assert HARD_CEILINGS["leaderboard_units"] == 0


def test_plan_estimates_per_source():
    early = estimate_seed_plan([SEED_EARLY_BUYERS], discovery=True)
    assert early["totals"]["birdeye_requests"] == 5
    assert early["totals"]["birdeye_units"] == 60 + 4 * 25
    assert early["seed_is_not"] == "evidence"
    supplied = estimate_seed_plan(
        [SEED_EARLY_BUYERS], tokens=[JUP, JUP], discovery=True,
    )
    assert supplied["per_source"][SEED_EARLY_BUYERS]["token_list_requests"] == 0
    assert supplied["totals"]["birdeye_requests"] == 2
    assert supplied["totals"]["birdeye_units"] == 50
    smart = estimate_seed_plan([SEED_SMART_MONEY], discovery=True)
    assert smart["totals"]["leaderboard_requests"] == 0
    assert smart["per_source"][SEED_SMART_MONEY]["viable"] is False
    plan = plan_request_counts({
        "wallets": [],
        "phases": (1,),
        "discovery": True,
        "seed_sources": [SEED_EARLY_BUYERS],
        "discovery_source": SEED_EARLY_BUYERS,
        "birdeye_tokens": [],
        "caps": HARD_CEILINGS,
    })
    assert plan["seed_sources"] == [SEED_EARLY_BUYERS]
    assert plan["totals"]["birdeye_requests"] == 5
    assert plan["totals"]["birdeye_units"] == 160
    assert plan["seed_plan"]["seed_is_not"] == "evidence"


def test_durable_token_and_first_buyer_fixtures():
    tokens = select_durable_tokens(
        token_list_items(_fixture("token_list_durable.json")),
        now_unix=1791331200,
    )
    assert [row["address"] for row in tokens] == [
        JUP,
        "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    ]
    buyers = select_early_buyers_sold_well(
        first_buyer_rows(_fixture("first_buyers_sold_well.json")),
        token=JUP,
    )
    assert JXT in {row["address"] for row in buyers}
    assert all(row["position_status"] in ("sell_partial", "sell_all") for row in buyers)
    assert buyers[0]["seed_is_not"] == "evidence"
    assert buyers[0]["position_status"] == "sell_partial"


def test_cheap_prescreen_uses_captured_signals_only():
    hot = cheap_prescreen_decision({"trade_count": 900, "window_days": 30})
    assert hot["dropped"] is True
    assert "cheap_prescreen_high_trade_rate" in hot["drop_reasons"]
    young = cheap_prescreen_decision({"history_days": 12, "trades_per_day": 3})
    assert young["dropped"] is True
    assert "cheap_prescreen_short_history" in young["drop_reasons"]
    ok = cheap_prescreen_decision({"trade_count": 40, "window_days": 30, "history_days": 90})
    assert ok["dropped"] is False
    assert history_span_days([{"blockTime": 100}, {"blockTime": 100 + 86400}], created_in_range=False) is None
    spanned = history_span_days(
        [{"blockTime": 1_700_000_000}, {"blockTime": 1_700_000_000 + 5 * 86400}],
        created_in_range=True,
        now_unix=1_700_000_000 + 5 * 86400,
    )
    assert str(spanned) == "5.0000"


def _phase1_config(tmp_path, seed_source, tokens=None):
    return validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / DRAFT_REL_13),
        "output_dir": str(tmp_path / "out"),
        "phases": "1",
        "discovery": True,
        "seed_source": seed_source,
        "birdeye_tokens": tokens or [],
        "wallets": "",
    })


def test_early_buyers_dry_run_replays_recorded_fixtures(tmp_path):
    grant = load_grant(ROOT / DRAFT_REL_13)
    assert grant.get("enabled") is False
    config = _phase1_config(tmp_path, "early-buyers-durable")
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    recorder.fixtures = {
        BIRDEYE_TOKEN_LIST_PATH: _fixture("token_list_durable.json"),
        BIRDEYE_FIRST_BUYERS_PATH: _fixture("first_buyers_sold_well.json"),
    }
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    result = asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    assert result["seed_source"] == SEED_EARLY_BUYERS
    assert result["seed_is_not"] == "evidence"
    assert JXT in result["addresses"]
    assert JXT in config["wallets"]
    assert state["seed_metadata"][JXT]["primary_seed_source"] == SEED_EARLY_BUYERS
    assert state["spend"]["birdeye_requests"] >= 2
    paths = {call["path"] for call in recorder.calls}
    assert BIRDEYE_TOKEN_LIST_PATH in paths
    assert BIRDEYE_FIRST_BUYERS_PATH in paths


def test_smart_money_dry_run_records_not_viable(tmp_path):
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "smart-money-leaderboard")
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    result = asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    assert result["viable"] is False
    assert result["addresses"] == []
    assert result["seed_source"] == SEED_SMART_MONEY
    assert "No viable" in result["blocker"]
    assert recorder.calls == []
    assert state["spend"]["birdeye_requests"] == 0


def test_smart_money_live_is_refused(tmp_path):
    from scanner.mass_search.adapters import SourceError

    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "smart-money-leaderboard")
    config["dry_run"] = False
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    with pytest.raises(SourceError) as caught:
        asyncio.run(phase1_discovery(store, grant, config, state, RecorderTransport()))
    store.close()
    assert caught.value.state == "NOT_VIABLE"


def test_phase1_cheap_filter_drops_high_rate_before_history(tmp_path):
    config = _phase1_config(tmp_path, "gainers-losers,prescreen-filter")
    state = {
        "wallets": [JXT, "Gygj9QQby4j2jryqyqBHvLP7ctv2SaANgh4sCb69BUpA"],
        "seed_metadata": {
            JXT: {"seed_sources": ["gainers-losers"], "primary_seed_source": "gainers-losers", "trade_count": 40},
            "Gygj9QQby4j2jryqyqBHvLP7ctv2SaANgh4sCb69BUpA": {
                "seed_sources": ["gainers-losers"],
                "primary_seed_source": "gainers-losers",
                "trade_count": 900,
            },
        },
    }
    config["seed_sources"] = ["gainers-losers", "prescreen-filter"]
    config["birdeye_window"] = "30d"
    dropped = apply_cheap_prescreen_phase1(config, state)
    assert dropped == ["Gygj9QQby4j2jryqyqBHvLP7ctv2SaANgh4sCb69BUpA"]
    assert config["wallets"] == [JXT]
    assert SEED_PRESCREEN_FILTER in state["seed_metadata"]["Gygj9QQby4j2jryqyqBHvLP7ctv2SaANgh4sCb69BUpA"]["seed_sources"]


def test_discovery_identity_includes_seed_sources():
    a = discovery_identity({"discovery_source": "gainers-losers", "birdeye_window": "30d", "birdeye_sort": "PnL"})
    b = discovery_identity({
        "seed_sources": ["early-buyers-durable"],
        "discovery_source": "early-buyers-durable",
        "birdeye_window": "30d",
        "birdeye_sort": "PnL",
    })
    assert a != b
    assert "early-buyers-durable" in b


def test_validate_config_records_seed_sources(tmp_path):
    config = validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / DRAFT_REL_13),
        "output_dir": str(tmp_path / "out"),
        "phases": "1",
        "discovery": True,
        "seed_source": "early-buyers-durable,prescreen-filter",
        "wallets": "",
    })
    assert config["seed_sources"] == [SEED_EARLY_BUYERS, SEED_PRESCREEN_FILTER]
    assert config["discovery_source"] == SEED_EARLY_BUYERS
    assert config["PRODUCT_READY"] is False
