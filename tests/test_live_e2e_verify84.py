"""Verify-84c16e2 D1–D6 regressions. Offline only: no live calls, no secrets."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from scanner.investigation import PYUSD
from scanner.mass_search import live_e2e as live_e2e_mod
from scanner.mass_search.live_e2e import (
    LiveE2EError,
    _phase4_wallet_row,
    assert_free_disk_before_paid_requests,
    known_trade_rate_from_state,
    phase4_offline,
    resolve_dry_run_ledger_home,
    run_live_e2e,
)
from scanner.mass_search.qualification_gates import (
    GT25_ECONOMIC_TRADES_RULE,
    attach_economic_trade_rate,
    combined_economic_trade_rate,
    economic_trade_rate,
    first_defined_int,
    raw_economic_trade_rate,
    trade_rate_from,
    with_gt25_blocker,
)
from scanner.storage import Store
import tools.independent_episode_audit as auditor

USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
TOKEN_A = "TokenA1111111111111111111111111111111111111"

WALLETS = {
    "3jvkujAb": {
        "address": "3jvkujAb111111111111111111111111111111111",
        "day": "2026-08-30",
        "raw": 35,
        "decoded": 24,
    },
    "8B3KyNP6": {
        "address": "8B3KyNP611111111111111111111111111111111",
        "day": "2026-10-03",
        "raw": 37,
        "decoded": 25,
    },
    "8tH2ia4F": {
        "address": "8tH2ia4F111111111111111111111111111111111",
        "day": "2026-08-26",
        "raw": 74,
        "decoded": 22,
    },
}


def _unix(day):
    return int(datetime.fromisoformat(f"{day}T12:00:00+00:00").timestamp())


def _token_usdt_swap(wallet, sig, block_time, token=TOKEN_A):
    return {
        "transaction": {
            "signatures": [sig],
            "message": {"accountKeys": [wallet, "11111111111111111111111111111111"]},
        },
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [1_000_000_000, 1],
            "postBalances": [999_995_000, 1],
            "preTokenBalances": [
                {"owner": wallet, "mint": token, "uiTokenAmount": {"amount": "100"}},
                {"owner": wallet, "mint": USDT, "uiTokenAmount": {"amount": "0"}},
            ],
            "postTokenBalances": [
                {"owner": wallet, "mint": token, "uiTokenAmount": {"amount": "0"}},
                {"owner": wallet, "mint": USDT, "uiTokenAmount": {"amount": "50"}},
            ],
        },
        "blockTime": block_time,
    }


def _decoded_events(count, day, mint=TOKEN_A):
    stamp = _unix(day)
    return [
        {"kind": "buy", "signature": f"decoded-{index}", "mint": mint, "timestamp": stamp + index}
        for index in range(count)
    ]


def _raw_swaps(wallet, count, day):
    stamp = _unix(day)
    return [_token_usdt_swap(wallet, f"raw-{index}", stamp + index) for index in range(count)]


@pytest.mark.parametrize("prefix", ["3jvkujAb", "8B3KyNP6", "8tH2ia4F"])
def test_d1_raw_tx_count_beats_decoder_on_named_wallet_days(prefix):
    spec = WALLETS[prefix]
    address = spec["address"]
    records = _raw_swaps(address, spec["raw"], spec["day"])
    events = _decoded_events(spec["decoded"], spec["day"])
    decoded = economic_trade_rate(events)
    raw = raw_economic_trade_rate(records, address)
    combined = combined_economic_trade_rate(events=events, records=records, address=address)
    assert decoded["max"] == spec["decoded"]
    assert raw["max"] == spec["raw"]
    assert raw["max_on"] == spec["day"]
    assert combined["max"] == spec["raw"]
    assert combined["max_on"] == spec["day"]
    independent, _incomplete = auditor.raw_economic_trades_by_utc_day(records, address)
    assert independent[spec["day"]] == spec["raw"]
    assert auditor.combined_economic_trades_by_utc_day(events, records, address)[spec["day"]] == spec["raw"]


def test_d1_multi_hop_nets_to_one_tx():
    wallet = WALLETS["3jvkujAb"]["address"]
    hop = _token_usdt_swap(wallet, "hop", _unix("2026-08-30"))
    hop["meta"]["preTokenBalances"].append(
        {"owner": wallet, "mint": "MidMint111111111111111111111111111111111", "uiTokenAmount": {"amount": "0"}}
    )
    hop["meta"]["postTokenBalances"].append(
        {"owner": wallet, "mint": "MidMint111111111111111111111111111111111", "uiTokenAmount": {"amount": "0"}}
    )
    rate = raw_economic_trade_rate([hop], wallet)
    assert rate["max"] == 1


def test_d1_fail_closed_when_timestamp_missing():
    wallet = WALLETS["8B3KyNP6"]["address"]
    records = _raw_swaps(wallet, 3, "2026-10-03")
    records[0]["blockTime"] = None
    rate = raw_economic_trade_rate(records, wallet)
    assert rate["incomplete"] is True
    assert rate["incomplete_uncounted"] >= 1


def test_d6_float_timestamp_counts_and_zero_is_zero():
    events = [
        {"kind": "buy", "signature": "f1", "mint": TOKEN_A, "timestamp": 1_775_000_000.9},
    ]
    rate = economic_trade_rate(events)
    assert rate["max"] == 1
    assert rate["incomplete"] is False
    assert first_defined_int(0, None, 4) == 0
    target = {}
    attach_economic_trade_rate(target, [])
    assert target["max_economic_trades_in_one_day"] == 0
    row = _phase4_wallet_row(
        {"address": "z", "history": {}, "prescreen": {}, "bundle_or_distribution": {}, "window": {}},
        {"max_economic_trades_in_one_day": 0, "completed_known_cost_positions": 0, "qualification_level": {}},
    )
    assert row["max_economic_trades_in_one_day"] == 0


def test_d6_stored_max_does_not_override_higher_event_count():
    events = _decoded_events(20, "2026-01-02")
    report = {
        "max_economic_trades_in_one_day": 10,
        "max_economic_trades_on": "2026-01-01",
        "captured_history_events": events,
    }
    rate = trade_rate_from(report=report)
    assert rate["max"] == 20
    assert rate["max_on"] == "2026-01-02"


def test_d6_pyusd_mint_constant():
    assert PYUSD == "2b1kV6DkPAnxd5ixfnxCpjxmKwqjjaYmCZfHsFu24GXo"


def test_d4_oversold_flatten_records_losing_episode():
    def row(kind, sig, ts, qty, sol, post, pre="0"):
        return {
            "kind": kind,
            "mint": "M",
            "signature": sig,
            "timestamp": ts,
            "slot": ts,
            "quantity_raw": str(qty),
            "consideration_sol": str(sol),
            "fees_and_tips_sol": "0",
            "observed_pre_quantity_raw": pre,
            "observed_post_quantity_raw": str(post),
            "settlement_asset": "SOL",
        }

    original = auditor.REPORT_START, auditor.REPORT_END
    auditor.REPORT_START, auditor.REPORT_END = 0, 2 ** 40
    try:
        loser = [row("buy", "b1", 1, 100, 10, 100), row("sell", "s1", 2, 150, 2, 0)]
        eps, _unres, _known, omitted = auditor._fifo(loser)
        assert eps == []
        assert omitted
        assert Decimal(omitted[0]["net_profit_sol"]) < 0
        winner = [row("buy", "b1", 1, 100, 1, 100), row("sell", "s1", 2, 150, 20, 0)]
        _eps, _unres, _known, omitted_win = auditor._fifo(winner)
        assert omitted_win == []
        exact = [row("buy", "b1", 1, 100, 10, 100), row("sell", "s1", 2, 100, 2, 0)]
        eps_exact, _unres, _known, omitted_exact = auditor._fifo(exact)
        assert len(eps_exact) == 1
        assert Decimal(eps_exact[0]["net_profit_sol"]) < 0
        assert omitted_exact == []

        def loss_visible(trades):
            eps, _u, _k, omitted = auditor._fifo(trades)
            return any(Decimal(e["net_profit_sol"]) < 0 for e in eps) or bool(omitted)

        case3 = [
            row("buy", "b1", 1, 100, 10, 100),
            {**row("sell", "s1", 2, 120, 2, 0), "observed_post_quantity_raw": ""},
            row("sell", "s2", 3, 30, 0.1, 0),
        ]
        case4 = [
            row("buy", "b1", 1, 100, 10, 100),
            row("sell", "s1", 2, 120, 2, 30),
            row("sell", "s2", 3, 30, 0.1, 0),
        ]
        case8 = [
            row("buy", "b1", 1, 100, 10, 100),
            row("buy", "x", 2, 10, 1, 10),
            row("sell", "x", 2, 150, 2, 10),
            row("sell", "s3", 3, 10, 1.5, 0),
        ]
        assert loss_visible(case3)
        assert loss_visible(case4)
        assert loss_visible(case8)
    finally:
        auditor.REPORT_START, auditor.REPORT_END = original


def test_d5_blocker_always_names_gt25_with_count_and_date():
    rate = {"max": 41, "max_on": "2026-09-09"}
    assert GT25_ECONOMIC_TRADES_RULE in with_gt25_blocker("per_wallet_cap", rate)
    assert "41" in with_gt25_blocker("controlled_pair", rate)
    assert "2026-09-09" in with_gt25_blocker("multi_signer_bundle_buy", rate)
    report = {
        "address": "EZcv4WSE111111111111111111111111111111111",
        "history": {"history_complete": False, "history_complete_reason": "per_wallet_cap"},
        "bundle_or_distribution": {"excluded": True, "reason": "controlled_pair"},
        "prescreen": {},
        "window": {},
        "max_economic_trades_in_one_day": 41,
        "max_economic_trades_on": "2026-09-09",
    }
    profile = {
        "max_economic_trades_in_one_day": 41,
        "max_economic_trades_on": "2026-09-09",
        "completed_known_cost_positions": 0,
        "qualification_level": {"level": "insufficient_evidence"},
    }
    row = _phase4_wallet_row(report, profile)
    assert GT25_ECONOMIC_TRADES_RULE in (row["blocker"] or "")
    assert "41" in (row["blocker"] or "")
    assert "2026-09-09" in (row["blocker"] or "")


def test_d5_triage_drop_names_known_count(tmp_path):
    from scanner.mass_search.seed_sources import helius_triage_decision

    address = "2M2vLX3411111111111111111111111111111111"
    day = int(datetime(2025, 3, 2, tzinfo=timezone.utc).timestamp())
    events = [
        {"kind": "buy", "signature": f"t{i}", "mint": f"M{i}", "timestamp": day + i}
        for i in range(45)
    ]
    decision = helius_triage_decision(
        [{"events": events, "records": [], "address": address}],
        now_unix=day + 86400,
        address=address,
    )
    assert decision["dropped"] is True
    assert decision["max_economic_trades_in_one_day"] == 45
    assert decision["max_economic_trades_on"] == "2025-03-02"
    state = {
        "phase2": {
            address: {
                "dropped": True,
                "triage_decision": decision,
            }
        },
        "phase3": {},
    }
    store = Store(tmp_path / "led")
    result = phase4_offline(
        store,
        {
            "bounds": {"report_start_inclusive": "2026-01-01T00:00:00Z", "report_end_exclusive": "2026-10-08T00:00:00Z"},
            "output_dir": str(tmp_path / "out"),
            "wallets": [address],
            "phases": (4,),
            "authorization_id": "dry",
            "dry_run": True,
        },
        state,
    )
    store.close()
    row = result["wallets"][0]
    assert "no captured history" in (row["blocker"] or "")
    assert GT25_ECONOMIC_TRADES_RULE in (row["blocker"] or "")
    assert "45" in (row["blocker"] or "")
    assert "2025-03-02" in (row["blocker"] or "")
    known = known_trade_rate_from_state(state, address)
    assert known["max"] == 45


def test_d2_resume_phases_4_recomputes_stale_rows(tmp_path, monkeypatch):
    from tests.test_live_e2e_spend_safety import _arm_grant, _live_kwargs, pin_test_ledger

    pin_test_ledger(tmp_path, monkeypatch)
    grant = _arm_grant(tmp_path, helius_req=10, helius_units=100, bind_hash=False)
    out = tmp_path / "stale4"
    address = "StaleWallet111111111111111111111111111111"
    state = {
        "kind": "live-e2e-run-state-v1",
        "status": "completed",
        "phases_done": [2, 3, 4],
        "wallets": [address],
        "bounds": {
            "window_days": 30,
            "report_window_days": 30,
            "earlier_history_days": 60,
            "report_end_exclusive": "2026-10-07T00:00:00Z",
        },
        "phase2": {address: {"done": True}},
        "phase3": {address: {"done": True, "pages": 1}},
        "phase4_wallets": [{
            "address": address,
            "completed_trades": 99,
            "blocker": "stale-old-code",
        }],
        "phase4_fingerprint": "old",
        "spend": {"birdeye_requests": 0, "birdeye_units": 0, "helius_requests": 0, "helius_units": 0},
        "phase_spend": {},
        "PRODUCT_READY": False,
    }
    out.mkdir()
    (out / "RUN_STATE.json").write_text(json.dumps(state), encoding="utf-8")
    result = asyncio.run(run_live_e2e({
        **_live_kwargs(tmp_path, grant, out, [address], phases="4", resume=True),
        "mode": "dry-run",
    }))
    rows = result.get("wallets") or []
    assert rows
    assert rows[0].get("blocker") != "stale-old-code"
    assert rows[0].get("completed_trades") != 99
    assert "max_economic_trades_in_one_day" in rows[0]


def _ledger_fingerprint(root):
    root = Path(root)
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_d3_dry_run_does_not_touch_armed_ledger(tmp_path, monkeypatch):
    from tests.test_live_e2e_spend_safety import _arm_grant, _live_kwargs

    armed = tmp_path / "armed-ledgers"
    armed.mkdir()
    marker = armed / "do-not-touch.txt"
    marker.write_text("armed", encoding="utf-8")
    store = Store(armed / "live-e2e-proof-2026-10-13-mitch")
    store.put("reports", "keep", {"id": "keep", "note": "preexisting"})
    store.close()
    before = _ledger_fingerprint(armed)
    monkeypatch.delenv("SCANNER_LIVE_LEDGER_HOME", raising=False)
    monkeypatch.delenv("SCANNER_LIVE_LEDGER_DIR", raising=False)
    monkeypatch.setattr(live_e2e_mod, "DEFAULT_LEDGER_ROOT", armed)
    monkeypatch.setattr(live_e2e_mod, "PINNED_LEDGER_ABSOLUTE", str(armed))
    monkeypatch.setattr(live_e2e_mod, "COMMITTED_LEDGER_ABSOLUTE", str(armed))
    monkeypatch.setattr("scanner.mass_search.live_e2e_ledger.DEFAULT_LEDGER_ROOT", armed)
    grant = _arm_grant(tmp_path, helius_req=10, helius_units=100, bind_hash=False)
    out = tmp_path / "dry-out"
    out.mkdir()
    address = "DryRunWallet11111111111111111111111111111"
    (out / "RUN_STATE.json").write_text(json.dumps({
        "kind": "live-e2e-run-state-v1",
        "status": "completed",
        "phases_done": [2, 3],
        "wallets": [address],
        "bounds": {
            "window_days": 30,
            "report_window_days": 30,
            "earlier_history_days": 60,
            "report_end_exclusive": "2026-10-07T00:00:00Z",
        },
        "phase2": {address: {"done": True}},
        "phase3": {address: {"done": True, "pages": 0}},
        "spend": {"birdeye_requests": 0, "birdeye_units": 0, "helius_requests": 0, "helius_units": 0},
        "phase_spend": {},
        "PRODUCT_READY": False,
    }), encoding="utf-8")
    result = asyncio.run(run_live_e2e({
        **_live_kwargs(tmp_path, grant, out, [address], phases="4", resume=True),
        "mode": "dry-run",
        "ledger_dir": None,
    }))
    assert result["dry_run"] is True
    assert _ledger_fingerprint(armed) == before
    isolated = out / ".dry-run-ledger"
    assert isolated.is_dir()
    with pytest.raises(LiveE2EError, match="armed grant ledger"):
        resolve_dry_run_ledger_home(out, armed)


def test_disk_refuse_before_paid_request(tmp_path, monkeypatch):
    monkeypatch.setenv("SCANNER_MIN_FREE_DISK_MB", "2048")
    monkeypatch.setattr(
        live_e2e_mod.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=100 * 1024 * 1024),
    )
    with pytest.raises(LiveE2EError, match="refusing before any paid request"):
        assert_free_disk_before_paid_requests(tmp_path)
    opened = []

    def fake_validate(_raw):
        return {
            "dry_run": False,
            "output_dir": str(tmp_path / "out"),
            "authorization_id": "x",
            "ledger_dir": None,
            "ledger_home": None,
            "store_path": str(tmp_path / "led"),
            "grant": {},
        }

    monkeypatch.setattr(live_e2e_mod, "validate_config", fake_validate)
    monkeypatch.setattr(
        live_e2e_mod,
        "open_grant_store",
        lambda *args, **kwargs: opened.append("store") or (_ for _ in ()).throw(AssertionError("store opened")),
    )
    with pytest.raises(LiveE2EError, match="refusing before any paid request"):
        asyncio.run(run_live_e2e({"mode": "live"}))
    assert opened == []
