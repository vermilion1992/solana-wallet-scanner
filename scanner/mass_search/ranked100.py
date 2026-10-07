"""RANKED_100_DISCOVERY_PILOT: one exact Birdeye page, local shortlist ≤20.

Offline is the default. Live HTTP is refused unless a separately armed grant,
confirmed quota, and credentials are all present. G1 grant must not be reused.
"""
from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from scanner.mass_search.adapters import (
    ALLOWED_BIRDEYE_HOST,
    ALLOWED_BIRDEYE_PATH,
    BirdeyeTraderAdapter,
    SourceError,
    parse_trader_row,
)
from scanner.mass_search.capability import (
    LIVE_AUTH_SCHEMA,
    documented_birdeye_traders,
    redact_secrets,
    utc_now,
    validate_live_authorization,
)
from scanner.mass_search.plan import canonical_json, sha256_json
from scanner.mass_search.universe import synthetic_address

ROOT = Path(__file__).resolve().parents[2]
GRANT_PATH = ROOT / "config" / "live_authorization.g2-ranked100-discovery-granted.json"
G1_GRANT_PATH = ROOT / "config" / "live_authorization.g1-granted.json"
EXAMPLE_PATH = ROOT / "work_packages" / "mass_wallet_search_v1" / "config" / "live_authorization.example.json"
DRAFT_PATH = ROOT / "config" / "live_authorization.proof-grant-draft.json"

OUTCOME_LABEL = "RANKED_100_DISCOVERY_PILOT"
AUTHORIZATION_ID = "live-g2-ranked100-discovery-2026-10-05-mitch"
G1_AUTHORIZATION_ID = "live-g1-vertical-slice-2026-10-05-mitch"
CANDIDATE_LABEL = (
    "Provider-ranked candidate — profitability and copyability not independently verified."
)
CACHE_KIND = "mass_search_cache"
CACHE_RECORD_KIND = "ranked100-discovery-cache-v1"
SHORTLIST_RECORD_KIND = "ranked100-discovery-shortlist-v1"
BIRDEYE_KEY_ENV = "BIRDEYE_API_KEY"
DOCUMENTED_BIRDEYE_UNITS = 30

EXACT_QUERY = {
    "provider": "birdeye",
    "method": "GET",
    "host": ALLOWED_BIRDEYE_HOST,
    "path": ALLOWED_BIRDEYE_PATH,
    "chain": "solana",
    "params": {
        "type": "30d",
        "sort_by": "trader_score",
        "sort_type": "desc",
        "offset": 0,
        "limit": 100,
    },
}

RANKED_100_PRESET = {
    "name": "Ranked-100 discovery-only pilot",
    "outcome_label": OUTCOME_LABEL,
    "not_full_g2": True,
    "candidate_target": 100,
    "local_shortlist_ceiling": 20,
    "live_enrichment": False,
    "helius_requests": 0,
    "helius_units": 0,
    "other_providers": 0,
    "exact_query": deepcopy(EXACT_QUERY),
    "incomplete_below_target": "honest_incomplete_acquisition",
    "pad_shortlist": False,
    "candidate_label": CANDIDATE_LABEL,
    "heuristics": {
        "prefer_positive_reported_realised_pnl": True,
        "prefer_recent_activity_within_days": 7,
        "prefer_provider_trade_count_at_least": 20,
        "trade_window": "30d",
        "rank_survivors_by": "provider_trader_score",
        "missing_metric_stays": "unknown",
        "high_score_missing_fields": "needs_verification",
        "trade_count_is_not": "completed_profitable_trades",
        "adjustable": True,
    },
}


def load_ranked100_grant(path=None):
    payload = json.loads(Path(path or GRANT_PATH).read_text(encoding="utf-8"))
    if payload.get("schema_version") != LIVE_AUTH_SCHEMA:
        raise ValueError("Grant must use live-research-authorization-v1")
    if payload.get("authorization_id") == G1_AUTHORIZATION_ID:
        raise ValueError("G1 grant must not be reused for RANKED_100_DISCOVERY_PILOT")
    if payload.get("authorization_id") != AUTHORIZATION_ID:
        raise ValueError("This runner only accepts live-g2-ranked100-discovery-2026-10-05-mitch")
    if payload.get("do_not_reset_setup_pilot") is not True:
        raise ValueError("Ranked-100 grant must leave setup-pilot untouched")
    if payload.get("max_additional_spend_usd") != "0":
        raise ValueError("Ranked-100 grant forbids additional spend")
    return payload


