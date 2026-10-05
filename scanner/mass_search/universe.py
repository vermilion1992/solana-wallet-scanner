"""Frozen universe ingestion, membership retention and paginated summaries."""
from __future__ import annotations

import hashlib
import json
import uuid

from scanner.config import LIMITS, validate_address
from scanner.storage import now

from .metrics import build_metric, sort_key_for_metric
from .plan import sha256_json
from .schema import MASS_UNIVERSE_CAPACITY
from .triage import candidate_id

CHAIN = "solana"


def synthetic_address(index):
    """Deterministic valid 32-byte Solana address for local fixtures and scale tests."""
    if type(index) is not int or index < 0:
        raise ValueError("synthetic address index must be a non-negative integer")
    raw = (index + 1).to_bytes(32, "big")
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number = int.from_bytes(raw, "big")
    chars = []
    while number:
        number, rem = divmod(number, 58)
        chars.append(alphabet[rem])
    pad = sum(1 for byte in raw if byte == 0) if raw[0] == 0 else 0
    if raw[0] == 0:
        pad = 0
        for byte in raw:
            if byte:
                break
            pad += 1
    encoded = (alphabet[0] * pad) + "".join(reversed(chars))
    return validate_address(encoded)


def ingest_page(store, run_id, page, *, capacity=MASS_UNIVERSE_CAPACITY):
    """Add one source page. Duplicates keep memberships; invalid rows stay counted."""
    if page.get("state") in ("ENTITLEMENT_BLOCKED", "RATE_LIMITED", "UNAVAILABLE", "UNAUTHORIZED"):
        if not page.get("rows"):
            raise ValueError("Provider failure cannot be recorded as an empty-success universe")
    raw_rows = page.get("raw_count", len(page.get("rows") or []))
    unique_added = 0
    duplicates = 0
    invalids = 0
    added_ids = []
    timestamp = now()
    with store.lock, store.db:
        existing = store.db.execute(
            "SELECT COUNT(DISTINCT candidate_id) FROM candidate_memberships WHERE run_id=?",
            (run_id,),
        ).fetchone()[0]
        for row in page.get("rows") or []:
            if not row.get("valid"):
                invalids += 1
                continue
            address = validate_address(row["address"])
            ident = candidate_id(row.get("chain") or CHAIN, address)
            seen = store.db.execute(
                "SELECT 1 FROM candidate_memberships WHERE run_id=? AND candidate_id=?",
                (run_id, ident),
            ).fetchone()
            current = store.db.execute("SELECT 1 FROM candidate_universe WHERE candidate_id=?", (ident,)).fetchone()
            if current is None:
                store.db.execute(
                    "INSERT INTO candidate_universe VALUES (?,?,?,?,?,?)",
                    (ident, CHAIN, address, "unresolved", timestamp, timestamp),
                )
            store.db.execute(
                "INSERT INTO candidate_memberships VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, run_id, ident, row.get("source_id") or page["source_id"], row.get("page"),
                 row.get("stratum"), row.get("rank"), page.get("evidence_sha256"),
                 row.get("inclusion_reason") or "source_page", row.get("source_timestamp"),
                 row.get("fetch_timestamp"), json.dumps(row.get("raw") or {}, separators=(",", ":"))),
            )
            if seen:
                duplicates += 1
            else:
                if existing + unique_added >= capacity:
                    raise ValueError("Local bulk-universe capacity reached; legacy discovery caps are unchanged")
                unique_added += 1
                added_ids.append(ident)
                _write_provider_metrics(store, run_id, ident, row, page, timestamp)
        if existing + unique_added > capacity:
            raise ValueError("Local bulk-universe capacity reached")
    return {
        "raw_rows": raw_rows,
        "unique_added": unique_added,
        "duplicate_rows": duplicates,
        "invalid_rows": invalids,
        "added_ids": added_ids,
        "legacy_candidate_cap": LIMITS["candidate_cap"],
        "legacy_deep_audit_cap": LIMITS["deep_audit_cap"],
        "bulk_capacity": capacity,
    }


def _write_provider_metrics(store, run_id, ident, row, page, timestamp):
    window = {
        "start_inclusive": page.get("window_start") or "1970-01-01T00:00:00Z",
        "end_exclusive": page.get("window_end") or "2100-01-01T00:00:00Z",
    }
    evidence = [page["evidence_sha256"]] if page.get("evidence_sha256") else []
    provider = page.get("source_id")
    if row.get("realized_pnl") is None:
        metric = build_metric(
            metric_key="provider_realized_pnl", candidate_id=ident, value=None, unit=row.get("realized_pnl_unit") or "USD",
            state="UNKNOWN", basis="PROVIDER_REPORTED", window=window, population="provider_summary",
            population_count=0, observed_at=timestamp, evidence_sha256=evidence,
            missing_dependencies=["provider_realized_pnl"], source_provider=provider,
            notes=["Missing reported profit is deferred, not a zero."],
        )
    else:
        metric = build_metric(
            metric_key="provider_realized_pnl", candidate_id=ident, value=row["realized_pnl"],
            unit=row.get("realized_pnl_unit") or "USD", state="KNOWN", basis="PROVIDER_REPORTED",
            window=window, population="provider_summary", population_count=1, observed_at=timestamp,
            evidence_sha256=evidence or ["0" * 64], missing_dependencies=[], source_provider=provider,
            notes=["Provider-reported USD or native figure; not independently reconciled."],
        )
    _insert_metric(store, run_id, metric)
    if row.get("trade_count") is None:
        trade = build_metric(
            metric_key="provider_trade_count", candidate_id=ident, value=None, unit="count",
            state="UNKNOWN", basis="PROVIDER_REPORTED", window=window, population="provider_summary",
            population_count=0, observed_at=timestamp, evidence_sha256=evidence,
            missing_dependencies=["provider_trade_count"], source_provider=provider,
            notes=["Trade count is a queue-priority proxy, not completed positions."],
        )
    else:
        trade = build_metric(
            metric_key="provider_trade_count", candidate_id=ident, value=str(row["trade_count"]),
            unit="count", state="KNOWN", basis="PROVIDER_REPORTED", window=window,
            population="provider_summary", population_count=1, observed_at=timestamp,
            evidence_sha256=evidence or ["0" * 64], missing_dependencies=[], source_provider=provider,
            notes=["Cannot substitute for strict completed-position count."],
        )
    _insert_metric(store, run_id, trade)


