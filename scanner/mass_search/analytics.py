"""Scoped analytics from the production pipeline. No wallet-specific constants."""
from __future__ import annotations

from decimal import Decimal
from statistics import median

from scanner.mass_search.settlement import USDC, isolate_known_cost_by_mint, settlement_of, _ordered_rows

ANALYTICS_KIND = "wallet-analytics-v1"


def _decimal(value):
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _map_event(row, index=0):
    usdc_amount = row.get("amount_usdc") or row.get("consideration_usdc")
    settlement = "USDC" if (settlement_of(row) == USDC or usdc_amount not in (None, "")) else "SOL"
    quantity = row.get("quantity_raw") or row.get("units") or row.get("amount")
    cost = row.get("amount_usdc") or row.get("consideration_usdc") if settlement == "USDC" else (
        row.get("amount_sol") or row.get("consideration_sol")
    )
    timestamp = row.get("timestamp") or row.get("block_time")
    return {
        "tx_ref": row.get("signature") or row.get("tx_ref"),
        "timestamp": timestamp,
        "seconds_from_start": row.get("seconds_from_start"),
        "token": row.get("mint"),
        "side": row.get("kind"),
        "quantity": str(quantity) if quantity not in (None, "") else None,
        "settlement_asset": settlement,
        "proceeds_or_cost": str(cost) if cost not in (None, "") else None,
        "allocated_basis": None,
        "fee_sol": str(row["fee_sol"]) if row.get("fee_sol") not in (None, "") else (
            str(row["wallet_fee_sol"]) if row.get("wallet_fee_sol") not in (None, "") else None
        ),
        "reconciliation_or_exclusion": row.get("unresolved_basis") and "unresolved_basis" or "supported_market_trade",
        "order": row.get("order") if isinstance(row.get("order"), int) and not isinstance(row.get("order"), bool) else index,
    }


def _sale_pnl(event, basis):
    proceeds = _decimal(event.get("proceeds_or_cost"))
    cost = _decimal(basis)
    if proceeds is None or cost is None:
        return None
    return proceeds - cost


