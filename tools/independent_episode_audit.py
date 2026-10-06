#!/usr/bin/env python3
"""Decoder-independent audit of captured research-search B episodes.

Reconstructs qualifying episodes from raw instructions, balances, ownership
and pinned protocol interfaces. Imports no scanner/ code. JSON parsing is
the only shared library used with the application.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/CAPTURE_MANIFEST.json"
OUT = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage/INDEPENDENT_AUDIT.json"

WSOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_SWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
JUPITER = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
SYSTEM = "11111111111111111111111111111111"
LAMPORTS = Decimal(1_000_000_000)
REPORT_START = datetime.fromisoformat("2026-09-05T13:29:27+00:00").timestamp()
REPORT_END = datetime.fromisoformat("2026-10-05T13:29:27+00:00").timestamp()
ACQUISITION = datetime.fromisoformat("2026-07-07T13:29:27+00:00").timestamp()

# Pinned published discriminators (Pump IDL / Jupiter instruction-parser).
PINNED = {
    (PUMP, "33e685a4017f83ad"): ("buy", 6, (5,)),
    (PUMP, "66063d1201daebea"): ("sell", 6, (5,)),
    (PUMP, "5df6823ce7e940b2"): ("sell_v2", 13, (14,)),
    (PUMP, "c2ab1c46684d5b2f"): ("buy_exact_quote_in_v2", 13, (14,)),
    (PUMP, "b817ee6167c5d33d"): ("buy_v2", 13, (14,)),
    (PUMP_SWAP, "66063d1201daebea"): ("sell", 1, (5, 6)),
    (PUMP_SWAP, "33e685a4017f83ad"): ("buy", 1, (5, 6)),
    (PUMP_SWAP, "c62e1552b4d9e870"): ("buy_exact_quote_in", 1, (5, 6)),
    (JUPITER, "bb64facc31c4af14"): ("route_v2", 0, (1, 2)),
    (JUPITER, "d19853937cfed8e9"): ("shared_accounts_route_v2", 1, (2, 5)),
}
JITO_TIPS = {
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
}
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _canonical(value):
    with localcontext() as ctx:
        ctx.prec = 192
        quantized = Decimal(value).quantize(Decimal("0.000000001"))
        text = format(quantized, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text


def _b58decode(value):
    if isinstance(value, list) and len(value) == 2 and value[1] == "base64":
        import base64
        return base64.b64decode(value[0], validate=True)
    if not isinstance(value, str):
        return b""
    number = 0
    for char in value:
        if char not in B58:
            return b""
        number = number * 58 + B58.index(char)
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\0" * (len(value) - len(value.lstrip("1"))) + body


def _keys(raw):
    message = (raw.get("transaction") or {}).get("message") or {}
    meta = raw.get("meta") or {}
    entries = message.get("accountKeys") or []
    keys = [item.get("pubkey") if isinstance(item, dict) else item for item in entries]
    loaded = meta.get("loadedAddresses") or {}
    if all(isinstance(item, str) for item in entries) or (entries and isinstance(entries[0], dict) and "pubkey" in (entries[0] or {})):
        keys = keys + list(loaded.get("writable") or []) + list(loaded.get("readonly") or [])
    return [key for key in keys if isinstance(key, str)]


def _program(instruction, keys):
    program = instruction.get("programId")
    if isinstance(program, str):
        return program
    index = instruction.get("programIdIndex")
    if isinstance(index, int) and 0 <= index < len(keys):
        return keys[index]
    return None


def _accounts(instruction, keys):
    accounts = instruction.get("accounts") or []
    resolved = []
    for item in accounts:
        if isinstance(item, int) and 0 <= item < len(keys):
            resolved.append(keys[item])
        elif isinstance(item, str):
            resolved.append(item)
    return resolved


def _owned_token_deltas(raw, address):
    meta = raw.get("meta") or {}
    deltas = defaultdict(lambda: Decimal("0"))
    pre = {}
    post = {}
    for field, dest in (("preTokenBalances", pre), ("postTokenBalances", post)):
        for balance in meta.get(field) or []:
            if not isinstance(balance, dict) or balance.get("owner") != address:
                continue
            mint = balance.get("mint")
            amount = (balance.get("uiTokenAmount") or {}).get("amount")
            if mint and amount not in (None, ""):
                dest[mint] = dest.get(mint, Decimal("0")) + Decimal(str(amount))
    mints = set(pre) | set(post)
    for mint in mints:
        deltas[mint] = post.get(mint, Decimal("0")) - pre.get(mint, Decimal("0"))
    return dict(deltas), pre, post


def _native_delta(raw, address, keys):
    meta = raw.get("meta") or {}
    try:
        index = keys.index(address)
    except ValueError:
        return Decimal("0"), False
    pre = meta.get("preBalances") or []
    post = meta.get("postBalances") or []
    if index >= len(pre) or index >= len(post):
        return Decimal("0"), False
    fee = meta.get("fee") if isinstance(meta.get("fee"), int) else 0
    paid = keys[0] == address if keys else False
    delta = Decimal(post[index] - pre[index])
    if paid:
        delta += Decimal(fee)
    return delta, paid


def _verified_tips(raw, keys, address):
    tips = Decimal("0")
    message = (raw.get("transaction") or {}).get("message") or {}
    for instruction in message.get("instructions") or []:
        parsed = instruction.get("parsed") if isinstance(instruction, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else None
        if not isinstance(info, dict) or parsed.get("type") != "transfer":
            continue
        if info.get("source") != address:
            continue
        dest = info.get("destination")
        lamports = info.get("lamports")
        if dest in JITO_TIPS and isinstance(lamports, int):
            tips += Decimal(lamports)
    return tips


def _route(raw, address, keys):
    message = (raw.get("transaction") or {}).get("message") or {}
    for index, instruction in enumerate(message.get("instructions") or []):
        if not isinstance(instruction, dict):
            continue
        program = _program(instruction, keys)
        payload = _b58decode(instruction.get("data"))
        if len(payload) < 8:
            continue
        disc = payload[:8].hex()
        layout = PINNED.get((program, disc))
        if not layout:
            continue
        name, authority_idx, owned_idx = layout
        accounts = _accounts(instruction, keys)
        if authority_idx >= len(accounts) or accounts[authority_idx] != address:
            continue
        owned = [accounts[i] for i in owned_idx if i < len(accounts)]
        return {
            "program": program,
            "instruction": name,
            "discriminator": disc,
            "authority": accounts[authority_idx],
            "owned": owned,
            "path": f"transaction.message.instructions.{index}",
        }
    return None


def _unwrap(record):
    if not isinstance(record, dict):
        return record
    if "transaction" in record:
        return record
    raw = record.get("raw")
    if isinstance(raw, dict):
        result = raw.get("result")
        if isinstance(result, dict) and "transaction" in result:
            return result
        if "transaction" in raw:
            return raw
    result = record.get("result")
    if isinstance(result, dict) and "transaction" in result:
        return result
    return record


def reconstruct_record(record, address):
    raw = _unwrap(record)
    if not isinstance(raw, dict):
        return None
    meta = raw.get("meta") or {}
    if meta.get("err") is not None:
        return None
    keys = _keys(raw)
    if address not in keys:
        return None
    route = _route(raw, address, keys)
    if not route:
        return None
    token_deltas, pre, post = _owned_token_deltas(raw, address)
    native, paid = _native_delta(raw, address, keys)
    wsol = token_deltas.pop(WSOL, Decimal("0"))
    settlement = native + wsol
    tips = _verified_tips(raw, keys, address)
    fee = Decimal(meta.get("fee") or 0) if paid else Decimal("0")
    assets = [(mint, qty) for mint, qty in token_deltas.items() if qty != 0 and mint != USDC]
    conversions = []
    if USDC in token_deltas and token_deltas[USDC] != 0 and settlement != 0:
        conversions.append("usdc_sol")
    if len(assets) != 1 or settlement == 0 or (assets[0][1] > 0) == (settlement > 0):
        if conversions:
            return None
        return None
    mint, quantity = assets[0]
    kind = "buy" if quantity > 0 else "sell"
    signature = record.get("signature") or ((raw.get("transaction") or {}).get("signatures") or [None])[0]
    timestamp = raw.get("blockTime")
    return {
        "kind": kind,
        "mint": mint,
        "quantity_raw": str(abs(quantity)),
        "consideration_sol": _canonical(abs(settlement) / LAMPORTS),
        "network_fee_sol": _canonical(fee / LAMPORTS),
        "tips_sol": _canonical(tips / LAMPORTS),
        "fees_and_tips_sol": _canonical((fee + tips) / LAMPORTS),
        "signature": signature,
        "timestamp": timestamp,
        "program": route["program"],
        "instruction": route["instruction"],
        "discriminator": route["discriminator"],
        "path": route["path"],
        "observed_pre_quantity_raw": str(pre.get(mint, Decimal("0"))),
        "source": "independent-pinned-interface",
    }


def _gta_records(payload):
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


def _load_pages(address, pages):
    records = []
    seen = set()
    for page in pages:
        path = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06" / page["repo_gz_path"]
        raw = gzip.decompress(path.read_bytes())
        if page.get("raw_sha256"):
            assert hashlib.sha256(raw).hexdigest() == page["raw_sha256"]
        for item in _gta_records(json.loads(raw)):
            if not isinstance(item, dict):
                continue
            signature = item.get("signature")
            tx = item.get("transaction") if isinstance(item.get("transaction"), dict) else {}
            sigs = tx.get("signatures") or []
            if not signature and sigs:
                signature = sigs[0]
            if signature and signature in seen:
                continue
            if signature:
                seen.add(signature)
            records.append(item)
    return records


def _fifo(trades):
    by_mint = defaultdict(list)
    for trade in trades:
        by_mint[trade["mint"]].append(trade)
    episodes = []
    unresolved = 0
    known_sales = 0
    for mint, rows in by_mint.items():
        rows = sorted(rows, key=lambda row: (row.get("timestamp") or 0, row.get("signature") or ""))
        first_buy = next((row for row in rows if row["kind"] == "buy"), None)
        opening = Decimal(str(first_buy["observed_pre_quantity_raw"])) if first_buy else Decimal("0")
        lots = []
        inventory = Decimal("0")
        opened = False
        episode_pnl = Decimal("0")
        for row in rows:
            qty = Decimal(row["quantity_raw"])
            consideration = Decimal(row["consideration_sol"])
            fees = Decimal(row.get("fees_and_tips_sol") or 0)
            if row["kind"] == "buy":
                if opening > 0 and not lots and inventory == 0:
                    pass
                lots.append({"qty": qty, "cost": consideration, "fees": fees})
                inventory += qty
                opened = True
                continue
            remaining = qty
            if opening > 0:
                take = opening if opening <= remaining else remaining
                opening -= take
                remaining -= take
                unresolved += 1
                if remaining <= 0:
                    continue
            basis = Decimal("0")
            buy_fees = Decimal("0")
            matched = Decimal("0")
            while remaining > 0 and lots:
                lot = lots[0]
                take = lot["qty"] if lot["qty"] <= remaining else remaining
                share = lot["cost"] * take / lot["qty"]
                fee_share = lot["fees"] * take / lot["qty"]
                basis += share
                buy_fees += fee_share
                lot["cost"] -= share
                lot["fees"] -= fee_share
                lot["qty"] -= take
                remaining -= take
                matched += take
                inventory -= take
                if lot["qty"] == 0:
                    lots.pop(0)
            if remaining > 0:
                unresolved += 1
            if matched > 0:
                proceeds = consideration * matched / qty
                sale_fees = fees * matched / qty
                pnl = proceeds - basis - buy_fees - sale_fees
                known_sales += 1
                episode_pnl += pnl
            if opened and inventory == 0 and remaining == 0 and opening == 0:
                timestamp = row.get("timestamp")
                in_window = timestamp is not None and REPORT_START <= timestamp < REPORT_END
                if in_window:
                    episodes.append({
                        "mint": mint,
                        "close_signature": row["signature"],
                        "net_profit_sol": _canonical(episode_pnl),
                    })
                opened = False
                episode_pnl = Decimal("0")
        if first_buy and Decimal(str(first_buy["observed_pre_quantity_raw"])) > 0:
            # Opening inventory consumed before captured buys; leftover opening is not a clean episode.
            pass
    return episodes, unresolved, known_sales


def audit_address(address, pages):
    records = _load_pages(address, pages)
    trades = []
    for record in records:
        event = reconstruct_record(record, address)
        if event:
            trades.append(event)
    episodes, unresolved, known_sales = _fifo(trades)
    wins = sum(1 for item in episodes if Decimal(item["net_profit_sol"]) > 0)
    return {
        "address": address,
        "records": len(records),
        "independently_reconstructed_trades": len(trades),
        "clean_episodes": len(episodes),
        "episode_win_rate": _canonical(Decimal(wins) / Decimal(len(episodes))) if episodes else None,
        "unresolved_basis_sales": unresolved,
        "known_cost_sales": known_sales,
        "episodes": episodes,
        "imports_scanner": False,
        "source": "raw_instructions_balances_ownership_pinned_interfaces",
        "PRODUCT_READY": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_address = defaultdict(list)
    for entry in (manifest.get("pages") or {}).values():
        by_address[entry["address"]].append(entry)
    results = []
    for address, pages in sorted(by_address.items(), key=lambda item: item[0]):
        pages = sorted(pages, key=lambda item: item.get("page_index") or 0)
        results.append(audit_address(address, pages))
    payload = {
        "kind": "independent-episode-audit-v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wallets": results,
        "imports_scanner": False,
        "PRODUCT_READY": False,
    }
    if args.write:
        OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wallets": [{k: row[k] for k in ("address", "clean_episodes", "independently_reconstructed_trades", "unresolved_basis_sales")} for row in results]}, indent=2))
    return payload


if __name__ == "__main__":
    main()
