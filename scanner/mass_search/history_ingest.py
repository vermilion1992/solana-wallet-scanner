"""Shared historical ingest: anchored requests, persist-then-quarantine, reports.

Not a milestone runner. Callers stay on the existing application path:
request construction → credential-free source persist → signature check →
authorised v2 cache → decoder → accounting → MassSearchService.reconstruct_candidate.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from scanner.investigation import decode_supported_swaps

from .adapters import SourceError
from .capability import utc_now
from .evidence_integrity import (
    CACHE_KEY_PREFIX_V2,
    PAGE_KIND_V2,
    sanitize_transaction_records,
)
from .service import MassSearchService
from .settlement import independent_settlement_worksheet

HELIUS_METHOD = "getTransactionsForAddress"
HELIUS_ENDPOINT = "https://mainnet.helius-rpc.com/"
CACHE_KIND = "mass_search_cache"
SOURCE_CAPTURE_KIND = "mass_search_source_capture"
QUARANTINE_KIND = "mass_search_source_quarantine"

HISTORICAL_ANCHOR_REQUIRED = "HISTORICAL_ANCHOR_REQUIRED"
SIGNATURE_MISMATCH = "SIGNATURE_MISMATCH"
UNSUPPORTED_UNTIL = "UNSUPPORTED_UNTIL"
HISTORICAL_ANCHOR_KEYS = frozenset({"paginationToken"})
DOCUMENTED_BLOCK_TIME_KEYS = frozenset({"gte", "gt", "lte", "lt", "eq"})
PROVIDER_SIDE_CUTOFF_ISO = "2026-10-05T13:29:27Z"
PROVIDER_SIDE_CUTOFF_UNIX = 1791206967
NEXT_CAPTURE_DRAFT_REL = "config/live_authorization.ranked100-depth-biased-next-capture-draft.json"

EXACT_HELIUS_OPTIONS = {
    "transactionDetails": "full",
    "limit": 100,
    "sortOrder": "desc",
    "commitment": "finalized",
    "maxSupportedTransactionVersion": 1,
    "filters": {"status": "any", "tokenAccounts": "all"},
}

REPLAY_AUTHORIZATION_ID = "offline-g1-archive-replay"


def source_capture_key(authorization_id, address, page_index):
    return f"g3-reacquire-source:{authorization_id}:{address}:page:{page_index}"


def quarantine_key(authorization_id, address, page_index):
    return f"g3-quarantine:{authorization_id}:{address}:page:{page_index}"


def authorised_cache_key(authorization_id, address, page_index):
    return f"{CACHE_KEY_PREFIX_V2}{authorization_id}:{address}:page:{page_index}"


def signature_lte(options):
    filters = (options or {}).get("filters") if isinstance((options or {}).get("filters"), dict) else {}
    bound = filters.get("signature") if isinstance(filters.get("signature"), dict) else {}
    value = bound.get("lte")
    return value if isinstance(value, str) and value else None


def assert_no_unsupported_until(options):
    """Top-level until is not a documented getTransactionsForAddress bound."""
    if isinstance(options, dict) and "until" in options:
        raise SourceError(
            UNSUPPORTED_UNTIL,
            "Top-level until is not a documented getTransactionsForAddress bound; "
            "use filters.blockTime.lt and/or paginationToken",
        )
    return True


def iso_to_unix(value):
    if type(value) is int:
        return value
    text = str(value).replace("Z", "+00:00")
    return int(datetime.fromisoformat(text).timestamp())


def provider_side_cutoff_unix(iso=None):
    return iso_to_unix(iso or PROVIDER_SIDE_CUTOFF_ISO)


def _base_gta_options(options):
    """Strip paginationToken and documented signature/blockTime bounds for encoding compare."""
    compare = {k: v for k, v in (options or {}).items() if k not in HISTORICAL_ANCHOR_KEYS}
    filters = dict(compare.get("filters") or {})
    filters.pop("signature", None)
    filters.pop("blockTime", None)
    compare["filters"] = filters
    return compare


def _assert_documented_block_time(bound):
    if not isinstance(bound, dict) or not bound:
        raise SourceError("UNAUTHORIZED", "filters.blockTime must be a non-empty documented comparator object")
    extra = set(bound) - DOCUMENTED_BLOCK_TIME_KEYS
    if extra:
        raise SourceError("UNAUTHORIZED", "filters.blockTime keys must be gte/gt/lte/lt/eq")
    for key, value in bound.items():
        if type(value) is not int:
            raise SourceError("UNAUTHORIZED", f"filters.blockTime.{key} must be a Unix timestamp integer")
    return True


def assert_gta_options_not_widened(options):
    """Frozen GTA encoding plus paginationToken, filters.signature.lte, filters.blockTime."""
    assert_no_unsupported_until(options)
    compare = _base_gta_options(options)
    if compare != EXACT_HELIUS_OPTIONS:
        raise SourceError("UNAUTHORIZED", "Query options drifted from the frozen GTA encoding")
    extra = set((options or {}).keys()) - set(EXACT_HELIUS_OPTIONS) - HISTORICAL_ANCHOR_KEYS
    if extra:
        raise SourceError("UNAUTHORIZED", "Query widening is forbidden")
    filters = (options or {}).get("filters") if isinstance((options or {}).get("filters"), dict) else {}
    extra_filters = set(filters) - {"status", "tokenAccounts", "signature", "blockTime"}
    if extra_filters:
        raise SourceError("UNAUTHORIZED", "Query widening is forbidden")
    bound = filters.get("signature")
    if bound is not None:
        if not isinstance(bound, dict) or set(bound) != {"lte"} or not isinstance(bound.get("lte"), str) or not bound.get("lte"):
            raise SourceError("UNAUTHORIZED", "filters.signature must be {lte: <signature>}")
    block = filters.get("blockTime")
    if block is not None:
        _assert_documented_block_time(block)
    return True


def assert_historical_request_anchored(options, *, expected_signatures=None):
    """Reject unanchored newest-first before any provider dispatch."""
    assert_no_unsupported_until(options)
    expected = list(expected_signatures or [])
    if not expected:
        return True
    sort = (options or {}).get("sortOrder")
    has_anchor = bool((options or {}).get("paginationToken") or signature_lte(options))
    if sort == "desc" and not has_anchor:
        raise SourceError(
            HISTORICAL_ANCHOR_REQUIRED,
            "Unanchored newest-first request is forbidden when historical signatures are the required target",
        )
    return True


def documented_gta_contract(options):
    """Local interpretation of the documented GTA shape. Does not prove server behaviour."""
    assert_gta_options_not_widened(options)
    bound = signature_lte(options)
    token = (options or {}).get("paginationToken")
    filters = (options or {}).get("filters") if isinstance((options or {}).get("filters"), dict) else {}
    block = filters.get("blockTime") if isinstance(filters.get("blockTime"), dict) else {}
    return {
        "method": HELIUS_METHOD,
        "sort_order": (options or {}).get("sortOrder"),
        "inclusive_newest_signature": bound,
        "boundary_inclusive": True if bound else None,
        "continuation_token": token,
        "block_time": dict(block) if block else None,
        "block_time_lt": block.get("lt") if block else None,
        "is_unanchored_newest_first": (options or {}).get("sortOrder") == "desc" and not bound and not token,
        "until_present": isinstance(options, dict) and "until" in options,
        "server_behaviour_not_proven": True,
        "note": (
            "filters.signature.lte is the documented inclusive newest-signature bound. "
            "filters.blockTime.lt is the documented exclusive Unix-time bound. "
            "sortOrder=desc treats the first returned record as newest. "
            "Continuation uses paginationToken. Top-level until is unsupported. "
            "This local contract does not prove Helius accepted or applied the bound."
        ),
    }


def evaluate_response_against_gta_contract(options, signatures):
    """Check a candidate page against the documented request shape, not a live mock."""
    contract = documented_gta_contract(options)
    bound = contract["inclusive_newest_signature"]
    sigs = list(signatures or [])
    return {
        **contract,
        "boundary_included": bool(bound) and bound in sigs,
        "first_is_treated_as_newest": contract["sort_order"] == "desc",
        "first_signature": sigs[0] if sigs else None,
        "matches_intended_newest": bool(bound) and bool(sigs) and sigs[0] == bound,
        "continuation": bool(contract["continuation_token"]),
        "server_behaviour_not_proven": True,
    }


def build_historical_gta_options(
    *,
    page_index=0,
    expected_signatures=None,
    pagination_token=None,
    until=None,
    signature_lte_bound=None,
    historical_target=None,
    block_time=None,
    block_time_lt=None,
):
    """Construct a GTA page. Historical page 0 uses filters.signature.lte, not until.

    Next-capture continuations use paginationToken plus filters.blockTime.lt.
    A top-level ISO until is rejected.
    """
    if until is not None:
        raise SourceError(
            UNSUPPORTED_UNTIL,
            "Top-level until is not a documented getTransactionsForAddress bound; "
            "use filters.blockTime.lt and/or paginationToken",
        )
    options = {
        **EXACT_HELIUS_OPTIONS,
        "filters": dict(EXACT_HELIUS_OPTIONS["filters"]),
    }
    expected = list(expected_signatures or [])
    required = bool(expected) if historical_target is None else bool(historical_target)
    bound = signature_lte_bound
    token = pagination_token
    if required:
        if page_index == 0 and not bound and not token and expected:
            bound = expected[0]
        if page_index >= 1 and not token:
            raise SourceError(
                HISTORICAL_ANCHOR_REQUIRED,
                "Historical continuation requires the frozen paginationToken; newest-first-now is forbidden",
            )
    if token:
        options["paginationToken"] = token
    if bound:
        options["filters"] = {**options["filters"], "signature": {"lte": bound}}
    block = dict(block_time) if isinstance(block_time, dict) else {}
    if block_time_lt is not None:
        block["lt"] = int(block_time_lt)
    if block:
        options["filters"] = {**options["filters"], "blockTime": block}
    if required:
        assert_historical_request_anchored(options, expected_signatures=expected)
    assert_gta_options_not_widened(options)
    return options


def proposed_sanitised_historical_request(
    address,
    *,
    page_index=0,
    expected_signatures=None,
    pagination_token=None,
    signature_lte_bound=None,
):
    """Credential-free outgoing request that would be proposed for later live historical work."""
    options = build_historical_gta_options(
        page_index=page_index,
        expected_signatures=expected_signatures,
        pagination_token=pagination_token,
        signature_lte_bound=signature_lte_bound,
    )
    expected = list(expected_signatures or [])
    bound = signature_lte(options)
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": HELIUS_METHOD,
        "params": [address, options],
        "endpoint": HELIUS_ENDPOINT,
        "query_string_credentials": "OMITTED",
        "headers": {},
        "secrets": False,
        "historical_anchor": {
            "filters.signature.lte": bound,
            "paginationToken": options.get("paginationToken"),
            "sortOrder": options.get("sortOrder"),
            "page_index": page_index,
            "expected_newest_signature": expected[0] if expected else None,
            "expected_signature_count": len(expected),
            "boundary_inclusive": True if bound else None,
            "note": (
                "filters.signature.lte is the documented inclusive newest-signature bound "
                "so newest-first-now cannot substitute current chain-tip history. "
                "Later pages use the frozen paginationToken. "
                "filters.blockTime.lt is the documented exclusive Unix-time bound. "
                "Top-level until is rejected."
            ),
        },
        "PRODUCT_READY": False,
        "not_a_dispatched_request": True,
        "not_a_guarantee_of_exact_signature_match": True,
    }


def next_capture_draft_path(path=None):
    if path is not None:
        return Path(path)
    return Path(__file__).resolve().parents[2] / NEXT_CAPTURE_DRAFT_REL


def load_next_capture_draft(path=None):
    """Load the disabled next-capture draft. Never treats it as an armed grant."""
    payload = json.loads(next_capture_draft_path(path).read_text(encoding="utf-8"))
    if payload.get("enabled") is True:
        raise SourceError("UNAUTHORIZED", "Repo next-capture draft must stay enabled:false")
    params = ((payload.get("exact_query") or {}).get("params") or {})
    if "until" in params:
        raise SourceError(
            UNSUPPORTED_UNTIL,
            "Draft exact_query must not use top-level until; use filters.blockTime.lt",
        )
    return payload


def next_capture_block_time_lt(draft=None):
    payload = draft if draft is not None else load_next_capture_draft()
    filters = ((payload.get("exact_query") or {}).get("params") or {}).get("filters") or {}
    block = filters.get("blockTime") if isinstance(filters.get("blockTime"), dict) else {}
    if type(block.get("lt")) is int:
        return block["lt"]
    return provider_side_cutoff_unix(payload.get("provider_side_cutoff"))


def serialize_next_capture_gta_request(address, *, pagination_token, block_time_lt=None, draft=None):
    """Box-driver request body for one next-capture continuation. Not dispatched."""
    cutoff = next_capture_block_time_lt(draft) if block_time_lt is None else int(block_time_lt)
    if not pagination_token:
        raise SourceError(
            HISTORICAL_ANCHOR_REQUIRED,
            "Next-capture continuation requires the frozen paginationToken",
        )
    options = build_historical_gta_options(
        page_index=1,
        pagination_token=pagination_token,
        block_time_lt=cutoff,
        historical_target=True,
    )
    assert_gta_options_not_widened(options)
    if "until" in options:
        raise SourceError(UNSUPPORTED_UNTIL, "Serialized next-capture request must not contain top-level until")
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": HELIUS_METHOD,
        "params": [address, options],
        "endpoint": HELIUS_ENDPOINT,
        "http_method": "POST",
        "query_string_credentials": "OMITTED",
        "headers": {},
        "secrets": False,
        "not_a_dispatched_request": True,
        "draft_enabled": False,
        "PRODUCT_READY": False,
        "helius_contract": "filters.blockTime.lt + paginationToken; top-level until is unsupported",
    }


def serialize_box_driver_next_capture_first_request(path=None):
    """Request the box driver would emit for the phase-1 gtfo continuation. Never dispatched."""
    draft = load_next_capture_draft(path)
    if draft.get("enabled") is not False:
        raise SourceError("UNAUTHORIZED", "Next-capture serializer refuses any non-disabled draft")
    plan = draft.get("adaptive_plan") or {}
    phases = list(plan.get("phases") or [])
    phase1 = next((row for row in phases if row.get("phase") == 1), None)
    if not phase1 or not phase1.get("wallets"):
        raise SourceError("UNAUTHORIZED", "Adaptive plan must name a phase-1 gtfo continuation")
    address = phase1["wallets"][0]
    wallet = next((row for row in draft.get("allowed_wallets") or [] if row.get("address") == address), None)
    if not wallet:
        raise SourceError("UNAUTHORIZED", "Phase-1 wallet is missing from allowed_wallets")
    request = serialize_next_capture_gta_request(
        address,
        pagination_token=wallet.get("continue_from_pagination_token"),
        draft=draft,
    )
    request["adaptive_phase"] = 1
    request["named_dependency"] = wallet.get("named_dependency") or phase1.get("named_dependency")
    request["then"] = phase1.get("then")
    return request


async def dispatch_historical_transport(transport, address, options, page_index, *, expected_signatures=None):
    """Anchor check happens before the transport is invoked."""
    assert_historical_request_anchored(options, expected_signatures=expected_signatures)
    assert_gta_options_not_widened(options)
    return await transport(address, options=options, page_index=page_index)


def persist_credential_free_source(store, evidence_dir, authorization_id, address, page_index, capture):
    """Write the source response before signature validation. No credentials."""
    payload = {
        "kind": "g3-reacquire-source-response-v1",
        "authorization_id": authorization_id,
        "address": address,
        "page_index": page_index,
        "http_status": capture.get("http_status"),
        "evidence_sha256": capture.get("evidence_sha256"),
        "pagination_token": capture.get("pagination_token"),
        "record_count": len(capture.get("records") or []),
        "signatures": list(capture.get("signatures") or []),
        "cleaned_body": capture.get("cleaned_body"),
        "fetched_at": utc_now(),
        "credential_free": True,
        "PRODUCT_READY": False,
    }
    if store is not None:
        store.put(SOURCE_CAPTURE_KIND, source_capture_key(authorization_id, address, page_index), payload)
    if evidence_dir is not None:
        Path(evidence_dir).mkdir(parents=True, exist_ok=True)
        (Path(evidence_dir) / f"SOURCE_RESPONSE_page{page_index}.json").write_text(
            json.dumps(payload, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    return payload


def quarantine_signature_mismatch(
    store,
    evidence_dir,
    authorization_id,
    address,
    page_index,
    *,
    actual,
    expected,
    mismatch,
):
    """Keep the mismatch as evidence. Do not write authorised cache or analyse it."""
    payload = {
        "kind": "g3-source-quarantine-v1",
        "authorization_id": authorization_id,
        "address": address,
        "page_index": page_index,
        "status": SIGNATURE_MISMATCH,
        "mismatch": mismatch,
        "actual_signatures": list(actual or []),
        "expected_signatures": list(expected or []),
        "source_capture_key": source_capture_key(authorization_id, address, page_index),
        "analysed": False,
        "authorised_cache_written": False,
        "credential_free": True,
        "PRODUCT_READY": False,
        "quarantined_at": utc_now(),
        "note": "Mismatch is not the authorised historical sample. Do not decode or account it.",
    }
    if store is not None:
        store.put(QUARANTINE_KIND, quarantine_key(authorization_id, address, page_index), payload)
        existing = store.get(CACHE_KIND, authorised_cache_key(authorization_id, address, page_index))
        if existing is not None:
            raise SourceError(
                SIGNATURE_MISMATCH,
                "Authorised historical cache already present; refusing to treat a mismatch as that sample",
            )
    if evidence_dir is not None:
        Path(evidence_dir).mkdir(parents=True, exist_ok=True)
        (Path(evidence_dir) / f"QUARANTINE_page{page_index}.json").write_text(
            json.dumps(payload, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    return payload


def ingest_fetched_historical_page(
    store,
    evidence_dir,
    authorization_id,
    address,
    page_index,
    result,
    *,
    expected_signatures,
    options,
    reason,
    record_signatures,
    compare_signatures,
    persist_authorised_page,
):
    """Persist credential-free source, then validate. Quarantine mismatches."""
    actual = record_signatures(result.get("records") or [])
    capture = dict(result)
    capture["signatures"] = actual
    persist_credential_free_source(
        store, evidence_dir, authorization_id, address, page_index, capture,
    )
    expected = list(expected_signatures or [])
    if expected:
        matched, mismatch = compare_signatures(actual, expected)
        if not matched:
            quarantine_signature_mismatch(
                store, evidence_dir, authorization_id, address, page_index,
                actual=actual, expected=expected, mismatch=mismatch,
            )
            raise SourceError(SIGNATURE_MISMATCH, "Returned signatures do not match the frozen original segment")
    sanitized = sanitize_transaction_records(result.get("records") or [])
    page = {
        "kind": PAGE_KIND_V2,
        "address": address,
        "page_index": page_index,
        "reason": reason,
        "query": {
            "method": HELIUS_METHOD,
            "options": {k: v for k, v in options.items() if k not in HISTORICAL_ANCHOR_KEYS},
        },
        "request_pagination_token": options.get("paginationToken"),
        "request_signature_lte": signature_lte(options),
        "records": sanitized["records"],
        "signatures": actual,
        "signature_match": True,
        "mismatch": {"matched": len(actual)},
        "pagination_token": result.get("pagination_token"),
        "evidence_sha256": result.get("evidence_sha256") or sanitized["source_body_sha256"],
        "source_body_sha256": sanitized["source_body_sha256"],
        "normalized_sha256": sanitized["normalized_sha256"],
        "integrity": sanitized["integrity"],
        "http_status": result.get("http_status", 200),
        "fetched_at": utc_now(),
        "external_requests": int(result.get("external_requests") or 1),
    }
    if persist_authorised_page is not None:
        persist_authorised_page(page)
    elif store is not None:
        store.put(CACHE_KIND, authorised_cache_key(authorization_id, address, page_index), page)
    return page


def visible_report_allowed(*, worksheet, completed_positions):
    """Independent worksheet must succeed. Episode count alone is not a visible report."""
    return bool(worksheet) and int(completed_positions or 0) >= 1


def _visible_completed_positions(episodes, worksheet):
    if episodes and episodes.get("wallet_completed_episodes") is not None:
        return int(episodes["wallet_completed_episodes"])
    return 0


def reconcile_worksheets(production, independent):
    """Keep both worksheets. Never replace production with independent to hide a difference."""
    from .metrics import format_decimal

    payload = {
        "production_worksheet": production,
        "independent_worksheet": independent,
    }
    if not production or not independent:
        payload["status"] = "INCOMPLETE"
        payload["note"] = "One worksheet is missing; both results are retained when present."
        return payload
    prod_assets = production.get("by_quote_asset") or {}
    indep_assets = independent.get("by_quote_asset") or {}
    if prod_assets or indep_assets:
        per_asset = {}
        agree = True
        for asset in sorted(set(prod_assets) | set(indep_assets)):
            prod_ws = prod_assets.get(asset) or {}
            indep_ws = indep_assets.get(asset) or {}
            key = "total_profit_usdc" if asset == "USDC" else "total_profit_sol"
            prod_total = prod_ws.get(key)
            indep_total = indep_ws.get(key)
            if prod_total in (None, "") and indep_total in (None, ""):
                per_asset[asset] = {"status": "BOTH_EMPTY"}
                continue
            if prod_total in (None, "") or indep_total in (None, ""):
                per_asset[asset] = {"status": "INCOMPLETE", "production": prod_total, "independent": indep_total}
                agree = False
                continue
            same = Decimal(str(prod_total)) == Decimal(str(indep_total))
            per_asset[asset] = {
                "status": "AGREE" if same else "CONFLICT",
                "production": str(prod_total),
                "independent": str(indep_total),
            }
            agree = agree and same
        payload["by_quote_asset"] = per_asset
        payload["status"] = "AGREE" if agree and per_asset else "INCOMPLETE"
        payload["note"] = "Per quote asset; no FX."
        return payload
    prod_usdc = production.get("total_profit_usdc")
    indep_usdc = independent.get("total_profit_usdc")
    prod_sol = production.get("total_profit_sol")
    indep_sol = independent.get("total_profit_sol")
    if prod_usdc not in (None, "") or indep_usdc not in (None, "") or production.get("settlement_asset") == "USDC":
        if (prod_usdc in (None, "") and prod_sol not in (None, "")) or (indep_usdc in (None, "") and indep_sol not in (None, "")):
            payload["status"] = "CONFLICT"
            payload["note"] = "Worksheets use different settlement assets; no FX conversion is applied."
            return payload
        if prod_usdc in (None, "") or indep_usdc in (None, ""):
            payload["status"] = "INCOMPLETE"
            payload["note"] = "USDC worksheet total is missing; both results are retained when present."
            payload["production_total_profit_usdc"] = prod_usdc
            payload["independent_total_profit_usdc"] = indep_usdc
            return payload
        production_total = Decimal(str(prod_usdc))
        independent_total = Decimal(str(indep_usdc))
        payload["production_total_profit_usdc"] = format_decimal(production_total)
        payload["independent_total_profit_usdc"] = format_decimal(independent_total)
        payload["difference_usdc"] = format_decimal(independent_total - production_total)
        payload["settlement_asset"] = "USDC"
        if production_total == independent_total:
            payload["status"] = "AGREE"
            return payload
        payload["status"] = "CONFLICT"
        payload["note"] = (
            "Worksheets disagree. The report keeps the production worksheet; "
            "the independent result is retained separately and is not substituted."
        )
        return payload
    if prod_sol in (None, "") or indep_sol in (None, ""):
        payload["status"] = "INCOMPLETE"
        payload["note"] = "One worksheet is missing; both results are retained when present."
        return payload
    production_total = Decimal(str(prod_sol))
    independent_total = Decimal(str(indep_sol))
    payload["production_total_profit_sol"] = format_decimal(production_total)
    payload["independent_total_profit_sol"] = format_decimal(independent_total)
    payload["difference_sol"] = format_decimal(independent_total - production_total)
    if production_total == independent_total:
        payload["status"] = "AGREE"
        return payload
    payload["status"] = "CONFLICT"
    payload["note"] = (
        "Worksheets disagree. The report keeps the production worksheet; "
        "the independent result is retained separately and is not substituted."
    )
    return payload


def _classification_observations(classification, decoded):
    observations = []
    counts = classification.get("counts") or {}
    if counts:
        observations.append({
            "kind": "tx_classification",
            "detail": ", ".join(f"{name}={count}" for name, count in sorted(counts.items())),
            "count": classification.get("transactions"),
        })
    coverage = decoded.get("coverage") or {}
    observations.append({
        "kind": "decoder_coverage",
        "detail": (
            f"decoded_swaps={coverage.get('decoded_swaps')} "
            f"failed={coverage.get('failed_transactions')} "
            f"unresolved={coverage.get('unresolved_transactions')}"
        ),
        "count": coverage.get("transactions"),
    })
    fees = classification.get("fee_totals") or {}
    if fees:
        observations.append({
            "kind": "fees",
            "detail": (
                f"visible_fee_sol={fees.get('fee_sol')} "
                f"failed_fee_sol={fees.get('failed_fee_sol')} "
                f"(not P&L; integer lamports {fees.get('fee_lamports')})"
            ),
            "count": fees.get("transactions_with_integer_fee"),
        })
    reasons = Counter(row.get("reason") for row in (decoded.get("unresolved") or []) if row.get("reason"))
    for reason, count in reasons.most_common(8):
        observations.append({"kind": "unresolved", "reason": reason, "count": count})
    return observations


def _decoder_coverage(decoded, classification):
    coverage = dict(decoded.get("coverage") or {})
    fees = classification.get("fee_totals") or {}
    coverage.update({
        "visible_fee_lamports": fees.get("fee_lamports"),
        "visible_fee_sol": fees.get("fee_sol"),
        "failed_fee_lamports": fees.get("failed_fee_lamports"),
        "failed_fee_sol": fees.get("failed_fee_sol"),
        "not_pnl": True,
    })
    return coverage


def _partial_findings(classification, decoded):
    fees = classification.get("fee_totals") or {}
    coverage = decoded.get("coverage") or {}
    return [
        {
            "severity": "info",
            "title": "No supported market swaps with known-cost settlement on this captured page",
            "detail": (
                "Holder-fee distributions, failed transactions, and unreviewed Jupiter/PumpSwap "
                "inners stay visible. Rewards and fees are not treated as profit. "
                "Absence of a SOL swap is not proof the wallet is not a trader."
            ),
        },
        {
            "severity": "info",
            "title": "Visible transaction fees are not profit",
            "detail": (
                f"{fees.get('fee_sol')} SOL fees across {fees.get('transactions_with_integer_fee')} txs; "
                f"{fees.get('failed_fee_sol')} SOL on {coverage.get('failed_transactions')} failed txs."
            ),
        },
    ]


def replay_cached_history_to_report(
    store,
    *,
    address,
    records,
    window_start,
    window_end,
    acquisition_start=None,
    mint=None,
    clock=None,
    corpus_kind="GENUINE_REPLAY",
    authorization_id=REPLAY_AUTHORIZATION_ID,
    source_id="archived-history-replay",
):
    """Exact shared path: cache → decoder → accounting → saved application report."""
    from .g3_history import (
        _ordered_inventory_rows,
        completed_episodes,
        declared_subset_events,
        decoder_events_by_mint,
        persist_page,
    )

    service = MassSearchService(store, clock=clock or (lambda: window_end))
    plan = deepcopy(service.preview_plan()["plan"])
    plan["live_enabled"] = False
    plan["selection"]["report_window_days"] = 30
    run = service.create_run(plan, source_id=source_id, corpus_kind=corpus_kind)
    sanitized = sanitize_transaction_records(records)
    page = {
        "kind": PAGE_KIND_V2,
        "address": address,
        "page_index": 0,
        "reason": "offline_archived_replay",
        "records": sanitized["records"],
        "source_body_sha256": sanitized["source_body_sha256"],
        "normalized_sha256": sanitized["normalized_sha256"],
        "integrity": sanitized["integrity"],
        "units_are": "archive",
        "external_requests": 0,
    }
    persist_page(store, authorization_id, address, 0, page)
    from .canonical_records import canonical_decode_records, classify_normalised_records

    wrapped = canonical_decode_records(sanitized["records"])
    decoded = decode_supported_swaps(wrapped, address)
    classification = classify_normalised_records(wrapped, address)
    from .record_breakdown import partition_records

    breakdown = partition_records(
        wrapped, decoded, address,
        window_start=window_start,
        window_end=window_end,
        acquisition_start=acquisition_start,
    )
    by_mint, truncated = decoder_events_by_mint(
        decoded,
        address=address,
        window_start=window_start,
        window_end=window_end,
        acquisition_start=acquisition_start,
    )
    if mint:
        events = _ordered_inventory_rows(by_mint.get(mint) or [])
        report_mint = mint
        try:
            worksheet = independent_settlement_worksheet(events) if events else None
            worksheet_error = None
        except ValueError as error:
            worksheet = None
            worksheet_error = str(error)
    else:
        events = declared_subset_events(by_mint)
        report_mint = "declared-supported-subset"
        from .g3_history import declared_subset_worksheet
        try:
            worksheet = declared_subset_worksheet(by_mint)
            worksheet_error = None
        except ValueError as error:
            worksheet = None
            worksheet_error = str(error)
    observations = _classification_observations(classification, decoded)
    if not events:
        report = {
            "id": f"ranked-partial-{address[:8]}-{run['run_id'][:8]}",
            "address": address,
            "label": f"Mass-search subset · {corpus_kind}",
            "source": "mass-search",
            "corpus_kind": corpus_kind,
            "created_at": window_end,
            "window": {"start": window_start, "end": window_end},
            "methodology": None,
            "policy": "UNRESOLVED",
            "evidence_status": "partial",
            "metrics": {},
            "checks": [],
            "findings": _partial_findings(classification, decoded),
            "evidence": [],
            "coverage": _decoder_coverage(decoded, classification),
            "g3_status": "PARTIAL_NO_SUPPORTED_SOL_SWAPS",
            "source_integrity": sanitized["integrity"],
            "observations": observations,
            "worksheet": None,
            "independent_worksheet": worksheet,
            "worksheet_reconciliation": reconcile_worksheets(None, worksheet),
            "unsupported_transactions": list((decoded.get("coverage") or {}).get("unsupported_transactions") or []),
            "unsupported_tx_count": int((decoded.get("coverage") or {}).get("unsupported_tx_count") or 0),
            "decoded_unresolved_cash_count": int((decoded.get("coverage") or {}).get("decoded_unresolved_cash_count") or 0),
            "decoded_unresolved_cash": list((decoded.get("coverage") or {}).get("decoded_unresolved_cash") or []),
            "worksheet_error": worksheet_error,
            "record_breakdown": breakdown,
            "unsupported_swaps_in_window": breakdown["counts"]["unsupported_swap"],
            "in_window_swaps": breakdown["in_window_swaps"],
            "unsupported_swap_share_in_window": breakdown["unsupported_swap_share_in_window"],
            "in_window_span": breakdown["in_window_span"],
            "conversions": [row for row in (decoded.get("events") or []) if row.get("kind") == "conversion"],
            "events": [],
            "positions": [],
            "counts": {"closed": 0, "open": 0, "interrupted": 0, "unresolved": classification["transactions"]},
            "classification": {
                "counts": classification["counts"],
                "transactions": classification["transactions"],
                "fee_totals": classification.get("fee_totals"),
                "pump_idl_pin": classification["pump_idl_pin"],
            },
            "research": {
                "scope": "Fetched sample; recognized single spot routes with SOL/wSOL or USDC settlement",
                "history_complete": False,
                "supported_swaps": int((decoded.get("coverage") or {}).get("decoded_swaps") or 0),
            },
            "notes": [
                "Honest partial report. No independently reconciled completed known-cost position on this captured page.",
                "Holder-fee distributions, failed transactions, and unreviewed Jupiter/PumpSwap inners stay visible.",
                "Rewards and fees are not trading P&L. No SOL swap is not proof the wallet is not a trader.",
                "PRODUCT_READY remains false.",
            ],
            "offline_replay": True,
            "PRODUCT_READY": False,
            "not_match": True,
            "not_ranked_wallet_pipeline_proof": True,
            "shortlist_rank": 1,
            "visible_report": False,
        }
        store.put("reports", report["id"], report)
        return {
            "run_id": run["run_id"],
            "report_id": report["id"],
            "report": report,
            "worksheet": None,
            "independent_worksheet": worksheet,
            "worksheet_reconciliation": report["worksheet_reconciliation"],
            "visible_report": False,
            "classification": classification,
            "external_requests": 0,
            "truncated_before_acquisition_support": truncated,
            "PRODUCT_READY": False,
            "not_match": True,
        }
    episodes = completed_episodes(by_mint)
    reconstructed = service.reconstruct_candidate(
        run["run_id"], f"solana:{address}", events,
        corpus_kind=corpus_kind, mint=report_mint,
    )
    report = reconstructed["report"]
    report["source"] = "mass-search"
    report["policy"] = report.get("policy") or "UNRESOLVED"
    production = reconstructed.get("worksheet") or report.get("worksheet")
    report["worksheet"] = production
    report["independent_worksheet"] = worksheet
    report["worksheet_reconciliation"] = reconcile_worksheets(production, worksheet)
    report["declared_mints"] = [mint] if mint else sorted(by_mint)
    report["source_integrity"] = sanitized["integrity"]
    report["observations"] = observations
    report["classification"] = {
        "counts": classification["counts"],
        "transactions": classification["transactions"],
        "fee_totals": classification.get("fee_totals"),
        "pump_idl_pin": classification["pump_idl_pin"],
    }
    report["coverage"] = {
        **(report.get("coverage") or {}),
        **_decoder_coverage(decoded, classification),
    }
    report["offline_replay"] = True
    report["PRODUCT_READY"] = False
    report["not_ranked_wallet_pipeline_proof"] = True
    report["wallet_completed_episodes"] = episodes["wallet_completed_episodes"]
    report["wallet_sale_count"] = episodes.get("wallet_sale_count")
    report["completed_episode_detail"] = episodes
    report["by_quote_asset"] = (production or worksheet or {}).get("by_quote_asset")
    report["unsupported_transactions"] = list((decoded.get("coverage") or {}).get("unsupported_transactions") or [])
    report["unsupported_tx_count"] = int((decoded.get("coverage") or {}).get("unsupported_tx_count") or 0)
    report["decoded_unresolved_cash_count"] = int((decoded.get("coverage") or {}).get("decoded_unresolved_cash_count") or 0)
    report["decoded_unresolved_cash"] = list((decoded.get("coverage") or {}).get("decoded_unresolved_cash") or [])
    report["worksheet_error"] = worksheet_error
    if worksheet_error:
        report.setdefault("findings", []).append({
            "severity": "error",
            "title": "Worksheet construction failed",
            "detail": worksheet_error,
        })
        report["visible_report"] = False
    residual = Decimal("0")
    start_unix = datetime.fromisoformat(window_start.replace("Z", "+00:00")).timestamp()
    end_unix = (
        datetime.fromisoformat(window_end.replace("Z", "+00:00")).timestamp()
        if window_end else None
    )
    for event in decoded.get("events") or []:
        if event.get("kind") != "buy":
            continue
        timestamp = event.get("timestamp")
        if not isinstance(timestamp, (int, float)) or isinstance(timestamp, bool):
            continue
        if timestamp < start_unix:
            continue
        if end_unix is not None and timestamp >= end_unix:
            continue
        funding = event.get("excluded_funding_sol")
        if funding not in (None, ""):
            residual += Decimal(str(funding))
        else:
            for item in event.get("retained_account_funding") or []:
                if isinstance(item.get("lamports"), int):
                    residual += Decimal(item["lamports"]) / Decimal(1_000_000_000)
    if residual != 0:
        quantized = residual.quantize(Decimal("0.000000001"))
        report["residual_sol"] = format(quantized, "f")
        report["residual_sol_note"] = (
            "explained by identified new-account rent on buys in the report window, "
            "excluded from swap consideration"
        )
        report["residual_sol_scope"] = "in_window_buys"
    sensitivity = Decimal("0")
    verified_tips = Decimal("0")
    platform_fees = Decimal("0")
    failed_fees = Decimal("0")
    charges = []
    for event in decoded.get("events") or []:
        if event.get("unverified_debits_sol") not in (None, ""):
            sensitivity += Decimal(str(event["unverified_debits_sol"]))
        if event.get("tips_sol") not in (None, ""):
            verified_tips += Decimal(str(event["tips_sol"]))
        if event.get("platform_fee_sol") not in (None, ""):
            platform_fees += Decimal(str(event["platform_fee_sol"]))
        if event.get("kind") == "fee" and event.get("failed") and event.get("paid_by_wallet"):
            failed_fees += Decimal(str(event.get("amount_sol") or event.get("network_fee_sol") or 0))
            charges.append({
                "signature": event.get("signature"),
                "economic_role": "network_plus_priority_fee",
                "sol": event.get("amount_sol") or event.get("network_fee_sol"),
                "transaction_failed": True,
                "allocate_to": "failed_attempts",
            })
        elif event.get("kind") == "tip":
            charges.append({
                "signature": event.get("signature"),
                "economic_role": "verified_tip",
                "sol": event.get("tips_sol"),
                "separate_successful_transaction": True,
                "allocate_to": "other_activity",
            })
        elif event.get("kind") in ("buy", "sell"):
            if event.get("network_fee_sol") not in (None, "", "0"):
                charges.append({
                    "signature": event.get("signature"),
                    "economic_role": "network_plus_priority_fee",
                    "sol": event.get("network_fee_sol"),
                    "episode_closed": True,
                    "allocate_to": "closed_episodes",
                })
            if event.get("tips_sol") not in (None, "", "0"):
                charges.append({
                    "signature": event.get("signature"),
                    "economic_role": "verified_tip",
                    "sol": event.get("tips_sol"),
                    "episode_closed": True,
                    "allocate_to": "closed_episodes",
                })
            if event.get("platform_fee_sol") not in (None, "", "0"):
                charges.append({
                    "signature": event.get("signature"),
                    "economic_role": "proven_router_or_platform_fee",
                    "sol": event.get("platform_fee_sol"),
                    "episode_closed": True,
                    "allocate_to": "closed_episodes",
                })
            if event.get("unverified_debits_sol") not in (None, "", "0"):
                charges.append({
                    "signature": event.get("signature"),
                    "economic_role": "unexplained_transfer",
                    "sol": event.get("unverified_debits_sol"),
                })
    from scanner.mass_search.qualification_gates import allocate_verified_costs
    allocation = allocate_verified_costs(charges)
    report["verified_tips_sol"] = str(verified_tips)
    report["proven_platform_fees_sol"] = str(platform_fees)
    report["failed_attempt_expenses_sol"] = str(failed_fees)
    report["unallocated_verified_costs_sol"] = allocation.get("other_activity_sol")
    report["cost_allocation"] = allocation
    report["sensitivity_unverified_debits_sol"] = str(sensitivity)
    report["sensitivity_unverified_debits_note"] = (
        "Unexplained transfers stay in sensitivity and are never called fees. "
        "Proven router or platform fees and published-list tips are costs. "
        "Wallet-paid network fees on failed transactions are charged; their transfers are excluded."
    )
    report["record_breakdown"] = breakdown
    report["unsupported_swaps_in_window"] = breakdown["counts"]["unsupported_swap"]
    report["in_window_swaps"] = breakdown["in_window_swaps"]
    report["unsupported_swap_share_in_window"] = breakdown["unsupported_swap_share_in_window"]
    report["in_window_span"] = breakdown["in_window_span"]
    report["conversions"] = [row for row in (decoded.get("events") or []) if row.get("kind") == "conversion"]
    report["visible_report"] = visible_report_allowed(
        worksheet=production or worksheet,
        completed_positions=_visible_completed_positions(episodes, production or worksheet),
    )
    report["not_match"] = True
    if worksheet and worksheet.get("settlement_asset") == "USDC":
        report["g3_status"] = "PARTIAL_USDC_KNOWN_COST"
        report["research"] = {
            **(report.get("research") or {}),
            "scope": "Fetched sample; recognized single spot routes with SOL/wSOL or USDC settlement",
            "history_complete": False,
            "supported_swaps": int((decoded.get("coverage") or {}).get("decoded_swaps") or 0),
            "settlement_asset": "USDC",
        }
        report["notes"] = [
            "USDC-settled Jupiter route_v2 subset. SOL fees stay SOL and are not converted.",
            "Holder-fee distributions are rewards, not trading P&L.",
            "Leading/unbacked sells stay unresolved_basis. PRODUCT_READY remains false.",
        ]
    from .research_profile import build_research_profile, default_filters
    report["research_profile"] = build_research_profile(
        report, filters=default_filters(), classification=classification,
    )
    from .funnel_abc import classify_candidate
    report["funnel"] = classify_candidate(
        provider_rank=1,
        capture_available=True,
        profile=report["research_profile"],
        classification=classification,
        worksheet=production or worksheet,
    )
    store.put("reports", report["id"], report)
    return {
        "run_id": run["run_id"],
        "report_id": report["id"],
        "report": report,
        "worksheet": report.get("worksheet"),
        "independent_worksheet": worksheet,
        "worksheet_reconciliation": report["worksheet_reconciliation"],
        "visible_report": visible_report_allowed(
            worksheet=production or worksheet,
            completed_positions=_visible_completed_positions(episodes, production or worksheet),
        ),
        "external_requests": 0,
        "truncated_before_acquisition_support": truncated,
        "PRODUCT_READY": False,
        "not_match": True,
    }


# --- Next-capture dispatch boundary (offline; never a live grant) ---

NAMED_DEPENDENCY_PROGRESS = {
    "kind": "named_dependency_progress_v1",
    "measurable_progress": (
        "named_sale_or_lot_unresolved_basis_cleared",
        "named_sale_or_lot_gained_classified_cost_role",
        "named_opening_lot_now_has_known_basis",
    ),
    "requires_observable_result_before_another_page": True,
    "not_progress": (
        "wallet_turned_positive",
        "episode_count_increased_without_touching_named_item",
        "unrelated_new_mints",
    ),
}

G1_AUTHORIZATION_ID = "live-g1-vertical-slice-2026-10-05-mitch"
NEXT_CAPTURE_WRONG_KIND = frozenset({
    G1_AUTHORIZATION_ID,
    "live-ranked100-research-search-2026-10-06-mitch",
    "live-ranked100-g3-history-2026-10-06-mitch",
    "live-ranked100-g2-discovery-2026-10-05-mitch",
})


def named_dependency_progress(previous_page_result, wallet_entry):
    """Measurable progress requires an identified sale/lot plus an observed result.

    A bare boolean, free-text named_dependency, or incidental positivity is
    never progress. Identical named evidence yields the same decision whether
    or not wallet_turned_positive is also reported.
    """
    named_items = list((wallet_entry or {}).get("named_dependency_items") or [])
    observations = list((previous_page_result or {}).get("named_dependency_observations") or [])
    incidental_positive = bool((previous_page_result or {}).get("wallet_turned_positive"))
    accepted = list((wallet_entry or {}).get("acceptable_progress_observations") or [])
    if not named_items:
        return {
            "progress": False,
            "approached": False,
            "resolved": False,
            "reason": "no_named_sale_or_lot_recorded",
            "incidental_positivity_ignored": incidental_positive,
            "matched": [],
            **NAMED_DEPENDENCY_PROGRESS,
        }
    if not accepted:
        return {
            "progress": False,
            "approached": False,
            "resolved": False,
            "reason": "no_acceptable_progress_observations",
            "incidental_positivity_ignored": incidental_positive,
            "matched": [],
            **NAMED_DEPENDENCY_PROGRESS,
        }
    matched = []
    for item in named_items:
        key = item.get("signature") or item.get("mint")
        for row in observations:
            if key and key in {row.get("signature"), row.get("mint")}:
                result = row.get("result")
                if result in accepted:
                    matched.append(row)
                elif result in (None, "") and "named_sale_or_lot_unresolved_basis_cleared" in accepted and row.get("unresolved_basis_cleared"):
                    matched.append(row)
                elif result in (None, "") and "named_sale_or_lot_gained_classified_cost_role" in accepted and row.get("classified_cost_role"):
                    matched.append(row)
    return {
        "progress": bool(matched),
        "approached": bool(matched),
        "resolved": any(row.get("unresolved_basis_cleared") for row in matched),
        "reason": "named_sale_or_lot_observed" if matched else "named_sale_or_lot_not_observed",
        "incidental_positivity_ignored": incidental_positive,
        "matched": matched,
        **NAMED_DEPENDENCY_PROGRESS,
    }


def _next_capture_refuse(draft, code, detail):
    return {
        "allowed": False,
        "dispatched": False,
        "code": code,
        "detail": detail,
        "not_a_dispatched_request": True,
        "transport_calls": 0,
        "draft_enabled": bool((draft or {}).get("enabled")),
        "PRODUCT_READY": False,
    }


def draft_execution_artifact_hash(draft):
    payload = json.dumps(draft or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


RESERVED_UNALLOCATED = 12
NEXT_CAPTURE_STATE_KIND = "next_capture_offline_state"
EXHAUSTED_CURSOR = "__exhausted__"


def _parse_aware(value):
    if value in (None, ""):
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def _strict_nonneg_int(value):
    if type(value) is not int or value < 0:
        return None
    return value


def validate_operator_quota_record(record, draft=None):
    """Operator-supplied remaining-quota confirmation. Truthy strings are not enough."""
    if not isinstance(record, dict):
        return "quota_not_bound"
    if record.get("kind") != "operator_quota_record_v1":
        return "quota_not_bound"
    ceiling = _strict_nonneg_int(record.get("ceiling"))
    reserved = _strict_nonneg_int(record.get("reserved_unallocated"))
    usable = _strict_nonneg_int(record.get("usable_ceiling"))
    remaining = _strict_nonneg_int(record.get("remaining"))
    if None in (ceiling, reserved, usable, remaining):
        return "quota_not_bound"
    if reserved != RESERVED_UNALLOCATED:
        return "reserved_is_discretionary"
    if usable != ceiling - reserved:
        return "quota_inconsistent"
    if remaining > usable:
        return "quota_inconsistent"
    if record.get("overages_enabled") is not False:
        return "overages_not_disabled"
    if not str(record.get("operator") or "").strip():
        return "quota_operator_missing"
    confirmed = _parse_aware(record.get("confirmed_at"))
    if confirmed is None:
        return "quota_confirmed_at_missing"
    baseline = _strict_nonneg_int(record.get("baseline"))
    if baseline is None:
        return "quota_baseline_missing"
    if remaining > baseline or baseline > usable:
        return "quota_inconsistent"
    if draft is not None:
        expected_id = (draft or {}).get("authorization_id")
        if record.get("authorization_id") != expected_id:
            return "quota_authorization_mismatch"
        expected_hash = (draft or {}).get("execution_artifact_hash") or draft_execution_artifact_hash(draft)
        record_hash = record.get("execution_artifact_hash") or record.get("execution_artifact_hash_of_this_draft")
        if record_hash != expected_hash:
            return "quota_artifact_mismatched"
    return None


def validate_approval_expiry_relationship(grant, *, now=None):
    approval = _parse_aware(grant.get("approval_timestamp"))
    expiry = _parse_aware(grant.get("expiry"))
    if grant.get("approval_timestamp") in (None, ""):
        return "missing_approval_timestamp"
    if approval is None:
        return "invalid_approval_timestamp"
    if grant.get("expiry") in (None, ""):
        return "missing_expiry"
    if expiry is None:
        return "invalid_expiry"
    moment = now or datetime.now(timezone.utc)
    if approval >= expiry:
        return "approval_not_before_expiry"
    if approval > moment:
        return "approval_in_the_future"
    if expiry <= moment:
        return "expired_grant"
    return None


def validate_fresh_approval_bind(grant, draft, *, now=None):
    """Validate bind fields before any transport call. Returning names is not enough."""
    if not grant:
        return "missing_grant"
    if grant.get("enabled") is True:
        return "grant_enabled"
    if grant.get("consumed") or grant.get("status") == "consumed":
        return "consumed_grant"
    if grant.get("authorization_id") in NEXT_CAPTURE_WRONG_KIND:
        return "wrong_kind_grant"
    if grant.get("authorization_id") != (draft or {}).get("authorization_id"):
        return "wrong_kind_grant"
    if grant.get("synthetic_offline_authorization") is not True:
        return "not_synthetic_offline_authorization"
    expected = (draft or {}).get("execution_artifact_hash") or draft_execution_artifact_hash(draft)
    if grant.get("execution_artifact_hash_of_this_draft") != expected:
        return "artifact_mismatched_grant"
    if grant.get("overages_enabled") is not False:
        return "overages_not_disabled"
    quota_error = validate_operator_quota_record(grant.get("current_remaining_quota_confirmation"), draft)
    if quota_error:
        return quota_error
    time_error = validate_approval_expiry_relationship(grant, now=now)
    if time_error:
        return time_error
    record = grant.get("current_remaining_quota_confirmation") or {}
    confirmed = _parse_aware(record.get("confirmed_at"))
    approval = _parse_aware(grant.get("approval_timestamp"))
    expiry = _parse_aware(grant.get("expiry"))
    if confirmed and approval and confirmed < approval:
        return "quota_confirmed_before_approval"
    if confirmed and expiry and confirmed > expiry:
        return "quota_confirmed_after_expiry"
    moment = now or datetime.now(timezone.utc)
    if confirmed and confirmed > moment:
        return "quota_confirmed_in_the_future"
    return None


def _receipt_matches_dispatch(receipt, last_dispatch):
    if not isinstance(receipt, dict) or not isinstance(last_dispatch, dict):
        return False
    if receipt.get("consumed") is True:
        return False
    if receipt.get("page_identity") in (None, ""):
        return False
    required = ("response_id", "page_identity", "address", "authorization_id", "attempt")
    for key in required:
        expected = last_dispatch.get(key)
        if expected in (None, ""):
            return False
        got = receipt.get(key)
        if got in (None, "") and key in ("address", "authorization_id", "attempt"):
            if (
                receipt.get("response_id") == last_dispatch.get("response_id")
                and receipt.get("page_identity") == last_dispatch.get("page_identity")
            ):
                got = expected
        if got != expected:
            return False
    return True


def replay_bound_to_last_dispatch(last_dispatch, replay_receipts):
    """Replay is a receipt for a specific last page/response/wallet/grant/attempt."""
    if not isinstance(last_dispatch, dict) or not last_dispatch.get("response_id"):
        return False
    if last_dispatch.get("status") in ("reserved", "failed"):
        return False
    for key in ("page_identity", "address", "authorization_id", "attempt"):
        if last_dispatch.get(key) in (None, ""):
            return False
    for row in replay_receipts or []:
        if _receipt_matches_dispatch(row, last_dispatch):
            return True
    return False


def bind_progress_to_replay(previous_progress, last_dispatch, replay_receipts):
    """Progress is only accepted when it names the latest replayed response."""
    if not previous_progress:
        return previous_progress
    if not replay_bound_to_last_dispatch(last_dispatch, replay_receipts):
        return {"named_dependency_observations": []}
    bound_id = previous_progress.get("response_id") or previous_progress.get("replay_response_id")
    bound_page = previous_progress.get("page_identity")
    expected_id = (last_dispatch or {}).get("response_id")
    expected_page = (last_dispatch or {}).get("page_identity")
    if bound_id != expected_id:
        return {"named_dependency_observations": []}
    if bound_page not in (None, "", expected_page) and bound_page != expected_page:
        return {"named_dependency_observations": []}
    return previous_progress


def record_next_capture_replay(state, receipt):
    """Attach a receipt only when it names the last dispatched response. Single-use."""
    state = state if state is not None else empty_next_capture_state()
    dispatch = state.get("last_dispatch") or {}
    if not replay_bound_to_last_dispatch(dispatch, [receipt]):
        return False
    receipts = list(state.get("replay_receipts") or [])
    for row in receipts:
        if (
            row.get("response_id") == (receipt or {}).get("response_id")
            and row.get("attempt") == dispatch.get("attempt")
        ):
            return False
    bound = {
        "response_id": dispatch.get("response_id"),
        "page_identity": dispatch.get("page_identity"),
        "address": dispatch.get("address"),
        "authorization_id": dispatch.get("authorization_id"),
        "attempt": dispatch.get("attempt"),
    }
    receipts.append(bound)
    state["replay_receipts"] = receipts
    state["replay_completed"] = True
    return True


def wallet_cursor_state(state, address, wallet=None):
    recorded = ((state or {}).get("cursor_state") or {}).get(address)
    if recorded in ("not-started", "open", "exhausted"):
        return recorded
    accepted = ((state or {}).get("accepted_continuation") or {}).get(address)
    if accepted == EXHAUSTED_CURSOR:
        return "exhausted"
    if accepted:
        return "open"
    return "not-started"


def _progress_wallet(draft, wallet, last_dispatch):
    if not (wallet or {}).get("shares_global_phase_two_progress_rule"):
        return wallet
    preceding = (last_dispatch or {}).get("address")
    allowed = list((draft or {}).get("allowed_wallets") or [])
    if preceding:
        found = next((row for row in allowed if row.get("address") == preceding), None)
        if found:
            return found
    return next((row for row in allowed if row.get("phase") == 1), wallet)


def evaluate_next_capture_dispatch(
    *,
    draft,
    requested,
    grant=None,
    replay_completed=False,
    previous_progress=None,
    requests_used=0,
    per_wallet_used=None,
    accepted_continuation=None,
    fake_transport=None,
    last_dispatch=None,
    replay_receipts=None,
    cursor_state=None,
    now=None,
):
    """Offline dispatch boundary. Never invokes a network transport.

    Caller-supplied phase and a free-standing replay_completed flag are not
    trusted. Replay must name the last dispatched page/response identity.
    """
    del fake_transport
    del replay_completed
    per_wallet_used = per_wallet_used or {}
    accepted_continuation = accepted_continuation or {}
    cursor_state = cursor_state or {}
    address = (requested or {}).get("address")
    cutoff = (requested or {}).get("block_time_lt")
    cursor = (requested or {}).get("pagination_token")
    expected_cutoff = next_capture_block_time_lt(draft)
    excluded = (draft or {}).get("excluded_from_this_draft") or {}
    allowed = list((draft or {}).get("allowed_wallets") or [])
    wallet = next((row for row in allowed if row.get("address") == address), None)
    budget = (draft or {}).get("page_budget") or {}
    ceiling = int((draft or {}).get("max_dispatched_requests") or budget.get("total_request_ceiling") or 20)
    reserved = int(budget.get("reserved_unallocated") or 0)
    usable_ceiling = ceiling - reserved
    wallet_cap = int((wallet or {}).get("initial_pages") or 0) + int(
        (wallet or {}).get("max_additional_pages_if_previous_resolved_named_dependency") or 0
    )
    used = int(per_wallet_used.get(address) or 0)
    total_used = int(requests_used or 0)
    phase1 = next((row for row in allowed if row.get("phase") == 1), None)
    is_phase1 = bool(wallet and phase1 and wallet.get("address") == phase1.get("address"))
    a6ps_start = bool((wallet or {}).get("separately_authorized_phase_two_start"))
    replay_ok = replay_bound_to_last_dispatch(last_dispatch, replay_receipts)
    recorded_cursor = cursor_state.get(address) or wallet_cursor_state(
        {
            "cursor_state": cursor_state,
            "accepted_continuation": accepted_continuation,
            "per_wallet_used": per_wallet_used,
        },
        address,
        wallet,
    )

    def refuse(code, detail):
        return _next_capture_refuse(draft, code, detail)

    if (draft or {}).get("enabled") is not False:
        return refuse("draft_must_stay_disabled", "Repo next-capture draft must stay enabled:false")
    if grant:
        bind_error = validate_fresh_approval_bind(grant, draft, now=now) if grant.get("synthetic_offline_authorization") else None
        if grant.get("enabled") is True:
            return refuse("grant_enabled", "This evaluator never arms a live grant")
        if grant.get("consumed") or grant.get("status") == "consumed":
            return refuse("consumed_grant", "Authorization already consumed")
        if grant.get("authorization_id") in NEXT_CAPTURE_WRONG_KIND:
            return refuse("wrong_kind_grant", "g1/other consumed grants are not permission for this capture")
        if grant.get("authorization_id") != (draft or {}).get("authorization_id"):
            return refuse("wrong_kind_grant", "Grant authorization_id is not this draft")
        if bind_error:
            return refuse(bind_error, "Fresh approval bind fields failed validation")
        quota = grant.get("current_remaining_quota_confirmation") or {}
        remaining = _strict_nonneg_int(quota.get("remaining"))
        if remaining is None:
            return refuse("quota_not_bound", "Remaining approved allowance is not a strict non-negative integer")
        if total_used >= remaining:
            return refuse("quota_exhausted", "Remaining approved allowance is already consumed")
    if address in excluded:
        return refuse("excluded_wallet", excluded.get(address) or "wallet excluded from this draft")
    if wallet is None:
        return refuse("wrong_wallet", "Address is not in allowed_wallets")
    if cutoff not in (None, expected_cutoff) and int(cutoff) != int(expected_cutoff):
        return refuse("wrong_cutoff", f"blockTime.lt must be {expected_cutoff}")
    if recorded_cursor == "exhausted" or accepted_continuation.get(address) == EXHAUSTED_CURSOR:
        return refuse("cursor_exhausted", "Terminal response already consumed; no further request for this wallet")
    if recorded_cursor == "open":
        expected_cursor = accepted_continuation.get(address)
    elif recorded_cursor == "not-started":
        expected_cursor = wallet.get("continue_from_pagination_token")
    else:
        expected_cursor = accepted_continuation.get(address) or wallet.get("continue_from_pagination_token")
    if expected_cursor == EXHAUSTED_CURSOR:
        return refuse("cursor_exhausted", "Terminal response already consumed; no further request for this wallet")
    if expected_cursor and cursor != expected_cursor:
        return refuse("wrong_cursor", "paginationToken is not the accepted preceding continuation")
    if not expected_cursor and cursor:
        return refuse("wrong_cursor", "paginationToken is not authorized for this wallet")
    if not is_phase1 and total_used == 0 and not replay_ok:
        return refuse("non_gtfo_initial", "Only the phase-1 gtfo continuation may be the first dispatch")
    if (total_used >= 1 or used >= 1) and not replay_ok:
        return refuse("second_before_replay", "Any second dispatch requires offline replay of the last page")
    if int(requests_used or 0) >= usable_ceiling:
        return refuse("over_budget", "Reserved 12 cannot become discretionary spend or override the usable ceiling")
    if requested.get("use_reserved") and not (grant or {}).get("amended_reserved_authorization"):
        return refuse("reserved_unavailable", "Reserved 12 stays unavailable without an amended freshly bound authorization")
    if used >= int((wallet or {}).get("initial_pages") or 0) and (wallet or {}).get("additional_page_unavailable"):
        return refuse("additional_page_unavailable", "Additional page is explicitly unavailable for this wallet")
    if used >= wallet_cap:
        return refuse("per_wallet_limit", "Reserved budget cannot override a stricter per-wallet limit")
    allowance = wallet.get("executable_allowance")
    decoder_first = bool(wallet.get("decoder_first") or int(wallet.get("initial_pages") or 0) == 0)
    if decoder_first:
        items = list(wallet.get("named_dependency_items") or [])
        try:
            allowance_n = int(allowance)
        except (TypeError, ValueError):
            allowance_n = 0
        if allowance_n <= 0 or not items:
            return refuse(
                "zero_executable_allowance",
                "Decoder-first wallets have zero executable pages until a named sale/lot and a positive executable_allowance are recorded",
            )
        if used >= allowance_n:
            return refuse("zero_executable_allowance", "executable_allowance already consumed")
    previous_progress = bind_progress_to_replay(previous_progress, last_dispatch, replay_receipts)
    if not is_phase1:
        if not replay_ok:
            return refuse("phase_two_before_replay", "Non-gtfo pages require offline replay of the last dispatched page")
        if a6ps_start and used == 0:
            pass
        else:
            progressed = named_dependency_progress(previous_progress, _progress_wallet(draft, wallet, last_dispatch))
            if not progressed.get("progress"):
                return refuse(
                    "named_dependency_not_approached",
                    "Further pages require an observable result on a named sale/lot before another page",
                )
    elif used >= 1:
        progressed = named_dependency_progress(previous_progress, wallet)
        if not progressed.get("progress"):
            return refuse(
                "named_dependency_not_approached",
                "Further gtfo pages require an observable result on a named sale/lot",
            )
    if requested.get("continue_because_positive") or requested.get("stop_because_positive"):
        return refuse("outcome_driven", "Never stop or continue because a wallet turned positive")
    return {
        "allowed": True,
        "dispatched": False,
        "code": "would_serialize_only",
        "detail": "Boundary passed. Draft stays enabled:false; this is not a live dispatch.",
        "not_a_dispatched_request": True,
        "transport_calls": 0,
        "draft_enabled": False,
        "PRODUCT_READY": False,
        "expected_cursor": expected_cursor,
        "cursor_state": recorded_cursor,
        "replay_bound": replay_ok,
        "fresh_approval_must_bind": [
            "execution_artifact_hash_of_this_draft",
            "current_remaining_quota_confirmation",
            "overages_enabled=false",
            "approval_timestamp",
            "expiry",
        ],
    }


def empty_next_capture_state():
    return {
        "requests": [],
        "requests_used": 0,
        "per_wallet_used": {},
        "replay_completed": False,
        "accepted_continuation": {},
        "cursor_state": {},
        "last_dispatch": None,
        "replay_receipts": [],
        "attempts": [],
        "attempt_seq": 0,
        "generation": 0,
        "phase1_dispatched": False,
    }


def load_next_capture_state(store, draft, state=None):
    """Durable store state is authoritative whenever a store exists.

    A stale or empty caller-supplied state cannot reset a persisted timeout,
    consumed attempt, or last_dispatch identity.
    """
    if store is not None:
        saved = store.get(NEXT_CAPTURE_STATE_KIND, (draft or {}).get("authorization_id"))
        if saved:
            return saved
        return empty_next_capture_state()
    if state is not None:
        return state
    return empty_next_capture_state()


def persist_next_capture_state(store, draft, state):
    if store is None:
        return state
    store.put(NEXT_CAPTURE_STATE_KIND, (draft or {}).get("authorization_id"), state)
    return state


def _response_identity(serialized, result):
    payload = json.dumps(
        {"serialized": serialized, "result": result},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _mint_response_id(draft, address, page_identity, attempt_seq, serialized):
    return _response_identity(
        serialized,
        {
            "authorization_id": (draft or {}).get("authorization_id"),
            "address": address,
            "page_identity": page_identity,
            "attempt": attempt_seq,
        },
    )


def _transport_error_or_garbage(result):
    if not isinstance(result, dict):
        return True
    if result.get("error") not in (None, "", False):
        return True
    if result.get("errors"):
        return True
    return False


def run_next_capture_offline(
    *,
    draft,
    requested,
    grant,
    transport,
    state=None,
    previous_progress=None,
    now=None,
    store=None,
):
    """Intended offline runner. Reserve before transport; persist after.

    Repository draft stays enabled:false. Only a clearly synthetic authorization
    that binds artifact/quota/overages/time/expiry may reach the recorder.
    Failed or timed-out transport still consumes the reserved attempt.
    A durable store is required. Load through reserve-persist is serialized
    by CAS on generation (or the store lock). The loser refuses before transport.
    """
    if store is None:
        refused = _next_capture_refuse(draft, "durable_store_required", "Offline capture refuses to dispatch without a durable store")
        return {**refused, "state": state or empty_next_capture_state()}
    lock = getattr(store, "lock", None)

    loaded = load_next_capture_state(store, draft, state)
    expected_generation = int(loaded.get("generation") or 0)
    decision = evaluate_next_capture_dispatch(
        draft=draft,
        requested=requested,
        grant=grant,
        previous_progress=previous_progress,
        requests_used=int(loaded.get("requests_used") or 0),
        per_wallet_used=loaded.get("per_wallet_used") or {},
        accepted_continuation=loaded.get("accepted_continuation") or {},
        last_dispatch=loaded.get("last_dispatch"),
        replay_receipts=loaded.get("replay_receipts") or [],
        cursor_state=loaded.get("cursor_state") or {},
        now=now,
    )
    if not decision.get("allowed"):
        return {**decision, "transport_calls": 0, "state": loaded}
    bind_error = validate_fresh_approval_bind(grant, draft, now=now)
    if bind_error:
        refused = _next_capture_refuse(draft, bind_error, "Fresh approval bind fields failed validation")
        return {**refused, "state": loaded}
    address = requested.get("address")
    expected_cursor = decision.get("expected_cursor")
    serialized = serialize_next_capture_gta_request(
        address,
        pagination_token=expected_cursor,
        draft=draft,
    )
    options = (serialized.get("params") or [None, {}])[1] or {}
    serialized_cursor = options.get("paginationToken")
    if serialized_cursor != expected_cursor:
        refused = _next_capture_refuse(draft, "wrong_cursor", "Serialized request continuation does not match accepted state")
        return {**refused, "state": loaded}
    used = dict(loaded.get("per_wallet_used") or {})
    used[address] = int(used.get(address) or 0) + 1
    attempt_seq = int(loaded.get("attempt_seq") or 0) + 1
    attempts = list(loaded.get("attempts") or [])
    attempt = {
        "address": address,
        "pagination_token": expected_cursor,
        "status": "reserved",
        "cutoff": next_capture_block_time_lt(draft),
        "attempt": attempt_seq,
        "authorization_id": (draft or {}).get("authorization_id"),
    }
    attempts.append(attempt)
    requests = list(loaded.get("requests") or [])
    requests.append({
        "address": address,
        "pagination_token": expected_cursor,
        "cutoff": next_capture_block_time_lt(draft),
        "status": "reserved",
        "attempt": attempt_seq,
    })
    current = dict(loaded)
    current.update({
        "requests": requests,
        "requests_used": int(loaded.get("requests_used") or 0) + 1,
        "per_wallet_used": used,
        "attempts": attempts,
        "attempt_seq": attempt_seq,
        "generation": expected_generation + 1,
        "replay_completed": False,
        "replay_receipts": [],
        "last_dispatch": {
            "address": address,
            "page_identity": expected_cursor,
            "status": "reserved",
            "response_id": None,
            "authorization_id": (draft or {}).get("authorization_id"),
            "attempt": attempt_seq,
        },
        "phase1_dispatched": True,
    })
    won = False
    if hasattr(store, "cas_put"):
        won = bool(store.cas_put(NEXT_CAPTURE_STATE_KIND, (draft or {}).get("authorization_id"), current, expected_generation))
    elif lock is not None:
        with lock:
            fresh = load_next_capture_state(store, draft, None)
            if int(fresh.get("generation") or 0) != expected_generation:
                won = False
            else:
                persist_next_capture_state(store, draft, current)
                won = True
    else:
        persist_next_capture_state(store, draft, current)
        won = True
    if not won:
        refused = _next_capture_refuse(draft, "concurrent_reservation", "Lost the durable reservation race; refuse before transport")
        return {**refused, "state": load_next_capture_state(store, draft, current)}

    def _persist_after_transport(mutator):
        def _apply():
            latest = load_next_capture_state(store, draft, current)
            mutator(latest)
            latest["generation"] = int(latest.get("generation") or 0) + 1
            persist_next_capture_state(store, draft, latest)
            return latest

        if lock is not None:
            with lock:
                return _apply()
        return _apply()

    try:
        result = transport(serialized)
    except Exception as exc:
        def _fail(latest):
            latest_attempts = list(latest.get("attempts") or [])
            if latest_attempts:
                latest_attempts[-1]["status"] = "failed"
                latest_attempts[-1]["error"] = type(exc).__name__
                latest_attempts[-1]["detail"] = str(exc)[:240]
            latest_requests = list(latest.get("requests") or [])
            if latest_requests:
                latest_requests[-1]["status"] = "failed"
            latest["attempts"] = latest_attempts
            latest["requests"] = latest_requests
            latest["last_dispatch"] = {
                "address": address,
                "page_identity": expected_cursor,
                "status": "failed",
                "response_id": None,
                "authorization_id": (draft or {}).get("authorization_id"),
                "attempt": attempt_seq,
            }

        current = _persist_after_transport(_fail)
        return {
            "allowed": True,
            "dispatched": True,
            "synthetic_offline_only": True,
            "code": "synthetic_recorder_failed",
            "detail": "Synthetic recorder failed or timed out after the attempt was reserved. Not a live grant.",
            "transport_calls": 1,
            "attempt_consumed": True,
            "not_a_live_dispatch": True,
            "draft_enabled": False,
            "PRODUCT_READY": False,
            "serialized": serialized,
            "state": current,
        }
    if _transport_error_or_garbage(result):
        def _garbage(latest):
            latest_attempts = list(latest.get("attempts") or [])
            if latest_attempts:
                latest_attempts[-1]["status"] = "failed"
                latest_attempts[-1]["error"] = "transport_error_envelope"
            latest_requests = list(latest.get("requests") or [])
            if latest_requests:
                latest_requests[-1]["status"] = "failed"
            latest["attempts"] = latest_attempts
            latest["requests"] = latest_requests
            latest["last_dispatch"] = {
                "address": address,
                "page_identity": expected_cursor,
                "status": "failed",
                "response_id": None,
                "authorization_id": (draft or {}).get("authorization_id"),
                "attempt": attempt_seq,
            }

        current = _persist_after_transport(_garbage)
        return {
            "allowed": True,
            "dispatched": True,
            "synthetic_offline_only": True,
            "code": "synthetic_recorder_failed",
            "detail": "Error or non-page transport result is not a clean terminal cursor.",
            "transport_calls": 1,
            "attempt_consumed": True,
            "not_a_live_dispatch": True,
            "draft_enabled": False,
            "PRODUCT_READY": False,
            "serialized": serialized,
            "state": current,
        }
    next_token = result.get("pagination_token") or result.get("paginationToken")
    response_id = _mint_response_id(draft, address, expected_cursor, attempt_seq, serialized)

    def _succeed(latest):
        continuation = dict(latest.get("accepted_continuation") or {})
        cursors = dict(latest.get("cursor_state") or {})
        if next_token:
            continuation[address] = next_token
            cursors[address] = "open"
        else:
            continuation[address] = EXHAUSTED_CURSOR
            cursors[address] = "exhausted"
        latest_attempts = list(latest.get("attempts") or [])
        if latest_attempts:
            latest_attempts[-1]["status"] = "succeeded"
            latest_attempts[-1]["response_id"] = response_id
        reqs = list(latest.get("requests") or [])
        if reqs:
            reqs[-1]["status"] = "succeeded"
            reqs[-1]["response_id"] = response_id
        latest.update({
            "attempts": latest_attempts,
            "requests": reqs,
            "accepted_continuation": continuation,
            "cursor_state": cursors,
            "last_dispatch": {
                "address": address,
                "response_id": response_id,
                "page_identity": expected_cursor,
                "next_token": next_token,
                "exhausted": not bool(next_token),
                "authorization_id": (draft or {}).get("authorization_id"),
                "attempt": attempt_seq,
            },
            "replay_receipts": [],
            "replay_completed": False,
        })

    current = _persist_after_transport(_succeed)
    return {
        "allowed": True,
        "dispatched": True,
        "synthetic_offline_only": True,
        "code": "synthetic_recorder_dispatch",
        "detail": "Synthetic offline authorization reached the recorder once. Not a live grant.",
        "transport_calls": 1,
        "attempt_consumed": True,
        "not_a_live_dispatch": True,
        "draft_enabled": False,
        "PRODUCT_READY": False,
        "serialized": serialized,
        "response_id": response_id,
        "state": current,
    }
