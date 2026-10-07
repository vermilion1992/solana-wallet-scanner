#!/usr/bin/env python3
"""Offline RANKED_100_DISCOVERY_PILOT. Never dispatches live Birdeye/Helius."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner.mass_search.ranked100 import GRANT_PATH, run_ranked100_pilot
from scanner.storage import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, default=ROOT / "evidence" / "mass-wallet-funnel" / "ranked100-offline")
    parser.add_argument("--live", action="store_true", help="Refused: this tool is offline-only")
    args = parser.parse_args()
    if args.live:
        print(json.dumps({
            "outcome_label": "RANKED_100_DISCOVERY_PILOT",
            "status": "BLOCKED",
            "blocker": "offline_tool_refuses_live",
            "detail": "tools/mass_search_ranked100_offline.py never dispatches provider HTTP",
            "grant_path": str(GRANT_PATH.relative_to(ROOT)),
            "PRODUCT_READY": False,
        }, indent=2))
        return 2
    args.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(args.data_dir)
    try:
        result = run_ranked100_pilot(store, evidence_dir=args.evidence, allow_live=False)
    finally:
        store.close()
    print(json.dumps({
        "outcome_label": result.get("outcome_label"),
        "status": result.get("status"),
        "authorization_id": result.get("authorization_id"),
        "grant_enabled": result.get("grant_enabled"),
        "from_cache": result.get("from_cache"),
        "external_requests": result.get("external_requests"),
        "unique_valid_wallets": (result.get("cache") or {}).get("unique_valid_wallets"),
        "acquisition_complete": (result.get("cache") or {}).get("acquisition_complete"),
        "shortlist_count": result.get("shortlist_count"),
        "arming_blockers": [row["code"] for row in result.get("arming_blockers") or []],
        "birdeye_requests_used": result.get("birdeye_requests_used"),
        "PRODUCT_READY": False,
    }, indent=2))
    return 0 if result.get("status") == "OFFLINE_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
