"""Source capability records and live-authorization gates. Offline is the default."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

from .evidence_integrity import redact_secrets
from .plan import canonical_json, sha256_json

CAPABILITY_VERSION = "mass-search-capability-v1"
ALLOWED_STATES = (
    "DOCUMENTED_NOT_TESTED",
    "AUTHORIZED_AVAILABLE",
    "UNAUTHORIZED",
    "ENTITLEMENT_BLOCKED",
    "RATE_LIMITED",
    "INCOMPLETE_SCOPE",
    "UNSUPPORTED_SCHEMA",
    "UNAVAILABLE",
)
ALLOWED_ROLES = ("GO", "GO_LIMITED", "NO_GO")
LIVE_AUTH_SCHEMA = "live-research-authorization-v1"
BIRDEYE_DOCS_URL = "https://docs.birdeye.so/reference/get-trader-gainers-losers"
BIRDEYE_DOCS_REVIEWED_ON = "2026-10-05"
BIRDEYE_ENDPOINT = "https://public-api.birdeye.so/trader/gainers-losers"
HELIUS_HISTORY_DOCS = "https://www.helius.dev/docs/rpc/gettransactionsforaddress"
JUPITER_QUOTE_DOCS = "https://developers.jup.ag/docs/swap/v1/get-quote"

REQUIRED_PROVIDER_FIELDS = (
    "provider_id",
    "allowed_operations",
    "billing_unit",
    "existing_plan_confirmed",
    "remaining_quota_confirmed_at",
    "cycle_start",
    "cycle_end_exclusive",
    "max_requests",
    "max_units",
    "max_concurrency",
    "max_duration_seconds",
)


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _require_iso(value, name):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be an ISO-8601 timestamp")
    stamp = value[:-1] + "+00:00" if value.endswith("Z") else value
    datetime.fromisoformat(stamp)
    return value


def documented_birdeye_traders():
    return {
        "schema_version": CAPABILITY_VERSION,
        "source_id": "birdeye-traders",
        "provider": "birdeye",
        "operation": "GET /trader/gainers-losers",
        "docs_url": BIRDEYE_DOCS_URL,
        "docs_reviewed_on": BIRDEYE_DOCS_REVIEWED_ON,
        "auth_mode": "api-key-header",
        "requested_chain": "solana",
        "window_param": "type",
        "supported_windows": ["yesterday", "today", "1W", "30d", "90d"],
        "sort_fields": ["PnL", "realized_pnl", "unrealized_pnl", "trader_score"],
        "sort_compatibility": {
            "trader_score": {
                "supported": True,
                "silent_fallback_to_pnl_sort": False,
                "is_not": [
                    "independently_verified_profit",
                    "copyability",
                    "normalized_evidence_status",
                    "completed_profitable_trades",
                ],
                "note": "Provider ranking score only. Keep separate from evidence status. Capability previously listed P&L sorts only; trader_score is now an explicit supported sort.",
            }
        },
        "currency": "USD",
        "accounting_definition": "PROVIDER_REPORTED",
        "timestamp_meaning": "provider ranking snapshot, not an atomic as-of universe",
        "page_limit": 100,
        "offset_maximum": 10000,
        "offset_plus_limit_maximum": 10000,
        "cost_model": {
            "billing_unit": "birdeye_compute_unit",
            "documented_units_per_request": 30,
            "tested": False,
            "note": "Birdeye documents GET /trader/gainers-losers as 30 CU fixed (2026-10-05). The older repo figure of 25 was stale. Documented CU is not a dashboard receipt.",
        },
        "rate_limit": "unknown-until-probe",
        "known_floors": [
            {
                "field": "realized_pnl_sort",
                "unit": "USD",
                "documented_minimum": "1000",
                "excludes": "traders below the documented USD floor; not convertible to the SOL strict gate",
            }
        ],
        "field_map": {
            "address": {"path": ["address"], "required": True},
            "realized_pnl": {"path": ["realized_pnl", "pnl"], "unit": "USD", "basis": "PROVIDER_REPORTED"},
            "trade_count": {"path": ["trade_count", "tx_counts"], "unit": "count", "proxy": True, "is_not": "completed_profitable_trades"},
            "last_active": {"path": ["last_trade_unix_time", "last_active"], "unit": "unix_seconds"},
            "trader_score": {
                "path": ["trader_score", "score"],
                "unit": "provider_score",
                "basis": "PROVIDER_REPORTED",
                "evidence_status": "not_independent_verification",
                "note": "Provider ranking score only. Not profitability or copyability evidence.",
            },
        },
        "state": "DOCUMENTED_NOT_TESTED",
        "role_decision": "NO_GO",
        "tested_cases": [],
        "unresolved_limitations": [
            "User entitlement and remaining quota are unconfirmed.",
            "USD ranking floors cannot prove SOL strict thresholds.",
            "Moving offset pages are not an atomic historical universe.",
            "trader_score is a provider rank, not independently verified profitability or copyability.",
        ],
        "sanitized_response_evidence": None,
        "notes": [
            "Documentation retrieval is not provider collection.",
            "A present API key is not authority for a mass run.",
        ],
    }


def documented_public_sampler_fallback():
    return {
        "schema_version": CAPABILITY_VERSION,
        "source_id": "public-pool-sampler",
        "provider": "geckoterminal",
        "operation": "existing public-pool discovery",
        "docs_url": "repository:scanner/discovery.py",
        "docs_reviewed_on": BIRDEYE_DOCS_REVIEWED_ON,
        "auth_mode": "none",
        "requested_chain": "solana",
        "currency": "activity-count",
        "accounting_definition": "not-profit",
        "page_limit": 20,
        "state": "AUTHORIZED_AVAILABLE",
        "role_decision": "GO_LIMITED",
        "unresolved_limitations": [
            "Legacy 20-candidate sampler is not a completed 1,000-wallet search.",
            "Observed buying and selling is not historical profit.",
        ],
        "notes": ["Keep labelled as a fallback. Do not rename it a mass-search proof."],
    }


def documented_helius_history():
    return {
        "schema_version": CAPABILITY_VERSION,
        "source_id": "helius-history",
        "provider": "helius",
        "operation": "getTransactionsForAddress",
        "docs_url": HELIUS_HISTORY_DOCS,
        "docs_reviewed_on": BIRDEYE_DOCS_REVIEWED_ON,
        "auth_mode": "query-api-key",
        "state": "DOCUMENTED_NOT_TESTED",
        "role_decision": "GO_LIMITED",
        "unresolved_limitations": [
            "Token-account options do not prove every former ownership lifecycle.",
            "Existing setup-pilot ledger must not be reset.",
        ],
    }


def documented_jupiter_quotes():
    return {
        "schema_version": CAPABILITY_VERSION,
        "source_id": "jupiter-quote",
        "provider": "jupiter",
        "operation": "GET quote",
        "docs_url": JUPITER_QUOTE_DOCS,
        "docs_reviewed_on": BIRDEYE_DOCS_REVIEWED_ON,
        "state": "DOCUMENTED_NOT_TESTED",
        "role_decision": "GO_LIMITED",
        "notes": ["Quotes are estimates, not fills. No transaction construction."],
    }


def validate_capability(record):
    if not isinstance(record, dict):
        raise ValueError("Capability record must be an object")
    result = deepcopy(record)
    if result.get("schema_version") != CAPABILITY_VERSION:
        raise ValueError("Unsupported capability schema")
    if result.get("state") not in ALLOWED_STATES:
        raise ValueError("Unsupported capability state")
    if result.get("role_decision") not in ALLOWED_ROLES:
        raise ValueError("Unsupported capability role")
    if result["role_decision"] == "GO" and result["state"] != "AUTHORIZED_AVAILABLE":
        raise ValueError("GO requires an authorized available source")
    return result


def live_authorization_from_store(store):
    payload = store.get("configuration", "live_authorization")
    if payload is None:
        return None
    return validate_live_authorization(payload)


def validate_live_authorization(payload):
    if not isinstance(payload, dict) or payload.get("schema_version") != LIVE_AUTH_SCHEMA:
        raise ValueError("Live authorization must use live-research-authorization-v1")
    if payload.get("enabled") is not True:
        return {**deepcopy(payload), "enabled": False, "reason": "Authorization file is disabled"}
    for key in ("authorization_id", "authorized_by_user_at", "expires_at"):
        if not payload.get(key):
            raise ValueError(f"Enabled live authorization requires {key}")
    _require_iso(payload["authorized_by_user_at"], "authorized_by_user_at")
    expires = _require_iso(payload["expires_at"], "expires_at")
    if expires <= utc_now():
        return {**deepcopy(payload), "enabled": False, "reason": "Authorization expired"}
    if payload.get("max_additional_spend_usd") != "0" or payload.get("overages_enabled") or payload.get("allow_paid_upgrade"):
        raise ValueError("Paid spend, overages and upgrades remain forbidden")
    if payload.get("allow_signing_or_submission") is not False:
        raise ValueError("Signing or transaction submission is forbidden")
    providers = payload.get("providers")
    if not isinstance(providers, list) or not providers:
        raise ValueError("Enabled live authorization requires explicit per-provider budgets")
    for entry in providers:
        if not isinstance(entry, dict) or any(field not in entry for field in REQUIRED_PROVIDER_FIELDS):
            raise ValueError("Each provider budget is missing required fields")
        if type(entry.get("max_requests")) is not int or type(entry.get("max_units")) is not int:
            raise ValueError("Provider max_requests and max_units must be integers")
        if entry["max_requests"] == 0 and entry["max_units"] == 0:
            if entry.get("allowed_operations"):
                raise ValueError("A zero-budget provider cannot allowlist operations")
            continue
        if entry["max_requests"] < 1 or entry["max_units"] < 1:
            raise ValueError("Provider max_requests and max_units must be positive, or both 0 when the provider is forbidden")
        if entry.get("existing_plan_confirmed") is not True or not entry.get("remaining_quota_confirmed_at"):
            raise ValueError("Remaining quota must be operator-confirmed before live collection")
        if not isinstance(entry.get("allowed_operations"), list) or not entry["allowed_operations"]:
            raise ValueError("Provider allowed_operations must be a non-empty list")
        if any(not isinstance(item, str) or "sign" in item.lower() or "swap" == item.lower() for item in entry["allowed_operations"]):
            raise ValueError("Signing or swap-submission operations are not allowlisted")
    return deepcopy(payload)


def authorization_sha256(payload):
    if not payload or not payload.get("enabled"):
        return None
    sanitized = deepcopy(payload)
    sanitized.pop("notes", None)
    return sha256_json(sanitized)


# redact_secrets is the schema-aware implementation in evidence_integrity.
# Do not restore substring matching of "token" on transaction evidence.


def access_blocker(source_id="birdeye-traders"):
    if source_id == "birdeye-traders":
        return {
            "provider": "birdeye",
            "operation": "GET /trader/gainers-losers (page size 100, offset+limit <= 10000)",
            "purpose": "Genuine unique-candidate acquisition for REAL_SEARCH_BENCHMARK (target 1,000 addresses)",
            "call_ceiling": 10,
            "credit_ceiling": 250,
            "billing_unit": "birdeye_compute_unit",
            "expected_duration": "under 5 minutes if the entitled endpoint answers",
            "max_additional_spend_usd": "0",
            "overages": False,
            "paid_upgrade": False,
            "required_confirmation": [
                "existing_plan_confirmed",
                "remaining_quota_confirmed_at",
                "cycle_start",
                "cycle_end_exclusive",
            ],
            "note": "config/live_authorization.example.json is not a permission grant.",
        }
    if source_id == "helius-history":
        return {
            "provider": "helius",
            "operation": "getTransactionsForAddress for surviving wallets only",
            "purpose": "Targeted native history for REAL_ANALYTICS_DEMONSTRATED",
            "call_ceiling": 20,
            "credit_ceiling": 600,
            "billing_unit": "helius_credit",
            "expected_duration": "bounded per-wallet tranches; existing setup-pilot must not be reset",
            "max_additional_spend_usd": "0",
            "overages": False,
            "required_confirmation": ["remaining setup-pilot or confirmed monthly cycle remaining quota"],
        }
    return {
        "provider": source_id,
        "operation": "unspecified",
        "purpose": "Live collection remains blocked until a named authorized operation exists",
        "max_additional_spend_usd": "0",
    }


def apply_probe_result(record, *, state, role, tested_cases=None, limitations=None, sanitized=None):
    updated = validate_capability({
        **record,
        "state": state,
        "role_decision": role,
        "tested_cases": list(tested_cases or record.get("tested_cases") or []),
        "unresolved_limitations": list(limitations or record.get("unresolved_limitations") or []),
        "sanitized_response_evidence": redact_secrets(sanitized) if sanitized is not None else record.get("sanitized_response_evidence"),
    })
    updated["capability_sha256"] = hashlib.sha256(canonical_json({k: updated[k] for k in updated if k != "capability_sha256"}).encode()).hexdigest()
    return updated
