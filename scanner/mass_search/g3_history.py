"""G3_RANKED100_HISTORY: bounded Helius history on a frozen ranked-100 shortlist.

Offline is the default. Live HTTP is refused unless a separately armed grant,
confirmed Helius quota/entitlement, and credentials are all present.
G1 and ranked-100 grants must not be reused. Setup-pilot must not be reset.
"""
from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from scanner.investigation import decode_supported_swaps
from scanner.storage import QuotaExceeded

from .adapters import SourceError
from .capability import (
    LIVE_AUTH_SCHEMA,
    redact_secrets,
    utc_now,
    validate_live_authorization,
)
from .live_g1 import _count_method, _wrap_records, independent_fifo_worksheet
from .plan import canonical_json, sha256_json
from .service import MassSearchService

ROOT = Path(__file__).resolve().parents[2]
GRANT_PATH = ROOT / "config" / "live_authorization.g3-ranked100-history-granted.json"
G1_GRANT_PATH = ROOT / "config" / "live_authorization.g1-granted.json"
RANKED100_GRANT_PATH = ROOT / "config" / "live_authorization.g2-ranked100-discovery-granted.json"
EXAMPLE_PATH = ROOT / "work_packages" / "mass_wallet_search_v1" / "config" / "live_authorization.example.json"
DRAFT_PATH = ROOT / "config" / "live_authorization.proof-grant-draft.json"
FREEZE_PATH = ROOT / "evidence" / "mass-wallet-funnel" / "g3-ranked100-history" / "FROZEN_CANDIDATES.json"
SHORTLIST_PATH = ROOT / "evidence" / "mass-wallet-funnel" / "ranked100-discovery-pilot-2026-10-05" / "SHORTLIST.json"

OUTCOME_LABEL = "G3_RANKED100_HISTORY"
AUTHORIZATION_ID = "live-g3-ranked100-history-2026-10-06-mitch"
G1_AUTHORIZATION_ID = "live-g1-vertical-slice-2026-10-05-mitch"
RANKED100_AUTHORIZATION_ID = "live-g2-ranked100-discovery-2026-10-05-mitch"
PARENT_COMMIT = "159639b1bc4fd20d6504026f8d58247f1b2e42c9"
HELIUS_KEY_ENV = "HELIUS_API_KEY"
HELIUS_ENDPOINT = "https://mainnet.helius-rpc.com/"
DOCUMENTED_HELIUS_UNITS = 10
CACHE_KIND = "mass_search_cache"
HELIUS_METHOD = "getTransactionsForAddress"

EXACT_HELIUS_OPTIONS = {
    "transactionDetails": "full",
    "limit": 100,
    "sortOrder": "desc",
    "commitment": "finalized",
    "maxSupportedTransactionVersion": 1,
    "filters": {"status": "any", "tokenAccounts": "all"},
}


def load_g3_grant(path=None):
    payload = json.loads(Path(path or GRANT_PATH).read_text(encoding="utf-8"))
    if payload.get("schema_version") != LIVE_AUTH_SCHEMA:
        raise ValueError("Grant must use live-research-authorization-v1")
    if payload.get("authorization_id") in (G1_AUTHORIZATION_ID, RANKED100_AUTHORIZATION_ID):
        raise ValueError("G1 and ranked-100 grants must not be reused for G3_RANKED100_HISTORY")
    if payload.get("authorization_id") != AUTHORIZATION_ID:
        raise ValueError("This runner only accepts live-g3-ranked100-history-2026-10-06-mitch")
    if payload.get("do_not_reset_setup_pilot") is not True:
        raise ValueError("G3 grant must leave setup-pilot untouched")
    if payload.get("max_additional_spend_usd") != "0":
        raise ValueError("G3 grant forbids additional spend")
    return payload


