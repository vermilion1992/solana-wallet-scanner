"""Offline G3_INTEGRITY_REACQUIRE_RANK1: new id, one-wallet scope, STOP_NO_SEGMENT."""
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
    FREEZE_PATH,
    GRANT_PATH,
    OUTCOME_LABEL,
    PARENT_RECOVERY_COMMIT,
    STOP_NO_SEGMENT,
    armed_test_grant,
    arming_blockers,
    assert_grant_ceilings,
    assert_non_grants_stay_disabled,
    assert_page_in_scope,
    assert_wallet_in_scope,
    extract_signatures_from_sqlite,
    load_freeze,
    load_reacquire_grant,
    page1_allowed,
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
    assert STOP_NO_SEGMENT in blockers
    assert "signature_manifest_unfrozen" in blockers
    assert "missing_provider_credentials" in blockers


def test_leftover_g3_and_prior_grants_cannot_be_loaded_as_reacquire():
    with pytest.raises(ValueError, match="must not be reused"):
        load_reacquire_grant(ROOT / "config/live_authorization.g1-granted.json")
    with pytest.raises(ValueError, match="must not be reused"):
        load_reacquire_grant(ROOT / "config/live_authorization.g2-ranked100-discovery-granted.json")
    with pytest.raises(ValueError, match="must not be reused"):
        load_reacquire_grant(ROOT / "config/live_authorization.g3-ranked100-history-granted.json")


def test_out_of_scope_wallets_pages_and_ceilings_are_rejected():
    freeze = load_freeze(FREEZE_PATH)
    assert freeze["signature_manifest"]["status"] == STOP_NO_SEGMENT
    assert freeze["pages"][0]["signatures"] == []
    assert freeze["pages"][1]["signatures"] == []
    assert freeze["pages"][0]["evidence_sha256"] == "b0fa9cb76a9e9531b5654f4fa22b0e9b7ef9a81ab61fa21bc16a649de0fb492d"
    assert freeze["pages"][1]["evidence_sha256"] == "2cdb237a8adbca04ee4f9e04abd469a525ce499beca1def7e39a3a908244a0fd"
    assert freeze["windows"]["report_end_exclusive"] == "2026-10-05T13:29:27Z"
    assert freeze["encoding_and_version"]["sortOrder"] == "desc"
    assert freeze["encoding_and_version"]["maxSupportedTransactionVersion"] == 1
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


def test_offline_prep_validates_grant_and_records_stop_no_segment(store, monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    setup = store.reserve("helius", "getTransaction", 200, "setup-pilot", 200)
    store.dispatch(setup)
    store.settle(setup)
    result = run_reacquire(store, allow_live=False)
    assert result["status"] == "OFFLINE_PASS"
    assert result["outcome_label"] == OUTCOME_LABEL
    assert result["authorization_id"] == AUTHORIZATION_ID
    assert result["grant_enabled"] is False
    assert result["signature_manifest_status"] == STOP_NO_SEGMENT
    assert result["original_segments_identified"] is False
    assert result["page0_signature_count"] == 0
    assert result["page1_signature_count"] == 0
    assert result["external_requests"] == 0
    assert result["PRODUCT_READY"] is False
    assert result["parent_recovery_commit"] == PARENT_RECOVERY_COMMIT
    assert store.usage("helius", "setup-pilot", 200)["remaining"] == 0
    codes = {row["code"] for row in result["arming_blockers"]}
    assert STOP_NO_SEGMENT in codes
    assert "grant_disabled" in codes
    non = assert_non_grants_stay_disabled()
    assert non["reacquire_enabled"] is False
    assert non["g3_leftover_enabled"] is False


def test_live_flag_stays_blocked_on_stop_no_segment_even_if_armed(store, monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY", "not-a-real-key")
    result = run_reacquire(store, allow_live=True, grant=armed_test_grant(), credentials={"helius": True})
    assert result["status"] == "BLOCKED"
    assert result["blocker"] == STOP_NO_SEGMENT
    assert result["external_requests"] == 0
    assert result["helius_requests_used"] == 0


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
