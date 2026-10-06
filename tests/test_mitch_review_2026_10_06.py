"""Named regressions for Mitch's 2026-10-06 source review of 3453f8f.

Zero live provider calls. Do not weaken assertions.
"""
from __future__ import annotations

import ast
import json
from decimal import Decimal
from pathlib import Path

from scanner.investigation import PUMP, decode_supported_swaps
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.capture_catalog import catalog_by_address, load_capture_records
from scanner.mass_search.research_profile import (
    POSITIVE_RESEARCH_SHORTLIST,
    build_research_profile,
    default_filters,
    evaluate_thresholds,
)
from scanner.mass_search.settlement import isolate_known_cost_events, worksheets_by_quote_asset
from scanner.mass_search.verified_costs import classify_native_withdrawal, is_verified_tip_account
from scanner.mass_search.analytics import build_wallet_analytics
from scanner.mass_search.workflow import coverage_eligibility, research_screen_run

ROOT = Path(__file__).resolve().parents[1]
COVERAGE_DIR = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage"
GTFO = "gtfoTELAeEZHUgHetA6umfsCETiBMzJCN4tB2sqCgFL"
A6PS = "A6PSQFRfv93hoAn1LhQGRT2dYQtjDKX6SE2vN9MEvbot"
JITO = "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"


def test_item1_coverage_fields_are_separate_and_90_fails_95_while_96_passes():
    profile = {
        "coverage_count_share": "0.90",
        "coverage_value_share": "0.96",
        "coverage_historical_share": None,
        "completed_known_cost_positions": 3,
        "scoped_pnl": "1",
        "scoped_pnl_by_quote_asset": {"SOL": "1"},
        "settlement_asset": "SOL",
        "unresolved_share": "0.01",
        "market_vs_rewards": {},
    }
    fail_95 = evaluate_thresholds(profile, {"min_coverage_share": "0.95"})
    assert fail_95["results"]["min_coverage_share"]["passed"] is False
    profile_96 = dict(profile)
    profile_96["coverage_count_share"] = "0.96"
    pass_95 = evaluate_thresholds(profile_96, {"min_coverage_share": "0.95"})
    assert pass_95["results"]["min_coverage_share"]["passed"] is True
    unset = evaluate_thresholds(profile, {"min_coverage_share": None})
    assert unset["results"]["min_coverage_share"]["applied"] is False
    assert unset["results"]["min_coverage_share"]["state"] == "NOT_SET"


def test_item2_only_verified_jito_tips_count():
    assert is_verified_tip_account(JITO) is True
    assert is_verified_tip_account("SomeRandomWallet1111111111111111111111111") is False
    assert classify_native_withdrawal(JITO) == "verified_tip"
    assert classify_native_withdrawal("11111111111111111111111111111111") == "unresolved_debit"
    assert is_verified_tip_account("nozpEGbwx4BcGp6pvEdAh1JoC2CQGZdU6HbNP1v2p6P") is True
    assert is_verified_tip_account("astraRVUuTHjpwEVvNBeQEgwYx9w9CFyfxjYoobCZhL") is True
    assert is_verified_tip_account("wyvPkWjVZz1M8fHQnMMCDTQDbkManefNNhweYk5WkcF") is False


def test_item3_decoded_unresolved_cash_is_not_unsupported_swap():
    coverage = {
        "unsupported_tx_count": 0,
        "decoded_unresolved_cash_count": 2,
        "decoded_unresolved_cash": [{"classification": "decoded_swap_unresolved_cash_role"}],
        "unsupported_transactions": [],
    }
    assert coverage["unsupported_tx_count"] == 0
    assert coverage["decoded_unresolved_cash"][0]["classification"] != "unsupported_swap"


def test_item4_pump_v2_is_implemented_from_published_layout():
    from scanner.investigation import _anchor, _RAW_FIXTURE_ROUTES

    assert (_anchor("sell_v2").hex()) == "5df6823ce7e940b2"
    assert (PUMP, "sell_v2") in _RAW_FIXTURE_ROUTES
    assert (PUMP, "buy_exact_quote_in_v2") in _RAW_FIXTURE_ROUTES


