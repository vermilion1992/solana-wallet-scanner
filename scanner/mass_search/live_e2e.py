"""Parametrised LIVE end-to-end runner. Offline dry-run is the default proof path.

HTTP product routes never dispatch. This module is the only live entry for the
2026-10-07 proof grant. Dry-run uses a recorder transport and never opens a
socket. Live HTTP runs only when the operator arms a local grant and passes
--live on the box.

Helius getTransactionsForAddress metering (docs.helius.dev, repo review
2026-10-07; documented estimate, not a dashboard receipt):

- transactionDetails=signatures: 10 credits flat, up to 1,000 signatures.
- transactionDetails=full: 10 credits per 100 transactions returned, rounded
  up, minimum 10. Failed calls are free per docs; this runner still charges
  after dispatch (reserve-before-transport, dispatched always charged).
- Documented max limit is 1,000. A full page of limit=1,000 does not reduce
  credits versus ten limit=100 pages for the same 1,000 transactions (both
  100 credits). It does reduce request count, which matters because the
  proof grant caps requests at 500.
- The next-capture freeze in history_ingest.EXACT_HELIUS_OPTIONS stays
  limit=100 / full / desc. This runner uses a separate encoding and does
  not call assert_gta_options_not_widened.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from scanner.investigation import (
    DFLOW,
    DFLOW_DST,
    DGMG,
    FLASHX,
    GMGN,
    JUPITER,
    LIGHTHOUSE,
    METEORA_DAMM_V2,
    METEORA_DLMM,
    OKX_DEX_ROUTER,
    PHOTON,
    PUMP,
    PUMP_FEE_PROGRAM,
    PUMP_SWAP,
    RAYDIUM_AMM,
    RAYDIUM_CPMM,
    REVIEWED_OUTER_VENUES,
    RFQ_FILL,
    TOKEN_2022_ID,
    WHIRLPOOL,
    _keys,
    _program,
    decode_supported_swaps,
)
from scanner.mass_search.adapters import (
    ALLOWED_BIRDEYE_HOST,
    ALLOWED_BIRDEYE_PATH,
    ALLOWED_BIRDEYE_PATHS,
    BIRDEYE_FIRST_BUYERS_PATH,
    BIRDEYE_TOKEN_LIST_PATH,
    BIRDEYE_TOKEN_TX_SEEK_PATH,
    BIRDEYE_TOP_TRADERS_PATH,
    BirdeyeTraderAdapter,
    SourceError,
)
from scanner.mass_search.bundle_detect import detect_bundle_or_distribution
from scanner.mass_search.capability import LIVE_AUTH_SCHEMA, redact_secrets, utc_now, validate_live_authorization
from scanner.mass_search.evidence_integrity import redact_text, sanitize_jsonrpc_body, scrub_bytes
from scanner.mass_search.g3_history import inject_undecoded_buy_taints
from scanner.mass_search.history_ingest import replay_cached_history_to_report
from scanner.mass_search.labels import wallet_status_fields
from scanner.mass_search.live_e2e_ledger import (
    DEFAULT_LEDGER_ROOT,
    ExclusiveLock,
    LEDGER_ENV,
    LEDGER_HOME_ENV,
    LockHeld,
    committed_draft_payload,
    empty_phase_spend,
    empty_spend,
    grant_ledger_path,
    integrity_record,
    ledger_home,
    load_receipt,
    merge_spend,
    open_grant_store,
    phase_caps_from_grant,
    provider_caps,
    put_receipt,
    RECEIPT_KIND,
    CHAIN_ENTRY_KIND,
    receipt_is_spent,
    request_identity,
    spend_from_ledger,
    verify_receipt_chain,
)
from scanner.mass_search.qualification_gates import (
    coverage_shares,
    economic_trade_rate,
    qualifying_profit,
)
from scanner.mass_search.seed_sources import (
    ALLOWED_NANSEN_PATHS,
    BIRDEYE_FIRST_BUYERS_UNITS,
    BIRDEYE_TOKEN_LIST_UNITS,
    BIRDEYE_TOKEN_TX_SEEK_UNITS,
    BIRDEYE_TOKEN_TXS_PATH,
    BIRDEYE_TOKEN_TXS_UNITS,
    COUNT_KINDS,
    DURABLE_TOKEN_MIN_LIQUIDITY_USD,
    DURABLE_TOKEN_MIN_MARKET_CAP_USD,
    FIRST_BLOCK_EXCLUSION_SECONDS,
    TOKEN_INTERSECT_WINDOWS,
    TRIAGE_SAMPLES,
    NANSEN_FIRST_FUNDER_PATH,
    NANSEN_HOST,
    NANSEN_LABELS_PATH,
    NANSEN_LEADERBOARD_PATH,
    NANSEN_LEADERBOARD_UNITS,
    NANSEN_PNL_SUMMARY_PATH,
    NANSEN_PROFILER_UNITS,
    NANSEN_TIMEFRAMES,
    SEED_BIRDEYE_TOP,
    SEED_CU_DOCS,
    SEED_NANSEN,
    SEED_PRESCREEN_FILTER,
    SEED_TOKEN_INTERSECT,
    SeedSourceError,
    TOKEN_INTERSECT_CONTROLS,
    TOKEN_INTERSECT_SEASONED,
    cheap_prescreen_decision,
    cheap_prescreen_enabled,
    cost_per_audit_worthy,
    densest_utc_day_bounds,
    estimate_seed_plan,
    helius_triage_decision,
    helius_triage_enabled,
    history_span_days,
    intersect_token_cohorts,
    nansen_billing_from_headers,
    nansen_date_range_from_bounds,
    nansen_first_funder_supported,
    nansen_leaderboard_body,
    nansen_leaderboard_rows,
    nansen_pnl_summary_body,
    nansen_schema_kind_for_path,
    redact_nansen_error_body,
    token_txs_params,
    ordinary_windows,
    parse_seed_sources,
    primary_seed_source,
    record_seed_metadata,
    resolve_seed_sources,
    seed_fields_for_wallet,
    select_control_tokens,
    select_durable_tokens,
    select_nansen_wallets,
    token_list_items,
    validate_nansen_body,
    token_tx_items,
    token_tx_owners,
    utc_now_unix,
)
from scanner.mass_search.research_profile import (
    attach_live_independent_audit,
    build_research_profile,
    default_filters,
    independently_audited,
)
from scanner.mass_search.workflow import _authoritative_saved_profile
from scanner.storage import QuotaExceeded, Store

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

ROOT = Path(__file__).resolve().parents[2]
AUTHORIZATION_ID = "live-e2e-proof-2026-10-07-mitch"
AUTHORIZATION_ID_NEXT = "live-e2e-proof-2026-10-09-mitch"
AUTHORIZATION_ID_11 = "live-e2e-proof-2026-10-11-mitch"
AUTHORIZATION_ID_12 = "live-e2e-proof-2026-10-12-mitch"
AUTHORIZATION_ID_13 = "live-e2e-proof-2026-10-13-mitch"
DRAFT_REL = "config/live_authorization.live-e2e-proof-2026-10-07-mitch-draft.json"
DRAFT_REL_NEXT = "config/live_authorization.live-e2e-proof-2026-10-09-mitch-draft.json"
DRAFT_REL_11 = "config/live_authorization.live-e2e-proof-2026-10-11-mitch-draft.json"
DRAFT_REL_12 = "config/live_authorization.live-e2e-proof-2026-10-12-mitch-draft.json"
DRAFT_REL_13 = "config/live_authorization.live-e2e-proof-2026-10-13-mitch-draft.json"
DRAFT_PATH = ROOT / DRAFT_REL
# --live accepts the 2026-10-12 and 2026-10-13 drafts. 07, 09 and 11 are retired.
# Dry-run may still load a retired draft.
LIVE_KNOWN_DRAFTS = {
    AUTHORIZATION_ID_12: DRAFT_REL_12,
    AUTHORIZATION_ID_13: DRAFT_REL_13,
}
RETIRED_LIVE_DRAFTS = {
    AUTHORIZATION_ID: DRAFT_REL,
    AUTHORIZATION_ID_NEXT: DRAFT_REL_NEXT,
    AUTHORIZATION_ID_11: DRAFT_REL_11,
}
KNOWN_DRAFTS = {**RETIRED_LIVE_DRAFTS, **LIVE_KNOWN_DRAFTS}
# Pinned committed-blob hashes. A local commit of an inflated draft cannot
# satisfy --live unless this constant is also changed (HARD_CEILINGS still bind).
PINNED_DRAFT_HASHES = {
    AUTHORIZATION_ID: "ca4c3f9637d5d8ee11475a8c1704bb964a0a7bed4e126c69e92c65ef9043f410",
    AUTHORIZATION_ID_NEXT: "cda7b98d4d3bf0c219c53f4c37f2c6bc3b62d9480b60ad69d01f1709fc65af62",
    AUTHORIZATION_ID_11: "a2b6b4b53717f9d7dcb5f0f9a60bd073274af4e810aae3943af7edb9d003512b",
    AUTHORIZATION_ID_12: "65b14ccd9e60e453760a1d1da55c825d1083c86c416bc8957985b361fc483270",
    AUTHORIZATION_ID_13: "e9629ca44a48671bb9a61c1b3c2ec19a42aa5338b1fc53e00c55498fe3254a2e",
}
HARD_CEILINGS = {
    "birdeye_requests": 40,
    "birdeye_units": 1400,
    "helius_requests": 3000,
    "helius_units": 30000,
    "nansen_requests": 20,
    "nansen_units": 100,
    "leaderboard_requests": 0,
    "leaderboard_units": 0,
}
FATAL_SEED_STATES = frozenset({
    "ENTITLEMENT_BLOCKED",
    "UNSUPPORTED_SCHEMA",
    "UNAUTHORIZED",
    "RATE_LIMITED",
    "PAYMENT_REQUIRED",
})
# Ledger home is pinned here and in the committed draft, not in the armed copy.
# --live uses this absolute path. It must not depend on HOME.
PINNED_LEDGER_REL = ".scanner/live-e2e-ledgers"
COMMITTED_LEDGER_ABSOLUTE = "/home/box/.scanner/live-e2e-ledgers"
PINNED_LEDGER_ABSOLUTE = COMMITTED_LEDGER_ABSOLUTE
BIRDEYE_KEY_ENV = "BIRDEYE_API_KEY"
HELIUS_KEY_ENV = "HELIUS_API_KEY"
NANSEN_KEY_ENV = "NANSEN_API_KEY"
HELIUS_ENDPOINT = "https://mainnet.helius-rpc.com/"
HELIUS_METHOD = "getTransactionsForAddress"
HELIUS_MIN_INTERVAL_ENV = "SCANNER_HELIUS_MIN_INTERVAL_SEC"
HELIUS_BACKOFF_ENV = "SCANNER_HELIUS_BACKOFF_SEC"
DEFAULT_HELIUS_MIN_INTERVAL = 0.5
DEFAULT_HELIUS_BACKOFF = 2.0
_HELIUS_LAST_CALL = 0.0
_HELIUS_PACE_LOCK = asyncio.Lock() if hasattr(asyncio, "Lock") else None
BIRDEYE_MIN_INTERVAL_ENV = "SCANNER_BIRDEYE_MIN_INTERVAL_SEC"
BIRDEYE_BACKOFF_ENV = "SCANNER_BIRDEYE_BACKOFF_SEC"
DEFAULT_BIRDEYE_MIN_INTERVAL = 4.0
DEFAULT_BIRDEYE_BACKOFF = 4.0
BIRDEYE_RATE_LIMIT_RETRIES = 2
_BIRDEYE_LAST_CALL = 0.0
_BIRDEYE_PACE_LOCK = asyncio.Lock() if hasattr(asyncio, "Lock") else None

GTA_MAX_LIMIT = 1000
GTA_SAMPLE_LIMIT = 100
SIG_ONLY_UNITS = 10
FULL_100_UNITS = 10
FULL_1000_UNITS = 100
BIRDEYE_UNITS = 30
BIRDEYE_TOP_TRADERS_UNITS = 35
BIRDEYE_DEFAULT_LIMIT = 100
BIRDEYE_DEFAULT_WINDOW = "30d"
BIRDEYE_DEFAULT_SORT = "trader_score"
BIRDEYE_TOP_TRADERS_SORTS = frozenset({
    "volume", "trade", "total_pnl", "unrealized_pnl", "realized_pnl", "volume_usd",
})
BIRDEYE_TOP_TRADERS_DEFAULT_SORT = "realized_pnl"
BIRDEYE_DISCOVERY_GAINERS = "gainers-losers"
BIRDEYE_DISCOVERY_TOP_TRADERS = "top-traders"
# Liquid established tokens for solo-trader top-traders discovery.
ESTABLISHED_LIQUID_MINTS = (
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
)
# Documented CU (docs.birdeye.so/docs/compute-unit-cost, reviewed 2026-10-07):
# GET /trader/gainers-losers = 30 CU fixed. Supported type= yesterday|today|1W|30d|90d;
# sort_by = PnL|realized_pnl|unrealized_pnl|trader_score.
# GET /defi/v2/tokens/top_traders = 35 CU fixed. time_frame=30m|1h|2h|4h|6h|8h|12h|24h
# plus 2d|3d|7d|14d|30d|60d|90d; sort_by=volume|trade|total_pnl|unrealized_pnl|realized_pnl|volume_usd.
BIRDEYE_CU_DOCS = {
    BIRDEYE_DISCOVERY_GAINERS: {
        "path": ALLOWED_BIRDEYE_PATH,
        "documented_cu": BIRDEYE_UNITS,
        "docs": "https://docs.birdeye.so/docs/compute-unit-cost",
        "reviewed_on": "2026-10-07",
    },
    BIRDEYE_DISCOVERY_TOP_TRADERS: {
        "path": BIRDEYE_TOP_TRADERS_PATH,
        "documented_cu": BIRDEYE_TOP_TRADERS_UNITS,
        "docs": "https://docs.birdeye.so/docs/compute-unit-cost",
        "reviewed_on": "2026-10-07",
    },
    SEED_TOKEN_INTERSECT: SEED_CU_DOCS[SEED_TOKEN_INTERSECT],
    SEED_NANSEN: SEED_CU_DOCS[SEED_NANSEN],
}

L2TEX_PROGRAM = LIGHTHOUSE
FLASHX_PROGRAM = FLASHX
B311_PROGRAM = "B3111yJCeHBcA1bizdJjUFPALfhAfSRnAbJzGUtnt56A"
KNOWN_BLOCKING_PROGRAMS = {
    FLASHX_PROGRAM: "FLASHX Axiom",
    B311_PROGRAM: "B311 unreviewed",
    DFLOW: "DFlow",
    DFLOW_DST: "DFlow DST FulfillOrder",
    DGMG: "DGMg PumpSwap router",
    GMGN: "GMGN",
    PHOTON: "Photon",
    METEORA_DLMM: "Meteora DLMM",
}
# Photon and DFlow DST layouts are pinned but unsupported (0 real txs decode).
SUPPORTED_PROGRAMS = frozenset(REVIEWED_OUTER_VENUES) | {
    JUPITER, PUMP, PUMP_SWAP, RAYDIUM_CPMM, RAYDIUM_AMM, WHIRLPOOL, METEORA_DAMM_V2,
    OKX_DEX_ROUTER, RFQ_FILL, DFLOW, FLASHX, GMGN, METEORA_DLMM,
}
INFRA_PROGRAMS = frozenset({
    "11111111111111111111111111111111",
    "ComputeBudget111111111111111111111111111111",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    TOKEN_2022_ID,
    LIGHTHOUSE,
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
    "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo",
    PUMP_FEE_PROGRAM,
})
STATE_NAME = "RUN_STATE.json"
PLAN_NAME = "DRY_RUN_PLAN.json"
RESULTS_NAME = "RESULTS.json"
SUMMARY_NAME = "SUMMARY.md"
GTA_DOCS_NAME = "GTA_PAGE_SIZE.md"
NAME_MAX = 255

SEARCH_B_COHORT = (
    "gtfoTELAeEZHUgHetA6umfsCETiBMzJCN4tB2sqCgFL",
    "CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU",
    "BVZtNYBjivojQnJhocggTVqkbFDYNr2R61c6BZLkY9n9",
    "BSN5bh8At4BkTGMoysA76fvsvoTsVpjaXRatNJYJBtCM",
    "DQ7nsa6RPG9F6QjqDUa7LEN5CEvs9sPssXyRYVRb9Cys",
    "A6PSQFRfv93hoAn1LhQGRT2dYQtjDKX6SE2vN9MEvbot",
    "An9sREpLnAXVi4KMaTGuGvgET51CyaukLUTMtxzmLYSB",
    "58PWvekDbHVPFB9FXGQrpumHD16NRajahkYLHiTvxvDL",
    "AW6Pddy72jXDbMUPoSaTB7joJVvMmEMXaYPJhpRqMzD6",
    "CRXomDFunLoRm5N54TyxCxAzn6NJtvnjKvuxudHSV68U",
)


class LiveE2EError(ValueError):
    """Bad params or invariant violation. CLI maps this to exit 2."""


def _iso_to_unix(value):
    if type(value) is int:
        return value
    text = str(value).replace("Z", "+00:00")
    return int(datetime.fromisoformat(text).timestamp())


def _sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(redact_secrets(payload), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_grant(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != LIVE_AUTH_SCHEMA:
        raise LiveE2EError("Grant must use live-research-authorization-v1")
    return validate_live_authorization(payload)


def provider_entry(grant, provider_id):
    for entry in grant.get("providers") or []:
        if entry.get("provider_id") == provider_id:
            return entry
    raise LiveE2EError(f"Grant does not include {provider_id}")


def credential_presence():
    return {
        "birdeye": bool(os.environ.get(BIRDEYE_KEY_ENV)),
        "helius": bool(os.environ.get(HELIUS_KEY_ENV) or os.environ.get("HELIUS_KEY")),
        "nansen": bool(os.environ.get(NANSEN_KEY_ENV)),
    }


def parse_phases(value):
    if value in (None, "", "all"):
        return (1, 2, 3, 4)
    if isinstance(value, (list, tuple)):
        items = [int(item) for item in value]
    else:
        items = [int(part.strip()) for part in str(value).split(",") if part.strip()]
    if not items or any(item not in (1, 2, 3, 4) for item in items):
        raise LiveE2EError("phases must be a subset of 1,2,3,4")
    return tuple(sorted(set(items)))


def _is_wallet_file(value):
    text = str(value)
    if not text or len(text) >= NAME_MAX or "," in text:
        return False
    try:
        return Path(text).is_file()
    except OSError:
        return False


def parse_wallets(value):
    if value in (None, "", []):
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    if _is_wallet_file(value):
        payload = json.loads(Path(value).read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return [str(item).strip() for item in payload if str(item).strip()]
        rows = payload.get("wallets") or payload.get("addresses") or []
        out = []
        for row in rows:
            if isinstance(row, str) and row.strip():
                out.append(row.strip())
            elif isinstance(row, dict) and row.get("address"):
                out.append(str(row["address"]).strip())
        return out
    return [part.strip() for part in str(value).split(",") if part.strip()]


def window_bounds(window_days, earlier_history_days, *, end=None, history_to_first=False, history_start_unix=None, report_window_days=None):
    if type(window_days) is not int or not 1 <= window_days <= 365:
        raise LiveE2EError("window_days must be an integer 1-365")
    report_days = window_days if report_window_days is None else report_window_days
    if type(report_days) is not int or not 1 <= report_days <= 365:
        raise LiveE2EError("report_window_days must be an integer 1-365")
    if history_to_first or history_start_unix is not None:
        if type(earlier_history_days) is not int or earlier_history_days < 0:
            raise LiveE2EError("earlier_history_days must be a non-negative integer")
    elif type(earlier_history_days) is not int or not 0 <= earlier_history_days <= 365:
        raise LiveE2EError("earlier_history_days must be an integer 0-365")
    end = end or datetime.now(timezone.utc).replace(microsecond=0)
    report_start = end - timedelta(days=report_days)
    if history_start_unix is not None:
        if type(history_start_unix) is not int or history_start_unix < 0:
            raise LiveE2EError("history_start_unix must be a non-negative Unix timestamp")
        history_start = datetime.fromtimestamp(history_start_unix, tz=timezone.utc).replace(microsecond=0)
        if history_start > report_start:
            raise LiveE2EError("history_start_unix cannot be after the report window start")
        earlier = max(int((report_start - history_start).total_seconds() // 86400), 0)
    elif history_to_first:
        history_start = datetime(2020, 3, 16, tzinfo=timezone.utc)
        earlier = max(int((report_start - history_start).total_seconds() // 86400), 0)
    else:
        history_start = report_start - timedelta(days=earlier_history_days)
        earlier = earlier_history_days
    return {
        "report_end_exclusive": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "report_start_inclusive": report_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "history_start_inclusive": history_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "report_start_unix": int(report_start.timestamp()),
        "report_end_unix": int(end.timestamp()),
        "history_start_unix": int(history_start.timestamp()),
        "window_days": window_days,
        "report_window_days": report_days,
        "earlier_history_days": earlier,
        "history_to_first": bool(history_to_first or history_start_unix is not None),
    }


def _iso(dt):
    if isinstance(dt, datetime):
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(dt)


def _parse_iso(text):
    return datetime.fromisoformat(str(text).replace("Z", "+00:00"))


def record_block_times(records):
    times = []
    for row in records or []:
        stamp = row.get("blockTime") or row.get("timestamp")
        if stamp is None and isinstance(row.get("transaction"), dict):
            stamp = row["transaction"].get("blockTime")
        if type(stamp) is int:
            times.append(stamp)
    return times


def align_wallet_bounds(records, bounds):
    """Anchor report end to this wallet's last captured blockTime.

    Coverage uses the captured span so a later run clock cannot hide an
    uncovered earlier transaction. P&L still uses the requested report days
    ending at min(configured_end, last+1).

    Alignment is last-tx anchoring, not a clock-now window. A quiet wallet's
    "30d" can therefore end at its last transaction (stale versus the
    configured report_end). Gates still consume the aligned end. Both the
    configured and aligned ends are returned so reports can document the
    difference (D9). This function does not change how alignment works.
    """
    times = record_block_times(records)
    configured_end = _parse_iso(bounds["report_end_exclusive"])
    configured_hist = _parse_iso(bounds["history_start_inclusive"])
    last = max(times) if times else None
    first = min(times) if times else None
    end = configured_end
    if last is not None:
        last_end = datetime.fromtimestamp(last + 1, tz=timezone.utc)
        if last_end < end:
            end = last_end
    report_days = int(bounds.get("report_window_days") or bounds.get("window_days") or 30)
    start = end - timedelta(days=report_days)
    hist = configured_hist
    cov_start = configured_hist
    if first is not None:
        first_dt = datetime.fromtimestamp(first, tz=timezone.utc)
        if first_dt < hist:
            hist = first_dt
        if first_dt < cov_start:
            cov_start = first_dt
    return {
        "report_start_inclusive": _iso(start),
        "report_end_exclusive": _iso(end),
        "configured_report_end_exclusive": _iso(configured_end),
        "aligned_report_end_exclusive": _iso(end),
        "report_end_anchored_to_last_tx": bool(last is not None and end != configured_end),
        "history_start_inclusive": _iso(hist),
        "coverage_start_inclusive": _iso(cov_start),
        "coverage_end_exclusive": _iso(end),
        "report_window_days": report_days,
        "report_start_unix": int(start.timestamp()),
        "report_end_unix": int(end.timestamp()),
        "history_start_unix": int(hist.timestamp()),
    }


def gta_options(*, details, limit, start_unix, end_unix, pagination_token=None, sort_order="desc"):
    """Helius GTA options. Version and token-account filter are explicit.

    maxSupportedTransactionVersion=1 is required so v0/address-lookup
    transactions are returned. Omitting it is documented as legacy-only.
    tokenAccounts=all is a conscious choice: owner-only misses ATA history.
    Token-account discovery before Dec 2022 is incomplete per Helius.
    """
    if details not in ("signatures", "full"):
        raise LiveE2EError("GTA transactionDetails must be signatures or full")
    if type(limit) is not int or not 1 <= limit <= GTA_MAX_LIMIT:
        raise LiveE2EError(f"GTA limit must be 1-{GTA_MAX_LIMIT}")
    if sort_order not in ("desc", "asc"):
        raise LiveE2EError("GTA sortOrder must be desc or asc")
    options = {
        "transactionDetails": details,
        "limit": limit,
        "sortOrder": sort_order,
        "commitment": "finalized",
        "maxSupportedTransactionVersion": 1,
        "filters": {
            "status": "any",
            "tokenAccounts": "all",
            "blockTime": {"gte": int(start_unix), "lt": int(end_unix)},
        },
    }
    if pagination_token:
        options["paginationToken"] = pagination_token
    return options


def documented_units(details, limit):
    if details == "signatures":
        return SIG_ONLY_UNITS
    if limit <= 100:
        return FULL_100_UNITS
    return FULL_1000_UNITS


def gta_page_size_note():
    return {
        "kind": "helius-gta-page-size-v1",
        "docs": "https://www.helius.dev/docs/rpc/gettransactionsforaddress",
        "reviewed_on": "2026-10-07",
        "max_limit": GTA_MAX_LIMIT,
        "signatures_only": {
            "transactionDetails": "signatures",
            "limit": GTA_MAX_LIMIT,
            "credits": SIG_ONLY_UNITS,
            "note": "10 credits flat for up to 1,000 signatures.",
        },
        "full_sample": {
            "transactionDetails": "full",
            "limit": GTA_SAMPLE_LIMIT,
            "credits": FULL_100_UNITS,
            "note": "One sample page. 10 credits per 100 txs returned.",
        },
        "full_history": {
            "transactionDetails": "full",
            "limit": GTA_MAX_LIMIT,
            "credits_worst_case": FULL_1000_UNITS,
            "note": (
                "Largest documented page. Same credits as ten limit=100 pages "
                "for 1,000 returned txs; fewer requests. next-capture freeze "
                "stays limit=100 and is not used here."
            ),
        },
        "PRODUCT_READY": False,
    }


def collect_program_ids(records):
    """Resolve instruction programs via accountKeys + loadedAddresses, including inners."""
    found = []
    for record in records or []:
        raw = record
        if isinstance(record, dict) and isinstance(record.get("raw"), dict):
            raw = record["raw"]
        if isinstance(raw, dict) and isinstance(raw.get("result"), dict) and "transaction" not in raw:
            raw = raw["result"]
        if not isinstance(raw, dict):
            continue
        transaction = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
        message = transaction.get("message") if isinstance(transaction.get("message"), dict) else {}
        meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        if not message:
            continue
        try:
            keys = _keys(message, meta)
        except (ValueError, TypeError, KeyError, IndexError):
            keys = []
        instructions = list(message.get("instructions") or [])
        for group in meta.get("innerInstructions") or []:
            if isinstance(group, dict):
                instructions.extend(group.get("instructions") or [])
        for instruction in instructions:
            if not isinstance(instruction, dict):
                continue
            try:
                program = _program(instruction, keys) if keys else instruction.get("programId")
            except (ValueError, TypeError, KeyError, IndexError):
                program = instruction.get("programId")
            if isinstance(program, str) and 32 <= len(program) <= 44:
                found.append(program)
    return found


def _record_signature(record):
    if not isinstance(record, dict):
        return None
    if record.get("signature"):
        return record["signature"]
    raw = record.get("raw") if isinstance(record.get("raw"), dict) else record
    if isinstance(raw, dict) and isinstance(raw.get("result"), dict) and "transaction" not in raw:
        raw = raw["result"]
    tx = raw.get("transaction") if isinstance(raw, dict) else None
    sigs = (tx or {}).get("signatures") if isinstance(tx, dict) else None
    if isinstance(sigs, list) and sigs:
        return sigs[0]
    return None


def _record_abs_sol(record, address=None):
    raw = record
    if isinstance(record, dict) and isinstance(record.get("raw"), dict):
        raw = record["raw"]
    if isinstance(raw, dict) and isinstance(raw.get("result"), dict) and "transaction" not in raw:
        raw = raw["result"]
    if not isinstance(raw, dict):
        return Decimal("0")
    meta = raw.get("meta") or {}
    message = ((raw.get("transaction") or {}).get("message") or {})
    try:
        keys = _keys(message, meta)
    except (ValueError, TypeError, KeyError, IndexError):
        return Decimal("0")
    if not keys:
        return Decimal("0")
    target = address if address in keys else keys[0]
    try:
        index = keys.index(target)
    except ValueError:
        return Decimal("0")
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    if index >= len(pre) or index >= len(post):
        return Decimal("0")
    delta = Decimal(post[index] - pre[index])
    fee = meta.get("fee") if isinstance(meta.get("fee"), int) else 0
    if keys[0] == target:
        delta += Decimal(fee)
    return abs(delta) / Decimal(1_000_000_000)


def _decoded_swap_signatures(records, address=None):
    address = address or ""
    try:
        from scanner.mass_search.canonical_records import canonical_decode_records
        decoded = decode_supported_swaps(canonical_decode_records(records or []), address)
    except Exception:
        return set()
    found = set()
    for event in decoded.get("events") or []:
        # USDC↔SOL DFlow/Jupiter fills are reviewed conversions, not
        # missing venues. They must not rank as DFlow blockers.
        if event.get("kind") in ("buy", "sell", "conversion") and event.get("signature"):
            found.add(event["signature"])
    return found


def classify_programs(records, address=None):
    """Rank programs that appear in UNDECODED swaps only, by count and by value.

    Pump fee-calculation `pfeeUxB6` is infra (it appears inside decoded PumpSwap
    too) and is never a venue blocker.
    """
    decoded_sigs = _decoded_swap_signatures(records, address)
    counts = {}
    value = {}
    for record in records or []:
        signature = _record_signature(record)
        if signature and signature in decoded_sigs:
            continue
        programs = []
        raw = record
        if isinstance(record, dict) and isinstance(record.get("raw"), dict):
            raw = record["raw"]
        if isinstance(raw, dict) and isinstance(raw.get("result"), dict) and "transaction" not in raw:
            raw = raw["result"]
        if not isinstance(raw, dict):
            continue
        for program in collect_program_ids([record]):
            programs.append(program)
        sol = _record_abs_sol(record, address)
        seen = set()
        for program in programs:
            if program in INFRA_PROGRAMS or program in seen:
                continue
            seen.add(program)
            counts[program] = counts.get(program, 0) + 1
            value[program] = value.get(program, Decimal("0")) + sol
    blockers = []
    seen = set()
    ranked = sorted(counts.items(), key=lambda item: (-value.get(item[0], Decimal("0")), -item[1], item[0]))
    for program, count in ranked:
        if program in seen:
            continue
        seen.add(program)
        label = KNOWN_BLOCKING_PROGRAMS.get(program, "unsupported_or_unreviewed")
        blockers.append({
            "program_id": program,
            "label": label,
            "observations": count,
            "value_sol": str(value.get(program, Decimal("0"))),
            "supported": False,
        })
    supported_hits = sum(count for program, count in counts.items() if program in SUPPORTED_PROGRAMS)
    blocking_hits = sum(row["observations"] for row in blockers)
    total = supported_hits + blocking_hits
    supported_value = sum((val for program, val in value.items() if program in SUPPORTED_PROGRAMS), Decimal("0"))
    blocking_value = sum((val for program, val in value.items() if program not in SUPPORTED_PROGRAMS), Decimal("0"))
    value_total = supported_value + blocking_value
    return {
        "program_counts": counts,
        "program_value_sol": {key: str(val) for key, val in value.items()},
        "blockers": blockers,
        "supported_observations": supported_hits,
        "unsupported_observations": blocking_hits,
        "supported_value_sol": str(supported_value),
        "unsupported_value_sol": str(blocking_value),
        "decodable_share": None if not total else str((Decimal(supported_hits) / Decimal(total)).quantize(Decimal("0.0001"))),
        "supported_venue_value_share": (
            None if not value_total
            else str((supported_value / value_total).quantize(Decimal("0.0001")))
        ),
    }


def compute_bot_rate(sig_records, window_days):
    """Robust txs / active day. A 7-minute 4-tx burst is not 96/day.

    Denominator is max(observed span in days, 1 day). Distinct UTC dates
    only raise the floor when the observed span is under one day (a
    midnight-crossing burst), so 100 txs over exactly one observed day
    stay 100/day while genuine HFT still fires.
    """
    count = len(sig_records or [])
    times = []
    for row in sig_records or []:
        stamp = None
        if isinstance(row, dict):
            stamp = row.get("blockTime") or row.get("timestamp")
            if stamp is None:
                stamp = ((row.get("transaction") or {}).get("blockTime"))
        if type(stamp) is int:
            times.append(stamp)
    if not times:
        span = Decimal(max(int(window_days or 1), 1))
        return (Decimal(count) / span).quantize(Decimal("0.0001"))
    observed = Decimal(max(times) - min(times)) / Decimal(86400)
    span = max(observed, Decimal("1"))
    if observed < Decimal("1"):
        active_days = Decimal(len({datetime.fromtimestamp(stamp, tz=timezone.utc).date() for stamp in times}))
        span = max(span, active_days)
    return (Decimal(count) / span).quantize(Decimal("0.0001"))


def page_sort_key(path):
    """Numeric pageN.bin order (page2 before page10)."""
    stem = Path(path).stem
    digits = stem[4:] if stem.startswith("page") else stem
    if digits.isdigit():
        return (0, int(digits))
    return (1, stem)


def unwrap_gta_record(record):
    if not isinstance(record, dict):
        return {}
    if "transaction" in record:
        return record
    raw = record.get("raw")
    if isinstance(raw, dict):
        result = raw.get("result")
        if isinstance(result, dict) and "transaction" in result:
            return result
        if "transaction" in raw:
            return raw
    return record


def oldest_native_prebalance(records, address):
    """Oldest captured native preBalance. Same-second ties prefer preBalance 0."""
    oldest = None
    for record in records or []:
        raw = unwrap_gta_record(record)
        if not isinstance(raw, dict):
            continue
        stamp = raw.get("blockTime") or raw.get("timestamp") or ((raw.get("transaction") or {}).get("blockTime"))
        if type(stamp) is not int:
            continue
        meta = raw.get("meta") or {}
        try:
            keys = _keys((raw.get("transaction") or {}).get("message") or {}, meta)
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if address not in keys:
            continue
        index = keys.index(address)
        pre = meta.get("preBalances") or []
        if index >= len(pre):
            continue
        slot = raw.get("slot")
        if type(slot) is not int:
            slot = 2**62
        signature = ((raw.get("transaction") or {}).get("signatures") or [None])[0] or ""
        key = (stamp, 0 if pre[index] == 0 else 1, slot, signature)
        if oldest is None or key < oldest[0]:
            oldest = (key, stamp, pre[index])
    if oldest is None:
        return None, None
    return oldest[1], oldest[2]


def mints_sold_without_acquisition(records, address):
    """Mints sold in-history with no prior in-history acquisition (unknown basis)."""
    from scanner.mass_search.bundle_detect import _owned_token_deltas, _sale_mints, _unwrap

    acquired = set()
    unknown = set()
    rows = []
    for record in records or []:
        raw = _unwrap(record)
        if not isinstance(raw, dict) or (raw.get("meta") or {}).get("err") is not None:
            continue
        stamp = raw.get("blockTime") or raw.get("timestamp") or ((raw.get("transaction") or {}).get("blockTime"))
        if type(stamp) is not int:
            continue
        slot = raw.get("slot") if type(raw.get("slot")) is int else 0
        signature = ((raw.get("transaction") or {}).get("signatures") or [None])[0] or ""
        try:
            keys = _keys((raw.get("transaction") or {}).get("message") or {}, raw.get("meta") or {})
        except (ValueError, TypeError, KeyError, IndexError):
            keys = []
        rows.append((stamp, slot, signature, raw, keys))
    rows.sort()
    for _stamp, _slot, _signature, raw, keys in rows:
        deltas = _owned_token_deltas(raw, address)
        for mint, qty in deltas.items():
            if qty > 0:
                acquired.add(mint)
        for mint in _sale_mints(raw, keys, address, deltas):
            if mint not in acquired:
                unknown.add(mint)
    return unknown


def assess_history_completeness(records, leftover_token, *, address, cap_truncated=False, page_cap_hit=False):
    """Complete only when pagination is exhausted or first-funding is proven.

    Oldest native preBalance 0 alone is not enough: wallets drain to 0 SOL
    while still holding tokens that are absent from that tx's token
    pre-balances. A later sale of a mint with no in-history acquisition is
    unknown basis and is never complete.
    """
    stamp, pre = oldest_native_prebalance(records, address)
    created_in_range = pre == 0
    leftover = bool(leftover_token)
    unknown = mints_sold_without_acquisition(records, address)
    base = {
        "wallet_created_in_range": created_in_range,
        "leftover_pagination_token": leftover,
        "oldest_block_time": stamp,
        "oldest_native_prebalance": pre,
        "unknown_basis_mints": sorted(unknown),
    }
    if cap_truncated:
        return {**base, "history_complete": False, "history_complete_reason": "cap_truncated"}
    if page_cap_hit and leftover:
        return {**base, "history_complete": False, "history_complete_reason": "page_cap_with_leftover_token"}
    if unknown:
        return {**base, "history_complete": False, "history_complete_reason": "unknown_basis_sale"}
    if leftover and not created_in_range:
        return {
            **base,
            "history_complete": False,
            "history_complete_reason": "pagination_token_remaining_earlier_history",
        }
    if created_in_range:
        return {**base, "history_complete": True, "history_complete_reason": "wallet_created_in_range"}
    if not leftover:
        return {**base, "history_complete": True, "history_complete_reason": "no_leftover_pagination_token"}
    return {**base, "history_complete": False, "history_complete_reason": "unproven"}


def seed_counterparties_from_records(records, address):
    """Cheap solo-trader seeds: non-infra counterparties that did not co-sign.

    Exchange hot-wallet funders (single signer, no co-sign) and peer
    withdraw destinations are candidates. Service co-signers, DEX pools,
    fee vaults and token accounts are skipped.
    """
    from scanner.mass_search.bundle_detect import (
        INFRA,
        _has_reviewed_swap,
        _native_counterparties,
        _signers,
        _token_account_keys,
        _unwrap,
    )
    from scanner.investigation import REVIEWED_OUTER_VENUES

    found = []
    seen = set()
    for record in records or []:
        raw = _unwrap(record)
        if not isinstance(raw, dict) or (raw.get("meta") or {}).get("err") is not None:
            continue
        try:
            keys = _keys((raw.get("transaction") or {}).get("message") or {}, raw.get("meta") or {})
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if not keys:
            continue
        if _has_reviewed_swap(raw, keys):
            continue
        if any(key in REVIEWED_OUTER_VENUES for key in keys):
            continue
        token_accounts = _token_account_keys(raw, keys)
        signers = _signers(raw, keys)
        for party, kind, amount in _native_counterparties(raw, keys, address):
            if party in INFRA or party in seen or party in token_accounts:
                continue
            if party in REVIEWED_OUTER_VENUES:
                continue
            if party in signers and address in signers:
                continue
            seen.add(party)
            found.append({
                "address": party,
                "role": kind,
                "lamports": str(amount),
                "source_wallet": address,
            })
    return found


def discovery_identity(config):
    """Distinct Phase-1 identity: source|window|sort|tokens."""
    sources = config.get("seed_sources") or [config.get("discovery_source") or BIRDEYE_DISCOVERY_GAINERS]
    source = ",".join(sources)
    window = config.get("birdeye_window") or BIRDEYE_DEFAULT_WINDOW
    sort = config.get("birdeye_sort") or BIRDEYE_DEFAULT_SORT
    tokens = ",".join(config.get("birdeye_tokens") or [])
    return f"{source}|{window}|{sort}|{tokens}"


def _merge_discovery_wallets(config, state, addresses, *, source=None, extras=None):
    """Union newly discovered addresses into the run wallet pool."""
    existing = list(state.get("wallets") or config.get("wallets") or [])
    seen = set(existing)
    extras = extras or {}
    for address in addresses or []:
        if address and address not in seen:
            existing.append(address)
            seen.add(address)
        if address and source:
            record_seed_metadata(state, address, source, extras.get(address))
    config["wallets"] = existing
    state["wallets"] = existing
    return existing


def _seed_window_days(config):
    text = str(config.get("birdeye_window") or "")
    if text.endswith("d") and text[:-1].isdigit():
        return max(int(text[:-1]), 1)
    if text in ("1W", "7d"):
        return 7
    if text in ("yesterday", "today"):
        return 1
    return max(int(config.get("window_days") or 30), 1)


def apply_cheap_prescreen_phase1(config, state):
    """Drop high-rate seeds using Phase 1 provider rows. No extra calls."""
    if not cheap_prescreen_enabled(config.get("seed_sources")):
        return []
    window = _seed_window_days(config)
    dropped = []
    kept = []
    for address in list(state.get("wallets") or config.get("wallets") or []):
        meta = (state.get("seed_metadata") or {}).get(address) or {}
        decision = cheap_prescreen_decision({
            "trade_count": meta.get("trade_count"),
            "window_days": window,
            "trades_per_day": meta.get("trades_per_day"),
        })
        if decision["dropped"]:
            dropped.append(address)
            state.setdefault("cheap_prescreen", {})[address] = decision
            record_seed_metadata(state, address, SEED_PRESCREEN_FILTER, decision)
        else:
            kept.append(address)
    config["wallets"] = kept
    state["wallets"] = kept
    state["cheap_prescreen_dropped"] = dropped
    return dropped


def wallet_triage_requests(state, address, *, triage=False):
    """Requests already counted against --per-wallet-cap from phase 2."""
    row = ((state or {}).get("phase2") or {}).get(address) or {}
    if row.get("requests") is not None:
        return int(row["requests"])
    if row.get("triage") or triage:
        return TRIAGE_SAMPLES
    return 0


def wallet_phase3_requests(state, address):
    cursor = ((state or {}).get("phase3") or {}).get(address) or {}
    return int(cursor.get("requests") or cursor.get("pages") or 0)


def phase3_remaining_budget(config, state, address, *, triage=False):
    """Remaining Helius requests this wallet may spend in phase 3."""
    cap = config.get("per_wallet_cap")
    if cap is None:
        return None
    used = wallet_phase3_requests(state, address) + wallet_triage_requests(state, address, triage=triage)
    return max(0, int(cap) - used)


def phase3_planned_pages(config, state, address, estimated_pages, *, triage=False):
    already = wallet_phase3_requests(state, address)
    needed = max(0, int(estimated_pages) - already)
    remaining = phase3_remaining_budget(config, state, address, triage=triage)
    if remaining is None:
        return needed
    return min(needed, remaining)


def phase1_produced_seed_count(state):
    wallets = list((state or {}).get("wallets") or [])
    if wallets:
        return len(wallets)
    count = 0
    for key, row in ((state or {}).get("discoveries") or {}).items():
        if not isinstance(row, dict):
            continue
        if key.endswith("|helius_triage"):
            continue
        count += int(row.get("count") or len(row.get("addresses") or []) or 0)
    return count


def discovered_seed_pool(config, state):
    """Resume pool: explicit --wallets, else this run's phase-1 discoveries."""
    if config.get("wallets_supplied") and config.get("wallets"):
        return list(config.get("wallets") or [])
    state_wallets = [addr for addr in ((state or {}).get("wallets") or []) if addr]
    if state_wallets:
        return state_wallets
    combined = []
    seen = set()
    for key, row in ((state or {}).get("discoveries") or {}).items():
        if not isinstance(row, dict):
            continue
        for addr in row.get("addresses") or []:
            if addr and addr not in seen:
                seen.add(addr)
                combined.append(addr)
    return combined


