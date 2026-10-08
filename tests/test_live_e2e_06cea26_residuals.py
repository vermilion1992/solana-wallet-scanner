"""06cea26 live-run residuals. Offline only; keys must stay unset or dummy."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from scanner.investigation import (
    PHOTON,
    UNSUPPORTED_PINNED_OUTER,
    decode_supported_swaps,
)
from scanner.mass_search.bundle_detect import detect_bundle_or_distribution
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.g3_history import inject_undecoded_buy_taints
from scanner.mass_search.live_e2e import (
    AUTHORIZATION_ID,
    LIVE_KNOWN_DRAFTS,
    RETIRED_LIVE_DRAFTS,
    LiveE2EError,
    assess_history_completeness,
    birdeye_failure_state,
    compute_bot_rate,
    discovery_identity,
    estimate_phase3_pages,
    page_sort_key,
    validate_config,
)
from scanner.mass_search.research_profile import (
    build_research_profile,
    default_filters,
    evaluate_thresholds,
)
from scanner.mass_search.settlement import isolate_known_cost_events

FIXTURE = Path("tests/fixtures/live-e2e-06cea26")
ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


def test_retired_07_draft_refused_for_live(tmp_path, monkeypatch):
    assert AUTHORIZATION_ID in RETIRED_LIVE_DRAFTS
    assert AUTHORIZATION_ID not in LIVE_KNOWN_DRAFTS
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(tmp_path / "ledger"))
    monkeypatch.setenv("HELIUS_API_KEY", "dummy-helius-key-06cea26")
    raw = json.loads((ROOT / "config/live_authorization.live-e2e-proof-2026-10-07-mitch-draft.json").read_text())
    raw["enabled"] = True
    raw["authorized_by_user_at"] = "2026-10-07T00:00:00Z"
    raw["expires_at"] = "2099-01-01T00:00:00Z"
    raw["armed_home"] = str(Path.home())
    raw["ledger_home"] = str(tmp_path / "ledger")
    raw["draft_artifact_hash"] = "ca4c3f9637d5d8ee11475a8c1704bb964a0a7bed4e126c69e92c65ef9043f410"
    for entry in raw["providers"]:
        entry["existing_plan_confirmed"] = True
        entry["remaining_quota_confirmed_at"] = "2026-10-07T00:00:00Z"
    grant = tmp_path / "armed-07.json"
    grant.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(LiveE2EError, match="retired"):
        validate_config({
            "mode": "live",
            "grant_path": str(grant),
            "output_dir": str(tmp_path / "out"),
            "ledger_dir": str(tmp_path / "ledger"),
            "wallets": ["W000000000000000000000000000000000000000001"],
            "phases": "2",
            "window_days": 30,
            "earlier_history_days": 60,
        })


def test_b1_truncated_history_is_explicit():
    payload = _load("jxt-oldest-records.json")
    assessed = assess_history_completeness(
        payload["records"],
        payload["leftover_pagination_token"],
        address=payload["address"],
    )
    assert assessed["history_complete"] is False
    assert assessed["history_complete_reason"] == "pagination_token_remaining_earlier_history"
    assert assessed["wallet_created_in_range"] is False
    assert assessed["oldest_native_prebalance"] not in (0, None)

    created = json.loads(json.dumps(payload["records"]))
    raw = created[0]
    if "transaction" in raw:
        keys = []
        message = (raw.get("transaction") or {}).get("message") or {}
        for item in message.get("accountKeys") or []:
            keys.append(item if isinstance(item, str) else item.get("pubkey"))
        if payload["address"] in keys:
            idx = keys.index(payload["address"])
            pre = raw.setdefault("meta", {}).setdefault("preBalances", [])
            if idx < len(pre):
                pre[idx] = 0
    created_assessed = assess_history_completeness(created, True, address=payload["address"])
    assert created_assessed["wallet_created_in_range"] is True
    assert created_assessed["leftover_pagination_token"] is True
    assert created_assessed["history_complete"] is False
    assert created_assessed["history_complete_reason"] == "pagination_token_remaining_earlier_history"


def test_b2_token_inflow_without_account_keys():
    payload = _load("token-in-no-account-keys.json")
    detected = detect_bundle_or_distribution(payload["records"], payload["address"])
    # Never-sold inflows are quarantined inventory, not a wallet-level block.
    assert "transfer_in_zero_basis" not in (detected.get("reasons") or [])
    assert detected.get("quarantined_mints")


def test_b3_fee_payer_multi_signer_is_flagged():
    payload = _load("dky-multi-signer-fee-payer.json")
    detected = detect_bundle_or_distribution([payload["record"]], payload["address"])
    assert detected["excluded"] is True
    assert "multi_signer_bundle_buy" in detected["reasons"]
    assert detected["multi_signer_buys"][0]["wallet_is_fee_payer"] is True


def test_b4_undecoded_buy_taint_reaches_profile():
    decoded = inject_undecoded_buy_taints(
        {"events": [
            {"kind": "sell", "mint": "M", "quantity_raw": "10", "signature": "s1",
             "amount_sol": "2", "timestamp": 20, "seconds_from_start": 20},
        ]},
        [{
            "signature": "u1",
            "transaction": {"signatures": ["u1"], "message": {"accountKeys": ["W"]}},
            "meta": {
                "err": None,
                "preTokenBalances": [{"owner": "W", "mint": "M", "uiTokenAmount": {"amount": "0"}}],
                "postTokenBalances": [{"owner": "W", "mint": "M", "uiTokenAmount": {"amount": "10"}}],
            },
            "blockTime": 10,
        }],
        "W",
    )
    report = {
        "events": [
            {"kind": "sell", "mint": "M", "quantity_raw": "10", "signature": "s1",
             "amount_sol": "2", "timestamp": 20, "seconds_from_start": 20},
        ],
        "worksheet": {},
        "classification": {"counts": {}, "transactions": 2},
        "coverage": {"decoded_swaps": 1},
    }
    profile = build_research_profile(report, filters=default_filters(), decoded=decoded)
    assert profile["unresolved_basis_sales"] >= 1
    assert profile.get("matched_fragment_pnl") in (None, "")


def test_b5_photon_is_honestly_unsupported():
    assert PHOTON in UNSUPPORTED_PINNED_OUTER
    payload = json.loads((Path("tests/fixtures/live-e2e-phase3") / "photon-swap.json").read_text())
    decoded = decode_supported_swaps(canonical_decode_records([payload["record"]]), payload["address"])
    trades = [row for row in decoded.get("events") or [] if row.get("kind") in ("buy", "sell")]
    assert trades == []


def test_b5_flashx_fixture_does_not_fake_a_decode():
    payload = json.loads((Path("tests/fixtures/live-e2e-phase3") / "flashx-swap.json").read_text())
    decoded = decode_supported_swaps(canonical_decode_records([payload["record"]]), payload["address"])
    trades = [row for row in decoded.get("events") or [] if row.get("kind") in ("buy", "sell")]
    assert trades == []


def test_bst_token2022_close_decodes_pumpswap_sell():
    payload = _load("bst-missing-close.json")
    decoded = decode_supported_swaps(canonical_decode_records([payload["record"]]), payload["address"])
    sells = [row for row in decoded.get("events") or [] if row.get("kind") == "sell"]
    assert len(sells) == 1
    assert sells[0]["mint"].startswith("CZJfrAmM")
    assert Decimal(str(sells[0]["quantity_raw"])) == Decimal("1905803009216")


def test_birdeye_429_and_success_false_are_errors():
    assert birdeye_failure_state(429, {"success": True})[0] == "RATE_LIMITED"
    state, message, retryable = birdeye_failure_state(200, {"success": False, "message": "Too many requests"})
    assert state == "RATE_LIMITED"
    assert retryable is True
    assert "Too many" in message
    assert birdeye_failure_state(200, {"success": True, "data": {"items": []}}) is None


def test_zero_completed_fails_min_scoped_pnl():
    judged = evaluate_thresholds(
        {
            "completed_known_cost_positions": 0,
            "settlement_asset": "SOL",
            "scoped_pnl": None,
            "scoped_pnl_by_quote_asset": {},
        },
        {"min_scoped_pnl_sol": "0"},
    )
    assert judged["results"]["min_scoped_pnl_sol"]["passed"] is False
    assert judged["criteria_met"] is False


def test_bot_rate_uses_observed_span_not_window():
    records = [{"blockTime": 1_000_000}, {"blockTime": 1_000_000 + 86400}]
    rate = compute_bot_rate(records * 50, window_days=30)
    assert rate == Decimal("100.0000")
    full_page = [{"blockTime": 1_000_000 + i} for i in range(1000)]
    dense = compute_bot_rate(full_page, window_days=30)
    assert dense > Decimal("50")


def test_benign_wsol_wrap_is_not_zero_basis():
    wsol = "So11111111111111111111111111111111111111112"
    record = {
        "signature": "wrap",
        "transaction": {"signatures": ["wrap"], "message": {"accountKeys": ["W"], "instructions": []}},
        "meta": {
            "err": None,
            "preTokenBalances": [],
            "postTokenBalances": [{"owner": "W", "mint": wsol, "uiTokenAmount": {"amount": "1000000000"}}],
            "preBalances": [2_000_000_000],
            "postBalances": [1_000_000_000],
            "fee": 5000,
        },
        "blockTime": 1,
    }
    detected = detect_bundle_or_distribution([record], "W")
    assert "transfer_in_zero_basis" not in (detected.get("reasons") or [])


def test_usdc_deposit_without_sale_is_not_zero_basis():
    usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    record = {
        "signature": "usdc",
        "transaction": {
            "signatures": ["usdc"],
            "message": {
                "accountKeys": ["W", "Other"],
                "instructions": [{
                    "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                    "parsed": {"type": "transfer", "info": {
                        "authority": "Other", "source": "OtherATA", "destination": "WATA",
                    }},
                }],
            },
        },
        "meta": {
            "err": None,
            "preTokenBalances": [{"owner": "W", "mint": usdc, "uiTokenAmount": {"amount": "0"}}],
            "postTokenBalances": [{"owner": "W", "mint": usdc, "uiTokenAmount": {"amount": "1000000"}}],
            "preBalances": [1, 1],
            "postBalances": [1, 1],
            "fee": 5000,
        },
        "blockTime": 1,
    }
    detected = detect_bundle_or_distribution([record], "W")
    assert detected.get("excluded") is False


def test_page_sort_is_numeric():
    names = [Path(f"page{n}.bin") for n in ("10", "2", "1", "0")]
    ordered = [p.name for p in sorted(names, key=page_sort_key)]
    assert ordered == ["page0.bin", "page1.bin", "page2.bin", "page10.bin"]


def test_discovery_identity_distinguishes_requests():
    a = discovery_identity({"discovery_source": "gainers-losers", "birdeye_window": "30d", "birdeye_sort": "PnL"})
    b = discovery_identity({"discovery_source": "gainers-losers", "birdeye_window": "1W", "birdeye_sort": "PnL"})
    c = discovery_identity({
        "discovery_source": "top-traders",
        "birdeye_window": "30d",
        "birdeye_sort": "realized_pnl",
        "birdeye_tokens": ["A", "B"],
    })
    assert a != b != c
    assert a != c


def test_planner_uses_prescreen_density():
    estimates = estimate_phase3_pages(
        {"window_days": 30, "earlier_history_days": 60, "wallets": ["W"], "wallets_supplied": True},
        state={"phase2": {"W": {"address": "W", "dropped": False, "in_window_tx_count": 900}}},
    )
    assert estimates["W"] >= 2
    dense = estimate_phase3_pages(
        {"window_days": 30, "earlier_history_days": 60, "wallets": ["W"], "wallets_supplied": True,
         "bounds": {"earlier_history_days": 300}},
        state={"phase2": {"W": {"address": "W", "dropped": False, "in_window_tx_count": 1000}}},
    )
    assert dense["W"] > 2


def test_fifo_undecoded_taint_still_holds():
    rows = [
        {"kind": "undecoded_buy", "units": "100", "mint": "M", "signature": "u1",
         "seconds_from_start": 0, "timestamp_missing": False,
         "settlement_mint": "So11111111111111111111111111111111111111112"},
        {"kind": "sell", "units": "40", "mint": "M", "signature": "s1", "consideration_sol": "2",
         "seconds_from_start": 2, "timestamp_missing": False,
         "settlement_mint": "So11111111111111111111111111111111111111112"},
    ]
    known, unresolved = isolate_known_cost_events(rows)
    assert unresolved
    assert not any(row.get("kind") == "sell" and not row.get("unresolved_basis") for row in known)
