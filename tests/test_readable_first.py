"""Readable-first funnel. Offline only. PRODUCT_READY stays false."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from scanner.investigation import JUPITER, USDC
from scanner.mass_search.live_e2e import (
    DRAFT_PATH,
    _phase2_finish,
    phase3_wallets,
    plan_request_counts,
    unscreened_address_set,
    validate_config,
)
from scanner.mass_search.qualification_gates import MAX_ECONOMIC_TRADES_PER_UTC_DAY
from scanner.mass_search.readable_first import (
    DEFER_UNREADABLE,
    DROP,
    FUNNEL_VERSION,
    KEEP,
    READABLE_SHARE_THRESHOLD,
    SAMPLE_CLASS_UNREADABLE,
    UNSCREENED,
    attach_sample,
    bot_prescreen_decision,
    decide_sample,
    format_dry_run_plan,
    rank_by_nansen_pnl,
    readable_first_plan,
    readable_first_target_n,
    readable_first_walk_cap,
    sample_readable_shares,
    select_deep_pull,
    walk_ranked,
    write_dry_run_plan,
    write_funnel_report,
)
from scanner.mass_search.seed_sources import NANSEN_TIMEFRAMES_FUNNEL, estimate_seed_plan

WALLET = "RfirstWallet11111111111111111111111111112"
MINT = "RfirstMint1111111111111111111111111111112"
TOKEN_ATA = "RfirstTokAta11111111111111111111111111112"
USDC_ATA = "RfirstUsdcAta1111111111111111111111111112"
POOL_TOK = "RfirstPoolTok1111111111111111111111111112"
POOL_USDC = "RfirstPoolUsdc111111111111111111111111112"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
UNKNOWN = "UnkRfProgram1111111111111111111111111111"
IN_WINDOW = int(datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp())


def _swap(*, signature, token_pre, token_post, usdc_pre, usdc_post, program=JUPITER, block_time=IN_WINDOW):
    return {
        "signature": signature,
        "blockTime": block_time,
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [WALLET, TOKEN_ATA, USDC_ATA, POOL_TOK, POOL_USDC, program, TOKEN],
                "instructions": [{"programId": program, "accounts": [WALLET, TOKEN_ATA, USDC_ATA], "data": "route"}],
            },
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [2_000_000_000, 2_039_280, 2_039_280, 1, 1, 1, 1],
            "postBalances": [1_999_995_000, 2_039_280, 2_039_280, 1, 1, 1, 1],
            "preTokenBalances": [
                {"accountIndex": 1, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": token_pre, "decimals": 6}},
                {"accountIndex": 2, "mint": USDC, "owner": WALLET, "uiTokenAmount": {"amount": usdc_pre, "decimals": 6}},
            ],
            "postTokenBalances": [
                {"accountIndex": 1, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"amount": token_post, "decimals": 6}},
                {"accountIndex": 2, "mint": USDC, "owner": WALLET, "uiTokenAmount": {"amount": usdc_post, "decimals": 6}},
            ],
        },
    }


def _decoded(signature, amount="100"):
    return {
        "events": [{
            "kind": "sell",
            "signature": signature,
            "mint": MINT,
            "timestamp": IN_WINDOW,
            "amount_usdc": amount,
            "consideration_usdc": amount,
            "settlement_asset": "USDC",
        }]
    }


def test_clean_sample_is_kept():
    records = [_swap(signature="clean", token_pre="1000000", token_post="0", usdc_pre="0", usdc_post="100000000")]
    shares = sample_readable_shares(records, WALLET, decoded=_decoded("clean"))
    assert shares["count_share"] == "1"
    assert shares["value_share"] == "1"
    assert decide_sample(shares)["decision"] == KEEP


def test_unreadable_heavy_sample_is_deferred_not_passed():
    records = [_swap(
        signature="bad", token_pre="1000000", token_post="0",
        usdc_pre="0", usdc_post="100000000", program=UNKNOWN,
    )]
    shares = sample_readable_shares(records, WALLET, decoded={"events": []})
    assert shares["unreadable_n"] == 1
    decision = decide_sample(shares)
    assert decision["decision"] == DEFER_UNREADABLE
    assert decision["can_only_drop_or_defer"] is True
    assert shares["unreadable_programs"][0][0] == UNKNOWN


def test_missing_value_denominator_defers():
    shares = {
        "swap_like_n": 2,
        "count_share": "1",
        "value_share": None,
    }
    assert decide_sample(shares)["decision"] == DEFER_UNREADABLE


def test_empty_sample_defers():
    shares = sample_readable_shares([], WALLET)
    assert decide_sample(shares)["decision"] == DEFER_UNREADABLE


def test_adding_unreadable_never_raises_readable_share():
    clean = _swap(signature="clean", token_pre="1000000", token_post="0", usdc_pre="0", usdc_post="100000000")
    extra = _swap(
        signature="bad", token_pre="2000000", token_post="0",
        usdc_pre="0", usdc_post="20000000", program=UNKNOWN,
    )
    base = sample_readable_shares([clean], WALLET, decoded=_decoded("clean"))
    added = sample_readable_shares([clean, extra], WALLET, decoded=_decoded("clean"))
    assert Decimal(str(added["count_share"])) <= Decimal(str(base["count_share"]))
    assert Decimal(str(added["value_share"])) <= Decimal(str(base["value_share"]))


def test_bot_prescreen_raw_under_threshold_cannot_drop():
    rows = [{"signature": f"s{i}", "blockTime": IN_WINDOW + i} for i in range(9)]
    decision = bot_prescreen_decision(rows)
    assert decision["decision"] == KEEP
    assert decision["can_only_drop_or_defer"] is True
    assert decision["screen"]["passed"] is True


def test_bot_prescreen_raw_over_needs_decode_does_not_drop_alone():
    rows = [{"signature": f"s{i}", "blockTime": IN_WINDOW + i} for i in range(20)]
    decision = bot_prescreen_decision(rows)
    assert decision["decision"] != DROP
    assert decision.get("needs_decode") is True


def test_bot_prescreen_dex_over_15_drops():
    rows = [{"signature": f"s{i}", "blockTime": IN_WINDOW + i} for i in range(20)]
    decision = bot_prescreen_decision(rows, dex_stats={"max_per_day": 16, "busiest_day": "2026-09-20"})
    assert decision["decision"] == DROP
    assert decision["can_only_drop_or_defer"] is True


def test_bot_prescreen_enormous_history_defers():
    rows = [{"signature": f"s{i}", "blockTime": IN_WINDOW + i} for i in range(12)]
    decision = bot_prescreen_decision(rows, history_cap=5)
    assert decision["decision"] == DEFER_UNREADABLE


def test_walk_ranked_continues_until_n_or_cap():
    rows = [
        {"address": "A", "funnel_decision": DEFER_UNREADABLE, "realized_pnl_usd": "900"},
        {"address": "B", "funnel_decision": KEEP, "realized_pnl_usd": "50"},
        {"address": "C", "funnel_decision": DROP, "realized_pnl_usd": "800", "drop_reason": "bot"},
        {"address": "D", "funnel_decision": KEEP, "realized_pnl_usd": "40"},
        {"address": "E", "funnel_decision": KEEP, "realized_pnl_usd": "30"},
    ]
    walked = walk_ranked(rows, n=2)
    assert [row["address"] for row in walked["kept"]] == ["B", "D"]
    assert walked["unscreened"][0]["address"] == "E"
    assert walked["unscreened"][0]["funnel_reason"] == "n_reached"
    # Cap limits examinations in PnL order. A (900, deferred) consumes the only slot.
    capped = walk_ranked(rows, n=2, cap=1)
    assert capped["examined"] == 1
    assert capped["deferred_unreadable"][0]["address"] == "A"
    assert any(row.get("funnel_reason") == "cap_reached" for row in capped["unscreened"])


def test_rank_is_nansen_pnl():
    ranked = rank_by_nansen_pnl([
        {"address": "low", "realized_pnl_usd": "1"},
        {"address": "high", "vendor_metrics": {"realized_pnl_usd": "99"}},
    ])
    assert [row["address"] for row in ranked] == ["high", "low"]


def test_select_deep_pull_skips_dropped():
    rows = [
        {"address": "x", "funnel_decision": KEEP, "dropped": True, "realized_pnl_usd": "9"},
        {"address": "y", "funnel_decision": KEEP, "dropped": False, "realized_pnl_usd": "1"},
    ]
    assert select_deep_pull(rows, n=5) == ["y"]


def test_select_deep_pull_respects_walk_cap():
    rows = [
        {"address": "A", "funnel_decision": DEFER_UNREADABLE, "dropped": False, "realized_pnl_usd": "90"},
        {"address": "B", "funnel_decision": KEEP, "dropped": False, "realized_pnl_usd": "10"},
        {"address": "C", "funnel_decision": KEEP, "dropped": False, "realized_pnl_usd": "5"},
    ]
    assert select_deep_pull(rows, n=2, cap=1) == []
    assert select_deep_pull(rows, n=2, cap=2) == ["B"]


def test_n_comes_from_per_run_cap_when_n_omitted():
    assert readable_first_target_n({"nansen_dex_trades_wallet_cap": 7}) == 7
    assert readable_first_target_n({"readable_first_n": 3, "nansen_dex_trades_wallet_cap": 7}) == 3
    assert readable_first_walk_cap({"readable_first_cap": 4, "nansen_dex_trades_wallet_cap": 9}) == 4
    assert readable_first_walk_cap({"nansen_dex_trades_wallet_cap": 9}) == 9
    assert readable_first_walk_cap({"nansen_dex_trades_wallet_cap": 0}) is None
    assert readable_first_walk_cap({}) is None


def test_screens_never_mark_audit_or_coverage_pass():
    shares = sample_readable_shares(
        [_swap(signature="clean", token_pre="1000000", token_post="0", usdc_pre="0", usdc_post="100000000")],
        WALLET,
        decoded=_decoded("clean"),
    )
    decision = decide_sample(shares)
    bot = bot_prescreen_decision([{"signature": "s", "blockTime": IN_WINDOW}])
    for blob in (shares, decision, bot):
        assert blob.get("independently_audited") is not True
        assert blob.get("coverage_passed") is not True
        assert blob.get("PRODUCT_READY") is not True


def test_attach_sample_stamps_phase2_row():
    records = [_swap(
        signature="bad", token_pre="1000000", token_post="0",
        usdc_pre="0", usdc_post="100000000", program=UNKNOWN,
    )]
    row = attach_sample({"address": WALLET, "dropped": False}, records, WALLET, decoded={"events": []})
    assert row["funnel_decision"] == DEFER_UNREADABLE
    assert row["deferred"] is True
    assert row["readable_first"]["unreadable_programs"][0][0] == UNKNOWN


def test_plan_has_every_stage_and_funnel_windows():
    plan = readable_first_plan(
        leaderboard_pages=2,
        token_count=3,
        token_pnl_calls=3,
        discovered_wallets=10,
        deep_n=4,
        nansen_profile_cap=5,
    )
    names = [stage["stage"] for stage in plan["stages"]]
    assert names == ["discovery", "rule_a", "bot_prescreen", "decodability_sample", "deep_pull"]
    assert plan["timeframes"] == list(NANSEN_TIMEFRAMES_FUNNEL)
    assert plan["totals"]["nansen_requests"] > 0
    assert plan["totals"]["helius_requests"] > 0
    assert "0.97" in plan["stages"][3]["threshold"]
    text = format_dry_run_plan(plan)
    assert "Totals:" in text
    assert plan["PRODUCT_READY"] is False


def test_plan_is_at_least_seed_plan_runtime():
    seed = estimate_seed_plan(
        ["nansen"],
        nansen_enabled=True,
        nansen_calibrate=True,
        nansen_dex_trades_wallet_cap=4,
        nansen_dex_trades_max_pages=3,
    )
    nansen = seed["per_source"]["nansen"]
    assert nansen["leaderboard_requests"] == 0
    assert nansen["dex_trades_requests"] == 12
    plan = readable_first_plan(discovered_wallets=4, dex_pages=3)
    bot = next(stage for stage in plan["stages"] if stage["stage"] == "bot_prescreen")
    assert bot["nansen_requests"] >= nansen["dex_trades_requests"]


def test_funnel_report_writes_json_and_markdown(tmp_path):
    walked = walk_ranked([
        {"address": "keep1", "funnel_decision": KEEP, "realized_pnl_usd": "10"},
        {
            "address": "defer1",
            "funnel_decision": DEFER_UNREADABLE,
            "realized_pnl_usd": "9",
            "readable_first": {"unreadable_programs": [(UNKNOWN, 4)]},
            "funnel_reason": "readable_share_below_0.97",
        },
        {"address": "drop1", "funnel_decision": DROP, "drop_reason": "gt_15_economic_trades_in_one_day"},
    ], n=3)
    report = write_funnel_report(tmp_path, walked)
    assert (tmp_path / "READABLE_FIRST_FUNNEL.json").is_file()
    markdown = (tmp_path / "READABLE_FIRST_FUNNEL.md").read_text(encoding="utf-8")
    assert "defer1" in markdown
    assert UNKNOWN in markdown
    assert report["version"] == FUNNEL_VERSION
    assert report["dominant_unreadable_programs"][0][0] == UNKNOWN


def test_threshold_is_point_nine_seven():
    assert READABLE_SHARE_THRESHOLD == Decimal("0.97")
    assert MAX_ECONOMIC_TRADES_PER_UTC_DAY == 15


def test_live_e2e_readable_first_plan_and_phase3(tmp_path):
    cfg = validate_config({
        "mode": "dry-run",
        "grant_path": DRAFT_PATH,
        "output_dir": tmp_path,
        "wallets": [WALLET],
        "phases": "2,3",
        "readable_first": True,
        "readable_first_n": 1,
        "window_days": 30,
        "earlier_history_days": 60,
    })
    assert cfg["readable_first"] is True
    assert cfg["nansen_timeframes"] == [30, 90, 180]
    assert cfg["helius_signatures_prescreen"] is True
    assert cfg["readable_first_cap"] is None
    plan = plan_request_counts(cfg)
    assert plan["readable_first"] is True
    assert "Totals:" in plan["readable_first_dry_run"]
    text = write_dry_run_plan(tmp_path, plan["readable_first_plan"])
    assert (tmp_path / "READABLE_FIRST_PLAN.md").is_file()
    assert (tmp_path / "READABLE_FIRST_PLAN.json").is_file()
    markdown = (tmp_path / "READABLE_FIRST_PLAN.md").read_text(encoding="utf-8")
    assert "discovery" in markdown
    assert "bot_prescreen" in markdown
    assert "decodability_sample" in markdown
    assert "Totals:" in markdown
    assert "Totals:" in text
    state = {
        "phase2": {
            WALLET: {
                "address": WALLET,
                "dropped": False,
                "funnel_decision": KEEP,
                "realized_pnl_usd": "12",
            },
            "OtherWallet11111111111111111111111111112": {
                "address": "OtherWallet11111111111111111111111111112",
                "dropped": False,
                "funnel_decision": KEEP,
                "realized_pnl_usd": "1",
            },
        }
    }
    assert phase3_wallets(cfg, state) == [WALLET]


def test_phase2_finish_walks_until_n_or_cap(tmp_path):
    other = "OtherWallet11111111111111111111111111112"
    third = "ThirdWallet11111111111111111111111111112"
    fourth = "FourthWallet1111111111111111111111111112"
    cfg = {
        "readable_first": True,
        "readable_first_n": 2,
        "readable_first_cap": 3,
        "output_dir": tmp_path,
        "batch": True,
    }
    state = {}
    rows = [
        {
            "address": WALLET, "dropped": False, "deferred": True,
            "funnel_decision": DEFER_UNREADABLE, "coverability_rank_key": 0,
            "nansen_realized_pnl_usd": "900",
        },
        {
            "address": other, "dropped": True,
            "funnel_decision": DROP, "coverability_rank_key": 0,
            "nansen_realized_pnl_usd": "800", "drop_reason": "gt_15_economic_trades_in_one_day",
        },
        {
            "address": third, "dropped": False,
            "funnel_decision": KEEP, "coverability_rank_key": 0,
            "nansen_realized_pnl_usd": "50",
        },
        {
            "address": fourth, "dropped": False,
            "funnel_decision": KEEP, "coverability_rank_key": 0,
            "nansen_realized_pnl_usd": "40",
        },
    ]
    out = _phase2_finish(cfg, state, rows)
    assert out["kept"] == [third]
    assert state["funnel_walk"]["cap"] == 3
    assert state["funnel_walk"]["n"] == 2
    assert (tmp_path / "READABLE_FIRST_FUNNEL.json").is_file()
    assert (tmp_path / "READABLE_FIRST_FUNNEL.md").is_file()
    assert fourth in unscreened_address_set(state)
    assert WALLET not in unscreened_address_set(state)
    assert phase3_wallets(cfg, state) == [third]


def test_phase3_uses_walk_cap_when_funnel_walk_missing():
    cfg = {
        "readable_first": True,
        "readable_first_n": 2,
        "readable_first_cap": 1,
    }
    state = {
        "phase2": {
            "A": {"address": "A", "dropped": False, "funnel_decision": DEFER_UNREADABLE, "realized_pnl_usd": "90"},
            "B": {"address": "B", "dropped": False, "funnel_decision": KEEP, "realized_pnl_usd": "10"},
        }
    }
    assert phase3_wallets(cfg, state) == []


def test_dry_run_plan_lists_every_stage_cost():
    plan = readable_first_plan(
        leaderboard_pages=2,
        token_count=2,
        token_pnl_calls=2,
        discovered_wallets=8,
        deep_n=3,
        walk_cap=12,
        nansen_profile_cap=4,
    )
    text = format_dry_run_plan(plan)
    for stage in ("discovery", "rule_a", "bot_prescreen", "decodability_sample", "deep_pull"):
        assert stage in text
    assert "Totals:" in text
    deep = next(item for item in plan["stages"] if item["stage"] == "deep_pull")
    assert deep["walk_cap"] == 12
    assert deep["wallets"] == 3
    assert plan["gates_unchanged"] == [
        "coverage_0.99_result_relevant",
        "min_3_completed_episodes",
        "independently_audited_within_2",
        "zero_unresolved_basis_sales",
        "bot_gt_15_economic_trades_full_history",
    ]