def estimate_phase3_pages(config, state=None):
    """Pages per wallet from pre-screen tx density (minimum 2)."""
    state = state or {}
    window_days = max(int(config.get("window_days") or 30), 1)
    earlier = max(int((config.get("bounds") or {}).get("earlier_history_days") or config.get("earlier_history_days") or 60), 0)
    history_days = window_days + earlier
    estimates = {}
    for address in phase3_wallets(config, state):
        row = ((state.get("phase2") or {}).get(address) or {})
        in_window = int(row.get("in_window_tx_count") or 0)
        if in_window <= 0:
            estimates[address] = 2
            continue
        projected = (Decimal(in_window) / Decimal(window_days)) * Decimal(history_days)
        pages = int(math.ceil(projected / Decimal(GTA_MAX_LIMIT)))
        if in_window >= GTA_MAX_LIMIT:
            pages = max(pages, 2)
        estimates[address] = max(pages, 2)
    return estimates


def prescreen_rank_score(row):
    """(supported-venue share by value) x (has known-basis buys) x (not bundle/bot/pair)."""
    share = Decimal(str(row.get("supported_venue_value_share") or "0"))
    has_buys = Decimal("1") if row.get("has_known_basis_buys") else Decimal("0")
    dirty = row.get("bundle") or row.get("bot") or row.get("controlled_pair")
    clean = Decimal("0") if dirty else Decimal("1")
    return (share * has_buys * clean).quantize(Decimal("0.0001"))


