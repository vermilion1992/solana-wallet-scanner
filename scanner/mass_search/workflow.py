"""Cached ranked-100 → filter → reconstruct any captured wallet. Zero live calls."""
from __future__ import annotations

import json
from pathlib import Path

from scanner.mass_search.acquisition_gate import gate_status
from scanner.mass_search.analytics import build_wallet_analytics
from scanner.mass_search.capture_catalog import (
    ANALYSIS_VERSION,
    EXPECTED_CAPTURE_SHA,
    WINDOWS,
    catalog_by_address,
    catalog_entries,
    evidence_cache_key,
    genuine_captured_addresses,
    load_capture_records,
    ranked_snapshot_identity,
)
from scanner.mass_search.funnel_abc import classify_candidate, rank_next_candidates
from scanner.mass_search.g3_reacquire import ALLOWED_WALLET
from scanner.mass_search.history_ingest import replay_cached_history_to_report, visible_report_allowed
from scanner.mass_search.visible_report import hydrate_visible_report, persist_visible_report, visible_report_passes
from scanner.mass_search.research_profile import (
    RESEARCH_SCREEN_DEFAULTS,
    apply_research_window,
    build_research_profile,
    evaluate_thresholds,
    independently_audited,
    load_committed_independent_audit,
    load_filters,
    qualification_category,
)
from scanner.mass_search.qualification_gates import reconcile_saved_profile
from scanner.mass_search.service import MassSearchService

ROOT = Path(__file__).resolve().parents[2]
RANKED_RAW_PATH = ROOT / "evidence/mass-wallet-funnel/ranked100-discovery-pilot-2026-10-05/RAW.json"
SHORTLIST_PATH = ROOT / "evidence/mass-wallet-funnel/ranked100-discovery-pilot-2026-10-05/SHORTLIST.json"
CAPTURE_PATH = ROOT / "evidence/mass-wallet-funnel/ranked100-anchored-validation-live/SOURCE_RESPONSE_page0.json"
CAPTURED_ADDRESSES = genuine_captured_addresses()
USER_SHORTLIST_KIND = "user_shortlist"
PHONE_ACCESS_BLOCKER = (
    "No permitted remote preview environment is configured in repo CI, docs, or deploy config. "
    "Away from the operator's own LAN this app cannot be opened on a phone. "
    "On the operator's computer, ./run.sh --lan binds the built frontend to that machine's "
    "LAN IP with a mandatory session token (unauthenticated API stays 401). "
    "Creating a new public, tunneled, or unauthenticated deployment is forbidden."
)


def _load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_ranked_universe():
    raw = _load_json(RANKED_RAW_PATH)
    items = (((raw.get("raw_page") or {}).get("data") or {}).get("items")) or []
    shortlist = _load_json(SHORTLIST_PATH)
    short_by_address = {row["address"]: row for row in shortlist.get("shortlist") or []}
    genuine = genuine_captured_addresses()
    rows = []
    seen = set()
    for index, item in enumerate(items):
        address = item.get("address")
        if not address or address in seen:
            continue
        seen.add(address)
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
            "capture_available": address in genuine,
            "label": short.get("label") or "Provider-ranked candidate — profitability and copyability not independently verified.",
            "evidence_status": "cached_capture" if address in genuine else "unverified",
            "row_kind": "ranked100",
        })
    snapshot = ranked_snapshot_identity()
    return {
        "kind": "ranked-100-cached-universe-v1",
        "ranked_count": len(rows),
        "shortlist_count": len(short_by_address),
        "capture_count": sum(1 for row in rows if row["capture_available"]),
        "rows": rows,
        "capture_sha256": EXPECTED_CAPTURE_SHA,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_raw_sha256": snapshot["raw_sha256"],
        "snapshot_shortlist_sha256": snapshot["shortlist_sha256"],
        "analysis_version": ANALYSIS_VERSION,
        "PRODUCT_READY": False,
        "live_enabled": False,
    }


def user_shortlist_addresses(store):
    if store is None or not hasattr(store, "list"):
        return set()
    try:
        rows = store.list(USER_SHORTLIST_KIND) or []
    except Exception:
        return set()
    return {row["address"] for row in rows if isinstance(row, dict) and row.get("address") and row.get("selected") is not False}


def set_user_shortlist(store, address, selected=True):
    if not address:
        raise ValueError("Address is required")
    if selected:
        store.put(USER_SHORTLIST_KIND, address, {"address": address, "selected": True, "source": "ui"})
    else:
        store.put(USER_SHORTLIST_KIND, address, {"address": address, "selected": False, "source": "ui"})
    return {"address": address, "selected": bool(selected), "shortlist": sorted(user_shortlist_addresses(store))}


def _safe_int(value):
    from decimal import Decimal, InvalidOperation

    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return None
    if not parsed.is_finite() or parsed != parsed.to_integral_value():
        return None
    return int(parsed)


def _safe_float(value):
    from decimal import Decimal, InvalidOperation

    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return None
    if not parsed.is_finite():
        return None
    return float(parsed)


def apply_local_filters(rows, filters, *, user_shortlist=None):
    """Cheap provider-proxy screen. Unset thresholds do not hide rows."""
    proxy = (filters or {}).get("provider_proxy") or {}
    thresholds = (filters or {}).get("thresholds") or {}
    min_trades = _safe_int(proxy.get("min_provider_trade_count", thresholds.get("min_provider_trade_count")))
    min_score = _safe_float(proxy.get("min_provider_score"))
    only_shortlist = bool(proxy.get("only_shortlist") or (filters or {}).get("only_shortlist"))
    only_captured = bool(proxy.get("only_captured") or (filters or {}).get("only_captured"))
    only_user = bool(proxy.get("only_user_shortlist"))
    selected = []
    for row in rows:
        if only_shortlist and not row.get("shortlisted"):
            continue
        if only_captured and not row.get("capture_available"):
            continue
        if only_user and row.get("address") not in (user_shortlist or set()):
            continue
        if min_trades is not None:
            trades = _safe_int(row.get("trade_count") or 0)
            if trades is None or trades < min_trades:
                continue
        if min_score is not None:
            score = _safe_float(row.get("provider_score"))
            if score is None or score < min_score:
                continue
        selected.append(row)
    return selected


