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


def _order_key(row):
    order = row.get("order")
    return order if isinstance(order, int) and not isinstance(order, bool) else 0


def _ordered_rows(rows):
    dated = [row for row in rows if not row.get("timestamp_missing") and row.get("seconds_from_start") is not None]
    return sorted(dated, key=lambda row: (row["seconds_from_start"], _order_key(row), row.get("signature") or ""))


def _group_by_mint(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row.get("mint"), []).append(row)
    return grouped


FEE_ALLOCATION = (
    "Whole-transaction SOL fees and settlement proceeds are allocated by "
    "quantity: matched = original * matched_qty / qty; unmatched = original "
    "minus matched so the two parts sum to the original integer/decimal total."
)


def _split_amount(original, *, take, total):
    """Allocate `take/total` of original; caller assigns the remainder to the other part."""
    with localcontext() as ctx:
        ctx.prec = 192
        if original in (None, "") or total == 0:
            return None
        return Decimal(str(original)) * take / total


def _scale_trade(event, *, units, original_units, remainder_of=None):
    """Pro-rate proceeds and SOL fees by quantity. Never invent a zero cost.

    When remainder_of is the already-scaled matched sibling, this side takes
    original minus matched so proceeds and fees are fully accounted.
    """
    scaled = dict(event)
    scaled["units"] = canonical(units)
    for key in ("consideration_usdc", "consideration_sol", "amount_usdc", "amount_sol", "wallet_fee_sol"):
        if event.get(key) in (None, ""):
            continue
        if remainder_of is not None and remainder_of.get(key) not in (None, ""):
            scaled[key] = canonical(Decimal(str(event[key])) - Decimal(str(remainder_of[key])))
        else:
            scaled[key] = canonical(_split_amount(event[key], take=units, total=original_units))
    scaled["fee_allocation"] = FEE_ALLOCATION
    return scaled


def _split_sale_fragments(event, allocations):
    """Split one sale into quantity fragments that sum to the original amounts."""
    fragments = []
    remaining_event = event
    remaining_units = Decimal(str(event["units"]))
    for take, dest, flags in allocations:
        if take <= 0:
            continue
        if take == remaining_units:
            part = dict(remaining_event)
            part["units"] = canonical(take)
        else:
            part = _scale_trade(remaining_event, units=take, original_units=remaining_units)
            leftover = _scale_trade(remaining_event, units=remaining_units - take, original_units=remaining_units, remainder_of=part)
            remaining_event = leftover
            remaining_units = remaining_units - take
        part.update(flags)
        fragments.append((dest, part))
    return fragments


