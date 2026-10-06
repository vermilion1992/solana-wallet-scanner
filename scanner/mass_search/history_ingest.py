"""Shared historical ingest: anchored requests, persist-then-quarantine, reports.

Not a milestone runner. Callers stay on the existing application path:
request construction → credential-free source persist → signature check →
authorised v2 cache → decoder → accounting → MassSearchService.reconstruct_candidate.
"""
from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from datetime import datetime
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
    """Did the previous page resolve or approach a named sale/lot?"""
    named_items = list((wallet_entry or {}).get("named_dependency_items") or [])
    observations = list((previous_page_result or {}).get("named_dependency_observations") or [])
    if (previous_page_result or {}).get("wallet_turned_positive"):
        return {
            "progress": False,
            "approached": False,
            "resolved": False,
            "reason": "wallet_turned_positive_is_not_progress",
            **NAMED_DEPENDENCY_PROGRESS,
        }
    if not named_items:
        named_text = (wallet_entry or {}).get("named_dependency")
        if named_text and (previous_page_result or {}).get("approached_named_dependency") is True:
            return {
                "progress": True,
                "approached": True,
                "resolved": bool((previous_page_result or {}).get("resolved_named_dependency")),
                "reason": "operator_recorded_named_item_observation",
                **NAMED_DEPENDENCY_PROGRESS,
            }
        return {
            "progress": False,
            "approached": False,
            "resolved": False,
            "reason": "no_named_sale_or_lot_recorded",
            **NAMED_DEPENDENCY_PROGRESS,
        }
    matched = []
    for item in named_items:
        key = item.get("signature") or item.get("mint")
        for row in observations:
            if key and key in {row.get("signature"), row.get("mint")}:
                if row.get("result") in NAMED_DEPENDENCY_PROGRESS["measurable_progress"] or row.get(
                    "unresolved_basis_cleared"
                ) or row.get("classified_cost_role"):
                    matched.append(row)
    return {
        "progress": bool(matched),
        "approached": bool(matched),
        "resolved": any(row.get("unresolved_basis_cleared") for row in matched),
        "reason": "named_sale_or_lot_observed" if matched else "named_sale_or_lot_not_observed",
        "matched": matched,
        **NAMED_DEPENDENCY_PROGRESS,
    }


def evaluate_next_capture_dispatch(
    *,
    draft,
    requested,
    grant=None,
    replay_completed=False,
    previous_progress=None,
    requests_used=0,
    per_wallet_used=None,
    fake_transport=None,
):
    """Offline dispatch boundary. Never invokes a network transport.

    A later live approval must bind this draft's execution artifact, current
    remaining quota, overages_disabled, approval time, and expiry. This
    function does not invent that grant.
    """
    del fake_transport  # callers may pass a recorder; this path never calls it
    per_wallet_used = per_wallet_used or {}
    address = (requested or {}).get("address")
    phase = (requested or {}).get("phase")
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

    def refuse(code, detail):
        return {
            "allowed": False,
            "dispatched": False,
            "code": code,
            "detail": detail,
            "not_a_dispatched_request": True,
            "draft_enabled": bool((draft or {}).get("enabled")),
            "PRODUCT_READY": False,
        }

    if (draft or {}).get("enabled") is not False:
        return refuse("draft_must_stay_disabled", "Repo next-capture draft must stay enabled:false")
    if grant:
        if grant.get("enabled") is True:
            return refuse("grant_enabled", "This evaluator never arms a live grant")
        if grant.get("consumed") or grant.get("status") == "consumed":
            return refuse("consumed_grant", "Authorization already consumed")
        if grant.get("authorization_id") in NEXT_CAPTURE_WRONG_KIND:
            return refuse("wrong_kind_grant", "g1/other consumed grants are not permission for this capture")
        if grant.get("authorization_id") != (draft or {}).get("authorization_id"):
            return refuse("wrong_kind_grant", "Grant authorization_id is not this draft")
    if address in excluded:
        return refuse("excluded_wallet", excluded.get(address) or "wallet excluded from this draft")
    if wallet is None:
        return refuse("wrong_wallet", "Address is not in allowed_wallets")
    if cutoff not in (None, expected_cutoff) and int(cutoff) != int(expected_cutoff):
        return refuse("wrong_cutoff", f"blockTime.lt must be {expected_cutoff}")
    expected_cursor = wallet.get("continue_from_pagination_token")
    if cursor and expected_cursor and cursor != expected_cursor and int(per_wallet_used.get(address) or 0) == 0:
        return refuse("wrong_cursor", "paginationToken is not the frozen continuation for this wallet")
    if int(phase or 0) >= 2 and not replay_completed:
        return refuse("phase_two_before_replay", "Phase two requires offline replay of phase one")
    if int(requests_used or 0) >= usable_ceiling:
        return refuse("over_budget", "Reserved 12 cannot become discretionary spend or override the usable ceiling")
    if int(per_wallet_used.get(address) or 0) >= wallet_cap:
        return refuse("per_wallet_limit", "Reserved budget cannot override a stricter per-wallet limit")
    if wallet.get("decoder_first") or int(wallet.get("initial_pages") or 0) == 0:
        recorded = bool(wallet.get("named_dependency_items")) or bool(wallet.get("specific_dependency_recorded"))
        if not recorded:
            return refuse(
                "zero_executable_allowance",
                "58PW-style decoder-first wallets have zero executable pages until a specific named sale/lot is recorded",
            )
    if int(phase or 1) >= 2 and address.startswith("A6PS"):
        if not replay_completed:
            return refuse("phase_two_before_replay", "A6PS is separately justified but still requires replay")
        # A6PS does not require gtfo's opening-basis dependency. It still shares
        # the global ceiling and must not skip replay.
    elif int(phase or 1) >= 2:
        progressed = named_dependency_progress(previous_progress, wallet)
        phase1 = next((row for row in allowed if row.get("phase") == 1), None)
        if not progressed.get("progress"):
            gtfo_progress = named_dependency_progress(previous_progress, phase1 or {})
            if not gtfo_progress.get("progress"):
                return refuse(
                    "named_dependency_not_approached",
                    "Further pages require an observable result on a named sale/lot before another page",
                )
    if requested.get("continue_because_positive") or requested.get("stop_because_positive"):
        return refuse("outcome_driven", "Never stop or continue because a wallet turned positive")
    return {
        "allowed": True,
        "dispatched": False,
        "code": "would_serialize_only",
        "detail": "Boundary passed. Draft stays enabled:false; this is not a live dispatch.",
        "not_a_dispatched_request": True,
        "draft_enabled": False,
        "PRODUCT_READY": False,
        "fresh_approval_must_bind": [
            "execution_artifact_hash_of_this_draft",
            "current_remaining_quota_confirmation",
            "overages_enabled=false",
            "approval_timestamp",
            "expiry",
        ],
    }
