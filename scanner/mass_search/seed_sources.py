"""Phase 1 seed sources. A seed is never evidence.

Primary sources feed the unchanged prove-it pipeline. Cheap pre-spend
filters drop high-rate or young wallets using signals already captured
in Phase 1 provider rows or the Phase 2 cheap sample — never extra
provider calls.

Leaderboard investigation (2026-10-07): GMGN, Cielo and Kolscan have no
official keyless ToS-safe read API. Live fetch is refused. Caps stay 0.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from scanner.config import validate_address

SEED_GAINERS = "gainers-losers"
SEED_TOP_TRADERS = "top-traders"
SEED_SMART_MONEY = "smart-money-leaderboard"
SEED_EARLY_BUYERS = "early-buyers-durable"
SEED_PRESCREEN_FILTER = "prescreen-filter"

PRIMARY_SEED_SOURCES = frozenset({
    SEED_GAINERS,
    SEED_TOP_TRADERS,
    SEED_SMART_MONEY,
    SEED_EARLY_BUYERS,
})
SEED_SOURCES = PRIMARY_SEED_SOURCES | {SEED_PRESCREEN_FILTER}

BIRDEYE_TOKEN_LIST_PATH = "/defi/v3/token/list"
BIRDEYE_FIRST_BUYERS_PATH = "/token/v1/first-buyers"
# docs.birdeye.so/docs/compute-unit-cost (reviewed 2026-10-07): Token List V3
# is listed at 60 CU. The endpoint page currently says 50 CU. Charge the
# higher documented table figure.
BIRDEYE_TOKEN_LIST_UNITS = 60
# docs.birdeye.so/docs/compute-unit-cost: Token - First Buyers = 25 CU.
BIRDEYE_FIRST_BUYERS_UNITS = 25

DURABLE_TOKEN_MIN_AGE_DAYS = 21
DURABLE_TOKEN_MIN_LIQUIDITY_USD = 100000
DURABLE_TOKEN_MIN_MARKET_CAP_USD = 500000
DURABLE_TOKEN_MAX_LAST_TRADE_AGE_DAYS = 7
EARLY_BUYER_MAX_TOKENS = 4
EARLY_BUYER_PAGE_LIMIT = 70
SOLD_WELL_STATUSES = frozenset({"sell_partial", "sell_all"})
EARLY_BUYER_SKIP_TAGS = frozenset({"bundler", "sniper", "dev", "insider"})

CHEAP_MAX_TRADES_PER_DAY = Decimal("25")
CHEAP_MIN_HISTORY_DAYS = Decimal("30")

QUOTE_MINTS = frozenset({
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
})

LEADERBOARD_VIABILITY = {
    "gmgn": {
        "viable": False,
        "official_api": False,
        "requires_key": False,
        "tos_safe": False,
        "reason": (
            "GMGN has no official public API. Rank/quotation URLs used by "
            "scrapers are unofficial and ToS-problematic. Not implemented."
        ),
    },
    "cielo": {
        "viable": False,
        "official_api": True,
        "requires_key": True,
        "tos_safe": True,
        "reason": (
            "Cielo's official API (developer.cielo.finance) requires X-API-KEY "
            "and a paid plan. Not implemented without a key."
        ),
    },
    "kolscan": {
        "viable": False,
        "official_api": False,
        "requires_key": False,
        "tos_safe": False,
        "reason": (
            "Kolscan has no official public GET API. The site loads the "
            "leaderboard via a browser-intercepted POST. Not scraped."
        ),
    },
}

SEED_CU_DOCS = {
    SEED_GAINERS: {
        "provider": "birdeye",
        "path": "/trader/gainers-losers",
        "documented_cu": 30,
        "docs": "https://docs.birdeye.so/docs/compute-unit-cost",
        "reviewed_on": "2026-10-07",
    },
    SEED_TOP_TRADERS: {
        "provider": "birdeye",
        "path": "/defi/v2/tokens/top_traders",
        "documented_cu": 35,
        "docs": "https://docs.birdeye.so/docs/compute-unit-cost",
        "reviewed_on": "2026-10-07",
    },
    SEED_EARLY_BUYERS: {
        "provider": "birdeye",
        "paths": {
            "token_list": {
                "path": BIRDEYE_TOKEN_LIST_PATH,
                "documented_cu": BIRDEYE_TOKEN_LIST_UNITS,
            },
            "first_buyers": {
                "path": BIRDEYE_FIRST_BUYERS_PATH,
                "documented_cu": BIRDEYE_FIRST_BUYERS_UNITS,
            },
        },
        "docs": "https://docs.birdeye.so/docs/compute-unit-cost",
        "reviewed_on": "2026-10-07",
        "note": (
            "1 token-list call plus one first-buyers page per durable token "
            f"(default {EARLY_BUYER_MAX_TOKENS}). A seed is not evidence."
        ),
    },
    SEED_SMART_MONEY: {
        "provider": "leaderboard",
        "documented_cu": 0,
        "viable": False,
        "vendors": LEADERBOARD_VIABILITY,
        "note": (
            "No official keyless ToS-safe leaderboard. Live fetch is refused. "
            "Grant leaderboard_* caps stay 0."
        ),
    },
    SEED_PRESCREEN_FILTER: {
        "provider": None,
        "documented_cu": 0,
        "max_trades_per_day": str(CHEAP_MAX_TRADES_PER_DAY),
        "min_history_days": str(CHEAP_MIN_HISTORY_DAYS),
        "note": (
            "Uses Phase 1 provider rows and/or the Phase 2 cheap sample. "
            "Zero extra provider calls."
        ),
    },
}


class SeedSourceError(ValueError):
    """Invalid --seed-source value or combination."""


def parse_seed_sources(raw):
    """Parse --seed-source. Empty means inherit --discovery-source later."""
    if raw in (None, "", []):
        return []
    if isinstance(raw, (list, tuple)):
        parts = [str(item).strip() for item in raw if str(item).strip()]
    else:
        parts = [part.strip() for part in str(raw).split(",") if part.strip()]
    unknown = [part for part in parts if part not in SEED_SOURCES]
    if unknown:
        raise SeedSourceError(f"unknown --seed-source {unknown}; choose from {sorted(SEED_SOURCES)}")
    primaries = [part for part in parts if part in PRIMARY_SEED_SOURCES]
    if len(set(primaries)) > 1:
        raise SeedSourceError("at most one primary --seed-source (plus optional prescreen-filter)")
    # Preserve order, drop duplicates.
    seen = set()
    ordered = []
    for part in parts:
        if part not in seen:
            ordered.append(part)
            seen.add(part)
    return ordered


def resolve_seed_sources(seed_sources, discovery_source):
    """Fill an empty --seed-source from --discovery-source."""
    sources = list(seed_sources or [])
    if not any(item in PRIMARY_SEED_SOURCES for item in sources):
        fallback = discovery_source or SEED_GAINERS
        if fallback not in PRIMARY_SEED_SOURCES:
            raise SeedSourceError(f"unknown discovery source {fallback}")
        sources = [fallback, *[item for item in sources if item == SEED_PRESCREEN_FILTER]]
    return sources


def primary_seed_source(sources):
    for item in sources or []:
        if item in PRIMARY_SEED_SOURCES:
            return item
    return SEED_GAINERS


def cheap_prescreen_enabled(sources):
    return SEED_PRESCREEN_FILTER in (sources or [])


def leaderboard_not_viable_reason():
    parts = [
        f"{name}: {row['reason']}"
        for name, row in LEADERBOARD_VIABILITY.items()
    ]
    return "No viable keyless ToS-safe smart-money leaderboard. " + " ".join(parts)


def estimate_seed_plan(sources, *, tokens=None, discovery=True, wallets=None):
    """Dry-run request/credit estimates per seed source. No HTTP."""
    sources = list(sources or [])
    tokens = list(tokens or [])
    wallets = list(wallets or [])
    per_source = {}
    birdeye_requests = 0
    birdeye_units = 0
    leaderboard_requests = 0
    leaderboard_units = 0
    primary = primary_seed_source(sources)
    if discovery or not wallets:
        if primary == SEED_TOP_TRADERS:
            n = max(len(tokens), 1)
            birdeye_requests += n
            birdeye_units += n * 35
            per_source[SEED_TOP_TRADERS] = {
                "provider": "birdeye",
                "requests": n,
                "units": n * 35,
                "billing_unit": "birdeye_compute_unit",
                "note": "35 CU per token (docs.birdeye.so compute-unit-cost).",
            }
        elif primary == SEED_EARLY_BUYERS:
            token_n = len(tokens) if tokens else EARLY_BUYER_MAX_TOKENS
            list_req = 0 if tokens else 1
            list_units = 0 if tokens else BIRDEYE_TOKEN_LIST_UNITS
            buyer_units = token_n * BIRDEYE_FIRST_BUYERS_UNITS
            birdeye_requests += list_req + token_n
            birdeye_units += list_units + buyer_units
            per_source[SEED_EARLY_BUYERS] = {
                "provider": "birdeye",
                "requests": list_req + token_n,
                "units": list_units + buyer_units,
                "billing_unit": "birdeye_compute_unit",
                "token_list_requests": list_req,
                "token_list_units": list_units,
                "first_buyers_requests": token_n,
                "first_buyers_units": buyer_units,
                "note": SEED_CU_DOCS[SEED_EARLY_BUYERS]["note"],
            }
        elif primary == SEED_SMART_MONEY:
            per_source[SEED_SMART_MONEY] = {
                "provider": "leaderboard",
                "requests": 0,
                "units": 0,
                "viable": False,
                "vendors": LEADERBOARD_VIABILITY,
                "note": leaderboard_not_viable_reason(),
            }
        elif primary == SEED_GAINERS:
            birdeye_requests += 1
            birdeye_units += 30
            per_source[SEED_GAINERS] = {
                "provider": "birdeye",
                "requests": 1,
                "units": 30,
                "billing_unit": "birdeye_compute_unit",
                "note": "30 CU (docs.birdeye.so compute-unit-cost).",
            }
    if cheap_prescreen_enabled(sources):
        per_source[SEED_PRESCREEN_FILTER] = {
            "provider": None,
            "requests": 0,
            "units": 0,
            "max_trades_per_day": str(CHEAP_MAX_TRADES_PER_DAY),
            "min_history_days": str(CHEAP_MIN_HISTORY_DAYS),
            "note": SEED_CU_DOCS[SEED_PRESCREEN_FILTER]["note"],
        }
    return {
        "seed_sources": sources,
        "primary_seed_source": primary,
        "per_source": per_source,
        "totals": {
            "birdeye_requests": birdeye_requests,
            "birdeye_units": birdeye_units,
            "leaderboard_requests": leaderboard_requests,
            "leaderboard_units": leaderboard_units,
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


def select_durable_tokens(items, *, now_unix, skip_mints=None, limit=EARLY_BUYER_MAX_TOKENS):
    """Tokens that have been listed for weeks and still trade. Not a lead."""
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
        picked.append({
            "address": address,
            "liquidity": str(liquidity),
            "market_cap": str(market_cap),
            "listing_time": listing,
            "last_trade_unix_time": last_trade,
            "seed_is_not": "evidence",
        })
        if len(picked) >= int(limit):
            break
    return picked


def first_buyer_rows(body):
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
    """First buyers who later sold, minus tagged extractors. Provider echo only."""
    selected = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        address = _safe_address(
            row.get("wallet_address") or row.get("address") or row.get("wallet") or row.get("owner")
        )
        if not address:
            continue
        tags = {str(tag).lower() for tag in (row.get("tags") or []) if tag}
        if tags & EARLY_BUYER_SKIP_TAGS:
            continue
        status = str(row.get("position_status") or "").lower()
        if status not in SOLD_WELL_STATUSES:
            continue
        selected.append({
            "address": address,
            "token": token,
            "position_status": status,
            "first_buy_volume_usd": (
                None if row.get("first_buy_volume_usd") is None
                else str(row.get("first_buy_volume_usd"))
            ),
            "tags": sorted(tags),
            "seed_source": SEED_EARLY_BUYERS,
            "seed_is_not": "evidence",
        })
    return selected


def cheap_prescreen_decision(signals, *, max_trades_per_day=None, min_history_days=None):
    """Drop on already-captured signals. Never a provider call."""
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


def history_span_days(records, *, created_in_range=False, now_unix=None):
    """Age from already-captured sample timestamps. None if unknown."""
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
        span = Decimal(end - oldest) / Decimal(86400)
        return span.quantize(Decimal("0.0001"))
    # Without a creation proof the sample span is a lower bound only.
    # Do not drop as "short history" on a lower bound.
    return None


def record_seed_metadata(state, address, source, extra=None):
    """Attach provenance. A seed source is never evidence."""
    if not address or not source:
        return None
    state.setdefault("seed_metadata", {})
    existing = state["seed_metadata"].get(address) or {}
    sources = [item for item in (existing.get("seed_sources") or []) if item]
    if source not in sources:
        sources.append(source)
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
            "seed_is_not": "evidence",
        }
    return {
        "seed_source": meta.get("primary_seed_source"),
        "seed_sources": list(meta.get("seed_sources") or []),
        "seed_is_not": "evidence",
        "seed_token": meta.get("token"),
    }


def utc_now_unix():
    return int(datetime.now(timezone.utc).timestamp())
