"""Shared result-relevant coverage fixtures for offline tests.

A whole-span unsupported share is not a known denominator. Tests that
exercise lead machinery or coverage-status mapping must attach R with
the same numbers they already claimed, so the gate can see a versioned
set. Empty R still blocks.
"""
from __future__ import annotations

from decimal import Decimal

from scanner.mass_search.result_relevant_coverage import COVERAGE_GATE_VERSION


def result_relevant_shares(by_count="0", by_consideration=None, *, size=1):
    """Versioned R whose unsupported shares match the caller's whole-span claim."""
    consideration = dict(by_consideration or {"SOL": "0"})
    return {
        "version": COVERAGE_GATE_VERSION,
        "size": size,
        "denominator": size,
        "empty": False,
        "count_share": str(Decimal("1") - Decimal(str(by_count))),
        "value_share": str(min(Decimal("1") - Decimal(str(value)) for value in consideration.values())),
        "unsupported_swap_share": {
            "by_count": str(by_count),
            "by_consideration": {asset: str(share) for asset, share in consideration.items()},
        },
        "lineage_mints": [],
        "signatures": [f"rr-fixture-{index}" for index in range(size)],
        "gate_passed": False,
        "PRODUCT_READY": False,
    }


def attach_result_relevant(breakdown, *, by_count="0", by_consideration=None, size=1):
    """Copy unsupported shares onto result_relevant. Does not invent coverage."""
    row = dict(breakdown or {})
    shares = row.get("unsupported_swap_share_in_window") or {}
    count = shares.get("by_count", by_count)
    consideration = shares.get("by_consideration") or by_consideration or {"SOL": "0"}
    row["result_relevant"] = result_relevant_shares(count, consideration, size=size)
    return row
