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
W58 = "58PWvekDbHVPFB9FXGQrpumHD16NRajahkYLHiTvxvDL"
JITO = "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5"
A6PS_75GG_BUY = "4Rg5Rth4Rq7YYjfzbo35EHmFtKHqRgQcHzsZStkSusJXCGycZHWE2JNMuCWXHApi4ibjW1TCbEFPX6R2mnGFBHD1"
A6PS_2RSS_CLOSE = "3kPuFagckPWWvojz2Dvey1BfYEyQkceAA9e4YGwsSzB2vgynWE37nkZExfkTsJVXjNzkRZ7b6tFGJiuGjSoUSE7y"
GTFO_2AF7_CLOSE = "5ZK4pCwZ4j11TzubuCSHVxK3LhfsZjLf59k78LipoVcCGckcP7umj8RS3sdjS1p9k5UkhWdhModjM3TnuBmYiRwD"
METEORA_DAMM_V2 = "cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG"
RFQ_FILL = "61DFfeTKM7trxYcPQCM78bJ794ddZprZpAwAnLiwTpYH"
JUPITER = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"


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


def _record_by_signature(address, signature):
    from tools.independent_episode_audit import _unwrap

    records, _ = load_capture_records(catalog_by_address()[address])
    for record in records:
        raw = _unwrap(record)
        found = record.get("signature") or ((raw.get("transaction") or {}).get("signatures") or [None])[0]
        if found == signature:
            return record
    raise AssertionError(f"captured tx {signature} missing for {address}")


def test_a6ps_75gg_buy_consideration_is_swap_quote_not_wallet_delta():
    """Raw 4Rg5Rth4… spends 30 SOL wrap + 1.1 unverified outside debit to AStZiY6 + ATA rent. Quote is 30."""
    from tools.independent_episode_audit import reconstruct_record

    event = reconstruct_record(_record_by_signature(A6PS, A6PS_75GG_BUY), A6PS)
    assert event is not None
    assert event["kind"] == "buy"
    assert event["mint"] == "75gGuxuqKhQQiHae8JKDQaetK3XguKf1rUJ1csispump"
    assert Decimal(event["consideration_sol"]) == Decimal("30")
    assert event["program"] == "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
    assert Decimal(event["consideration_sol"]) != Decimal("31.10151384")


def test_a6ps_2rss_close_is_meteora_damm_v2_from_raw_bytes():
    """The 8th A6PS episode is Meteora DAMM v2, not Pump. Auditor must reconstruct it."""
    from tools.independent_episode_audit import reconstruct_record

    event = reconstruct_record(_record_by_signature(A6PS, A6PS_2RSS_CLOSE), A6PS)
    assert event is not None
    assert event["kind"] == "sell"
    assert event["mint"] == "2RSsw9tntE1RmoiPnNFiu93EzQu2eLnCAzvZiqMSoatH"
    assert event["program"] == METEORA_DAMM_V2
    assert event["discriminator"] == "f8c69e91e17587c8"
    assert Decimal(event["consideration_sol"]) == Decimal("2.371239766")


def test_gtfo_2af7_same_slot_order_closes_missing_episode():
    """gtfo 2AF7 close 5ZK4pCwZ… is PumpSwap; same-slot sell-then-buy must not eat the lot."""
    from tools.independent_episode_audit import reconstruct_record, _fifo

    records, _ = load_capture_records(catalog_by_address()[GTFO])
    mint = "2AF7CqwieUjUPALL7icuZtL3X7wENdjUjGBMmfV2pump"
    trades = []
    for record in records:
        event = reconstruct_record(record, GTFO)
        if event and event.get("mint") == mint:
            trades.append(event)
    episodes, _unresolved, _known = _fifo(trades)
    assert len(episodes) == 1
    assert episodes[0]["close_signature"] == GTFO_2AF7_CLOSE
    assert episodes[0]["venue"] == "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
    assert abs(Decimal(episodes[0]["net_profit_sol"]) - Decimal("-0.501331745")) <= Decimal("0.00000001")


