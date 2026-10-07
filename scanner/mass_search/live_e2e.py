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
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from scanner.investigation import (
    DFLOW,
    JUPITER,
    METEORA_DAMM_V2,
    OKX_DEX_ROUTER,
    PUMP,
    PUMP_SWAP,
    RAYDIUM_AMM,
    RAYDIUM_CPMM,
    REVIEWED_OUTER_VENUES,
    RFQ_FILL,
    TOKEN_2022_ID,
    WHIRLPOOL,
    decode_supported_swaps,
)
from scanner.mass_search.adapters import ALLOWED_BIRDEYE_HOST, ALLOWED_BIRDEYE_PATH, BirdeyeTraderAdapter, SourceError
from scanner.mass_search.capability import LIVE_AUTH_SCHEMA, redact_secrets, utc_now, validate_live_authorization
from scanner.mass_search.evidence_integrity import sanitize_jsonrpc_body
from scanner.mass_search.history_ingest import replay_cached_history_to_report
from scanner.mass_search.labels import wallet_status_fields
from scanner.mass_search.qualification_gates import coverage_shares, qualifying_profit
from scanner.mass_search.research_profile import build_research_profile, default_filters, independently_audited
from scanner.mass_search.workflow import _authoritative_saved_profile
from scanner.storage import QuotaExceeded, Store

ROOT = Path(__file__).resolve().parents[2]
AUTHORIZATION_ID = "live-e2e-proof-2026-10-07-mitch"
DRAFT_REL = "config/live_authorization.live-e2e-proof-2026-10-07-mitch-draft.json"
DRAFT_PATH = ROOT / DRAFT_REL
BIRDEYE_KEY_ENV = "BIRDEYE_API_KEY"
HELIUS_KEY_ENV = "HELIUS_API_KEY"
HELIUS_ENDPOINT = "https://mainnet.helius-rpc.com/"
HELIUS_METHOD = "getTransactionsForAddress"

GTA_MAX_LIMIT = 1000
GTA_SAMPLE_LIMIT = 100
SIG_ONLY_UNITS = 10
FULL_100_UNITS = 10
FULL_1000_UNITS = 100
BIRDEYE_UNITS = 30
BIRDEYE_DEFAULT_LIMIT = 100
BIRDEYE_DEFAULT_WINDOW = "30d"
BIRDEYE_DEFAULT_SORT = "trader_score"

L2TEX_PROGRAM = "L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95"
KNOWN_BLOCKING_PROGRAMS = {
    OKX_DEX_ROUTER: "OKX SwapTob",
    DFLOW: "DFlow",
    L2TEX_PROGRAM: "L2TExMFK",
    RFQ_FILL: "RFQ",
    TOKEN_2022_ID: "Token-2022 observed-only",
}
SUPPORTED_PROGRAMS = frozenset(REVIEWED_OUTER_VENUES) | {
    JUPITER, PUMP, PUMP_SWAP, RAYDIUM_CPMM, RAYDIUM_AMM, WHIRLPOOL, METEORA_DAMM_V2,
}
INFRA_PROGRAMS = frozenset({
    "11111111111111111111111111111111",
    "ComputeBudget111111111111111111111111111111",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr",
    "Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo",
})
STATE_NAME = "RUN_STATE.json"
PLAN_NAME = "DRY_RUN_PLAN.json"
RESULTS_NAME = "RESULTS.json"
SUMMARY_NAME = "SUMMARY.md"
GTA_DOCS_NAME = "GTA_PAGE_SIZE.md"
RECEIPT_KIND = "live_e2e_receipt"

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
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
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


def parse_wallets(value):
    if value in (None, "", []):
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    path = Path(value)
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
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


