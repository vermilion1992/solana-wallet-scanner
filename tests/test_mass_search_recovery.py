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
