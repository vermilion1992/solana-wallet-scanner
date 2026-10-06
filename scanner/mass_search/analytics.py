"""Scoped analytics from the production pipeline. No wallet-specific constants."""
from __future__ import annotations

from decimal import Decimal
from statistics import median

from scanner.mass_search.settlement import USDC, isolate_known_cost_by_mint, settlement_of

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
        "order": index,
    }


def _sale_pnl(event, basis):
    proceeds = _decimal(event.get("proceeds_or_cost"))
    cost = _decimal(basis)
    if proceeds is None or cost is None:
        return None
    return proceeds - cost


def build_wallet_analytics(report):
    """Attach scoped metrics. Missing basis stays unresolved, not zero."""
    worksheet = report.get("worksheet") or report.get("independent_worksheet") or {}
    events = [row for row in (report.get("events") or []) if row.get("kind") in ("buy", "sell")]
    mapped = [_map_event(row, index) for index, row in enumerate(events)]
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
        })
    known, unresolved = isolate_known_cost_by_mint(known_inputs) if known_inputs else ([], [])
    unresolved_sigs = {row.get("signature") for row in unresolved}
    known_sells = [row for row in known if row["kind"] == "sell"]
    settlement = worksheet.get("settlement_asset")
    if not settlement:
        if any(item["settlement_asset"] == "USDC" for item in mapped):
            settlement = "USDC"
        elif mapped:
            settlement = "SOL"
    basis_list = worksheet.get("sale_fifo_basis_usdc") if settlement == "USDC" else worksheet.get("sale_fifo_basis_sol")
    basis_list = list(basis_list or [])
    sale_index = 0
    wins = 0
    completed = 0
    hold_seconds = []
    for item in mapped:
        if item["tx_ref"] in unresolved_sigs and item["side"] == "sell":
            item["reconciliation_or_exclusion"] = "unresolved_basis"
            item["allocated_basis"] = None
            continue
        if item["side"] == "sell" and sale_index < len(basis_list):
            item["allocated_basis"] = str(basis_list[sale_index])
            pnl = _sale_pnl(item, item["allocated_basis"])
            item["known_cost_pnl"] = str(pnl) if pnl is not None else None
            if pnl is not None:
                completed += 1
                if pnl > 0:
                    wins += 1
            sale_index += 1
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
    scoped_pnl = worksheet.get("total_profit_usdc") if settlement == "USDC" else worksheet.get("total_profit_sol")
    fees = classification.get("fee_totals") or {}
    open_positions = int((report.get("counts") or {}).get("open") or 0)
    profile = report.get("research_profile") or {}
    if profile.get("open_or_unresolved", {}).get("open_inventory_present") and not open_positions:
        open_positions = int(profile.get("open_buys_in_sample") or 0)
    win_rate = None
    if completed:
        win_rate = format(Decimal(wins) / Decimal(completed), "f")
    usdc_excludes_sol_fees = settlement == "USDC"
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
        "known_cost_realised_pnl": {
            "USDC": worksheet.get("total_profit_usdc") if settlement == "USDC" else None,
            "SOL": worksheet.get("total_profit_sol") if settlement != "USDC" else None,
            "settlement_asset": settlement,
            "usdc_excludes_sol_fees": usdc_excludes_sol_fees,
            "no_fx": True,
        },
        "completed_known_cost_positions": int(
            report.get("wallet_completed_episodes") or profile.get("completed_known_cost_positions") or completed
        ),
        "win_rate": {
            "wins": wins,
            "denominator": completed,
            "denominator_is": "completed_known_cost_positions",
            "rate": win_rate,
            "state": "KNOWN" if completed else "NOT_EVALUATED",
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
