"""S1-S9 seed-source fixes. Offline only: no live calls, no secrets."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from scanner.mass_search.adapters import (
    BIRDEYE_TOKEN_LIST_PATH,
    BIRDEYE_TOKEN_TXS_PATH,
    SourceError,
)
from scanner.mass_search.live_e2e import (
    FATAL_SEED_STATES,
    HARD_CEILINGS,
    PINNED_DRAFT_HASHES,
    AUTHORIZATION_ID_13,
    DRAFT_REL_13,
    RecorderTransport,
    ROOT,
    _nansen_error_from_response,
    _nansen_seed_call,
    bind_caps_from_grant,
    birdeye_failure_state,
    empty_phase_spend,
    empty_spend,
    load_grant,
    phase1_discovery,
    phase2_prescreen,
    phase3_wallets,
    validate_config,
)
from scanner.mass_search.live_e2e_ledger import open_grant_store, phase_caps_from_grant, spend_from_ledger
from scanner.mass_search.seed_sources import (
    BIRDEYE_CU_DOCS_URL,
    BIRDEYE_TOKEN_LIST_UNITS,
    BIRDEYE_TOKEN_TXS_UNITS,
    BIRDEYE_TOKEN_TX_SEEK_UNITS,
    NANSEN_LEADERBOARD_PATH,
    NANSEN_PNL_SUMMARY_PATH,
    SEED_NANSEN,
    SEED_TOKEN_INTERSECT,
    SeedSourceError,
    helius_triage_decision,
    nansen_billing_from_headers,
    nansen_first_funder_supported,
    nansen_leaderboard_body,
    nansen_pnl_summary_body,
    redact_nansen_error_body,
    validate_nansen_body,
)

JXT = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
JUP = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
BONK = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
FIXTURE_DIR = ROOT / "tests/fixtures/seed_sources"


def _fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    home = tmp_path / "ledger-home"
    home.mkdir()
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(home))
    monkeypatch.delenv("NANSEN_API_KEY", raising=False)
    return home


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


def test_s2_cu_constants_match_official_birdeye_docs():
    assert BIRDEYE_TOKEN_LIST_UNITS == 60
    assert BIRDEYE_TOKEN_TXS_UNITS == 10
    assert BIRDEYE_TOKEN_TX_SEEK_UNITS == 12
    assert "birdeye.so" in BIRDEYE_CU_DOCS_URL
    assert PINNED_DRAFT_HASHES[AUTHORIZATION_ID_13] == (
        "e9629ca44a48671bb9a61c1b3c2ec19a42aa5338b1fc53e00c55498fe3254a2e"
    )


def test_s3_official_nansen_bodies_pass_and_legacy_bodies_fail():
    leaderboard = nansen_leaderboard_body(timeframe=90, page=1, per_page=50)
    assert leaderboard == {
        "chains": ["solana"],
        "timeframe": 90,
        "pagination": {"page": 1, "per_page": 50},
    }
    validate_nansen_body("leaderboard", leaderboard)
    with pytest.raises(SeedSourceError, match="unknown fields"):
        validate_nansen_body("leaderboard", {"chain": "solana", "dateRange": "90d"})
    with pytest.raises(SeedSourceError, match="missing required field"):
        validate_nansen_body("leaderboard", {"timeframe": 90})
    with pytest.raises(SeedSourceError, match="not in"):
        validate_nansen_body("leaderboard", {"chains": ["solana"], "timeframe": 14})

    summary = nansen_pnl_summary_body(
        wallet_address=JXT,
        date_from="2026-01-01T00:00:00Z",
        date_to="2026-10-07T00:00:00Z",
    )
    assert summary["chain"] == "solana"
    assert summary["date"] == {"from": "2026-01-01T00:00:00Z", "to": "2026-10-07T00:00:00Z"}
    validate_nansen_body("pnl_summary", summary)
    with pytest.raises(SeedSourceError, match="missing required field date"):
        validate_nansen_body("pnl_summary", {"chain": "solana", "wallet_address": JXT})

    with pytest.raises(SeedSourceError, match="not in"):
        validate_nansen_body("first_funder", {"address": "0xabc", "chain": "solana"})
    validate_nansen_body("first_funder", {"address": "0xabc", "chain": "all"})
    assert nansen_first_funder_supported(chain="solana") is False


def test_s3_fake_that_accepts_any_body_cannot_hide_schema_violation(tmp_path):
    class AcceptAny:
        def __init__(self):
            self.called = False

        async def nansen(self, method, path, body=None):
            self.called = True
            return {"status": 200, "body": {"data": []}, "raw_bytes": b"{}"}

    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "nansen")
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    fake = AcceptAny()
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend()}
    with pytest.raises(SeedSourceError):
        asyncio.run(_nansen_seed_call(
            store, grant, config, state, fake,
            path=NANSEN_LEADERBOARD_PATH,
            body={"chain": "solana", "dateRange": "90d"},
            operation="smart_money_pnl_leaderboard",
            units=5,
            wallet="_leaderboard_90",
            page=0,
            identity="test",
        ))
    assert fake.called is False
    store.close()


def test_s3_nansen_dry_run_sends_official_bodies(tmp_path, monkeypatch):
    monkeypatch.setenv("NANSEN_API_KEY", "offline-fixture-not-a-live-secret")
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "nansen")
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    recorder.fixtures = {NANSEN_LEADERBOARD_PATH: _fixture("nansen_leaderboard.json")}
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    bodies = [call["body"] for call in recorder.calls if call["provider"] == "nansen"]
    assert bodies
    assert all("dateRange" not in body for body in bodies)
    assert all("chain" != list(body)[0] or "chains" in body or body.get("chain") == "solana" for body in bodies)
    leaderboards = [body for body in bodies if "chains" in body]
    assert leaderboards
    for body in leaderboards:
        validate_nansen_body("leaderboard", body)
        assert body["chains"] == ["solana"]
        assert body["timeframe"] in (90, 180)
    summaries = [body for body in bodies if "date" in body and "address" in body]
    # pnl-summary is off by default (nansen_profiles=0). If a test config
    # enables it, the body must still be the official schema.
    for body in summaries:
        validate_nansen_body("pnl_summary", body)
        assert body["chain"] == "solana"
        assert body["date"]["from"] and body["date"]["to"]
    assert all(call["path"] != "/api/v1/profiler/address/first-funder" for call in recorder.calls)


def test_s4_nansen_billing_headers_and_redacted_error():
    billing = nansen_billing_from_headers({
        "X-Nansen-Credits-Cost": "5",
        "X-Nansen-Credits-Used": "5",
        "X-Nansen-Credits-Remaining": "994",
        "X-Request-Id": "req-1",
    })
    assert billing == {
        "credits_cost": "5",
        "credits_used": "5",
        "credits_remaining": "994",
        "request_id": "req-1",
    }
    envelope = redact_nansen_error_body({
        "code": "forbidden",
        "message": "plan_upgrade_required",
        "error": "Forbidden",
        "status": 403,
        "request_id": "req-1",
        "wallet_private_key": "should-not-leak",
        "apikey": "should-not-leak",
    })
    assert envelope["code"] == "forbidden"
    assert envelope["message"] == "plan_upgrade_required"
    assert "wallet_private_key" not in envelope
    assert "apikey" not in envelope


def test_s1_dry_run_does_not_write_consumed_grant_receipts(tmp_path):
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "token_intersect", [JUP, BONK, USDC])
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    recorder.fixtures = {
        BIRDEYE_TOKEN_LIST_PATH: _fixture("token_list_durable.json"),
        BIRDEYE_TOKEN_TXS_PATH: _fixture("token_txs_seek.json"),
    }
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    spend, _ = spend_from_ledger(store)
    assert spend["birdeye_requests"] == 0
    assert spend["birdeye_units"] == 0
    receipts = store.list("live_e2e_receipt") or []
    assert all((row or {}).get("state") != "consumed" for row in receipts)
    store.close()


def test_s6a_overlapping_samples_are_deduped_by_signature():
    t0 = 1_790_000_000
    recs = [{"signature": f"s{i}", "blockTime": t0 + i * 60} for i in range(14)]
    evs = [{"kind": "buy" if i % 2 == 0 else "sell", "timestamp": t0 + i * 60, "signature": f"s{i}"} for i in range(14)]
    decision = helius_triage_decision(
        [
            {"records": recs, "events": evs},
            {"records": list(reversed(recs)), "events": list(reversed(evs))},
            {"records": [], "events": []},
        ],
        now_unix=t0 + 400 * 86400,
    )
    assert decision["max_economic_trades_in_one_day"] == 14
    assert decision["dropped"] is False


def test_s6ap_fee_first_same_signature_does_not_drop_trades():
    t0 = 1_790_000_000
    recs = [{"signature": "same", "blockTime": t0 + i} for i in range(3)]
    evs = [
        {"kind": "fee", "timestamp": t0, "signature": "same", "mint": None},
        {"kind": "buy", "timestamp": t0, "signature": "same", "mint": "MintA"},
        {"kind": "sell", "timestamp": t0 + 1, "signature": "same", "mint": "MintA"},
    ]
    decision = helius_triage_decision(
        [{"records": recs, "events": evs}],
        now_unix=t0 + 400 * 86400,
    )
    assert decision["max_economic_trades_in_one_day"] == 2
    assert decision["economic_trades"] == 2
    assert decision["dropped"] is False


def test_s6b_triage_ignores_legacy_max_bot_rate(tmp_path):
    config = validate_config({
        "mode": "dry-run",
        "grant_path": str(ROOT / DRAFT_REL_13),
        "output_dir": str(tmp_path / "out"),
        "phases": "2",
        "discovery": False,
        "seed_source": "token_intersect",
        "wallets": JXT,
        "max_bot_rate": "0.0001",
        "min_in_window_tx": "999",
        "max_unsupported_share": "0",
    })
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": [JXT]}
    result = asyncio.run(phase2_prescreen(store, load_grant(ROOT / DRAFT_REL_13), config, state, recorder))
    store.close()
    row = result["wallets"][0]
    assert row["triage"] is True
    assert row["dropped"] is False
    assert row["drop_reason"] is None


def test_s5_resume_skips_fatal_seed_source(tmp_path):
    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "nansen")
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = RecorderTransport()
    state = {
        "spend": empty_spend(),
        "phase_spend": empty_phase_spend(),
        "wallets": [],
        "seed_source_failures": {
            SEED_NANSEN: {"stop_after_failure": True, "state": "UNSUPPORTED_SCHEMA"},
        },
    }
    result = asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    assert result["per_source"][SEED_NANSEN]["stop_after_failure"] is True
    assert recorder.calls == []


def test_s7_phase_leaderboard_cap_above_zero_is_refused():
    grant = load_grant(ROOT / DRAFT_REL_13)
    with pytest.raises(Exception, match="leaderboard"):
        bind_caps_from_grant(
            {
                **grant,
                "phase_caps": {
                    **grant["phase_caps"],
                    "1": {**grant["phase_caps"]["1"], "leaderboard_requests": 1},
                },
            },
            {},
            mode="dry-run",
        )
    draft_phase = phase_caps_from_grant(grant)
    assert draft_phase["1"]["leaderboard_requests"] == 0
    assert HARD_CEILINGS["leaderboard_requests"] == 0


def test_s8_partial_raw_saved_when_later_token_call_fails(tmp_path):
    class FailAfterList(RecorderTransport):
        async def birdeye(self, method, path, params):
            if path == BIRDEYE_TOKEN_TXS_PATH:
                raise SourceError(
                    "ENTITLEMENT_BLOCKED",
                    "Your API key lacks sufficient permissions to access this resource",
                )
            return await super().birdeye(method, path, params)

    grant = load_grant(ROOT / DRAFT_REL_13)
    config = _phase1_config(tmp_path, "token_intersect")
    Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
    store, _ = open_grant_store(config["authorization_id"])
    recorder = FailAfterList()
    recorder.fixtures = {BIRDEYE_TOKEN_LIST_PATH: _fixture("token_list_durable.json")}
    state = {"spend": empty_spend(), "phase_spend": empty_phase_spend(), "wallets": []}
    with pytest.raises(SourceError) as caught:
        asyncio.run(phase1_discovery(store, grant, config, state, recorder))
    store.close()
    assert caught.value.state == "ENTITLEMENT_BLOCKED"
    raw = Path(config["output_dir"]) / "raw/phase1/token-intersect.bin"
    assert raw.is_file() and raw.stat().st_size > 2
    assert state["seed_source_failures"][SEED_TOKEN_INTERSECT]["stop_after_failure"] is True
    txs_calls = [call for call in recorder.calls if call["path"] == BIRDEYE_TOKEN_TXS_PATH]
    assert txs_calls == []


def test_s9_permission_refusal_is_entitlement_blocked():
    state, message, retryable = birdeye_failure_state(
        200,
        {"success": False, "message": "Your API key lacks sufficient permissions to access this resource"},
    )
    assert state == "ENTITLEMENT_BLOCKED"
    assert retryable is False
    assert "lacks sufficient permissions" in message
    assert birdeye_failure_state(200, {"success": False, "message": "Too many requests"})[0] == "RATE_LIMITED"


def test_s1p_dry_run_does_not_write_grant_lock_or_config(tmp_path, monkeypatch):
    from scanner.mass_search.live_e2e import run_live_e2e
    from tests.test_live_e2e_spend_safety import _arm_grant, _empty_helius, _live_kwargs, pin_test_ledger

    ledger = pin_test_ledger(tmp_path, monkeypatch)
    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", _empty_helius)
    grant_path = _arm_grant(tmp_path, helius_req=10, helius_units=100, bind_hash=False)
    grant = json.loads(Path(grant_path).read_text(encoding="utf-8"))
    out = tmp_path / "dry-out"
    store, _ = open_grant_store(grant["authorization_id"])
    store.put("configuration", "live_authorization", {"marker": "pre-dry-run"})
    store.close()
    asyncio.run(run_live_e2e({
        **_live_kwargs(tmp_path, grant_path, out, [], phases="1"),
        "mode": "dry-run",
        "discovery": False,
        "seed_source": "",
        "wallets": "",
    }))
    assert list(ledger.rglob("GRANT.lock")) == []
    store, _ = open_grant_store(grant["authorization_id"])
    assert store.get("configuration", "live_authorization") == {"marker": "pre-dry-run"}
    store.close()


def test_nansen_402_is_entitlement_blocked():
    err = _nansen_error_from_response(402, {"message": "payment required"}, {"credits_remaining": None})
    assert err.state == "ENTITLEMENT_BLOCKED"
    assert err.http_status == 402
    assert err.state in FATAL_SEED_STATES


def test_nansen_429_is_fatal_so_resume_does_not_resend():
    err = _nansen_error_from_response(429, {"message": "slow down"}, {"credits_remaining": "10"})
    assert err.state == "RATE_LIMITED"
    assert err.retryable is False
    assert "RATE_LIMITED" in FATAL_SEED_STATES


def test_phase3_does_not_fallback_when_phase2_drops_everyone():
    config = {"wallets": [JXT, BONK], "wallets_supplied": True}
    state = {
        "phase2": {
            JXT: {"address": JXT, "dropped": True},
            BONK: {"address": BONK, "dropped": True},
        },
        "wallets": [JXT, BONK, USDC],
    }
    assert phase3_wallets(config, state) == []
    state["phase2"][JXT]["dropped"] = False
    assert phase3_wallets(config, state) == [JXT]
