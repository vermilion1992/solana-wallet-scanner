"""Throughput primitives. Ordering and cost only; gates stay fail-closed.

Token bucket + 429 backoff, a wallet+range page cache so paid pages are
never fetched twice, a Phase 4 process pool with per-wallet isolation, and
a batch funnel report. Drop or defer only. PRODUCT_READY stays false.
"""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path

from scanner.mass_search.qualification_gates import MAX_ECONOMIC_TRADES_PER_UTC_DAY
from scanner.mass_search.readable_first import (
    DEFER_UNREADABLE,
    DROP,
    KEEP,
    UNSCREENED,
    readable_first_plan,
    walk_ranked,
    write_funnel_report,
)
from scanner.mass_search.seed_sources import (
    HELIUS_SIGNATURES_CREDIT_NOTE,
    HELIUS_SIGNATURES_HISTORY_CAP,
    HELIUS_SIGNATURES_METHOD,
    HELIUS_SIGNATURES_PAGE_SIZE,
    HELIUS_SIGNATURES_UNITS,
    NANSEN_TIMEFRAMES_FUNNEL,
    cost_per_audit_worthy,
    helius_signatures_prescreen,
)

THROUGHPUT_VERSION = "throughput-funnel-v1"
CACHE_KIND = "raw-page-cache-v1"
DEFAULT_WORKERS = 2
GATES_UNCHANGED = (
    "coverage_0.99_result_relevant",
    "min_3_completed_episodes",
    "independently_audited_within_2",
    "zero_unresolved_basis_sales",
    f"bot_gt_{MAX_ECONOMIC_TRADES_PER_UTC_DAY}_economic_trades_full_history",
)


class TokenBucket:
    """Async-safe token bucket. Never issues a token that was not refilled."""

    def __init__(self, rate_per_sec, burst=None, *, clock=None):
        self.rate = max(float(rate_per_sec), 0.0)
        burst_n = int(burst) if burst not in (None, "") else max(1, int(self.rate) or 1)
        self.burst = max(1, burst_n)
        self._tokens = float(self.burst)
        self._clock = clock or time.monotonic
        self._updated = self._clock()

    def _refill(self):
        now = self._clock()
        elapsed = max(0.0, now - self._updated)
        self._updated = now
        if self.rate > 0:
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate)

    def try_take(self, n=1):
        self._refill()
        need = max(1, int(n))
        if self._tokens >= need:
            self._tokens -= need
            return True
        return False

    def wait_seconds(self, n=1):
        self._refill()
        need = max(1, int(n))
        if self._tokens >= need or self.rate <= 0:
            return 0.0
        return (need - self._tokens) / self.rate


