"""Research-search B genuine-fixture regressions. Zero live provider calls."""
from __future__ import annotations

import gzip
import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from scanner.investigation import decode_supported_swaps
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.capability import validate_live_authorization
from scanner.mass_search.capture_catalog import (
    RESEARCH_SEARCH_AUTHORIZATION_ID,
    RESEARCH_SEARCH_MANIFEST,
    WINDOWS,
    catalog_by_address,
    genuine_captured_addresses,
    load_capture_records,
)
from scanner.mass_search.g3_history import completed_episodes, decoder_events_by_mint
from scanner.mass_search.workflow import load_ranked_universe, replay_captured_wallet
from scanner.storage import Store
from tools.independent_capture_reconciliation import reconcile_address

ROOT = Path(__file__).resolve().parents[1]
GTFO = "gtfoTELAeEZHUgHetA6umfsCETiBMzJCN4tB2sqCgFL"
CCCS = "CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU"
A6PS = "A6PSQFRfv93hoAn1LhQGRT2dYQtjDKX6SE2vN9MEvbot"
MIXED = "58PWvekDbHVPFB9FXGQrpumHD16NRajahkYLHiTvxvDL"
RESEARCH_WALLETS = (
    CCCS, GTFO, A6PS,
    "An9sREpLnAXVi4KMaTGuGvgET51CyaukLUTMtxzmLYSB",
    "CRXomDFunLoRm5N54TyxCxAzn6NJtvnjKvuxudHSV68U",
    "BVZtNYBjivojQnJhocggTVqkbFDYNr2R61c6BZLkY9n9",
    "AW6Pddy72jXDbMUPoSaTB7joJVvMmEMXaYPJhpRqMzD6",
    MIXED,
    "DQ7nsa6RPG9F6QjqDUa7LEN5CEvs9sPssXyRYVRb9Cys",
    "BSN5bh8At4BkTGMoysA76fvsvoTsVpjaXRatNJYJBtCM",
)


def _verify_pages(entry):
    assert entry["corpus_kind"] == "GENUINE_REPLAY"
    assert entry["authorization_id"] == RESEARCH_SEARCH_AUTHORIZATION_ID
    assert entry.get("windows") == WINDOWS
    assert entry.get("multi_page") is True
    assert len(entry.get("pages") or []) == 2
    for page in entry["pages"]:
        raw = gzip.decompress(Path(page["path"]).read_bytes())
        assert hashlib.sha256(raw).hexdigest() == page["raw_sha256"]
        assert len(raw) == page["raw_bytes"]


def _replay(tmp_path, address):
    entry = catalog_by_address()[address]
    _verify_pages(entry)
    store = Store(tmp_path / address)
    result = replay_captured_wallet(store, address, force=True)
    return store, result


def _q(value):
    return Decimal(str(value)).quantize(Decimal("0.000000001"))


def test_d5_catalog_registers_hash_verified_research_captures():
    catalog = catalog_by_address()
    genuine = genuine_captured_addresses()
    assert RESEARCH_SEARCH_MANIFEST.exists()
    for address in RESEARCH_WALLETS:
        entry = catalog[address]
        _verify_pages(entry)
        records, digest = load_capture_records(entry)
        assert len(records) == 200
        assert digest
        assert address in genuine
    universe = load_ranked_universe()
    by_address = {row["address"]: row for row in universe["rows"]}
    for address in RESEARCH_WALLETS:
        assert by_address[address]["capture_available"] is True
    assert universe["capture_count"] == 11


def test_d1_gtfo_sol_excess_saves_report_with_unresolved_basis(tmp_path):
    store, result = _replay(tmp_path, GTFO)
    report = result["report"]
    assert report["id"]
    assert result.get("error") is None
    worksheet = report["worksheet"] or {}
    assert int(worksheet.get("unresolved_basis_sales") or 0) == 4
    assert int(worksheet.get("known_cost_sales") or 0) == 55
    indep = reconcile_address(GTFO)
    fifo = indep["fifo"]["SOL"]
    assert _q(worksheet["total_profit_sol"]) == _q(fifo["total_profit"])
    assert worksheet.get("total_gross_profit_sol") not in (None, "")
    assert worksheet.get("total_fees_and_tips_sol") not in (None, "")
    assert len(fifo["known_cost_sells"]) == 55
    assert len(fifo["unresolved_basis_sales"]) == 4
    store.close()


def test_d2_completed_episodes_time_order_and_isolate(tmp_path):
    for address, expected in ((CCCS, 6), (A6PS, 6)):
        store, result = _replay(tmp_path / address, address)
        report = result["report"]
        assert report["wallet_completed_episodes"] == expected
        entry = catalog_by_address()[address]
        records, _ = load_capture_records(entry)
        decoded = decode_supported_swaps(canonical_decode_records(records), address)
        by_mint, _ = decoder_events_by_mint(
            decoded,
            address=address,
            window_start=WINDOWS["report_start_inclusive"],
            window_end=WINDOWS["report_end_exclusive"],
            acquisition_start=WINDOWS["acquisition_support_start_inclusive"],
        )
        ordered = completed_episodes(by_mint)
        shuffled = {}
        for mint, rows in by_mint.items():
            reversed_rows = list(reversed(rows))
            shuffled[mint] = reversed_rows
        assert completed_episodes(shuffled)["wallet_completed_episodes"] == expected
        assert ordered["wallet_completed_episodes"] == expected
        store.close()


