"""Phase 1 seed sources. A seed is never evidence.

Combinable sources: birdeye_top, token_intersect, nansen.
Cheap Helius triage (earliest / recent / older-month) runs after seeds
and before --history-to-first. Vendor metrics stay on seed_metadata.

GMGN / Cielo / Kolscan stay unimplemented (no keyless ToS-safe API).
Nansen is optional: missing NANSEN_API_KEY disables the source and
must never produce a dummy live call.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from scanner.config import validate_address

SEED_BIRDEYE_TOP = "birdeye_top"
SEED_TOKEN_INTERSECT = "token_intersect"
SEED_NANSEN = "nansen"
SEED_PRESCREEN_FILTER = "prescreen-filter"

# Backward aliases from the first discovery checkpoint.
SEED_GAINERS = "gainers-losers"
SEED_TOP_TRADERS = "top-traders"
SEED_EARLY_BUYERS = "early-buyers-durable"
SEED_SMART_MONEY = "smart-money-leaderboard"

SEED_ALIASES = {
    SEED_GAINERS: SEED_BIRDEYE_TOP,
    SEED_TOP_TRADERS: SEED_BIRDEYE_TOP,
    SEED_EARLY_BUYERS: SEED_TOKEN_INTERSECT,
    SEED_SMART_MONEY: SEED_NANSEN,
}

PRIMARY_SEED_SOURCES = frozenset({SEED_BIRDEYE_TOP, SEED_TOKEN_INTERSECT, SEED_NANSEN})
SEED_SOURCES = PRIMARY_SEED_SOURCES | {
    SEED_PRESCREEN_FILTER, SEED_GAINERS, SEED_TOP_TRADERS, SEED_EARLY_BUYERS, SEED_SMART_MONEY,
}

BIRDEYE_TOKEN_LIST_PATH = "/defi/v3/token/list"
BIRDEYE_FIRST_BUYERS_PATH = "/token/v1/first-buyers"
BIRDEYE_TOKEN_TX_SEEK_PATH = "/defi/txs/token/seek_by_time"
BIRDEYE_TOKEN_TXS_PATH = "/defi/txs/token"
# Current official CU (docs.birdeye.so/docs/compute-unit-cost and
# docs.birdeye.so/reference/compute-unit-cost, fetched 2026-10-07):
# GET /defi/v3/token/list = 60 CU; GET /defi/txs/token = 10 CU;
# GET /defi/txs/token/seek_by_time = 10 CU. The box verify report cited
# 50 / 12 from an older data.birdeye.so table; current docs win.
BIRDEYE_TOKEN_LIST_UNITS = 60
BIRDEYE_FIRST_BUYERS_UNITS = 25
BIRDEYE_TOKEN_TX_SEEK_UNITS = 10
BIRDEYE_TOKEN_TXS_UNITS = 10
BIRDEYE_CU_VERIFIED_ON = "2026-10-07"
BIRDEYE_CU_DOCS_URL = "https://docs.birdeye.so/docs/compute-unit-cost"

NANSEN_HOST = "api.nansen.ai"
NANSEN_KEY_ENV = "NANSEN_API_KEY"
NANSEN_LEADERBOARD_PATH = "/api/v1/smart-money/pnl-leaderboard"
NANSEN_PNL_SUMMARY_PATH = "/api/v1/profiler/address/pnl-summary"
NANSEN_FIRST_FUNDER_PATH = "/api/v1/profiler/address/first-funder"
NANSEN_LABELS_PATH = "/api/v1/profiler/address/labels"
ALLOWED_NANSEN_PATHS = frozenset({
    NANSEN_LEADERBOARD_PATH,
    NANSEN_PNL_SUMMARY_PATH,
    NANSEN_FIRST_FUNDER_PATH,
})
NANSEN_LEADERBOARD_UNITS = 5
NANSEN_PROFILER_UNITS = 1
NANSEN_TIMEFRAME_ENUM = (1, 7, 30, 90, 180)
NANSEN_TIMEFRAMES = (90, 180)
NANSEN_CHAIN = "solana"
NANSEN_FIRST_FUNDER_CHAIN = "all"
NANSEN_BILLING_HEADER_NAMES = (
    "X-Nansen-Credits-Cost",
    "X-Nansen-Credits-Used",
    "X-Nansen-Credits-Remaining",
    "X-Request-Id",
)
# Official OpenAPI, fetched 2026-10-07 from docs.nansen.ai.
# Smart Money PnL leaderboard: POST /api/v1/smart-money/pnl-leaderboard
# requires chains[] and timeframe ∈ {1,7,30,90,180}; additionalProperties false.
# Profiler pnl-summary: required chain + date DateRange; prefers wallet_address.
# First-funder: EVM-only, chain fixed to "all". Dropped for Solana.
NANSEN_SCHEMAS = {
    "leaderboard": {
        "additionalProperties": False,
        "required": ["chains", "timeframe"],
        "properties": {
            "chains": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "timeframe": {"enum": list(NANSEN_TIMEFRAME_ENUM)},
            "pagination": {"type": "object"},
            "filters": {"type": "object"},
            "order_by": {"type": "array"},
        },
    },
    "pnl_summary": {
        "additionalProperties": False,
        "required": ["chain", "date"],
        "properties": {
            "wallet_address": {"type": "string"},
            "address": {"type": "string"},
            "entity_name": {"type": "string"},
            "chain": {"type": "string"},
            "date": {"type": "object", "required": ["from", "to"], "properties": {"from": {"type": "string"}, "to": {"type": "string"}}},
            "pagination": {"type": "object"},
        },
    },
    "first_funder": {
        "additionalProperties": False,
        "required": ["address"],
        "properties": {
            "address": {"type": "string"},
            "chain": {"enum": [NANSEN_FIRST_FUNDER_CHAIN]},
        },
    },
}

DURABLE_TOKEN_MIN_AGE_DAYS = 21
DURABLE_TOKEN_MAX_AGE_DAYS = 42
DURABLE_TOKEN_MIN_LIQUIDITY_USD = 100000
DURABLE_TOKEN_MIN_MARKET_CAP_USD = 500000
DURABLE_TOKEN_MAX_LAST_TRADE_AGE_DAYS = 7
TOKEN_INTERSECT_SEASONED = 8
TOKEN_INTERSECT_CONTROLS = 2
TOKEN_INTERSECT_WINDOWS = 3
TOKEN_INTERSECT_PAGES_PER_WINDOW = 1
TOKEN_INTERSECT_MIN_COHORTS = 3
FIRST_BLOCK_EXCLUSION_SECONDS = 86400

CHEAP_MAX_TRADES_PER_DAY = Decimal("25")
CHEAP_MIN_HISTORY_DAYS = Decimal("30")
TRIAGE_PREFER_AGE_DAYS = Decimal("180")
TRIAGE_SAMPLES = 3
TRIAGE_SAMPLE_LIMIT = 100
TRIAGE_SAMPLE_UNITS = 10

QUOTE_MINTS = frozenset({
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
})

# Keep these count kinds separate. Dune rows are route legs, not trades.
COUNT_KINDS = (
    "transactions",
    "economic_trades",
    "route_legs",
    "positions",
    "completed_episodes",
)

LEADERBOARD_VIABILITY = {
    "gmgn": {
        "viable": False,
        "reason": "No official public API. Unofficial quotation URLs are scraper-only.",
    },
    "cielo": {
        "viable": False,
        "reason": "Official API requires X-API-KEY and a paid plan. Deferred.",
    },
    "kolscan": {
        "viable": False,
        "reason": "No official public GET. Browser-intercepted POST is not scraped.",
    },
    "nansen": {
        "viable": True,
        "requires_key": True,
        "key_env": NANSEN_KEY_ENV,
        "reason": (
            "Official POST /api/v1/smart-money/pnl-leaderboard (5 credits) plus "
            "profiler pnl-summary (1 credit). First-funder is EVM-only and is "
            "not called for Solana. Disabled when the key is absent. Never "
            "call labels (100 credits) or premium_labels."
        ),
    },
}

# ChatGPT-supplied program IDs. Only IDs already pinned in investigation.py
# are trusted. The rest stay unverified and must not become supported venues.
RESEARCH_PROGRAM_IDS = {
    "jupiter_v6": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
    "okx_router_unverified": "6m2CDdhRgxpH4WjvdzxAYbGxwdGUz5MziiL5jek2kBma",
    "raydium_amm_v4": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    "raydium_cpmm": "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
    "raydium_clmm_unverified": "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
    "raydium_stable_unverified": "5quBtoiQqxF9Jv6KYKctB59NT3gtJD2Y65kdnB1Uev3h",
    "raydium_router_unverified": "routeUGWgWzqBWFcrCfv8tritsqukccJPu3q5GPP3xS",
    "launchlab_unverified": "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
    "meteora_dlmm": "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",
    "meteora_damm_v1_unverified": "Eo7WjKq67rjJQSZxS6z3YkapzY3eMj6Xy8X5EQVn5UaB",
    "meteora_damm_v2": "cpamdpZCGKUy5JxQXB4dcpGPiikHawvSWAd6mEn1sGG",
    "meteora_dbc_unverified": "dbcij3LWUppWqq96dh6gJWwBifmcGfLSB5D4DuSMaqN",
    "pump": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
    "pumpswap": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
    "orca_whirlpool": "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
    "phoenix_unverified": "PhoeNiXZ8ByJGLkxNfZRnkUfjvmuYqLR89jjFHGqdXY",
    "dflow": "DF1ow4tspfHX9JwWJsAb9epbkA8hmpSEAtxXy1V27QBH",
}

SEED_CU_DOCS = {
    SEED_BIRDEYE_TOP: {
        "provider": "birdeye",
        "path": "/trader/gainers-losers",
        "documented_cu": 30,
        "alt_path": "/defi/v2/tokens/top_traders",
        "alt_cu": 35,
        "docs": "https://docs.birdeye.so/docs/compute-unit-cost",
        "reviewed_on": "2026-10-07",
    },
    SEED_TOKEN_INTERSECT: {
        "provider": "birdeye",
        "paths": {
            "token_list": {"path": BIRDEYE_TOKEN_LIST_PATH, "documented_cu": BIRDEYE_TOKEN_LIST_UNITS},
            "token_txs": {"path": BIRDEYE_TOKEN_TXS_PATH, "documented_cu": BIRDEYE_TOKEN_TXS_UNITS},
            "token_txs_seek": {"path": BIRDEYE_TOKEN_TX_SEEK_PATH, "documented_cu": BIRDEYE_TOKEN_TX_SEEK_UNITS},
        },
        "primary_tx_path": BIRDEYE_TOKEN_TXS_PATH,
        "docs": BIRDEYE_CU_DOCS_URL,
        "reviewed_on": BIRDEYE_CU_VERIFIED_ON,
        "note": (
            "Seasoned-token buyers in ordinary windows (not first-block). "
            "Primary sampler is /defi/txs/token (10 CU); seek_by_time is not "
            "assumed entitled. Intersect wallets in >=3 unrelated token cohorts. "
            "A seed is not evidence."
        ),
    },
    SEED_NANSEN: {
        "provider": "nansen",
        "leaderboard_path": NANSEN_LEADERBOARD_PATH,
        "leaderboard_credits": NANSEN_LEADERBOARD_UNITS,
        "profiler_credits": NANSEN_PROFILER_UNITS,
        "avoid": [NANSEN_LABELS_PATH, "premium_labels"],
        "docs": "https://docs.nansen.ai/api/smart-money/pnl-leaderboard",
        "reviewed_on": "2026-10-07",
        "note": (
            "Disabled when NANSEN_API_KEY is absent. Never a dummy live call. "
            "First-funder is EVM-only and is not called for Solana."
        ),
    },
}


class SeedSourceError(ValueError):
    """Invalid --seed-source value or combination."""


def _schema_type_ok(value, expected):
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return type(value) is int and not isinstance(value, bool)
    return True


def validate_nansen_body(kind, body):
    """Validate a request body against the published Nansen OpenAPI schema.

    A transport fake that accepts any JSON cannot hide a schema violation:
    this runs on the body before the call.
    """
    schema = NANSEN_SCHEMAS.get(kind)
    if schema is None:
        raise SeedSourceError(f"unknown Nansen schema kind {kind}")
    if not isinstance(body, dict):
        raise SeedSourceError("Nansen body must be an object")
    allowed = set(schema.get("properties") or {})
    extra = set(body) - allowed
    if schema.get("additionalProperties") is False and extra:
        raise SeedSourceError(f"Nansen {kind} unknown fields {sorted(extra)}")
    for field in schema.get("required") or []:
        if field not in body:
            raise SeedSourceError(f"Nansen {kind} missing required field {field}")
    for field, spec in (schema.get("properties") or {}).items():
        if field not in body:
            continue
        value = body[field]
        expected = spec.get("type")
        if expected and not _schema_type_ok(value, expected):
            raise SeedSourceError(f"Nansen {kind} field {field} has the wrong type")
        enum = spec.get("enum")
        if enum is not None and value not in enum:
            raise SeedSourceError(f"Nansen {kind} field {field}={value!r} is not in {enum}")
        if expected == "array" and spec.get("minItems") and len(value) < spec["minItems"]:
            raise SeedSourceError(f"Nansen {kind} field {field} is empty")
        if field == "date" and isinstance(value, dict):
            for part in (spec.get("required") or ()):
                if part not in value or not value.get(part):
                    raise SeedSourceError(f"Nansen {kind} date.{part} is required")
    return True


def nansen_leaderboard_body(*, timeframe, page=1, per_page=50):
    body = {
        "chains": [NANSEN_CHAIN],
        "timeframe": int(timeframe),
        "pagination": {"page": int(page), "per_page": int(per_page)},
    }
    validate_nansen_body("leaderboard", body)
    return body


def nansen_pnl_summary_body(*, wallet_address, date_from, date_to):
    body = {
        "wallet_address": wallet_address,
        "chain": NANSEN_CHAIN,
        "date": {"from": date_from, "to": date_to},
    }
    validate_nansen_body("pnl_summary", body)
    return body


def nansen_first_funder_supported(*, chain=NANSEN_CHAIN):
    """First-funder is EVM-only; Solana must not send the call."""
    return False if chain == NANSEN_CHAIN else True


def nansen_schema_kind_for_path(path):
    if path == NANSEN_LEADERBOARD_PATH:
        return "leaderboard"
    if path == NANSEN_PNL_SUMMARY_PATH:
        return "pnl_summary"
    if path == NANSEN_FIRST_FUNDER_PATH:
        return "first_funder"
    raise SeedSourceError(f"no Nansen schema for path {path}")


def nansen_iso_datetime(unix):
    return datetime.fromtimestamp(int(unix), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def nansen_date_range_from_bounds(bounds):
    start = int((bounds or {}).get("report_start_unix") or 0)
    end = int((bounds or {}).get("report_end_unix") or 0)
    if start <= 0 or end <= 0 or end <= start:
        end = utc_now_unix()
        start = end - (90 * 86400)
    return nansen_iso_datetime(start), nansen_iso_datetime(end)


def nansen_billing_from_headers(headers):
    """Capture official Nansen billing headers. Values are strings or None."""
    if headers is None:
        return {
            "credits_cost": None,
            "credits_used": None,
            "credits_remaining": None,
            "request_id": None,
        }
    getter = headers.get if hasattr(headers, "get") else lambda key, default=None: None
    return {
        "credits_cost": getter("X-Nansen-Credits-Cost") or getter("x-nansen-credits-cost"),
        "credits_used": getter("X-Nansen-Credits-Used") or getter("x-nansen-credits-used"),
        "credits_remaining": getter("X-Nansen-Credits-Remaining") or getter("x-nansen-credits-remaining"),
        "request_id": getter("X-Request-Id") or getter("x-request-id"),
    }


def redact_nansen_error_body(payload):
    """Keep the official error envelope fields only. No raw secrets or addresses."""
    if not isinstance(payload, dict):
        return {"message": "non-json"}
    return {
        "code": payload.get("code"),
        "message": payload.get("message") or payload.get("error"),
        "error": payload.get("error"),
        "status": payload.get("status"),
        "request_id": payload.get("request_id"),
        "param": payload.get("param"),
        "doc_url": payload.get("doc_url"),
    }


def token_txs_params(token, *, offset=0, limit=50):
    """GET /defi/txs/token query. No after_time/before_time; filter client-side."""
    return {
        "address": token,
        "offset": int(offset),
        "limit": int(limit),
        "tx_type": "swap",
        "sort_type": "desc",
    }


def canonicalize_seed_name(name):
    return SEED_ALIASES.get(name, name)


def parse_seed_sources(raw):
    """Parse combinable --seed-source values. Empty inherits later."""
    if raw in (None, "", []):
        return []
    if isinstance(raw, (list, tuple)):
        parts = [str(item).strip() for item in raw if str(item).strip()]
    else:
        parts = [part.strip() for part in str(raw).split(",") if part.strip()]
    unknown = [part for part in parts if part not in SEED_SOURCES]
    if unknown:
        raise SeedSourceError(f"unknown --seed-source {unknown}; choose from {sorted(PRIMARY_SEED_SOURCES)}")
    seen = set()
    ordered = []
    for part in parts:
        mapped = canonicalize_seed_name(part)
        if mapped == SEED_PRESCREEN_FILTER:
            if mapped not in seen:
                ordered.append(mapped)
                seen.add(mapped)
            continue
        if mapped not in seen:
            ordered.append(mapped)
            seen.add(mapped)
    return ordered


def resolve_seed_sources(seed_sources, discovery_source):
    sources = list(seed_sources or [])
    if not any(item in PRIMARY_SEED_SOURCES for item in sources):
        fallback = canonicalize_seed_name(discovery_source or SEED_BIRDEYE_TOP)
        if fallback not in PRIMARY_SEED_SOURCES:
            fallback = SEED_BIRDEYE_TOP
        extras = [item for item in sources if item == SEED_PRESCREEN_FILTER]
        sources = [fallback, *extras]
    return sources


def primary_seed_source(sources):
    for item in sources or []:
        if item in PRIMARY_SEED_SOURCES:
            return item
    return SEED_BIRDEYE_TOP


def cheap_prescreen_enabled(sources):
    return SEED_PRESCREEN_FILTER in (sources or [])


def helius_triage_enabled(sources):
    """3-sample triage runs for the new seed paths, not legacy birdeye_top-only."""
    return any(item in {SEED_TOKEN_INTERSECT, SEED_NANSEN} for item in (sources or []))


def nansen_source_selected(sources):
    return SEED_NANSEN in (sources or [])


def leaderboard_not_viable_reason():
    return (
        "GMGN/Cielo/Kolscan are not viable without a key or scrape. "
        "Use --seed-source nansen with NANSEN_API_KEY for the official leaderboard."
    )


def estimate_seed_plan(sources, *, tokens=None, discovery=True, wallets=None, nansen_enabled=False, birdeye_top_mode=None):
    """Dry-run request/credit estimates per selected source. No HTTP."""
    sources = [canonicalize_seed_name(item) for item in (sources or [])]
    tokens = list(tokens or [])
    wallets = list(wallets or [])
    per_source = {}
    birdeye_requests = 0
    birdeye_units = 0
    nansen_requests = 0
    nansen_units = 0
    helius_triage_requests = 0
    helius_triage_units = 0
    run_discovery = discovery or not wallets
    if run_discovery and SEED_BIRDEYE_TOP in sources:
        if birdeye_top_mode == "top-traders":
            token_n = max(len(tokens), 1)
            birdeye_requests += token_n
            birdeye_units += token_n * 35
            per_source[SEED_BIRDEYE_TOP] = {
                "provider": "birdeye",
                "requests": token_n,
                "units": token_n * 35,
                "billing_unit": "birdeye_compute_unit",
                "note": "top-traders 35 CU per token via --discovery-source top-traders.",
            }
        else:
            birdeye_requests += 1
            birdeye_units += 30
            per_source[SEED_BIRDEYE_TOP] = {
                "provider": "birdeye",
                "requests": 1,
                "units": 30,
                "billing_unit": "birdeye_compute_unit",
                "note": "Default gainers-losers 30 CU. top-traders is 35 CU/token via --discovery-source.",
            }
    if run_discovery and SEED_TOKEN_INTERSECT in sources:
        token_n = len(tokens) if tokens else (TOKEN_INTERSECT_SEASONED + TOKEN_INTERSECT_CONTROLS)
        list_req = 0 if tokens else 1
        tx_req = token_n * TOKEN_INTERSECT_WINDOWS * TOKEN_INTERSECT_PAGES_PER_WINDOW
        units = (0 if tokens else BIRDEYE_TOKEN_LIST_UNITS) + tx_req * BIRDEYE_TOKEN_TXS_UNITS
        birdeye_requests += list_req + tx_req
        birdeye_units += units
        per_source[SEED_TOKEN_INTERSECT] = {
            "provider": "birdeye",
            "requests": list_req + tx_req,
            "units": units,
            "billing_unit": "birdeye_compute_unit",
            "token_list_requests": list_req,
            "token_tx_requests": tx_req,
            "note": SEED_CU_DOCS[SEED_TOKEN_INTERSECT]["note"],
        }
    if run_discovery and SEED_NANSEN in sources:
        if nansen_enabled:
            nansen_requests += len(NANSEN_TIMEFRAMES)
            nansen_units += len(NANSEN_TIMEFRAMES) * NANSEN_LEADERBOARD_UNITS
            per_source[SEED_NANSEN] = {
                "provider": "nansen",
                "requests": nansen_requests,
                "units": nansen_units,
                "billing_unit": "nansen_credit",
                "timeframes": list(NANSEN_TIMEFRAMES),
                "note": "2 leaderboard calls (90d/180d). Profiler is planned only for kept candidates.",
            }
        else:
            per_source[SEED_NANSEN] = {
                "provider": "nansen",
                "requests": 0,
                "units": 0,
                "enabled": False,
                "note": "NANSEN_API_KEY absent; source disabled; no dummy call.",
            }
    n = len(wallets)
    if helius_triage_enabled(sources) and n:
        helius_triage_requests = n * TRIAGE_SAMPLES
        helius_triage_units = helius_triage_requests * TRIAGE_SAMPLE_UNITS
    if helius_triage_enabled(sources):
        per_source["helius_triage"] = {
            "provider": "helius",
            "requests": helius_triage_requests,
            "units": helius_triage_units,
            "billing_unit": "helius_credit",
            "samples": ["earliest", "recent", "older_month"],
            "note": (
                "Up to 3 bounded full samples (limit 100, 10 credits). "
                ">25 economic trades in one UTC day rejects. Under 25 proves nothing. "
                "Prefer 180+ days of observed age. Survivors only get --history-to-first."
            ),
        }
    return {
        "seed_sources": sources,
        "primary_seed_source": primary_seed_source(sources),
        "per_source": per_source,
        "totals": {
            "birdeye_requests": birdeye_requests,
            "birdeye_units": birdeye_units,
            "nansen_requests": nansen_requests,
            "nansen_units": nansen_units,
            "helius_triage_requests": helius_triage_requests,
            "helius_triage_units": helius_triage_units,
            "leaderboard_requests": 0,
            "leaderboard_units": 0,
        },
        "seed_is_not": "evidence",
        "PRODUCT_READY": False,
    }


def _as_number(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _as_unix(value):
    if type(value) is int and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _safe_address(value):
    try:
        return validate_address(value)
    except (TypeError, ValueError):
        return None


def token_list_items(body):
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if isinstance(data, dict):
        items = data.get("items") or data.get("tokens") or data.get("list")
        if isinstance(items, list):
            return items
    if isinstance(data, list):
        return data
    items = body.get("items")
    return items if isinstance(items, list) else []


def select_durable_tokens(items, *, now_unix, skip_mints=None, limit=TOKEN_INTERSECT_SEASONED):
    """Tokens listed for weeks that still trade. Not a lead."""
    skip = set(skip_mints or ()) | QUOTE_MINTS
    min_listing = int(now_unix) - (DURABLE_TOKEN_MIN_AGE_DAYS * 86400)
    min_last_trade = int(now_unix) - (DURABLE_TOKEN_MAX_LAST_TRADE_AGE_DAYS * 86400)
    picked = []
    for row in items or []:
        if not isinstance(row, dict):
            continue
        address = _safe_address(row.get("address") or row.get("mint"))
        if not address or address in skip:
            continue
        liquidity = _as_number(row.get("liquidity") or row.get("liquidity_usd"))
        market_cap = _as_number(row.get("mc") or row.get("market_cap") or row.get("marketcap"))
        listing = _as_unix(
            row.get("recent_listing_time") or row.get("listing_time") or row.get("created_at")
        )
        last_trade = _as_unix(
            row.get("last_trade_unix_time") or row.get("last_trade_time") or row.get("last_trade")
        )
        if liquidity is None or liquidity < Decimal(DURABLE_TOKEN_MIN_LIQUIDITY_USD):
            continue
        if market_cap is None or market_cap < Decimal(DURABLE_TOKEN_MIN_MARKET_CAP_USD):
            continue
        if listing is None or listing > min_listing:
            continue
        if last_trade is None or last_trade < min_last_trade:
            continue
        change = _as_number(
            row.get("price_change_24h_percent")
            or row.get("v24hChangePercent")
            or row.get("price_change_24h")
        )
        picked.append({
            "address": address,
            "liquidity": str(liquidity),
            "market_cap": str(market_cap),
            "listing_time": listing,
            "last_trade_unix_time": last_trade,
            "price_change_24h_percent": str(change) if change is not None else None,
            "role": "seasoned",
            "seed_is_not": "evidence",
        })
        if len(picked) >= int(limit):
            break
    return picked


def select_control_tokens(items, *, now_unix, skip=None, limit=TOKEN_INTERSECT_CONTROLS):
    """Flat or declining seasoned tokens. Still just seeds."""
    skip = set(skip or ())
    controls = []
    for row in select_durable_tokens(items, now_unix=now_unix, skip_mints=skip, limit=50):
        change = _as_number(row.get("price_change_24h_percent"))
        if change is None or change > 0:
            continue
        row = dict(row)
        row["role"] = "control_flat_or_declining"
        controls.append(row)
        if len(controls) >= int(limit):
            break
    return controls


def ordinary_windows(listing_unix):
    """Buyer windows after the first day. Never the first-block hour."""
    start = int(listing_unix) + FIRST_BLOCK_EXCLUSION_SECONDS
    return (
        {"name": "ordinary_24h_7d", "after_time": start, "before_time": start + 6 * 86400},
        {"name": "pullback_14d_21d", "after_time": int(listing_unix) + 14 * 86400, "before_time": int(listing_unix) + 21 * 86400},
        {"name": "later_28d_35d", "after_time": int(listing_unix) + 28 * 86400, "before_time": int(listing_unix) + 35 * 86400},
    )


def token_tx_items(body):
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if isinstance(data, dict):
        items = data.get("items") or data.get("txs") or data.get("transactions")
        if isinstance(items, list):
            return items
    if isinstance(data, list):
        return data
    items = body.get("items")
    return items if isinstance(items, list) else []


def token_tx_owners(rows, *, token=None, window=None, after_time=None, before_time=None):
    """Ordinary-period buyers. First-block (tx time < after_time) are dropped."""
    owners = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        owner = _safe_address(
            row.get("owner")
            or row.get("ownerAddress")
            or row.get("wallet")
            or row.get("address")
            or (row.get("from") or {}).get("address")
            or (row.get("source") or {}).get("owner")
        )
        if not owner:
            continue
        stamp = _as_unix(
            row.get("blockUnixTime") or row.get("block_unix_time") or row.get("unixTime") or row.get("timestamp")
        )
        if after_time is not None and stamp is not None and stamp < int(after_time):
            continue
        if before_time is not None and stamp is not None and stamp > int(before_time):
            continue
        side = str(row.get("txType") or row.get("side") or row.get("type") or "swap").lower()
        if side in ("add", "remove"):
            continue
        owners.append({
            "address": owner,
            "token": token,
            "window": window,
            "tx_time": stamp,
            "seed_source": SEED_TOKEN_INTERSECT,
            "seed_is_not": "evidence",
        })
    return owners


def intersect_token_cohorts(appearances, *, min_cohorts=TOKEN_INTERSECT_MIN_COHORTS):
    """Wallets that bought >=3 unrelated seasoned/control tokens."""
    by_wallet = defaultdict(set)
    extras = {}
    for row in appearances or []:
        address = row.get("address")
        token = row.get("token")
        if not address or not token:
            continue
        by_wallet[address].add(token)
        extras.setdefault(address, {"tokens": [], "windows": []})
        extras[address]["tokens"].append(token)
        if row.get("window"):
            extras[address]["windows"].append(row.get("window"))
    selected = []
    for address, tokens in by_wallet.items():
        if len(tokens) < int(min_cohorts):
            continue
        selected.append({
            "address": address,
            "cohort_count": len(tokens),
            "tokens": sorted(tokens),
            "selection_reason": f"intersected_{len(tokens)}_unrelated_token_cohorts",
            "seed_source": SEED_TOKEN_INTERSECT,
            "seed_is_not": "evidence",
            "rank": None,
        })
    selected.sort(key=lambda row: (-row["cohort_count"], row["address"]))
    for index, row in enumerate(selected, start=1):
        row["rank"] = index
    return selected


def nansen_leaderboard_rows(body):
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get("items") or data.get("wallets") or data.get("data")
        if isinstance(items, list):
            return items
    items = body.get("items")
    return items if isinstance(items, list) else []


def select_nansen_wallets(rows, *, timeframe, seen=None):
    """Provider-ranked wallets. Metrics are stored separately, never evidence."""
    seen = set(seen or ())
    selected = []
    for index, row in enumerate(rows or [], start=1):
        if not isinstance(row, dict):
            continue
        address = _safe_address(row.get("address") or row.get("wallet") or row.get("wallet_address"))
        if not address or address in seen:
            continue
        seen.add(address)
        selected.append({
            "address": address,
            "rank": index,
            "timeframe": timeframe,
            "selection_reason": f"nansen_pnl_leaderboard_{timeframe}d",
            "seed_source": SEED_NANSEN,
            "seed_is_not": "evidence",
            "vendor_metrics": {
                "realized_pnl_usd": row.get("realized_pnl_usd"),
                "unrealized_pnl_usd": row.get("unrealized_pnl_usd"),
                "n_trades": row.get("n_trades"),
                "n_tokens": row.get("n_tokens"),
                "win_rate": row.get("win_rate"),
                "is_not": "independently_verified_profit_or_copyability",
            },
        })
    return selected


def first_buyer_rows(body):
    """Kept for fixture compatibility. token_intersect does not use first-block buyers."""
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if isinstance(data, dict):
        buyers = data.get("buyers") or data.get("items") or data.get("list")
        if isinstance(buyers, list):
            return buyers
    buyers = body.get("buyers") or body.get("items")
    return buyers if isinstance(buyers, list) else []


def select_early_buyers_sold_well(rows, *, token=None):
    """Deprecated first-buyer helper. token_intersect must not call this for seeds."""
    return []


def cheap_prescreen_decision(signals, *, max_trades_per_day=None, min_history_days=None):
    """Legacy helper. Prefer helius_triage_decision for new runs."""
    max_rate = Decimal(str(max_trades_per_day or CHEAP_MAX_TRADES_PER_DAY))
    min_age = Decimal(str(min_history_days or CHEAP_MIN_HISTORY_DAYS))
    trades_per_day = _as_number(signals.get("trades_per_day"))
    if trades_per_day is None:
        trade_count = _as_number(signals.get("trade_count"))
        window_days = _as_number(signals.get("window_days")) or Decimal("1")
        if trade_count is not None and window_days > 0:
            trades_per_day = (trade_count / window_days).quantize(Decimal("0.0001"))
    history_days = _as_number(signals.get("history_days"))
    reasons = []
    if trades_per_day is not None and trades_per_day > max_rate:
        reasons.append("cheap_prescreen_high_trade_rate")
    if history_days is not None and history_days < min_age:
        reasons.append("cheap_prescreen_short_history")
    return {
        "dropped": bool(reasons),
        "drop_reasons": reasons,
        "trades_per_day": str(trades_per_day) if trades_per_day is not None else None,
        "history_days": str(history_days) if history_days is not None else None,
        "max_trades_per_day": str(max_rate),
        "min_history_days": str(min_age),
        "seed_is_not": "evidence",
    }


def economic_trades_by_utc_day(events):
    """Count decoded buy/sell events per UTC date. Not raw transactions."""
    counts = Counter()
    for event in events or []:
        if not isinstance(event, dict):
            continue
        if event.get("kind") not in ("buy", "sell"):
            continue
        stamp = event.get("block_time") or event.get("blockTime") or event.get("timestamp")
        if type(stamp) is not int:
            continue
        day = datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()
        counts[day] += 1
    return dict(counts)


def helius_triage_decision(samples, *, now_unix, bundle=None, created_in_range=False):
    """Drop only on confirmed >25 economic trades in a UTC day, youth, or bundle.

    Under 25 economic trades/day proves nothing. Age under 180 days is a
    preference, not a hard drop, unless creation is proven under 30 days.
    """
    records = []
    events = []
    seen_sigs = set()
    seen_event_sigs = set()
    for sample in samples or []:
        for row in sample.get("records") or []:
            sig = row.get("signature") if isinstance(row, dict) else None
            if sig and sig in seen_sigs:
                continue
            if sig:
                seen_sigs.add(sig)
            records.append(row)
        for event in sample.get("events") or []:
            sig = event.get("signature") if isinstance(event, dict) else None
            if sig and sig in seen_event_sigs:
                continue
            if sig:
                seen_event_sigs.add(sig)
            events.append(event)
    times = []
    for row in records:
        if not isinstance(row, dict):
            continue
        stamp = row.get("blockTime") or row.get("timestamp")
        if stamp is None:
            stamp = ((row.get("transaction") or {}).get("blockTime"))
        if type(stamp) is int:
            times.append(stamp)
    oldest = min(times) if times else None
    history_days = None
    if oldest is not None:
        history_days = (Decimal(int(now_unix) - oldest) / Decimal(86400)).quantize(Decimal("0.0001"))
    by_day = economic_trades_by_utc_day(events)
    max_day = max(by_day.values()) if by_day else 0
    reasons = []
    if max_day > 25:
        reasons.append("triage_gt_25_economic_trades_in_one_day")
    if created_in_range and history_days is not None and history_days < CHEAP_MIN_HISTORY_DAYS:
        reasons.append("triage_short_history")
    if (bundle or {}).get("excluded"):
        reasons.append((bundle or {}).get("reason") or "bundle_or_distribution")
    return {
        "dropped": bool(reasons),
        "drop_reasons": reasons,
        "history_days": str(history_days) if history_days is not None else None,
        "prefer_age_days": str(TRIAGE_PREFER_AGE_DAYS),
        "age_preferred": bool(history_days is not None and history_days >= TRIAGE_PREFER_AGE_DAYS),
        "economic_trades_by_day": by_day,
        "max_economic_trades_in_one_day": max_day,
        "transactions": len(records),
        "economic_trades": sum(by_day.values()),
        "count_kinds": list(COUNT_KINDS),
        "seed_is_not": "evidence",
    }


def history_span_days(records, *, created_in_range=False, now_unix=None):
    times = []
    for row in records or []:
        if not isinstance(row, dict):
            continue
        stamp = row.get("blockTime") or row.get("timestamp")
        if stamp is None:
            stamp = ((row.get("transaction") or {}).get("blockTime"))
        if type(stamp) is int:
            times.append(stamp)
    if not times:
        return None
    oldest = min(times)
    newest = max(times)
    end = int(now_unix) if now_unix is not None else newest
    if created_in_range:
        return (Decimal(end - oldest) / Decimal(86400)).quantize(Decimal("0.0001"))
    return None


def record_seed_metadata(state, address, source, extra=None):
    if not address or not source:
        return None
    state.setdefault("seed_metadata", {})
    existing = state["seed_metadata"].get(address) or {}
    sources = [item for item in (existing.get("seed_sources") or []) if item]
    mapped = canonicalize_seed_name(source)
    if mapped not in sources:
        sources.append(mapped)
    meta = {
        "seed_sources": sources,
        "primary_seed_source": sources[0],
        "seed_is_not": "evidence",
    }
    for key, value in (existing or {}).items():
        if key not in meta and key not in ("seed_sources", "primary_seed_source"):
            meta[key] = value
    for key, value in (extra or {}).items():
        if value is not None:
            meta[key] = value
    state["seed_metadata"][address] = meta
    return meta


def seed_fields_for_wallet(state, address):
    meta = ((state or {}).get("seed_metadata") or {}).get(address) or {}
    if not meta:
        return {
            "seed_source": None,
            "seed_sources": [],
            "seed_rank": None,
            "selection_reason": None,
            "seed_is_not": "evidence",
            "vendor_metrics": None,
        }
    return {
        "seed_source": meta.get("primary_seed_source"),
        "seed_sources": list(meta.get("seed_sources") or []),
        "seed_rank": meta.get("rank"),
        "selection_reason": meta.get("selection_reason"),
        "seed_is_not": "evidence",
        "vendor_metrics": meta.get("vendor_metrics"),
        "seed_token": meta.get("token"),
    }


def cost_per_audit_worthy(spend_by_source, audit_worthy_by_source):
    """Credits per independently audited wallet. None when the denominator is 0."""
    out = {}
    for source, spend in (spend_by_source or {}).items():
        worthy = int((audit_worthy_by_source or {}).get(source) or 0)
        units = int((spend or {}).get("units") or 0)
        out[source] = {
            "units": units,
            "requests": int((spend or {}).get("requests") or 0),
            "audit_worthy": worthy,
            "cost_per_audit_worthy": None if worthy <= 0 else str((Decimal(units) / Decimal(worthy)).quantize(Decimal("0.0001"))),
            "seed_is_not": "evidence",
        }
    return out


def pinned_research_program_ids():
    """Research IDs that already match investigation.py constants."""
    return {
        key: value
        for key, value in RESEARCH_PROGRAM_IDS.items()
        if not key.endswith("_unverified")
    }


def unverified_research_program_ids():
    """ChatGPT-supplied IDs that must not become supported venues."""
    return {
        key: value
        for key, value in RESEARCH_PROGRAM_IDS.items()
        if key.endswith("_unverified")
    }


def utc_now_unix():
    return int(datetime.now(timezone.utc).timestamp())