def window_bounds(window_days, earlier_history_days, *, end=None):
    if type(window_days) is not int or not 1 <= window_days <= 365:
        raise LiveE2EError("window_days must be an integer 1-365")
    if type(earlier_history_days) is not int or not 0 <= earlier_history_days <= 365:
        raise LiveE2EError("earlier_history_days must be an integer 0-365")
    end = end or datetime.now(timezone.utc).replace(microsecond=0)
    report_start = end - timedelta(days=window_days)
    history_start = report_start - timedelta(days=earlier_history_days)
    return {
        "report_end_exclusive": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "report_start_inclusive": report_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "history_start_inclusive": history_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "report_start_unix": int(report_start.timestamp()),
        "report_end_unix": int(end.timestamp()),
        "history_start_unix": int(history_start.timestamp()),
        "window_days": window_days,
        "earlier_history_days": earlier_history_days,
    }


def gta_options(*, details, limit, start_unix, end_unix, pagination_token=None):
    if details not in ("signatures", "full"):
        raise LiveE2EError("GTA transactionDetails must be signatures or full")
    if type(limit) is not int or not 1 <= limit <= GTA_MAX_LIMIT:
        raise LiveE2EError(f"GTA limit must be 1-{GTA_MAX_LIMIT}")
    options = {
        "transactionDetails": details,
        "limit": limit,
        "sortOrder": "desc",
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
    found = []

    def walk(node):
        if isinstance(node, dict):
            for key in ("programId", "program_id", "program"):
                value = node.get(key)
                if isinstance(value, str) and 32 <= len(value) <= 44:
                    found.append(value)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(records)
    return found


def classify_programs(records):
    counts = {}
    for program in collect_program_ids(records):
        counts[program] = counts.get(program, 0) + 1
    blockers = []
    seen = set()
    for program, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        if program in INFRA_PROGRAMS:
            continue
        label = KNOWN_BLOCKING_PROGRAMS.get(program)
        if label and program not in seen:
            seen.add(program)
            blockers.append({
                "program_id": program,
                "label": label,
                "observations": count,
                "supported": False,
            })
        elif program not in SUPPORTED_PROGRAMS and program not in seen:
            seen.add(program)
            blockers.append({
                "program_id": program,
                "label": "unsupported_or_unreviewed",
                "observations": count,
                "supported": False,
            })
    supported_hits = sum(count for program, count in counts.items() if program in SUPPORTED_PROGRAMS)
    blocking_hits = sum(row["observations"] for row in blockers)
    total = supported_hits + blocking_hits
    return {
        "program_counts": counts,
        "blockers": blockers,
        "supported_observations": supported_hits,
        "unsupported_observations": blocking_hits,
        "decodable_share": None if not total else str((Decimal(supported_hits) / Decimal(total)).quantize(Decimal("0.0001"))),
    }


def plan_request_counts(config):
    wallets = list(config["wallets"])
    phases = set(config["phases"])
    discovery = bool(config.get("discovery"))
    birdeye_requests = 1 if 1 in phases and (discovery or not wallets) else 0
    if 1 in phases and wallets and not discovery:
        birdeye_requests = 0
    n = len(wallets)
    helius_phase2 = (2 * n) if 2 in phases else 0
    helius_phase3 = n if 3 in phases else 0
    birdeye_units = birdeye_requests * BIRDEYE_UNITS
    helius_units = 0
    if 2 in phases:
        helius_units += n * (SIG_ONLY_UNITS + FULL_100_UNITS)
    if 3 in phases:
        helius_units += n * FULL_1000_UNITS
    return {
        "kind": "live-e2e-request-plan-v1",
        "dry_run": True,
        "phases": list(config["phases"]),
        "wallet_count": n,
        "per_phase": {
            "1": {
                "provider": "birdeye",
                "requests": birdeye_requests,
                "units": birdeye_units,
                "billing_unit": "birdeye_compute_unit",
                "note": "0 when a wallet list is supplied without --discovery",
            },
            "2": {
                "provider": "helius",
                "requests": helius_phase2,
                "units": n * (SIG_ONLY_UNITS + FULL_100_UNITS) if 2 in phases else 0,
                "billing_unit": "helius_credit",
                "note": "1 signatures-only (limit 1000, 10 CU) + 1 full sample (limit 100, 10 CU) per wallet",
            },
            "3": {
                "provider": "helius",
                "requests": helius_phase3,
                "units": n * FULL_1000_UNITS if 3 in phases else 0,
                "billing_unit": "helius_credit",
                "note": (
                    "Dry-run recorder returns empty pages, so paging stops after "
                    "one full limit=1000 page per wallet. Live continues until "
                    "the window is covered or the cap is hit. Units are the "
                    "documented worst case (100 credits / 1000 txs)."
                ),
            },
            "4": {"provider": None, "requests": 0, "units": 0, "note": "offline only"},
        },
        "totals": {
            "birdeye_requests": birdeye_requests,
            "birdeye_units": birdeye_units,
            "helius_requests": helius_phase2 + helius_phase3,
            "helius_units": helius_units,
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
    )


class RecorderTransport:
    """Records planned provider calls. Never opens a socket."""

    def __init__(self):
        self.calls = []

    async def birdeye(self, method, path, params):
        self.calls.append({
            "provider": "birdeye",
            "method": method,
            "path": path,
            "params": dict(params or {}),
            "units": BIRDEYE_UNITS,
        })
        return {
            "status": 200,
            "fetched_at": utc_now(),
            "body": {"data": {"items": []}},
            "raw_bytes": b'{"data":{"items":[]}}',
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
        "phase2": {},
        "phase3": {},
        "receipts": {},
        "spend": {
            "birdeye_requests": 0,
            "birdeye_units": 0,
            "helius_requests": 0,
            "helius_units": 0,
        },
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


def _receipt_key(provider, attempt):
    return f"{provider}:{attempt}"


def consume_receipt(store, grant, provider, attempt, payload):
    key = _receipt_key(provider, attempt)
    existing = store.get(RECEIPT_KIND, key)
    if existing and existing.get("consumed") is True:
        raise LiveE2EError(f"receipt already consumed: {key}")
    receipt = {
        "response_id": payload.get("response_id") or uuid.uuid4().hex,
        "provider": provider,
        "attempt": attempt,
        "authorization_id": grant.get("authorization_id"),
        "consumed": True,
        "sha256": payload.get("sha256"),
        "units": payload.get("units"),
    }
    store.put(RECEIPT_KIND, key, receipt)
    return receipt


def remaining_caps(config, spend):
    caps = config["caps"]
    return {
        "birdeye_requests": caps["birdeye_requests"] - spend["birdeye_requests"],
        "birdeye_units": caps["birdeye_units"] - spend["birdeye_units"],
        "helius_requests": caps["helius_requests"] - spend["helius_requests"],
        "helius_units": caps["helius_units"] - spend["helius_units"],
    }


def hard_stop_if_needed(config, spend, *, provider, units):
    left = remaining_caps(config, spend)
    if provider == "birdeye":
        if left["birdeye_requests"] < 1 or left["birdeye_units"] < units:
            raise SourceError("RATE_LIMITED", "Birdeye cap reached; hard stop")
    else:
        if left["helius_requests"] < 1 or left["helius_units"] < units:
            raise SourceError("RATE_LIMITED", "Helius cap reached; hard stop")


async def _live_birdeye(method, path, params):
    key = os.environ.get(BIRDEYE_KEY_ENV)
    if not key:
        raise SourceError("UNAUTHORIZED", "BIRDEYE_API_KEY is not present in this runtime")
    if path != ALLOWED_BIRDEYE_PATH:
        raise SourceError("UNAUTHORIZED", "Birdeye path is not allowlisted")
    import httpx

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
    return {
        "status": response.status_code,
        "body": body,
        "fetched_at": utc_now(),
        "raw_bytes": raw,
    }


async def _live_helius(address, *, options, page_index=0):
    key = os.environ.get(HELIUS_KEY_ENV) or os.environ.get("HELIUS_KEY")
    if not key:
        raise SourceError("UNAUTHORIZED", "HELIUS_API_KEY is not present in this runtime")
    import httpx

    payload = {"jsonrpc": "2.0", "id": page_index + 1, "method": HELIUS_METHOD, "params": [address, options]}
    async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(40, connect=10)) as client:
        response = await client.post(HELIUS_ENDPOINT, params={"api-key": key}, json=payload)
    raw = response.content
    status = response.status_code
    if status in (401, 403):
        raise SourceError("ENTITLEMENT_BLOCKED", "Helius rejected the key or plan", http_status=status)
    if status == 429:
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


def _save_raw(output_dir, relative, raw_bytes):
    path = Path(output_dir) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    data = raw_bytes if isinstance(raw_bytes, (bytes, bytearray)) else bytes(raw_bytes)
    path.write_bytes(data)
    digest = _sha256_bytes(data)
    written = path.read_bytes()
    if _sha256_bytes(written) != digest:
        raise LiveE2EError("raw response checksum mismatch after write")
    return digest


async def _dispatch_helius(store, grant, config, state, transport, address, options, *, phase, page_index):
    entry = provider_entry(grant, "helius")
    units = documented_units(options.get("transactionDetails"), int(options.get("limit") or 0))
    hard_stop_if_needed(config, state["spend"], provider="helius", units=units)
    if config.get("per_wallet_cap") is not None:
        used = int((state.get("phase3") or {}).get(address, {}).get("requests") or 0)
        used += int((state.get("phase2") or {}).get(address, {}).get("requests") or 0)
        if used >= int(config["per_wallet_cap"]):
            raise SourceError("RATE_LIMITED", "Per-wallet request cap reached; hard stop")
    reservation = None
    if not config.get("dry_run"):
        reservation = store.reserve("helius", HELIUS_METHOD, units, entry["cycle_start"], entry["max_units"])
        store.dispatch(reservation)
    try:
        result = await transport(address, options=options, page_index=page_index)
        if reservation:
            store.settle(reservation, charge=True)
    except Exception:
        if reservation:
            try:
                store.settle(reservation, charge=True)
            except ValueError:
                pass
        raise
    raw = result.get("raw_bytes") or b""
    digest = _save_raw(
        config["output_dir"],
        f"raw/phase{phase}/{address}/page{page_index}.bin",
        raw,
    )
    attempt = state["spend"]["helius_requests"] + 1
    consume_receipt(store, grant, "helius", attempt, {"sha256": digest, "units": units})
    state["spend"]["helius_requests"] += 1
    state["spend"]["helius_units"] += units
    return {**result, "evidence_sha256": digest, "units": units}


async def phase1_discovery(store, grant, config, state, recorder):
    if 1 not in config["phases"]:
        return {"skipped": True}
    if config["wallets"] and not config.get("discovery"):
        return {"skipped": True, "reason": "wallet_list_supplied"}
    hard_stop_if_needed(config, state["spend"], provider="birdeye", units=BIRDEYE_UNITS)
    params = {
        "type": config.get("birdeye_window") or BIRDEYE_DEFAULT_WINDOW,
        "sort_by": config.get("birdeye_sort") or BIRDEYE_DEFAULT_SORT,
        "sort_type": "desc",
        "offset": 0,
        "limit": int(config.get("birdeye_limit") or BIRDEYE_DEFAULT_LIMIT),
    }
    reservation = None
    if config["dry_run"]:
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
        try:
            adapter = BirdeyeTraderAdapter(transport=_live_birdeye)
            page = await adapter.fetch_page(
                offset=0,
                limit=int(params["limit"]),
                window=params["type"],
                authorization=grant,
                store=store,
                sort_by=params["sort_by"],
                sort_type="desc",
            )
            store.settle(reservation, charge=True)
        except Exception:
            if reservation:
                try:
                    store.settle(reservation, charge=True)
                except ValueError:
                    pass
            raise
        raw = json.dumps(redact_secrets(page.get("raw_body") or {}), sort_keys=True, separators=(",", ":")).encode()
        addresses = [row["address"] for row in (page.get("rows") or []) if row.get("valid") and row.get("address")]
    digest = _save_raw(config["output_dir"], "raw/phase1/birdeye.bin", raw)
    consume_receipt(store, grant, "birdeye", 1, {"sha256": digest, "units": BIRDEYE_UNITS})
    state["spend"]["birdeye_requests"] += 1
    state["spend"]["birdeye_units"] += BIRDEYE_UNITS
    if not config["wallets"]:
        config["wallets"] = addresses
        state["wallets"] = list(addresses)
    return {"addresses": addresses, "sha256": digest, "count": len(addresses)}


async def phase2_prescreen(store, grant, config, state, recorder):
    if 2 not in config["phases"]:
        return {"skipped": True}
    bounds = config["bounds"]
    transport = recorder.helius if config["dry_run"] else _live_helius
    thresholds = config.get("prescreen") or {}
    min_in_window = int(thresholds.get("min_in_window_tx") or 0)
    max_unsupported_share = Decimal(str(thresholds.get("max_unsupported_share") or "1"))
    max_bot_rate = Decimal(str(thresholds.get("max_bot_rate") or "1"))
    rows = []
    for address in config["wallets"]:
        if address in (state.get("phase2") or {}) and (state["phase2"][address] or {}).get("done"):
            rows.append(state["phase2"][address])
            continue
        sig_opts = gta_options(
            details="signatures",
            limit=GTA_MAX_LIMIT,
            start_unix=bounds["report_start_unix"],
            end_unix=bounds["report_end_unix"],
        )
        sigs = await _dispatch_helius(store, grant, config, state, transport, address, sig_opts, phase=2, page_index=0)
        sample_opts = gta_options(
            details="full",
            limit=GTA_SAMPLE_LIMIT,
            start_unix=bounds["history_start_unix"],
            end_unix=bounds["report_end_unix"],
        )
        sample = await _dispatch_helius(store, grant, config, state, transport, address, sample_opts, phase=2, page_index=1)
        programs = classify_programs(sample.get("records") or [])
        in_window = len(sigs.get("records") or [])
        unsupported_share = Decimal(programs["decodable_share"] or "1")
        unsupported_share = Decimal("1") - unsupported_share if programs["decodable_share"] is not None else Decimal("0")
        bot_rate = Decimal("0")
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
        row = {
            "address": address,
            "in_window_tx_count": in_window,
            "sample_records": len(sample.get("records") or []),
            "decodable_share": programs["decodable_share"],
            "unsupported_share": str(unsupported_share),
            "program_blockers": programs["blockers"],
            "coverability_rank_key": programs["decodable_share"] or "0",
            "dropped": dropped,
            "drop_reason": drop_reason,
            "requests": 2,
            "done": True,
        }
        state.setdefault("phase2", {})[address] = row
        save_state(config["output_dir"], state)
        rows.append(row)
    ranked = sorted(rows, key=lambda row: (row.get("dropped") is True, -float(row.get("coverability_rank_key") or 0), row["address"]))
    kept = [row["address"] for row in ranked if not row.get("dropped")]
    return {"wallets": ranked, "kept": kept}


async def phase3_history(store, grant, config, state, recorder):
    if 3 not in config["phases"]:
        return {"skipped": True}
    bounds = config["bounds"]
    transport = recorder.helius if config["dry_run"] else _live_helius
    kept = [
        row["address"]
        for row in ((state.get("phase2") or {}).values() if state.get("phase2") else [{"address": a, "dropped": False} for a in config["wallets"]])
        if not (isinstance(row, dict) and row.get("dropped"))
    ]
    if not kept:
        kept = list(config["wallets"])
    pages = {}
    for address in kept:
        cursor = (state.get("phase3") or {}).get(address) or {"pages": 0, "requests": 0, "done": False}
        if cursor.get("done"):
            pages[address] = cursor
            continue
        token = cursor.get("pagination_token")
        while True:
            options = gta_options(
                details="full",
                limit=GTA_MAX_LIMIT,
                start_unix=bounds["history_start_unix"],
                end_unix=bounds["report_end_unix"],
                pagination_token=token,
            )
            result = await _dispatch_helius(
                store, grant, config, state, transport, address, options,
                phase=3, page_index=cursor["pages"],
            )
            cursor["pages"] += 1
            cursor["requests"] = cursor.get("requests", 0) + 1
            cursor["pagination_token"] = result.get("pagination_token")
            cursor["last_sha256"] = result.get("evidence_sha256")
            token = result.get("pagination_token")
            records = result.get("records") or []
            oldest = None
            for row in records:
                stamp = row.get("blockTime") or row.get("timestamp") or ((row.get("transaction") or {}).get("blockTime"))
                if type(stamp) is int:
                    oldest = stamp if oldest is None else min(oldest, stamp)
            covered = not token or not records or (oldest is not None and oldest <= bounds["history_start_unix"])
            if covered or config["dry_run"]:
                cursor["done"] = True
                cursor["window_covered"] = bool(covered)
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
    return {
        "address": report.get("address"),
        "coverage_count_share": shares.get("coverage_count_share"),
        "coverage_value_share": shares.get("coverage_value_share"),
        "coverage_mandatory_share": shares.get("coverage_mandatory_share"),
        "completed_trades": (profile or {}).get("completed_known_cost_positions"),
        "sample_positions": (profile or {}).get("sample_positions"),
        "realized_pnl_sol": ((profile or {}).get("scoped_pnl_by_quote_asset") or {}).get("SOL"),
        "realized_pnl_usdc": ((profile or {}).get("scoped_pnl_by_quote_asset") or {}).get("USDC"),
        "completed_episode_net": (profile or {}).get("completed_episode_net"),
        "completed_episode_net_unit": (profile or {}).get("completed_episode_net_unit"),
        "qualifying_profit": str(profit) if profit is not None else None,
        "qualifying_unit": unit,
        "audit_status": ((profile or {}).get("independent_audit") or {}).get("status") or "not_independently_audited",
        "independently_audited": independently_audited(report, profile),
        "lead_level": level.get("level") or "insufficient_evidence",
        "blocker": blocker,
        "coverage_status": fields.get("coverage_status"),
        "program_blockers": ((report.get("prescreen") or {}).get("program_blockers")),
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
        if raw_dir.is_dir():
            for path in sorted(raw_dir.glob("page*.bin")):
                try:
                    body = json.loads(path.read_bytes().decode("utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    continue
                result = body.get("result") if isinstance(body, dict) else None
                data = (result or {}).get("data") if isinstance(result, dict) else result
                if isinstance(data, list):
                    records.extend(data)
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
                "program_blockers": ((state.get("phase2") or {}).get(address) or {}).get("program_blockers") or [],
                "PRODUCT_READY": False,
            })
            continue
        decoded = decode_supported_swaps(records, address)
        result = replay_cached_history_to_report(
            store,
            address=address,
            records=records,
            window_start=bounds["report_start_inclusive"],
            window_end=bounds["report_end_exclusive"],
            acquisition_start=bounds["history_start_inclusive"],
            corpus_kind="GENUINE_LIVE",
            authorization_id=config.get("authorization_id") or AUTHORIZATION_ID,
            source_id="live-e2e-proof",
        )
        report = result["report"]
        report["prescreen"] = (state.get("phase2") or {}).get(address) or {}
        profile = build_research_profile(report, filters=default_filters(), decoded=decoded)
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
        "## Wallets",
        "",
    ]
    for row in (results.get("wallets") or []):
        lines.append(
            f"- {row.get('address')}: coverage count={row.get('coverage_count_share')} "
            f"value={row.get('coverage_value_share')}; completed={row.get('completed_trades')}; "
            f"PnL SOL={row.get('realized_pnl_sol')} USDC={row.get('realized_pnl_usdc')}; "
            f"audit={row.get('audit_status')}; level={row.get('lead_level')}; "
            f"blocker={row.get('blocker')}"
        )
        blockers = row.get("program_blockers") or []
        if blockers:
            labels = ", ".join(f"{item.get('label')} ({item.get('program_id')})" for item in blockers)
            lines.append(f"  program blockers: {labels}")
    lines.append("")
    return "\n".join(lines) + "\n"


def bind_caps_from_grant(grant, overrides):
    birdeye = provider_entry(grant, "birdeye")
    helius = provider_entry(grant, "helius")
    caps = {
        "birdeye_requests": int(birdeye.get("max_requests") or 0),
        "birdeye_units": int(birdeye.get("max_units") or 0),
        "helius_requests": int(helius.get("max_requests") or 0),
        "helius_units": int(helius.get("max_units") or 0),
    }
    for key in caps:
        if overrides.get(key) is not None:
            value = int(overrides[key])
            if value < 0:
                raise LiveE2EError(f"{key} cannot be negative")
            if value > caps[key]:
                raise LiveE2EError(f"{key} cannot exceed grant ceiling {caps[key]}")
            caps[key] = value
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
    if raw["mode"] == "live" and grant.get("authorization_id") != AUTHORIZATION_ID:
        raise LiveE2EError(f"live runner expects {AUTHORIZATION_ID}")
    output_dir = Path(raw["output_dir"])
    store_path = Path(raw.get("store_path") or (output_dir / "store"))
    phases = parse_phases(raw.get("phases"))
    wallets = parse_wallets(raw.get("wallets"))
    window_days = 30 if raw.get("window_days") is None else int(raw.get("window_days"))
    earlier = 60 if raw.get("earlier_history_days") is None else int(raw.get("earlier_history_days"))
    caps = bind_caps_from_grant(grant, {
        "birdeye_requests": raw.get("max_birdeye_requests"),
        "birdeye_units": raw.get("max_birdeye_units"),
        "helius_requests": raw.get("max_helius_requests"),
        "helius_units": raw.get("max_helius_units"),
    })
    if raw["mode"] == "live":
        presence = credential_presence()
        if 1 in phases and (raw.get("discovery") or not wallets) and not presence["birdeye"]:
            raise LiveE2EError("missing_provider_credentials: BIRDEYE_API_KEY")
        if (2 in phases or 3 in phases) and not presence["helius"]:
            raise LiveE2EError("missing_provider_credentials: HELIUS_API_KEY")
    return {
        "mode": raw["mode"],
        "dry_run": raw["mode"] == "dry-run",
        "grant": grant,
        "grant_path": str(grant_path),
        "authorization_id": grant.get("authorization_id"),
        "output_dir": str(output_dir),
        "store_path": str(store_path),
        "phases": phases,
        "wallets": wallets,
        "discovery": bool(raw.get("discovery")),
        "window_days": window_days,
        "earlier_history_days": earlier,
        "bounds": window_bounds(window_days, earlier),
        "caps": caps,
        "per_wallet_cap": raw.get("per_wallet_cap"),
        "resume": bool(raw.get("resume")),
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
    store = require_durable_store(config["store_path"])
    store.put("configuration", "live_authorization", config["grant"])
    state = load_or_create_state(output_dir, config, resume=config["resume"])
    state["authorization_id"] = config["authorization_id"]
    recorder = RecorderTransport()
    plan = plan_request_counts(config)
    plan["within_caps"] = within_caps(plan, config["caps"])
    plan["gta_page_size"] = gta_page_size_note()
    _write_json(output_dir / PLAN_NAME, plan)
    if not plan["within_caps"] and not config["dry_run"]:
        raise LiveE2EError("planned requests exceed grant/runner caps")
    try:
        try:
            done = set(state.get("phases_done") or [])
            if 1 in config["phases"] and 1 not in done:
                state["phase1"] = await phase1_discovery(store, config["grant"], config, state, recorder)
                state["phases_done"] = sorted(done | {1})
                done = set(state["phases_done"])
                save_state(output_dir, state)
            if 2 in config["phases"] and 2 not in done:
                state["phase2_result"] = await phase2_prescreen(store, config["grant"], config, state, recorder)
                state["phases_done"] = sorted(done | {2})
                done = set(state["phases_done"])
                save_state(output_dir, state)
            if 3 in config["phases"] and 3 not in done:
                state["phase3_result"] = await phase3_history(store, config["grant"], config, state, recorder)
                state["phases_done"] = sorted(done | {3})
                done = set(state["phases_done"])
                save_state(output_dir, state)
            phase4 = {"wallets": state.get("phase4_wallets") or []}
            if 4 in config["phases"] and 4 not in done:
                phase4 = phase4_offline(store, config, state)
                state["phase4_wallets"] = phase4.get("wallets") or []
                state["phases_done"] = sorted(done | {4})
                save_state(output_dir, state)
            state["status"] = "completed"
            status = "completed"
            blocker = None
        except (SourceError, LiveE2EError, QuotaExceeded) as error:
            state["status"] = "blocked"
            state["blocker"] = getattr(error, "state", None) or error.__class__.__name__
            state["detail"] = str(error)
            phase4 = {"wallets": state.get("phase4_wallets") or []}
            status = "blocked"
            blocker = state["blocker"]
        save_state(output_dir, state)
        results = {
            "kind": "live-e2e-results-v1",
            "status": status,
            "blocker": blocker,
            "dry_run": config["dry_run"],
            "authorization_id": config["authorization_id"],
            "grant_enabled": bool(config["grant"].get("enabled")),
            "phases": list(config["phases"]),
            "bounds": config["bounds"],
            "spend": state["spend"],
            "plan": plan,
            "recorder_calls": recorder.calls,
            "phase1": state.get("phase1"),
            "phase2": state.get("phase2_result"),
            "phase3": state.get("phase3_result"),
            "wallets": phase4.get("wallets") or [],
            "PRODUCT_READY": False,
        }
        _write_json(output_dir / RESULTS_NAME, redact_secrets(results))
        (output_dir / SUMMARY_NAME).write_text(human_summary(results), encoding="utf-8")
        return results
    finally:
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
    parser.add_argument("--window-days", dest="window_days", type=int, default=30)
    parser.add_argument("--earlier-history-days", dest="earlier_history_days", type=int, default=60)
    parser.add_argument("--per-wallet-cap", dest="per_wallet_cap", type=int)
    parser.add_argument("--max-birdeye-requests", dest="max_birdeye_requests", type=int)
    parser.add_argument("--max-birdeye-units", dest="max_birdeye_units", type=int)
    parser.add_argument("--max-helius-requests", dest="max_helius_requests", type=int)
    parser.add_argument("--max-helius-units", dest="max_helius_units", type=int)
    parser.add_argument("--birdeye-limit", dest="birdeye_limit", type=int, default=100)
    parser.add_argument("--birdeye-window", dest="birdeye_window", default="30d")
    parser.add_argument("--birdeye-sort", dest="birdeye_sort", default="trader_score")
    parser.add_argument("--min-in-window-tx", dest="min_in_window_tx", type=int, default=0)
    parser.add_argument("--max-unsupported-share", dest="max_unsupported_share", default="1")
    parser.add_argument("--max-bot-rate", dest="max_bot_rate", default="1")
    parser.add_argument("--output", dest="output_dir", required=True)
    parser.add_argument("--store", dest="store_path")
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    raw = vars(args)
    raw["mode"] = "dry-run" if args.dry_run else "live"
    import asyncio

    try:
        result = asyncio.run(run_live_e2e(raw))
    except (LiveE2EError, SourceError, QuotaExceeded) as error:
        print(str(error))
        return 2
    print(json.dumps({
        "status": result["status"],
        "dry_run": result["dry_run"],
        "spend": result["spend"],
        "plan_totals": result["plan"]["totals"],
        "within_caps": result["plan"]["within_caps"],
        "PRODUCT_READY": False,
    }, indent=2))
    return 0