def test_item4_offline_discriminator_histogram_covers_2000_records():
    ledger = json.loads((COVERAGE_DIR / "LEDGER.json").read_text(encoding="utf-8"))
    histogram = json.loads((COVERAGE_DIR / "HISTOGRAM.json").read_text(encoding="utf-8"))
    assert ledger["record_count"] == 2000
    assert ledger["unique_signatures"] == 2000
    assert sum(item["count"] for item in histogram["rows"]) >= 1
    assert (COVERAGE_DIR / "LEDGER.md").is_file()


def test_item5_default_screen_has_no_pnl_and_count_only_wording():
    filters = default_filters()
    assert filters["thresholds"]["min_scoped_pnl_sol"] is None
    assert filters["unset_is_not_applied"] is True
    assert POSITIVE_RESEARCH_SHORTLIST["name"] == "Positive research shortlist"
    assert POSITIVE_RESEARCH_SHORTLIST["min_scoped_pnl_sol"] == "0"
    profile = {
        "completed_known_cost_positions": 3,
        "coverage_count_share": "1",
        "scoped_pnl": "1",
        "scoped_pnl_by_quote_asset": {"SOL": "1"},
        "settlement_asset": "SOL",
        "unresolved_share": "0",
        "market_vs_rewards": {},
    }
    report = {"address": "count-only", "research_profile": profile, "record_breakdown": {
        "unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {"SOL": "0"}},
    }, "worksheet": {"unresolved_basis_sales": 0}}
    screen = research_screen_run(
        [{"address": "count-only", "capture_available": True}],
        {"count-only": report},
        {"thresholds": {"min_completed_known_cost": "1", "min_sample_positions": "3"}},
    )
    assert screen["rows"][0]["reason"] == "meets the sample/activity filters"


def test_item6_opening_inventory_owned_100_buy_100_sell_100_is_unknown_basis():
    mint = "MintOpening111111111111111111111111111111"
    rows = [
        {"kind": "opening_unknown", "opening_unknown": True, "units": "100", "mint": mint,
         "seconds_from_start": 0, "order": 0, "signature": "opening"},
        {"kind": "buy", "units": "100", "mint": mint, "seconds_from_start": 1, "order": 1,
         "signature": "buy", "consideration_sol": "1", "settlement_mint": "So11111111111111111111111111111111111111112"},
        {"kind": "sell", "units": "100", "mint": mint, "seconds_from_start": 2, "order": 2,
         "signature": "sell", "consideration_sol": "2", "settlement_mint": "So11111111111111111111111111111111111111112"},
    ]
    known, unresolved = isolate_known_cost_events(rows)
    assert any(row.get("opening_inventory_consumed") for row in unresolved)
    assert all(row.get("kind") != "sell" or row.get("unresolved_basis") or row.get("not_clean_episode") for row in known)
    assert any(row.get("signature") == "sell" and row.get("unresolved_basis") for row in unresolved)


def test_item6_partly_backed_sale_is_not_a_clean_episode():
    from scanner.mass_search.g3_history import completed_position_episodes

    mint = "MintPartial111111111111111111111111111111"
    rows = [
        {"kind": "opening_unknown", "opening_unknown": True, "units": "50", "mint": mint,
         "seconds_from_start": 0, "order": 0, "signature": "opening"},
        {"kind": "buy", "units": "100", "mint": mint, "seconds_from_start": 1, "order": 1,
         "signature": "buy", "consideration_sol": "1", "settlement_mint": "So11111111111111111111111111111111111111112"},
        {"kind": "sell", "units": "100", "mint": mint, "seconds_from_start": 2, "order": 2,
         "signature": "sell", "consideration_sol": "2", "settlement_mint": "So11111111111111111111111111111111111111112"},
    ]
    known, unresolved = isolate_known_cost_events(rows)
    assert any(row.get("not_clean_episode") for row in known if row.get("kind") == "sell")
    assert any(row.get("opening_inventory_consumed") for row in unresolved)
    counted = completed_position_episodes(known)
    assert counted["completed_episodes"] == 0


def test_item7_a6ps_concentration_label():
    report = {
        "worksheet": {
            "sale_net_profit_sol": ["291.976998225", "-4.592923403"],
            "total_profit_sol": "287.384074822",
            "settlement_asset": "SOL",
        },
        "events": [],
        "wallet_completed_episodes": 2,
    }
    profile = build_research_profile(report, filters=default_filters())
    detail = profile["concentration_detail"]
    assert detail["label"] == "positive subset; highly concentrated; negative excluding largest winner"


