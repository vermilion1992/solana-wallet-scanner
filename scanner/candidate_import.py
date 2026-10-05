"""Offline public-address imports and dated aggregation of saved candidate cohorts.

Imports contain identifiers only and never perform native verification. Combining
samples preserves their dates, pool memberships and omissions; it does not turn
recent pool observations into a historical wallet ledger or a profit ranking.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import re
import uuid

from .accounting import METHODOLOGY
from .config import validate_address

IMPORT_VERSION = "public-address-import-v1"
UNIVERSE_VERSION = "saved-candidate-universe-v1"
PROGRESS_KEYS = ("observed", "identity_checked", "sample_audited", "history_reconstructed")
HISTORY_CHECKS = ("evidence_history", "evidence_identity", "evidence_basis", "evidence_positions", "evidence_fees")


def _date(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return date.astimezone(timezone.utc) if date.tzinfo is not None else None
    except ValueError:
        return None


def _hashes(values):
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value))) if isinstance(values, list) else []


def _addresses(values):
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        try:
            address = validate_address(value)
        except ValueError:
            continue
        if address not in result:
            result.append(address)
    return result


def _strings(values):
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value)) if isinstance(values, list) else []


def _cap(candidate_cap):
    if type(candidate_cap) is not int or not 1 <= candidate_cap <= 20:
        raise ValueError("Candidate cap must be between 1 and 20.")


def import_candidate_cohort(addresses, *, candidate_cap=20, cohort_id=None, created_at=None):
    """Build one import cohort; the caller may persist it without network reads.

    Input is a list of 1–1000 public-address strings. All entries are validated
    before any result is returned, including entries beyond the retained cap.
    Duplicates preserve first-occurrence order; omitted unique addresses remain
    counted. No labels, credentials, provider claims, or verification fields are
    accepted in the input.
    """
    _cap(candidate_cap)
    if not isinstance(addresses, list) or not 1 <= len(addresses) <= 1000:
        raise ValueError("Import requires a list of 1–1000 public Solana addresses.")
    if cohort_id is not None and (not isinstance(cohort_id, str) or not re.fullmatch(r"[a-f0-9]{32}", cohort_id)):
        raise ValueError("Import cohort identifier must be 32 lowercase hexadecimal characters.")
    timestamp = _date(created_at) if created_at is not None else datetime.now(timezone.utc)
    if timestamp is None:
        raise ValueError("Import date must be an explicit UTC-compatible timestamp.")
    unique = list(dict.fromkeys(validate_address(address) for address in addresses))
    identifier = cohort_id or uuid.uuid4().hex
    observed_at = timestamp.isoformat()
    rows = [{"address": address, "source": "user-list", "origin_type": "user-list", "status": "unresolved",
             "signatures": [], "pools": [], "evidence": [], "observed_buys": 0, "observed_sells": 0,
             "states": dict.fromkeys(PROGRESS_KEYS, False), "stage": "listed",
             "reason": "User-listed public address; native identity and wallet history have not been verified by this import."}
            for address in unique[:candidate_cap]]
    return {"id": identifier, "version": IMPORT_VERSION, "created_at": observed_at, "cohort_date": timestamp.date().isoformat(),
            "source": "user-list", "status": "completed", "stage": "Public addresses imported", "reason": "Public identifiers saved; no provider request or audit was performed.",
            "universe": [], "candidates": rows, "rejected_leads": [], "evidence": [], "misses": [],
            "sample": {"network": "solana", "universe": "User-supplied public address list", "candidate_cap": candidate_cap,
                       "native_validation_cap": 0, "provider_requests": 0, "history_window": None},
            "counts": {"input_rows": len(addresses), "unique_addresses": len(unique), "duplicate_rows": len(addresses) - len(unique),
                       "omitted_addresses": max(0, len(unique) - candidate_cap), "candidates": len(rows), "candidate": 0,
                       "unresolved": len(rows), "rejected": 0, "leads_observed": 0, "leads_deferred": max(0, len(unique) - candidate_cap),
                       "native_transaction_lookups": 0, "native_account_checks": 0},
            "limitations": ["An imported identifier is a research lead, not evidence of observed trading, a verified wallet identity, or profitability.",
                            "Imported members enter the common screening and cohort audit route only after their own native identity evidence is verified.",
                            "The candidate cap retains the first unique addresses; omitted addresses are counted and can be imported in another bounded batch."]}


def _identity_verified(candidate, cohort):
    validation = candidate.get("validation") if isinstance(candidate.get("validation"), dict) else {}
    hashes = set(_hashes(candidate.get("evidence")))
    cohort_evidence = cohort.get("evidence") if isinstance(cohort.get("evidence"), list) else []
    hashes.update(item.get("hash") for item in cohort_evidence if isinstance(item, dict) and isinstance(item.get("hash"), str))
    required = _hashes([validation.get("transaction_evidence_hash"), validation.get("account_evidence_hash")])
    return bool(candidate.get("status") == "candidate" and validation.get("identity_verified") is True and
                validation.get("account_type") == "system-owned signer" and candidate.get("address") in _strings(validation.get("economic_signers")) and
                len(required) == 2 and set(required) <= hashes and isinstance(validation.get("token_flows"), list) and validation["token_flows"])


def _live_report(report, address):
    return isinstance(report, dict) and report.get("source") == "live" and report.get("preview", False) is False and report.get("address") == address


def _sample_report(report):
    evidence = report.get("evidence") if isinstance(report.get("evidence"), list) else []
    return any(isinstance(item, dict) and item.get("kind") in ("transaction", "getTransaction") and _hashes([item.get("hash")]) for item in evidence)


def _history_report(report):
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    checks = report.get("checks") if isinstance(report.get("checks"), list) else []
    return bool(report.get("evidence_status") == "verified" and report.get("methodology") == METHODOLOGY and _sample_report(report) and
                coverage.get("history_scope_complete") is True and coverage.get("historical_ownership_verified") is True and
                all(len([check for check in checks if isinstance(check, dict) and check.get("key") == key]) == 1 and
                    next(check for check in checks if isinstance(check, dict) and check.get("key") == key).get("state") == "PASS" for key in HISTORY_CHECKS))


def derive_candidate_progress(candidate, cohort=None, reports=()):
    """Derive evidence stages; a completed job alone never advances a stage.

    ``identity_checked`` denotes a recorded successful native identity check.
    ``sample_audited`` needs a live report linked to actual transaction evidence.
    ``history_reconstructed`` additionally needs explicit verified history and
    ownership coverage plus passing history/basis/positions/fees checks.
    It does not require profitable financial thresholds.
    """
    if not isinstance(candidate, dict):
        raise ValueError("Candidate progress requires a candidate object.")
    cohort = cohort if isinstance(cohort, dict) else {}
    try:
        address = validate_address(candidate.get("address"))
    except ValueError:
        address = None
    rows = [report for report in reports if _live_report(report, address)] if isinstance(reports, (list, tuple)) else []
    observed = bool(candidate.get("source") == "pool-trades" and _strings(candidate.get("signatures")) and
                    _addresses(candidate.get("pools")) and _hashes(candidate.get("evidence")))
    sample_reports = [report for report in rows if _sample_report(report)]
    history_reports = [report for report in sample_reports if _history_report(report)]
    states = {"observed": observed, "identity_checked": bool(address and _identity_verified(candidate, cohort)),
              "sample_audited": bool(sample_reports), "history_reconstructed": bool(history_reports)}
    stage = next((key for key in reversed(PROGRESS_KEYS) if states[key]), "listed")
    return {"states": states, "stage": stage,
            "sample_report_ids": _strings([report.get("id") for report in sample_reports]),
            "history_report_ids": _strings([report.get("id") for report in history_reports])}


def aggregate_candidate_universe(cohorts, reports=(), *, candidate_cap=20):
    """Deduplicate saved cohort members, preserving dated origins and omissions.

    This is an offline display, capped independently of durable cohort records.
    No report, cohort, quota, or native verification state is mutated. Sorting is
    latest saved membership first, then public address; no profit rank is inferred.
    """
    _cap(candidate_cap)
    if not isinstance(cohorts, (list, tuple)):
        raise ValueError("Saved universe requires a cohort list.")
    reports = [report for report in reports if isinstance(report, dict)] if isinstance(reports, (list, tuple)) else []
    merged, seen_cohorts = {}, set()
    counts = {"cohorts": 0, "candidate_records": 0, "duplicate_records": 0, "invalid_records": 0, "memberships": 0}
    for cohort in cohorts:
        if not isinstance(cohort, dict) or not isinstance(cohort.get("id"), str) or not cohort["id"] or cohort["id"] in seen_cohorts:
            continue
        if cohort.get("source") == "demo":
            continue
        seen_cohorts.add(cohort["id"])
        counts["cohorts"] += 1
        candidates = cohort.get("candidates") if isinstance(cohort.get("candidates"), list) else []
        seen_members = set()
        for candidate in candidates:
            counts["candidate_records"] += 1
            if not isinstance(candidate, dict):
                counts["invalid_records"] += 1
                continue
            try:
                address = validate_address(candidate.get("address"))
            except ValueError:
                counts["invalid_records"] += 1
                continue
            if candidate.get("source") == "demo":
                counts["invalid_records"] += 1
                continue
            if address in seen_members:
                counts["duplicate_records"] += 1
                continue
            seen_members.add(address)
            counts["memberships"] += 1
            origin_type = "user-list" if candidate.get("source") == "user-list" or cohort.get("source") == "user-list" else "pool-trades"
            linked_ids = _strings([candidate.get("report_id")])
            scan_ids = _strings(cohort.get("audit_scan_ids"))
            linked_reports = [report for report in reports if report.get("id") in linked_ids or report.get("scan_id") in scan_ids or report.get("discovery_cohort_id") == cohort["id"]]
            progress = derive_candidate_progress(candidate, cohort, linked_reports)
            origin = {"cohort_id": cohort["id"], "created_at": cohort.get("created_at") if _date(cohort.get("created_at")) else None,
                      "cohort_date": cohort.get("cohort_date"), "source": cohort.get("source"), "origin_type": origin_type,
                      "member_status": candidate.get("status") if candidate.get("status") in ("candidate", "rejected", "unresolved") else "unresolved",
                      "states": progress["states"], "pools": _addresses(candidate.get("pools")), "signatures": _strings(candidate.get("signatures")),
                      "evidence": _hashes(candidate.get("evidence")), "reason": candidate.get("reason", "Saved research lead")}
            row = merged.setdefault(address, {"address": address, "source": "saved-universe", "status": "unresolved", "first_seen": None, "last_seen": None,
                                              "origin_types": [], "cohort_ids": [], "origins": [], "pools": [], "signatures": [], "evidence": [],
                                              "report_ids": [], "audit_eligible_cohort_ids": [], "states": dict.fromkeys(PROGRESS_KEYS, False),
                                              "reason": "Dated saved research memberships; observed activity and identity checks do not establish historical profit."})
            row["origins"].append(origin)
            row["origin_types"] = _strings(row["origin_types"] + [origin_type])
            row["cohort_ids"].append(cohort["id"])
            row["pools"] = _addresses(row["pools"] + origin["pools"])
            row["signatures"] = _strings(row["signatures"] + origin["signatures"])
            row["evidence"] = _hashes(row["evidence"] + origin["evidence"])
            row["report_ids"] = _strings(row["report_ids"] + linked_ids)
            for key in PROGRESS_KEYS:
                row["states"][key] |= progress["states"][key]
            if progress["states"]["identity_checked"]:
                row["audit_eligible_cohort_ids"].append(cohort["id"])
            date = _date(origin["created_at"])
            if date:
                if row["first_seen"] is None or date < _date(row["first_seen"]):
                    row["first_seen"] = date.isoformat()
                if row["last_seen"] is None or date > _date(row["last_seen"]):
                    row["last_seen"] = date.isoformat()
    for address, row in merged.items():
        progress = derive_candidate_progress({"address": address}, reports=reports)
        for key in ("sample_audited", "history_reconstructed"):
            row["states"][key] |= progress["states"][key]
        row["report_ids"] = _strings(row["report_ids"] + progress["sample_report_ids"])
        live_reports = [report for report in reports if _live_report(report, address) and isinstance(report.get("id"), str)]
        if live_reports:
            latest = max(live_reports, key=lambda report: (_date(report.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), report["id"]))
            row["report_id"] = latest["id"]
        row["stage"] = next((key for key in reversed(PROGRESS_KEYS) if row["states"][key]), "listed")
        row["status"] = "candidate" if row["states"]["identity_checked"] else "rejected" if all(origin["member_status"] == "rejected" for origin in row["origins"]) else "unresolved"
        row["origins"].sort(key=lambda origin: (origin["created_at"] or "", origin["cohort_id"]))
    ordered = sorted(merged.values(), key=lambda row: (-(_date(row["last_seen"]).timestamp() if row["last_seen"] else float("-inf")), row["address"]))
    returned = ordered[:candidate_cap]
    counts.update(unique_candidates=len(ordered), returned_candidates=len(returned), omitted_candidates=max(0, len(ordered) - candidate_cap),
                  returned_memberships=sum(len(row["origins"]) for row in returned))
    counts["omitted_memberships"] = counts["memberships"] - counts["returned_memberships"]
    for key in PROGRESS_KEYS:
        counts[key] = sum(row["states"][key] for row in ordered)
    return {"version": UNIVERSE_VERSION, "candidates": returned, "counts": counts, "limits": {"candidate_cap": candidate_cap},
            "limitations": ["Memberships preserve each discovery/import date and pool set. Combining them does not establish 30-day coverage or a wallet profit ranking.",
                            "Successful native identity, a bounded sample report, and reconstructed history are separate evidence stages; a completed job advances none of them by itself.",
                            "The display cap omits counted saved candidates and memberships without deleting their original cohorts.",
                            "Imported addresses remain unresolved until separate native evidence exists. Audit eligibility applies to the original verified cohort membership."]}
