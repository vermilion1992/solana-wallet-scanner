"""G3_INTEGRITY_REACQUIRE_RANK1: one-wallet integrity reacquire, offline default.

Repo grant template stays disabled. Leftover G3_RANKED100_HISTORY (15/150) must
not be reused. Live HTTP is refused while the original rank-1 signature
manifests are STOP_NO_SEGMENT — newest-first GTA now would substitute current
history.
"""
from __future__ import annotations

import json
import os
import sqlite3
from copy import deepcopy
from pathlib import Path

from .adapters import SourceError
from .capability import (
    LIVE_AUTH_SCHEMA,
    utc_now,
    validate_live_authorization,
)
from .evidence_integrity import CACHE_KEY_PREFIX_V1, CACHE_KEY_PREFIX_V2
from .g3_history import (
    AUTHORIZATION_ID as G3_LEFTOVER_AUTHORIZATION_ID,
    EXAMPLE_PATH,
    G1_AUTHORIZATION_ID,
    G1_GRANT_PATH,
    GRANT_PATH as G3_LEFTOVER_GRANT_PATH,
    RANKED100_AUTHORIZATION_ID,
    RANKED100_GRANT_PATH,
)
from .g3_history import DRAFT_PATH

ROOT = Path(__file__).resolve().parents[2]
GRANT_PATH = ROOT / "config" / "live_authorization.g3-integrity-reacquire-rank1-draft.json"
FREEZE_PATH = ROOT / "evidence" / "mass-wallet-funnel" / "g3-integrity-reacquire-rank1" / "FROZEN_SEGMENTS.json"

OUTCOME_LABEL = "G3_INTEGRITY_REACQUIRE_RANK1"
AUTHORIZATION_ID = "live-g3-integrity-reacquire-rank1-2026-10-06-mitch"
ALLOWED_WALLET = "25865JdBJVVLbt6Kfe4KnKrVCy8UVCYFRRBAPvmJ17LL"
PARENT_RECOVERY_COMMIT = "fe6a398a40c59d1e1afcb3788c3ccba00d936779"
HELIUS_KEY_ENV = "HELIUS_API_KEY"
HELIUS_METHOD = "getTransactionsForAddress"
DOCUMENTED_HELIUS_UNITS = 10
MAX_WALLETS = 1
MAX_REQUESTS = 2
MAX_UNITS = 20
MAX_TXS_PER_CALL = 100
MAX_DURATION_SECONDS = 300
MAX_PAGE_INDEX = 1
CACHE_KIND = "mass_search_cache"

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


def load_freeze(path=None):
    payload = json.loads(Path(path or FREEZE_PATH).read_text(encoding="utf-8"))
    if payload.get("kind") != "g3-integrity-reacquire-rank1-freeze-v1":
        raise ValueError("Unsupported reacquire freeze schema")
    if payload.get("authorization_id") != AUTHORIZATION_ID:
        raise ValueError("Freeze authorization_id mismatch")
    if payload.get("parent_recovery_commit") != PARENT_RECOVERY_COMMIT:
        raise ValueError("Freeze parent_recovery_commit must remain fe6a398a40c59d1e1afcb3788c3ccba00d936779")
    if payload.get("allowed_wallet") != ALLOWED_WALLET:
        raise ValueError("Freeze wallet must remain the original rank-1 address")
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
    return all(len(row.get("signatures") or []) == 100 for row in pages)


def page1_allowed(page0, *, recorded_reason, mint=None, signature=None, classification=None):
    """Page 1 needs intact page 0 plus a specific missing-boundary reason."""
    classification = classification or (page0 or {}).get("integrity") or {}
    if classification.get("integrity_failure") or classification.get("status") in {
        "SOURCE_RECORDS_DAMAGED", "MALFORMED",
    }:
        return False, "page0_integrity_failed"
    if recorded_reason in FORBIDDEN_PAGE1_REASONS or not recorded_reason:
        return False, "page1_not_for_episode_count_or_pnl"
    if recorded_reason not in ALLOWED_PAGE1_REASONS:
        return False, "page1_reason_not_acquisition_or_position_boundary"
    if not mint or not signature:
        return False, "page1_requires_mint_sig_reason"
    if classification.get("status") and classification.get("status") != "INTACT":
        return False, "page0_not_intact"
    return True, recorded_reason


def should_stop_after_visible_position(*, completed_positions, visible_report):
    if completed_positions >= 1 and visible_report:
        return True, "one_completed_position_reconciled"
    return False, None


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
            "detail": "Original rank-1 page 0/1 signatures and pagination tokens are not in surviving PR metadata; newest-first GTA now would substitute current/latest history",
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
        for child in node.values():
            _collect_signatures(child, found)
    elif isinstance(node, list):
        for child in node:
            _collect_signatures(child, found)


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
            "Local damaged cache produced 100+100 signatures. This does not authorise "
            "newest-first GTA now. A fetch strategy that preserves those exact segments "
            "still needs an explicit overlay freeze before any live dispatch."
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


def run_reacquire(store, *, allow_live=False, grant=None, freeze=None, evidence_dir=None, credentials=None):
    grant = grant or load_reacquire_grant()
    freeze = freeze or load_freeze()
    checked = validate_live_authorization(grant)
    non_grants = assert_non_grants_stay_disabled()
    blockers = arming_blockers(grant, credentials=credentials, freeze=freeze)
    manifest_status = signature_manifest_status(freeze)
    receipt = {
        "outcome_label": OUTCOME_LABEL,
        "authorization_id": grant.get("authorization_id"),
        "grant_enabled": bool(checked.get("enabled")),
        "repo_template_enabled": False,
        "freeze_verified": True,
        "allowed_wallet": ALLOWED_WALLET,
        "signature_manifest_status": manifest_status,
        "original_segments_identified": original_segments_identified(freeze),
        "page0_signature_count": len((freeze.get("pages") or [{}])[0].get("signatures") or []),
        "page1_signature_count": len((freeze.get("pages") or [{}, {}])[1].get("signatures") or []),
        "windows": freeze.get("windows"),
        "encoding_and_version": freeze.get("encoding_and_version"),
        "page_hashes": {
            row["page_index"]: row.get("evidence_sha256") for row in freeze.get("pages") or []
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
    }
    if evidence_dir is not None:
        Path(evidence_dir).mkdir(parents=True, exist_ok=True)
        (Path(evidence_dir) / "OFFLINE_PREP_RECEIPT.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8",
        )
    if store is not None:
        setup = store.usage("helius", "setup-pilot", 200)
        receipt["setup_pilot"] = setup
        if int(setup.get("used") or 0) != 0:
            receipt["setup_pilot_untouched"] = False
    if manifest_status == STOP_NO_SEGMENT or not receipt["original_segments_identified"]:
        receipt["status"] = "OFFLINE_PASS" if not allow_live else "BLOCKED"
        receipt["stop_reason"] = STOP_NO_SEGMENT
        receipt["blocker"] = STOP_NO_SEGMENT
        receipt["detail"] = (
            "Original rank-1 segments are not identified from surviving metadata. "
            "Zero provider calls."
        )
        return receipt
    if allow_live:
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
                ) if code in codes
            )
            return receipt
        receipt["status"] = "BLOCKED"
        receipt["blocker"] = "live_transport_not_attached_in_this_module"
        receipt["detail"] = "Segments are frozen, but this offline-prep module does not attach Helius HTTP."
        return receipt
    receipt["status"] = "OFFLINE_PASS"
    receipt["stop_reason"] = "offline_prep_only"
    return receipt
