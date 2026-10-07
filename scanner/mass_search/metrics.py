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


MATERIAL_EXIT_VERSION = "material-exit-v2"
QUANTITY_WEIGHTED_EXIT_NOTE = (
    "quantity_weighted_exit_seconds is the sold-unit-weighted time from that "
    "position's first acquisition to each sale. It is not quantity-weighted lot "
    "holding time (each lot's own open-to-close duration)."
)


def _event_seconds(event):
    if event.get("timestamp_missing") or event.get("unresolved_order"):
        return None
    value = event.get("seconds_from_start")
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _event_units(event):
    if "units" not in event or event.get("units") in (None, ""):
        return None
    try:
        units = Decimal(str(event["units"]))
    except (ArithmeticError, ValueError, TypeError):
        return None
    if not units.is_finite() or units <= 0:
        return None
    return units


def _unknown_material_exit(*, missing, mint=None, position_index=None):
    return {
        "state": "UNKNOWN",
        "missing_dependencies": list(missing),
        "first_sale_seconds": None,
        "exit_50_seconds": None,
        "exit_90_seconds": None,
        "final_hold_seconds": None,
        "position_opened_seconds": None,
        "position_closed_seconds": None,
        "position_hold_seconds": None,
        "quantity_weighted_exit_seconds": None,
        "first_sale_window_offset_seconds": None,
        "exit_50_window_offset_seconds": None,
        "exit_90_window_offset_seconds": None,
        "quantity_weighted_exit_window_offset_seconds": None,
        "sold_units": None,
        "acquired_units": None,
        "open_units": None,
        "mint": mint,
        "position_index": position_index,
        "method_version": MATERIAL_EXIT_VERSION,
        "quantity_weighted_exit_note": QUANTITY_WEIGHTED_EXIT_NOTE,
    }


def _position_material_exit(events, *, mint, position_index, completed, total_acquired=None):
    """Opening-relative timings for one mint-scoped flat-to-flat (or still-open) episode."""
    dated = []
    for event in events:
        if event.get("kind") not in ("buy", "sell"):
            continue
        seconds = _event_seconds(event)
        units = _event_units(event)
        if seconds is None:
            return _unknown_material_exit(
                missing=["missing_opening_time" if event.get("kind") == "buy" else "ambiguous_order"],
                mint=mint, position_index=position_index,
            )
        if units is None:
            return _unknown_material_exit(
                missing=["unresolved_quantities"], mint=mint, position_index=position_index,
            )
        dated.append({**event, "seconds_from_start": seconds, "units": units})
    dated.sort(key=lambda row: (row["seconds_from_start"], row.get("signature") or ""))
    if total_acquired is None:
        total_acquired = sum((row["units"] for row in dated if row["kind"] == "buy"), Decimal("0"))
    else:
        try:
            total_acquired = Decimal(str(total_acquired))
        except (ArithmeticError, ValueError, TypeError):
            return _unknown_material_exit(
                missing=["unresolved_quantities"], mint=mint, position_index=position_index,
            )
    if total_acquired <= 0:
        return _unknown_material_exit(
            missing=["acquired_units"], mint=mint, position_index=position_index,
        )
    opened = None
    first_sale_abs = t50_abs = t90_abs = closed = None
    sold = Decimal("0")
    weighted_abs = Decimal("0")
    for event in dated:
        seconds = event["seconds_from_start"]
        if event["kind"] == "buy":
            if opened is None:
                opened = seconds
            continue
        if opened is None:
            return _unknown_material_exit(
                missing=["missing_opening_time"], mint=mint, position_index=position_index,
            )
        previous = sold
        sold += event["units"]
        weighted_abs += event["units"] * seconds
        if first_sale_abs is None:
            first_sale_abs = seconds
        ratio_before = previous / total_acquired
        ratio_after = sold / total_acquired
        if t50_abs is None and ratio_after >= Decimal("0.5") and ratio_before < Decimal("0.5"):
            t50_abs = seconds
        if t90_abs is None and ratio_after >= Decimal("0.9") and ratio_before < Decimal("0.9"):
            t90_abs = seconds
        if sold == total_acquired:
            closed = seconds
    if opened is None:
        return _unknown_material_exit(
            missing=["missing_opening_time"], mint=mint, position_index=position_index,
        )
    if first_sale_abs is None:
        payload = _unknown_material_exit(
            missing=["no_supported_sale"], mint=mint, position_index=position_index,
        )
        payload["position_opened_seconds"] = opened
        payload["acquired_units"] = format_decimal(total_acquired)
        payload["sold_units"] = "0"
        payload["open_units"] = format_decimal(total_acquired)
        payload["completed"] = bool(completed)
        return payload

    def _rel(absolute):
        return None if absolute is None else absolute - opened

    final = None if closed is None else closed - opened
    return {
        "state": "KNOWN",
        "missing_dependencies": [],
        "first_sale_seconds": _rel(first_sale_abs),
        "exit_50_seconds": _rel(t50_abs),
        "exit_90_seconds": _rel(t90_abs),
        "final_hold_seconds": final,
        "position_opened_seconds": opened,
        "position_closed_seconds": closed,
        "position_hold_seconds": final,
        "quantity_weighted_exit_seconds": format_decimal((weighted_abs / sold) - opened) if sold else None,
        "first_sale_window_offset_seconds": first_sale_abs,
        "exit_50_window_offset_seconds": t50_abs,
        "exit_90_window_offset_seconds": t90_abs,
        "quantity_weighted_exit_window_offset_seconds": format_decimal(weighted_abs / sold) if sold else None,
        "sold_units": format_decimal(sold),
        "acquired_units": format_decimal(total_acquired),
        "open_units": format_decimal(total_acquired - sold),
        "mint": mint,
        "position_index": position_index,
        "completed": bool(completed),
        "method_version": MATERIAL_EXIT_VERSION,
        "quantity_weighted_exit_note": QUANTITY_WEIGHTED_EXIT_NOTE,
    }


