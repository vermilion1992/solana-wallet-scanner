"""Query-only discovery adapters. Live HTTP is refused without a validated authorization."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from scanner.config import validate_address
from scanner.storage import QuotaExceeded

from .capability import (
    access_blocker,
    apply_probe_result,
    documented_birdeye_traders,
    live_authorization_from_store,
    redact_secrets,
    validate_live_authorization,
)
from .plan import canonical_json

ADAPTER_VERSION = "mass-search-adapter-v1"
ALLOWED_BIRDEYE_HOST = "public-api.birdeye.so"
ALLOWED_BIRDEYE_PATH = "/trader/gainers-losers"


class SourceError(Exception):
    def __init__(self, state, message, *, http_status=None, retryable=False):
        super().__init__(message)
        self.state = state
        self.http_status = http_status
        self.retryable = retryable


def _lookup(row, path):
    if not isinstance(row, dict):
        return None
    if len(path) == 1 and path[0] in row:
        return row[path[0]]
    for key in path:
        if isinstance(row, dict) and key in row:
            return row[key]
    return None


def parse_trader_row(raw, *, field_map, source_id, page, offset, fetch_timestamp, source_timestamp=None):
    """Map a provider or fixture row. Unmapped or unreviewed fields stay unknown."""
    if not isinstance(raw, dict):
        return {"valid": False, "reason": "invalid_row", "raw": raw}
    address = _lookup(raw, field_map["address"]["path"])
    try:
        address = validate_address(address)
    except (TypeError, ValueError):
        return {"valid": False, "reason": "invalid_address", "raw": redact_secrets(raw)}
    realized = _lookup(raw, field_map["realized_pnl"]["path"])
    trade_count = _lookup(raw, field_map["trade_count"]["path"])
    last_active = _lookup(raw, field_map["last_active"]["path"])
    score_map = field_map.get("trader_score") or {"path": ["trader_score", "score"], "unit": "provider_score"}
    score = _lookup(raw, score_map["path"])
    extras = sorted(set(raw) - {"address", "realized_pnl", "pnl", "trade_count", "tx_counts",
                                "last_trade_unix_time", "last_active", "volume", "rank", "network",
                                "trader_score", "score"})
    return {
        "valid": True,
        "address": address,
        "chain": "solana",
        "source_id": source_id,
        "page": page,
        "offset": offset,
        "rank": raw.get("rank"),
        "realized_pnl": None if realized is None else str(realized),
        "realized_pnl_unit": field_map["realized_pnl"].get("unit", "USD"),
        "realized_pnl_basis": field_map["realized_pnl"].get("basis", "PROVIDER_REPORTED"),
        "trade_count": trade_count if type(trade_count) is int and not isinstance(trade_count, bool) else None,
        "trade_count_is_not": "completed_profitable_trades",
        "last_active": last_active,
        "trader_score": None if score is None else str(score),
        "trader_score_unit": score_map.get("unit", "provider_score"),
        "trader_score_basis": score_map.get("basis", "PROVIDER_REPORTED"),
        "trader_score_is_not": "independently_verified_profit_or_copyability",
        "unreviewed_fields": extras,
        "source_timestamp": source_timestamp,
        "fetch_timestamp": fetch_timestamp,
        "raw": redact_secrets(raw),
    }


class FixtureTraderAdapter:
    """Explicitly synthetic or replayed pages. Makes zero network calls."""

    source_id = "fixture-traders"
    live = False

    def __init__(self, pages, *, corpus_kind="SYNTHETIC", source_timestamp=None, fetch_timestamp=None):
        if not isinstance(pages, list) or not pages:
            raise ValueError("Fixture adapter requires at least one page")
        self.pages = [list(page) for page in pages]
        self.corpus_kind = corpus_kind
        self.source_timestamp = source_timestamp
        self.fetch_timestamp = fetch_timestamp
        self.requests = 0
        self.capability = apply_probe_result(
            {**documented_birdeye_traders(), "source_id": self.source_id, "provider": "fixture"},
            state="AUTHORIZED_AVAILABLE",
            role="GO_LIMITED",
            tested_cases=["fixture-page"],
            limitations=["Fixture transport is not a live provider entitlement."],
        )

    def fetch_page(self, *, offset, limit, window="30d", authorization=None, store=None):
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 100:
            raise ValueError("offset/limit must follow the documented Birdeye page contract")
        if offset + limit > 10000:
            raise SourceError("INCOMPLETE_SCOPE", "offset + limit exceeds the documented 10,000 bound")
        page_index = offset // max(limit, 1)
        if page_index >= len(self.pages):
            rows = []
        else:
            rows = self.pages[page_index][:limit]
        self.requests += 1
        parsed = [parse_trader_row(row, field_map=self.capability["field_map"], source_id=self.source_id,
                                   page=page_index, offset=offset, fetch_timestamp=self.fetch_timestamp or "fixture",
                                   source_timestamp=self.source_timestamp) for row in rows]
        raw = {"offset": offset, "limit": limit, "window": window, "items": rows}
        digest = hashlib.sha256(canonical_json(redact_secrets(raw)).encode()).hexdigest()
        next_offset = offset + limit if page_index + 1 < len(self.pages) else None
        if next_offset is not None and next_offset == offset:
            raise SourceError("INCOMPLETE_SCOPE", "Non-progressing cursor rejected")
        return {
            "source_id": self.source_id,
            "state": "AUTHORIZED_AVAILABLE",
            "window": window,
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset,
            "rows": parsed,
            "raw_count": len(rows),
            "evidence_sha256": digest,
            "billing_unit": "fixture_request",
            "units": 1,
            "external_requests": 0,
            "corpus_kind": self.corpus_kind,
        }


class BirdeyeTraderAdapter:
    """Read-only Birdeye ranking client. Refuses collection without live authorization."""

    source_id = "birdeye-traders"
    live = True

    def __init__(self, *, transport=None, docs_record=None):
        self.transport = transport
        self.capability = docs_record or documented_birdeye_traders()
        self.requests = 0

    def _authorized_entry(self, authorization, store):
        auth = authorization if authorization is not None else (live_authorization_from_store(store) if store else None)
        if auth is None:
            raise SourceError("UNAUTHORIZED", "No live authorization is present", retryable=False)
        checked = validate_live_authorization(auth)
        if not checked.get("enabled"):
            raise SourceError("UNAUTHORIZED", checked.get("reason") or "Live authorization is disabled", retryable=False)
        for entry in checked["providers"]:
            if entry["provider_id"] == "birdeye" and "trader_gainers_losers" in entry["allowed_operations"]:
                return checked, entry
        raise SourceError("UNAUTHORIZED", "Authorization does not include Birdeye trader_gainers_losers")

    def _reserve(self, store, entry, units):
        if store is None:
            return None
        cap = entry["max_units"]
        return store.reserve("birdeye", "trader_gainers_losers", units, entry["cycle_start"], cap)

    def _used_requests(self, store, entry):
        memory = self.requests
        if store is None:
            return memory
        with store.lock:
            row = store.db.execute(
                "SELECT COUNT(*) FROM reservations WHERE provider=? AND cycle=? AND method=? "
                "AND state IN ('dispatched','settled')",
                ("birdeye", entry["cycle_start"], "trader_gainers_losers"),
            ).fetchone()
        return max(memory, int(row[0] if row else 0))

    def _enforce_query(self, authorization, *, window, sort_by, sort_type, offset, limit):
        if sort_by not in self.capability.get("sort_fields", []):
            raise SourceError(
                "UNSUPPORTED_SCHEMA",
                f"Unsupported sort_by {sort_by}; silent fallback is forbidden",
            )
        exact = (authorization or {}).get("exact_query")
        if not exact:
            return
        params = exact.get("params") or {}
        expected = {
            "type": params.get("type"),
            "sort_by": params.get("sort_by"),
            "sort_type": params.get("sort_type"),
            "offset": params.get("offset"),
            "limit": params.get("limit"),
        }
        actual = {"type": window, "sort_by": sort_by, "sort_type": sort_type, "offset": offset, "limit": limit}
        if actual != expected:
            raise SourceError(
                "UNSUPPORTED_SCHEMA",
                "Request does not match the authorized exact query; silent fallback is forbidden",
            )

    async def fetch_page(self, *, offset, limit, window="30d", authorization=None, store=None,
                         sort_by="realized_pnl", sort_type="desc"):
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 100:
            raise ValueError("offset/limit must follow the documented Birdeye page contract")
        if offset + limit > 10000:
            raise SourceError("INCOMPLETE_SCOPE", "offset + limit exceeds the documented 10,000 bound")
        if window not in self.capability["supported_windows"]:
            raise SourceError("UNSUPPORTED_SCHEMA", f"Unsupported ranking window {window}")
        auth, entry = self._authorized_entry(authorization, store)
        self._enforce_query(auth, window=window, sort_by=sort_by, sort_type=sort_type, offset=offset, limit=limit)
        if self._used_requests(store, entry) >= entry["max_requests"]:
            raise SourceError("RATE_LIMITED", "Authorization request ceiling reached")
        units = int(self.capability["cost_model"]["documented_units_per_request"])
        reservation = None
        try:
            reservation = self._reserve(store, entry, units)
            if reservation and store:
                store.dispatch(reservation)
                self.requests += 1
            elif store is None:
                self.requests += 1
            if self.transport is None:
                raise SourceError("UNAUTHORIZED", "Live HTTP transport is not attached; collection remains blocked")
            response = await self.transport("GET", ALLOWED_BIRDEYE_PATH, params={
                "type": window, "sort_by": sort_by, "sort_type": sort_type, "offset": offset, "limit": limit,
            })
            status = int(response.get("status", 0))
            body = response.get("body")
            if status in (401, 403):
                raise SourceError("ENTITLEMENT_BLOCKED", "Provider rejected the key or plan", http_status=status)
            if status == 429:
                raise SourceError("RATE_LIMITED", "Provider rate limit", http_status=status, retryable=True)
            if status in (404, 501, 503):
                raise SourceError("UNAVAILABLE", "Provider endpoint unavailable", http_status=status, retryable=status >= 500)
            if status != 200 or not isinstance(body, dict):
                raise SourceError("UNSUPPORTED_SCHEMA", "Unexpected provider response", http_status=status)
            items = body.get("data", {}).get("items") if isinstance(body.get("data"), dict) else body.get("items")
            if items is None:
                items = body.get("data") if isinstance(body.get("data"), list) else None
            if not isinstance(items, list):
                raise SourceError("UNSUPPORTED_SCHEMA", "Provider items array is missing")
            parsed = [parse_trader_row(row, field_map=self.capability["field_map"], source_id=self.source_id,
                                       page=offset // limit, offset=offset,
                                       fetch_timestamp=response.get("fetched_at"),
                                       source_timestamp=body.get("updateTime") or body.get("updated_at"))
                      for row in items]
            if store and reservation:
                store.settle(reservation, charge=True)
            reservation = None
            return {
                "source_id": self.source_id,
                "state": "AUTHORIZED_AVAILABLE",
                "window": window,
                "offset": offset,
                "limit": limit,
                "next_offset": offset + limit if items and offset + limit < 10000 else None,
                "rows": parsed,
                "raw_count": len(items),
                "evidence_sha256": hashlib.sha256(canonical_json(redact_secrets(body)).encode()).hexdigest(),
                "billing_unit": "birdeye_compute_unit",
                "units": units,
                "external_requests": 1,
                "corpus_kind": "GENUINE_LIVE",
                "authorization_id": auth.get("authorization_id"),
                "query": {
                    "type": window,
                    "sort_by": sort_by,
                    "sort_type": sort_type,
                    "offset": offset,
                    "limit": limit,
                },
                "raw_body": redact_secrets(body),
                "raw_bytes": response.get("raw_bytes"),
            }
        except QuotaExceeded as error:
            raise SourceError("RATE_LIMITED", str(error)) from error
        except SourceError:
            if store and reservation:
                try:
                    store.settle(reservation, charge=True)
                except ValueError:
                    pass
            raise
        except Exception as error:
            if store and reservation:
                try:
                    store.settle(reservation, charge=True)
                except ValueError:
                    pass
            raise SourceError("UNAVAILABLE", "Provider request failed or timed out") from error
        finally:
            if store and reservation:
                try:
                    store.release(reservation)
                except ValueError:
                    pass


def classify_http_state(status):
    if status in (401, 403):
        return "ENTITLEMENT_BLOCKED"
    if status == 429:
        return "RATE_LIMITED"
    if status in (404, 501, 503):
        return "UNAVAILABLE"
    return "UNSUPPORTED_SCHEMA"


def empty_success_forbidden(state, rows):
    if state in ("ENTITLEMENT_BLOCKED", "RATE_LIMITED", "UNAVAILABLE", "UNAUTHORIZED") and rows == []:
        return True
    return False
