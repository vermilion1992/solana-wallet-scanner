"""G3_INTEGRITY_REACQUIRE_RANK1: one-wallet integrity reacquire, offline default.

Repo grant template stays disabled. Leftover G3_RANKED100_HISTORY (15/150) must
not be reused. Live HTTP is refused unless original rank-1 signatures are
frozen, a local armed grant is present, and Helius quota is confirmed.
Returned signatures must match the frozen manifest; mismatch stops the run.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from copy import deepcopy
from pathlib import Path

import httpx

from scanner.investigation import decode_supported_swaps
from scanner.storage import QuotaExceeded

from .adapters import SourceError
from .capability import (
    LIVE_AUTH_SCHEMA,
    utc_now,
    validate_live_authorization,
)
from .evidence_integrity import (
    CACHE_KEY_PREFIX_V1,
    CACHE_KEY_PREFIX_V2,
    PAGE_KIND_V2,
    SOURCE_RECORDS_DAMAGED,
    SOURCE_RECORDS_INTACT,
    sanitize_jsonrpc_body,
    sanitize_transaction_records,
)
from .g3_history import (
    AUTHORIZATION_ID as G3_LEFTOVER_AUTHORIZATION_ID,
    DRAFT_PATH,
    EXAMPLE_PATH,
    G1_AUTHORIZATION_ID,
    GRANT_PATH as G3_LEFTOVER_GRANT_PATH,
    RANKED100_AUTHORIZATION_ID,
    RANKED100_GRANT_PATH,
    _count_method,
    completed_episodes,
    completed_position_episodes,
    decoder_events_by_mint,
    independent_fifo_worksheet,
)
from .history_ingest import (
    HISTORICAL_ANCHOR_REQUIRED,
    assert_gta_options_not_widened,
    assert_historical_request_anchored,
    build_historical_gta_options,
    dispatch_historical_transport,
    ingest_fetched_historical_page,
    persist_credential_free_source,
    proposed_sanitised_historical_request,
    replay_cached_history_to_report,
    source_capture_key as ingest_source_capture_key,
    visible_report_allowed,
)

ROOT = Path(__file__).resolve().parents[2]
GRANT_PATH = ROOT / "config" / "live_authorization.g3-integrity-reacquire-rank1-draft.json"
FREEZE_PATH = ROOT / "evidence" / "mass-wallet-funnel" / "g3-integrity-reacquire-rank1" / "FROZEN_SEGMENTS.json"
OVERLAY_PATH = ROOT / "evidence" / "mass-wallet-funnel" / "g3-integrity-reacquire-rank1" / "rank1-signature-overlay.json"

OUTCOME_LABEL = "G3_INTEGRITY_REACQUIRE_RANK1"
AUTHORIZATION_ID = "live-g3-integrity-reacquire-rank1-2026-10-06-mitch"
ALLOWED_WALLET = "25865JdBJVVLbt6Kfe4KnKrVCy8UVCYFRRBAPvmJ17LL"
PARENT_RECOVERY_COMMIT = "fe6a398a40c59d1e1afcb3788c3ccba00d936779"
HELIUS_KEY_ENV = "HELIUS_API_KEY"
HELIUS_ENDPOINT = "https://mainnet.helius-rpc.com/"
HELIUS_METHOD = "getTransactionsForAddress"
DOCUMENTED_HELIUS_UNITS = 10
MAX_WALLETS = 1
MAX_REQUESTS = 2
MAX_UNITS = 20
MAX_TXS_PER_CALL = 100
MAX_DURATION_SECONDS = 300
MAX_PAGE_INDEX = 1
CACHE_KIND = "mass_search_cache"
SOURCE_CAPTURE_KIND = "mass_search_source_capture"

EXACT_HELIUS_OPTIONS = {
    "transactionDetails": "full",
    "limit": 100,
    "sortOrder": "desc",
    "commitment": "finalized",
    "maxSupportedTransactionVersion": 1,
    "filters": {"status": "any", "tokenAccounts": "all"},
}

FORBIDDEN_PAGE1_REASONS = {
    "insufficient_episodes_pagination_token_present",
    "below_g3_bar",
    "better_pnl",
    "fewer_than_10_episodes",
}
ALLOWED_PAGE1_REASONS = {
    "missing_earlier_acquisition_boundary",
    "missing_open_position_boundary",
}
STOP_NO_SEGMENT = "STOP_NO_SEGMENT"
EXTRACT_OK = "EXTRACT_OK"
SIGNATURE_MISMATCH = "SIGNATURE_MISMATCH"


def _provider(grant, provider_id):
    for entry in grant.get("providers") or []:
        if entry.get("provider_id") == provider_id:
            return entry
    return None


def assert_grant_ceilings(grant):
    if grant.get("authorization_id") != AUTHORIZATION_ID:
        raise ValueError("Reacquire grant authorization_id mismatch")
    if grant.get("max_additional_spend_usd") != "0":
        raise ValueError("Reacquire grant forbids additional spend")
    if grant.get("do_not_reset_setup_pilot") is not True:
        raise ValueError("Reacquire grant must leave setup-pilot untouched")
    if grant.get("allowed_wallet") != ALLOWED_WALLET:
        raise ValueError("Reacquire grant wallet scope mismatch")
    if int(grant.get("max_wallet_investigations") or 0) != MAX_WALLETS:
        raise ValueError("Reacquire grant allows exactly one wallet")
    if int(grant.get("max_dispatched_requests") or 0) > MAX_REQUESTS:
        raise ValueError("Reacquire grant exceeds max 2 dispatched requests")
    if int(grant.get("max_requests_per_wallet") or 0) > MAX_REQUESTS:
        raise ValueError("Reacquire grant exceeds max 2 requests per wallet")
    helius = _provider(grant, "helius")
    if helius is None:
        raise ValueError("Reacquire grant requires a Helius budget")
    if helius.get("max_requests") != MAX_REQUESTS or helius.get("max_units") != MAX_UNITS:
        raise ValueError("Helius ceilings must be 2 requests / 20 credits")
    if helius.get("documented_units_per_request") != DOCUMENTED_HELIUS_UNITS:
        raise ValueError("Documented GTA cost must remain 10 credits")
    if helius.get("max_concurrency") != 1:
        raise ValueError("Reacquire concurrency must be 1")
    if helius.get("max_duration_seconds") != MAX_DURATION_SECONDS:
        raise ValueError("Reacquire max duration must be 300 seconds")
    if helius.get("allowed_operations") != [HELIUS_METHOD]:
        raise ValueError("Reacquire allows getTransactionsForAddress only")
    if int(grant.get("max_full_txs_per_call") or 0) != MAX_TXS_PER_CALL:
        raise ValueError("Reacquire max full txs/call must be 100")
    query = (grant.get("exact_query") or {}).get("params") or {}
    if {k: query[k] for k in EXACT_HELIUS_OPTIONS if k in query} != EXACT_HELIUS_OPTIONS:
        raise ValueError("Reacquire exact_query params drifted from frozen GTA encoding")
    birdeye = _provider(grant, "birdeye")
    if birdeye is None or birdeye.get("max_requests") != 0 or birdeye.get("max_units") != 0:
        raise ValueError("Birdeye must remain 0/0 on the reacquire grant")
    if birdeye.get("allowed_operations"):
        raise ValueError("Birdeye operations must stay empty")
    leftover = grant.get("g3_leftover_authorization_id_forbidden")
    if leftover != G3_LEFTOVER_AUTHORIZATION_ID:
        raise ValueError("Grant must explicitly forbid leftover G3_RANKED100_HISTORY reuse")
    return True


def load_reacquire_grant(path=None):
    payload = json.loads(Path(path or GRANT_PATH).read_text(encoding="utf-8"))
    if payload.get("schema_version") != LIVE_AUTH_SCHEMA:
        raise ValueError("Grant must use live-research-authorization-v1")
    forbidden = {
        G1_AUTHORIZATION_ID,
        RANKED100_AUTHORIZATION_ID,
        G3_LEFTOVER_AUTHORIZATION_ID,
    }
    if payload.get("authorization_id") in forbidden:
        raise ValueError("G1, ranked-100, and leftover G3 grants must not be reused for reacquire")
    if payload.get("authorization_id") != AUTHORIZATION_ID:
        raise ValueError("This runner only accepts live-g3-integrity-reacquire-rank1-2026-10-06-mitch")
    assert_grant_ceilings(payload)
    return payload


def _page_from_overlay(overlay, page_index):
    pages = overlay.get("pages") or {}
    if isinstance(pages, dict):
        return pages.get(f"page{page_index}") or pages.get(str(page_index))
    if isinstance(pages, list) and len(pages) > page_index:
        return pages[page_index]
    return None


def load_signature_overlay(path=None):
    payload = json.loads(Path(path or OVERLAY_PATH).read_text(encoding="utf-8"))
    if payload.get("kind") != "g3-integrity-reacquire-rank1-signature-overlay-v1":
        raise ValueError("Unsupported signature overlay schema")
    if payload.get("authorization_id") != AUTHORIZATION_ID:
        raise ValueError("Overlay authorization_id mismatch")
    if payload.get("wallet") != ALLOWED_WALLET:
        raise ValueError("Overlay wallet is outside the one-wallet reacquire scope")
    page0 = _page_from_overlay(payload, 0) or {}
    page1 = _page_from_overlay(payload, 1) or {}
    if len(page0.get("signatures") or []) != 100 or len(page1.get("signatures") or []) != 100:
        raise ValueError("Overlay must contain 100+100 original signatures")
    if page0.get("evidence_sha256") != "b0fa9cb76a9e9531b5654f4fa22b0e9b7ef9a81ab61fa21bc16a649de0fb492d":
        raise ValueError("Overlay page0 evidence_sha256 does not match the frozen historical page")
    if page1.get("evidence_sha256") != "2cdb237a8adbca04ee4f9e04abd469a525ce499beca1def7e39a3a908244a0fd":
        raise ValueError("Overlay page1 evidence_sha256 does not match the frozen historical page")
    if not page0.get("pagination_token") or not page1.get("pagination_token"):
        raise ValueError("Overlay must include intact pagination tokens")
    return payload


def apply_overlay(freeze, overlay):
    updated = deepcopy(freeze)
    for page_index, key in ((0, "page0"), (1, "page1")):
        src = _page_from_overlay(overlay, page_index) or {}
        dest = updated["pages"][page_index]
        dest["signatures"] = list(src.get("signatures") or [])
        dest["signature_count_frozen"] = len(dest["signatures"])
        dest["pagination_token"] = src.get("pagination_token")
        dest["pagination_token_status"] = "FROZEN_FROM_BOX_EXTRACT"
        dest["balances_status"] = src.get("balances_status") or SOURCE_RECORDS_DAMAGED
        if src.get("slot_min") is not None:
            dest["slot_min"] = src["slot_min"]
            dest["slot_max"] = src["slot_max"]
        if src.get("blockTime_min") is not None:
            dest["blockTime_min"] = src["blockTime_min"]
            dest["blockTime_max"] = src["blockTime_max"]
    updated["pages"][1]["request_pagination_token"] = updated["pages"][0].get("pagination_token")
    updated["signature_manifest"] = {
        **(updated.get("signature_manifest") or {}),
        "status": EXTRACT_OK,
        "original_segments_identified": True,
        "page0_signature_count": 100,
        "page1_signature_count": 100,
        "pagination_tokens_frozen_from_box_extract": True,
        "token_balances": SOURCE_RECORDS_DAMAGED,
        "overlay_kind": overlay.get("kind"),
        "overlay_extracted_at": overlay.get("extracted_at"),
        "overlay_result": overlay.get("result") or EXTRACT_OK,
        "do_not_substitute_current_latest_history": True,
    }
    return updated


def load_freeze(path=None, overlay_path=None):
    payload = json.loads(Path(path or FREEZE_PATH).read_text(encoding="utf-8"))
    if payload.get("kind") != "g3-integrity-reacquire-rank1-freeze-v1":
        raise ValueError("Unsupported reacquire freeze schema")
    if payload.get("authorization_id") != AUTHORIZATION_ID:
        raise ValueError("Freeze authorization_id mismatch")
    if payload.get("parent_recovery_commit") != PARENT_RECOVERY_COMMIT:
        raise ValueError("Freeze parent_recovery_commit must remain fe6a398a40c59d1e1afcb3788c3ccba00d936779")
    if payload.get("allowed_wallet") != ALLOWED_WALLET:
        raise ValueError("Freeze wallet must remain the original rank-1 address")
    if overlay_path is not None:
        payload = apply_overlay(payload, load_signature_overlay(overlay_path))
    pages = payload.get("pages") or []
    if [row.get("page_index") for row in pages] != [0, 1]:
        raise ValueError("Freeze must describe original pages 0 and 1 only")
    if any(row.get("address") != ALLOWED_WALLET for row in pages):
        raise ValueError("Freeze pages must stay on the rank-1 wallet")
    encoding = payload.get("encoding_and_version") or {}
    for key, expected in EXACT_HELIUS_OPTIONS.items():
        if encoding.get(key) != expected:
            raise ValueError(f"Frozen encoding drifted at {key}")
    windows = payload.get("windows") or {}
    if windows.get("report_end_exclusive") != "2026-10-05T13:29:27Z":
        raise ValueError("Report-end must stay the original discovery cutoff")
    if windows.get("report_start_inclusive") != "2026-09-05T13:29:27Z":
        raise ValueError("Report-start must stay 30 days before cutoff")
    if windows.get("acquisition_support_start_inclusive") != "2026-07-07T13:29:27Z":
        raise ValueError("Acquisition-support start must stay 90 days before cutoff")
    manifest = payload.get("signature_manifest") or {}
    if manifest.get("status") != STOP_NO_SEGMENT:
        if not manifest.get("original_segments_identified"):
            raise ValueError("Signature manifest cannot claim readiness without identified segments")
        page0 = pages[0].get("signatures") or []
        page1 = pages[1].get("signatures") or []
        if len(page0) != 100 or len(page1) != 100:
            raise ValueError("Ready signature manifests must freeze 100 signatures per original page")
        if not pages[0].get("pagination_token") or not pages[1].get("pagination_token"):
            raise ValueError("Ready freeze must include intact pagination tokens")
    return payload


def assert_wallet_in_scope(freeze, address):
    if address != (freeze or {}).get("allowed_wallet") or address != ALLOWED_WALLET:
        raise SourceError("UNAUTHORIZED", "Address is outside the one-wallet reacquire scope")
    return True


def assert_page_in_scope(page_index):
    if page_index not in (0, 1):
        raise SourceError("UNAUTHORIZED", "Page index is outside the frozen 0/1 reacquire scope")
    return True


def assert_non_grants_stay_disabled():
    example = validate_live_authorization(json.loads(EXAMPLE_PATH.read_text(encoding="utf-8")))
    draft = validate_live_authorization(json.loads(DRAFT_PATH.read_text(encoding="utf-8")))
    ranked = validate_live_authorization(json.loads(RANKED100_GRANT_PATH.read_text(encoding="utf-8")))
    leftover = validate_live_authorization(json.loads(G3_LEFTOVER_GRANT_PATH.read_text(encoding="utf-8")))
    reacquire = validate_live_authorization(json.loads(GRANT_PATH.read_text(encoding="utf-8")))
    if any(row.get("enabled") for row in (example, draft, ranked, leftover, reacquire)):
        raise ValueError("Example, proof-draft, ranked-100, leftover G3, or reacquire grant is enabled")
    return {
        "example_enabled": False,
        "draft_enabled": False,
        "ranked100_enabled": False,
        "g3_leftover_enabled": False,
        "reacquire_enabled": False,
        "g1_not_reused": True,
        "ranked100_not_reused": True,
        "g3_leftover_not_reused": True,
    }


def signature_manifest_status(freeze=None):
    freeze = freeze if freeze is not None else load_freeze()
    manifest = freeze.get("signature_manifest") or {}
    return manifest.get("status") or STOP_NO_SEGMENT


def original_segments_identified(freeze=None):
    freeze = freeze if freeze is not None else load_freeze()
    manifest = freeze.get("signature_manifest") or {}
    pages = freeze.get("pages") or []
    if manifest.get("status") == STOP_NO_SEGMENT:
        return False
    if not manifest.get("original_segments_identified"):
        return False
    if not all(len(row.get("signatures") or []) == 100 for row in pages):
        return False
    return all(bool(row.get("pagination_token")) for row in pages)


def frozen_signatures(freeze, page_index):
    pages = freeze.get("pages") or []
    if page_index >= len(pages):
        return []
    return list(pages[page_index].get("signatures") or [])


def request_pagination_token(freeze, page_index):
    """Page 0 originally had no token; page 1 uses the token returned with page 0."""
    if page_index == 0:
        return None
    if page_index == 1:
        pages = freeze.get("pages") or []
        explicit = pages[1].get("request_pagination_token") if len(pages) > 1 else None
        return explicit or (pages[0].get("pagination_token") if pages else None)
    return None


def proposed_historical_requests(freeze=None):
    """Sanitised outgoing requests for any later live historical work. No secrets."""
    freeze = freeze if freeze is not None else load_freeze()
    page0 = frozen_signatures(freeze, 0)
    page1 = frozen_signatures(freeze, 1)
    return {
        "page0": proposed_sanitised_historical_request(
            ALLOWED_WALLET, page_index=0, expected_signatures=page0,
        ),
        "page1": proposed_sanitised_historical_request(
            ALLOWED_WALLET,
            page_index=1,
            expected_signatures=page1,
            pagination_token=request_pagination_token(freeze, 1),
        ),
        "PRODUCT_READY": False,
        "not_a_live_grant": True,
    }


def page1_allowed(page0, *, recorded_reason, mint=None, signature=None, classification=None):
    """Page 1 needs intact page 0 plus a specific missing-boundary reason."""
    classification = classification or (page0 or {}).get("integrity") or {}
    if classification.get("integrity_failure") or classification.get("status") in {
        SOURCE_RECORDS_DAMAGED, "MALFORMED",
    }:
        return False, "page0_integrity_failed"
    if recorded_reason in FORBIDDEN_PAGE1_REASONS or not recorded_reason:
        return False, "page1_not_for_episode_count_or_pnl"
    if recorded_reason not in ALLOWED_PAGE1_REASONS:
        return False, "page1_reason_not_acquisition_or_position_boundary"
    if not mint or not signature:
        return False, "page1_requires_mint_sig_reason"
    if classification.get("status") and classification.get("status") not in {"INTACT", SOURCE_RECORDS_INTACT}:
        return False, "page0_not_intact"
    return True, recorded_reason


def should_stop_after_visible_position(*, completed_positions, visible_report):
    if completed_positions >= 1 and visible_report:
        return True, "one_completed_position_reconciled"
    return False, None


def infer_missing_boundary(by_mint, counted=None):
    """Only a specific missing acquisition/position boundary, never episode-count/PnL."""
    counted = counted or {}
    details = counted.get("per_mint_detail") or {}
    for mint, rows in (by_mint or {}).items():
        dated = [row for row in rows if not row.get("timestamp_missing")]
        if not dated:
            continue
        ordered = sorted(dated, key=lambda row: (row.get("seconds_from_start") is None, row.get("seconds_from_start") or 0, row.get("signature") or ""))
        first = ordered[0]
        signature = first.get("signature")
        if not signature:
            continue
        if first.get("kind") == "sell":
            return {
                "reason": "missing_open_position_boundary",
                "mint": mint,
                "signature": signature,
            }
        detail = details.get(mint) or completed_position_episodes(dated)
        if detail.get("unsupported_sale_exceeds_inventory"):
            return {
                "reason": "missing_earlier_acquisition_boundary",
                "mint": mint,
                "signature": signature,
            }
    return None


def arming_blockers(grant, *, credentials=None, freeze=None):
    blockers = []
    if grant.get("authorization_id") in {
        G1_AUTHORIZATION_ID, RANKED100_AUTHORIZATION_ID, G3_LEFTOVER_AUTHORIZATION_ID,
    }:
        blockers.append({
            "code": "prior_grant_reuse_forbidden",
            "detail": "G1, ranked-100, and leftover G3 grants must not be reused",
        })
        return blockers
    if grant.get("authorization_id") != AUTHORIZATION_ID:
        blockers.append({"code": "unexpected_authorization_id", "detail": grant.get("authorization_id")})
    if grant.get("enabled") is not True:
        blockers.append({
            "code": "grant_disabled",
            "detail": "Repo reacquire template stays enabled:false; arm only a local uncommitted copy on the secure box",
        })
    expires = grant.get("expires_at")
    if isinstance(expires, str) and expires and expires <= utc_now():
        blockers.append({"code": "grant_expired", "detail": expires})
    try:
        assert_grant_ceilings(grant)
    except ValueError as error:
        blockers.append({"code": "ceiling_or_scope_mismatch", "detail": str(error)})
    helius = _provider(grant, "helius")
    if helius is None:
        blockers.append({"code": "missing_helius_budget", "detail": "Helius ceiling is required"})
    else:
        if helius.get("existing_plan_confirmed") is not True:
            blockers.append({
                "code": "existing_plan_unconfirmed",
                "detail": "Operator must confirm the existing Helius plan and getTransactionsForAddress entitlement",
            })
        if not helius.get("remaining_quota_confirmed_at"):
            blockers.append({
                "code": "remaining_quota_unconfirmed",
                "detail": "Operator must confirm remaining Helius credits; leftover G3 units must not be reused",
            })
        if helius.get("max_requests") != MAX_REQUESTS or helius.get("max_units") != MAX_UNITS:
            blockers.append({"code": "helius_ceiling_mismatch", "detail": "Helius must be 2 requests / 20 credits"})
    birdeye = _provider(grant, "birdeye")
    if birdeye is not None and (birdeye.get("max_requests") != 0 or birdeye.get("max_units") != 0):
        blockers.append({"code": "birdeye_must_be_zero", "detail": "This grant forbids new discovery"})
    if grant.get("max_additional_spend_usd") != "0":
        blockers.append({"code": "paid_spend_forbidden", "detail": "max_additional_spend_usd must be 0"})
    presence = credentials if credentials is not None else {
        "helius": bool(os.environ.get(HELIUS_KEY_ENV) or os.environ.get("HELIUS_KEY")),
    }
    if not presence.get("helius"):
        blockers.append({"code": "missing_provider_credentials", "detail": "HELIUS_API_KEY is absent in this runtime"})
    freeze = freeze if freeze is not None else load_freeze()
    if not original_segments_identified(freeze):
        blockers.append({
            "code": STOP_NO_SEGMENT,
            "detail": "Original rank-1 page 0/1 signatures are not frozen; newest-first GTA now would substitute current/latest history",
        })
        blockers.append({
            "code": "signature_manifest_unfrozen",
            "detail": "Do not dispatch until 100+100 original signatures are recovered without inventing them",
        })
    return blockers


def armed_test_grant(base=None):
    """In-memory grant for tests. Never writes enabled=true to disk."""
    payload = deepcopy(base or json.loads(GRANT_PATH.read_text(encoding="utf-8")))
    payload["enabled"] = True
    payload["expires_at"] = "2099-01-01T00:00:00Z"
    for entry in payload["providers"]:
        if entry["provider_id"] == "helius":
            entry["existing_plan_confirmed"] = True
            entry["remaining_quota_confirmed_at"] = payload["authorized_by_user_at"]
    return validate_live_authorization(payload)


def _collect_signatures(node, found):
    if isinstance(node, dict):
        value = node.get("signature")
        if isinstance(value, str) and value and value != "[REDACTED]":
            found.append(value)
        sigs = node.get("signatures")
        if isinstance(sigs, list):
            for item in sigs:
                if isinstance(item, str) and item and item != "[REDACTED]":
                    found.append(item)
        for key, child in node.items():
            if key in {"signature", "signatures"}:
                continue
            _collect_signatures(child, found)
    elif isinstance(node, list):
        for child in node:
            _collect_signatures(child, found)


def record_signatures(records):
    ordered = []
    seen = set()
    for item in records or []:
        found = []
        if isinstance(item, dict):
            if isinstance(item.get("signature"), str):
                found.append(item["signature"])
            tx = item.get("transaction") if isinstance(item.get("transaction"), dict) else {}
            raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
            for block in (item, tx, raw, raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}):
                sigs = block.get("signatures") if isinstance(block, dict) else None
                if isinstance(sigs, list) and sigs and isinstance(sigs[0], str):
                    found.append(sigs[0])
                if isinstance(block, dict) and isinstance(block.get("signature"), str):
                    found.append(block["signature"])
        for signature in found:
            if signature and signature != "[REDACTED]" and signature not in seen:
                seen.add(signature)
                ordered.append(signature)
                break
    return ordered


def compare_signatures(actual, expected):
    actual = list(actual or [])
    expected = list(expected or [])
    if actual == expected:
        return True, {"matched": len(actual)}
    return False, {
        "actual_count": len(actual),
        "expected_count": len(expected),
        "first_actual": actual[0] if actual else None,
        "first_expected": expected[0] if expected else None,
        "prefix_match": len(os.path.commonprefix([actual, expected])) if actual and expected else 0,
    }


def extract_signatures_from_sqlite(sqlite_path, *, address=ALLOWED_WALLET):
    """Read-only recovery from a local G3 cache. Zero provider calls."""
    path = Path(sqlite_path)
    result = {
        "status": STOP_NO_SEGMENT,
        "sqlite_path": str(path),
        "address": address,
        "external_requests": 0,
        "pages": {0: [], 1: []},
        "page_found": {0: False, 1: False},
        "PRODUCT_READY": False,
    }
    if address != ALLOWED_WALLET:
        result["blocker"] = "wallet_out_of_scope"
        return result
    if not path.is_file():
        result["blocker"] = "sqlite_missing"
        return result
    keys = []
    leftover_id = G3_LEFTOVER_AUTHORIZATION_ID
    for prefix in (CACHE_KEY_PREFIX_V1, CACHE_KEY_PREFIX_V2):
        for page_index in (0, 1):
            keys.append((page_index, f"{prefix}{leftover_id}:{address}:page:{page_index}"))
            keys.append((page_index, f"{prefix}{AUTHORIZATION_ID}:{address}:page:{page_index}"))
    try:
        connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    except sqlite3.Error:
        result["blocker"] = "sqlite_unreadable"
        return result
    try:
        for page_index, cache_id in keys:
            row = connection.execute(
                "SELECT payload FROM records WHERE kind=? AND id=?",
                (CACHE_KIND, cache_id),
            ).fetchone()
            if not row:
                continue
            result["page_found"][page_index] = True
            try:
                payload = json.loads(row[0])
            except json.JSONDecodeError:
                continue
            found = []
            _collect_signatures(payload, found)
            ordered = []
            seen = set()
            for signature in found:
                if signature not in seen:
                    seen.add(signature)
                    ordered.append(signature)
            if ordered and not result["pages"][page_index]:
                result["pages"][page_index] = ordered
    finally:
        connection.close()
    page0 = result["pages"][0]
    page1 = result["pages"][1]
    if len(page0) == 100 and len(page1) == 100:
        result["status"] = "LOCAL_SIGNATURES_RECOVERED"
        result["detail"] = (
            "Local damaged cache produced 100+100 signatures. Compare them to the "
            "frozen overlay before any live dispatch. Newest-first GTA now is still forbidden."
        )
    else:
        result["detail"] = (
            f"Local sqlite did not yield 100+100 original signatures "
            f"(page0={len(page0)}, page1={len(page1)})."
        )
    return result


def application_commit(repo=ROOT):
    head = repo / ".git" / "HEAD"
    if not head.is_file():
        return None
    ref = head.read_text(encoding="utf-8").strip()
    if ref.startswith("ref:"):
        ref_path = repo / ".git" / ref.split(" ", 1)[1]
        if ref_path.is_file():
            return ref_path.read_text(encoding="utf-8").strip()
        return None
    return ref


def used_helius_requests(store, grant):
    entry = _provider(grant, "helius")
    if store is None or entry is None:
        return 0
    return _count_method(store, "helius", entry["cycle_start"], HELIUS_METHOD)


def used_helius_units(store, grant):
    entry = _provider(grant, "helius")
    if store is None or entry is None:
        return 0
    return int(store.usage("helius", entry["cycle_start"], entry["max_units"])["used"])


def page_cache_key(authorization_id, address, page_index):
    return f"{CACHE_KEY_PREFIX_V2}{authorization_id}:{address}:page:{page_index}"


def source_capture_key(authorization_id, address, page_index):
    return ingest_source_capture_key(authorization_id, address, page_index)


def assert_options_not_widened(options):
    return assert_gta_options_not_widened(options)


async def helius_gta_http(address, *, options, page_index):
    """Live Helius transport. Never logs the key. Cloud agents must not call this."""
    key = os.environ.get(HELIUS_KEY_ENV) or os.environ.get("HELIUS_KEY")
    if not key:
        raise SourceError("UNAUTHORIZED", "HELIUS_API_KEY is not present in this runtime")
    assert_wallet_in_scope({"allowed_wallet": ALLOWED_WALLET}, address)
    assert_page_in_scope(page_index)
    assert_options_not_widened(options)
    payload = {"jsonrpc": "2.0", "id": 1, "method": HELIUS_METHOD, "params": [address, options]}
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(40, connect=10)) as client:
            response = await client.post(HELIUS_ENDPOINT, params={"api-key": key}, json=payload)
    except httpx.TransportError as error:
        raise SourceError("UNAVAILABLE", "Helius connection failed") from error
    status = response.status_code
    if status in (401, 403):
        raise SourceError("ENTITLEMENT_BLOCKED", "Helius rejected the key or plan", http_status=status)
    if status == 429:
        raise SourceError("RATE_LIMITED", "Helius rate limit", http_status=status)
    try:
        body = response.json()
    except ValueError as error:
        raise SourceError("UNSUPPORTED_SCHEMA", "Helius returned non-JSON", http_status=status) from error
    if status != 200 or not isinstance(body, dict):
        raise SourceError("UNSUPPORTED_SCHEMA", "Unexpected Helius response", http_status=status)
    if body.get("error"):
        code = (body.get("error") or {}).get("code") if isinstance(body.get("error"), dict) else None
        if code == -32601:
            raise SourceError("ENTITLEMENT_BLOCKED", "getTransactionsForAddress is unavailable for this account")
        raise SourceError("UNAVAILABLE", "Helius rejected getTransactionsForAddress")
    result = body.get("result") or {}
    data = result.get("data") if isinstance(result, dict) else None
    if data is None and isinstance(result, list):
        data = result
    if not isinstance(data, list):
        data = []
    cleaned = sanitize_jsonrpc_body(body)
    cleaned_result = cleaned.get("result") or {}
    cleaned_data = cleaned_result.get("data") if isinstance(cleaned_result, dict) else None
    if cleaned_data is None and isinstance(cleaned_result, list):
        cleaned_data = cleaned_result
    if not isinstance(cleaned_data, list):
        cleaned_data = data
    raw_bytes = json.dumps(cleaned, sort_keys=True, separators=(",", ":")).encode()
    return {
        "records": cleaned_data,
        "pagination_token": result.get("paginationToken") if isinstance(result, dict) else None,
        "evidence_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "http_status": status,
        "cleaned_body": cleaned,
        "external_requests": 1,
    }


def persist_source_capture(store, evidence_dir, authorization_id, address, page_index, capture):
    payload = dict(capture)
    if "signatures" not in payload:
        payload["signatures"] = record_signatures(payload.get("records") or [])
    return persist_credential_free_source(
        store, evidence_dir, authorization_id, address, page_index, payload,
    )


async def fetch_reacquire_page(store, grant, freeze, address, *, page_index, reason, transport, evidence_dir=None):
    assert_wallet_in_scope(freeze, address)
    assert_page_in_scope(page_index)
    entry = _provider(grant, "helius")
    if entry is None or HELIUS_METHOD not in (entry.get("allowed_operations") or []):
        raise SourceError("UNAUTHORIZED", "Grant does not allow getTransactionsForAddress")
    if used_helius_requests(store, grant) >= entry["max_requests"]:
        raise SourceError("RATE_LIMITED", "Helius reacquire request ceiling reached")
    if used_helius_units(store, grant) + DOCUMENTED_HELIUS_UNITS > entry["max_units"]:
        raise SourceError("RATE_LIMITED", "Helius reacquire credit ceiling reached")
    expected = frozen_signatures(freeze, page_index)
    options = build_historical_gta_options(
        page_index=page_index,
        expected_signatures=expected,
        pagination_token=request_pagination_token(freeze, page_index),
    )
    assert_historical_request_anchored(options, expected_signatures=expected)
    reservation = store.reserve("helius", HELIUS_METHOD, DOCUMENTED_HELIUS_UNITS,
                                entry["cycle_start"], entry["max_units"])
    try:
        store.dispatch(reservation)
        if transport is None:
            raise SourceError("UNAUTHORIZED", "Live HTTP transport is not attached; collection remains blocked")
        result = await dispatch_historical_transport(
            transport, address, options, page_index, expected_signatures=expected,
        )
        store.settle(reservation, charge=True)

        def persist_authorised(page):
            page["units"] = DOCUMENTED_HELIUS_UNITS
            page["units_are"] = "documented_estimate_not_confirmed_dashboard_receipt"
            if store is not None:
                store.put(CACHE_KIND, page_cache_key(grant.get("authorization_id"), address, page_index), page)

        return ingest_fetched_historical_page(
            store, evidence_dir, grant.get("authorization_id"), address, page_index, result,
            expected_signatures=expected,
            options=options,
            reason=reason,
            record_signatures=record_signatures,
            compare_signatures=compare_signatures,
            persist_authorised_page=persist_authorised,
        )
    except SourceError:
        try:
            store.settle(reservation, charge=True)
        except ValueError:
            pass
        raise
    except QuotaExceeded as error:
        raise SourceError("RATE_LIMITED", str(error)) from error
    except Exception as error:
        try:
            store.settle(reservation, charge=True)
        except ValueError:
            pass
        raise SourceError("UNAVAILABLE", "Provider request failed or timed out") from error


def _base_receipt(grant, freeze, checked, blockers, non_grants):
    return {
        "outcome_label": OUTCOME_LABEL,
        "authorization_id": grant.get("authorization_id"),
        "grant_enabled": bool(checked.get("enabled")),
        "repo_template_enabled": False,
        "freeze_verified": True,
        "allowed_wallet": ALLOWED_WALLET,
        "signature_manifest_status": signature_manifest_status(freeze),
        "original_segments_identified": original_segments_identified(freeze),
        "page0_signature_count": len(frozen_signatures(freeze, 0)),
        "page1_signature_count": len(frozen_signatures(freeze, 1)),
        "windows": freeze.get("windows"),
        "encoding_and_version": freeze.get("encoding_and_version"),
        "page_hashes": {
            row["page_index"]: row.get("evidence_sha256") for row in freeze.get("pages") or []
        },
        "pagination_tokens": {
            "page0": (freeze.get("pages") or [{}])[0].get("pagination_token"),
            "page1": (freeze.get("pages") or [{}, {}])[1].get("pagination_token") if len(freeze.get("pages") or []) > 1 else None,
        },
        "arming_blockers": blockers,
        "non_grants": non_grants,
        "external_requests": 0,
        "helius_requests_used": 0,
        "helius_units_used": 0,
        "birdeye_requests_used": 0,
        "setup_pilot_untouched": True,
        "PRODUCT_READY": False,
        "not_full_g2": True,
        "not_match": True,
        "application_commit": application_commit(),
        "parent_recovery_commit": PARENT_RECOVERY_COMMIT,
        "token_balances": SOURCE_RECORDS_DAMAGED,
    }


def _summarize_page(page, freeze, *, decode=None):
    windows = freeze.get("windows") or {}
    decode = decode or decode_supported_swaps
    decoded = decode(page.get("records") or [], ALLOWED_WALLET)
    if not isinstance(decoded, dict):
        decoded = {"events": []}
    by_mint, truncated = decoder_events_by_mint(
        decoded,
        address=ALLOWED_WALLET,
        window_start=windows.get("report_start_inclusive"),
        window_end=windows.get("report_end_exclusive"),
        acquisition_start=windows.get("acquisition_support_start_inclusive"),
    )
    counted = completed_episodes(by_mint)
    worksheet = None
    if counted["wallet_completed_episodes"] >= 1:
        try:
            usable = []
            for mint in sorted(by_mint):
                usable.extend([row for row in by_mint[mint] if not row.get("timestamp_missing")])
            worksheet = independent_fifo_worksheet(usable)
        except ValueError:
            worksheet = None
    return {
        "decoded": decoded,
        "by_mint": by_mint,
        "truncated_before_acquisition_support": truncated,
        "counted": counted,
        "worksheet": worksheet,
        "visible_report": visible_report_allowed(
            worksheet=worksheet,
            completed_positions=counted["wallet_completed_episodes"],
        ),
        "integrity": (page or {}).get("integrity") or {},
    }


def _save_reacquire_application_report(store, grant, freeze, page, summary):
    """Success is a saved retrievable report on the normal application path."""
    windows = freeze.get("windows") or {}
    saved = replay_cached_history_to_report(
        store,
        address=ALLOWED_WALLET,
        records=page.get("records") or [],
        window_start=windows.get("report_start_inclusive"),
        window_end=windows.get("report_end_exclusive"),
        acquisition_start=windows.get("acquisition_support_start_inclusive"),
        corpus_kind="GENUINE_REPLAY",
        authorization_id=grant.get("authorization_id"),
        source_id="reacquire-history-replay",
    )
    if saved.get("report") and summary.get("worksheet"):
        saved["report"]["worksheet"] = summary["worksheet"]
        store.put("reports", saved["report"]["id"], saved["report"])
    return saved


async def run_reacquire_live(store, grant, freeze, *, transport, evidence_dir=None, decode=None, page1_request=None):
    receipt = _base_receipt(grant, freeze, validate_live_authorization(grant), [], assert_non_grants_stay_disabled())
    pages = []
    try:
        page0 = await fetch_reacquire_page(
            store, grant, freeze, ALLOWED_WALLET,
            page_index=0, reason="first_page_frozen_segment",
            transport=transport, evidence_dir=evidence_dir,
        )
        pages.append(page0)
        summary = _summarize_page(page0, freeze, decode=decode)
        receipt["page0_integrity"] = (page0.get("integrity") or {}).get("status")
        receipt["wallet_completed_episodes"] = summary["counted"]["wallet_completed_episodes"]
        receipt["visible_report"] = summary["visible_report"]
        receipt["worksheet"] = summary["worksheet"]
        if summary["visible_report"]:
            saved = _save_reacquire_application_report(store, grant, freeze, page0, summary)
            receipt["report_id"] = saved.get("report_id")
            receipt["search_run_id"] = saved.get("run_id")
            if not saved.get("report_id"):
                receipt["visible_report"] = False
                summary["visible_report"] = False
        stop, why = should_stop_after_visible_position(
            completed_positions=summary["counted"]["wallet_completed_episodes"],
            visible_report=summary["visible_report"],
        )
        if stop:
            receipt["status"] = "PASS_VISIBLE_POSITION"
            receipt["stop_reason"] = why
            receipt["pages_fetched"] = [0]
            return _finalize_live_receipt(store, grant, receipt, pages)
        requested = page1_request or infer_missing_boundary(summary["by_mint"], summary["counted"])
        ok, gate = page1_allowed(
            page0,
            recorded_reason=(requested or {}).get("reason"),
            mint=(requested or {}).get("mint"),
            signature=(requested or {}).get("signature"),
            classification=page0.get("integrity"),
        )
        receipt["page1_gate"] = {"allowed": ok, "reason": gate, "request": requested}
        if not ok:
            receipt["status"] = "INCOMPLETE"
            receipt["stop_reason"] = gate
            receipt["pages_fetched"] = [0]
            return _finalize_live_receipt(store, grant, receipt, pages)
        page1 = await fetch_reacquire_page(
            store, grant, freeze, ALLOWED_WALLET,
            page_index=1, reason=requested["reason"],
            transport=transport, evidence_dir=evidence_dir,
        )
        pages.append(page1)
        merged = {
            "records": list(page0.get("records") or []) + list(page1.get("records") or []),
            "integrity": page1.get("integrity") or page0.get("integrity"),
        }
        summary = _summarize_page(merged, freeze, decode=decode)
        receipt["wallet_completed_episodes"] = summary["counted"]["wallet_completed_episodes"]
        receipt["visible_report"] = summary["visible_report"]
        receipt["worksheet"] = summary["worksheet"]
        if summary["visible_report"]:
            saved = _save_reacquire_application_report(store, grant, freeze, merged, summary)
            receipt["report_id"] = saved.get("report_id")
            receipt["search_run_id"] = saved.get("run_id")
            if not saved.get("report_id"):
                receipt["visible_report"] = False
                summary["visible_report"] = False
        stop, why = should_stop_after_visible_position(
            completed_positions=summary["counted"]["wallet_completed_episodes"],
            visible_report=summary["visible_report"],
        )
        receipt["status"] = "PASS_VISIBLE_POSITION" if stop else "INCOMPLETE"
        receipt["stop_reason"] = why or "page1_complete_no_reconciled_position"
        receipt["pages_fetched"] = [0, 1]
        return _finalize_live_receipt(store, grant, receipt, pages)
    except SourceError as error:
        receipt["status"] = "BLOCKED"
        receipt["blocker"] = error.state
        receipt["detail"] = str(error)
        receipt["stop_reason"] = error.state
        receipt["pages_fetched"] = [row.get("page_index") for row in pages]
        return _finalize_live_receipt(store, grant, receipt, pages)


def _finalize_live_receipt(store, grant, receipt, pages):
    receipt["external_requests"] = used_helius_requests(store, grant)
    receipt["helius_requests_used"] = receipt["external_requests"]
    receipt["helius_units_used"] = used_helius_units(store, grant)
    receipt["page_integrity"] = [
        {"page_index": row.get("page_index"), "integrity": (row.get("integrity") or {}).get("status"),
         "signature_match": row.get("signature_match")}
        for row in pages
    ]
    if store is not None:
        setup = store.usage("helius", "setup-pilot", 200)
        receipt["setup_pilot"] = setup
        receipt["setup_pilot_untouched"] = int(setup.get("used") or 0) == 0
    receipt["PRODUCT_READY"] = False
    return receipt


def run_reacquire(
    store,
    *,
    allow_live=False,
    grant=None,
    freeze=None,
    overlay_path=None,
    evidence_dir=None,
    credentials=None,
    transport=None,
    decode=None,
    page1_request=None,
    attach_live_http=None,
):
    grant = grant or load_reacquire_grant()
    freeze = freeze or load_freeze(overlay_path=overlay_path)
    checked = validate_live_authorization(grant)
    non_grants = assert_non_grants_stay_disabled()
    blockers = arming_blockers(grant, credentials=credentials, freeze=freeze)
    receipt = _base_receipt(grant, freeze, checked, blockers, non_grants)
    if evidence_dir is not None and not allow_live:
        Path(evidence_dir).mkdir(parents=True, exist_ok=True)
        (Path(evidence_dir) / "OFFLINE_PREP_RECEIPT.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8",
        )
    if store is not None:
        setup = store.usage("helius", "setup-pilot", 200)
        receipt["setup_pilot"] = setup
        if int(setup.get("used") or 0) != 0:
            receipt["setup_pilot_untouched"] = False
    if not original_segments_identified(freeze) or signature_manifest_status(freeze) == STOP_NO_SEGMENT:
        receipt["status"] = "OFFLINE_PASS" if not allow_live else "BLOCKED"
        receipt["stop_reason"] = STOP_NO_SEGMENT
        receipt["blocker"] = STOP_NO_SEGMENT
        receipt["detail"] = (
            "Original rank-1 segments are not identified. Zero provider calls."
        )
        receipt["transport_called"] = False
        return receipt
    if not allow_live:
        receipt["status"] = "OFFLINE_PASS"
        receipt["stop_reason"] = "offline_prep_only"
        receipt["detail"] = "Segments are frozen (EXTRACT_OK). Live remains box-only after quota confirm."
        receipt["transport_called"] = False
        return receipt
    codes = {row["code"] for row in blockers}
    if codes:
        receipt["status"] = "BLOCKED"
        receipt["blocker"] = next(
            code for code in (
                "prior_grant_reuse_forbidden",
                "grant_disabled",
                STOP_NO_SEGMENT,
                "missing_provider_credentials",
                "existing_plan_unconfirmed",
                "remaining_quota_unconfirmed",
                "grant_expired",
            ) if code in codes
        )
        receipt["transport_called"] = False
        return receipt
    if transport is None:
        should_attach = True if attach_live_http is None else attach_live_http
        if should_attach:
            transport = helius_gta_http
        else:
            receipt["status"] = "BLOCKED"
            receipt["blocker"] = "live_transport_not_attached_in_this_module"
            receipt["transport_called"] = False
            return receipt
    live = asyncio.run(run_reacquire_live(
        store, grant, freeze,
        transport=transport,
        evidence_dir=evidence_dir,
        decode=decode,
        page1_request=page1_request,
    ))
    receipt.update(live)
    receipt["transport_called"] = True
    receipt["PRODUCT_READY"] = False
    if evidence_dir is not None:
        Path(evidence_dir).mkdir(parents=True, exist_ok=True)
        (Path(evidence_dir) / "LIVE_RECEIPT.json").write_text(
            json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8",
        )
    return receipt
