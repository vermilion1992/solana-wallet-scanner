"""G1 grant, independent worksheet oracle, and live-runner blockers."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from scanner.mass_search.capability import validate_live_authorization
from scanner.mass_search.live_g1 import (
    GRANT_PATH,
    independent_fifo_worksheet,
    load_grant,
    run_g1,
)
from scanner.mass_search.universe import synthetic_address
from scanner.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def test_g1_grant_enabled_and_non_grants_stay_disabled():
    raw = json.loads(GRANT_PATH.read_text(encoding="utf-8"))
    assert raw["enabled"] is False
    grant = load_grant(GRANT_PATH)
    assert grant["enabled"] is False
    assert grant.get("reason") == "Authorization file is disabled"
    assert grant["authorization_id"] == "live-g1-vertical-slice-2026-10-05-mitch"
    assert grant["max_additional_spend_usd"] == "0"
    assert grant["overages_enabled"] is False
    assert grant["do_not_reset_setup_pilot"] is True
    birdeye = next(entry for entry in grant["providers"] if entry["provider_id"] == "birdeye")
    helius = next(entry for entry in grant["providers"] if entry["provider_id"] == "helius")
    assert birdeye["max_requests"] == 10 and birdeye["max_units"] == 250
    assert helius["max_requests"] == 20 and helius["max_units"] == 600
    example = validate_live_authorization(json.loads(
        (ROOT / "work_packages/mass_wallet_search_v1/config/live_authorization.example.json").read_text()
    ))
    draft = validate_live_authorization(json.loads(
        (ROOT / "config/live_authorization.proof-grant-draft.json").read_text()
    ))
    ranked100 = validate_live_authorization(json.loads(
        (ROOT / "config/live_authorization.g2-ranked100-discovery-granted.json").read_text()
    ))
    assert example["enabled"] is False
    assert draft["enabled"] is False
    assert ranked100["enabled"] is False
    assert ranked100.get("authorization_id") == "live-g2-ranked100-discovery-2026-10-05-mitch"
    g3 = validate_live_authorization(json.loads(
        (ROOT / "config/live_authorization.g3-ranked100-history-granted.json").read_text()
    ))
    assert g3["enabled"] is False
    assert g3.get("authorization_id") == "live-g3-ranked100-history-2026-10-06-mitch"
    reacquire = validate_live_authorization(json.loads(
        (ROOT / "config/live_authorization.g3-integrity-reacquire-rank1-draft.json").read_text()
    ))
    assert reacquire["enabled"] is False
    assert reacquire.get("authorization_id") == "live-g3-integrity-reacquire-rank1-2026-10-06-mitch"
    anchored = validate_live_authorization(json.loads(
        (ROOT / "config/live_authorization.ranked100-anchored-validation-draft.json").read_text()
    ))
    assert anchored["enabled"] is False
    assert anchored.get("authorization_id") == "live-ranked100-anchored-validation-2026-10-06-mitch"
    assert anchored.get("authorized_by_user_at") is None
    assert anchored.get("expires_at") is None
    nxt = validate_live_authorization(json.loads(
        (ROOT / "config/live_authorization.ranked100-next-candidates-draft.json").read_text()
    ))
    assert nxt["enabled"] is False
    assert nxt.get("authorization_id") == "live-ranked100-next-candidates-2026-10-06-mitch"
    assert nxt.get("authorized_by_user_at") is None
    assert nxt.get("expires_at") is None
    live_e2e = validate_live_authorization(json.loads(
        (ROOT / "config/live_authorization.live-e2e-proof-2026-10-07-mitch-draft.json").read_text()
    ))
    assert live_e2e["enabled"] is False
    assert live_e2e.get("authorization_id") == "live-e2e-proof-2026-10-07-mitch"
    assert live_e2e.get("authorized_by_user_at") is None


def test_independent_fifo_oracle_does_not_import_production_helper():
    events = [
        {"kind": "buy", "units": "100", "consideration_sol": "1", "wallet_fee_sol": "0.01"},
        {"kind": "sell", "units": "50", "consideration_sol": "0.8", "wallet_fee_sol": "0.005"},
        {"kind": "sell", "units": "45", "consideration_sol": "0.72", "wallet_fee_sol": "0.005"},
        {"kind": "sell", "units": "5", "consideration_sol": "0.08", "wallet_fee_sol": "0.005"},
    ]
    worksheet = independent_fifo_worksheet(events)
    assert worksheet["oracle"] == "independent-g1-fifo-v1"
    assert worksheet["total_profit_sol"].startswith("0.575")
    assert "scanner.mass_search.metrics" not in independent_fifo_worksheet.__globals__
    assert "fifo_sale_results" not in independent_fifo_worksheet.__globals__


def test_g1_blocks_without_provider_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("BIRDEYE_API_KEY", raising=False)
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    store = Store(tmp_path / "data")
    setup = store.reserve("helius", "getTransaction", 200, "setup-pilot", 200)
    store.dispatch(setup)
    store.settle(setup)
    assert store.usage("helius", "setup-pilot", 200)["remaining"] == 0
    result = asyncio.run(run_g1(
        store,
        evidence_dir=tmp_path / "evidence",
        application_sha="test",
        hardware={"test": True},
    ))
    assert result["status"] == "BLOCKED"
    assert result["blocker"] == "grant_disabled"
    assert result["authorization_id"] == "live-g1-vertical-slice-2026-10-05-mitch"
    assert store.usage("helius", "setup-pilot", 200)["remaining"] == 0
    assert not (tmp_path / "evidence" / result["run_id"] / "PRE_RUN_FREEZE.json").is_file()
    assert (tmp_path / "evidence" / result["run_id"] / "G1_RESULT.json").is_file()
    store.close()


def test_g1_mocked_supported_pair_does_not_touch_setup_pilot(tmp_path, monkeypatch):
    monkeypatch.delenv("BIRDEYE_API_KEY", raising=False)
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    store = Store(tmp_path / "data")
    setup = store.reserve("helius", "getTransaction", 200, "setup-pilot", 200)
    store.dispatch(setup)
    store.settle(setup)
    address = synthetic_address(7)
    mint = "Mint1111111111111111111111111111111111111"

    async def birdeye(method, path, params):
        return {
            "status": 200,
            "fetched_at": "2026-10-05T00:00:00Z",
            "body": {"data": {"items": [{"address": address, "realized_pnl": "12.5", "trade_count": 24}]}},
        }

    async def helius(target, **kwargs):
        assert target == address
        return {"records": [{"transaction": {"signatures": ["sig-buy"]}}], "external_requests": 1,
                "evidence_sha256": "a" * 64}

    def decode(records, target):
        return {
            "events": [
                {"kind": "buy", "timestamp": 1_700_000_000, "quantity_raw": "100", "amount_sol": "1",
                 "fee_sol": "0.01", "mint": mint, "signature": "sig-buy", "evidence": ["a" * 64]},
                {"kind": "sell", "timestamp": 1_700_000_030, "quantity_raw": "100", "amount_sol": "1.2",
                 "fee_sol": "0.01", "mint": mint, "signature": "sig-sell", "evidence": ["a" * 64]},
            ],
            "coverage": {"decoded_swaps": 2},
        }

    armed = json.loads(GRANT_PATH.read_text(encoding="utf-8"))
    armed["enabled"] = True
    armed["expires_at"] = "2099-01-01T00:00:00Z"
    for entry in armed["providers"]:
        entry["existing_plan_confirmed"] = True
        entry["remaining_quota_confirmed_at"] = armed["authorized_by_user_at"]
    grant_path = tmp_path / "g1-armed-test.json"
    grant_path.write_text(json.dumps(armed), encoding="utf-8")
    result = asyncio.run(run_g1(
        store,
        evidence_dir=tmp_path / "evidence",
        application_sha="test",
        hardware={"test": True},
        transports={"birdeye": birdeye, "helius": helius, "decode": decode, "skip_credential_check": True},
        grant_path=grant_path,
    ))
    assert result["status"] == "PASS"
    assert result["address"] == address
    assert result["not_wallet_wide_match"] is True
    assert result["independent_worksheet"]["total_profit_sol"].startswith("0.18")
    assert result["setup_pilot_before"]["remaining"] == 0
    assert result["setup_pilot_after"]["remaining"] == 0
    store.close()
