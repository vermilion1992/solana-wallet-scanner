"""Shared qualification, coverage, audit-fingerprint and ledger gates.

Accounting policy version is part of the audit content fingerprint. A changed
policy, capture, window, transaction set or completed-episode ledger requires a
new audit. The worksheet total is never the qualifying value.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from statistics import median

ACCOUNTING_POLICY_VERSION = (
    "completed-episode-ledger-v1+asset-atomic-v1+coverage-count-and-value-v1+"
    "audit-1to1-v1"
)

# Asset-specific atomic units. Tolerances are integer atomics, then converted.
# Rounding policy: quantize to the asset quantum with ROUND_HALF_EVEN (banker's
# rounding). Comparison uses the integer atomic difference after that quantize.
# SOL quantum is 1 lamport (1e-9). USDC quantum is 1 base unit (1e-6).
ATOMIC_UNITS = {
    "SOL": Decimal("0.000000001"),
    "USDC": Decimal("0.000001"),
}
ATOMIC_TOLERANCE = {
    "SOL": 2,   # 2 lamports
    "USDC": 2,  # 2 USDC base units
}
ROUNDING_POLICY = (
    "Quantize each amount to the asset quantum (SOL 1e-9 / USDC 1e-6) with "
    "ROUND_HALF_EVEN. Two values agree when the absolute atomic difference is "
    "at most 2 units of that asset. Never apply a SOL lamport tolerance to USDC."
)

COVERAGE_LEAD_SHARE = Decimal("0.99")
COVERAGE_WATCH_SHARE = Decimal("0.95")
STRONGER_MIN_EPISODES = 20
STRONGER_MIN_MINTS = 3
STRONGER_MIN_ACTIVE_DAYS = 3
STRONGER_MIN_SPAN_DAYS = 7
CROSS_CURRENCY_SENSITIVITY = "cross-currency sensitivity not established"
SENSITIVITY_NOT_ESTABLISHED = "sensitivity not established"
REQUIRED_EPISODE_COMPONENTS = ("acquisition", "proceeds", "costs", "net")
CONCENTRATED_LABEL = "positive subset; highly concentrated; negative excluding largest winner"
POSITIVE_SUBSET_LABEL = "positive subset"
SYNTHETIC_CORPUS = "SYNTHETIC"
DISPLAY_QUANTUM = Decimal("0.000000001")


def _decimal(value):
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _display_decimal(value):
    if value in (None, ""):
        return None
    quantized = Decimal(str(value)).quantize(DISPLAY_QUANTUM)
    text = format(quantized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def asset_quantum(unit):
    return ATOMIC_UNITS.get(unit or "SOL", ATOMIC_UNITS["SOL"])


def atomic_tolerance(unit):
    quantum = asset_quantum(unit)
    count = ATOMIC_TOLERANCE.get(unit or "SOL", 2)
    return quantum * count


def quantize_asset(value, unit):
    amount = _decimal(value)
    if amount is None:
        return None
    return amount.quantize(asset_quantum(unit), rounding=ROUND_HALF_EVEN)


def amounts_agree(left, right, unit):
    a, b = quantize_asset(left, unit), quantize_asset(right, unit)
    if a is None or b is None:
        return False
    quantum = asset_quantum(unit)
    delta_atomics = abs(a - b) / quantum
    return delta_atomics <= ATOMIC_TOLERANCE.get(unit or "SOL", 2)


def tolerance_text(unit):
    unit = unit or "SOL"
    count = ATOMIC_TOLERANCE.get(unit, 2)
    if unit == "USDC":
        return f"{count} USDC base units"
    if unit == "SOL":
        return f"{count} lamports"
    return f"{count} {unit} atomic units"


def even_sample_median(values):
    """Statistical median: mid value for odd n, mean of the two central values for even n."""
    ordered = [Decimal(str(item)) for item in values if item not in (None, "")]
    if not ordered:
        return None
    return median(ordered)


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _window_bounds(report):
    window = (report or {}).get("window") or {}
    return {
        "start": window.get("start") or window.get("start_inclusive"),
        "end": window.get("end") or window.get("end_exclusive"),
    }


def raw_capture_hashes(report=None, entry=None):
    hashes = []
    if entry:
        if entry.get("sha256"):
            hashes.append(str(entry["sha256"]))
        for page in entry.get("pages") or []:
            digest = page.get("raw_sha256") or page.get("sha256")
            if digest:
                hashes.append(str(digest))
    report = report or {}
    if report.get("capture_sha256"):
        hashes.append(str(report["capture_sha256"]))
    for digest in report.get("raw_capture_hashes") or []:
        if digest:
            hashes.append(str(digest))
    return sorted(set(hashes))


def ordered_transaction_ids(report):
    seen = []
    for event in (report or {}).get("events") or []:
        signature = event.get("signature")
        if signature and signature not in seen:
            seen.append(signature)
    if not seen:
        for signature in (report or {}).get("ordered_transaction_set") or []:
            if signature and signature not in seen:
                seen.append(signature)
    return seen


def completed_episode_ledger(report, profile=None):
    """The explicit qualifying ledger: completed flat-to-flat episodes only."""
    if report and "completed_episode_ledger" in report:
        return list(report.get("completed_episode_ledger") or [])
    if profile and "completed_episode_ledger" in profile:
        return list(profile.get("completed_episode_ledger") or [])
    episodes = []
    for item in (report or {}).get("completed_episode_pnls") or []:
        if isinstance(item, dict):
            episodes.append(dict(item))
        else:
            episodes.append({"net": str(item)})
    return episodes


def episode_membership_key(episode):
    return "|".join([
        str(episode.get("mint") or ""),
        str(episode.get("close_signature") or episode.get("close") or ""),
        str(episode.get("net") or ""),
        str(episode.get("unit") or episode.get("settlement_asset") or ""),
        str(episode.get("basis") or episode.get("acquisition") or ""),
        str(episode.get("proceeds") or ""),
        str(episode.get("costs") or episode.get("verified_costs") or ""),
    ])


def compute_audit_fingerprint(report=None, *, entry=None, profile=None, episodes=None):
    if entry is None and (report or {}).get("address"):
        try:
            from scanner.mass_search.capture_catalog import catalog_by_address
            entry = catalog_by_address().get(report.get("address"))
        except Exception:
            entry = None
    window = _window_bounds(report or {})
    hashes = raw_capture_hashes(report, entry)
    tx_ids = ordered_transaction_ids(report or {})
    ledger = episodes if episodes is not None else completed_episode_ledger(report, profile)
    membership = [episode_membership_key(item) for item in ledger]
    payload = {
        "raw_capture_hashes": hashes,
        "reporting_window": window,
        "ordered_transaction_set": _sha256_text("\n".join(tx_ids)),
        "ordered_transaction_count": len(tx_ids),
        "completed_episode_ledger": _sha256_text("\n".join(membership)),
        "completed_episode_count": len(ledger),
        "accounting_policy_version": ACCOUNTING_POLICY_VERSION,
    }
    payload["fingerprint"] = _sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return payload


def audit_fingerprint_matches(audit, fingerprint):
    if not isinstance(audit, dict) or not isinstance(fingerprint, dict):
        return False
    stored = audit.get("content_fingerprint") or audit.get("fingerprint")
    if isinstance(stored, dict):
        stored_id = stored.get("fingerprint")
        stored_policy = stored.get("accounting_policy_version")
        stored_window = stored.get("reporting_window")
        stored_raw = stored.get("raw_capture_hashes")
        stored_tx = stored.get("ordered_transaction_set")
        stored_ledger = stored.get("completed_episode_ledger")
    else:
        stored_id = stored
        stored_policy = audit.get("accounting_policy_version")
        stored_window = audit.get("reporting_window")
        stored_raw = audit.get("raw_capture_hashes")
        stored_tx = audit.get("ordered_transaction_set")
        stored_ledger = audit.get("completed_episode_ledger_fingerprint")
    if not stored_id or stored_id != fingerprint.get("fingerprint"):
        return False
    if stored_policy and stored_policy != fingerprint.get("accounting_policy_version"):
        return False
    if stored_window and stored_window != fingerprint.get("reporting_window"):
        return False
    if stored_raw and list(stored_raw) != list(fingerprint.get("raw_capture_hashes") or []):
        return False
    if stored_tx and stored_tx != fingerprint.get("ordered_transaction_set"):
        return False
    if stored_ledger and stored_ledger != fingerprint.get("completed_episode_ledger"):
        return False
    return True


def bindable_independent_audit(audit, fingerprint):
    """Return the audit only when its content fingerprint matches. Otherwise None."""
    if not audit or not fingerprint:
        return None
    if not audit_fingerprint_matches(audit, fingerprint):
        return None
    return audit


def coverage_shares(report, profile=None):
    """Count and value coverage. Denominator includes unsupported suspected trading."""
    breakdown = (report or {}).get("record_breakdown") or {}
    shares = breakdown.get("unsupported_swap_share_in_window") or {}
    if not shares and profile:
        shares = profile.get("unsupported_swap_share_in_window") or {}
    by_count = _decimal(shares.get("by_count"))
    count_share = (Decimal("1") - by_count) if by_count is not None else None
    value_coverages = []
    for value in (shares.get("by_consideration") or {}).values():
        amount = _decimal(value)
        if amount is not None:
            value_coverages.append(Decimal("1") - amount)
    value_share = min(value_coverages) if value_coverages else None
    mandatory = None
    if count_share is not None and value_share is not None:
        mandatory = min(count_share, value_share)
    elif count_share is not None:
        mandatory = None
    return {
        "coverage_count_share": _display_decimal(count_share),
        "coverage_value_share": _display_decimal(value_share),
        "coverage_mandatory_share": _display_decimal(mandatory),
        "coverage_historical_share": None,
        "count_share": count_share,
        "value_share": value_share,
        "mandatory_share": mandatory,
        "denominator_includes_unsupported_suspected_trading": True,
    }


def _json_safe_gate(gate):
    safe = dict(gate)
    for key in ("count_share", "value_share", "mandatory_share"):
        if isinstance(safe.get(key), Decimal):
            safe[key] = _display_decimal(safe[key])
    return safe


def mandatory_coverage_gate(report, profile=None, *, min_share=None):
    """One shared gate: count AND value must both meet the threshold.

    Missing value coverage is not treated as 100%. The denominator includes
    unsupported suspected trading activity.
    """
    threshold = _decimal(min_share) if min_share not in (None, "") else COVERAGE_LEAD_SHARE
    shares = coverage_shares(report, profile)
    count_share = shares["count_share"]
    value_share = shares["value_share"]
    passed = (
        count_share is not None
        and value_share is not None
        and count_share >= threshold
        and value_share >= threshold
    )
    return _json_safe_gate({
        **shares,
        "threshold": _display_decimal(threshold),
        "passed": passed,
        "reason": None if passed else (
            "coverage gate requires count AND value; missing value share"
            if value_share is None or count_share is None
            else "coverage gate requires count AND value"
        ),
    })


def _parse_timestamp(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        stamp = datetime.fromtimestamp(int(value), tz=timezone.utc)
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            stamp = datetime.fromisoformat(text)
        except ValueError:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def trading_activity(events):
    """Active days and span from trading events only (buy/sell)."""
    days = []
    stamps = []
    for event in events or []:
        if event.get("kind") not in ("buy", "sell"):
            continue
        stamp = _parse_timestamp(event.get("timestamp") or event.get("block_time") or event.get("day"))
        if stamp is None:
            continue
        stamps.append(stamp)
        days.append(stamp.date().isoformat())
    unique_days = sorted(set(days))
    if not stamps:
        return {
            "active_trading_days": 0,
            "active_trading_day_list": [],
            "span_days": 0,
            "first_trade": None,
            "last_trade": None,
            "source": "trading_events",
        }
    first, last = min(stamps), max(stamps)
    span_days = (last.date() - first.date()).days
    return {
        "active_trading_days": len(unique_days),
        "active_trading_day_list": unique_days,
        "span_days": span_days,
        "first_trade": first.isoformat().replace("+00:00", "Z"),
        "last_trade": last.isoformat().replace("+00:00", "Z"),
        "source": "trading_events",
    }


def stronger_shortlist_activity_ok(activity):
    return (
        int(activity.get("active_trading_days") or 0) >= STRONGER_MIN_ACTIVE_DAYS
        and int(activity.get("span_days") or 0) >= STRONGER_MIN_SPAN_DAYS
    )


def qualifying_profit(profile, report=None):
    """Completed-episode ledger net only. Worksheet totals are never used.

    Report-level completed_episode_net / wallet_completed_episodes summaries
    are not a fallback. Those fields can contradict the bound ledger.
    """
    ledger = completed_episode_ledger(report, profile)
    if ledger:
        unit = (profile or {}).get("completed_episode_net_unit")
        amount = _decimal((profile or {}).get("completed_episode_net"))
        vector = (profile or {}).get("completed_episode_net_vector") or {}
        if amount is None or not vector:
            derived_net, derived_unit, derived_vector = episode_net_from_ledger(
                ledger, fallback_unit=unit
            )
            amount = amount if amount is not None else _decimal(derived_net)
            unit = unit or derived_unit
            vector = vector or derived_vector
        return amount, unit, vector
    unit = (profile or {}).get("completed_episode_net_unit")
    amount = _decimal((profile or {}).get("completed_episode_net"))
    vector = (profile or {}).get("completed_episode_net_vector") or {}
    return amount, unit, vector


def episode_net_from_ledger(episodes, fallback_unit=None):
    if not episodes:
        return None, fallback_unit, {}
    by_unit = {}
    for item in episodes:
        unit = item.get("unit") or item.get("settlement_asset") or fallback_unit or "SOL"
        net = _decimal(item.get("net") or item.get("pnl"))
        if net is None:
            continue
        by_unit[unit] = by_unit.get(unit, Decimal("0")) + net
    vector = {unit: _display_decimal(value) for unit, value in by_unit.items()}
    if len(by_unit) == 1:
        unit = next(iter(by_unit))
        return _display_decimal(by_unit[unit]), unit, vector
    if not by_unit:
        return None, fallback_unit, {}
    return None, "mixed", vector


def sensitivity_result(report, profile):
    """Sensitivity against the completed-episode ledger.

    A non-SOL settlement asset cannot establish an all-in sign because SOL
    costs are not converted. That blocks lead status.
    """
    amount, unit, vector = qualifying_profit(profile, report)
    if unit not in (None, "SOL") or (vector and set(vector) - {"SOL"}):
        return {
            "flips": False,
            "blocks_lead": True,
            "reason": CROSS_CURRENCY_SENSITIVITY,
            "vector": vector or ({unit: _display_decimal(amount)} if unit and amount is not None else {}),
        }
    if amount is None:
        return {
            "flips": False,
            "blocks_lead": True,
            "reason": SENSITIVITY_NOT_ESTABLISHED,
            "evidence_state": "not_established",
            "vector": vector or {},
        }
    present = False
    raw = None
    if report and "sensitivity_unverified_debits_sol" in report:
        present = True
        raw = report.get("sensitivity_unverified_debits_sol")
    elif profile and "sensitivity_unverified_debits_sol" in profile:
        present = True
        raw = profile.get("sensitivity_unverified_debits_sol")
    if not present:
        return {
            "flips": False,
            "blocks_lead": True,
            "reason": SENSITIVITY_NOT_ESTABLISHED,
            "evidence_state": "not_established",
            "vector": {"SOL": _display_decimal(amount)},
        }
    sensitivity = _decimal(raw)
    if sensitivity is None:
        return {
            "flips": False,
            "blocks_lead": True,
            "reason": SENSITIVITY_NOT_ESTABLISHED,
            "evidence_state": "not_established",
            "vector": {"SOL": _display_decimal(amount)},
        }
    if sensitivity <= 0:
        return {
            "flips": False,
            "blocks_lead": False,
            "reason": None,
            "evidence_state": "measured_zero",
            "vector": {"SOL": _display_decimal(amount)},
        }
    flips = amount > 0 and (amount - sensitivity) <= 0
    return {
        "flips": flips,
        "blocks_lead": flips,
        "reason": "unresolved adjacent debits flip the sensitivity net sign" if flips else None,
        "evidence_state": "measured",
        "vector": {"SOL": _display_decimal(amount)},
    }


def concentration_from_episodes(episodes, qualifying_net=None, qualifying_unit=None):
    """Largest-episode / mint / day dependence from the completed-episode ledger."""
    values = []
    by_mint = {}
    by_day = {}
    for item in episodes or []:
        net = _decimal(item.get("net") or item.get("pnl"))
        if net is None:
            continue
        values.append(net)
        mint = item.get("mint") or "unknown"
        by_mint[mint] = by_mint.get(mint, Decimal("0")) + net
        day = item.get("day") or item.get("close_day")
        if not day:
            stamp = _parse_timestamp(item.get("timestamp") or item.get("close_timestamp"))
            day = stamp.date().isoformat() if stamp else None
        if day:
            by_day[day] = by_day.get(day, Decimal("0")) + net
    largest = max(values) if values else None
    scoped = _decimal(qualifying_net)
    without = (scoped - largest) if scoped is not None and largest is not None else None
    largest_mint = max(by_mint, key=by_mint.get) if by_mint else None
    without_mint = (scoped - by_mint[largest_mint]) if scoped is not None and largest_mint else None
    largest_day = max(by_day, key=by_day.get) if by_day else None
    without_day = (scoped - by_day[largest_day]) if scoped is not None and largest_day else None
    label = None
    if scoped is not None and largest is not None and without is not None:
        if scoped > 0 and without < 0:
            label = CONCENTRATED_LABEL
        elif scoped > 0:
            label = POSITIVE_SUBSET_LABEL
    return {
        "largest_winner": _display_decimal(largest),
        "result_excluding_largest_winner": _display_decimal(without),
        "distinct_tokens": len(by_mint),
        "mean_net_per_episode": _display_decimal(sum(values) / len(values)) if values else None,
        "median_net_per_episode": _display_decimal(even_sample_median(values)),
        "label": label,
        "largest_episode_dependence": {
            "largest": _display_decimal(largest),
            "excluding": _display_decimal(without),
            "sign_depends_on_largest_episode": bool(scoped is not None and scoped > 0 and without is not None and without < 0),
        },
        "largest_mint_dependence": {
            "mint": largest_mint,
            "largest": _display_decimal(by_mint.get(largest_mint)) if largest_mint else None,
            "excluding": _display_decimal(without_mint),
            "sign_depends_on_largest_mint": bool(scoped is not None and scoped > 0 and without_mint is not None and without_mint < 0),
        },
        "largest_day_dependence": {
            "day": largest_day,
            "largest": _display_decimal(by_day.get(largest_day)) if largest_day else None,
            "excluding": _display_decimal(without_day),
            "sign_depends_on_largest_day": bool(scoped is not None and scoped > 0 and without_day is not None and without_day < 0),
        },
        "source": "completed_episode_ledger",
        "unit": qualifying_unit,
    }


def worksheet_episode_bridge(worksheet_total, episode_net, unit):
    worksheet = _decimal(worksheet_total)
    episode = _decimal(episode_net)
    if worksheet is None or episode is None:
        return None
    return {
        "worksheet_total": _display_decimal(worksheet),
        "completed_episode_net": _display_decimal(episode),
        "bridge": _display_decimal(worksheet - episode),
        "unit": unit,
        "note": (
            "worksheet total minus completed-episode net. "
            "The worksheet is never the qualifying value."
        ),
        "worksheet_is_not_qualifying": True,
    }


def component_bridge(app, auditor, unit):
    """Episode membership / acquisition / proceeds / cost agreement, not just net."""
    unit = unit or "SOL"
    fields = (
        ("acquisition", ("basis", "acquisition", "basis_sol")),
        ("proceeds", ("proceeds", "proceeds_sol")),
        ("costs", ("verified_costs", "costs", "verified_costs_sol")),
        ("net", ("net", "net_profit_sol")),
    )
    components = {}
    all_agree = True
    for name, keys in fields:
        app_value = next((app.get(key) for key in keys if app and app.get(key) not in (None, "")), None)
        auditor_value = next((auditor.get(key) for key in keys if auditor and auditor.get(key) not in (None, "")), None)
        if app_value in (None, "") or auditor_value in (None, ""):
            components[name] = {
                "app": None if app_value in (None, "") else str(app_value),
                "auditor": None if auditor_value in (None, "") else str(auditor_value),
                "delta": None,
                "agree": False,
                "tolerance": tolerance_text(unit),
                "reason": "required component missing; missing-on-both is not auto-agree",
            }
            all_agree = False
            continue
        app_q = quantize_asset(app_value, unit)
        auditor_q = quantize_asset(auditor_value, unit)
        delta = None if app_q is None or auditor_q is None else app_q - auditor_q
        agree = amounts_agree(app_value, auditor_value, unit)
        if not agree:
            all_agree = False
        components[name] = {
            "app": _display_decimal(app_q) if app_q is not None else None,
            "auditor": _display_decimal(auditor_q) if auditor_q is not None else None,
            "delta": _display_decimal(delta) if delta is not None else None,
            "agree": agree,
            "tolerance": tolerance_text(unit),
        }
    membership = None
    if app and auditor:
        app_close = app.get("close_signature") or app.get("close")
        auditor_close = auditor.get("close_signature") or auditor.get("close")
        app_mint = app.get("mint")
        auditor_mint = auditor.get("mint")
        exact = bool(app_mint and auditor_mint and app_close and auditor_close
                     and app_mint == auditor_mint and app_close == auditor_close)
        membership = {
            "app": {"mint": app_mint, "close_signature": app_close},
            "auditor": {"mint": auditor_mint, "close_signature": auditor_close},
            "agree": exact,
            "one_to_one": exact,
            "mint_only_fallback": False,
        }
        if not membership["agree"]:
            all_agree = False
    return {
        "unit": unit,
        "tolerance": tolerance_text(unit),
        "rounding_policy": ROUNDING_POLICY,
        "membership": membership,
        "components": components,
        "agree": all_agree,
        "required_components": list(REQUIRED_EPISODE_COMPONENTS),
    }


def aggregate_rounding_bridge(app_net, auditor_net, unit):
    """Label aggregate rounding without widening the declared 2-atomic tolerance."""
    unit = unit or "SOL"
    app_q = quantize_asset(app_net, unit)
    auditor_q = quantize_asset(auditor_net, unit)
    if app_q is None or auditor_q is None:
        return None
    delta = app_q - auditor_q
    within = amounts_agree(app_net, auditor_net, unit)
    atomics = int(abs(delta) / asset_quantum(unit))
    return {
        "app": _display_decimal(app_q),
        "auditor": _display_decimal(auditor_q),
        "delta": _display_decimal(delta),
        "delta_atomics": atomics,
        "unit": unit,
        "within_declared_tolerance": within,
        "tolerance": tolerance_text(unit),
        "rounding_policy": ROUNDING_POLICY,
        "note": (
            "Aggregate agrees within the declared 2-atomic tolerance."
            if within else
            "Aggregate differs by more than the declared 2-atomic tolerance. "
            "Do not print 'within 2'. Per-episode components may still agree. "
            "Tolerance is not widened."
        ),
    }


def format_auditor_confirmation(app_net, auditor_net, unit, *, independently_audited=False):
    """Confirmation text for the audited completed-episode scope only."""
    if not independently_audited or auditor_net in (None, ""):
        return None
    unit = unit or "SOL"
    bridge = aggregate_rounding_bridge(app_net, auditor_net, unit)
    if not bridge:
        return None
    if bridge["within_declared_tolerance"]:
        return f"auditor confirms within {tolerance_text(unit)}: {bridge['auditor']} {unit}"
    return (
        f"aggregate rounding bridge {bridge['delta']} {unit} "
        f"({bridge['delta_atomics']} atomics, not within {tolerance_text(unit)}; "
        f"app {bridge['app']} vs auditor {bridge['auditor']}; "
        "per-episode components may still agree)"
    )


def match_auditor_episode(app_episode, auditor_episodes, *, used=None):
    """Exact one-to-one close-signature + mint. No mint-only fallback."""
    used = used if used is not None else set()
    mint = (app_episode or {}).get("mint")
    close = (app_episode or {}).get("close_signature") or (app_episode or {}).get("close")
    if not mint or not close:
        return None
    for index, row in enumerate(auditor_episodes or []):
        if index in used:
            continue
        if row.get("mint") == mint and (row.get("close_signature") or row.get("close")) == close:
            used.add(index)
            return row
    return None


def exposure_outside_completed_episodes(report, profile=None):
    profile = profile or {}
    open_known = _decimal(profile.get("open_inventory_known_cost")) or _decimal((report or {}).get("open_inventory_known_cost"))
    open_unknown = _decimal(profile.get("open_inventory_unknown_cost")) or _decimal((report or {}).get("open_inventory_unknown_cost"))
    failed = _decimal((report or {}).get("failed_attempt_expenses_sol"))
    if failed is None:
        failed = _decimal(((report or {}).get("classification") or {}).get("fee_totals", {}).get("failed_fee_sol"))
    unallocated = _decimal((report or {}).get("unallocated_verified_costs_sol"))
    if unallocated is None:
        unallocated = _decimal(profile.get("unallocated_verified_costs_sol"))
    return {
        "known_cost_open_inventory": _display_decimal(open_known),
        "known_cost_open_inventory_unit": (
            (profile.get("completed_episode_net_unit") or (report or {}).get("completed_episode_net_unit"))
            if open_known is not None else None
        ),
        "inventory_of_unknown_cost": _display_decimal(open_unknown) if open_unknown is not None else None,
        "inventory_of_unknown_cost_status": "known" if open_unknown is not None else "unknown",
        "inventory_of_unknown_cost_unit": None if open_unknown is None else (
            profile.get("completed_episode_net_unit") or (report or {}).get("completed_episode_net_unit")
        ),
        "open_lots": int(profile.get("open_buys_in_sample") or 0),
        "open_lots_unit": "lots",
        "failed_attempt_expenses": _display_decimal(failed),
        "failed_attempt_expenses_unit": "SOL",
        "unallocated_verified_costs": _display_decimal(unallocated),
        "unallocated_verified_costs_unit": "SOL",
        "note": (
            "Exposure left outside the completed-episode ledger. "
            "Lot counts are not a valuation. Unknown cost stays unknown. "
            "These amounts are not subtracted twice from episode nets."
        ),
    }


def requested_history_interval(report, entry=None):
    requested = ((entry or {}).get("windows") or {})
    window = _window_bounds(report or {})
    traversed = (report or {}).get("in_window_span") or {}
    first = traversed.get("first") or traversed.get("first_timestamp") or traversed.get("start")
    last = traversed.get("last") or traversed.get("last_timestamp") or traversed.get("end")
    hours = traversed.get("hours") if first and last else None
    observed = bool(first and last)
    return {
        "requested_start": requested.get("report_start_inclusive") or window.get("start"),
        "requested_end": requested.get("report_end_exclusive") or window.get("end"),
        "traversed_start": first if observed else None,
        "traversed_end": last if observed else None,
        "hours": hours if observed else None,
        "requested_history_interval_actually_traversed": {
            "start": first if observed else None,
            "end": last if observed else None,
            "hours": hours if observed else None,
            "complete": False,
            "status": "observed" if observed else "not_evaluated",
            "note": (
                "Coverage of captured transactions is not completeness of wallet history."
                if observed else
                "Traversed interval not established. The requested reporting window is not a substitute."
            ),
        },
    }


def hold_time_stats(episodes, open_positions=None, *, now=None):
    completed_holds = []
    for item in episodes or []:
        hold = item.get("hold_seconds")
        if hold in (None, ""):
            opened = _parse_timestamp(item.get("opened_at") or item.get("open_timestamp"))
            closed = _parse_timestamp(item.get("closed_at") or item.get("close_timestamp") or item.get("timestamp"))
            if opened and closed:
                hold = int((closed - opened).total_seconds())
        if hold not in (None, ""):
            completed_holds.append(int(hold))
    ages = []
    reference = now or datetime.now(timezone.utc)
    for item in open_positions or []:
        age = item.get("age_seconds")
        if age in (None, ""):
            opened = _parse_timestamp(item.get("opened_at") or item.get("timestamp"))
            if opened:
                age = int((reference - opened).total_seconds())
        if age not in (None, ""):
            ages.append(int(age))
    return {
        "completed_episodes": {
            "median_seconds": int(median(completed_holds)) if completed_holds else None,
            "sample_count": len(completed_holds),
            "distribution_seconds": sorted(completed_holds),
            "min_seconds": min(completed_holds) if completed_holds else None,
            "max_seconds": max(completed_holds) if completed_holds else None,
        },
        "open_positions": {
            "ages_seconds": sorted(ages) if open_positions is not None else None,
            "sample_count": len(ages) if open_positions is not None else None,
            "median_age_seconds": int(median(ages)) if ages else None,
            "status": "observed" if open_positions is not None else "not_evaluated",
            "note": None if open_positions is not None else "open-position ages not evaluated",
        },
    }


def allocate_verified_costs(charges):
    """Allocate each verified cost once across closed / open / failed / other."""
    buckets = {
        "closed_episodes": Decimal("0"),
        "open_positions": Decimal("0"),
        "failed_attempts": Decimal("0"),
        "other_activity": Decimal("0"),
    }
    sensitivity = Decimal("0")
    rows = []
    seen = set()
    for item in charges or []:
        key = (
            item.get("signature"),
            item.get("recipient"),
            item.get("instruction_path") or item.get("path"),
            item.get("lamports") or item.get("sol"),
        )
        if key in seen:
            continue
        seen.add(key)
        amount = _decimal(item.get("sol"))
        if amount is None and item.get("lamports") not in (None, ""):
            amount = Decimal(str(item["lamports"])) / Decimal("1000000000")
        if amount is None:
            continue
        role = item.get("economic_role") or item.get("role")
        failed = bool(item.get("transaction_failed"))
        if role in ("unexplained_transfer", "unresolved_debit", "unresolved_debit_not_a_tip"):
            sensitivity += amount
            rows.append({**item, "allocated_to": "sensitivity_not_a_fee", "counted_as_fee": False})
            continue
        if failed and role == "network_plus_priority_fee":
            buckets["failed_attempts"] += amount
            rows.append({**item, "allocated_to": "failed_attempts", "counted_as_fee": True})
            continue
        bucket = item.get("allocate_to")
        if bucket not in buckets:
            if item.get("episode_closed"):
                bucket = "closed_episodes"
            elif item.get("open_position"):
                bucket = "open_positions"
            elif failed:
                bucket = "failed_attempts"
            else:
                bucket = "other_activity"
        buckets[bucket] += amount
        rows.append({**item, "allocated_to": bucket, "counted_as_fee": True})
    return {
        "closed_episodes_sol": _display_decimal(buckets["closed_episodes"]),
        "open_positions_sol": _display_decimal(buckets["open_positions"]),
        "failed_attempts_sol": _display_decimal(buckets["failed_attempts"]),
        "other_activity_sol": _display_decimal(buckets["other_activity"]),
        "sensitivity_unexplained_transfers_sol": _display_decimal(sensitivity),
        "no_double_subtraction": True,
        "unexplained_transfers_are_not_fees": True,
        "rows": rows,
    }


def is_synthetic_case(report, profile=None):
    corpus = (report or {}).get("corpus_kind") or (profile or {}).get("corpus_kind")
    if corpus == SYNTHETIC_CORPUS:
        return True
    if (report or {}).get("synthetic") or (profile or {}).get("synthetic"):
        return True
    if (report or {}).get("label") and "SYNTHETIC" in str(report.get("label")):
        return True
    return False


def mark_synthetic(payload, *, reason):
    marked = dict(payload)
    if marked.get("corpus_kind") != "GENUINE_REPLAY":
        marked["corpus_kind"] = SYNTHETIC_CORPUS
    marked["synthetic"] = True
    marked["synthetic_reason"] = reason
    marked["not_a_genuine_research_wallet"] = True
    marked["not_proof"] = True
    return marked