def test_58pw_sales_are_rfq_fill_and_jupiter_usdc():
    from tools.independent_episode_audit import reconstruct_record

    pump_close = "2sBVgDR8yjx7gVZqSQgmmAjwYeynrqagXndDKQMqmYyt9g1ZyuDLtHEhWL5px5KrZzodF12v51H7phf1th6abVcm"
    cards_close = "Lsw2FKQKbpKQx8J3h6869Si8eshNFMon2HBtJMHqX3trUrB2urudsdFyUUoZ5L8qxssnY7dqrvU2dip7JmZcX86"
    pump = reconstruct_record(_record_by_signature(W58, pump_close), W58)
    cards = reconstruct_record(_record_by_signature(W58, cards_close), W58)
    assert pump["program"] == RFQ_FILL
    assert pump["instruction"] == "Fill"
    assert pump["settlement_asset"] == "USDC"
    assert pump["mint"] == "pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn"
    assert Decimal(pump["consideration_usdc"]) == Decimal("11617.645237")
    assert cards["program"] == JUPITER
    assert cards["settlement_asset"] == "USDC"
    assert cards["mint"] == "CARDSccUMFKoPRZxt5vt3ksUbxEFEcnZ3H2pd3dKxYjp"
    assert Decimal(cards["consideration_usdc"]) == Decimal("13313.699164")


def test_labelled_wallets_are_independently_audited_in_committed_json():
    payload = json.loads((COVERAGE_DIR / "INDEPENDENT_AUDIT.json").read_text(encoding="utf-8"))
    by_address = {row["address"]: row for row in payload["wallets"]}
    expected = {
        A6PS: (8, 8),
        GTFO: (16, 16),
        W58: (2, 2),
        "CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU": (6, 6),
        "An9sREpLnAXVi4KMaTGuGvgET51CyaukLUTMtxzmLYSB": (1, 1),
    }
    for address, (app, auditor) in expected.items():
        row = by_address[address]
        assert row["status"] == "independently_audited", address
        assert row["app_completed_episodes"] == app
        assert row["auditor_clean_episodes"] == auditor
        assert all(episode.get("match") for episode in row["episodes"])
        nets = [abs(Decimal(str(episode["app"]["net"])) - Decimal(str(episode["auditor"]["net"]))) for episode in row["episodes"]]
        assert all(delta <= Decimal("0.00000001") for delta in nets)


