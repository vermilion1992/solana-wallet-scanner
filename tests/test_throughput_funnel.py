"""Throughput funnel: screens, cache, parallelism, batch. Offline only."""
from __future__ import annotations

import asyncio
import time
from decimal import Decimal

from scanner.mass_search.live_e2e import DRAFT_PATH, plan_request_counts, validate_config
from scanner.mass_search.qualification_gates import MAX_ECONOMIC_TRADES_PER_UTC_DAY
from scanner.mass_search.readable_first import DEFER_UNREADABLE, DROP, KEEP
from scanner.mass_search.seed_sources import estimate_seed_plan
from scanner.mass_search.throughput import (
    HELIUS_SIGNATURES_METHOD,
    HELIUS_SIGNATURES_UNITS,
    PageLedger,
    TokenBucket,
    fetch_with_cache_and_backoff,
    gather_capped,
    isolated_phase4_sleep_worker,
    load_cached_page,
    raw_page_cache_key,
    run_batch_funnel,
    run_phase4_pool,
    screen_signatures,
    signatures_credit_note,
    signatures_rpc_body,
    store_cached_page,
)

IN_WINDOW = 1_790_000_000


def test_signatures_method_is_one_credit():
    note = signatures_credit_note()
    assert note["method"] == "getSignaturesForAddress"
    assert note["units"] == 1
    assert note["page_size"] == 1000
    assert "1 credit" in note["note"]
    body = signatures_rpc_body("Wallet11111111111111111111111111111111112")
    assert body["method"] == HELIUS_SIGNATURES_METHOD
    assert body["params"][1]["limit"] == 1000


def test_signatures_screen_drop_or_defer_only():
    quiet = [{"signature": f"s{i}", "blockTime": IN_WINDOW + i} for i in range(9)]
    quiet_out = screen_signatures(quiet)
    assert quiet_out["passed"] is True
    assert quiet_out["passed_lead"] is False
    assert quiet_out["can_only_drop_or_defer"] is True
    busy = [{"signature": f"s{i}", "blockTime": IN_WINDOW + i} for i in range(20)]
    busy_out = screen_signatures(busy)
    assert busy_out["needs_decode"] is True
    assert busy_out["dropped"] is False
    huge = [{"signature": f"s{i}", "blockTime": IN_WINDOW + i} for i in range(8)]
    deferred = screen_signatures(huge, history_cap=3)
    assert deferred["deferred"] is True
    assert deferred["passed_lead"] is False


def test_d11_1_calibrate_plan_has_dex_not_leaderboard():
    plan = estimate_seed_plan(
        ["nansen"],
        nansen_enabled=True,
        nansen_calibrate=True,
        nansen_dex_trades_wallet_cap=5,
        nansen_dex_trades_max_pages=3,
    )
    nansen = plan["per_source"]["nansen"]
    assert nansen["leaderboard_requests"] == 0
    assert nansen["dex_trades_requests"] == 15
    assert nansen["requests"] >= nansen["dex_trades_requests"]


def test_page_cache_same_key_not_paid_twice(tmp_path):
    key = raw_page_cache_key(
        wallet="Abc1111111111111111111111111111111111112",
        start_unix=1, end_unix=2, method="getSignaturesForAddress", page=0,
    )
    ledger = PageLedger()
    calls = {"n": 0}

    async def fetch():
        calls["n"] += 1
        return b"paid-page"

    async def run():
        first = await fetch_with_cache_and_backoff(
            key, cache_root=tmp_path, ledger=ledger, units=1, fetch=fetch,
        )
        second = await fetch_with_cache_and_backoff(
            key, cache_root=tmp_path, ledger=ledger, units=1, fetch=fetch,
        )
        return first, second

    first, second = asyncio.run(run())
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["units"] == 0
    assert calls["n"] == 1
    assert len(ledger.paid) == 1
    assert load_cached_page(tmp_path, key) == b"paid-page"


def test_429_retry_does_not_discard_or_double_pay(tmp_path):
    key = raw_page_cache_key(
        wallet="Def1111111111111111111111111111111111112",
        start_unix=1, end_unix=2, method="getTransactionsForAddress", page=0,
    )
    ledger = PageLedger()
    calls = {"n": 0}

    class Rate(Exception):
        state = "RATE_LIMITED"

    async def fetch():
        calls["n"] += 1
        if calls["n"] == 1:
            raise Rate()
        return b"recovered"

    async def no_sleep(_):
        return None

    result = asyncio.run(fetch_with_cache_and_backoff(
        key, cache_root=tmp_path, ledger=ledger, units=10, fetch=fetch,
        retries=2, backoff_seconds=0, sleep=no_sleep,
    ))
    assert result["raw"] == b"recovered"
    assert len(ledger.paid) == 1
    assert ledger.discards == []
    assert calls["n"] == 2


