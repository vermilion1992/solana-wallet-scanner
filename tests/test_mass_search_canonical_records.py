"""Shared decode-record contract and genuine rank-1 page-0 classification. Offline only."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from scanner.investigation import PUMP, decode_supported_swaps
from scanner.mass_search.canonical_records import (
    PUMP_IDL_PIN,
    canonical_decode_records,
    classify_normalised_records,
    gta_records_from_capture,
    is_canonical_decode_record,
    unwrap_gta_record,
)
from scanner.mass_search.g3_reacquire import (
    ALLOWED_WALLET,
    PAGE0_SIGNATURE_LTE,
    PAGE1_PAGINATION_TOKEN,
    armed_test_grant,
    frozen_signatures,
    load_anchored_validation_grant,
    load_freeze,
    run_reacquire,
    _summarize_page,
)
from scanner.mass_search.history_ingest import replay_cached_history_to_report
from scanner.mass_search.live_g1 import _wrap_records
from scanner.storage import Store

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "evidence/mass-wallet-funnel/ranked100-anchored-validation-live/SOURCE_RESPONSE_page0.json"
EXPECTED_CAPTURE_SHA = "53a5c6f46ec2e0f8c895df6398116756ae3728892f0a6b702137f56d8624328d"
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


def _load_capture_records():
    payload = json.loads(CAPTURE.read_text(encoding="utf-8"))
    return gta_records_from_capture(payload)


def test_capture_sha_and_record_count():
    digest = hashlib.sha256(CAPTURE.read_bytes()).hexdigest()
    assert digest == EXPECTED_CAPTURE_SHA
    assert CAPTURE.stat().st_size == 2403585
    records = _load_capture_records()
    assert len(records) == 100
    assert records[0]["transaction"]["signatures"][0] == PAGE0_SIGNATURE_LTE
    assert "raw" not in records[0]


def test_canonical_wrap_is_idempotent_and_preserves_body():
    records = _load_capture_records()[:3]
    once = canonical_decode_records(records)
    twice = canonical_decode_records(once)
    assert [row["evidence_hash"] for row in once] == [row["evidence_hash"] for row in twice]
    assert all(is_canonical_decode_record(row) for row in once)
    assert unwrap_gta_record(once[0])["meta"]["preTokenBalances"] == records[0]["meta"]["preTokenBalances"]
    assert unwrap_gta_record(once[0])["meta"]["innerInstructions"] == records[0]["meta"]["innerInstructions"]
    assert unwrap_gta_record(once[2])["meta"].get("err") == records[2]["meta"].get("err")
    aliased = _wrap_records(once)
    assert [row["evidence_hash"] for row in aliased] == [row["evidence_hash"] for row in once]


def test_unwrapped_gta_is_missing_raw_wrapped_is_not():
    records = _load_capture_records()
    bare = decode_supported_swaps(records, ALLOWED_WALLET)
    reasons = {row.get("reason") for row in bare.get("unresolved") or []}
    assert "Missing raw transaction result" in reasons
    wrapped = decode_supported_swaps(canonical_decode_records(records), ALLOWED_WALLET)
    reasons = {row.get("reason") for row in wrapped.get("unresolved") or []}
    assert "Missing raw transaction result" not in reasons
    assert wrapped["coverage"]["failed_transactions"] == 19
    assert wrapped["coverage"]["decoded_swaps"] == 0


def test_summarize_page_uses_shared_wrap():
    records = _load_capture_records()
    summary = _summarize_page({"records": records, "integrity": {"status": "SOURCE_RECORDS_INTACT"}}, {"windows": WINDOWS})
    reasons = {row.get("reason") for row in summary["decoded"].get("unresolved") or []}
    assert "Missing raw transaction result" not in reasons
    assert summary["counted"]["wallet_completed_episodes"] == 0
    assert summary["visible_report"] is False
    assert any("distribute_fee_to_holders is not a spot swap" in (row.get("reason") or "") for row in summary["decoded"].get("unresolved") or [])


def test_classify_every_tx_independently_of_swap_reconstruction():
    records = canonical_decode_records(_load_capture_records())
    classified = classify_normalised_records(records, ALLOWED_WALLET)
    assert classified["transactions"] == 100
    assert classified["pump_idl_pin"]["sha256"] == PUMP_IDL_PIN["sha256"]
    counts = classified["counts"]
    assert counts.get("pump_bonding_curve_swap_candidate", 0) == 0
    assert counts["failed_on_chain"] == 19
    assert counts["pump_holder_fee_distribution"] == 61
    assert counts["unreviewed_jupiter_discriminator"] == 6
    assert counts["inner_pumpswap_without_reviewed_outer"] == 2
    assert counts["unsupported_transaction_version"] == 1
    assert counts["wallet_absent_from_account_keys"] == 5
    first = classified["rows"][0]
    assert first["class"] == "pump_holder_fee_distribution"
    assert first["outer_venues"][0]["program"] == PUMP
    assert first["outer_venues"][0]["instruction"] == "distribute_fee_to_holders"
    fees = classified["fee_totals"]
    expected_lamports = sum(
        row["fee_lamports"] for row in classified["rows"] if isinstance(row.get("fee_lamports"), int)
    )
    failed_lamports = sum(
        row["fee_lamports"]
        for row in classified["rows"]
        if row.get("failed") and isinstance(row.get("fee_lamports"), int)
    )
    assert fees["fee_lamports"] == expected_lamports
    assert fees["failed_fee_lamports"] == failed_lamports
    assert fees["not_pnl"] is True
    assert fees["fee_sol"] == str(Decimal(expected_lamports) / Decimal(1_000_000_000))


def test_runner_stubbed_capture_persists_before_validate_and_skips_page1(store, tmp_path):
    freeze = load_freeze()
    records = _load_capture_records()
    calls = []

    async def transport(address, *, options, page_index):
        calls.append({
            "page_index": page_index,
            "signature_lte": ((options.get("filters") or {}).get("signature") or {}).get("lte"),
            "until": options.get("until"),
        })
        return {
            "records": records,
            "pagination_token": PAGE1_PAGINATION_TOKEN,
            "http_status": 200,
            "external_requests": 1,
        }

    result = run_reacquire(
        store,
        allow_live=True,
        grant=armed_test_grant(load_anchored_validation_grant()),
        freeze=freeze,
        credentials={"helius": True},
        transport=transport,
        evidence_dir=tmp_path / "anchored-replay",
    )
    assert [row["page_index"] for row in calls] == [0]
    assert calls[0]["until"] is None
    assert calls[0]["signature_lte"] == PAGE0_SIGNATURE_LTE
    assert result["page_integrity"][0]["signature_match"] is True
    assert result["page_integrity"][0]["integrity"] == "SOURCE_RECORDS_INTACT"
    assert result["status"] == "INCOMPLETE"
    assert result["stop_reason"] == "page1_not_for_episode_count_or_pnl"
    assert result["page1_gate"]["allowed"] is False
    assert result["external_requests"] == 1
    assert result["wallet_completed_episodes"] == 0


def test_replay_saves_honest_partial_report(store):
    records = _load_capture_records()
    result = replay_cached_history_to_report(
        store,
        address=ALLOWED_WALLET,
        records=records,
        window_start=WINDOWS["report_start_inclusive"],
        window_end=WINDOWS["report_end_exclusive"],
        acquisition_start=WINDOWS["acquisition_support_start_inclusive"],
        corpus_kind="GENUINE_REPLAY",
        authorization_id="live-ranked100-anchored-validation-2026-10-06-mitch",
        source_id="ranked100-anchored-offline-replay",
    )
    assert result["report_id"]
    report = store.get("reports", result["report_id"])
    assert report["source"] == "mass-search"
    assert report["g3_status"] == "PARTIAL_NO_SUPPORTED_SOL_SWAPS"
    assert report["worksheet"] is None
    assert report["PRODUCT_READY"] is False
    assert report["shortlist_rank"] == 1
    assert any(item.get("kind") == "tx_classification" for item in report["observations"])
    assert report["classification"]["counts"]["pump_holder_fee_distribution"] == 61
    assert report["classification"]["fee_totals"]["not_pnl"] is True
    assert report["classification"]["fee_totals"]["fee_lamports"] > 0
    assert any(item.get("kind") == "fees" for item in report["observations"])
    assert report["coverage"]["decoded_swaps"] == 0
    assert report["coverage"]["failed_transactions"] == 19
    assert report["coverage"]["not_pnl"] is True
    assert report["findings"]
    assert result["visible_report"] is False
    assert result["external_requests"] == 0