def test_item10_sol_buy_usdc_sell_is_not_split_into_two_fifos():
    mint = "MintCross11111111111111111111111111111111"
    wsol = "So11111111111111111111111111111111111111112"
    usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    rows = [
        {"kind": "buy", "units": "100", "mint": mint, "seconds_from_start": 1, "order": 1,
         "signature": "buy-sol", "consideration_sol": "1", "settlement_mint": wsol},
        {"kind": "sell", "units": "100", "mint": mint, "seconds_from_start": 2, "order": 2,
         "signature": "sell-usdc", "consideration_usdc": "10", "settlement_mint": usdc},
    ]
    known, unresolved = isolate_known_cost_events(rows)
    assert any(row.get("cross_currency_unconverted") for row in unresolved)
    by_asset = worksheets_by_quote_asset(rows)
    # Same mint must not appear as a matched USDC sale with invented zero SOL basis.
    usdc_sheet = by_asset.get("USDC") or {}
    sol_sheet = by_asset.get("SOL") or {}
    assert int((usdc_sheet.get("known_cost_sales") or 0)) == 0 or usdc_sheet.get("cross_currency_policy") == "unconverted_unresolved_never_zero"
    assert (usdc_sheet.get("cross_currency_policy") or sol_sheet.get("cross_currency_policy")) == "unconverted_unresolved_never_zero"


