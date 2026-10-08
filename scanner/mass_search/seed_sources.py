"""Phase 1 seed sources. A seed is never evidence.

Combinable sources: birdeye_top, token_intersect, nansen.
Cheap Helius triage (earliest / recent / older-month) runs after seeds
and before --history-to-first. Vendor metrics stay on seed_metadata.

GMGN / Cielo / Kolscan stay unimplemented (no keyless ToS-safe API).
Nansen is optional: missing NANSEN_API_KEY disables the source and
must never produce a dummy live call.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from scanner.config import validate_address
from scanner.mass_search.qualification_gates import (
    GT_ECONOMIC_TRADES_RULE,
    HISTORY_AGE_RULE,
    HISTORY_AGE_RULE_HELIUS,
    MAX_ECONOMIC_TRADES_PER_UTC_DAY,
    combined_economic_trade_rate,
    economic_trades_by_utc_day,
    first_defined_int,
    raw_economic_trade_rate,
)

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
# Official Birdeye CU table (data.birdeye.so, linked from docs.birdeye.so
# llms.txt; the docs.birdeye.so/docs/compute-unit-cost URL 404s):
# GET /defi/v3/token/list = 50 CU (code uses 60 = safe over-count);
# GET /defi/txs/token = 10 CU;
# GET /defi/txs/token/seek_by_time = 12 CU (Lite+ only).
BIRDEYE_TOKEN_LIST_UNITS = 60
BIRDEYE_FIRST_BUYERS_UNITS = 25
BIRDEYE_TOKEN_TX_SEEK_UNITS = 12
BIRDEYE_TOKEN_TXS_UNITS = 10
BIRDEYE_CU_VERIFIED_ON = "2026-10-08"
BIRDEYE_CU_DOCS_URL = "https://data.birdeye.so"

NANSEN_HOST = "api.nansen.ai"
NANSEN_KEY_ENV = "NANSEN_API_KEY"
NANSEN_LEADERBOARD_PATH = "/api/v1/smart-money/pnl-leaderboard"
NANSEN_PNL_SUMMARY_PATH = "/api/v1/profiler/address/pnl-summary"
NANSEN_FIRST_FUNDER_PATH = "/api/v1/profiler/address/first-funder"
NANSEN_LABELS_PATH = "/api/v1/profiler/address/labels"
NANSEN_DEX_TRADES_PATH = "/api/v1/profiler/dex-trades"
NANSEN_TGM_PNL_LEADERBOARD_PATH = "/api/v1/tgm/pnl-leaderboard"
ALLOWED_NANSEN_PATHS = frozenset({
    NANSEN_LEADERBOARD_PATH,
    NANSEN_PNL_SUMMARY_PATH,
    NANSEN_FIRST_FUNDER_PATH,
    NANSEN_DEX_TRADES_PATH,
    NANSEN_TGM_PNL_LEADERBOARD_PATH,
})
NANSEN_LEADERBOARD_UNITS = 5
NANSEN_TGM_PNL_LEADERBOARD_UNITS = 5
NANSEN_PROFILER_UNITS = 1
NANSEN_DEX_TRADES_UNITS = 1
NANSEN_LEADERBOARD_PER_PAGE = 50
NANSEN_LEADERBOARD_PER_PAGE_MAX = 1000
NANSEN_DEX_TRADES_MAX_PAGES = 3
NANSEN_DEX_TRADES_HISTORY_FROM = "2020-03-17"
NANSEN_DEX_TRADES_MAX_PER_DAY = Decimal(MAX_ECONOMIC_TRADES_PER_UTC_DAY)
# D11-4 / D11-6: Nansen coverage is incomplete (9T546u). Age drop is off
# unless an explicit min_history_days or a Helius first-signature time is
# supplied. Named so grant/runner config can select helius_first_signature.
NANSEN_DEX_TRADES_MIN_HISTORY_DAYS = None
HISTORY_AGE_RULE_DEFAULT = HISTORY_AGE_RULE
NANSEN_TIMEFRAMES_FUNNEL = (30, 90, 180)
RULE_A_MAX_AVG_TRADES_PER_DAY = Decimal("5")
RULE_A_MIN_TOKENS = 2
RULE_A_MAX_TOKENS = 30
RULE_A_MIN_REALIZED_PNL = Decimal("0")
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
    "dex_trades": {
        "additionalProperties": False,
        "required": ["address", "chain", "date"],
        "properties": {
            "address": {"type": "string"},
            "chain": {"type": "string"},
            "date": {"type": "object", "required": ["from", "to"], "properties": {"from": {"type": "string"}, "to": {"type": "string"}}},
            "pagination": {"type": "object"},
            "order_by": {"type": "array"},
        },
    },
    "tgm_pnl_leaderboard": {
        "additionalProperties": False,
        "required": ["chain", "token_address"],
        "properties": {
            "chain": {"type": "string"},
            "token_address": {"type": "string"},
            "date": {"type": "object"},
            "pagination": {"type": "object"},
            "filters": {"type": "object"},
            "order_by": {"type": "array"},
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

CHEAP_MAX_TRADES_PER_DAY = Decimal(MAX_ECONOMIC_TRADES_PER_UTC_DAY)
CHEAP_MIN_HISTORY_DAYS = Decimal("30")
# Helius Standard JSON-RPC. https://www.helius.dev/docs/billing/credits
# Standard methods = 1 credit. getSignaturesForAddress returns ≤1000
# signatures per call. Enhanced getTransactionsForAddress is not this method.
HELIUS_SIGNATURES_METHOD = "getSignaturesForAddress"
HELIUS_SIGNATURES_PAGE_SIZE = 1000
HELIUS_SIGNATURES_UNITS = 1
HELIUS_SIGNATURES_HISTORY_CAP = 50_000
HELIUS_SIGNATURES_CREDIT_NOTE = (
    "Helius Standard JSON-RPC getSignaturesForAddress costs 1 credit per call "
    "(https://www.helius.dev/docs/billing/credits). 1000 signatures per request. "
    "Enhanced history is a different, more expensive method and is not used here."
)
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

# Bot-rule definition (app + independent auditor, 2026-10-08):
# Every economic swap is a trade, including token-to-token. Identity is
# (signature, kind, mint): one multi-leg tx is not counted more than once
# per mint/kind. Route-leg hops are not trades, so a multi-hop route in one
# tx is one trade, not one per hop. An independent unique-(sig, kind, mint)
# count must match. Under 15/day proves nothing; >15 on full history is the
# lead gate.
BOT_RULE_DEFINITION = (
    "economic_swap_including_token_to_token; "
    "dedupe=(signature,kind,mint); "
    "route_legs_are_not_trades; "
    "multi_hop_same_tx_counts_once_per_mint_kind"
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
    if kind == "tgm_pnl_leaderboard":
        refuse_nansen_premium_labels(body)
    return True


def refuse_nansen_premium_labels(body):
    """tgm/pnl-leaderboard charges 150 credits when premium_labels is true."""
    if not isinstance(body, dict):
        return True
    if body.get("premium_labels") not in (None, False):
        raise SeedSourceError("Nansen tgm/pnl-leaderboard refuses premium_labels")
    filters = body.get("filters")
    if isinstance(filters, dict) and filters.get("premium_labels") not in (None, False):
        raise SeedSourceError("Nansen tgm/pnl-leaderboard refuses premium_labels")
    return True


def nansen_per_page(value, default=NANSEN_LEADERBOARD_PER_PAGE):
    try:
        page = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        page = int(default)
    if page < 1 or page > NANSEN_LEADERBOARD_PER_PAGE_MAX:
        raise SeedSourceError(
            f"Nansen per_page must be 1..{NANSEN_LEADERBOARD_PER_PAGE_MAX}, got {page}"
        )
    return page


def nansen_leaderboard_body(*, timeframe, page=1, per_page=50):
    body = {
        "chains": [NANSEN_CHAIN],
        "timeframe": int(timeframe),
        "pagination": {"page": int(page), "per_page": nansen_per_page(per_page)},
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


def nansen_dex_trades_body(*, address, date_from, date_to, page=1, per_page=1000):
    body = {
        "address": address,
        "chain": NANSEN_CHAIN,
        "date": {"from": date_from, "to": date_to},
        "pagination": {"page": int(page), "per_page": nansen_per_page(per_page)},
        "order_by": [{"field": "block_timestamp", "direction": "DESC"}],
    }
    validate_nansen_body("dex_trades", body)
    return body


def nansen_tgm_pnl_leaderboard_body(
    *,
    token_address,
    date_from=None,
    date_to=None,
    page=1,
    per_page=1000,
    nof_trades_min=2,
    nof_trades_max=20,
    pnl_usd_realised_min=2000,
):
    body = {
        "chain": NANSEN_CHAIN,
        "token_address": token_address,
        "pagination": {"page": int(page), "per_page": nansen_per_page(per_page)},
        "filters": {
            "nof_trades": {"min": int(nof_trades_min), "max": int(nof_trades_max)},
            "pnl_usd_realised": {"min": int(pnl_usd_realised_min)},
        },
    }
    if date_from and date_to:
        body["date"] = {"from": date_from, "to": date_to}
    refuse_nansen_premium_labels(body)
    validate_nansen_body("tgm_pnl_leaderboard", body)
    return body


def nansen_schema_kind_for_path(path):
    if path == NANSEN_LEADERBOARD_PATH:
        return "leaderboard"
    if path == NANSEN_PNL_SUMMARY_PATH:
        return "pnl_summary"
    if path == NANSEN_FIRST_FUNDER_PATH:
        return "first_funder"
    if path == NANSEN_DEX_TRADES_PATH:
        return "dex_trades"
    if path == NANSEN_TGM_PNL_LEADERBOARD_PATH:
        return "tgm_pnl_leaderboard"
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


def nansen_leaderboard_page_count(pages=None):
    try:
        return max(1, int(pages or 1))
    except (TypeError, ValueError):
        return 1


def estimate_nansen_profiler_count(
    *,
    profile_cap=None,
    request_cap=None,
    unit_cap=None,
    already_requests=0,
    already_units=0,
    leaderboard_pages=1,
    per_page=None,
    timeframes=None,
):
    """Upper bound on pnl-summary calls. Runtime must not exceed this."""
    frames = tuple(timeframes) if timeframes else NANSEN_TIMEFRAMES
    leaderboard_req = len(frames) * nansen_leaderboard_page_count(leaderboard_pages)
    leaderboard_units = leaderboard_req * NANSEN_LEADERBOARD_UNITS
    page_size = NANSEN_LEADERBOARD_PER_PAGE
    try:
        if per_page not in (None, ""):
            page_size = nansen_per_page(per_page)
    except SeedSourceError:
        page_size = NANSEN_LEADERBOARD_PER_PAGE
    worst = page_size * leaderboard_req
    profile_n = worst
    if profile_cap is not None:
        profile_n = min(profile_n, max(0, int(profile_cap)))
    if request_cap is not None:
        remaining = max(0, int(request_cap) - int(already_requests) - leaderboard_req)
        profile_n = min(profile_n, remaining)
    if unit_cap is not None:
        remaining_units = max(0, int(unit_cap) - int(already_units) - leaderboard_units)
        profile_n = min(profile_n, remaining_units // NANSEN_PROFILER_UNITS)
    return profile_n


def estimate_nansen_dex_trades_count(
    *,
    wallet_cap=0,
    max_pages=NANSEN_DEX_TRADES_MAX_PAGES,
    request_cap=None,
    unit_cap=None,
    already_requests=0,
    already_units=0,
):
    """Upper bound on profiler/dex-trades calls. Counts calls, not rows."""
    try:
        wallets = max(0, int(wallet_cap or 0))
    except (TypeError, ValueError):
        wallets = 0
    try:
        pages = int(max_pages if max_pages not in (None, "") else NANSEN_DEX_TRADES_MAX_PAGES)
    except (TypeError, ValueError):
        pages = NANSEN_DEX_TRADES_MAX_PAGES
    if pages < 1:
        raise ValueError("nansen_dex_trades_max_pages must be >= 1")
    bound = wallets * pages
    if request_cap is not None:
        bound = min(bound, max(0, int(request_cap) - int(already_requests)))
    if unit_cap is not None:
        bound = min(bound, max(0, int(unit_cap) - int(already_units)) // NANSEN_DEX_TRADES_UNITS)
    return bound


def estimate_helius_signatures_count(
    wallet_count,
    *,
    history_cap=None,
    page_size=None,
    request_cap=None,
    unit_cap=None,
    already_requests=0,
    already_units=0,
):
    """Worst-case getSignaturesForAddress calls. Plan ≥ runtime."""
    try:
        wallets = max(0, int(wallet_count or 0))
    except (TypeError, ValueError):
        wallets = 0
    try:
        cap = int(history_cap if history_cap not in (None, "") else HELIUS_SIGNATURES_HISTORY_CAP)
    except (TypeError, ValueError):
        cap = HELIUS_SIGNATURES_HISTORY_CAP
    try:
        size = int(page_size if page_size not in (None, "") else HELIUS_SIGNATURES_PAGE_SIZE)
    except (TypeError, ValueError):
        size = HELIUS_SIGNATURES_PAGE_SIZE
    if size < 1:
        raise ValueError("helius signatures page size must be >= 1")
    pages = (max(cap, 1) + size - 1) // size
    bound = wallets * pages
    if request_cap is not None:
        bound = min(bound, max(0, int(request_cap) - int(already_requests)))
    if unit_cap is not None:
        leftover = max(0, int(unit_cap) - int(already_units))
        bound = min(bound, leftover // HELIUS_SIGNATURES_UNITS)
    return bound


def estimate_seed_plan(
    sources,
    *,
    tokens=None,
    discovery=True,
    wallets=None,
    nansen_enabled=False,
    birdeye_top_mode=None,
    nansen_profile_cap=None,
    nansen_request_cap=None,
    nansen_unit_cap=None,
    nansen_leaderboard_pages=1,
    nansen_per_page=None,
    nansen_dex_trades_wallet_cap=0,
    nansen_dex_trades_max_pages=NANSEN_DEX_TRADES_MAX_PAGES,
    nansen_token_pnl_tokens=None,
    nansen_token_pnl_max_calls=0,
    birdeye_retry_headroom=2,
    nansen_calibrate=False,
    nansen_timeframes=None,
    helius_signatures_prescreen=False,
    helius_signatures_history_cap=None,
):
    """Dry-run request/credit estimates per selected source. No HTTP.

    Nansen includes leaderboard calls plus optional profiler / dex-trades /
    per-token pnl-leaderboard loops. Planner counts calls, not rows.
    Calibration mode plans dex-trades only (D11-1: plan ≥ runtime).
    """
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
    try:
        retry_headroom = max(0, int(birdeye_retry_headroom or 0))
    except (TypeError, ValueError):
        retry_headroom = 0
    if run_discovery and SEED_BIRDEYE_TOP in sources:
        if birdeye_top_mode == "top-traders":
            token_n = max(len(tokens), 1)
            birdeye_requests += token_n + retry_headroom
            birdeye_units += token_n * 35 + retry_headroom * 35
            per_source[SEED_BIRDEYE_TOP] = {
                "provider": "birdeye",
                "requests": token_n + retry_headroom,
                "units": token_n * 35 + retry_headroom * 35,
                "billing_unit": "birdeye_compute_unit",
                "retry_headroom_requests": retry_headroom,
                "note": "top-traders 35 CU per token via --discovery-source top-traders.",
            }
        else:
            birdeye_requests += 1 + retry_headroom
            birdeye_units += 30 + retry_headroom * 30
            per_source[SEED_BIRDEYE_TOP] = {
                "provider": "birdeye",
                "requests": 1 + retry_headroom,
                "units": 30 + retry_headroom * 30,
                "billing_unit": "birdeye_compute_unit",
                "retry_headroom_requests": retry_headroom,
                "note": "Default gainers-losers 30 CU. top-traders is 35 CU/token via --discovery-source.",
            }
    if run_discovery and SEED_TOKEN_INTERSECT in sources:
        token_n = len(tokens) if tokens else (TOKEN_INTERSECT_SEASONED + TOKEN_INTERSECT_CONTROLS)
        list_req = 0 if tokens else 1
        tx_req = token_n * TOKEN_INTERSECT_WINDOWS * TOKEN_INTERSECT_PAGES_PER_WINDOW
        units = (0 if tokens else BIRDEYE_TOKEN_LIST_UNITS) + tx_req * BIRDEYE_TOKEN_TXS_UNITS
        try:
            retry_headroom = max(0, int(birdeye_retry_headroom or 0))
        except (TypeError, ValueError):
            retry_headroom = 0
        retry_units = retry_headroom * (
            BIRDEYE_TOKEN_LIST_UNITS if list_req else BIRDEYE_TOKEN_TXS_UNITS
        )
        birdeye_requests += list_req + tx_req + retry_headroom
        birdeye_units += units + retry_units
        per_source[SEED_TOKEN_INTERSECT] = {
            "provider": "birdeye",
            "requests": list_req + tx_req + retry_headroom,
            "units": units + retry_units,
            "billing_unit": "birdeye_compute_unit",
            "token_list_requests": list_req,
            "token_tx_requests": tx_req,
            "retry_headroom_requests": retry_headroom,
            "note": SEED_CU_DOCS[SEED_TOKEN_INTERSECT]["note"],
        }
    if run_discovery and SEED_NANSEN in sources:
        if nansen_enabled:
            if nansen_timeframes:
                frames = tuple(int(item) for item in nansen_timeframes)
            else:
                frames = NANSEN_TIMEFRAMES
            pages = nansen_leaderboard_page_count(nansen_leaderboard_pages)
            if nansen_calibrate:
                leaderboard_req = 0
                leaderboard_units = 0
                profile_n = 0
            else:
                leaderboard_req = len(frames) * pages
                leaderboard_units = leaderboard_req * NANSEN_LEADERBOARD_UNITS
                profile_n = estimate_nansen_profiler_count(
                    profile_cap=nansen_profile_cap,
                    request_cap=nansen_request_cap,
                    unit_cap=nansen_unit_cap,
                    leaderboard_pages=pages,
                    per_page=nansen_per_page,
                    timeframes=frames,
                )
            after_profile_req = leaderboard_req + profile_n
            after_profile_units = leaderboard_units + profile_n * NANSEN_PROFILER_UNITS
            dex_n = estimate_nansen_dex_trades_count(
                wallet_cap=nansen_dex_trades_wallet_cap,
                max_pages=nansen_dex_trades_max_pages,
                request_cap=nansen_request_cap,
                unit_cap=nansen_unit_cap,
                already_requests=after_profile_req,
                already_units=after_profile_units,
            )
            token_n = 0
            try:
                call_cap = max(0, int(nansen_token_pnl_max_calls or 0))
            except (TypeError, ValueError):
                call_cap = 0
            planned_tokens = select_discovery_tokens(
                configured=nansen_token_pnl_tokens,
                limit=call_cap,
            )
            if planned_tokens:
                token_n = len(planned_tokens)
                if nansen_request_cap is not None:
                    token_n = min(token_n, max(0, int(nansen_request_cap) - after_profile_req - dex_n))
                if nansen_unit_cap is not None:
                    leftover = max(0, int(nansen_unit_cap) - after_profile_units - dex_n * NANSEN_DEX_TRADES_UNITS)
                    token_n = min(token_n, leftover // NANSEN_TGM_PNL_LEADERBOARD_UNITS)
            nansen_requests += after_profile_req + dex_n + token_n
            nansen_units += (
                after_profile_units
                + dex_n * NANSEN_DEX_TRADES_UNITS
                + token_n * NANSEN_TGM_PNL_LEADERBOARD_UNITS
            )
            per_source[SEED_NANSEN] = {
                "provider": "nansen",
                "requests": nansen_requests,
                "units": nansen_units,
                "billing_unit": "nansen_credit",
                "timeframes": list(frames),
                "calibration": bool(nansen_calibrate),
                "leaderboard_requests": leaderboard_req,
                "leaderboard_pages": pages,
                "leaderboard_per_page": nansen_per_page or NANSEN_LEADERBOARD_PER_PAGE,
                "profiler_requests": profile_n,
                "profile_cap": nansen_profile_cap,
                "dex_trades_requests": dex_n,
                "token_pnl_requests": token_n,
                "note": (
                    (
                        f"calibration: 0 leaderboard, {dex_n} dex-trades "
                        f"({nansen_dex_trades_wallet_cap} wallets × "
                        f"{nansen_dex_trades_max_pages} page(s)). Plan ≥ runtime."
                    )
                    if nansen_calibrate else
                    (
                        f"{leaderboard_req} leaderboard calls "
                        f"({len(frames)} timeframes × {pages} page(s), "
                        f"per_page={nansen_per_page or NANSEN_LEADERBOARD_PER_PAGE}) plus up to "
                        f"{profile_n} pnl-summary, {dex_n} dex-trades and {token_n} "
                        "tgm/pnl-leaderboard calls. Planner counts calls, not rows. "
                        "Already-known wallets from --exclude-known-from are skipped."
                    )
                ),
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
            "samples": ["earliest", "recent", "densest_day_or_older_month"],
            "note": (
                "Up to 3 bounded full samples (limit 100, 10 credits): earliest, "
                "recent, then the densest UTC day from those samples (older-month "
                f"fallback). >{MAX_ECONOMIC_TRADES_PER_UTC_DAY} economic trades "
                f"in one UTC day rejects. Under {MAX_ECONOMIC_TRADES_PER_UTC_DAY} "
                "proves nothing. Prefer 180+ days of observed age. Survivors only "
                "get --history-to-first."
            ),
        }
    if helius_signatures_prescreen and n:
        sig_n = estimate_helius_signatures_count(
            n, history_cap=helius_signatures_history_cap,
        )
        helius_triage_requests += sig_n
        helius_triage_units += sig_n * HELIUS_SIGNATURES_UNITS
        per_source["helius_signatures_prescreen"] = {
            "provider": "helius",
            "method": HELIUS_SIGNATURES_METHOD,
            "requests": sig_n,
            "units": sig_n * HELIUS_SIGNATURES_UNITS,
            "billing_unit": "helius_credit",
            "page_size": HELIUS_SIGNATURES_PAGE_SIZE,
            "history_cap": helius_signatures_history_cap or HELIUS_SIGNATURES_HISTORY_CAP,
            "threshold": MAX_ECONOMIC_TRADES_PER_UTC_DAY,
            "can_only_drop_or_defer": True,
            "credit_note": HELIUS_SIGNATURES_CREDIT_NOTE,
            "note": (
                f"Worst-case {sig_n} getSignaturesForAddress calls "
                f"(1 credit each). Raw ≤{MAX_ECONOMIC_TRADES_PER_UTC_DAY} "
                "on every UTC day passes the screen; any day over needs "
                "decode. Enormous history is deferred. Drop or defer only."
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
            "leaderboard_requests": (per_source.get(SEED_NANSEN) or {}).get("leaderboard_requests") or 0,
            "leaderboard_units": (
                ((per_source.get(SEED_NANSEN) or {}).get("leaderboard_requests") or 0)
                * NANSEN_LEADERBOARD_UNITS
            ),
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


def tgm_row_address(row):
    """D12-4: tgm/pnl-leaderboard puts the wallet in trader_address."""
    if not isinstance(row, dict):
        return None
    return _safe_address(
        row.get("trader_address")
        or row.get("address")
        or row.get("wallet")
        or row.get("wallet_address")
    )


def tgm_row_metrics(row):
    """Vendor fields already on the tgm row. Used to pre-rank before Helius."""
    if not isinstance(row, dict):
        return {}
    return {
        "realized_pnl_usd": (
            row.get("pnl_usd_realised")
            or row.get("realized_pnl_usd")
            or row.get("realizedPnlUsd")
        ),
        "n_trades": row.get("nof_trades") or row.get("n_trades") or row.get("trades"),
        "unrealized_pnl_usd": row.get("pnl_usd_unrealised") or row.get("unrealized_pnl_usd"),
        "win_rate": row.get("win_rate"),
        "address_label": row.get("address_label") or row.get("label"),
        "is_not": "independently_verified_profit_or_copyability",
    }


def tgm_pre_rank_key(metrics):
    """Cheapest pre-rank: realized PnL, then trade count. Before any Helius spend."""
    try:
        pnl = Decimal(str((metrics or {}).get("realized_pnl_usd") or 0))
    except (TypeError, ValueError, ArithmeticError):
        pnl = Decimal("0")
    try:
        trades = int((metrics or {}).get("n_trades") or 0)
    except (TypeError, ValueError):
        trades = 0
    return (-pnl, -trades)


# Seasoned liquid tokens that readable wallets actually trade (run-12 keep tokens
# plus the established set). Quotes are excluded. Configurable count, hundreds.
# Jupiter verified token list (token.jup.ag) + Solana official mint pages,
# checked 2026-10-08. MEW is cat-in-a-dogs-world, not a truncated lookalike.
PINNED_MINT_SOURCES = {
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": ("JUP", "https://token.jup.ag"),
    "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": ("RAY", "https://token.jup.ag"),
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": ("BONK", "https://token.jup.ag"),
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": ("WIF", "https://token.jup.ag"),
    "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr": ("POPCAT", "https://token.jup.ag"),
    "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump": ("FARTCOIN", "https://token.jup.ag"),
    "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv": ("PENGU", "https://token.jup.ag"),
    "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN": ("TRUMP", "https://token.jup.ag"),
    "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5": ("MEW", "https://mew.xyz"),
    "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE": ("ORCA", "https://www.orca.so"),
    "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux": ("HNT", "https://www.helium.com"),
    "KMNo3nJsBXfcpJTVhZcXLW7RmTwTt4GVFE7suUBo9sS": ("KMNO", "https://kamino.finance"),
    "rndrizKT3MK1iimdxRdWabcF7Zg7AR5T4nud4EkHBof": ("RENDER", "https://rendernetwork.com"),
    "DriFtupJYLTosbwoN8koPeVaVrZK8QhKKKgqq0XKjz9": ("DRIFT", "https://www.drift.trade"),
    "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL": ("JTO", "https://token.jup.ag"),
    "85VBFQZC9TZkfaptBWjvUw7YbZjy52A6mjtPGjstQAmQ": ("W", "https://token.jup.ag"),
    "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3": ("PYTH", "https://token.jup.ag"),
}
MEW_MINT = "MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5"
DISCOVERY_LIQUID_MINTS = tuple(PINNED_MINT_SOURCES)


def select_discovery_tokens(*, configured=None, observed=None, limit=200):
    """Liquid seasoned mints. Observed readable-wallet tokens win, then the pin."""
    try:
        cap = max(0, int(limit or 0))
    except (TypeError, ValueError):
        cap = 0
    if cap == 0:
        return []
    ordered = []
    seen = set()
    for mint in list(configured or []) + list(observed or []) + list(DISCOVERY_LIQUID_MINTS):
        if not isinstance(mint, str) or not mint or mint in seen or mint in QUOTE_MINTS:
            continue
        seen.add(mint)
        ordered.append(mint)
        if cap and len(ordered) >= cap:
            break
    return ordered


def select_tgm_wallets(rows, *, token, seen=None, billing=None):
    """Every unique tgm trader. No ≥2-token intersect. Record the source token."""
    if seen is None:
        seen = {}
    selected = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        address = tgm_row_address(row)
        if not address:
            continue
        metrics = tgm_row_metrics(row)
        entry = seen.get(address)
        if entry is None:
            entry = {
                "address": address,
                "selection_reason": "nansen_tgm_pnl_leaderboard",
                "seed_source": SEED_NANSEN,
                "seed_is_not": "evidence",
                "already_seen": False,
                "vendor_metrics": dict(metrics),
                "source_tokens": [token] if token else [],
                "billing": billing,
            }
            seen[address] = entry
            selected.append(entry)
        else:
            tokens = list(entry.get("source_tokens") or [])
            if token and token not in tokens:
                tokens.append(token)
            entry["source_tokens"] = tokens
            if metrics.get("realized_pnl_usd") and not entry["vendor_metrics"].get("realized_pnl_usd"):
                entry["vendor_metrics"].update(metrics)
            if billing and not entry.get("billing"):
                entry["billing"] = billing
    return selected


def select_nansen_wallets(rows, *, timeframe, seen=None):
    """Provider-ranked wallets. Metrics are stored separately, never evidence.

    Mutates the caller's `seen` set so 90d and 180d share one dedupe. A wallet
    on both boards is selected once; per-timeframe rank/PnL is recorded later.
    """
    if seen is None:
        seen = set()
    selected = []
    for index, row in enumerate(rows or [], start=1):
        if not isinstance(row, dict):
            continue
        address = tgm_row_address(row)
        if not address:
            continue
        payload = {
            "address": address,
            "rank": index,
            "timeframe": timeframe,
            "selection_reason": f"nansen_pnl_leaderboard_{timeframe}d",
            "seed_source": SEED_NANSEN,
            "seed_is_not": "evidence",
            "already_seen": address in seen,
            "vendor_metrics": {
                "realized_pnl_usd": row.get("realized_pnl_usd"),
                "unrealized_pnl_usd": row.get("unrealized_pnl_usd"),
                "n_trades": row.get("n_trades"),
                "n_tokens": row.get("n_tokens"),
                "win_rate": row.get("win_rate"),
                "held_tokens_count": row.get("held_tokens_count"),
                "open_trades": row.get("open_trades"),
                "avg_trade_roi": row.get("avg_trade_roi"),
                "total_pnl_usd": row.get("total_pnl_usd"),
                "address_label": row.get("address_label") or row.get("label"),
                "is_not": "independently_verified_profit_or_copyability",
            },
        }
        if address not in seen:
            seen.add(address)
        selected.append(payload)
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


NANSEN_HOLD_FIELDS = (
    "avg_hold_time",
    "average_hold_time",
    "avg_holding_time",
    "hold_time",
    "median_hold_time",
    "avg_hold_seconds",
    "average_holding_period",
    "hold_time_seconds",
    "avg_hold_time_seconds",
    "avg_hold_time_ms",
    "median_hold_seconds",
)


def nansen_high_frequency_drop(
    vendor_metrics,
    *,
    timeframe=None,
    max_avg_trades_per_day=None,
    min_tokens=None,
    max_tokens=None,
    min_realized_pnl=None,
):
    """Drop-only vendor pre-filter. Missing fields never pass a wallet.

    Rule A (defaults): avg trades/day ≤ 5, 2 ≤ n_tokens ≤ 30, realized
    PnL > 0. Discovery filter only — not a proof gate. Short-hold ≤ 300s
    still drops when present. Absence of a field is not a pass; it is
    simply no drop for that rule.
    """
    metrics = dict(vendor_metrics or {})
    profiler = metrics.get("profiler_pnl_summary")
    if isinstance(profiler, dict):
        metrics = {**metrics, **profiler}
    reasons = []
    evidence = {}
    max_avg = _as_number(max_avg_trades_per_day)
    if max_avg is None:
        max_avg = RULE_A_MAX_AVG_TRADES_PER_DAY
    trades = _as_number(
        metrics.get("n_trades")
        if metrics.get("n_trades") is not None
        else metrics.get("trade_count")
        if metrics.get("trade_count") is not None
        else metrics.get("num_trades")
        if metrics.get("num_trades") is not None
        else metrics.get("trades")
    )
    days = _as_number(timeframe)
    if days is None:
        days = _as_number(metrics.get("timeframe")) or Decimal("90")
    if days <= 0:
        days = Decimal("90")
    if trades is not None:
        rate = (trades / days).quantize(Decimal("0.0001"))
        evidence["n_trades"] = str(trades)
        evidence["timeframe_days"] = str(days)
        evidence["implied_trades_per_day"] = str(rate)
        if rate > max_avg:
            reasons.append(
                f"nansen_rule_a_avg_trades_per_day:{rate}/d > {max_avg}/d over {days}d ({trades} trades)"
            )
        elif rate > CHEAP_MAX_TRADES_PER_DAY:
            reasons.append(
                f"nansen_vendor_{GT_ECONOMIC_TRADES_RULE}:{rate}/d over {days}d ({trades} trades)"
            )
    tokens = _as_number(metrics.get("n_tokens") if metrics.get("n_tokens") is not None else metrics.get("held_tokens_count"))
    min_tok = _as_number(min_tokens)
    max_tok = _as_number(max_tokens)
    if min_tok is None:
        min_tok = Decimal(RULE_A_MIN_TOKENS)
    if max_tok is None:
        max_tok = Decimal(RULE_A_MAX_TOKENS)
    if tokens is not None:
        evidence["n_tokens"] = str(tokens)
        if tokens < min_tok or tokens > max_tok:
            reasons.append(f"nansen_rule_a_token_count:{tokens} not in [{min_tok},{max_tok}]")
    pnl = _as_number(
        metrics.get("realized_pnl_usd")
        if metrics.get("realized_pnl_usd") is not None
        else metrics.get("total_pnl_usd")
    )
    min_pnl = _as_number(min_realized_pnl)
    if min_pnl is None:
        min_pnl = RULE_A_MIN_REALIZED_PNL
    if pnl is not None:
        evidence["realized_pnl_usd"] = str(pnl)
        if pnl <= min_pnl:
            reasons.append(f"nansen_rule_a_realized_pnl:{pnl} <= {min_pnl}")
    hold = None
    hold_field = None
    for field in NANSEN_HOLD_FIELDS:
        if metrics.get(field) in (None, ""):
            continue
        hold = _as_number(metrics.get(field))
        if hold is not None:
            hold_field = field
            break
    if hold is not None and hold_field:
        name = hold_field.lower()
        seconds = hold
        if "ms" in name or "millis" in name:
            seconds = hold / Decimal("1000")
        elif "minute" in name:
            seconds = hold * Decimal("60")
        elif "hour" in name:
            seconds = hold * Decimal("3600")
        elif hold > Decimal("100000"):
            seconds = hold / Decimal("1000")
        evidence[hold_field] = str(hold)
        evidence["hold_seconds"] = str(seconds)
        if seconds <= Decimal("300"):
            reasons.append(f"nansen_vendor_short_hold:{hold_field}={hold}")
    return {
        "dropped": bool(reasons),
        "drop_reasons": reasons,
        "evidence": evidence,
        "can_only_drop": True,
        "seed_is_not": "evidence",
    }


NANSEN_INFRA_LABEL_WORDS = frozenset({
    "lp", "lending", "lend", "borrow", "mm", "orderbook",
})
NANSEN_INFRA_LABEL_PHRASES = frozenset({
    "liquidity provider", "market maker", "limit order",
})


def _nansen_label_texts(meta):
    """Collect Nansen label strings, including address_label on real rows."""
    labels = []
    if not isinstance(meta, dict):
        return labels

    def _push(item):
        if isinstance(item, str) and item.strip():
            labels.append(item)
        elif isinstance(item, dict):
            text = item.get("label") or item.get("name") or item.get("type") or item.get("address_label")
            if isinstance(text, str) and text.strip():
                labels.append(text)

    raw = []
    raw.extend(meta.get("labels") or [])
    raw.extend(meta.get("nansen_labels") or [])
    _push(meta.get("address_label"))
    _push(meta.get("label"))
    vendor = meta.get("vendor_metrics") or {}
    if isinstance(vendor, dict):
        raw.extend(vendor.get("labels") or [])
        _push(vendor.get("address_label"))
        _push(vendor.get("label"))
    for item in raw:
        _push(item)
    return labels


def nansen_infra_label_drop(meta):
    """Pre-drop LP / lending / market-maker wallets from Nansen row labels.

    Real Nansen rows carry address_label (vendor_metrics.address_label).
    Match whole words/tokens only: 'alpha' must not match 'lp', and
    'community' must not match 'mm'. Empty or missing labels are no drop.
    """
    import re
    labels = _nansen_label_texts(meta)
    hits = []
    for label in labels:
        tokens = set(re.findall(r"[a-z0-9]+", label.lower()))
        phrase = " ".join(re.findall(r"[a-z0-9]+", label.lower()))
        if tokens & NANSEN_INFRA_LABEL_WORDS:
            hits.append(label)
            continue
        if any(item in phrase for item in NANSEN_INFRA_LABEL_PHRASES):
            hits.append(label)
    if not hits:
        return None
    return {
        "dropped": True,
        "drop_reasons": [f"nansen_infra_label:{label}" for label in hits],
        "evidence": {"labels": hits},
        "can_only_drop": True,
        "seed_is_not": "evidence",
    }


def nansen_dex_trades_rows(body):
    if not isinstance(body, dict):
        return []
    data = body.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        items = data.get("items") or data.get("trades") or data.get("data")
        if isinstance(items, list):
            return [row for row in items if isinstance(row, dict)]
    items = body.get("items") or body.get("trades")
    return [row for row in items if isinstance(row, dict)] if isinstance(items, list) else []


def _dex_trade_hash(row):
    return row.get("transaction_hash") or row.get("tx_hash") or row.get("signature")


def _dex_trade_timestamp(row):
    raw = row.get("block_timestamp") or row.get("timestamp") or row.get("blockTime")
    if raw in (None, ""):
        return None
    if type(raw) is int and not isinstance(raw, bool):
        return raw if raw > 10_000_000_000 else raw  # already seconds or ms?
    if isinstance(raw, str):
        text = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except (TypeError, ValueError):
            if raw.isdigit():
                return int(raw)
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    return None


def helius_signatures_prescreen(rows, *, max_per_day=None, history_cap=None):
    """Cheap getSignaturesForAddress screen. Raw tx count per UTC day.

    A raw count ≤ MAX_ECONOMIC_TRADES_PER_UTC_DAY on every day passes:
    the wallet cannot break the >15 economic-trades rule. Any day above
    the cap needs decoding. History above history_cap is deferred.
    Drop or defer only; this never marks a lead.
    """
    cap = first_defined_int(max_per_day)
    if cap is None:
        cap = MAX_ECONOMIC_TRADES_PER_UTC_DAY
    length_cap = first_defined_int(history_cap)
    if length_cap is None:
        length_cap = HELIUS_SIGNATURES_HISTORY_CAP
    by_day = defaultdict(int)
    incomplete = 0
    seen = set()
    earliest = None
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        signature = row.get("signature") or row.get("txHash") or row.get("tx_hash")
        stamp = row.get("blockTime") if row.get("blockTime") is not None else row.get("timestamp")
        if signature:
            if signature in seen:
                continue
            seen.add(signature)
        if type(stamp) is not int or isinstance(stamp, bool):
            try:
                stamp = int(stamp)
            except (TypeError, ValueError):
                incomplete += 1
                continue
        if earliest is None or stamp < earliest:
            earliest = stamp
        day = datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%Y-%m-%d")
        by_day[day] += 1
    maximum = max(by_day.values()) if by_day else 0
    over_days = {day: count for day, count in by_day.items() if count > cap}
    total = len(seen) if seen else sum(by_day.values())
    # D12-7: a history exactly at the cap is incomplete (pagination stopped).
    deferred = bool(total >= length_cap)
    passed = bool(by_day) and not over_days and incomplete == 0 and not deferred
    cannot_fail_bot = bool(by_day) and not over_days and incomplete == 0
    return {
        "passed": passed,
        "cannot_fail_bot_rule": cannot_fail_bot,
        "needs_decode": bool(over_days) or bool(incomplete) or not by_day,
        "deferred": deferred,
        "dropped": False,
        "history_length": total,
        "history_cap": length_cap,
        "first_sig_unix": earliest,
        "max_per_day": maximum,
        "max_on": max(by_day, key=by_day.get) if by_day else None,
        "over_days": over_days,
        "per_day": dict(by_day),
        "incomplete_timestamps": incomplete,
        "threshold": cap,
        "can_only_drop_or_defer": True,
        "seed_is_not": "evidence",
        "rule": GT_ECONOMIC_TRADES_RULE,
    }


def dex_trades_per_utc_day(rows):
    """Distinct transaction_hash per UTC day. Legs of one tx count once."""
    days = defaultdict(set)
    earliest = None
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        digest = _dex_trade_hash(row)
        if not digest or digest in seen:
            continue
        seen.add(digest)
        ts = _dex_trade_timestamp(row)
        if ts is None:
            continue
        if ts > 10_000_000_000:
            ts = ts // 1000
        day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        days[day].add(digest)
        if earliest is None or ts < earliest:
            earliest = ts
    counts = {day: len(hashes) for day, hashes in days.items()}
    busiest = max(counts.values()) if counts else 0
    busiest_day = max(counts, key=counts.get) if counts else None
    return {
        "per_day": counts,
        "max_per_day": busiest,
        "busiest_day": busiest_day,
        "earliest_unix": earliest,
        "distinct_hashes": len(seen),
        "days": len(counts),
    }


def nansen_dex_trades_drop(
    stats,
    *,
    now_unix=None,
    max_per_day=None,
    min_history_days=None,
    helius_first_sig_unix=None,
    age_rule=None,
):
    """Drop-only. Error/empty stats mean no drop.

    Age is off by default (D11-4). Nansen earliest_unix is never the age
    clock — 9T546u was false-dropped because Nansen coverage started late.
    Enable age only with an explicit min_history_days or age_rule=
    helius_first_signature, and then only with a Helius first-signature time.
    The >MAX_ECONOMIC_TRADES_PER_UTC_DAY drop is unchanged.
    """
    if not isinstance(stats, dict) or not stats:
        return {
            "dropped": False,
            "drop_reasons": [],
            "can_only_drop": True,
            "seed_is_not": "evidence",
            "empty_or_error": True,
        }
    reasons = []
    cap = _as_number(max_per_day)
    if cap is None:
        cap = NANSEN_DEX_TRADES_MAX_PER_DAY
    busiest = _as_number(stats.get("max_per_day"))
    if busiest is not None and busiest > cap:
        reasons.append(f"nansen_dex_trades_gt_{cap}_per_day:{busiest} on {stats.get('busiest_day')}")
    rule = age_rule or HISTORY_AGE_RULE
    min_age = _as_number(min_history_days)
    if min_age is None and rule == HISTORY_AGE_RULE_HELIUS:
        min_age = Decimal("60")
    if min_age is None:
        min_age = _as_number(NANSEN_DEX_TRADES_MIN_HISTORY_DAYS)
    earliest = _as_unix(helius_first_sig_unix)
    # Never fall back to Nansen earliest_unix. That was the 9T546u false drop.
    if min_age is not None and earliest is not None:
        now = _as_unix(now_unix) or utc_now_unix()
        age_days = Decimal(now - earliest) / Decimal(86400)
        if age_days < min_age:
            reasons.append(f"nansen_dex_trades_history_lt_{min_age}d:{age_days.quantize(Decimal('0.1'))}d")
    return {
        "dropped": bool(reasons),
        "drop_reasons": reasons,
        "evidence": {
            "max_per_day": stats.get("max_per_day"),
            "busiest_day": stats.get("busiest_day"),
            "earliest_unix": stats.get("earliest_unix"),
            "helius_first_sig_unix": helius_first_sig_unix,
            "distinct_hashes": stats.get("distinct_hashes"),
            "age_rule": "off" if min_age is None else f"{rule}:{min_age}",
        },
        "can_only_drop": True,
        "seed_is_not": "evidence",
    }


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


# economic_trades_by_utc_day: shared helper. BOT_RULE_DEFINITION.
# (signature, kind, mint) dedupe; token-to-token included; route legs are
# not trades; ISO or unix timestamps.


def _sample_address(samples, fallback=None):
    if fallback:
        return fallback
    for sample in samples or []:
        if sample.get("address"):
            return sample["address"]
    return None


def densest_utc_day_bounds(samples, *, address=None):
    """UTC day with the most economic trades in the samples already fetched."""
    events = []
    records = []
    for sample in samples or []:
        events.extend(sample.get("events") or [])
        records.extend(sample.get("records") or [])
    wallet = _sample_address(samples, address)
    rate = combined_economic_trade_rate(events=events, records=records, address=wallet)
    by_day = rate.get("by_day") or {}
    if not by_day:
        return None
    day = max(by_day, key=lambda item: (by_day[item], item))
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    start_unix = int(start.timestamp())
    return {
        "name": "densest_day",
        "day": day,
        "start_unix": start_unix,
        "end_unix": start_unix + 86400,
        "trades": int(by_day[day]),
    }


def _triage_record_signature(row):
    if not isinstance(row, dict):
        return None
    if row.get("signature"):
        return row["signature"]
    tx = row.get("transaction") if isinstance(row.get("transaction"), dict) else {}
    sigs = tx.get("signatures") or []
    return sigs[0] if sigs else None


def helius_triage_decision(samples, *, now_unix, bundle=None, created_in_range=False, address=None):
    """Drop only on confirmed >15 economic trades in a UTC day, youth, or bundle.

    Uses the rent-aware raw count (and decoded, taking the per-day max).
    Under 15 economic trades/day proves nothing. Age under 180 days is a
    preference, not a hard drop, unless creation is proven under 30 days.
    """
    records = []
    events = []
    seen_sigs = set()
    seen_event_sigs = set()
    wallet = _sample_address(samples, address)
    for sample in samples or []:
        for row in sample.get("records") or []:
            sig = _triage_record_signature(row)
            if sig and sig in seen_sigs:
                continue
            if sig:
                seen_sigs.add(sig)
            records.append(row)
        for event in sample.get("events") or []:
            if not isinstance(event, dict):
                continue
            sig = event.get("signature")
            kind = event.get("kind")
            mint = event.get("mint")
            key = (sig, kind, mint)
            if sig and key in seen_event_sigs:
                continue
            if sig:
                seen_event_sigs.add(key)
            events.append(event)
    times = []
    for row in records:
        if not isinstance(row, dict):
            continue
        stamp = row.get("blockTime") or row.get("timestamp")
        if stamp is None:
            stamp = ((row.get("transaction") or {}).get("blockTime"))
        if type(stamp) is int and not isinstance(stamp, bool):
            times.append(stamp)
    oldest = min(times) if times else None
    history_days = None
    if oldest is not None:
        history_days = (Decimal(int(now_unix) - oldest) / Decimal(86400)).quantize(Decimal("0.0001"))
    rate = combined_economic_trade_rate(events=events, records=records, address=wallet)
    raw_only = raw_economic_trade_rate(records, wallet) if wallet else None
    by_day = rate.get("by_day") or {}
    max_day = first_defined_int(rate.get("max")) or 0
    max_on = rate.get("max_on")
    reasons = []
    if max_day > MAX_ECONOMIC_TRADES_PER_UTC_DAY:
        reasons.append(f"triage_{GT_ECONOMIC_TRADES_RULE}")
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
        "economic_trades_by_utc_day": by_day,
        "max_economic_trades_in_one_day": max_day,
        "max_economic_trades_on": max_on,
        "raw_max_economic_trades_in_one_day": None if not raw_only else raw_only.get("max"),
        "raw_max_economic_trades_on": None if not raw_only else raw_only.get("max_on"),
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
    extra = dict(extra or {})
    incoming_tf = extra.pop("timeframes", None)
    meta = {
        "seed_sources": sources,
        "primary_seed_source": sources[0],
        "seed_is_not": "evidence",
    }
    for key, value in (existing or {}).items():
        if key not in meta and key not in ("seed_sources", "primary_seed_source"):
            meta[key] = value
    merged_tf = dict(existing.get("timeframes") or {})
    if incoming_tf:
        for tf, payload in incoming_tf.items():
            if not payload:
                continue
            key = str(tf)
            merged_tf[key] = {**(merged_tf.get(key) or {}), **payload}
    incoming_timeframe = extra.get("timeframe")
    if incoming_timeframe is not None and mapped == SEED_NANSEN:
        tf_key = str(incoming_timeframe)
        slot = dict(merged_tf.get(tf_key) or {})
        for field in ("rank", "selection_reason", "vendor_metrics", "billing"):
            if extra.get(field) is not None:
                slot[field] = extra[field]
        slot["timeframe"] = incoming_timeframe
        merged_tf[tf_key] = slot
        already = existing.get("timeframe")
        if already not in (None, incoming_timeframe) and existing.get("rank") is not None:
            extra = {
                key: value
                for key, value in extra.items()
                if key not in ("rank", "timeframe", "selection_reason", "vendor_metrics")
            }
    if merged_tf:
        meta["timeframes"] = merged_tf
    for key, value in extra.items():
        if value is not None:
            meta[key] = value
    state["seed_metadata"][address] = meta
    return meta


def _wallets_from_payload(payload):
    found = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, str) and item:
                found.append(item)
            elif isinstance(item, dict):
                addr = item.get("address") or item.get("wallet") or item.get("wallet_address")
                if addr:
                    found.append(addr)
        return found
    if not isinstance(payload, dict):
        return found
    for key in ("wallets", "addresses"):
        value = payload.get(key)
        if isinstance(value, list):
            found.extend(_wallets_from_payload(value))
    for key in ("phase2", "phase3", "phase4", "discoveries", "seed_metadata"):
        value = payload.get(key)
        if isinstance(value, dict):
            found.extend(value.keys())
            for row in value.values():
                if isinstance(row, dict):
                    found.extend(_wallets_from_payload(row))
    return found


def load_known_wallets_from_outputs(paths):
    """Addresses already seen in prior run outputs. Used to buy only fresh Nansen seeds."""
    from pathlib import Path

    known = set()
    for raw in paths or []:
        path = Path(raw)
        candidates = []
        if path.is_file():
            candidates.append(path)
        elif path.is_dir():
            for name in ("RUN_STATE.json", "RESULTS.json", "STATE.json", "state.json", "wallets.json"):
                candidate = path / name
                if candidate.is_file():
                    candidates.append(candidate)
            phase4 = path / "phase4.json"
            if phase4.is_file():
                candidates.append(phase4)
        for candidate in candidates:
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            for address in _wallets_from_payload(payload):
                if isinstance(address, str) and len(address) >= 32:
                    known.add(address)
    return known


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
        "timeframes": meta.get("timeframes"),
        "seed_token": meta.get("token"),
    }


def cost_per_audit_worthy(spend_by_source, audit_worthy_by_source):
    """Credits per independently audited wallet across every provider and phase.

    `units`/`requests` stay the source-bucket totals (may mix providers once
    Helius triage/history is attributed). `by_provider` splits Birdeye / Helius
    / Nansen so phase-3 Helius is never omitted. None when the denominator is 0.
    """
    out = {}
    for source, spend in (spend_by_source or {}).items():
        worthy = int((audit_worthy_by_source or {}).get(source) or 0)
        units = int((spend or {}).get("units") or 0)
        requests = int((spend or {}).get("requests") or 0)
        by_provider = dict((spend or {}).get("by_provider") or {})
        if not by_provider and spend:
            provider = spend.get("provider")
            if provider:
                by_provider = {provider: {"requests": requests, "units": units}}
        all_units = sum(int((row or {}).get("units") or 0) for row in by_provider.values()) or units
        out[source] = {
            "units": units,
            "requests": requests,
            "audit_worthy": worthy,
            "cost_per_audit_worthy": None if worthy <= 0 else str((Decimal(units) / Decimal(worthy)).quantize(Decimal("0.0001"))),
            "by_provider": by_provider,
            "all_providers_units": all_units,
            "cost_per_audit_worthy_all_providers": (
                None if worthy <= 0 else str((Decimal(all_units) / Decimal(worthy)).quantize(Decimal("0.0001")))
            ),
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
