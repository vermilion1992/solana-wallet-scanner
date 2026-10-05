#!/usr/bin/env python3
"""Offline contract/integrity checks; NOT chain provenance or profit verification.

Exit 0: declared contract and applicable profile conditions are satisfied.
Exit 1: malformed, inconsistent or corrupt receipt/artifact.
Exit 2: valid structure, but requested live/forward evidence is incomplete.

Uses only the Python standard library. Never reads credentials or the network.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

VERSION = "mass-search-receipt-v1"
HASH = re.compile(r"^[a-f0-9]{64}$")
COMMIT = re.compile(r"^[a-f0-9]{40}$")
DECIMAL = re.compile(r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")
CORPORA = {"SYNTHETIC", "GENUINE_REPLAY", "GENUINE_LIVE"}
STAGES = ("triage", "behaviour", "reconstruct", "forward_select")
ROLES = {
    "candidate_snapshot", "decisions", "requests", "budget_ledger",
    "source_manifest", "wallet_reports", "reconciliation", "test_results",
    "selection_manifest", "forward_signals", "forward_quotes", "forward_positions",
}
LIVE_ROLES = {"candidate_snapshot", "decisions", "requests", "budget_ledger", "source_manifest"}
ANALYTICS_ROLES = {"wallet_reports", "reconciliation", "source_manifest"}
FORWARD_ROLES = {"selection_manifest", "forward_signals", "forward_quotes", "forward_positions", "budget_ledger", "source_manifest"}
MAX_RECEIPT_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
DISCLAIMER = "Contract/integrity checks only; genuine provenance, independent arithmetic and financial usefulness require separate review."


class InvalidReceipt(ValueError):
    """The supplied receipt violates the fixed v1 contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidReceipt(message)


def fields(value: Any, names: str, where: str) -> dict:
    require(isinstance(value, dict), f"{where}: expected object")
    wanted = set(names.split())
    require(set(value) == wanted, f"{where}: missing={sorted(wanted-set(value))}; unexpected={sorted(set(value)-wanted)}")
    return value


def count(value: Any, where: str) -> int:
    require(type(value) is int and value >= 0, f"{where}: expected nonnegative integer (not boolean)")
    return value


def boolean(value: Any, where: str) -> bool:
    require(type(value) is bool, f"{where}: expected boolean")
    return value


