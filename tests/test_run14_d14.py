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
    _nansen_body_digest,
    _nansen_call_stem,
    _nansen_seed_call,
    _nansen_timeout_was_billed,
    _persist_nansen_paid,
    _phase1_nansen,
    _phase1_nansen_token_pnl,
    _rid,
    DEFAULT_ECONOMIC_PROBE_DAYS,
    _dispatch_helius,
    assess_history_completeness,
    bind_run_spend,
    empty_phase_spend,
    empty_spend,
    gta_options,
    load_grant,
    nansen_tgm_pnl_leaderboard_body,
    nansen_vendor_drop_decision,
    parse_run_caps,
    phase2_prescreen,
    rank_over_days_for_probe,
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
    apply_blocked_headline_pnl,
    apply_headline_losing_pnl,
    evaluate_thresholds,
)
from scanner.mass_search.verified_costs import PUBLISHED_TIP_ACCOUNTS
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


def test_d14_new7_blocked_headline_fails_every_pnl_filter():
    profile = {
        "completed_known_cost_positions": 2,
        "scoped_pnl": "10",
        "scoped_pnl_unit": "SOL",
        "scoped_pnl_by_quote_asset": {"SOL": "10", "USDC": "376"},
        "completed_episode_net": "10",
        "completed_episode_net_unit": "SOL",
    }
    apply_blocked_headline_pnl(profile, {})
    assert profile["scoped_pnl"] is None
    assert profile["scoped_pnl_by_quote_asset"] == {}
    assert profile["headline_pnl_blocked"] is True
    sol = evaluate_thresholds(profile, {"min_scoped_pnl_sol": "5"})["results"]["min_scoped_pnl_sol"]
    usdc = evaluate_thresholds(profile, {"min_scoped_pnl_usdc": "5"})["results"]["min_scoped_pnl_usdc"]
    assert sol["state"] == "FAIL" and sol["passed"] is False
    assert usdc["state"] == "FAIL" and usdc["passed"] is False


def test_d14_new7_neighbor_overstated_map_and_negative_threshold_still_fail():
    profile = {
        "completed_known_cost_positions": 3,
        "scoped_pnl": None,
        "scoped_pnl_unit": None,
        "scoped_pnl_by_quote_asset": {"SOL": "10"},
        "headline_pnl_blocked": True,
    }
    sol = evaluate_thresholds(profile, {"min_scoped_pnl_sol": "5"})["results"]["min_scoped_pnl_sol"]
    assert sol["state"] == "FAIL" and sol["passed"] is False
    neg = evaluate_thresholds(profile, {"min_scoped_pnl_sol": "-100"})["results"]["min_scoped_pnl_sol"]
    assert neg["state"] == "FAIL" and neg["passed"] is False
    report = {"scoped_pnl_by_quote_asset": {"USDC": "50"}}
    apply_blocked_headline_pnl(profile, report)
    assert report["scoped_pnl_by_quote_asset"] == {}
    clean = {
        "completed_known_cost_positions": 2,
        "scoped_pnl": "10",
        "scoped_pnl_unit": "SOL",
        "scoped_pnl_by_quote_asset": {"SOL": "10"},
        "headline_pnl_blocked": False,
    }
    ok = evaluate_thresholds(clean, {"min_scoped_pnl_sol": "5"})["results"]["min_scoped_pnl_sol"]
    assert ok["state"] == "PASS" and ok["passed"] is True


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
        body=body,
    )
    assert saved and saved.get("body")
    assert saved.get("replayed_from_receipt") is False
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


def test_d14_6_live_refuses_unreceipted_planted_file(tmp_path):
    config = _dry_config(tmp_path)
    config["dry_run"] = False
    config["nansen_enabled"] = False
    grant = {"enabled": False, "reason": "grant disabled"}
    store, _ = open_grant_store(config["authorization_id"])
    state = _empty_state(config)
    body = nansen_tgm_pnl_leaderboard_body(
        token_address="Tok11111111111111111111111111111111111111",
        date_from="2026-07-01", date_to="2026-10-01", page=1, per_page=1000,
    )
    stem = _nansen_call_stem("tgm_pnl_leaderboard", "_tgm_Tok11111", 1, "ident", body=body)
    paid = Path(config["output_dir"]) / "raw/phase1/nansen-paid"
    paid.mkdir(parents=True, exist_ok=True)
    (paid / f"{stem}.bin").write_bytes(
        json.dumps({"data": [{"trader_address": "PLANTED", "pnl_usd_realised": 1e6}]}).encode()
    )
    calls = []

    async def boom(*_a, **_k):
        calls.append(True)
        raise AssertionError("live call")

    import scanner.mass_search.live_e2e as live_mod
    live_mod._live_nansen = boom
    with pytest.raises(SourceError, match="UNAUTHORIZED|grant disabled|NANSEN_API_KEY"):
        asyncio.run(_nansen_seed_call(
            store, grant, config, state, None,
            path=NANSEN_TGM_PNL_LEADERBOARD_PATH, body=body,
            operation="tgm_pnl_leaderboard", units=5,
            wallet="_tgm_Tok11111", page=1, identity="ident",
        ))
    assert calls == []
    store.close()


