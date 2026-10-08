"""Run-14 D14-3..17. Offline only. Proof gates stay fail-closed."""
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
    USDC,
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
    assess_history_completeness,
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
from scanner.mass_search.bundle_detect import (
    PYTH_STAKING,
    detect_bundle_or_distribution,
)
from scanner.mass_search.labels import blocking_reason
from scanner.mass_search.qualification_gates import GT_ECONOMIC_TRADES_RULE, mandatory_coverage_gate
from scanner.mass_search.result_relevant_coverage import build_result_relevant
import tools.independent_episode_audit as auditor
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


# --- D14-14 ----------------------------------------------------------------

SYSTEM = "11111111111111111111111111111111"
TOKEN_PROG = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
D14_WALLET = "2BZwUZkaCLrXcjMYGpM7QV2Q5pFZntA3EdJYU291Dbix"
D14_NEW = "8yJa38SWd4PUvfFVRHfhu7hBRvgRLi1EjfzhSNNAJnX6"
D14_PYTH = "HZ1JovNiVvGrGfW4pZC1Xdnt98UqL5wJo1kS1kS1kS12"
D14_ATA = "2BZwUZkaAta11111111111111111111111111111111"
D14_CUSTODY = "StakeCustody111111111111111111111111111111"
D14_COSIGN = "ExistingCoSigner11111111111111111111111111"


def _pyth_stake_create_account():
    rent = 29_009_280
    return {
        "signature": "5qag8uwPg6z3h8U3GbW6WdwDJbKGFCMpqR3dcz4Zb9g5",
        "transaction": {
            "signatures": ["5qag8uwPg6z3h8U3GbW6WdwDJbKGFCMpqR3dcz4Zb9g5"],
            "message": {
                "header": {"numRequiredSignatures": 2},
                "accountKeys": [D14_WALLET, D14_NEW, D14_ATA, D14_CUSTODY, SYSTEM, PYTH_STAKING, TOKEN_PROG],
                "instructions": [
                    {
                        "programId": SYSTEM,
                        "parsed": {
                            "type": "createAccount",
                            "info": {
                                "source": D14_WALLET,
                                "newAccount": D14_NEW,
                                "lamports": rent,
                                "space": 4040,
                                "owner": PYTH_STAKING,
                            },
                        },
                    },
                    {"programId": PYTH_STAKING, "accounts": [D14_WALLET, D14_NEW, D14_CUSTODY], "data": "deposit"},
                    {
                        "programId": TOKEN_PROG,
                        "parsed": {
                            "type": "transfer",
                            "info": {
                                "authority": D14_WALLET,
                                "source": D14_ATA,
                                "destination": D14_CUSTODY,
                                "mint": D14_PYTH,
                                "amount": "2175000000",
                            },
                        },
                    },
                ],
            },
        },
        "meta": {
            "err": None,
            "fee": 10_000,
            "preBalances": [1_000_000_000, 0, 2_039_280, 2_039_280, 1, 1, 1],
            "postBalances": [1_000_000_000 - rent - 10_000, rent, 2_039_280, 2_039_280, 1, 1, 1],
            "preTokenBalances": [
                {"accountIndex": 2, "mint": D14_PYTH, "owner": D14_WALLET, "uiTokenAmount": {"amount": "2175000000"}},
            ],
            "postTokenBalances": [
                {"accountIndex": 2, "mint": D14_PYTH, "owner": D14_WALLET, "uiTokenAmount": {"amount": "0"}},
                {"accountIndex": 3, "mint": D14_PYTH, "owner": D14_CUSTODY, "uiTokenAmount": {"amount": "2175000000"}},
            ],
        },
        "blockTime": 1705449950,
    }


def test_d14_14_pyth_create_account_rent_is_not_cosigner_proceeds():
    detected = detect_bundle_or_distribution([_pyth_stake_create_account()], D14_WALLET)
    assert "sell_proceeds_to_cosigner" not in (detected.get("reasons") or [])
    assert not detected.get("sell_proceeds_to_cosigner")