def phase4_targets(config, state=None):
    """Phase 4 wallets: explicit --wallets, else phase-3 done wallets.

    An empty selection is not a completed Phase 4.
    """
    state = state or {}
    if config.get("wallets_supplied") and config.get("wallets"):
        return list(config.get("wallets") or [])
    done3 = [
        addr
        for addr, row in (state.get("phase3") or {}).items()
        if isinstance(row, dict) and row.get("done") and addr
    ]
    if done3:
        return done3
    if config.get("wallets"):
        return list(config.get("wallets") or [])
    return []


def phase3_wallets(config, state=None):
    """Phase-3 targets: phase-2 survivors only. Never fall back to the full pool."""
    state = state or {}
    phase2 = state.get("phase2") or {}
    kept_rows = [
        row
        for row in phase2.values()
        if isinstance(row, dict) and row.get("address") and not row.get("dropped")
    ]
    kept_rows.sort(key=lambda row: (
        -float(row.get("coverability_rank_key") or 0),
        row.get("address") or "",
    ))
    kept = [row["address"] for row in kept_rows]
    if phase2:
        if config.get("wallets_supplied"):
            supplied = list(config.get("wallets") or [])
            kept_set = set(kept)
            return [addr for addr in supplied if addr in kept_set]
        return kept
    if config.get("wallets_supplied"):
        return list(config.get("wallets") or [])
    if kept:
        return kept
    return list(config.get("wallets") or [])


def plan_request_counts(config, state=None):
    wallets = list(config["wallets"])
    phases = set(config["phases"])
    discovery = bool(config.get("discovery"))
    sources = list(config.get("seed_sources") or [config.get("discovery_source") or BIRDEYE_DISCOVERY_GAINERS])
    source = primary_seed_source(sources)
    tokens = list(config.get("birdeye_tokens") or [])
    discovery_mode = config.get("discovery_source")
    seed_plan = estimate_seed_plan(
        sources,
        tokens=tokens,
        discovery=discovery or (1 in phases and not wallets),
        wallets=wallets,
        nansen_enabled=bool((config.get("nansen_enabled") if "nansen_enabled" in config else os.environ.get(NANSEN_KEY_ENV))),
        birdeye_top_mode=discovery_mode if discovery_mode == BIRDEYE_DISCOVERY_TOP_TRADERS else BIRDEYE_DISCOVERY_GAINERS,
        nansen_profile_cap=config.get("nansen_profile_cap"),
        nansen_request_cap=(config.get("caps") or {}).get("nansen_requests"),
        nansen_unit_cap=(config.get("caps") or {}).get("nansen_units"),
    )
    if 1 in phases and (discovery or not wallets):
        birdeye_requests = seed_plan["totals"]["birdeye_requests"]
        birdeye_units = seed_plan["totals"]["birdeye_units"]
        nansen_requests = seed_plan["totals"].get("nansen_requests") or 0
        nansen_units = seed_plan["totals"].get("nansen_units") or 0
    else:
        birdeye_requests = 0
        birdeye_units = 0
        nansen_requests = 0
        nansen_units = 0
    if 1 in phases and wallets and not discovery:
        birdeye_requests = 0
        birdeye_units = 0
        nansen_requests = 0
        nansen_units = 0
    n = len(wallets)
    n3 = len(phase3_wallets(config, state)) if 3 in phases else 0
    triage = helius_triage_enabled(sources)
    helius_phase2 = ((3 * n) if triage else (2 * n)) if 2 in phases else 0
    page_estimates = estimate_phase3_pages(config, state) if 3 in phases else {}
    per_wallet_cap = config.get("per_wallet_cap")
    if 3 in phases:
        page_estimates = {
            address: phase3_planned_pages(config, state, address, int(pages), triage=triage)
            for address, pages in page_estimates.items()
        }
    helius_phase3 = sum(page_estimates.values()) if 3 in phases else 0
    if 3 in phases and not page_estimates and n3:
        remaining = phase3_remaining_budget(config, state, None, triage=triage)
        helius_phase3 = min(2, remaining if remaining is not None else 2) * n3
    helius_units = 0
    if 2 in phases:
        if triage:
            helius_units += n * 3 * FULL_100_UNITS
        else:
            helius_units += n * (SIG_ONLY_UNITS + FULL_100_UNITS)
    if 3 in phases:
        helius_units += helius_phase3 * FULL_1000_UNITS
    return {
        "kind": "live-e2e-request-plan-v1",
        "dry_run": True,
        "phases": list(config["phases"]),
        "wallet_count": n,
        "discovery_source": source,
        "seed_sources": sources,
        "seed_plan": seed_plan,
        "phase3_page_estimates": page_estimates,
        "per_wallet_cap": per_wallet_cap,
        "birdeye_cu_docs": BIRDEYE_CU_DOCS,
        "seed_cu_docs": SEED_CU_DOCS,
        "per_phase": {
            "1": {
                "provider": "birdeye+nansen",
                "requests": birdeye_requests,
                "units": birdeye_units,
                "billing_unit": "birdeye_compute_unit",
                "nansen_requests": nansen_requests,
                "nansen_units": nansen_units,
                "note": (
                    "0 when a wallet list is supplied without --discovery. "
                    f"{source}: see seed_plan.per_source. A seed is never evidence."
                ),
                "per_source": seed_plan.get("per_source") or {},
            },
            "2": {
                "provider": "helius",
                "requests": helius_phase2,
                "units": (
                    (n * 3 * FULL_100_UNITS) if triage else (n * (SIG_ONLY_UNITS + FULL_100_UNITS))
                ) if 2 in phases else 0,
                "billing_unit": "helius_credit",
                "note": (
                    "3 bounded full samples (earliest/recent/older-month, limit 100, 10 CU each) per wallet"
                    if triage else
                    "1 signatures-only (limit 1000, 10 CU) + 1 full sample (limit 100, 10 CU) per wallet"
                ),
            },
            "3": {
                "provider": "helius",
                "requests": helius_phase3,
                "units": helius_phase3 * FULL_1000_UNITS if 3 in phases else 0,
                "billing_unit": "helius_credit",
                "note": (
                    "Planner estimates pages per wallet from pre-screen tx "
                    "density (in-window count / window days × history days / 1000), "
                    "minimum 2, then clips each wallet to the remaining "
                    "--per-wallet-cap after triage requests already counted "
                    "against that same cap (typically 3) and pages already fetched. "
                    "A leftover paginationToken is not the end unless first-funding "
                    "is proven. Units are the documented worst case "
                    "(100 credits / 1000 txs) per estimated page."
                ),
            },
            "4": {"provider": None, "requests": 0, "units": 0, "note": "offline only"},
        },
        "totals": {
            "birdeye_requests": birdeye_requests,
            "birdeye_units": birdeye_units,
            "helius_requests": helius_phase2 + helius_phase3,
            "helius_units": helius_units,
            "nansen_requests": nansen_requests,
            "nansen_units": nansen_units,
            "leaderboard_requests": seed_plan["totals"].get("leaderboard_requests") or 0,
            "leaderboard_units": seed_plan["totals"].get("leaderboard_units") or 0,
        },
        "caps": config["caps"],
        "PRODUCT_READY": False,
    }


def within_caps(plan, caps):
    totals = plan["totals"]
    return (
        totals["birdeye_requests"] <= caps["birdeye_requests"]
        and totals["birdeye_units"] <= caps["birdeye_units"]
        and totals["helius_requests"] <= caps["helius_requests"]
        and totals["helius_units"] <= caps["helius_units"]
        and int(totals.get("nansen_requests") or 0) <= int(caps.get("nansen_requests") or 0)
        and int(totals.get("nansen_units") or 0) <= int(caps.get("nansen_units") or 0)
    )


class RecorderTransport:
    """Records planned provider calls. Never opens a socket."""

    def __init__(self):
        self.calls = []
        self.fail_at = {}
        self._path_counts = {}

    def _maybe_fail(self, path):
        count = self._path_counts.get(path, 0) + 1
        self._path_counts[path] = count
        spec = (self.fail_at or {}).get(path)
        if not spec:
            return
        after = int(spec.get("after") or 1)
        times = spec.get("times")
        if count < after:
            return
        if times is not None and count >= after + int(times):
            return
        error = spec.get("error")
        if error is None:
            error = SourceError("RATE_LIMITED", "Birdeye rate limit", http_status=429, retryable=True)
        raise error

    async def birdeye(self, method, path, params):
        units = BIRDEYE_UNITS
        if path == BIRDEYE_TOP_TRADERS_PATH:
            units = BIRDEYE_TOP_TRADERS_UNITS
        elif path == BIRDEYE_TOKEN_LIST_PATH:
            units = BIRDEYE_TOKEN_LIST_UNITS
        elif path == BIRDEYE_TOKEN_TXS_PATH:
            units = BIRDEYE_TOKEN_TXS_UNITS
        elif path == BIRDEYE_TOKEN_TX_SEEK_PATH:
            units = BIRDEYE_TOKEN_TX_SEEK_UNITS
        elif path == BIRDEYE_FIRST_BUYERS_PATH:
            units = BIRDEYE_FIRST_BUYERS_UNITS
        fixture = (getattr(self, "fixtures", None) or {}).get(path)
        if fixture is not None:
            body = fixture if isinstance(fixture, dict) else {}
            raw = json.dumps(body, separators=(",", ":")).encode() if isinstance(fixture, dict) else bytes(fixture)
            if not isinstance(fixture, dict):
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    body = {"data": {"items": []}}
        else:
            body = {"data": {"items": []}}
            raw = b'{"data":{"items":[]}}'
        self.calls.append({
            "provider": "birdeye",
            "method": method,
            "path": path,
            "params": dict(params or {}),
            "units": units,
        })
        self._maybe_fail(path)
        return {
            "status": 200,
            "fetched_at": utc_now(),
            "body": body,
            "raw_bytes": raw,
        }

    async def helius(self, address, *, options, page_index=0):
        details = (options or {}).get("transactionDetails")
        limit = int((options or {}).get("limit") or 0)
        units = documented_units(details, limit)
        self.calls.append({
            "provider": "helius",
            "address": address,
            "page_index": page_index,
            "options": {k: v for k, v in (options or {}).items() if k != "paginationToken"},
            "units": units,
        })
        raw = b'{"jsonrpc":"2.0","result":{"data":[],"paginationToken":null}}'
        return {
            "records": [],
            "pagination_token": None,
            "http_status": 200,
            "raw_bytes": raw,
            "evidence_sha256": _sha256_bytes(raw),
            "units": units,
            "external_requests": 1,
        }

    async def nansen(self, method, path, body=None):
        if path not in ALLOWED_NANSEN_PATHS:
            raise SourceError("UNAUTHORIZED", "Nansen path is not allowlisted")
        validate_nansen_body(nansen_schema_kind_for_path(path), body or {})
        units = NANSEN_LEADERBOARD_UNITS if path == NANSEN_LEADERBOARD_PATH else NANSEN_PROFILER_UNITS
        fixture = (getattr(self, "fixtures", None) or {}).get(path)
        if fixture is not None:
            payload = fixture if isinstance(fixture, dict) else {}
            raw = json.dumps(payload, separators=(",", ":")).encode() if isinstance(fixture, dict) else bytes(fixture)
            if not isinstance(fixture, dict):
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    payload = {"data": []}
        else:
            payload = {"data": []}
            raw = b'{"data":[]}'
        self.calls.append({
            "provider": "nansen",
            "method": method,
            "path": path,
            "body": dict(body or {}),
            "units": units,
        })
        return {
            "status": 200,
            "fetched_at": utc_now(),
            "body": payload,
            "raw_bytes": raw,
            "units": units,
        }


def require_durable_store(path):
    store_path = Path(path)
    if store_path.exists() and store_path.is_file():
        raise LiveE2EError("store path must be a directory")
    store_path.mkdir(parents=True, exist_ok=True)
    store = Store(store_path)
    if not hasattr(store, "reserve") or store.db is None:
        raise LiveE2EError("durable store required")
    return store


def _empty_state(config):
    return {
        "kind": "live-e2e-run-state-v1",
        "authorization_id": config.get("authorization_id"),
        "status": "started",
        "phases_done": [],
        "wallets": list(config.get("wallets") or []),
        "bounds": dict(config.get("bounds") or {}),
        "phase2": {},
        "phase3": {},
        "receipts": {},
        "spend": empty_spend(),
        "phase_spend": empty_phase_spend(),
        "PRODUCT_READY": False,
    }


def load_or_create_state(output_dir, config, *, resume):
    path = Path(output_dir) / STATE_NAME
    if path.is_file():
        state = _read_json(path)
        if state.get("status") == "completed" and not resume:
            raise LiveE2EError("duplicate run: output already completed; pass --resume to reopen")
        if not resume and state.get("status") not in (None, "started"):
            raise LiveE2EError("existing run state present; pass --resume to continue")
        if resume:
            return state
        raise LiveE2EError("existing run state present; pass --resume to continue")
    return _empty_state(config)


def save_state(output_dir, state):
    _write_json(Path(output_dir) / STATE_NAME, state)
    return state


def reconcile_state_spend(store, state):
    ledger_spend, ledger_phase = spend_from_ledger(store)
    state["spend"] = merge_spend(state.get("spend"), ledger_spend)
    merged_phase = empty_phase_spend()
    existing = state.get("phase_spend") or {}
    for phase in merged_phase:
        merged_phase[phase] = merge_spend(existing.get(phase), ledger_phase.get(phase))
    state["phase_spend"] = merged_phase
    return state


def remaining_caps(config, spend):
    caps = config["caps"]
    spend = spend or {}
    return {
        "birdeye_requests": caps["birdeye_requests"] - int(spend.get("birdeye_requests") or 0),
        "birdeye_units": caps["birdeye_units"] - int(spend.get("birdeye_units") or 0),
        "helius_requests": caps["helius_requests"] - int(spend.get("helius_requests") or 0),
        "helius_units": caps["helius_units"] - int(spend.get("helius_units") or 0),
        "nansen_requests": int(caps.get("nansen_requests") or 0) - int(spend.get("nansen_requests") or 0),
        "nansen_units": int(caps.get("nansen_units") or 0) - int(spend.get("nansen_units") or 0),
    }


def hard_stop_if_needed(config, spend, *, provider, units, phase=None, phase_spend=None):
    left = remaining_caps(config, spend)
    if provider == "birdeye":
        if left["birdeye_requests"] < 1 or left["birdeye_units"] < units:
            raise SourceError("CAP_EXCEEDED", "Birdeye cap reached; hard stop")
    elif provider == "nansen":
        if left["nansen_requests"] < 1 or left["nansen_units"] < units:
            raise SourceError("CAP_EXCEEDED", "Nansen cap reached; hard stop")
    else:
        if left["helius_requests"] < 1 or left["helius_units"] < units:
            raise SourceError("CAP_EXCEEDED", "Helius cap reached; hard stop")
    if phase is None:
        return
    phase_caps = (config.get("caps") or {}).get("phase_caps") or {}
    limits = phase_caps.get(str(phase)) or {}
    used = (phase_spend or {}).get(str(phase)) or empty_spend()
    req_key = f"{provider}_requests"
    unit_key = f"{provider}_units"
    if limits.get(req_key) is not None and used.get(req_key, 0) + 1 > int(limits[req_key]):
        raise SourceError("CAP_EXCEEDED", f"Phase {phase} {provider} request cap reached; hard stop")
    if limits.get(unit_key) is not None and used.get(unit_key, 0) + units > int(limits[unit_key]):
        raise SourceError("CAP_EXCEEDED", f"Phase {phase} {provider} credit cap reached; hard stop")
    for key in ("leaderboard_requests", "leaderboard_units"):
        if limits.get(key) is not None and int(limits[key]) <= HARD_CEILINGS.get(key, 0):
            if int(limits[key]) <= 0 and provider == "leaderboard":
                raise SourceError("CAP_EXCEEDED", f"Phase {phase} {key} cap reached; hard stop")


def _account_spend(state, *, provider, units, phase):
    state.setdefault("spend", empty_spend())
    state.setdefault("phase_spend", empty_phase_spend())
    state["spend"].setdefault(f"{provider}_requests", 0)
    state["spend"].setdefault(f"{provider}_units", 0)
    state["spend"][f"{provider}_requests"] += 1
    state["spend"][f"{provider}_units"] += units
    bucket = state["phase_spend"].setdefault(str(phase), empty_spend())
    bucket.setdefault(f"{provider}_requests", 0)
    bucket.setdefault(f"{provider}_units", 0)
    bucket[f"{provider}_requests"] += 1
    bucket[f"{provider}_units"] += units


def _account_source_spend(state, source, *, provider, units):
    if not source:
        return
    state.setdefault("source_spend", {})
    bucket = state["source_spend"].setdefault(source, {"requests": 0, "units": 0, "provider": provider, "by_provider": {}})
    bucket["requests"] += 1
    bucket["units"] += units
    bucket["provider"] = provider
    by_provider = bucket.setdefault("by_provider", {})
    row = by_provider.setdefault(provider, {"requests": 0, "units": 0})
    row["requests"] += 1
    row["units"] += units


def _helius_min_interval():
    text = os.environ.get(HELIUS_MIN_INTERVAL_ENV)
    if text in (None, ""):
        return DEFAULT_HELIUS_MIN_INTERVAL
    try:
        value = float(text)
    except (TypeError, ValueError):
        return DEFAULT_HELIUS_MIN_INTERVAL
    return max(value, 0.0)


def _helius_backoff_seconds():
    text = os.environ.get(HELIUS_BACKOFF_ENV)
    if text in (None, ""):
        return DEFAULT_HELIUS_BACKOFF
    try:
        value = float(text)
    except (TypeError, ValueError):
        return DEFAULT_HELIUS_BACKOFF
    return max(value, 0.0)


def _birdeye_min_interval():
    text = os.environ.get(BIRDEYE_MIN_INTERVAL_ENV)
    if text in (None, ""):
        return DEFAULT_BIRDEYE_MIN_INTERVAL
    try:
        value = float(text)
    except (TypeError, ValueError):
        return DEFAULT_BIRDEYE_MIN_INTERVAL
    return max(value, 0.0)


def _birdeye_backoff_seconds():
    text = os.environ.get(BIRDEYE_BACKOFF_ENV)
    if text in (None, ""):
        return DEFAULT_BIRDEYE_BACKOFF
    try:
        value = float(text)
    except (TypeError, ValueError):
        return DEFAULT_BIRDEYE_BACKOFF
    return max(value, 0.0)


async def pace_birdeye_call():
    """Default 4s between Birdeye calls. Every live attempt is still receipted."""
    global _BIRDEYE_LAST_CALL
    interval = _birdeye_min_interval()
    if interval <= 0:
        return interval
    lock = _BIRDEYE_PACE_LOCK
    if lock is None:
        now = time.monotonic()
        wait = interval - (now - _BIRDEYE_LAST_CALL)
        if wait > 0:
            await asyncio.sleep(wait)
        _BIRDEYE_LAST_CALL = time.monotonic()
        return interval
    async with lock:
        now = time.monotonic()
        wait = interval - (now - _BIRDEYE_LAST_CALL)
        if wait > 0:
            await asyncio.sleep(wait)
        _BIRDEYE_LAST_CALL = time.monotonic()
    return interval


async def pace_helius_call():
    """Default 2 rps (0.5s). Every live attempt is still receipted by the caller."""
    global _HELIUS_LAST_CALL
    interval = _helius_min_interval()
    if interval <= 0:
        return interval
    lock = _HELIUS_PACE_LOCK
    if lock is None:
        now = time.monotonic()
        wait = interval - (now - _HELIUS_LAST_CALL)
        if wait > 0:
            await asyncio.sleep(wait)
        _HELIUS_LAST_CALL = time.monotonic()
        return interval
    async with lock:
        now = time.monotonic()
        wait = interval - (now - _HELIUS_LAST_CALL)
        if wait > 0:
            await asyncio.sleep(wait)
        _HELIUS_LAST_CALL = time.monotonic()
    return interval


def birdeye_failure_state(status, body):
    """A 429 or success:false body is a failed request, never an empty success."""
    if status in (401, 403):
        return "ENTITLEMENT_BLOCKED", "Birdeye rejected the key or plan", False
    if status == 429:
        return "RATE_LIMITED", "Birdeye rate limit", True
    if isinstance(body, dict) and body.get("success") is False:
        message = str(body.get("message") or "Birdeye success=false")
        lowered = message.lower()
        if "too many" in lowered or "rate" in lowered:
            return "RATE_LIMITED", message, True
        if (
            "permission" in lowered
            or "lacks sufficient" in lowered
            or "not entitled" in lowered
            or "not authorized" in lowered
            or "access this resource" in lowered
        ):
            return "ENTITLEMENT_BLOCKED", message, False
        return "UNSUPPORTED_SCHEMA", message, False
    if status != 200:
        return "UNSUPPORTED_SCHEMA", "Unexpected Birdeye response", False
    return None