def test_d14_6_neighbor_different_dates_do_not_share_stem_and_dry_run_file_stays_offline(tmp_path):
    config = _dry_config(tmp_path)
    body_a = nansen_leaderboard_body(timeframe=90, page=1, per_page=50)
    body_b = dict(body_a)
    body_b["date"] = {"from": "2025-01-01", "to": "2025-02-01"}
    stem_a = _nansen_call_stem("smart_money_pnl_leaderboard", "_lb", 0, "d14-6", body=body_a)
    stem_b = _nansen_call_stem("smart_money_pnl_leaderboard", "_lb", 0, "d14-6", body=body_b)
    assert stem_a != stem_b
    dry = _dry_config(tmp_path / "dry")
    grant = load_grant(DRAFT)
    store, _ = open_grant_store(dry["authorization_id"])
    state = _empty_state(dry)
    bind_run_spend(dry, state)

    class Rec:
        async def nansen(self, method, path, body=None):
            return {
                "status": 200,
                "body": {"data": [{"address": JXT}]},
                "raw_bytes": b'{"data":[{"address":"dry"}]}',
                "fetched_at": "2026-10-08T00:00:00Z",
                "billing": {"credits_cost": 5},
            }

    asyncio.run(_nansen_seed_call(
        store, grant, dry, state, Rec(),
        path=NANSEN_LEADERBOARD_PATH, body=body_a,
        operation="smart_money_pnl_leaderboard", units=5,
        wallet="_lb", page=0, identity="d14-6",
    ))
    live = dict(dry)
    live["dry_run"] = False
    live["nansen_enabled"] = False
    with pytest.raises(SourceError, match="UNAUTHORIZED|NANSEN_API_KEY"):
        asyncio.run(_nansen_seed_call(
            store, {"enabled": False, "reason": "grant disabled"}, live, state, None,
            path=NANSEN_LEADERBOARD_PATH, body=body_a,
            operation="smart_money_pnl_leaderboard", units=5,
            wallet="_lb", page=0, identity="d14-6",
        ))
    store.close()


def test_d14_6_neighbor_matching_consumed_receipt_replays_in_live(tmp_path):
    config = _dry_config(tmp_path)
    config["dry_run"] = False
    config["nansen_enabled"] = False
    grant = load_grant(DRAFT)
    store, _ = open_grant_store(config["authorization_id"])
    state = _empty_state(config)
    body = nansen_leaderboard_body(timeframe=90, page=1, per_page=50)
    raw = b'{"data":[{"address":"paid-live"}]}'
    _persist_nansen_paid(
        config, state, operation="smart_money_pnl_leaderboard", wallet="_lb",
        page=0, identity="d14-6",
        response={"raw_bytes": raw, "status": 200, "fetched_at": "2026-10-08T00:00:00Z", "billing": {}},
        parsed_rows=[{"address": "paid-live"}],
        body=body, path=NANSEN_LEADERBOARD_PATH,
    )
    sidecar_path = Path(config["output_dir"]) / "raw/phase1/nansen-paid"
    stem = _nansen_call_stem("smart_money_pnl_leaderboard", "_lb", 0, "d14-6", body=body)
    sidecar = json.loads((sidecar_path / f"{stem}.rows.json").read_text())
    sidecar["dry_run"] = False
    (sidecar_path / f"{stem}.rows.json").write_text(json.dumps(sidecar))
    digest = sidecar["sha256"]
    token_key = _rid(
        config, "nansen", wallet="_lb", phase=1, page=0,
        cursor=f"d14-6:{NANSEN_LEADERBOARD_PATH}:_lb:{_nansen_body_digest(body)}",
    )
    put_receipt(store, grant, token_key, {
        "provider": "nansen", "wallet": "_lb", "phase": 1, "page": 0,
        "units": 5, "state": "consumed",
        "operation": "smart_money_pnl_leaderboard",
        "body_sha256": _nansen_body_digest(body),
        "sha256": digest, "path": NANSEN_LEADERBOARD_PATH,
    })
    replayed = asyncio.run(_nansen_seed_call(
        store, {"enabled": False, "reason": "grant disabled"}, config, state, None,
        path=NANSEN_LEADERBOARD_PATH, body=body,
        operation="smart_money_pnl_leaderboard", units=5,
        wallet="_lb", page=0, identity="d14-6",
    ))
    assert replayed.get("replayed_from_receipt") is True
    assert replayed["body"]["data"][0]["address"] == "paid-live"
    store.close()


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
    assert screen["cannot_fail_bot_rule"] is False
    decision = bot_prescreen_decision(cap_rows, history_cap=40)
    assert decision["decision"] != DROP
    assert decision["screen"]["cannot_fail_bot_rule"] is False
    early = bot_prescreen_decision(
        cap_rows, history_cap=40,
        economic_drop={"dropped": True, "max": 18, "day": "2026-09-20"},
    )
    assert early["decision"] == DROP
    missing = helius_signatures_prescreen([{"signature": "x"}])
    assert missing["cannot_fail_bot_rule"] is False
    assert missing["incomplete_timestamps"] == 1