def _filter_effects(universe_rows, visible_rows, filters):
    proxy = (filters or {}).get("provider_proxy") or {}
    effects = []
    for key, label, unit in (
        ("min_provider_trade_count", "Minimum provider trade count", "provider_trades"),
        ("min_provider_score", "Minimum provider score", "provider_score"),
        ("only_shortlist", "Provider shortlist only", "flag"),
        ("only_user_shortlist", "Your shortlist only", "flag"),
        ("only_captured", "Cached history only", "flag"),
    ):
        value = proxy.get(key)
        missing = value in (None, "", False)
        effects.append({
            "key": key,
            "group": "provider_proxy",
            "label": label,
            "unit": unit,
            "value": value,
            "missing": missing,
            "unknown_never_passes": True,
            "visible_count": len(visible_rows),
            "universe_count": len(universe_rows),
        })
    for key, label in (
        ("min_completed_known_cost", "Minimum completed known-cost positions"),
        ("min_sample_positions", "Minimum sample positions"),
        ("min_coverage_share", "Minimum coverage share (count AND value)"),
        ("min_scoped_pnl_usdc", "Minimum scoped USDC P&L"),
        ("min_scoped_pnl_sol", "Minimum scoped SOL P&L"),
        ("max_hold_t90_seconds", "Maximum hold t90"),
        ("max_concentration", "Maximum concentration"),
        ("max_unresolved_share", "Maximum unresolved share"),
        ("min_market_vs_rewards_ratio", "Minimum market/rewards ratio"),
        ("max_holder_fee_share", "Maximum holder-fee share"),
    ):
        value = ((filters or {}).get("thresholds") or {}).get(key)
        effects.append({
            "key": key,
            "group": "reconstructed_evidence",
            "label": label,
            "unit": ((filters or {}).get("units") or {}).get(key),
            "value": value,
            "missing": value in (None, ""),
            "unknown_never_passes": True,
            "applies_only_to_analysed_wallets": True,
        })
    window_days = (filters or {}).get("window_days")
    effects.append({
        "key": "window_days",
        "group": "capture_window",
        "label": "Report window days",
        "unit": "days",
        "value": window_days,
        "missing": window_days in (None, ""),
        "unknown_never_passes": True,
        "is_not": "proof_gate",
    })
    return effects


def _reconstructed_pass(profile, filters):
    """Re-evaluate current filters against reconciled authoritative values.

    Unset thresholds are not applied. Stale saved threshold_results are ignored.
    """
    thresholds = (filters or {}).get("thresholds") or {}
    if not any(value not in (None, "") for value in thresholds.values()):
        return None
    judged = evaluate_thresholds(profile or {}, thresholds)
    if not judged.get("evaluated"):
        return None
    return all(judged["results"][key].get("passed") for key in judged["evaluated"])


def saved_reports(store):
    if store is None or not hasattr(store, "list"):
        return []
    try:
        return [item for item in store.list("reports") if (item or {}).get("source") == "mass-search"]
    except Exception:
        return []


def reports_by_address(store):
    mapped = {}
    for report in saved_reports(store):
        address = report.get("address")
        if address:
            mapped.setdefault(address, report)
    return mapped


def _attach_research(store, result, *, address, filters=None, ranked_row=None, entry=None):
    report = result["report"]
    filters = filters or load_filters(store)
    from scanner.mass_search.qualification_gates import (
        bindable_independent_audit,
        compute_audit_fingerprint,
    )
    from scanner.mass_search.research_profile import _episode_ledger_from_report
    ledger = _episode_ledger_from_report(report)
    fingerprint = compute_audit_fingerprint(
        report,
        entry=entry,
        episodes=ledger,
    )
    report["audit_fingerprint"] = fingerprint
    audit = load_committed_independent_audit(address, fingerprint, ledger)
    if audit and bindable_independent_audit(audit, fingerprint, ledger):
        report["independent_audit"] = audit
    elif report.get("independent_audit"):
        attached = report["independent_audit"]
        if attached.get("content_fingerprint") or attached.get("fingerprint"):
            if not bindable_independent_audit(attached, fingerprint, ledger):
                report["independent_audit"] = None
    profile = build_research_profile(
        report,
        filters=filters,
        classification=report.get("classification"),
    )
    universe = load_ranked_universe()
    ranked_row = ranked_row or next((row for row in universe["rows"] if row["address"] == address), {})
    funnel = classify_candidate(
        provider_rank=ranked_row.get("provider_rank"),
        provider_trade_count=ranked_row.get("trade_count"),
        provider_score=ranked_row.get("provider_score"),
        capture_available=True,
        profile=profile,
        classification=report.get("classification"),
        worksheet=report.get("worksheet") or report.get("independent_worksheet"),
    )
    next_candidates = rank_next_candidates(universe["rows"], exclude_addresses=[address], limit=5)
    analytics = build_wallet_analytics({**report, "research_profile": profile})
    cache_key = evidence_cache_key(entry or {"address": address, "sha256": "", "windows": {}})
    report["research_profile"] = profile
    report["funnel"] = funnel
    report["analytics"] = analytics
    report["analysis_cache_key"] = cache_key
    report["next_candidates"] = [
        {
            "address": row["address"],
            "provider_rank": row["provider_rank"],
            "trade_count": row["trade_count"],
            "shortlisted": row["shortlisted"],
            "capture_available": bool(row.get("capture_available")),
        }
        for row in next_candidates
    ]
    report["shortlist_rank"] = ranked_row.get("provider_rank")
    report["not_safe_to_copy"] = True
    report["PRODUCT_READY"] = False
    for key in ("not_match", "not_ranked_wallet_pipeline_proof"):
        if key in result:
            report[key] = result[key]
    if result.get("cache_hit"):
        cached_report = result.get("report") or report
        if isinstance(cached_report, dict) and "visible_report" in cached_report:
            persist_visible_report(report, hydrate_visible_report(cached_report, cache_hit=True))
        # Absent stays unknown. Do not materialize False onto an old report.
    elif report.get("visible_report") is True:
        persist_visible_report(report, True)
    elif report.get("visible_report") is False:
        persist_visible_report(report, False)
    else:
        worksheet = report.get("worksheet") or report.get("independent_worksheet")
        if report.get("wallet_completed_episodes") is not None:
            completed = int(report["wallet_completed_episodes"])
        else:
            completed = int((profile or {}).get("completed_known_cost_positions") or 0)
        persist_visible_report(report, visible_report_allowed(worksheet=worksheet, completed_positions=completed))
    result["visible_report"] = visible_report_passes(report)
    report["result_scope"] = "conditional_on_captured_inventory"
    store.put("reports", report["id"], report)
    result["report"] = report
    result["research_profile"] = profile
    result["funnel"] = funnel
    result["analytics"] = analytics
    result["next_candidates"] = report["next_candidates"]
    result["external_requests"] = 0
    return result