async def _live_birdeye(method, path, params):
    key = os.environ.get(BIRDEYE_KEY_ENV)
    if not key:
        raise SourceError("UNAUTHORIZED", "BIRDEYE_API_KEY is not present in this runtime")
    if path not in ALLOWED_BIRDEYE_PATHS:
        raise SourceError("UNAUTHORIZED", "Birdeye path is not allowlisted")
    import httpx

    await pace_birdeye_call()
    headers = {"X-API-KEY": key, "x-chain": "solana", "accept": "application/json"}
    async with httpx.AsyncClient(
        base_url=f"https://{ALLOWED_BIRDEYE_HOST}",
        follow_redirects=False,
        timeout=httpx.Timeout(25, connect=10),
    ) as client:
        response = await client.request(method, path, params=params, headers=headers)
    raw = response.content
    try:
        body = response.json()
    except ValueError:
        body = None
    status = response.status_code
    failure = birdeye_failure_state(status, body)
    if failure:
        state, message, retryable = failure
        if retryable:
            backoff = _birdeye_backoff_seconds()
            if backoff:
                await asyncio.sleep(backoff)
        raise SourceError(state, message, http_status=status, retryable=retryable)
    return {
        "status": status,
        "body": body,
        "fetched_at": utc_now(),
        "raw_bytes": raw,
    }


def nansen_path_allowed(path):
    if path == NANSEN_LABELS_PATH or "premium_labels" in str(path) or "labels" in str(path).split("/")[-1]:
        raise SourceError("UNAUTHORIZED", "Nansen labels/premium_labels are forbidden (100 credits)")
    if path not in ALLOWED_NANSEN_PATHS:
        raise SourceError("UNAUTHORIZED", "Nansen path is not allowlisted")
    return True


def _validate_nansen_request(path, body):
    nansen_path_allowed(path)
    if path == NANSEN_FIRST_FUNDER_PATH and not nansen_first_funder_supported():
        raise SourceError("UNAUTHORIZED", "Nansen first-funder is EVM-only; not called for Solana")
    validate_nansen_body(nansen_schema_kind_for_path(path), body or {})
    return True


def _nansen_error_from_response(status, payload, billing):
    envelope = redact_nansen_error_body(payload)
    extras = {"billing": billing, "error_body": envelope}
    if status in (401, 403):
        message = envelope.get("message") or "Nansen rejected the key or plan"
        return SourceError("ENTITLEMENT_BLOCKED", message, http_status=status, extras=extras)
    if status == 402:
        message = envelope.get("message") or "Nansen payment required"
        return SourceError("ENTITLEMENT_BLOCKED", message, http_status=status, extras=extras)
    if status == 429:
        return SourceError("RATE_LIMITED", envelope.get("message") or "Nansen rate limit", http_status=status, retryable=False, extras=extras)
    message = envelope.get("message") or "Unexpected Nansen response"
    return SourceError("UNSUPPORTED_SCHEMA", message, http_status=status, extras=extras)


def _put_receipt(config, store, grant, key, payload):
    """Write a grant-ledger receipt. Dry-run never touches the real ledger."""
    if config.get("dry_run"):
        return None
    return put_receipt(store, grant, key, payload)


def _retained_seed_pages(state, source):
    progress = ((state or {}).get("seed_source_progress") or {}).get(source) or {}
    if int(progress.get("paid_pages") or 0) > 0:
        return True
    discoveries = (state or {}).get("discoveries") or {}
    for key, row in discoveries.items():
        if isinstance(row, dict) and str(key).endswith(f"|{source}") and (
            row.get("addresses") or int(row.get("paid_pages") or 0)
        ):
            return True
    return False


def _seed_source_stopped(state, source):
    row = ((state or {}).get("seed_source_failures") or {}).get(source) or {}
    if _retained_seed_pages(state, source) and not row.get("exhausted"):
        return False
    return bool(row.get("stop_after_failure") or row.get("fatal"))


def _record_seed_source_failure(state, source, error, *, retained_pages=0):
    code = getattr(error, "state", None) or "FAILED"
    extras = getattr(error, "extras", None) or {}
    retained = int(retained_pages or 0) > 0 or _retained_seed_pages(state, source)
    stop = code in FATAL_SEED_STATES and not (code == "RATE_LIMITED" and retained)
    state.setdefault("seed_source_failures", {})[source] = {
        "state": code,
        "message": str(error),
        "fatal": code in FATAL_SEED_STATES and not retained,
        "stop_after_failure": stop,
        "retained_pages": int(retained_pages or 0) or int(
            (((state or {}).get("seed_source_progress") or {}).get(source) or {}).get("paid_pages") or 0
        ),
        "billing": extras.get("billing"),
        "error_body": extras.get("error_body"),
    }
    return state["seed_source_failures"][source]


def _save_seed_raw_parts(config, identity, source, raw_parts):
    raw = b"\n".join(part for part in raw_parts if part) if raw_parts else b"{}"
    if source == SEED_NANSEN:
        stem = "nansen"
    elif source == SEED_TOKEN_INTERSECT:
        stem = "token-intersect"
    else:
        stem = "birdeye"
    digest = _save_raw(
        config["output_dir"],
        f"raw/phase1/{stem}-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]}.bin",
        raw,
    )
    _save_raw(config["output_dir"], f"raw/phase1/{stem}.bin", raw)
    return digest


async def _live_nansen(method, path, body=None):
    """Official Nansen POST. Missing key disables the source; never a dummy call."""
    key = os.environ.get(NANSEN_KEY_ENV)
    if not key:
        raise SourceError("UNAUTHORIZED", "NANSEN_API_KEY is not present; nansen source is disabled")
    _validate_nansen_request(path, body)
    import httpx

    headers = {"apikey": key, "content-type": "application/json", "accept": "application/json"}
    async with httpx.AsyncClient(
        base_url=f"https://{NANSEN_HOST}",
        follow_redirects=False,
        timeout=httpx.Timeout(25, connect=10),
    ) as client:
        response = await client.request(method, path, json=body or {}, headers=headers)
    raw = response.content
    try:
        payload = response.json()
    except ValueError:
        payload = None
    billing = nansen_billing_from_headers(getattr(response, "headers", None))
    status = response.status_code
    if status != 200:
        raise _nansen_error_from_response(status, payload, billing)
    return {
        "status": status,
        "body": payload,
        "fetched_at": utc_now(),
        "raw_bytes": raw,
        "billing": billing,
    }


async def _live_helius(address, *, options, page_index=0):
    key = os.environ.get(HELIUS_KEY_ENV) or os.environ.get("HELIUS_KEY")
    if not key:
        raise SourceError("UNAUTHORIZED", "HELIUS_API_KEY is not present in this runtime")
    import httpx

    await pace_helius_call()
    payload = {"jsonrpc": "2.0", "id": page_index + 1, "method": HELIUS_METHOD, "params": [address, options]}
    headers = {"content-type": "application/json"}
    async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(40, connect=10)) as client:
        response = await client.post(HELIUS_ENDPOINT, params={"api-key": key}, json=payload, headers=headers)
    raw = response.content
    status = response.status_code
    if status in (401, 403):
        raise SourceError("ENTITLEMENT_BLOCKED", "Helius rejected the key or plan", http_status=status)
    if status == 429:
        backoff = _helius_backoff_seconds()
        if backoff:
            await asyncio.sleep(backoff)
        raise SourceError("RATE_LIMITED", "Helius rate limit", http_status=status, retryable=True)
    try:
        body = response.json()
    except ValueError as error:
        raise SourceError("UNSUPPORTED_SCHEMA", "Helius returned non-JSON", http_status=status) from error
    if status != 200 or not isinstance(body, dict) or body.get("error"):
        raise SourceError("UNSUPPORTED_SCHEMA", "Unexpected Helius response", http_status=status)
    result = body.get("result") or {}
    data = result.get("data") if isinstance(result, dict) else None
    if data is None and isinstance(result, list):
        data = result
    if not isinstance(data, list):
        data = []
    cleaned = sanitize_jsonrpc_body(body)
    return {
        "records": data,
        "pagination_token": result.get("paginationToken") if isinstance(result, dict) else None,
        "http_status": status,
        "raw_bytes": raw,
        "evidence_sha256": _sha256_bytes(raw),
        "cleaned": cleaned,
        "units": documented_units(options.get("transactionDetails"), int(options.get("limit") or 0)),
        "external_requests": 1,
    }


def _runtime_secrets():
    values = []
    for name in ("BIRDEYE_API_KEY", "HELIUS_API_KEY", "HELIUS_KEY", NANSEN_KEY_ENV):
        value = os.environ.get(name)
        if value and len(value) >= 8:
            values.append(value)
    return values


def _save_raw(output_dir, relative, raw_bytes):
    path = Path(output_dir) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    data = raw_bytes if isinstance(raw_bytes, (bytes, bytearray)) else bytes(raw_bytes)
    written, original_sha, scrubbed = scrub_bytes(data, extra_secrets=_runtime_secrets())
    path.write_bytes(written)
    written_sha = _sha256_bytes(written)
    if _sha256_bytes(path.read_bytes()) != written_sha:
        raise LiveE2EError("raw response checksum mismatch after write")
    _write_json(path.with_name(path.name + ".integrity.json"), integrity_record(
        original_sha256=original_sha,
        written_sha256=written_sha,
        scrubbed=scrubbed,
    ))
    return original_sha


def _next_receipt_key(store, base, *, explicit_retry):
    existing = load_receipt(store, base)
    if isinstance(existing, dict) and existing.get("state") == "consumed":
        return base, existing, True
    if receipt_is_spent(existing) and not explicit_retry:
        return base, existing, True
    if receipt_is_spent(existing) and explicit_retry:
        if existing.get("state") != "failed":
            # reserved/dispatched: adopt the saved page if present; do not
            # mint a retry key that would re-send a consumed success.
            return base, existing, True
        index = 1
        while receipt_is_spent(load_receipt(store, f"{base}:retry{index}")):
            index += 1
        return f"{base}:retry{index}", None, False
    return base, existing, False


def _receipt_sha_for_page(store, address, page_name, phase=None):
    """Ledger consumed-receipt sha256 for a saved page, if present."""
    if store is None or not hasattr(store, "list"):
        return None
    stem = Path(page_name).stem
    digits = stem[4:] if stem.startswith("page") else ""
    if not digits.isdigit():
        return None
    page_index = int(digits)
    try:
        from scanner.mass_search.live_e2e_ledger import RECEIPT_KIND
        rows = store.list(RECEIPT_KIND) or []
    except Exception:
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("wallet") != address:
            continue
        if phase is not None:
            row_phase = row.get("phase")
            if row_phase is None or int(row_phase) != int(phase):
                continue
        row_page = row.get("page")
        if row_page is None or int(row_page) != page_index:
            continue
        if row.get("state") != "consumed":
            continue
        sha = row.get("sha256")
        if isinstance(sha, str) and len(sha) == 64:
            return sha
    return None