def load_freeze(path=None):
    payload = json.loads(Path(path or FREEZE_PATH).read_text(encoding="utf-8"))
    if payload.get("kind") != "g3-ranked100-history-freeze-v1":
        raise ValueError("Unsupported G3 freeze schema")
    if payload.get("parent_commit") != PARENT_COMMIT:
        raise ValueError("Freeze parent_commit must remain 159639b1bc4fd20d6504026f8d58247f1b2e42c9")
    if payload.get("authorization_id") != AUTHORIZATION_ID:
        raise ValueError("Freeze authorization_id mismatch")
    initials = payload.get("initial_candidates") or []
    reserves = payload.get("reserve_candidates") or []
    if [row["shortlist_rank"] for row in initials] != [1, 3, 5]:
        raise ValueError("Initial candidates must be shortlist ranks 1, 3, 5")
    if [row["shortlist_rank"] for row in reserves] != [6, 7]:
        raise ValueError("Reserve candidates must be shortlist ranks 6, 7")
    allowed = {row["address"] for row in initials + reserves}
    if len(allowed) != 5:
        raise ValueError("Freeze must contain exactly five unique addresses")
    return payload


def assert_freeze_matches_shortlist(freeze=None, shortlist_path=None):
    freeze = freeze or load_freeze()
    short = json.loads(Path(shortlist_path or SHORTLIST_PATH).read_text(encoding="utf-8"))
    by_rank = {row["shortlist_rank"]: row for row in short["shortlist"]}
    for row in freeze["initial_candidates"] + freeze["reserve_candidates"]:
        source = by_rank[row["shortlist_rank"]]
        if source["address"] != row["address"]:
            raise ValueError(f"Freeze address drift at rank {row['shortlist_rank']}")
    return True


def assert_non_grants_stay_disabled():
    example = validate_live_authorization(json.loads(EXAMPLE_PATH.read_text(encoding="utf-8")))
    draft = validate_live_authorization(json.loads(DRAFT_PATH.read_text(encoding="utf-8")))
    ranked = validate_live_authorization(json.loads(RANKED100_GRANT_PATH.read_text(encoding="utf-8")))
    g3 = validate_live_authorization(json.loads(GRANT_PATH.read_text(encoding="utf-8")))
    if example.get("enabled") or draft.get("enabled") or ranked.get("enabled") or g3.get("enabled"):
        raise ValueError("Example, draft, ranked-100, or G3 grant file is enabled in this offline-prep tree")
    return {
        "example_enabled": False,
        "draft_enabled": False,
        "ranked100_enabled": False,
        "g3_enabled": False,
        "g1_not_reused": True,
        "ranked100_not_reused": True,
    }


def _provider(grant, provider_id):
    for entry in grant.get("providers") or []:
        if entry.get("provider_id") == provider_id:
            return entry
    return None


def arming_blockers(grant, *, credentials=None):
    """Helius pricing/entitlement/quota must be confirmed. A key or G1 pass is not enough."""
    blockers = []
    if grant.get("authorization_id") in (G1_AUTHORIZATION_ID, RANKED100_AUTHORIZATION_ID):
        blockers.append({"code": "prior_grant_reuse_forbidden", "detail": "G1 and ranked-100 grants must not be reused"})
        return blockers
    if grant.get("authorization_id") != AUTHORIZATION_ID:
        blockers.append({"code": "unexpected_authorization_id", "detail": grant.get("authorization_id")})
    if grant.get("enabled") is not True:
        blockers.append({"code": "grant_disabled", "detail": "G3 grant stays disabled until Helius quota/entitlement confirmation"})
    expires = grant.get("expires_at")
    if isinstance(expires, str) and expires and expires <= utc_now():
        blockers.append({"code": "grant_expired", "detail": expires})
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
                "detail": "Operator must confirm remaining Helius credits and documented 10-credit GTA pricing; a present key or G1 pass is not enough",
            })
        if helius.get("max_requests") != 15 or helius.get("max_units") != 150:
            blockers.append({"code": "helius_ceiling_mismatch", "detail": "Helius must be 15 requests / 150 credits"})
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
    return blockers


def frozen_addresses(freeze):
    return [row["address"] for row in freeze["initial_candidates"] + freeze["reserve_candidates"]]


def assert_address_frozen(freeze, address):
    allowed = set(frozen_addresses(freeze))
    if address not in allowed:
        raise SourceError("UNAUTHORIZED", "Address is not on the frozen G3 candidate list")


