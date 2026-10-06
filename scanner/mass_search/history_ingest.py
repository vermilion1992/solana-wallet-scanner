"""Shared historical ingest: anchored requests, persist-then-quarantine, reports.

Not a milestone runner. Callers stay on the existing application path:
request construction → credential-free source persist → signature check →
authorised v2 cache → decoder → accounting → MassSearchService.reconstruct_candidate.
"""
from __future__ import annotations

import json
from collections import Counter
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
    for event in decoded.get("events") or []:
        if event.get("kind") not in ("buy", "sell"):
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
            "explained by identified program-account funding, excluded from swap consideration"
        )
    sensitivity = Decimal("0")
    verified_tips = Decimal("0")
    for event in decoded.get("events") or []:
        if event.get("unverified_debits_sol") not in (None, ""):
            sensitivity += Decimal(str(event["unverified_debits_sol"]))
        if event.get("tips_sol") not in (None, ""):
            verified_tips += Decimal(str(event["tips_sol"]))
    report["verified_tips_sol"] = str(verified_tips)
    report["sensitivity_unverified_debits_sol"] = str(sensitivity)
    report["sensitivity_unverified_debits_note"] = (
        "Arbitrary outside SOL withdrawals are not tips. This labelled sensitivity "
        "figure is excluded from net P&L."
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
