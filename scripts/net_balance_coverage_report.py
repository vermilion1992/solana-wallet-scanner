#!/usr/bin/env python3
"""Offline coverage before/after the net-balance fallback. No provider HTTP."""
from __future__ import annotations

import gzip
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner.investigation import (  # noqa: E402
    JUPITER,
    RAYDIUM_AMM,
    RAYDIUM_CLMM,
    WHIRLPOOL,
    decode_supported_swaps,
)
from scanner.mass_search.canonical_records import (  # noqa: E402
    canonical_decode_records,
    unwrap_gta_record,
)

PROGRAMS = {
    "jupiter_v6": JUPITER,
    "orca_whirlpool": WHIRLPOOL,
    "raydium_clmm": RAYDIUM_CLMM,
    "raydium_amm_v4": RAYDIUM_AMM,
}

DEFAULT_CORPORA = {
    "fixtures_live_raw": ROOT / "tests/fixtures/live-raw",
    "fixtures_phase3": ROOT / "tests/fixtures/live-e2e-phase3",
    "fixtures_f635a45": ROOT / "tests/fixtures/live-e2e-f635a45",
    "net_balance_venues": ROOT / "tests/fixtures/net-balance-venues",
    "research_search_b": ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06",
}


def _corpus_dirs():
    mapping = dict(DEFAULT_CORPORA)
    mapping["run_8b"] = Path(os.environ.get("LIVE_E2E_8B_DIR") or ROOT / "live-e2e-8b")
    mapping["run_10"] = Path(os.environ.get("LIVE_E2E_10_DIR") or ROOT / "live-e2e-10")
    return mapping


def _iter_records(path: Path):
    if not path.exists():
        return
    files = [path] if path.is_file() else [
        item for item in path.rglob("*")
        if item.is_file() and (
            item.suffix.lower() in {".json", ".bin", ".gz"}
            or item.name.endswith(".json.gz")
        )
    ]
    for file in files:
        try:
            raw = file.read_bytes()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            payload = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and payload.get("record"):
            yield payload.get("address"), unwrap_gta_record(payload["record"]) or payload["record"]
            continue
        body = payload.get("result") if isinstance(payload, dict) else None
        data = []
        if isinstance(body, dict):
            data = body.get("data") or []
        elif isinstance(body, list):
            data = body
        elif isinstance(payload, list):
            data = payload
        for item in data:
            if isinstance(item, dict) and (item.get("transaction") or item.get("raw")):
                yield None, unwrap_gta_record(item) or item


def _wallet(record, address):
    if address:
        return address
    message = ((record.get("transaction") or {}).get("message") or {})
    keys = []
    for key in message.get("accountKeys") or []:
        keys.append(key["pubkey"] if isinstance(key, dict) else key)
    return keys[0] if keys else None


def _programs(record):
    message = ((record.get("transaction") or {}).get("message") or {})
    keys = []
    for key in message.get("accountKeys") or []:
        keys.append(key["pubkey"] if isinstance(key, dict) else key)
    loaded = (record.get("meta") or {}).get("loadedAddresses") or {}
    keys.extend(loaded.get("writable") or [])
    keys.extend(loaded.get("readonly") or [])
    found = set()
    instructions = list(message.get("instructions") or [])
    for group in (record.get("meta") or {}).get("innerInstructions") or []:
        instructions.extend((group or {}).get("instructions") or [])
    for instruction in instructions:
        if not isinstance(instruction, dict):
            continue
        program = instruction.get("programId")
        if not program:
            index = instruction.get("programIdIndex")
            if isinstance(index, int) and 0 <= index < len(keys):
                program = keys[index]
        if program:
            found.add(program)
    return found


def _decoded(events):
    return [event for event in events or [] if event.get("kind") in {"buy", "sell", "conversion"}]


def measure_corpus(path: Path, limit=None):
    stats = {
        "present": path.exists(),
        "path": str(path),
        "transactions": 0,
        "before_decoded": 0,
        "after_decoded": 0,
        "by_program": {},
    }
    if not path.exists():
        return stats
    for name in PROGRAMS:
        stats["by_program"][name] = {
            "txs": 0,
            "before_decoded": 0,
            "after_decoded": 0,
        }
    counted = 0
    for address, record in _iter_records(path):
        if not isinstance(record, dict) or not record.get("transaction"):
            continue
        wallet = _wallet(record, address)
        if not wallet:
            continue
        if (record.get("meta") or {}).get("err") is not None:
            continue
        programs = _programs(record)
        counted += 1
        stats["transactions"] += 1
        before = decode_supported_swaps(
            canonical_decode_records([record]), wallet, allow_net_balance=False
        )
        after = decode_supported_swaps(
            canonical_decode_records([record]), wallet, allow_net_balance=True
        )
        before_ok = bool(_decoded(before.get("events")))
        after_ok = bool(_decoded(after.get("events")))
        if before_ok:
            stats["before_decoded"] += 1
        if after_ok:
            stats["after_decoded"] += 1
        for name, program in PROGRAMS.items():
            if program not in programs:
                continue
            row = stats["by_program"][name]
            row["txs"] += 1
            if before_ok:
                row["before_decoded"] += 1
            if after_ok:
                row["after_decoded"] += 1
        if limit and counted >= limit:
            break
    return stats


def report(limit=None):
    payload = {
        "kind": "net-balance-coverage-v1",
        "PRODUCT_READY": False,
        "note": (
            "Offline only. run_8b / run_10 populate when LIVE_E2E_8B_DIR / "
            "LIVE_E2E_10_DIR or live-e2e-8b / live-e2e-10 trees are present."
        ),
        "corpora": {},
    }
    for name, path in _corpus_dirs().items():
        payload["corpora"][name] = measure_corpus(path, limit=limit)
    return payload


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    payload = report(limit=limit)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