def page_cache_key(authorization_id, address, page_index):
    return f"g3-history:{authorization_id}:{address}:page:{page_index}"


def wallet_log_key(authorization_id, address):
    return f"g3-history:{authorization_id}:{address}:log"


def load_cached_page(store, authorization_id, address, page_index):
    if store is None:
        return None
    return store.get(CACHE_KIND, page_cache_key(authorization_id, address, page_index))


def persist_page(store, authorization_id, address, page_index, payload):
    if store is None:
        return payload
    store.put(CACHE_KIND, page_cache_key(authorization_id, address, page_index), payload)
    return payload


def wallet_request_count(store, authorization_id, address):
    if store is None:
        return 0
    log = store.get(CACHE_KIND, wallet_log_key(authorization_id, address)) or {}
    return int(log.get("dispatched_requests") or 0)


def record_wallet_attempt(store, authorization_id, address, *, page_index, reason, charged, status):
    if store is None:
        return
    key = wallet_log_key(authorization_id, address)
    log = store.get(CACHE_KIND, key) or {
        "kind": "g3-history-wallet-log-v1",
        "address": address,
        "dispatched_requests": 0,
        "attempts": [],
    }
    log["dispatched_requests"] = int(log.get("dispatched_requests") or 0) + 1
    log["attempts"] = list(log.get("attempts") or []) + [{
        "page_index": page_index,
        "reason": reason,
        "charged": charged,
        "status": status,
        "at": utc_now(),
    }]
    store.put(CACHE_KIND, key, log)


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


def further_page_allowed(first_page, episodes, *, recorded_reason):
    if not recorded_reason:
        return False, "further_page_requires_recorded_evidence_reason"
    if not first_page.get("pagination_token"):
        return False, "no_pagination_token"
    if episodes >= 10:
        return False, "g3_episode_bar_already_met"
    allowed = {
        "insufficient_episodes_pagination_token_present",
        "page_truncated_below_g3_episode_bar",
    }
    if recorded_reason not in allowed:
        return False, "further_page_reason_not_evidence_based"
    return True, recorded_reason


def decoder_events_by_mint(decoded, *, address, window_start, window_end=None, acquisition_start=None):
    events = [row for row in (decoded.get("events") or []) if row.get("kind") in ("buy", "sell")]
    start = datetime.fromisoformat(window_start.replace("Z", "+00:00"))
    start_unix = start.timestamp()
    acq_unix = None
    if acquisition_start:
        acq_unix = datetime.fromisoformat(acquisition_start.replace("Z", "+00:00")).timestamp()
    end_unix = None
    if window_end:
        end_unix = datetime.fromisoformat(window_end.replace("Z", "+00:00")).timestamp()
    by_mint = {}
    truncated_before_window = 0
    for row in events:
        mint = row.get("mint")
        if not mint:
            continue
        timestamp = row.get("timestamp")
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            if acq_unix is not None and timestamp < acq_unix:
                truncated_before_window += 1
                continue
            seconds = int(timestamp - start_unix)
        else:
            seconds = 0
        by_mint.setdefault(mint, []).append({
            "kind": row["kind"],
            "units": str(row.get("quantity_raw") or "0"),
            "consideration_sol": str(row.get("amount_sol") or "0"),
            "wallet_fee_sol": str(row.get("fee_sol") or "0"),
            "seconds_from_start": seconds,
            "signature": row.get("signature"),
            "mint": mint,
            "address": address,
            "evidence": row.get("evidence") or [],
        })
    return by_mint, truncated_before_window


def completed_episodes(by_mint):
    """Count supported FIFO sales per mint. Missing stays unknown; do not invent."""
    total = 0
    per_mint = {}
    for mint, rows in by_mint.items():
        kinds = {row["kind"] for row in rows}
        if "buy" not in kinds or "sell" not in kinds:
            per_mint[mint] = 0
            continue
        try:
            worksheet = independent_fifo_worksheet(rows)
        except ValueError:
            per_mint[mint] = 0
            continue
        count = len(worksheet.get("sale_net_profit_sol") or [])
        per_mint[mint] = count
        total += count
    return {"wallet_completed_episodes": total, "per_mint": per_mint}