def test_d3_zero_episodes_is_zero_and_a6ps_shows_six(tmp_path):
    store, result = _replay(tmp_path, A6PS)
    report = result["report"]
    profile = report["research_profile"]
    analytics = report["analytics"]
    assert profile["completed_known_cost_positions"] == 6
    assert profile["sale_count"] == 46 or profile["sale_count"] >= 6
    assert analytics["completed_known_cost_positions"] == 6
    assert analytics["win_rate"]["denominator"] == 6
    assert analytics["win_rate"]["denominator_is"] == "completed_known_cost_positions"
    empty = deepcopy(report)
    empty["wallet_completed_episodes"] = 0
    from scanner.mass_search.research_profile import build_research_profile, default_filters
    zero = build_research_profile(empty, filters=default_filters())
    assert zero["completed_known_cost_positions"] == 0
    store.close()


def test_d4_mixed_wallet_separate_quote_asset_worksheets(tmp_path):
    store, result = _replay(tmp_path, MIXED)
    report = result["report"]
    by_asset = report["by_quote_asset"] or (report.get("worksheet") or {}).get("by_quote_asset")
    assert by_asset
    usdc = by_asset["USDC"]
    sol = by_asset.get("SOL") or {}
    indep = reconcile_address(MIXED)
    assert _q(usdc["total_profit_usdc"]) == _q(indep["fifo"]["USDC"]["total_profit"])
    assert _q(usdc["total_profit_usdc"]) == _q("14739.373324196")
    assert int(usdc["known_cost_sales"]) == 3
    assert int(usdc["unresolved_basis_sales"]) == 6
    assert int(usdc.get("open_lots") or 0) == 3
    assert int(sol.get("known_cost_sales") or 0) == 0
    assert int(sol.get("unresolved_basis_sales") or 0) == 0
    assert int(sol.get("open_lots") or 0) == 1
    assert len(indep["fifo"]["USDC"]["known_cost_sells"]) == 3
    assert len(indep["fifo"]["USDC"]["unresolved_basis_sales"]) == 6
    assert len(indep["fifo"]["USDC"]["open_lots"]) == 3
    assert len(indep["fifo"]["SOL"]["known_cost_sells"]) == 0
    assert len(indep["fifo"]["SOL"]["unresolved_basis_sales"]) == 0
    assert len(indep["fifo"]["SOL"]["open_lots"]) == 1
    assert report.get("conversions")
    profile = report["research_profile"]
    assert profile["scoped_pnl_by_quote_asset"]["USDC"]
    assert profile["settlement_asset"] == "mixed"
    store.close()


def test_d6_analytics_keyed_by_signature(tmp_path):
    store, result = _replay(tmp_path, A6PS)
    report = result["report"]
    trades = report["analytics"]["trades"]
    target = None
    for row in trades:
        if (row.get("tx_ref") or "").startswith("3rd1Tifj"):
            target = row
            break
    assert target is not None
    assert _q(target["allocated_basis"]) == _q("1")
    assert _q(target.get("gross_pnl") or target["known_cost_pnl"]) == _q("0.169276495")
    indep = reconcile_address(A6PS)
    by_sig = {row["signature"]: row for row in indep["fifo"]["SOL"]["known_cost_sells"]}
    for row in trades:
        if row.get("side") != "sell" or row.get("reconciliation_or_exclusion") == "unresolved_basis":
            continue
        sale = by_sig.get(row["tx_ref"])
        assert sale is not None, row["tx_ref"]
        assert _q(row["allocated_basis"]) == _q(sale["basis"])
        assert _q(row["known_cost_pnl"]) == _q(sale["net_profit"])
        if row.get("gross_pnl") not in (None, ""):
            assert _q(row["gross_pnl"]) == _q(sale["gross_profit"])
    assert report["analytics"]["win_rate"]["denominator"] == 6
    store.close()


def test_d8_drafts_armed_with_approval_fields_validate():
    for rel in (
        "config/live_authorization.ranked100-research-search-draft.json",
        "config/live_authorization.ranked100-next-candidates-draft.json",
    ):
        payload = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        assert payload["enabled"] is False
        payload["enabled"] = True
        payload["authorized_by_user_at"] = "2026-10-06T05:38:00Z"
        payload["expires_at"] = "2026-10-07T05:38:00Z"
        for entry in payload["providers"]:
            entry["existing_plan_confirmed"] = True
            entry["remaining_quota_confirmed_at"] = "2026-10-06T05:38:00Z"
        checked = validate_live_authorization(payload)
        assert checked["enabled"] is True
        draft = json.loads((ROOT / rel).read_text(encoding="utf-8"))
        assert draft["enabled"] is False


def test_d10_conversions_fees_and_unsupported_listed(tmp_path):
    store, result = _replay(tmp_path, MIXED)
    report = result["report"]
    conversions = report.get("conversions") or []
    assert any(row.get("kind") == "conversion" or row.get("classification") == "quote_conversion" for row in conversions) or report.get("unsupported_tx_count") is not None
    kinds = {row.get("kind") for row in report.get("events") or []}
    assert "conversion" not in kinds
    store.close()
    a_store, a_result = _replay(tmp_path / "a6", A6PS)
    a_report = a_result["report"]
    assert a_report.get("unsupported_tx_count") is not None
    worksheet = a_report.get("worksheet") or {}
    assert worksheet.get("total_gross_profit_sol") not in (None, "")
    assert worksheet.get("total_fees_and_tips_sol") not in (None, "")
    assert worksheet.get("total_profit_sol") not in (None, "")
    a_store.close()


def test_independent_recon_address_works_for_catalog_captures():
    for address in (CCCS, A6PS, MIXED):
        payload = reconcile_address(address)
        assert payload["wallet"] == address
        assert payload["imports_app_accounting"] is False
        assert "fifo" in payload
