#!/usr/bin/env python3
"""Offline G3_RANKED100_HISTORY prep. Never dispatches live Helius/Birdeye."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner.mass_search.g3_history import GRANT_PATH, run_g3_history
from scanner.storage import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, default=ROOT / "evidence" / "mass-wallet-funnel" / "g3-ranked100-history-offline")
    parser.add_argument("--live", action="store_true", help="Refused: this tool is offline-only")
    args = parser.parse_args()
    if args.live:
        print(json.dumps({
            "outcome_label": "G3_RANKED100_HISTORY",
            "status": "BLOCKED",
            "blocker": "offline_tool_refuses_live",
            "detail": "tools/mass_search_g3_ranked100_offline.py never dispatches provider HTTP",
            "grant_path": str(GRANT_PATH.relative_to(ROOT)),
            "PRODUCT_READY": False,
        }, indent=2))
        return 2
    args.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(args.data_dir)
    try:
        result = run_g3_history(store, evidence_dir=args.evidence, allow_live=False)
    finally:
        store.close()
    print(json.dumps({
        "outcome_label": result.get("outcome_label"),
        "status": result.get("status"),
        "authorization_id": result.get("authorization_id"),
        "grant_enabled": result.get("grant_enabled"),
        "freeze_verified": result.get("freeze_verified"),
        "external_requests": result.get("external_requests"),
        "arming_blockers": [row["code"] for row in result.get("arming_blockers") or []],
        "initial_addresses": result.get("initial_addresses"),
        "reserve_addresses": result.get("reserve_addresses"),
        "helius_requests_used": result.get("helius_requests_used"),
        "PRODUCT_READY": False,
    }, indent=2))
    return 0 if result.get("status") == "OFFLINE_PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
