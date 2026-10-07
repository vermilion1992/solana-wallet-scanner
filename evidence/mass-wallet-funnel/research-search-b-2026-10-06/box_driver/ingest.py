#!/usr/bin/env python3
"""Offline ingest of research-search captures through the app replay path."""
import json
import sys
from pathlib import Path

REPO = Path(sys.argv[1] if len(sys.argv) > 1 else "/workspace")
DATA = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/research-search-b-appdata")
sys.path.insert(0, str(REPO))

from scanner.mass_search.capture_catalog import RESEARCH_SEARCH_MANIFEST, catalog_by_address
from scanner.mass_search.workflow import replay_captured_wallet
from scanner.storage import Store

manifest = json.loads(RESEARCH_SEARCH_MANIFEST.read_text())
order = []
seen = set()
for page in manifest["pages"].values():
    if page["address"] in seen:
        continue
    seen.add(page["address"])
    order.append(page["address"])
order.sort(key=lambda addr: catalog_by_address()[addr].get("provider_rank") or 999)

DATA.mkdir(parents=True, exist_ok=True)
store = Store(DATA)
results = {}
entries = {}
try:
    catalog = catalog_by_address()
    for addr in order:
        entry = catalog[addr]
        entries[addr] = {
            "address": addr,
            "authorization_id": entry.get("authorization_id"),
            "pages": entry.get("pages"),
            "windows": entry.get("windows"),
        }
        try:
            replayed = replay_captured_wallet(store, addr, force=True)
            results[addr] = {
                "report_id": replayed["report_id"],
                "visible_report": replayed.get("visible_report"),
            }
        except Exception as exc:
            import traceback
            tb = traceback.extract_tb(exc.__traceback__)
            results[addr] = {
                "error": f"{type(exc).__name__}: {exc}",
                "where": [f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}" for frame in tb[-4:]],
            }
finally:
    store.close()

out = Path(sys.argv[3] if len(sys.argv) > 3 else DATA / "INGEST_RESULT.json")
out.write_text(json.dumps({"entries": entries, "results": results}, indent=2, default=str) + "\n")
print(json.dumps(results, indent=1))
