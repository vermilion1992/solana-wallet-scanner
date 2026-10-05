"""A/B/C funnel. Provider rank is not verification. Next-action is explicit."""
from __future__ import annotations

from decimal import Decimal

FUNNEL_KIND = "research-funnel-abc-v1"

STAGE_A = "A_worth_investigating"
STAGE_B = "B_evidence_establishes_results"
STAGE_C = "C_meets_research_criteria"


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def classify_candidate(
    *,
    provider_rank=None,
    provider_trade_count=None,
    provider_score=None,
    capture_available=False,
    profile=None,
    classification=None,
    worksheet=None,
):
    """Separate provider rank from verification. Rank-1 is one candidate."""
    profile = profile or {}
    classification = classification or {}
    counts = classification.get("counts") or {}
    market = int(profile.get("market_vs_rewards", {}).get("market_swaps") or 0)
    holder_fees = int(profile.get("market_vs_rewards", {}).get("holder_fee_distributions") or counts.get("pump_holder_fee_distribution") or 0)
    completed = int(profile.get("completed_known_cost_positions") or 0)
    scoped = profile.get("scoped_pnl")
    criteria_met = bool(profile.get("criteria_met"))
    holder_heavy = False
    if holder_fees and market:
        holder_heavy = holder_fees > market
    elif holder_fees and not market and not capture_available:
        holder_heavy = False

    a_reasons = []
    a_pass = False
    if market:
        a_pass = True
        a_reasons.append("sample_contains_market_trades")
    if provider_trade_count and int(provider_trade_count) >= 20:
        a_reasons.append("provider_trade_count_proxy_unverified")
        if not capture_available:
            a_pass = True
    if provider_score not in (None, ""):
        a_reasons.append("provider_score_is_not_verification")
    if not a_pass and capture_available:
        a_reasons.append("captured_sample_has_no_market_trades")
    if not a_pass and not capture_available:
        a_reasons.append("no_capture_and_weak_provider_proxy")

    b_reasons = []
    if completed >= 1 and scoped not in (None, ""):
        b_state = "PARTIAL" if (
            profile.get("unresolved_basis_sales") or profile.get("open_or_unresolved", {}).get("inner_unreviewed")
        ) else "ESTABLISHED"
        b_reasons.append("known_cost_completed_position_reconciled")
        if b_state == "PARTIAL":
            b_reasons.append("sample_still_has_unresolved_or_open_inventory")
    elif capture_available and market:
        b_state = "INSUFFICIENT"
        b_reasons.append("market_trades_present_but_no_known_cost_completed_position")
    elif capture_available:
        b_state = "INSUFFICIENT"
        b_reasons.append("capture_does_not_establish_trading_results")
    else:
        b_state = "UNVERIFIED"
        b_reasons.append("no_cached_history_capture")

    if holder_heavy:
        a_reasons.append("holder_fee_heavy_sample_classified_as_rewards_not_pnl")
        b_reasons.append("holder_rewards_are_not_trading_pnl")

    c_state = "NOT_EVALUATED"
    c_reasons = ["unset_thresholds_do_not_pass"]
    if profile.get("evaluated_thresholds"):
        c_state = "MET" if criteria_met else "NOT_MET"
        c_reasons = ["evaluated_local_thresholds"]
        if not criteria_met:
            c_reasons.append("one_or_more_set_thresholds_failed_or_unknown")
    if profile.get("unset_thresholds") and profile.get("evaluated_thresholds"):
        c_state = "NOT_MET"
        c_reasons.append("remaining_unset_thresholds_do_not_pass")

    next_action = _next_action(
        provider_rank=provider_rank,
        capture_available=capture_available,
        a_pass=a_pass,
        b_state=b_state,
        c_state=c_state,
        holder_heavy=holder_heavy,
        completed=completed,
        unresolved_basis=int(profile.get("unresolved_basis_sales") or 0),
    )
    return {
        "kind": FUNNEL_KIND,
        "provider_rank": provider_rank,
        "provider_rank_is_not_verification": True,
        "A": {
            "id": STAGE_A,
            "state": "YES" if a_pass else "NO",
            "reasons": a_reasons,
        },
        "B": {
            "id": STAGE_B,
            "state": b_state,
            "reasons": b_reasons,
            "completed_known_cost_positions": completed,
            "scoped_pnl": scoped,
            "scoped_pnl_unit": profile.get("scoped_pnl_unit"),
        },
        "C": {
            "id": STAGE_C,
            "state": c_state,
            "reasons": c_reasons,
            "criteria_met": criteria_met,
            "safe_to_copy": False,
        },
        "holder_fee_heavy": holder_heavy,
        "next_action": next_action,
        "PRODUCT_READY": False,
        "not_safe_to_copy": True,
    }


def _next_action(*, provider_rank, capture_available, a_pass, b_state, c_state, holder_heavy, completed, unresolved_basis):
    if capture_available and holder_heavy and completed >= 1:
        return {
            "code": "investigate_better_shortlist_candidates",
            "detail": (
                "Rank-1 sample is holder-fee-heavy but has a known-cost market close. "
                "Investigate other saved ranked-100 candidates locally before any new grant."
            ),
            "live_required": False,
        }
    if capture_available and unresolved_basis and completed >= 1:
        return {
            "code": "keep_unresolved_basis_visible_and_compare_shortlist",
            "detail": (
                "Leading/unbacked sells stay unresolved on this page. "
                "Compare other cached shortlist wallets. Earlier-page history needs a new grant."
            ),
            "live_required": False,
            "optional_grant": "earlier_page_for_unbacked_sale_or_other_shortlist_history",
        }
    if capture_available and not a_pass:
        return {
            "code": "skip_to_next_ranked_candidate",
            "detail": "This captured sample did not establish market trades. Open the next ranked-100 row.",
            "live_required": False,
        }
    if not capture_available and a_pass:
        return {
            "code": "cached_browse_only_until_grant",
            "detail": (
                "Worth investigating from provider proxies only. "
                "No cached history. A future grant is required to reconstruct trades."
            ),
            "live_required": True,
            "do_not_dispatch": True,
        }
    return {
        "code": "browse_cached_shortlist",
        "detail": "Stay on cached ranked-100 rows. Zero provider calls.",
        "live_required": False,
    }


def rank_next_candidates(rows, *, exclude_addresses=None, limit=5):
    """Prefer higher provider trade-count among unverified shortlist rows. Not verification."""
    exclude = set(exclude_addresses or [])
    scored = []
    for row in rows or []:
        address = row.get("address")
        if not address or address in exclude:
            continue
        if row.get("capture_available"):
            continue
        trade_count = _int((row.get("metrics") or {}).get("trade_count") or row.get("trade_count")) or 0
        score = Decimal(str(row.get("provider_score") or (row.get("metrics") or {}).get("provider_score") or "0"))
        scored.append((trade_count, score, -int(row.get("provider_rank") or row.get("shortlist_rank") or 10**6), row))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [item[3] for item in scored[:limit]]
