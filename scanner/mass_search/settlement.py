"""Settlement-aware subset worksheets. SOL/wSOL and USDC stay separate."""
from __future__ import annotations

from decimal import Decimal, localcontext

from scanner.accounting import canonical
from scanner.investigation import WSOL
from scanner.mass_search.metrics import format_decimal

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS = 6
SETTLEMENT_SOL = WSOL
SETTLEMENT_USDC = USDC


def settlement_of(event):
    value = event.get("settlement_mint")
    if value == USDC or event.get("consideration_usdc") not in (None, ""):
        return USDC
    return WSOL


def _ordered_rows(rows):
    dated = [row for row in rows if not row.get("timestamp_missing") and row.get("seconds_from_start") is not None]
    return sorted(dated, key=lambda row: (row["seconds_from_start"], row.get("signature") or ""))


def _group_by_mint(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row.get("mint"), []).append(row)
    return grouped


def isolate_known_cost_events(rows):
    """Keep buys and sells that have inventory. Leading/unbacked sells stay unresolved."""
    known = []
    unresolved = []
    inventory = Decimal("0")
    for event in _ordered_rows(rows):
        units = Decimal(str(event["units"]))
        if event["kind"] == "buy":
            inventory += units
            known.append(event)
            continue
        if event["kind"] == "sell":
            if inventory <= 0 or units > inventory:
                unresolved.append({
                    **event,
                    "unresolved_basis": True,
                    "reason": "Sale has no known acquisition cost in this sample",
                })
                continue
            inventory -= units
            known.append(event)
    return known, unresolved


def isolate_known_cost_by_mint(rows):
    """Isolate known-cost inventory per mint. Cross-mint lots are never mixed."""
    known = []
    unresolved = []
    for mint_rows in _group_by_mint(rows).values():
        part_known, part_unresolved = isolate_known_cost_events(mint_rows)
        known.extend(part_known)
        unresolved.extend(part_unresolved)
    return known, unresolved


def usdc_fifo_worksheet(events):
    """Production FIFO in USDC. SOL network fees are not converted and are not USDC P&L."""
    indexed = [event for event in events if event.get("kind") in ("buy", "sell")]
    mints = {event.get("mint") for event in indexed if event.get("mint")}
    if len(mints) > 1:
        basis = []
        profits = []
        total = Decimal("0")
        used = []
        for mint in sorted(mints):
            part = usdc_fifo_worksheet([event for event in indexed if event.get("mint") == mint])
            basis.extend(part["sale_fifo_basis_usdc"])
            profits.extend(part["sale_net_profit_usdc"])
            if part.get("total_profit_usdc") not in (None, ""):
                total += Decimal(str(part["total_profit_usdc"]))
                used.append(mint)
        return {
            "sale_fifo_basis_usdc": basis,
            "sale_net_profit_usdc": profits,
            "total_profit_usdc": canonical(total) if used else None,
            "total_profit_sol": None,
            "settlement_mint": USDC,
            "settlement_asset": "USDC",
            "oracle": "production-usdc-fifo-v1",
            "sol_fees_not_converted": True,
            "not_fx": True,
            "declared_mints": used,
        }
    with localcontext() as ctx:
        ctx.prec = 192
        lots = []
        sales = []
        for event in indexed:
            units = Decimal(str(event["units"]))
            if event["kind"] == "buy":
                consideration = Decimal(str(event["consideration_usdc"]))
                lots.append({"units": units, "unit_cost": consideration / units})
            elif event["kind"] == "sell":
                remaining = units
                basis = Decimal("0")
                while remaining > 0:
                    if not lots:
                        raise ValueError("Sale exceeds supported USDC-settled inventory")
                    lot = lots[0]
                    take = min(lot["units"], remaining)
                    basis += lot["unit_cost"] * take
                    lot["units"] -= take
                    remaining -= take
                    if lot["units"] == 0:
                        lots.pop(0)
                proceeds = Decimal(str(event["consideration_usdc"]))
                sales.append({
                    "basis": canonical(basis),
                    "net_profit": canonical(proceeds - basis),
                })
        total = sum((Decimal(sale["net_profit"]) for sale in sales), Decimal("0"))
        return {
            "sale_fifo_basis_usdc": [sale["basis"] for sale in sales],
            "sale_net_profit_usdc": [sale["net_profit"] for sale in sales],
            "total_profit_usdc": canonical(total) if sales else None,
            "total_profit_sol": None,
            "settlement_mint": USDC,
            "settlement_asset": "USDC",
            "oracle": "production-usdc-fifo-v1",
            "sol_fees_not_converted": True,
            "not_fx": True,
        }