def _replay_synthetic(store, entry, *, filters=None):
    if entry.get("raise_on_replay"):
        raise ValueError(entry.get("error") or "synthetic engineering failure")
    windows = entry.get("windows") or WINDOWS
    service = MassSearchService(store, clock=lambda: windows["report_end_exclusive"])
    plan = service.preview_plan()["plan"]
    plan["live_enabled"] = False
    run = service.create_run(plan, source_id="synthetic-engineering-fixture", corpus_kind="SYNTHETIC")
    reconstructed = service.reconstruct_candidate(
        run["run_id"],
        f"solana:{entry['address']}",
        entry.get("events") or [],
        corpus_kind="SYNTHETIC",
        mint=((entry.get("events") or [{}])[0] or {}).get("mint") or "SynthMint",
        window_start=windows["report_start_inclusive"],
        window_end=windows["report_end_exclusive"],
    )
    report = reconstructed["report"]
    report["source"] = "mass-search"
    report["address"] = entry["address"]
    report["corpus_kind"] = "SYNTHETIC"
    report["offline_replay"] = True
    report["not_proof"] = True
    report["label"] = entry.get("label")
    report["window"] = {
        "start": windows["report_start_inclusive"],
        "end": windows["report_end_exclusive"],
    }
    payload = {
        "run_id": run["run_id"],
        "report_id": report["id"],
        "report": report,
        "external_requests": 0,
    }
    if not (entry.get("events") or []):
        report["visible_report"] = False
        report["not_match"] = True
        payload["visible_report"] = False
        payload["not_match"] = True
    elif "visible_report" in report:
        payload["visible_report"] = report["visible_report"] is True
    if "not_match" in report:
        payload["not_match"] = report["not_match"]
    store.put("reports", report["id"], report)
    return _attach_research(
        store,
        payload,
        address=entry["address"],
        filters=filters,
        entry=entry,
    )


def _cached_report(store, address, entry):
    report = reports_by_address(store).get(address)
    if not report:
        return None
    expected = evidence_cache_key(entry)
    if report.get("analysis_cache_key") and report.get("analysis_cache_key") != expected:
        return None
    if entry.get("sha256") and report.get("capture_sha256") and report.get("capture_sha256") != entry["sha256"]:
        return None
    return report


def replay_captured_wallet(store, address=ALLOWED_WALLET, *, filters=None, force=False):
    catalog = catalog_by_address()
    entry = catalog.get(address)
    if entry is None:
        raise ValueError("History required — not analysed")
    filters = filters or load_filters(store)
    if not force:
        cached = _cached_report(store, address, entry)
        if cached:
            result = {
                "run_id": cached.get("run_id"),
                "report_id": cached["id"],
                "report": cached,
                "external_requests": 0,
                "cache_hit": True,
                "visible_report": hydrate_visible_report(cached, cache_hit=True),
                "not_match": cached.get("not_match"),
                "PRODUCT_READY": False,
            }
            result = _attach_research(store, result, address=address, filters=filters, entry=entry)
            result["cache_hit"] = True
            return result
    if entry.get("mode") == "synthetic_events":
        result = _replay_synthetic(store, entry, filters=filters)
    else:
        records, digest = load_capture_records(entry)
        windows = entry.get("windows") or WINDOWS
        result = replay_cached_history_to_report(
            store,
            address=address,
            records=records,
            window_start=windows["report_start_inclusive"],
            window_end=windows["report_end_exclusive"],
            acquisition_start=windows.get("acquisition_support_start_inclusive"),
            mint=entry.get("mint"),
            corpus_kind=entry.get("corpus_kind") or "GENUINE_REPLAY",
            authorization_id=entry.get("authorization_id") or "offline-cached-replay",
            source_id=entry.get("source_id") or "ranked100-product-offline-replay",
        )
        result["report"]["capture_sha256"] = digest
        result = _attach_research(store, result, address=address, filters=filters, entry=entry)
    result["cache_hit"] = False
    return result


def phone_access_status():
    return {
        "preview_available": False,
        "permitted_preview_environment": None,
        "frontend_reaches_backend": "same_origin_launcher_only",
        "blocker": PHONE_ACCESS_BLOCKER,
        "required_path": "local authenticated launcher; opt-in ./run.sh --lan on the operator's own Wi-Fi",
        "away_from_home_blocker": "No permitted remote preview exists.",
        "do_not_create_external_deployment": True,
    }


