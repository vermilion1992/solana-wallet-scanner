"""Verify-02712bf / run-9 D1 root-cause regressions. Offline only."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import scanner.mass_search.live_e2e as L
from scanner.mass_search.live_e2e_ledger import open_grant_store
from scanner.mass_search.qualification_gates import (
    GT25_ECONOMIC_TRADES_RULE,
    RAW_SOL_FLOOR_LAMPORTS,
    bot_rate_disagreement_blocker,
    combined_economic_trade_rate,
    merge_trade_rates,
    raw_economic_trade_rate,
    with_gt25_blocker,
)
from scanner.mass_search.seed_sources import (
    NANSEN_LEADERBOARD_PATH,
    NANSEN_PNL_SUMMARY_PATH,
    helius_triage_decision,
)
import tools.independent_episode_audit as auditor

ROOT = L.ROOT
A = "WaLLet1111111111111111111111111111111111111"
X = "MintX11111111111111111111111111111111111111"
Y = "MintY11111111111111111111111111111111111111"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
T0 = 1759276800


def tb(idx, mint, amt, owner=A):
    return {"accountIndex": idx, "mint": mint, "owner": owner, "uiTokenAmount": {"amount": str(amt)}}


def rec(sig, bt, pre_tok, post_tok, native=0, fee=5000, err=None, n_acc=8, pre_lamports=None, post_lamports=None, swap=True):
    pre = [10_000_000_000] + [2_039_280] * (n_acc - 1)
    post = list(pre)
    post[0] += native - fee
    if pre_lamports:
        for i, value in pre_lamports.items():
            pre[i] = value
    if post_lamports:
        for i, value in post_lamports.items():
            post[i] = value
    meta = {
        "err": err,
        "fee": fee,
        "preBalances": pre,
        "postBalances": post,
        "preTokenBalances": pre_tok,
        "postTokenBalances": post_tok,
        "loadedAddresses": {"writable": [], "readonly": []},
    }
    if swap:
        meta["logMessages"] = ["Program log: Instruction: Swap"]
    return {
        "blockTime": bt,
        "transaction": {
            "signatures": [sig],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [A] + [f"Acc{i}" for i in range(1, n_acc)],
            },
        },
        "meta": meta,
    }


def test_rent_aware_floor_is_1e5():
    # DC replaced SWAP_LOG_RE with an independent word-atom scan so the
    # auditor cannot be a clone of the app's SWAP_LIKE_LOG_RE. The floor
    # and reviewed-program set stay public; the log signal must still exist.
    assert RAW_SOL_FLOOR_LAMPORTS == 100_000
    assert hasattr(auditor, "_AUDITOR_SWAP_LOG_ATOMS")
    assert hasattr(auditor, "_auditor_log_looks_like_swap")
    assert hasattr(auditor, "REVIEWED_SWAP_PROGRAM_IDS")
    assert "INDEPENDENT_SOL_FLOOR_LAMPORTS" not in auditor.__dict__


def test_d1_micro_sol_swaps_count_and_rent_only_does_not():
    micro_buy = rec("mb", T0 + 10, [tb(1, X, 0)], [tb(1, X, 1000)], native=-1_000_000)
    micro_sell = rec("ms", T0 + 20, [tb(1, X, 1000)], [tb(1, X, 0)], native=2_000_000)
    airdrop_two = rec(
        "ad2", T0 + 30, [], [tb(1, X, 1000), tb(2, Y, 5)],
        native=-4_078_560, pre_lamports={1: 0, 2: 0}, swap=False,
    )
    close_two = rec(
        "to2", T0 + 40, [tb(1, X, 1000), tb(2, Y, 5)], [],
        native=4_078_560, post_lamports={1: 0, 2: 0}, swap=False,
    )
    app = raw_economic_trade_rate([micro_buy, micro_sell, airdrop_two, close_two], A)
    aud, inc = auditor.raw_economic_trades_by_utc_day([micro_buy, micro_sell, airdrop_two, close_two], A)
    assert app["max"] == 2
    assert aud[app["max_on"]] == 2
    assert inc == 0


def test_d1_expected_cfk6_bzstep_policy_matches_1e5_rent_aware():
    """Synthetic stand-in for live CFk6 151 / BZSTEP 203 at the 1e5 rent-aware floor."""
    day = int(datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp())
    records = [
        rec(f"cfk6-{i}", day + i, [tb(1, X, 0)], [tb(1, X, 1000 + i)], native=-1_000_000)
        for i in range(151)
    ]
    rate = raw_economic_trade_rate(records, A)
    independent, _ = auditor.raw_economic_trades_by_utc_day(records, A)
    assert rate["max"] == 151
    assert rate["max_on"] == "2026-09-30"
    assert independent["2026-09-30"] == 151
    day2 = int(datetime(2026, 9, 26, tzinfo=timezone.utc).timestamp())
    records2 = [
        rec(f"bz-{i}", day2 + i, [tb(1, X, 0)], [tb(1, X, 1000 + i)], native=-1_000_000)
        for i in range(203)
    ]
    rate2 = raw_economic_trade_rate(records2, A)
    independent2, _ = auditor.raw_economic_trades_by_utc_day(records2, A)
    assert rate2["max"] == 203
    assert rate2["max_on"] == "2026-09-26"
    assert independent2["2026-09-26"] == 203


def test_d2_auditor_count_is_not_a_clone():
    import inspect
    app_src = inspect.getsource(L.__dict__.get("raw_economic_trades_by_utc_day") or __import__(
        "scanner.mass_search.qualification_gates", fromlist=["raw_economic_trades_by_utc_day"]
    ).raw_economic_trades_by_utc_day)
    aud_src = inspect.getsource(auditor.raw_economic_trades_by_utc_day)
    import difflib
    ratio = difflib.SequenceMatcher(None, app_src, aud_src).ratio()
    assert ratio < 0.85
    aud_src = inspect.getsource(auditor)
    # Independence proof: atom scan + reviewed-program set, not the app regex.
    assert "_AUDITOR_SWAP_LOG_ATOMS" in aud_src
    assert "_auditor_log_looks_like_swap" in aud_src
    assert "REVIEWED_SWAP_PROGRAM_IDS" in aud_src
    assert "INDEPENDENT_SOL_FLOOR_LAMPORTS" not in aud_src
    assert "_has_swap_signal" in aud_src


def test_d2_disagreement_gate_names_both_numbers():
    text = bot_rate_disagreement_blocker(
        {"max": 27, "max_on": "2026-09-01"},
        {"max": 11, "max_on": "2026-09-02"},
    )
    assert text
    assert "27" in text and "11" in text
    assert "2026-09-01" in text and "2026-09-02" in text
    assert bot_rate_disagreement_blocker({"max": 30, "max_on": "d"}, {"max": 40, "max_on": "d"}) is None
    row = L._phase4_wallet_row(
        {
            "address": A,
            "history": {},
            "bundle_or_distribution": {},
            "prescreen": {},
            "window": {},
            "max_economic_trades_in_one_day": 27,
            "max_economic_trades_on": "2026-09-01",
            "independent_audit": {"max_economic_trades_in_one_day": 11, "max_economic_trades_on": "2026-09-02"},
        },
        {
            "max_economic_trades_in_one_day": 27,
            "max_economic_trades_on": "2026-09-01",
            "completed_known_cost_positions": 0,
            "qualification_level": {"level": "insufficient_evidence"},
            "independent_audit": {"max_economic_trades_in_one_day": 11, "max_economic_trades_on": "2026-09-02"},
        },
    )
    assert "app_auditor_bot_rate_disagree" in (row["blocker"] or "")
    assert row["lead_level"] == "insufficient_evidence"


def test_d7_no_stored_day_inf_dedupe_and_single_gt25():
    rate = merge_trade_rates({"max": 0, "max_on": None, "by_day": {}})
    assert rate["max_on"] != "stored"
    assert "stored" not in (rate.get("by_day") or {})
    inf_rec = rec("inf", float("inf"), [tb(1, X, 0)], [tb(1, X, 1000)], native=-5_000_000)
    by_day, incomplete = __import__(
        "scanner.mass_search.qualification_gates", fromlist=["raw_economic_trades_by_utc_day"]
    ).raw_economic_trades_by_utc_day([inf_rec], A)
    assert by_day == {}
    assert incomplete >= 1
    aud, aud_inc = auditor.raw_economic_trades_by_utc_day([inf_rec], A)
    assert aud == {}
    assert aud_inc >= 1
    buy = rec("dup", T0 + 10, [tb(1, X, 0)], [tb(1, X, 1000)], native=-5_000_000)
    deduped = raw_economic_trade_rate([buy, buy], A)
    assert deduped["max"] == 1
    blocker = with_gt25_blocker(GT25_ECONOMIC_TRADES_RULE, {"max": 130, "max_on": "2026-09-30"})
    assert blocker.count(GT25_ECONOMIC_TRADES_RULE) == 1
    assert "130" in blocker and "2026-09-30" in blocker


def test_triage_uses_raw_rent_aware_count():
    records = [
        rec(f"raw{i}", T0 + i, [tb(1, X, 0)], [tb(1, X, 1000 + i)], native=-1_000_000)
        for i in range(30)
    ]
    decision = helius_triage_decision(
        [{"events": [], "records": records, "address": A}],
        now_unix=T0 + 86400,
        address=A,
    )
    assert decision["dropped"] is True
    assert decision["max_economic_trades_in_one_day"] >= 26
    assert f"triage_{GT25_ECONOMIC_TRADES_RULE}" in decision["drop_reasons"]


def test_nansen_phase1_keeps_both_timeframes(tmp_path, monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", "offline-fixture-not-a-live-secret")
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(tmp_path / "led"))
    grant = L.load_grant(ROOT / L.DRAFT_REL_13)
    config = L.validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / L.DRAFT_REL_13),
        "output_dir": str(tmp_path / "out"),
        "phases": "1",
        "discovery": True,
        "seed_source": "nansen",
        "nansen_profile_cap": 0,
        "wallets": "",
    })
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    config["nansen_enabled"] = True
    store, _ = open_grant_store(config["authorization_id"])
    board = json.loads((ROOT / "tests/fixtures/seed_sources/nansen_leaderboard.json").read_text(encoding="utf-8"))
    rec = L.RecorderTransport()
    rec.fixtures = {NANSEN_LEADERBOARD_PATH: board, NANSEN_PNL_SUMMARY_PATH: {"data": {}}}
    state = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": []}
    asyncio.run(L.phase1_discovery(store, grant, config, state, rec))
    store.close()
    assert state.get("seed_metadata")
    for meta in state["seed_metadata"].values():
        assert set((meta.get("timeframes") or {})) == {"90", "180"}
