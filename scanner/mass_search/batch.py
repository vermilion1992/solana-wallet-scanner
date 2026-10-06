"""Offline batch analysis of any selected wallet with cached history."""
from __future__ import annotations

import time
import uuid

from scanner.mass_search.capture_catalog import catalog_by_address
from scanner.mass_search.instrumentation import provider_call_count
from scanner.mass_search.workflow import replay_captured_wallet

BATCH_KIND = "ranked_batch"
HISTORY_REQUIRED = "History required — not analysed"
INCOMPLETE_EVIDENCE = "Analysed with incomplete evidence"
IN_FLIGHT = "A batch is already in progress"


def _now():
    return time.time()


def _inflight_batch(store):
    try:
        rows = store.list(BATCH_KIND) or []
    except Exception:
        return None
    for row in rows:
        if isinstance(row, dict) and row.get("status") in ("pending", "running"):
            return row
    return None


def create_batch(store, addresses, *, include_fixtures=False):
    existing = _inflight_batch(store)
    if existing:
        raise ValueError(IN_FLIGHT)
    catalog = catalog_by_address()
    requested = []
    seen = set()
    for address in addresses or []:
        if not address or address in seen:
            continue
        seen.add(address)
        requested.append(address)
    if include_fixtures:
        for address, entry in catalog.items():
            if entry.get("corpus_kind") == "SYNTHETIC" and address not in seen:
                seen.add(address)
                requested.append(address)
    batch_id = str(uuid.uuid4())
    outcomes = []
    for address in requested:
        entry = catalog.get(address)
        outcomes.append({
            "address": address,
            "status": "pending",
            "capture_available": bool(entry),
            "corpus_kind": (entry or {}).get("corpus_kind"),
            "not_proof": bool((entry or {}).get("not_proof") or (entry or {}).get("corpus_kind") == "SYNTHETIC"),
            "label": (entry or {}).get("label"),
            "report_id": None,
            "detail": None,
        })
    payload = {
        "kind": "ranked-batch-v1",
        "batch_id": batch_id,
        "status": "pending",
        "created_at": _now(),
        "cancel_requested": False,
        "index": 0,
        "total": len(outcomes),
        "completed": 0,
        "outcomes": outcomes,
        "external_requests": 0,
        "provider_calls": provider_call_count(),
        "PRODUCT_READY": False,
    }
    store.put(BATCH_KIND, batch_id, payload)
    return payload


def get_batch(store, batch_id):
    payload = store.get(BATCH_KIND, batch_id)
    if not payload:
        raise ValueError("Unknown batch")
    return payload


def cancel_batch(store, batch_id):
    payload = get_batch(store, batch_id)
    payload["cancel_requested"] = True
    if payload.get("status") in ("pending", "running"):
        payload["status"] = "cancelled"
    store.put(BATCH_KIND, batch_id, payload)
    return payload


def _analyse_one(store, outcome):
    address = outcome["address"]
    catalog = catalog_by_address()
    if address not in catalog:
        outcome["status"] = "history_required"
        outcome["detail"] = HISTORY_REQUIRED
        return outcome
    try:
        result = replay_captured_wallet(store, address)
        report = result.get("report") or {}
        if report.get("visible_report") is False or result.get("visible_report") is False:
            outcome["status"] = "incomplete_evidence"
            outcome["detail"] = INCOMPLETE_EVIDENCE
        else:
            outcome["status"] = "cached" if result.get("cache_hit") else "analysed"
            outcome["detail"] = None
        outcome["report_id"] = result.get("report_id")
        outcome["funnel"] = result.get("funnel")
        outcome["scoped_pnl"] = (result.get("analytics") or {}).get("scoped_pnl")
        outcome["scoped_pnl_unit"] = (result.get("analytics") or {}).get("scoped_pnl_unit")
        if report.get("corpus_kind") == "SYNTHETIC":
            outcome["not_proof"] = True
            outcome["detail"] = "SYNTHETIC — engineering fixture, not proof"
    except Exception as exc:
        outcome["status"] = "error"
        outcome["detail"] = str(exc)
        outcome["report_id"] = None
    return outcome


def step_batch(store, batch_id):
    payload = get_batch(store, batch_id)
    if payload.get("cancel_requested"):
        payload["status"] = "cancelled"
        store.put(BATCH_KIND, batch_id, payload)
        return payload
    index = int(payload.get("index") or 0)
    outcomes = payload.get("outcomes") or []
    if index >= len(outcomes):
        payload["status"] = "completed"
        store.put(BATCH_KIND, batch_id, payload)
        return payload
    payload["status"] = "running"
    outcome = _analyse_one(store, outcomes[index])
    outcomes[index] = outcome
    payload["outcomes"] = outcomes
    payload["index"] = index + 1
    payload["completed"] = index + 1
    payload["external_requests"] = 0
    payload["provider_calls"] = provider_call_count()
    if payload["index"] >= len(outcomes):
        payload["status"] = "completed"
    if payload.get("cancel_requested"):
        payload["status"] = "cancelled"
    store.put(BATCH_KIND, batch_id, payload)
    return payload


def run_batch(store, batch_id):
    payload = get_batch(store, batch_id)
    while payload.get("status") not in ("completed", "cancelled") and int(payload.get("index") or 0) < int(payload.get("total") or 0):
        if payload.get("cancel_requested"):
            payload["status"] = "cancelled"
            store.put(BATCH_KIND, batch_id, payload)
            break
        payload = step_batch(store, batch_id)
    return payload


def create_and_run(store, addresses, *, include_fixtures=False):
    payload = create_batch(store, addresses, include_fixtures=include_fixtures)
    return run_batch(store, payload["batch_id"])
