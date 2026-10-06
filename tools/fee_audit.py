#!/usr/bin/env python3
"""Offline fee audit for gtfo and CccS largest charges (Mitch item 8)."""
from __future__ import annotations

import gzip
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from scanner.compiled_instructions import CompiledInstructionError, normalize_instruction, SYSTEM_ID
from scanner.mass_search.capture_catalog import catalog_by_address, load_capture_records
from scanner.mass_search.verified_costs import is_verified_tip_account

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage/FEE_AUDIT.json"
WALLETS = {
    "gtfoTELAeEZHUgHetA6umfsCETiBMzJCN4tB2sqCgFL": "gtfo",
    "CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU": "CccS",
}


def _keys(raw):
    message = (raw.get("transaction") or {}).get("message") or {}
    meta = raw.get("meta") or {}
    entries = message.get("accountKeys") or []
    keys = [item.get("pubkey") if isinstance(item, dict) else item for item in entries]
    loaded = meta.get("loadedAddresses") or {}
    return keys + list(loaded.get("writable") or []) + list(loaded.get("readonly") or [])


def audit_wallet(address):
    entry = catalog_by_address()[address]
    records, _ = load_capture_records(entry)
    charges = []
    for record in records:
        raw = record.get("result") if isinstance(record.get("result"), dict) else record
        if not isinstance(raw, dict):
            continue
        meta = raw.get("meta") or {}
        keys = _keys(raw)
        signature = record.get("signature") or ((raw.get("transaction") or {}).get("signatures") or [None])[0]
        fee = meta.get("fee") if isinstance(meta.get("fee"), int) else 0
        payer = keys[0] if keys else None
        if fee:
            charges.append({
                "signature": signature,
                "recipient": "network_fee_burn",
                "instruction_path": "meta.fee",
                "fee_payer": payer,
                "lamports": fee,
                "sol": str(Decimal(fee) / Decimal(1_000_000_000)),
                "economic_role": "network_plus_priority_fee",
                "counted_elsewhere": False,
                "verified_tip": False,
            })
        message = (raw.get("transaction") or {}).get("message") or {}
        instructions = list(message.get("instructions") or [])
        paths = [f"transaction.message.instructions.{index}" for index in range(len(instructions))]
        for group in (meta.get("innerInstructions") or []):
            if not isinstance(group, dict):
                continue
            outer = group.get("index")
            for inner_index, instruction in enumerate(group.get("instructions") or []):
                instructions.append(instruction)
                paths.append(f"meta.innerInstructions.{outer}.{inner_index}")
        for path, instruction in zip(paths, instructions):
            if not isinstance(instruction, dict):
                continue
            parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else None
            if parsed is None and instruction.get("data") is not None:
                program = instruction.get("programId")
                index = instruction.get("programIdIndex")
                if program is None and isinstance(index, int) and 0 <= index < len(keys):
                    program = keys[index]
                if program == SYSTEM_ID or instruction.get("program") == "system":
                    try:
                        viewed = normalize_instruction(instruction, keys, inner=path.startswith("meta.inner"), path=path, signers={keys[0]} if keys else set())
                        parsed = viewed["instruction"].get("parsed")
                    except (CompiledInstructionError, ValueError, KeyError, IndexError, TypeError):
                        parsed = None
            info = parsed.get("info") if isinstance(parsed, dict) else None
            if not isinstance(info, dict) or parsed.get("type") != "transfer":
                continue
            if info.get("source") != address:
                continue
            dest = info.get("destination")
            lamports = info.get("lamports")
            if not isinstance(lamports, int):
                continue
            verified = is_verified_tip_account(dest)
            charges.append({
                "signature": signature,
                "recipient": dest,
                "instruction_path": path,
                "fee_payer": payer,
                "lamports": lamports,
                "sol": str(Decimal(lamports) / Decimal(1_000_000_000)),
                "economic_role": "verified_tip" if verified else "unresolved_debit_not_a_tip",
                "counted_elsewhere": verified,
                "verified_tip": verified,
            })
    charges.sort(key=lambda item: item["lamports"], reverse=True)
    verified = sum(item["lamports"] for item in charges if item["verified_tip"])
    unresolved = sum(item["lamports"] for item in charges if item["economic_role"] == "unresolved_debit_not_a_tip")
    network = sum(item["lamports"] for item in charges if item["economic_role"] == "network_plus_priority_fee")
    return {
        "address": address,
        "largest_charges": charges[:15],
        "totals_lamports": {
            "network_plus_priority": network,
            "verified_tips": verified,
            "unresolved_debits_sensitivity": unresolved,
        },
        "totals_sol": {
            "network_plus_priority": str(Decimal(network) / Decimal(1_000_000_000)),
            "verified_tips": str(Decimal(verified) / Decimal(1_000_000_000)),
            "unresolved_debits_sensitivity": str(Decimal(unresolved) / Decimal(1_000_000_000)),
        },
        "note": "Net P&L uses verified costs only. Unresolved debits are a labelled sensitivity figure.",
    }


def main():
    payload = {
        "kind": "fee-audit-v1",
        "wallets": {label: audit_wallet(address) for address, label in WALLETS.items()},
        "PRODUCT_READY": False,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({label: row["totals_sol"] for label, row in payload["wallets"].items()}, indent=2))


if __name__ == "__main__":
    main()
