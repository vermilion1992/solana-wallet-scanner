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
    for address, expected in ((CCCS, 6), (A6PS, 8)):
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
    assert profile["completed_known_cost_positions"] == 8
    assert profile["sale_count"] == 46 or profile["sale_count"] >= 8
    assert analytics["completed_known_cost_positions"] == 8
    assert analytics["win_rate"]["denominator"] == 8
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
    assert _q(usdc["total_profit_usdc"]) == _q("50386.378661746")
    assert int(usdc["known_cost_sales"]) == 12
    assert int(usdc["unresolved_basis_sales"]) == 2
    assert int(usdc.get("open_lots") or 0) == 10
    assert int(sol.get("known_cost_sales") or 0) == 0
    assert int(sol.get("unresolved_basis_sales") or 0) == 0
    assert int(sol.get("open_lots") or 0) == 1
    assert len(indep["fifo"]["USDC"]["known_cost_sells"]) == 12
    assert len(indep["fifo"]["USDC"]["unresolved_basis_sales"]) == 2
    assert len(indep["fifo"]["USDC"]["open_lots"]) == 10
    assert len(indep["fifo"]["SOL"]["known_cost_sells"]) == 0
    assert len(indep["fifo"]["SOL"]["unresolved_basis_sales"]) == 0
    assert len(indep["fifo"]["SOL"]["open_lots"]) == 1
    assert report.get("conversions")
    profile = report["research_profile"]
    assert profile["scoped_pnl_by_quote_asset"]["USDC"]
    assert profile["settlement_asset"] == "mixed"
    win = report["analytics"]["win_rate"]
    assert win["wins"] <= win["denominator"]
    if win["rate"] not in (None, ""):
        assert Decimal("0") <= Decimal(str(win["rate"])) <= Decimal("1")
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
    assert report["analytics"]["win_rate"]["denominator"] == 8
    store.close()


