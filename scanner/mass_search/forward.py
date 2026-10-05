"""Quote-only forward comparison helpers. No signing or fill claims."""
from __future__ import annotations

from decimal import Decimal

from .metrics import earliest_quote_request_seconds, format_decimal, unavailable_exit


def simulate_fixed_entry_first_sale(*, capital_sol, entry_sol, open_positions, max_open,
                                    notification_receipt_seconds, decode_completed_seconds,
                                    reaction_delay_seconds, quote_request_seconds, quote_available,
                                    exit_quote_available, remaining_units="0"):
    if quote_request_seconds < earliest_quote_request_seconds(
        notification_receipt_seconds=notification_receipt_seconds,
        decode_completed_seconds=decode_completed_seconds,
        reaction_delay_seconds=reaction_delay_seconds,
    ):
        return {"accepted": False, "reason": "quote_before_deadline"}
    if open_positions >= max_open:
        return {"accepted": False, "reason": "max_open_positions"}
    if Decimal(str(capital_sol)) < Decimal(str(entry_sol)):
        return {"accepted": False, "reason": "unfunded_entry", "capital_sol": format_decimal(capital_sol)}
    if not quote_available:
        return {"accepted": False, "reason": "entry_quote_unavailable"}
    remaining_cash = format_decimal(Decimal(str(capital_sol)) - Decimal(str(entry_sol)))
    if not exit_quote_available:
        return {
            "accepted": True,
            "entry": True,
            "remaining_cash_sol": remaining_cash,
            "exit": unavailable_exit(open_units=remaining_units or "0", exit_quote_available=False),
            "quotes_are_fills": False,
        }
    return {
        "accepted": True,
        "entry": True,
        "remaining_cash_sol": remaining_cash,
        "exit": {"closed": True, "quotes_are_fills": False},
        "quotes_are_fills": False,
    }


def proportional_exit(*, sold_units, pre_sale_inventory, follower_units):
    if pre_sale_inventory is None:
        return {"state": "UNKNOWN", "reason": "unknown_leader_inventory", "closed_units": None}
    sold = Decimal(str(sold_units))
    inventory = Decimal(str(pre_sale_inventory))
    held = Decimal(str(follower_units))
    if inventory <= 0:
        return {"state": "UNKNOWN", "reason": "non_positive_leader_inventory"}
    raw = (sold / inventory) * held
    closed = int(raw.to_integral_value(rounding="ROUND_DOWN"))
    return {"state": "KNOWN", "closed_units": str(closed), "remaining_units": format_decimal(held - closed)}


def overlap_note(wallets_by_mint):
    overlapping = {mint: wallets for mint, wallets in wallets_by_mint.items() if len(wallets) > 1}
    return {
        "independent_validations": False if overlapping else True,
        "overlapping_mints": overlapping,
        "note": "Shared tokens are not independent proof.",
    }
