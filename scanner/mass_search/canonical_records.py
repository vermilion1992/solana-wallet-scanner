"""One canonical decode-record contract for every historical ingest path.

GTA pages, archived SOURCE_RESPONSE captures, and already-wrapped decoder
records all become {signature, raw, evidence_hash, transaction_index?} once.
A second pass does not wrap again. Hashes, order, balances, inners and
failures stay on the raw body.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from scanner.investigation import (
    JUPITER,
    METEORA_DAMM_V2,
    PUMP,
    PUMP_SWAP,
    RAYDIUM_AMM,
    RAYDIUM_CPMM,
    RFQ_FILL,
    WHIRLPOOL,
    _anchor,
    _data,
    _keys,
    _program,
)

CANONICAL_KIND = "canonical-decode-record-v1"
PUMP_IDL_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "retained_protocol_funding"
    / "pump-native.json"
)
PUMP_IDL_PIN = {
    "repository": "pump-fun/pump-public-docs",
    "commit": "e0687ae9b7e064a0f54efc7297c65eecfbba3a8f",
    "document": "idl/pump.json",
    "local_fixture": "tests/fixtures/retained_protocol_funding/pump-native.json",
    "sha256": "ffe966c42f1af41652ee753fe2f1e3f7cd4077d7e6f49faf3138959c8b56064b",
}
PUMP_SWAP_INSTRUCTIONS = ("buy", "sell", "buy_exact_sol_in", "sell_v2", "buy_exact_quote_in_v2", "buy_v2")
JUPITER_REVIEWED = (
    "route",
    "route_with_token_ledger",
    "exact_out_route",
    "shared_accounts_route",
    "shared_accounts_route_with_token_ledger",
    "shared_accounts_exact_out_route",
    "route_v2",
    "shared_accounts_route_v2",
    "exact_out_route_v2",
    "shared_accounts_exact_out_route_v2",
)
PUMPSWAP_REVIEWED = ("buy", "sell", "buy_exact_quote_in")
DECODED_OUTER_PROGRAMS = {
    PUMP, PUMP_SWAP, JUPITER, RAYDIUM_CPMM, RAYDIUM_AMM, WHIRLPOOL,
    METEORA_DAMM_V2, RFQ_FILL,
}
LAMPORTS = Decimal(1_000_000_000)


def _pump_instruction_names():
    payload = json.loads(PUMP_IDL_PATH.read_text(encoding="utf-8"))
    return {bytes(item["discriminator"]).hex(): item["name"] for item in payload.get("instructions") or []}


def is_canonical_decode_record(item):
    if not isinstance(item, dict):
        return False
    raw = item.get("raw")
    return isinstance(raw, dict) and "transaction" in raw


def unwrap_gta_record(item):
    """Return the GTA/RPC transaction body. Does not invent fields."""
    if not isinstance(item, dict):
        return item
    if is_canonical_decode_record(item):
        return item["raw"]
    if "transaction" in item:
        return item
    raw = item.get("raw")
    if isinstance(raw, dict):
        result = raw.get("result")
        if isinstance(result, dict) and "transaction" in result:
            return result
        if "transaction" in raw:
            return raw
    result = item.get("result")
    if isinstance(result, dict) and "transaction" in result:
        return result
    return item


def gta_records_from_capture(payload):
    """Extract the GTA data list from a SOURCE_RESPONSE, JSON-RPC body, or list."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    records = payload.get("records")
    if isinstance(records, list) and records and isinstance(records[0], dict) and "transaction" in records[0]:
        return records
    body = payload.get("cleaned_body") if isinstance(payload.get("cleaned_body"), dict) else payload
    result = body.get("result") if isinstance(body, dict) else None
    if isinstance(result, dict) and isinstance(result.get("data"), list):
        return result["data"]
    if isinstance(result, list):
        return result
    if isinstance(records, list):
        return records
    return []


def _signature_of(raw, fallback=None):
    if isinstance(fallback, str) and fallback:
        return fallback
    if not isinstance(raw, dict):
        return None
    if isinstance(raw.get("signature"), str) and raw["signature"]:
        return raw["signature"]
    tx = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
    sigs = tx.get("signatures")
    if isinstance(sigs, list) and sigs and isinstance(sigs[0], str):
        return sigs[0]
    return None