def _display_amount(value):
    if value in (None, ""):
        return None
    quantized = Decimal(str(value)).quantize(Decimal("0.000000001"))
    text = format(quantized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _sale_lookup(worksheet):
    rows = []
    if worksheet.get("sale_rows"):
        rows.extend(worksheet["sale_rows"])
    for part in (worksheet.get("by_quote_asset") or {}).values():
        if part and part.get("sale_rows"):
            rows.extend(part["sale_rows"])
    lookup = {}
    for row in rows:
        key = (row.get("signature"), row.get("split_part") or "matched")
        lookup[key] = row
    return lookup


def _inject_opening_inventory(rows):
    """Mirror decoder opening-inventory injection so win-rate uses clean episodes."""
    from decimal import Decimal

    by_mint = {}
    for row in rows:
        by_mint.setdefault(row.get("mint"), []).append(row)
    injected = []
    for mint, mint_rows in by_mint.items():
        first_buy = next((row for row in mint_rows if row.get("kind") == "buy"), None)
        pre = (first_buy or {}).get("observed_pre_quantity_raw")
        try:
            opening = Decimal(str(pre)) if pre not in (None, "") else Decimal("0")
        except Exception:
            opening = Decimal("0")
        if first_buy and opening > 0:
            injected.append({
                "kind": "opening_unknown",
                "opening_unknown": True,
                "units": str(opening),
                "mint": mint,
                "seconds_from_start": (first_buy.get("seconds_from_start") or 0) - 1,
                "order": -1,
                "signature": f"opening-inventory:{mint}",
            })
        injected.extend(mint_rows)
    return injected


def _completed_positions(report, profile, fallback):
    if report.get("wallet_completed_episodes") is not None:
        return int(report["wallet_completed_episodes"])
    if profile.get("completed_known_cost_positions") is not None:
        return int(profile["completed_known_cost_positions"])
    return int(fallback or 0)


def completed_episode_pnls(known_rows, sale_by_key):
    """Net P&L of each completed flat-to-flat position. Open-position sales are excluded."""
    grouped = {}
    for row in known_rows:
        if row.get("unresolved_basis"):
            continue
        grouped.setdefault(row.get("mint"), []).append(row)
    pnls = []
    for rows in grouped.values():
        inventory = Decimal("0")
        opened = False
        episode_pnl = Decimal("0")
        episode_has_sale = False
        for event in _ordered_rows(rows):
            units = Decimal(str(event.get("units") or event.get("quantity") or 0))
            if event.get("kind") == "buy":
                inventory += units
                opened = True
                continue
            if event.get("kind") != "sell":
                continue
            key = (event.get("signature"), event.get("split_part") or "matched")
            sale = sale_by_key.get(key)
            pnl = _decimal((sale or {}).get("net_profit")) if sale else _decimal(event.get("known_cost_pnl") or event.get("net_profit"))
            if pnl is not None:
                episode_pnl += pnl
                episode_has_sale = True
            inventory -= units
            if not opened or inventory != 0:
                continue
            role = event.get("role")
            qualified = event.get("window_qualified")
            if role is None and qualified is None:
                in_window = True
            else:
                in_window = role == "in_report" or bool(qualified)
            clean = (
                event.get("whole_sale_pnl_resolved") is not False
                and not event.get("partial_known_cost")
                and not event.get("not_clean_episode")
                and not event.get("opening_inventory_consumed")
                and not event.get("unresolved_basis")
            )
            if in_window and episode_has_sale and clean:
                pnls.append(episode_pnl)
            opened = False
            episode_pnl = Decimal("0")
            episode_has_sale = False
    return pnls


def build_wallet_analytics(report):
    """Attach scoped metrics. Missing basis stays unresolved, not zero."""
    worksheet = report.get("worksheet") or report.get("independent_worksheet") or {}
    events = [row for row in (report.get("events") or []) if row.get("kind") in ("buy", "sell")]
    known_inputs = []
    for row in events:
        known_inputs.append({
            "kind": row["kind"],
            "units": str(row.get("quantity_raw") or row.get("units") or "0"),
            "mint": row.get("mint"),
            "seconds_from_start": row.get("seconds_from_start") or 0,
            "signature": row.get("signature"),
            "settlement_mint": row.get("settlement_mint"),
            "consideration_usdc": row.get("amount_usdc") or row.get("consideration_usdc"),
            "consideration_sol": row.get("amount_sol") or row.get("consideration_sol"),
            "wallet_fee_sol": row.get("fee_sol") or row.get("wallet_fee_sol"),
            "timestamp": row.get("timestamp") or row.get("block_time"),
            "order": row.get("order"),
            "observed_pre_quantity_raw": row.get("observed_pre_quantity_raw"),
            "not_clean_episode": row.get("not_clean_episode"),
            "opening_inventory_consumed": row.get("opening_inventory_consumed"),
            "partial_known_cost": row.get("partial_known_cost"),
            "whole_sale_pnl_resolved": row.get("whole_sale_pnl_resolved"),
        })
    if known_inputs:
        known_inputs = _inject_opening_inventory(known_inputs)
        known, unresolved = isolate_known_cost_by_mint(known_inputs)
    else:
        known, unresolved = [], []
    # Trades are the FIFO split rows, not the original unsplit sells.
    split_rows = sorted(
        list(known) + list(unresolved),
        key=lambda row: (
            row.get("seconds_from_start") or 0,
            row.get("order") if isinstance(row.get("order"), int) and not isinstance(row.get("order"), bool) else 0,
            row.get("signature") or "",
            row.get("unresolved_basis") is True,
        ),
    )
    mapped = [_map_event(row, index) for index, row in enumerate(split_rows)]
    settlement = worksheet.get("settlement_asset")
    if not settlement:
        if any(item["settlement_asset"] == "USDC" for item in mapped):
            settlement = "USDC"
        elif mapped:
            settlement = "SOL"
    sale_by_key = _sale_lookup(worksheet)
    mint_pnl = {}
    hold_seconds = []
    for item, source in zip(mapped, split_rows):
        if source.get("unresolved_basis"):
            item["reconciliation_or_exclusion"] = "unresolved_basis"
            item["allocated_basis"] = None
            item["known_cost_pnl"] = None
            item["unmatched_quantity"] = str(source.get("unmatched_quantity") or source.get("units") or "")
            item["whole_sale_pnl_resolved"] = False
            item["result_scope"] = "conditional_on_captured_inventory"
            item["split_part"] = source.get("split_part") or "unresolved"
            continue
        if item["side"] != "sell":
            continue
        key = (source.get("signature") or item.get("tx_ref"), source.get("split_part") or "matched")
        sale = sale_by_key.get(key)
        if sale:
            item["allocated_basis"] = _display_amount(sale.get("basis"))
            item["known_cost_pnl"] = _display_amount(sale.get("net_profit"))
            item["gross_pnl"] = _display_amount(sale.get("gross_profit"))
            item["fees_and_tips"] = _display_amount(sale.get("fees_and_tips"))
            item["split_part"] = sale.get("split_part") or "matched"
            pnl = _decimal(sale.get("net_profit"))
        else:
            item["allocated_basis"] = None
            item["known_cost_pnl"] = None
            item["split_part"] = source.get("split_part") or "matched"
            pnl = None
        item["whole_sale_pnl_resolved"] = source.get("whole_sale_pnl_resolved") is True
        item["result_scope"] = "conditional_on_captured_inventory"
        item["partial_known_cost"] = bool(source.get("partial_known_cost"))
        if pnl is not None:
            mint = source.get("mint") or item.get("token")
            mint_pnl[mint] = mint_pnl.get(mint, Decimal("0")) + pnl
    episode_pnls = completed_episode_pnls(
        [row for row in split_rows if not row.get("unresolved_basis")],
        sale_by_key,
    )
    exit_diag = report.get("material_exit") or {}
    sample_count = exit_diag.get("sample_count")
    if sample_count in (None, "") and exit_diag.get("final_hold_seconds") is not None:
        sample_count = 1
    if exit_diag.get("final_hold_seconds") is not None:
        hold_seconds.append(int(exit_diag["final_hold_seconds"]))
    hold_n = int(sample_count or len(hold_seconds) or 0)
    median_hold = None
    if hold_seconds:
        median_hold = int(median(hold_seconds))
    elif exit_diag.get("final_hold_seconds") is not None:
        median_hold = int(exit_diag["final_hold_seconds"])
    classification = report.get("classification") or {}
    counts = classification.get("counts") or {}
    coverage = report.get("coverage") or {}
    window = report.get("window") or {}
    by_quote = worksheet.get("by_quote_asset") or {}
    if settlement == "mixed" or len(by_quote) > 1:
        scoped_pnl = None
        settlement = "mixed"
    elif settlement == "USDC":
        scoped_pnl = worksheet.get("total_profit_usdc")
        if scoped_pnl in (None, "") and "USDC" in by_quote:
            scoped_pnl = (by_quote["USDC"] or {}).get("total_profit_usdc")
    else:
        scoped_pnl = worksheet.get("total_profit_sol")
        if scoped_pnl in (None, "") and "SOL" in by_quote:
            scoped_pnl = (by_quote["SOL"] or {}).get("total_profit_sol")
    fees = classification.get("fee_totals") or {}
    open_positions = int((report.get("counts") or {}).get("open") or 0)
    profile = report.get("research_profile") or {}
    if profile.get("open_or_unresolved", {}).get("open_inventory_present") and not open_positions:
        open_positions = int(profile.get("open_buys_in_sample") or 0)
    positions = len(episode_pnls)
    official = _completed_positions(report, profile, positions)
    if official and positions and official != positions:
        # Same set: prefer the clean-episode P&L list; never invent extra wins.
        positions = min(official, positions)
        episode_pnls = episode_pnls[:positions]
    elif official and not episode_pnls:
        positions = official
    wins = sum(1 for value in episode_pnls if value > 0)
    if wins > positions:
        wins = positions
    win_rate = None
    if positions:
        win_rate = format(Decimal(wins) / Decimal(positions), "f")
    usdc_excludes_sol_fees = settlement == "USDC"
    known_pnl = {
        "USDC": None,
        "SOL": None,
        "settlement_asset": settlement,
        "usdc_excludes_sol_fees": usdc_excludes_sol_fees,
        "no_fx": True,
    }
    if "USDC" in by_quote:
        known_pnl["USDC"] = (by_quote["USDC"] or {}).get("total_profit_usdc")
    elif settlement == "USDC":
        known_pnl["USDC"] = worksheet.get("total_profit_usdc")
    if "SOL" in by_quote:
        known_pnl["SOL"] = (by_quote["SOL"] or {}).get("total_profit_sol")
        known_pnl["SOL_gross"] = (by_quote["SOL"] or {}).get("total_gross_profit_sol")
        known_pnl["SOL_fees_and_tips"] = (by_quote["SOL"] or {}).get("total_fees_and_tips_sol")
    elif settlement == "SOL":
        known_pnl["SOL"] = worksheet.get("total_profit_sol")
        known_pnl["SOL_gross"] = worksheet.get("total_gross_profit_sol")
        known_pnl["SOL_fees_and_tips"] = worksheet.get("total_fees_and_tips_sol")
    return {
        "kind": ANALYTICS_KIND,
        "address": report.get("address"),
        "captured_period": {
            "start": window.get("start") or window.get("start_inclusive"),
            "end": window.get("end") or window.get("end_exclusive"),
            "note": "Coverage of captured transactions is not completeness of wallet history.",
        },
        "scope": {
            "population": "supported_closed_subset_on_captured_page",
            "history_complete": False,
            "transactions_in_capture": int(classification.get("transactions") or coverage.get("transactions") or 0),
            "decoded_swaps": int(coverage.get("decoded_swaps") or len(events)),
            "not": "complete_wallet_history",
        },
        "trades": mapped,
        "known_cost_realised_pnl": known_pnl,
        "completed_known_cost_positions": positions,
        "sale_count": int(profile.get("sale_count") or 0),
        "win_rate": {
            "wins": wins,
            "denominator": positions,
            "denominator_is": "completed_known_cost_positions",
            "rate": win_rate,
            "state": "KNOWN" if positions else "NOT_EVALUATED",
            "same_set": True,
            "bounded_unit_interval": True,
        },
        "median_hold": {
            "seconds": median_hold,
            "sample_count": hold_n,
            "method": exit_diag.get("aggregation_method") or "median_of_completed_known_cost_holds",
            "method_version": exit_diag.get("method_version") or "material-exit-v2",
            "open_positions_excluded": True,
            "n_equals_one_disclosed": hold_n == 1,
            "note": "n=1 is one completed position, not a wallet-wide median." if hold_n == 1 else None,
        },
        "t90": {
            "seconds": exit_diag.get("exit_90_seconds"),
            "method_version": exit_diag.get("method_version") or "material-exit-v2",
            "sample_count": hold_n,
        },
        "open_positions": open_positions,
        "unresolved_basis_sales": len(unresolved),
        "rewards": {
            "holder_fee_distributions": int(counts.get("pump_holder_fee_distribution") or 0),
            "are_not_trading_pnl": True,
        },
        "attributable_fees": {
            "fee_sol": (fees or {}).get("fee_sol"),
            "not_pnl": True,
            "sol_fees_not_converted_into_usdc": usdc_excludes_sol_fees,
        },
        "scoped_pnl": scoped_pnl,
        "scoped_pnl_unit": settlement,
        "reconciliation": (report.get("worksheet_reconciliation") or {}).get("status"),
        "failed_on_chain": int(counts.get("failed_on_chain") or coverage.get("failed_transactions") or 0),
        "unsupported_or_unresolved_inner": int(counts.get("inner_pumpswap_without_reviewed_outer") or 0),
        "result_scope": "conditional_on_captured_inventory",
        "visible_report": report.get("visible_report") is True,
        "safe_to_copy": False,
        "PRODUCT_READY": False,
        "unrealised_pnl": None,
        "unrealised_pnl_state": "NOT_EVALUATED",
        "unrealised_reason": "No reliable valuation feed in this offline path.",
    }