def isolate_known_cost_events(rows):
    """Keep buys and sells that have inventory. Opening unknown-basis is consumed first.

    Inventory is per token. A sale that consumes lots bought in a different
    quote asset is unconverted: the matched fragment stays visible, P&L is
    unresolved (never zero), and the episode is not clean.
    """
    known = []
    unresolved = []
    lots = []
    opening_unknown = Decimal("0")
    for event in _ordered_rows(rows):
        units = Decimal(str(event["units"]))
        if event.get("opening_unknown") or event.get("kind") == "opening_unknown":
            opening_unknown += units
            continue
        if event["kind"] == "buy":
            lots.append({
                "units": units,
                "settlement": settlement_of(event),
                "undecoded": bool(event.get("undecoded_buy")),
            })
            if event.get("undecoded_buy"):
                continue
            known.append(event)
            continue
        if event["kind"] == "undecoded_buy":
            lots.append({"units": units, "settlement": None, "undecoded": True})
            continue
        if event["kind"] != "sell":
            continue
        remaining = units
        opening_take = Decimal("0")
        if opening_unknown > 0 and remaining > 0:
            opening_take = opening_unknown if opening_unknown <= remaining else remaining
            opening_unknown -= opening_take
            remaining -= opening_take
        sale_settlement = settlement_of(event)
        same_take = Decimal("0")
        cross_take = Decimal("0")
        undecoded_take = Decimal("0")
        while remaining > 0 and lots:
            lot = lots[0]
            take = lot["units"] if lot["units"] <= remaining else remaining
            if lot.get("undecoded"):
                undecoded_take += take
            elif lot["settlement"] != sale_settlement:
                cross_take += take
            else:
                same_take += take
            lot["units"] -= take
            remaining -= take
            if lot["units"] == 0:
                lots.pop(0)
        leftover_take = remaining
        if undecoded_take > 0:
            # An earlier undecoded buy taints this sale. Never emit a partial
            # matched-fragment figure; the whole sale is unknown-basis.
            leftover_take += same_take + cross_take + undecoded_take
            same_take = Decimal("0")
            cross_take = Decimal("0")
        dirty = opening_take > 0 or cross_take > 0 or leftover_take > 0 or undecoded_take > 0
        allocations = [
            (same_take, "known", {
                "result_scope": "conditional_on_captured_inventory",
                "whole_sale_pnl_resolved": not dirty,
                "partial_known_cost": dirty,
                "split_part": event.get("split_part") or "matched",
                **({"not_clean_episode": True} if dirty else {}),
            }),
            (opening_take, "unresolved", {
                "unresolved_basis": True,
                "opening_inventory_consumed": True,
                "split_part": "unresolved",
                "whole_sale_pnl_resolved": False,
                "result_scope": "conditional_on_captured_inventory",
                "reason": "Sale matches pre-capture opening inventory; no verified zero-inventory checkpoint",
            }),
            (cross_take, "cross", {
                "unresolved_basis": True,
                "cross_currency_unconverted": True,
                "not_clean_episode": True,
                "split_part": "unresolved",
                "whole_sale_pnl_resolved": False,
                "result_scope": "conditional_on_captured_inventory",
                "reason": "Unconverted cross-currency sale; inventory is per token; P&L unresolved, never zero",
            }),
            (leftover_take, "unresolved", {
                "unresolved_basis": True,
                "split_part": "unresolved",
                "whole_sale_pnl_resolved": False,
                "result_scope": "conditional_on_captured_inventory",
                "reason": (
                    "Sale has no known acquisition cost in this sample"
                    if leftover_take == units
                    else "Sale remainder has no known acquisition cost in this sample"
                ),
                "unmatched_quantity": canonical(leftover_take),
            }),
        ]
        for dest, part in _split_sale_fragments(event, allocations):
            if dest == "known":
                known.append(part)
            elif dest == "cross":
                unresolved.append(part)
                inventory_sell = dict(part)
                inventory_sell["unresolved_basis"] = False
                inventory_sell["split_part"] = "matched_inventory_only"
                known.append(inventory_sell)
            else:
                unresolved.append(part)
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