def test_parallel_gather_no_lost_page_no_double_spend(tmp_path):
    ledger = PageLedger()
    bucket = TokenBucket(1000, burst=8)

    async def job(i):
        key = raw_page_cache_key(
            wallet=f"W{i:02d}111111111111111111111111111111111112",
            start_unix=10, end_unix=20, method="getSignaturesForAddress", page=0,
        )

        async def fetch():
            return f"page-{i}".encode()

        return await fetch_with_cache_and_backoff(
            key, cache_root=tmp_path, ledger=ledger, units=1, fetch=fetch,
        )

    results = asyncio.run(gather_capped([lambda i=i: job(i) for i in range(6)], bucket, concurrency=3))
    assert len(results) == 6
    assert len(ledger.paid) == 6
    assert len(ledger.fetches) == 6
    assert ledger.discards == []
    assert {item["raw"] for item in results} == {f"page-{i}".encode() for i in range(6)}


def test_phase4_pool_fail_closed_and_keeps_order():
    def worker(payload):
        if payload["address"] == "bad":
            raise RuntimeError("boom")
        return {"address": payload["address"], "ok": True, "PRODUCT_READY": False}

    rows = run_phase4_pool(
        [{"address": "a"}, {"address": "bad"}, {"address": "c"}],
        worker,
        workers=3,
        backend="thread",
    )
    assert [row["address"] for row in rows] == ["a", "bad", "c"]
    assert rows[1]["independently_audited"] is False
    assert "phase4_wallet_failed" in rows[1]["blocker"]
    assert rows[0]["ok"] is True


def test_phase4_parallel_speedup_on_synthetic():
    payloads = [{"address": f"w{i}", "sleep": 0.05} for i in range(4)]
    start = time.monotonic()
    sequential = run_phase4_pool(payloads, isolated_phase4_sleep_worker, workers=1)
    seq_s = time.monotonic() - start
    start = time.monotonic()
    parallel = run_phase4_pool(payloads, isolated_phase4_sleep_worker, workers=4, backend="thread")
    par_s = time.monotonic() - start
    assert len(sequential) == len(parallel) == 4
    assert par_s < seq_s * 0.8


def test_batch_funnel_writes_spend_and_wall(tmp_path):
    rows = [
        {"address": "keep1", "funnel_decision": KEEP, "realized_pnl_usd": "9", "audit_worthy": True},
        {"address": "defer1", "funnel_decision": DEFER_UNREADABLE, "realized_pnl_usd": "1"},
        {"address": "drop1", "funnel_decision": DROP, "drop_reason": "gt_15_economic_trades_in_one_day"},
    ]
    report = run_batch_funnel(
        rows,
        n=1,
        spend_by_stage={
            "discovery": {"provider": "nansen", "units": 30, "requests": 6},
            "bot_prescreen": {"provider": "helius", "units": 4, "requests": 4},
        },
        wall_s_by_stage={"discovery": 1.2, "bot_prescreen": 0.4},
        output_dir=tmp_path,
    )
    assert report["PRODUCT_READY"] is False
    assert report["survivors"] == ["keep1"]
    assert (tmp_path / "THROUGHPUT_BATCH.json").is_file()
    assert (tmp_path / "THROUGHPUT_BATCH.md").is_file()
    assert report["cost_per_audit_worthy"]["batch"]["audit_worthy"] == 1
    assert report["wall_s_by_stage"]["discovery"] == 1.2
    assert MAX_ECONOMIC_TRADES_PER_UTC_DAY == 15


def test_live_e2e_batch_enables_funnel_and_one_credit_plan(tmp_path):
    cfg = validate_config({
        "mode": "dry-run",
        "grant_path": DRAFT_PATH,
        "output_dir": tmp_path,
        "wallets": ["BatchWallet11111111111111111111111111112"],
        "phases": "2",
        "batch": True,
        "readable_first_n": 1,
        "window_days": 30,
        "earlier_history_days": 60,
    })
    assert cfg["batch"] is True
    assert cfg["readable_first"] is True
    assert cfg["helius_signatures_prescreen"] is True
    assert cfg["nansen_timeframes"] == [30, 90, 180]
    assert cfg["helius_signatures_history_cap"] == 50_000
    plan = plan_request_counts(cfg)
    assert plan["helius_signatures"]["method"] == HELIUS_SIGNATURES_METHOD
    assert plan["helius_signatures"]["units"] == HELIUS_SIGNATURES_UNITS
    assert plan["per_phase"]["2"]["units"] >= 1
    assert plan["batch"] is True
    assert plan["PRODUCT_READY"] is False


def test_signatures_screen_never_marks_a_lead():
    quiet = [{"signature": f"s{i}", "blockTime": IN_WINDOW + (i * 86400)} for i in range(5)]
    out = screen_signatures(quiet)
    assert out["passed"] is True
    assert out["passed_lead"] is False
    assert out["dropped"] is False
    assert out["can_only_drop_or_defer"] is True
