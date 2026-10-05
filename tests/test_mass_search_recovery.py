"""Offline data-integrity recovery: redaction, G1 archive roundtrip, damaged vs unsupported."""
from __future__ import annotations

import gzip
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scanner.app import create_app
from scanner.investigation import decode_supported_swaps
from scanner.mass_search.capability import redact_secrets
from scanner.mass_search.evidence_integrity import (
    SOURCE_RECORDS_DAMAGED,
    classify_records,
    legacy_substring_redact,
    redact_secrets as schema_redact,
    required_token_fields_preserved,
    sanitize_transaction_records,
    structural_redaction_fixture,
    validate_transaction_record,
)
from scanner.mass_search.g3_history import (
    _ordered_inventory_rows,
    completed_episodes,
    completed_position_episodes,
    decoder_events_by_mint,
    fixture_closed_records,
    fixture_decode,
    further_page_allowed,
    load_freeze,
    persist_page,
    run_g3_history,
)
from scanner.mass_search.history_ingest import reconcile_worksheets, replay_cached_history_to_report
from scanner.mass_search.metrics import material_exit_v1
from scanner.mass_search.service import MassSearchService, events_to_accounting
from scanner.mass_search.live_g1 import _wrap_records, independent_fifo_worksheet
from scanner.storage import Store

ROOT = Path(__file__).resolve().parents[1]
G1_ARCHIVE = ROOT / (
    "evidence/mass-wallet-funnel/1bffe2ac21854424aa3fe3b8bf6a22ae/"
    "archives/helius_gta_survivor_desc100.json.gz"
)
G1_ADDRESS = "GatgyE2SqnNNjNeNGR8MG1VSVxFGxgyjB111hYJRTkee"
G1_MINT = "4oPr8EG6qxbYksWt2F3rJ4CqqvpcPrZ4aWg4ByDJpump"
G1_PNL = "-0.167725526"
G1_WINDOW_START = "2026-09-05T12:11:35.382917Z"
G1_WINDOW_END = "2026-10-05T12:11:35.382917Z"
G1_ACQ_START = "2026-06-07T12:11:35.382917Z"
LAUNCH_TOKEN = "test-private-launch-token"
BASE_URL = "http://127.0.0.1:8765"


def load_g1_records():
    body = json.loads(gzip.open(G1_ARCHIVE, "rb").read())
    return list((body.get("result") or {}).get("data") or [])


def g1_mint_events(decoded):
    by_mint, _ = decoder_events_by_mint(
        decoded, address=G1_ADDRESS,
        window_start=G1_WINDOW_START,
        window_end=G1_WINDOW_END,
        acquisition_start=G1_ACQ_START,
    )
    return by_mint.get(G1_MINT) or []


def test_legacy_reproducer_still_destroys_token_fields():
    after = legacy_substring_redact(structural_redaction_fixture())
    instruction = after["meta"]["innerInstructions"][0]["instructions"][0]
    assert after["meta"]["preTokenBalances"] == "[REDACTED]"
    assert after["meta"]["postTokenBalances"] == "[REDACTED]"
    assert after["transaction"]["message"]["accountKeys"][0] == "[REDACTED]"
    assert instruction["programId"] == "[REDACTED]"
    assert instruction["parsed"]["info"]["tokenAmount"] == "[REDACTED]"


def test_schema_aware_redaction_preserves_token_fields_and_protects_credentials():
    fixture = structural_redaction_fixture()
    after = schema_redact(fixture)
    preserved = required_token_fields_preserved(after)
    assert all(preserved.values()), preserved
    assert after["meta"]["api_key"] == "[REDACTED]"
    assert "super-secret-test-value" not in json.dumps(after)
    assert redact_secrets({"X-API-KEY": "abcd1234", "items": [1]})["X-API-KEY"] == "[REDACTED]"
    assert redact_secrets({"authorization_id": "live-g3-ranked100-history-2026-10-06-mitch"})[
        "authorization_id"
    ] == "live-g3-ranked100-history-2026-10-06-mitch"


