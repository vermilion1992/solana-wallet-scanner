"""4bbb364 live-run residuals. Offline only; keys must stay unset or dummy."""
from __future__ import annotations

import asyncio
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from scanner.investigation import decode_supported_swaps
from scanner.mass_search.adapters import SourceError
from scanner.mass_search.bundle_detect import detect_bundle_or_distribution
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.live_e2e import (
    AUTHORIZATION_ID_11,
    AUTHORIZATION_ID_12,
    BIRDEYE_DISCOVERY_TOP_TRADERS,
    BIRDEYE_TOP_TRADERS_DEFAULT_SORT,
    BIRDEYE_TOP_TRADERS_SORTS,
    COMMITTED_LEDGER_ABSOLUTE,
    DRAFT_REL_11,
    HARD_CEILINGS,
    PINNED_DRAFT_HASHES,
    _dispatch_helius,
    _verify_saved_page,
    expected_pinned_ledger,
    run_live_e2e,
    seed_counterparties_from_records,
    window_bounds,
)
from scanner.mass_search.live_e2e_ledger import RECEIPT_KIND, put_receipt, verify_receipt_chain
from scanner.mass_search.research_profile import (
    attach_live_independent_audit,
    build_research_profile,
    default_filters,
    evaluate_thresholds,
)
from scanner.storage import Store
from tests.test_live_e2e_spend_safety import (
    FAKE_HELIUS,
    WALLETS,
    _arm_grant,
    _empty_helius,
    _live_kwargs,
    pin_test_ledger,
)
from tools.independent_episode_audit import _fifo

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_F635 = ROOT / "tests/fixtures/live-e2e-f635a45"
FIXTURE_P3 = ROOT / "tests/fixtures/live-e2e-phase3"
JXT = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
JITO_TIP = "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    return pin_test_ledger(tmp_path, monkeypatch)