def assert_non_grants_stay_disabled():
    example = validate_live_authorization(json.loads(EXAMPLE_PATH.read_text(encoding="utf-8")))
    draft = validate_live_authorization(json.loads(DRAFT_PATH.read_text(encoding="utf-8")))
    ranked = validate_live_authorization(json.loads(GRANT_PATH.read_text(encoding="utf-8")))
    if example.get("enabled") or draft.get("enabled") or ranked.get("enabled"):
        raise ValueError("Example, draft, or ranked-100 grant file is enabled in this offline-prep tree")
    g1 = json.loads(G1_GRANT_PATH.read_text(encoding="utf-8"))
    if g1.get("authorization_id") != G1_AUTHORIZATION_ID:
        raise ValueError("G1 grant identity changed unexpectedly")
    return {
        "example_enabled": False,
        "draft_enabled": False,
        "ranked100_enabled": False,
        "g1_not_reused": True,
    }


def _provider(grant, provider_id):
    for entry in grant.get("providers") or []:
        if entry.get("provider_id") == provider_id:
            return entry
    return None


def arming_blockers(grant, *, credentials=None):
    """Conditions that must be satisfied before any live spend. Does not arm."""
    blockers = []
    if grant.get("authorization_id") == G1_AUTHORIZATION_ID:
        blockers.append({"code": "g1_grant_reuse_forbidden", "detail": "G1 grant must not be reused"})
        return blockers
    if grant.get("authorization_id") != AUTHORIZATION_ID:
        blockers.append({"code": "unexpected_authorization_id", "detail": grant.get("authorization_id")})
    if grant.get("enabled") is not True:
        blockers.append({"code": "grant_disabled", "detail": "Ranked-100 grant stays disabled until quota/CU confirmation"})
    expires = grant.get("expires_at")
    if isinstance(expires, str) and expires and expires <= utc_now():
        blockers.append({"code": "grant_expired", "detail": expires})
    birdeye = _provider(grant, "birdeye")
    if birdeye is None:
        blockers.append({"code": "missing_birdeye_budget", "detail": "Birdeye ceiling is required"})
    else:
        if birdeye.get("existing_plan_confirmed") is not True:
            blockers.append({"code": "existing_plan_unconfirmed", "detail": "Operator must confirm the existing Birdeye plan"})
        if not birdeye.get("remaining_quota_confirmed_at"):
            blockers.append({
                "code": "remaining_quota_unconfirmed",
                "detail": "Operator must confirm remaining Birdeye quota/CU on the billing dashboard before arming",
            })
        if birdeye.get("max_requests") != 1 or birdeye.get("max_units") != 30:
            blockers.append({"code": "birdeye_ceiling_mismatch", "detail": "Birdeye must be 1 request / 30 CU"})
    helius = _provider(grant, "helius")
    if helius is not None and (helius.get("max_requests") != 0 or helius.get("max_units") != 0):
        blockers.append({"code": "helius_must_be_zero", "detail": "This pilot forbids Helius"})
    if grant.get("max_additional_spend_usd") != "0":
        blockers.append({"code": "paid_spend_forbidden", "detail": "max_additional_spend_usd must be 0"})
    presence = credentials if credentials is not None else {
        "birdeye": bool(os.environ.get(BIRDEYE_KEY_ENV)),
    }
    if not presence.get("birdeye"):
        blockers.append({"code": "missing_provider_credentials", "detail": "BIRDEYE_API_KEY is absent in this runtime"})
    return blockers


def cache_key(authorization_id):
    digest = sha256_json(EXACT_QUERY)
    return f"ranked100:{authorization_id}:{digest}"


def load_cached_page(store, authorization_id):
    if store is None:
        return None
    return store.get(CACHE_KIND, cache_key(authorization_id))