def _verify_saved_page(path, relative=None, expected_sha=None, *, require_ledger_sha=False):
    """Require integrity receipt + result body. Sidecar rewrite alone cannot pass.

    The immutable ledger receipt sha256 is the source of truth. A tampered
    page that only rewrites written_sha256 (keeping original_sha256 equal to
    the ledger sha) is rejected when the file bytes no longer match.
    """
    path = Path(path)
    label = relative or str(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise SourceError("MISSING_CAPTURE", f"raw page missing: {label}; not covered")
    raw = path.read_bytes()
    file_sha = _sha256_bytes(raw)
    integrity_path = path.with_name(path.name + ".integrity.json")
    if not integrity_path.is_file():
        raise SourceError("MISSING_CAPTURE", f"integrity receipt missing: {label}; not covered")
    try:
        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceError("MISSING_CAPTURE", f"integrity receipt unreadable: {label}; not covered") from error
    written = integrity.get("written_sha256")
    original = integrity.get("original_sha256")
    scrubbed = bool(integrity.get("scrubbed"))
    if written != file_sha:
        raise SourceError("MISSING_CAPTURE", f"raw page hash mismatch: {label}; not covered")
    if require_ledger_sha and not expected_sha:
        raise SourceError(
            "MISSING_CAPTURE",
            f"no ledger receipt sha for {label}; refusing unreceipted page; not covered",
        )
    if expected_sha and file_sha != expected_sha:
        raise SourceError(
            "MISSING_CAPTURE",
            f"ledger receipt sha mismatch: {label}; file was rewritten; not covered",
        )
    if expected_sha and original and original != expected_sha:
        raise SourceError(
            "MISSING_CAPTURE",
            f"sidecar original_sha256 disagrees with ledger: {label}; not covered",
        )
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceError("MISSING_CAPTURE", f"raw page unreadable: {label}; not covered") from error
    if not isinstance(body, dict) or body.get("error") is not None or "result" not in body:
        raise SourceError("MISSING_CAPTURE", f"raw page is an error body: {label}; not covered")
    result = body.get("result")
    data = result.get("data") if isinstance(result, dict) else result
    if data is None:
        raise SourceError("MISSING_CAPTURE", f"raw page has no result records: {label}; not covered")
    if not isinstance(data, list):
        raise SourceError("MISSING_CAPTURE", f"raw page result is not a list: {label}; not covered")
    token = result.get("paginationToken") if isinstance(result, dict) else None
    return raw, data, token


def _import_paid_page(config, store, phase, address, page_index, expected_sha):
    """Copy a previously paid page into this output dir by verified ledger sha."""
    relative = f"raw/phase{phase}/{address}/page{page_index}.bin"
    dest = Path(config["output_dir"]) / relative
    roots = list(config.get("import_raw_dirs") or [])
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        candidates = []
        if root.is_file() and root.name.endswith(".bin"):
            candidates.append(root)
        else:
            candidates.extend(root.rglob(f"page{page_index}.bin"))
            named = root / "raw" / f"phase{phase}" / address / f"page{page_index}.bin"
            if named.is_file():
                candidates.append(named)
        for candidate in candidates:
            if not candidate.is_file():
                continue
            digest = _sha256_bytes(candidate.read_bytes())
            if expected_sha and digest != expected_sha:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(candidate.read_bytes())
            sidecar = candidate.with_name(candidate.name + ".integrity.json")
            if sidecar.is_file():
                dest.with_name(dest.name + ".integrity.json").write_bytes(sidecar.read_bytes())
            raw, records, token = _verify_saved_page(
                dest, relative, expected_sha=expected_sha, require_ledger_sha=True,
            )
            return raw, records, token
    guidance = (
        f"Paid page sha256={expected_sha} is not in this output dir "
        f"({relative}). Copy the page plus sidecar from the prior run, or pass "
        f"--import-raw-dir pointing at that raw tree. Refusing to re-send a "
        f"consumed receipt."
    )
    raise SourceError("MISSING_CAPTURE", guidance)


def _replay_saved_page(config, phase, address, page_index, units, store=None):
    relative = f"raw/phase{phase}/{address}/page{page_index}.bin"
    path = Path(config["output_dir"]) / relative
    expected_sha = _receipt_sha_for_page(store, address, f"page{page_index}.bin", phase=phase) if store is not None else None
    missing = not path.is_file() or path.stat().st_size == 0
    if missing and (expected_sha or config.get("import_raw_dirs")):
        raw, records, token = _import_paid_page(
            config, store, phase, address, page_index, expected_sha,
        )
    else:
        if missing:
            raise SourceError(
                "MISSING_CAPTURE",
                f"raw page missing: {relative}; not covered. A consumed receipt "
                f"exists or the file was never copied. Pass --import-raw-dir "
                f"<prior-raw-root> or copy the paid page plus sidecar. "
                f"Refusing to re-send.",
            )
        if store is not None:
            try:
                verify_receipt_chain(store)
            except ValueError as error:
                raise SourceError("MISSING_CAPTURE", f"receipt hash chain failed: {error}; not covered") from error
        raw, records, token = _verify_saved_page(
            path, relative, expected_sha=expected_sha, require_ledger_sha=True,
        )
    return {
        "records": records,
        "pagination_token": token,
        "http_status": 200,
        "raw_bytes": raw,
        "evidence_sha256": _sha256_bytes(raw),
        "units": units,
        "external_requests": 0,
        "replayed_from_receipt": True,
    }


async def _dispatch_helius(store, grant, config, state, transport, address, options, *, phase, page_index):
    entry = provider_entry(grant, "helius")
    units = documented_units(options.get("transactionDetails"), int(options.get("limit") or 0))
    cursor = (options or {}).get("paginationToken")
    base = request_identity("helius", wallet=address, phase=phase, page=page_index, cursor=cursor)
    key, existing, replay = _next_receipt_key(store, base, explicit_retry=config.get("explicit_retry"))
    if replay:
        reconcile_state_spend(store, state)
        save_state(config["output_dir"], state)
        return _replay_saved_page(config, phase, address, page_index, units, store=store)
    existing_page = Path(config["output_dir"]) / f"raw/phase{phase}/{address}/page{page_index}.bin"
    reserved_pending = isinstance(existing, dict) and existing.get("state") in ("reserved", "dispatched")
    if existing_page.is_file() and existing_page.stat().st_size > 0 and not reserved_pending:
        raise SourceError(
            "UNRECEIPTED_PAGE",
            f"refusing unreceipted page in output dir: raw/phase{phase}/{address}/page{page_index}.bin; not covered",
        )
    if existing_page.is_file() and existing_page.stat().st_size > 0 and reserved_pending:
        # Kill between save_raw and consumed receipt: adopt the reserved file.
        relative = f"raw/phase{phase}/{address}/page{page_index}.bin"
        try:
            verify_receipt_chain(store)
        except ValueError as error:
            raise SourceError("MISSING_CAPTURE", f"receipt hash chain failed: {error}; not covered") from error
        raw, records, token = _verify_saved_page(existing_page, relative, require_ledger_sha=False)
        adopted = {
            "records": records,
            "pagination_token": token,
            "http_status": 200,
            "raw_bytes": raw,
            "evidence_sha256": _sha256_bytes(raw),
            "units": units,
            "external_requests": 0,
            "replayed_from_receipt": True,
        }
        _put_receipt(config, store, grant, key, {
            "provider": "helius",
            "wallet": address,
            "phase": phase,
            "page": page_index,
            "cursor": cursor,
            "units": units,
            "state": "consumed",
            "sha256": adopted.get("evidence_sha256"),
            "adopted_existing_file": True,
        })
        _account_spend(state, provider="helius", units=units, phase=phase)
        save_state(config["output_dir"], state)
        return {**adopted, "adopted_existing_file": True}
    hard_stop_if_needed(
        config, state["spend"], provider="helius", units=units,
        phase=phase, phase_spend=state.get("phase_spend"),
    )
    if config.get("per_wallet_cap") is not None:
        used = int((state.get("phase3") or {}).get(address, {}).get("requests") or 0)
        used += int((state.get("phase2") or {}).get(address, {}).get("requests") or 0)
        if used >= int(config["per_wallet_cap"]):
            raise SourceError("WALLET_CAP", "Per-wallet request cap reached; continue with other wallets")
    reservation = None
    _put_receipt(config, store, grant, key, {
        "provider": "helius",
        "wallet": address,
        "phase": phase,
        "page": page_index,
        "cursor": cursor,
        "units": units,
        "state": "reserved",
        "response_id": uuid.uuid4().hex,
    })
    if not config.get("dry_run"):
        reservation = store.reserve("helius", HELIUS_METHOD, units, entry["cycle_start"], entry["max_units"])
        store.dispatch(reservation)
        _put_receipt(config, store, grant, key, {
            **(load_receipt(store, key) or {}),
            "state": "dispatched",
            "reservation_id": reservation,
            "units": units,
            "provider": "helius",
            "wallet": address,
            "phase": phase,
            "page": page_index,
            "cursor": cursor,
        })
    charged = False
    try:
        result = await transport(address, options=options, page_index=page_index)
        if reservation:
            store.settle(reservation, charge=True)
            charged = True
        raw = result.get("raw_bytes") or b""
        digest = _save_raw(
            config["output_dir"],
            f"raw/phase{phase}/{address}/page{page_index}.bin",
            raw,
        )
        _put_receipt(config, store, grant, key, {
            "provider": "helius",
            "wallet": address,
            "phase": phase,
            "page": page_index,
            "cursor": cursor,
            "units": units,
            "state": "consumed",
            "sha256": digest,
            "reservation_id": reservation,
        })
        _account_spend(state, provider="helius", units=units, phase=phase)
        save_state(config["output_dir"], state)
        return {**result, "evidence_sha256": digest, "units": units}
    except Exception:
        if reservation and not charged:
            try:
                store.settle(reservation, charge=True)
            except ValueError:
                pass
        _put_receipt(config, store, grant, key, {
            "provider": "helius",
            "wallet": address,
            "phase": phase,
            "page": page_index,
            "cursor": cursor,
            "units": units,
            "state": "failed",
            "reservation_id": reservation,
        })
        _account_spend(state, provider="helius", units=units, phase=phase)
        save_state(config["output_dir"], state)
        raise


async def _birdeye_seed_call(store, grant, config, state, recorder, *, path, params, operation, units, wallet, page, identity, source=None):
    """Ledgered Birdeye GET with bounded RATE_LIMITED retries inside caps."""
    last_error = None
    attempts = 1 + BIRDEYE_RATE_LIMIT_RETRIES
    for attempt in range(attempts):
        try:
            return await _birdeye_seed_call_once(
                store, grant, config, state, recorder,
                path=path, params=params, operation=operation, units=units,
                wallet=wallet, page=page, identity=identity, source=source,
                attempt=attempt,
            )
        except SourceError as error:
            last_error = error
            if getattr(error, "state", None) != "RATE_LIMITED":
                raise
            if attempt + 1 >= attempts:
                break
            left = remaining_caps(config, state["spend"])
            if left["birdeye_requests"] < 1 or left["birdeye_units"] < units:
                break
            backoff = _birdeye_backoff_seconds()
            if backoff:
                await asyncio.sleep(backoff * (attempt + 1))
    raise last_error


async def _birdeye_seed_call_once(store, grant, config, state, recorder, *, path, params, operation, units, wallet, page, identity, source=None, attempt=0):
    """Ledgered, grant-gated Birdeye GET. Dry-run uses the recorder only."""
    token_key = request_identity("birdeye", wallet=wallet, phase=1, page=page, cursor=f"{identity}:{path}:{wallet}:a{attempt}")
    hard_stop_if_needed(
        config, state["spend"], provider="birdeye", units=units,
        phase=1, phase_spend=state.get("phase_spend"),
    )
    reservation = None
    if config["dry_run"]:
        _put_receipt(config, store, grant, token_key, {
            "provider": "birdeye", "wallet": wallet, "phase": 1, "page": page,
            "units": units, "state": "planned", "discovery_identity": identity,
            "path": path,
        })
        response = await recorder.birdeye("GET", path, params)
        _account_spend(state, provider="birdeye", units=units, phase=1)
        _account_source_spend(state, source, provider="birdeye", units=units)
        return response
    if not grant.get("enabled"):
        raise SourceError("UNAUTHORIZED", grant.get("reason") or "grant disabled")
    if operation not in (provider_entry(grant, "birdeye").get("allowed_operations") or []):
        raise SourceError("UNAUTHORIZED", f"Authorization does not include Birdeye {operation}")
    try:
        entry = provider_entry(grant, "birdeye")
        reservation = store.reserve(
            "birdeye", operation, units, entry["cycle_start"], entry["max_units"],
        )
        store.dispatch(reservation)
        _put_receipt(config, store, grant, token_key, {
            "provider": "birdeye", "wallet": wallet, "phase": 1, "page": page,
            "units": units, "state": "dispatched", "reservation_id": reservation,
            "discovery_identity": identity, "path": path,
        })
        response = await _live_birdeye("GET", path, params)
        store.settle(reservation, charge=True)
        _put_receipt(config, store, grant, token_key, {
            "provider": "birdeye", "wallet": wallet, "phase": 1, "page": page,
            "units": units, "state": "consumed", "reservation_id": reservation,
            "discovery_identity": identity, "path": path,
        })
        _account_spend(state, provider="birdeye", units=units, phase=1)
        _account_source_spend(state, source, provider="birdeye", units=units)
        return response
    except Exception:
        if reservation:
            try:
                store.settle(reservation, charge=True)
            except ValueError:
                pass
        _put_receipt(config, store, grant, token_key, {
            "provider": "birdeye", "wallet": wallet, "phase": 1, "page": page,
            "units": units, "state": "failed", "reservation_id": reservation,
            "path": path,
        })
        _account_spend(state, provider="birdeye", units=units, phase=1)
        _account_source_spend(state, source, provider="birdeye", units=units)
        raise


async def _nansen_seed_call(store, grant, config, state, recorder, *, path, body, operation, units, wallet, page, identity):
    """Ledgered, grant-gated Nansen POST. Absent key never produces a dummy live call."""
    _validate_nansen_request(path, body)
    token_key = request_identity("nansen", wallet=wallet, phase=1, page=page, cursor=f"{identity}:{path}:{wallet}")
    hard_stop_if_needed(
        config, state["spend"], provider="nansen", units=units,
        phase=1, phase_spend=state.get("phase_spend"),
    )
    reservation = None
    if config["dry_run"]:
        _put_receipt(config, store, grant, token_key, {
            "provider": "nansen", "wallet": wallet, "phase": 1, "page": page,
            "units": units, "state": "planned", "discovery_identity": identity,
            "path": path, "body": body,
        })
        response = await recorder.nansen("POST", path, body)
        _account_spend(state, provider="nansen", units=units, phase=1)
        _account_source_spend(state, SEED_NANSEN, provider="nansen", units=units)
        return response
    if not config.get("nansen_enabled"):
        raise SourceError("UNAUTHORIZED", "NANSEN_API_KEY is not present; nansen source is disabled")
    if not grant.get("enabled"):
        raise SourceError("UNAUTHORIZED", grant.get("reason") or "grant disabled")
    if operation not in (provider_entry(grant, "nansen").get("allowed_operations") or []):
        raise SourceError("UNAUTHORIZED", f"Authorization does not include Nansen {operation}")
    try:
        entry = provider_entry(grant, "nansen")
        reservation = store.reserve(
            "nansen", operation, units, entry["cycle_start"], entry["max_units"],
        )
        store.dispatch(reservation)
        _put_receipt(config, store, grant, token_key, {
            "provider": "nansen", "wallet": wallet, "phase": 1, "page": page,
            "units": units, "state": "dispatched", "reservation_id": reservation,
            "discovery_identity": identity, "path": path, "body": body,
        })
        response = await _live_nansen("POST", path, body)
        store.settle(reservation, charge=True)
        _put_receipt(config, store, grant, token_key, {
            "provider": "nansen", "wallet": wallet, "phase": 1, "page": page,
            "units": units, "state": "consumed", "reservation_id": reservation,
            "discovery_identity": identity, "path": path,
            "billing": response.get("billing"),
        })
        _account_spend(state, provider="nansen", units=units, phase=1)
        _account_source_spend(state, SEED_NANSEN, provider="nansen", units=units)
        return response
    except Exception as error:
        if reservation:
            try:
                store.settle(reservation, charge=True)
            except ValueError:
                pass
        extras = getattr(error, "extras", None) or {}
        _put_receipt(config, store, grant, token_key, {
            "provider": "nansen", "wallet": wallet, "phase": 1, "page": page,
            "units": units, "state": "failed", "reservation_id": reservation,
            "path": path, "billing": extras.get("billing"),
            "error_body": extras.get("error_body"),
        })
        _account_spend(state, provider="nansen", units=units, phase=1)
        _account_source_spend(state, SEED_NANSEN, provider="nansen", units=units)
        raise


async def _phase1_nansen(store, grant, config, state, recorder, identity):
    """Optional official leaderboard. Missing key disables the source; never a dummy call."""
    enabled = bool(config.get("nansen_enabled"))
    if not enabled:
        note = {
            "enabled": False,
            "addresses": [],
            "reason": "NANSEN_API_KEY absent; source disabled; no dummy call",
            "seed_source": SEED_NANSEN,
            "seed_is_not": "evidence",
            "PRODUCT_READY": False,
        }
        raw = json.dumps(note, sort_keys=True, separators=(",", ":")).encode()
        digest = _save_raw(
            config["output_dir"],
            f"raw/phase1/nansen-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]}.bin",
            raw,
        )
        _save_raw(config["output_dir"], "raw/phase1/nansen.bin", raw)
        state.setdefault("discoveries", {})[identity] = note
        save_state(config["output_dir"], state)
        return {
            "addresses": [],
            "sha256": digest,
            "count": 0,
            "discovery_identity": identity,
            "pool_size": len(state.get("wallets") or []),
            "enabled": False,
            "seed_source": SEED_NANSEN,
            "seed_is_not": "evidence",
        }
    raw_parts = []
    extras = {}
    seen = set()
    selected = []
    date_from, date_to = nansen_date_range_from_bounds(config.get("bounds"))
    try:
        for page, timeframe in enumerate(NANSEN_TIMEFRAMES):
            body = nansen_leaderboard_body(timeframe=timeframe, page=1, per_page=50)
            response = await _nansen_seed_call(
                store, grant, config, state, recorder,
                path=NANSEN_LEADERBOARD_PATH,
                body=body,
                operation="smart_money_pnl_leaderboard",
                units=NANSEN_LEADERBOARD_UNITS,
                wallet=f"_leaderboard_{timeframe}",
                page=page,
                identity=identity,
            )
            raw_parts.append(response.get("raw_bytes") or b"{}")
            for row in select_nansen_wallets(
                nansen_leaderboard_rows(response.get("body")),
                timeframe=timeframe,
                seen=seen,
            ):
                selected.append(row)
                existing = extras.get(row["address"]) or {}
                timeframes = dict(existing.get("timeframes") or {})
                timeframes[str(timeframe)] = {
                    "rank": row.get("rank"),
                    "selection_reason": row.get("selection_reason"),
                    "vendor_metrics": row.get("vendor_metrics"),
                    "billing": response.get("billing"),
                    "timeframe": timeframe,
                }
                if row["address"] not in extras:
                    extras[row["address"]] = {
                        "rank": row.get("rank"),
                        "selection_reason": row.get("selection_reason"),
                        "vendor_metrics": row.get("vendor_metrics"),
                        "timeframe": timeframe,
                        "billing": response.get("billing"),
                        "timeframes": timeframes,
                    }
                else:
                    extras[row["address"]]["timeframes"] = timeframes
        profile_page = len(NANSEN_TIMEFRAMES)
        profile_cap = config.get("nansen_profile_cap")
        profiled = 0
        for row in selected:
            address = row["address"]
            if profile_cap is not None and profiled >= int(profile_cap):
                break
            left = remaining_caps(config, state["spend"])
            if left["nansen_requests"] < 1 or left["nansen_units"] < NANSEN_PROFILER_UNITS:
                break
            if not nansen_first_funder_supported():
                pass
            body = nansen_pnl_summary_body(
                wallet_address=address, date_from=date_from, date_to=date_to,
            )
            response = await _nansen_seed_call(
                store, grant, config, state, recorder,
                path=NANSEN_PNL_SUMMARY_PATH,
                body=body,
                operation="profiler_pnl_summary",
                units=NANSEN_PROFILER_UNITS,
                wallet=address,
                page=profile_page,
                identity=identity,
            )
            profile_page += 1
            raw_parts.append(response.get("raw_bytes") or b"{}")
            vendor = dict((extras.get(address) or {}).get("vendor_metrics") or {})
            payload = response.get("body") if isinstance(response.get("body"), dict) else {}
            # Documented pnl-summary body is top-level (top5_tokens, realized_pnl_usd).
            nested = payload.get("data") if isinstance(payload, dict) else None
            vendor["profiler_pnl_summary"] = nested if isinstance(nested, dict) else payload
            vendor["is_not"] = "independently_verified_profit_or_copyability"
            extras[address]["vendor_metrics"] = vendor
            extras[address]["billing"] = response.get("billing")
            profiled += 1
    except Exception:
        if raw_parts:
            _save_seed_raw_parts(config, identity, SEED_NANSEN, raw_parts)
        raise
    addresses = [row["address"] for row in selected]
    digest = _save_seed_raw_parts(config, identity, SEED_NANSEN, raw_parts)
    state.setdefault("discoveries", {})[identity] = {
        "addresses": list(addresses),
        "sha256": digest,
        "count": len(addresses),
        "seed_source": SEED_NANSEN,
        "seed_is_not": "evidence",
        "enabled": True,
    }
    _merge_discovery_wallets(config, state, addresses, source=SEED_NANSEN, extras=extras)
    save_state(config["output_dir"], state)
    return {
        "addresses": addresses,
        "sha256": digest,
        "count": len(addresses),
        "discovery_identity": identity,
        "pool_size": len(state.get("wallets") or []),
        "enabled": True,
        "seed_source": SEED_NANSEN,
        "seed_is_not": "evidence",
    }


async def _phase1_token_intersect(store, grant, config, state, recorder, identity):
    """Seasoned-token ordinary-period buyers, intersected across >=3 cohorts."""
    tokens = list(config.get("birdeye_tokens") or [])
    raw_parts = []
    now = utc_now_unix()
    chosen = []
    if tokens:
        listing = now - (40 * 86400)
        chosen = [{"address": token, "listing_time": listing, "role": "supplied"} for token in tokens]
    else:
        list_params = {
            "sort_by": "liquidity",
            "sort_type": "desc",
            "offset": 0,
            "limit": 50,
            "min_liquidity": DURABLE_TOKEN_MIN_LIQUIDITY_USD,
            "min_market_cap": DURABLE_TOKEN_MIN_MARKET_CAP_USD,
        }
        response = await _birdeye_seed_call(
            store, grant, config, state, recorder,
            path=BIRDEYE_TOKEN_LIST_PATH,
            params=list_params,
            operation="token_list",
            units=BIRDEYE_TOKEN_LIST_UNITS,
            wallet="_token_list",
            page=0,
            identity=identity,
            source=SEED_TOKEN_INTERSECT,
        )
        raw_parts.append(response.get("raw_bytes") or b"{}")
        items = token_list_items(response.get("body"))
        seasoned = select_durable_tokens(items, now_unix=now, limit=TOKEN_INTERSECT_SEASONED)
        controls = select_control_tokens(
            items,
            now_unix=now,
            skip=[row["address"] for row in seasoned],
            limit=TOKEN_INTERSECT_CONTROLS,
        )
        chosen = seasoned + controls
    appearances = []
    page = 1
    limit = min(int(config.get("birdeye_limit") or 50), 50)
    rate_limited = None
    try:
        for token_row in chosen:
            token = token_row.get("address")
            listing = token_row.get("listing_time") or (now - (40 * 86400))
            if not token:
                continue
            after_first_block = int(listing) + FIRST_BLOCK_EXCLUSION_SECONDS
            windows = ordinary_windows(listing)
            for window_index in range(TOKEN_INTERSECT_WINDOWS):
                params = token_txs_params(token, offset=window_index * limit, limit=limit)
                response = await _birdeye_seed_call(
                    store, grant, config, state, recorder,
                    path=BIRDEYE_TOKEN_TXS_PATH,
                    params=params,
                    operation="token_txs",
                    units=BIRDEYE_TOKEN_TXS_UNITS,
                    wallet=token,
                    page=page,
                    identity=identity,
                    source=SEED_TOKEN_INTERSECT,
                )
                page += 1
                raw_parts.append(response.get("raw_bytes") or b"{}")
                state.setdefault("seed_source_progress", {})[SEED_TOKEN_INTERSECT] = {
                    "paid_pages": len(raw_parts),
                    "tokens": [row.get("address") for row in chosen],
                    "seed_source": SEED_TOKEN_INTERSECT,
                }
                save_state(config["output_dir"], state)
                items = token_tx_items(response.get("body"))
                windowed = False
                for window in windows:
                    owners = token_tx_owners(
                        items,
                        token=token,
                        window=window["name"],
                        after_time=window["after_time"],
                        before_time=window["before_time"],
                    )
                    if owners:
                        windowed = True
                        appearances.extend(owners)
                if not windowed:
                    appearances.extend(token_tx_owners(
                        items,
                        token=token,
                        window="recent_ordinary",
                        after_time=after_first_block,
                    ))
    except SourceError as error:
        if raw_parts:
            _save_seed_raw_parts(config, identity, SEED_TOKEN_INTERSECT, raw_parts)
        if getattr(error, "state", None) == "RATE_LIMITED" and raw_parts:
            rate_limited = error
        else:
            raise
    except Exception:
        if raw_parts:
            _save_seed_raw_parts(config, identity, SEED_TOKEN_INTERSECT, raw_parts)
        raise
    selected = intersect_token_cohorts(appearances)
    extras = {
        row["address"]: {
            "rank": row.get("rank"),
            "selection_reason": row.get("selection_reason"),
            "tokens": row.get("tokens"),
            "cohort_count": row.get("cohort_count"),
        }
        for row in selected
    }
    addresses = [row["address"] for row in selected]
    raw = b"\n".join(raw_parts) if raw_parts else b"{}"
    digest = _save_raw(
        config["output_dir"],
        f"raw/phase1/token-intersect-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:12]}.bin",
        raw,
    )
    _save_raw(config["output_dir"], "raw/phase1/token-intersect.bin", raw)
    state.setdefault("discoveries", {})[identity] = {
        "addresses": list(addresses),
        "sha256": digest,
        "count": len(addresses),
        "tokens": [row.get("address") for row in chosen],
        "paid_pages": len(raw_parts),
        "partial": bool(rate_limited),
        "seed_source": SEED_TOKEN_INTERSECT,
        "seed_is_not": "evidence",
    }
    state.setdefault("seed_source_progress", {})[SEED_TOKEN_INTERSECT] = {
        "paid_pages": len(raw_parts),
        "addresses": list(addresses),
        "partial": bool(rate_limited),
        "seed_source": SEED_TOKEN_INTERSECT,
    }
    _merge_discovery_wallets(config, state, addresses, source=SEED_TOKEN_INTERSECT, extras=extras)
    if rate_limited:
        _record_seed_source_failure(state, SEED_TOKEN_INTERSECT, rate_limited, retained_pages=len(raw_parts))
    save_state(config["output_dir"], state)
    result = {
        "addresses": addresses,
        "sha256": digest,
        "count": len(addresses),
        "discovery_identity": identity,
        "pool_size": len(state.get("wallets") or []),
        "paid_pages": len(raw_parts),
        "partial": bool(rate_limited),
        "seed_source": SEED_TOKEN_INTERSECT,
        "seed_is_not": "evidence",
    }
    if rate_limited:
        result["rate_limited"] = True
        result["stop_after_failure"] = False
    return result


async def phase1_discovery(store, grant, config, state, recorder):
    if 1 not in config["phases"]:
        return {"skipped": True}
    if config["wallets"] and not config.get("discovery"):
        return {"skipped": True, "reason": "wallet_list_supplied"}
    sources = list(config.get("seed_sources") or [config.get("discovery_source") or BIRDEYE_DISCOVERY_GAINERS])
    identity = discovery_identity(config)
    per_source = {}
    combined = []
    for source in sources:
        if source == SEED_PRESCREEN_FILTER:
            continue
        source_identity = f"{identity}|{source}"
        if _seed_source_stopped(state, source):
            prior_fail = ((state.get("seed_source_failures") or {}).get(source) or {})
            per_source[source] = {
                "skipped": True,
                "stop_after_failure": True,
                "reason": prior_fail.get("state") or prior_fail.get("reason"),
                "addresses": [],
                "count": 0,
                "seed_source": source,
                "seed_is_not": "evidence",
            }
            continue
        prior = ((state.get("discoveries") or {}).get(source_identity) or {})
        if prior.get("addresses") is not None and source_identity in (state.get("discoveries") or {}):
            addresses = list(prior.get("addresses") or [])
            _merge_discovery_wallets(config, state, addresses, source=source)
            per_source[source] = {**prior, "replayed_from_receipt": True}
            for addr in addresses:
                if addr not in combined:
                    combined.append(addr)
            continue
        try:
            if source == SEED_TOKEN_INTERSECT:
                result = await _phase1_token_intersect(store, grant, config, state, recorder, source_identity)
            elif source == SEED_NANSEN:
                result = await _phase1_nansen(store, grant, config, state, recorder, source_identity)
            elif source == SEED_BIRDEYE_TOP:
                result = await _phase1_birdeye_top(store, grant, config, state, recorder, source_identity)
            else:
                continue
        except SourceError as error:
            retained = 0
            progress = ((state.get("seed_source_progress") or {}).get(source) or {})
            retained = int(progress.get("paid_pages") or 0)
            _record_seed_source_failure(state, source, error, retained_pages=retained)
            save_state(config["output_dir"], state)
            if getattr(error, "state", None) == "RATE_LIMITED" and retained:
                prior = ((state.get("discoveries") or {}).get(source_identity) or {})
                per_source[source] = {**prior, "rate_limited": True, "stop_after_failure": False}
                for addr in prior.get("addresses") or []:
                    if addr not in combined:
                        combined.append(addr)
                continue
            raise
        per_source[source] = result
        for addr in result.get("addresses") or []:
            if addr not in combined:
                combined.append(addr)
    state.setdefault("discoveries", {})[identity] = {
        "addresses": list(combined),
        "count": len(combined),
        "per_source": {key: {"count": row.get("count"), "seed_source": key} for key, row in per_source.items()},
        "seed_sources": sources,
        "seed_is_not": "evidence",
    }
    save_state(config["output_dir"], state)
    return {
        "addresses": combined,
        "count": len(combined),
        "discovery_identity": identity,
        "pool_size": len(state.get("wallets") or []),
        "per_source": per_source,
        "seed_sources": sources,
        "seed_source": primary_seed_source(sources),
        "seed_is_not": "evidence",
    }


async def _phase1_birdeye_top(store, grant, config, state, recorder, identity):
    source = config.get("discovery_source") or BIRDEYE_DISCOVERY_GAINERS
    if source not in (BIRDEYE_DISCOVERY_GAINERS, BIRDEYE_DISCOVERY_TOP_TRADERS):
        source = BIRDEYE_DISCOVERY_GAINERS
    if source == BIRDEYE_DISCOVERY_TOP_TRADERS:
        token_count = max(len(config.get("birdeye_tokens") or []), 1)
        phase1_units = token_count * BIRDEYE_TOP_TRADERS_UNITS
    else:
        phase1_units = BIRDEYE_UNITS
    hard_stop_if_needed(
        config, state["spend"], provider="birdeye", units=phase1_units,
        phase=1, phase_spend=state.get("phase_spend"),
    )
    params = {
        "type": config.get("birdeye_window") or BIRDEYE_DEFAULT_WINDOW,
        "sort_by": config.get("birdeye_sort") or BIRDEYE_DEFAULT_SORT,
        "sort_type": "desc",
        "offset": 0,
        "limit": int(config.get("birdeye_limit") or BIRDEYE_DEFAULT_LIMIT),
    }
    if source == BIRDEYE_DISCOVERY_TOP_TRADERS:
        params["time_frame"] = params.pop("type")
        params["tokens"] = list(config.get("birdeye_tokens") or [])
        sort = params.get("sort_by") or BIRDEYE_TOP_TRADERS_DEFAULT_SORT
        if sort not in BIRDEYE_TOP_TRADERS_SORTS:
            params["sort_by"] = BIRDEYE_TOP_TRADERS_DEFAULT_SORT
    base = request_identity("birdeye", wallet="_", phase=1, page=0, cursor=identity)
    key, existing, replay = _next_receipt_key(store, base, explicit_retry=config.get("explicit_retry"))
    if replay:
        reconcile_state_spend(store, state)
        prior = ((state.get("discoveries") or {}).get(identity) or {})
        addresses = list(prior.get("addresses") or [])
        _merge_discovery_wallets(config, state, addresses, source=SEED_BIRDEYE_TOP)
        save_state(config["output_dir"], state)
        return {
            "addresses": addresses,
            "replayed_from_receipt": True,
            "discovery_identity": identity,
            "count": len(addresses),
            "seed_source": SEED_BIRDEYE_TOP,
            "seed_is_not": "evidence",
        }
    reservation = None
    batch_receipt = source != BIRDEYE_DISCOVERY_TOP_TRADERS
    if batch_receipt:
        _put_receipt(config, store, grant, key, {
            "provider": "birdeye",
            "wallet": "_",
            "phase": 1,
            "page": 0,
            "units": phase1_units,
            "state": "reserved",
        })
    charged = False
    extras = {}
    try:
        if source == BIRDEYE_DISCOVERY_TOP_TRADERS:
            tokens = list(config.get("birdeye_tokens") or [])
            if not tokens:
                raise LiveE2EError("top-traders discovery requires --birdeye-tokens")
            addresses = []
            raw_parts = []
            sort = params.get("sort_by") or BIRDEYE_TOP_TRADERS_DEFAULT_SORT
            if sort not in BIRDEYE_TOP_TRADERS_SORTS:
                sort = BIRDEYE_TOP_TRADERS_DEFAULT_SORT
            if not config["dry_run"]:
                if not grant.get("enabled"):
                    raise SourceError("UNAUTHORIZED", grant.get("reason") or "grant disabled")
                if "token_top_traders" not in (provider_entry(grant, "birdeye").get("allowed_operations") or []):
                    raise SourceError("UNAUTHORIZED", "Authorization does not include Birdeye token_top_traders")
            for index, token in enumerate(tokens):
                token_key = request_identity(
                    "birdeye", wallet=token, phase=1, page=index, cursor=f"{identity}:{token}",
                )
                token_units = BIRDEYE_TOP_TRADERS_UNITS
                hard_stop_if_needed(
                    config, state["spend"], provider="birdeye", units=token_units,
                    phase=1, phase_spend=state.get("phase_spend"),
                )
                call_params = {
                    "address": token,
                    "time_frame": params.get("time_frame") or BIRDEYE_DEFAULT_WINDOW,
                    "sort_by": sort,
                    "sort_type": "desc",
                    "offset": 0,
                    "limit": min(int(params.get("limit") or 10), 10),
                }
                token_res = None
                if config["dry_run"]:
                    _put_receipt(config, store, grant, token_key, {
                        "provider": "birdeye", "wallet": token, "phase": 1, "page": index,
                        "units": token_units, "state": "consumed", "discovery_identity": identity,
                    })
                    response = await recorder.birdeye("GET", BIRDEYE_TOP_TRADERS_PATH, call_params)
                    raw_parts.append(response.get("raw_bytes") or b"{}")
                    _account_spend(state, provider="birdeye", units=token_units, phase=1)
                    _account_source_spend(state, SEED_BIRDEYE_TOP, provider="birdeye", units=token_units)
                    continue
                try:
                    entry = provider_entry(grant, "birdeye")
                    token_res = store.reserve(
                        "birdeye", "token_top_traders", token_units, entry["cycle_start"], entry["max_units"],
                    )
                    store.dispatch(token_res)
                    _put_receipt(config, store, grant, token_key, {
                        "provider": "birdeye", "wallet": token, "phase": 1, "page": index,
                        "units": token_units, "state": "dispatched", "reservation_id": token_res,
                        "discovery_identity": identity,
                    })
                    response = await _live_birdeye("GET", BIRDEYE_TOP_TRADERS_PATH, call_params)
                    store.settle(token_res, charge=True)
                    _put_receipt(config, store, grant, token_key, {
                        "provider": "birdeye", "wallet": token, "phase": 1, "page": index,
                        "units": token_units, "state": "consumed", "reservation_id": token_res,
                        "discovery_identity": identity,
                    })
                    _account_spend(state, provider="birdeye", units=token_units, phase=1)
                    _account_source_spend(state, SEED_BIRDEYE_TOP, provider="birdeye", units=token_units)
                except Exception:
                    if token_res:
                        try:
                            store.settle(token_res, charge=True)
                        except ValueError:
                            pass
                    _put_receipt(config, store, grant, token_key, {
                        "provider": "birdeye", "wallet": token, "phase": 1, "page": index,
                        "units": token_units, "state": "failed", "reservation_id": token_res,
                    })
                    _account_spend(state, provider="birdeye", units=token_units, phase=1)
                    raise
                body = response.get("body") if isinstance(response.get("body"), dict) else {}
                items = body.get("data", {}).get("items") if isinstance(body.get("data"), dict) else body.get("items")
                if not isinstance(items, list):
                    items = body.get("data") if isinstance(body.get("data"), list) else []
                for row in items or []:
                    addr = row.get("address") or row.get("wallet") or row.get("owner")
                    if addr:
                        addresses.append(addr)
                        extras[addr] = {
                            "trade_count": row.get("trade_count") or row.get("trade"),
                            "token": token,
                        }
                raw_parts.append(response.get("raw_bytes") or b"{}")
            charged = True
            reservation = None
            raw = b"\n".join(raw_parts) if raw_parts else b"{}"
        elif config["dry_run"]:
            response = await recorder.birdeye("GET", ALLOWED_BIRDEYE_PATH, params)
            raw = response.get("raw_bytes") or b"{}"
            addresses = []
        else:
            if not grant.get("enabled"):
                raise SourceError("UNAUTHORIZED", grant.get("reason") or "grant disabled")
            entry = provider_entry(grant, "birdeye")
            reservation = store.reserve(
                "birdeye", "trader_gainers_losers", BIRDEYE_UNITS, entry["cycle_start"], entry["max_units"],
            )
            store.dispatch(reservation)
            _put_receipt(config, store, grant, key, {
                "provider": "birdeye",
                "wallet": "_",
                "phase": 1,
                "page": 0,
                "units": BIRDEYE_UNITS,
                "state": "dispatched",
                "reservation_id": reservation,
            })
            # Adapter must not receive the store: one documented 30 CU reserve only.
            adapter = BirdeyeTraderAdapter(transport=_live_birdeye)
            page = await adapter.fetch_page(
                offset=0,
                limit=int(params["limit"]),
                window=params.get("type") or BIRDEYE_DEFAULT_WINDOW,
                authorization=grant,
                store=None,
                sort_by=params["sort_by"],
                sort_type="desc",
            )
            store.settle(reservation, charge=True)
            charged = True
            raw = page.get("raw_bytes")
            if not isinstance(raw, (bytes, bytearray)):
                raw = json.dumps(page.get("raw_body") or {}, sort_keys=True, separators=(",", ":")).encode()
            addresses = []
            for row in (page.get("rows") or []):
                if row.get("valid") and row.get("address"):
                    addresses.append(row["address"])
                    extras[row["address"]] = {"trade_count": row.get("trade_count")}
    except Exception:
        if reservation and not charged:
            try:
                store.settle(reservation, charge=True)
            except ValueError:
                pass
        if batch_receipt:
            _put_receipt(config, store, grant, key, {
                "provider": "birdeye",
                "wallet": "_",
                "phase": 1,
                "page": 0,
                "units": phase1_units,
                "state": "failed",
                "reservation_id": reservation,
            })
            _account_spend(state, provider="birdeye", units=phase1_units, phase=1)
        save_state(config["output_dir"], state)
        raise
    digest_name = "birdeye-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12] + ".bin"
    digest = _save_raw(config["output_dir"], f"raw/phase1/{digest_name}", raw)
    _save_raw(config["output_dir"], "raw/phase1/birdeye.bin", raw)
    if batch_receipt:
        _put_receipt(config, store, grant, key, {
            "provider": "birdeye",
            "wallet": "_",
            "phase": 1,
            "page": 0,
            "units": phase1_units,
            "state": "consumed",
            "sha256": digest,
            "reservation_id": reservation,
            "discovery_identity": identity,
        })
        _account_spend(state, provider="birdeye", units=phase1_units, phase=1)
        _account_source_spend(state, SEED_BIRDEYE_TOP, provider="birdeye", units=phase1_units)
    state.setdefault("discoveries", {})[identity] = {
        "addresses": list(addresses),
        "sha256": digest,
        "count": len(addresses),
        "units": phase1_units,
        "seed_source": SEED_BIRDEYE_TOP,
        "seed_is_not": "evidence",
    }
    for extra in extras.values():
        extra.setdefault("selection_reason", f"birdeye_{source}")
    _merge_discovery_wallets(config, state, addresses, source=SEED_BIRDEYE_TOP, extras=extras)
    save_state(config["output_dir"], state)
    return {
        "addresses": addresses,
        "sha256": digest,
        "count": len(addresses),
        "discovery_identity": identity,
        "pool_size": len(state.get("wallets") or []),
        "seed_source": SEED_BIRDEYE_TOP,
        "seed_is_not": "evidence",
    }


def _triage_sample_options(bounds):
    """Earliest / recent / older-month bounded full samples. Limit 100 each."""
    history_start = int(bounds["history_start_unix"])
    report_end = int(bounds["report_end_unix"])
    older_end = max(report_end - (30 * 86400), history_start + 1)
    older_start = max(older_end - (30 * 86400), history_start)
    return (
        ("earliest", gta_options(
            details="full", limit=GTA_SAMPLE_LIMIT,
            start_unix=history_start, end_unix=report_end, sort_order="asc",
        )),
        ("recent", gta_options(
            details="full", limit=GTA_SAMPLE_LIMIT,
            start_unix=history_start, end_unix=report_end, sort_order="desc",
        )),
        ("older_month", gta_options(
            details="full", limit=GTA_SAMPLE_LIMIT,
            start_unix=older_start, end_unix=older_end, sort_order="desc",
        )),
    )


def _triage_third_sample(bounds, samples):
    """Retarget the third sample at the densest UTC day already seen."""
    densest = densest_utc_day_bounds(samples)
    if densest:
        return ("densest_day", gta_options(
            details="full", limit=GTA_SAMPLE_LIMIT,
            start_unix=densest["start_unix"], end_unix=densest["end_unix"],
            sort_order="desc",
        ))
    return _triage_sample_options(bounds)[2]


async def phase2_prescreen(store, grant, config, state, recorder):
    if 2 not in config["phases"]:
        return {"skipped": True}
    bounds = config["bounds"]
    transport = recorder.helius if config["dry_run"] else _live_helius
    thresholds = config.get("prescreen") or {}
    min_in_window = int(thresholds.get("min_in_window_tx") or 0)
    max_unsupported_share = Decimal(str(thresholds.get("max_unsupported_share") or "1"))
    max_bot_rate = Decimal(str(thresholds.get("max_bot_rate") or "1"))
    triage = helius_triage_enabled(config.get("seed_sources"))
    rows = []
    for address in config["wallets"]:
        if address in (state.get("phase2") or {}) and (state["phase2"][address] or {}).get("done"):
            rows.append(state["phase2"][address])
            continue
        if triage:
            samples = []
            sample_records = []
            try:
                specs = list(_triage_sample_options(bounds))
                for page_index in range(TRIAGE_SAMPLES):
                    if page_index == 2:
                        name, options = _triage_third_sample(bounds, samples)
                    else:
                        name, options = specs[page_index]
                    page = await _dispatch_helius(
                        store, grant, config, state, transport, address, options,
                        phase=2, page_index=page_index,
                    )
                    records = page.get("records") or []
                    events = []
                    try:
                        from scanner.mass_search.canonical_records import canonical_decode_records
                        decoded = decode_supported_swaps(canonical_decode_records(records), address)
                        events = list(decoded.get("events") or [])
                    except Exception:
                        events = []
                    samples.append({"name": name, "records": records, "events": events})
                    sample_records.extend(records)
                    seed_source = seed_fields_for_wallet(state, address).get("seed_source") or "helius_triage"
                    _account_source_spend(state, seed_source, provider="helius", units=FULL_100_UNITS)
                    _account_source_spend(state, "helius_triage", provider="helius", units=FULL_100_UNITS)
            except SourceError as error:
                if getattr(error, "state", None) in ("WALLET_CAP", "MISSING_CAPTURE", "UNRECEIPTED_PAGE"):
                    row = {
                        "address": address,
                        "dropped": True,
                        "drop_reason": str(getattr(error, "state")).lower(),
                        "done": True,
                        "history_complete": False,
                        "triage": True,
                        **seed_fields_for_wallet(state, address),
                    }
                    state.setdefault("phase2", {})[address] = row
                    save_state(config["output_dir"], state)
                    rows.append(row)
                    continue
                raise
            programs = classify_programs(sample_records, address)
            in_window = len(samples[1]["records"] if len(samples) > 1 else sample_records)
            unsupported_share = Decimal(programs["decodable_share"] or "1")
            unsupported_share = Decimal("1") - unsupported_share if programs["decodable_share"] is not None else Decimal("0")
            bot_rate = compute_bot_rate(sample_records, config.get("window_days") or 30)
            bundle = detect_bundle_or_distribution(sample_records, address)
            seeds = seed_counterparties_from_records(sample_records, address)
            if seeds:
                state.setdefault("seed_counterparties", {})[address] = list(seeds)
                pooled = list(state.get("wallets") or config.get("wallets") or [])
                for seed in seeds:
                    addr = seed.get("address") if isinstance(seed, dict) else seed
                    if addr and addr not in pooled:
                        pooled.append(addr)
                state["wallets"] = pooled
            decoded_sigs = _decoded_swap_signatures(sample_records, address)
            has_known_basis_buys = any(
                event.get("kind") == "buy"
                for sample in samples
                for event in (sample.get("events") or [])
            ) or bool(decoded_sigs)
            created = False
            try:
                created = bool(
                    assess_history_completeness(sample_records, None, address=address).get("wallet_created_in_range")
                )
            except Exception:
                created = False
            decision = helius_triage_decision(
                samples,
                now_unix=bounds.get("report_end_unix"),
                bundle=bundle,
                created_in_range=created,
            )
            dropped = bool(decision["dropped"])
            drop_reason = ",".join(decision["drop_reasons"]) if dropped else None
            row = {
                "address": address,
                "in_window_tx_count": in_window,
                "sample_records": len(sample_records),
                "decodable_share": programs["decodable_share"],
                "unsupported_share": str(unsupported_share),
                "supported_venue_value_share": programs.get("supported_venue_value_share"),
                "has_known_basis_buys": has_known_basis_buys,
                "bundle": bundle.get("excluded"),
                "bundle_reasons": bundle.get("reasons") or [],
                "controlled_pair": bundle.get("controlled_pair") or [],
                "controlled_pair_explanation": bundle.get("controlled_pair_explanation"),
                "bot": bot_rate > max_bot_rate,
                "bot_rate": str(bot_rate),
                "program_blockers": programs["blockers"],
                "coverability_rank_key": str(prescreen_rank_score({
                    "supported_venue_value_share": programs.get("supported_venue_value_share") or "0",
                    "has_known_basis_buys": has_known_basis_buys,
                    "bundle": bundle.get("excluded"),
                    "bot": bot_rate > max_bot_rate,
                    "controlled_pair": bundle.get("controlled_pair"),
                })),
                "dropped": dropped,
                "drop_reason": drop_reason,
                "requests": 3,
                "done": True,
                "triage": True,
                "triage_decision": decision,
                "count_kinds": list(COUNT_KINDS),
                **seed_fields_for_wallet(state, address),
            }
            state.setdefault("phase2", {})[address] = row
            save_state(config["output_dir"], state)
            rows.append(row)
            continue
        sig_opts = gta_options(
            details="signatures",
            limit=GTA_MAX_LIMIT,
            start_unix=bounds["report_start_unix"],
            end_unix=bounds["report_end_unix"],
        )
        try:
            sigs = await _dispatch_helius(store, grant, config, state, transport, address, sig_opts, phase=2, page_index=0)
            sample_opts = gta_options(
                details="full",
                limit=GTA_SAMPLE_LIMIT,
                start_unix=bounds["history_start_unix"],
                end_unix=bounds["report_end_unix"],
            )
            sample = await _dispatch_helius(store, grant, config, state, transport, address, sample_opts, phase=2, page_index=1)
        except SourceError as error:
            if getattr(error, "state", None) in ("WALLET_CAP", "MISSING_CAPTURE", "UNRECEIPTED_PAGE"):
                row = {
                    "address": address,
                    "dropped": True,
                    "drop_reason": str(getattr(error, "state")).lower(),
                    "done": True,
                    "history_complete": False,
                }
                state.setdefault("phase2", {})[address] = row
                save_state(config["output_dir"], state)
                rows.append(row)
                continue
            raise
        sample_records = sample.get("records") or []
        programs = classify_programs(sample_records, address)
        in_window = len(sigs.get("records") or [])
        unsupported_share = Decimal(programs["decodable_share"] or "1")
        unsupported_share = Decimal("1") - unsupported_share if programs["decodable_share"] is not None else Decimal("0")
        bot_rate = compute_bot_rate(sigs.get("records") or [], config.get("window_days") or 30)
        bundle = detect_bundle_or_distribution(sample_records, address)
        seeds = seed_counterparties_from_records(sample_records, address)
        if seeds:
            state.setdefault("seed_counterparties", {})[address] = list(seeds)
            pooled = list(state.get("wallets") or config.get("wallets") or [])
            for seed in seeds:
                addr = seed.get("address") if isinstance(seed, dict) else seed
                if addr and addr not in pooled:
                    pooled.append(addr)
            state["wallets"] = pooled
        decoded_sigs = _decoded_swap_signatures(sample_records, address)
        has_known_basis_buys = False
        try:
            from scanner.mass_search.canonical_records import canonical_decode_records
            decoded = decode_supported_swaps(canonical_decode_records(sample_records), address)
            has_known_basis_buys = any(event.get("kind") == "buy" for event in decoded.get("events") or [])
        except Exception:
            has_known_basis_buys = bool(decoded_sigs)
        dropped = False
        drop_reason = None
        if in_window < min_in_window:
            dropped = True
            drop_reason = "below_min_in_window_tx"
        elif unsupported_share > max_unsupported_share:
            dropped = True
            drop_reason = "unsupported_program_heavy"
        elif bot_rate > max_bot_rate:
            dropped = True
            drop_reason = "bot_rate"
        elif bundle.get("excluded"):
            dropped = True
            drop_reason = bundle.get("reason") or "bundle_or_distribution"
        elif cheap_prescreen_enabled(config.get("seed_sources")):
            created = False
            try:
                created = bool(
                    assess_history_completeness(sample_records, None, address=address).get("wallet_created_in_range")
                )
            except Exception:
                created = False
            history_days = history_span_days(
                sample_records,
                created_in_range=created,
                now_unix=bounds.get("report_end_unix"),
            )
            decision = cheap_prescreen_decision({
                "trades_per_day": bot_rate,
                "history_days": history_days,
            })
            if decision["dropped"]:
                dropped = True
                drop_reason = ",".join(decision["drop_reasons"])
                state.setdefault("cheap_prescreen", {})[address] = decision
                record_seed_metadata(state, address, SEED_PRESCREEN_FILTER, decision)
        row = {
            "address": address,
            "in_window_tx_count": in_window,
            "sample_records": len(sample_records),
            "decodable_share": programs["decodable_share"],
            "unsupported_share": str(unsupported_share),
            "supported_venue_value_share": programs.get("supported_venue_value_share"),
            "has_known_basis_buys": has_known_basis_buys,
            "bundle": bundle.get("excluded"),
            "bundle_reasons": bundle.get("reasons") or [],
            "controlled_pair": bundle.get("controlled_pair") or [],
            "controlled_pair_explanation": bundle.get("controlled_pair_explanation"),
            "bot": bot_rate > max_bot_rate,
            "bot_rate": str(bot_rate),
            "program_blockers": programs["blockers"],
            "coverability_rank_key": str(prescreen_rank_score({
                "supported_venue_value_share": programs.get("supported_venue_value_share") or "0",
                "has_known_basis_buys": has_known_basis_buys,
                "bundle": bundle.get("excluded"),
                "bot": bot_rate > max_bot_rate,
                "controlled_pair": bundle.get("controlled_pair"),
            })),
            "dropped": dropped,
            "drop_reason": drop_reason,
            "requests": 2,
            "done": True,
            **seed_fields_for_wallet(state, address),
        }
        state.setdefault("phase2", {})[address] = row
        save_state(config["output_dir"], state)
        rows.append(row)
    ranked = sorted(rows, key=lambda row: (
        row.get("dropped") is True,
        -float(row.get("coverability_rank_key") or 0),
        row["address"],
    ))
    kept = [row["address"] for row in ranked if not row.get("dropped")]
    return {"wallets": ranked, "kept": kept}


async def phase3_history(store, grant, config, state, recorder):
    if 3 not in config["phases"]:
        return {"skipped": True}
    bounds = config["bounds"]
    transport = recorder.helius if config["dry_run"] else _live_helius
    kept = phase3_wallets(config, state)
    pages = {}
    triage = helius_triage_enabled(config.get("seed_sources"))
    for address in kept:
        cursor = (state.get("phase3") or {}).get(address) or {"pages": 0, "requests": 0, "done": False}
        remaining = phase3_remaining_budget(config, state, address, triage=triage)
        history_finished = bool(
            cursor.get("history_complete")
            or cursor.get("window_covered")
            or cursor.get("early_stop_bot_rate")
            or cursor.get("history_complete_reason") in (
                "wallet_created_in_range",
                "no_leftover_pagination_token",
                "gt_25_economic_trades_in_one_day",
            )
        )
        if cursor.get("done") and history_finished:
            pages[address] = cursor
            continue
        if cursor.get("done") and remaining == 0:
            pages[address] = cursor
            continue
        if cursor.get("done") and remaining not in (None, 0) and not history_finished:
            cursor = dict(cursor)
            cursor["done"] = False
        token = cursor.get("pagination_token")
        while True:
            page_cap = config.get("per_wallet_cap")
            used = int(cursor.get("requests") or 0)
            used += wallet_triage_requests(state, address, triage=triage)
            if page_cap is not None and used >= int(page_cap):
                cursor["done"] = True
                cursor["history_complete"] = False
                cursor["history_complete_reason"] = "per_wallet_cap"
                cursor["leftover_pagination_token"] = bool(token)
                cursor["window_covered"] = False
                cursor["history_reached_window_start"] = False
                break
            options = gta_options(
                details="full",
                limit=GTA_MAX_LIMIT,
                start_unix=bounds["history_start_unix"],
                end_unix=bounds["report_end_unix"],
                pagination_token=token,
            )
            try:
                result = await _dispatch_helius(
                    store, grant, config, state, transport, address, options,
                    phase=3, page_index=cursor["pages"],
                )
            except SourceError as error:
                code = getattr(error, "state", None)
                if code in ("WALLET_CAP", "MISSING_CAPTURE", "UNRECEIPTED_PAGE"):
                    cursor["done"] = True
                    cursor["history_complete"] = False
                    cursor["history_complete_reason"] = (
                        "per_wallet_cap" if code == "WALLET_CAP" else str(code).lower()
                    )
                    cursor["leftover_pagination_token"] = bool(token)
                    cursor["window_covered"] = False
                    break
                raise
            cursor["pages"] += 1
            cursor["requests"] = cursor.get("requests", 0) + 1
            cursor["pagination_token"] = result.get("pagination_token")
            cursor["last_sha256"] = result.get("evidence_sha256")
            token = result.get("pagination_token")
            records = result.get("records") or []
            seed_source = seed_fields_for_wallet(state, address).get("seed_source") or "helius_history"
            _account_source_spend(state, seed_source, provider="helius", units=FULL_1000_UNITS)
            page_events = []
            try:
                from scanner.mass_search.canonical_records import canonical_decode_records
                decoded = decode_supported_swaps(canonical_decode_records(records), address)
                page_events = list(decoded.get("events") or [])
            except Exception:
                page_events = []
            rate = economic_trade_rate(page_events)
            if rate["max"] > 25:
                cursor["done"] = True
                cursor["history_complete"] = False
                cursor["history_complete_reason"] = "gt_25_economic_trades_in_one_day"
                cursor["early_stop_bot_rate"] = True
                cursor["leftover_pagination_token"] = bool(token)
                cursor["window_covered"] = False
                cursor["history_reached_window_start"] = False
                cursor["max_economic_trades_in_one_day"] = rate["max"]
                cursor["max_economic_trades_on"] = rate["max_on"]
                break
            oldest = None
            for row in records:
                stamp = row.get("blockTime") or row.get("timestamp") or ((row.get("transaction") or {}).get("blockTime"))
                if type(stamp) is int:
                    oldest = stamp if oldest is None else min(oldest, stamp)
            limit = int(options.get("limit") or GTA_MAX_LIMIT)
            short_page = len(records) < limit
            created = assess_history_completeness(
                records, token, address=address,
            )
            reached_bound = oldest is not None and oldest <= bounds["history_start_unix"]
            no_more = not records or not token
            created_complete = bool(created["wallet_created_in_range"]) and (short_page or not records)
            covered = no_more or created_complete or (
                reached_bound and created["wallet_created_in_range"]
            )
            used_after = int(cursor.get("requests") or 0) + wallet_triage_requests(state, address, triage=triage)
            hit_page_cap = page_cap is not None and used_after >= int(page_cap)
            if covered or config["dry_run"] or hit_page_cap:
                cursor["done"] = True
                cursor["window_covered"] = bool(covered)
                cursor["history_reached_window_start"] = bool(covered or reached_bound)
                cursor["leftover_pagination_token"] = bool(token)
                cursor["history_complete"] = bool(created["history_complete"]) and not hit_page_cap
                if hit_page_cap and token:
                    cursor["history_complete"] = False
                    cursor["history_complete_reason"] = "per_wallet_cap"
                elif token and not created["wallet_created_in_range"]:
                    cursor["history_complete"] = False
                    cursor["history_complete_reason"] = "pagination_token_remaining_earlier_history"
                else:
                    cursor["history_complete_reason"] = created["history_complete_reason"]
                cursor["wallet_created_in_range"] = created["wallet_created_in_range"]
                cursor["oldest_block_time"] = created["oldest_block_time"]
                cursor["oldest_native_prebalance"] = created["oldest_native_prebalance"]
                break
            state.setdefault("phase3", {})[address] = cursor
            save_state(config["output_dir"], state)
        state.setdefault("phase3", {})[address] = cursor
        save_state(config["output_dir"], state)
        pages[address] = cursor
    return {"pages": pages}


def _phase4_wallet_row(report, profile):
    shares = coverage_shares(report, profile)
    profit, unit, vector = qualifying_profit(profile, report)
    level = (profile or {}).get("qualification_level") or {}
    fields = wallet_status_fields(report, profile)
    blocker = fields.get("blocking_reason")
    if level.get("level") in ("provisional_research_lead", "stronger_research_shortlist"):
        blocker = None
    completed = int((profile or {}).get("completed_known_cost_positions") or 0)
    realized = (vector or {}) if completed else {}
    bundle = (report.get("bundle_or_distribution") or {}) if isinstance(report, dict) else {}
    if bundle.get("excluded"):
        level = {"level": "insufficient_evidence"}
        blocker = bundle.get("reason") or "bundle_or_distribution"
    history = (report.get("history") or {}) if isinstance(report, dict) else {}
    if history.get("history_complete") is False:
        level = {"level": "insufficient_evidence"}
        blocker = history.get("history_complete_reason") or "history_incomplete"
    return {
        "address": report.get("address"),
        "coverage_count_share": shares.get("coverage_count_share"),
        "coverage_value_share": shares.get("coverage_value_share"),
        "coverage_mandatory_share": shares.get("coverage_mandatory_share"),
        "completed_trades": completed,
        "sample_positions": (profile or {}).get("sample_positions"),
        "realized_pnl_sol": realized.get("SOL"),
        "realized_pnl_usdc": realized.get("USDC"),
        "realized_pnl_usdt": realized.get("USDT"),
        "completed_episode_net": (profile or {}).get("completed_episode_net"),
        "completed_episode_net_unit": (profile or {}).get("completed_episode_net_unit"),
        "qualifying_profit": str(profit) if profit is not None else None,
        "qualifying_unit": unit,
        "audit_status": ((profile or {}).get("independent_audit") or {}).get("status") or "not_independently_audited",
        "independently_audited": independently_audited(report, profile),
        "lead_level": level.get("level") or "insufficient_evidence",
        "blocker": blocker,
        "max_economic_trades_in_one_day": (
            (profile or {}).get("max_economic_trades_in_one_day")
            or (report or {}).get("max_economic_trades_in_one_day")
            or level.get("max_economic_trades_in_one_day")
        ),
        "max_economic_trades_on": (
            (profile or {}).get("max_economic_trades_on")
            or (report or {}).get("max_economic_trades_on")
            or level.get("max_economic_trades_on")
        ),
        "max_trades_per_day": (
            (profile or {}).get("max_trades_per_day")
            or (report or {}).get("max_trades_per_day")
            or level.get("max_trades_per_day")
        ),
        "max_trades_per_day_on": (
            (profile or {}).get("max_trades_per_day_on")
            or (report or {}).get("max_trades_per_day_on")
            or level.get("max_trades_per_day_on")
        ),
        "coverage_status": fields.get("coverage_status"),
        "program_blockers": ((report.get("prescreen") or {}).get("program_blockers")),
        "bundle": bundle.get("excluded"),
        "bundle_reasons": bundle.get("reasons") or [],
        "controlled_pair": bundle.get("controlled_pair") or [],
        "controlled_pair_explanation": bundle.get("controlled_pair_explanation"),
        "bot": ((report.get("prescreen") or {}).get("bot")),
        "bot_rate": ((report.get("prescreen") or {}).get("bot_rate")),
        "supported_venue_value_share": (
            (report.get("prescreen") or {}).get("supported_venue_value_share")
            or shares.get("coverage_value_share")
        ),
        "has_known_basis_buys": ((report.get("prescreen") or {}).get("has_known_basis_buys")),
        "history_complete": history.get("history_complete"),
        "history_complete_reason": history.get("history_complete_reason"),
        "history_pages_fetched": history.get("pages_fetched") or history.get("phase3_pages"),
        "history_reached_window_start": history.get("history_reached_window_start"),
        "not_audited_reason": (
            None
            if independently_audited(report, profile)
            else (
                blocker
                or history.get("history_complete_reason")
                or ((profile or {}).get("independent_audit") or {}).get("reason")
                or "not_independently_audited"
            )
        ),
        "wallet_created_in_range": history.get("wallet_created_in_range"),
        "leftover_pagination_token": history.get("leftover_pagination_token"),
        "pnl_scope": (
            "decoded_subset"
            if shares.get("coverage_count_share") not in (None, "", "1", "1.0000")
            else "decoded"
        ),
        "pnl_note": (
            "App realized P&L is the decoded-subset FIFO, not the wallet's "
            "full balance-delta P&L. A high-coverage gap versus the auditor "
            "(e.g. 9R3m89gX −362 vs +8,221) means the decoded sample is not "
            "representative; unknown-basis / incomplete history blocks a lead."
            if shares.get("coverage_count_share") not in (None, "", "1", "1.0000")
            else None
        ),
        "quarantined_mints": bundle.get("quarantined_mints") or [],
        "sold_quarantined_mints": bundle.get("sold_quarantined_mints") or [],
        "quarantine_never_sold": len(bundle.get("quarantined_mints") or []) - len(bundle.get("sold_quarantined_mints") or []),
        "configured_report_end_exclusive": ((report.get("window") or {}).get("configured_report_end_exclusive")),
        "aligned_report_end_exclusive": ((report.get("window") or {}).get("aligned_report_end_exclusive")),
        "report_end_anchored_to_last_tx": ((report.get("window") or {}).get("report_end_anchored_to_last_tx")),
        "seed_source": (report.get("seed_source") if isinstance(report, dict) else None),
        "seed_sources": (report.get("seed_sources") if isinstance(report, dict) else None) or [],
        "seed_rank": (report.get("seed_rank") if isinstance(report, dict) else None),
        "selection_reason": (report.get("selection_reason") if isinstance(report, dict) else None),
        "vendor_metrics": (report.get("vendor_metrics") if isinstance(report, dict) else None),
        "seed_is_not": "evidence",
        "PRODUCT_READY": False,
    }


def phase4_offline(store, config, state):
    if 4 not in config["phases"]:
        return {"skipped": True}
    bounds = config["bounds"]
    rows = []
    for address in config["wallets"]:
        raw_dir = Path(config["output_dir"]) / "raw" / "phase3" / address
        records = []
        expected_pages = int(((state.get("phase3") or {}).get(address) or {}).get("pages") or 0)
        missing_page = False
        if expected_pages:
            for index in range(expected_pages):
                path = raw_dir / f"page{index}.bin"
                if not path.is_file() or path.stat().st_size == 0:
                    missing_page = True
                    break
        leftover_token = None
        page_blocker = "missing raw page; not covered"
        try:
            verify_receipt_chain(store)
        except ValueError:
            missing_page = True
        store_has_receipts = bool(
            hasattr(store, "list")
            and (store.list(RECEIPT_KIND) or store.list(CHAIN_ENTRY_KIND))
        )
        if raw_dir.is_dir() and not missing_page:
            for path in sorted(raw_dir.glob("page*.bin"), key=page_sort_key):
                try:
                    expected_sha = _receipt_sha_for_page(store, address, path.name, phase=3)
                    _raw, data, token = _verify_saved_page(
                        path,
                        f"raw/phase3/{address}/{path.name}",
                        expected_sha=expected_sha,
                        require_ledger_sha=store_has_receipts,
                    )
                except SourceError:
                    missing_page = True
                    integrity_path = path.with_name(path.name + ".integrity.json")
                    if integrity_path.is_file():
                        try:
                            integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
                        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                            integrity = {}
                        if integrity.get("scrubbed"):
                            page_blocker = "scrubbed provider echo; not covered"
                    records = []
                    break
                leftover_token = token
                records.extend(data)
        if missing_page:
            rows.append({
                "address": address,
                "coverage_count_share": None,
                "coverage_value_share": None,
                "completed_trades": 0,
                "realized_pnl_sol": None,
                "realized_pnl_usdc": None,
                "audit_status": "not_independently_audited",
                "independently_audited": False,
                "lead_level": "insufficient_evidence",
                "blocker": page_blocker,
                "history_pages_fetched": expected_pages,
                "history_reached_window_start": False,
                "not_audited_reason": page_blocker,
                "coverage_status": "blocked",
                "program_blockers": ((state.get("phase2") or {}).get(address) or {}).get("program_blockers") or [],
                **seed_fields_for_wallet(state, address),
                "PRODUCT_READY": False,
            })
            continue
        if not records:
            rows.append({
                "address": address,
                "coverage_count_share": None,
                "coverage_value_share": None,
                "completed_trades": 0,
                "realized_pnl_sol": None,
                "realized_pnl_usdc": None,
                "audit_status": "not_independently_audited",
                "independently_audited": False,
                "lead_level": "insufficient_evidence",
                "blocker": "no captured history in this run",
                "history_pages_fetched": expected_pages,
                "history_reached_window_start": False,
                "not_audited_reason": "no captured history in this run",
                "program_blockers": ((state.get("phase2") or {}).get(address) or {}).get("program_blockers") or [],
                **seed_fields_for_wallet(state, address),
                "PRODUCT_READY": False,
            })
            continue
        from scanner.mass_search.canonical_records import canonical_decode_records
        decoded = inject_undecoded_buy_taints(
            decode_supported_swaps(canonical_decode_records(records), address),
            records,
            address,
        )
        bundle = detect_bundle_or_distribution(records, address)
        phase3_cursor = (state.get("phase3") or {}).get(address) or {}
        history = assess_history_completeness(
            records,
            leftover_token if leftover_token is not None else phase3_cursor.get("leftover_pagination_token") or phase3_cursor.get("pagination_token"),
            address=address,
            cap_truncated=bool(phase3_cursor) and not phase3_cursor.get("done"),
            page_cap_hit=bool(phase3_cursor.get("history_complete_reason") == "page_cap_with_leftover_token"),
        )
        history["pages_fetched"] = int(phase3_cursor.get("pages") or 0)
        history["phase3_pages"] = int(phase3_cursor.get("pages") or 0)
        history["history_reached_window_start"] = bool(
            phase3_cursor.get("history_reached_window_start")
            or phase3_cursor.get("window_covered")
        )
        if phase3_cursor.get("history_complete") is False:
            history["history_complete"] = False
            history["history_complete_reason"] = phase3_cursor.get("history_complete_reason") or history["history_complete_reason"]
        aligned = align_wallet_bounds(records, bounds)
        result = replay_cached_history_to_report(
            store,
            address=address,
            records=records,
            window_start=aligned["report_start_inclusive"],
            window_end=aligned["report_end_exclusive"],
            acquisition_start=aligned["history_start_inclusive"],
            coverage_start=aligned["coverage_start_inclusive"],
            coverage_end=aligned["coverage_end_exclusive"],
            corpus_kind="GENUINE_REPLAY",
            authorization_id=config.get("authorization_id") or AUTHORIZATION_ID,
            source_id="live-e2e-proof",
        )
        report = result["report"]
        window_doc = dict(report.get("window") or {})
        window_doc.update({
            "start": aligned["report_start_inclusive"],
            "end": aligned["report_end_exclusive"],
            "configured_report_end_exclusive": aligned.get("configured_report_end_exclusive"),
            "aligned_report_end_exclusive": aligned.get("aligned_report_end_exclusive") or aligned["report_end_exclusive"],
            "report_end_anchored_to_last_tx": aligned.get("report_end_anchored_to_last_tx"),
        })
        report["window"] = window_doc
        report["prescreen"] = (state.get("phase2") or {}).get(address) or {}
        report.update(seed_fields_for_wallet(state, address))
        report["bundle_or_distribution"] = bundle
        report["history"] = history
        report["history_complete"] = history.get("history_complete")
        profile = build_research_profile(report, filters=default_filters(), decoded=decoded)
        audit = attach_live_independent_audit(report, profile, records, address)
        report["independent_audit"] = audit
        if audit and audit.get("status") == "independently_audited":
            profile = build_research_profile(report, filters=default_filters(), decoded=decoded)
        else:
            profile["independent_audit"] = audit
            from scanner.mass_search.research_profile import qualification_level
            profile["qualification_level"] = qualification_level(report, profile)
        report["research_profile"] = profile
        store.put("reports", report["id"], report)
        row = _phase4_wallet_row(report, _authoritative_saved_profile(report) or profile)
        rows.append(row)
    return {"wallets": rows}


def human_summary(results):
    lines = [
        "# LIVE E2E summary",
        "",
        f"Status: {results.get('status')}",
        f"Dry-run: {results.get('dry_run')}",
        f"PRODUCT_READY: false",
        "",
        "## Spend",
        "",
        json.dumps(results.get("spend") or {}, indent=2),
        "",
        "## Cost per audit-worthy candidate",
        "",
        json.dumps(results.get("cost_per_audit_worthy") or {}, indent=2),
        "",
        "## Wallets",
        "",
    ]
    for row in (results.get("wallets") or []):
        lines.append(
            f"- {row.get('address')}: coverage count={row.get('coverage_count_share')} "
            f"value={row.get('coverage_value_share')}; completed={row.get('completed_trades')}; "
            f"PnL SOL={row.get('realized_pnl_sol')} USDC={row.get('realized_pnl_usdc')}; "
            f"audit={row.get('audit_status')}; level={row.get('lead_level')}; "
            f"blocker={row.get('blocker')}; seed={row.get('seed_source')} "
            f"rank={row.get('seed_rank')} reason={row.get('selection_reason')}"
        )
        blockers = row.get("program_blockers") or []
        if blockers:
            labels = ", ".join(f"{item.get('label')} ({item.get('program_id')})" for item in blockers)
            lines.append(f"  program blockers: {labels}")
    lines.append("")
    return "\n".join(lines) + "\n"


def load_committed_draft(rel=DRAFT_REL):
    try:
        return committed_draft_payload(rel, repo_root=ROOT)
    except ValueError as error:
        raise LiveE2EError(str(error)) from error


def expected_pinned_ledger(armed_home=None):
    """Absolute ledger home. --live must not depend on HOME."""
    return Path(PINNED_LEDGER_ABSOLUTE).expanduser().resolve()


def assert_live_ledger_identity(grant):
    recorded_home = grant.get("armed_home")
    recorded_ledger = grant.get("ledger_home")
    if not recorded_home or not recorded_ledger:
        raise LiveE2EError(
            "armed grant must record armed_home and ledger_home; "
            "ledger identity is not relocatable for --live"
        )
    if Path(recorded_home).expanduser().resolve() != Path.home().resolve():
        raise LiveE2EError("HOME differs from armed_home recorded at arming")
    pinned = expected_pinned_ledger()
    auth_id = grant.get("authorization_id")
    if auth_id in LIVE_KNOWN_DRAFTS:
        try:
            draft, _ = load_committed_draft(LIVE_KNOWN_DRAFTS[auth_id])
        except LiveE2EError:
            draft = {}
        draft_pin = draft.get("pinned_ledger_home")
        if not draft_pin or not Path(str(draft_pin)).is_absolute():
            raise LiveE2EError("committed draft pinned_ledger_home must be an absolute path")
        if PINNED_LEDGER_ABSOLUTE == COMMITTED_LEDGER_ABSOLUTE:
            if Path(draft_pin).resolve() != Path(COMMITTED_LEDGER_ABSOLUTE).resolve():
                raise LiveE2EError("committed draft pinned_ledger_home disagrees with the code constant")
    if Path(recorded_ledger).expanduser().resolve() != pinned:
        raise LiveE2EError(
            "armed ledger_home is not the pinned ledger home "
            f"({pinned}); re-arming with a new ledger home is refused"
        )
    env_home = os.environ.get(LEDGER_HOME_ENV) or os.environ.get(LEDGER_ENV)
    if env_home:
        if Path(env_home).expanduser().resolve() != pinned:
            raise LiveE2EError(
                "refusing SCANNER_LIVE_LEDGER_* override that differs from "
                "the pinned ledger home"
            )
    else:
        default = expected_pinned_ledger(Path.home())
        if default != pinned:
            raise LiveE2EError("default ledger home differs from the pinned ledger home")
    return pinned


def bind_caps_from_grant(grant, overrides, *, mode="dry-run"):
    caps = provider_caps(grant)
    caps["phase_caps"] = phase_caps_from_grant(grant)
    auth_id = grant.get("authorization_id")
    if mode == "live" and auth_id in KNOWN_DRAFTS:
        pinned = PINNED_DRAFT_HASHES.get(auth_id)
        bound = grant.get("draft_artifact_hash")
        if not bound:
            raise LiveE2EError("draft_artifact_hash is required for --live")
        if pinned and bound != pinned:
            raise LiveE2EError("armed grant is not bound to the pinned draft artifact")
        draft, draft_hash = load_committed_draft(KNOWN_DRAFTS[auth_id])
        if bound != draft_hash:
            raise LiveE2EError("armed grant is not bound to the committed draft artifact")
        draft_caps = provider_caps(draft)
        if not grant.get("phase_caps"):
            caps["phase_caps"] = phase_caps_from_grant(draft)
        for key in HARD_CEILINGS:
            if key not in caps and key not in draft_caps:
                continue
            if key not in caps:
                caps[key] = 0
            if key not in draft_caps:
                draft_caps[key] = 0
            if caps[key] > HARD_CEILINGS[key]:
                raise LiveE2EError(f"armed {key} {caps[key]} exceeds hard ceiling {HARD_CEILINGS[key]}")
            if draft_caps[key] > HARD_CEILINGS[key]:
                raise LiveE2EError(f"committed draft {key} exceeds hard ceiling {HARD_CEILINGS[key]}")
            if caps[key] > draft_caps[key]:
                raise LiveE2EError(
                    f"armed {key} {caps[key]} exceeds committed draft cap {draft_caps[key]}"
                )
        draft_phase = phase_caps_from_grant(draft)
        for phase, limits in (caps.get("phase_caps") or {}).items():
            allowed = draft_phase.get(phase) or {}
            for key, value in limits.items():
                if key in HARD_CEILINGS and value > HARD_CEILINGS[key]:
                    raise LiveE2EError(
                        f"armed phase {phase} {key} {value} exceeds hard ceiling {HARD_CEILINGS[key]}"
                    )
                if key in allowed and value > allowed[key]:
                    raise LiveE2EError(
                        f"armed phase {phase} {key} {value} exceeds draft {allowed[key]}"
                    )
        caps["draft_artifact_hash"] = draft_hash
        caps["pinned_draft_hash"] = pinned
    for key in HARD_CEILINGS:
        if overrides.get(key) is not None:
            value = int(overrides[key])
            if value < 0:
                raise LiveE2EError(f"{key} cannot be negative")
            ceiling = caps.get(key)
            if ceiling is None:
                ceiling = HARD_CEILINGS[key]
                caps[key] = ceiling
            if value > ceiling:
                raise LiveE2EError(f"{key} cannot exceed grant ceiling {ceiling}")
            caps[key] = value
    for phase, limits in (caps.get("phase_caps") or {}).items():
        for key in ("leaderboard_requests", "leaderboard_units"):
            if limits.get(key) is None:
                continue
            if int(limits[key]) > HARD_CEILINGS[key]:
                raise LiveE2EError(
                    f"phase {phase} {key} {limits[key]} exceeds hard ceiling {HARD_CEILINGS[key]}"
                )
    return caps


def validate_config(raw):
    if raw.get("mode") not in ("dry-run", "live"):
        raise LiveE2EError("pass --dry-run or --live")
    grant_path = raw.get("grant_path")
    if not grant_path:
        raise LiveE2EError("grant file path is required")
    grant = load_grant(grant_path)
    if raw["mode"] == "live" and not grant.get("enabled"):
        raise LiveE2EError(grant.get("reason") or "grant disabled")
    if raw["mode"] == "live" and grant.get("authorization_id") in RETIRED_LIVE_DRAFTS:
        raise LiveE2EError(
            "2026-10-07, 2026-10-09 and 2026-10-11 drafts are retired for --live; "
            "use live-e2e-proof-2026-10-12-mitch"
        )
    if raw["mode"] == "live" and grant.get("authorization_id") not in LIVE_KNOWN_DRAFTS:
        raise LiveE2EError(f"live runner expects one of {sorted(LIVE_KNOWN_DRAFTS)}")
    if raw["mode"] == "live":
        assert_live_ledger_identity(grant)
    output_dir = Path(raw["output_dir"])
    authorization_id = grant.get("authorization_id")
    ledger_dir = raw.get("ledger_dir")
    try:
        store_path = grant_ledger_path(authorization_id, ledger_dir)
    except ValueError as error:
        raise LiveE2EError(str(error)) from error
    phases = parse_phases(raw.get("phases"))
    wallets_raw = raw.get("wallets")
    wallets = parse_wallets(wallets_raw)
    wallets_supplied = wallets_raw not in (None, "", [])
    tokens_raw = raw.get("birdeye_tokens")
    if isinstance(tokens_raw, str):
        raw["birdeye_tokens"] = [part.strip() for part in tokens_raw.split(",") if part.strip()]
    elif tokens_raw in (None, ""):
        raw["birdeye_tokens"] = []
    requested_discovery = raw.get("discovery_source") or BIRDEYE_DISCOVERY_GAINERS
    try:
        seed_sources = resolve_seed_sources(
            parse_seed_sources(raw.get("seed_source") or raw.get("seed_sources")),
            requested_discovery,
        )
    except SeedSourceError as error:
        raise LiveE2EError(str(error)) from error
    raw["seed_sources"] = seed_sources
    if requested_discovery in (BIRDEYE_DISCOVERY_GAINERS, BIRDEYE_DISCOVERY_TOP_TRADERS):
        raw["discovery_source"] = requested_discovery
    else:
        raw["discovery_source"] = primary_seed_source(seed_sources)
    if raw["discovery_source"] == BIRDEYE_DISCOVERY_TOP_TRADERS and not raw["birdeye_tokens"]:
        raw["birdeye_tokens"] = list(ESTABLISHED_LIQUID_MINTS)
    import_raw = raw.get("import_raw_dir") or raw.get("import_raw_dirs") or []
    if isinstance(import_raw, str):
        import_raw = [part.strip() for part in import_raw.split(",") if part.strip()]
    window_days = 30 if raw.get("window_days") is None else int(raw.get("window_days"))
    report_window_days = raw.get("report_window_days")
    if report_window_days not in (None, ""):
        report_window_days = int(report_window_days)
    else:
        report_window_days = None
    earlier = 60 if raw.get("earlier_history_days") is None else int(raw.get("earlier_history_days"))
    history_to_first = bool(raw.get("history_to_first"))
    history_start_unix = raw.get("history_start_unix")
    if history_start_unix not in (None, ""):
        history_start_unix = int(history_start_unix)
    else:
        history_start_unix = None
    caps = bind_caps_from_grant(grant, {
        "birdeye_requests": raw.get("max_birdeye_requests"),
        "birdeye_units": raw.get("max_birdeye_units"),
        "helius_requests": raw.get("max_helius_requests"),
        "helius_units": raw.get("max_helius_units"),
    }, mode=raw["mode"])
    if raw["mode"] == "live":
        presence = credential_presence()
        needs_birdeye = (
            1 in phases
            and (raw.get("discovery") or not wallets)
            and any(item in {SEED_BIRDEYE_TOP, SEED_TOKEN_INTERSECT} for item in seed_sources)
        )
        if needs_birdeye and not presence["birdeye"]:
            raise LiveE2EError("missing_provider_credentials: BIRDEYE_API_KEY")
        if (2 in phases or 3 in phases) and not presence["helius"]:
            raise LiveE2EError("missing_provider_credentials: HELIUS_API_KEY")
    bounds = window_bounds(
        window_days, earlier,
        history_to_first=history_to_first,
        history_start_unix=history_start_unix,
        report_window_days=report_window_days,
    )
    if history_to_first or history_start_unix is not None:
        earlier = bounds["earlier_history_days"]
    return {
        "mode": raw["mode"],
        "dry_run": raw["mode"] == "dry-run",
        "grant": grant,
        "grant_path": str(grant_path),
        "authorization_id": authorization_id,
        "output_dir": str(output_dir),
        "ledger_dir": str(ledger_dir) if ledger_dir else None,
        "store_path": str(store_path),
        "phases": phases,
        "wallets": wallets,
        "wallets_supplied": wallets_supplied,
        "discovery": bool(raw.get("discovery")),
        "discovery_source": raw.get("discovery_source") or BIRDEYE_DISCOVERY_GAINERS,
        "seed_sources": list(raw.get("seed_sources") or [raw.get("discovery_source") or BIRDEYE_DISCOVERY_GAINERS]),
        "nansen_enabled": bool(os.environ.get(NANSEN_KEY_ENV)),
        "birdeye_tokens": list(raw.get("birdeye_tokens") or []),
        "window_days": window_days,
        "report_window_days": bounds.get("report_window_days"),
        "earlier_history_days": earlier,
        "history_to_first": history_to_first,
        "history_start_unix": history_start_unix,
        "import_raw_dirs": list(import_raw),
        "bounds": bounds,
        "caps": caps,
        "per_wallet_cap": raw.get("per_wallet_cap"),
        "nansen_profile_cap": (
            int(raw["nansen_profile_cap"]) if raw.get("nansen_profile_cap") not in (None, "") else None
        ),
        "resume": bool(raw.get("resume")),
        "explicit_retry": bool(raw.get("explicit_retry")),
        "birdeye_limit": int(raw.get("birdeye_limit") or BIRDEYE_DEFAULT_LIMIT),
        "birdeye_window": raw.get("birdeye_window") or BIRDEYE_DEFAULT_WINDOW,
        "birdeye_sort": raw.get("birdeye_sort") or BIRDEYE_DEFAULT_SORT,
        "prescreen": {
            "min_in_window_tx": int(raw.get("min_in_window_tx") or 0),
            "max_unsupported_share": str(raw.get("max_unsupported_share") or "1"),
            "max_bot_rate": str(raw.get("max_bot_rate") or "1"),
        },
        "PRODUCT_READY": False,
    }


async def run_live_e2e(raw):
    config = validate_config(raw)
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / GTA_DOCS_NAME, gta_page_size_note())
    try:
        store, ledger_path = open_grant_store(config["authorization_id"], config.get("ledger_dir"))
    except ValueError as error:
        raise LiveE2EError(str(error)) from error
    grant_lock = ExclusiveLock(ledger_path / "GRANT.lock")
    output_lock = ExclusiveLock(output_dir / "RUN.lock")
    try:
        if not config.get("dry_run"):
            grant_lock.acquire()
        output_lock.acquire()
    except LockHeld as error:
        store.close()
        raise LiveE2EError(str(error)) from error
    try:
        if not config.get("dry_run"):
            store.put("configuration", "live_authorization", config["grant"])
        state = load_or_create_state(output_dir, config, resume=config["resume"])
        state["authorization_id"] = config["authorization_id"]
        if state.get("bounds"):
            persisted = state["bounds"]
            if persisted.get("window_days") != config["window_days"]:
                raise LiveE2EError(
                    f"--window-days {config['window_days']} disagrees with persisted "
                    f"{persisted.get('window_days')}"
                )
            persisted_htf = bool(persisted.get("history_to_first"))
            config_htf = bool(config.get("history_to_first") or config.get("history_start_unix") is not None)
            if persisted_htf != config_htf:
                raise LiveE2EError(
                    f"--history-to-first {config.get('history_to_first')} disagrees "
                    f"with persisted {persisted.get('history_to_first')}"
                )
            if persisted_htf:
                if persisted.get("history_start_unix") != config["bounds"]["history_start_unix"]:
                    raise LiveE2EError(
                        "--history-start-unix disagrees with persisted history_start_unix"
                    )
                config["earlier_history_days"] = persisted.get("earlier_history_days")
            elif persisted.get("earlier_history_days") != config["earlier_history_days"]:
                raise LiveE2EError(
                    f"--earlier-history-days {config['earlier_history_days']} disagrees "
                    f"with persisted {persisted.get('earlier_history_days')}"
                )
            new_report_days = config.get("report_window_days")
            persisted_report_days = persisted.get("report_window_days") or persisted.get("window_days")
            if new_report_days and int(new_report_days) != int(persisted_report_days or 0):
                end = _parse_iso(persisted["report_end_exclusive"])
                updated = window_bounds(
                    int(persisted["window_days"]),
                    int(persisted.get("earlier_history_days") or config["earlier_history_days"] or 0),
                    end=end,
                    history_to_first=persisted_htf,
                    history_start_unix=persisted.get("history_start_unix") if persisted_htf else None,
                    report_window_days=int(new_report_days),
                )
                config["bounds"] = updated
                state["bounds"] = dict(updated)
                # Stale Phase 4 rows were computed under the old window.
                # Never serve 30d RESULTS under a 90d bound (§9.2).
                state["phases_done"] = [
                    phase for phase in (state.get("phases_done") or []) if phase != 4
                ]
                state["phase4_wallets"] = []
            else:
                config["bounds"] = persisted
        else:
            state["bounds"] = dict(config["bounds"])
        try:
            verify_receipt_chain(store)
        except ValueError as error:
            raise LiveE2EError(f"ledger receipt chain failed: {error}") from error
        reconcile_state_spend(store, state)
        save_state(output_dir, state)
        recorder = RecorderTransport()
        plan = plan_request_counts(config, state)
        plan["within_caps"] = within_caps(plan, config["caps"])
        plan["gta_page_size"] = gta_page_size_note()
        plan["phase3_wallets"] = phase3_wallets(config, state)
        _write_json(output_dir / PLAN_NAME, plan)
        if not plan["within_caps"] and not config["dry_run"]:
            raise LiveE2EError("planned requests exceed grant/runner caps")
        phase4 = {"wallets": state.get("phase4_wallets") or []}
        status = "started"
        blocker = None
        try:
            done = set(state.get("phases_done") or [])
            identity = discovery_identity(config)
            discovery_done = identity in (state.get("discoveries") or {})
            if 1 in config["phases"] and (1 not in done or (config.get("discovery") and not discovery_done)):
                state["phase1"] = await phase1_discovery(store, config["grant"], config, state, recorder)
                apply_cheap_prescreen_phase1(config, state)
                state["phases_done"] = sorted(done | {1})
                done = set(state["phases_done"])
                save_state(output_dir, state)
            if not (config.get("wallets_supplied") and config.get("wallets")):
                loaded = discovered_seed_pool(config, state)
                if loaded:
                    config["wallets"] = list(loaded)
                    state["wallets"] = list(loaded)
            wanted = list(config.get("wallets") or [])
            if any(phase in config["phases"] for phase in (2, 3, 4)) and not wanted:
                produced = phase1_produced_seed_count(state)
                if produced:
                    raise SourceError(
                        "EMPTY_SEED_POOL",
                        f"phase {sorted(set(config['phases']) & {2, 3, 4})} has an empty "
                        f"wallet pool but phase 1 produced {produced} seeds; "
                        "resume must load the run's own phase-1 output",
                    )
            phase2_pending = [
                addr for addr in wanted
                if not ((state.get("phase2") or {}).get(addr) or {}).get("done")
            ]
            if 2 in config["phases"] and (2 not in done or phase2_pending):
                state["phase2_result"] = await phase2_prescreen(store, config["grant"], config, state, recorder)
                still = [
                    addr for addr in wanted
                    if not ((state.get("phase2") or {}).get(addr) or {}).get("done")
                ]
                if still:
                    state["phases_done"] = sorted(item for item in done if item != 2)
                    raise SourceError(
                        "INCOMPLETE_SCOPE",
                        f"phase 2 has {len(still)} unscreened wallets; not completed",
                    )
                state["phases_done"] = sorted(done | {2})
                done = set(state["phases_done"])
                save_state(output_dir, state)
            wanted3 = phase3_wallets(config, state)
            phase3_pending = [
                addr for addr in wanted3
                if not ((state.get("phase3") or {}).get(addr) or {}).get("done")
            ]
            if 3 in config["phases"] and (3 not in done or phase3_pending):
                state["phase3_result"] = await phase3_history(store, config["grant"], config, state, recorder)
                still3 = [
                    addr for addr in wanted3
                    if not ((state.get("phase3") or {}).get(addr) or {}).get("done")
                ]
                if still3:
                    state["phases_done"] = sorted(item for item in done if item != 3)
                    raise SourceError(
                        "INCOMPLETE_SCOPE",
                        f"phase 3 has {len(still3)} unfinished wallets; not completed",
                    )
                state["phases_done"] = sorted(done | {3})
                done = set(state["phases_done"])
                save_state(output_dir, state)
            wanted4 = phase4_targets(config, state)
            already4 = {
                row.get("address")
                for row in (state.get("phase4_wallets") or [])
                if isinstance(row, dict) and row.get("address")
            }
            pending4 = [addr for addr in wanted4 if addr not in already4]
            if 4 in config["phases"] and (4 not in done or pending4):
                if not wanted4:
                    phase4 = {"wallets": [], "processed": 0}
                    state["phase4_wallets"] = []
                    # Never mark Phase 4 done when nothing was processed.
                else:
                    prior = {
                        row.get("address"): row
                        for row in (state.get("phase4_wallets") or [])
                        if isinstance(row, dict) and row.get("address")
                    }
                    replay_config = dict(config)
                    replay_config["wallets"] = wanted4
                    phase4 = phase4_offline(store, replay_config, state)
                    processed = phase4.get("wallets") or []
                    for row in processed:
                        if row.get("address"):
                            prior[row["address"]] = row
                    state["phase4_wallets"] = list(prior.values())
                    phase4 = {"wallets": state["phase4_wallets"]}
                    if processed:
                        state["phases_done"] = sorted(set(done) | {4})
                        done = set(state["phases_done"])
                save_state(output_dir, state)
            else:
                phase4 = {"wallets": state.get("phase4_wallets") or []}
            pending = [
                addr for addr in wanted
                if 2 in config["phases"]
                and not ((state.get("phase2") or {}).get(addr) or {}).get("done")
            ]
            if pending:
                state["status"] = "incomplete"
                state["blocker"] = "unprocessed_wallets"
                state["detail"] = f"{len(pending)} wallets not yet screened"
                status = "incomplete"
                blocker = "unprocessed_wallets"
            else:
                state["status"] = "completed"
                state["blocker"] = None
                state["detail"] = None
                status = "completed"
                blocker = None
        except BaseException as error:
            state["status"] = "blocked"
            state["blocker"] = getattr(error, "state", None) or error.__class__.__name__
            state["detail"] = redact_text(str(error))
            phase4 = {"wallets": state.get("phase4_wallets") or []}
            status = "blocked"
            blocker = state["blocker"]
            save_state(output_dir, state)
            if not isinstance(error, Exception):
                raise
        save_state(output_dir, state)
        results = {
            "kind": "live-e2e-results-v1",
            "status": status,
            "blocker": blocker,
            "detail": redact_text(state.get("detail") or ""),
            "dry_run": config["dry_run"],
            "authorization_id": config["authorization_id"],
            "grant_enabled": bool(config["grant"].get("enabled")),
            "phases": list(config["phases"]),
            "bounds": config["bounds"],
            "spend": state["spend"],
            "phase_spend": state.get("phase_spend"),
            "plan": plan,
            "recorder_calls": recorder.calls,
            "phase1": state.get("phase1"),
            "phase2": state.get("phase2_result"),
            "phase3": state.get("phase3_result"),
            "wallets": phase4.get("wallets") or [],
            "PRODUCT_READY": False,
        }
        audit_worthy = {}
        for row in results["wallets"]:
            if not (row.get("independently_audited") or row.get("audit_status") == "independently_audited"):
                continue
            for source in row.get("seed_sources") or ([row.get("seed_source")] if row.get("seed_source") else []):
                audit_worthy[source] = int(audit_worthy.get(source) or 0) + 1
        results["cost_per_audit_worthy"] = cost_per_audit_worthy(state.get("source_spend") or {}, audit_worthy)
        results["seed_is_not"] = "evidence"
        results["count_kinds"] = list(COUNT_KINDS)
        _write_json(output_dir / RESULTS_NAME, redact_secrets(results))
        (output_dir / SUMMARY_NAME).write_text(redact_text(human_summary(results)), encoding="utf-8")
        return results
    finally:
        output_lock.release()
        grant_lock.release()
        store.close()


