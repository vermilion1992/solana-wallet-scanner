"""Offline batch analysis of any selected wallet with cached history.

Process model: one scanner process per data directory. The launcher holds
`.runtime.lock` (see `scanner.__main__.data_directory_lock`). A second
process on the same data dir raises InstanceAlreadyRunning. In-process
admission is a single `store.lock` critical section at create_batch.
HTTP create/step/cancel are sync routes so overlapping callers run in
the threadpool and actually contend; they must not sit on the event loop.
Batch admission never consults the acquisition grant; the acquisition
gate never creates or steps a ranked batch.
"""
from __future__ import annotations

import time
import uuid

from scanner.mass_search.capture_catalog import catalog_by_address
from scanner.mass_search.instrumentation import provider_call_count
from scanner.mass_search.visible_report import visible_report_passes
from scanner.mass_search.workflow import replay_captured_wallet

BATCH_KIND = "ranked_batch"
HISTORY_REQUIRED = "History required — not analysed"
INCOMPLETE_EVIDENCE = "Analysed with incomplete evidence"
IN_FLIGHT = "A batch is already in progress"
PROCESS_MODEL = "single_process_per_data_dir"
_ADMISSION_BARRIER = None
_STEP_HOLD = None


class BatchBusy(ValueError):
    """Second concurrent admission. HTTP maps this to 409."""

    status_code = 409


def hold_admission_barrier_for_test(barrier):
    """Test hook: both HTTP callers wait here, then contend for store.lock."""
    global _ADMISSION_BARRIER
    _ADMISSION_BARRIER = barrier


def hold_step_for_test(event):
    """Test hook: step_batch waits here while still executing."""
    global _STEP_HOLD
    _STEP_HOLD = event


def _now():
    return time.time()


def _request_fingerprint(addresses, include_fixtures):
    return {"addresses": list(addresses), "include_fixtures": bool(include_fixtures)}


def _held_batch(store):
    """Admission is held while a batch is pending/running or still executing."""
    try:
        rows = store.list(BATCH_KIND) or []
    except Exception:
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("executing") is True:
            return row
        if row.get("status") in ("pending", "running"):
            return row
    return None


def _inflight_batch(store):
    return _held_batch(store)


def create_batch(store, addresses, *, include_fixtures=False):
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
    fingerprint = _request_fingerprint(requested, include_fixtures)
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
        "status": "pending",
        "created_at": _now(),
        "cancel_requested": False,
        "executing": False,
        "index": 0,
        "total": len(outcomes),
        "completed": 0,
        "outcomes": outcomes,
        "request_fingerprint": fingerprint,
        "process_model": PROCESS_MODEL,
        "admission": "store.lock critical section; launcher .runtime.lock is the process guard",
        "acquisition_independent": True,
        "external_requests": 0,
        "provider_calls": provider_call_count(),
        "PRODUCT_READY": False,
    }
    if _ADMISSION_BARRIER is not None:
        _ADMISSION_BARRIER.wait()
    with store.lock:
        existing = _held_batch(store)
        if existing:
            if existing.get("request_fingerprint") == fingerprint:
                attached = dict(existing)
                attached["attached"] = True
                return attached
            raise BatchBusy(IN_FLIGHT)
        batch_id = str(uuid.uuid4())
        payload["batch_id"] = batch_id
        payload["attached"] = False
        store.put(BATCH_KIND, batch_id, payload)
        return payload


def get_batch(store, batch_id):
    payload = store.get(BATCH_KIND, batch_id)
    if not payload:
        raise ValueError("Unknown batch")
    return payload


def cancel_batch(store, batch_id):
    """Request cancel. Admission stays held while executing is still True."""
    with store.lock:
        payload = get_batch(store, batch_id)
        payload["cancel_requested"] = True
        if payload.get("executing") is True:
            store.put(BATCH_KIND, batch_id, payload)
            return payload
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
        if not visible_report_passes(report) or result.get("visible_report") is not True:
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
    """Claim at most one index. A second stepper attaches and does not re-analyse."""
    with store.lock:
        payload = get_batch(store, batch_id)
        if payload.get("cancel_requested") and payload.get("executing") is not True:
            payload["status"] = "cancelled"
            payload["executing"] = False
            store.put(BATCH_KIND, batch_id, payload)
            return payload
        if payload.get("executing") is True:
            payload["attached"] = True
            payload["step_ignored"] = "already_executing"
            store.put(BATCH_KIND, batch_id, payload)
            return payload
        index = int(payload.get("index") or 0)
        outcomes = payload.get("outcomes") or []
        if index >= len(outcomes):
            payload["status"] = "completed"
            payload["executing"] = False
            store.put(BATCH_KIND, batch_id, payload)
            return payload
        payload["status"] = "running"
        payload["executing"] = True
        payload["attached"] = False
        payload.pop("step_ignored", None)
        store.put(BATCH_KIND, batch_id, payload)
    if _STEP_HOLD is not None:
        _STEP_HOLD.wait()
    try:
        outcome = _analyse_one(store, outcomes[index])
        outcomes[index] = outcome
        payload["outcomes"] = outcomes
        payload["index"] = index + 1
        payload["completed"] = index + 1
        payload["external_requests"] = 0
        payload["provider_calls"] = provider_call_count()
        if payload["index"] >= len(outcomes):
            payload["status"] = "completed"
        return payload
    finally:
        with store.lock:
            latest = store.get(BATCH_KIND, batch_id) or {}
            if latest.get("cancel_requested") or payload.get("cancel_requested"):
                payload["cancel_requested"] = True
                payload["status"] = "cancelled"
            payload["executing"] = False
            store.put(BATCH_KIND, batch_id, payload)


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
    """Create or attach. An attached caller must not start a second runner."""
    payload = create_batch(store, addresses, include_fixtures=include_fixtures)
    if payload.get("attached"):
        return payload
    return run_batch(store, payload["batch_id"])
