"""Run 9 / 9b regressions. Offline only: no live calls, no secrets."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scanner.mass_search.live_e2e as L
from scanner.mass_search.adapters import BIRDEYE_TOKEN_TXS_PATH, SourceError
from scanner.mass_search.live_e2e_ledger import grant_ledger_path, open_grant_store
from scanner.mass_search.qualification_gates import (
    combined_economic_trade_rate,
    raw_economic_trade_rate,
    with_gt25_blocker,
)
from scanner.mass_search.seed_sources import (
    NANSEN_LEADERBOARD_PATH,
    NANSEN_PNL_SUMMARY_PATH,
    SEED_NANSEN,
    SEED_TOKEN_INTERSECT,
    estimate_seed_plan,
    load_known_wallets_from_outputs,
    nansen_high_frequency_drop,
)
import tools.independent_episode_audit as auditor

ROOT = L.ROOT
JUP = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN_X = "TokenX1111111111111111111111111111111111111"
CFK6 = "CFk6sQA8hHUm1pvafGCr22oeCcbQZceft6Dt7hTGrYPy"
BZSTEP = "BZSTEPUJQLxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
W1 = "4zTQe6QiUWqAD8czsGpXdm8hMHNnh38DF19KS5mXKBa3"
FIX = ROOT / "tests/fixtures/seed_sources"


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    home = tmp_path / "ledger-home"
    home.mkdir()
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(home))
    monkeypatch.setenv("SCANNER_BIRDEYE_BACKOFF_SEC", "0")
    monkeypatch.setenv("SCANNER_BIRDEYE_MIN_INTERVAL_SEC", "0")
    monkeypatch.setenv("SCANNER_HELIUS_MIN_INTERVAL_SEC", "0")
    monkeypatch.delenv("NANSEN_API_KEY", raising=False)
    return home


def _unix(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def _small_sol_swap(wallet, sig, block_time, token=TOKEN_X, token_in=True):
    """Single-token SOL-quoted fill under the old 3e6 lamport noise floor."""
    pre_token = "0" if token_in else "1000000"
    post_token = "1000000" if token_in else "0"
    native_delta = -400_000 if token_in else 400_000
    fee = 5000
    pre_sol = 10_000_000
    post_sol = pre_sol + native_delta - fee
    return {
        "blockTime": block_time,
        "transaction": {
            "signatures": [sig],
            "message": {"accountKeys": [wallet, "11111111111111111111111111111111"]},
        },
        "meta": {
            "err": None,
            "fee": fee,
            "preBalances": [pre_sol, 1],
            "postBalances": [post_sol, 1],
            "preTokenBalances": [
                {"owner": wallet, "mint": token, "uiTokenAmount": {"amount": pre_token}},
            ],
            "postTokenBalances": [
                {"owner": wallet, "mint": token, "uiTokenAmount": {"amount": post_token}},
            ],
        },
    }


def _cfg(tmp_path, **raw):
    out = raw.pop("out", "out")
    base = {
        "mode": "dry-run",
        "grant_path": str(ROOT / L.DRAFT_REL_13),
        "output_dir": str(tmp_path / out),
        "phases": "1",
        "discovery": True,
        "wallets": "",
    }
    base.update(raw)
    cfg = L.validate_config(base)
    Path(cfg["output_dir"]).mkdir(parents=True, exist_ok=True)
    return cfg


def _fx(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_d9_3_cfk6_small_sol_swaps_count_145():
    day = "2026-09-30"
    stamp = _unix(day)
    records = [_small_sol_swap(CFK6, f"cfk6-{i}", stamp + i) for i in range(145)]
    rate = combined_economic_trade_rate(events=[], records=records, address=CFK6)
    assert rate["max"] == 145
    assert rate["max_on"] == day
    independent, _ = auditor.raw_economic_trades_by_utc_day(records, CFK6)
    assert independent[day] == 145
    assert with_gt25_blocker(None, rate)


def test_d9_3_bzstep_small_sol_swaps_count_182():
    day = "2026-09-26"
    stamp = _unix(day)
    records = [_small_sol_swap(BZSTEP, f"bz-{i}", stamp + i) for i in range(182)]
    raw = raw_economic_trade_rate(records, BZSTEP)
    assert raw["max"] == 182
    assert raw["max_on"] == day
    independent, _ = auditor.raw_economic_trades_by_utc_day(records, BZSTEP)
    assert independent[day] == 182


def test_d9_3_unwraps_nested_gta_and_transaction_meta():
    wallet = CFK6
    stamp = _unix("2026-09-30")
    inner = _small_sol_swap(wallet, "nested", stamp)
    wrapped = {"raw": {"result": inner}}
    meta_nested = {
        "blockTime": stamp,
        "transaction": {
            "signatures": ["meta-nested"],
            "message": {"accountKeys": [wallet, "11111111111111111111111111111111"]},
            "meta": inner["meta"],
        },
    }
    rate = raw_economic_trade_rate([wrapped, meta_nested], wallet)
    assert rate["max"] == 2


def test_d9_3_sol_noise_still_drops_fee_only():
    wallet = CFK6
    record = {
        "blockTime": _unix("2026-09-22"),
        "transaction": {"signatures": ["fee"], "message": {"accountKeys": [wallet]}},
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [10_000_000],
            "postBalances": [9_995_000],
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }
    assert raw_economic_trade_rate([record], wallet)["max"] == 0


def test_ds3_history_to_first_plan_uses_per_wallet_cap():
    config = {
        "wallets": [W1],
        "wallets_supplied": True,
        "phases": (3,),
        "window_days": 30,
        "earlier_history_days": 60,
        "history_to_first": True,
        "per_wallet_cap": 40,
        "seed_sources": [SEED_NANSEN],
        "caps": dict(L.HARD_CEILINGS),
        "bounds": {"earlier_history_days": 60, "history_to_first": True},
    }
    state = {
        "phase2": {
            W1: {"address": W1, "dropped": False, "requests": 3, "triage": True, "in_window_tx_count": 100},
        }
    }
    plan = L.plan_request_counts(config, state)
    assert plan["phase3_page_estimates"][W1] == 37
    assert plan["totals"]["helius_requests"] == 37


@pytest.mark.parametrize("cap,in_window", [(16, 100), (12, 10), (40, 100)])
def test_ds3_htf_plan_is_upper_bound_of_runtime(tmp_path, monkeypatch, cap, in_window):
    pages = {W1: 50}
    calls = []

    async def fake(address, *, options, page_index=0):
        calls.append((address, page_index))
        tok = f"tok-{page_index + 1}" if page_index + 1 < pages[address] else None
        recs = [{"blockTime": 1_791_000_000 - page_index, "transaction": {"signatures": [f"{page_index}"], "message": {"accountKeys": [address]}}, "meta": {"err": None, "fee": 5000, "preBalances": [10**9], "postBalances": [10**9 - 5000], "preTokenBalances": [], "postTokenBalances": []}}]
        raw = json.dumps({"jsonrpc": "2.0", "result": {"data": recs, "paginationToken": tok}}).encode()
        return {"records": recs, "pagination_token": tok, "http_status": 200, "raw_bytes": raw, "evidence_sha256": hashlib.sha256(raw).hexdigest(), "units": 0, "external_requests": 1}

    monkeypatch.setattr(L, "_live_helius", fake)
    cfg = L.validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / L.DRAFT_REL_13),
        "output_dir": str(tmp_path / "out"),
        "phases": "3",
        "discovery": False,
        "seed_source": "nansen",
        "wallets": W1,
        "per_wallet_cap": cap,
        "history_to_first": True,
    })
    Path(cfg["output_dir"]).mkdir(parents=True, exist_ok=True)
    cfg["dry_run"] = False
    st = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": [W1],
          "phase2": {W1: {"address": W1, "dropped": False, "requests": 3, "triage": True, "in_window_tx_count": in_window}},
          "bounds": cfg["bounds"]}
    plan = L.plan_request_counts(cfg, st)
    grant = copy.deepcopy(L.load_grant(ROOT / L.DRAFT_REL_13))
    grant["enabled"] = True
    store, _ = open_grant_store(cfg["authorization_id"])
    asyncio.run(L.phase3_history(store, grant, cfg, st, L.RecorderTransport()))
    store.close()
    assert len(calls) <= cap - 3
    assert st["spend"]["helius_requests"] <= plan["totals"]["helius_requests"]


def test_ds4_triage_source_spend_not_double_counted(tmp_path, monkeypatch):
    calls = []

    async def fake(address, *, options, page_index=0):
        calls.append(page_index)
        recs = []
        raw = json.dumps({"jsonrpc": "2.0", "result": {"data": recs, "paginationToken": None}}).encode()
        return {"records": recs, "pagination_token": None, "http_status": 200, "raw_bytes": raw, "evidence_sha256": hashlib.sha256(raw).hexdigest(), "units": 0, "external_requests": 1}

    monkeypatch.setattr(L, "_live_helius", fake)
    cfg = L.validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / L.DRAFT_REL_13),
        "output_dir": str(tmp_path / "out"),
        "phases": "2",
        "discovery": False,
        "seed_source": "token_intersect",
        "wallets": W1,
        "per_wallet_cap": 6,
        "history_to_first": True,
    })
    Path(cfg["output_dir"]).mkdir(parents=True, exist_ok=True)
    cfg["dry_run"] = False
    st = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": [W1], "bounds": cfg["bounds"]}
    grant = copy.deepcopy(L.load_grant(ROOT / L.DRAFT_REL_13))
    grant["enabled"] = True
    store, _ = open_grant_store(cfg["authorization_id"])
    asyncio.run(L.phase2_prescreen(store, grant, cfg, st, L.RecorderTransport()))
    store.close()
    paid = len(calls)
    booked = sum(int(v.get("requests") or 0) for v in (st.get("source_spend") or {}).values())
    assert paid == st["spend"]["helius_requests"]
    assert booked == paid


def test_ds1_dry_run_books_failed_429(tmp_path):
    cfg = _cfg(tmp_path, seed_source="token_intersect", birdeye_tokens=[JUP, BONK, USDC], max_birdeye_requests=40)
    store, _ = open_grant_store(cfg["authorization_id"])
    rec = L.RecorderTransport()
    rec.fixtures = {BIRDEYE_TOKEN_TXS_PATH: _fx("token_txs_seek.json")}
    rec.fail_at = {BIRDEYE_TOKEN_TXS_PATH: {"after": 5, "times": 1}}
    st = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": []}
    grant = L.load_grant(ROOT / L.DRAFT_REL_13)
    asyncio.run(L.phase1_discovery(store, grant, cfg, st, rec))
    store.close()
    assert st["spend"]["birdeye_requests"] == len(rec.calls)
    assert st["spend"]["birdeye_requests"] == 10


def test_ds2_plan_has_retry_headroom_under_429(tmp_path, monkeypatch):
    fake_calls = []

    async def fake(method, path, params):
        fake_calls.append(path)
        n = len(fake_calls)
        if n == 5:
            raise SourceError("RATE_LIMITED", "Birdeye rate limit", http_status=429, retryable=True)
        body = _fx("token_txs_seek.json")
        raw = json.dumps(body).encode()
        return {"status": 200, "body": body, "fetched_at": "x", "raw_bytes": raw}

    monkeypatch.setattr(L, "_live_birdeye", fake)
    grant = copy.deepcopy(L.load_grant(ROOT / L.DRAFT_REL_13))
    grant["enabled"] = True
    cfg = _cfg(tmp_path, seed_source="token_intersect", birdeye_tokens=[JUP, BONK, USDC])
    cfg["dry_run"] = False
    plan = L.plan_request_counts(cfg, {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": []})
    store, _ = open_grant_store(cfg["authorization_id"])
    st = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": []}
    asyncio.run(L.phase1_discovery(store, grant, cfg, st, L.RecorderTransport()))
    store.close()
    assert st["spend"]["birdeye_requests"] <= plan["totals"]["birdeye_requests"]
    assert plan["totals"]["birdeye_requests"] >= 10


def test_grant_14_is_live_known_with_own_ledger_and_disabled():
    path = ROOT / L.DRAFT_REL_14
    draft = json.loads(path.read_text(encoding="utf-8"))
    assert draft["enabled"] is False
    assert draft["PRODUCT_READY"] is False
    assert draft["authorization_id"] == L.AUTHORIZATION_ID_14
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert L.PINNED_DRAFT_HASHES[L.AUTHORIZATION_ID_14] == digest
    assert L.AUTHORIZATION_ID_14 in L.LIVE_KNOWN_DRAFTS
    nansen = next(row for row in draft["providers"] if row["provider_id"] == "nansen")
    assert nansen["max_requests"] == 60
    assert nansen["max_units"] == 300
    assert L.HARD_CEILINGS["nansen_requests"] == 60
    assert L.HARD_CEILINGS["nansen_units"] == 300
    p13 = grant_ledger_path(L.AUTHORIZATION_ID_13, home="/tmp/ledgers")
    p14 = grant_ledger_path(L.AUTHORIZATION_ID_14, home="/tmp/ledgers")
    assert p13 != p14
    assert p14.name == L.AUTHORIZATION_ID_14


def test_draft_13_hash_unchanged():
    digest = hashlib.sha256((ROOT / L.DRAFT_REL_13).read_bytes()).hexdigest()
    assert L.PINNED_DRAFT_HASHES[L.AUTHORIZATION_ID_13] == digest
    assert digest == "e9629ca44a48671bb9a61c1b3c2ec19a42aa5338b1fc53e00c55498fe3254a2e"


def test_nansen_pagination_and_exclude_known(tmp_path, monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", "offline-fixture-not-a-live-secret")
    known_dir = tmp_path / "prior"
    known_dir.mkdir()
    (known_dir / "STATE.json").write_text(json.dumps({
        "wallets": ["jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"],
    }), encoding="utf-8")
    assert "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ" in load_known_wallets_from_outputs([known_dir])
    cfg = _cfg(tmp_path, seed_source="nansen", nansen_profile_cap=0, nansen_leaderboard_pages=2)
    cfg["exclude_known_from"] = [str(known_dir)]
    cfg["nansen_enabled"] = True
    store, _ = open_grant_store(cfg["authorization_id"])
    rec = L.RecorderTransport()
    rec.fixtures = {NANSEN_LEADERBOARD_PATH: _fx("nansen_leaderboard.json")}
    st = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": []}
    plan = L.plan_request_counts(cfg, st)
    assert plan["totals"]["nansen_requests"] == 4
    grant = L.load_grant(ROOT / L.DRAFT_REL_13)
    result = asyncio.run(L.phase1_discovery(store, grant, cfg, st, rec))
    store.close()
    assert "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ" not in result["addresses"]
    assert "Gygj9QQby4j2jryqyqBHvLP7ctv2SaANgh4sCb69BUpA" in result["addresses"]
    lb = [c for c in rec.calls if c.get("path") == NANSEN_LEADERBOARD_PATH]
    assert len(lb) == 4
    pages = {c["body"]["pagination"]["page"] for c in lb}
    assert pages == {1, 2}


def test_token_intersect_import_by_path_no_http(tmp_path):
    grant = L.load_grant(ROOT / L.DRAFT_REL_13)
    first = _cfg(tmp_path, seed_source="token_intersect", birdeye_tokens=[JUP, BONK, USDC], out="prior")
    Path(first["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(first["authorization_id"])
    rec = L.RecorderTransport()
    rec.fixtures = {BIRDEYE_TOKEN_TXS_PATH: _fx("token_txs_seek.json")}
    st = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": []}
    first_result = asyncio.run(L.phase1_discovery(store, grant, first, st, rec))
    store.close()
    paid = len(rec.calls)
    assert paid >= 9
    second = _cfg(
        tmp_path, seed_source="token_intersect", birdeye_tokens=[JUP, BONK, USDC],
        import_raw_dir=first["output_dir"], out="fresh",
    )
    Path(second["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(second["authorization_id"])
    rec2 = L.RecorderTransport()
    rec2.fixtures = {BIRDEYE_TOKEN_TXS_PATH: {"data": {"items": []}}}
    st2 = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": []}
    imported = asyncio.run(L.phase1_discovery(store, grant, second, st2, rec2))
    store.close()
    ti = (imported.get("per_source") or {}).get(SEED_TOKEN_INTERSECT) or {}
    assert rec2.calls == []
    assert st2["spend"]["birdeye_requests"] == 0
    assert ti.get("imported") is True
    assert imported["addresses"] == first_result["addresses"]


def test_d9_4_higher_cap_marks_capped_wallet_pending():
    state = {
        "phase2": {W1: {"address": W1, "dropped": False, "requests": 3, "triage": True}},
        "phase3": {W1: {
            "pages": 1, "requests": 1, "done": True,
            "history_complete": False,
            "history_complete_reason": "per_wallet_cap",
            "leftover_pagination_token": True,
        }},
    }
    low = {"per_wallet_cap": 4, "seed_sources": [SEED_NANSEN]}
    high = {"per_wallet_cap": 8, "seed_sources": [SEED_NANSEN]}
    assert L.phase3_needs_more_pages(low, state, W1, triage=True) is False
    assert L.phase3_needs_more_pages(high, state, W1, triage=True) is True


def test_d9_4_resume_run_enters_phase3_for_capped_wallet(tmp_path, monkeypatch):
    calls = []

    async def fake_history(store, grant, config, state, recorder):
        calls.append(config.get("per_wallet_cap"))
        for address in L.phase3_wallets(config, state):
            cursor = dict((state.get("phase3") or {}).get(address) or {})
            cursor["done"] = True
            cursor["pages"] = int(cursor.get("pages") or 0) + 2
            cursor["requests"] = int(cursor.get("requests") or 0) + 2
            cursor["history_complete_reason"] = "per_wallet_cap"
            cursor["leftover_pagination_token"] = True
            state.setdefault("phase3", {})[address] = cursor
        return {"pages": state["phase3"]}

    monkeypatch.setattr(L, "phase3_history", fake_history)
    out = tmp_path / "out"
    out.mkdir()
    cfg = L.validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / L.DRAFT_REL_13),
        "output_dir": str(out),
        "phases": "3",
        "discovery": False,
        "seed_source": "nansen",
        "wallets": W1,
        "per_wallet_cap": 4,
        "history_to_first": True,
        "resume": True,
    })
    state = {
        "wallets": [W1],
        "phases_done": [2, 3],
        "bounds": cfg["bounds"],
        "spend": L.empty_spend(),
        "phase_spend": L.empty_phase_spend(),
        "phase2": {W1: {"address": W1, "dropped": False, "done": True, "requests": 3, "triage": True}},
        "phase3": {W1: {
            "address": W1, "pages": 1, "requests": 1, "done": True,
            "history_complete": False, "history_complete_reason": "per_wallet_cap",
            "leftover_pagination_token": True, "pagination_token": "tok1",
        }},
        "PRODUCT_READY": False,
    }
    L.save_state(str(out), state)
    result = asyncio.run(L.run_live_e2e({
        "mode": "dry-run",
        "grant_path": str(ROOT / L.DRAFT_REL_13),
        "output_dir": str(out),
        "phases": "3",
        "discovery": False,
        "seed_source": "nansen",
        "wallets": W1,
        "per_wallet_cap": 8,
        "history_to_first": True,
        "resume": True,
    }))
    assert calls == [8]
    persisted = json.loads((out / L.STATE_NAME).read_text(encoding="utf-8"))
    assert persisted["phase3"][W1]["pages"] == 3
    assert result["status"] in ("completed", "blocked", "started") or "phase3" in persisted


def test_d9_5_window_start_from_oldest_even_on_cap():
    end = datetime(2026, 10, 8, 0, 52, 22, tzinfo=timezone.utc)
    bounds = L.window_bounds(30, 60, end=end, history_to_first=True, report_window_days=30)
    oldest_reached = int((end.timestamp())) - (35 * 86400)
    oldest_short = int((end.timestamp())) - (5 * 86400)
    reached = L.window_reach_from_oldest(oldest_reached, bounds)
    short = L.window_reach_from_oldest(oldest_short, bounds)
    assert reached["history_reached_window_start"] is True
    assert reached["window_start_reached"]["30"] is True
    assert short["history_reached_window_start"] is False
    assert short["window_start_reached"]["30"] is False
    cursor = {}
    L.apply_window_reach(cursor, [{"blockTime": oldest_reached}], bounds)
    assert cursor["history_reached_window_start"] is True


def test_d9_5_early_stop_does_not_force_window_false(tmp_path, monkeypatch):
    end = datetime(2026, 10, 8, 0, 52, 22, tzinfo=timezone.utc)
    start = int(end.timestamp()) - 30 * 86400
    day = start - 3600
    events = [{"kind": "buy", "signature": f"hot{i}", "mint": f"M{i}", "timestamp": day + i} for i in range(26)]
    monkeypatch.setattr(
        "scanner.mass_search.live_e2e.decode_supported_swaps",
        lambda records, address: {"events": events},
    )

    async def fake_dispatch(store, grant, config, state, transport, address, options, *, phase, page_index):
        recs = [{"signature": f"hot{i}", "blockTime": day + i} for i in range(26)]
        return {"records": recs, "pagination_token": "more", "evidence_sha256": "abc"}

    monkeypatch.setattr(L, "_dispatch_helius", fake_dispatch)
    grant = L.load_grant(ROOT / L.DRAFT_REL_13)
    cfg = L.validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / L.DRAFT_REL_13),
        "output_dir": str(tmp_path / "out"),
        "phases": "3",
        "discovery": False,
        "seed_source": "nansen",
        "wallets": W1,
        "per_wallet_cap": 8,
        "history_to_first": True,
    })
    cfg["bounds"] = L.window_bounds(30, 60, end=end, history_to_first=True, report_window_days=30)
    Path(cfg["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(cfg["authorization_id"])
    st = {
        "spend": L.empty_spend(),
        "phase_spend": L.empty_phase_spend(),
        "wallets": [W1],
        "phase2": {W1: {"address": W1, "dropped": False, "requests": 3, "triage": True}},
        "seed_metadata": {W1: {"seed_sources": [SEED_NANSEN], "primary_seed_source": SEED_NANSEN}},
    }
    result = asyncio.run(L.phase3_history(store, grant, cfg, st, L.RecorderTransport()))
    store.close()
    cursor = result["pages"][W1]
    assert cursor["early_stop_bot_rate"] is True
    assert cursor["history_reached_window_start"] is True
    assert cursor["window_start_reached"]["30"] is True


def test_nansen_prefilter_drops_only_obvious_hf():
    drop_trades = nansen_high_frequency_drop({"n_trades": 4000}, timeframe=90)
    assert drop_trades["dropped"] is True
    assert drop_trades["can_only_drop"] is True
    drop_hold = nansen_high_frequency_drop({"n_trades": 10, "avg_hold_seconds": 12}, timeframe=90)
    assert drop_hold["dropped"] is True
    keep_missing = nansen_high_frequency_drop({}, timeframe=90)
    assert keep_missing["dropped"] is False
    keep_low = nansen_high_frequency_drop({"n_trades": 14}, timeframe=90)
    assert keep_low["dropped"] is False


def test_nansen_prefilter_applied_before_helius(tmp_path, monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", "offline-fixture-not-a-live-secret")
    cfg = _cfg(tmp_path, seed_source="nansen", nansen_profile_cap=0)
    cfg["nansen_enabled"] = True
    store, _ = open_grant_store(cfg["authorization_id"])
    rec = L.RecorderTransport()
    rec.fixtures = {
        NANSEN_LEADERBOARD_PATH: {
            "data": [
                {"address": W1, "n_trades": 5000, "realized_pnl_usd": 1},
                {"address": "Gygj9QQby4j2jryqyqBHvLP7ctv2SaANgh4sCb69BUpA", "n_trades": 8, "realized_pnl_usd": 1},
            ]
        },
        NANSEN_PNL_SUMMARY_PATH: {"realized_pnl_usd": 1},
    }
    st = {"spend": L.empty_spend(), "phase_spend": L.empty_phase_spend(), "wallets": []}
    grant = L.load_grant(ROOT / L.DRAFT_REL_13)
    asyncio.run(L.phase1_discovery(store, grant, cfg, st, rec))
    store.close()
    assert W1 not in st["wallets"]
    assert W1 in (st.get("nansen_prefilter_dropped") or {})
    assert (tmp_path / "out" / "NANSEN_PREFILTER_DROPPED.json").is_file()
    log = json.loads((tmp_path / "out" / "NANSEN_PREFILTER_DROPPED.json").read_text(encoding="utf-8"))
    assert log["can_only_drop"] is True
    assert log["count"] >= 1
    assert "Gygj9QQby4j2jryqyqBHvLP7ctv2SaANgh4sCb69BUpA" in st["wallets"]


def test_arg_parser_has_run9_ops_flags():
    args = L.build_arg_parser().parse_args([
        "--dry-run", "--grant", "config/x.json", "--output", "/tmp/out",
        "--nansen-leaderboard-pages", "3",
        "--exclude-known-from", "/tmp/prior",
        "--import-raw-dir", "/tmp/old-raw",
    ])
    assert args.nansen_leaderboard_pages == 3
    assert args.exclude_known_from == ["/tmp/prior"]
    assert args.import_raw_dir == ["/tmp/old-raw"]


def test_estimate_seed_plan_retry_headroom_default():
    plan = estimate_seed_plan([SEED_TOKEN_INTERSECT], tokens=[JUP, BONK, USDC], discovery=True)
    assert plan["totals"]["birdeye_requests"] == 11
    assert plan["per_source"][SEED_TOKEN_INTERSECT]["retry_headroom_requests"] == 2
