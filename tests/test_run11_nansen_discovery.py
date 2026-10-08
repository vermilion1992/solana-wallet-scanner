"""Run-11 Nansen discovery: per_page, Rule A, dex-trades, pnl-summary off, tgm refuse."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from scanner.mass_search.live_e2e import (
    build_arg_parser,
    nansen_rule_a_kwargs,
    nansen_vendor_drop_decision,
    plan_request_counts,
    validate_config,
)
from scanner.mass_search.seed_sources import (
    ALLOWED_NANSEN_PATHS,
    NANSEN_DEX_TRADES_PATH,
    NANSEN_LEADERBOARD_PER_PAGE_MAX,
    NANSEN_TGM_PNL_LEADERBOARD_PATH,
    SeedSourceError,
    dex_trades_per_utc_day,
    estimate_seed_plan,
    nansen_dex_trades_body,
    nansen_dex_trades_drop,
    nansen_high_frequency_drop,
    nansen_leaderboard_body,
    nansen_per_page,
    nansen_schema_kind_for_path,
    nansen_tgm_pnl_leaderboard_body,
    refuse_nansen_premium_labels,
    select_nansen_wallets,
    validate_nansen_body,
)

GRANT = Path(__file__).resolve().parents[1] / "config/live_authorization.live-e2e-proof-2026-10-13-mitch-draft.json"


def test_nansen_per_page_bounds_and_body():
    assert nansen_per_page(1000) == 1000
    assert nansen_per_page(1) == 1
    with pytest.raises(SeedSourceError):
        nansen_per_page(0)
    with pytest.raises(SeedSourceError):
        nansen_per_page(NANSEN_LEADERBOARD_PER_PAGE_MAX + 1)
    body = nansen_leaderboard_body(timeframe=90, page=1, per_page=1000)
    assert body["pagination"]["per_page"] == 1000
    assert body["pagination"]["page"] == 1


def test_rule_a_drops_and_keeps():
    keep = nansen_high_frequency_drop(
        {"n_trades": 90, "n_tokens": 5, "realized_pnl_usd": 12},
        timeframe=90,
    )
    assert keep["dropped"] is False
    drop_rate = nansen_high_frequency_drop(
        {"n_trades": 541, "n_tokens": 5, "realized_pnl_usd": 12},
        timeframe=90,
    )
    assert drop_rate["dropped"] is True
    assert any("avg_trades_per_day" in item for item in drop_rate["drop_reasons"])
    drop_tokens = nansen_high_frequency_drop(
        {"n_trades": 90, "n_tokens": 1, "realized_pnl_usd": 12},
        timeframe=90,
    )
    assert drop_tokens["dropped"] is True
    drop_pnl = nansen_high_frequency_drop(
        {"n_trades": 90, "n_tokens": 5, "realized_pnl_usd": 0},
        timeframe=90,
    )
    assert drop_pnl["dropped"] is True
    missing = nansen_high_frequency_drop({"n_trades": 90}, timeframe=90)
    assert missing["dropped"] is False


def test_select_nansen_wallets_keeps_rule_a_fields():
    rows = [{
        "address": "9hciHnHz11111111111111111111111111111111111",
        "realized_pnl_usd": 10,
        "n_trades": 40,
        "n_tokens": 4,
        "held_tokens_count": 3,
        "open_trades": 1,
        "avg_trade_roi": 0.2,
        "total_pnl_usd": 12,
        "address_label": "Smart Trader",
    }]
    selected = select_nansen_wallets(rows, timeframe=90)
    vendor = selected[0]["vendor_metrics"]
    assert vendor["held_tokens_count"] == 3
    assert vendor["open_trades"] == 1
    assert vendor["avg_trade_roi"] == 0.2
    assert vendor["total_pnl_usd"] == 12
    assert vendor["address_label"] == "Smart Trader"


def test_dex_trades_schema_and_drop_only():
    assert NANSEN_DEX_TRADES_PATH in ALLOWED_NANSEN_PATHS
    assert nansen_schema_kind_for_path(NANSEN_DEX_TRADES_PATH) == "dex_trades"
    body = nansen_dex_trades_body(
        address="9hciHnHz11111111111111111111111111111111111",
        date_from="2020-03-17",
        date_to="2026-10-08",
        page=1,
        per_page=1000,
    )
    validate_nansen_body("dex_trades", body)
    with pytest.raises(SeedSourceError):
        validate_nansen_body("dex_trades", {**body, "extra": True})
    rows = [
        {"transaction_hash": "aa", "block_timestamp": "2025-01-18T00:00:00Z"},
        {"transaction_hash": "aa", "block_timestamp": "2025-01-18T01:00:00Z"},
        {"transaction_hash": "bb", "block_timestamp": "2025-01-18T02:00:00Z"},
    ]
    stats = dex_trades_per_utc_day(rows)
    assert stats["max_per_day"] == 2
    assert stats["distinct_hashes"] == 2
    busy = dex_trades_per_utc_day(
        [{"transaction_hash": f"t{i}", "block_timestamp": "2025-01-18T00:00:00Z"} for i in range(26)]
    )
    hit = nansen_dex_trades_drop(busy, now_unix=1_780_000_000)
    assert hit["dropped"] is True
    assert hit["can_only_drop"] is True
    empty = nansen_dex_trades_drop({}, now_unix=1_780_000_000)
    assert empty["dropped"] is False
    assert empty.get("empty_or_error") is True


def test_tgm_pnl_leaderboard_refuses_premium_labels():
    assert NANSEN_TGM_PNL_LEADERBOARD_PATH in ALLOWED_NANSEN_PATHS
    body = nansen_tgm_pnl_leaderboard_body(
        token_address="A7bdiYdS11111111111111111111111111111111111",
        date_from="2026-07-10T00:00:00Z",
        date_to="2026-10-08T00:00:00Z",
    )
    assert "premium_labels" not in body
    with pytest.raises(SeedSourceError):
        refuse_nansen_premium_labels({**body, "premium_labels": True})
    with pytest.raises(SeedSourceError):
        validate_nansen_body("tgm_pnl_leaderboard", {**body, "premium_labels": True})
    refuse_nansen_premium_labels({**body, "premium_labels": False})


def test_pnl_summary_off_by_default_and_plan_counts_calls(tmp_path):
    parser = build_arg_parser()
    args = parser.parse_args([
        "--dry-run",
        "--grant", str(GRANT),
        "--output", str(tmp_path / "out"),
        "--seed-source", "nansen",
        "--discovery",
        "--phases", "1",
    ])
    assert args.nansen_profiles == 0
    assert args.nansen_per_page == 50
    config = validate_config({
        **vars(args),
        "mode": "dry-run",
        "nansen_enabled": True,
    })
    assert config["nansen_profile_cap"] == 0
    plan = estimate_seed_plan(
        ["nansen"],
        discovery=True,
        nansen_enabled=True,
        nansen_profile_cap=0,
        nansen_leaderboard_pages=1,
        nansen_per_page=1000,
    )
    nansen = plan["per_source"]["nansen"]
    assert nansen["leaderboard_requests"] == 2
    assert nansen["profiler_requests"] == 0
    assert nansen["dex_trades_requests"] == 0
    assert nansen["requests"] == 2


def test_vendor_drop_uses_rule_a_thresholds():
    meta = {
        "timeframe": 90,
        "vendor_metrics": {"n_trades": 300, "n_tokens": 5, "realized_pnl_usd": 10},
    }
    hit = nansen_vendor_drop_decision(meta, {
        "nansen_max_avg_trades_per_day": "2.5",
        "nansen_min_tokens": 3,
        "nansen_max_tokens": 10,
        "nansen_min_realized_pnl": "0",
    })
    assert hit and hit["dropped"] is True
    keep = nansen_vendor_drop_decision(meta, {
        "nansen_max_avg_trades_per_day": "25",
        "nansen_min_tokens": 0,
        "nansen_max_tokens": 100,
        "nansen_min_realized_pnl": "-1",
    })
    assert keep is None
    kwargs = nansen_rule_a_kwargs({})
    assert Decimal(str(kwargs["max_avg_trades_per_day"])) == Decimal("5")
