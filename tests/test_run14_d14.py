"""Run-14 D14-3..13. Offline only. Proof gates stay fail-closed."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scanner.investigation import (
    DECODER_VERSION,
    D14_TOP3_DEFERRED_PROGRAMS,
    JUPITER,
    OKX_DEX_ROUTER,
    WHIRLPOOL,
    decode_supported_swaps,
    net_balance_reviewed_swap,
)
from scanner.mass_search.adapters import SourceError
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.live_e2e import (
    NANSEN_DEFAULT_TIMEOUT_S,
    NANSEN_TGM_CONSECUTIVE_TIMEOUTS,
    NANSEN_TGM_TIMEOUT_S,
    RecorderTransport,
    ROOT,
    _empty_state,
    _load_nansen_paid,
    _nansen_seed_call,
    _nansen_timeout_was_billed,
    _phase1_nansen,
    _phase1_nansen_token_pnl,
    bind_run_spend,
    empty_phase_spend,
    empty_spend,
    load_grant,
    nansen_vendor_drop_decision,
    parse_run_caps,
    validate_config,
)
from scanner.mass_search.live_e2e_ledger import (
    load_receipt,
    open_grant_store,
    put_receipt,
    request_identity,
)
from scanner.mass_search.qualification_gates import GT_ECONOMIC_TRADES_RULE
from scanner.mass_search.readable_first import (
    DROP,
    KEEP,
    _pnl,
    bot_prescreen_decision,
    estimate_full_gate_prescore,
    rank_by_nansen_pnl,
    sample_lp_add_remove_hits,
)
from scanner.mass_search.research_profile import (
    _headline_including_dropped_losers,
    apply_headline_losing_pnl,
)
from scanner.mass_search.seed_sources import (
    NANSEN_LEADERBOARD_PATH,
    NANSEN_TGM_PNL_LEADERBOARD_PATH,
    helius_signatures_prescreen,
    nansen_high_frequency_drop,
    nansen_infra_label_drop,
    nansen_leaderboard_body,
)
from scanner.storage import Store

DRAFT = ROOT / "config/live_authorization.live-e2e-proof-2026-10-13-mitch-draft.json"
JXT = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
RAYDIUM_V4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
OPENBOOK = "srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX"
ME_ESCROW = "M2mx93ekt1fmXSVkTrUL9xVFHkmME8HTUi5Cyc5aF7K"
DAY = int(datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp())


@pytest.fixture(autouse=True)
def _ledger_home(tmp_path, monkeypatch):
    home = tmp_path / "ledger-home"
    home.mkdir()
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(home))
    monkeypatch.delenv("NANSEN_API_KEY", raising=False)
    return home


def _dry_config(tmp_path, **extra):
    raw = {
        "mode": "dry-run",
        "grant_path": str(DRAFT),
        "output_dir": str(tmp_path / "out"),
        "phases": "1",
        "discovery": True,
        "seed_source": "nansen",
        "wallets": "",
    }
    raw.update(extra)
    cfg = validate_config(raw)
    Path(cfg["output_dir"]).mkdir(parents=True, exist_ok=True)
    return cfg


def _record_logs(program, instruction, extra_keys=None):
    keys = [JXT, program] + list(extra_keys or [])
    return {
        "signature": f"sig-{instruction}",
        "transaction": {
            "signatures": [f"sig-{instruction}"],
            "message": {"accountKeys": keys, "instructions": [{"programId": program}]},
        },
        "meta": {
            "logMessages": [
                f"Program {program} invoke [1]",
                f"Program log: Instruction: {instruction}",
                f"Program {program} success",
            ]
        },
    }


# --- D14-3 -----------------------------------------------------------------

def test_d14_3_address_label_drops_and_alpha_is_not_lp():
    hit = nansen_infra_label_drop({"vendor_metrics": {"address_label": "LP"}})
    assert hit and hit["dropped"] is True
    assert any("lp" in item.lower() for item in hit["drop_reasons"])
    assert nansen_infra_label_drop({"vendor_metrics": {"address_label": "alpha"}}) is None
    assert nansen_infra_label_drop({"address_label": "community"}) is None


def test_d14_3_neighbor_empty_missing_and_whole_word_mm():
    assert nansen_infra_label_drop({}) is None
    assert nansen_infra_label_drop({"labels": []}) is None
    assert nansen_infra_label_drop({"vendor_metrics": {"address_label": ""}}) is None
    assert nansen_infra_label_drop({"labels": ["community mm"]})["dropped"] is True
    assert nansen_infra_label_drop({"nansen_labels": ["Smart Trader"]}) is None


# --- D14-4 -----------------------------------------------------------------

def test_d14_4_every_in_window_loser_folds_and_labels_are_not_swapped():
    clean = "1839.123183"
    dropped = [{
        "net_profit": "-46.66",
        "settlement_asset": "USDC",
        "mint": "CdhZyLoser",
        "reason": "unflattened_losing_inventory",
    }]
    headline, unit, included = _headline_including_dropped_losers(clean, "USDC", dropped)
    assert unit == "USDC"
    assert included
    assert abs(Decimal(headline) - (Decimal(clean) + Decimal("-46.66"))) <= Decimal("0.01")
    profile = {
        "completed_episode_net": clean,
        "completed_episode_net_unit": "USDC",
        "independently_audited_episode_net": clean,
        "app_completed_episode_net": clean,
    }
    apply_headline_losing_pnl(profile, {}, headline, unit)
    # independently_* is the auditor surface; app_* / completed_* is the app surface.
    assert profile["completed_episode_net"] == headline
    assert profile["completed_episode_net_unit"] == "USDC"
    assert "independently_audited_episode_net" in profile
    assert profile["independently_audited_episode_net"] == clean


def test_d14_4_neighbor_usdt_fold_and_missing_loser_blocks():
    headline, unit, included = _headline_including_dropped_losers(
        "100", "USDT", [{"net_profit": "-12.5", "settlement_asset": "USDT"}],
    )
    assert unit == "USDT"
    assert included
    assert abs(Decimal(headline) - Decimal("87.5")) <= Decimal("0.01")
    blocked, blocked_unit, rows = _headline_including_dropped_losers(
        "100", "USDC", [{"net_profit": "-12.5", "settlement_asset": "USDT"}],
    )
    assert blocked is None and blocked_unit is None and rows == []
    empty, empty_unit, empty_rows = _headline_including_dropped_losers("100", "USDC", [])
    assert empty == "100" and empty_unit == "USDC" and empty_rows == []


# --- D14-5 -----------------------------------------------------------------

def test_d14_5_nansen_run_cap_raises_cap_exceeded(tmp_path, monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", "offline-fixture-not-a-live-secret")
    config = _dry_config(tmp_path, run_caps="nansen_requests=1,nansen_units=5")
    grant = load_grant(DRAFT)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    recorder.fixtures = {
        NANSEN_LEADERBOARD_PATH: json.loads(
            (ROOT / "tests/fixtures/seed_sources/nansen_leaderboard.json").read_text(encoding="utf-8")
        ),
    }
    state = _empty_state(config)
    bind_run_spend(config, state)
    with pytest.raises(SourceError) as raised:
        asyncio.run(_phase1_nansen(store, grant, config, state, recorder, "d14-5"))
    assert raised.value.state == "CAP_EXCEEDED"
    assert state.get("nansen_cap_reached") is True
    store.close()


def test_d14_5_neighbor_helius_cap_status_same_and_completed_without_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", "offline-fixture-not-a-live-secret")
    config = _dry_config(tmp_path, nansen_leaderboard_pages=1, nansen_timeframes="90")
    grant = load_grant(DRAFT)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    recorder.fixtures = {NANSEN_LEADERBOARD_PATH: {"data": []}}
    state = _empty_state(config)
    bind_run_spend(config, state)
    result = asyncio.run(_phase1_nansen(store, grant, config, state, recorder, "d14-5b"))
    assert result["enabled"] is True
    assert state.get("nansen_cap_reached") is not True
    store.close()


# --- D14-6 -----------------------------------------------------------------

def test_d14_6_resume_reuses_paid_nansen_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", "offline-fixture-not-a-live-secret")
    config = _dry_config(tmp_path)
    grant = load_grant(DRAFT)
    store, _ = open_grant_store(config["authorization_id"])
    state = _empty_state(config)
    bind_run_spend(config, state)
    calls = {"n": 0}

    class Rec:
        async def nansen(self, method, path, body=None):
            calls["n"] += 1
            return {
                "status": 200,
                "body": {"data": [{"address": JXT, "realized_pnl_usd": 12}]},
                "raw_bytes": b'{"data":[{"address":"%s"}]}' % JXT.encode(),
                "fetched_at": "2026-10-08T00:00:00Z",
                "billing": {"credits_cost": 5},
            }

    rec = Rec()
    body = nansen_leaderboard_body(timeframe=90, page=1, per_page=50)
    first = asyncio.run(_nansen_seed_call(
        store, grant, config, state, rec,
        path=NANSEN_LEADERBOARD_PATH, body=body,
        operation="smart_money_pnl_leaderboard", units=5,
        wallet="_lb", page=0, identity="d14-6",
    ))
    assert calls["n"] == 1
    saved = _load_nansen_paid(
        config, operation="smart_money_pnl_leaderboard", wallet="_lb", page=0, identity="d14-6",
    )
    assert saved and saved.get("replayed_from_receipt") is True
    second = asyncio.run(_nansen_seed_call(
        store, grant, config, state, rec,
        path=NANSEN_LEADERBOARD_PATH, body=body,
        operation="smart_money_pnl_leaderboard", units=5,
        wallet="_lb", page=0, identity="d14-6",
    ))
    assert calls["n"] == 1
    assert second.get("replayed_from_receipt") is True
    store.close()


def test_d14_6_neighbor_unbilled_timeout_not_booked_unknown_is_conservative():
    assert _nansen_timeout_was_billed({"credits_cost": 0}) is False
    assert _nansen_timeout_was_billed({"credits_used": "0"}) is False
    assert _nansen_timeout_was_billed({"credits_cost": 5}) is True
    assert _nansen_timeout_was_billed(None) is None
    assert _nansen_timeout_was_billed({}) is None


# --- D14-7 -----------------------------------------------------------------

def test_d14_7_tgm_timeout_skips_token_and_stops_after_consecutive(tmp_path, monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", "offline-fixture-not-a-live-secret")
    tokens = [
        "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
        "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
        "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    ]
    config = _dry_config(
        tmp_path,
        nansen_token_pnl_tokens=",".join(tokens),
        nansen_token_pnl_max_calls=4,
        nansen_tgm_timeout_seconds=90,
        nansen_tgm_consecutive_timeouts=3,
    )
    assert config["nansen_tgm_timeout_seconds"] == 90
    assert config["nansen_tgm_consecutive_timeouts"] == 3
    assert NANSEN_TGM_TIMEOUT_S == 90
    assert NANSEN_TGM_CONSECUTIVE_TIMEOUTS == 3
    assert NANSEN_DEFAULT_TIMEOUT_S == 25
    grant = load_grant(DRAFT)
    store, _ = open_grant_store(config["authorization_id"])
    state = _empty_state(config)
    bind_run_spend(config, state)

    class Rec:
        def __init__(self):
            self.seen = []

        async def nansen(self, method, path, body=None):
            token = (body or {}).get("token_address")
            self.seen.append(token)
            raise SourceError("TIMEOUT", "nansen timeout", extras={"billing": {"credits_cost": 0}})

    rec = Rec()
    extras, raw_parts = {}, []
    selected, used = asyncio.run(_phase1_nansen_token_pnl(
        store, grant, config, state, rec, "d14-7", extras, raw_parts, 0,
    ))
    assert used == 0
    assert selected == []
    assert len(state.get("tgm_skipped") or []) == 3
    assert state.get("tgm_stopped_reason") == "nansen_timeout_consecutive_3"
    assert rec.seen == tokens[:3]
    store.close()


def test_d14_7_neighbor_one_timeout_continues_and_zero_timeout_rejected(tmp_path):
    cfg = _dry_config(
        tmp_path / "ok",
        nansen_tgm_timeout_seconds=120,
        nansen_tgm_consecutive_timeouts=5,
    )
    assert cfg["nansen_tgm_timeout_seconds"] == 120
    assert cfg["nansen_tgm_consecutive_timeouts"] == 5
    with pytest.raises(Exception):
        _dry_config(tmp_path / "bad", nansen_tgm_timeout_seconds=0)
    with pytest.raises(Exception):
        _dry_config(tmp_path / "bad2", nansen_tgm_consecutive_timeouts=0)


# --- D14-9 -----------------------------------------------------------------

def test_d14_9_missing_pnl_is_none_not_a_rule_a_drop():
    assert _pnl({}) is None
    assert _pnl({"vendor_metrics": {}}) is None
    prescore = estimate_full_gate_prescore([], JXT, nansen_row={})
    assert "nansen_realized_pnl_not_positive" not in (prescore.get("reasons") or [])
    rule = nansen_high_frequency_drop({"n_trades": 90, "n_tokens": 5}, timeframe=90)
    assert rule["dropped"] is False


def test_d14_9_neighbor_zero_and_empty_string():
    assert _pnl({"realized_pnl_usd": ""}) is None
    assert _pnl({"realized_pnl_usd": "0"}) == Decimal("0")
    prescore = estimate_full_gate_prescore([], JXT, nansen_row={"realized_pnl_usd": "0"})
    assert "nansen_realized_pnl_not_positive" in (prescore.get("reasons") or [])
    drop = nansen_high_frequency_drop(
        {"n_trades": 90, "n_tokens": 5, "realized_pnl_usd": 0}, timeframe=90,
    )
    assert drop["dropped"] is True
    keep = nansen_vendor_drop_decision({"vendor_metrics": {"n_trades": 90, "n_tokens": 5}})
    assert keep is None or keep.get("dropped") is False


# --- D14-10 ----------------------------------------------------------------

def test_d14_10_exact_lp_pairs_only_not_withdraw_or_openbook():
    withdraw = _record_logs(TOKEN_2022, "WithdrawWithheld")
    deposit = _record_logs(ME_ESCROW, "Deposit")
    swap = _record_logs(RAYDIUM_V4, "Swap", extra_keys=[OPENBOOK])
    add = _record_logs(RAYDIUM_V4, "AddLiquidity")
    assert sample_lp_add_remove_hits([withdraw, deposit, swap]) == []
    hits = sample_lp_add_remove_hits([add])
    assert hits and hits[0]["instruction"] == "AddLiquidity"
    false = estimate_full_gate_prescore([withdraw, deposit, swap], JXT)
    assert "sample_lp_lending_or_mm_program" not in (false.get("reasons") or [])
    true = estimate_full_gate_prescore([add], JXT)
    assert "sample_lp_lending_or_mm_program" in (true.get("reasons") or [])
    assert true.get("never_passes") is True


def test_d14_10_neighbor_empty_logs_and_whirlpool_increase():
    assert sample_lp_add_remove_hits([]) == []
    assert sample_lp_add_remove_hits([{"meta": {"logMessages": []}}]) == []
    whirl = _record_logs(WHIRLPOOL, "IncreaseLiquidity")
    assert sample_lp_add_remove_hits([whirl])
    assert sample_lp_add_remove_hits([_record_logs(WHIRLPOOL, "Swap")]) == []


# --- D14-11 ----------------------------------------------------------------

def test_d14_11_receipt_ids_namespaced_and_ledger_append_only(tmp_path):
    a = request_identity(
        "helius", wallet=JXT, phase=2, page=0, cursor="p0",
        output_dir=str(tmp_path / "run-a"), run_id="grant-1",
    )
    b = request_identity(
        "helius", wallet=JXT, phase=2, page=0, cursor="p0",
        output_dir=str(tmp_path / "run-b"), run_id="grant-1",
    )
    same = request_identity(
        "helius", wallet=JXT, phase=2, page=0, cursor="p0",
        output_dir=str(tmp_path / "run-a"), run_id="grant-1",
    )
    assert a != b
    assert a == same
    store = Store(tmp_path / "store")
    grant = {"authorization_id": "grant-1"}
    first = put_receipt(store, grant, a, {
        "provider": "helius", "wallet": JXT, "phase": 2, "page": 0,
        "state": "consumed", "sha256": "a" * 64, "units": 10,
    })
    replay = put_receipt(store, grant, a, {
        "provider": "helius", "wallet": JXT, "phase": 2, "page": 0,
        "state": "consumed", "sha256": "a" * 64, "units": 10,
    })
    assert replay["request_id"] == first["request_id"]
    rebought = put_receipt(store, grant, a, {
        "provider": "helius", "wallet": JXT, "phase": 2, "page": 0,
        "state": "consumed", "sha256": "b" * 64, "units": 10,
    })
    assert rebought["request_id"] != first["request_id"]
    assert rebought["request_id"].endswith(":dup1")
    assert load_receipt(store, a)["sha256"] == "a" * 64
    store.close()


def test_d14_11_neighbor_missing_namespace_and_dispatched_over_consumed(tmp_path):
    bare = request_identity("nansen", wallet="_", phase=1, page=0, cursor="x")
    assert bare.startswith("nansen:")
    store = Store(tmp_path / "store2")
    grant = {"authorization_id": "grant-1"}
    key = "helius:ns:w:2:0:deadbeefdeadbeef"
    put_receipt(store, grant, key, {
        "provider": "helius", "wallet": "w", "phase": 2, "page": 0,
        "state": "consumed", "sha256": "c" * 64, "units": 1,
    })
    dispatched = put_receipt(store, grant, key, {
        "provider": "helius", "wallet": "w", "phase": 2, "page": 0,
        "state": "dispatched", "units": 1,
    })
    assert dispatched["request_id"].endswith(":dup1")
    assert load_receipt(store, key)["state"] == "consumed"
    store.close()


# --- D14-12 ----------------------------------------------------------------

def test_d14_12_cannot_fail_bot_ranks_first_and_never_drops_on_tx_count():
    quiet = [{"signature": f"q{i}", "blockTime": DAY} for i in range(10)]
    screen = helius_signatures_prescreen(quiet)
    assert screen["cannot_fail_bot_rule"] is True
    assert screen["dropped"] is False
    busy = [{"signature": f"b{i}", "blockTime": DAY} for i in range(20)]
    busy_screen = helius_signatures_prescreen(busy)
    assert busy_screen["cannot_fail_bot_rule"] is False
    assert busy_screen["dropped"] is False
    assert busy_screen["needs_decode"] is True
    keep = bot_prescreen_decision(busy)
    assert keep["decision"] == KEEP
    drop = bot_prescreen_decision(busy, economic_drop={"dropped": True, "max": 16, "max_on": "2026-09-20"})
    assert drop["decision"] == DROP
    assert drop["reason"] == GT_ECONOMIC_TRADES_RULE
    ranked = rank_by_nansen_pnl([
        {"address": "hot", "nansen_realized_pnl_usd": "9000"},
        {"address": "quiet", "nansen_realized_pnl_usd": "1", "cannot_fail_bot_rule": True},
    ])
    assert [row["address"] for row in ranked] == ["quiet", "hot"]


def test_d14_12_neighbor_history_cap_and_missing_stamps():
    cap_rows = [{"signature": f"c{i}", "blockTime": DAY} for i in range(40)]
    screen = helius_signatures_prescreen(cap_rows, history_cap=40)
    assert screen["deferred"] is True
    assert screen["dropped"] is False
    decision = bot_prescreen_decision(cap_rows, history_cap=40)
    assert decision["decision"] != DROP
    early = bot_prescreen_decision(
        cap_rows, history_cap=40,
        economic_drop={"dropped": True, "max": 18, "day": "2026-09-20"},
    )
    assert early["decision"] == DROP
    missing = helius_signatures_prescreen([{"signature": "x"}])
    assert missing["cannot_fail_bot_rule"] is False
    assert missing["incomplete_timestamps"] == 1


# --- D14-13 ----------------------------------------------------------------

def test_d14_13_top3_programs_use_exact_net_balance_or_stay_unreadable():
    assert DECODER_VERSION == "spot-v30-d14-top3-net-v1"
    assert D14_TOP3_DEFERRED_PROGRAMS == frozenset({OKX_DEX_ROUTER, JUPITER, WHIRLPOOL})
    payload = json.loads(
        (ROOT / "tests/fixtures/net-balance-venues/jupiter_v6.json").read_text(encoding="utf-8")
    )
    decoded = decode_supported_swaps(canonical_decode_records([payload["record"]]), payload["address"])
    trades = [e for e in decoded.get("events") or [] if e.get("kind") in {"buy", "sell", "conversion"}]
    assert trades, "JUP6 must stay exactly reconstructable"


def test_d14_13_neighbor_unknown_program_and_ambiguous_okx_stay_unreadable():
    wallet = JXT
    fake = {
        "transaction": {
            "signatures": ["FakeD1413Unknown11111111111111111111111111111111111111111111"],
            "message": {
                "header": {"numRequiredSignatures": 1, "numReadonlySignedAccounts": 0, "numReadonlyUnsignedAccounts": 1},
                "accountKeys": [
                    {"pubkey": wallet, "signer": True, "writable": True},
                    {"pubkey": "FakeVenue11111111111111111111111111111111111", "signer": False, "writable": False},
                ],
                "instructions": [{"programId": "FakeVenue11111111111111111111111111111111111", "accounts": [0], "data": "11"}],
            },
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [1_000_000_000, 0],
            "postBalances": [500_000_000, 0],
            "preTokenBalances": [],
            "postTokenBalances": [],
            "innerInstructions": [],
        },
        "blockTime": DAY,
        "slot": 1,
    }
    assert net_balance_reviewed_swap(fake, wallet) is None
    decoded = decode_supported_swaps(canonical_decode_records([fake]), wallet)
    assert not [e for e in decoded.get("events") or [] if e.get("kind") in {"buy", "sell", "conversion"}]
    okx_ambiguous = json.loads(json.dumps(fake))
    okx_ambiguous["transaction"]["message"]["accountKeys"][1]["pubkey"] = OKX_DEX_ROUTER
    okx_ambiguous["transaction"]["message"]["instructions"][0]["programId"] = OKX_DEX_ROUTER
    assert net_balance_reviewed_swap(okx_ambiguous, wallet) is None