def persist_cache(store, payload):
    if store is None:
        return payload
    store.put(CACHE_KIND, cache_key(payload["authorization_id"]), payload)
    return payload


def persist_shortlist(store, authorization_id, payload):
    if store is None:
        return payload
    store.put(CACHE_KIND, f"ranked100-shortlist:{authorization_id}", payload)
    return payload


def rescreen_from_cache(store, grant, *, heuristics=None):
    """Change local filters without any provider call. Missing cache is not a fetch trigger."""
    cached = load_cached_page(store, grant["authorization_id"])
    if cached is None:
        raise SourceError(
            "UNAUTHORIZED",
            "No cached ranked-100 page; refusing a second provider request",
        )
    screening = screen_ranked100(
        cached["parsed_rows"],
        heuristics=heuristics,
        as_of=cached.get("fetched_at"),
    )
    persist_shortlist(store, grant["authorization_id"], screening)
    return screening, cached


def used_birdeye_requests(store, grant):
    entry = _provider(grant, "birdeye")
    if store is None or entry is None:
        return 0
    with store.lock:
        row = store.db.execute(
            "SELECT COUNT(*) FROM reservations WHERE provider=? AND cycle=? AND method=? "
            "AND state IN ('dispatched','settled')",
            ("birdeye", entry["cycle_start"], "trader_gainers_losers"),
        ).fetchone()
    return int(row[0] if row else 0)


def parse_ranked_items(items, *, fetch_timestamp, source_id="birdeye-traders"):
    field_map = documented_birdeye_traders()["field_map"]
    parsed = []
    for index, raw in enumerate(items or []):
        row = parse_trader_row(
            raw,
            field_map=field_map,
            source_id=source_id,
            page=0,
            offset=0,
            fetch_timestamp=fetch_timestamp,
        )
        row["source_order"] = index
        parsed.append(row)
    return parsed


def _decimal(value):
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return number


def _unix_seconds(value):
    if type(value) is int and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _as_of_unix(value):
    if value is None:
        return None
    if type(value) is int and not isinstance(value, bool):
        return value
    if not isinstance(value, str) or not value:
        return None
    stamp = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return int(datetime.fromisoformat(stamp).timestamp())
    except ValueError:
        return None


def default_heuristics():
    return deepcopy(RANKED_100_PRESET["heuristics"])