def best_mint(by_mint, episode_counts):
    ranked = sorted(
        ((mint, episode_counts["per_mint"].get(mint, 0), len(rows)) for mint, rows in by_mint.items()),
        key=lambda item: (-item[1], -item[2], item[0]),
    )
    return ranked[0][0] if ranked else None


def armed_test_grant(base=None):
    """In-memory grant for adapter-path tests. Never writes enabled=true to disk."""
    payload = deepcopy(base or json.loads(GRANT_PATH.read_text(encoding="utf-8")))
    payload["enabled"] = True
    payload["expires_at"] = "2099-01-01T00:00:00Z"
    for entry in payload["providers"]:
        if entry["provider_id"] == "helius":
            entry["existing_plan_confirmed"] = True
            entry["remaining_quota_confirmed_at"] = payload["authorized_by_user_at"]
    return validate_live_authorization(payload)


async def fetch_helius_page(store, grant, address, *, page_index, reason, transport=None, pagination_token=None):
    entry = _provider(grant, "helius")
    if entry is None or HELIUS_METHOD not in (entry.get("allowed_operations") or []):
        raise SourceError("UNAUTHORIZED", "Grant does not allow getTransactionsForAddress")
    if used_helius_requests(store, grant) >= entry["max_requests"]:
        raise SourceError("RATE_LIMITED", "Helius G3 request ceiling reached")
    if used_helius_units(store, grant) + DOCUMENTED_HELIUS_UNITS > entry["max_units"]:
        raise SourceError("RATE_LIMITED", "Helius G3 credit ceiling reached")
    if wallet_request_count(store, grant.get("authorization_id"), address) >= int(entry.get("max_requests_per_wallet") or 3):
        raise SourceError("RATE_LIMITED", "Per-wallet G3 request ceiling reached")
    options = dict(EXACT_HELIUS_OPTIONS)
    if pagination_token:
        options["paginationToken"] = pagination_token
    reservation = store.reserve("helius", HELIUS_METHOD, DOCUMENTED_HELIUS_UNITS,
                                entry["cycle_start"], entry["max_units"])
    try:
        store.dispatch(reservation)
        record_wallet_attempt(
            store, grant.get("authorization_id"), address,
            page_index=page_index, reason=reason, charged=True, status="dispatched",
        )
        if transport is None:
            raise SourceError("UNAUTHORIZED", "Live HTTP transport is not attached; collection remains blocked")
        result = await transport(address, options=options, page_index=page_index)
        store.settle(reservation, charge=True)
        records = result.get("records") or []
        raw_bytes = json.dumps(redact_secrets({"records": records, "options": options}),
                               sort_keys=True, separators=(",", ":"), default=str).encode()
        page = {
            "kind": "g3-history-page-v1",
            "address": address,
            "page_index": page_index,
            "reason": reason,
            "query": {"method": HELIUS_METHOD, "options": {k: v for k, v in options.items() if k != "paginationToken"}},
            "records": redact_secrets(records),
            "pagination_token": result.get("pagination_token"),
            "evidence_sha256": result.get("evidence_sha256") or hashlib.sha256(raw_bytes).hexdigest(),
            "units": DOCUMENTED_HELIUS_UNITS,
            "external_requests": 1,
            "http_status": result.get("http_status", 200),
            "fetched_at": utc_now(),
            "units_are": "documented_estimate_not_confirmed_dashboard_receipt",
        }
        persist_page(store, grant.get("authorization_id"), address, page_index, page)
        return page
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


def _fixture_page(address, records, *, page_index=0, pagination_token=None, reason="fixture_first_page"):
    raw_bytes = json.dumps(redact_secrets({"records": records}), sort_keys=True, separators=(",", ":"), default=str).encode()
    return {
        "kind": "g3-history-page-v1",
        "address": address,
        "page_index": page_index,
        "reason": reason,
        "query": {"method": HELIUS_METHOD, "options": dict(EXACT_HELIUS_OPTIONS)},
        "records": records,
        "pagination_token": pagination_token,
        "evidence_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "units": 0,
        "external_requests": 0,
        "http_status": 200,
        "fetched_at": utc_now(),
        "units_are": "fixture",
    }