def text(value: Any, where: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{where}: expected nonempty string")
    return value


def enum(value: Any, allowed: set | tuple, where: str) -> str:
    require(isinstance(value, str) and value in allowed, f"{where}: unsupported value")
    return value


def digest(value: Any, where: str) -> str:
    require(isinstance(value, str) and HASH.fullmatch(value) is not None, f"{where}: expected lowercase SHA-256")
    return value


def timestamp(value: Any, where: str) -> datetime:
    text(value, where)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidReceipt(f"{where}: invalid ISO datetime") from exc
    require(result.tzinfo is not None and result.utcoffset() is not None, f"{where}: explicit timezone required")
    return result


def money(value: Any, where: str) -> Decimal:
    require(isinstance(value, str) and len(value) <= 80 and DECIMAL.fullmatch(value) is not None,
            f"{where}: expected unsigned fixed-point decimal string")
    return Decimal(value)


def finite_measure(value: Any, where: str) -> None:
    if value is not None:
        require(type(value) in (int, float), f"{where}: expected finite number or null")
        try:
            valid = value >= 0 and math.isfinite(value)
        except (OverflowError, ValueError):
            valid = False
        require(valid, f"{where}: expected nonnegative finite measure")


def unique_json(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidReceipt(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise InvalidReceipt(f"Non-finite JSON constant: {value}")


def load_receipt(path: Path) -> dict:
    require(path.stat().st_size <= MAX_RECEIPT_BYTES, "Receipt exceeds 2 MiB")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_json,
                          parse_constant=reject_constant)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidReceipt(f"Receipt is not valid UTF-8 JSON: {exc}") from exc


def artifact_roles(items: Any, root: Path) -> dict[str, set[str]]:
    require(isinstance(items, list) and bool(items), "artifacts: nonempty list required")
    require(root.is_dir(), "Evidence root must be an existing directory")
    root = root.resolve()
    seen = set()
    roles = {kind: set() for kind in CORPORA}
    for index, item in enumerate(items):
        label = f"artifacts[{index}]"
        item = fields(item, "path sha256 corpus_kind roles", label)
        relative = text(item["path"], label + ".path")
        p = PurePosixPath(relative)
        require("\\" not in relative and ":" not in relative and "\x00" not in relative
                and not p.is_absolute() and ".." not in p.parts and relative != ".",
                label + ": artifact path must be relative and cannot traverse")
        try:
            target = (root / p).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise InvalidReceipt(f"{label}: missing/unresolvable artifact") from exc
        require(target.is_relative_to(root), label + ": artifact escapes evidence root")
        require(target.is_file(), label + ": artifact must be a regular file")
        require(target not in seen, label + ": duplicate artifact target")
        seen.add(target)
        require(target.stat().st_size <= MAX_ARTIFACT_BYTES, label + ": artifact exceeds 64 MiB")
        expected = digest(item["sha256"], label + ".sha256")
        h = hashlib.sha256()
        size = 0
        with target.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                size += len(chunk)
                require(size <= MAX_ARTIFACT_BYTES, label + ": artifact grew beyond 64 MiB")
                h.update(chunk)
        require(h.hexdigest() == expected, label + ": artifact SHA-256 mismatch")
        kind = enum(item["corpus_kind"], CORPORA, label + ".corpus_kind")
        supplied = item["roles"]
        require(isinstance(supplied, list) and bool(supplied), label + ": artifact roles required")
        for role in supplied:
            enum(role, ROLES, label + ".roles[]")
        require(len(supplied) == len(set(supplied)), label + ": duplicate roles")
        roles[kind].update(supplied)
    return roles


def validate(receipt: Any, evidence_root: Path, profile: str = "development") -> dict:
    """Validate a receipt declaration without authenticating its financial claims."""
    enum(profile, {"development", "live-search", "forward-operation"}, "profile")
    r = fields(receipt, "schema_version run_id corpus_kind application execution selection universe stages budget measurements analytics forward artifacts claims notes", "receipt")
    require(r["schema_version"] == VERSION, "Unsupported receipt version")
    require(isinstance(r["run_id"], str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", r["run_id"]), "Invalid run_id")
    kind = enum(r["corpus_kind"], CORPORA, "corpus_kind")
    a = fields(r["application"], "commit source_sha256 dirty lock_sha256", "application")
    require(isinstance(a["commit"], str) and COMMIT.fullmatch(a["commit"]) is not None, "application.commit: full lowercase Git SHA required")
    digest(a["source_sha256"], "application.source_sha256")
    require(boolean(a["dirty"], "application.dirty") is False, "Acceptance source must be frozen, not dirty")
    require(isinstance(a["lock_sha256"], dict) and bool(a["lock_sha256"]), "application.lock_sha256: nonempty object required")
    for name, sha in a["lock_sha256"].items():
        text(name, "lock name")
        digest(sha, "lock digest")

    execution = fields(r["execution"], "started_at ended_at status exit_code", "execution")
    start = timestamp(execution["started_at"], "execution.started_at")
    end = timestamp(execution["ended_at"], "execution.ended_at") if execution["ended_at"] is not None else None
    state = enum(execution["status"], {"COMPLETE", "PARTIAL", "BLOCKED", "RUNNING"}, "execution.status")
    if execution["exit_code"] is not None:
        count(execution["exit_code"], "execution.exit_code")
    if end is not None:
        require(end >= start, "Execution ends before it starts")
    if state == "COMPLETE":
        require(end is not None and type(execution["exit_code"]) is int and execution["exit_code"] == 0, "Complete execution needs end time and zero exit code")
    if state == "RUNNING":
        require(end is None and execution["exit_code"] is None, "Running execution cannot have a final exit/end")

    selection = fields(r["selection"], "plan_frozen_at as_of universe_sealed_at cohort_frozen_at plan_sha256 universe_sha256 cohort_sha256 strategy_id", "selection")
    frozen = timestamp(selection["plan_frozen_at"], "selection.plan_frozen_at")
    asof = timestamp(selection["as_of"], "selection.as_of")
    require(asof <= frozen <= start, "Selection cutoff/plan freeze must precede execution")
    # A future acquired universe cannot be frozen before its acquisition. Keep
    # policy pre-registration distinct from sealing results and selecting a cohort.
    sealed = timestamp(selection["universe_sealed_at"], "selection.universe_sealed_at")
    require(sealed >= start and (end is None or sealed <= end), "Universe sealing must fall within execution")
    cohort = timestamp(selection["cohort_frozen_at"], "selection.cohort_frozen_at") if selection["cohort_frozen_at"] is not None else None
    require((cohort is None) == (selection["cohort_sha256"] is None), "Cohort freeze and hash must be supplied together")
    if cohort is not None:
        digest(selection["cohort_sha256"], "selection.cohort_sha256")
        require(cohort >= sealed and (end is None or cohort <= end), "Cohort must be frozen after universe sealing and within execution")
    digest(selection["plan_sha256"], "selection.plan_sha256")
    digest(selection["universe_sha256"], "selection.universe_sha256")
    text(selection["strategy_id"], "selection.strategy_id")

    u = fields(r["universe"], "raw_rows unique_candidates duplicate_rows invalid_rows", "universe")
    for name, value in u.items():
        count(value, "universe." + name)
    require(u["raw_rows"] == u["unique_candidates"] + u["duplicate_rows"] + u["invalid_rows"], "Universe row accounting does not conserve")
    stages = r["stages"]
    require(isinstance(stages, list) and len(stages) == len(STAGES), "Exactly four ordered stages required")
    previous = u["unique_candidates"]
    for expected, item in zip(STAGES, stages):
        item = fields(item, "name input promoted rejected deferred pending", "stage")
        require(item["name"] == expected, "Stage order/name mismatch")
        for key in ("input", "promoted", "rejected", "deferred", "pending"):
            count(item[key], "stage." + key)
        require(item["input"] == previous, "Stage input must equal previous promoted output")
        require(item["input"] == sum(item[key] for key in ("promoted", "rejected", "deferred", "pending")), "Stage decisions do not conserve input")
        if state == "COMPLETE":
            require(item["pending"] == 0, "Complete run cannot hide pending candidates")
        previous = item["promoted"]

    budget = fields(r["budget"], "live_authorized authorization_sha256 paid_spend_usd paid_limit_usd providers", "budget")
    authorized = boolean(budget["live_authorized"], "budget.live_authorized")
    if budget["authorization_sha256"] is not None:
        digest(budget["authorization_sha256"], "budget.authorization_sha256")
    require(not authorized or budget["authorization_sha256"] is not None, "Live authorisation needs a receipt hash")
    spend = money(budget["paid_spend_usd"], "budget.paid_spend_usd")
    limit = money(budget["paid_limit_usd"], "budget.paid_limit_usd")
    require(spend <= limit, "Paid spend exceeds declared cap")
    require(spend == 0 and limit == 0, "This v1 contract authorises no additional paid spend")
    require(isinstance(budget["providers"], list), "budget.providers must be a list")
    provider_ids = set()
    active_units = 0
    for row in budget["providers"]:
        row = fields(row, "id billing_unit used reserved limit", "provider budget")
        pid = text(row["id"], "provider.id")
        require(pid not in provider_ids, "Duplicate provider budget")
        provider_ids.add(pid)
        text(row["billing_unit"], "provider.billing_unit")
        for name in ("used", "reserved", "limit"):
            count(row[name], "provider." + name)
        require(row["used"] + row["reserved"] <= row["limit"], "Used plus reserved units exceed provider cap")
        active_units += row["used"] + row["reserved"]
    require(authorized or active_units == 0, "Unapproved live units consumed/reserved")

    measurements = fields(r["measurements"], "cached_rows refilter_external_requests refilter_p95_ms cold_live_seconds raw_history_wallets decoded_transactions supported_trades", "measurements")
    for name, value in measurements.items():
        (finite_measure if name in ("refilter_p95_ms", "cold_live_seconds") else count)(value, "measurements." + name)
    require(measurements["refilter_external_requests"] == 0, "Cached refilter must make zero external calls")
    analytics = fields(r["analytics"], "reports_populated reports_reconciled min_closed_observed_episodes_per_report control_case_included profitable_candidates", "analytics")
    for name, value in analytics.items():
        (boolean if name == "control_case_included" else count)(value, "analytics." + name)
    require(analytics["reports_reconciled"] <= analytics["reports_populated"], "More reconciled reports than populated reports")
    require(analytics["profitable_candidates"] <= analytics["reports_reconciled"], "Positive candidate count exceeds reconciled reports")
    require(analytics["reports_populated"] <= measurements["raw_history_wallets"] <= u["unique_candidates"], "History/report population exceeds its declared universe")

    f = fields(r["forward"], "state selection_frozen_before_observation started_at signal_count quote_count closed_positions monitoring_gaps valuations_complete", "forward")
    enum(f["state"], {"NOT_RUN", "RUNNING", "COMPLETE", "BLOCKED"}, "forward.state")
    boolean(f["selection_frozen_before_observation"], "forward.selection_frozen_before_observation")
    boolean(f["valuations_complete"], "forward.valuations_complete")
    for name in ("signal_count", "quote_count", "closed_positions", "monitoring_gaps"):
        count(f[name], "forward." + name)
    forward_start = timestamp(f["started_at"], "forward.started_at") if f["started_at"] is not None else None
    if forward_start is not None:
        require(cohort is not None and forward_start >= cohort, "Forward observation requires a previously frozen actual cohort")
        require(end is None or forward_start <= end, "Forward observation starts after execution ended")
    if f["state"] == "NOT_RUN":
        require(forward_start is None and f["signal_count"] == f["quote_count"] == f["closed_positions"] == 0, "NOT_RUN cannot contain observed forward activity")
    if f["state"] in {"RUNNING", "COMPLETE"}:
        require(forward_start is not None, "Started forward observation needs a start timestamp")

    role_sets = artifact_roles(r["artifacts"], evidence_root)
    require(isinstance(r["notes"], list) and all(isinstance(n, str) for n in r["notes"]), "notes must be strings")
    claims = fields(r["claims"], "mass_search_proven analytics_demonstrated forward_operational_proven strict_full_wallet_ready", "claims")
    for name, value in claims.items():
        boolean(value, "claims." + name)
    require(not claims["strict_full_wallet_ready"], "This narrower receipt cannot grant legacy full-wallet acceptance")

    live = role_sets["GENUINE_LIVE"]
    real = live | role_sets["GENUINE_REPLAY"]
    conditions = {
        "mass_search_proven": kind == "GENUINE_LIVE" and authorized and state == "COMPLETE"
            and u["unique_candidates"] >= 1000 and measurements["cold_live_seconds"] is not None
            and LIVE_ROLES <= live,
        "analytics_demonstrated": kind in {"GENUINE_LIVE", "GENUINE_REPLAY"}
            and analytics["reports_reconciled"] >= 3
            and analytics["min_closed_observed_episodes_per_report"] >= 10
            and analytics["control_case_included"] and measurements["supported_trades"] > 0
            and ANALYTICS_ROLES <= real,
        "forward_operational_proven": kind == "GENUINE_LIVE" and authorized
            and f["state"] == "COMPLETE" and forward_start is not None
            and f["selection_frozen_before_observation"] and f["signal_count"] >= 2
            and f["quote_count"] >= 2 and f["closed_positions"] >= 1 and FORWARD_ROLES <= live,
    }
    for claim, satisfied in conditions.items():
        require(not claims[claim] or satisfied, f"Unsupported positive declaration: {claim}")
    required = {"development": (), "live-search": ("mass_search_proven", "analytics_demonstrated"),
                "forward-operation": ("forward_operational_proven",)}[profile]
    missing = [name for name in required if not conditions[name]]
    return {"checker": VERSION, "profile": profile, "state": "INCOMPLETE" if missing else "CONTRACT_VALID",
            "exit_code": 2 if missing else 0, "missing_profile_conditions": missing,
            "declaration_conditions": conditions, "disclaimer": DISCLAIMER}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--profile", choices=("development", "live-search", "forward-operation"), default="development")
    parser.add_argument("--evidence-root", type=Path, help="Artifact root; defaults to receipt directory")
    args = parser.parse_args(argv)
    try:
        result = validate(load_receipt(args.receipt), args.evidence_root or args.receipt.parent, args.profile)
    except (InvalidReceipt, OSError, RecursionError, OverflowError) as exc:
        result = {"checker": VERSION, "profile": args.profile, "state": "INVALID", "exit_code": 1,
                  "error": str(exc), "disclaimer": DISCLAIMER}
    print(json.dumps(result, indent=2, allow_nan=False))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
