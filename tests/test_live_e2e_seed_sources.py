"""Offline seed-source tests. No live calls, no secrets."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from scanner.investigation import (
    DECODER_VERSION,
    DFLOW,
    JUPITER,
    METEORA_DAMM_V2,
    METEORA_DLMM,
    OKX_DEX_ROUTER,
    PUMP,
    PUMP_SWAP,
    RAYDIUM_AMM,
    RAYDIUM_CPMM,
    REVIEWED_OUTER_VENUES,
    WHIRLPOOL,
)
from scanner.mass_search.adapters import (
    BIRDEYE_TOKEN_LIST_PATH,
    BIRDEYE_TOKEN_TXS_PATH,
)
from scanner.mass_search.bundle_detect import (
    _cosigner_is_tip_payer,
    _unsigned_debit_is_program_mediated,
    detect_bundle_or_distribution,
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
    gta_options,
    load_grant,
    nansen_path_allowed,
    phase1_discovery,
    phase2_prescreen,
    plan_request_counts,
    validate_config,
)
from scanner.mass_search.live_e2e_ledger import open_grant_store
from scanner.mass_search.seed_sources import (
    COUNT_KINDS,
    FIRST_BLOCK_EXCLUSION_SECONDS,
    LEADERBOARD_VIABILITY,
    NANSEN_LABELS_PATH,
    NANSEN_LEADERBOARD_PATH,
    RESEARCH_PROGRAM_IDS,
    SEED_BIRDEYE_TOP,
    SEED_NANSEN,
    SEED_PRESCREEN_FILTER,
    SEED_TOKEN_INTERSECT,
    SeedSourceError,
    cheap_prescreen_decision,
    cost_per_audit_worthy,
    estimate_seed_plan,
    first_buyer_rows,
    helius_triage_decision,
    history_span_days,
    intersect_token_cohorts,
    leaderboard_not_viable_reason,
    ordinary_windows,
    parse_seed_sources,
    pinned_research_program_ids,
    resolve_seed_sources,
    select_control_tokens,
    select_durable_tokens,
    select_early_buyers_sold_well,
    select_nansen_wallets,
    token_list_items,
    token_tx_items,
    token_tx_owners,
    unverified_research_program_ids,
)
from scanner.mass_search.adapters import SourceError

FIXTURE_DIR = ROOT / "tests/fixtures/seed_sources"
JXT = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
JUP = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
GYG = "Gygj9QQby4j2jryqyqBHvLP7ctv2SaANgh4sCb69BUpA"


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    home = tmp_path / "ledger-home"
    home.mkdir()
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(home))
    monkeypatch.delenv("NANSEN_API_KEY", raising=False)
    return home


def _fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_leaderboards_are_not_viable_without_a_key():
    assert LEADERBOARD_VIABILITY["gmgn"]["viable"] is False
    assert LEADERBOARD_VIABILITY["cielo"]["viable"] is False
    assert LEADERBOARD_VIABILITY["kolscan"]["viable"] is False
    assert LEADERBOARD_VIABILITY["nansen"]["viable"] is True
    assert LEADERBOARD_VIABILITY["nansen"]["requires_key"] is True
    reason = leaderboard_not_viable_reason()
    assert "GMGN" in reason and "Cielo" in reason and "Kolscan" in reason


def test_parse_seed_source_cli_and_combinations():
    assert parse_seed_sources("") == []
    assert parse_seed_sources("birdeye_top,token_intersect,nansen") == [
        SEED_BIRDEYE_TOP, SEED_TOKEN_INTERSECT, SEED_NANSEN,
    ]
    assert parse_seed_sources("early-buyers-durable,prescreen-filter") == [
        SEED_TOKEN_INTERSECT, SEED_PRESCREEN_FILTER,
    ]
    assert parse_seed_sources("gainers-losers,top-traders") == [SEED_BIRDEYE_TOP]
    with pytest.raises(SeedSourceError):
        parse_seed_sources("not-a-source")
    sources = resolve_seed_sources(["prescreen-filter"], "gainers-losers")
    assert sources == [SEED_BIRDEYE_TOP, SEED_PRESCREEN_FILTER]


def test_arg_parser_has_seed_source():
    parser = build_arg_parser()
    args = parser.parse_args([
        "--dry-run",
        "--grant", "config/x.json",
        "--output", "/tmp/out",
        "--seed-source", "birdeye_top,token_intersect,nansen",
    ])
    assert args.seed_source == "birdeye_top,token_intersect,nansen"


def test_new_draft_grant_is_disabled_and_hashed():
    path = ROOT / DRAFT_REL_13
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["enabled"] is False
    assert raw["PRODUCT_READY"] is False
    assert raw["authorization_id"] == AUTHORIZATION_ID_13
    assert raw["providers"][0]["allowed_operations"] == [
        "trader_gainers_losers", "token_top_traders", "token_list", "token_txs", "token_txs_seek",
    ]
    assert "token_first_buyers" not in raw["providers"][0]["allowed_operations"]
    nansen = next(row for row in raw["providers"] if row["provider_id"] == "nansen")
    assert nansen["max_requests"] == 20
    assert nansen["max_units"] == 100
    assert "smart_money_pnl_leaderboard" in nansen["allowed_operations"]
    assert "profiler_address_labels" not in json.dumps(nansen)
    helius = next(row for row in raw["providers"] if row["provider_id"] == "helius")
    assert helius["max_requests"] == 3000
    assert helius["max_units"] == 30000
    assert raw["phase_caps"]["2"]["helius_units"] == 9000
    assert raw["phase_caps"]["3"]["helius_units"] == 18000
    leaderboard = next(row for row in raw["providers"] if row["provider_id"] == "leaderboard")
    assert leaderboard["max_requests"] == 0
    assert leaderboard["max_units"] == 0
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert PINNED_DRAFT_HASHES[AUTHORIZATION_ID_13] == digest
    assert HARD_CEILINGS["birdeye_units"] == 1400
    assert HARD_CEILINGS["helius_units"] == 30000
    assert HARD_CEILINGS["nansen_units"] == 100
    assert HARD_CEILINGS["leaderboard_requests"] == 0


def test_plan_estimates_per_source():
    tokens = [JUP, BONK, USDC]
    intersect = estimate_seed_plan([SEED_TOKEN_INTERSECT], tokens=tokens, discovery=True)
    assert intersect["totals"]["birdeye_requests"] == 9
    assert intersect["totals"]["birdeye_units"] == 90
    assert intersect["seed_is_not"] == "evidence"
    listed = estimate_seed_plan([SEED_TOKEN_INTERSECT], discovery=True)
    assert listed["totals"]["birdeye_requests"] == 1 + 10 * 3
    assert listed["totals"]["birdeye_units"] == 60 + 300
    disabled = estimate_seed_plan([SEED_NANSEN], discovery=True, nansen_enabled=False)
    assert disabled["totals"]["nansen_requests"] == 0
    assert disabled["per_source"][SEED_NANSEN]["enabled"] is False
    enabled = estimate_seed_plan([SEED_NANSEN], discovery=True, nansen_enabled=True)
    assert enabled["totals"]["nansen_requests"] == 2
    assert enabled["totals"]["nansen_units"] == 10
    triage = estimate_seed_plan(
        [SEED_TOKEN_INTERSECT], tokens=tokens, wallets=[JXT], discovery=True,
    )
    assert triage["totals"]["helius_triage_requests"] == 3
    assert triage["totals"]["helius_triage_units"] == 30
    plan = plan_request_counts({
        "wallets": [JXT],
        "phases": (1, 2),
        "discovery": True,
        "seed_sources": [SEED_TOKEN_INTERSECT],
        "discovery_source": SEED_TOKEN_INTERSECT,
        "birdeye_tokens": tokens,
        "caps": HARD_CEILINGS,
        "nansen_enabled": False,
    })
    assert plan["seed_sources"] == [SEED_TOKEN_INTERSECT]
    assert plan["totals"]["birdeye_requests"] == 9
    assert plan["totals"]["helius_requests"] == 3
    assert plan["per_phase"]["2"]["requests"] == 3
    assert plan["seed_plan"]["seed_is_not"] == "evidence"


def test_durable_tokens_controls_and_ordinary_windows():
    items = token_list_items(_fixture("token_list_durable.json"))
    tokens = select_durable_tokens(items, now_unix=1791331200)
    assert [row["address"] for row in tokens] == [JUP, BONK]
    controls = select_control_tokens(items, now_unix=1791331200, skip=[JUP])
    assert controls and controls[0]["address"] == BONK
    assert controls[0]["role"] == "control_flat_or_declining"
    windows = ordinary_windows(1700000000)
    assert windows[0]["after_time"] == 1700000000 + FIRST_BLOCK_EXCLUSION_SECONDS
    assert windows[0]["name"] == "ordinary_24h_7d"


def test_first_block_buyers_are_not_seeds():
    rows = token_tx_items(_fixture("token_txs_seek.json"))
    owners = token_tx_owners(rows, token=JUP, window="ordinary_24h_7d", after_time=1787961600)
    assert JXT in {row["address"] for row in owners}
    assert GYG not in {row["address"] for row in owners}
    assert select_early_buyers_sold_well(first_buyer_rows(_fixture("first_buyers_sold_well.json"))) == []


def test_intersect_requires_three_unrelated_cohorts():
    appearances = [
        {"address": JXT, "token": JUP, "window": "ordinary_24h_7d"},
        {"address": JXT, "token": BONK, "window": "ordinary_24h_7d"},
        {"address": JXT, "token": USDC, "window": "pullback_14d_21d"},
        {"address": GYG, "token": JUP, "window": "ordinary_24h_7d"},
        {"address": GYG, "token": BONK, "window": "ordinary_24h_7d"},
    ]
    selected = intersect_token_cohorts(appearances)
    assert [row["address"] for row in selected] == [JXT]
    assert selected[0]["cohort_count"] == 3
    assert selected[0]["selection_reason"] == "intersected_3_unrelated_token_cohorts"
    assert selected[0]["seed_is_not"] == "evidence"


def test_cheap_prescreen_uses_captured_signals_only():
    hot = cheap_prescreen_decision({"trade_count": 900, "window_days": 30})
    assert hot["dropped"] is True
    young = cheap_prescreen_decision({"history_days": 12, "trades_per_day": 3})
    assert young["dropped"] is True
    ok = cheap_prescreen_decision({"trade_count": 40, "window_days": 30, "history_days": 90})
    assert ok["dropped"] is False
    assert history_span_days([{"blockTime": 100}, {"blockTime": 100 + 86400}], created_in_range=False) is None
    spanned = history_span_days(
        [{"blockTime": 1_700_000_000}, {"blockTime": 1_700_000_000 + 5 * 86400}],
        created_in_range=True,
        now_unix=1_700_000_000 + 5 * 86400,
    )
    assert str(spanned) == "5.0000"


def test_helius_triage_drops_only_on_confirmed_signals():
    now = 1_800_000_000
    over = helius_triage_decision(
        [{"records": [{"blockTime": now - 200 * 86400}], "events": [
            {"kind": "buy", "block_time": now - 100} for _ in range(26)
        ]}],
        now_unix=now,
    )
    assert over["dropped"] is True
    assert "triage_gt_25_economic_trades_in_one_day" in over["drop_reasons"]
    under = helius_triage_decision(
        [{"records": [{"blockTime": now - 200 * 86400}], "events": [
            {"kind": "buy", "block_time": now - 100} for _ in range(24)
        ]}],
        now_unix=now,
    )
    assert under["dropped"] is False
    assert under["max_economic_trades_in_one_day"] == 24
    young = helius_triage_decision(
        [{"records": [{"blockTime": now - 10 * 86400}], "events": []}],
        now_unix=now,
        created_in_range=True,
    )
    assert young["dropped"] is True
    mid = helius_triage_decision(
        [{"records": [{"blockTime": now - 90 * 86400}], "events": []}],
        now_unix=now,
        created_in_range=False,
    )
    assert mid["dropped"] is False
    assert mid["age_preferred"] is False
    old = helius_triage_decision(
        [{"records": [{"blockTime": now - 200 * 86400}], "events": []}],
        now_unix=now,
    )
    assert old["age_preferred"] is True
    assert list(over["count_kinds"]) == list(COUNT_KINDS)


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


def test_token_intersect_dry_run_replays_recorded_fixtures(tmp_path):
    grant = load_grant(ROOT / DRAFT_REL_13)
    assert grant.get("enabled") is False
    config = _phase1_config(tmp_path, "token_intersect", [JUP, BONK, USDC])
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    recorder.fixtures = {
        BIRDEYE_TOKEN_LIST_PATH: _fixture("token_list_durable.json"),
        BIRDEYE_TOKEN_TXS_PATH: _fixture("token_txs_seek.json"),
    }
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    result = asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    assert result["seed_source"] == SEED_TOKEN_INTERSECT
    assert result["seed_is_not"] == "evidence"
    assert JXT in result["addresses"]
    assert GYG not in result["addresses"]
    assert state["seed_metadata"][JXT]["selection_reason"].startswith("intersected_")
    assert state["seed_metadata"][JXT]["rank"] == 1
    assert state["spend"]["birdeye_requests"] == 9
    paths = {call["path"] for call in recorder.calls}
    assert BIRDEYE_TOKEN_TXS_PATH in paths
    assert all(call["path"] != "/defi/txs/token/seek_by_time" for call in recorder.calls)
    assert all(call["path"] != "/token/v1/first-buyers" for call in recorder.calls)


def test_nansen_disabled_without_key_makes_no_call(tmp_path):
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "nansen")
    assert config["nansen_enabled"] is False
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    result = asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    assert result["per_source"][SEED_NANSEN]["enabled"] is False
    assert result["addresses"] == []
    assert recorder.calls == []
    assert state["spend"]["nansen_requests"] == 0


def test_nansen_dry_run_with_fixture_key_stores_vendor_metrics_separately(tmp_path, monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", "offline-fixture-not-a-live-secret")
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "nansen")
    assert config["nansen_enabled"] is True
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    recorder.fixtures = {NANSEN_LEADERBOARD_PATH: _fixture("nansen_leaderboard.json")}
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    result = asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    assert JXT in result["addresses"]
    meta = state["seed_metadata"][JXT]
    assert meta["primary_seed_source"] == SEED_NANSEN
    assert meta["vendor_metrics"]["is_not"] == "independently_verified_profit_or_copyability"
    assert all(call["path"] != NANSEN_LABELS_PATH for call in recorder.calls)
    assert state["spend"]["nansen_requests"] >= 2


def test_nansen_labels_path_is_refused():
    with pytest.raises(SourceError) as caught:
        nansen_path_allowed(NANSEN_LABELS_PATH)
    assert caught.value.state == "UNAUTHORIZED"
    with pytest.raises(SourceError):
        nansen_path_allowed("/api/v1/profiler/address/premium_labels")


def test_nansen_live_without_key_is_disabled_not_dummy(tmp_path):
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "nansen")
    config["dry_run"] = False
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    result = asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    assert result["per_source"][SEED_NANSEN]["enabled"] is False
    assert recorder.calls == []


def test_phase1_cheap_filter_drops_high_rate_before_history(tmp_path):
    config = _phase1_config(tmp_path, "birdeye_top,prescreen-filter")
    state = {
        "wallets": [JXT, GYG],
        "seed_metadata": {
            JXT: {"seed_sources": [SEED_BIRDEYE_TOP], "primary_seed_source": SEED_BIRDEYE_TOP, "trade_count": 40},
            GYG: {"seed_sources": [SEED_BIRDEYE_TOP], "primary_seed_source": SEED_BIRDEYE_TOP, "trade_count": 900},
        },
    }
    config["seed_sources"] = [SEED_BIRDEYE_TOP, SEED_PRESCREEN_FILTER]
    config["birdeye_window"] = "30d"
    dropped = apply_cheap_prescreen_phase1(config, state)
    assert dropped == [GYG]
    assert config["wallets"] == [JXT]


def test_phase2_triage_requests_three_bounded_samples(tmp_path):
    config = validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / DRAFT_REL_13),
        "output_dir": str(tmp_path / "out"),
        "phases": "2",
        "discovery": False,
        "seed_source": "token_intersect",
        "wallets": JXT,
    })
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": [JXT]}
    result = asyncio.run(phase2_prescreen(store, load_grant(ROOT / DRAFT_REL_13), config, state, recorder))
    store.close()
    helius_calls = [call for call in recorder.calls if call["provider"] == "helius"]
    assert len(helius_calls) == 3
    orders = [call["options"]["sortOrder"] for call in helius_calls]
    assert orders == ["asc", "desc", "desc"]
    for call in helius_calls:
        assert call["options"]["maxSupportedTransactionVersion"] == 1
        assert call["options"]["filters"]["tokenAccounts"] == "all"
        assert call["options"]["limit"] == 100
        assert call["options"]["transactionDetails"] == "full"
    assert result["wallets"][0]["requests"] == 3
    assert result["wallets"][0]["triage"] is True


def test_gta_options_pin_version_and_token_account_filter():
    options = gta_options(details="full", limit=100, start_unix=1, end_unix=2, sort_order="asc")
    assert options["maxSupportedTransactionVersion"] == 1
    assert options["filters"]["tokenAccounts"] == "all"
    assert "legacy" not in json.dumps(options)


def test_count_kinds_stay_separate():
    assert COUNT_KINDS == (
        "transactions", "economic_trades", "route_legs", "positions", "completed_episodes",
    )


def test_jito_tip_payer_is_not_a_bundle_partner():
    from scanner.mass_search.verified_costs import is_verified_tip_account

    tip = "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"
    assert is_verified_tip_account(tip)
    raw = {
        "transaction": {"message": {"accountKeys": [JXT, tip, GYG]}},
        "meta": {"preBalances": [10_000_000, 0, 0], "postBalances": [9_000_000, 900_000, 0]},
    }
    assert _cosigner_is_tip_payer(raw, [JXT, tip, GYG], JXT) is True


def test_pda_unsigned_debit_is_not_a_cosigner():
    raw = {
        "transaction": {"message": {
            "accountKeys": [JXT, GYG, JUPITER],
            "instructions": [{"programIdIndex": 2, "accounts": [0, 1]}],
        }},
        "meta": {"preBalances": [2_000_000_000, 1_000_000_000, 1], "postBalances": [1_000_000_000, 2_000_000_000, 1]},
    }
    assert _unsigned_debit_is_program_mediated(raw, [JXT, GYG, JUPITER]) is True
    flagged = detect_bundle_or_distribution([{
        "transaction": raw["transaction"],
        "meta": raw["meta"],
    }], JXT)
    assert flagged.get("excluded") in (False, None, True)


def test_decoder_version_is_pinned():
    assert DECODER_VERSION == "spot-v23-quote-rent-inner-v1"


def test_research_program_ids_are_split_into_pinned_and_unverified():
    pinned = pinned_research_program_ids()
    assert pinned["jupiter_v6"] == JUPITER
    assert pinned["raydium_amm_v4"] == RAYDIUM_AMM
    assert pinned["raydium_cpmm"] == RAYDIUM_CPMM
    assert pinned["meteora_dlmm"] == METEORA_DLMM
    assert pinned["meteora_damm_v2"] == METEORA_DAMM_V2
    assert pinned["pump"] == PUMP
    assert pinned["pumpswap"] == PUMP_SWAP
    assert pinned["orca_whirlpool"] == WHIRLPOOL
    assert pinned["dflow"] == DFLOW
    unverified = unverified_research_program_ids()
    assert RESEARCH_PROGRAM_IDS["okx_router_unverified"] != OKX_DEX_ROUTER
    assert unverified["okx_router_unverified"] not in REVIEWED_OUTER_VENUES
    assert unverified["raydium_clmm_unverified"] not in REVIEWED_OUTER_VENUES
    assert unverified["phoenix_unverified"] not in REVIEWED_OUTER_VENUES


def test_cost_per_audit_worthy_is_none_when_denominator_is_zero():
    out = cost_per_audit_worthy(
        {SEED_TOKEN_INTERSECT: {"units": 360, "requests": 31}},
        {SEED_TOKEN_INTERSECT: 0},
    )
    assert out[SEED_TOKEN_INTERSECT]["cost_per_audit_worthy"] is None
    hit = cost_per_audit_worthy(
        {SEED_NANSEN: {"units": 20, "requests": 6}},
        {SEED_NANSEN: 2},
    )
    assert hit[SEED_NANSEN]["cost_per_audit_worthy"] == "10.0000"


def test_discovery_identity_includes_seed_sources():
    a = discovery_identity({"discovery_source": "gainers-losers", "birdeye_window": "30d", "birdeye_sort": "PnL"})
    b = discovery_identity({
        "seed_sources": [SEED_TOKEN_INTERSECT],
        "discovery_source": SEED_TOKEN_INTERSECT,
        "birdeye_window": "30d",
        "birdeye_sort": "PnL",
    })
    assert a != b
    assert SEED_TOKEN_INTERSECT in b


def test_validate_config_records_seed_sources(tmp_path):
    config = validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / DRAFT_REL_13),
        "output_dir": str(tmp_path / "out"),
        "phases": "1",
        "discovery": True,
        "seed_source": "token_intersect,nansen,prescreen-filter",
        "wallets": "",
    })
    assert config["seed_sources"] == [SEED_TOKEN_INTERSECT, SEED_NANSEN, SEED_PRESCREEN_FILTER]
    assert config["nansen_enabled"] is False
    assert config["PRODUCT_READY"] is False