def canonical_decode_records(records):
    """Normalise any mix of GTA bodies and wrapped records. No double-wrap."""
    wrapped = []
    for item in records or []:
        if is_canonical_decode_record(item):
            wrapped.append(item)
            continue
        raw = unwrap_gta_record(item)
        signature = None
        tx_index = None
        if isinstance(item, dict):
            signature = item.get("signature")
            tx_index = item.get("transaction_index")
        if isinstance(raw, dict):
            signature = _signature_of(raw, signature)
            if tx_index is None:
                tx_index = raw.get("transactionIndex")
        encoded = json.dumps(raw, sort_keys=True, separators=(",", ":"), default=str).encode()
        wrapped.append({
            "signature": signature,
            "raw": raw,
            "evidence_hash": hashlib.sha256(encoded).hexdigest(),
            "transaction_index": tx_index,
        })
    return wrapped


def _named_instruction(program, data, pump_names):
    try:
        payload = _data(data)
    except (ValueError, TypeError):
        return None
    disc = payload[:8].hex()
    if program == PUMP:
        return pump_names.get(disc) or disc
    if program == PUMP_SWAP:
        names = PUMPSWAP_REVIEWED
    elif program == JUPITER:
        names = JUPITER_REVIEWED
    elif program == PUMP:
        names = PUMP_SWAP_INSTRUCTIONS
    else:
        names = ()
    for name in names:
        if payload[:8] == _anchor(name):
            return name
    return disc


def classify_normalised_transaction(record, address, *, pump_names=None):
    """Classify one canonical record. Does not invent trades."""
    pump_names = pump_names if pump_names is not None else _pump_instruction_names()
    raw = unwrap_gta_record(record)
    signature = record.get("signature") if isinstance(record, dict) else None
    if not isinstance(raw, dict):
        return {"signature": signature, "class": "missing_raw", "reason": "Missing raw transaction result"}
    signature = _signature_of(raw, signature)
    version = raw.get("version", "legacy")
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    message = ((raw.get("transaction") or {}).get("message") if isinstance(raw.get("transaction"), dict) else {}) or {}
    row = {
        "signature": signature,
        "version": version,
        "failed": meta.get("err") is not None,
        "fee_lamports": meta.get("fee"),
        "wallet_in_keys": False,
        "outer_venues": [],
        "inner_venues": [],
        "class": "unclassified",
        "reason": None,
    }
    if version not in ("legacy", 0, 1):
        row["class"] = "unsupported_transaction_version"
        row["reason"] = "Unsupported transaction version"
        return row
    if meta.get("err") is not None:
        row["class"] = "failed_on_chain"
        row["reason"] = "On-chain failure; fees stay visible and no trade is reconstructed"
        try:
            keys = _keys(message, meta)
            row["wallet_in_keys"] = address in keys
            row["fee_payer"] = keys[0] if keys else None
        except ValueError:
            pass
        return row
    try:
        keys = _keys(message, meta)
    except ValueError as error:
        row["class"] = "malformed_keys"
        row["reason"] = str(error)
        return row
    row["wallet_in_keys"] = address in keys
    if address not in keys:
        row["class"] = "wallet_absent_from_account_keys"
        row["reason"] = "Investigated wallet is absent from transaction account keys"
        return row
    for instruction in message.get("instructions") or []:
        if not isinstance(instruction, dict):
            continue
        try:
            program = _program(instruction, keys)
        except (ValueError, TypeError, IndexError):
            continue
        if program in DECODED_OUTER_PROGRAMS:
            row["outer_venues"].append({
                "program": program,
                "instruction": _named_instruction(program, instruction.get("data"), pump_names),
            })
    for group in meta.get("innerInstructions") or []:
        if not isinstance(group, dict):
            continue
        for instruction in group.get("instructions") or []:
            if not isinstance(instruction, dict):
                continue
            try:
                program = _program(instruction, keys)
            except (ValueError, TypeError, IndexError):
                continue
            if program in (PUMP, PUMP_SWAP, JUPITER):
                name = _named_instruction(program, instruction.get("data"), pump_names)
                if name and name != "e445a52e51cb9a1d":
                    row["inner_venues"].append({"program": program, "instruction": name})
    outer_names = {item["instruction"] for item in row["outer_venues"]}
    inner_swaps = [
        item for item in row["inner_venues"]
        if item["program"] == PUMP_SWAP and item["instruction"] in PUMPSWAP_REVIEWED
    ]
    if "distribute_fee_to_holders" in outer_names:
        row["class"] = "pump_holder_fee_distribution"
        row["reason"] = "Reviewed Pump instruction distribute_fee_to_holders is not a spot swap"
        return row
    if any(item["program"] == PUMP and item["instruction"] in PUMP_SWAP_INSTRUCTIONS for item in row["outer_venues"]):
        row["class"] = "pump_bonding_curve_swap_candidate"
        row["reason"] = "Outer Pump buy/sell/buy_exact_sol_in is present for the existing adapter"
        return row
    if any(item["program"] == PUMP_SWAP and item["instruction"] in PUMPSWAP_REVIEWED for item in row["outer_venues"]):
        row["class"] = "pumpswap_spot_swap_candidate"
        row["reason"] = "Outer PumpSwap buy/sell/buy_exact_quote_in is a reviewed spot swap"
        return row
    if any(item["program"] == JUPITER for item in row["outer_venues"]):
        reviewed = any(item["instruction"] in JUPITER_REVIEWED for item in row["outer_venues"])
        row["class"] = "reviewed_jupiter_route" if reviewed else "unreviewed_jupiter_discriminator"
        row["inner_pumpswap_swaps"] = inner_swaps
        row["reason"] = (
            "Reviewed Jupiter route"
            if reviewed
            else "Outer Jupiter discriminator is not a reviewed route; inner PumpSwap is not treated as an outer swap"
        )
        return row
    if any(item["program"] in (RAYDIUM_CPMM, RAYDIUM_AMM, WHIRLPOOL) for item in row["outer_venues"]):
        row["class"] = "reviewed_amm_spot_swap_candidate"
        row["reason"] = "Outer Raydium or Orca instruction is a reviewed spot swap"
        return row
    if any(item["program"] == METEORA_DAMM_V2 for item in row["outer_venues"]):
        row["class"] = "reviewed_meteora_damm_v2_swap_candidate"
        row["reason"] = "Outer Meteora DAMM v2 swap is a reviewed spot swap"
        return row
    if any(item["program"] == RFQ_FILL for item in row["outer_venues"]):
        row["class"] = "reviewed_rfq_fill_swap_candidate"
        row["reason"] = "Outer 61DFfeTK Fill is a reviewed spot swap"
        return row
    if inner_swaps:
        row["class"] = "inner_pumpswap_without_reviewed_outer"
        row["inner_pumpswap_swaps"] = inner_swaps
        row["reason"] = "PumpSwap buy/sell appears only as an inner instruction under an unreviewed outer"
        return row
    if row["outer_venues"]:
        row["class"] = "reviewed_program_not_a_spot_swap"
        row["reason"] = "Recognized program instruction is not a reviewed spot swap"
        return row
    row["class"] = "no_reviewed_outer_spot_swap"
    row["reason"] = "No reviewed outer spot swap; transfers and balances alone do not prove trading"
    return row


