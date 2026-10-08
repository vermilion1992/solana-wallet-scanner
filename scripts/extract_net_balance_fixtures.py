#!/usr/bin/env python3
"""Extract one compact real-tx fixture per reviewed swap program. Offline only."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner.investigation import (  # noqa: E402
    JUPITER,
    RAYDIUM_AMM,
    RAYDIUM_CLMM,
    WHIRLPOOL,
    decode_supported_swaps,
    net_balance_reviewed_swap,
)
from scanner.mass_search.canonical_records import (  # noqa: E402
    canonical_decode_records,
    unwrap_gta_record,
)
import tools.independent_episode_audit as auditor  # noqa: E402

TARGETS = {
    "jupiter_v6": JUPITER,
    "orca_whirlpool": WHIRLPOOL,
    "raydium_clmm": RAYDIUM_CLMM,
    "raydium_amm_v4": RAYDIUM_AMM,
}
OUT = ROOT / "tests/fixtures/net-balance-venues"


def _records_from_payload(payload):
    if isinstance(payload, dict) and payload.get("record"):
        address = payload.get("address")
        yield address, unwrap_gta_record(payload["record"]) or payload["record"]
        return
    if isinstance(payload, dict) and payload.get("transaction"):
        yield None, payload
        return
    body = payload.get("result") if isinstance(payload, dict) else None
    data = []
    if isinstance(body, dict):
        data = body.get("data") or []
    elif isinstance(body, list):
        data = body
    elif isinstance(payload, list):
        data = payload
    for item in data:
        if isinstance(item, dict):
            yield None, unwrap_gta_record(item) or item


def _wallet(record):
    message = ((record.get("transaction") or {}).get("message") or {})
    keys = message.get("accountKeys") or []
    header = message.get("header") or {}
    needed = header.get("numRequiredSignatures") or 1
    resolved = []
    for key in keys:
        resolved.append(key["pubkey"] if isinstance(key, dict) else key)
    if resolved:
        return resolved[0] if needed else resolved[0]
    return None


def _outer_programs(record):
    message = ((record.get("transaction") or {}).get("message") or {})
    keys = []
    for key in message.get("accountKeys") or []:
        keys.append(key["pubkey"] if isinstance(key, dict) else key)
    loaded = (record.get("meta") or {}).get("loadedAddresses") or {}
    keys.extend(loaded.get("writable") or [])
    keys.extend(loaded.get("readonly") or [])
    programs = []
    for ix in message.get("instructions") or []:
        if not isinstance(ix, dict):
            continue
        pid = ix.get("programId")
        if not pid:
            idx = ix.get("programIdIndex")
            if isinstance(idx, int) and 0 <= idx < len(keys):
                pid = keys[idx]
        if pid:
            programs.append(pid)
    return programs


B311 = "B3111yJCeHBcA1bizdJjUFPALfhAfSRnAbJzGUtnt56A"
PHOTON = "99vQwtBwYtrqqD9YSXbdum3KBdxPAVxYTaQ3cfnJSrN2"
UNREVIEWED_WRAPPERS = frozenset({B311, PHOTON})


def _has_outer_program(record, program):
    return program in set(_outer_programs(record))


def _iter_files():
    roots = [
        ROOT / "tests/fixtures/live-e2e-phase3",
        ROOT / "tests/fixtures/live-e2e-f635a45",
        ROOT / "tests/fixtures/live-raw",
        ROOT / "tests/fixtures/retained_protocol_funding",
        ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06",
        ROOT / "evidence/mass-wallet-funnel/live-e2e-proof-2026-10-07",
    ]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() in {".json", ".bin"} and path.is_file():
                yield path


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    found = {name: None for name in TARGETS}
    used_sigs = set()
    candidates = {name: [] for name in TARGETS}
    for path in _iter_files():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        for address, record in _records_from_payload(payload):
            if not isinstance(record, dict) or not record.get("transaction"):
                continue
            wallet = address or _wallet(record)
            if not wallet:
                continue
            signature = ((record.get("transaction") or {}).get("signatures") or [None])[0]
            if not signature or signature in used_sigs:
                continue
            outers = set(_outer_programs(record))
            if outers & UNREVIEWED_WRAPPERS:
                continue
            app = net_balance_reviewed_swap(record, wallet)
            aud = auditor.reconstruct_record(record, wallet)
            if not app or app.get("kind") not in {"buy", "sell", "conversion"}:
                continue
            if not aud or aud.get("kind") != app.get("kind") or aud.get("mint") != app.get("mint"):
                continue
            layout = decode_supported_swaps(
                canonical_decode_records([record]), wallet, allow_net_balance=False
            )
            layout_trades = [
                event for event in layout.get("events") or []
                if event.get("kind") in {"buy", "sell", "conversion"}
            ]
            for name, program in TARGETS.items():
                outer_hit = _has_outer_program(record, program)
                if not outer_hit and program not in set(_outer_programs(record)):
                    # Local corpora have no direct Whirlpool/CLMM/AMMv4 outers.
                    # Accept a hop under a reviewed outer when the net is clean.
                    keys = []
                    message = ((record.get("transaction") or {}).get("message") or {})
                    for key in message.get("accountKeys") or []:
                        keys.append(key["pubkey"] if isinstance(key, dict) else key)
                    loaded = (record.get("meta") or {}).get("loadedAddresses") or {}
                    keys.extend(loaded.get("writable") or [])
                    keys.extend(loaded.get("readonly") or [])
                    hop = False
                    for group in (record.get("meta") or {}).get("innerInstructions") or []:
                        for ix in (group or {}).get("instructions") or []:
                            if not isinstance(ix, dict):
                                continue
                            pid = ix.get("programId")
                            if not pid:
                                idx = ix.get("programIdIndex")
                                if isinstance(idx, int) and 0 <= idx < len(keys):
                                    pid = keys[idx]
                            if pid == program:
                                hop = True
                                break
                        if hop:
                            break
                    if not hop:
                        continue
                elif not outer_hit:
                    continue
                rank = 0 if outer_hit else 1
                if layout_trades:
                    rank += 5
                if app.get("kind") == "conversion":
                    rank += 2
                candidates[name].append((
                    rank,
                    {
                        "address": wallet,
                        "signature": signature,
                        "program": program,
                        "kind": app["kind"],
                        "mint": app["mint"],
                        "source_path": str(path.relative_to(ROOT)),
                        "record": record,
                    },
                ))
    for name in TARGETS:
        options = sorted(candidates[name], key=lambda item: item[0])
        for rank, payload in options:
            if payload["signature"] in used_sigs:
                continue
            found[name] = payload
            used_sigs.add(payload["signature"])
            break
    index = {}
    for name, payload in found.items():
        if not payload:
            print(f"MISSING {name}", file=sys.stderr)
            continue
        dest = OUT / f"{name}.json"
        dest.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        index[name] = {
            "file": dest.name,
            "address": payload["address"],
            "signature": payload["signature"],
            "program": payload["program"],
            "kind": payload["kind"],
            "mint": payload["mint"],
            "source_path": payload["source_path"],
        }
        print(f"WROTE {name} {payload['signature'][:12]} {payload['kind']}")
    (OUT / "INDEX.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return 0 if all(found.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