def screen_ranked100(rows, *, heuristics=None, as_of=None):
    """First-pass local screening. Missing measurements stay unknown. Do not pad."""
    rules = {**default_heuristics(), **(heuristics or {})}
    as_of_unix = _as_of_unix(as_of) or _as_of_unix(utc_now())
    seen = {}
    decisions = []
    for row in rows:
        source_order = row.get("source_order", len(decisions))
        if not row.get("valid"):
            decisions.append({
                "address": None,
                "source_order": source_order,
                "decision": "excluded",
                "reason_codes": [row.get("reason") or "invalid_row"],
                "label": CANDIDATE_LABEL,
                "provider_score": None,
                "uncertainty": ["invalid_or_unusable_row"],
            })
            continue
        address = row["address"]
        if address in seen:
            decisions.append({
                "address": address,
                "source_order": source_order,
                "decision": "excluded",
                "reason_codes": ["excluded_duplicate_address"],
                "label": CANDIDATE_LABEL,
                "provider_score": row.get("trader_score"),
                "uncertainty": ["duplicate_keeps_first_source_order"],
            })
            continue
        seen[address] = source_order
        reasons = []
        uncertainty = []
        score = _decimal(row.get("trader_score"))
        pnl = _decimal(row.get("realized_pnl"))
        trades = row.get("trade_count")
        last_active = _unix_seconds(row.get("last_active"))
        eligible = True
        if score is None:
            eligible = False
            reasons.append("excluded_missing_provider_score")
            uncertainty.append("provider_score_unknown")
        metrics = {
            "provider_score": None if score is None else format(score, "f"),
            "provider_score_unit": row.get("trader_score_unit") or "provider_score",
            "provider_score_basis": "PROVIDER_REPORTED",
            "realized_pnl": None if pnl is None else format(pnl, "f"),
            "realized_pnl_unit": row.get("realized_pnl_unit") or "USD",
            "realized_pnl_basis": row.get("realized_pnl_basis") or "PROVIDER_REPORTED",
            "realized_pnl_definition": "provider-reported realised P&L; currency attached; not independently verified",
            "trade_count": trades,
            "trade_count_is_not": "completed_profitable_trades",
            "last_active": last_active,
            "last_active_unit": "unix_seconds",
        }
        if pnl is None:
            uncertainty.append("realized_pnl_unknown")
        elif rules.get("prefer_positive_reported_realised_pnl"):
            if pnl > 0:
                reasons.append("prefer_positive_reported_realised_pnl")
            else:
                eligible = False
                reasons.append("excluded_known_non_positive_reported_pnl")
        if last_active is None:
            uncertainty.append("recent_activity_unknown")
        else:
            age_days = Decimal(as_of_unix - last_active) / Decimal(86400)
            metrics["activity_age_days"] = format(age_days, "f")
            if age_days <= Decimal(str(rules["prefer_recent_activity_within_days"])):
                reasons.append("prefer_recent_activity_within_days")
            else:
                eligible = False
                reasons.append("excluded_stale_provider_activity")
        if trades is None:
            uncertainty.append("trade_count_unknown")
            reasons.append("provider_trade_count_proxy_not_completed_profitable_trades")
        else:
            reasons.append("provider_trade_count_proxy_not_completed_profitable_trades")
            if trades >= int(rules["prefer_provider_trade_count_at_least"]):
                reasons.append("prefer_repeated_trading_proxy")
            else:
                eligible = False
                reasons.append("excluded_low_provider_trade_count_proxy")
        if score is not None and uncertainty:
            reasons.append("high_score_missing_fields_needs_verification")
        decisions.append({
            "address": address,
            "source_order": source_order,
            "decision": "eligible" if eligible else "excluded",
            "reason_codes": reasons or ["provider_ranked_row"],
            "label": CANDIDATE_LABEL,
            "provider_score": None if score is None else format(score, "f"),
            "metrics": metrics,
            "uncertainty": uncertainty,
            "evidence_status": "unverified",
        })

    eligible = [row for row in decisions if row["decision"] == "eligible"]
    ranked = sorted(
        eligible,
        key=lambda row: (
            Decimal(row["provider_score"] or "0") * -1,
            row["source_order"],
            row["address"] or "",
        ),
    )
    ceiling = RANKED_100_PRESET["local_shortlist_ceiling"]
    shortlist = []
    for index, row in enumerate(ranked):
        item = dict(row)
        if index < ceiling:
            item["decision"] = "shortlisted"
            item["shortlist_rank"] = index + 1
            item["reason_codes"] = list(item["reason_codes"]) + ["ranked_by_provider_score"]
            shortlist.append(item)
        else:
            item["decision"] = "excluded"
            item["reason_codes"] = list(item["reason_codes"]) + ["excluded_below_shortlist_ceiling"]
    shortlist_ids = {item["address"] for item in shortlist}
    exclusions = []
    for row in decisions:
        if row["address"] in shortlist_ids and row["decision"] == "eligible":
            continue
        if row["decision"] == "eligible" and row["address"] not in shortlist_ids:
            overflow = next(item for item in ranked if item["address"] == row["address"])
            exclusions.append({
                **overflow,
                "decision": "excluded",
                "reason_codes": list(overflow["reason_codes"]) + ["excluded_below_shortlist_ceiling"],
            })
        elif row["decision"] != "eligible":
            exclusions.append(row)
    unique_valid = len(seen)
    return {
        "kind": SHORTLIST_RECORD_KIND,
        "outcome_label": OUTCOME_LABEL,
        "candidate_label": CANDIDATE_LABEL,
        "heuristics": rules,
        "unique_valid_wallets": unique_valid,
        "acquisition_complete": unique_valid >= RANKED_100_PRESET["candidate_target"],
        "acquisition_note": (
            None if unique_valid >= RANKED_100_PRESET["candidate_target"]
            else "honest_incomplete_acquisition"
        ),
        "shortlist": shortlist,
        "exclusions": exclusions,
        "shortlist_count": len(shortlist),
        "padded": False,
        "not_confirmed_profitable": True,
        "not_independently_verified": True,
    }


