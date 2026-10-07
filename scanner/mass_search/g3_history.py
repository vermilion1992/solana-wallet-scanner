"""G3_RANKED100_HISTORY: bounded Helius history on a frozen ranked-100 shortlist.

Offline is the default. Live HTTP is refused unless a separately armed grant,
confirmed Helius quota/entitlement, and credentials are all present.
G1 and ranked-100 grants must not be reused. Setup-pilot must not be reset.
"""
from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from datetime import datetime
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
from .evidence_integrity import (
    CACHE_KEY_PREFIX_V1,
    CACHE_KEY_PREFIX_V2,
    PAGE_KIND_V1,
    PAGE_KIND_V2,
    SOURCE_RECORDS_DAMAGED,
    classify_decoded_sample,
    classify_records,
    sanitize_transaction_records,
)
from .live_g1 import _count_method, _wrap_records, independent_fifo_worksheet
from .settlement import USDC, isolate_known_cost_events, map_decoder_trade, settlement_of
from .history_ingest import build_historical_gta_options
from .service import MassSearchService

ROOT = Path(__file__).resolve().parents[2]
GRANT_PATH = ROOT / "config" / "live_authorization.g3-ranked100-history-granted.json"
G1_GRANT_PATH = ROOT / "config" / "live_authorization.g1-granted.json"
RANKED100_GRANT_PATH = ROOT / "config" / "live_authorization.g2-ranked100-discovery-granted.json"
EXAMPLE_PATH = ROOT / "work_packages" / "mass_wallet_search_v1" / "config" / "live_authorization.example.json"
DRAFT_PATH = ROOT / "config" / "live_authorization.proof-grant-draft.json"
REACQUIRE_GRANT_PATH = ROOT / "config" / "live_authorization.g3-integrity-reacquire-rank1-draft.json"
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
    reacquire = validate_live_authorization(json.loads(REACQUIRE_GRANT_PATH.read_text(encoding="utf-8")))
    if any(row.get("enabled") for row in (example, draft, ranked, g3, reacquire)):
        raise ValueError("Example, draft, ranked-100, leftover G3, or reacquire grant file is enabled in this offline-prep tree")
    return {
        "example_enabled": False,
        "draft_enabled": False,
        "ranked100_enabled": False,
        "g3_enabled": False,
        "reacquire_enabled": False,
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


def page_cache_key(authorization_id, address, page_index, *, version=2):
    prefix = CACHE_KEY_PREFIX_V2 if version == 2 else CACHE_KEY_PREFIX_V1
    return f"{prefix}{authorization_id}:{address}:page:{page_index}"


def wallet_log_key(authorization_id, address):
    return f"g3-history:{authorization_id}:{address}:log"


def load_cached_page(store, authorization_id, address, page_index):
    if store is None:
        return None
    current = store.get(CACHE_KIND, page_cache_key(authorization_id, address, page_index, version=2))
    if current:
        return current
    legacy = store.get(CACHE_KIND, page_cache_key(authorization_id, address, page_index, version=1))
    if not legacy:
        return None
    marked = deepcopy(legacy)
    marked["integrity"] = {
        "status": SOURCE_RECORDS_DAMAGED,
        "reason": "legacy_substring_redaction_v1",
        "records": len(legacy.get("records") or []),
        "intact": 0,
        "damaged": len(legacy.get("records") or []),
        "integrity_failure": True,
        "all_unsupported": False,
    }
    marked["legacy_cache"] = True
    marked["kind"] = marked.get("kind") or PAGE_KIND_V1
    return marked


def persist_page(store, authorization_id, address, page_index, payload):
    if store is None:
        return payload
    if payload.get("kind") == PAGE_KIND_V1 or payload.get("legacy_cache"):
        return payload
    store.put(CACHE_KIND, page_cache_key(authorization_id, address, page_index, version=2), payload)
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


def further_page_allowed(first_page, episodes, *, recorded_reason, classification=None):
    classification = classification or {}
    if classification.get("integrity_failure") or classification.get("status") == SOURCE_RECORDS_DAMAGED:
        return False, "corrupted_inputs_do_not_justify_another_page"
    if classification.get("classification") in {
        SOURCE_RECORDS_DAMAGED, "MALFORMED", "UNSUPPORTED", "TRANSFERS_WITHOUT_REVIEWED_SWAP", "INACTIVITY",
    }:
        return False, classification.get("reason") or "unsupported_semantics_do_not_justify_another_page"
    if classification.get("justifies_further_page") is False:
        return False, classification.get("reason") or "sample_does_not_justify_another_page"
    if not recorded_reason:
        return False, "further_page_requires_recorded_evidence_reason"
    if not first_page.get("pagination_token"):
        return False, "no_pagination_token"
    if episodes >= 10:
        return False, "g3_episode_bar_already_met"
    allowed = {
        "insufficient_episodes_pagination_token_present",
        "page_truncated_below_g3_episode_bar",
        "insufficient_sample",
        "missing_acquisition_may_need_earlier_page",
        "insufficient_episodes_on_intact_sample",
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
        order = row.get("order")
        unresolved_order = isinstance(row.get("slot"), int) and order is None
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            if acq_unix is not None and timestamp < acq_unix:
                truncated_before_window += 1
                continue
            if end_unix is not None and timestamp >= end_unix:
                continue
            seconds = int(timestamp - start_unix)
            timestamp_missing = False
            if acq_unix is not None and timestamp < start_unix:
                role = "acquisition_support"
            else:
                role = "in_report"
            window_qualified = role == "in_report"
        else:
            seconds = None
            timestamp_missing = True
            role = "timestamp_missing"
            window_qualified = False
            unresolved_order = True
        mapped = map_decoder_trade(
            row,
            address=address,
            seconds=seconds,
            timestamp_missing=timestamp_missing,
            role=role,
            window_qualified=window_qualified,
            unresolved_order=unresolved_order,
        )
        by_mint.setdefault(mint, []).append(mapped)
    for mint, rows in list(by_mint.items()):
        first_buy = next((row for row in _ordered_inventory_rows(rows) if row.get("kind") == "buy"), None)
        if not first_buy:
            continue
        pre = first_buy.get("observed_pre_quantity_raw")
        if pre in (None, "", "0"):
            continue
        try:
            opening_units = Decimal(str(pre))
        except Exception:
            continue
        if opening_units <= 0:
            continue
        opening_order = first_buy.get("order")
        by_mint[mint] = [{
            "kind": "opening_unknown",
            "opening_unknown": True,
            "units": str(opening_units),
            "mint": mint,
            "seconds_from_start": (first_buy.get("seconds_from_start") or 0) - 1,
            "order": (opening_order - 1) if isinstance(opening_order, int) and not isinstance(opening_order, bool) else -1,
            "signature": f"opening-inventory:{mint}",
            "timestamp_missing": False,
            "settlement_mint": first_buy.get("settlement_mint"),
            "reason": "Pre-capture owned balance; no verified wallet-wide zero-inventory checkpoint",
        }] + rows
    return by_mint, truncated_before_window


def _ordered_inventory_rows(rows):
    from .settlement import _ordered_rows

    return _ordered_rows(rows)


def completed_position_episodes(rows):
    """Count genuine flat-to-flat position episodes. Partial exits are not completed episodes."""
    from decimal import Decimal

    inventory = Decimal("0")
    opened = False
    complete = 0
    sales = 0
    for event in _ordered_inventory_rows(rows):
        units = Decimal(str(event["units"]))
        if event.get("opening_unknown") or event.get("kind") == "opening_unknown":
            continue
        if event["kind"] == "buy":
            inventory += units
            opened = True
        elif event["kind"] == "sell":
            sales += 1
            if inventory <= 0:
                return {
                    "completed_episodes": 0,
                    "sale_count": sales,
                    "open": False,
                    "unsupported_sale_exceeds_inventory": True,
                }
            inventory -= units
            if inventory < 0:
                return {
                    "completed_episodes": 0,
                    "sale_count": sales,
                    "open": True,
                    "unsupported_sale_exceeds_inventory": True,
                }
            if opened and inventory == 0:
                role = event.get("role")
                qualified = event.get("window_qualified")
                if role is None and qualified is None:
                    in_window = True
                else:
                    in_window = role == "in_report" or bool(qualified)
                clean = (
                    event.get("whole_sale_pnl_resolved") is not False
                    and not event.get("partial_known_cost")
                    and not event.get("not_clean_episode")
                    and not event.get("opening_inventory_consumed")
                )
                if in_window and clean:
                    complete += 1
                opened = False
    return {
        "completed_episodes": complete,
        "sale_count": sales,
        "open": inventory > 0,
        "unsupported_sale_exceeds_inventory": False,
    }


def completed_episodes(by_mint):
    """Completed episodes are flat-to-flat closes, not FIFO sale counts."""
    total = 0
    sales = 0
    per_mint = {}
    per_mint_detail = {}
    for mint, rows in by_mint.items():
        usable = [row for row in rows if not row.get("timestamp_missing")]
        kinds = {row["kind"] for row in usable}
        if usable and settlement_of(usable[0]) == USDC:
            known, unresolved = isolate_known_cost_events(usable)
            known_kinds = {row["kind"] for row in known}
            if "buy" not in known_kinds or "sell" not in known_kinds:
                per_mint[mint] = 0
                per_mint_detail[mint] = {
                    "completed_episodes": 0,
                    "sale_count": sum(1 for row in usable if row["kind"] == "sell"),
                    "open": any(row["kind"] == "buy" for row in known),
                    "unresolved_basis_sales": len(unresolved),
                }
                continue
            counted = completed_position_episodes(known)
            counted["unresolved_basis_sales"] = len(unresolved)
            per_mint[mint] = counted["completed_episodes"]
            per_mint_detail[mint] = counted
            total += counted["completed_episodes"]
            sales += counted["sale_count"]
            continue
        usable = _ordered_inventory_rows(usable)
        known, unresolved = isolate_known_cost_events(usable)
        known_kinds = {row["kind"] for row in known}
        if "buy" not in known_kinds or "sell" not in known_kinds:
            per_mint[mint] = 0
            per_mint_detail[mint] = {
                "completed_episodes": 0,
                "sale_count": sum(1 for row in usable if row["kind"] == "sell"),
                "open": any(row["kind"] == "buy" for row in known),
                "unresolved_basis_sales": len(unresolved),
            }
            continue
        counted = completed_position_episodes(known)
        counted["unresolved_basis_sales"] = len(unresolved)
        per_mint[mint] = counted["completed_episodes"]
        per_mint_detail[mint] = counted
        total += counted["completed_episodes"]
        sales += counted["sale_count"]
    return {
        "wallet_completed_episodes": total,
        "wallet_sale_count": sales,
        "per_mint": per_mint,
        "per_mint_detail": per_mint_detail,
    }


def declared_subset_events(by_mint):
    """Wallet declared subset is every supported dated event, not the best mint alone."""
    declared = []
    for mint in sorted(by_mint):
        declared.extend(_ordered_inventory_rows(by_mint[mint]))
    return declared


def declared_subset_worksheet(by_mint):
    from .settlement import independent_settlement_worksheet

    used = []
    usdc_rows = []
    sol_rows = []
    for mint in sorted(by_mint):
        rows = _ordered_inventory_rows(by_mint[mint])
        if not rows:
            continue
        if settlement_of(rows[0]) == USDC:
            usdc_rows.extend(rows)
            used.append(mint)
        else:
            sol_rows.extend(rows)
            used.append(mint)
    worksheet = independent_settlement_worksheet(usdc_rows + sol_rows)
    if not worksheet:
        return None
    worksheet["declared_mints"] = used
    worksheet["population"] = "declared_supported_subset"
    return worksheet


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


async def fetch_helius_page(store, grant, address, *, page_index, reason, transport=None, pagination_token=None,
                            expected_signatures=None):
    entry = _provider(grant, "helius")
    if entry is None or HELIUS_METHOD not in (entry.get("allowed_operations") or []):
        raise SourceError("UNAUTHORIZED", "Grant does not allow getTransactionsForAddress")
    if used_helius_requests(store, grant) >= entry["max_requests"]:
        raise SourceError("RATE_LIMITED", "Helius G3 request ceiling reached")
    if used_helius_units(store, grant) + DOCUMENTED_HELIUS_UNITS > entry["max_units"]:
        raise SourceError("RATE_LIMITED", "Helius G3 credit ceiling reached")
    if wallet_request_count(store, grant.get("authorization_id"), address) >= int(entry.get("max_requests_per_wallet") or 3):
        raise SourceError("RATE_LIMITED", "Per-wallet G3 request ceiling reached")
    options = build_historical_gta_options(
        page_index=page_index,
        expected_signatures=expected_signatures,
        pagination_token=pagination_token,
    )
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
        sanitized = sanitize_transaction_records(result.get("records") or [])
        page = {
            "kind": PAGE_KIND_V2,
            "address": address,
            "page_index": page_index,
            "reason": reason,
            "query": {"method": HELIUS_METHOD, "options": {k: v for k, v in options.items() if k != "paginationToken"}},
            "records": sanitized["records"],
            "pagination_token": result.get("pagination_token"),
            "evidence_sha256": result.get("evidence_sha256") or sanitized["source_body_sha256"],
            "source_body_sha256": sanitized["source_body_sha256"],
            "normalized_sha256": sanitized["normalized_sha256"],
            "integrity": sanitized["integrity"],
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
    sanitized = sanitize_transaction_records(records)
    return {
        "kind": PAGE_KIND_V2,
        "address": address,
        "page_index": page_index,
        "reason": reason,
        "query": {"method": HELIUS_METHOD, "options": dict(EXACT_HELIUS_OPTIONS)},
        "records": sanitized["records"],
        "pagination_token": pagination_token,
        "evidence_sha256": sanitized["source_body_sha256"],
        "source_body_sha256": sanitized["source_body_sha256"],
        "normalized_sha256": sanitized["normalized_sha256"],
        "integrity": sanitized["integrity"],
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
    integrity = page.get("integrity") or classify_records(page.get("records") or [])
    observations = []
    if integrity.get("integrity_failure") or integrity.get("status") == SOURCE_RECORDS_DAMAGED:
        classification = {
            "classification": SOURCE_RECORDS_DAMAGED,
            "justifies_further_page": False,
            "reason": "corrupted_inputs_do_not_justify_another_page",
        }
        observations.append({
            "kind": SOURCE_RECORDS_DAMAGED,
            "detail": "Required token balance arrays were destroyed or never stored intact. Integrity failure is not an unsupported trade.",
        })
        report = {
            "id": f"g3-damaged-{address[:8]}-{page.get('page_index') or 0}",
            "address": address,
            "source": "mass-search",
            "policy": "UNRESOLVED",
            "g3_status": SOURCE_RECORDS_DAMAGED,
            "source_integrity": integrity,
            "observations": observations,
            "worksheet": None,
            "events": [],
            "notes": ["SOURCE_RECORDS_DAMAGED. Do not invent profitability. Do not silently reacquire."],
        }
        store.put("reports", report["id"], report)
        run_id = getattr(service, "_g3_run_id", None)
        if run_id:
            with store.lock, store.db:
                store.db.execute(
                    "INSERT INTO report_links VALUES (?,?,?,?,?,?)",
                    (uuid.uuid4().hex, run_id, f"solana:{address}", report["id"],
                     json.dumps({"source_integrity": integrity, "observations": observations}),
                     utc_now()),
                )
        return {
            "address": address,
            "shortlist_rank": candidate["shortlist_rank"],
            "role": candidate["role"],
            "status": SOURCE_RECORDS_DAMAGED,
            "g3_qualifying": False,
            "wallet_completed_episodes": 0,
            "wallet_sale_count": 0,
            "per_mint_episodes": {},
            "per_mint_drilldown": {},
            "declared_mints": [],
            "report_mint": None,
            "report_id": report["id"],
            "policy": "UNRESOLVED",
            "not_wallet_wide_match": True,
            "worksheet": None,
            "observations": observations,
            "classification": classification,
            "integrity": integrity,
            "truncated_before_acquisition_support": 0,
            "coverage_note": "Damaged source records are not a venue-coverage measurement.",
            "page_evidence_sha256": page.get("evidence_sha256"),
            "source_body_sha256": page.get("source_body_sha256"),
            "normalized_sha256": page.get("normalized_sha256"),
            "from_cache": bool(page.get("from_cache")),
            "external_requests": int(page.get("external_requests") or 0),
            "label": candidate.get("label"),
            "pagination_token_present": bool(page.get("pagination_token")),
        }
    decode = decode or decode_supported_swaps
    records = _wrap_records(page.get("records") or [])
    decoded = decode(records, address)
    classification = classify_decoded_sample(decoded, integrity)
    by_mint, truncated = decoder_events_by_mint(
        decoded, address=address,
        window_start=windows["report_start_inclusive"],
        window_end=windows["report_end_exclusive"],
        acquisition_start=windows["acquisition_support_start_inclusive"],
    )
    episodes = completed_episodes(by_mint)
    declared_events = declared_subset_events(by_mint)
    worksheet = declared_subset_worksheet(by_mint)
    mint = None if not by_mint else "declared-supported-subset"
    report = None
    corpus = "SYNTHETIC" if page.get("units_are") == "fixture" else "GENUINE_LIVE"
    unresolved = list((decoded.get("unresolved") or [])[:20])
    observations.extend({
        "kind": "unsupported" if row.get("reason") else "observation",
        "signature": row.get("signature"),
        "reason": row.get("reason"),
        "path": row.get("path"),
    } for row in unresolved)
    missing = [row for rows in by_mint.values() for row in rows if row.get("timestamp_missing")]
    if missing:
        observations.append({
            "kind": "timestamp_missing",
            "count": len(missing),
            "detail": "Missing timestamps stay missing and do not qualify hold-time or the report window.",
        })
    if declared_events:
        reconstructed = service.reconstruct_candidate(
            service._g3_run_id, f"solana:{address}", declared_events,
            corpus_kind=corpus, mint=mint,
        )
        report = reconstructed["report"]
        report["source"] = "mass-search"
        report["policy"] = report.get("policy") or "UNRESOLVED"
        report["worksheet"] = worksheet or report.get("worksheet")
        report["g3_status"] = "DECLARED_SUBSET"
        report["source_integrity"] = integrity
        report["declared_mints"] = sorted(by_mint)
        report["per_mint_drilldown"] = episodes.get("per_mint_detail") or {}
        report["observations"] = observations
        report["wallet_completed_episodes"] = episodes["wallet_completed_episodes"]
        store.put("reports", report["id"], report)
    qualifying = bool(worksheet) and episodes["wallet_completed_episodes"] >= 10
    if integrity.get("integrity_failure"):
        status = SOURCE_RECORDS_DAMAGED
    elif worksheet and not qualifying:
        status = "VISIBLE_BELOW_G3"
    elif qualifying:
        status = "QUALIFYING"
    else:
        status = classification.get("classification") or "NO_SUPPORTED_CLOSED_PAIR"
        if status == "SUPPORTED_ACTIVITY":
            status = "NO_SUPPORTED_CLOSED_PAIR"
    return {
        "address": address,
        "shortlist_rank": candidate["shortlist_rank"],
        "role": candidate["role"],
        "status": status,
        "g3_qualifying": qualifying,
        "wallet_completed_episodes": episodes["wallet_completed_episodes"],
        "wallet_sale_count": episodes.get("wallet_sale_count") or 0,
        "per_mint_episodes": episodes["per_mint"],
        "per_mint_drilldown": episodes.get("per_mint_detail") or {},
        "declared_mints": sorted(by_mint),
        "report_mint": mint,
        "report_id": None if report is None else report["id"],
        "policy": None if report is None else report.get("policy"),
        "not_wallet_wide_match": True,
        "worksheet": worksheet,
        "observations": observations,
        "classification": classification,
        "integrity": integrity,
        "truncated_before_acquisition_support": truncated,
        "coverage_note": "Honest truncation: events before the 90-day acquisition-support start were excluded; missing timestamps stay unknown. Exclusive report-end is enforced. Declared subset matches qualification.",
        "page_evidence_sha256": page.get("evidence_sha256"),
        "source_body_sha256": page.get("source_body_sha256"),
        "normalized_sha256": page.get("normalized_sha256"),
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
                classification={**(summary.get("integrity") or {}), **(summary.get("classification") or {})},
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