def _funnel_counts(rows):
    counts = {
        "A_YES": 0,
        "A_NO": 0,
        "B_ESTABLISHED": 0,
        "B_PARTIAL": 0,
        "B_INSUFFICIENT": 0,
        "B_UNVERIFIED": 0,
        "C_MET": 0,
        "C_NOT_MET": 0,
        "C_NOT_EVALUATED": 0,
        "awaiting_evidence": 0,
        "retained": 0,
        "rejected_provider_proxy": 0,
        "rejected_reconstructed": 0,
        "analysed": 0,
        "history_required": 0,
    }
    for row in rows:
        funnel = row.get("funnel") or {}
        a_state = (funnel.get("A") or {}).get("state")
        b_state = (funnel.get("B") or {}).get("state")
        c_state = (funnel.get("C") or {}).get("state")
        if a_state == "YES":
            counts["A_YES"] += 1
        else:
            counts["A_NO"] += 1
        key = f"B_{b_state}" if b_state else None
        if key in counts:
            counts[key] += 1
        c_key = f"C_{c_state}" if c_state else None
        if c_key in counts:
            counts[c_key] += 1
        if row.get("report_id"):
            counts["analysed"] += 1
            counts["retained"] += 1
        elif row.get("capture_available"):
            counts["awaiting_evidence"] += 1
        else:
            counts["awaiting_evidence"] += 1
            counts["history_required"] += 1
        if row.get("screen_rejected"):
            counts["rejected_provider_proxy"] += 1
        if row.get("reconstructed_rejected"):
            counts["rejected_reconstructed"] += 1
    return counts


def _authoritative_saved_profile(report):
    """Reuse a saved profile only after ledger-authoritative overlay. No rebuild."""
    if not report:
        return None
    profile = report.get("research_profile")
    if not profile:
        return None
    try:
        return reconcile_saved_profile(report, profile)
    except Exception:
        return {
            "completed_episode_ledger": [],
            "completed_known_cost_positions": 0,
            "independent_audit": None,
            "qualification_category": {"category": "analysed_incomplete"},
            "qualification_level": {"level": "insufficient_evidence"},
            "funnel": {"A": {"state": "unknown"}, "B": {"state": "unknown"}, "C": {"state": "NOT_MET"}},
            "ledger_summary_contradiction": True,
            "failed_closed": True,
        }


def _profile_for_view(report, filters):
    """Apply window_days to reconstructed episodes/P&L/sample before screening."""
    if not report:
        return None
    window_days = (filters or {}).get("window_days")
    if window_days not in (None, ""):
        clipped = apply_research_window(report, window_days)
        return build_research_profile(clipped, filters=filters)
    return _authoritative_saved_profile(report)


def visible_mass_search_report(report):
    """Copy whose funnel, category, and profile follow reconciled evidence."""
    if not report:
        return report
    visible = dict(report)
    profile = _authoritative_saved_profile(visible)
    if not profile:
        return visible
    visible["research_profile"] = profile
    visible["funnel"] = classify_candidate(
        capture_available=True,
        profile=profile,
        classification=visible.get("classification"),
        worksheet=visible.get("worksheet"),
    )
    visible["qualification_category"] = profile.get("qualification_category")
    visible["independent_audit"] = profile.get("independent_audit")
    visible["audit_fingerprint"] = profile.get("audit_fingerprint")
    visible["completed_episode_ledger"] = profile.get("completed_episode_ledger")
    return visible


def ranked_workflow_view(store, *, filters=None, extra_universe_rows=None):
    filters = filters or load_filters(store)
    universe = load_ranked_universe()
    if extra_universe_rows:
        universe = {
            **universe,
            "rows": list(universe["rows"]) + list(extra_universe_rows),
        }
    user_short = user_shortlist_addresses(store)
    reports = reports_by_address(store)
    catalog = catalog_by_address()
    screened = apply_local_filters(universe["rows"], filters, user_shortlist=user_short)
    screened_addresses = {row["address"] for row in screened}
    rows = []
    for row in screened:
        report = reports.get(row["address"])
        profile = _profile_for_view(report, filters)
        reconstructed_ok = _reconstructed_pass(profile, filters) if profile else None
        if reconstructed_ok is False:
            continue
        funnel = classify_candidate(
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
            "completed_episode_ledger": (profile or {}).get("completed_episode_ledger"),
            "independent_audit": (profile or {}).get("independent_audit"),
            "audit_fingerprint": (profile or {}).get("audit_fingerprint"),
            "research_profile": profile,
            "analytics": (report or {}).get("analytics"),
            "qualification_category": (profile or {}).get("qualification_category") or qualification_category(report, profile),
            "qualification_level": (profile or {}).get("qualification_level"),
            "coverage_status": (profile or {}).get("coverage_status"),
            "coverage_status_display": (profile or {}).get("coverage_status_display") or (profile or {}).get("coverage_status"),
            "blocking_reason": (profile or {}).get("blocking_reason"),
            "user_shortlisted": row["address"] in user_short,
            "history_required": not row["capture_available"] and not (report or {}).get("id"),
            "history_required_label": "History required — not analysed" if not row["capture_available"] and not (report or {}).get("id") else None,
            "can_open_report": bool((report or {}).get("id") or row["capture_available"]),
            "reconstructed_rejected": reconstructed_ok is False,
            "in_window_span": (report or {}).get("in_window_span") or (profile or {}).get("in_window_span"),
            "unsupported_swaps_in_window": (report or {}).get("unsupported_swaps_in_window"),
            "in_window_swaps": (report or {}).get("in_window_swaps"),
        })
    all_classified = []
    for row in universe["rows"]:
        report = reports.get(row["address"])
        profile = _profile_for_view(report, filters)
        funnel = classify_candidate(
            provider_rank=row["provider_rank"],
            provider_trade_count=row.get("trade_count"),
            provider_score=row.get("provider_score"),
            capture_available=row["capture_available"],
            profile=profile or {},
            classification=(report or {}).get("classification"),
            worksheet=(report or {}).get("worksheet"),
        )
        all_classified.append({
            **row,
            "funnel": funnel,
            "report_id": (report or {}).get("id"),
            "screen_rejected": row["address"] not in screened_addresses,
            "reconstructed_rejected": _reconstructed_pass(profile, filters) is False if profile else False,
        })
    extras = []
    for entry in catalog_entries():
        if entry["address"] in {row["address"] for row in universe["rows"]}:
            continue
        report = reports.get(entry["address"])
        extra_profile = _profile_for_view(report, filters)
        extras.append({
            "address": entry["address"],
            "provider_rank": None,
            "trade_count": None,
            "shortlisted": False,
            "capture_available": True,
            "label": entry.get("label"),
            "evidence_status": entry.get("evidence_status"),
            "row_kind": "synthetic_fixture" if entry.get("corpus_kind") == "SYNTHETIC" else "control_archive",
            "not_proof": bool(entry.get("not_proof") or entry.get("corpus_kind") == "SYNTHETIC"),
            "corpus_kind": entry.get("corpus_kind"),
            "report_id": (report or {}).get("id"),
            "funnel": classify_candidate(
                capture_available=True,
                profile=extra_profile or {},
                classification=(report or {}).get("classification"),
                worksheet=(report or {}).get("worksheet"),
            ),
            "research_profile": extra_profile,
            "analytics": (report or {}).get("analytics"),
            "user_shortlisted": entry["address"] in user_short,
            "history_required": False,
            "can_open_report": True,
        })
    return {
        "kind": "ranked-workflow-view-v1",
        "filters": filters,
        "filter_effects": _filter_effects(universe["rows"], rows, filters),
        "ranked_count": universe["ranked_count"],
        "visible_count": len(rows),
        "capture_sha256": universe["capture_sha256"],
        "snapshot_id": universe.get("snapshot_id"),
        "snapshot_raw_sha256": universe.get("snapshot_raw_sha256"),
        "snapshot_shortlist_sha256": universe.get("snapshot_shortlist_sha256"),
        "analysis_version": universe.get("analysis_version"),
        "rows": rows,
        "engineering_fixtures": [row for row in extras if row["row_kind"] == "synthetic_fixture"],
        "control_archives": [row for row in extras if row["row_kind"] == "control_archive"],
        "funnel_counts": _funnel_counts(all_classified),
        "user_shortlist": sorted(user_short),
        "budget_enabled": False,
        "live_enabled": False,
        "live_approval_required": True,
        "acquisition_gate": gate_status(store),
        "phone_access": phone_access_status(),
        "research_screen": research_screen_run(universe["rows"], reports, filters),
        "PRODUCT_READY": False,
        "not_safe_to_copy": True,
        "note": "Cached browse only. Budget view stays disabled without a live approval. Rank-1 and worth-investigating are not verified profitable.",
    }


