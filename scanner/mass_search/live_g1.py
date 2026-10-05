"""G1-only live vertical slice. Hard ceilings. No setup-pilot reset. No secrets in evidence."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path

import httpx

from scanner.investigation import decode_supported_swaps
from scanner.storage import QuotaExceeded

from .adapters import BirdeyeTraderAdapter, SourceError, ALLOWED_BIRDEYE_HOST, ALLOWED_BIRDEYE_PATH
from .capability import (
    LIVE_AUTH_SCHEMA,
    authorization_sha256,
    redact_secrets,
    utc_now,
    validate_live_authorization,
)
from .evidence_integrity import sanitize_jsonrpc_body
from .plan import load_default_plan
from .service import MassSearchService
from .universe import ingest_page, seal_universe

ROOT = Path(__file__).resolve().parents[2]
GRANT_PATH = ROOT / "config" / "live_authorization.g1-granted.json"
EXAMPLE_PATH = ROOT / "work_packages" / "mass_wallet_search_v1" / "config" / "live_authorization.example.json"
DRAFT_PATH = ROOT / "config" / "live_authorization.proof-grant-draft.json"
BIRDEYE_KEY_ENV = "BIRDEYE_API_KEY"
HELIUS_KEY_ENV = "HELIUS_API_KEY"
HELIUS_ENDPOINT = "https://mainnet.helius-rpc.com/"
BIRDEYE_UNITS_PER_PAGE = 25
HELIUS_UNITS_PER_GTA = 10
G1_BIRDEYE_LIMIT = 20
G1_HELIUS_LIMIT = 50
G1_MAX_CANDIDATES = 5


def load_grant(path=None):
    payload = json.loads(Path(path or GRANT_PATH).read_text(encoding="utf-8"))
    checked = validate_live_authorization(payload)
    if checked.get("schema_version") != LIVE_AUTH_SCHEMA:
        raise ValueError("Grant must use live-research-authorization-v1")
    return checked


def assert_example_and_draft_are_not_grants():
    example = validate_live_authorization(json.loads(EXAMPLE_PATH.read_text(encoding="utf-8")))
    draft = validate_live_authorization(json.loads(DRAFT_PATH.read_text(encoding="utf-8")))
    if example.get("enabled") or draft.get("enabled"):
        raise ValueError("Example or draft grant file is enabled; refuse to treat them as this G1 grant")
    return {"example_enabled": False, "draft_enabled": False}


def credential_presence():
    return {
        "birdeye": bool(os.environ.get(BIRDEYE_KEY_ENV)),
        "helius": bool(os.environ.get(HELIUS_KEY_ENV) or os.environ.get("HELIUS_KEY")),
    }


def _provider(grant, provider_id):
    for entry in grant["providers"]:
        if entry["provider_id"] == provider_id:
            return entry
    raise SourceError("UNAUTHORIZED", f"Grant does not include {provider_id}")


def independent_fifo_worksheet(events):
    """Oracle FIFO. Does not import production ranking or fifo_sale_results."""
    with localcontext() as ctx:
        ctx.prec = 192
        lots = []
        sales = []
        for event in events:
            units = Decimal(str(event["units"]))
            if event["kind"] == "buy":
                consideration = Decimal(str(event["consideration_sol"]))
                fee = Decimal(str(event.get("wallet_fee_sol") or "0"))
                lots.append({"units": units, "unit_cost": (consideration + fee) / units})
            elif event["kind"] == "sell":
                remaining = units
                basis = Decimal("0")
                while remaining > 0:
                    if not lots:
                        raise ValueError("Sale exceeds supported inventory")
                    lot = lots[0]
                    take = min(lot["units"], remaining)
                    basis += lot["unit_cost"] * take
                    lot["units"] -= take
                    remaining -= take
                    if lot["units"] == 0:
                        lots.pop(0)
                fee = Decimal(str(event.get("wallet_fee_sol") or "0"))
                proceeds = Decimal(str(event["consideration_sol"]))
                sales.append({
                    "basis": format(basis, "f"),
                    "net_profit": format(proceeds - basis - fee, "f"),
                })
        total = sum((Decimal(sale["net_profit"]) for sale in sales), Decimal("0"))
        return {
            "sale_fifo_basis_sol": [sale["basis"] for sale in sales],
            "sale_net_profit_sol": [sale["net_profit"] for sale in sales],
            "total_profit_sol": format(total, "f"),
            "oracle": "independent-g1-fifo-v1",
        }


def decoder_events_to_subset(decoded, *, address, window_start):
    events = [row for row in (decoded.get("events") or []) if row.get("kind") in ("buy", "sell")]
    by_mint = {}
    start = datetime.fromisoformat(window_start.replace("Z", "+00:00"))
    start_unix = start.timestamp()
    for row in events:
        mint = row.get("mint")
        if not mint:
            continue
        timestamp = row.get("timestamp")
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            seconds = int(timestamp - start_unix)
        else:
            seconds = 0
        by_mint.setdefault(mint, []).append({
            "kind": row["kind"],
            "units": str(row.get("quantity_raw") or "0"),
            "consideration_sol": str(row.get("amount_sol") or "0"),
            "wallet_fee_sol": str(row.get("fee_sol") or "0"),
            "seconds_from_start": seconds,
            "signature": row.get("signature"),
            "mint": mint,
            "address": address,
            "evidence": row.get("evidence") or [],
        })
    for mint, rows in by_mint.items():
        kinds = {row["kind"] for row in rows}
        if "buy" in kinds and "sell" in kinds:
            try:
                independent_fifo_worksheet(rows)
            except ValueError:
                continue
            return {"mint": mint, "events": rows, "reason": None}
    return {
        "mint": None,
        "events": [],
        "reason": "No supported closed buy+sell pair on one mint in the fetched sample",
    }


def write_freeze(*, evidence_dir, grant, application_sha, hardware):
    evidence_dir = Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    freeze = {
        "kind": "mass-search-g1-pre-run-freeze-v1",
        "frozen_at": utc_now(),
        "application_commit": application_sha,
        "authorization_id": grant.get("authorization_id"),
        "authorization_sha256": authorization_sha256(grant),
        "first_live_target": "G1_VERTICAL_SLICE_ONLY",
        "corpus_kind": "GENUINE_LIVE",
        "source_ids": ["birdeye-traders", "helius-history"],
        "windows": {
            "report_window_days": 30,
            "verification_window_days": 90,
            "timestamp_semantics": "Birdeye ranking snapshot is not an atomic as-of universe; Helius blockTime is chain time",
        },
        "ceilings": {
            "birdeye": {"max_requests": 10, "max_units": 250, "billing_unit": "birdeye_compute_unit"},
            "helius": {"max_requests": 20, "max_units": 600, "billing_unit": "helius_credit"},
            "max_additional_spend_usd": "0",
            "overages_enabled": False,
            "do_not_reset_setup_pilot": True,
        },
        "stop_conditions": [
            "G1 only — one survivor with supported buy+sell",
            "Stop on 401/403/429/quota/missing credentials",
            "Do not run G2/G3/G5/G6",
        ],
        "hardware": hardware,
        "example_and_draft_not_grants": assert_example_and_draft_are_not_grants(),
    }
    path = evidence_dir / "PRE_RUN_FREEZE.json"
    path.write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    return freeze


def _spend_snapshot(store, grant):
    birdeye = _provider(grant, "birdeye")
    helius = _provider(grant, "helius")
    return {
        "birdeye": store.usage("birdeye", birdeye["cycle_start"], birdeye["max_units"]),
        "helius": store.usage("helius", helius["cycle_start"], helius["max_units"]),
        "setup_pilot": store.usage("helius", "setup-pilot", 200),
    }


async def _birdeye_http(method, path, params):
    key = os.environ.get(BIRDEYE_KEY_ENV)
    if not key:
        raise SourceError("UNAUTHORIZED", "BIRDEYE_API_KEY is not present in this runtime")
    if path != ALLOWED_BIRDEYE_PATH:
        raise SourceError("UNAUTHORIZED", "Birdeye path is not allowlisted")
    headers = {"X-API-KEY": key, "x-chain": "solana", "accept": "application/json"}
    async with httpx.AsyncClient(
        base_url=f"https://{ALLOWED_BIRDEYE_HOST}",
        follow_redirects=False,
        timeout=httpx.Timeout(25, connect=10),
    ) as client:
        response = await client.request(method, path, params=params, headers=headers)
    body = None
    try:
        body = response.json()
    except ValueError:
        body = None
    return {"status": response.status_code, "body": body, "fetched_at": utc_now()}


async def _helius_gta(store, grant, address, *, limit, pagination_token=None):
    key = os.environ.get(HELIUS_KEY_ENV) or os.environ.get("HELIUS_KEY")
    if not key:
        raise SourceError("UNAUTHORIZED", "HELIUS_API_KEY is not present in this runtime")
    entry = _provider(grant, "helius")
    if "getTransactionsForAddress" not in entry["allowed_operations"]:
        raise SourceError("UNAUTHORIZED", "Grant does not allow getTransactionsForAddress")
    if store.usage("helius", entry["cycle_start"], entry["max_units"])["used"] >= entry["max_requests"]:
        # request ceiling is tracked separately below
        pass
    used_requests = _count_method(store, "helius", entry["cycle_start"], "getTransactionsForAddress")
    if used_requests >= entry["max_requests"]:
        raise SourceError("RATE_LIMITED", "Helius G1 request ceiling reached")
    options = {
        "transactionDetails": "full",
        "limit": limit,
        "sortOrder": "asc",
        "commitment": "finalized",
        "maxSupportedTransactionVersion": 1,
        "filters": {"status": "any", "tokenAccounts": "all"},
    }
    if pagination_token:
        options["paginationToken"] = pagination_token
    reservation = store.reserve("helius", "getTransactionsForAddress", HELIUS_UNITS_PER_GTA,
                                entry["cycle_start"], entry["max_units"])
    request_id = 1
    payload = {"jsonrpc": "2.0", "id": request_id, "method": "getTransactionsForAddress",
               "params": [address, options]}
    try:
        store.dispatch(reservation)
        async with httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(40, connect=10)) as client:
            response = await client.post(HELIUS_ENDPOINT, params={"api-key": key}, json=payload)
        status = response.status_code
        if status in (401, 403):
            store.settle(reservation, charge=True)
            raise SourceError("ENTITLEMENT_BLOCKED", "Helius rejected the key or plan", http_status=status)
        if status == 429:
            store.settle(reservation, charge=True)
            raise SourceError("RATE_LIMITED", "Helius rate limit", http_status=status, retryable=True)
        try:
            body = response.json()
        except ValueError:
            store.settle(reservation, charge=True)
            raise SourceError("UNSUPPORTED_SCHEMA", "Helius returned non-JSON", http_status=status)
        if status != 200 or not isinstance(body, dict):
            store.settle(reservation, charge=True)
            raise SourceError("UNSUPPORTED_SCHEMA", "Unexpected Helius response", http_status=status)
        if body.get("error"):
            store.settle(reservation, charge=True)
            code = (body.get("error") or {}).get("code") if isinstance(body.get("error"), dict) else None
            if code == -32601:
                raise SourceError("ENTITLEMENT_BLOCKED", "getTransactionsForAddress is unavailable for this account")
            raise SourceError("UNAVAILABLE", "Helius rejected getTransactionsForAddress")
        store.settle(reservation, charge=True)
        result = body.get("result") or {}
        data = result.get("data") if isinstance(result, dict) else None
        if data is None and isinstance(result, list):
            data = result
        if not isinstance(data, list):
            data = []
        cleaned = sanitize_jsonrpc_body(body)
        cleaned_result = cleaned.get("result") or {}
        cleaned_data = cleaned_result.get("data") if isinstance(cleaned_result, dict) else None
        if cleaned_data is None and isinstance(cleaned_result, list):
            cleaned_data = cleaned_result
        if not isinstance(cleaned_data, list):
            cleaned_data = data
        raw_bytes = json.dumps(cleaned, sort_keys=True, separators=(",", ":")).encode()
        return {
            "records": cleaned_data,
            "pagination_token": result.get("paginationToken") if isinstance(result, dict) else None,
            "evidence_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "units": HELIUS_UNITS_PER_GTA,
            "external_requests": 1,
            "http_status": status,
        }
    except SourceError:
        raise
    except QuotaExceeded as error:
        raise SourceError("RATE_LIMITED", str(error)) from error
    except httpx.TransportError as error:
        try:
            store.settle(reservation, charge=True)
        except ValueError:
            pass
        raise SourceError("UNAVAILABLE", "Helius connection failed") from error


def _count_method(store, provider, cycle, method):
    with store.lock:
        row = store.db.execute(
            "SELECT COUNT(*) FROM reservations WHERE provider=? AND cycle=? AND method=? AND state IN ('dispatched','settled')",
            (provider, cycle, method),
        ).fetchone()
    return int(row[0] if row else 0)


def _wrap_records(records):
    """Shared canonical decode wrappers. Already-wrapped records are not wrapped again."""
    from .canonical_records import canonical_decode_records

    return canonical_decode_records(records)


async def run_g1(store, *, evidence_dir, application_sha, hardware=None, transports=None, grant_path=None):
    """Smallest G1 path. Returns PASS or BLOCKED. Never invents wallets."""
    run_id = uuid.uuid4().hex
    evidence_dir = Path(evidence_dir) / run_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    grant = load_grant(grant_path)
    non_grants = assert_example_and_draft_are_not_grants()
    if not grant.get("enabled"):
        return _blocked(store, grant, evidence_dir, run_id, "grant_disabled",
                        "Named grant is not enabled", application_sha, hardware)
    if grant.get("authorization_id") != "live-g1-vertical-slice-2026-10-05-mitch":
        return _blocked(store, grant, evidence_dir, run_id, "unexpected_authorization_id",
                        "G1 runner expects live-g1-vertical-slice-2026-10-05-mitch", application_sha, hardware)
    freeze = write_freeze(evidence_dir=evidence_dir, grant=grant, application_sha=application_sha,
                          hardware=hardware or {"runtime": "python", "note": "local G1 runner"})
    store.put("configuration", "live_authorization", grant)
    setup_before = store.usage("helius", "setup-pilot", 200)
    presence = credential_presence()
    transports = transports or {}
    if transports.get("skip_credential_check") is not True:
        missing = [name for name, ok in presence.items() if not ok]
        if missing:
            return _blocked(
                store, grant, evidence_dir, run_id, "missing_provider_credentials",
                "Live G1 stopped before any provider HTTP: "
                + ", ".join(f"{name.upper()}_API_KEY absent" for name in missing)
                + ". Grant remains enabled. Example/draft remain disabled. Setup-pilot untouched.",
                application_sha, hardware, freeze=freeze, extra={"missing_env": missing, "presence": presence},
            )

    service = MassSearchService(store)
    plan = deepcopy(load_default_plan())
    plan["live_enabled"] = True
    plan["selection"]["universe_target_unique"] = G1_BIRDEYE_LIMIT
    run = service.create_run(plan, source_id="birdeye-traders", corpus_kind="GENUINE_LIVE", authorization=grant)
    spend = {"external_requests": 0}

    try:
        adapter = BirdeyeTraderAdapter(transport=transports.get("birdeye") or _birdeye_http)
        page = await adapter.fetch_page(
            offset=0, limit=G1_BIRDEYE_LIMIT, window="30d", authorization=grant, store=store,
        )
        spend["external_requests"] += int(page.get("external_requests") or 0)
        page["window_start"] = run["window_start"]
        page["window_end"] = run["window_end"]
        ingested = ingest_page(store, run["run_id"], page)
        seal_universe(store, run["run_id"], extra=ingested)
        candidates = [row["address"] for row in page.get("rows") or [] if row.get("valid") and row.get("address")]
        if not candidates:
            return _blocked(store, grant, evidence_dir, run_id, "empty_discovery_page",
                            "Birdeye page returned no valid addresses", application_sha, hardware,
                            freeze=freeze, extra={"page_state": page.get("state"), "raw_count": page.get("raw_count")})

        helius_fetch = transports.get("helius") or (
            lambda address, **kwargs: _helius_gta(store, grant, address, **kwargs)
        )
        decode = transports.get("decode") or decode_supported_swaps
        inspected = []
        for address in candidates[:G1_MAX_CANDIDATES]:
            history = await helius_fetch(address, limit=G1_HELIUS_LIMIT)
            spend["external_requests"] += int(history.get("external_requests") or 1)
            records = _wrap_records(history.get("records") or [])
            decoded = decode(records, address)
            subset = decoder_events_to_subset(decoded, address=address, window_start=run["window_start"])
            inspected.append({
                "address": address,
                "transactions": len(records),
                "decoded_swaps": (decoded.get("coverage") or {}).get("decoded_swaps"),
                "subset_reason": subset["reason"],
                "history_sha256": history.get("evidence_sha256"),
            })
            if not subset["events"]:
                continue
            oracle = independent_fifo_worksheet(subset["events"])
            reconstructed = service.reconstruct_candidate(
                run["run_id"], f"solana:{address}", subset["events"],
                corpus_kind="GENUINE_LIVE", mint=subset["mint"],
            )
            report = reconstructed["report"]
            report["policy"] = report.get("policy") or "UNRESOLVED"
            if report.get("source") != "mass-search":
                report["source"] = "mass-search"
            store.put("reports", report["id"], report)
            result = {
                "gate": "G1",
                "status": "PASS",
                "run_id": run_id,
                "search_run_id": run["run_id"],
                "authorization_id": grant["authorization_id"],
                "grant_path": str(GRANT_PATH.relative_to(ROOT)),
                "address": address,
                "report_id": report["id"],
                "corpus_kind": "GENUINE_LIVE",
                "policy": report.get("policy") or "UNRESOLVED",
                "not_wallet_wide_match": True,
                "worksheet": reconstructed.get("worksheet"),
                "independent_worksheet": oracle,
                "inspected_candidates": inspected,
                "spend": {**_spend_snapshot(store, grant), "external_requests": spend["external_requests"]},
                "setup_pilot_before": setup_before,
                "setup_pilot_after": store.usage("helius", "setup-pilot", 200),
                "freeze": freeze,
                "non_grants": non_grants,
            }
            if result["setup_pilot_before"] != result["setup_pilot_after"]:
                result["status"] = "BLOCKED"
                result["blocker"] = "setup_pilot_changed"
                result["detail"] = "G1 must not reset or charge setup-pilot"
            _write_receipt(evidence_dir, result)
            return result

        return _blocked(
            store, grant, evidence_dir, run_id, "no_supported_closed_pair",
            "Fetched native history did not decode to a supported closed buy+sell on one mint",
            application_sha, hardware, freeze=freeze,
            extra={"inspected_candidates": inspected, "spend": {**_spend_snapshot(store, grant),
                                                                "external_requests": spend["external_requests"]}},
        )
    except SourceError as error:
        return _blocked(
            store, grant, evidence_dir, run_id, error.state,
            str(error), application_sha, hardware, freeze=freeze,
            extra={"http_status": error.http_status, "spend": _spend_snapshot(store, grant)},
        )


def _blocked(store, grant, evidence_dir, run_id, code, detail, application_sha, hardware,
             freeze=None, extra=None):
    result = {
        "gate": "G1",
        "status": "BLOCKED",
        "run_id": run_id,
        "authorization_id": grant.get("authorization_id"),
        "grant_path": str(GRANT_PATH.relative_to(ROOT)),
        "grant_enabled": bool(grant.get("enabled")),
        "blocker": code,
        "detail": detail,
        "application_commit": application_sha,
        "spend": extra.get("spend") if extra and extra.get("spend") else _spend_snapshot(store, grant),
        "setup_pilot": store.usage("helius", "setup-pilot", 200),
        "freeze": freeze,
        "missing_dependency": detail,
    }
    if extra:
        result["extra"] = redact_secrets(extra)
    _write_receipt(evidence_dir, result)
    return result


def _public_receipt(result):
    """Keep operational G1 fields. Never persist API-key values."""
    payload = json.loads(json.dumps(result, default=str))
    return payload


def _write_receipt(evidence_dir, result):
    path = Path(evidence_dir) / "G1_RESULT.json"
    path.write_text(json.dumps(_public_receipt(result), indent=2) + "\n", encoding="utf-8")
    (Path(evidence_dir) / "INDEX.json").write_text(json.dumps({
        "run_id": result.get("run_id"),
        "gate": "G1",
        "status": result.get("status"),
        "authorization_id": result.get("authorization_id"),
        "blocker": result.get("blocker"),
        "result": "G1_RESULT.json",
        "freeze": "PRE_RUN_FREEZE.json",
    }, indent=2) + "\n", encoding="utf-8")