def build_arg_parser():
    parser = argparse.ArgumentParser(description="LIVE E2E proof runner. Use --dry-run before any spend.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Recorder transport; no provider HTTP")
    mode.add_argument("--live", action="store_true", help="Operator-box live path; requires armed grant and keys")
    parser.add_argument("--grant", dest="grant_path", required=True)
    parser.add_argument("--phases", default="all")
    parser.add_argument("--wallets", default="")
    parser.add_argument("--discovery", action="store_true")
    parser.add_argument(
        "--discovery-source",
        dest="discovery_source",
        default=BIRDEYE_DISCOVERY_GAINERS,
        choices=(BIRDEYE_DISCOVERY_GAINERS, BIRDEYE_DISCOVERY_TOP_TRADERS),
        help="Legacy alias for --seed-source gainers-losers|top-traders.",
    )
    parser.add_argument(
        "--seed-source",
        dest="seed_source",
        default="",
        help=(
            "Comma-separated Phase 1 seeds: birdeye_top, token_intersect, nansen "
            "(aliases: gainers-losers, top-traders, early-buyers-durable, "
            "smart-money-leaderboard). Combinable. Optional prescreen-filter. "
            "A seed is never evidence. Overrides --discovery-source."
        ),
    )
    parser.add_argument(
        "--birdeye-tokens",
        dest="birdeye_tokens",
        default="",
        help="Comma-separated liquid token mints for --discovery-source top-traders",
    )
    parser.add_argument("--window-days", dest="window_days", type=int, default=30)
    parser.add_argument(
        "--report-window-days",
        dest="report_window_days",
        type=int,
        help="Optional longer report window (default = --window-days, typically 30)",
    )
    parser.add_argument("--earlier-history-days", dest="earlier_history_days", type=int, default=60)
    parser.add_argument(
        "--history-to-first",
        dest="history_to_first",
        action="store_true",
        help="Fetch each wallet back to its first transaction (or --history-start-unix) under --per-wallet-cap",
    )
    parser.add_argument(
        "--history-start-unix",
        dest="history_start_unix",
        type=int,
        help="Optional earlier bound (Unix seconds) when --history-to-first is set",
    )
    parser.add_argument("--per-wallet-cap", dest="per_wallet_cap", type=int)
    parser.add_argument(
        "--nansen-profile-cap",
        dest="nansen_profile_cap",
        type=int,
        help="Max Nansen pnl-summary calls after the two leaderboard pages. Plan equals this bound.",
    )
    parser.add_argument("--max-birdeye-requests", dest="max_birdeye_requests", type=int)
    parser.add_argument("--max-birdeye-units", dest="max_birdeye_units", type=int)
    parser.add_argument("--max-helius-requests", dest="max_helius_requests", type=int)
    parser.add_argument("--max-helius-units", dest="max_helius_units", type=int)
    parser.add_argument("--birdeye-limit", dest="birdeye_limit", type=int, default=100)
    parser.add_argument("--birdeye-window", dest="birdeye_window", default="30d")
    parser.add_argument("--birdeye-sort", dest="birdeye_sort", default=BIRDEYE_TOP_TRADERS_DEFAULT_SORT)
    parser.add_argument("--min-in-window-tx", dest="min_in_window_tx", type=int, default=0)
    parser.add_argument("--max-unsupported-share", dest="max_unsupported_share", default="1")
    parser.add_argument("--max-bot-rate", dest="max_bot_rate", default="1")
    parser.add_argument("--output", dest="output_dir", required=True)
    parser.add_argument("--store", dest="store_path")
    parser.add_argument("--ledger-dir", dest="ledger_dir", help="Grant-scoped spend ledger root (outside output)")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--explicit-retry", dest="explicit_retry", action="store_true",
                        help="Re-send a failed request; consumed successes are never re-sent")
    parser.add_argument(
        "--import-raw-dir",
        dest="import_raw_dir",
        action="append",
        default=[],
        help="Prior raw-page tree; import paid pages by verified ledger sha (no re-send)",
    )
    return parser