def _integer_fee_lamports(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def fee_totals_from_rows(rows):
    """Sum visible integer fees. Not P&L."""
    total = 0
    failed = 0
    known = 0
    failed_known = 0
    for row in rows or []:
        fee = _integer_fee_lamports(row.get("fee_lamports"))
        if fee is None:
            continue
        total += fee
        known += 1
        if row.get("failed"):
            failed += fee
            failed_known += 1
    return {
        "transactions_with_integer_fee": known,
        "failed_transactions_with_integer_fee": failed_known,
        "fee_lamports": total,
        "failed_fee_lamports": failed,
        "fee_sol": str(Decimal(total) / LAMPORTS),
        "failed_fee_sol": str(Decimal(failed) / LAMPORTS),
        "not_pnl": True,
        "note": "Visible transaction fees only. Raw SOL delta is not profit.",
    }


def classify_normalised_records(records, address):
    pump_names = _pump_instruction_names()
    rows = [classify_normalised_transaction(record, address, pump_names=pump_names) for record in records]
    counts = Counter(row["class"] for row in rows)
    return {
        "kind": "ranked-capture-classification-v1",
        "address": address,
        "transactions": len(rows),
        "counts": dict(counts),
        "fee_totals": fee_totals_from_rows(rows),
        "rows": rows,
        "pump_idl_pin": PUMP_IDL_PIN,
        "PRODUCT_READY": False,
    }