@pytest.fixture
def fake_keys(monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY", FAKE_HELIUS)
    monkeypatch.setenv("BIRDEYE_API_KEY", "dummy-birdeye-key-4bbb364")
    monkeypatch.delenv("HELIUS_KEY", raising=False)


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_laj_jto_rfq_round_trip_decodes_when_pages_present():
    page = Path(__file__).resolve().parents[1] / "tests/fixtures/live-raw/4bbb364-a/9LajrZcitRMGxjZYLh9LGsQsvjwo7pjnRri8BJTrrqrE/page0.bin"
    assert page.is_file(), f"committed fixture missing: {page}"
    addr = "9LajrZcitRMGxjZYLh9LGsQsvjwo7pjnRri8BJTrrqrE"
    jto = "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL"
    records = (json.loads(page.read_bytes()).get("result") or {}).get("data") or []
    decoded = decode_supported_swaps(canonical_decode_records(records), addr)
    kinds = {row.get("kind") for row in decoded.get("events") or [] if row.get("mint") == jto}
    assert "buy" in kinds
    assert "sell" in kinds


def test_zyps6thf_pump_amm_decodes_as_buy():
    payload = _load(FIXTURE_F635 / "jxt-jito-tip.json")
    decoded = decode_supported_swaps(canonical_decode_records([payload["record"]]), payload["address"])
    buys = [row for row in decoded.get("events") or [] if row.get("kind") == "buy"]
    assert buys, decoded.get("coverage")
    assert any(
        (row.get("signature") or "").startswith("ZyPS6ThF")
        or Decimal(str(row.get("amount_sol") or row.get("consideration_sol") or 0)) >= Decimal("12")
        for row in buys
    )


def test_never_sold_airdrop_is_quarantined_not_wallet_block():
    mint = "SpamMint111111111111111111111111111111111"
    record = {
        "signature": "airdrop",
        "transaction": {
            "signatures": ["airdrop"],
            "message": {"accountKeys": ["W"], "instructions": []},
        },
        "meta": {
            "err": None,
            "preTokenBalances": [],
            "postTokenBalances": [{"owner": "W", "mint": mint, "uiTokenAmount": {"amount": "1000"}}],
            "preBalances": [1],
            "postBalances": [1],
            "fee": 5000,
        },
    }
    detected = detect_bundle_or_distribution([record], "W")
    assert "transfer_in_zero_basis" not in (detected.get("reasons") or [])
    assert mint in (detected.get("quarantined_mints") or [])
    assert mint not in (detected.get("sold_quarantined_mints") or [])
    assert detected.get("excluded") is False


def test_sold_quarantined_mint_is_unresolved_not_profit():
    mint = "GiftedMint11111111111111111111111111111111"
    inflow = {
        "signature": "in",
        "transaction": {"signatures": ["in"], "message": {"accountKeys": ["W", "Other"], "instructions": []}},
        "meta": {
            "err": None,
            "preTokenBalances": [],
            "postTokenBalances": [{"owner": "W", "mint": mint, "uiTokenAmount": {"amount": "10"}}],
            "preBalances": [1, 1],
            "postBalances": [1, 1],
            "fee": 5000,
        },
        "blockTime": 10,
    }
    sale = {
        "signature": "out",
        "transaction": {"signatures": ["out"], "message": {"accountKeys": ["W"], "instructions": []}},
        "meta": {
            "err": None,
            "preTokenBalances": [{"owner": "W", "mint": mint, "uiTokenAmount": {"amount": "10"}}],
            "postTokenBalances": [{"owner": "W", "mint": mint, "uiTokenAmount": {"amount": "0"}}],
            "preBalances": [1],
            "postBalances": [2_000_000_000],
            "fee": 5000,
        },
        "blockTime": 20,
    }
    detected = detect_bundle_or_distribution([inflow, sale], "W")
    assert mint in (detected.get("sold_quarantined_mints") or [])
    report = {
        "address": "W",
        "events": [{
            "kind": "sell", "mint": mint, "quantity_raw": "10", "signature": "out",
            "amount_sol": "2", "timestamp": 20, "seconds_from_start": 20,
        }],
        "worksheet": {"total_profit_sol": "2", "settlement_asset": "SOL"},
        "classification": {"counts": {}, "transactions": 2},
        "coverage": {"decoded_swaps": 1},
        "bundle_or_distribution": detected,
        "completed_episode_ledger": [{
            "mint": mint, "close_signature": "out", "net": "2", "unit": "SOL",
            "basis": "0", "proceeds": "2", "costs": "0",
        }],
    }
    profile = build_research_profile(report, filters=default_filters())
    assert mint in (profile.get("sold_quarantined_mints") or [])
    assert profile["unresolved_basis_sales"] >= 1
    assert not any(item.get("mint") == mint for item in profile.get("completed_episode_ledger") or [])


def test_same_mint_partner_stays_flagged_with_jito_tip():
    payload = _load(FIXTURE_P3 / "bundle-gv3ksnug.json")
    record = payload["record"]
    detected = detect_bundle_or_distribution([record], payload["address"])
    assert "multi_signer_bundle_buy" in (detected.get("reasons") or [])
    # V4 disguise: a same-mint partner that also pays a 0.001 SOL Jito tip.
    keys = []
    message = (record.get("transaction") or {}).get("message") or {}
    for item in message.get("accountKeys") or []:
        keys.append(item if isinstance(item, str) else item.get("pubkey"))
    partner = next((key for key in keys if key != payload["address"] and len(key) > 20), None)
    assert partner
    if JITO_TIP not in keys:
        message.setdefault("accountKeys", []).append(JITO_TIP)
        meta = record.setdefault("meta", {})
        meta.setdefault("preBalances", []).append(0)
        meta.setdefault("postBalances", []).append(1_000_000)
    detected = detect_bundle_or_distribution([record], payload["address"])
    assert "multi_signer_bundle_buy" in (detected.get("reasons") or [])


def test_one_hop_forwarder_flags_controller():
    wallet = "Wallet1111111111111111111111111111111111111"
    hop = "HopAddr111111111111111111111111111111111111"
    controller = "CtrlAddr1111111111111111111111111111111111"
    fund = {
        "signature": "fund-hop",
        "transaction": {
            "signatures": ["fund-hop"],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [wallet, hop],
                "instructions": [],
            },
        },
        "meta": {
            "err": None,
            "preBalances": [5_000_000_000, 0],
            "postBalances": [2_000_000_000, 3_000_000_000],
            "fee": 5000,
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }
    sweep = {
        "signature": "hop-to-ctrl",
        "transaction": {
            "signatures": ["hop-to-ctrl"],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [hop, controller],
                "instructions": [],
            },
        },
        "meta": {
            "err": None,
            "preBalances": [3_000_000_000, 1_000_000_000],
            "postBalances": [0, 4_000_000_000],
            "fee": 5000,
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }
    inbound = {
        "signature": "ctrl-funds",
        "transaction": {
            "signatures": ["ctrl-funds"],
            "message": {
                "header": {"numRequiredSignatures": 1},
                "accountKeys": [controller, wallet],
                "instructions": [],
            },
        },
        "meta": {
            "err": None,
            "preBalances": [10_000_000_000, 0],
            "postBalances": [5_000_000_000, 5_000_000_000],
            "fee": 5000,
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }
    detected = detect_bundle_or_distribution([inbound, fund, sweep], wallet)
    assert "controlled_pair" in (detected.get("reasons") or [])
    expl = detected.get("controlled_pair_explanation") or ""
    assert "co-signs" not in expl
    assert "one-hop" in expl or controller[:8] in expl


def test_dominated_wording_does_not_say_cosigns():
    payload = _load(FIXTURE_F635 / "bst-controlled-pair.json")
    detected = detect_bundle_or_distribution(payload["records"], payload["address"])
    expl = detected.get("controlled_pair_explanation") or ""
    if "controlled_pair" in (detected.get("reasons") or []):
        assert "co-signs" not in expl
        assert "dominates" in expl or "signs funding" in expl


def test_usdc_threshold_fails_sol_only_wallet():
    judged = evaluate_thresholds(
        {
            "completed_known_cost_positions": 18,
            "settlement_asset": "SOL",
            "scoped_pnl": "-182.29",
            "scoped_pnl_by_quote_asset": {"SOL": "-182.29"},
        },
        {"min_scoped_pnl_usdc": "10000"},
    )
    assert judged["results"]["min_scoped_pnl_usdc"]["passed"] is False
    assert judged["results"]["min_scoped_pnl_usdc"]["state"] == "FAIL"
    assert judged["criteria_met"] is False


def test_scoped_pnl_uses_completed_episode_not_worksheet():
    report = {
        "address": "FLTEaaQQ",
        "events": [
            {"kind": "buy", "mint": "M", "quantity_raw": "1", "signature": "b1",
             "amount_usdc": "10", "timestamp": 10, "seconds_from_start": 10, "settlement_asset": "USDC"},
            {"kind": "sell", "mint": "M", "quantity_raw": "1", "signature": "s1",
             "amount_usdc": "73.40", "timestamp": 20, "seconds_from_start": 20, "settlement_asset": "USDC"},
        ],
        "worksheet": {"total_profit_usdc": "52395", "settlement_asset": "USDC"},
        "classification": {"counts": {}, "transactions": 2},
        "coverage": {"decoded_swaps": 2},
        "completed_episode_ledger": [{
            "mint": "M", "close_signature": "s1", "net": "63.40", "unit": "USDC",
            "basis": "10", "proceeds": "73.40", "costs": "0", "timestamp": 20,
        }],
    }
    profile = build_research_profile(report, filters=default_filters())
    assert Decimal(str(profile["scoped_pnl"])) == Decimal("63.40")
    assert Decimal(str(profile["scoped_pnl_by_quote_asset"]["USDC"])) == Decimal("63.40")


def test_mixed_quote_assets_keep_mixed_settlement():
    report = {
        "address": "MixedWallet",
        "events": [],
        "worksheet": {
            "settlement_asset": "mixed",
            "by_quote_asset": {
                "USDC": {"total_profit_usdc": "63.40", "known_cost_sales": 1},
                "SOL": {"total_profit_sol": "0", "known_cost_sales": 0, "open_lots": 1},
            },
        },
        "classification": {"counts": {}, "transactions": 2},
        "coverage": {"decoded_swaps": 2},
        "completed_episode_ledger": [{
            "mint": "M", "close_signature": "s1", "net": "63.40", "unit": "USDC",
            "basis": "10", "proceeds": "73.40", "costs": "0", "timestamp": 20,
        }],
    }
    profile = build_research_profile(report, filters=default_filters())
    assert profile["settlement_asset"] == "mixed"
    assert Decimal(str(profile["scoped_pnl_by_quote_asset"]["USDC"])) == Decimal("63.40")


def test_report_window_days_optional_default_30():
    default = window_bounds(30, 60)
    assert default["report_window_days"] == 30
    long = window_bounds(30, 60, report_window_days=90)
    assert long["report_window_days"] == 90
    assert (long["report_end_unix"] - long["report_start_unix"]) == 90 * 86400
    assert default["window_days"] == 30


def test_auditor_dropped_losers_cannot_certify():
    trades = [
        {
            "mint": "LoseMint111111111111111111111111111111111",
            "kind": "buy",
            "quantity_raw": "10",
            "consideration_sol": "20",
            "fees_and_tips_sol": "0",
            "settlement_asset": "SOL",
            "signature": "buy1",
            "slot": 1,
            "transaction_index": 0,
            "timestamp": 1,
            "observed_pre_quantity_raw": "0",
            "program": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
            "instruction": "buy",
        },
        {
            "mint": "LoseMint111111111111111111111111111111111",
            "kind": "sell",
            "quantity_raw": "10",
            "consideration_sol": "1",
            "fees_and_tips_sol": "0",
            "settlement_asset": "SOL",
            "signature": "sell1",
            "slot": 2,
            "transaction_index": 0,
            "timestamp": 2,
            "observed_pre_quantity_raw": "10",
            "program": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
            "instruction": "sell",
        },
    ]
    episodes, _unresolved, _known, omitted = _fifo(trades)
    assert episodes == []
    assert omitted
    report = {
        "address": "W",
        "window": {"start": "2026-09-07T00:00:00Z", "end": "2026-10-07T00:00:00Z"},
        "events": [],
        "worksheet": {},
        "classification": {"counts": {}, "transactions": 0},
        "coverage": {},
        "completed_episode_ledger": [{
            "mint": "WinMint", "close_signature": "c1", "net": "1", "unit": "SOL",
            "basis": "1", "proceeds": "2", "costs": "0",
        }],
    }
    profile = {
        "completed_episode_ledger": report["completed_episode_ledger"],
        "completed_episode_net": "1",
        "completed_episode_net_unit": "SOL",
        "audit_fingerprint": {"fingerprint": "x" * 64, "accounting_policy_version": "v"},
    }
    audit = attach_live_independent_audit(report, profile, [], "W")
    assert audit["status"] == "not_independently_audited"
    assert audit.get("dropped_losers") or audit.get("reason")


def test_scrubbed_true_cannot_waive_ledger_sha(tmp_path):
    page = tmp_path / "page0.bin"
    original = b'{"jsonrpc":"2.0","result":{"data":[{"sig":"ZyPS6ThF"}],"paginationToken":null}}'
    orig_sha = hashlib.sha256(original).hexdigest()
    tampered = b'{"jsonrpc":"2.0","result":{"data":[],"paginationToken":null}}'
    page.write_bytes(tampered)
    new_sha = hashlib.sha256(tampered).hexdigest()
    page.with_name("page0.bin.integrity.json").write_text(json.dumps({
        "written_sha256": new_sha,
        "original_sha256": orig_sha,
        "scrubbed": True,
    }), encoding="utf-8")
    with pytest.raises(SourceError, match="ledger receipt sha mismatch"):
        _verify_saved_page(page, expected_sha=orig_sha, require_ledger_sha=True)


def test_unreceipted_page_is_refused(tmp_path, fake_keys):
    address = WALLETS[0]
    dest = tmp_path / "out" / "raw" / "phase2" / address
    dest.mkdir(parents=True)
    body = b'{"jsonrpc":"2.0","result":{"data":[{"planted":true}],"paginationToken":null}}'
    (dest / "page0.bin").write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    (dest / "page0.bin.integrity.json").write_text(json.dumps({
        "written_sha256": digest, "original_sha256": digest, "scrubbed": False,
    }), encoding="utf-8")
    store = Store(tmp_path / "store")
    grant = {
        "authorization_id": AUTHORIZATION_ID_11,
        "enabled": True,
        "providers": [{
            "provider_id": "helius",
            "allowed_operations": ["getTransactionsForAddress"],
            "cycle_start": "2026-10-07T00:00:00Z",
            "max_units": 30000,
        }],
    }
    config = {"output_dir": str(tmp_path / "out"), "dry_run": True, "explicit_retry": False}
    state = {"spend": {"helius_requests": 0, "helius_units": 0, "birdeye_requests": 0, "birdeye_units": 0}}

    async def transport(*_args, **_kwargs):
        raise AssertionError("planted page must not dispatch HTTP")

    with pytest.raises(SourceError, match="unreceipted"):
        asyncio.run(_dispatch_helius(
            store, grant, config, state, transport, address,
            {"transactionDetails": "signatures", "limit": 1000},
            phase=2, page_index=0,
        ))
    store.close()


def test_top_traders_books_one_receipt_per_token(tmp_path, fake_keys, monkeypatch):
    calls = []

    async def birdeye(*args, **kwargs):
        calls.append(1)
        body = {"success": True, "data": {"items": [{"address": WALLETS[0]}]}}
        return {"status": 200, "body": body, "fetched_at": "2026-10-07T00:00:00Z", "raw_bytes": b"{}"}

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_birdeye", birdeye)
    tokens = [
        "So11111111111111111111111111111111111111112",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    ]
    grant = _arm_grant(tmp_path, birdeye_req=10, birdeye_units=350)
    result = asyncio.run(run_live_e2e({
        **_live_kwargs(tmp_path, grant, tmp_path / "tt", [], phases="1"),
        "discovery": True,
        "discovery_source": BIRDEYE_DISCOVERY_TOP_TRADERS,
        "birdeye_tokens": tokens,
        "birdeye_sort": "trader_score",
    }))
    assert result["spend"]["birdeye_requests"] == 3
    assert result["spend"]["birdeye_units"] == 105
    assert len(calls) == 3
    from scanner.mass_search.live_e2e import PINNED_LEDGER_REL
    store = Store(Path.home() / PINNED_LEDGER_REL / AUTHORIZATION_ID_12)
    receipts = [row for row in (store.list(RECEIPT_KIND) or []) if row.get("provider") == "birdeye"]
    store.close()
    assert len(receipts) == 3
    assert BIRDEYE_TOP_TRADERS_DEFAULT_SORT in BIRDEYE_TOP_TRADERS_SORTS
    assert "trader_score" not in BIRDEYE_TOP_TRADERS_SORTS


def test_committed_ledger_pin_is_absolute():
    draft = json.loads((ROOT / DRAFT_REL_11).read_text(encoding="utf-8"))
    assert draft["pinned_ledger_home"] == COMMITTED_LEDGER_ABSOLUTE
    assert Path(COMMITTED_LEDGER_ABSOLUTE).is_absolute()
    digest = hashlib.sha256((ROOT / DRAFT_REL_11).read_bytes()).hexdigest()
    assert PINNED_DRAFT_HASHES[AUTHORIZATION_ID_11] == digest
    assert HARD_CEILINGS["helius_units"] == 40000


def test_expected_pinned_ledger_ignores_home(monkeypatch, tmp_path):
    from scanner.mass_search import live_e2e
    monkeypatch.setattr(live_e2e, "PINNED_LEDGER_ABSOLUTE", COMMITTED_LEDGER_ABSOLUTE)
    monkeypatch.setenv("HOME", str(tmp_path / "someone-else"))
    assert live_e2e.expected_pinned_ledger() == Path(COMMITTED_LEDGER_ABSOLUTE)


def test_seed_counterparties_returns_address_dicts():
    exchange = _load(FIXTURE_F635 / "jxt-exchange-fund.json")
    seeds = seed_counterparties_from_records(exchange["records"], exchange["address"])
    assert seeds
    assert all(isinstance(row, dict) and row.get("address") for row in seeds)


def test_receipt_chain_detects_tampered_hash(tmp_path):
    store = Store(tmp_path / "store")
    put_receipt(store, {"authorization_id": AUTHORIZATION_ID_11}, "helius:w:3:0:x", {
        "provider": "helius", "wallet": WALLETS[0], "phase": 3, "page": 0,
        "state": "consumed", "sha256": "a" * 64, "units": 10,
    })
    verify_receipt_chain(store)
    row = store.get(RECEIPT_KIND, "helius:w:3:0:x")
    row["sha256"] = "b" * 64
    store.put(RECEIPT_KIND, "helius:w:3:0:x", row)
    with pytest.raises(ValueError, match="receipt_hash"):
        verify_receipt_chain(store)
    store.close()
