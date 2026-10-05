"""Offline G3_RANKED100_HISTORY: freeze, ledgers, pipeline reconstruct, no live."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scanner.mass_search.adapters import SourceError
from scanner.mass_search.capability import validate_live_authorization
from scanner.mass_search.g3_history import (
    AUTHORIZATION_ID,
    FREEZE_PATH,
    G1_AUTHORIZATION_ID,
    GRANT_PATH,
    OUTCOME_LABEL,
    PARENT_COMMIT,
    RANKED100_AUTHORIZATION_ID,
    armed_test_grant,
    arming_blockers,
    assert_address_frozen,
    assert_freeze_matches_shortlist,
    completed_episodes,
    decoder_events_by_mint,
    fixture_closed_records,
    fixture_decode,
    further_page_allowed,
    load_freeze,
    load_g3_grant,
    run_g3_history,
)
from scanner.storage import Store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "data")
    yield instance
    instance.close()


def test_committed_g3_grant_is_disabled_and_not_prior_grants():
    grant = load_g3_grant(GRANT_PATH)
    checked = validate_live_authorization(grant)
    assert grant["authorization_id"] == AUTHORIZATION_ID
    assert grant["authorization_id"] not in (G1_AUTHORIZATION_ID, RANKED100_AUTHORIZATION_ID)
    assert grant["enabled"] is False
    assert checked["enabled"] is False
    assert grant["authorized_by_user_at"] == "2026-10-05T14:19:00Z"
    assert grant["expires_at"] == "2026-10-06T14:19:00Z"
    assert grant["parent_commit"] == PARENT_COMMIT
    assert grant["max_additional_spend_usd"] == "0"
    assert grant["do_not_reset_setup_pilot"] is True
    helius = next(entry for entry in grant["providers"] if entry["provider_id"] == "helius")
    birdeye = next(entry for entry in grant["providers"] if entry["provider_id"] == "birdeye")
    assert helius["max_requests"] == 15 and helius["max_units"] == 150
    assert helius["max_requests_per_wallet"] == 3
    assert helius["documented_units_per_request"] == 10
    assert birdeye["max_requests"] == 0 and birdeye["max_units"] == 0
    assert helius["existing_plan_confirmed"] is False
    assert helius["remaining_quota_confirmed_at"] is None
    blockers = {row["code"] for row in arming_blockers(grant, credentials={"helius": False})}
    assert "grant_disabled" in blockers
    assert "remaining_quota_unconfirmed" in blockers
    assert "existing_plan_unconfirmed" in blockers
    assert "missing_provider_credentials" in blockers


def test_g1_and_ranked100_cannot_be_loaded_as_g3():
    with pytest.raises(ValueError, match="must not be reused"):
        load_g3_grant(ROOT / "config/live_authorization.g1-granted.json")
    with pytest.raises(ValueError, match="must not be reused"):
        load_g3_grant(ROOT / "config/live_authorization.g2-ranked100-discovery-granted.json")


def test_freeze_is_ranks_1_3_5_and_reserves_6_7():
    freeze = load_freeze(FREEZE_PATH)
    assert_freeze_matches_shortlist(freeze)
    assert freeze["parent_commit"] == PARENT_COMMIT
    assert [row["shortlist_rank"] for row in freeze["initial_candidates"]] == [1, 3, 5]
    assert [row["shortlist_rank"] for row in freeze["reserve_candidates"]] == [6, 7]
    assert [row["address"] for row in freeze["initial_candidates"]] == [
        "25865JdBJVVLbt6Kfe4KnKrVCy8UVCYFRRBAPvmJ17LL",
        "DSJVxpK1gwZvFsiYdaRz7Ly51vTXnAwHGfLGWcRvVJGE",
        "3g8KsJE1yhJvBo6kvqvxLnoSXQ9suqQnHMqGFs3LFckM",
    ]
    assert freeze["no_additional_live_addresses"] is True
    assert freeze["windows"]["report_end_exclusive"] == "2026-10-05T13:29:27Z"
    assert freeze["windows"]["report_start_inclusive"] == "2026-09-05T13:29:27Z"
    assert freeze["windows"]["acquisition_support_start_inclusive"] == "2026-07-07T13:29:27Z"
    extra = "So11111111111111111111111111111111111111112"
    with pytest.raises(SourceError, match="not on the frozen"):
        assert_address_frozen(freeze, extra)


def test_further_page_requires_evidence_reason():
    page = {"pagination_token": "next"}
    ok, why = further_page_allowed(page, 4, recorded_reason=None)
    assert ok is False
    ok, why = further_page_allowed(page, 4, recorded_reason="insufficient_episodes_pagination_token_present")
    assert ok is True and why == "insufficient_episodes_pagination_token_present"
    ok, _ = further_page_allowed(page, 10, recorded_reason="insufficient_episodes_pagination_token_present")
    assert ok is False
    ok, _ = further_page_allowed({"pagination_token": None}, 2, recorded_reason="insufficient_episodes_pagination_token_present")
    assert ok is False


def test_offline_prep_verifies_freeze_without_provider_calls(store, monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    setup = store.reserve("helius", "getTransaction", 200, "setup-pilot", 200)
    store.dispatch(setup)
    store.settle(setup)
    result = run_g3_history(store, allow_live=False)
    assert result["status"] == "OFFLINE_PASS"
    assert result["outcome_label"] == OUTCOME_LABEL
    assert result["grant_enabled"] is False
    assert result["freeze_verified"] is True
    assert result["external_requests"] == 0
    assert result["PRODUCT_READY"] is False
    assert store.usage("helius", "setup-pilot", 200)["remaining"] == 0
    codes = {row["code"] for row in result["arming_blockers"]}
    assert "grant_disabled" in codes
    assert "remaining_quota_unconfirmed" in codes


def test_live_flag_stays_blocked_while_grant_disabled(store, monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    result = run_g3_history(store, allow_live=True)
    assert result["status"] == "BLOCKED"
    assert result["blocker"] == "grant_disabled"
    assert result["external_requests"] == 0


def test_three_fixture_reports_qualify_and_skip_reserves(store):
    freeze = load_freeze()
    initials = [row["address"] for row in freeze["initial_candidates"]]
    reserves = [row["address"] for row in freeze["reserve_candidates"]]
    fixtures = {address: fixture_closed_records(sales=10) for address in initials}
    result = run_g3_history(
        store, allow_live=False, fixture_pages=fixtures, decode=fixture_decode(10),
    )
    assert result["status"] == "G3_PASS"
    assert result["qualifying_reports"] == 3
    assert result["external_requests"] == 0
    assert result["stop_reason"] == "three_qualifying_reports"
    seen = {row["address"] for row in result["inspected_candidates"]}
    assert seen == set(initials)
    assert not (seen & set(reserves))
    for row in result["inspected_candidates"]:
        assert row["g3_qualifying"] is True
        assert row["wallet_completed_episodes"] == 10
        assert row["not_wallet_wide_match"] is True
        assert row["worksheet"]["oracle"] == "independent-g1-fifo-v1"
        assert row["report_id"]
    assert store.usage("helius", "setup-pilot", 200)["used"] == 0


def test_small_report_is_visible_but_does_not_pass_g3(store):
    freeze = load_freeze()
    address = freeze["initial_candidates"][0]["address"]
    result = run_g3_history(
        store,
        allow_live=False,
        fixture_pages={address: fixture_closed_records(sales=3)},
        decode=fixture_decode(3),
    )
    row = result["inspected_candidates"][0]
    assert row["status"] == "VISIBLE_BELOW_G3"
    assert row["g3_qualifying"] is False
    assert row["wallet_completed_episodes"] == 3
    assert row["worksheet"]
    assert result["qualifying_reports"] == 0
    assert result["visible_below_g3"] == 1


def test_failed_dispatch_consumes_ledger_and_reopen_is_zero_network(tmp_path):
    grant = armed_test_grant()
    freeze = load_freeze()
    address = freeze["initial_candidates"][0]["address"]
    calls = {"n": 0}

    async def boom(target, **kwargs):
        calls["n"] += 1
        assert kwargs["options"]["sortOrder"] == "desc"
        assert kwargs["options"]["limit"] == 100
        assert kwargs["options"]["transactionDetails"] == "full"
        raise TimeoutError("simulated timeout")

    store = Store(tmp_path / "data")
    store.put("configuration", "live_authorization", grant)
    with pytest.raises(SourceError, match="timed out"):
        import asyncio
        from scanner.mass_search.g3_history import fetch_helius_page
        asyncio.run(fetch_helius_page(store, grant, address, page_index=0, reason="first_page_no_equivalent_cache",
                                      transport=boom))
    assert calls["n"] == 1
    used = store.usage("helius", grant["providers"][0]["cycle_start"], 150)
    assert used["used"] == 10
    store.close()

    restarted = Store(tmp_path / "data")
    used2 = restarted.usage("helius", grant["providers"][0]["cycle_start"], 150)
    assert used2["used"] == 10
    assert restarted.usage("helius", "setup-pilot", 200)["used"] == 0
    restarted.close()


def test_reopen_cached_page_makes_zero_calls(tmp_path):
    freeze = load_freeze()
    initials = [row["address"] for row in freeze["initial_candidates"]]
    fixtures = {address: fixture_closed_records(sales=10) for address in initials}
    first = Store(tmp_path / "data")
    result = run_g3_history(first, fixture_pages=fixtures, decode=fixture_decode(10))
    assert result["qualifying_reports"] == 3
    first.close()
    calls = {"n": 0}

    async def transport(target, **kwargs):
        calls["n"] += 1
        return {"records": [], "pagination_token": None}

    restarted = Store(tmp_path / "data")
    again = run_g3_history(restarted, fixture_pages=None, transport=transport, decode=fixture_decode(10))
    assert calls["n"] == 0
    assert again["external_requests"] == 0
    assert all(row.get("from_cache") for row in again["inspected_candidates"])
    restarted.close()


def test_episode_count_does_not_relabel_trade_count():
    events = fixture_decode(2)([{}, {}, {}, {}], "addr")
    by_mint, _ = decoder_events_by_mint(
        events, address="addr",
        window_start="2026-09-05T13:29:27Z",
        window_end="2026-10-05T13:29:27Z",
        acquisition_start="2026-07-07T13:29:27Z",
    )
    counted = completed_episodes(by_mint)
    assert counted["wallet_completed_episodes"] == 2
    assert "completed_profitable_trades" not in json.dumps(counted)