def coverage_eligibility(report, profile=None):
    """Item 12: shared count-AND-value gate. 99% eligible, 95-99% watchlist, else blocked."""
    from decimal import Decimal

    from scanner.mass_search.qualification_gates import (
        CROSS_CURRENCY_SENSITIVITY,
        SENSITIVITY_NOT_ESTABLISHED,
        mandatory_coverage_gate,
    )
    from scanner.mass_search.research_profile import sensitivity_sign_flips

    gate = mandatory_coverage_gate(report, profile)
    unresolved = (profile or {}).get("unresolved_basis_sales")
    if unresolved in (None, ""):
        unresolved = ((report or {}).get("worksheet") or {}).get("unresolved_basis_sales")
    cost_dependency = sensitivity_sign_flips(report, profile or {})
    coverage_cost = cost_dependency not in (None, False, SENSITIVITY_NOT_ESTABLISHED)
    dependency = int(unresolved or 0) > 0 or bool(coverage_cost)
    count_share = Decimal(str(gate["count_share"])) if gate.get("count_share") not in (None, "") else None
    value_share = Decimal(str(gate["value_share"])) if gate.get("value_share") not in (None, "") else None
    if count_share is None and value_share is None:
        status = "blocked_unknown_denominator"
    else:
        # Watchlist/block bands still use the worse of the two shares, including
        # unsupported suspected trading in the denominator. Lead eligibility
        # requires the mandatory conjunction (count AND value).
        parts = [share for share in (count_share, value_share) if share is not None]
        resolved = min(parts) if parts and value_share is not None and count_share is not None else (
            min(parts) if parts else None
        )
        if resolved is None:
            status = "blocked_unknown_denominator"
        elif gate["passed"] and not dependency:
            status = "provisional_eligible"
        elif gate["passed"] and dependency:
            status = "coverage_eligibility_pending_reassessment"
        elif resolved >= Decimal("0.95"):
            status = "watchlist_incomplete_evidence"
        else:
            status = "coverage_blocked"
        if value_share is None or count_share is None:
            if resolved is not None and resolved >= Decimal("0.99"):
                status = "blocked_unknown_denominator"
    if dependency and status in ("provisional_eligible", "watchlist_incomplete_evidence"):
        status = "coverage_eligibility_pending_reassessment"
    if cost_dependency == CROSS_CURRENCY_SENSITIVITY and status == "provisional_eligible":
        status = "coverage_eligibility_pending_reassessment"
        dependency = True
    return {
        "status": status,
        "dependency_unresolved_basis": int(unresolved or 0) > 0,
        "dependency_unresolved_costs": bool(coverage_cost),
        "coverage_gate": gate,
        "note": (
            "A missing purchase or unresolved adjacent cost that could change "
            "the decision blocks regardless of percentage. Count and value "
            "coverage are both required; the denominator includes unsupported "
            "suspected trading."
        ),
    }


def _decoder_coverage_block(report, profile):
    judged = coverage_eligibility(report, profile)
    if judged["status"] in ("provisional_eligible",):
        return None
    if judged["status"] == "coverage_eligibility_pending_reassessment":
        return "coverage eligibility pending reassessment"
    if judged["status"] == "watchlist_incomplete_evidence":
        return "inconclusive: decoder coverage watchlist (95-99%)"
    return f"inconclusive: decoder coverage ({judged['status']})"