def test_damaged_balances_are_integrity_failure_not_unsupported():
    damaged = deepcopy(structural_redaction_fixture())
    damaged["meta"]["preTokenBalances"] = "[REDACTED]"
    checked = validate_transaction_record(damaged)
    assert checked["ok"] is False
    assert checked["code"] == SOURCE_RECORDS_DAMAGED
    census = classify_records([damaged, structural_redaction_fixture()])
    assert census["status"] == SOURCE_RECORDS_DAMAGED
    assert census["damaged"] == 1
    assert census["intact"] == 1
    assert census["integrity_failure"] is True
    ok, why = further_page_allowed(
        {"pagination_token": "next"}, 0,
        recorded_reason="insufficient_episodes_pagination_token_present",
        classification=census,
    )
    assert ok is False
    assert why == "corrupted_inputs_do_not_justify_another_page"


def test_partial_exits_are_not_ten_complete_episodes():
    rows = []
    rows.append({
        "kind": "buy", "units": "100", "consideration_sol": "10", "wallet_fee_sol": "0",
        "seconds_from_start": 0, "signature": "b", "mint": "MintA",
        "role": "in_report", "window_qualified": True,
    })
    for index in range(10):
        rows.append({
            "kind": "sell", "units": "9", "consideration_sol": "1", "wallet_fee_sol": "0",
            "seconds_from_start": 10 + index, "signature": f"s{index}", "mint": "MintA",
            "role": "in_report", "window_qualified": True,
        })
    counted = completed_position_episodes(rows)
    assert counted["sale_count"] == 10
    assert counted["completed_episodes"] == 0
    assert counted["open"] is True
    wallet = completed_episodes({"MintA": rows})
    assert wallet["wallet_completed_episodes"] == 0
    assert wallet["wallet_sale_count"] == 10


def test_ten_flat_to_flat_pairs_still_count_as_ten():
    events = fixture_decode(10)([{}] * 20, "addr")
    by_mint, _ = decoder_events_by_mint(
        events, address="addr",
        window_start="2026-09-05T13:29:27Z",
        window_end="2026-10-05T13:29:27Z",
        acquisition_start="2026-07-07T13:29:27Z",
    )
    counted = completed_episodes(by_mint)
    assert counted["wallet_completed_episodes"] == 10
    assert counted["wallet_sale_count"] == 10


def test_missing_timestamp_stays_missing_and_exclusive_end_is_enforced():
    from datetime import datetime, timezone
    start = datetime(2026, 9, 20, tzinfo=timezone.utc).timestamp()
    end = datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp()
    decoded = {"events": [
        {"kind": "buy", "timestamp": None, "quantity_raw": "1", "amount_sol": "1",
         "fee_sol": "0", "mint": "MintA", "signature": "missing"},
        {"kind": "sell", "timestamp": end, "quantity_raw": "1", "amount_sol": "1",
         "fee_sol": "0", "mint": "MintA", "signature": "at-end"},
        {"kind": "buy", "timestamp": start, "quantity_raw": "1", "amount_sol": "1",
         "fee_sol": "0", "mint": "MintA", "signature": "in-window"},
    ]}
    by_mint, _ = decoder_events_by_mint(
        decoded, address="addr",
        window_start="2026-09-20T00:00:00Z",
        window_end="2026-10-10T00:00:00Z",
        acquisition_start="2026-07-07T00:00:00Z",
    )
    rows = by_mint["MintA"]
    missing = [row for row in rows if row["signature"] == "missing"][0]
    assert missing["timestamp_missing"] is True
    assert missing["seconds_from_start"] is None
    assert missing["window_qualified"] is False
    assert all(row["signature"] != "at-end" for row in rows)