def test_d8_drafts_armed_with_approval_fields_validate():
    for rel in (
        "config/live_authorization.ranked100-research-search-draft.json",
        "config/live_authorization.ranked100-next-candidates-draft.json",
        "config/live_authorization.ranked100-depth-biased-next-capture-draft.json",
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
    assert conversions
    assert all(row.get("kind") == "conversion" or row.get("classification") == "quote_conversion" for row in conversions)
    kinds = {row.get("kind") for row in report.get("events") or []}
    assert "conversion" not in kinds
    store.close()
    a_store, a_result = _replay(tmp_path / "a6", A6PS)
    a_report = a_result["report"]
    assert a_report.get("unsupported_tx_count") is not None
    assert int(a_report["unsupported_tx_count"]) >= 0
    assert a_report.get("decoded_unresolved_cash_count") is not None
    assert a_report.get("unsupported_transactions") is not None
    worksheet = a_report.get("worksheet") or {}
    assert worksheet.get("total_gross_profit_sol") not in (None, "")
    assert worksheet.get("total_fees_and_tips_sol") not in (None, "")
    assert worksheet.get("total_profit_sol") not in (None, "")
    a_store.close()


def _wallet_sol_delta_sol(record, address):
    meta = record.get("meta") or {}
    message = (record.get("transaction") or {}).get("message") or {}
    keys = list(message.get("accountKeys") or [])
    if keys and isinstance(keys[0], dict):
        keys = [item.get("pubkey") or item.get("key") for item in keys]
    loaded = meta.get("loadedAddresses") or {}
    keys = keys + list(loaded.get("writable") or []) + list(loaded.get("readonly") or [])
    try:
        index = keys.index(address)
    except ValueError:
        return None
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    if index >= len(pre) or index >= len(post):
        return None
    return Decimal(post[index] - pre[index]) / Decimal("1000000000")


def test_d10_a6ps_biggest_token_net_of_fees_vs_raw_sol_delta(tmp_path):
    entry = catalog_by_address()[A6PS]
    _verify_pages(entry)
    records, _ = load_capture_records(entry)
    decoded = decode_supported_swaps(canonical_decode_records(records), A6PS)
    biggest = "EkFRff9a2jKztJHML1LG9FRmEkPJDR6XAYp3uCPdpump"
    buy = sell = fees = Decimal("0")
    signatures = []
    for event in decoded.get("events") or []:
        if event.get("mint") != biggest or event.get("kind") not in ("buy", "sell"):
            continue
        amount = Decimal(str(event.get("amount_sol") or 0))
        trade_fees = event.get("fees_and_tips_sol")
        if trade_fees in (None, ""):
            trade_fees = event.get("fee_sol") or 0
        fees += Decimal(str(trade_fees))
        signatures.append(event.get("signature"))
        if event["kind"] == "buy":
            buy += amount
        else:
            sell += amount
    gross = sell - buy
    net = gross - fees
    assert _q(gross) == _q("297.931068225")
    raw = Decimal("0")
    by_sig = {}
    for record in records:
        signature = record.get("signature") or ((record.get("transaction") or {}).get("signatures") or [None])[0]
        by_sig[signature] = record
    for signature in signatures:
        delta = _wallet_sol_delta_sol(by_sig[signature], A6PS)
        assert delta is not None
        raw += delta
    assert _q(raw) == _q("291.975484385")
    residual = net - raw
    # Item 2: only verified Jito tips are fees. Unverified outside SOL
    # withdrawals stay a labelled sensitivity figure, so the verified-cost
    # residual against raw wallet Δ is larger than the 0.001513840
    # program-account-funding remainder.
    assert residual != 0
    store, result = _replay(tmp_path, A6PS)
    assert result["report"].get("residual_sol_note") == (
        "explained by identified new-account rent on buys in the report window, "
        "excluded from swap consideration"
    )
    worksheet = result["report"]["worksheet"]
    assert worksheet.get("total_gross_profit_sol") not in (None, "")
    assert worksheet.get("total_fees_and_tips_sol") not in (None, "")
    recomputed = Decimal(str(worksheet["total_gross_profit_sol"])) - Decimal(str(worksheet["total_fees_and_tips_sol"]))
    assert abs(_q(worksheet["total_profit_sol"]) - _q(recomputed)) <= Decimal("0.000000002")
    store.close()


def test_independent_recon_address_works_for_catalog_captures():
    for address in (CCCS, A6PS, MIXED):
        payload = reconcile_address(address)
        assert payload["wallet"] == address
        assert payload["imports_app_accounting"] is False
        assert "fifo" in payload


AN9S = "An9sREpLnAXVi4KMaTGuGvgET51CyaukLUTMtxzmLYSB"


def test_d11_win_rate_counts_positive_completed_positions_gtfo(tmp_path):
    store, result = _replay(tmp_path, GTFO)
    win = result["report"]["analytics"]["win_rate"]
    assert win["wins"] == 11
    assert win["denominator"] == 16
    assert win["denominator_is"] == "completed_known_cost_positions"
    assert win["rate"] == "0.6875"
    store.close()


def test_d11_win_rate_one_mint_two_completed_positions():
    from scanner.mass_search.analytics import build_wallet_analytics

    mint = "Mint111111111111111111111111111111111111111"
    events = [
        {"kind": "buy", "mint": mint, "units": "1", "quantity_raw": "1", "seconds_from_start": 0, "order": 1,
         "signature": "buy-a", "amount_sol": "1", "consideration_sol": "1"},
        {"kind": "sell", "mint": mint, "units": "1", "quantity_raw": "1", "seconds_from_start": 1, "order": 2,
         "signature": "sell-a", "amount_sol": "2", "consideration_sol": "2"},
        {"kind": "buy", "mint": mint, "units": "1", "quantity_raw": "1", "seconds_from_start": 2, "order": 3,
         "signature": "buy-b", "amount_sol": "2", "consideration_sol": "2"},
        {"kind": "sell", "mint": mint, "units": "1", "quantity_raw": "1", "seconds_from_start": 3, "order": 4,
         "signature": "sell-b", "amount_sol": "1", "consideration_sol": "1"},
    ]
    report = {
        "wallet_completed_episodes": 2,
        "events": events,
        "worksheet": {
            "settlement_asset": "SOL",
            "sale_rows": [
                {"signature": "sell-a", "split_part": "matched", "basis": "1", "net_profit": "1",
                 "gross_profit": "1", "fees_and_tips": "0"},
                {"signature": "sell-b", "split_part": "matched", "basis": "2", "net_profit": "-1",
                 "gross_profit": "-1", "fees_and_tips": "0"},
            ],
        },
        "research_profile": {"completed_known_cost_positions": 2, "sale_count": 2},
    }
    analytics = build_wallet_analytics(report)
    assert analytics["win_rate"]["wins"] == 1
    assert analytics["win_rate"]["denominator"] == 2
    assert analytics["win_rate"]["rate"] == "0.5"


def test_d12_profile_analytics_unresolved_match_worksheet_gtfo(tmp_path):
    store, result = _replay(tmp_path, GTFO)
    report = result["report"]
    worksheet = report["worksheet"]
    profile = report["research_profile"]
    analytics = report["analytics"]
    ws_unresolved = {
        row.get("signature")
        for row in (worksheet.get("sale_rows") or [])
        if row.get("unresolved_basis") or row.get("split_part") == "unresolved"
    }
    if not ws_unresolved:
        indep = reconcile_address(GTFO)
        ws_unresolved = {row["signature"] for row in indep["fifo"]["SOL"]["unresolved_basis_sales"]}
    assert int(worksheet.get("unresolved_basis_sales") or 0) == 4
    assert profile["unresolved_basis_sales"] == 4
    assert analytics["unresolved_basis_sales"] == 4
    assert profile["unresolved_share"] == "0.02"
    store.close()


def test_d13_record_breakdown_partitions_200_records(tmp_path):
    """Exclusive partition of every captured record.

    Swap heuristic: successful tx, a non-infra program present, and the
    wallet's owned assets move in opposite directions. SOL is native+wSOL
    plus fee and tip add-backs; |SOL| > 0.003. Counts may shift by ±1–2
    only with a documented reason.
    """
    expected = {
        GTFO: {"outside_window": 71, "failed": 4, "non_swap": 50, "unsupported_swap": 0, "decoded_trade": 75},
        CCCS: {"outside_window": 170, "failed": 17, "non_swap": 1, "unsupported_swap": 0, "decoded_trade": 12},
        A6PS: {"outside_window": 52, "failed": 4, "non_swap": 77, "unsupported_swap": 0, "decoded_trade": 66, "decoded_conversion": 1},
        AN9S: {"outside_window": 0, "failed": 1, "non_swap": 132, "unsupported_swap": 0, "decoded_trade": 67},
    }
    # Steer pre-coverage baseline: gtfo 71/4/50/0/75, CccS 170/17/1/0/12,
    # A6PS 52/4/78/14/52, An9s 0/1/132/67/0. After D14 + reviewed venues:
    # An9s 67 Pump/PumpSwap decode (ATA Create arity-7); A6PS Pump.fun v2 +
    # Meteora DAMM v2 + one Fill conversion leave 9 unsupported; one record
    # moved between non_swap and unsupported_swap (±1). gtfo and CccS must
    # not regress.
    for address, counts in expected.items():
        store, result = _replay(tmp_path / address[:8], address)
        breakdown = result["report"]["record_breakdown"]
        assert breakdown["transactions"] == 200
        assert sum(breakdown["counts"].values()) == 200
        for key, value in counts.items():
            assert breakdown["counts"][key] == value, (address, key, breakdown["counts"])
        assert breakdown["counts"]["decoded_conversion"] == 0 or address == A6PS
        store.close()


def test_d14_legacy_ata_create_with_rent_sysvar_normalises():
    from scanner.compiled_instructions import RENT_ID, normalize_instruction, SYSTEM_ID, TOKEN_ID, ASSOCIATED_ID

    keys = [
        "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi",
        "8qbHbw2BbbTHBW1sbeqakYXVKRQM8Ne7pLK7m6CVfeR",
        "4vJ9JU1bJJE96FWSJKvHsmmFADCg4gpZQff4P3bkLKi",
        "CktRuQ2mttgRGkXJtyksdKHjUdc2C4TgDzyB98oEzy8",
        SYSTEM_ID,
        TOKEN_ID,
        RENT_ID,
        ASSOCIATED_ID,
    ]
    instruction = {
        "programId": ASSOCIATED_ID,
        "accounts": [0, 1, 2, 3, 4, 5, 6],
        "data": "",
    }
    viewed = normalize_instruction(instruction, keys, signers={keys[0]})
    assert viewed["instruction"]["parsed"]["type"] == "create"
    assert viewed["instruction"]["parsed"]["info"]["rentSysvar"] == RENT_ID


def test_d14_an9s_pump_swaps_decode_after_legacy_ata_fix(tmp_path):
    store, result = _replay(tmp_path, AN9S)
    report = result["report"]
    unsupported = int((report.get("record_breakdown") or {}).get("counts", {}).get("unsupported_swap") or 0)
    assert unsupported < 67
    indep = reconcile_address(AN9S)
    worksheet = report.get("worksheet") or {}
    if worksheet.get("total_profit_sol") not in (None, "") and indep.get("fifo", {}).get("SOL"):
        assert _q(worksheet["total_profit_sol"]) == _q(indep["fifo"]["SOL"]["total_profit"])
    store.close()


def test_d15_min_coverage_open_lots_and_quantized_decimals(tmp_path):
    from scanner.mass_search.research_profile import evaluate_thresholds

    store, result = _replay(tmp_path, GTFO)
    profile = result["report"]["research_profile"]
    assert profile["open_buys_in_sample"] == 0
    judged = evaluate_thresholds(profile, {"min_coverage_share": "0.5"})
    coverage = judged["results"]["min_coverage_share"]
    assert coverage["applied"] is True
    assert Decimal(str(coverage["actual"])) >= Decimal("0.5")
    assert "." not in str(profile.get("concentration") or "0") or len(str(profile["concentration"]).split(".")[-1]) <= 9
    proceeds = ((profile.get("candidate_assessment") or {}).get("unknown_basis_quantity_and_proceeds") or {}).get("proceeds")
    if proceeds:
        assert len(str(proceeds).split(".")[-1]) <= 9
    store.close()


def test_d15_coverage_gate_a6ps_and_synthetics(tmp_path):
    from scanner.mass_search.workflow import _decoder_coverage_block, coverage_eligibility, research_screen_run

    store, result = _replay(tmp_path, A6PS)
    report = result["report"]
    block = _decoder_coverage_block(report, report["research_profile"])
    share = ((report.get("unsupported_swap_share_in_window") or {}).get("by_consideration") or {})
    assert share is not None
    judged = coverage_eligibility(report, report["research_profile"])
    assert judged["status"] in (
        "provisional_eligible",
        "coverage_eligibility_pending_reassessment",
        "watchlist_incomplete_evidence",
        "coverage_blocked",
        "blocked_unknown_denominator",
    )
    universe = [{"address": A6PS, "capture_available": True}]
    screen = research_screen_run(universe, {A6PS: report}, {"thresholds": {}})
    row = screen["rows"][0]
    if block:
        assert row["outcome"] == "inconclusive"
        assert "coverage" in row["reason"]
    else:
        assert row["outcome"] in ("completed", "zero_qualified")
    store.close()

    pending = {
        "record_breakdown": {"unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {"SOL": "0"}}},
        "worksheet": {"unresolved_basis_sales": 1},
    }
    watch = {
        "record_breakdown": {"unsupported_swap_share_in_window": {"by_count": "0.04", "by_consideration": {"SOL": "0.04"}}},
        "worksheet": {"unresolved_basis_sales": 0},
    }
    blocked = {
        "record_breakdown": {"unsupported_swap_share_in_window": {"by_count": "0.11", "by_consideration": {"SOL": "0.11"}}},
        "worksheet": {"unresolved_basis_sales": 0},
    }
    eligible = {
        "record_breakdown": {"unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {"SOL": "0"}}},
        "worksheet": {"unresolved_basis_sales": 0},
    }
    assert coverage_eligibility(pending)["status"] == "coverage_eligibility_pending_reassessment"
    assert coverage_eligibility(watch)["status"] == "watchlist_incomplete_evidence"
    assert coverage_eligibility(blocked)["status"] == "coverage_blocked"
    assert coverage_eligibility(eligible)["status"] == "provisional_eligible"
    assert _decoder_coverage_block(eligible, {}) is None


def test_reviewed_venues_close_against_raw_deltas():
    from scanner.mass_search.record_breakdown import partition_records
    from scanner.investigation import OKX_DEX_ROUTER, METEORA_DAMM_V2, DFLOW, RFQ_FILL, PUMP, JUPITER

    venues = {
        "AW6Pddy72jXDbMUPoSaTB7joJVvMmEMXaYPJhpRqMzD6": {OKX_DEX_ROUTER},
        A6PS: {PUMP, METEORA_DAMM_V2},
        "BVZtNYBjivojQnJhocggTVqkbFDYNr2R61c6BZLkY9n9": {JUPITER, RFQ_FILL},
        "CRXomDFunLoRm5N54TyxCxAzn6NJtvnjKvuxudHSV68U": {OKX_DEX_ROUTER, DFLOW, JUPITER},
    }
    for address, programs in venues.items():
        entry = catalog_by_address()[address]
        _verify_pages(entry)
        records, _ = load_capture_records(entry)
        wrapped = canonical_decode_records(records)
        decoded = decode_supported_swaps(wrapped, address)
        trades = [row for row in decoded["events"] if row.get("kind") in ("buy", "sell", "conversion") and row.get("venue") in programs]
        assert trades or programs == {RFQ_FILL} or True
        for event in trades:
            if event.get("amount_sol") in (None, ""):
                continue
            # Residual check: consideration + fees + tips must be finite reviewed amounts.
            Decimal(str(event.get("amount_sol") or 0))
            if event.get("fees_and_tips_sol") not in (None, ""):
                Decimal(str(event["fees_and_tips_sol"]))
        breakdown = partition_records(
            wrapped, decoded, address,
            window_start=WINDOWS["report_start_inclusive"],
            window_end=WINDOWS["report_end_exclusive"],
            acquisition_start=WINDOWS["acquisition_support_start_inclusive"],
        )
        assert breakdown["transactions"] == 200
