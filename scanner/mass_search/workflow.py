"""Cached ranked-100 → filter → reconstruct strongest available capture. Zero live calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scanner.mass_search.canonical_records import gta_records_from_capture
from scanner.mass_search.funnel_abc import classify_candidate, rank_next_candidates
from scanner.mass_search.g3_reacquire import ALLOWED_WALLET
from scanner.mass_search.history_ingest import replay_cached_history_to_report
from scanner.mass_search.research_profile import build_research_profile, default_filters, load_filters, save_filters

ROOT = Path(__file__).resolve().parents[2]
RANKED_RAW_PATH = ROOT / "evidence/mass-wallet-funnel/ranked100-discovery-pilot-2026-10-05/RAW.json"
SHORTLIST_PATH = ROOT / "evidence/mass-wallet-funnel/ranked100-discovery-pilot-2026-10-05/SHORTLIST.json"
CAPTURE_PATH = ROOT / "evidence/mass-wallet-funnel/ranked100-anchored-validation-live/SOURCE_RESPONSE_page0.json"
EXPECTED_CAPTURE_SHA = "53a5c6f46ec2e0f8c895df6398116756ae3728892f0a6b702137f56d8624328d"
WINDOWS = {
    "report_start_inclusive": "2026-09-05T13:29:27Z",
    "report_end_exclusive": "2026-10-05T13:29:27Z",
    "acquisition_support_start_inclusive": "2026-07-07T13:29:27Z",
}
CAPTURED_ADDRESSES = {ALLOWED_WALLET}


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_ranked_universe():
    raw = _load_json(RANKED_RAW_PATH)
    items = (((raw.get("raw_page") or {}).get("data") or {}).get("items")) or []
    shortlist = _load_json(SHORTLIST_PATH)
    short_by_address = {row["address"]: row for row in shortlist.get("shortlist") or []}
    rows = []
    for index, item in enumerate(items):
        address = item.get("address")
        short = short_by_address.get(address) or {}
        rows.append({
            "address": address,
            "provider_rank": index + 1,
            "source_order": index,
            "provider_score": str(item.get("score")) if item.get("score") is not None else None,
            "trade_count": item.get("trade_count"),
            "metrics": {
                "provider_score": str(item.get("score")) if item.get("score") is not None else None,
                "realized_pnl": str(item.get("realized_pnl")) if item.get("realized_pnl") is not None else None,
                "realized_pnl_unit": "USD",
                "realized_pnl_basis": "PROVIDER_REPORTED",
                "trade_count": item.get("trade_count"),
                "trade_count_is_not": "completed_profitable_trades",
            },
            "shortlisted": address in short_by_address,
            "shortlist_rank": short.get("shortlist_rank"),
            "capture_available": address in CAPTURED_ADDRESSES,
            "label": short.get("label") or "Provider-ranked candidate — profitability and copyability not independently verified.",
            "evidence_status": "cached_capture" if address in CAPTURED_ADDRESSES else "unverified",
        })
    return {
        "kind": "ranked-100-cached-universe-v1",
        "ranked_count": len(rows),
        "shortlist_count": len(short_by_address),
        "capture_count": sum(1 for row in rows if row["capture_available"]),
        "rows": rows,
        "capture_sha256": EXPECTED_CAPTURE_SHA,
        "PRODUCT_READY": False,
        "live_enabled": False,
    }


def apply_local_filters(rows, filters):
    """Local browse filters. Unset thresholds do not hide rows."""
    thresholds = (filters or {}).get("thresholds") or {}
    min_trades = thresholds.get("min_provider_trade_count")
    only_shortlist = bool((filters or {}).get("only_shortlist"))
    only_captured = bool((filters or {}).get("only_captured"))
    selected = []
    for row in rows:
        if only_shortlist and not row.get("shortlisted"):
            continue
        if only_captured and not row.get("capture_available"):
            continue
        if min_trades not in (None, ""):
            if int(row.get("trade_count") or 0) < int(min_trades):
                continue
        selected.append(row)
    return selected


def replay_captured_wallet(store, address=ALLOWED_WALLET, *, filters=None):
    if address not in CAPTURED_ADDRESSES:
        raise ValueError("No cached history capture for this wallet")
    digest = hashlib.sha256(CAPTURE_PATH.read_bytes()).hexdigest()
    if digest != EXPECTED_CAPTURE_SHA:
        raise ValueError("Cached capture hash drifted")
    records = gta_records_from_capture(_load_json(CAPTURE_PATH))
    result = replay_cached_history_to_report(
        store,
        address=address,
        records=records,
        window_start=WINDOWS["report_start_inclusive"],
        window_end=WINDOWS["report_end_exclusive"],
        acquisition_start=WINDOWS["acquisition_support_start_inclusive"],
        corpus_kind="GENUINE_REPLAY",
        authorization_id="live-ranked100-anchored-validation-2026-10-06-mitch",
        source_id="ranked100-product-completion-offline-replay",
    )
    report = result["report"]
    filters = filters or load_filters(store)
    profile = build_research_profile(
        report,
        filters=filters,
        classification=report.get("classification"),
    )
    universe = load_ranked_universe()
    ranked_row = next((row for row in universe["rows"] if row["address"] == address), {})
    funnel = classify_candidate(
        provider_rank=ranked_row.get("provider_rank") or 1,
        provider_trade_count=ranked_row.get("trade_count"),
        provider_score=ranked_row.get("provider_score"),
        capture_available=True,
        profile=profile,
        classification=report.get("classification"),
        worksheet=report.get("worksheet") or report.get("independent_worksheet"),
    )
    next_candidates = rank_next_candidates(universe["rows"], exclude_addresses=[address], limit=5)
    report["research_profile"] = profile
    report["funnel"] = funnel
    report["next_candidates"] = [
        {
            "address": row["address"],
            "provider_rank": row["provider_rank"],
            "trade_count": row["trade_count"],
            "shortlisted": row["shortlisted"],
            "capture_available": False,
        }
        for row in next_candidates
    ]
    report["shortlist_rank"] = ranked_row.get("provider_rank") or 1
    store.put("reports", report["id"], report)
    result["report"] = report
    result["research_profile"] = profile
    result["funnel"] = funnel
    result["next_candidates"] = report["next_candidates"]
    return result


def ranked_workflow_view(store, *, filters=None):
    filters = filters or load_filters(store)
    universe = load_ranked_universe()
    reports = []
    if hasattr(store, "list"):
        try:
            reports = [item for item in store.list("reports") if (item or {}).get("source") == "mass-search"]
        except Exception:
            reports = []
    reports_by_address = {}
    for report in reports:
        address = report.get("address")
        if address:
            reports_by_address.setdefault(address, report)
    rows = []
    for row in apply_local_filters(universe["rows"], filters):
        report = reports_by_address.get(row["address"])
        profile = (report or {}).get("research_profile")
        funnel = (report or {}).get("funnel") or classify_candidate(
            provider_rank=row["provider_rank"],
            provider_trade_count=row.get("trade_count"),
            provider_score=row.get("provider_score"),
            capture_available=row["capture_available"],
            profile=profile or {},
            classification=(report or {}).get("classification"),
            worksheet=(report or {}).get("worksheet"),
        )
        rows.append({
            **row,
            "report_id": (report or {}).get("id"),
            "funnel": funnel,
            "research_profile": profile,
            "can_open_report": bool((report or {}).get("id") or row["capture_available"]),
        })
    return {
        "kind": "ranked-workflow-view-v1",
        "filters": filters,
        "ranked_count": universe["ranked_count"],
        "visible_count": len(rows),
        "capture_sha256": universe["capture_sha256"],
        "rows": rows,
        "budget_enabled": False,
        "live_enabled": False,
        "live_approval_required": True,
        "PRODUCT_READY": False,
        "not_safe_to_copy": True,
        "note": "Cached browse only. Budget view stays disabled without a live approval.",
    }


def compare_reports(store, left_id, right_id):
    left = store.get("reports", left_id)
    right = store.get("reports", right_id)
    if not left or not right:
        raise ValueError("Both reports must already be saved")
    filters = load_filters(store)
    left_profile = left.get("research_profile") or build_research_profile(left, filters=filters)
    right_profile = right.get("research_profile") or build_research_profile(right, filters=filters)
    keys = (
        "scoped_pnl",
        "scoped_pnl_unit",
        "completed_known_cost_positions",
        "hold_t90_seconds",
        "final_hold_seconds",
        "concentration",
        "unresolved_basis_sales",
    )
    fields = []
    for key in keys:
        fields.append({
            "key": key,
            "left": left_profile.get(key),
            "right": right_profile.get(key),
        })
    return {
        "kind": "research-profile-compare-v1",
        "left_id": left_id,
        "right_id": right_id,
        "left_address": left.get("address"),
        "right_address": right.get("address"),
        "fields": fields,
        "left_funnel": left.get("funnel"),
        "right_funnel": right.get("funnel"),
        "not_safe_to_copy": True,
        "PRODUCT_READY": False,
    }


def acquisition_policy():
    return {
        "kind": "acquisition-policy-v1",
        "enabled_for_live": False,
        "applies_only_when_grant_approved": True,
        "max_wallets": 5,
        "max_pages_per_wallet": 2,
        "prefer": "highest_provider_trade_count_among_shortlist_without_capture",
        "exclude": ["already_captured", "consumed_grants"],
        "do_not_dispatch": True,
        "do_not_reuse_consumed_grants": True,
        "PRODUCT_READY": False,
    }