def empty_usdc_worksheet(*, unresolved=0, known=0):
    return {
        "sale_fifo_basis_usdc": [],
        "sale_net_profit_usdc": [],
        "total_profit_usdc": None,
        "total_profit_sol": None,
        "settlement_mint": USDC,
        "settlement_asset": "USDC",
        "oracle": "production-usdc-fifo-v1",
        "sol_fees_not_converted": True,
        "not_fx": True,
        "unresolved_basis_sales": unresolved,
        "known_cost_trades": known,
    }


def settlement_aware_worksheet(events):
    """Production worksheet. One settlement asset. Mixed SOL+USDC is refused."""
    from scanner.mass_search.live_g1 import independent_fifo_worksheet

    usable = [row for row in events if row.get("kind") in ("buy", "sell")]
    if not usable:
        return None
    mints = {settlement_of(row) for row in usable}
    if USDC in mints and WSOL in mints:
        raise ValueError("SOL and USDC consideration cannot share one worksheet; no FX")
    if mints == {USDC}:
        known, unresolved = isolate_known_cost_by_mint(usable)
        if not known or not any(row["kind"] == "sell" for row in known):
            payload = empty_usdc_worksheet(unresolved=len(unresolved), known=len(known))
            return payload
        worksheet = usdc_fifo_worksheet(known)
        worksheet["unresolved_basis_sales"] = len(unresolved)
        worksheet["known_cost_trades"] = len(known)
        return worksheet
    return independent_fifo_worksheet(usable)


def independent_settlement_worksheet(events):
    """Independent worksheet. USDC uses the live_g1 oracle; SOL uses G1 FIFO."""
    from scanner.mass_search.live_g1 import independent_fifo_worksheet, independent_usdc_fifo_worksheet

    usable = [row for row in events if row.get("kind") in ("buy", "sell")]
    if not usable:
        return None
    mints = {settlement_of(row) for row in usable}
    if USDC in mints and WSOL in mints:
        raise ValueError("SOL and USDC consideration cannot share one worksheet; no FX")
    if mints == {USDC}:
        known, unresolved = isolate_known_cost_by_mint(usable)
        if not known or not any(row["kind"] == "sell" for row in known):
            payload = empty_usdc_worksheet(unresolved=len(unresolved), known=len(known))
            payload["oracle"] = "independent-usdc-fifo-v1"
            return payload
        worksheet = independent_usdc_fifo_worksheet(known)
        worksheet["unresolved_basis_sales"] = len(unresolved)
        worksheet["known_cost_trades"] = len(known)
        return worksheet
    return independent_fifo_worksheet(usable)


def map_decoder_trade(row, *, address, seconds, timestamp_missing, role, window_qualified, unresolved_order):
    settlement = row.get("settlement_mint") or WSOL
    mapped = {
        "kind": row["kind"],
        "units": str(row.get("quantity_raw") or "0"),
        "wallet_fee_sol": str(row.get("fee_sol") or "0"),
        "seconds_from_start": seconds,
        "timestamp_missing": timestamp_missing,
        "window_qualified": window_qualified,
        "role": role,
        "unresolved_order": unresolved_order,
        "signature": row.get("signature"),
        "mint": row.get("mint"),
        "address": address,
        "path": row.get("path"),
        "evidence": row.get("evidence") or [],
        "settlement_mint": settlement,
        "instruction": row.get("instruction"),
        "venue": row.get("venue") or row.get("source"),
        "classification": row.get("classification") or "market",
    }
    if settlement == USDC:
        mapped["consideration_usdc"] = str(row.get("amount_usdc") or "0")
        mapped["amount_usdc"] = str(row.get("amount_usdc") or "0")
    else:
        mapped["consideration_sol"] = str(row.get("amount_sol") or "0")
    if "paid_by_wallet" in row:
        mapped["paid_by_wallet"] = row["paid_by_wallet"]
    return mapped


def format_settlement_amount(worksheet):
    if not worksheet:
        return None, None
    if worksheet.get("settlement_asset") == "USDC" or worksheet.get("total_profit_usdc") not in (None, ""):
        return worksheet.get("total_profit_usdc"), "USDC"
    if worksheet.get("total_profit_sol") not in (None, ""):
        return format_decimal(Decimal(str(worksheet["total_profit_sol"]))), "SOL"
    return None, worksheet.get("settlement_asset")