async def acquire_or_cache_page(store, grant, address, *, page_index, reason, transport=None, fixture_pages=None,
                                pagination_token=None, allow_live=False):
    cached = load_cached_page(store, grant.get("authorization_id"), address, page_index)
    if cached:
        served = deepcopy(cached)
        served["from_cache"] = True
        served["external_requests"] = 0
        return served
    if fixture_pages and address in fixture_pages:
        raw = fixture_pages[address]
        records = raw[page_index] if isinstance(raw, list) and raw and isinstance(raw[0], list) else raw
        page = _fixture_page(address, records, page_index=page_index, reason=reason)
        persist_page(store, grant.get("authorization_id"), address, page_index, page)
        return page
    if allow_live or transport is not None:
        return await fetch_helius_page(
            store, grant, address, page_index=page_index, reason=reason,
            transport=transport, pagination_token=pagination_token,
        )
    raise SourceError("UNAUTHORIZED", "No cached G3 page; refusing a provider request")


def _summarize_candidate(store, grant, freeze, service, candidate, page, *, decode=None):
    address = candidate["address"]
    windows = freeze["windows"]
    decode = decode or decode_supported_swaps
    records = _wrap_records(page.get("records") or [])
    decoded = decode(records, address)
    by_mint, truncated = decoder_events_by_mint(
        decoded, address=address,
        window_start=windows["report_start_inclusive"],
        window_end=windows["report_end_exclusive"],
        acquisition_start=windows["acquisition_support_start_inclusive"],
    )
    episodes = completed_episodes(by_mint)
    mint = best_mint(by_mint, episodes)
    report = None
    worksheet = None
    corpus = "SYNTHETIC" if page.get("units_are") == "fixture" else "GENUINE_LIVE"
    if mint and by_mint[mint]:
        subset_events = by_mint[mint]
        try:
            worksheet = independent_fifo_worksheet(subset_events)
        except ValueError:
            worksheet = None
        reconstructed = service.reconstruct_candidate(
            service._g3_run_id, f"solana:{address}", subset_events,
            corpus_kind=corpus, mint=mint,
        )
        report = reconstructed["report"]
        report["source"] = "mass-search"
        report["policy"] = report.get("policy") or "UNRESOLVED"
        store.put("reports", report["id"], report)
    qualifying = bool(worksheet) and episodes["wallet_completed_episodes"] >= 10
    if worksheet and not qualifying:
        status = "VISIBLE_BELOW_G3"
    elif qualifying:
        status = "QUALIFYING"
    else:
        status = "NO_SUPPORTED_CLOSED_PAIR"
    return {
        "address": address,
        "shortlist_rank": candidate["shortlist_rank"],
        "role": candidate["role"],
        "status": status,
        "g3_qualifying": qualifying,
        "wallet_completed_episodes": episodes["wallet_completed_episodes"],
        "per_mint_episodes": episodes["per_mint"],
        "report_mint": mint,
        "report_id": None if report is None else report["id"],
        "policy": None if report is None else report.get("policy"),
        "not_wallet_wide_match": True,
        "worksheet": worksheet,
        "truncated_before_acquisition_support": truncated,
        "coverage_note": "Honest truncation: events before the 90-day acquisition-support start were excluded; missing timestamps stay unknown.",
        "page_evidence_sha256": page.get("evidence_sha256"),
        "from_cache": bool(page.get("from_cache")),
        "external_requests": int(page.get("external_requests") or 0),
        "label": candidate.get("label"),
        "pagination_token_present": bool(page.get("pagination_token")),
    }


