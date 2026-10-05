"""Metric records, decimal comparison and independent diagnostic arithmetic."""
from __future__ import annotations

from decimal import Decimal, localcontext
from statistics import median

from .schema import VALUE_SCALE

METRIC_VERSION = "mass-search-metric-v1"
KNOWN_STATES = ("KNOWN", "UNKNOWN", "CONFLICT", "STALE")
KNOWN_BASES = (
    "PROVIDER_REPORTED",
    "RAW_DERIVED_SUBSET",
    "INDEPENDENTLY_RECONCILED_SUBSET",
    "STRICT_WALLET",
    "FORWARD_QUOTE_MODEL",
)
DECIMAL_RE = r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$"


def decimal_value(value):
    if value is None:
        return None
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Metric value must be a finite decimal")
    return number


def format_decimal(value):
    number = decimal_value(value)
    if number is None:
        return None
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def value_nanos(value):
    number = decimal_value(value)
    if number is None:
        return None
    scaled = (number * VALUE_SCALE).to_integral_value()
    return int(scaled)


def compare_decimal(left, right):
    return decimal_value(left).compare(decimal_value(right))


def sort_key_for_metric(value, candidate_id):
    nanos = value_nanos(value) if value is not None else None
    missing = nanos is None
    return (missing, -(nanos or 0), candidate_id)


def build_metric(*, metric_key, candidate_id, value, unit, state, basis, window, population,
                 population_count, method_version=METRIC_VERSION, observed_at, evidence_sha256,
                 missing_dependencies, source_provider, is_wallet_wide_verified=False, notes=None):
    if state not in KNOWN_STATES:
        raise ValueError("Unsupported metric state")
    if basis not in KNOWN_BASES:
        raise ValueError("Unsupported metric basis")
    if type(population_count) is not int or population_count < 0:
        raise ValueError("population_count must be a non-negative integer")
    if not isinstance(window, dict) or "start_inclusive" not in window or "end_exclusive" not in window:
        raise ValueError("Metric window must include start_inclusive and end_exclusive")
    if window["start_inclusive"] >= window["end_exclusive"]:
        raise ValueError("Metric window must have positive duration")
    evidence = list(evidence_sha256 or [])
    missing = list(missing_dependencies or [])
    if state == "KNOWN":
        if value is None:
            raise ValueError("KNOWN metrics require a decimal value")
        format_decimal(value)
        if not evidence:
            raise ValueError("KNOWN metrics require evidence hashes")
    if state in ("UNKNOWN", "CONFLICT"):
        if value is not None:
            raise ValueError(f"{state} metrics cannot carry a value")
        if not missing:
            raise ValueError(f"{state} metrics require missing dependencies")
    if basis != "STRICT_WALLET" and is_wallet_wide_verified:
        raise ValueError("Only STRICT_WALLET metrics may be wallet-wide verified")
    if is_wallet_wide_verified and (state != "KNOWN" or missing):
        raise ValueError("Wallet-wide verified metrics cannot retain unknowns")
    return {
        "metric_key": metric_key,
        "candidate_id": candidate_id,
        "value": None if value is None else format_decimal(value),
        "unit": unit,
        "state": state,
        "basis": basis,
        "window": dict(window),
        "population": population,
        "population_count": population_count,
        "method_version": method_version,
        "observed_at": observed_at,
        "evidence_sha256": evidence,
        "missing_dependencies": missing,
        "source_provider": source_provider,
        "is_wallet_wide_verified": bool(is_wallet_wide_verified),
        "notes": list(notes or []),
        "value_nanos": value_nanos(value) if state == "KNOWN" else None,
    }


def compare_to_threshold(metric, threshold_value, threshold_unit):
    """Never convert currencies or substitute proxies to force a comparison."""
    if not isinstance(metric, dict) or metric.get("state") != "KNOWN":
        return {"state": "UNKNOWN", "reason": "metric_unavailable"}
    if metric.get("unit") != threshold_unit:
        return {"state": "UNKNOWN", "reason": "currency_or_unit_mismatch",
                "convert_at_current_price": False}
    return {"state": "KNOWN", "comparison": int(compare_decimal(metric["value"], threshold_value)),
            "reason": "same_unit_direct"}


