"""Offline RANKED100_ANCHORED_VALIDATION draft binding. No live spend."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scanner.mass_search.capability import validate_live_authorization
from scanner.mass_search.g3_history import AUTHORIZATION_ID as G3_LEFTOVER_ID
from scanner.mass_search.g3_reacquire import (
    ALLOWED_WALLET,
    ANCHORED_VALIDATION_AUTHORIZATION_ID,
    ANCHORED_VALIDATION_GRANT_PATH,
    ANCHORED_VALIDATION_OUTCOME,
    AUTHORIZATION_ID,
    FREEZE_PATH,
    GRANT_PATH,
    OVERLAY_PATH,
    PAGE0_SIGNATURE_LTE,
    PAGE1_PAGINATION_TOKEN,
    SIGNATURE_MISMATCH,
    accepted_historical_authorization_ids,
    armed_test_grant,
    arming_blockers,
    assert_grant_ceilings,
    assert_non_grants_stay_disabled,
    frozen_signatures,
    load_anchored_validation_grant,
    load_freeze,
    load_reacquire_grant,
    proposed_historical_requests,
    run_reacquire,
)
from scanner.mass_search.history_ingest import (
    QUARANTINE_KIND,
    SOURCE_CAPTURE_KIND,
    authorised_cache_key,
    quarantine_key,
    source_capture_key,
)
from scanner.storage import Store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "data")
    yield instance
    instance.close()


def _records(signatures):
    return [
        {
            "signature": signature,
            "transaction": {"signatures": [signature], "message": {"accountKeys": [ALLOWED_WALLET]}},
            "meta": {"preTokenBalances": [], "postTokenBalances": [], "preBalances": [], "postBalances": []},
        }
        for signature in signatures
    ]


def test_anchored_validation_grant_is_disabled_not_authorised_and_bound():
    grant = load_anchored_validation_grant()
    checked = validate_live_authorization(grant)
    assert grant["authorization_id"] == ANCHORED_VALIDATION_AUTHORIZATION_ID
    assert grant["authorization_id"] != AUTHORIZATION_ID
    assert grant["enabled"] is False
    assert checked["enabled"] is False
    assert grant["draft_status"] == "DISABLED; NOT AUTHORISED"
    assert grant["authorized_by_user_at"] is None
    assert grant["expires_at"] is None
    assert grant["outcome_label"] == ANCHORED_VALIDATION_OUTCOME
    assert grant["allowed_wallet"] == ALLOWED_WALLET
    assert grant["max_additional_spend_usd"] == "0"
    assert grant["retries"] == 0
    assert grant["no_retries"] is True
    assert grant["max_dispatched_requests"] == 2
    assert grant["max_full_txs_per_call"] == 100
    helius = next(entry for entry in grant["providers"] if entry["provider_id"] == "helius")
    birdeye = next(entry for entry in grant["providers"] if entry["provider_id"] == "birdeye")
    assert helius["max_requests"] == 2 and helius["max_units"] == 20
    assert helius["documented_units_per_request"] == 10
    assert helius["max_concurrency"] == 1
    assert helius["max_duration_seconds"] == 300
    assert helius["retries"] == 0
    assert birdeye["max_requests"] == 0 and birdeye["max_units"] == 0
    assert grant["historical_anchor"]["page0_filters_signature_lte"] == PAGE0_SIGNATURE_LTE
    assert grant["historical_anchor"]["page1_pagination_token"] == PAGE1_PAGINATION_TOKEN
    assert grant["referenced_signature_manifests"]["freeze_path"] == "evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1/FROZEN_SEGMENTS.json"
    assert grant["referenced_signature_manifests"]["overlay_path"] == "evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1/rank1-signature-overlay.json"
    assert grant["referenced_signature_manifests"]["do_not_overwrite"] is True
    assert_grant_ceilings(grant)
    assert ANCHORED_VALIDATION_AUTHORIZATION_ID in accepted_historical_authorization_ids()
    blockers = {row["code"] for row in arming_blockers(grant, credentials={"helius": False})}
    assert "grant_disabled" in blockers
    assert "not_authorised" in blockers
    assert "remaining_quota_unconfirmed" in blockers
    assert "missing_provider_credentials" in blockers


def test_prior_grants_cannot_be_loaded_as_anchored_validation():
    with pytest.raises(ValueError, match="must not be reused"):
        load_anchored_validation_grant(ROOT / "config/live_authorization.g1-granted.json")
    with pytest.raises(ValueError, match="must not be reused"):
        load_anchored_validation_grant(ROOT / "config/live_authorization.g2-ranked100-discovery-granted.json")
    with pytest.raises(ValueError, match="must not be reused"):
        load_anchored_validation_grant(ROOT / "config/live_authorization.g3-ranked100-history-granted.json")
    with pytest.raises(ValueError, match="must not be reused"):
        load_anchored_validation_grant(GRANT_PATH)
    with pytest.raises(ValueError, match="must not be reused"):
        load_reacquire_grant(ANCHORED_VALIDATION_GRANT_PATH)


def test_anchored_validation_ceilings_reject_widening():
    bloated = dict(load_anchored_validation_grant())
    bloated["providers"] = [dict(entry) for entry in bloated["providers"]]
    bloated["providers"][0] = dict(bloated["providers"][0])
    bloated["providers"][0]["max_requests"] = 15
    bloated["providers"][0]["max_units"] = 150
    with pytest.raises(ValueError, match="2 requests / 20 credits"):
        assert_grant_ceilings(bloated)
    reused = dict(load_anchored_validation_grant())
    reused["reacquire_authorization_id_forbidden"] = "wrong"
    with pytest.raises(ValueError, match="must not reuse the reacquire"):
        assert_grant_ceilings(reused)


def test_offline_prep_uses_new_grant_id_and_frozen_manifests(store, monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY_PATH.read_text(encoding="utf-8"))
    assert freeze["authorization_id"] == AUTHORIZATION_ID
    assert overlay["authorization_id"] == AUTHORIZATION_ID
    grant = load_anchored_validation_grant()
    result = run_reacquire(store, allow_live=False, grant=grant)
    assert result["status"] == "OFFLINE_PASS"
    assert result["authorization_id"] == ANCHORED_VALIDATION_AUTHORIZATION_ID
    assert result["outcome_label"] == ANCHORED_VALIDATION_OUTCOME
    assert result["grant_enabled"] is False
    assert result["external_requests"] == 0
    assert result["PRODUCT_READY"] is False
    assert result["allowed_wallet"] == ALLOWED_WALLET
    assert result["page0_signature_count"] == 100
    assert result["page1_signature_count"] == 100
    assert result["pagination_tokens"]["page0"] == PAGE1_PAGINATION_TOKEN
    proposed = proposed_historical_requests()
    page0 = proposed["page0"]["params"][1]
    page1 = proposed["page1"]["params"][1]
    assert page0["filters"]["signature"]["lte"] == PAGE0_SIGNATURE_LTE
    assert "until" not in page0
    assert page1["paginationToken"] == PAGE1_PAGINATION_TOKEN
    assert "until" not in page1
    assert proposed["page0"]["secrets"] is False
    assert "api-key" not in json.dumps(proposed).lower()
    non = assert_non_grants_stay_disabled()
    assert non["anchored_validation_enabled"] is False
    assert non["reacquire_enabled"] is False
    assert G3_LEFTOVER_ID != ANCHORED_VALIDATION_AUTHORIZATION_ID


def test_anchored_validation_mismatch_quarantines_under_new_grant_id(store, tmp_path):
    freeze = load_freeze()
    calls = []
    evidence_dir = tmp_path / "anchored-mismatch"

    async def transport(address, *, options, page_index):
        calls.append({
            "page_index": page_index,
            "token": options.get("paginationToken"),
            "until": options.get("until"),
            "signature_lte": ((options.get("filters") or {}).get("signature") or {}).get("lte"),
        })
        newer = ["newerTipSig111111111111111111111111111111111111111111111111111"]
        return {"records": _records(newer + frozen_signatures(freeze, page_index)[1:]), "http_status": 200}

    result = run_reacquire(
        store,
        allow_live=True,
        grant=armed_test_grant(load_anchored_validation_grant()),
        freeze=freeze,
        credentials={"helius": True},
        transport=transport,
        evidence_dir=evidence_dir,
    )
    assert result["status"] == "BLOCKED"
    assert result["blocker"] == SIGNATURE_MISMATCH
    assert result["authorization_id"] == ANCHORED_VALIDATION_AUTHORIZATION_ID
    assert [row["page_index"] for row in calls] == [0]
    assert calls[0]["until"] is None
    assert calls[0]["signature_lte"] == PAGE0_SIGNATURE_LTE
    capture = store.get(SOURCE_CAPTURE_KIND, source_capture_key(ANCHORED_VALIDATION_AUTHORIZATION_ID, ALLOWED_WALLET, 0))
    assert capture is not None
    quarantined = store.get(QUARANTINE_KIND, quarantine_key(ANCHORED_VALIDATION_AUTHORIZATION_ID, ALLOWED_WALLET, 0))
    assert quarantined is not None
    assert quarantined["analysed"] is False
    assert store.get("mass_search_cache", authorised_cache_key(ANCHORED_VALIDATION_AUTHORIZATION_ID, ALLOWED_WALLET, 0)) is None
    assert store.get(SOURCE_CAPTURE_KIND, source_capture_key(AUTHORIZATION_ID, ALLOWED_WALLET, 0)) is None