async def run_g3_history_async(
    store,
    *,
    grant_path=None,
    freeze_path=None,
    transport=None,
    decode=None,
    fixture_pages=None,
    allow_live=False,
    further_page_reason=None,
    evidence_dir=None,
    application_sha=None,
):
    grant = load_g3_grant(grant_path)
    freeze = load_freeze(freeze_path)
    assert_freeze_matches_shortlist(freeze)
    non_grants = assert_non_grants_stay_disabled()
    blockers = arming_blockers(grant)
    setup_before = store.usage("helius", "setup-pilot", 200)
    result = {
        "outcome_label": OUTCOME_LABEL,
        "not_full_g2": True,
        "authorization_id": grant.get("authorization_id"),
        "grant_enabled": bool(grant.get("enabled")),
        "parent_commit": freeze["parent_commit"],
        "freeze_path": str(Path(freeze_path or FREEZE_PATH).relative_to(ROOT)),
        "arming_blockers": blockers,
        "non_grants": non_grants,
        "setup_pilot": setup_before,
        "external_requests": 0,
        "PRODUCT_READY": False,
        "winners_not_required": True,
        "g3_min_episodes": 10,
        "target_reports": 3,
    }
    if allow_live and blockers:
        result.update({"status": "BLOCKED", "blocker": blockers[0]["code"], "detail": blockers[0]["detail"]})
        _write_receipt(evidence_dir, result)
        return result
    if allow_live:
        grant = validate_live_authorization(grant)

    can_collect = bool(allow_live or transport is not None or fixture_pages)
    if not can_collect:
        result.update({
            "status": "OFFLINE_PASS",
            "detail": "Offline G3 prep; freeze verified; live Helius not dispatched",
            "freeze_verified": True,
            "initial_addresses": [row["address"] for row in freeze["initial_candidates"]],
            "reserve_addresses": [row["address"] for row in freeze["reserve_candidates"]],
            "helius_requests_used": 0,
            "setup_pilot_after": setup_before,
        })
        _write_receipt(evidence_dir, result)
        return result

    service = MassSearchService(store, clock=lambda: freeze["discovery_cutoff"])
    plan = deepcopy(service.preview_plan()["plan"])
    plan["live_enabled"] = False
    plan["selection"]["report_window_days"] = 30
    plan["selection"]["verification_window_days"] = 90
    run = service.create_run(plan, source_id="helius-history", corpus_kind="SYNTHETIC")
    service._g3_run_id = run["run_id"]
    inspected = []
    queue = list(freeze["initial_candidates"])
    reserves = list(freeze["reserve_candidates"])
    investigations = 0

    try:
        while True:
            qualifying = [row for row in inspected if row.get("g3_qualifying")]
            if len(qualifying) >= 3:
                result["stop_reason"] = "three_qualifying_reports"
                break
            if investigations >= 5:
                result["stop_reason"] = "wallet_investigation_cap"
                break
            if not queue:
                if reserves and len(qualifying) < 3:
                    queue.append(reserves.pop(0))
                else:
                    result["stop_reason"] = "queue_exhausted"
                    break
            candidate = queue.pop(0)
            assert_address_frozen(freeze, candidate["address"])
            investigations += 1
            try:
                page = await acquire_or_cache_page(
                    store, grant, candidate["address"], page_index=0,
                    reason="first_page_no_equivalent_cache",
                    transport=transport, fixture_pages=fixture_pages, allow_live=allow_live,
                )
            except SourceError as error:
                if error.state == "UNAUTHORIZED" and not allow_live and transport is None:
                    inspected.append({
                        "address": candidate["address"],
                        "shortlist_rank": candidate["shortlist_rank"],
                        "role": candidate["role"],
                        "status": "NO_HISTORY",
                        "g3_qualifying": False,
                        "wallet_completed_episodes": 0,
                        "external_requests": 0,
                        "from_cache": False,
                        "detail": str(error),
                    })
                    continue
                raise
            summary = _summarize_candidate(store, grant, freeze, service, candidate, page, decode=decode)
            result["external_requests"] += int(summary.get("external_requests") or 0)
            ok, why = further_page_allowed(
                page, summary["wallet_completed_episodes"], recorded_reason=further_page_reason,
            )
            if not summary["g3_qualifying"] and ok and (allow_live or transport is not None):
                extra = await acquire_or_cache_page(
                    store, grant, candidate["address"], page_index=1,
                    reason=why, transport=transport, fixture_pages=fixture_pages,
                    pagination_token=page.get("pagination_token"), allow_live=allow_live,
                )
                merged = deepcopy(page)
                merged["records"] = list(page.get("records") or []) + list(extra.get("records") or [])
                merged["external_requests"] = int(page.get("external_requests") or 0) + int(extra.get("external_requests") or 0)
                summary = _summarize_candidate(store, grant, freeze, service, candidate, merged, decode=decode)
                result["external_requests"] += int(extra.get("external_requests") or 0)
            inspected.append(summary)
    except SourceError as error:
        result.update({
            "status": "BLOCKED",
            "blocker": error.state,
            "detail": str(error),
            "inspected_candidates": inspected,
            "helius_requests_used": used_helius_requests(store, grant),
            "helius_units_used": used_helius_units(store, grant),
            "setup_pilot_after": store.usage("helius", "setup-pilot", 200),
        })
        _write_receipt(evidence_dir, result)
        return result

    qualifying = [row for row in inspected if row.get("g3_qualifying")]
    visible = [row for row in inspected if row.get("worksheet") and not row.get("g3_qualifying")]
    if len(qualifying) >= 3:
        status = "G3_PASS"
    elif not allow_live:
        status = "OFFLINE_PASS"
    else:
        status = "INCOMPLETE"
    result.update({
        "status": status,
        "search_run_id": run["run_id"],
        "inspected_candidates": inspected,
        "qualifying_reports": len(qualifying),
        "visible_below_g3": len(visible),
        "investigations": investigations,
        "helius_requests_used": used_helius_requests(store, grant),
        "helius_units_used": used_helius_units(store, grant),
        "helius_units_are": "documented_estimate_not_confirmed_dashboard_receipt",
        "setup_pilot_after": store.usage("helius", "setup-pilot", 200),
        "windows": freeze["windows"],
        "application_sha": application_sha,
    })
    if result["setup_pilot"] != result["setup_pilot_after"]:
        result["status"] = "BLOCKED"
        result["blocker"] = "setup_pilot_changed"
        result["detail"] = "G3 must not reset or charge setup-pilot"
    _write_receipt(evidence_dir, result)
    return result