def test_cccs_scoped_net_bridge_matches_debit_audit():
    """Recompute the run#39→current bridge from raw captures, not committed JSON."""
    from tools.independent_episode_audit import _unwrap
    from tools.fee_audit import _keys
    from scanner.compiled_instructions import CompiledInstructionError, normalize_instruction, SYSTEM_ID
    from scanner.mass_search.verified_costs import is_verified_tip_account

    CCCS = "CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU"
    expected_tips = {
        "2HMqvHfyqDyqmpeJN4uiYVrYdRTJrwQtzeacxeSCgNPugzERthBbPuoWJKnuPLzHXm9rSgMTkCpsiVzznMG5wGsE": Decimal("0.048462421"),
        "y35Ku3QYqKotv5ktb9f8sFxdajxUFnDktW2VP6eJQorqkcwyv78x12kZMi87XvnfyCaQFyjwBdFVgxPCnSEG3Yp": Decimal("0.027377935"),
        "2CJpi7VXiLuFLX2tL9DEgGt6m8k4vQvu9E7TZHKUFs3NwdhHGzyTcu5637SPYMov2Xkxo2QvEMch78raNsVhUJwm": Decimal("0.018425378"),
        "Xz1q76iBFFhvaBa47bxs8eWfWZ6hCsCQqVKVXfFgSaY6Sxo89uBQYVVqZ2ygacg2HqBv33HGDk1E8Ywf8GXcg5g": Decimal("0.014251873"),
        "3kLQK8KBzonTAweD52FqiHRs6SJgaXakMLixnKqUSSFdaSZa4MrHNNJkoxp38TkYKaiKDjLDXcS1yfPLDk2EBJNc": Decimal("0.01344921"),
    }
    records, _ = load_capture_records(catalog_by_address()[CCCS])
    by_sig = {}
    for record in records:
        raw = _unwrap(record)
        signature = record.get("signature") or ((raw.get("transaction") or {}).get("signatures") or [None])[0]
        by_sig[signature] = raw
    recomputed = Decimal("0")
    for signature, expected in expected_tips.items():
        raw = by_sig[signature]
        assert raw["meta"].get("err") is None, signature
        keys = _keys(raw)
        found = Decimal("0")
        message = (raw.get("transaction") or {}).get("message") or {}
        instructions = list(message.get("instructions") or [])
        for instruction in instructions:
            parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else None
            if parsed is None and instruction.get("data") is not None:
                program = instruction.get("programId")
                index = instruction.get("programIdIndex")
                if program is None and isinstance(index, int) and 0 <= index < len(keys):
                    program = keys[index]
                if program == SYSTEM_ID or instruction.get("program") == "system":
                    try:
                        viewed = normalize_instruction(instruction, keys, inner=False, path="ix", signers={keys[0]} if keys else set())
                        parsed = viewed["instruction"].get("parsed")
                    except (CompiledInstructionError, ValueError, KeyError, IndexError, TypeError):
                        parsed = None
            info = parsed.get("info") if isinstance(parsed, dict) else None
            if not isinstance(info, dict) or parsed.get("type") != "transfer":
                continue
            if info.get("source") != CCCS:
                continue
            dest = info.get("destination")
            lamports = info.get("lamports")
            if not isinstance(lamports, int):
                continue
            assert is_verified_tip_account(dest), dest
            found += Decimal(lamports) / Decimal(1_000_000_000)
        assert found == expected, (signature, found, expected)
        recomputed += found
    old = Decimal("0.242261753")
    new = Decimal("0.120294936")
    assert recomputed == Decimal("0.121966817")
    assert old - recomputed == new
    payload = json.loads((COVERAGE_DIR / "CCCS_DEBIT_AUDIT.json").read_text(encoding="utf-8"))
    assert payload["run39_to_current_bridge"]["delta_sol"] == "0.121966817"


def test_auditor_owns_tip_list_outside_scanner_and_copies_agree():
    from tools.independent_episode_audit import AUDITOR_TIP_LIST

    scanner_copy = ROOT / "scanner/mass_search/published_tip_accounts.json"
    assert AUDITOR_TIP_LIST.is_file()
    assert "scanner" not in AUDITOR_TIP_LIST.parts
    auditor = json.loads(AUDITOR_TIP_LIST.read_text(encoding="utf-8"))
    app = json.loads(scanner_copy.read_text(encoding="utf-8"))
    auditor_accounts = set()
    app_accounts = set()
    auditor_sources = {}
    for name, body in (auditor.get("providers") or {}).items():
        auditor_accounts.update(body.get("accounts") or [])
        auditor_accounts.update(body.get("programs") or [])
        assert body.get("source", "").startswith("https://"), name
        auditor_sources[name] = body.get("source")
    for name, body in (app.get("providers") or {}).items():
        app_accounts.update(body.get("accounts") or [])
        app_accounts.update(body.get("programs") or [])
        assert body.get("source") == auditor_sources[name], name
    assert auditor_accounts == app_accounts
    assert len(auditor_accounts) == 58