def raw_page_cache_key(*, wallet, start_unix, end_unix, method, page=0, extra=None):
    """Stable key: wallet + range + method. Same key must not be paid twice."""
    payload = {
        "wallet": wallet,
        "start": int(start_unix or 0),
        "end": int(end_unix or 0),
        "method": method,
        "page": int(page or 0),
        "extra": extra or {},
        "kind": CACHE_KIND,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return f"{wallet[:12]}:{method}:{digest}"


def cache_path(root, key):
    return Path(root) / "page-cache" / f"{key}.bin"


def load_cached_page(root, key):
    path = cache_path(root, key)
    if not path.is_file() or path.stat().st_size == 0:
        return None
    return path.read_bytes()


def store_cached_page(root, key, raw):
    path = cache_path(root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = raw if isinstance(raw, (bytes, bytearray)) else bytes(raw)
    path.write_bytes(data)
    return path


class PageLedger:
    """In-memory paid-page ledger for tests and concurrent fetchers."""

    def __init__(self):
        self.paid = {}
        self.fetches = []
        self.discards = []

    def pay(self, key, units):
        if key in self.paid:
            raise ValueError(f"double spend for {key}")
        self.paid[key] = int(units)

    def record_fetch(self, key, raw):
        self.fetches.append(key)
        return raw

    def record_discard(self, key):
        self.discards.append(key)


async def fetch_with_cache_and_backoff(
    key,
    *,
    cache_root,
    ledger,
    units,
    fetch,
    retries=2,
    backoff_seconds=0.0,
    sleep=None,
):
    """Pay once. 429 retries keep the paid page. Never discard a paid fetch."""
    cached = load_cached_page(cache_root, key)
    if cached is not None:
        return {"raw": cached, "cache_hit": True, "units": 0, "external_requests": 0}
    ledger.pay(key, units)
    last_error = None
    sleeper = sleep or _async_sleep
    for attempt in range(1 + max(0, int(retries))):
        try:
            raw = await fetch()
        except Exception as error:
            last_error = error
            if getattr(error, "state", None) == "RATE_LIMITED" and attempt < retries:
                if backoff_seconds:
                    await sleeper(backoff_seconds * (attempt + 1))
                continue
            raise
        ledger.record_fetch(key, raw)
        store_cached_page(cache_root, key, raw)
        return {"raw": raw, "cache_hit": False, "units": units, "external_requests": 1, "attempts": attempt + 1}
    if last_error:
        raise last_error
    raise RuntimeError("fetch_with_cache_and_backoff exhausted retries")


async def _async_sleep(seconds):
    import asyncio
    await asyncio.sleep(seconds)


async def gather_capped(jobs, bucket, *, concurrency=4):
    """Run coroutines under a token bucket. Order of results matches jobs."""
    import asyncio

    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def run_one(job):
        async with sem:
            while not bucket.try_take():
                wait = bucket.wait_seconds()
                if wait > 0:
                    await asyncio.sleep(wait)
                else:
                    break
            return await job()

    return await asyncio.gather(*(run_one(job) for job in jobs))


def signatures_rpc_body(address, *, limit=HELIUS_SIGNATURES_PAGE_SIZE, before=None):
    opts = {"limit": int(limit)}
    if before:
        opts["before"] = before
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": HELIUS_SIGNATURES_METHOD,
        "params": [address, opts],
    }


def signatures_credit_note():
    return {
        "method": HELIUS_SIGNATURES_METHOD,
        "units": HELIUS_SIGNATURES_UNITS,
        "page_size": HELIUS_SIGNATURES_PAGE_SIZE,
        "note": HELIUS_SIGNATURES_CREDIT_NOTE,
        "history_cap_default": HELIUS_SIGNATURES_HISTORY_CAP,
        "threshold": MAX_ECONOMIC_TRADES_PER_UTC_DAY,
        "can_only_drop_or_defer": True,
    }


def screen_signatures(rows, *, max_per_day=None, history_cap=None):
    """Cheap raw-count screen. Drop or defer only; never a lead."""
    result = helius_signatures_prescreen(rows, max_per_day=max_per_day, history_cap=history_cap)
    result["can_only_drop_or_defer"] = True
    result["passed_lead"] = False
    return result


def run_phase4_pool(payloads, worker, *, workers=DEFAULT_WORKERS, backend="process"):
    """One worker per wallet. A worker exception becomes a fail-closed row."""
    items = list(payloads or [])
    if not items:
        return []
    workers_n = max(1, int(workers or 1))
    if workers_n == 1:
        return [_safe_worker(worker, item) for item in items]
    pool_cls = ThreadPoolExecutor if backend == "thread" else ProcessPoolExecutor
    rows = [None] * len(items)
    with pool_cls(max_workers=workers_n) as pool:
        futures = {pool.submit(_safe_worker, worker, item): idx for idx, item in enumerate(items)}
        for future in as_completed(futures):
            rows[futures[future]] = future.result()
    return rows


def _safe_worker(worker, payload):
    try:
        return worker(payload)
    except Exception as error:
        address = payload.get("address") if isinstance(payload, dict) else None
        return {
            "address": address,
            "independently_audited": False,
            "lead_level": "insufficient_evidence",
            "blocker": f"phase4_wallet_failed:{type(error).__name__}: {error}",
            "PRODUCT_READY": False,
        }


def isolated_phase4_sleep_worker(payload):
    """Synthetic worker for the speedup benchmark. No provider I/O."""
    delay = float((payload or {}).get("sleep") or 0)
    if delay:
        time.sleep(delay)
    return {
        "address": (payload or {}).get("address"),
        "ok": True,
        "PRODUCT_READY": False,
    }


def batch_funnel_report(
    walked,
    *,
    spend_by_stage=None,
    wall_s_by_stage=None,
    audit_worthy=None,
    extra=None,
):
    spend = dict(spend_by_stage or {})
    walls = dict(wall_s_by_stage or {})
    stages = []
    for name in ("discovery", "rule_a", "bot_prescreen", "decodability_sample", "deep_pull"):
        stages.append({
            "stage": name,
            "spend": spend.get(name) or {},
            "wall_s": walls.get(name),
        })
    kept = [row.get("address") for row in (walked or {}).get("kept") or []]
    worthy = int(audit_worthy or 0)
    source_spend = {"batch": {"units": 0, "requests": 0, "by_provider": {}}}
    for blob in spend.values():
        if not isinstance(blob, dict):
            continue
        source_spend["batch"]["units"] += int(blob.get("units") or 0)
        source_spend["batch"]["requests"] += int(blob.get("requests") or 0)
        provider = blob.get("provider")
        if provider:
            current = source_spend["batch"]["by_provider"].setdefault(
                provider, {"units": 0, "requests": 0},
            )
            current["units"] += int(blob.get("units") or 0)
            current["requests"] += int(blob.get("requests") or 0)
    payload = {
        "kind": "throughput-batch-v1",
        "version": THROUGHPUT_VERSION,
        "timeframes": list(NANSEN_TIMEFRAMES_FUNNEL),
        "stages": stages,
        "survivors": kept,
        "deferred_unreadable": [
            row.get("address") for row in (walked or {}).get("deferred_unreadable") or []
        ],
        "dropped": [row.get("address") for row in (walked or {}).get("dropped") or []],
        "unscreened": [row.get("address") for row in (walked or {}).get("unscreened") or []],
        "spend_by_stage": spend,
        "wall_s_by_stage": walls,
        "cost_per_audit_worthy": cost_per_audit_worthy(source_spend, {"batch": worthy}),
        "audit_worthy": worthy,
        "gates_unchanged": list(GATES_UNCHANGED),
        "can_only_drop_or_defer": True,
        "PRODUCT_READY": False,
    }
    if extra:
        payload.update(extra)
    return payload


def write_batch_report(output_dir, report):
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "THROUGHPUT_BATCH.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        f"# Throughput batch ({report.get('version')})",
        "",
        f"Survivors: {len(report.get('survivors') or [])}",
        f"Audit-worthy: {report.get('audit_worthy')}",
        "",
        "## Spend and wall time per stage",
        "",
    ]
    for stage in report.get("stages") or []:
        lines.append(
            f"- {stage.get('stage')}: spend={stage.get('spend')} wall_s={stage.get('wall_s')}"
        )
    lines.append("")
    lines.append(f"Cost per audit-worthy: {report.get('cost_per_audit_worthy')}")
    lines.append("PRODUCT_READY false. Gates unchanged.")
    (root / "THROUGHPUT_BATCH.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_batch_funnel(rows, *, n, cap=None, spend_by_stage=None, wall_s_by_stage=None, output_dir=None):
    """Offline batch: walk the ranked list until N keep or the cap is hit."""
    walked = walk_ranked(rows, n=n, cap=cap)
    worthy = len([
        row for row in walked["kept"]
        if row.get("independently_audited") or row.get("audit_worthy")
    ])
    report = batch_funnel_report(
        walked,
        spend_by_stage=spend_by_stage,
        wall_s_by_stage=wall_s_by_stage,
        audit_worthy=worthy,
        extra={"plan": readable_first_plan(deep_n=n, discovered_wallets=len(rows or []))},
    )
    if output_dir:
        write_batch_report(output_dir, report)
        write_funnel_report(output_dir, walked)
    return report