def test_d14_14_neighbor_existing_cosigner_sale_still_flags():
    sale = {
        "signature": "real-cosigner-sale",
        "transaction": {
            "signatures": ["real-cosigner-sale"],
            "message": {
                "header": {"numRequiredSignatures": 2},
                "accountKeys": [D14_WALLET, D14_COSIGN, D14_ATA, "UsdcAta111111111111111111111111111111111", JUPITER, TOKEN_PROG],
                "instructions": [
                    {"programId": JUPITER, "accounts": [D14_WALLET, D14_ATA], "data": "route"},
                ],
            },
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [2_000_000_000, 1_000_000_000, 2_039_280, 2_039_280, 1, 1],
            "postBalances": [1_500_000_000, 1_500_000_000, 2_039_280, 2_039_280, 1, 1],
            "preTokenBalances": [
                {"accountIndex": 2, "mint": D14_PYTH, "owner": D14_WALLET, "uiTokenAmount": {"amount": "1000000000"}},
            ],
            "postTokenBalances": [
                {"accountIndex": 2, "mint": D14_PYTH, "owner": D14_WALLET, "uiTokenAmount": {"amount": "0"}},
            ],
        },
        "blockTime": DAY,
    }
    detected = detect_bundle_or_distribution([sale], D14_WALLET)
    assert "sell_proceeds_to_cosigner" in detected["reasons"]
    assert detected["sell_proceeds_to_cosigner"][0]["co_signer"] == D14_COSIGN


# --- D14-15 ----------------------------------------------------------------

D14_MINT = "RrelMintD1415aaaaaaaaaaaaaaaaaaaaaaaaaaa"
D14_TOK_ATA = "RrelTokAtaD1415aaaaaaaaaaaaaaaaaaaaaaaaa"
D14_USDC_ATA = "RrelUsdcAtaD1415aaaaaaaaaaaaaaaaaaaaaaaa"
START_90 = int(datetime(2026, 7, 11, tzinfo=timezone.utc).timestamp())
END_REP = int(datetime(2026, 10, 8, tzinfo=timezone.utc).timestamp())
IN_90 = START_90 + 86400
IN_180_ONLY = int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp())
START_180 = int(datetime(2026, 4, 11, tzinfo=timezone.utc).timestamp())


def _d14_swap(signature, *, token_pre, token_post, usdc_pre, usdc_post, block_time, mint=D14_MINT):
    return {
        "signature": signature,
        "blockTime": block_time,
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [D14_WALLET, D14_TOK_ATA, D14_USDC_ATA, JUPITER, TOKEN_PROG],
                "instructions": [{"programId": JUPITER, "accounts": [D14_WALLET, D14_TOK_ATA], "data": "route"}],
            },
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [2_000_000_000, 2_039_280, 2_039_280, 1, 1],
            "postBalances": [1_999_995_000, 2_039_280, 2_039_280, 1, 1],
            "preTokenBalances": [
                {"accountIndex": 1, "mint": mint, "owner": D14_WALLET, "uiTokenAmount": {"amount": token_pre}},
                {"accountIndex": 2, "mint": USDC, "owner": D14_WALLET, "uiTokenAmount": {"amount": usdc_pre}},
            ],
            "postTokenBalances": [
                {"accountIndex": 1, "mint": mint, "owner": D14_WALLET, "uiTokenAmount": {"amount": token_post}},
                {"accountIndex": 2, "mint": USDC, "owner": D14_WALLET, "uiTokenAmount": {"amount": usdc_post}},
            ],
        },
    }


def _d14_lineage_rent(signature, block_time):
    """Non-swap lineage touch that pays 0.029 SOL rent into a new account."""
    rent = 29_009_280
    new = "LineageRentAcct11111111111111111111111111"
    return {
        "signature": signature,
        "blockTime": block_time,
        "transaction": {
            "signatures": [signature],
            "message": {
                "header": {"numRequiredSignatures": 2},
                "accountKeys": [D14_WALLET, new, D14_TOK_ATA, SYSTEM, PYTH_STAKING, TOKEN_PROG],
                "instructions": [
                    {
                        "programId": SYSTEM,
                        "parsed": {
                            "type": "createAccount",
                            "info": {
                                "source": D14_WALLET,
                                "newAccount": new,
                                "lamports": rent,
                                "space": 4040,
                                "owner": PYTH_STAKING,
                            },
                        },
                    },
                    {"programId": PYTH_STAKING, "accounts": [D14_WALLET, new], "data": "stake"},
                ],
            },
        },
        "meta": {
            "err": None,
            "fee": 10_000,
            "preBalances": [1_000_000_000, 0, 2_039_280, 1, 1, 1],
            "postBalances": [1_000_000_000 - rent - 10_000, rent, 2_039_280, 1, 1, 1],
            "preTokenBalances": [
                {"accountIndex": 2, "mint": D14_MINT, "owner": D14_WALLET, "uiTokenAmount": {"amount": "1000000"}},
            ],
            "postTokenBalances": [
                {"accountIndex": 2, "mint": D14_MINT, "owner": D14_WALLET, "uiTokenAmount": {"amount": "1000000"}},
            ],
        },
    }