def _insert_metric(store, run_id, metric):
    store.db.execute(
        "INSERT INTO metric_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uuid.uuid4().hex, run_id, metric["candidate_id"], metric["metric_key"], metric["value"],
         metric["unit"], metric["state"], metric["basis"], metric["window"]["start_inclusive"],
         metric["window"]["end_exclusive"], metric["population"], metric["population_count"],
         metric["method_version"], metric["observed_at"], json.dumps(metric["evidence_sha256"]),
         json.dumps(metric["missing_dependencies"]), metric["source_provider"],
         int(metric["is_wallet_wide_verified"]), json.dumps(metric["notes"]), metric["value_nanos"]),
    )


def universe_counts(store, run_id):
    with store.lock:
        raw, unique = store.db.execute(
            "SELECT COUNT(*), COUNT(DISTINCT candidate_id) FROM candidate_memberships WHERE run_id=?",
            (run_id,),
        ).fetchone()
    return {
        "raw_rows": raw,
        "unique_candidates": unique,
        "duplicate_rows": raw - unique,
        "invalid_rows": 0,
    }


def seal_universe(store, run_id, *, extra=None):
    payload = universe_counts(store, run_id)
    if extra:
        payload["invalid_rows"] = int(extra.get("invalid_rows") or 0)
        payload["raw_rows"] = int(extra.get("raw_rows") or payload["raw_rows"])
        payload["duplicate_rows"] = int(extra.get("duplicate_rows") or payload["duplicate_rows"])
    digest = sha256_json(payload)
    timestamp = now()
    with store.lock, store.db:
        store.db.execute(
            "UPDATE search_runs SET universe_sealed_at=?, universe_sha256=?, updated_at=? WHERE run_id=?",
            (timestamp, digest, timestamp, run_id),
        )
    return {**payload, "universe_sha256": digest, "universe_sealed_at": timestamp}


def page_summaries(store, run_id, *, stage=None, sort_metric="provider_realized_pnl",
                   cursor=None, limit=50, descending=True, data_run_id=None):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("Page size must be between 1 and 200")
    metric_run = data_run_id or run_id
    with store.lock:
        if stage:
            rows = store.db.execute(
                """SELECT d.candidate_id, d.result, d.reason_codes, u.address, m.value, m.value_nanos, m.unit, m.state
                   FROM stage_decisions d
                   JOIN candidate_universe u ON u.candidate_id = d.candidate_id
                   LEFT JOIN metric_snapshots m ON m.run_id = ? AND m.candidate_id = d.candidate_id
                        AND m.metric_key = ?
                   WHERE d.run_id=? AND d.stage_id=?""",
                (metric_run, sort_metric, run_id, stage),
            ).fetchall()
        else:
            rows = store.db.execute(
                """SELECT DISTINCT mem.candidate_id, NULL, NULL, u.address, m.value, m.value_nanos, m.unit, m.state
                   FROM candidate_memberships mem
                   JOIN candidate_universe u ON u.candidate_id = mem.candidate_id
                   LEFT JOIN metric_snapshots m ON m.run_id = ? AND m.candidate_id = mem.candidate_id
                        AND m.metric_key = ?
                   WHERE mem.run_id=?""",
                (metric_run, sort_metric, run_id),
            ).fetchall()
    ranked = []
    for row in rows:
        ranked.append((row[5], row[0], row))
    ranked.sort(key=lambda item: (
        item[0] is None,
        (-item[0] if descending else item[0] or 0) if item[0] is not None else 0,
        item[1],
    ))
    start = 0
    if cursor:
        for index, item in enumerate(ranked):
            if item[1] == cursor:
                start = index + 1
                break
    page_rows = ranked[start:start + limit]
    page = []
    for _nanos, _ident, row in page_rows:
        page.append({
            "candidate_id": row[0],
            "result": row[1],
            "reason_codes": json.loads(row[2]) if row[2] else [],
            "address": row[3],
            "sort_value": row[4],
            "sort_nanos": row[5],
            "unit": row[6],
            "metric_state": row[7],
        })
    next_cursor = page[-1]["candidate_id"] if len(page) == limit and start + limit < len(ranked) else None
    return {"items": page, "next_cursor": next_cursor, "total": len(ranked), "limit": limit}


def detect_cursor_loop(seen_offsets, offset):
    if offset in seen_offsets:
        raise ValueError("Repeated page offset or non-progressing cursor")
    seen_offsets.add(offset)
    return seen_offsets