def test_d14_12_history_above_cap_is_not_bot_clean():
    d0 = DAY - (DAY % 86400)
    rows = []
    for day in range(1000):
        for i in range(10):
            rows.append({"signature": f"s{day}_{i}", "blockTime": d0 - day * 86400 + i * 60})
    screen = helius_signatures_prescreen(rows, history_cap=10000)
    assert screen["deferred"] is True
    assert screen["cannot_fail_bot_rule"] is False
    decision = bot_prescreen_decision(rows, history_cap=10000)
    assert decision["reason"] == "history_above_cap"
    assert decision["screen"]["cannot_fail_bot_rule"] is False
    ranked = rank_by_nansen_pnl([
        {"address": "capped", "cannot_fail_bot_rule": screen["cannot_fail_bot_rule"], "nansen_realized_pnl_usd": "1"},
        {"address": "pnl_big", "vendor_metrics": {"realized_pnl_usd": "1000000"}},
    ])
    assert [row["address"] for row in ranked] == ["pnl_big", "capped"]


def test_d14_12_neighbor_exact_cap_and_quiet_history_still_cannot_fail():
    d0 = DAY - (DAY % 86400)
    exact = []
    for day in range(667):
        for i in range(15):
            exact.append({"signature": f"e{day}_{i}", "blockTime": d0 - day * 86400 + i * 60})
    screen = helius_signatures_prescreen(exact, history_cap=10000)
    assert screen["deferred"] is True
    assert screen["cannot_fail_bot_rule"] is False
    quiet = [{"signature": f"q{i}", "blockTime": DAY + i} for i in range(10)]
    quiet_screen = helius_signatures_prescreen(quiet)
    assert quiet_screen["deferred"] is False
    assert quiet_screen["cannot_fail_bot_rule"] is True
    ranked = rank_by_nansen_pnl([
        {"address": "deferred", "cannot_fail_bot_rule": False, "nansen_realized_pnl_usd": "9"},
        {"address": "quiet", "cannot_fail_bot_rule": True, "nansen_realized_pnl_usd": "1"},
    ])
    assert [row["address"] for row in ranked] == ["quiet", "deferred"]


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