def test_g1_archive_survives_sanitize_cache_real_decoder_and_worksheet(tmp_path):
    assert G1_ARCHIVE.is_file()
    records = load_g1_records()
    sanitized = sanitize_transaction_records(records)
    assert sanitized["integrity"]["status"] != SOURCE_RECORDS_DAMAGED
    assert sanitized["integrity"]["intact"] == 100
    assert sanitized["source_body_sha256"] != sanitized["normalized_sha256"]
    store = Store(tmp_path / "data")
    page = {
        "kind": "g3-history-page-v2",
        "address": G1_ADDRESS,
        "page_index": 0,
        "records": sanitized["records"],
        "source_body_sha256": sanitized["source_body_sha256"],
        "normalized_sha256": sanitized["normalized_sha256"],
        "integrity": sanitized["integrity"],
    }
    persist_page(store, "live-g3-ranked100-history-2026-10-06-mitch", G1_ADDRESS, 0, page)
    store.close()
    restarted = Store(tmp_path / "data")
    cached = restarted.get(
        "mass_search_cache",
        f"g3-history-v2:live-g3-ranked100-history-2026-10-06-mitch:{G1_ADDRESS}:page:0",
    )
    assert cached["source_body_sha256"] == sanitized["source_body_sha256"]
    decoded = decode_supported_swaps(_wrap_records(cached["records"]), G1_ADDRESS)
    assert (decoded.get("coverage") or {}).get("decoded_swaps") == 45
    events = _ordered_inventory_rows(g1_mint_events(decoded))
    assert len(events) == 5
    worksheet = independent_fifo_worksheet(events)
    assert Decimal(worksheet["total_profit_sol"]) == Decimal(G1_PNL)
    assert worksheet["oracle"] == "independent-g1-fifo-v1"
    mutated = deepcopy(cached["records"])
    mutated[0]["meta"]["preTokenBalances"] = "[REDACTED]"
    census = classify_records(mutated)
    assert census["status"] == SOURCE_RECORDS_DAMAGED
    assert census["damaged"] >= 1
    destroyed = legacy_substring_redact(records[0])
    assert validate_transaction_record(destroyed)["code"] == SOURCE_RECORDS_DAMAGED
    restarted.close()