def research_screen_run(universe_rows, reports, filters):
    """Evaluate the saved snapshot against thresholds fixed before the run.

    Outcomes stay distinct: completed (qualified), zero-qualified,
    inconclusive (insufficient history), not_executed.
    """
    from scanner.mass_search.research_profile import RESEARCH_SCREEN_DEFAULTS

    screen = {}
    incoming = (filters or {}).get("thresholds") or {}
    for key, default in RESEARCH_SCREEN_DEFAULTS.items():
        value = incoming.get(key)
        if value not in (None, ""):
            screen[key] = value
        elif default not in (None, ""):
            screen[key] = default
    from scanner.mass_search.labels import research_label_tables, wallet_status_fields

    inconclusive = 0
    qualified = 0
    zero_qualified = 0
    not_executed = 0
    rows = []
    for row in universe_rows:
        report = reports.get(row["address"])
        if not row.get("capture_available") and not report:
            inconclusive += 1
            labels = wallet_status_fields(report, None)
            rows.append({
                "address": row["address"],
                "outcome": "inconclusive",
                "reason": "insufficient history — History required — not analysed",
                "qualification_category": qualification_category(None, None),
                "qualification_level": {"level": "insufficient_evidence", "label": "insufficient evidence"},
                "coverage_status": labels["coverage_status"],
                "blocking_reason": labels["blocking_reason"],
            })
            continue
        profile = _profile_for_view(report, filters)
        if not profile:
            not_executed += 1
            labels = wallet_status_fields(report, None)
            rows.append({
                "address": row["address"],
                "outcome": "not_executed",
                "reason": "capture available; analysis not executed",
                "qualification_category": qualification_category(report, None),
                "qualification_level": {"level": "insufficient_evidence", "label": "insufficient evidence"},
                "coverage_status": labels["coverage_status"],
                "blocking_reason": labels["blocking_reason"],
            })
            continue
        labels = wallet_status_fields(report, profile)
        audited = independently_audited(report, profile)
        sensitivity_state = (profile or {}).get("sensitivity_evidence_state")
        certified = audited and sensitivity_state not in (None, "not_established")
        coverage_block = _decoder_coverage_block(report, profile)
        if coverage_block:
            inconclusive += 1
            rows.append({
                "address": row["address"],
                "outcome": "inconclusive",
                "reason": coverage_block,
                "qualification_category": (profile or {}).get("qualification_category") or qualification_category(report, profile),
                "qualification_level": (profile or {}).get("qualification_level"),
                "coverage_status": labels["coverage_status"],
                "coverage_status_display": labels.get("coverage_status_display") or labels["coverage_status"],
                "blocking_reason": labels["blocking_reason"],
                "independently_audited": audited,
                "certified_research_wallet": False,
                "screen_match_kind": None,
                "in_window_span": (report.get("in_window_span") or profile.get("in_window_span")),
            })
            continue
        judged = evaluate_thresholds(profile, screen)
        if judged["criteria_met"]:
            qualified += 1
            outcome = "completed"
            reason = (
                "sample/activity filter match; not a certified research wallet"
                if not certified
                else "meets the screen on matched trades in the captured window"
            )
        else:
            zero_qualified += 1
            outcome = "zero_qualified"
            reason = "documented screen thresholds not met"
        rows.append({
            "address": row["address"],
            "outcome": outcome,
            "reason": reason,
            "threshold_results": judged["results"],
            "qualification_category": (profile or {}).get("qualification_category") or qualification_category(report, profile),
            "qualification_level": (profile or {}).get("qualification_level"),
            "coverage_status": labels["coverage_status"],
            "coverage_status_display": labels.get("coverage_status_display") or labels["coverage_status"],
            "blocking_reason": labels["blocking_reason"],
            "independently_audited": audited,
            "certified_research_wallet": bool(certified and judged["criteria_met"]),
            "screen_match_kind": "sample_activity_filter_match" if judged["criteria_met"] else None,
            "in_window_span": (report.get("in_window_span") or profile.get("in_window_span")),
        })
    if qualified:
        run_outcome = "completed"
    elif inconclusive and not qualified:
        run_outcome = "inconclusive"
    elif zero_qualified:
        run_outcome = "zero_qualified"
    else:
        run_outcome = "not_executed"
    label_tables = research_label_tables(rows)
    return {
        "kind": "research-screen-run-v1",
        "thresholds_fixed_before_evaluation": screen,
        "unknown_never_passes": True,
        "outcome": run_outcome,
        "outcome_class": (
            "inconclusive_insufficient_history"
            if run_outcome == "inconclusive"
            else run_outcome
        ),
        "counts": {
            "inconclusive": inconclusive,
            "completed_qualified": qualified,
            "zero_qualified": zero_qualified,
            "not_executed": not_executed,
            "universe": len(universe_rows),
            "qualification": {
                "not_evaluated": sum(1 for item in rows if (item.get("qualification_category") or {}).get("category") == "not_evaluated"),
                "analysed_incomplete": sum(1 for item in rows if (item.get("qualification_category") or {}).get("category") == "analysed_incomplete"),
                "positive_matched_position_evidence": sum(1 for item in rows if (item.get("qualification_category") or {}).get("category") == "positive_matched_position_evidence"),
                "positive_net_realised_over_window": sum(1 for item in rows if (item.get("qualification_category") or {}).get("category") == "positive_net_realised_over_window"),
                "profitable_account_performance": sum(1 for item in rows if (item.get("qualification_category") or {}).get("category") == "profitable_account_performance"),
            },
            "qualification_level": label_tables["qualification_level_counts"],
            "coverage_status": label_tables["coverage_status_counts"],
        },
        "label_tables": label_tables,
        "completed_qualified_are_sample_activity_filter_matches": True,
        "completed_qualified_are_not_certified_research_wallets": True,
        "note": (
            "Today's run over the saved snapshot is inconclusive for wallets "
            "without a genuine capture. A single matched trade never qualifies the account. "
            "coverage_status and qualification_level are different fields. "
            "completed_qualified counts sample/activity filter matches. It is not "
            "independent-audit or sensitivity certification."
        ),
        "rows": rows,
        "PRODUCT_READY": False,
    }


