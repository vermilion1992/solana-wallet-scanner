"""Strict report qualification and factual, read-only copy suitability observations.

Qualification uses the saved strict policy, never conditional research profit.
Behavior diagnostics describe observed episodes and token capabilities, without
asserting misconduct, copy execution, or safety. No provider calls are made.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext
import re

from .accounting import METHODOLOGY, canonical, decimal
from .history_evidence import VERSION as HISTORY_METHODOLOGY
from .position_evidence import VERSION as POSITION_METHODOLOGY
from .research import VERSION as RESEARCH_METHODOLOGY


EVIDENCE_KEYS = tuple("evidence_" + name for name in
                      ("history", "identity", "basis", "positions", "fees", "classification", "valuation", "findings"))
METRIC_KEYS = ("profit_sol", "realised_roi_pct", "median_roi_pct", "win_rate_pct", "median_hold_hours",
               "completed_positions", "completed_positions_90d", "traded_mints", "rapid_sale_pct",
               "avg_buys", "avg_sells", "positive_weeks", "largest_contribution_pct")
UNKNOWN_REVIEW_KEYS = ("follower_exploitation", "creator_links", "liquidity_withdrawal", "holder_concentration")
with localcontext() as _context:
    _context.prec = 192
    FIVE_MINUTES_HOURS = Decimal(1) / Decimal(12)


def _number(value, *, signed=False):
    try:
        return decimal(value, signed=signed, max_length=512)
    except (ValueError, TypeError, AttributeError):
        return None


def _hashes(values):
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value))) if isinstance(values, list) else []


def qualify_report(report):
    """Return qualification for the saved report/preset; do not re-filter it.

    All PDF gate and metric keys must appear exactly once and explicitly PASS.
    Synthetic reports, previews, stale/partial evidence and conditional profit
    cannot qualify. The immutable report and its checks are never changed.
    """
    if not isinstance(report, dict):
        raise ValueError("Qualification requires a report object.")
    preset = report.get("preset") if isinstance(report.get("preset"), dict) else {}
    required = EVIDENCE_KEYS + METRIC_KEYS + (("economic_pnl_sol",) if preset.get("require_positive_economic_pnl", True) else ())
    raw_checks = report.get("checks")
    checks = [deepcopy(check) for check in raw_checks if isinstance(check, dict)] if isinstance(raw_checks, list) else []
    if isinstance(raw_checks, list) and any(not isinstance(check, dict) for check in raw_checks):
        checks.append({"key": "saved_checks", "label": "Saved checks", "state": "UNKNOWN", "actual": None,
                       "reason": "Saved report contains a malformed check."})
    for check in checks:
        if check.get("state") not in ("PASS", "FAIL", "UNKNOWN"):
            check.update(state="UNKNOWN", reason="Saved check has no valid evidence state.")
    for key in required:
        matching = [check for check in checks if check.get("key") == key]
        if len(matching) != 1:
            checks.append({"key": key, "label": key.replace("_", " ").capitalize(), "state": "UNKNOWN",
                           "actual": None, "reason": "Required saved-policy check is missing or repeated."})
    current_method = report.get("methodology") == METHODOLOGY
    if not current_method:
        checks.append({"key": "methodology", "label": "Current accounting methodology", "state": "UNKNOWN",
                       "actual": report.get("methodology"), "expected": METHODOLOGY,
                       "reason": "Rebuild this saved report from source evidence using the current accounting methodology."})
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    history = coverage.get("history_evidence") if isinstance(coverage.get("history_evidence"), dict) else {}
    saved_history = history.get("version")
    current_history = saved_history == HISTORY_METHODOLOGY
    if not current_history:
        checks.append({"key": "history_methodology", "label": "Current account receipt methodology", "state": "UNKNOWN",
                       "actual": saved_history, "expected": HISTORY_METHODOLOGY,
                       "reason": "Rebuild from saved records to reconcile account-specific receipts under the current methodology."})
    position = coverage.get("position_evidence") if isinstance(coverage.get("position_evidence"), dict) else {}
    saved_position = position.get("version")
    current_position = saved_position == POSITION_METHODOLOGY
    if not current_position:
        checks.append({"key": "position_methodology", "label": "Current account position methodology", "state": "UNKNOWN",
                       "actual": saved_position, "expected": POSITION_METHODOLOGY,
                       "reason": "Rebuild from saved records to evaluate all position chronology dependencies under the current methodology."})
    if report.get('archive_input_hash'):
        from .archive_input import METHOD as ARCHIVE_METHODOLOGY
        archive = report.get('archive_accounting')
        saved_archive = archive.get('version') if isinstance(archive, dict) else None
        if saved_archive != ARCHIVE_METHODOLOGY:
            checks.append({'key': 'archive_methodology', 'label': 'Current archived-source methodology', 'state': 'UNKNOWN',
                           'actual': saved_archive, 'expected': ARCHIVE_METHODOLOGY,
                           'reason': 'Rebuild this archived report offline before qualification under the current source interpretation.'})
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    profit = metrics.get("profit_sol") if isinstance(metrics.get("profit_sol"), dict) else {}
    amount = _number(profit.get("value"), signed=True) if profit.get("status") == "known" else None
    if amount is None and not any(check.get("key") == "strict_profit_value" for check in checks):
        checks.append({"key": "strict_profit_value", "label": "Strict profit value", "state": "UNKNOWN", "actual": None,
                       "reason": "A known strict profit metric is required; conditional research P&L cannot substitute."})
    failed = [check for check in checks if check["state"] == "FAIL"]
    unknown = [check for check in checks if check["state"] == "UNKNOWN"]
    policy = report.get("policy") if report.get("policy") in ("MATCH", "MISS", "UNRESOLVED") else "UNRESOLVED"
    evidence = report.get("evidence_status") if report.get("evidence_status") in ("verified", "partial", "unknown", "stale") else "unknown"
    eligible_source = report.get("source") == "live" and report.get("preview", False) is False
    qualified = bool(eligible_source and current_method and current_history and current_position and policy == "MATCH" and evidence == "verified" and amount is not None and
                     isinstance(raw_checks, list) and raw_checks and len(checks) == len(raw_checks) and
                     all(check["state"] == "PASS" for check in checks))
    if qualified:
        reason = "The saved live report passes every required check for its saved filters with verified evidence."
    elif not eligible_source:
        reason = "Demo, synthetic and preview reports do not qualify as live wallet matches."
    elif not current_method:
        reason = "Rebuild this saved report using the current accounting methodology before qualification."
    elif not current_history:
        reason = "Rebuild this saved report using the current account receipt methodology before qualification."
    elif not current_position:
        reason = "Rebuild this saved report using the current account position methodology before qualification."
    elif failed:
        reason = "Known strict checks fail; other unresolved checks remain visible."
    elif unknown or evidence != "verified":
        reason = "Required financial or evidence checks remain unresolved."
    else:
        reason = "The saved financial policy does not establish a strict match."
    return {"report_id": report.get("id"), "preset_version": preset.get("version"), "preset_snapshot": deepcopy(preset),
            "methodology": report.get("methodology"), "window": deepcopy(report.get("window")),
            "financial_policy": policy, "evidence_status": evidence, "profit_sol": canonical(amount),
            "qualified": qualified, "failed_checks": failed, "unknown_checks": unknown, "checks": checks,
            "reason": reason, "notes": ["Qualification applies to this saved preset and reporting window.",
                                       "Financial qualification does not certify trader intent, copied fills, or future safety."]}


def review_copy_behavior(report):
    """Describe observed behavior without changing strict policy or claiming safety.

    Independently reviewed findings may be supplied as ``reviewed_copy_checks``
    or existing token gates. A supplied PASS/FAIL is retained only with
    ``reviewed: true``, ``primary_evidence: true`` (or a hash list), and evidence
    hashes present in the report's source evidence. Other missing reviews remain
    UNKNOWN; this helper does not create an independent review certificate.
    """
    if not isinstance(report, dict):
        raise ValueError("Copy review requires a report object.")
    preset = report.get("preset") if isinstance(report.get("preset"), dict) else {}
    research = report.get("research") if isinstance(report.get("research"), dict) else {}
    current_research = research.get('version') == RESEARCH_METHODOLOGY
    source_checks = report.get("checks") if isinstance(report.get("checks"), list) else []
    position_checks = [check for check in source_checks if isinstance(check, dict) and check.get("key") == "evidence_positions"]
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    history = coverage.get("history_evidence") if isinstance(coverage.get("history_evidence"), dict) else {}
    position = coverage.get("position_evidence") if isinstance(coverage.get("position_evidence"), dict) else {}
    verified_positions = (report.get("source") == "live" and report.get("evidence_status") == "verified" and history.get("version") == HISTORY_METHODOLOGY and
                          position.get("version") == POSITION_METHODOLOGY and
                          report.get("methodology") == METHODOLOGY and report.get("preview", False) is False and
                          len(position_checks) == 1 and position_checks[0].get("state") == "PASS")
    rows = report.get("positions", []) if verified_positions else research.get("episodes", []) if current_research else []
    rows = [row for row in rows if isinstance(row, dict) and row.get("status") == "closed" and row.get("in_window", True) is True] if isinstance(rows, list) else []
    conditional = not verified_positions
    scope = ("Verified strict completed positions in the saved reporting window" if verified_positions else
             "Observed supported spot episodes in the fetched subset; timing remains conditional on earlier inventory and intervening flows")
    chronology_known = research.get("chronology_unknown") is not True or verified_positions or current_research
    findings, checks = [], {}
    min_hold = _number(preset.get("min_hold_hours", "1"))
    max_rapid = _number(preset.get("max_rapid_sale_pct", "10"))
    if min_hold is None:
        min_hold = Decimal(1)
    if max_rapid is None:
        max_rapid = Decimal(10)

    def observe(key, detail, actual=None, evidence=None, **extra):
        checks[key] = {"state": "OBSERVED", "detail": detail, "actual": actual,
                       "evidence": _hashes(evidence or []), "conditional": conditional, **extra}

    def unknown(key, detail):
        checks[key] = {"state": "UNKNOWN", "detail": detail, "actual": None, "evidence": [], "conditional": conditional}

    if not current_research and not verified_positions:
        unknown('research_methodology', 'Saved scoped research is stale or missing; create an immutable offline child before using its observations.')

    def timing_supported(row):
        # Global uncertainty may coexist with an independently supported v3
        # episode. A roleless legacy row cannot declare that disjointness.
        state = row.get('timing_state')
        if not verified_positions and research.get('chronology_unknown') is True:
            return current_research and state == 'PASS'
        return row.get('timing_state', 'PASS') == 'PASS'

    timing_rows = []
    for row in rows if chronology_known else []:
        if not timing_supported(row):
            continue
        hold, exit90, first = (_number(row.get(key)) for key in ("hold_hours", "sold_90_pct_hours", "first_sale_hours"))
        evidence = _hashes(row.get("evidence"))
        if hold is not None and exit90 is not None and exit90 <= hold:
            timing_rows.append((row, hold, exit90, first, evidence))
            if exit90 <= FIVE_MINUTES_HOURS and hold >= min_hold:
                findings.append({"key": "long_tail_hold", "severity": "warning", "title": "Remainder extends final holding time",
                                 "detail": "At least 90% of observed acquired units sold within five minutes, while the final strict-zero exit met the minimum holding time. These timings describe different behavior.",
                                 "actual": {"episode_id": row.get("id"), "mint": row.get("mint"), "final_hold_hours": canonical(hold),
                                            "exit_90_hours": canonical(exit90), "threshold_hours": canonical(min_hold)},
                                 "evidence": evidence, "conditional": conditional or row.get("conditional") is True})
    if timing_rows:
        observe("long_tail_holds", "Final holding time is compared with the time to sell 90% of observed acquired units; this diagnostic does not change strict holding metrics.",
                {"observed_episodes": len(rows), "episodes_with_known_timings": len(timing_rows),
                 "long_tail_episodes": sum(item["key"] == "long_tail_hold" for item in findings), "minimum_hold_hours": canonical(min_hold)},
                [digest for _, _, _, _, hashes in timing_rows for digest in hashes])
    else:
        unknown("long_tail_holds", "Completed episodes with evidenced final and 90% exit timings are needed.")
    first_values = [(row, _number(row.get("first_sale_hours")) if timing_supported(row) else None)
                    for row in rows] if chronology_known else []
    if first_values and all(value is not None for _, value in first_values):
        with localcontext() as context:
            context.prec = 192
            rapid_count = sum(value <= FIVE_MINUTES_HOURS for _, value in first_values)
            rapid_pct = Decimal(rapid_count) / Decimal(len(first_values)) * Decimal(100)
        above = rapid_pct > max_rapid
        observe("rapid_first_sales", "First positive economic sale within five minutes, measured only over the observed completed subset. This is an observational comparison, not a strict policy failure or misconduct finding.",
                {"rapid_episodes": rapid_count, "completed_episodes": len(first_values), "observed_pct": canonical(rapid_pct), "preset_max_pct": canonical(max_rapid)},
                [digest for row, _ in first_values for digest in _hashes(row.get("evidence"))], comparison="ABOVE_PRESET" if above else "WITHIN_PRESET")
        if above:
            findings.append({"key": "rapid_first_sales", "severity": "warning", "title": "Observed early exits exceed the preset reference",
                             "detail": checks["rapid_first_sales"]["detail"], "actual": checks["rapid_first_sales"]["actual"],
                             "evidence": checks["rapid_first_sales"]["evidence"], "conditional": conditional})
    else:
        unknown("rapid_first_sales", "All eligible episode first-sale timings and chronology are needed for this subset comparison.")

    def count(value):
        return value if type(value) is int and value >= 0 else None
    unresolved_basis = count(research.get("unresolved_basis_sales")) if current_research else None
    unmatched = count(research.get("observed_unmatched_sales")) if current_research else None
    if unresolved_basis is not None or unmatched is not None:
        observe("unmatched_basis", "Sales with unresolved earlier inventory or unmatched fetched purchase cost remain counted; they cannot be treated as zero-cost profit.",
                {"unresolved_basis_sales": unresolved_basis, "observed_unmatched_sales": unmatched}, research.get("evidence"))
    else:
        unknown("unmatched_basis", "Sale matching and acquisition provenance have not been assessed.")
    events = report.get("events")
    if isinstance(events, list):
        incoming = [event for event in events if isinstance(event, dict) and event.get("kind") == "transfer_in"]
        observe("incoming_transfers", "Observed incoming token movements require acquisition provenance; their presence alone does not establish a gift, insider allocation, cost basis, or misconduct. Counts cover the supplied retrieved records, including any basis lookback.",
                {"observed_transfers": len(incoming), "without_supplied_basis": sum(event.get("basis_sol") is None for event in incoming)},
                [digest for event in incoming for digest in _hashes(event.get("evidence"))])
    else:
        unknown("incoming_transfers", "Retrieved token transfer evidence is unavailable.")

    token_risk = report.get("token_risk") if isinstance(report.get("token_risk"), list) else []
    token_flags, token_observations, unknown_controls = [], [], set()
    for token_index, token in enumerate(token_risk):
        if not isinstance(token, dict):
            unknown_controls.add((token_index, "token_observation"))
            continue
        gates = token.get("gates") if isinstance(token.get("gates"), dict) else {}
        for key, gate in gates.items():
            if not isinstance(gate, dict) or gate.get("state") not in ("PASS", "FAIL", "OBSERVED", "FLAGGED"):
                unknown_controls.add((token_index, key))
        retained_keys = set()
        for finding in token.get("findings", []) if isinstance(token.get("findings"), list) else []:
            if isinstance(finding, dict):
                hashes = _hashes(finding.get("evidence"))
                key = finding.get("key") if isinstance(finding.get("key"), str) else "token_finding"
                if finding.get("state") not in ("PASS", "FAIL", "OBSERVED", "FLAGGED") or not hashes:
                    unknown_controls.add((token_index, key))
                    continue
                copied = deepcopy(finding)
                copied.setdefault("key", "token_finding")
                copied.setdefault("severity", "info")
                copied.setdefault("title", "Recorded token observation")
                copied.setdefault("detail", "Legacy token finding lacks a description; inspect the original report.")
                copied.setdefault("mint", token.get("mint"))
                copied.setdefault("conditional", True)
                copied["evidence"] = hashes
                findings.append(copied)
                token_observations.append(copied)
                retained_keys.add(key)
                if finding.get("state") == "FAIL":
                    token_flags.append(copied)
        for key, gate in gates.items():
            if not isinstance(gate, dict) or gate.get("state") != "FAIL" or key in retained_keys:
                continue
            hashes = _hashes(gate.get("evidence"))
            if not hashes:
                unknown_controls.add((token_index, key))
                continue
            copied = {"key": key, "state": "FAIL", "severity": "warning", "mint": token.get("mint"),
                      "title": str(key).replace("_", " ").capitalize(), "detail": gate.get("detail", "Recorded current token capability requires review."),
                      "actual": deepcopy(gate.get("actual")), "evidence": hashes, "conditional": True}
            findings.append(copied)
            token_observations.append(copied)
            token_flags.append(copied)
    if token_risk:
        checks["current_token_findings"] = {"state": "FLAGGED" if token_flags else "UNKNOWN" if unknown_controls else "OBSERVED",
                                            "detail": f"{len(token_observations)} evidenced current token observations retained; {len(unknown_controls)} control findings remain unresolved in the token-risk gates. Current capabilities do not establish misconduct or future sellability.",
                                            "actual": {"mints_observed": len(token_risk), "flagged_findings": len(token_flags),
                                                       "observed_control_findings": len(token_observations), "unknown_control_findings": len(unknown_controls)},
                                            "evidence": list(dict.fromkeys(digest for item in token_observations for digest in _hashes(item.get("evidence")))), "conditional": True}
    else:
        unknown("current_token_findings", "Current token controls have not been supplied.")

    supplied = report.get("reviewed_copy_checks") if isinstance(report.get("reviewed_copy_checks"), dict) else {}
    primary_hashes = set(_hashes([item.get("hash") for item in report.get("evidence", []) if isinstance(item, dict)])) if isinstance(report.get("evidence"), list) else set()
    aliases = {"liquidity_withdrawal": "liquidity_control"}
    scoped_mints = set()
    for population in (report.get("events"), report.get("positions"), research.get("episodes")):
        if isinstance(population, list):
            scoped_mints.update(item["mint"] for item in population if isinstance(item, dict) and
                                isinstance(item.get("mint"), str) and item["mint"] and item.get("classification") != "settlement" and
                                item["mint"] != "So11111111111111111111111111111111111111112")
    observed_mints = {token["mint"] for token in token_risk if isinstance(token, dict) and isinstance(token.get("mint"), str) and token["mint"]}
    token_scope_covered = not scoped_mints or scoped_mints <= observed_mints
    def valid_review(gate):
        if not isinstance(gate, dict):
            return False
        hashes = _hashes(gate.get("evidence"))
        primary = gate.get("primary_evidence")
        explicit_primary = primary is True or bool(_hashes(primary)) and set(_hashes(primary)) <= set(hashes)
        return bool(gate.get("reviewed") is True and explicit_primary and hashes and set(hashes) <= primary_hashes and gate.get("state") in ("PASS", "FAIL"))
    for key in UNKNOWN_REVIEW_KEYS:
        wallet_review = supplied.get(key)
        token_reviews = [token.get("gates", {}).get(aliases.get(key, key)) for token in token_risk if isinstance(token, dict) and isinstance(token.get("gates"), dict)]
        reviewed = [wallet_review] if valid_review(wallet_review) else [gate for gate in token_reviews if valid_review(gate)]
        if reviewed and (valid_review(wallet_review) or len(reviewed) == len(token_risk) and bool(token_risk) and token_scope_covered):
            selected = next((gate for gate in reviewed if gate["state"] == "FAIL"), reviewed[0])
            checks[key] = {**deepcopy(selected), "detail": selected.get("detail") if isinstance(selected.get("detail"), str) else "Existing independent review of the stated primary evidence.",
                           "actual": selected.get("actual"), "evidence": _hashes(selected.get("evidence")), "conditional": False}
        else:
            unknown(key, "Independent reviewed primary evidence is required; absence of a detected finding does not establish this check.")
    return {"scope": scope, "conditional": conditional, "checks": checks, "findings": findings,
            "unknown_checks": [key for key, check in checks.items() if check["state"] == "UNKNOWN"],
            "notes": ["Observed timing comparisons do not modify the saved strict policy or allege trader intent.",
                      "Current token permissions and reported liquidity cannot establish safe copying or future exits.",
                      "No safety score, copied-fill estimate, replay, paper trading or execution is produced."]}