def _usdc_canonical(value):
    quantized = Decimal(str(value)).quantize(Decimal("0.000000001"))
    text = format(quantized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def usdc_fifo_worksheet(events):
    """Production FIFO in USDC. SOL network fees are not converted and are not USDC P&L."""
    indexed = [event for event in events if event.get("kind") in ("buy", "sell")]
    mints = {event.get("mint") for event in indexed if event.get("mint")}
    if len(mints) > 1:
        basis = []
        profits = []
        sale_rows = []
        total = Decimal("0")
        used = []
        for mint in sorted(mints):
            part = usdc_fifo_worksheet([event for event in indexed if event.get("mint") == mint])
            basis.extend(part["sale_fifo_basis_usdc"])
            profits.extend(part["sale_net_profit_usdc"])
            if part.get("total_profit_usdc") not in (None, ""):
                total += Decimal(str(part["total_profit_usdc"]))
                used.append(mint)
            part_rows = part.get("sale_rows") or []
            sale_rows.extend(part_rows)
        return {
            "sale_fifo_basis_usdc": basis,
            "sale_net_profit_usdc": profits,
            "sale_rows": sale_rows,
            "total_profit_usdc": _usdc_canonical(total) if used else None,
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
                lots.append({"remaining_units": units, "remaining_cost": consideration})
            elif event["kind"] == "sell":
                remaining = units
                basis = Decimal("0")
                while remaining > 0:
                    if not lots:
                        raise ValueError("Sale exceeds supported USDC-settled inventory")
                    lot = lots[0]
                    take = remaining if remaining <= lot["remaining_units"] else lot["remaining_units"]
                    share = lot["remaining_cost"] * take / lot["remaining_units"]
                    basis += share
                    lot["remaining_cost"] -= share
                    lot["remaining_units"] -= take
                    remaining -= take
                    if lot["remaining_units"] == 0:
                        lots.pop(0)
                proceeds = Decimal(str(event["consideration_usdc"]))
                profit = _usdc_canonical(proceeds - basis)
                sales.append({
                    "signature": event.get("signature"),
                    "split_part": event.get("split_part") or "matched",
                    "mint": event.get("mint"),
                    "basis": _usdc_canonical(basis),
                    "gross_profit": profit,
                    "fees_and_tips": "0",
                    "net_profit": profit,
                    "units": event.get("units"),
                })
        total = sum((Decimal(sale["net_profit"]) for sale in sales), Decimal("0"))
        return {
            "sale_fifo_basis_usdc": [sale["basis"] for sale in sales],
            "sale_net_profit_usdc": [sale["net_profit"] for sale in sales],
            "sale_rows": sales,
            "total_profit_usdc": _usdc_canonical(total) if sales else None,
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
        "sale_rows": [],
        "total_profit_usdc": None,
        "total_profit_sol": None,
        "settlement_mint": USDC,
        "settlement_asset": "USDC",
        "oracle": "production-usdc-fifo-v1",
        "sol_fees_not_converted": True,
        "not_fx": True,
        "unresolved_basis_sales": unresolved,
        "known_cost_trades": known,
        "known_cost_sales": 0,
        "open_lots": 0,
        "whole_sale_pnl_resolved": unresolved == 0,
        "result_scope": "conditional_on_captured_inventory",
        "fee_allocation": FEE_ALLOCATION,
    }


def empty_sol_worksheet(*, unresolved=0, known=0, oracle="independent-g1-fifo-v1"):
    return {
        "sale_fifo_basis_sol": [],
        "sale_net_profit_sol": [],
        "sale_rows": [],
        "total_profit_sol": None,
        "total_gross_profit_sol": None,
        "total_fees_and_tips_sol": None,
        "oracle": oracle,
        "settlement_asset": "SOL",
        "not_fx": True,
        "unresolved_basis_sales": unresolved,
        "known_cost_trades": known,
        "known_cost_sales": 0,
        "open_lots": 0,
        "whole_sale_pnl_resolved": unresolved == 0,
        "result_scope": "conditional_on_captured_inventory",
        "fee_allocation": FEE_ALLOCATION,
    }


def _open_lot_count(known):
    lots = {}
    for event in _ordered_rows(known):
        mint = event.get("mint")
        units = Decimal(str(event["units"]))
        lots.setdefault(mint, [])
        if event["kind"] == "buy":
            lots[mint].append(units)
            continue
        if event["kind"] != "sell":
            continue
        remaining = units
        while remaining > 0 and lots[mint]:
            take = lots[mint][0] if lots[mint][0] <= remaining else remaining
            lots[mint][0] -= take
            remaining -= take
            if lots[mint][0] == 0:
                lots[mint].pop(0)
    return sum(1 for mint_lots in lots.values() for lot in mint_lots if lot > 0)


def _annotate_isolated_worksheet(worksheet, known, unresolved):
    if not worksheet:
        return None
    worksheet["unresolved_basis_sales"] = len(unresolved)
    worksheet["known_cost_trades"] = len(known)
    worksheet["known_cost_sales"] = sum(1 for row in known if row.get("kind") == "sell")
    worksheet["open_lots"] = _open_lot_count(known)
    worksheet["whole_sale_pnl_resolved"] = len(unresolved) == 0
    worksheet["result_scope"] = "conditional_on_captured_inventory"
    worksheet["fee_allocation"] = FEE_ALLOCATION
    worksheet["not_fx"] = True
    return worksheet


def _single_asset_worksheet(events, *, production):
    from scanner.mass_search.live_g1 import independent_fifo_worksheet, independent_usdc_fifo_worksheet

    usable = [row for row in events if row.get("kind") in ("buy", "sell")]
    if not usable:
        return None
    known, unresolved = isolate_known_cost_by_mint(usable)
    asset = "USDC" if {settlement_of(row) for row in usable} == {USDC} else "SOL"
    if asset == "USDC":
        if not known or not any(row["kind"] == "sell" for row in known):
            payload = empty_usdc_worksheet(unresolved=len(unresolved), known=len(known))
            if not production:
                payload["oracle"] = "independent-usdc-fifo-v1"
            payload["open_lots"] = _open_lot_count(known)
            return payload
        worksheet = usdc_fifo_worksheet(known) if production else independent_usdc_fifo_worksheet(known)
        return _annotate_isolated_worksheet(worksheet, known, unresolved)
    if not known or not any(row["kind"] == "sell" for row in known):
        payload = empty_sol_worksheet(unresolved=len(unresolved), known=len(known))
        payload["open_lots"] = _open_lot_count(known)
        return payload
    worksheet = independent_fifo_worksheet(known)
    return _annotate_isolated_worksheet(worksheet, known, unresolved)


def worksheets_by_quote_asset(events, *, production=True):
    """Separate SOL and USDC worksheets. Never convert. Excess sales isolate known cost.

    A mint bought in one quote and sold in another is kept on one inventory
    ledger. Its P&L is unconverted/unresolved, never split into two FIFOs and
    never reported as zero.
    """
    usable = [
        row for row in events
        if row.get("kind") in ("buy", "sell") and row.get("split_part") != "matched_inventory_only"
    ]
    by_mint = {}
    for row in usable:
        by_mint.setdefault(row.get("mint"), []).append(row)
    grouped = {USDC: [], WSOL: []}
    cross_currency = []
    for mint, rows in by_mint.items():
        settlements = {settlement_of(row) for row in rows}
        if len(settlements) > 1:
            cross_currency.extend(rows)
            continue
        grouped[next(iter(settlements))].extend(rows)
    by_asset = {}
    if grouped[USDC]:
        by_asset["USDC"] = _single_asset_worksheet(grouped[USDC], production=production)
    if grouped[WSOL]:
        by_asset["SOL"] = _single_asset_worksheet(grouped[WSOL], production=production)
    cross_sells = sum(1 for row in cross_currency if row.get("kind") == "sell")
    note = (
        "Cross-currency inventory is per token; unconverted P&L is unresolved, never zero."
        if cross_currency else None
    )
    attached = False
    for worksheet in by_asset.values():
        if worksheet is None:
            continue
        worksheet["cross_currency_unconverted_sales"] = cross_sells
        worksheet["cross_currency_policy"] = "unconverted_unresolved_never_zero"
        if note:
            worksheet["cross_currency_note"] = note
        if not attached and cross_sells:
            worksheet["unresolved_basis_sales"] = int(worksheet.get("unresolved_basis_sales") or 0) + cross_sells
            attached = True
    if cross_currency and not by_asset:
        sells = sum(1 for row in cross_currency if row.get("kind") == "sell")
        return {
            "SOL": {
                **empty_sol_worksheet(unresolved=sells, known=0),
                "cross_currency_unconverted_sales": sells,
                "cross_currency_policy": "unconverted_unresolved_never_zero",
                "cross_currency_note": note,
            }
        }
    return {asset: worksheet for asset, worksheet in by_asset.items() if worksheet}


def _mixed_wrapper(by_asset, *, oracle):
    sol = by_asset.get("SOL") or {}
    usdc = by_asset.get("USDC") or {}
    return {
        "by_quote_asset": by_asset,
        "not_fx": True,
        "settlement_asset": "mixed",
        "total_profit_sol": sol.get("total_profit_sol"),
        "total_profit_usdc": usdc.get("total_profit_usdc"),
        "total_gross_profit_sol": sol.get("total_gross_profit_sol"),
        "total_fees_and_tips_sol": sol.get("total_fees_and_tips_sol"),
        "sale_fifo_basis_sol": list(sol.get("sale_fifo_basis_sol") or []),
        "sale_net_profit_sol": list(sol.get("sale_net_profit_sol") or []),
        "sale_fifo_basis_usdc": list(usdc.get("sale_fifo_basis_usdc") or []),
        "sale_net_profit_usdc": list(usdc.get("sale_net_profit_usdc") or []),
        "sale_rows": list(sol.get("sale_rows") or []) + list(usdc.get("sale_rows") or []),
        "unresolved_basis_sales": sum(int((item or {}).get("unresolved_basis_sales") or 0) for item in by_asset.values()),
        "known_cost_trades": sum(int((item or {}).get("known_cost_trades") or 0) for item in by_asset.values()),
        "known_cost_sales": sum(int((item or {}).get("known_cost_sales") or 0) for item in by_asset.values()),
        "result_scope": "conditional_on_captured_inventory",
        "fee_allocation": FEE_ALLOCATION,
        "oracle": oracle,
    }


def settlement_aware_worksheet(events):
    """Production worksheet. Mixed SOL+USDC stays per quote asset with no FX."""
    by_asset = worksheets_by_quote_asset(events, production=True)
    if not by_asset:
        return None
    if len(by_asset) == 1:
        asset, worksheet = next(iter(by_asset.items()))
        inner = {key: value for key, value in worksheet.items() if key != "by_quote_asset"}
        worksheet["by_quote_asset"] = {asset: inner}
        return worksheet
    return _mixed_wrapper(by_asset, oracle="production-mixed-no-fx-v1")


def independent_settlement_worksheet(events):
    """Independent worksheet. Mixed SOL+USDC stays per quote asset with no FX."""
    by_asset = worksheets_by_quote_asset(events, production=False)
    if not by_asset:
        return None
    if len(by_asset) == 1:
        asset, worksheet = next(iter(by_asset.items()))
        inner = {key: value for key, value in worksheet.items() if key != "by_quote_asset"}
        worksheet["by_quote_asset"] = {asset: inner}
        return worksheet
    return _mixed_wrapper(by_asset, oracle="independent-mixed-no-fx-v1")


def map_decoder_trade(row, *, address, seconds, timestamp_missing, role, window_qualified, unresolved_order):
    settlement = row.get("settlement_mint") or WSOL
    mapped = {
        "kind": row["kind"],
        "units": str(row.get("quantity_raw") or "0"),
        "wallet_fee_sol": str(
            row.get("fees_and_tips_sol")
            if row.get("fees_and_tips_sol") not in (None, "")
            else row.get("fee_sol") or "0"
        ),
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
        "undecoded_buy": bool(row.get("undecoded_buy") or row.get("kind") == "undecoded_buy"),
        "order": row.get("order") if isinstance(row.get("order"), int) else row.get("transaction_index"),
        "timestamp": row.get("timestamp") or row.get("block_time"),
        "observed_pre_quantity_raw": row.get("observed_pre_quantity_raw"),
        "observed_post_quantity_raw": row.get("observed_post_quantity_raw"),
        "network_fee_sol": str(row["network_fee_sol"]) if row.get("network_fee_sol") not in (None, "") else None,
        "tips_sol": str(row["tips_sol"]) if row.get("tips_sol") not in (None, "") else None,
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