def median_hold_hours(values):
    if not values:
        return {"state": "UNKNOWN", "value": None, "population_count": 0,
                "missing_dependencies": ["eligible_closed_holds"]}
    hours = [decimal_value(item) for item in values]
    return {"state": "KNOWN", "value": format_decimal(median(hours)), "population_count": len(hours)}


def four_week_consistency(week_nets):
    if not isinstance(week_nets, list) or len(week_nets) != 4:
        return {"state": "UNKNOWN", "missing_dependencies": ["four_independent_weeks"]}
    known = []
    for week in week_nets:
        if week is None:
            return {"state": "UNKNOWN", "missing_dependencies": ["complete_week_history"]}
        known.append(decimal_value(week))
    total = sum(known, Decimal("0"))
    return {
        "state": "KNOWN",
        "positive_weeks": sum(1 for item in known if item > 0),
        "four_week_net": format_decimal(total),
        "overlapping_windows_used": False,
    }


def concentration(per_mint_net):
    nets = [decimal_value(item) for item in per_mint_net]
    total = sum(nets, Decimal("0"))
    positives = [item for item in nets if item > 0]
    largest = max(nets) if nets else Decimal("0")
    without_largest = total - largest
    gross = sum(positives, Decimal("0"))
    return {
        "net_profit": format_decimal(total),
        "net_without_largest_winner": format_decimal(without_largest),
        "largest_winner_share_of_net": None if total == 0 else format_decimal((largest / total) * 100),
        "largest_winner_share_of_gross_positive": None if gross == 0 else format_decimal((largest / gross) * 100),
        "denominators_interchangeable": False,
    }


def combined_economics(*, closed_net, known_open):
    return format_decimal(decimal_value(closed_net) + decimal_value(known_open))


def fifo_sale_results(events):
    """Independent worksheet for the package's buy/sell fee fixture. Not a second engine.

    Distinct mints keep separate inventories. Mixing them would invent a cross-mint lot.
    """
    indexed = [event for event in events if event.get("kind") in ("buy", "sell")]
    mints = {event.get("mint") for event in indexed if event.get("mint")}
    if len(mints) > 1:
        basis = []
        profits = []
        total = Decimal("0")
        for mint in sorted(mints):
            part = fifo_sale_results([event for event in events if event.get("mint") == mint])
            basis.extend(part["sale_fifo_basis_sol"])
            profits.extend(part["sale_net_profit_sol"])
            total += decimal_value(part["total_profit_sol"])
        return {
            "sale_fifo_basis_sol": basis,
            "sale_net_profit_sol": profits,
            "total_profit_sol": format_decimal(total),
            "declared_mints": sorted(mints),
        }
    with localcontext() as ctx:
        ctx.prec = 192
        lots = []
        sales = []
        for event in events:
            units = Decimal(str(event["units"]))
            if event["kind"] == "buy":
                consideration = Decimal(str(event["consideration_sol"]))
                fee = Decimal(str(event.get("wallet_fee_sol") or "0"))
                lots.append({"units": units, "unit_cost": (consideration + fee) / units})
            elif event["kind"] == "sell":
                remaining = units
                basis = Decimal("0")
                while remaining > 0:
                    if not lots:
                        raise ValueError("Sale exceeds supported inventory")
                    lot = lots[0]
                    take = min(lot["units"], remaining)
                    basis += lot["unit_cost"] * take
                    lot["units"] -= take
                    remaining -= take
                    if lot["units"] == 0:
                        lots.pop(0)
                fee = Decimal(str(event.get("wallet_fee_sol") or "0"))
                proceeds = Decimal(str(event["consideration_sol"]))
                sales.append({
                    "basis": format_decimal(basis),
                    "net_profit": format_decimal(proceeds - basis - fee),
                })
        total = sum((decimal_value(sale["net_profit"]) for sale in sales), Decimal("0"))
        return {
            "sale_fifo_basis_sol": [sale["basis"] for sale in sales],
            "sale_net_profit_sol": [sale["net_profit"] for sale in sales],
            "total_profit_sol": format_decimal(total),
        }


