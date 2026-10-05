"""Offline RANKED_100_DISCOVERY_PILOT: trader_score, one-request ledger, shortlist honesty."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from scanner.mass_search.adapters import BirdeyeTraderAdapter, SourceError, parse_trader_row
from scanner.mass_search.capability import documented_birdeye_traders, validate_live_authorization
from scanner.mass_search.ranked100 import (
    AUTHORIZATION_ID,
    CANDIDATE_LABEL,
    EXACT_QUERY,
    G1_AUTHORIZATION_ID,
    GRANT_PATH,
    OUTCOME_LABEL,
    RANKED_100_PRESET,
    acquire_ranked100_page,
    armed_test_grant,
    arming_blockers,
    available_metrics,
    fixture_ranked_page,
    load_ranked100_grant,
    parse_ranked_items,
    rescreen_from_cache,
    run_ranked100_pilot,
    screen_ranked100,
)
from scanner.mass_search.universe import synthetic_address
from scanner.storage import Store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "data")
    yield instance
    instance.close()


def test_committed_ranked100_grant_is_disabled_and_not_g1():
    grant = load_ranked100_grant(GRANT_PATH)
    checked = validate_live_authorization(grant)
    assert grant["authorization_id"] == AUTHORIZATION_ID
    assert grant["authorization_id"] != G1_AUTHORIZATION_ID
    assert grant["enabled"] is False
    assert checked["enabled"] is False
    assert grant["outcome_label"] == OUTCOME_LABEL
    assert grant["not_full_g2"] is True
    assert grant["do_not_reset_setup_pilot"] is True
    assert grant["max_additional_spend_usd"] == "0"
    assert grant["authorized_by_user_at"] == "2026-10-05T13:01:00Z"
    assert grant["expires_at"] == "2026-10-06T13:01:00Z"
    assert grant["exact_query"]["params"] == EXACT_QUERY["params"]
    birdeye = next(entry for entry in grant["providers"] if entry["provider_id"] == "birdeye")
    helius = next(entry for entry in grant["providers"] if entry["provider_id"] == "helius")
    assert birdeye["max_requests"] == 1 and birdeye["max_units"] == 30
    assert helius["max_requests"] == 0 and helius["max_units"] == 0
    assert helius["allowed_operations"] == []
    assert birdeye["existing_plan_confirmed"] is False
    assert birdeye["remaining_quota_confirmed_at"] is None
    blockers = {row["code"] for row in arming_blockers(grant, credentials={"birdeye": False})}
    assert "grant_disabled" in blockers
    assert "remaining_quota_unconfirmed" in blockers
    assert "existing_plan_unconfirmed" in blockers
    assert "missing_provider_credentials" in blockers
    g1 = json.loads((ROOT / "config/live_authorization.g1-granted.json").read_text())
    assert g1["authorization_id"] == G1_AUTHORIZATION_ID
    assert g1["authorization_id"] != AUTHORIZATION_ID


def test_g1_grant_cannot_be_loaded_as_ranked100():
    with pytest.raises(ValueError, match="G1 grant must not be reused"):
        load_ranked100_grant(ROOT / "config/live_authorization.g1-granted.json")


def test_zero_budget_helius_can_arm_in_memory_without_helius_quota():
    checked = armed_test_grant()
    assert checked["enabled"] is True
    helius = next(entry for entry in checked["providers"] if entry["provider_id"] == "helius")
    assert helius["max_requests"] == 0
    assert helius["allowed_operations"] == []
    birdeye = next(entry for entry in checked["providers"] if entry["provider_id"] == "birdeye")
    assert birdeye["remaining_quota_confirmed_at"]


def test_capability_lists_trader_score_separately_from_evidence():
    record = documented_birdeye_traders()
    assert "trader_score" in record["sort_fields"]
    assert record["sort_compatibility"]["trader_score"]["silent_fallback_to_pnl_sort"] is False
    score = record["field_map"]["trader_score"]
    assert score["basis"] == "PROVIDER_REPORTED"
    assert score["evidence_status"] == "not_independent_verification"
    assert record["field_map"]["trade_count"]["is_not"] == "completed_profitable_trades"


def test_parse_trader_row_keeps_provider_score_out_of_unreviewed_and_evidence():
    address = synthetic_address(9)
    row = parse_trader_row(
        {
            "address": address,
            "trader_score": 88.5,
            "realized_pnl": "12.5",
            "trade_count": 21,
            "last_trade_unix_time": 1_700_000_000,
        },
        field_map=documented_birdeye_traders()["field_map"],
        source_id="birdeye-traders",
        page=0,
        offset=0,
        fetch_timestamp="2026-10-05T12:00:00Z",
    )
    assert row["valid"] is True
    assert row["trader_score"] == "88.5"
    assert row["trader_score_basis"] == "PROVIDER_REPORTED"
    assert row["trader_score_is_not"] == "independently_verified_profit_or_copyability"
    assert row["trade_count_is_not"] == "completed_profitable_trades"
    assert "trader_score" not in row["unreviewed_fields"]
    assert row["realized_pnl_unit"] == "USD"


def test_screen_ranked_page_with_score_field():
    items = fixture_ranked_page()
    parsed = parse_ranked_items(items, fetch_timestamp="2026-10-05T12:00:00Z")
    result = screen_ranked100(parsed, as_of="2026-10-05T12:00:00Z")
    assert result["outcome_label"] == OUTCOME_LABEL
    assert result["unique_valid_wallets"] == 100
    assert result["acquisition_complete"] is True
    assert result["shortlist_count"] <= 20
    assert result["shortlist_count"] == 20
    assert result["padded"] is False
    scores = [float(row["provider_score"]) for row in result["shortlist"]]
    assert scores == sorted(scores, reverse=True)
    for row in result["shortlist"]:
        assert row["label"] == CANDIDATE_LABEL
        assert row["evidence_status"] == "unverified"
        assert "ranked_by_provider_score" in row["reason_codes"]
        assert "provider_trade_count_proxy_not_completed_profitable_trades" in row["reason_codes"]
        assert "completed profitable trades" not in " ".join(row["reason_codes"])
    excluded_codes = {code for row in result["exclusions"] for code in row["reason_codes"]}
    assert "excluded_known_non_positive_reported_pnl" in excluded_codes
    assert "excluded_low_provider_trade_count_proxy" in excluded_codes
    assert "excluded_stale_provider_activity" in excluded_codes


def test_incomplete_page_is_honest():
    items = fixture_ranked_page()[:40]
    parsed = parse_ranked_items(items, fetch_timestamp="2026-10-05T12:00:00Z")
    result = screen_ranked100(parsed, as_of="2026-10-05T12:00:00Z")
    assert result["unique_valid_wallets"] == 40
    assert result["acquisition_complete"] is False
    assert result["acquisition_note"] == "honest_incomplete_acquisition"
    assert result["shortlist_count"] <= 20
    assert result["padded"] is False


def test_duplicate_addresses_keep_first_source_order():
    address = synthetic_address(3000)
    other = synthetic_address(3001)
    fetch_at = "2026-10-05T12:00:00Z"
    as_of = int(datetime.fromisoformat("2026-10-05T12:00:00+00:00").timestamp())
    recent = as_of - 2 * 86400
    items = [
        {"address": address, "trader_score": 10, "realized_pnl": "5", "trade_count": 20,
         "last_trade_unix_time": recent},
        {"address": address, "trader_score": 99, "realized_pnl": "50", "trade_count": 80,
         "last_trade_unix_time": recent},
        {"address": other, "trader_score": 8, "realized_pnl": "4", "trade_count": 22,
         "last_trade_unix_time": recent},
    ]
    parsed = parse_ranked_items(items, fetch_timestamp=fetch_at)
    result = screen_ranked100(parsed, as_of=fetch_at)
    assert result["unique_valid_wallets"] == 2
    assert any("excluded_duplicate_address" in row["reason_codes"] for row in result["exclusions"])
    first = next(row for row in result["shortlist"] if row["address"] == address)
    assert first["provider_score"] == "10"


def test_missing_metrics_stay_unknown_and_need_verification():
    items = [{"address": synthetic_address(4000 + i), "trader_score": 500 - i} for i in range(5)]
    parsed = parse_ranked_items(items, fetch_timestamp="2026-10-05T12:00:00Z")
    result = screen_ranked100(parsed, as_of="2026-10-05T12:00:00Z")
    assert result["shortlist_count"] == 5
    for row in result["shortlist"]:
        assert "realized_pnl_unknown" in row["uncertainty"]
        assert "recent_activity_unknown" in row["uncertainty"]
        assert "trade_count_unknown" in row["uncertainty"]
        assert "high_score_missing_fields_needs_verification" in row["reason_codes"]
        assert row["evidence_status"] == "unverified"
        assert row["label"] == CANDIDATE_LABEL
    metrics = available_metrics(parsed)
    assert metrics["trader_score"] == 5
    assert metrics["realized_pnl"] == 0


def test_zero_qualifiers_are_honest_and_not_padded():
    as_of = int(datetime.fromisoformat("2026-10-05T12:00:00+00:00").timestamp())
    recent = as_of - 2 * 86400
    items = [
        {
            "address": synthetic_address(5000 + i),
            "trader_score": 900 - i,
            "realized_pnl": "-1",
            "trade_count": 40,
            "last_trade_unix_time": recent,
        }
        for i in range(8)
    ]
    parsed = parse_ranked_items(items, fetch_timestamp="2026-10-05T12:00:00Z")
    result = screen_ranked100(parsed, as_of="2026-10-05T12:00:00Z")
    assert result["shortlist_count"] == 0
    assert result["padded"] is False
    assert result["unique_valid_wallets"] == 8
    assert all("excluded_known_non_positive_reported_pnl" in row["reason_codes"] for row in result["exclusions"])


def test_adapter_rejects_silent_sort_fallback(store):
    grant = armed_test_grant()
    adapter = BirdeyeTraderAdapter(transport=None)

    async def _run():
        with pytest.raises(SourceError, match="exact query"):
            await adapter.fetch_page(
                offset=0, limit=100, window="30d", sort_by="realized_pnl", sort_type="desc",
                authorization=grant, store=store,
            )

    asyncio.run(_run())


def test_adapter_rejects_unknown_sort_without_fallback(store):
    grant = armed_test_grant()
    del grant["exact_query"]
    adapter = BirdeyeTraderAdapter(transport=None)

    async def _run():
        with pytest.raises(SourceError, match="silent fallback is forbidden"):
            await adapter.fetch_page(
                offset=0, limit=100, window="30d", sort_by="mystery_sort", sort_type="desc",
                authorization=grant, store=store,
            )

    asyncio.run(_run())


def test_one_request_boundary_and_failed_attempt_consumes_ledger(store):
    grant = armed_test_grant()
    calls = {"n": 0}

    async def boom(method, path, params):
        calls["n"] += 1
        assert params == EXACT_QUERY["params"]
        raise TimeoutError("simulated timeout")

    async def _first():
        return await acquire_ranked100_page(store, grant, transport=boom, allow_live=False)

    with pytest.raises(SourceError, match="timed out"):
        asyncio.run(_first())
    assert calls["n"] == 1
    assert store.usage("birdeye", grant["providers"][0]["cycle_start"], 30)["used"] == 30

    async def _second():
        return await acquire_ranked100_page(store, grant, transport=boom, allow_live=False)

    with pytest.raises(SourceError, match="one-request ceiling"):
        asyncio.run(_second())
    assert calls["n"] == 1
    assert store.usage("helius", "setup-pilot", 200)["used"] == 0


def test_reopen_after_restart_makes_zero_calls(tmp_path):
    grant = armed_test_grant()
    items = fixture_ranked_page()
    calls = {"n": 0}

    async def transport(method, path, params):
        calls["n"] += 1
        assert params["sort_by"] == "trader_score"
        assert params["type"] == "30d"
        assert params["limit"] == 100
        assert params["offset"] == 0
        return {
            "status": 200,
            "fetched_at": "2026-10-05T12:00:00Z",
            "body": {"data": {"items": items}},
        }

    first = Store(tmp_path / "data")
    page, from_cache = asyncio.run(acquire_ranked100_page(first, grant, transport=transport))
    assert from_cache is False
    assert calls["n"] == 1
    assert page["unique_valid_wallets"] == 100
    first.close()

    restarted = Store(tmp_path / "data")
    page2, from_cache2 = asyncio.run(acquire_ranked100_page(restarted, grant, transport=transport))
    assert from_cache2 is True
    assert calls["n"] == 1
    assert page2["evidence_sha256"] == page["evidence_sha256"]
    screening, cached = rescreen_from_cache(
        restarted, grant,
        heuristics={"prefer_provider_trade_count_at_least": 50},
    )
    assert cached["from_cache"] is False or page2["from_cache"] is True
    assert calls["n"] == 1
    assert screening["padded"] is False
    assert all(row["label"] == CANDIDATE_LABEL for row in screening["shortlist"])
    assert restarted.usage("helius", "setup-pilot", 200)["used"] == 0
    restarted.close()


def test_offline_pilot_uses_fixture_and_does_not_arm(store, monkeypatch):
    monkeypatch.delenv("BIRDEYE_API_KEY", raising=False)
    setup = store.reserve("helius", "getTransaction", 200, "setup-pilot", 200)
    store.dispatch(setup)
    store.settle(setup)
    result = run_ranked100_pilot(store, allow_live=False)
    assert result["status"] == "OFFLINE_PASS"
    assert result["grant_enabled"] is False
    assert result["external_requests"] == 0
    assert result["PRODUCT_READY"] is False
    assert result["not_full_g2"] is True
    assert result["shortlist_count"] <= RANKED_100_PRESET["local_shortlist_ceiling"]
    assert result["cache"]["unique_valid_wallets"] == 100
    codes = {row["code"] for row in result["arming_blockers"]}
    assert "grant_disabled" in codes
    assert "missing_provider_credentials" in codes
    assert store.usage("helius", "setup-pilot", 200)["remaining"] == 0
    again = run_ranked100_pilot(store, allow_live=False)
    assert again["from_cache"] is True
    assert again["external_requests"] == 0


def test_live_flag_stays_blocked_while_grant_disabled(store, monkeypatch):
    monkeypatch.delenv("BIRDEYE_API_KEY", raising=False)
    result = run_ranked100_pilot(store, allow_live=True)
    assert result["status"] == "BLOCKED"
    assert result["blocker"] == "grant_disabled"
    assert result["external_requests"] == 0
