"""What `visible_report` means and how it is persisted.

`visible_report` is a qualification flag on a saved mass-search report:

- True: the saved report has an independent worksheet and at least one
  completed known-cost position. It may be shown as a visible completed-
  position result. It is not an account-performance claim and is not
  PRODUCT_READY.
- False: the report is saved, but it is not a visible completed-position
  result (no-event capture, incomplete worksheet, or no completed
  known-cost position).
- absent: compatibility for reports written before this field existed.
  Treat as unknown. Gates and compare treat unknown as not-True. Never
  default absent to True if True would make the report pass anything.

The exact stored value is copied through save, JSON serialize, Store
retrieve, frontend hydration, and reopen. Explicit False must survive.
Defaults apply only when the field is absent.
"""
from __future__ import annotations


def stored_visible_report(payload):
    """Return True, False, or None (absent / unknown)."""
    if not isinstance(payload, dict) or "visible_report" not in payload:
        return None
    return payload["visible_report"] is True


def persist_visible_report(payload, value):
    """Write True or False. Never invent True from a missing value."""
    if value is True:
        payload["visible_report"] = True
    else:
        payload["visible_report"] = False
    return payload


def visible_report_passes(payload):
    """True only when the stored flag is exactly True. Absent never passes."""
    return stored_visible_report(payload) is True


def hydrate_visible_report(payload, *, cache_hit=False, fallback=None):
    """Reopen / cache-hit policy.

    Present True or False is kept. Absent on a cache hit or reopen is
    unknown/false, never True.
    """
    if isinstance(payload, dict) and "visible_report" in payload:
        return payload["visible_report"] is True
    if fallback is True:
        return True
    return False