def _d14_existing_cosigner_sale():
    return {
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


def test_d14_14_neighbor_existing_cosigner_sale_still_flags():
    sale = _d14_existing_cosigner_sale()
    detected = detect_bundle_or_distribution([sale], D14_WALLET)
    assert "sell_proceeds_to_cosigner" in detected["reasons"]
    assert detected["sell_proceeds_to_cosigner"][0]["co_signer"] == D14_COSIGN


def _d14_14_flag(record):
    return "sell_proceeds_to_cosigner" in (detect_bundle_or_distribution([record], D14_WALLET).get("reasons") or [])


def test_d14_14_fresh_cosigner_pre_zero_still_flags():
    sale = _d14_existing_cosigner_sale()
    fresh = json.loads(json.dumps(sale))
    fresh["meta"]["preBalances"][1] = 0
    fresh["meta"]["postBalances"][1] = 500_000_000
    assert _d14_14_flag(fresh) is True


def test_d14_14_neighbor_system_create_account_and_seed_still_flag():
    sale = _d14_existing_cosigner_sale()
    funded = json.loads(json.dumps(sale))
    funded["meta"]["preBalances"][1] = 0
    funded["meta"]["postBalances"][1] = 500_000_000
    funded["transaction"]["message"]["accountKeys"].append(SYSTEM)
    funded["meta"]["preBalances"].append(1)
    funded["meta"]["postBalances"].append(1)
    funded["transaction"]["message"]["instructions"].append({
        "programId": SYSTEM,
        "parsed": {
            "type": "createAccount",
            "info": {
                "source": D14_WALLET, "newAccount": D14_COSIGN,
                "lamports": 500_000_000, "space": 0, "owner": SYSTEM,
            },
        },
    })
    assert _d14_14_flag(funded) is True
    seeded = json.loads(json.dumps(funded))
    seeded["transaction"]["message"]["instructions"][-1]["parsed"]["type"] = "createAccountWithSeed"
    assert _d14_14_flag(seeded) is True


def test_d14_14_neighbor_pyth_extra_and_system_owned_rent_plus_sol_flag():
    extra = 1_000_000_000
    p1 = _pyth_stake_create_account()
    p1["transaction"]["message"]["instructions"][0]["parsed"]["info"]["lamports"] += extra
    p1["meta"]["postBalances"][0] -= extra
    p1["meta"]["postBalances"][1] += extra
    assert _d14_14_flag(p1) is True
    p2 = _pyth_stake_create_account()
    p2["transaction"]["message"]["instructions"][0]["parsed"]["info"]["owner"] = SYSTEM
    p2["transaction"]["message"]["instructions"][0]["parsed"]["info"]["lamports"] += extra
    p2["meta"]["postBalances"][0] -= extra
    p2["meta"]["postBalances"][1] += extra
    assert _d14_14_flag(p2) is True


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


def _d14_otc(sig, block_time, mint, ata, sol_out, usdc_delta=None, parsed_system=False, tip_dest=None):
    rec = _d14_swap(
        sig, token_pre="0", token_post="1000000",
        usdc_pre="0", usdc_post="0", block_time=block_time, mint=mint,
    )
    rec["transaction"]["message"]["accountKeys"][1] = ata
    if parsed_system or tip_dest:
        dest = tip_dest or "OtcCounterparty11111111111111111111111111"
        rec["transaction"]["message"]["accountKeys"].append(dest)
        rec["meta"]["preBalances"].append(1)
        rec["meta"]["postBalances"].append(1 + sol_out)
        rec["transaction"]["message"]["instructions"] = [{
            "programId": SYSTEM,
            "parsed": {"type": "transfer", "info": {"source": D14_WALLET, "destination": dest, "lamports": sol_out}},
        }, {"programId": TOKEN_PROG, "accounts": [D14_WALLET], "data": "y"}]
    else:
        rec["transaction"]["message"]["instructions"] = [
            {"programId": SYSTEM, "accounts": [D14_WALLET], "data": "x"},
            {"programId": TOKEN_PROG, "accounts": [D14_WALLET], "data": "y"},
        ]
    fee = rec["meta"]["fee"] if isinstance(rec["meta"].get("fee"), int) else 0
    rec["meta"]["preBalances"][0] = 20_000_000_000
    rec["meta"]["postBalances"][0] = 20_000_000_000 - sol_out - fee
    if usdc_delta is not None:
        rec["meta"]["preTokenBalances"].append(
            {"accountIndex": 2, "mint": USDC, "owner": D14_WALLET, "uiTokenAmount": {"amount": "100000000000"}}
        )
        rec["meta"]["postTokenBalances"].append(
            {"accountIndex": 2, "mint": USDC, "owner": D14_WALLET, "uiTokenAmount": {"amount": str(100000000000 - usdc_delta)}}
        )
    return rec


def _d14_usdc_book(n=150):
    sells, events, trades = [], [], []
    for i in range(n):
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
        trades.append({
            "kind": "sell", "signature": sig, "mint": D14_MINT,
            "timestamp": IN_90 + i, "quantity_raw": "1000000",
            "consideration_usdc": "100", "settlement_asset": "USDC",
            "observed_pre_quantity_raw": "1000000", "observed_post_quantity_raw": "0",
        })
    return sells, events, trades


def _d14_15_run(extra, extras_time=None):
    sells, events, trades = _d14_usdc_book(150)
    records = sells + extra
    app = build_result_relevant(
        records, {"events": events}, D14_WALLET,
        report_start=START_90, report_end=END_REP, ledger=[{"mint": D14_MINT, "close_signature": "usdc-sell-0"}],
    )
    aud = auditor.result_relevant_coverage(
        D14_WALLET, records, trades, [{"mint": D14_MINT}],
        report_start=START_90, report_end=END_REP,
    )
    return app, aud


def test_d14_15_otc_sol_buy_is_unreadable_value_and_blocks():
    other = "OtherMintD1415bbbbbbbbbbbbbbbbbbbbbbbbbbb"
    other_ata = "OtherAtaD1415bbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    cases = [
        ("inwindow_lineage_10sol", _d14_otc("v1", IN_90 + 900, D14_MINT, D14_TOK_ATA, 10_000_000_000)),
        ("outwindow_lineage_10sol", _d14_otc("v2", IN_180_ONLY, D14_MINT, D14_TOK_ATA, 10_000_000_000)),
        ("inwindow_other_10sol", _d14_otc("v3", IN_90 + 901, other, other_ata, 10_000_000_000)),
        ("inwindow_other_0p5sol", _d14_otc("v8", IN_90 + 906, other, other_ata, 500_000_000)),
        ("parsed_system_10sol", _d14_otc("v9", IN_90 + 907, other, other_ata, 10_000_000_000, parsed_system=True)),
    ]
    for name, rec in cases:
        app, aud = _d14_15_run([rec])
        assert Decimal(str(app["count_share"])) >= Decimal("0.99"), name
        assert Decimal(str(app["value_share"])) < Decimal("0.99"), name
        assert app["gate_passed"] is False, name
        assert Decimal(str(aud["value_share"])) < Decimal("0.99"), name
        assert aud["gate_passed"] is False, name
        assert Decimal(str(aud["value_share"])) <= Decimal(str(app["value_share"])), name


