#!/usr/bin/env python3
"""Offline G3_INTEGRITY_REACQUIRE_RANK1 prep. Never dispatches live Helius/Birdeye."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner.mass_search.g3_reacquire import (
    ALLOWED_WALLET,
    GRANT_PATH,
    STOP_NO_SEGMENT,
    extract_signatures_from_sqlite,
    run_reacquire,
)
from scanner.storage import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "evidence" / "mass-wallet-funnel" / "g3-integrity-reacquire-rank1",
    )
    parser.add_argument("--live", action="store_true", help="Refused: this tool is offline-only")
    parser.add_argument("--extract-local-signatures", type=Path, default=None)
    parser.add_argument("--extract-out", type=Path, default=None)
    args = parser.parse_args()
    if args.live:
        print(json.dumps({
            "outcome_label": "G3_INTEGRITY_REACQUIRE_RANK1",
            "status": "BLOCKED",
            "blocker": "offline_tool_refuses_live",
            "detail": "tools/mass_search_g3_reacquire_offline.py never dispatches provider HTTP",
            "grant_path": str(GRANT_PATH.relative_to(ROOT)),
            "signature_manifest_status": STOP_NO_SEGMENT,
            "external_requests": 0,
            "PRODUCT_READY": False,
        }, indent=2))
        return 2
    if args.extract_local_signatures is not None:
        extracted = extract_signatures_from_sqlite(args.extract_local_signatures, address=ALLOWED_WALLET)
        if args.extract_out is not None:
            args.extract_out.parent.mkdir(parents=True, exist_ok=True)
            args.extract_out.write_text(json.dumps(extracted, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "outcome_label": "G3_INTEGRITY_REACQUIRE_RANK1",
            "status": extracted.get("status"),
            "blocker": extracted.get("blocker"),
            "detail": extracted.get("detail"),
            "page0_signature_count": len(extracted.get("pages", {}).get(0) or []),
            "page1_signature_count": len(extracted.get("pages", {}).get(1) or []),
            "external_requests": 0,
            "extract_out": str(args.extract_out) if args.extract_out else None,
            "PRODUCT_READY": False,
        }, indent=2))
        return 0 if extracted.get("status") == "LOCAL_SIGNATURES_RECOVERED" else 2
    if args.data_dir is None:
        parser.error("--data-dir is required unless --extract-local-signatures is set")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(args.data_dir)
    try:
        result = run_reacquire(store, evidence_dir=args.evidence, allow_live=False)
    finally:
        store.close()
    print(json.dumps({
        "outcome_label": result.get("outcome_label"),
        "status": result.get("status"),
        "authorization_id": result.get("authorization_id"),
        "grant_enabled": result.get("grant_enabled"),
        "freeze_verified": result.get("freeze_verified"),
        "signature_manifest_status": result.get("signature_manifest_status"),
        "original_segments_identified": result.get("original_segments_identified"),
        "page0_signature_count": result.get("page0_signature_count"),
        "page1_signature_count": result.get("page1_signature_count"),
        "stop_reason": result.get("stop_reason"),
        "external_requests": result.get("external_requests"),
        "arming_blockers": [row["code"] for row in result.get("arming_blockers") or []],
        "application_commit": result.get("application_commit"),
        "PRODUCT_READY": False,
    }, indent=2))
    return 0 if result.get("status") == "OFFLINE_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