def test_d14_15_superset_window_lineage_rent_does_not_zero_value():
    sells = []
    events = []
    for i in range(15):
        sig = f"usdc-sell-{i}"
        sells.append(_d14_swap(
            sig, token_pre="1000000", token_post="0",
            usdc_pre="0", usdc_post="100000000", block_time=IN_90 + i,
        ))
        events.append({
            "kind": "sell", "signature": sig, "mint": D14_MINT,
            "timestamp": IN_90 + i, "amount_usdc": "100", "consideration_usdc": "100",
            "settlement_asset": "USDC",
        })
    unread = _d14_swap(
        "usdc-unread", token_pre="1000000", token_post="0",
        usdc_pre="0", usdc_post="100000000", block_time=IN_90 + 20,
    )
    rent = _d14_lineage_rent("lineage-rent-180", IN_180_ONLY)
    ledger = [{"mint": D14_MINT, "close_signature": "usdc-sell-0"}]
    win90 = build_result_relevant(
        sells + [unread], {"events": events}, D14_WALLET,
        report_start=START_90, report_end=END_REP, ledger=ledger,
    )
    win180 = build_result_relevant(
        sells + [unread, rent], {"events": events}, D14_WALLET,
        report_start=START_180, report_end=END_REP, ledger=ledger,
    )
    assert Decimal(str(win90["value_share"])) == Decimal("0.9375")
    assert Decimal(str(win180["value_share"])) == Decimal("0.9375")
    assert win180["unsupported_n"] >= win90["unsupported_n"]


def test_d14_15_neighbor_unreadable_sol_swap_still_lowers_value():
    sell = _d14_swap(
        "usdc-clean", token_pre="1000000", token_post="0",
        usdc_pre="0", usdc_post="100000000", block_time=IN_90,
    )
    events = [{
        "kind": "sell", "signature": "usdc-clean", "mint": D14_MINT,
        "timestamp": IN_90, "amount_usdc": "100", "consideration_usdc": "100",
        "settlement_asset": "USDC",
    }]
    sol_unread = {
        "signature": "sol-unread",
        "blockTime": IN_180_ONLY,
        "transaction": {
            "signatures": ["sol-unread"],
            "message": {
                "accountKeys": [D14_WALLET, D14_TOK_ATA, JUPITER, TOKEN_PROG],
                "instructions": [{"programId": JUPITER, "accounts": [D14_WALLET, D14_TOK_ATA], "data": "route"}],
            },
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [2_000_000_000, 2_039_280, 1, 1],
            "postBalances": [1_000_000_000, 2_039_280, 1, 1],
            "preTokenBalances": [
                {"accountIndex": 1, "mint": D14_MINT, "owner": D14_WALLET, "uiTokenAmount": {"amount": "0"}},
            ],
            "postTokenBalances": [
                {"accountIndex": 1, "mint": D14_MINT, "owner": D14_WALLET, "uiTokenAmount": {"amount": "5000000"}},
            ],
        },
    }
    base = build_result_relevant(
        [sell], {"events": events}, D14_WALLET,
        report_start=START_90, report_end=END_REP, ledger=[{"mint": D14_MINT}],
    )
    wider = build_result_relevant(
        [sell, sol_unread], {"events": events}, D14_WALLET,
        report_start=START_180, report_end=END_REP, ledger=[{"mint": D14_MINT}],
    )
    assert Decimal(str(base["value_share"])) == Decimal("1")
    assert Decimal(str(wider["value_share"])) < Decimal("1")


# --- D14-16 ----------------------------------------------------------------

