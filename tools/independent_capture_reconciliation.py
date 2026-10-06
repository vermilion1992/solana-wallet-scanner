#!/usr/bin/env python3
"""Independent FIFO from a raw genuine capture.

Starts at the archived GTA page and classified decoder trades. It does not
import scanner.accounting, scanner.mass_search.settlement, or live_g1
worksheets. SOL fees stay SOL. Missing basis stays unknown, never zero.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from decimal import Decimal, localcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _canonical(value):
    with localcontext() as ctx:
        ctx.prec = 192
        quantized = Decimal(value).quantize(Decimal("0.000000001"))
        text = format(quantized, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text


def _fifo(trades, *, asset):
    lots = defaultdict(list)
    sells = []
    unresolved = []
    open_lots = []
    for trade in trades:
        mint = trade["mint"]
        qty = Decimal(trade["quantity_raw"])
        consideration = Decimal(trade["consideration"])
        fee = Decimal(trade.get("fee_sol") or 0)
        if trade["kind"] == "buy":
            cost = consideration + fee if asset == "SOL" else consideration
            lots[mint].append({
                "quantity_raw": qty,
                "consideration": cost,
                "signature": trade["signature"],
                "mint": mint,
            })
            continue
        remaining = qty
        basis = Decimal(0)
        consumed = []
        while remaining > 0 and lots[mint]:
            lot = lots[mint][0]
            take = lot["quantity_raw"] if lot["quantity_raw"] <= remaining else remaining
            share = (take / lot["quantity_raw"]) * lot["consideration"]
            basis += share
            lot["quantity_raw"] -= take
            lot["consideration"] -= share
            remaining -= take
            consumed.append({"signature": lot["signature"], "quantity_raw": str(take), "basis": _canonical(share)})
            if lot["quantity_raw"] == 0:
                lots[mint].pop(0)
        matched_qty = qty - remaining
        if matched_qty > 0:
            matched_proceeds = consideration * matched_qty / qty
            unmatched_proceeds = consideration - matched_proceeds
            matched_fee = fee * matched_qty / qty
            unmatched_fee = fee - matched_fee
            profit = matched_proceeds - basis
            if asset == "SOL":
                profit -= matched_fee
            sells.append({
                "signature": trade["signature"],
                "mint": mint,
                "quantity_raw": str(matched_qty),
                "proceeds": _canonical(matched_proceeds),
                "basis": _canonical(basis),
                "net_profit": _canonical(profit),
                "consumed_lots": consumed,
                "fee_sol": _canonical(matched_fee),
                "fee_in_pnl": asset == "SOL",
                "partial_known_cost": remaining > 0,
                "whole_sale_pnl_resolved": remaining == 0,
                "result_scope": "conditional_on_captured_inventory",
                "fee_allocation": "pro_rata_by_quantity; unmatched = original minus matched",
            })
        else:
            unmatched_proceeds = consideration
            unmatched_fee = fee
        if remaining > 0:
            unresolved.append({
                "signature": trade["signature"],
                "mint": mint,
                "unmatched_quantity_raw": str(remaining),
                "gross_proceeds": _canonical(unmatched_proceeds),
                "fee_sol": _canonical(unmatched_fee),
                "unresolved_basis": True,
                "whole_sale_pnl_resolved": False,
                "result_scope": "conditional_on_captured_inventory",
            })
    for mint, remaining_lots in lots.items():
        for lot in remaining_lots:
            if lot["quantity_raw"] > 0:
                open_lots.append({
                    "mint": mint,
                    "quantity_raw": str(lot["quantity_raw"]),
                    "consideration": _canonical(lot["consideration"]),
                    "signature": lot["signature"],
                })
    total = sum(Decimal(row["net_profit"]) for row in sells)
    return {
        "asset": asset,
        "known_cost_sells": sells,
        "unresolved_basis_sales": unresolved,
        "open_lots": open_lots,
        "total_profit": _canonical(total) if sells else None,
        "sol_fees_not_converted": asset == "USDC",
        "missing_basis_is_not_zero": True,
    }


def reconcile_rank1():
    from scanner.investigation import decode_supported_swaps
    from scanner.mass_search.canonical_records import canonical_decode_records
    from scanner.mass_search.capture_catalog import catalog_by_address, load_capture_records
    from scanner.mass_search.g3_reacquire import ALLOWED_WALLET

    records, digest = load_capture_records(catalog_by_address()[ALLOWED_WALLET])
    decoded = decode_supported_swaps(canonical_decode_records(records), ALLOWED_WALLET)
    trades = []
    for event in decoded["events"]:
        if event.get("kind") not in ("buy", "sell") or event.get("settlement_asset") != "USDC":
            continue
        trades.append({
            "kind": event["kind"],
            "mint": event["mint"],
            "quantity_raw": event["quantity_raw"],
            "consideration": event["amount_usdc"],
            "fee_sol": event.get("fee_sol") or "0",
            "signature": event.get("signature"),
            "timestamp": event.get("timestamp"),
            "classification": event.get("classification"),
        })
    trades.sort(key=lambda row: (row.get("timestamp") is None, row.get("timestamp") or 0))
    fifo = _fifo(trades, asset="USDC")
    return {
        "kind": "independent-capture-reconciliation-v1",
        "imports_app_accounting": False,
        "wallet": ALLOWED_WALLET,
        "capture_sha256": digest,
        "market_trades": len(trades),
        "classified_counts": {
            "buy": sum(1 for row in trades if row["kind"] == "buy"),
            "sell": sum(1 for row in trades if row["kind"] == "sell"),
        },
        "fifo": fifo,
        "headline_meaning": (
            "Known-cost realised USDC on the one matched 5tCju6YN sell "
            "(gross proceeds minus FIFO buy consideration). SOL fees stay SOL "
            "and are not subtracted. The leading unbacked 5tCju6YN sell is excluded. "
            "Open H4KU buys are inventory, not profit."
        ),
        "PRODUCT_READY": False,
    }


def reconcile_g1():
    from scanner.investigation import decode_supported_swaps
    from scanner.mass_search.canonical_records import canonical_decode_records
    from scanner.mass_search.capture_catalog import G1_ADDRESS, G1_MINT, catalog_by_address, load_capture_records

    records, digest = load_capture_records(catalog_by_address()[G1_ADDRESS])
    decoded = decode_supported_swaps(canonical_decode_records(records), G1_ADDRESS)
    trades = []
    for event in decoded["events"]:
        if event.get("kind") not in ("buy", "sell"):
            continue
        if event.get("mint") != G1_MINT:
            continue
        trades.append({
            "kind": event["kind"],
            "mint": event["mint"],
            "quantity_raw": event["quantity_raw"],
            "consideration": event.get("amount_sol") or "0",
            "fee_sol": event.get("fee_sol") or "0",
            "signature": event.get("signature"),
            "timestamp": event.get("timestamp"),
            "classification": event.get("classification"),
        })
    trades.sort(key=lambda row: (row.get("timestamp") is None, row.get("timestamp") or 0))
    fifo = _fifo(trades, asset="SOL")
    return {
        "kind": "independent-capture-reconciliation-v1",
        "imports_app_accounting": False,
        "wallet": G1_ADDRESS,
        "mint": G1_MINT,
        "capture_sha256": digest,
        "market_trades": len(trades),
        "fifo": fifo,
        "PRODUCT_READY": False,
    }


def reconcile_synthetic(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("kind") != "SYNTHETIC_ENGINEERING_FIXTURE":
        raise ValueError("Not a labelled synthetic engineering fixture")
    trades = []
    asset = "USDC"
    for event in payload.get("events") or []:
        if event.get("kind") not in ("buy", "sell"):
            continue
        usdc = event.get("consideration_usdc")
        sol = event.get("consideration_sol")
        if usdc not in (None, ""):
            consideration = usdc
            asset = "USDC"
        else:
            consideration = sol or "0"
            asset = "SOL"
        trades.append({
            "kind": event["kind"],
            "mint": event.get("mint") or "SynthMint",
            "quantity_raw": event["units"],
            "consideration": consideration,
            "fee_sol": event.get("wallet_fee_sol") or event.get("fee_sol") or "0",
            "signature": event.get("signature"),
            "timestamp": event.get("seconds_from_start"),
            "classification": event.get("classification"),
        })
    trades.sort(key=lambda row: (row.get("timestamp") is None, row.get("timestamp") or 0))
    return {
        "kind": "independent-capture-reconciliation-v1",
        "imports_app_accounting": False,
        "corpus_kind": "SYNTHETIC",
        "not_proof": True,
        "wallet": payload.get("address"),
        "market_trades": len(trades),
        "fifo": _fifo(trades, asset=asset),
        "PRODUCT_READY": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=("rank1", "g1", "synthetic"), default="rank1")
    parser.add_argument("--fixture", default="")
    args = parser.parse_args()
    if args.target == "synthetic":
        payload = reconcile_synthetic(args.fixture)
    else:
        payload = reconcile_rank1() if args.target == "rank1" else reconcile_g1()
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
