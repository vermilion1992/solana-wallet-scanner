#!/usr/bin/env python3
"""Secure-box live entry for G3_INTEGRITY_REACQUIRE_RANK1.

Refuses leftover G3 grants. Refuses the committed disabled template as a live
grant. Refuses dispatch while signature manifests are STOP_NO_SEGMENT. Does not
print secrets. Cloud agents must not run this against Helius.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner.mass_search.g3_reacquire import (
    AUTHORIZATION_ID,
    GRANT_PATH,
    STOP_NO_SEGMENT,
    load_reacquire_grant,
    run_reacquire,
)
from scanner.storage import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--grant", type=Path, required=True, help="Local uncommitted armed grant copy")
    parser.add_argument(
        "--evidence",
        type=Path,
        default=ROOT / "evidence" / "mass-wallet-funnel" / "g3-integrity-reacquire-rank1-live",
    )
    parser.add_argument("--overlay", type=Path, default=None, help="Optional local signature overlay JSON")
    args = parser.parse_args()
    grant_path = args.grant.resolve()
    if grant_path == GRANT_PATH.resolve():
        print(json.dumps({
            "outcome_label": "G3_INTEGRITY_REACQUIRE_RANK1",
            "status": "BLOCKED",
            "blocker": "repo_template_must_stay_disabled",
            "detail": "Do not arm config/live_authorization.g3-integrity-reacquire-rank1-draft.json in git. Copy it locally on the secure box.",
            "external_requests": 0,
            "PRODUCT_READY": False,
        }, indent=2))
        return 2
    try:
        grant = load_reacquire_grant(grant_path)
    except ValueError as error:
        print(json.dumps({
            "outcome_label": "G3_INTEGRITY_REACQUIRE_RANK1",
            "status": "BLOCKED",
            "blocker": "grant_rejected",
            "detail": str(error),
            "external_requests": 0,
            "PRODUCT_READY": False,
        }, indent=2))
        return 2
    if grant.get("authorization_id") != AUTHORIZATION_ID:
        print(json.dumps({
            "outcome_label": "G3_INTEGRITY_REACQUIRE_RANK1",
            "status": "BLOCKED",
            "blocker": "unexpected_authorization_id",
            "external_requests": 0,
            "PRODUCT_READY": False,
        }, indent=2))
        return 2
    args.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(args.data_dir)
    try:
        result = run_reacquire(
            store,
            allow_live=True,
            grant=grant,
            overlay_path=args.overlay,
            evidence_dir=args.evidence,
            credentials={"helius": bool(os.environ.get("HELIUS_API_KEY") or os.environ.get("HELIUS_KEY"))},
            attach_live_http=True,
        )
    finally:
        store.close()
    print(json.dumps({
        "outcome_label": result.get("outcome_label"),
        "status": result.get("status"),
        "authorization_id": result.get("authorization_id"),
        "blocker": result.get("blocker"),
        "stop_reason": result.get("stop_reason"),
        "detail": result.get("detail"),
        "signature_manifest_status": result.get("signature_manifest_status"),
        "original_segments_identified": result.get("original_segments_identified"),
        "page0_signature_count": result.get("page0_signature_count"),
        "page1_signature_count": result.get("page1_signature_count"),
        "external_requests": result.get("external_requests"),
        "helius_requests_used": result.get("helius_requests_used"),
        "arming_blockers": [row["code"] for row in result.get("arming_blockers") or []],
        "application_commit": result.get("application_commit"),
        "PRODUCT_READY": False,
        "note": (
            "STOP_NO_SEGMENT means do not dispatch. Recover original signatures from the "
            "box-local G3 sqlite first via the offline extractor; do not fetch current history."
        ) if result.get("blocker") == STOP_NO_SEGMENT else None,
    }, indent=2))
    return 0 if result.get("status") not in {"BLOCKED", None} else 2


if __name__ == "__main__":
    raise SystemExit(main())
