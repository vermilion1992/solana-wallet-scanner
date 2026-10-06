"""Working V1 product path: genuine USDC/Jupiter capture, G1 control, adversarial review."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from scanner.investigation import JUPITER, USDC, WSOL, decode_supported_swaps
from scanner.mass_search.canonical_records import (
    canonical_decode_records,
    classify_normalised_records,
    gta_records_from_capture,
)
from scanner.mass_search.funnel_abc import classify_candidate, rank_next_candidates
from scanner.mass_search.g3_reacquire import ALLOWED_WALLET
from scanner.mass_search.history_ingest import replay_cached_history_to_report
from scanner.mass_search.live_g1 import independent_fifo_worksheet, independent_usdc_fifo_worksheet
from scanner.mass_search.research_profile import default_filters, evaluate_thresholds
from scanner.mass_search.settlement import (
    isolate_known_cost_events,
    settlement_aware_worksheet,
    usdc_fifo_worksheet,
)
from scanner.mass_search.workflow import (
    EXPECTED_CAPTURE_SHA,
    acquisition_policy,
    load_ranked_universe,
    replay_captured_wallet,
)
from scanner.storage import Store

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "evidence/mass-wallet-funnel/ranked100-anchored-validation-live/SOURCE_RESPONSE_page0.json"
ROUTE_V2 = ROOT / "tests/fixtures/retained_protocol_funding/jupiter-route-v2.json"
WINDOWS = {
    "report_start_inclusive": "2026-09-05T13:29:27Z",
    "report_end_exclusive": "2026-10-05T13:29:27Z",
    "acquisition_support_start_inclusive": "2026-07-07T13:29:27Z",
}


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "data")
    yield instance
    instance.close()


def _records():
    return gta_records_from_capture(json.loads(CAPTURE.read_text(encoding="utf-8")))


def test_official_route_v2_fixture_is_pinned():
    payload = json.loads(ROUTE_V2.read_text(encoding="utf-8"))
    digest = hashlib.sha256(ROUTE_V2.read_bytes()).hexdigest()
    assert digest == "946a3278be88c29eff98a4167599c607da222e4c24938224f0990631c06ff218"
    assert payload["program"] == JUPITER
    assert payload["instruction"] == "route_v2"
    assert payload["discriminator_hex"] == "bb64facc31c4af14"
    assert payload["authority_index"] == 0
    assert payload["owned_token_account_indexes"] == [1, 2]


def test_genuine_capture_market_trades_are_usdc_not_sol_or_rewards(store):
    assert hashlib.sha256(CAPTURE.read_bytes()).hexdigest() == EXPECTED_CAPTURE_SHA
    records = _records()
    wrapped = canonical_decode_records(records)
    classified = classify_normalised_records(wrapped, ALLOWED_WALLET)
    decoded = decode_supported_swaps(wrapped, ALLOWED_WALLET)
    swaps = [row for row in decoded["events"] if row.get("kind") in ("buy", "sell")]
    assert classified["counts"]["pump_holder_fee_distribution"] == 61
    assert classified["counts"]["reviewed_jupiter_route"] == 6
    assert classified["counts"]["failed_on_chain"] == 19
    assert classified["counts"]["inner_pumpswap_without_reviewed_outer"] == 2
    assert decoded["coverage"]["decoded_swaps"] == 6
    assert len(swaps) == 6
    assert {row["kind"] for row in swaps} == {"buy", "sell"}
    assert all(row["settlement_mint"] == USDC for row in swaps)
    assert all(row["amount_sol"] is None for row in swaps)
    assert all(row["classification"] == "market" for row in swaps)
    assert {row["amount_usdc"] for row in swaps if row["kind"] == "buy"} == {"3000", "2000"}
    result = replay_cached_history_to_report(
        store,
        address=ALLOWED_WALLET,
        records=records,
        window_start=WINDOWS["report_start_inclusive"],
        window_end=WINDOWS["report_end_exclusive"],
        acquisition_start=WINDOWS["acquisition_support_start_inclusive"],
    )
    report = result["report"]
    assert result["visible_report"] is True
    assert report["worksheet"]["total_profit_usdc"] == "376.028087"
    assert report["independent_worksheet"]["total_profit_usdc"] == "376.028087"
    assert report["worksheet"]["total_profit_sol"] is None
    assert report["worksheet_reconciliation"]["status"] == "AGREE"
    assert report["wallet_completed_episodes"] == 1
    assert report["material_exit"]["final_hold_seconds"] == 852
    assert report["material_exit"]["exit_90_seconds"] == 852
    assert report["material_exit"]["method_version"] == "material-exit-v2"
    assert report["research_profile"]["scoped_pnl"] == "376.028087"
    assert report["research_profile"]["completed_known_cost_positions"] == 1
    assert report["research_profile"]["unresolved_basis_sales"] == 1
    assert report["research_profile"]["safe_to_copy"] is False
    assert report["funnel"]["A"]["state"] == "YES"
    assert report["funnel"]["B"]["state"] == "PARTIAL"
    assert report["funnel"]["C"]["state"] == "NOT_EVALUATED"
    assert report["funnel"]["holder_fee_heavy"] is True
    assert report["PRODUCT_READY"] is False
    fees = classified["fee_totals"]
    assert fees["not_pnl"] is True
    assert Decimal(report["worksheet"]["total_profit_usdc"]) != Decimal(fees["fee_sol"])


def test_known_cost_isolates_leading_sell_and_keeps_matching_close():
    rows = [
        {"kind": "sell", "units": "10", "consideration_usdc": "100", "seconds_from_start": 1, "mint": "a", "signature": "s1"},
        {"kind": "buy", "units": "5", "consideration_usdc": "50", "seconds_from_start": 2, "mint": "a", "signature": "s2"},
        {"kind": "sell", "units": "5", "consideration_usdc": "80", "seconds_from_start": 3, "mint": "a", "signature": "s3"},
    ]
    known, unresolved = isolate_known_cost_events(rows)
    assert len(unresolved) == 1
    assert unresolved[0]["signature"] == "s1"
    assert [row["signature"] for row in known] == ["s2", "s3"]
    worksheet = usdc_fifo_worksheet(known)
    assert worksheet["total_profit_usdc"] == "30"
    assert worksheet["sol_fees_not_converted"] is True


def test_usdc_fifo_does_not_put_sol_fees_in_unit_cost():
    rows = [
        {"kind": "buy", "units": "10", "consideration_usdc": "100", "wallet_fee_sol": "1", "seconds_from_start": 1, "mint": "a"},
        {"kind": "sell", "units": "10", "consideration_usdc": "110", "wallet_fee_sol": "1", "seconds_from_start": 2, "mint": "a"},
    ]
    production = usdc_fifo_worksheet(rows)
    independent = independent_usdc_fifo_worksheet(rows)
    assert production["total_profit_usdc"] == "10"
    assert independent["total_profit_usdc"] == "10"
    assert production["total_profit_sol"] is None
    assert independent["sol_fees_not_converted"] is True


def test_mixed_sol_and_usdc_worksheet_is_refused():
    rows = [
        {"kind": "buy", "units": "1", "consideration_sol": "1", "seconds_from_start": 1, "mint": "a", "settlement_mint": WSOL},
        {"kind": "sell", "units": "1", "consideration_usdc": "2", "seconds_from_start": 2, "mint": "a", "settlement_mint": USDC},
    ]
    with pytest.raises(ValueError, match="no FX"):
        settlement_aware_worksheet(rows)


def test_g1_synthetic_oracle_fifo_is_unchanged():
    """Synthetic unit-test oracle only. Not the genuine G1 archive."""
    events = [
        {"kind": "buy", "units": "100", "consideration_sol": "1", "wallet_fee_sol": "0.01"},
        {"kind": "sell", "units": "50", "consideration_sol": "0.8", "wallet_fee_sol": "0.005"},
        {"kind": "sell", "units": "45", "consideration_sol": "0.72", "wallet_fee_sol": "0.005"},
        {"kind": "sell", "units": "5", "consideration_sol": "0.08", "wallet_fee_sol": "0.005"},
    ]
    worksheet = independent_fifo_worksheet(events)
    assert worksheet["oracle"] == "independent-g1-fifo-v1"
    assert worksheet["total_profit_sol"].startswith("0.575")
    assert "fifo_sale_results" not in independent_fifo_worksheet.__globals__


def test_unset_thresholds_do_not_pass():
    profile = {
        "completed_known_cost_positions": 1,
        "scoped_pnl": "376.028087",
        "settlement_asset": "USDC",
        "hold_t90_seconds": 852,
        "concentration": "1",
        "unresolved_share": "0.1",
        "market_vs_rewards": {"ratio_market_to_rewards": "0.1", "holder_fee_share": "0.6"},
    }
    unset = evaluate_thresholds(profile, default_filters()["thresholds"])
    assert unset["criteria_met"] is False
    assert unset["unset"]
    assert all(row["state"] == "UNSET" and row["passed"] is False for row in unset["results"].values())
    passed = evaluate_thresholds(profile, {"min_completed_known_cost": "1", "min_scoped_pnl_usdc": "300"})
    assert passed["results"]["min_completed_known_cost"]["passed"] is True
    assert passed["results"]["min_scoped_pnl_usdc"]["passed"] is True
    assert passed["criteria_met"] is False


def test_funnel_separates_provider_rank_and_points_at_next_shortlist():
    universe = load_ranked_universe()
    assert universe["ranked_count"] == 100
    assert universe["rows"][0]["address"] == ALLOWED_WALLET
    assert universe["rows"][0]["capture_available"] is True
    nxt = rank_next_candidates(universe["rows"], exclude_addresses=[ALLOWED_WALLET], limit=3)
    assert nxt
    assert ALLOWED_WALLET not in {row["address"] for row in nxt}
    assert nxt[0]["trade_count"] >= nxt[-1]["trade_count"]
    unverified = classify_candidate(
        provider_rank=2,
        provider_trade_count=1022,
        provider_score="88.8",
        capture_available=False,
    )
    assert unverified["A"]["state"] == "YES"
    assert unverified["B"]["state"] == "UNVERIFIED"
    assert unverified["C"]["state"] == "NOT_EVALUATED"
    assert unverified["next_action"]["do_not_dispatch"] is True
    policy = acquisition_policy()
    assert policy["enabled_for_live"] is False
    assert policy["do_not_dispatch"] is True


def test_workflow_replay_saves_reopenable_report(store):
    result = replay_captured_wallet(store)
    report = store.get("reports", result["report_id"])
    assert report["address"] == ALLOWED_WALLET
    assert report["worksheet"]["total_profit_usdc"] == "376.028087"
    assert report["funnel"]["next_action"]["code"] == "investigate_better_shortlist_candidates"
    assert report["next_candidates"]
    assert all(row["address"] != ALLOWED_WALLET for row in report["next_candidates"])
    assert result["external_requests"] == 0


def test_independent_reconciliation_does_not_import_app_accounting():
    import ast
    from pathlib import Path
    from decimal import Decimal

    source = Path("tools/independent_capture_reconciliation.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = {
        "scanner.accounting",
        "scanner.mass_search.settlement",
        "scanner.mass_search.live_g1",
        "scanner.mass_search.metrics",
        "scanner.mass_search.service",
    }
    assert forbidden.isdisjoint(imported)
    from tools.independent_capture_reconciliation import reconcile_g1, reconcile_rank1
    rank1 = reconcile_rank1()
    assert rank1["market_trades"] == 6
    assert Decimal(rank1["fifo"]["total_profit"]) == Decimal("376.028087")
    assert len(rank1["fifo"]["unresolved_basis_sales"]) == 1
    assert len(rank1["fifo"]["known_cost_sells"]) == 1
    assert rank1["fifo"]["known_cost_sells"][0]["fee_in_pnl"] is False
    assert len(rank1["fifo"]["open_lots"]) == 3
    g1 = reconcile_g1()
    assert g1["market_trades"] == 5
    assert Decimal(g1["fifo"]["total_profit"]) == Decimal("-0.167725526")


def test_partial_match_sell_splits_and_agrees_with_independent_tool(store):
    from tools.independent_capture_reconciliation import reconcile_synthetic

    fixture = ROOT / "tests/fixtures/synthetic_engineering/partial-match-sell.json"
    app = replay_captured_wallet(store, "SynthEngPARTIAL1111111111111111111111111")
    report = app["report"]
    assert report["corpus_kind"] == "SYNTHETIC"
    assert report["worksheet"]["total_profit_usdc"] == "20"
    assert report["worksheet"]["unresolved_basis_sales"] == 1
    assert report["research_profile"]["unresolved_basis_sales"] == 1
    independent = reconcile_synthetic(fixture)
    assert Decimal(independent["fifo"]["total_profit"]) == Decimal("20")
    assert len(independent["fifo"]["known_cost_sells"]) == 1
    assert Decimal(independent["fifo"]["known_cost_sells"][0]["proceeds"]) == Decimal("120")
    assert Decimal(independent["fifo"]["known_cost_sells"][0]["basis"]) == Decimal("100")
    assert len(independent["fifo"]["unresolved_basis_sales"]) == 1
    assert Decimal(independent["fifo"]["unresolved_basis_sales"][0]["gross_proceeds"]) == Decimal("60")
    assert independent["fifo"]["unresolved_basis_sales"][0]["unmatched_quantity_raw"] == "5"
    assert independent["fifo"]["open_lots"] == []
    assert Decimal(report["worksheet"]["total_profit_usdc"]) == Decimal(independent["fifo"]["total_profit"])


def test_partial_isolate_keeps_inventory_consistent():
    rows = [
        {"kind": "buy", "units": "10", "consideration_usdc": "100", "seconds_from_start": 1, "mint": "a", "signature": "b1"},
        {"kind": "sell", "units": "15", "consideration_usdc": "180", "seconds_from_start": 2, "mint": "a", "signature": "s1"},
    ]
    known, unresolved = isolate_known_cost_events(rows)
    assert [row["signature"] for row in known] == ["b1", "s1"]
    assert Decimal(known[1]["units"]) == Decimal("10")
    assert Decimal(known[1]["consideration_usdc"]) == Decimal("120")
    assert len(unresolved) == 1
    assert Decimal(unresolved[0]["units"]) == Decimal("5")
    assert Decimal(unresolved[0]["consideration_usdc"]) == Decimal("60")
    worksheet = usdc_fifo_worksheet(known)
    assert worksheet["total_profit_usdc"] == "20"
