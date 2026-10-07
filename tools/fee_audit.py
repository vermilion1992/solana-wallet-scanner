#!/usr/bin/env python3
"""Offline fee audit for gtfo and CccS largest charges (Mitch item 8)."""
from __future__ import annotations

import gzip
import json
import tempfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

from scanner.compiled_instructions import CompiledInstructionError, normalize_instruction, SYSTEM_ID
from scanner.mass_search.capture_catalog import catalog_by_address, load_capture_records
from scanner.mass_search.verified_costs import is_verified_tip_account, published_tip_lookup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage/FEE_AUDIT.json"
CCCS_OUT = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage/CCCS_DEBIT_AUDIT.json"
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
        failed = meta.get("err") is not None
        if fee and payer == address:
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
                "transaction_failed": failed,
                "executed": True,
            })
        if failed:
            # Failed transactions execute only the network fee. System transfers
            # and tips in the instruction list did not move.
            continue
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
            meta = published_tip_lookup(dest) or {}
            charges.append({
                "signature": signature,
                "recipient": dest,
                "instruction_path": path,
                "fee_payer": payer,
                "lamports": lamports,
                "sol": str(Decimal(lamports) / Decimal(1_000_000_000)),
                "economic_role": "verified_tip" if verified else "unresolved_debit_not_a_tip",
                "counted_elsewhere": bool(verified),
                "counted_elsewhere_as": "verified_tips_sol" if verified else None,
                "verified_tip": verified,
                "provider": meta.get("provider"),
                "source": meta.get("source"),
                "transaction_failed": False,
                "executed": True,
            })
    charges.sort(key=lambda item: item["lamports"], reverse=True)
    verified = sum(item["lamports"] for item in charges if item["verified_tip"])
    unresolved = sum(item["lamports"] for item in charges if item["economic_role"] == "unresolved_debit_not_a_tip")
    network = sum(item["lamports"] for item in charges if item["economic_role"] == "network_plus_priority_fee")
    large = [item for item in charges if item["economic_role"] != "network_plus_priority_fee" and Decimal(item["sol"]) > Decimal("0.01")]
    return {
        "address": address,
        "largest_charges": charges[:15],
        "debits_gt_0_01_sol": large,
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
        "note": (
            "Net P&L uses verified costs only: wallet-paid network fees (including "
            "failed transactions), published-list tips (including tips in separate "
            "successful transactions), and proven router or platform fees even when "
            "the recipient is not a tip account. Unexplained transfers stay in "
            "sensitivity and are never called fees. Failed-tx transfers are excluded."
        ),
    }


def _debit_row(item):
    return {
        "signature": item.get("signature"),
        "recipient": item.get("recipient"),
        "sol": item.get("sol"),
        "classification": item.get("economic_role"),
        "provider": item.get("provider"),
        "source": item.get("source"),
        "instruction_path": item.get("instruction_path"),
        "fee_payer": item.get("fee_payer"),
        "counted_elsewhere": item.get("counted_elsewhere"),
        "counted_elsewhere_as": item.get("counted_elsewhere_as"),
        "transaction_failed": item.get("transaction_failed"),
        "executed": item.get("executed"),
    }


def current_cccs_figures_from_captures():
    """Replay CccS captures. Do not copy scoped net or sensitivity from a prior file."""
    from scanner.mass_search.workflow import replay_captured_wallet
    from scanner.storage import Store

    address = "CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU"
    tmp = Path(tempfile.mkdtemp(prefix="cccs-current-"))
    store = Store(tmp / address)
    try:
        result = replay_captured_wallet(store, address, force=True)
        report = result["report"]
        profile = report.get("research_profile") or {}
        scoped = profile.get("scoped_pnl")
        if scoped in (None, ""):
            raise ValueError("CccS scoped net missing from capture replay")
        sensitivity = report.get("sensitivity_unverified_debits_sol")
        if sensitivity in (None, ""):
            raise ValueError("CccS swap-adjacent sensitivity missing from capture replay")
        return str(scoped), str(sensitivity)
    finally:
        store.close()


def write_cccs_debit_audit(payload):
    """Regenerate CccS debit rows and full-wallet totals from executed charges only."""
    cccs = payload["wallets"]["CccS"]
    gtfo = payload["wallets"]["gtfo"]
    existing = {}
    if CCCS_OUT.is_file():
        existing = json.loads(CCCS_OUT.read_text(encoding="utf-8"))
    bridge = existing.get("run39_to_current_bridge")
    scoped_net, swap_adjacent = current_cccs_figures_from_captures()
    body = {
        "kind": "cccs-debit-audit-v1",
        "earlier_fees_plus_tips_sol": existing.get("earlier_fees_plus_tips_sol", "0.134"),
        "aa2ef2d_unverified_outside_debits_sol": existing.get("aa2ef2d_unverified_outside_debits_sol", "1.428081532"),
        "aa2ef2d_scoped_net_sol": existing.get("aa2ef2d_scoped_net_sol", "0.242261753"),
        "current_scoped_net_sol": scoped_net,
        "current_swap_adjacent_sensitivity_sol": swap_adjacent,
        "current_full_wallet_unresolved_sol": cccs["totals_sol"]["unresolved_debits_sensitivity"],
        "current_full_wallet_verified_tips_sol": cccs["totals_sol"]["verified_tips"],
        "current_full_wallet_network_plus_priority_sol": cccs["totals_sol"]["network_plus_priority"],
        "why_0_134_became_1_428": existing.get("why_0_134_became_1_428"),
        "why_figures_changed_again_after_published_lists": existing.get("why_figures_changed_again_after_published_lists"),
        "failed_transactions_excluded": (
            "Failed transactions contribute only meta.fee. Transfers in those "
            "transactions did not execute and are omitted from verified tips and unresolved debits."
        ),
        "debits_gt_0_01_sol": [_debit_row(item) for item in cccs["debits_gt_0_01_sol"]],
        "gtfo_totals_sol": gtfo["totals_sol"],
        "PRODUCT_READY": False,
        "run39_to_current_bridge": bridge,
    }
    CCCS_OUT.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return body


def main():
    payload = {
        "kind": "fee-audit-v1",
        "note": (
            "Failed transactions contribute only the network fee. "
            "System transfers in those transactions did not execute."
        ),
        "wallets": {label: audit_wallet(address) for address, label in WALLETS.items()},
        "PRODUCT_READY": False,
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    cccs = write_cccs_debit_audit(payload)
    print(json.dumps({
        "fee_audit": {label: row["totals_sol"] for label, row in payload["wallets"].items()},
        "cccs_debit_rows": len(cccs["debits_gt_0_01_sol"]),
        "gtfo_totals_sol": cccs["gtfo_totals_sol"],
    }, indent=2))


if __name__ == "__main__":
    main()