def _format_unknown_basis(value):
    if not isinstance(value, dict):
        return value
    sales = value.get("sales")
    quantity = value.get("quantity")
    proceeds = value.get("proceeds")
    unit = value.get("unit") or ""
    from scanner.mass_search.research_profile import _display_decimal

    return (
        f"sales {sales} · qty {_display_decimal(quantity)} · proceeds {_display_decimal(proceeds)} {unit}"
    ).strip()


def compare_reports(store, left_id, right_id):
    left = store.get("reports", left_id)
    right = store.get("reports", right_id)
    if not left or not right:
        raise ValueError("Both reports must already be saved")
    filters = load_filters(store)
    left_profile = _authoritative_saved_profile(left) or build_research_profile(left, filters=filters)
    right_profile = _authoritative_saved_profile(right) or build_research_profile(right, filters=filters)
    left_analytics = left.get("analytics") or build_wallet_analytics({**left, "research_profile": left_profile})
    right_analytics = right.get("analytics") or build_wallet_analytics({**right, "research_profile": right_profile})
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
    fields.extend([
        {"key": "win_rate", "left": (left_analytics.get("win_rate") or {}).get("rate"), "right": (right_analytics.get("win_rate") or {}).get("rate")},
        {"key": "win_rate_denominator", "left": (left_analytics.get("win_rate") or {}).get("denominator"), "right": (right_analytics.get("win_rate") or {}).get("denominator")},
        {"key": "median_hold_n", "left": (left_analytics.get("median_hold") or {}).get("sample_count"), "right": (right_analytics.get("median_hold") or {}).get("sample_count")},
        {"key": "settlement_asset", "left": left_analytics.get("scoped_pnl_unit"), "right": right_analytics.get("scoped_pnl_unit")},
        {"key": "corpus_kind", "left": left.get("corpus_kind"), "right": right.get("corpus_kind")},
        {"key": "scope", "left": (left_analytics.get("scope") or {}).get("population"), "right": (right_analytics.get("scope") or {}).get("population")},
        {"key": "window_start", "left": (left.get("window") or {}).get("start"), "right": (right.get("window") or {}).get("start")},
        {"key": "window_end", "left": (left.get("window") or {}).get("end"), "right": (right.get("window") or {}).get("end")},
        {"key": "visible_report", "left": left.get("visible_report") is True, "right": right.get("visible_report") is True},
        {"key": "result_scope", "left": left.get("result_scope"), "right": right.get("result_scope")},
        {
            "key": "unknown_basis_quantity_and_proceeds",
            "left": _format_unknown_basis((left_profile.get("candidate_assessment") or {}).get("unknown_basis_quantity_and_proceeds")),
            "right": _format_unknown_basis((right_profile.get("candidate_assessment") or {}).get("unknown_basis_quantity_and_proceeds")),
        },
    ])
    mismatches = []
    left_unit = left_analytics.get("scoped_pnl_unit") or left_profile.get("scoped_pnl_unit")
    right_unit = right_analytics.get("scoped_pnl_unit") or right_profile.get("scoped_pnl_unit")
    if left_unit and right_unit and left_unit != right_unit:
        mismatches.append({"kind": "currency", "detail": f"{left_unit} versus {right_unit}; no FX conversion"})
    if (left.get("window") or {}) != (right.get("window") or {}):
        mismatches.append({"kind": "window", "detail": "Report windows differ; totals are not the same interval"})
    if left.get("corpus_kind") != right.get("corpus_kind"):
        mismatches.append({"kind": "corpus", "detail": "Genuine and synthetic or control corpora are not equivalent"})
    if left.get("visible_report") is not True or right.get("visible_report") is not True:
        mismatches.append({"kind": "incomplete_evidence", "detail": "At least one report is not a visible completed-position result"})
    if (left_profile.get("unresolved_basis_sales") or 0) or (right_profile.get("unresolved_basis_sales") or 0):
        mismatches.append({"kind": "incomplete_evidence", "detail": "Unresolved-basis sales stay unknown; they are not zero-cost closes"})
    left_window = left.get("window") or {}
    right_window = right.get("window") or {}
    left_events = [row for row in (left.get("events") or []) if row.get("kind") in ("buy", "sell")]
    right_events = [row for row in (right.get("events") or []) if row.get("kind") in ("buy", "sell")]
    return {
        "kind": "research-profile-compare-v1",
        "left_id": left_id,
        "right_id": right_id,
        "left_address": left.get("address"),
        "right_address": right.get("address"),
        "fields": fields,
        "mismatches": mismatches,
        "comparable": not any(item["kind"] in ("currency", "window") for item in mismatches),
        "window_policy": {
            "kind": "own_windows_shown_mismatch_blocks",
            "detail": (
                "Each report keeps its own window. Windows match; compare is shown."
                if (left.get("window") or {}) == (right.get("window") or {})
                else (
                    "Each report keeps its own window. Differing windows are not "
                    "recomputed onto a common interval. Compare is blocked."
                )
            ),
            "left_window": left_window,
            "right_window": right_window,
            "left_included_trades": len(left_events),
            "right_included_trades": len(right_events),
            "left_included_tx": [row.get("signature") for row in left_events],
            "right_included_tx": [row.get("signature") for row in right_events],
            "left_sample_size": left_profile.get("completed_known_cost_positions"),
            "right_sample_size": right_profile.get("completed_known_cost_positions"),
            "left_scoped_pnl": left_profile.get("scoped_pnl") or left_analytics.get("scoped_pnl"),
            "right_scoped_pnl": right_profile.get("scoped_pnl") or right_analytics.get("scoped_pnl"),
            "left_scoped_pnl_unit": left_profile.get("scoped_pnl_unit") or left_analytics.get("scoped_pnl_unit"),
            "right_scoped_pnl_unit": right_profile.get("scoped_pnl_unit") or right_analytics.get("scoped_pnl_unit"),
            "left_completed_episode_net": left_profile.get("completed_episode_net"),
            "right_completed_episode_net": right_profile.get("completed_episode_net"),
            "left_completed_episode_net_unit": left_profile.get("completed_episode_net_unit"),
            "right_completed_episode_net_unit": right_profile.get("completed_episode_net_unit"),
            "left_independently_audited": independently_audited(left, left_profile),
            "right_independently_audited": independently_audited(right, right_profile),
            "left_independently_audited_episode_net": (
                (left_profile.get("independent_audit") or {}).get("independently_audited_episode_net")
                if independently_audited(left, left_profile) else None
            ),
            "right_independently_audited_episode_net": (
                (right_profile.get("independent_audit") or {}).get("independently_audited_episode_net")
                if independently_audited(right, right_profile) else None
            ),
            "left_independently_audited_episode_net_unit": (
                (left_profile.get("independent_audit") or {}).get("independently_audited_episode_net_unit")
                if independently_audited(left, left_profile) else None
            ),
            "right_independently_audited_episode_net_unit": (
                (right_profile.get("independent_audit") or {}).get("independently_audited_episode_net_unit")
                if independently_audited(right, right_profile) else None
            ),
            "result_scope": "conditional_on_captured_inventory",
        },
        "left_funnel": classify_candidate(
            capture_available=True,
            profile=left_profile,
            classification=left.get("classification"),
            worksheet=left.get("worksheet"),
        ),
        "right_funnel": classify_candidate(
            capture_available=True,
            profile=right_profile,
            classification=right.get("classification"),
            worksheet=right.get("worksheet"),
        ),
        "left_qualification_category": left_profile.get("qualification_category"),
        "right_qualification_category": right_profile.get("qualification_category"),
        "left_independent_audit": left_profile.get("independent_audit"),
        "right_independent_audit": right_profile.get("independent_audit"),
        "left_audit_fingerprint": left_profile.get("audit_fingerprint"),
        "right_audit_fingerprint": right_profile.get("audit_fingerprint"),
        "left_completed_episode_ledger": left_profile.get("completed_episode_ledger"),
        "right_completed_episode_ledger": right_profile.get("completed_episode_ledger"),
        "left_analytics": left_analytics,
        "right_analytics": right_analytics,
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


def approval_proposal():
    universe = load_ranked_universe()
    next_rows = rank_next_candidates(universe["rows"], exclude_addresses=list(CAPTURED_ADDRESSES), limit=5)
    return {
        "kind": "single-approval-proposal-v1",
        "status": "NOT_AUTHORISED",
        "do_not_dispatch": True,
        "do_not_enable": True,
        "authorization_id": "live-ranked100-next-candidates-2026-10-06-mitch",
        "file": "config/live_authorization.ranked100-next-candidates-draft.json",
        "selected_candidates": [
            {
                "address": row["address"],
                "provider_rank": row["provider_rank"],
                "trade_count": row["trade_count"],
                "reason": "highest_provider_trade_count_among_shortlist_without_capture",
            }
            for row in next_rows
        ],
        "history_boundaries": {
            "method": "getTransactionsForAddress",
            "limit": 100,
            "sortOrder": "desc",
            "pages_per_wallet": 2,
            "optional_rank1_earlier_page_for_unbacked_sale": False,
            "optional_rank1_page_skipped_reason": (
                "Stored draft max_dispatched_requests=10 covers 5 wallets × 2 pages only; "
                "it does not unambiguously allocate an 11th rank-1 page."
            ),
        },
        "max_requests": 10,
        "max_units": 100,
        "max_spend_usd": "0",
        "stop_conditions": [
            "stop_once_one_completed_position_reconciled",
            "do_not_broaden_stop_after_one_into_validating_multiple_wallets",
            "failed_or_timed_out_dispatched_request_consumes_attempt",
        ],
        "realistic_yield": (
            "At most five unverified ranked-100 wallets, two pages each. The optional rank-1 "
            "earlier page is skipped because the stored draft does not unambiguously cover it. "
            "Not leftover grants. Not MATCH."
        ),
        "PRODUCT_READY": False,
    }


def research_search_proposal():
    """Separate disabled research-search grant. Does not touch the next-candidates draft."""
    path = ROOT / "config/live_authorization.ranked100-research-search-draft.json"
    payload = _load_json(path) if path.exists() else {}
    universe = load_ranked_universe()
    next_rows = rank_next_candidates(universe["rows"], exclude_addresses=list(CAPTURED_ADDRESSES), limit=10)
    return {
        "kind": "research-search-proposal-v1",
        "status": "NOT_AUTHORISED",
        "enabled": False,
        "do_not_dispatch": True,
        "do_not_enable": True,
        "authorization_id": payload.get("authorization_id") or "live-ranked100-research-search-2026-10-06-mitch",
        "file": "config/live_authorization.ranked100-research-search-draft.json",
        "separate_from": "live-ranked100-next-candidates-2026-10-06-mitch",
        "selected_candidates": [
            {
                "address": row["address"],
                "provider_rank": row["provider_rank"],
                "trade_count": row["trade_count"],
                "reason": "highest_provider_trade_count_among_shortlist_without_capture",
            }
            for row in next_rows
        ],
        "window_objective": "two newest-first GTA pages per wallet (documented 100-tx pages)",
        "max_pages_per_wallet": 2,
        "max_wallets": 10,
        "max_requests": 20,
        "documented_credits": 200,
        "documented_units_per_request": 10,
        "credits_needed_versus_balance": "needed=200 documented Helius credits; balance unconfirmed",
        "max_spend_usd": "0",
        "retries": 0,
        "stop_conditions": [
            "stop_when_budget_exhausted",
            "stop_when_coverage_objective_reached",
            "never_until_a_winner",
        ],
        "can_establish": (
            "At most ten additional ranked-100 wallets with page-bounded captured "
            "history for research-screen classes 1–2. Not an account-performance claim."
        ),
        "remains_uncertain": "Earlier inventory, transfers, valuations, SOL/USDC net, and wallets beyond the ten.",
        "PRODUCT_READY": False,
    }