def test_d14_15_neighbor_usdc_otc_and_verified_tip_and_exact_rent():
    other = "OtherMintD1415ccccccccccccccccccccccccccc"
    other_ata = "OtherAtaD1415cccccccccccccccccccccccccccc"
    usdc_app, usdc_aud = _d14_15_run([
        _d14_otc("v6", IN_90 + 904, other, other_ata, 0, usdc_delta=1_500_000_000),
    ])
    assert usdc_app["gate_passed"] is False
    assert Decimal(str(usdc_app["value_share"])) < Decimal("0.99")
    assert usdc_aud["gate_passed"] is False
    tip = next(iter(PUBLISHED_TIP_ACCOUNTS))
    tip_app, tip_aud = _d14_15_run([
        _d14_otc("vtip", IN_90 + 908, other, other_ata, 10_000_000, tip_dest=tip),
    ])
    assert Decimal(str(tip_app["value_share"])) == Decimal("1")
    sells, events, _trades = _d14_usdc_book(15)
    unread = _d14_swap(
        "usdc-unread", token_pre="1000000", token_post="0",
        usdc_pre="0", usdc_post="100000000", block_time=IN_90 + 20,
    )
    rent = _d14_lineage_rent("lineage-rent-180", IN_180_ONLY)
    win180 = build_result_relevant(
        sells + [unread, rent], {"events": events}, D14_WALLET,
        report_start=START_180, report_end=END_REP, ledger=[{"mint": D14_MINT}],
    )
    assert Decimal(str(win180["value_share"])) == Decimal("0.9375")


# --- D14-16 ----------------------------------------------------------------

