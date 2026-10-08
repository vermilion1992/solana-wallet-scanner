"""Shared qualification, coverage, audit-fingerprint and ledger gates.

Accounting policy version is part of the audit content fingerprint. A changed
policy, capture, window, transaction set or completed-episode ledger requires a
new audit. The worksheet total is never the qualifying value.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from statistics import median

ACCOUNTING_POLICY_VERSION = (
    "completed-episode-ledger-v1+asset-atomic-v1+coverage-count-and-value-v1+"
    "audit-1to1-v1"
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
MAX_ECONOMIC_TRADES_PER_UTC_DAY = 25
GT25_ECONOMIC_TRADES_RULE = "gt_25_economic_trades_in_one_day"
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


WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
RAW_QUOTE_ASSETS = frozenset({WSOL_MINT, USDC_MINT, USDT_MINT, "SOL"})
RAW_SOL_NOISE_LAMPORTS = 3_000_000


def _event_unix(event):
    stamp = (event or {}).get("block_time") or (event or {}).get("blockTime") or (event or {}).get("timestamp")
    if type(stamp) is int and not isinstance(stamp, bool):
        return stamp
    if isinstance(stamp, float) and stamp == stamp:
        return int(stamp)
    if isinstance(stamp, str) and stamp:
        try:
            return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp())
        except (TypeError, ValueError):
            return None
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


def gt25_blocker_text(rate):
    if not rate:
        return None
    maximum = first_defined_int(rate.get("max"))
    if maximum is None or maximum <= MAX_ECONOMIC_TRADES_PER_UTC_DAY:
        return None
    day = rate.get("max_on") or "unknown"
    return f"{GT25_ECONOMIC_TRADES_RULE}: {maximum} on {day}"


def with_gt25_blocker(blocker, rate):
    extra = gt25_blocker_text(rate)
    if not extra:
        return blocker
    if not blocker:
        return extra
    if extra in str(blocker):
        return blocker
    return f"{blocker}; {extra}"


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
        day = datetime.fromtimestamp(stamp, tz=timezone.utc).date().isoformat()
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


def _tx_account_keys(record):
    tx = record.get("transaction") if isinstance(record.get("transaction"), dict) else {}
    msg = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    keys = []
    for key in msg.get("accountKeys") or []:
        keys.append(key["pubkey"] if isinstance(key, dict) else key)
    meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
    loaded = meta.get("loadedAddresses") or {}
    keys.extend(list(loaded.get("writable") or []))
    keys.extend(list(loaded.get("readonly") or []))
    return keys


def wallet_asset_deltas(record, address):
    """Net wallet asset deltas. SOL nets native+fee+wSOL; rent/fee noise is dropped."""
    if not isinstance(record, dict) or not address:
        return None
    meta = record.get("meta")
    if not isinstance(meta, dict) or meta.get("err") is not None:
        return None
    deltas = Counter()
    for balance in meta.get("preTokenBalances") or []:
        if not isinstance(balance, dict) or balance.get("owner") != address:
            continue
        mint = balance.get("mint")
        amount = ((balance.get("uiTokenAmount") or {}).get("amount"))
        if mint and amount not in (None, ""):
            deltas[mint] -= int(amount)
    for balance in meta.get("postTokenBalances") or []:
        if not isinstance(balance, dict) or balance.get("owner") != address:
            continue
        mint = balance.get("mint")
        amount = ((balance.get("uiTokenAmount") or {}).get("amount"))
        if mint and amount not in (None, ""):
            deltas[mint] += int(amount)
    keys = _tx_account_keys(record)
    wallet_index = keys.index(address) if address in keys else None
    native = 0
    if wallet_index is not None:
        pre = meta.get("preBalances") or []
        post = meta.get("postBalances") or []
        if wallet_index < len(pre) and wallet_index < len(post):
            native = int(post[wallet_index]) - int(pre[wallet_index])
    fee = int(meta.get("fee") or 0) if keys and keys[0] == address else 0
    wrapped = deltas.pop(WSOL_MINT, 0)
    sol = native + fee + wrapped
    legs = {mint: qty for mint, qty in deltas.items() if qty}
    if abs(sol) > RAW_SOL_NOISE_LAMPORTS:
        legs["SOL"] = sol
    return legs


def raw_economic_keys_for_tx(record, address):
    """One successful economic-swap tx: count once per (kind, mint).

    Opposite-direction asset legs (including token-to-token and stable legs)
    make a swap. Non-quote tokens each contribute one key; a pure
    SOL↔USDC/USDT conversion counts 1. Multi-hop nets to the wallet's
    legs, so one route is one tx.
    """
    legs = wallet_asset_deltas(record, address)
    if not legs:
        return 0
    ups = [mint for mint, qty in legs.items() if qty > 0]
    downs = [mint for mint, qty in legs.items() if qty < 0]
    if not ups or not downs:
        return 0
    tokens = [mint for mint in legs if mint not in RAW_QUOTE_ASSETS]
    return len(tokens) if tokens else 1


def raw_economic_trades_by_utc_day(records, address):
    """Independent raw-tx bot-rate. Decoder-blind venues still count."""
    counts = Counter()
    incomplete = 0
    for record in records or []:
        if not isinstance(record, dict):
            continue
        n_keys = raw_economic_keys_for_tx(record, address)
        if n_keys <= 0:
            continue
        stamp = record.get("blockTime")
        if stamp is None:
            stamp = record.get("block_time") or record.get("timestamp")
        unix = _event_unix({"timestamp": stamp})
        if unix is None:
            incomplete += n_keys
            continue
        day = datetime.fromtimestamp(unix, tz=timezone.utc).date().isoformat()
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
    for rate in rates:
        if not rate:
            continue
        incomplete = incomplete or bool(rate.get("incomplete"))
        uncounted += int(rate.get("incomplete_uncounted") or 0)
        for day, count in (rate.get("by_day") or {}).items():
            try:
                by_day[day] = max(by_day[day], int(count))
            except (TypeError, ValueError):
                continue
        stored_max = first_defined_int(rate.get("max"))
        stored_on = rate.get("max_on")
        if stored_max is None:
            continue
        if stored_on:
            by_day[stored_on] = max(by_day[stored_on], stored_max)
        elif stored_max > (max(by_day.values()) if by_day else -1):
            by_day["stored"] = stored_max
    return _rate_from_by_day(by_day, incomplete=incomplete, incomplete_uncounted=uncounted)


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


def _stored_trade_rate(source):
    if not source:
        return None
    stored = first_defined_int(source.get("max_economic_trades_in_one_day"))
    if stored is None:
        stored = first_defined_int(source.get("max_trades_per_day"))
    if stored is None and not source.get("economic_trades_by_utc_day"):
        return None
    return {
        "by_day": source.get("economic_trades_by_utc_day") or {},
        "max": stored if stored is not None else 0,
        "max_on": source.get("max_economic_trades_on") or source.get("max_trades_per_day_on"),
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
