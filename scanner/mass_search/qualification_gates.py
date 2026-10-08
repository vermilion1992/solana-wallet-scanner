"""Shared qualification, coverage, audit-fingerprint and ledger gates.

Accounting policy version is part of the audit content fingerprint. A changed
policy, capture, window, transaction set or completed-episode ledger requires a
new audit. The worksheet total is never the qualifying value.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from statistics import median

ACCOUNTING_POLICY_VERSION = (
    "completed-episode-ledger-v1+asset-atomic-v1+coverage-count-and-value-v1+"
    "audit-1to1-v1+result-relevant-coverage-v1+gt15-v1+dc-verify-c85388e-v1"
)

# Asset-specific atomic units. Tolerances are integer atomics, then converted.
# Rounding policy: quantize to the asset quantum with ROUND_HALF_EVEN (banker's
# rounding). Comparison uses the integer atomic difference after that quantize.
# SOL quantum is 1 lamport (1e-9). USDC/USDT quantum is 1 base unit (1e-6).
ATOMIC_UNITS = {
    "SOL": Decimal("0.000000001"),
    "USDC": Decimal("0.000001"),
    "USDT": Decimal("0.000001"),
}
ATOMIC_TOLERANCE = {
    "SOL": 2,   # 2 lamports
    "USDC": 2,  # 2 USDC base units
    "USDT": 2,  # 2 USDT base units
}
ROUNDING_POLICY = (
    "Quantize each amount to the asset quantum (SOL 1e-9 / USDC 1e-6 / "
    "USDT 1e-6) with ROUND_HALF_EVEN. Two values agree when the absolute "
    "atomic difference is at most 2 units of that asset. Never apply a SOL "
    "lamport tolerance to USDC or USDT. Never sum mixed quote currencies."
)
MAX_ECONOMIC_TRADES_PER_UTC_DAY = 15
BOT_THRESHOLD_RULE = "economic_trades_per_utc_day"
BOT_GATE_VERSION = "gt15-v1"
# Age drop is off unless a caller supplies min_history_days or a Helius
# first-signature time. Named so grant/runner config can flip it.
HISTORY_AGE_RULE = "off"
HISTORY_AGE_RULE_HELIUS = "helius_first_signature"
GT_ECONOMIC_TRADES_RULE = f"gt_{MAX_ECONOMIC_TRADES_PER_UTC_DAY}_economic_trades_in_one_day"
GT15_ECONOMIC_TRADES_RULE = GT_ECONOMIC_TRADES_RULE
GT25_ECONOMIC_TRADES_RULE = GT_ECONOMIC_TRADES_RULE
BOT_RULE_DEFINITION = (
    "economic_swap_including_token_to_token; "
    "dedupe=(signature,kind,mint); "
    "route_legs_are_not_trades; "
    "multi_hop_same_tx_counts_once_per_mint_kind"
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
CANONICAL_AMOUNT = re.compile(r"^-?(?:0|[1-9]\d*)(?:\.\d+)?$")


def parse_canonical_amount(value):
    """Strict shared money grammar. Strings only; no sci-notation, spaces, or numerics."""
    if not isinstance(value, str) or not CANONICAL_AMOUNT.fullmatch(value):
        return None
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError, OverflowError):
        return None
    if not amount.is_finite():
        return None
    return amount


def _decimal(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("nan", "inf", "+inf", "-inf", "infinity", "-infinity"):
                return None
            if not CANONICAL_AMOUNT.fullmatch(value):
                return None
            amount = Decimal(value)
        elif isinstance(value, Decimal):
            amount = value
        elif type(value) is int:
            amount = Decimal(value)
        else:
            return None
        if not amount.is_finite():
            return None
        return amount
    except (InvalidOperation, ValueError, OverflowError):
        return None


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
    amount = parse_canonical_amount(value)
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
    if unit == "USDT":
        return f"{count} USDT base units"
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
        "bot_gate_version": BOT_GATE_VERSION,
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
    audit_policy = audit.get("accounting_policy_version")
    if stored_policy and stored_policy != fingerprint.get("accounting_policy_version"):
        return False
    if audit_policy and audit_policy != fingerprint.get("accounting_policy_version"):
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


def _bridge_app_identity(bridge):
    membership = (bridge or {}).get("membership") or {}
    app = membership.get("app") or {}
    mint = app.get("mint")
    close = app.get("close_signature") or app.get("close")
    if not mint or not close:
        return None
    return (str(mint), str(close))


def _bridge_auditor_identity(bridge):
    membership = (bridge or {}).get("membership") or {}
    auditor = membership.get("auditor") or {}
    mint = auditor.get("mint")
    close = auditor.get("close_signature") or auditor.get("close")
    if not mint or not close:
        return None
    return (str(mint), str(close))


LEDGER_COMPONENT_KEYS = {
    "acquisition": ("acquisition", "basis", "basis_sol"),
    "proceeds": ("proceeds", "proceeds_sol"),
    "costs": ("costs", "verified_costs", "verified_costs_sol"),
    "net": ("net", "pnl", "net_profit_sol"),
}


def _bridge_component_key(bridge):
    components = (bridge or {}).get("components") or {}
    amounts = []
    for name in REQUIRED_EPISODE_COMPONENTS:
        row = components.get(name) or {}
        amounts.append((name, str(row.get("app") or ""), str(row.get("auditor") or "")))
    return (
        _bridge_app_identity(bridge),
        _bridge_auditor_identity(bridge),
        (bridge or {}).get("unit"),
        tuple(amounts),
    )


def _ledger_component(episode, name):
    for key in LEDGER_COMPONENT_KEYS[name]:
        value = (episode or {}).get(key)
        if value not in (None, ""):
            return value
    return None


def _ledger_unit(episode):
    return (episode or {}).get("unit") or (episode or {}).get("settlement_asset")


def _bridge_app_matches_ledger(bridge, episode):
    """App-side comparison amounts/units must describe the bound ledger episode."""
    unit = (bridge or {}).get("unit")
    ledger_unit = _ledger_unit(episode)
    if not unit or not ledger_unit or unit != ledger_unit:
        return False
    components = (bridge or {}).get("components") or {}
    for name in REQUIRED_EPISODE_COMPONENTS:
        app_value = (components.get(name) or {}).get("app")
        ledger_value = _ledger_component(episode, name)
        if app_value in (None, "") or ledger_value in (None, ""):
            return False
        if not amounts_agree(app_value, ledger_value, ledger_unit):
            return False
    return True


def _bridges_from_episodes(audit):
    collected = []
    for episode in (audit or {}).get("episodes") or []:
        if not isinstance(episode, dict):
            continue
        bridge = episode.get("component_bridge")
        if isinstance(bridge, dict):
            collected.append(bridge)
    return collected


def _bridge_collections_equivalent(left, right):
    if len(left) != len(right):
        return False
    return sorted(_bridge_component_key(row) for row in left) == sorted(
        _bridge_component_key(row) for row in right
    )


def canonical_comparison_bridges(audit):
    """One stored comparison collection. Contradictory copies are rejected."""
    if not isinstance(audit, dict):
        return None
    listed = [row for row in (audit.get("component_bridges") or []) if isinstance(row, dict)]
    from_episodes = _bridges_from_episodes(audit)
    if listed and from_episodes and not _bridge_collections_equivalent(listed, from_episodes):
        return None
    return listed or from_episodes


def episode_comparison_bridges(audit):
    """Canonical per-episode component bridges, or empty when representations contradict."""
    return list(canonical_comparison_bridges(audit) or [])


def _sum_bridge_auditor_nets(bridges):
    total = Decimal("0")
    unit = None
    for bridge in bridges or []:
        bridge_unit = (bridge or {}).get("unit")
        if not bridge_unit:
            return None, None
        if unit is None:
            unit = bridge_unit
        elif unit != bridge_unit:
            return None, None
        auditor = parse_canonical_amount(((bridge.get("components") or {}).get("net") or {}).get("auditor"))
        if auditor is None:
            return None, None
        total += auditor
    return total, unit


def _ledger_net_and_unit(rows):
    validated = validate_episode_ledger(rows)
    if not validated.get("ok") or validated.get("empty") or validated.get("unit") in (None, "", "mixed"):
        return None, None
    return parse_canonical_amount(validated["net"]) or _decimal(validated["net"]), validated["unit"]


def _stored_headline_matches(audit, ledger, bridges):
    """Stored headline nets/units may be absent; when present they must equal derived sums."""
    auditor_sum, bridge_unit = _sum_bridge_auditor_nets(bridges)
    ledger_net, ledger_unit = _ledger_net_and_unit(ledger)
    if auditor_sum is None or ledger_net is None or not bridge_unit or not ledger_unit:
        return False
    if bridge_unit != ledger_unit:
        return False
    stored_auditor = audit.get("independently_audited_episode_net")
    stored_app = audit.get("app_completed_episode_net")
    stored_auditor_unit = audit.get("independently_audited_episode_net_unit")
    stored_app_unit = audit.get("app_completed_episode_net_unit")
    if stored_auditor_unit and stored_auditor_unit != bridge_unit:
        return False
    if stored_app_unit and stored_app_unit != ledger_unit:
        return False
    if stored_auditor not in (None, "") and not amounts_agree(stored_auditor, _display_decimal(auditor_sum), bridge_unit):
        return False
    if stored_app not in (None, "") and not amounts_agree(stored_app, _display_decimal(ledger_net), ledger_unit):
        return False
    return True


def derived_certificate_headlines(audit, ledger):
    """Headlines and confirmation from bridges + ledger. Never trust stored text."""
    bridges = canonical_comparison_bridges(audit) or []
    auditor_sum, bridge_unit = _sum_bridge_auditor_nets(bridges)
    ledger_net, ledger_unit = _ledger_net_and_unit(ledger)
    if auditor_sum is None or ledger_net is None or bridge_unit != ledger_unit:
        return None
    app_text = _display_decimal(ledger_net)
    auditor_text = _display_decimal(auditor_sum)
    return {
        "app_completed_episode_net": app_text,
        "app_completed_episode_net_unit": ledger_unit,
        "independently_audited_episode_net": auditor_text,
        "independently_audited_episode_net_unit": bridge_unit,
        "auditor_confirmation": format_auditor_confirmation(
            app_text, auditor_text, ledger_unit, independently_audited=True
        ),
    }


def _bridge_amounts_agree(bridge):
    """Recompute agreement from stored amounts. Flags are not evidence."""
    unit = (bridge or {}).get("unit") or "SOL"
    components = (bridge or {}).get("components") or {}
    for name in REQUIRED_EPISODE_COMPONENTS:
        row = components.get(name) or {}
        app_value = row.get("app")
        auditor_value = row.get("auditor")
        if app_value in (None, "") or auditor_value in (None, ""):
            return False
        if not amounts_agree(app_value, auditor_value, unit):
            return False
    return True


def certificate_comparison_proof(audit, ledger=None):
    """Validate stored comparisons against the bound ledger, not just each other.

    A missing or empty ledger cannot certify. App-side amounts and units must
    describe the matching ledger episode. Contradictory proof representations
    fail. Flags are not evidence.
    """
    if not isinstance(audit, dict):
        return False
    if audit.get("one_to_one_membership") is not True:
        return False
    rows = list(ledger or [])
    if not rows:
        return False
    bridges = canonical_comparison_bridges(audit)
    if not bridges:
        return False
    seen = set()
    by_id = {}
    for item in rows:
        mint = (item or {}).get("mint")
        close = (item or {}).get("close_signature") or (item or {}).get("close")
        if not mint or not close:
            return False
        key = (str(mint), str(close))
        if key in seen:
            return False
        seen.add(key)
        by_id[key] = item
    if len(bridges) != len(rows):
        return False
    matched = set()
    for bridge in bridges:
        app_id = _bridge_app_identity(bridge)
        auditor_id = _bridge_auditor_identity(bridge)
        if not app_id or not auditor_id or app_id != auditor_id:
            return False
        if app_id not in by_id or app_id in matched:
            return False
        matched.add(app_id)
        if not _bridge_amounts_agree(bridge):
            return False
        if not _bridge_app_matches_ledger(bridge, by_id[app_id]):
            return False
    if matched != seen:
        return False
    return _stored_headline_matches(audit, rows, bridges)


def bindable_independent_audit(audit, fingerprint, ledger=None):
    """Bind only a fingerprint-matched certificate that also has comparison proof.

    A fingerprint binds app inputs. It does not, by itself, establish that the
    accompanying auditor result contains a successful one-to-one comparison.
    Headlines and confirmation are replaced with derived values.
    """
    if not audit or not fingerprint:
        return None
    if not audit_fingerprint_matches(audit, fingerprint):
        return None
    if not certificate_comparison_proof(audit, ledger):
        return None
    headlines = derived_certificate_headlines(audit, ledger)
    if not headlines:
        return None
    bound = dict(audit)
    bound.update(headlines)
    return bound


def _shares_from_unsupported(shares):
    by_count = _decimal((shares or {}).get("by_count"))
    count_share = (Decimal("1") - by_count) if by_count is not None else None
    value_coverages = []
    for value in ((shares or {}).get("by_consideration") or {}).values():
        amount = _decimal(value)
        if amount is not None:
            value_coverages.append(Decimal("1") - amount)
    value_share = min(value_coverages) if value_coverages else None
    mandatory = None
    if count_share is not None and value_share is not None:
        mandatory = min(count_share, value_share)
    return count_share, value_share, mandatory


def coverage_shares(report, profile=None):
    """Count and value coverage. Gate uses result-relevant R when present.

    Whole-span shares stay on the report so old and new numbers are never mixed.
    Missing value coverage is not treated as 100%. Empty R blocks.
    """
    from scanner.mass_search.result_relevant_coverage import COVERAGE_GATE_VERSION

    breakdown = (report or {}).get("record_breakdown") or {}
    whole = breakdown.get("unsupported_swap_share_in_window") or {}
    if not whole and profile:
        whole = profile.get("unsupported_swap_share_in_window") or {}
    whole_count, whole_value, whole_mandatory = _shares_from_unsupported(whole)
    relevant = (
        breakdown.get("result_relevant")
        or (report or {}).get("result_relevant")
        or (profile or {}).get("result_relevant")
    )
    if relevant is None:
        return {
            "coverage_count_share": None,
            "coverage_value_share": None,
            "coverage_mandatory_share": None,
            "coverage_historical_share": None,
            "coverage_count_share_whole_span": _display_decimal(whole_count),
            "coverage_value_share_whole_span": _display_decimal(whole_value),
            "coverage_mandatory_share_whole_span": _display_decimal(whole_mandatory),
            "coverage_gate_version": None,
            "count_share": None,
            "value_share": None,
            "mandatory_share": None,
            "denominator_includes_unsupported_suspected_trading": True,
            "missing_result_relevant": True,
        }
    version = relevant.get("version")
    version_ok = version == COVERAGE_GATE_VERSION
    if (
        not version_ok
        or relevant.get("empty")
        or relevant.get("size") == 0
        or relevant.get("denominator") == 0
    ):
        count_share = value_share = mandatory = None
    else:
        count_share, value_share, mandatory = _shares_from_unsupported(
            relevant.get("unsupported_swap_share") or relevant
        )
        if relevant.get("count_share") is not None:
            count_share = _decimal(relevant.get("count_share"))
        if relevant.get("value_share") is not None:
            value_share = _decimal(relevant.get("value_share"))
        if count_share is not None and value_share is not None:
            mandatory = min(count_share, value_share)
    return {
        "coverage_count_share": _display_decimal(count_share),
        "coverage_value_share": _display_decimal(value_share),
        "coverage_mandatory_share": _display_decimal(mandatory),
        "coverage_historical_share": None,
        "coverage_count_share_whole_span": _display_decimal(whole_count),
        "coverage_value_share_whole_span": _display_decimal(whole_value),
        "coverage_mandatory_share_whole_span": _display_decimal(whole_mandatory),
        "coverage_gate_version": version,
        "result_relevant_size": relevant.get("size"),
        "result_relevant_lineage_mints": list(relevant.get("lineage_mints") or []),
        "count_share": count_share,
        "value_share": value_share,
        "mandatory_share": mandatory,
        "denominator_includes_unsupported_suspected_trading": True,
        "coverage_version_mismatch": not version_ok,
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
    reason = None
    relevant = (
        ((report or {}).get("record_breakdown") or {}).get("result_relevant")
        or (report or {}).get("result_relevant")
        or (profile or {}).get("result_relevant")
    )
    from scanner.mass_search.result_relevant_coverage import COVERAGE_GATE_VERSION as _RR_VERSION
    if relevant is None:
        passed = False
        reason = "missing result-relevant set"
    elif relevant.get("version") != _RR_VERSION:
        passed = False
        reason = "coverage_gate_version mismatch"
    elif relevant.get("empty") or relevant.get("size") == 0 or relevant.get("denominator") == 0:
        passed = False
        reason = "empty result-relevant set"
    else:
        passed = (
            count_share is not None
            and value_share is not None
            and count_share >= threshold
            and value_share >= threshold
        )
        if not passed:
            reason = (
                "coverage gate requires count AND value; missing value share"
                if value_share is None or count_share is None
                else "coverage gate requires count AND value"
            )
    audit = (report or {}).get("independent_audit") or {}
    app_r = relevant
    aud_r = audit.get("result_relevant") if isinstance(audit, dict) else None
    if app_r is not None and aud_r is not None:
        app_sigs = set(app_r.get("signatures") or [])
        aud_sigs = set(aud_r.get("signatures") or [])
        if app_sigs != aud_sigs:
            passed = False
            reason = "app and auditor disagree on result-relevant membership"
        else:
            app_pass = app_r.get("gate_passed")
            aud_pass = aud_r.get("gate_passed")
            if app_pass is not None and aud_pass is not None and bool(app_pass) != bool(aud_pass):
                passed = False
                reason = "app and auditor disagree on result-relevant pass/fail"
    return _json_safe_gate({
        **shares,
        "threshold": _display_decimal(threshold),
        "passed": passed,
        "reason": reason,
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


WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
JUPITER_V6 = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
JUPITER_V4 = "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB"
JUPITER_ROUTE_PROGRAMS = frozenset({JUPITER_V6, JUPITER_V4})
RAW_QUOTE_ASSETS = frozenset({WSOL_MINT, USDC_MINT, USDT_MINT, "SOL"})
RAW_SOL_FLOOR_LAMPORTS = 100_000
RAW_SOL_NOISE_LAMPORTS = RAW_SOL_FLOOR_LAMPORTS
RAW_TOKEN_DUST_UNITS = 1
RAW_TIP_SOL_LAMPORTS = 300_000
# LP position NFTs / Meteora add-remove / Orca OpenPosition. Used only to
# exclude non-trades; both-down real sells still count.
LP_LOG_RE = re.compile(
    r"Instruction: \w*(?:OpenPosition|ClosePosition|IncreaseLiquidity|"
    r"DecreaseLiquidity|AddLiquidity|RemoveLiquidity)\w*",
    re.I,
)
SWAP_LIKE_LOG_RE = re.compile(
    r"Instruction: (?:\w*Swap\w*|Buy\w*|Sell\w*|\w*Route\w*|Fill\w*|"
    r"\w*Exact\w*In\w*|\w*Exact\w*Out\w*)|SwapEvent",
    re.I,
)
ATA_RENT_LAMPORTS = 2_039_280


def _first_present(*values):
    """Return the first real value. 0 is present; None/''/bool are not."""
    for value in values:
        if value is None or isinstance(value, bool) or value == "":
            continue
        return value
    return None


def _event_unix(event):
    stamp = _first_present(
        (event or {}).get("block_time"),
        (event or {}).get("blockTime"),
        (event or {}).get("timestamp"),
    )
    if isinstance(stamp, bool):
        return None
    if type(stamp) is int:
        return stamp
    if isinstance(stamp, float):
        if not math.isfinite(stamp):
            return None
        try:
            return int(stamp)
        except (OverflowError, ValueError):
            return None
    if isinstance(stamp, str) and stamp:
        try:
            return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def _utc_day(unix):
    try:
        return datetime.fromtimestamp(int(unix), tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError, TypeError):
        return None


def _record_signature(record):
    raw = _unwrap_raw_record(record) if isinstance(record, dict) else {}
    if raw.get("signature"):
        return raw["signature"]
    tx = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
    sigs = tx.get("signatures") or []
    if sigs:
        return sigs[0]
    if isinstance(record, dict) and record.get("signature"):
        return record["signature"]
    return None


def first_defined_int(*values):
    """Treat 0 as a real max. None/'' are missing."""
    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def is_economic_bot(max_economic_trades_in_one_day, *, threshold=None):
    """True only when a known economic-trade max exceeds the UTC-day cap.

    A missing count cannot prove a bot. Tx-rate heuristics must not set this.
    """
    cap = MAX_ECONOMIC_TRADES_PER_UTC_DAY if threshold is None else int(threshold)
    maximum = first_defined_int(max_economic_trades_in_one_day)
    return maximum is not None and maximum > cap


def gt25_blocker_text(rate):
    if not rate:
        return None
    maximum = first_defined_int(rate.get("max"))
    if maximum is None or not is_economic_bot(maximum):
        return None
    day = rate.get("max_on") or "unknown"
    return f"{GT_ECONOMIC_TRADES_RULE}: {maximum} on {day}"


def with_gt25_blocker(blocker, rate):
    extra = gt25_blocker_text(rate)
    if not extra:
        return blocker
    if not blocker:
        return extra
    parts = [part.strip() for part in str(blocker).split(";") if part.strip()]
    kept = []
    prefix = GT_ECONOMIC_TRADES_RULE
    for part in parts:
        if part == extra or extra in part:
            continue
        if part == prefix or part.startswith(prefix + ":") or part.startswith(prefix + " "):
            continue
        kept.append(part)
    kept.append(extra)
    return "; ".join(kept)


def bot_rate_disagreement_blocker(app_rate, auditor_rate):
    """Fail closed when app and auditor disagree on the >15/day gate."""
    app_max = first_defined_int((app_rate or {}).get("max"))
    aud_max = first_defined_int((auditor_rate or {}).get("max"))
    if app_max is None and aud_max is None:
        return None
    if app_max is None or aud_max is None:
        return (
            f"app_auditor_bot_rate_disagree: app {app_max} on "
            f"{(app_rate or {}).get('max_on') or 'unknown'} vs auditor {aud_max} on "
            f"{(auditor_rate or {}).get('max_on') or 'unknown'}"
        )
    app_over = app_max > MAX_ECONOMIC_TRADES_PER_UTC_DAY
    aud_over = aud_max > MAX_ECONOMIC_TRADES_PER_UTC_DAY
    if app_over == aud_over:
        return None
    return (
        f"app_auditor_bot_rate_disagree: app {app_max} on "
        f"{(app_rate or {}).get('max_on') or 'unknown'} vs auditor {aud_max} on "
        f"{(auditor_rate or {}).get('max_on') or 'unknown'}"
    )


def economic_trade_identity(event):
    """Bot-rule identity: (signature, kind, mint). Token-to-token included."""
    if not isinstance(event, dict):
        return None
    if event.get("kind") not in ("buy", "sell"):
        return None
    signature = event.get("signature")
    if not signature:
        return None
    return (signature, event.get("kind"), event.get("mint"))


def independent_economic_trade_keys(events):
    """Independent (signature, kind, mint) set. Must match economic_trades_by_utc_day."""
    keys = []
    seen = set()
    for event in events or []:
        key = economic_trade_identity(event)
        if key is None or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def _decoded_trade_day_counts(events):
    """Decoded (signature, kind, mint) counts plus uncountable-timestamp tally."""
    counts = Counter()
    seen = set()
    incomplete = 0
    for event in events or []:
        if not isinstance(event, dict):
            continue
        key = economic_trade_identity(event)
        if key is None:
            if event.get("kind") not in ("buy", "sell"):
                continue
            key = (None, event.get("kind"), event.get("mint"), id(event))
        if event.get("signature") and key in seen:
            continue
        stamp = _event_unix(event)
        if stamp is None:
            incomplete += 1
            continue
        if event.get("signature"):
            seen.add(key)
        day = _utc_day(stamp)
        if day is None:
            incomplete += 1
            continue
        counts[day] += 1
    return dict(counts), incomplete


def economic_trades_by_utc_day(events):
    """Count every economic swap as a trade, including token-to-token.

    Dedupe by (signature, kind, mint) so one multi-leg tx is not counted more
    than once per mint/kind. Route-leg hops are not trades: a multi-hop route
    in one tx is one trade, not one per hop. An independent unique-
    (signature, kind, mint) count must match. Fee events are not trades.
    Overlapping samples collapse. Timestamps may be unix seconds or ISO-8601.
    Float timestamps count. Missing timestamps are not silently dropped:
    economic_trade_rate marks the day set incomplete (fail closed).
    """
    counts, _incomplete = _decoded_trade_day_counts(events)
    return counts


def _rate_from_by_day(by_day, *, incomplete=False, incomplete_uncounted=0):
    payload = {
        "by_day": dict(by_day or {}),
        "max": 0,
        "max_on": None,
        "incomplete": bool(incomplete or incomplete_uncounted),
        "incomplete_uncounted": int(incomplete_uncounted or 0),
    }
    if by_day:
        day = max(by_day, key=lambda item: (by_day[item], item))
        payload["max"] = int(by_day[day])
        payload["max_on"] = day
    return payload


def economic_trade_rate(events):
    by_day, incomplete = _decoded_trade_day_counts(events)
    return _rate_from_by_day(by_day, incomplete_uncounted=incomplete)


def _unwrap_raw_record(record):
    """GTA/RPC body. Nested raw/result wrappers must not hide meta."""
    if not isinstance(record, dict):
        return {}
    if "transaction" in record or isinstance(record.get("meta"), dict):
        return record
    raw = record.get("raw")
    if isinstance(raw, dict):
        result = raw.get("result")
        if isinstance(result, dict) and ("transaction" in result or isinstance(result.get("meta"), dict)):
            return result
        if "transaction" in raw or isinstance(raw.get("meta"), dict):
            return raw
    result = record.get("result")
    if isinstance(result, dict) and ("transaction" in result or isinstance(result.get("meta"), dict)):
        return result
    return record


def _record_meta(record):
    meta = record.get("meta")
    if isinstance(meta, dict):
        return meta
    tx = record.get("transaction")
    if isinstance(tx, dict) and isinstance(tx.get("meta"), dict):
        return tx["meta"]
    return None


def _tx_account_keys(record):
    tx = record.get("transaction") if isinstance(record.get("transaction"), dict) else {}
    msg = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    keys = []
    for key in msg.get("accountKeys") or []:
        keys.append(key["pubkey"] if isinstance(key, dict) else key)
    meta = _record_meta(record) or {}
    loaded = meta.get("loadedAddresses") or {}
    keys.extend(list(loaded.get("writable") or []))
    keys.extend(list(loaded.get("readonly") or []))
    return keys


def _token_balance_owner(balance, keys):
    owner = balance.get("owner")
    if owner:
        return owner
    index = balance.get("accountIndex")
    if type(index) is int and 0 <= index < len(keys):
        return keys[index]
    return None


def _token_amount_raw(balance):
    if not isinstance(balance, dict):
        return 0
    amount = ((balance.get("uiTokenAmount") or {}).get("amount"))
    if amount in (None, ""):
        return 0
    try:
        return int(amount)
    except (TypeError, ValueError):
        return 0


def _parsed_wallet_token_deltas(meta, address):
    """Fallback when token-balance meta is empty: parsed inner SPL transfers."""
    deltas = Counter()
    if not isinstance(meta, dict) or not address:
        return deltas
    instructions = []
    for group in meta.get("innerInstructions") or []:
        if isinstance(group, dict):
            instructions.extend(group.get("instructions") or [])
        elif isinstance(group, list):
            instructions.extend(group)
    for ix in instructions:
        if not isinstance(ix, dict):
            continue
        parsed = ix.get("parsed")
        if not isinstance(parsed, dict):
            continue
        if parsed.get("type") not in ("transfer", "transferChecked"):
            continue
        info = parsed.get("info") if isinstance(parsed.get("info"), dict) else {}
        mint = info.get("mint")
        amount = info.get("amount")
        if amount in (None, ""):
            token_amount = info.get("tokenAmount")
            if isinstance(token_amount, dict):
                amount = token_amount.get("amount")
        if not mint or amount in (None, ""):
            continue
        try:
            qty = int(amount)
        except (TypeError, ValueError):
            continue
        authority = info.get("authority") or info.get("owner")
        if authority == address:
            deltas[mint] -= qty
        dest_owner = info.get("destinationOwner")
        if dest_owner == address or info.get("destination") == address:
            deltas[mint] += qty
    return deltas


def wallet_asset_deltas(record, address):
    """Net wallet asset deltas. SOL is rent-aware then floored at ~1e5 lamports.

    Token legs are wallet-owned accountIndex rows in pre or post. Created
    (post-only) and closed (pre-only) wallet token accounts contribute their
    lamports, minus any wSOL token amount, so ATA rent is not a SOL trade
    leg. After that back-out, keep a SOL leg only when |sol| exceeds
    RAW_SOL_FLOOR_LAMPORTS (100_000). Nested GTA wrappers and
    transaction.meta are unwrapped. Empty token-balance meta falls back to
    parsed inner SPL transfers.
    """
    if not isinstance(record, dict) or not address:
        return None
    raw = _unwrap_raw_record(record)
    meta = _record_meta(raw)
    if not isinstance(meta, dict) or meta.get("err") is not None:
        return None
    keys = _tx_account_keys(raw)
    pre_lamports = meta.get("preBalances") or []
    post_lamports = meta.get("postBalances") or []
    pre_tok = {}
    post_tok = {}
    for balance in meta.get("preTokenBalances") or []:
        if isinstance(balance, dict) and type(balance.get("accountIndex")) is int:
            pre_tok[balance["accountIndex"]] = balance
    for balance in meta.get("postTokenBalances") or []:
        if isinstance(balance, dict) and type(balance.get("accountIndex")) is int:
            post_tok[balance["accountIndex"]] = balance
    mine = set()
    for index, balance in list(pre_tok.items()) + list(post_tok.items()):
        if _token_balance_owner(balance, keys) == address:
            mine.add(index)
    deltas = Counter()
    rent = 0
    for index in mine:
        before = pre_tok.get(index)
        after = post_tok.get(index)
        mint = (after or before).get("mint") if (after or before) else None
        qty_before = _token_amount_raw(before)
        qty_after = _token_amount_raw(after)
        if mint:
            deltas[mint] += qty_after - qty_before
        if before is None and after is not None and index < len(post_lamports):
            rent += int(post_lamports[index]) - (qty_after if mint == WSOL_MINT else 0)
        if before is not None and after is None and index < len(pre_lamports):
            rent -= int(pre_lamports[index]) - (qty_before if mint == WSOL_MINT else 0)
    if not mine:
        for balance in meta.get("preTokenBalances") or []:
            if not isinstance(balance, dict) or _token_balance_owner(balance, keys) != address:
                continue
            mint = balance.get("mint")
            if mint:
                deltas[mint] -= _token_amount_raw(balance)
        for balance in meta.get("postTokenBalances") or []:
            if not isinstance(balance, dict) or _token_balance_owner(balance, keys) != address:
                continue
            mint = balance.get("mint")
            if mint:
                deltas[mint] += _token_amount_raw(balance)
    if not any(qty for qty in deltas.values()):
        for mint, qty in _parsed_wallet_token_deltas(meta, address).items():
            deltas[mint] += qty
    wallet_index = keys.index(address) if address in keys else None
    native = 0
    if wallet_index is not None and wallet_index < len(pre_lamports) and wallet_index < len(post_lamports):
        native = int(post_lamports[wallet_index]) - int(pre_lamports[wallet_index])
    fee = int(meta.get("fee") or 0) if keys and keys[0] == address else 0
    wrapped = deltas.pop(WSOL_MINT, 0)
    sol_raw = native + fee + wrapped
    apply_rent = (wallet_index is not None and native < 0) or rent < 0
    sol = sol_raw + (rent if apply_rent else 0)
    legs = {mint: qty for mint, qty in deltas.items() if qty}
    if abs(sol) > RAW_SOL_FLOOR_LAMPORTS:
        legs["SOL"] = sol
    return legs


def _wallet_signed(record, address):
    """True when address is among the required signers."""
    if not isinstance(record, dict) or not address:
        return False
    raw = _unwrap_raw_record(record)
    tx = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
    msg = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    keys = []
    for key in msg.get("accountKeys") or []:
        keys.append(key["pubkey"] if isinstance(key, dict) else key)
    header = msg.get("header") if isinstance(msg.get("header"), dict) else {}
    needed = header.get("numRequiredSignatures")
    if type(needed) is not int or needed < 1:
        needed = 1
    return address in keys[:needed]


def _logs_text(record):
    raw = _unwrap_raw_record(record)
    meta = _record_meta(raw)
    if not isinstance(meta, dict):
        return ""
    return " ".join(str(item) for item in (meta.get("logMessages") or []) if item)


def _wallet_lp_nft_moved(record, address):
    """True when a 1-unit, 0-decimal mint (LP position NFT) moved for the wallet."""
    raw = _unwrap_raw_record(record)
    meta = _record_meta(raw)
    if not isinstance(meta, dict) or not address:
        return False
    keys = _tx_account_keys(raw)
    pre, post, decimals = {}, {}, {}
    for field, dest in (("preTokenBalances", pre), ("postTokenBalances", post)):
        for balance in meta.get(field) or []:
            if not isinstance(balance, dict) or _token_balance_owner(balance, keys) != address:
                continue
            mint = balance.get("mint")
            if not mint:
                continue
            dest[mint] = _token_amount_raw(balance)
            ui = balance.get("uiTokenAmount") if isinstance(balance.get("uiTokenAmount"), dict) else {}
            if type(ui.get("decimals")) is int:
                decimals[mint] = ui["decimals"]
    for mint in set(pre) | set(post):
        delta = post.get(mint, 0) - pre.get(mint, 0)
        if decimals.get(mint) == 0 and abs(delta) == 1:
            return True
    return False


def _has_lp_instruction(record):
    return bool(LP_LOG_RE.search(_logs_text(record)))


def _has_swap_like_log(record):
    return bool(SWAP_LIKE_LOG_RE.search(_logs_text(record)))


def _ix_program_id(instruction, keys):
    if not isinstance(instruction, dict):
        return None
    program = instruction.get("programId")
    if isinstance(program, str) and program:
        return program
    parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else {}
    if isinstance(parsed.get("programId"), str) and parsed.get("programId"):
        return parsed["programId"]
    index = instruction.get("programIdIndex")
    if type(index) is int and not isinstance(index, bool) and 0 <= index < len(keys):
        return keys[index]
    return None


def _reviewed_swap_route_programs():
    try:
        from scanner.investigation import NET_BALANCE_SWAP_PROGRAMS
        return frozenset(NET_BALANCE_SWAP_PROGRAMS) | JUPITER_ROUTE_PROGRAMS
    except Exception:
        return JUPITER_ROUTE_PROGRAMS


def _iter_record_instructions(record):
    raw = _unwrap_raw_record(record)
    meta = _record_meta(raw) or {}
    tx = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
    message = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    for instruction in message.get("instructions") or []:
        if isinstance(instruction, dict):
            yield instruction
    for group in meta.get("innerInstructions") or []:
        if isinstance(group, dict):
            items = group.get("instructions") or []
        elif isinstance(group, list):
            items = group
        else:
            continue
        for instruction in items:
            if isinstance(instruction, dict):
                yield instruction


def _has_reviewed_swap_instruction(record):
    """True when a reviewed swap/route program is present as a swap.

    A Whirlpool/Meteora program that only opens or changes an LP position is
    not a swap instruction. A Jupiter route that also logs AddLiquidity2 is.
    """
    raw = _unwrap_raw_record(record)
    keys = _tx_account_keys(raw)
    programs = _reviewed_swap_route_programs()
    if not any(_ix_program_id(instruction, keys) in programs for instruction in _iter_record_instructions(record)):
        return False
    if _has_swap_like_log(record):
        return True
    if LP_LOG_RE.search(_logs_text(record)):
        return False
    return True


def _has_jupiter_route_instruction(record):
    raw = _unwrap_raw_record(record)
    keys = _tx_account_keys(raw)
    return any(_ix_program_id(instruction, keys) in JUPITER_ROUTE_PROGRAMS for instruction in _iter_record_instructions(record))


def _is_lp_or_rent_or_tip_non_trade(record, address, material, token_downs, token_ups, quote_downs, quote_ups):
    """Exclude LP opens/closes and rent-only / tip-plus-airdrop transfers.

    LP is excluded only when there is no reviewed swap/route instruction and
    an LP NFT/position actually opens or changes. Tip+airdrop applies only
    when there is no swap instruction. A Jupiter hop that logs AddLiquidity2
    still counts.
    """
    has_swap_ix = _has_reviewed_swap_instruction(record)
    if not has_swap_ix and _wallet_lp_nft_moved(record, address):
        return True
    sol_down = -material["SOL"] if material.get("SOL", 0) < 0 else 0
    stable_down = any(material.get(mint, 0) < 0 for mint in (USDC_MINT, USDT_MINT))
    swap_log = _has_swap_like_log(record)
    # Rent-only or tip + token transfer out: token down, SOL-only quote down
    # at rent/tip size, no swap signal. Real both-down sells have Swap/Sell
    # logs or a stable quote move.
    if token_downs and not token_ups and quote_downs and not quote_ups:
        rent_or_tip = ATA_RENT_LAMPORTS + RAW_TIP_SOL_LAMPORTS
        if not has_swap_ix and not stable_down and not swap_log and 0 < sol_down <= rent_or_tip:
            return True
    # Tip + airdrop: token up, SOL down at or below the tip cutoff, no stable.
    # Apply only when there is no reviewed swap instruction.
    if not has_swap_ix and not swap_log and token_ups and quote_downs and not token_downs:
        if not stable_down and 0 < sol_down <= RAW_TIP_SOL_LAMPORTS:
            return True
    return False


def raw_economic_keys_for_tx(record, address):
    """Signed economic-swap keys for one successful tx.

    A token the wallet sold counts even when both legs go down (proceeds
    landed in another account). Dust leftovers of 1 raw unit are not a
    second key. Liquidity-position NFTs, 1-unit mints, rent-only SOL and
    tip-plus-airdrop are not trades.
    """
    if not _wallet_signed(record, address):
        return 0
    legs = wallet_asset_deltas(record, address)
    material = {}
    for mint, qty in (legs or {}).items():
        if mint in RAW_QUOTE_ASSETS or abs(qty) > RAW_TOKEN_DUST_UNITS:
            material[mint] = qty
    if not material:
        # Zero-net Jupiter round trips (BJcx-style arb) still count as a trade.
        if _has_jupiter_route_instruction(record) and (
            _has_swap_like_log(record) or _has_reviewed_swap_instruction(record)
        ):
            return 1
        return 0
    token_downs = [mint for mint, qty in material.items() if qty < 0 and mint not in RAW_QUOTE_ASSETS]
    token_ups = [mint for mint, qty in material.items() if qty > 0 and mint not in RAW_QUOTE_ASSETS]
    quote_downs = [mint for mint, qty in material.items() if qty < 0 and mint in RAW_QUOTE_ASSETS]
    quote_ups = [mint for mint, qty in material.items() if qty > 0 and mint in RAW_QUOTE_ASSETS]
    if _is_lp_or_rent_or_tip_non_trade(
        record, address, material, token_downs, token_ups, quote_downs, quote_ups,
    ):
        return 0
    if token_downs and token_ups:
        return len(token_downs + token_ups)
    if token_downs and (quote_downs or quote_ups):
        return len(token_downs)
    if token_ups and quote_downs:
        sol_down = -material["SOL"] if material.get("SOL", 0) < 0 else 0
        stable_down = any(material.get(mint, 0) < 0 for mint in (USDC_MINT, USDT_MINT))
        if (
            not _has_reviewed_swap_instruction(record)
            and not _has_swap_like_log(record)
            and not stable_down
            and 0 < sol_down <= RAW_TIP_SOL_LAMPORTS
        ):
            return 0
        return len(token_ups)
    if quote_ups and quote_downs:
        return 1
    return 0


def _record_unix(record):
    raw = _unwrap_raw_record(record) if isinstance(record, dict) else {}
    tx = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
    stamp = _first_present(
        raw.get("blockTime"),
        raw.get("block_time"),
        raw.get("timestamp"),
        tx.get("blockTime"),
        tx.get("timestamp"),
        record.get("blockTime") if isinstance(record, dict) else None,
        record.get("block_time") if isinstance(record, dict) else None,
        record.get("timestamp") if isinstance(record, dict) else None,
    )
    return _event_unix({"timestamp": stamp})


def raw_economic_trades_by_utc_day(records, address):
    """Raw-tx bot-rate over all captured records, one count per signature."""
    counts = Counter()
    incomplete = 0
    seen = set()
    for record in records or []:
        if not isinstance(record, dict):
            continue
        signature = _record_signature(record)
        if signature:
            if signature in seen:
                continue
            seen.add(signature)
        raw = _unwrap_raw_record(record)
        n_keys = raw_economic_keys_for_tx(raw, address)
        if n_keys <= 0:
            continue
        unix = _record_unix(record)
        if unix is None:
            incomplete += n_keys
            continue
        day = _utc_day(unix)
        if day is None:
            incomplete += n_keys
            continue
        counts[day] += n_keys
    return dict(counts), incomplete


def raw_economic_trade_rate(records, address):
    by_day, incomplete = raw_economic_trades_by_utc_day(records, address)
    return _rate_from_by_day(by_day, incomplete_uncounted=incomplete)


def merge_trade_rates(*rates):
    """Per-day max across raw, decoded, and stored. Fail closed if any is incomplete."""
    by_day = Counter()
    incomplete = False
    uncounted = 0
    dateless_max = None
    for rate in rates:
        if not rate:
            continue
        incomplete = incomplete or bool(rate.get("incomplete"))
        uncounted += int(rate.get("incomplete_uncounted") or 0)
        for day, count in (rate.get("by_day") or {}).items():
            if day in (None, "", "stored", "unknown"):
                continue
            try:
                by_day[day] = max(by_day[day], int(count))
            except (TypeError, ValueError):
                continue
        stored_max = first_defined_int(rate.get("max"))
        stored_on = rate.get("max_on")
        if stored_max is None:
            continue
        if stored_on in (None, "", "stored", "unknown"):
            if dateless_max is None or stored_max > dateless_max:
                dateless_max = stored_max
            continue
        by_day[stored_on] = max(by_day[stored_on], stored_max)
    payload = _rate_from_by_day(by_day, incomplete=incomplete, incomplete_uncounted=uncounted)
    if dateless_max is not None and dateless_max > (payload["max"] or 0):
        payload["max"] = dateless_max
        payload["max_on"] = None
    if payload.get("max_on") in ("stored", "unknown"):
        payload["max_on"] = None
    return payload


def combined_economic_trade_rate(events=None, records=None, address=None):
    """Larger of raw balance-leg count and decoded (signature, kind, mint)."""
    decoded = economic_trade_rate(events)
    raw = raw_economic_trade_rate(records, address) if records is not None and address else None
    return merge_trade_rates(decoded, raw)


def _events_from_report_or_profile(report, profile):
    events = []
    if report:
        events = list(report.get("captured_history_events") or [])
        if not events:
            events = list(report.get("events") or [])
    if profile and not events:
        events = list(profile.get("captured_history_events") or [])
    return events


def day_for_stored_max(by_day, stored=None):
    """Date of a saved max. Prefer the by_day entry that equals stored."""
    usable = {}
    for day, count in (by_day or {}).items():
        if day in (None, "", "stored", "unknown"):
            continue
        try:
            usable[str(day)] = int(count)
        except (TypeError, ValueError):
            continue
    if not usable:
        return None
    if stored is not None:
        matching = [day for day, count in usable.items() if count == stored]
        if matching:
            return max(matching)
    return max(usable, key=lambda day: (usable[day], day))


def _stored_trade_rate(source):
    if not source:
        return None
    stored = first_defined_int(source.get("max_economic_trades_in_one_day"))
    if stored is None:
        stored = first_defined_int(source.get("max_trades_per_day"))
    by_day = source.get("economic_trades_by_utc_day") or source.get("economic_trades_by_day") or {}
    if stored is None and not by_day:
        return None
    return {
        "by_day": by_day,
        "max": stored if stored is not None else 0,
        "max_on": (
            source.get("max_economic_trades_on")
            or source.get("max_trades_per_day_on")
            or day_for_stored_max(by_day, stored)
        ),
        "incomplete": bool(source.get("economic_trade_rate_incomplete")),
        "incomplete_uncounted": int(source.get("economic_trade_rate_incomplete_uncounted") or 0),
    }


def trade_rate_from(report=None, profile=None, records=None, address=None):
    """Larger of stored, decoded-event, and raw-tx counts. 0 is a real max."""
    events = _events_from_report_or_profile(report, profile)
    decoded = economic_trade_rate(events)
    raw = raw_economic_trade_rate(records, address) if records is not None and address else None
    stored = merge_trade_rates(_stored_trade_rate(profile), _stored_trade_rate(report))
    return merge_trade_rates(stored, decoded, raw)


def apply_trade_rate(target, rate):
    target["economic_trades_by_utc_day"] = rate["by_day"]
    target["max_economic_trades_in_one_day"] = rate["max"]
    target["max_economic_trades_on"] = rate["max_on"]
    target["max_trades_per_day"] = rate["max"]
    target["max_trades_per_day_on"] = rate["max_on"]
    target["economic_trade_rate_incomplete"] = bool(rate.get("incomplete"))
    target["economic_trade_rate_incomplete_uncounted"] = int(rate.get("incomplete_uncounted") or 0)
    return rate


def attach_economic_trade_rate(target, events, records=None, address=None):
    """Write max trades/day + date. Uses the larger of raw and decoded counts."""
    rate = combined_economic_trade_rate(events=events, records=records, address=address)
    return apply_trade_rate(target, rate)


def stronger_shortlist_activity_ok(activity, max_economic_trades_in_one_day=None):
    if (
        max_economic_trades_in_one_day is not None
        and int(max_economic_trades_in_one_day) > MAX_ECONOMIC_TRADES_PER_UTC_DAY
    ):
        return False
    return (
        int(activity.get("active_trading_days") or 0) >= STRONGER_MIN_ACTIVE_DAYS
        and int(activity.get("span_days") or 0) >= STRONGER_MIN_SPAN_DAYS
    )


def validate_episode_ledger(episodes):
    """Validated membership, count, units, and sums. No SOL fallback, no skipped nets."""
    rows = list(episodes or [])
    if not rows:
        return {
            "ok": True,
            "empty": True,
            "reason": "empty_ledger",
            "net": None,
            "unit": None,
            "vector": {},
            "count": 0,
            "episodes": [],
        }
    seen = set()
    by_unit = {}
    for item in rows:
        mint = (item or {}).get("mint")
        close = (item or {}).get("close_signature") or (item or {}).get("close")
        if not mint:
            return {
                "ok": False,
                "empty": False,
                "reason": "episode_identity_incomplete",
                "net": None,
                "unit": None,
                "vector": {},
                "count": 0,
                "episodes": rows,
            }
        if not close:
            return {
                "ok": False,
                "empty": False,
                "reason": "missing_close_signature",
                "net": None,
                "unit": None,
                "vector": {},
                "count": 0,
                "episodes": rows,
            }
        key = (str(mint), str(close))
        if key in seen:
            return {
                "ok": False,
                "empty": False,
                "reason": "duplicate_episode_identity",
                "net": None,
                "unit": None,
                "vector": {},
                "count": 0,
                "episodes": rows,
            }
        seen.add(key)
        unit = (item or {}).get("unit") or (item or {}).get("settlement_asset")
        net = _decimal((item or {}).get("net") if (item or {}).get("net") not in (None, "") else (item or {}).get("pnl"))
        if unit in (None, ""):
            return {
                "ok": False,
                "empty": False,
                "reason": "missing_settlement_unit",
                "net": None,
                "unit": None,
                "vector": {},
                "count": 0,
                "episodes": rows,
            }
        if net is None:
            return {
                "ok": False,
                "empty": False,
                "reason": "missing_episode_net",
                "net": None,
                "unit": None,
                "vector": {},
                "count": 0,
                "episodes": rows,
            }
        by_unit[unit] = by_unit.get(unit, Decimal("0")) + net
    vector = {unit: _display_decimal(value) for unit, value in by_unit.items()}
    if len(by_unit) == 1:
        unit = next(iter(by_unit))
        return {
            "ok": True,
            "empty": False,
            "reason": None,
            "net": _display_decimal(by_unit[unit]),
            "unit": unit,
            "vector": vector,
            "count": len(rows),
            "episodes": rows,
        }
    return {
        "ok": True,
        "empty": False,
        "reason": "mixed_settlement_units",
        "net": None,
        "unit": "mixed",
        "vector": vector,
        "count": len(rows),
        "episodes": rows,
    }


def episode_net_from_ledger(episodes, fallback_unit=None):
    """Derive net only from a validated ledger. fallback_unit is unused."""
    del fallback_unit
    validated = validate_episode_ledger(episodes)
    if not validated["ok"] or validated.get("empty"):
        return None, validated.get("unit"), validated.get("vector") or {}
    return validated["net"], validated["unit"], validated["vector"]


def qualifying_profit(profile, report=None):
    """Completed-episode ledger net only. Saved profile summaries never qualify."""
    ledger = completed_episode_ledger(report, profile)
    validated = validate_episode_ledger(ledger)
    if not validated["ok"] or validated.get("empty"):
        return None, None, {}
    amount = _decimal(validated["net"])
    return amount, validated["unit"], validated["vector"]


def _saved_fingerprint_id(fingerprint):
    if isinstance(fingerprint, dict):
        return fingerprint.get("fingerprint"), fingerprint.get("completed_episode_ledger")
    if fingerprint:
        return str(fingerprint), None
    return None, None


def _invalidate_saved_decisions(report, profile, *, ledger, contradiction):
    """Recompute fingerprint, audit bind, qualification, and thresholds after overlay."""
    current = compute_audit_fingerprint(report, profile=profile, episodes=ledger)
    saved_id, saved_ledger = _saved_fingerprint_id(profile.get("audit_fingerprint"))
    membership_changed = saved_ledger != current.get("completed_episode_ledger")
    if membership_changed or saved_id != current.get("fingerprint"):
        profile["audit_fingerprint"] = current
    else:
        profile["audit_fingerprint"] = current
    attached = (report or {}).get("independent_audit")
    if contradiction or not certificate_comparison_proof(attached, ledger):
        profile["independent_audit"] = None
    else:
        profile["independent_audit"] = bindable_independent_audit(attached, current, ledger)
    from scanner.mass_search.funnel_abc import classify_candidate
    from scanner.mass_search.research_profile import (
        classify_evidence,
        evaluate_thresholds,
        qualification_category,
        qualification_level,
    )
    from scanner.mass_search.labels import wallet_status_fields

    profile["completed_episode_ledger"] = list(ledger or [])
    eval_profile = dict(profile)
    if contradiction:
        unit = profile.get("completed_episode_net_unit") or "SOL"
        eval_profile["scoped_pnl"] = profile.get("completed_episode_net")
        eval_profile["scoped_pnl_by_quote_asset"] = (
            {unit: profile.get("completed_episode_net")}
            if profile.get("completed_episode_net") not in (None, "")
            else {}
        )
    results = evaluate_thresholds(eval_profile, profile.get("thresholds") or {})
    profile["threshold_results"] = results["results"]
    profile["criteria_met"] = results["criteria_met"]
    profile["evaluated_thresholds"] = results.get("evaluated")
    profile["unset_thresholds"] = results.get("unset")
    profile["evidence_class"] = classify_evidence(report or {}, eval_profile)
    profile["qualification_level"] = qualification_level(report, profile)
    profile["qualification_category"] = qualification_category(report, profile)
    profile["funnel"] = classify_candidate(
        provider_rank=(report or {}).get("provider_rank"),
        provider_trade_count=(report or {}).get("trade_count"),
        provider_score=(report or {}).get("provider_score"),
        capture_available=True,
        profile=profile,
        classification=(report or {}).get("classification"),
        worksheet=(report or {}).get("worksheet"),
    )
    fields = wallet_status_fields(report, profile)
    profile["coverage_status"] = fields["coverage_status"]
    profile["coverage_status_display"] = fields.get("coverage_status_display") or fields["coverage_status"]
    profile["blocking_reason"] = fields["blocking_reason"]
    return profile


def reconcile_saved_profile(report, profile):
    """Overwrite saved summaries from the bound ledger and invalidate stale decisions."""
    profile = dict(profile or {})
    ledger = completed_episode_ledger(report, profile)
    validated = validate_episode_ledger(ledger)
    saved_net = _decimal(profile.get("completed_episode_net"))
    saved_count = profile.get("completed_known_cost_positions")
    if not validated["ok"]:
        profile["completed_episode_net"] = None
        profile["completed_episode_net_unit"] = None
        profile["completed_episode_net_vector"] = {}
        profile["completed_known_cost_positions"] = 0
        profile["scoped_pnl"] = None
        profile["scoped_pnl_unit"] = None
        profile["scoped_pnl_by_quote_asset"] = {}
        profile["ledger_summary_contradiction"] = True
        profile["ledger_validation_reason"] = validated["reason"]
        events = [row for row in (report.get("events") or []) if row.get("kind") in ("buy", "sell")]
        if events:
            profile["sample_positions"] = len(events)
        shares = coverage_shares(report, profile)
        profile["coverage_count_share"] = shares["coverage_count_share"]
        profile["coverage_value_share"] = shares["coverage_value_share"]
        profile["coverage_mandatory_share"] = shares["coverage_mandatory_share"]
        return _invalidate_saved_decisions(report, profile, ledger=ledger, contradiction=True)
    derived_net = _decimal(validated["net"])
    derived_count = validated["count"]
    contradiction = False
    if saved_net is not None and derived_net is not None and saved_net != derived_net:
        contradiction = True
    if saved_net is not None and derived_net is None and saved_net != 0:
        contradiction = True
    if saved_count not in (None, "") and int(saved_count) != int(derived_count):
        contradiction = True
    if validated.get("empty") and (
        (saved_net is not None and saved_net != 0)
        or (saved_count not in (None, "") and int(saved_count) > 0)
        or (profile.get("completed_episode_net_vector") or {})
    ):
        contradiction = True
    profile["completed_episode_net"] = validated["net"]
    profile["completed_episode_net_unit"] = validated["unit"]
    profile["completed_episode_net_vector"] = validated["vector"]
    profile["completed_known_cost_positions"] = derived_count
    if derived_count < 1:
        profile["scoped_pnl"] = None
        profile["scoped_pnl_unit"] = None
        profile["scoped_pnl_by_quote_asset"] = {}
    events = [row for row in (report.get("events") or []) if row.get("kind") in ("buy", "sell")]
    if events:
        profile["sample_positions"] = len(events)
    elif profile.get("sample_positions") in (None, ""):
        sale_count = profile.get("sale_count")
        if sale_count not in (None, ""):
            try:
                profile["sample_positions"] = int(sale_count)
            except (TypeError, ValueError):
                pass
    shares = coverage_shares(report, profile)
    profile["coverage_count_share"] = shares["coverage_count_share"]
    profile["coverage_value_share"] = shares["coverage_value_share"]
    profile["coverage_mandatory_share"] = shares["coverage_mandatory_share"]
    profile["ledger_summary_contradiction"] = contradiction or bool(profile.get("ledger_summary_contradiction"))
    profile["ledger_validation_reason"] = validated.get("reason")
    return _invalidate_saved_decisions(
        report,
        profile,
        ledger=ledger,
        contradiction=bool(profile["ledger_summary_contradiction"]),
    )


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