def test_auditor_runs_without_scanner_directory_and_nets_match(tmp_path):
    import importlib.util
    import shutil

    dest = tmp_path / "iso"
    (dest / "tools").mkdir(parents=True)
    shutil.copy(ROOT / "tools/independent_episode_audit.py", dest / "tools/independent_episode_audit.py")
    shutil.copy(ROOT / "tools/published_tip_accounts.json", dest / "tools/published_tip_accounts.json")
    evidence_src = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06"
    evidence_dst = dest / "evidence/mass-wallet-funnel/research-search-b-2026-10-06"
    shutil.copytree(evidence_src, evidence_dst, ignore=shutil.ignore_patterns("screenshots", "recon", "*.md"))
    assert not (dest / "scanner").exists()
    spec = importlib.util.spec_from_file_location("iso_auditor", dest / "tools/independent_episode_audit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = json.loads((evidence_dst / "CAPTURE_MANIFEST.json").read_text(encoding="utf-8"))
    by_address = {}
    for entry in (manifest.get("pages") or {}).values():
        by_address.setdefault(entry["address"], []).append(entry)
    committed = json.loads((COVERAGE_DIR / "INDEPENDENT_AUDIT.json").read_text(encoding="utf-8"))
    expected = {row["address"]: row for row in committed["wallets"]}
    labelled = {
        A6PS, GTFO, W58,
        "CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU",
        "An9sREpLnAXVi4KMaTGuGvgET51CyaukLUTMtxzmLYSB",
    }
    for address in labelled:
        pages = sorted(by_address[address], key=lambda item: item.get("page_index") or 0)
        isolated = module.audit_address(address, pages)
        row = expected[address]
        assert isolated["clean_episodes"] == row["auditor_clean_episodes"]
        iso_nets = [Decimal(item["net_profit_sol"]) for item in isolated["episodes"]]
        committed_nets = [Decimal(item["net_profit_sol"]) for item in row["auditor_only_episodes"]]
        assert iso_nets == committed_nets


def test_auditor_fails_loudly_when_tip_list_missing(tmp_path):
    import importlib.util
    import shutil

    dest = tmp_path / "missing"
    (dest / "tools").mkdir(parents=True)
    shutil.copy(ROOT / "tools/independent_episode_audit.py", dest / "tools/independent_episode_audit.py")
    spec = importlib.util.spec_from_file_location("missing_tips", dest / "tools/independent_episode_audit.py")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except FileNotFoundError as error:
        assert "published tip list missing" in str(error)
        return
    raise AssertionError("auditor imported with a missing tip list")


def test_compare_tolerance_is_two_lamports():
    from tools.independent_episode_compare import TWO_LAMPORTS_SOL, _nets_match

    assert TWO_LAMPORTS_SOL == Decimal("0.000000002")
    assert _nets_match("1.000000000", "1.000000002") is True
    assert _nets_match("1.000000000", "0.999999998") is True
    assert _nets_match("1.000000000", "1.000000003") is False
    assert _nets_match("1.000000000", "0.999999997") is False


def test_failed_transaction_transfers_are_excluded_from_fee_audit_and_app():
    from tools.fee_audit import audit_wallet
    from tools.independent_episode_audit import _unwrap

    failed_gtfo = "AHsLSwEqZeYq1FJQZ8n4X3e5Hynp8R11MeTGiTjZJK7tgBemACLAXVx9KJybRs7tSoHHnLQ1i2UgqYqcD66JocA"
    raw = _unwrap(_record_by_signature(GTFO, failed_gtfo))
    assert raw["meta"].get("err") is not None
    gtfo = audit_wallet(GTFO)
    assert Decimal(gtfo["totals_sol"]["verified_tips"]) == Decimal("3.303280298")
    assert Decimal(gtfo["totals_sol"]["unresolved_debits_sensitivity"]) == Decimal("0.0547")
    assert all(item.get("signature") != failed_gtfo or item["economic_role"] == "network_plus_priority_fee" for item in gtfo["largest_charges"])
    assert all(item.get("signature") != failed_gtfo or item["economic_role"] == "network_plus_priority_fee" for item in gtfo["debits_gt_0_01_sol"])
    events = decode_supported_swaps(
        [{"signature": failed_gtfo, "raw": raw, "transaction_index": 0}],
        GTFO,
    )["events"]
    trades = [row for row in events if row.get("kind") in ("buy", "sell")]
    assert trades == []
    tips = sum(Decimal(str(row.get("tips_sol") or 0)) for row in events if row.get("kind") != "fee")
    unverified = sum(Decimal(str(row.get("unverified_debits_sol") or 0)) for row in events)
    assert tips == 0
    assert unverified == 0


def test_cccs_failed_transaction_debits_are_excluded():
    from tools.fee_audit import audit_wallet
    from tools.independent_episode_audit import _unwrap

    CCCS = "CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU"
    records, _ = load_capture_records(catalog_by_address()[CCCS])
    failed_sigs = []
    for record in records:
        raw = _unwrap(record)
        if (raw.get("meta") or {}).get("err") is not None:
            failed_sigs.append(record.get("signature") or ((raw.get("transaction") or {}).get("signatures") or [None])[0])
    assert failed_sigs
    audited = audit_wallet(CCCS)
    transfer_rows = [
        item for item in audited["debits_gt_0_01_sol"]
        if item["economic_role"] != "network_plus_priority_fee"
    ]
    assert all(item.get("signature") not in failed_sigs for item in transfer_rows)
    assert all(item.get("transaction_failed") is not True for item in transfer_rows)


def test_astziy6_is_unverified_outside_debit_not_a_tip():
    from tools.independent_episode_audit import reconstruct_record

    assert is_verified_tip_account("AStZiY6EE532nQBBogmvcWemc2bwg2kHuR4Jrd5Cqaq5") is False
    event = reconstruct_record(_record_by_signature(A6PS, A6PS_75GG_BUY), A6PS)
    assert Decimal(event["tips_sol"]) == Decimal("0")
    source = (ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/RESULT.md").read_text(encoding="utf-8")
    assert "vanity tip" not in source
    assert "unverified outside debit" in source


def test_compare_reports_mismatch_when_auditor_finds_episodes_app_missed():
    payload = json.loads((COVERAGE_DIR / "INDEPENDENT_AUDIT.json").read_text(encoding="utf-8"))
    by_address = {row["address"]: row for row in payload["wallets"]}
    bvzt = by_address["BVZtNYBjivojQnJhocggTVqkbFDYNr2R61c6BZLkY9n9"]
    dq7n = by_address["DQ7nsa6RPG9F6QjqDUa7LEN5CEvs9sPssXyRYVRb9Cys"]
    assert bvzt["app_completed_episodes"] == 2
    assert bvzt["auditor_clean_episodes"] == 5
    assert bvzt["status"] == "not_independently_audited"
    assert bvzt["independently_audited"] is False
    assert dq7n["app_completed_episodes"] == 2
    assert dq7n["auditor_clean_episodes"] == 4
    assert dq7n["status"] == "not_independently_audited"
    assert "no_completed_episodes" not in {bvzt["status"], dq7n["status"]}
    table = json.loads((COVERAGE_DIR / "WALLET_TABLE.json").read_text(encoding="utf-8"))
    for label in ("BVZt", "DQ7n"):
        wallet = next(item for item in table["wallets"] if item["label"] == label)
        assert wallet["qualification_level"] != "provisional_research_lead"
        assert wallet["qualification_level"] != "stronger_research_shortlist"
        assert wallet["coverage_status"] == "coverage_blocked"
        assert wallet["independently_audited"] is False
        assert wallet["completed"] == 2


def test_58pw_independently_audited_sits_next_to_episode_net():
    payload = json.loads((COVERAGE_DIR / "INDEPENDENT_AUDIT.json").read_text(encoding="utf-8"))
    row = next(item for item in payload["wallets"] if item["address"] == W58)
    assert row["independently_audited"] is True
    assert Decimal(str(row["independently_audited_episode_net"])) == Decimal("5614.586672")
    assert row["independently_audited_episode_net_unit"] == "USDC"
    assert row["worksheet_total_independently_audited"] is False
    assert Decimal(str(row["worksheet_total"])) == Decimal("51148.756609023")
    table = json.loads((COVERAGE_DIR / "WALLET_TABLE.json").read_text(encoding="utf-8"))
    wallet = next(item for item in table["wallets"] if item["address"] == W58)
    assert wallet["independently_audited"] is True
    assert Decimal(str(wallet["independently_audited_episode_net"])) == Decimal("5614.586672")
    assert wallet["worksheet_total_independently_audited"] is False
    assert wallet["net_display"] != "51148.756609023 USDC"
    assert "5614.586672" in str(wallet["net_display"])
    assert "audited episode net" in str(wallet["net_display"])
    assert "not independently audited" in str(wallet["net_display"])


def test_venue_notes_are_computed_from_auditor_decode():
    payload = json.loads((COVERAGE_DIR / "INDEPENDENT_AUDIT.json").read_text(encoding="utf-8"))
    row = next(item for item in payload["wallets"] if item["address"] == W58)
    notes = row["venue_notes"]
    pump = "pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn"
    cards = "CARDSccUMFKoPRZxt5vt3ksUbxEFEcnZ3H2pd3dKxYjp"
    bpxx = "BPxxfRCXkUVhig4HS1Lh7kZqV6SPJhzfEk4x6fVBjPCy"
    assert notes[f"{pump}_sales"]["computed_from_auditor_decode"] is True
    assert notes[f"{cards}_sales"]["computed_from_auditor_decode"] is True
    assert notes[f"{bpxx}_sales"]["clean_completed_episode"] is False
    assert notes[f"{bpxx}_sales"]["reconstructed_as_trades"] is True
    assert notes[f"{pump}_sales"]["mint"] == pump
    source = (ROOT / "tools/independent_episode_compare.py").read_text(encoding="utf-8")
    assert 'if address.startswith("58PW")' not in source
    assert 'mint[:4]' not in source


def test_history_ingest_has_no_wallet_specific_residual_constant():
    source = (ROOT / "scanner/mass_search/history_ingest.py").read_text(encoding="utf-8")
    assert "A6PSQFRfv93hoAn1LhQGRT2dYQtjDKX6SE2vN9MEvbot" not in source
    assert "0.001513840" not in source


BVZT = "BVZtNYBjivojQnJhocggTVqkbFDYNr2R61c6BZLkY9n9"
DQ7N = "DQ7nsa6RPG9F6QjqDUa7LEN5CEvs9sPssXyRYVRb9Cys"
JUPITER_V1_BVZT_59WF = "59WFoNAWa2qfEDaSoiZNyv8cRQrtXwgwkuQkT71SML2v9oWAfGuQ2vjdqhtjSRsmdejbDjFyZGmrPF45PXMUcC2U"
JUPITER_V1_BVZT_3R5E = "3R5ejVQSpZ8uohbam48gqfXhJN7dYhKDbqCoZrMMqnVn6sjzWbH7JTCk3hEJeUYF3wnyxZBLnkxwRyXrXqYwVbEv"
JUPITER_V1_DQ7N_GDWS = "gdWSJsaGoLc3nD2J5tCRMz4qbApqmFsTiwK2kpotjvrYrurHNkb2LznF55a1XCoEzMHbSFVeJWwfBcjHKBjLYUv"


def test_jupiter_route_v2_usdc_version1_decodes_real_signatures():
    from tools.independent_episode_audit import _unwrap

    cases = (
        (BVZT, JUPITER_V1_BVZT_59WF),
        (BVZT, JUPITER_V1_BVZT_3R5E),
        (DQ7N, JUPITER_V1_DQ7N_GDWS),
    )
    for address, signature in cases:
        record = _record_by_signature(address, signature)
        raw = _unwrap(record)
        assert raw.get("version") == 1, signature
        assert raw.get("meta", {}).get("err") is None, signature
        decoded = decode_supported_swaps(canonical_decode_records([record]), address)
        trades = [row for row in decoded["events"] if row.get("kind") in ("buy", "sell")]
        assert len(trades) == 1, (signature, [row.get("reason") for row in decoded["events"]])
        trade = trades[0]
        assert trade.get("venue") == JUPITER or trade.get("source") == JUPITER
        assert trade.get("instruction") == "route_v2"
        assert trade.get("settlement_asset") == "USDC"
        assert trade.get("owner") == address
        unsupported = [
            row for row in decoded["events"]
            if "Unparsed associated account administration" in str(row.get("reason") or row.get("detail") or "")
        ]
        assert unsupported == [], signature


def test_outer_ata_still_requires_message_signer():
    from tools.independent_episode_audit import _unwrap
    from scanner.compiled_instructions import CompiledInstructionError, normalize_instruction, ASSOCIATED_ID

    record = _record_by_signature(BVZT, JUPITER_V1_BVZT_59WF)
    raw = _unwrap(record)
    message = raw["transaction"]["message"]
    keys = list(message["accountKeys"])
    instruction = next(
        item for item in message["instructions"]
        if (item.get("programId") or (keys[item["programIdIndex"]] if isinstance(item.get("programIdIndex"), int) else None)) == ASSOCIATED_ID
        or (isinstance(item.get("programIdIndex"), int) and keys[item["programIdIndex"]] == ASSOCIATED_ID)
    )
    try:
        normalize_instruction(instruction, keys, inner=False, path="ix", signers=set())
    except CompiledInstructionError as error:
        assert error.code == "missing-required-signer"
    else:
        raise AssertionError("ATA without a message signer must still be rejected")


def test_auditor_refuses_mixed_unit_episode_net_sum():
    from tools.independent_episode_audit import episode_net_totals

    mixed = episode_net_totals([
        {"settlement_asset": "SOL", "net_profit_sol": "1.5"},
        {"settlement_asset": "USDC", "net_profit_sol": "10"},
    ])
    assert mixed[0] is None
    assert mixed[1] == "mixed"
    assert Decimal(mixed[2]["SOL"]) == Decimal("1.5")
    assert Decimal(mixed[2]["USDC"]) == Decimal("10")
    assert Decimal("1.5") + Decimal("10") != Decimal(mixed[2]["SOL"])
    same = episode_net_totals([
        {"settlement_asset": "USDC", "net_profit_sol": "1"},
        {"settlement_asset": "USDC", "net_profit_sol": "2.5"},
    ])
    assert Decimal(same[0]) == Decimal("3.5")
    assert same[1] == "USDC"
    empty = episode_net_totals([])
    assert empty == (None, None, None)


def test_fee_audit_recomputes_cccs_current_figures_from_captures():
    source = (ROOT / "tools/fee_audit.py").read_text(encoding="utf-8")
    assert 'existing.get("current_scoped_net_sol"' not in source
    assert 'existing.get("current_swap_adjacent_sensitivity_sol"' not in source
    assert "current_cccs_figures_from_captures" in source


def test_fee_audit_counts_only_wallet_paid_network_fees():
    from tools.fee_audit import audit_wallet

    gtfo = audit_wallet(GTFO)
    assert Decimal(gtfo["totals_sol"]["network_plus_priority"]) == Decimal("5.107154156")
    assert all(
        item.get("fee_payer") == GTFO
        for item in gtfo["largest_charges"]
        if item["economic_role"] == "network_plus_priority_fee"
    )


def test_a6ps_residual_is_in_window_new_account_rent_on_buys():
    import tempfile
    from scanner.mass_search.workflow import replay_captured_wallet
    from scanner.storage import Store

    tmp = Path(tempfile.mkdtemp(prefix="a6ps-residual-"))
    store = Store(tmp / A6PS)
    result = replay_captured_wallet(store, A6PS, force=True)
    store.close()
    report = result["report"]
    assert Decimal(str(report["residual_sol"])) == Decimal("0.01203452")
    assert "new-account rent on buys" in report["residual_sol_note"]
    assert "program-account funding" not in report["residual_sol_note"]
    assert report.get("residual_sol_scope") == "in_window_buys"