def available_metrics(rows):
    keys = {
        "trader_score": 0,
        "realized_pnl": 0,
        "trade_count": 0,
        "last_active": 0,
    }
    for row in rows:
        if not row.get("valid"):
            continue
        if row.get("trader_score") is not None:
            keys["trader_score"] += 1
        if row.get("realized_pnl") is not None:
            keys["realized_pnl"] += 1
        if row.get("trade_count") is not None:
            keys["trade_count"] += 1
        if row.get("last_active") is not None:
            keys["last_active"] += 1
    return keys


def _page_from_items(items, *, fetch_timestamp, source_id="fixture-traders", corpus_kind="SYNTHETIC"):
    parsed = parse_ranked_items(items, fetch_timestamp=fetch_timestamp, source_id=source_id)
    raw = {"items": items, "query": EXACT_QUERY["params"]}
    return {
        "source_id": source_id,
        "state": "AUTHORIZED_AVAILABLE",
        "window": EXACT_QUERY["params"]["type"],
        "offset": 0,
        "limit": 100,
        "query": dict(EXACT_QUERY["params"]),
        "rows": parsed,
        "raw_count": len(items),
        "raw_body": redact_secrets(raw),
        "evidence_sha256": hashlib.sha256(canonical_json(redact_secrets(raw)).encode()).hexdigest(),
        "billing_unit": "fixture_request",
        "units": 0,
        "external_requests": 0,
        "corpus_kind": corpus_kind,
        "fetched_at": fetch_timestamp,
    }


def fixture_ranked_page(*, fetch_timestamp="2026-10-05T12:00:00Z"):
    """Synthetic ranked page with trader_score plus mixed metric completeness."""
    as_of = _as_of_unix(fetch_timestamp)
    recent = as_of - 2 * 86400
    stale = as_of - 20 * 86400
    items = []
    for index in range(100):
        address = synthetic_address(2000 + index)
        row = {
            "address": address,
            "trader_score": 1000 - index,
            "rank": index + 1,
            "network": "solana",
        }
        if index < 25:
            row["realized_pnl"] = str(50 - index)
            row["pnl"] = row["realized_pnl"]
            row["trade_count"] = 20 + index
            row["last_trade_unix_time"] = recent
        elif index == 25:
            row["realized_pnl"] = "-3"
            row["trade_count"] = 40
            row["last_trade_unix_time"] = recent
        elif index == 26:
            row["realized_pnl"] = "12"
            row["trade_count"] = 4
            row["last_trade_unix_time"] = recent
        elif index == 27:
            row["realized_pnl"] = "12"
            row["trade_count"] = 40
            row["last_trade_unix_time"] = stale
        items.append(row)
    return items


def _cache_record(grant, page, *, from_cache, billed_requests):
    unique = len({row["address"] for row in page["rows"] if row.get("valid")})
    return {
        "kind": CACHE_RECORD_KIND,
        "outcome_label": OUTCOME_LABEL,
        "authorization_id": grant.get("authorization_id"),
        "query": deepcopy(EXACT_QUERY),
        "fetched_at": page.get("fetched_at") or utc_now(),
        "source_id": page.get("source_id"),
        "corpus_kind": page.get("corpus_kind"),
        "raw_page": page.get("raw_body") or redact_secrets({"rows": [row.get("raw") for row in page.get("rows") or []]}),
        "source_order": [row.get("address") for row in page.get("rows") or []],
        "scores": [
            {"address": row.get("address"), "trader_score": row.get("trader_score"), "source_order": row.get("source_order")}
            for row in page.get("rows") or [] if row.get("valid")
        ],
        "parsed_rows": page.get("rows") or [],
        "unique_valid_wallets": unique,
        "acquisition_complete": unique >= RANKED_100_PRESET["candidate_target"],
        "raw_count": page.get("raw_count"),
        "evidence_sha256": page.get("evidence_sha256"),
        "from_cache": from_cache,
        "billing": {
            "birdeye_requests": billed_requests,
            "birdeye_units_documented": DOCUMENTED_BIRDEYE_UNITS if billed_requests else 0,
            "units_are": "documented_estimate_not_confirmed_dashboard_receipt",
            "helius_requests": 0,
            "helius_units": 0,
            "other_providers": 0,
        },
        "external_requests": 0 if from_cache else int(page.get("external_requests") or 0),
    }