def split_material_exit_positions(events):
    """Mint-scoped flat-to-flat episodes. Distinct mints and episodes stay separate."""
    grouped = {}
    for event in events or []:
        if event.get("kind") not in ("buy", "sell"):
            continue
        grouped.setdefault(event.get("mint"), []).append(event)
    positions = []
    for mint, rows in grouped.items():
        if any(_event_seconds(row) is None or _event_units(row) is None for row in rows):
            missing = []
            if any(_event_units(row) is None for row in rows):
                missing.append("unresolved_quantities")
            if any(row.get("kind") == "buy" and _event_seconds(row) is None for row in rows):
                missing.append("missing_opening_time")
            if any(row.get("kind") == "sell" and _event_seconds(row) is None for row in rows) or any(
                row.get("unresolved_order") or row.get("timestamp_missing") for row in rows
            ):
                missing.append("ambiguous_order")
            positions.append({
                "mint": mint,
                "position_index": 0,
                "events": rows,
                "completed": False,
                "unresolved": True,
                "missing": missing or ["ambiguous_order"],
            })
            continue
        dated = sorted(rows, key=lambda row: (_event_seconds(row), row.get("signature") or ""))
        inventory = Decimal("0")
        current = []
        opened = False
        index = 0
        for row in dated:
            units = _event_units(row)
            current.append(row)
            if row["kind"] == "buy":
                inventory += units
                opened = True
                continue
            inventory -= units
            if inventory < 0:
                positions.append({
                    "mint": mint, "position_index": index, "events": current,
                    "completed": False, "unresolved": True, "missing": ["unresolved_quantities"],
                })
                current, opened, inventory, index = [], False, Decimal("0"), index + 1
                continue
            if opened and inventory == 0:
                positions.append({
                    "mint": mint, "position_index": index, "events": current,
                    "completed": True, "unresolved": False, "missing": [],
                })
                current, opened, inventory, index = [], False, Decimal("0"), index + 1
        if current:
            positions.append({
                "mint": mint, "position_index": index, "events": current,
                "completed": False, "unresolved": False, "missing": [],
            })
    return positions