def test_g1_archive_saves_retrievable_application_report_offline(tmp_path, monkeypatch):
    records = load_g1_records()
    store = Store(tmp_path / "data")
    saved = replay_cached_history_to_report(
        store,
        address=G1_ADDRESS,
        records=records,
        window_start=G1_WINDOW_START,
        window_end=G1_WINDOW_END,
        acquisition_start=G1_ACQ_START,
        mint=G1_MINT,
        clock=lambda: G1_WINDOW_END,
        corpus_kind="GENUINE_REPLAY",
        source_id="g1-archive-offline-replay",
    )
    assert saved["external_requests"] == 0
    assert saved["report_id"]
    assert saved["visible_report"] is True
    assert Decimal(saved["worksheet"]["total_profit_sol"]) == Decimal(G1_PNL)
    report = store.get("reports", saved["report_id"])
    assert report["address"] == G1_ADDRESS
    assert report["source"] == "mass-search"
    assert report["policy"] == "UNRESOLVED"
    assert report["PRODUCT_READY"] is False
    assert Decimal(report["worksheet"]["total_profit_sol"]) == Decimal(G1_PNL)
    trades = [row for row in report["events"] if row.get("kind") in ("buy", "sell")]
    assert [row["kind"] for row in trades] == ["buy", "buy", "buy", "buy", "sell"]
    assert all(row.get("mint") == G1_MINT for row in trades)
    closed = [row for row in report["positions"] if row.get("status") == "closed"]
    assert len(closed) == 1
    assert closed[0]["mint"] == G1_MINT
    assert closed[0]["buy_count"] == 4
    assert closed[0]["sell_count"] == 1
    assert report["research"]["supported_swaps"] == 5
    assert report["counts"]["closed"] == 1
    assert report["worksheet_reconciliation"]["status"] == "AGREE"
    assert Decimal(report["independent_worksheet"]["total_profit_sol"]) == Decimal(G1_PNL)
    decoded = decode_supported_swaps(_wrap_records(sanitize_transaction_records(records)["records"]), G1_ADDRESS)
    mint_events = _ordered_inventory_rows(g1_mint_events(decoded))
    expected_hold = mint_events[-1]["seconds_from_start"] - mint_events[0]["seconds_from_start"]
    sale_window_offset = mint_events[-1]["seconds_from_start"]
    exit_diag = report["material_exit"]
    assert exit_diag["method_version"] == "material-exit-v2"
    assert exit_diag["final_hold_seconds"] == expected_hold
    assert exit_diag["first_sale_seconds"] == expected_hold
    assert exit_diag["exit_50_seconds"] == expected_hold
    assert exit_diag["exit_90_seconds"] == expected_hold
    assert Decimal(str(exit_diag["quantity_weighted_exit_seconds"])) == Decimal(expected_hold)
    assert exit_diag["final_hold_seconds"] != sale_window_offset
    assert exit_diag["exit_90_window_offset_seconds"] == sale_window_offset
    assert Decimal(str(closed[0]["hold_hours"])) * Decimal("3600") == Decimal(expected_hold)
    from scanner.mass_search.service import _metrics_map
    from scanner.mass_search.triage import evaluate_behaviour, evaluate_forward_select
    from scanner.mass_search.plan import load_default_plan
    stored = _metrics_map(store, saved["run_id"])[f"solana:{G1_ADDRESS}"]
    assert stored["material_exit_t90_seconds"]["value"] == str(expected_hold)
    assert stored["material_exit_t90_seconds"]["method_version"] == "material-exit-v2"
    assert stored["material_exit_t90_seconds"]["value"] != str(sale_window_offset)
    plan = load_default_plan()
    candidate = {"candidate_id": f"solana:{G1_ADDRESS}", "address": G1_ADDRESS}
    behaviour = evaluate_behaviour(candidate, stored, plan)
    assert behaviour["result"] == "PROMOTED"
    assert "material_exit_observed" in behaviour["reason_codes"]
    assert evaluate_forward_select(candidate, stored, plan)["result"] == "PROMOTED"
    shifted = material_exit_v1([
        {**row, "seconds_from_start": row["seconds_from_start"] + 86_400} for row in mint_events
    ])
    assert shifted["final_hold_seconds"] == expected_hold
    assert shifted["first_sale_seconds"] == expected_hold
    assert shifted["exit_90_seconds"] == expected_hold
    assert Decimal(str(shifted["quantity_weighted_exit_seconds"])) == Decimal(expected_hold)
    store.close()

    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    monkeypatch.delenv("BIRDEYE_API_KEY", raising=False)
    import httpx

    async def forbidden(*args, **kwargs):
        raise AssertionError("G1 report reopen must not contact a provider")

    monkeypatch.setattr(httpx.AsyncClient, "post", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "get", forbidden)
    restarted = Store(tmp_path / "data")
    reopened = restarted.get("reports", saved["report_id"])
    assert reopened["id"] == saved["report_id"]
    assert Decimal(reopened["worksheet"]["total_profit_sol"]) == Decimal(G1_PNL)
    service = MassSearchService(restarted, clock=lambda: G1_WINDOW_END)
    linked = service.linked_reports(saved["run_id"])
    assert any(row["id"] == saved["report_id"] for row in linked)
    restarted.close()

    app = create_app(tmp_path / "data", LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as client:
        bootstrap = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        assert bootstrap.status_code == 200
        client.headers["x-csrf-token"] = bootstrap.json()["csrf"]
        listed = client.get(f"/api/mass-search/runs/{saved['run_id']}/reports")
        assert listed.status_code == 200
        found = next(item for item in listed.json()["reports"] if item["id"] == saved["report_id"])
        assert Decimal(found["worksheet"]["total_profit_sol"]) == Decimal(G1_PNL)
        assert found["address"] == G1_ADDRESS


def test_visible_below_g3_and_export_reopen_make_zero_provider_calls(tmp_path, monkeypatch):
    freeze = load_freeze()
    address = freeze["initial_candidates"][0]["address"]
    store = Store(tmp_path / "data")
    result = run_g3_history(
        store,
        fixture_pages={address: fixture_closed_records(sales=3)},
        decode=fixture_decode(3),
    )
    row = result["inspected_candidates"][0]
    assert row["status"] == "VISIBLE_BELOW_G3"
    assert row["g3_qualifying"] is False
    assert row["wallet_completed_episodes"] == 3
    assert row["worksheet"]
    assert row["declared_mints"]
    report_id = row["report_id"]
    store.close()

    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    import httpx

    async def forbidden(*args, **kwargs):
        raise AssertionError("Recovery reopen/export must not contact a provider")

    monkeypatch.setattr(httpx.AsyncClient, "post", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "get", forbidden)
    app = create_app(tmp_path / "data", LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as client:
        bootstrap = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        assert bootstrap.status_code == 200
        client.headers["x-csrf-token"] = bootstrap.json()["csrf"]
        listed = client.get(f"/api/mass-search/runs/{result['search_run_id']}/reports")
        assert listed.status_code == 200
        reports = listed.json()["reports"]
        assert reports
        found = next(item for item in reports if item["id"] == report_id)
        assert found["worksheet"]
        assert found.get("observations") is not None
        exported = client.get(f"/api/mass-search/runs/{result['search_run_id']}/export")
        assert exported.status_code == 200
        payload = json.loads(exported.content)
        assert payload["reports"]
        assert payload["reports"][0]["worksheet"]
        refilter = client.post(f"/api/mass-search/runs/{result['search_run_id']}/refilter", json={})
        assert refilter.status_code in (200, 400, 409)


def test_events_to_accounting_preserves_evidenced_payer_and_does_not_blanket_true():
    start = G1_WINDOW_START
    sponsored = events_to_accounting([
        {"kind": "buy", "units": "1", "consideration_sol": "1", "wallet_fee_sol": "0.001",
         "seconds_from_start": 0, "mint": "MintA", "signature": "buy-s", "paid_by_wallet": False},
        {"kind": "sell", "units": "1", "consideration_sol": "1", "wallet_fee_sol": "0",
         "seconds_from_start": 10, "mint": "MintA", "signature": "sell-s", "paid_by_wallet": False},
    ], mint="MintA", start=start)
    trades = [row for row in sponsored if row["kind"] in ("buy", "sell")]
    assert all(row["paid_by_wallet"] is False for row in trades)
    assert all(row["kind"] != "fee" for row in sponsored)

    evidenced = events_to_accounting([
        {"kind": "buy", "units": "1", "consideration_sol": "1", "wallet_fee_sol": "0.001",
         "seconds_from_start": 0, "mint": "MintA", "signature": "buy-e", "paid_by_wallet": True,
         "path": "swap/0", "evidence": ["a" * 64]},
        {"kind": "sell", "units": "1", "consideration_sol": "1.1", "wallet_fee_sol": "0.001",
         "seconds_from_start": 10, "mint": "MintA", "signature": "sell-e", "paid_by_wallet": True,
         "path": "swap/0", "evidence": ["b" * 64]},
    ], mint="MintA", start=start)
    buy = next(row for row in evidenced if row["kind"] == "buy")
    fee = next(row for row in evidenced if row["kind"] == "fee" and row["signature"] == "buy-e")
    assert buy["paid_by_wallet"] is True
    assert fee["paid_by_wallet"] is True
    assert fee["allocated_trade_path"] == buy["path"]


def test_accounting_integration_error_is_not_swallowed(tmp_path):
    store = Store(tmp_path / "data")
    service = MassSearchService(store, clock=lambda: G1_WINDOW_END)
    plan = service.preview_plan()["plan"]
    plan["live_enabled"] = False
    run = service.create_run(plan, source_id="payer-mismatch", corpus_kind="SYNTHETIC")
    with pytest.raises(ValueError, match="Accounting integration failed"):
        service.reconstruct_candidate(
            run["run_id"], "solana:Addr111111111111111111111111111111111111111",
            [
                {"kind": "buy", "units": "not-a-quantity", "consideration_sol": "1",
                 "seconds_from_start": 0, "mint": "MintA", "signature": "buy-bad",
                 "paid_by_wallet": True, "evidence": ["a" * 64]},
                {"kind": "sell", "units": "1", "consideration_sol": "1",
                 "seconds_from_start": 10, "mint": "MintA", "signature": "sell-bad",
                 "paid_by_wallet": True, "evidence": ["b" * 64]},
            ],
            mint="MintA",
        )
    store.close()


def test_multi_mint_fifo_keeps_separate_inventories_and_costs():
    events = [
        {"kind": "buy", "units": "10", "consideration_sol": "10", "wallet_fee_sol": "0",
         "seconds_from_start": 0, "mint": "MintA", "signature": "a-buy"},
        {"kind": "buy", "units": "2", "consideration_sol": "20", "wallet_fee_sol": "0",
         "seconds_from_start": 1, "mint": "MintB", "signature": "b-buy"},
        {"kind": "sell", "units": "10", "consideration_sol": "11", "wallet_fee_sol": "0",
         "seconds_from_start": 2, "mint": "MintA", "signature": "a-sell"},
        {"kind": "sell", "units": "2", "consideration_sol": "18", "wallet_fee_sol": "0",
         "seconds_from_start": 3, "mint": "MintB", "signature": "b-sell"},
    ]
    from scanner.mass_search.metrics import fifo_sale_results
    worksheet = fifo_sale_results(events)
    assert worksheet["declared_mints"] == ["MintA", "MintB"]
    assert Decimal(worksheet["sale_fifo_basis_sol"][0]) == Decimal("10")
    assert Decimal(worksheet["sale_fifo_basis_sol"][1]) == Decimal("20")
    assert Decimal(worksheet["total_profit_sol"]) == Decimal("-1")


def test_worksheet_disagreement_is_a_conflict_not_a_substitution():
    production = {"total_profit_sol": "-0.10", "sale_net_profit_sol": ["-0.10"], "sale_fifo_basis_sol": ["1"]}
    independent = {"total_profit_sol": "-0.167725526", "sale_net_profit_sol": ["-0.167725526"], "sale_fifo_basis_sol": ["7.90026"]}
    result = reconcile_worksheets(production, independent)
    assert result["status"] == "CONFLICT"
    assert result["production_worksheet"] == production
    assert result["independent_worksheet"] == independent
    assert result["production_total_profit_sol"] == "-0.1"
    assert Decimal(result["independent_total_profit_sol"]) == Decimal("-0.167725526")


def test_position_hold_is_window_shift_invariant():
    events = [
        {"kind": "buy", "units": "1", "consideration_sol": "1", "wallet_fee_sol": "0", "seconds_from_start": 1000},
        {"kind": "sell", "units": "1", "consideration_sol": "1", "wallet_fee_sol": "0", "seconds_from_start": 1598},
    ]
    first = material_exit_v1(events)
    shifted = material_exit_v1([
        {**row, "seconds_from_start": row["seconds_from_start"] + 50_000} for row in events
    ])
    for key in ("first_sale_seconds", "exit_50_seconds", "exit_90_seconds", "final_hold_seconds"):
        assert first[key] == 598
        assert shifted[key] == 598
    assert Decimal(str(first["quantity_weighted_exit_seconds"])) == Decimal("598")
    assert Decimal(str(shifted["quantity_weighted_exit_seconds"])) == Decimal("598")
    assert first["exit_90_window_offset_seconds"] != shifted["exit_90_window_offset_seconds"]


def test_dust_tail_t90_stays_opening_relative_not_final_hold():
    events = [
        {"kind": "buy", "units": "100", "seconds_from_start": 0, "mint": "MintA"},
        {"kind": "sell", "units": "90", "seconds_from_start": 30, "mint": "MintA"},
        {"kind": "sell", "units": "10", "seconds_from_start": 172800, "mint": "MintA"},
    ]
    timing = material_exit_v1(events)
    assert timing["exit_90_seconds"] == 30
    assert timing["final_hold_seconds"] == 172800
    assert timing["first_sale_seconds"] == 30


def test_interleaved_mints_and_repeated_positions_keep_own_exit_milestones():
    events = [
        {"kind": "buy", "units": "100", "seconds_from_start": 1000, "mint": "MintA", "signature": "a1"},
        {"kind": "buy", "units": "10", "seconds_from_start": 50, "mint": "MintB", "signature": "b1"},
        {"kind": "sell", "units": "100", "seconds_from_start": 1598, "mint": "MintA", "signature": "a1s"},
        {"kind": "sell", "units": "9", "seconds_from_start": 80, "mint": "MintB", "signature": "b1s"},
        {"kind": "sell", "units": "1", "seconds_from_start": 50 + 172800, "mint": "MintB", "signature": "b1d"},
        {"kind": "buy", "units": "10", "seconds_from_start": 5000, "mint": "MintA", "signature": "a2"},
        {"kind": "sell", "units": "10", "seconds_from_start": 5030, "mint": "MintA", "signature": "a2s"},
    ]
    timing = material_exit_v1(events)
    by_key = {(row["mint"], row["position_index"]): row for row in timing["positions"]}
    first_a = by_key[("MintA", 0)]
    second_a = by_key[("MintA", 1)]
    only_b = by_key[("MintB", 0)]
    assert first_a["first_sale_seconds"] == first_a["exit_90_seconds"] == first_a["final_hold_seconds"] == 598
    assert first_a["acquired_units"] == "100"
    assert second_a["exit_90_seconds"] == second_a["final_hold_seconds"] == 30
    assert only_b["exit_90_seconds"] == 30
    assert only_b["final_hold_seconds"] == 172800
    assert only_b["acquired_units"] == "10"
    assert timing["aggregation_method"] == "median"
    assert timing["sample_count"] == 3


def test_missing_opening_or_unresolved_quantities_do_not_substitute_window_offsets():
    missing_open = material_exit_v1([
        {"kind": "buy", "units": "1", "seconds_from_start": None, "mint": "MintA", "timestamp_missing": True},
        {"kind": "sell", "units": "1", "seconds_from_start": 2263932, "mint": "MintA"},
    ])
    assert missing_open["state"] == "UNKNOWN"
    assert missing_open["exit_90_seconds"] is None
    assert missing_open["first_sale_seconds"] is None
    assert missing_open["final_hold_seconds"] is None
    assert "missing_opening_time" in missing_open["missing_dependencies"]
    ambiguous = material_exit_v1([
        {"kind": "buy", "units": "1", "seconds_from_start": 10, "mint": "MintA", "unresolved_order": True},
        {"kind": "sell", "units": "1", "seconds_from_start": 20, "mint": "MintA"},
    ])
    assert ambiguous["state"] == "UNKNOWN"
    assert ambiguous["exit_90_seconds"] is None
    assert "ambiguous_order" in ambiguous["missing_dependencies"]
    bad_qty = material_exit_v1([
        {"kind": "buy", "units": "not-a-quantity", "seconds_from_start": 0, "mint": "MintA"},
        {"kind": "sell", "units": "1", "seconds_from_start": 20, "mint": "MintA"},
    ])
    assert bad_qty["state"] == "UNKNOWN"
    assert bad_qty["exit_90_seconds"] is None
    assert "unresolved_quantities" in bad_qty["missing_dependencies"]