def material_exit_v1(events, *, total_acquired=None, transfers_unknown=False):
    """Retrospective cumulative sold / total acquired. Additional buys move the milestone."""
    if transfers_unknown:
        return {
            "state": "UNKNOWN",
            "missing_dependencies": ["transfer_or_unknown_quantity"],
            "first_sale_seconds": None,
            "exit_50_seconds": None,
            "exit_90_seconds": None,
            "final_hold_seconds": None,
        }
    acquired = Decimal("0")
    sold = Decimal("0")
    first_sale = None
    t50 = t90 = final = None
    opened = None
    closed = None
    weighted = Decimal("0")
    if total_acquired is None:
        total_acquired = sum((Decimal(str(event["units"])) for event in events if event["kind"] == "buy"), Decimal("0"))
    else:
        total_acquired = Decimal(str(total_acquired))
    if total_acquired <= 0:
        return {"state": "UNKNOWN", "missing_dependencies": ["acquired_units"]}
    for event in events:
        units = Decimal(str(event["units"]))
        seconds = int(event["seconds_from_start"])
        if event["kind"] == "buy":
            if opened is None:
                opened = seconds
            acquired += units
            continue
        if event["kind"] != "sell":
            continue
        if first_sale is None:
            first_sale = seconds
        previous = sold
        sold += units
        weighted += units * seconds
        ratio_before = previous / total_acquired
        ratio_after = sold / total_acquired
        if t50 is None and ratio_after >= Decimal("0.5") and ratio_before < Decimal("0.5"):
            t50 = seconds
        if t90 is None and ratio_after >= Decimal("0.9") and ratio_before < Decimal("0.9"):
            t90 = seconds
        if sold == total_acquired:
            closed = seconds
            # Position hold is close − open, not the sale's report-window offset.
            final = None if opened is None else seconds - opened
    return {
        "state": "KNOWN" if first_sale is not None else "UNKNOWN",
        "first_sale_seconds": first_sale,
        "exit_50_seconds": t50,
        "exit_90_seconds": t90,
        "final_hold_seconds": final,
        "position_opened_seconds": opened,
        "position_closed_seconds": closed,
        "position_hold_seconds": final,
        "quantity_weighted_exit_seconds": format_decimal(weighted / sold) if sold else None,
        "sold_units": format_decimal(sold),
        "acquired_units": format_decimal(total_acquired),
        "open_units": format_decimal(total_acquired - sold),
        "method_version": "material-exit-v1",
        "missing_dependencies": [] if first_sale is not None else ["no_supported_sale"],
    }


def earliest_quote_request_seconds(*, notification_receipt_seconds, decode_completed_seconds, reaction_delay_seconds):
    return max(int(notification_receipt_seconds), int(decode_completed_seconds)) + int(reaction_delay_seconds)


def unavailable_exit(*, open_units, exit_quote_available, last_mark_sol=None):
    if exit_quote_available:
        raise ValueError("Use a dated amount-specific quote path when a quote exists")
    return {
        "closed_units": "0",
        "open_units": format_decimal(open_units),
        "supported_liquidation_value_sol": None,
        "use_last_mark_as_realized_exit": False,
        "last_mark_sol": last_mark_sol,
    }


def transfer_sale_outcome(*, sale_proceeds_sol, fee_sol, basis_sol):
    visible = sale_proceeds_sol is not None
    if basis_sol is None:
        return {
            "sale_visible": visible,
            "realised_pnl_sol": None,
            "wallet_fee_sol": format_decimal(fee_sol),
            "zero_basis_assumed": False,
        }
    return {
        "sale_visible": visible,
        "realised_pnl_sol": format_decimal(decimal_value(sale_proceeds_sol) - decimal_value(basis_sol) - decimal_value(fee_sol)),
        "wallet_fee_sol": format_decimal(fee_sol),
        "zero_basis_assumed": False,
    }