def run_g3_history(store, **kwargs):
    import asyncio
    return asyncio.run(run_g3_history_async(store, **kwargs))


def fixture_closed_records(*, sales, mint="Mint1111111111111111111111111111111111111"):
    """Synthetic decoder input: one buy+sell pair per completed episode."""
    records = []
    for index in range(sales):
        records.append({"transaction": {"signatures": [f"sig-buy-{index}"]}, "g3_fixture_sale": index})
        records.append({"transaction": {"signatures": [f"sig-sell-{index}"]}, "g3_fixture_sale": index})
    return records


def fixture_decode(sales=10, mint="Mint1111111111111111111111111111111111111", start_unix=1_789_862_400):
    def decode(records, address):
        events = []
        pairs = max(1, len(records) // 2)
        count = min(sales, pairs)
        for index in range(count):
            events.append({
                "kind": "buy", "timestamp": start_unix + index * 120, "quantity_raw": "10",
                "amount_sol": "1", "fee_sol": "0.001", "mint": mint,
                "signature": f"sig-buy-{index}", "evidence": ["b" * 64],
            })
            events.append({
                "kind": "sell", "timestamp": start_unix + index * 120 + 30, "quantity_raw": "10",
                "amount_sol": "1.1", "fee_sol": "0.001", "mint": mint,
                "signature": f"sig-sell-{index}", "evidence": ["c" * 64],
            })
        return {"events": events, "coverage": {"decoded_swaps": len(events)}}
    return decode


def _write_receipt(evidence_dir, result):
    if not evidence_dir:
        return
    path = Path(evidence_dir)
    path.mkdir(parents=True, exist_ok=True)
    payload = json.loads(json.dumps(redact_secrets(result), default=str))
    (path / "G3_RESULT.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (path / "INDEX.json").write_text(json.dumps({
        "outcome_label": OUTCOME_LABEL,
        "status": result.get("status"),
        "authorization_id": result.get("authorization_id"),
        "qualifying_reports": result.get("qualifying_reports"),
        "external_requests": result.get("external_requests"),
        "blocker": result.get("blocker"),
        "result": "G3_RESULT.json",
        "not_full_g2": True,
        "PRODUCT_READY": False,
    }, indent=2) + "\n", encoding="utf-8")