def _install_redacting_excepthook():
    def hook(exc_type, exc, tb):
        sys.stderr.write(redact_text(f"{getattr(exc_type, '__name__', 'Error')}: {exc}\n"))

    sys.excepthook = hook


def main(argv=None):
    _install_redacting_excepthook()
    try:
        args = build_arg_parser().parse_args(argv)
        raw = vars(args)
        raw["mode"] = "dry-run" if args.dry_run else "live"
        tokens = raw.get("birdeye_tokens")
        if isinstance(tokens, str) and tokens.strip():
            raw["birdeye_tokens"] = [part.strip() for part in tokens.split(",") if part.strip()]
        elif not tokens:
            raw["birdeye_tokens"] = []
        result = asyncio.run(run_live_e2e(raw))
    except BaseException as error:
        if isinstance(error, SystemExit):
            raise
        text = redact_text(f"{error.__class__.__name__}: {error}")
        print(text, file=sys.stderr)
        if isinstance(error, KeyboardInterrupt):
            return 130
        if isinstance(error, (LiveE2EError, SourceError, QuotaExceeded, LockHeld, Exception)):
            return 2
        raise
    print(json.dumps(redact_secrets({
        "status": result["status"],
        "dry_run": result["dry_run"],
        "spend": result["spend"],
        "plan_totals": result["plan"]["totals"],
        "within_caps": result["plan"]["within_caps"],
        "PRODUCT_READY": False,
    }), indent=2))
    if result.get("status") == "blocked":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
