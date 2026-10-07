#!/usr/bin/env python3
"""Run the authorised G1-only live vertical slice. No secrets in output."""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner.mass_search.live_g1 import GRANT_PATH, run_g1
from scanner.storage import Store


def application_sha():
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, default=ROOT / "evidence" / "mass-wallet-funnel")
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(args.data_dir)
    hardware = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
    }
    import asyncio
    result = asyncio.run(run_g1(
        store,
        evidence_dir=args.evidence,
        application_sha=application_sha(),
        hardware=hardware,
        grant_path=GRANT_PATH,
    ))
    print(json.dumps({
        "gate": result.get("gate"),
        "status": result.get("status"),
        "authorization_id": result.get("authorization_id"),
        "grant_path": result.get("grant_path"),
        "blocker": result.get("blocker"),
        "run_id": result.get("run_id"),
        "spend": result.get("spend"),
        "setup_pilot": result.get("setup_pilot") or result.get("setup_pilot_after"),
    }, indent=2))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
