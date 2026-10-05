"""Offline G3_INTEGRITY_REACQUIRE_RANK1: EXTRACT_OK freeze, mismatch stop, ceilings."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from scanner.mass_search.adapters import SourceError
from scanner.mass_search.capability import validate_live_authorization
from scanner.mass_search.g3_history import AUTHORIZATION_ID as G3_LEFTOVER_ID
from scanner.mass_search.g3_reacquire import (
    ALLOWED_WALLET,
    AUTHORIZATION_ID,
    EXTRACT_OK,
    FREEZE_PATH,
    GRANT_PATH,
    OVERLAY_PATH,
    OUTCOME_LABEL,
    PARENT_RECOVERY_COMMIT,
    SIGNATURE_MISMATCH,
    STOP_NO_SEGMENT,
    apply_overlay,
    armed_test_grant,
    arming_blockers,
    assert_grant_ceilings,
    assert_non_grants_stay_disabled,
    assert_page_in_scope,
    assert_wallet_in_scope,
    compare_signatures,
    extract_signatures_from_sqlite,
    fetch_reacquire_page,
    frozen_signatures,
    load_freeze,
    load_reacquire_grant,
    load_signature_overlay,
    page1_allowed,
    request_pagination_token,
    run_reacquire,
    should_stop_after_visible_position,
)
from scanner.storage import Store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "data")
    yield instance
    instance.close()


def _stop_freeze():
    freeze = deepcopy(load_freeze())
    freeze["signature_manifest"]["status"] = STOP_NO_SEGMENT
    freeze["signature_manifest"]["original_segments_identified"] = False
    freeze["pages"][0]["signatures"] = []
    freeze["pages"][1]["signatures"] = []
    freeze["pages"][0]["signature_count_frozen"] = 0
    freeze["pages"][1]["signature_count_frozen"] = 0
    return freeze


def _records(signatures):
    return [
        {
            "signature": signature,
            "transaction": {"signatures": [signature], "message": {"accountKeys": [ALLOWED_WALLET]}},
            "meta": {"preTokenBalances": [], "postTokenBalances": [], "preBalances": [], "postBalances": []},
        }
        for signature in signatures
    ]


def test_committed_reacquire_grant_is_disabled_and_not_leftover_g3():
    grant = load_reacquire_grant(GRANT_PATH)
    checked = validate_live_authorization(grant)
    assert grant["authorization_id"] == AUTHORIZATION_ID
    assert grant["authorization_id"] != G3_LEFTOVER_ID
    assert grant["enabled"] is False
    assert checked["enabled"] is False
    assert grant["authorized_by_user_at"] == "2026-10-05T15:37:00Z"
    assert grant["expires_at"] == "2026-10-06T15:37:00Z"
    assert grant["parent_recovery_commit"] == PARENT_RECOVERY_COMMIT
    assert grant["allowed_wallet"] == ALLOWED_WALLET
    assert grant["max_additional_spend_usd"] == "0"
    assert grant["do_not_reset_setup_pilot"] is True
    helius = next(entry for entry in grant["providers"] if entry["provider_id"] == "helius")
    birdeye = next(entry for entry in grant["providers"] if entry["provider_id"] == "birdeye")
    assert helius["max_requests"] == 2 and helius["max_units"] == 20
    assert helius["max_requests_per_wallet"] == 2
    assert helius["documented_units_per_request"] == 10
    assert helius["max_duration_seconds"] == 300
    assert helius["max_concurrency"] == 1
    assert birdeye["max_requests"] == 0 and birdeye["max_units"] == 0
    assert helius["existing_plan_confirmed"] is False
    assert helius["remaining_quota_confirmed_at"] is None
    assert_grant_ceilings(grant)
    blockers = {row["code"] for row in arming_blockers(grant, credentials={"helius": False})}
    assert "grant_disabled" in blockers
    assert STOP_NO_SEGMENT not in blockers
    assert "signature_manifest_unfrozen" not in blockers
    assert "missing_provider_credentials" in blockers
    assert "remaining_quota_unconfirmed" in blockers


def test_leftover_g3_and_prior_grants_cannot_be_loaded_as_reacquire():
    with pytest.raises(ValueError, match="must not be reused"):
        load_reacquire_grant(ROOT / "config/live_authorization.g1-granted.json")
    with pytest.raises(ValueError, match="must not be reused"):
        load_reacquire_grant(ROOT / "config/live_authorization.g2-ranked100-discovery-granted.json")
    with pytest.raises(ValueError, match="must not be reused"):
        load_reacquire_grant(ROOT / "config/live_authorization.g3-ranked100-history-granted.json")


def test_overlay_freeze_is_extract_ok_with_100_plus_100():
    freeze = load_freeze(FREEZE_PATH)
    overlay = load_signature_overlay(OVERLAY_PATH)
    assert overlay["result"] == EXTRACT_OK
    assert freeze["signature_manifest"]["status"] == EXTRACT_OK
    assert freeze["signature_manifest"]["original_segments_identified"] is True
    assert len(freeze["pages"][0]["signatures"]) == 100
    assert len(freeze["pages"][1]["signatures"]) == 100
    assert freeze["pages"][0]["pagination_token"] == "452802642:577"
    assert freeze["pages"][1]["pagination_token"] == "452554670:596"
    assert request_pagination_token(freeze, 0) is None
    assert request_pagination_token(freeze, 1) == "452802642:577"
    assert freeze["pages"][0]["signatures"][0] == overlay["pages"]["page0"]["signatures"][0]
    assert freeze["pages"][1]["signatures"][-1] == overlay["pages"]["page1"]["signatures"][-1]
    assert freeze["pages"][0]["evidence_sha256"] == "b0fa9cb76a9e9531b5654f4fa22b0e9b7ef9a81ab61fa21bc16a649de0fb492d"
    assert freeze["pages"][1]["evidence_sha256"] == "2cdb237a8adbca04ee4f9e04abd469a525ce499beca1def7e39a3a908244a0fd"
    assert freeze["windows"]["report_end_exclusive"] == "2026-10-05T13:29:27Z"
    assert freeze["encoding_and_version"]["sortOrder"] == "desc"
    merged = apply_overlay(_stop_freeze(), overlay)
    assert merged["signature_manifest"]["status"] == EXTRACT_OK
    assert len(merged["pages"][0]["signatures"]) == 100
    via_path = load_freeze(overlay_path=OVERLAY_PATH)
    assert via_path["pages"][0]["signatures"] == freeze["pages"][0]["signatures"]


def test_out_of_scope_wallets_pages_and_ceilings_are_rejected():
    freeze = load_freeze(FREEZE_PATH)
    assert_wallet_in_scope(freeze, ALLOWED_WALLET)
    with pytest.raises(SourceError, match="one-wallet"):
        assert_wallet_in_scope(freeze, "DSJVxpK1gwZvFsiYdaRz7Ly51vTXnAwHGfLGWcRvVJGE")
    assert_page_in_scope(0)
    assert_page_in_scope(1)
    with pytest.raises(SourceError, match="Page index"):
        assert_page_in_scope(2)
    bloated = deepcopy(load_reacquire_grant())
    bloated["providers"][0]["max_requests"] = 15
    bloated["providers"][0]["max_units"] = 150
    with pytest.raises(ValueError, match="2 requests / 20 credits"):
        assert_grant_ceilings(bloated)


def test_page1_requires_integrity_and_specific_boundary_not_episode_count():
    intact = {"integrity": {"status": "INTACT", "integrity_failure": False}}
    ok, why = page1_allowed(
        intact,
        recorded_reason="missing_earlier_acquisition_boundary",
        mint="Mint111111111111111111111111111111111111111",
        signature="Sig1111111111111111111111111111111111111111111111111111111111111111",
        classification=intact["integrity"],
    )
    assert ok is True and why == "missing_earlier_acquisition_boundary"
    ok, why = page1_allowed(
        intact,
        recorded_reason="insufficient_episodes_pagination_token_present",
        mint="Mint111111111111111111111111111111111111111",
        signature="Sig1111111111111111111111111111111111111111111111111111111111111111",
    )
    assert ok is False and why == "page1_not_for_episode_count_or_pnl"
    ok, why = page1_allowed(
        {"integrity": {"status": "SOURCE_RECORDS_DAMAGED", "integrity_failure": True}},
        recorded_reason="missing_earlier_acquisition_boundary",
        mint="Mint111111111111111111111111111111111111111",
        signature="Sig1111111111111111111111111111111111111111111111111111111111111111",
    )
    assert ok is False and why == "page0_integrity_failed"
    ok, why = page1_allowed(intact, recorded_reason="missing_open_position_boundary")
    assert ok is False and why == "page1_requires_mint_sig_reason"
    stop, reason = should_stop_after_visible_position(completed_positions=1, visible_report=True)
    assert stop is True and reason == "one_completed_position_reconciled"


def test_offline_prep_validates_extract_ok_without_provider_calls(store, monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    setup = store.reserve("helius", "getTransaction", 200, "setup-pilot", 200)
    store.dispatch(setup)
    store.settle(setup)
    result = run_reacquire(store, allow_live=False)
    assert result["status"] == "OFFLINE_PASS"
    assert result["outcome_label"] == OUTCOME_LABEL
    assert result["authorization_id"] == AUTHORIZATION_ID
    assert result["grant_enabled"] is False
    assert result["signature_manifest_status"] == EXTRACT_OK
    assert result["original_segments_identified"] is True
    assert result["page0_signature_count"] == 100
    assert result["page1_signature_count"] == 100
    assert result["external_requests"] == 0
    assert result["PRODUCT_READY"] is False
    assert result["parent_recovery_commit"] == PARENT_RECOVERY_COMMIT
    assert store.usage("helius", "setup-pilot", 200)["remaining"] == 0
    codes = {row["code"] for row in result["arming_blockers"]}
    assert STOP_NO_SEGMENT not in codes
    assert "grant_disabled" in codes
    non = assert_non_grants_stay_disabled()
    assert non["reacquire_enabled"] is False
    assert non["g3_leftover_enabled"] is False


def test_transport_not_called_when_stop_no_segment(store, monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY", "not-a-real-key")
    calls = {"n": 0}

    async def transport(address, **kwargs):
        calls["n"] += 1
        return {"records": [], "pagination_token": None, "http_status": 200}

    result = run_reacquire(
        store,
        allow_live=True,
        grant=armed_test_grant(),
        freeze=_stop_freeze(),
        credentials={"helius": True},
        transport=transport,
    )
    assert result["status"] == "BLOCKED"
    assert result["blocker"] == STOP_NO_SEGMENT
    assert result["external_requests"] == 0
    assert result["helius_requests_used"] == 0
    assert calls["n"] == 0
    assert result["transport_called"] is False


def test_disabled_grant_does_not_attach_or_call_transport(store, monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    calls = {"n": 0}

    async def transport(address, **kwargs):
        calls["n"] += 1
        return {"records": [], "http_status": 200}

    result = run_reacquire(store, allow_live=True, transport=transport)
    assert result["status"] == "BLOCKED"
    assert result["blocker"] == "grant_disabled"
    assert calls["n"] == 0
    assert result["external_requests"] == 0


def test_signature_mismatch_stops_without_page1(store):
    freeze = load_freeze()
    calls = []

    async def transport(address, *, options, page_index):
        calls.append({"page_index": page_index, "token": options.get("paginationToken")})
        return {"records": _records(["mismatchSig11111111111111111111111111111111111111111111111111"]), "http_status": 200}

    result = run_reacquire(
        store,
        allow_live=True,
        grant=armed_test_grant(),
        freeze=freeze,
        credentials={"helius": True},
        transport=transport,
    )
    assert result["status"] == "BLOCKED"
    assert result["blocker"] == SIGNATURE_MISMATCH
    assert result["stop_reason"] == SIGNATURE_MISMATCH
    assert [row["page_index"] for row in calls] == [0]
    assert calls[0]["token"] is None
    assert result["helius_requests_used"] == 1
    assert result["helius_units_used"] == 10
    assert store.usage("helius", "setup-pilot", 200)["used"] == 0


def test_page1_uses_frozen_token_and_skips_episode_count_reason(store):
    freeze = load_freeze()
    calls = []

    async def transport(address, *, options, page_index):
        calls.append({"page_index": page_index, "token": options.get("paginationToken"), "limit": options.get("limit")})
        return {"records": _records(frozen_signatures(freeze, page_index)), "http_status": 200, "pagination_token": freeze["pages"][page_index]["pagination_token"]}

    skipped = run_reacquire(
        store,
        allow_live=True,
        grant=armed_test_grant(),
        freeze=freeze,
        credentials={"helius": True},
        transport=transport,
        page1_request={
            "reason": "insufficient_episodes_pagination_token_present",
            "mint": "Mint111111111111111111111111111111111111111",
            "signature": freeze["pages"][0]["signatures"][-1],
        },
    )
    assert skipped["status"] == "INCOMPLETE"
    assert skipped["page1_gate"]["allowed"] is False
    assert [row["page_index"] for row in calls] == [0]

    store2 = Store(Path(store.path) / "page1")
    calls.clear()
    allowed = run_reacquire(
        store2,
        allow_live=True,
        grant=armed_test_grant(),
        freeze=freeze,
        credentials={"helius": True},
        transport=transport,
        page1_request={
            "reason": "missing_earlier_acquisition_boundary",
            "mint": "Mint111111111111111111111111111111111111111",
            "signature": freeze["pages"][0]["signatures"][-1],
        },
    )
    assert [row["page_index"] for row in calls] == [0, 1]
    assert calls[1]["token"] == "452802642:577"
    assert calls[1]["limit"] == 100
    assert allowed["pages_fetched"] == [0, 1]
    assert allowed["helius_requests_used"] == 2
    assert allowed["helius_units_used"] == 20
    store2.close()


def test_two_failures_consume_ceiling_and_block_third(store):
    import asyncio
    freeze = load_freeze()
    grant = armed_test_grant()
    calls = {"n": 0}

    async def boom(address, **kwargs):
        calls["n"] += 1
        raise TimeoutError("simulated timeout")

    async def once():
        await fetch_reacquire_page(
            store, grant, freeze, ALLOWED_WALLET,
            page_index=0, reason="first_page_frozen_segment", transport=boom,
        )

    for _ in range(2):
        with pytest.raises(SourceError):
            asyncio.run(once())
    assert calls["n"] == 2
    assert store.usage("helius", grant["providers"][0]["cycle_start"], 20)["used"] == 20
    with pytest.raises(SourceError, match="credit ceiling|request ceiling"):
        asyncio.run(once())
    assert calls["n"] == 2


def test_compare_signatures_detects_order_drift():
    freeze = load_freeze()
    page0 = frozen_signatures(freeze, 0)
    ok, _ = compare_signatures(page0, page0)
    assert ok is True
    drifted = [page0[-1]] + page0[:-1]
    ok, detail = compare_signatures(drifted, page0)
    assert ok is False
    assert detail["actual_count"] == 100


def test_extract_missing_or_empty_sqlite_stays_stop_no_segment(tmp_path):
    missing = extract_signatures_from_sqlite(tmp_path / "no.sqlite")
    assert missing["status"] == STOP_NO_SEGMENT
    assert missing["external_requests"] == 0
    store = Store(tmp_path / "data")
    store.close()
    empty = extract_signatures_from_sqlite(tmp_path / "data" / "scanner.sqlite")
    assert empty["status"] == STOP_NO_SEGMENT
    assert empty["pages"][0] == []
    assert empty["pages"][1] == []
    other = extract_signatures_from_sqlite(tmp_path / "data" / "scanner.sqlite", address="So11111111111111111111111111111111111111112")
    assert other["blocker"] == "wallet_out_of_scope"


def test_offline_cli_refuses_live(tmp_path):
    import subprocess
    import sys
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/mass_search_g3_reacquire_offline.py"),
            "--data-dir", str(tmp_path / "data"),
            "--live",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    payload = json.loads(proc.stdout)
    assert payload["blocker"] == "offline_tool_refuses_live"
    assert payload["external_requests"] == 0
    assert payload["PRODUCT_READY"] is False


def test_leftover_g3_loader_rejects_reacquire_id():
    from scanner.mass_search.g3_history import load_g3_grant
    with pytest.raises(ValueError, match="only accepts"):
        load_g3_grant(GRANT_PATH)