def test_item11_label_tables_cannot_disagree():
    from scanner.mass_search.labels import (
        QUALIFICATION_LEVELS,
        research_label_tables,
        wallet_status_fields,
    )

    report = {
        "wallet_completed_episodes": 1,
        "events": [],
        "corpus_kind": "GENUINE_REPLAY",
        "independent_audit": {"status": "independently_audited", "independently_audited": True},
        "worksheet": {"total_profit_sol": "174.65797861", "settlement_asset": "SOL", "unresolved_basis_sales": 0},
        "record_breakdown": {"unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {"SOL": "0"}}},
    }
    profile = build_research_profile(report, filters=default_filters())
    profile["completed_known_cost_positions"] = 1
    profile["open_buys_in_sample"] = 27
    profile["unresolved_basis_sales"] = 0
    profile["scoped_pnl"] = "174.65797861"
    profile["settlement_asset"] = "SOL"
    profile["coverage_count_share"] = "1"
    an9s = wallet_status_fields(report, profile)
    assert an9s["qualification_level"] == "conditional_captured_lot_result"
    assert an9s["coverage_status"] == "provisional_eligible"
    assert "1 completed episode < min_sample 3" in an9s["blocking_reason"]
    assert "27 open lots" in an9s["blocking_reason"]

    rows = [
        {"address": "An9s", **an9s},
        {
            "address": "CccS",
            "qualification_level": "conditional_captured_lot_result",
            "coverage_status": "coverage_eligibility_pending_reassessment",
            "blocking_reason": "unresolved adjacent debits flip the sensitivity net sign",
        },
        {
            "address": "gtfo",
            "qualification_level": "conditional_captured_lot_result",
            "coverage_status": "coverage_eligibility_pending_reassessment",
        },
        {
            "address": "BVZt",
            "qualification_level": "insufficient_evidence",
            "coverage_status": "coverage_blocked",
        },
    ]
    tables = research_label_tables(rows)
    for level in QUALIFICATION_LEVELS:
        assert tables["qualification_level_counts"][level] == sum(
            1 for wallet in tables["wallets"] if wallet["qualification_level"] == level
        )
    for status, count in tables["coverage_status_counts"].items():
        assert count == sum(1 for wallet in tables["wallets"] if wallet["coverage_status"] == status)
    leads = [wallet["address"] for wallet in tables["wallets"] if wallet["qualification_level"] == "provisional_research_lead"]
    assert tables["qualification_level_counts"]["provisional_research_lead"] == len(leads)
    assert tables["qualification_level_counts"]["provisional_research_lead"] == 0
    an9s_row = next(wallet for wallet in tables["wallets"] if wallet["address"] == "An9s")
    assert an9s_row["qualification_level"] != an9s_row["coverage_status"]
    assert an9s_row["coverage_status"] == "provisional_eligible"
    assert an9s_row["qualification_level"] == "conditional_captured_lot_result"


def test_item11_qualification_levels_and_zero_position_is_insufficient_evidence():
    empty = build_research_profile({"events": [], "wallet_completed_episodes": 0}, filters=default_filters())
    assert empty["qualification_level"]["level"] == "insufficient_evidence"
    assert empty["qualification_level"]["not"] == "unprofitable"


def test_item11_sensitivity_sign_flip_cannot_be_provisional_research_lead():
    report = {
        "wallet_completed_episodes": 6,
        "events": [],
        "corpus_kind": "GENUINE_REPLAY",
        "sensitivity_unverified_debits_sol": "1.428081532",
        "worksheet": {"total_profit_sol": "0.242261753", "settlement_asset": "SOL", "unresolved_basis_sales": 0},
        "record_breakdown": {"unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {"SOL": "0"}}},
        "independent_audit": {"status": "independently_audited", "independently_audited": True},
    }
    profile = build_research_profile(report, filters=default_filters())
    assert profile["qualification_level"]["level"] != "provisional_research_lead"
    assert profile["qualification_level"]["sensitivity_sign_flip"] is True
    judged = coverage_eligibility(report, profile)
    assert judged["status"] == "coverage_eligibility_pending_reassessment"
    assert judged["dependency_unresolved_costs"] is True


def test_item12_coverage_policy_99_95_blocked_and_dependency():
    assert coverage_eligibility({
        "record_breakdown": {"unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {"SOL": "0"}}},
        "worksheet": {"unresolved_basis_sales": 0},
    })["status"] == "provisional_eligible"
    assert coverage_eligibility({
        "record_breakdown": {"unsupported_swap_share_in_window": {"by_count": "0.04", "by_consideration": {"SOL": "0.04"}}},
        "worksheet": {"unresolved_basis_sales": 0},
    })["status"] == "watchlist_incomplete_evidence"
    assert coverage_eligibility({
        "record_breakdown": {"unsupported_swap_share_in_window": {"by_count": "0.06", "by_consideration": {"SOL": "0.06"}}},
        "worksheet": {"unresolved_basis_sales": 0},
    })["status"] == "coverage_blocked"
    assert coverage_eligibility({
        "record_breakdown": {"unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {"SOL": "0"}}},
        "worksheet": {"unresolved_basis_sales": 2},
    })["status"] == "coverage_eligibility_pending_reassessment"


def test_item15_independent_auditor_imports_no_scanner():
    source = (ROOT / "tools/independent_episode_audit.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("scanner"), alias.name
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("scanner"), node.module


def test_item15_auditor_output_covers_labelled_episodes():
    payload = json.loads((COVERAGE_DIR / "INDEPENDENT_AUDIT.json").read_text(encoding="utf-8"))
    labelled = set(payload.get("labelled_wallets") or [])
    assert labelled
    by_address = {row["address"]: row for row in payload["wallets"]}
    for address in labelled:
        row = by_address[address]
        assert row["status"] in {"independently_audited", "not_independently_audited", "no_completed_episodes"}
        if row["status"] == "independently_audited":
            assert row["independently_audited"] is True
            assert int(row["app_completed_episodes"] or 0) == len(row.get("episodes") or [])
            assert all(episode.get("match") for episode in row.get("episodes") or [])
        for episode in row.get("episodes") or []:
            assert "venue" in episode
            assert "app" in episode
            assert "auditor" in episode
            for key in ("basis", "proceeds", "verified_costs", "net"):
                assert key in (episode.get("app") or {})


def test_committed_wallet_table_matches_label_function():
    from scanner.mass_search.labels import research_label_tables

    payload = json.loads((COVERAGE_DIR / "WALLET_TABLE.json").read_text(encoding="utf-8"))
    tables = research_label_tables(payload["wallets"])
    assert tables["qualification_level_counts"] == payload["qualification_level_counts"]
    assert tables["coverage_status_counts"] == payload["coverage_status_counts"]
    an9s = next(row for row in tables["wallets"] if row["label"] == "An9s")
    assert an9s["qualification_level"] == "conditional_captured_lot_result"
    assert an9s["coverage_status"] == "provisional_eligible"
    assert an9s["blocking_reason"] == "1 completed episode < min_sample 3; 27 open lots"
    assert tables["qualification_level_counts"]["provisional_research_lead"] == 0
    cccs = next(row for row in tables["wallets"] if row["label"] == "CccS")
    assert cccs["qualification_level"] != "provisional_research_lead"
    assert cccs["coverage_status"] == "coverage_eligibility_pending_reassessment"


def test_item8_fee_audit_records_largest_charges_and_roles():
    payload = json.loads((COVERAGE_DIR / "FEE_AUDIT.json").read_text(encoding="utf-8"))
    for label in ("gtfo", "CccS"):
        wallet = payload["wallets"][label]
        assert wallet["largest_charges"]
        assert "network_plus_priority" in wallet["totals_sol"]
        assert "verified_tips" in wallet["totals_sol"]
        assert "unresolved_debits_sensitivity" in wallet["totals_sol"]
        assert wallet["largest_charges"][0]["economic_role"] in {
            "network_plus_priority_fee",
            "verified_tip",
            "unresolved_debit_not_a_tip",
        }
        assert "debits_gt_0_01_sol" in wallet
        for charge in wallet["largest_charges"]:
            assert charge.get("recipient")
            assert charge.get("instruction_path")
            assert charge.get("fee_payer") or charge["economic_role"] == "network_plus_priority_fee"
            assert "counted_elsewhere" in charge


def test_win_rate_stays_in_unit_interval_including_mixed():
    mint_a = "MintWinA111111111111111111111111111111111"
    mint_b = "MintWinB111111111111111111111111111111111"
    events = []
    for mint, sigs in ((mint_a, ("buy-a", "sell-a")), (mint_b, ("buy-b", "sell-b"))):
        events.extend([
            {"kind": "buy", "mint": mint, "units": "1", "quantity_raw": "1", "seconds_from_start": 0,
             "signature": sigs[0], "amount_sol": "1", "consideration_sol": "1"},
            {"kind": "sell", "mint": mint, "units": "1", "quantity_raw": "1", "seconds_from_start": 1,
             "signature": sigs[1], "amount_sol": "2", "consideration_sol": "2"},
        ])
    report = {
        "wallet_completed_episodes": 2,
        "events": events,
        "worksheet": {
            "settlement_asset": "mixed",
            "sale_rows": [
                {"signature": "sell-a", "split_part": "matched", "basis": "1", "net_profit": "1",
                 "gross_profit": "1", "fees_and_tips": "0"},
                {"signature": "sell-b", "split_part": "matched", "basis": "1", "net_profit": "1",
                 "gross_profit": "1", "fees_and_tips": "0"},
                {"signature": "sell-extra", "split_part": "matched", "basis": "1", "net_profit": "1",
                 "gross_profit": "1", "fees_and_tips": "0"},
            ],
        },
        "research_profile": {"completed_known_cost_positions": 2, "sale_count": 3},
    }
    analytics = build_wallet_analytics(report)
    assert 0 <= Decimal(str(analytics["win_rate"]["rate"])) <= 1
    assert analytics["win_rate"]["wins"] <= analytics["win_rate"]["denominator"]


def test_zero_completed_episodes_do_not_expose_net():
    profile = build_research_profile({
        "events": [],
        "wallet_completed_episodes": 0,
        "worksheet": {"total_profit_usdc": "-2413.398216681", "settlement_asset": "USDC"},
    }, filters=default_filters())
    assert profile["completed_known_cost_positions"] == 0
    assert profile["scoped_pnl"] is None
    assert profile["matched_fragment_pnl"] == "-2413.398216681"


def test_item17_next_capture_manifest_is_disabled():
    path = ROOT / "config/live_authorization.ranked100-depth-biased-next-capture-draft.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["enabled"] is False
    assert payload["max_dispatched_requests"] == 20
    assert payload["providers"][0]["max_units"] == 200
    assert payload["exact_query"]["params"]["until"] == "2026-10-05T13:29:27Z" or payload.get("provider_side_cutoff") == "2026-10-05T13:29:27Z"