def _d14_16_page(pre):
    return {
        "signature": "hist-tx",
        "blockTime": 1_700_000_000,
        "transaction": {
            "signatures": ["hist-tx"],
            "message": {"accountKeys": [D14_WALLET], "instructions": []},
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [pre],
            "postBalances": [1_000_000_000],
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }


def test_d14_16_page_cap_plus_leftover_never_completes():
    created = _d14_16_page(0)
    assessed = assess_history_completeness(
        [created], leftover_token="more-pages-remain", address=D14_WALLET, page_cap_hit=True,
    )
    assert assessed["wallet_created_in_range"] is True
    assert assessed["leftover_pagination_token"] is True
    assert assessed["history_complete"] is False
    assert assessed["history_complete_reason"] == "page_cap_with_leftover_token"


def test_d14_16_neighbor_zero_prebalance_never_clears_leftover():
    created = _d14_16_page(0)
    leftover = assess_history_completeness([created], leftover_token="still-a-token", address=D14_WALLET)
    assert leftover["wallet_created_in_range"] is True
    assert leftover["leftover_pagination_token"] is True
    assert leftover["history_complete"] is False
    assert leftover["history_complete_reason"] == "pagination_token_remaining_earlier_history"
    later = _d14_16_page(50_000_000)
    kept = assess_history_completeness([later], leftover_token="earlier", address=D14_WALLET)
    assert kept["wallet_created_in_range"] is False
    assert kept["leftover_pagination_token"] is True
    assert kept["history_complete"] is False


def test_d14_16_neighbor_no_token_or_empty_next_page_can_complete():
    created = _d14_16_page(0)
    none = assess_history_completeness([created], leftover_token=None, address=D14_WALLET)
    assert none["leftover_pagination_token"] is False
    assert none["history_complete"] is True
    empty = assess_history_completeness([created], leftover_token="", address=D14_WALLET)
    assert empty["leftover_pagination_token"] is False
    assert empty["history_complete"] is True


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


# --- D15-1 ----------------------------------------------------------------

def _d15_econ_swap(wallet, sig, block_time):
    rec = _d14_swap(
        sig, token_pre="1000000", token_post="0",
        usdc_pre="0", usdc_post="100000000", block_time=block_time,
    )
    rec["transaction"]["message"]["accountKeys"][0] = wallet
    rec["transaction"]["message"]["header"] = {"numRequiredSignatures": 1}
    rec["meta"]["preTokenBalances"][0]["owner"] = wallet
    rec["meta"]["postTokenBalances"][0]["owner"] = wallet
    rec["meta"]["preTokenBalances"][1]["owner"] = wallet
    rec["meta"]["postTokenBalances"][1]["owner"] = wallet
    return rec


def test_d15_1_phase2_probe_drops_over_15_economic_and_keeps_15(tmp_path, monkeypatch):
    import scanner.mass_search.live_e2e as live
    drop = D14_WALLET
    keep = JXT
    busy_day = datetime(2026, 9, 20, tzinfo=timezone.utc)
    stamp = int(busy_day.timestamp())

    async def fake_sigs(store, grant, config, state, transport, address, *, before=None, phase=2, page_index=0):
        rows = [{"signature": f"{address[:6]}-raw-{i}", "blockTime": stamp + i} for i in range(20)]
        return {"records": rows, "units": 1, "pagination_token": None}

    async def fake_gta(store, grant, config, state, transport, address, options, *, phase, page_index):
        n = 16 if address == drop else 15
        recs = [_d15_econ_swap(address, f"{address[:6]}-econ-{i}", stamp + i) for i in range(n)]
        return {"records": recs, "units": 10, "pagination_token": None}

    monkeypatch.setattr(live, "_dispatch_signatures", fake_sigs)
    monkeypatch.setattr(live, "_dispatch_helius", fake_gta)
    config = _dry_config(
        tmp_path,
        seed_source="birdeye_top",
        phases="2",
        discovery=False,
        wallets=f"{drop},{keep}",
        helius_signatures_prescreen=True,
    )
    grant = load_grant(DRAFT)
    store, _ = open_grant_store(config["authorization_id"])
    state = _empty_state(config)
    bind_run_spend(config, state)
    state["wallets"] = [drop, keep]
    result = asyncio.run(phase2_prescreen(store, grant, config, state, RecorderTransport()))
    store.close()
    by_addr = {row["address"]: row for row in result["wallets"]}
    assert by_addr[drop]["dropped"] is True
    assert by_addr[drop]["drop_reason"] == GT_ECONOMIC_TRADES_RULE
    assert by_addr[keep]["dropped"] is False
    assert by_addr[keep].get("drop_reason") not in {GT_ECONOMIC_TRADES_RULE, "gt_15_economic_trades_in_one_day"}


def test_d15_1_canonical_decode_records_is_in_scope():
    import scanner.mass_search.live_e2e as live
    assert hasattr(live, "canonical_decode_records")
    assert callable(live.canonical_decode_records)


def test_d15_1_live_e2e_has_no_undefined_names():
    import ast
    import builtins

    path = ROOT / "scanner/mass_search/live_e2e.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module_defined = set(dir(builtins))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_defined.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            module_defined.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                module_defined.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    module_defined.add(alias.asname or alias.name)

    def _bind(target, dest):
        if isinstance(target, ast.Name):
            dest.add(target.id)
        elif isinstance(target, ast.Tuple):
            for elt in target.elts:
                _bind(elt, dest)
        elif isinstance(target, ast.List):
            for elt in target.elts:
                _bind(elt, dest)

    issues = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        local = {arg.arg for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs}
        if node.args.vararg:
            local.add(node.args.vararg.arg)
        if node.args.kwarg:
            local.add(node.args.kwarg.arg)
        for child in ast.walk(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child is not node:
                local.add(child.name)
            elif isinstance(child, ast.ClassDef):
                local.add(child.name)
            elif isinstance(child, ast.Import):
                for alias in child.names:
                    local.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(child, ast.ImportFrom):
                for alias in child.names:
                    if alias.name != "*":
                        local.add(alias.asname or alias.name)
            elif isinstance(child, ast.arg):
                local.add(child.arg)
            elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                local.add(child.id)
            elif isinstance(child, ast.ExceptHandler) and child.name:
                local.add(child.name)
            elif isinstance(child, ast.alias):
                local.add(child.asname or child.name.split(".")[0])
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                if child.id not in local and child.id not in module_defined:
                    issues.append(f"{node.name}: undefined name {child.id!r}")
    assert not issues, "undefined names in live_e2e.py:\n" + "\n".join(issues[:40])


# --- D15-3 ----------------------------------------------------------------

GGG = "GgG65z3M111111111111111111111111111111112"
D5Z = "D5ZhwMF611111111111111111111111111111112"


def _d15_sig_rows(prefix, stamp, n):
    return [{"signature": f"{prefix}-{i}", "blockTime": stamp + i} for i in range(n)]


def _gta_day(options):
    filters = (options or {}).get("filters") or {}
    block = filters.get("blockTime") if isinstance(filters.get("blockTime"), dict) else {}
    start = block.get("gte")
    if start in (None, ""):
        start = (options or {}).get("start_unix") or 0
    return datetime.fromtimestamp(int(start), tz=timezone.utc).date().isoformat()


def test_d15_3_rank_over_days_highest_raw_count_first():
    ranked = rank_over_days_for_probe({"2026-09-20": 16, "2025-09-14": 120, "2024-11-08": 44})
    assert [day for day, _count in ranked] == ["2025-09-14", "2024-11-08", "2026-09-20"]
    assert DEFAULT_ECONOMIC_PROBE_DAYS == 8


def test_d15_3_later_page_bot_day_is_probed_and_dropped(tmp_path, monkeypatch):
    """GgG65z3M/D5ZhwMF6 shape: newest page is an over-day, bot day is later."""
    import scanner.mass_search.live_e2e as live
    monkeypatch.setattr(live, "HELIUS_SIGNATURES_PAGE_SIZE", 16)
    newest = datetime(2026, 9, 20, tzinfo=timezone.utc)
    bot_day = datetime(2025, 9, 14, tzinfo=timezone.utc)
    newest_ts = int(newest.timestamp())
    bot_ts = int(bot_day.timestamp())
    gta_days = []

    async def fake_sigs(store, grant, config, state, transport, address, *, before=None, phase=2, page_index=0):
        if page_index == 0:
            rows = _d15_sig_rows("new", newest_ts, 16)
        elif page_index == 1:
            rows = _d15_sig_rows("bot", bot_ts, 16)
        else:
            rows = _d15_sig_rows("bot2", bot_ts + 16, 8)
        return {"records": rows, "units": 1, "pagination_token": None}

    async def fake_gta(store, grant, config, state, transport, address, options, *, phase, page_index):
        day = _gta_day(options)
        start = int(((options or {}).get("filters") or {}).get("blockTime", {}).get("gte") or 0)
        gta_days.append(day)
        n = 16 if day == "2025-09-14" else 4
        recs = [_d15_econ_swap(address, f"{address[:4]}-{day}-{i}", start + i) for i in range(n)]
        return {"records": recs, "units": 10, "pagination_token": None}

    monkeypatch.setattr(live, "_dispatch_signatures", fake_sigs)
    monkeypatch.setattr(live, "_dispatch_helius", fake_gta)
    config = _dry_config(
        tmp_path,
        seed_source="birdeye_top",
        phases="2",
        discovery=False,
        wallets=D14_WALLET,
        helius_signatures_prescreen=True,
        helius_economic_probe_days=8,
    )
    grant = load_grant(DRAFT)
    store, _ = open_grant_store(config["authorization_id"])
    state = _empty_state(config)
    bind_run_spend(config, state)
    state["wallets"] = [D14_WALLET]
    result = asyncio.run(phase2_prescreen(store, grant, config, state, RecorderTransport()))
    store.close()
    row = result["wallets"][0]
    assert row["dropped"] is True
    assert row["drop_reason"] == GT_ECONOMIC_TRADES_RULE
    assert (row.get("economic_drop") or {}).get("day") == "2025-09-14"
    assert gta_days[0] == "2025-09-14"
    assert "2025-09-14" in gta_days
    assert row.get("cannot_fail_bot_rule") is False


def test_d15_3_probe_budget_marks_bot_unknown_and_ranks_below_clean(tmp_path, monkeypatch):
    import scanner.mass_search.live_e2e as live
    days = [datetime(2026, 1, 1 + i, tzinfo=timezone.utc) for i in range(9)]
    probed = []

    async def fake_sigs(store, grant, config, state, transport, address, *, before=None, phase=2, page_index=0):
        if address != D14_WALLET:
            stamp = int(days[0].timestamp())
            return {"records": _d15_sig_rows("clean", stamp, 5), "units": 1, "pagination_token": None}
        rows = []
        for day in days:
            stamp = int(day.timestamp())
            rows.extend(_d15_sig_rows(day.date().isoformat(), stamp, 16))
        return {"records": rows, "units": 1, "pagination_token": None}

    async def fake_gta(store, grant, config, state, transport, address, options, *, phase, page_index):
        day = _gta_day(options)
        start = int(((options or {}).get("filters") or {}).get("blockTime", {}).get("gte") or 0)
        if page_index >= 900000:
            probed.append(day)
        recs = [_d15_econ_swap(address, f"{address[:4]}-{day}-{i}", start + i) for i in range(4)]
        return {"records": recs, "units": 10, "pagination_token": None}

    monkeypatch.setattr(live, "_dispatch_signatures", fake_sigs)
    monkeypatch.setattr(live, "_dispatch_helius", fake_gta)
    config = _dry_config(
        tmp_path,
        seed_source="birdeye_top",
        phases="2",
        discovery=False,
        wallets=f"{D14_WALLET},{JXT}",
        helius_signatures_prescreen=True,
        helius_economic_probe_days=8,
    )
    grant = load_grant(DRAFT)
    store, _ = open_grant_store(config["authorization_id"])
    state = _empty_state(config)
    bind_run_spend(config, state)
    state["wallets"] = [D14_WALLET, JXT]
    result = asyncio.run(phase2_prescreen(store, grant, config, state, RecorderTransport()))
    store.close()
    by_addr = {row["address"]: row for row in result["wallets"]}
    unknown = by_addr[D14_WALLET]
    clean = by_addr[JXT]
    assert unknown["dropped"] is False
    assert unknown.get("bot_unknown") is True
    assert unknown.get("cannot_fail_bot_rule") is False
    assert len(probed) == 8
    assert (unknown.get("economic_drop") or {}).get("unprobed_days")
    # JXT has no over-days on the same fake_sigs? Wait, fake_sigs ignores address
    # and gives both wallets 9 over-days. Use a clean second wallet via address branch.
    del probed[:]  # ranking uses the stamped flags; rebuild a clean neighbor.
    ranked = rank_by_nansen_pnl([
        {"address": "clean", "cannot_fail_bot_rule": True, "nansen_realized_pnl_usd": "1"},
        {"address": D14_WALLET, "cannot_fail_bot_rule": False, "bot_unknown": True, "nansen_realized_pnl_usd": "999"},
        {"address": "probed-ok", "cannot_fail_bot_rule": False, "nansen_realized_pnl_usd": "50"},
    ])
    assert [row["address"] for row in ranked] == ["clean", "probed-ok", D14_WALLET]


def test_d15_3_neighbor_budget_covers_all_over_days_not_unknown(tmp_path, monkeypatch):
    import scanner.mass_search.live_e2e as live
    day = datetime(2026, 2, 1, tzinfo=timezone.utc)
    stamp = int(day.timestamp())

    async def fake_sigs(store, grant, config, state, transport, address, *, before=None, phase=2, page_index=0):
        return {"records": _d15_sig_rows("one", stamp, 16), "units": 1, "pagination_token": None}

    async def fake_gta(store, grant, config, state, transport, address, options, *, phase, page_index):
        recs = [_d15_econ_swap(address, f"ok-{i}", stamp + i) for i in range(4)]
        return {"records": recs, "units": 10, "pagination_token": None}

    monkeypatch.setattr(live, "_dispatch_signatures", fake_sigs)
    monkeypatch.setattr(live, "_dispatch_helius", fake_gta)
    config = _dry_config(
        tmp_path,
        seed_source="birdeye_top",
        phases="2",
        discovery=False,
        wallets=D14_WALLET,
        helius_signatures_prescreen=True,
        helius_economic_probe_days=8,
    )
    grant = load_grant(DRAFT)
    store, _ = open_grant_store(config["authorization_id"])
    state = _empty_state(config)
    bind_run_spend(config, state)
    state["wallets"] = [D14_WALLET]
    result = asyncio.run(phase2_prescreen(store, grant, config, state, RecorderTransport()))
    store.close()
    row = result["wallets"][0]
    assert row["dropped"] is False
    assert row.get("bot_unknown") is not True


# --- D15-2 ----------------------------------------------------------------

def test_d15_2_run_cap_is_hard_ceiling_under_concurrency(tmp_path):
    config = _dry_config(
        tmp_path,
        seed_source="birdeye_top",
        phases="2",
        discovery=False,
        wallets=JXT,
        run_caps="helius_requests=8,helius_units=25",
    )
    grant = load_grant(DRAFT)
    store, _ = open_grant_store(config["authorization_id"])
    state = _empty_state(config)
    bind_run_spend(config, state)
    started = []
    released = asyncio.Event()

    async def slow_transport(address, *, options, page_index=0):
        started.append(page_index)
        if len(started) < 4:
            await asyncio.sleep(0.05)
        raw = b'{"jsonrpc":"2.0","result":{"data":[],"paginationToken":null}}'
        return {
            "records": [],
            "pagination_token": None,
            "http_status": 200,
            "raw_bytes": raw,
            "units": 0,
        }

    options = gta_options(
        details="full",
        limit=100,
        start_unix=1_700_000_000,
        end_unix=1_700_086_400,
    )

    async def one(index):
        return await _dispatch_helius(
            store, grant, config, state, slow_transport, f"{JXT[:-1]}{index}",
            options, phase=2, page_index=index,
        )

    async def run():
        return await asyncio.gather(*(one(i) for i in range(4)), return_exceptions=True)

    outcomes = asyncio.run(run())
    store.close()
    units = int(state["run_spend"]["helius_units"])
    requests = int(state["run_spend"]["helius_requests"])
    assert units <= 25
    assert requests <= 2
    assert units == 20
    exceeded = [item for item in outcomes if isinstance(item, SourceError) and item.state == "CAP_EXCEEDED"]
    assert exceeded
    ok = [item for item in outcomes if isinstance(item, dict)]
    assert len(ok) == 2


def test_d15_2_neighbor_serial_requests_still_stop_at_the_cap(tmp_path):
    config = _dry_config(
        tmp_path,
        seed_source="birdeye_top",
        phases="2",
        discovery=False,
        wallets=JXT,
        run_caps="helius_requests=2,helius_units=20",
    )
    grant = load_grant(DRAFT)
    store, _ = open_grant_store(config["authorization_id"])
    state = _empty_state(config)
    bind_run_spend(config, state)

    async def transport(address, *, options, page_index=0):
        raw = b'{"jsonrpc":"2.0","result":{"data":[],"paginationToken":null}}'
        return {"records": [], "pagination_token": None, "http_status": 200, "raw_bytes": raw}

    options = gta_options(details="full", limit=100, start_unix=1_700_000_000, end_unix=1_700_086_400)

    async def run():
        await _dispatch_helius(store, grant, config, state, transport, JXT, options, phase=2, page_index=0)
        await _dispatch_helius(store, grant, config, state, transport, JXT, options, phase=2, page_index=1)
        with pytest.raises(SourceError) as raised:
            await _dispatch_helius(store, grant, config, state, transport, JXT, options, phase=2, page_index=2)
        assert raised.value.state == "CAP_EXCEEDED"

    asyncio.run(run())
    store.close()
    assert state["run_spend"]["helius_units"] == 20
    assert state["run_spend"]["helius_requests"] == 2
