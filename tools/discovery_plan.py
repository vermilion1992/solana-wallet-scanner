#!/usr/bin/env python3
"""Inspect evidence-linked candidate priorities from a local cache; no network."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner.discovery import plan_candidate_audits
from scanner.config import STRICT
from scanner.report_view import summary_inputs
from scanner.storage import Store


class ReadOnlyStore:
    """Read existing records/archives without launching workers or credentials."""

    def __init__(self, directory):
        self.path = Path(directory).resolve(strict=True)
        database = self.path / "scanner.sqlite"
        if not database.is_file():
            raise ValueError("The supplied directory has no scanner database.")
        self.db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA query_only=ON")
        self.lock = threading.RLock()

    def get(self, kind, identifier, default=None):
        row = self.db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, identifier)).fetchone()
        return json.loads(row[0]) if row else default

    def evidence(self, digest):
        return Store.evidence(self, digest)

    def close(self):
        self.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--cohort-id", required=True)
    parser.add_argument("--audit-cap", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    store = ReadOnlyStore(args.data_dir)
    try:
        cohort = store.get("discovery_cohorts", args.cohort_id)
        if not cohort:
            raise ValueError("Saved discovery cohort was not found.")
        settings = store.get("configuration", "settings", {})
        cap = settings.get("limits", {}).get("deep_audit_cap", 5)
        if args.audit_cap is not None:
            if args.audit_cap > cap:
                raise ValueError("Requested audit cap exceeds the configured workload limit.")
            cap = args.audit_cap
        plan = plan_candidate_audits(store, cohort, reports=summary_inputs(store),
                                     preset=store.get("configuration", "preset", dict(STRICT)), audit_cap=cap)
        text = json.dumps(plan, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    finally:
        store.close()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            stream.write(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