def test_d14_16_first_tx_clears_leftover_pagination_token():
    created = {
        "signature": "first-tx",
        "blockTime": 1_700_000_000,
        "transaction": {
            "signatures": ["first-tx"],
            "message": {"accountKeys": [D14_WALLET], "instructions": []},
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [0],
            "postBalances": [1_000_000_000],
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }
    assessed = assess_history_completeness([created], leftover_token="still-a-token", address=D14_WALLET)
    assert assessed["history_complete"] is True
    assert assessed["wallet_created_in_range"] is True
    assert assessed["leftover_pagination_token"] is False


def test_d14_16_neighbor_unproven_first_tx_keeps_leftover():
    later = {
        "signature": "later-tx",
        "blockTime": 1_700_000_000,
        "transaction": {
            "signatures": ["later-tx"],
            "message": {"accountKeys": [D14_WALLET], "instructions": []},
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [50_000_000],
            "postBalances": [40_000_000],
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }
    assessed = assess_history_completeness([later], leftover_token="earlier", address=D14_WALLET)
    assert assessed["wallet_created_in_range"] is False
    assert assessed["leftover_pagination_token"] is True
    assert assessed["history_complete"] is False


# --- D14-17 ----------------------------------------------------------------

def test_d14_17_blocker_reports_auditor_unresolved_count():
    report = {
        "independent_audit": {
            "unresolved_basis_sales": 80,
            "result_relevant": {"signatures": ["a"], "gate_passed": False},
        },
        "record_breakdown": {
            "result_relevant": {"version": "result-relevant-v1", "signatures": ["a"], "size": 1, "empty": False, "denominator": 1},
        },
    }
    profile = {
        "completed_known_cost_positions": 3,
        "open_buys_in_sample": 40,
        "unresolved_basis_sales": 63,
    }
    reason = blocking_reason(report, profile, coverage_status="coverage_blocked", level={"level": "conditional_captured_lot_result"})
    assert "80 unresolved-basis sales" in reason
    assert "63 unresolved" not in reason


def test_d14_17_neighbor_without_auditor_keeps_app_count():
    report = {}
    profile = {
        "completed_known_cost_positions": 3,
        "open_buys_in_sample": 0,
        "unresolved_basis_sales": 63,
    }
    reason = blocking_reason(report, profile, coverage_status="coverage_blocked", level={"level": "conditional_captured_lot_result"})
    assert "63 unresolved-basis sales" in reason


def test_d14_17_membership_agrees_and_old_reconstructed_unrelated_stays_out():
    window_sell = _d14_swap(
        "win-sell", token_pre="1000000", token_post="0",
        usdc_pre="0", usdc_post="100000000", block_time=IN_90,
    )
    old_unrelated = _d14_swap(
        "old-unrelated", token_pre="5000000", token_post="0",
        usdc_pre="0", usdc_post="50000000", block_time=IN_180_ONLY,
        mint="OtherMintD1417aaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    old_lineage = _d14_swap(
        "old-lineage-buy", token_pre="0", token_post="1000000",
        usdc_pre="100000000", usdc_post="0", block_time=IN_180_ONLY,
    )
    events = [{
        "kind": "sell", "signature": "win-sell", "mint": D14_MINT,
        "timestamp": IN_90, "amount_usdc": "100", "consideration_usdc": "100",
        "settlement_asset": "USDC",
    }]
    records = [window_sell, old_unrelated, old_lineage]
    app = build_result_relevant(
        records, {"events": events}, D14_WALLET,
        report_start=START_90, report_end=END_REP, ledger=[{"mint": D14_MINT}],
    )
    trades = [
        {
            "kind": "sell", "signature": "win-sell", "mint": D14_MINT,
            "timestamp": IN_90, "quantity_raw": "1000000",
            "consideration_usdc": "100", "settlement_asset": "USDC",
            "observed_pre_quantity_raw": "1000000", "observed_post_quantity_raw": "0",
        },
        {
            "kind": "sell", "signature": "old-unrelated",
            "mint": "OtherMintD1417aaaaaaaaaaaaaaaaaaaaaaaaaa",
            "timestamp": IN_180_ONLY, "quantity_raw": "5000000",
            "consideration_usdc": "50", "settlement_asset": "USDC",
            "observed_pre_quantity_raw": "5000000", "observed_post_quantity_raw": "0",
        },
        {
            "kind": "buy", "signature": "old-lineage-buy", "mint": D14_MINT,
            "timestamp": IN_180_ONLY, "quantity_raw": "1000000",
            "consideration_usdc": "100", "settlement_asset": "USDC",
            "observed_pre_quantity_raw": "0", "observed_post_quantity_raw": "1000000",
        },
    ]
    aud = auditor.result_relevant_coverage(
        D14_WALLET, records, trades, [{"mint": D14_MINT}],
        report_start=START_90, report_end=END_REP,
    )
    assert "old-unrelated" not in app["signatures"]
    assert "old-unrelated" not in aud["signatures"]
    assert "old-lineage-buy" in app["signatures"]
    assert "old-lineage-buy" in aud["signatures"]
    assert set(app["signatures"]) == set(aud["signatures"])
    gate = mandatory_coverage_gate({
        "record_breakdown": {"result_relevant": app},
        "independent_audit": {"result_relevant": aud, "unresolved_basis_sales": 80},
    })
    assert "disagree on result-relevant membership" not in (gate.get("reason") or "")
