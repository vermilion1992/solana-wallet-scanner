"""History-acquisition gate. Blocks before any provider contact. Never dispatches."""
from __future__ import annotations

from copy import deepcopy
from threading import Lock

from scanner.mass_search.capability import LIVE_AUTH_SCHEMA, utc_now, validate_live_authorization
from scanner.mass_search.instrumentation import provider_call_count

GATE_KIND = "acquisition_gate"
LOCK_KEY = "live-dispatch-lock"
LEDGER_KEY = "live-dispatch-ledger"
DRAFT_ID = "live-ranked100-next-candidates-2026-10-06-mitch"

_THREAD_LOCK = Lock()


def _block(code, detail, **extra):
    payload = {
        "allowed": False,
        "would_contact_provider": False,
        "blocked_before_provider": True,
        "code": code,
        "detail": detail,
        "do_not_dispatch": True,
        "provider_calls": provider_call_count(),
        "PRODUCT_READY": False,
    }
    payload.update(extra)
    return payload


def _grant_from_store(store):
    if store is None:
        return None
    return store.get("configuration", "live_authorization")


def evaluate_authorization(grant, *, now=None, requested_requests=1, requested_units=1, ledger=None):
    """Classify missing / disabled / expired / consumed / insufficient. No I/O."""
    clock = now or utc_now()
    if grant is None:
        return _block("missing", "No live authorization is present")
    if not isinstance(grant, dict):
        return _block("missing", "Live authorization payload is not an object")
    if grant.get("authorization_id") == DRAFT_ID and grant.get("enabled") is not True:
        return _block(
            "disabled",
            "Draft live-ranked100-next-candidates-2026-10-06-mitch stays DISABLED",
            authorization_id=DRAFT_ID,
        )
    if grant.get("enabled") is not True:
        return _block(
            "disabled",
            grant.get("draft_status") or grant.get("reason") or "Authorization is disabled",
            authorization_id=grant.get("authorization_id"),
        )
    if grant.get("schema_version") != LIVE_AUTH_SCHEMA:
        return _block("missing", "Live authorization schema is not live-research-authorization-v1")
    expires = grant.get("expires_at")
    if not expires:
        return _block("missing", "Enabled authorization requires expires_at")
    if expires <= clock:
        return _block("expired", "Authorization expired", authorization_id=grant.get("authorization_id"))
    if grant.get("do_not_dispatch") is True or (grant.get("acquisition_policy") or {}).get("do_not_dispatch") is True:
        return _block("disabled", "Authorization forbids dispatch", authorization_id=grant.get("authorization_id"))
    providers = grant.get("providers") or []
    helius = next((row for row in providers if row.get("provider_id") == "helius"), None)
    if helius is None:
        return _block("insufficient", "No Helius budget is present")
    max_requests = int(helius.get("max_requests") or grant.get("max_dispatched_requests") or 0)
    max_units = int(helius.get("max_units") or 0)
    used_requests = int((ledger or {}).get("used_requests") or grant.get("used_requests") or 0)
    used_units = int((ledger or {}).get("used_units") or grant.get("used_units") or 0)
    if used_requests >= max_requests or used_units >= max_units:
        return _block("consumed", "Authorization already consumed", authorization_id=grant.get("authorization_id"))
    remaining_requests = max_requests - used_requests
    remaining_units = max_units - used_units
    if requested_requests > remaining_requests or requested_units > remaining_units:
        return _block(
            "insufficient",
            "Remaining authorization is insufficient for the requested history",
            remaining_requests=remaining_requests,
            remaining_units=remaining_units,
        )
    # Product path never dispatches even if a test grant looks enabled.
    return _block(
        "do_not_dispatch",
        "Product path refuses dispatch; history acquisition stays offline",
        authorization_id=grant.get("authorization_id"),
        remaining_requests=remaining_requests,
        remaining_units=remaining_units,
    )


def _ledger(store):
    return store.get(GATE_KIND, LEDGER_KEY) or {
        "used_requests": 0,
        "used_units": 0,
        "in_flight": False,
        "reservations": [],
    }


def attempt_history_acquisition(
    store,
    grant=None,
    *,
    requested_requests=1,
    requested_units=1,
    actor="test",
    hold_reservation=False,
):
    """Reserve-or-block under a lock. Never contacts a provider."""
    with _THREAD_LOCK:
        if store is not None and hasattr(store, "lock"):
            store.lock.acquire()
        try:
            payload = grant if grant is not None else _grant_from_store(store)
            ledger = _ledger(store) if store is not None else {}
            if ledger.get("in_flight"):
                return _block("concurrent", "A history acquisition is already in flight; refusing double-spend")
            checked = evaluate_authorization(
                payload,
                requested_requests=requested_requests,
                requested_units=requested_units,
                ledger=ledger,
            )
            if checked["code"] in ("missing", "disabled", "expired", "consumed", "insufficient"):
                return checked
            if store is None:
                return checked
            reservation = {
                "actor": actor,
                "requested_requests": requested_requests,
                "requested_units": requested_units,
                "status": "held_without_dispatch",
            }
            updated = deepcopy(ledger)
            updated["in_flight"] = True
            updated["reservations"] = list(updated.get("reservations") or []) + [reservation]
            store.put(GATE_KIND, LEDGER_KEY, updated)
            store.put(GATE_KIND, LOCK_KEY, {"held": True, "actor": actor})
            if not hold_reservation:
                updated["in_flight"] = False
                store.put(GATE_KIND, LEDGER_KEY, updated)
                store.put(GATE_KIND, LOCK_KEY, {"held": False})
            checked["reservation_held"] = bool(hold_reservation)
            return checked
        finally:
            if store is not None and hasattr(store, "lock"):
                store.lock.release()


def simulate_consume_for_test(store, *, requests=1, units=1):
    """Test helper: mark units consumed without provider I/O."""
    ledger = _ledger(store)
    ledger["used_requests"] = int(ledger.get("used_requests") or 0) + int(requests)
    ledger["used_units"] = int(ledger.get("used_units") or 0) + int(units)
    ledger["in_flight"] = False
    store.put(GATE_KIND, LEDGER_KEY, ledger)
    return ledger


def hold_inflight_for_test(store, value=True):
    ledger = _ledger(store)
    ledger["in_flight"] = bool(value)
    store.put(GATE_KIND, LEDGER_KEY, ledger)
    return ledger


def gate_status(store=None):
    grant = _grant_from_store(store) if store is not None else None
    ledger = _ledger(store) if store is not None else {}
    checked = evaluate_authorization(grant, ledger=ledger)
    checked["draft_authorization_id"] = DRAFT_ID
    checked["draft_stays_disabled"] = True
    checked["live_enabled"] = False
    return checked