def _median_int_or_decimal(values):
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    mid = median(values)
    if isinstance(mid, Decimal):
        return mid
    if isinstance(mid, float) and mid.is_integer():
        return int(mid)
    if isinstance(mid, (int,)):
        return mid
    return mid


def material_exit_v2(events, *, total_acquired=None, transfers_unknown=False):
    """Per-position opening-relative material exit. Never pool raw units across mints."""
    if transfers_unknown:
        payload = _unknown_material_exit(missing=["transfer_or_unknown_quantity"])
        payload["aggregation_method"] = None
        payload["sample_count"] = 0
        payload["positions"] = []
        return payload
    explicit_total = total_acquired
    positions = split_material_exit_positions(events)
    if explicit_total is not None and len(positions) == 1 and not positions[0].get("unresolved"):
        computed = [_position_material_exit(
            positions[0]["events"], mint=positions[0]["mint"],
            position_index=positions[0]["position_index"], completed=positions[0]["completed"],
            total_acquired=explicit_total,
        )]
    else:
        computed = []
        for position in positions:
            if position.get("unresolved"):
                computed.append(_unknown_material_exit(
                    missing=position.get("missing") or ["ambiguous_order"],
                    mint=position.get("mint"), position_index=position.get("position_index"),
                ))
                continue
            computed.append(_position_material_exit(
                position["events"], mint=position.get("mint"),
                position_index=position.get("position_index"), completed=position.get("completed"),
            ))
    known = [row for row in computed if row.get("state") == "KNOWN"]
    if not known:
        missing = []
        for row in computed:
            missing.extend(row.get("missing_dependencies") or [])
        payload = _unknown_material_exit(missing=missing or ["no_supported_sale"])
        payload["aggregation_method"] = None
        payload["sample_count"] = 0
        payload["positions"] = computed
        return payload

    def _collect(key, *, numeric=True):
        values = [row[key] for row in known if row.get(key) is not None]
        if not values:
            return None
        if not numeric:
            return values[0] if len(values) == 1 else None
        if key == "quantity_weighted_exit_seconds":
            numbers = [Decimal(str(item)) for item in values]
            return format_decimal(_median_int_or_decimal(numbers))
        return _median_int_or_decimal(values)

    single = known[0] if len(known) == 1 else None
    payload = {
        "state": "KNOWN",
        "first_sale_seconds": _collect("first_sale_seconds"),
        "exit_50_seconds": _collect("exit_50_seconds"),
        "exit_90_seconds": _collect("exit_90_seconds"),
        "final_hold_seconds": _collect("final_hold_seconds"),
        "position_opened_seconds": single["position_opened_seconds"] if single else None,
        "position_closed_seconds": single["position_closed_seconds"] if single else None,
        "position_hold_seconds": _collect("final_hold_seconds"),
        "quantity_weighted_exit_seconds": _collect("quantity_weighted_exit_seconds"),
        "first_sale_window_offset_seconds": single["first_sale_window_offset_seconds"] if single else None,
        "exit_50_window_offset_seconds": single["exit_50_window_offset_seconds"] if single else None,
        "exit_90_window_offset_seconds": single["exit_90_window_offset_seconds"] if single else None,
        "quantity_weighted_exit_window_offset_seconds": (
            single["quantity_weighted_exit_window_offset_seconds"] if single else None
        ),
        "sold_units": single["sold_units"] if single else None,
        "acquired_units": single["acquired_units"] if single else None,
        "open_units": single["open_units"] if single else None,
        "method_version": MATERIAL_EXIT_VERSION,
        "quantity_weighted_exit_note": QUANTITY_WEIGHTED_EXIT_NOTE,
        "aggregation_method": "single" if len(known) == 1 else "median",
        "sample_count": len(known),
        "positions": computed,
        "missing_dependencies": [],
    }
    return payload


def material_exit_v1(events, *, total_acquired=None, transfers_unknown=False):
    """Compatibility entry point. Semantics are material-exit-v2 (opening-relative)."""
    return material_exit_v2(events, total_acquired=total_acquired, transfers_unknown=transfers_unknown)


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
