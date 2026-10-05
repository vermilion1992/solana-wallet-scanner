"""Shared historical ingest: anchored requests, persist-then-quarantine, reports.

Not a milestone runner. Callers stay on the existing application path:
request construction → credential-free source persist → signature check →
authorised v2 cache → decoder → accounting → MassSearchService.reconstruct_candidate.
"""
from __future__ import annotations

import json
from copy import deepcopy
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
from .live_g1 import _wrap_records, independent_fifo_worksheet
from .service import MassSearchService

HELIUS_METHOD = "getTransactionsForAddress"
HELIUS_ENDPOINT = "https://mainnet.helius-rpc.com/"
CACHE_KIND = "mass_search_cache"
SOURCE_CAPTURE_KIND = "mass_search_source_capture"
QUARANTINE_KIND = "mass_search_source_quarantine"

HISTORICAL_ANCHOR_REQUIRED = "HISTORICAL_ANCHOR_REQUIRED"
SIGNATURE_MISMATCH = "SIGNATURE_MISMATCH"
UNSUPPORTED_UNTIL = "UNSUPPORTED_UNTIL"
HISTORICAL_ANCHOR_KEYS = frozenset({"paginationToken"})

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
            "Top-level until is not a documented getTransactionsForAddress bound; use filters.signature.lte",
        )
    return True


def _base_gta_options(options):
    """Strip paginationToken and documented signature bound for encoding compare."""
    compare = {k: v for k, v in (options or {}).items() if k not in HISTORICAL_ANCHOR_KEYS}
    filters = dict(compare.get("filters") or {})
    filters.pop("signature", None)
    compare["filters"] = filters
    return compare


def assert_gta_options_not_widened(options):
    """Frozen GTA encoding plus paginationToken and filters.signature.lte only."""
    assert_no_unsupported_until(options)
    compare = _base_gta_options(options)
    if compare != EXACT_HELIUS_OPTIONS:
        raise SourceError("UNAUTHORIZED", "Query options drifted from the frozen GTA encoding")
    extra = set((options or {}).keys()) - set(EXACT_HELIUS_OPTIONS) - HISTORICAL_ANCHOR_KEYS
    if extra:
        raise SourceError("UNAUTHORIZED", "Query widening is forbidden")
    filters = (options or {}).get("filters") if isinstance((options or {}).get("filters"), dict) else {}
    extra_filters = set(filters) - {"status", "tokenAccounts", "signature"}
    if extra_filters:
        raise SourceError("UNAUTHORIZED", "Query widening is forbidden")
    bound = filters.get("signature")
    if bound is not None:
        if not isinstance(bound, dict) or set(bound) != {"lte"} or not isinstance(bound.get("lte"), str) or not bound.get("lte"):
            raise SourceError("UNAUTHORIZED", "filters.signature must be {lte: <signature>}")
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
    return {
        "method": HELIUS_METHOD,
        "sort_order": (options or {}).get("sortOrder"),
        "inclusive_newest_signature": bound,
        "boundary_inclusive": True if bound else None,
        "continuation_token": token,
        "is_unanchored_newest_first": (options or {}).get("sortOrder") == "desc" and not bound and not token,
        "until_present": isinstance(options, dict) and "until" in options,
        "server_behaviour_not_proven": True,
        "note": (
            "filters.signature.lte is the documented inclusive newest-signature bound. "
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
):
    """Construct a GTA page. Historical page 0 uses filters.signature.lte, not until."""
    if until is not None:
        raise SourceError(
            UNSUPPORTED_UNTIL,
            "Top-level until is not a documented getTransactionsForAddress bound; use filters.signature.lte",
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
                "Later pages use the frozen paginationToken. Top-level until is rejected."
            ),
        },
        "PRODUCT_READY": False,
        "not_a_dispatched_request": True,
        "not_a_guarantee_of_exact_signature_match": True,
    }


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
    production_total = Decimal(str(production["total_profit_sol"]))
    independent_total = Decimal(str(independent["total_profit_sol"]))
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
    decoded = decode_supported_swaps(_wrap_records(sanitized["records"]), address)
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
            worksheet = independent_fifo_worksheet(events) if events else None
        except ValueError:
            worksheet = None
    else:
        events = declared_subset_events(by_mint)
        report_mint = "declared-supported-subset"
        from .g3_history import declared_subset_worksheet
        worksheet = declared_subset_worksheet(by_mint)
    if not events:
        return {
            "run_id": run["run_id"],
            "report_id": None,
            "report": None,
            "worksheet": worksheet,
            "visible_report": False,
            "external_requests": 0,
            "truncated_before_acquisition_support": truncated,
            "PRODUCT_READY": False,
        }
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
    report["offline_replay"] = True
    report["PRODUCT_READY"] = False
    report["not_ranked_wallet_pipeline_proof"] = True
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
            completed_positions=1 if (production or worksheet) else 0,
        ),
        "external_requests": 0,
        "truncated_before_acquisition_support": truncated,
        "PRODUCT_READY": False,
        "not_match": True,
    }