async def acquire_ranked100_page(store, grant, *, transport=None, fixture_items=None, allow_live=False):
    cached = load_cached_page(store, grant["authorization_id"])
    if cached:
        served = deepcopy(cached)
        served["from_cache"] = True
        served["external_requests"] = 0
        return served, True
    used = used_birdeye_requests(store, grant)
    if used >= 1:
        raise SourceError(
            "RATE_LIMITED",
            "Ranked-100 one-request ceiling already consumed; reopen must use the cached page",
        )
    if allow_live:
        blockers = arming_blockers(grant)
        if blockers:
            raise SourceError("UNAUTHORIZED", blockers[0]["detail"])
        checked = validate_live_authorization(grant)
        adapter = BirdeyeTraderAdapter(transport=transport)
        page = await adapter.fetch_page(
            offset=EXACT_QUERY["params"]["offset"],
            limit=EXACT_QUERY["params"]["limit"],
            window=EXACT_QUERY["params"]["type"],
            sort_by=EXACT_QUERY["params"]["sort_by"],
            sort_type=EXACT_QUERY["params"]["sort_type"],
            authorization=checked,
            store=store,
        )
        page["fetched_at"] = page.get("fetched_at") or utc_now()
        record = _cache_record(grant, page, from_cache=False, billed_requests=1)
        persist_cache(store, record)
        return record, False

    items = fixture_items if fixture_items is not None else fixture_ranked_page()
    if transport is not None:
        checked = validate_live_authorization(grant) if grant.get("enabled") is True else None
        if checked is None:
            raise SourceError("UNAUTHORIZED", "Offline transport simulation still requires an enabled test grant")
        adapter = BirdeyeTraderAdapter(transport=transport)
        page = await adapter.fetch_page(
            offset=EXACT_QUERY["params"]["offset"],
            limit=EXACT_QUERY["params"]["limit"],
            window=EXACT_QUERY["params"]["type"],
            sort_by=EXACT_QUERY["params"]["sort_by"],
            sort_type=EXACT_QUERY["params"]["sort_type"],
            authorization=checked,
            store=store,
        )
        page["fetched_at"] = page.get("fetched_at") or utc_now()
        record = _cache_record(grant, page, from_cache=False, billed_requests=1)
        persist_cache(store, record)
        return record, False

    page = _page_from_items(items, fetch_timestamp=utc_now(), source_id="fixture-traders")
    record = _cache_record(grant, page, from_cache=False, billed_requests=0)
    persist_cache(store, record)
    return record, False


def run_ranked100_pilot(
    store,
    *,
    grant_path=None,
    fixture_items=None,
    transport=None,
    allow_live=False,
    heuristics=None,
    evidence_dir=None,
):
    """Offline-default pilot. Live dispatch is opt-in and still blocked by arming_blockers."""
    grant = load_ranked100_grant(grant_path)
    non_grants = assert_non_grants_stay_disabled()
    blockers = arming_blockers(grant)
    setup_pilot = store.usage("helius", "setup-pilot", 200) if store else None
    result = {
        "outcome_label": OUTCOME_LABEL,
        "not_full_g2": True,
        "authorization_id": grant.get("authorization_id"),
        "grant_path": str(Path(grant_path or GRANT_PATH).relative_to(ROOT)) if (grant_path or GRANT_PATH).is_absolute() else str(grant_path or GRANT_PATH),
        "grant_enabled": bool(grant.get("enabled")),
        "preset": deepcopy(RANKED_100_PRESET),
        "arming_blockers": blockers,
        "non_grants": non_grants,
        "setup_pilot": setup_pilot,
        "external_requests": 0,
        "from_cache": False,
        "PRODUCT_READY": False,
    }
    if allow_live:
        if blockers:
            result["status"] = "BLOCKED"
            result["blocker"] = blockers[0]["code"]
            result["detail"] = blockers[0]["detail"]
            _write_receipt(evidence_dir, result)
            return result
    else:
        result["live_dispatch"] = False
        result["detail"] = "Offline ranked-100 pilot; live Birdeye/Helius not dispatched"

    import asyncio

    async def _run():
        return await acquire_ranked100_page(
            store, grant if allow_live or transport is not None else grant,
            transport=transport,
            fixture_items=fixture_items,
            allow_live=allow_live,
        )

    try:
        cache, from_cache = asyncio.run(_run()) if not isinstance(store, type(None)) else asyncio.run(_run())
    except SourceError as error:
        result["status"] = "BLOCKED"
        result["blocker"] = error.state
        result["detail"] = str(error)
        result["birdeye_requests_used"] = used_birdeye_requests(store, grant)
        _write_receipt(evidence_dir, result)
        return result

    screening = screen_ranked100(
        cache["parsed_rows"],
        heuristics=heuristics,
        as_of=cache.get("fetched_at"),
    )
    persist_shortlist(store, grant["authorization_id"], screening)
    result.update({
        "status": "OFFLINE_PASS" if not allow_live else "PASS",
        "from_cache": from_cache,
        "external_requests": 0 if from_cache else int(cache.get("external_requests") or 0),
        "cache": {
            "evidence_sha256": cache.get("evidence_sha256"),
            "unique_valid_wallets": cache.get("unique_valid_wallets"),
            "acquisition_complete": cache.get("acquisition_complete"),
            "raw_count": cache.get("raw_count"),
            "query": cache.get("query"),
            "billing": cache.get("billing"),
            "fetched_at": cache.get("fetched_at"),
        },
        "available_metrics": available_metrics(cache["parsed_rows"]),
        "shortlist_count": screening["shortlist_count"],
        "shortlist": screening["shortlist"],
        "exclusions": screening["exclusions"],
        "acquisition_note": screening["acquisition_note"],
        "candidate_label": CANDIDATE_LABEL,
        "birdeye_requests_used": used_birdeye_requests(store, grant),
        "setup_pilot_after": store.usage("helius", "setup-pilot", 200) if store else None,
    })
    if result["setup_pilot"] != result["setup_pilot_after"] and result["setup_pilot"] is not None:
        result["status"] = "BLOCKED"
        result["blocker"] = "setup_pilot_changed"
        result["detail"] = "Ranked-100 must not reset or charge setup-pilot"
    _write_receipt(evidence_dir, result)
    return result


def _write_receipt(evidence_dir, result):
    if not evidence_dir:
        return
    path = Path(evidence_dir)
    path.mkdir(parents=True, exist_ok=True)
    payload = json.loads(json.dumps(redact_secrets(result), default=str))
    (path / "RANKED_100_RESULT.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (path / "INDEX.json").write_text(json.dumps({
        "outcome_label": OUTCOME_LABEL,
        "status": result.get("status"),
        "authorization_id": result.get("authorization_id"),
        "from_cache": result.get("from_cache"),
        "shortlist_count": result.get("shortlist_count"),
        "external_requests": result.get("external_requests"),
        "blocker": result.get("blocker"),
        "result": "RANKED_100_RESULT.json",
        "not_full_g2": True,
        "PRODUCT_READY": False,
    }, indent=2) + "\n", encoding="utf-8")


def armed_test_grant(base=None):
    """In-memory grant for adapter-path tests. Never writes enabled=true to disk."""
    payload = deepcopy(base or json.loads(GRANT_PATH.read_text(encoding="utf-8")))
    payload["enabled"] = True
    payload["expires_at"] = "2099-01-01T00:00:00Z"
    for entry in payload["providers"]:
        if entry["provider_id"] == "birdeye":
            entry["existing_plan_confirmed"] = True
            entry["remaining_quota_confirmed_at"] = payload["authorized_by_user_at"]
    return validate_live_authorization(payload)
