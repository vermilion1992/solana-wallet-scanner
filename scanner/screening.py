"""Frozen, sampled screening decisions independent of strict financial acceptance.

This module makes no provider calls and changes no saved report. The API must
save its result as a new assessment and recheck original identity sources before
supplying an explicit identity receipt. Conditional lot results are never wallet
profit, and a screening exclusion describes the selected preset, not intent.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import re

from .accounting import canonical, decimal, raw_quantity, utc
from .copy_review import qualify_report, review_copy_behavior
from .native_cash_observations import VERSION as CASH_VERSION
from .research import VERSION as RESEARCH_VERSION
from .wallet_identity import VERSION as IDENTITY_VERSION

VERSION = "wallet-screening-v1"
DEFAULT_PRESET = {
    "name": "Sampled wallet screening", "min_supported_swaps": 2,
    "min_matched_sales": 1, "max_rapid_sale_pct": "50",
    "require_positive_conditional_profit": False,
    "exclude_active_mint_authority": True, "exclude_active_freeze_authority": True,
    "exclude_restrictive_extensions": True,
    "continuation_max_transactions": 20, "continuation_max_credits": 100,
    "continuation_max_accounts": 10,
}
HASH = re.compile(r"^[a-f0-9]{64}$")
CONTROL_SETTINGS = {"mint_authority": "exclude_active_mint_authority",
                    "freeze_authority": "exclude_active_freeze_authority",
                    "token_extensions": "exclude_restrictive_extensions"}


def _hashes(values):
    return list(dict.fromkeys(value for value in values
                             if isinstance(value, str) and HASH.fullmatch(value))) if isinstance(values, list) else []


def _number(value, *, signed=False):
    try:
        return decimal(value, signed=signed, max_length=512)
    except (ValueError, TypeError, AttributeError):
        return None


def validate_screening_preset(value=None):
    """Validate a separate research preset; never edit the strict PDF preset."""
    if value is None:
        return deepcopy(DEFAULT_PRESET)
    if not isinstance(value, dict) or set(value) - set(DEFAULT_PRESET):
        raise ValueError("Unknown sampled screening setting")
    settings = {**DEFAULT_PRESET, **deepcopy(value)}
    if not isinstance(settings["name"], str) or not 1 <= len(settings["name"]) <= 100:
        raise ValueError("Screening preset name must contain 1–100 characters")
    limits = {"min_supported_swaps": (1, 10000), "min_matched_sales": (0, 10000),
              "continuation_max_transactions": (1, 1000), "continuation_max_credits": (1, 20000),
              "continuation_max_accounts": (1, 100)}
    for key, (lower, upper) in limits.items():
        if type(settings[key]) is not int or not lower <= settings[key] <= upper:
            raise ValueError(f"{key} must be an integer between {lower} and {upper}")
    for key in ("require_positive_conditional_profit", *CONTROL_SETTINGS.values()):
        if type(settings[key]) is not bool:
            raise ValueError(f"{key} must be boolean")
    rapid = _number(settings["max_rapid_sale_pct"])
    if rapid is None or rapid > 100:
        raise ValueError("max_rapid_sale_pct must be between 0 and 100")
    settings["max_rapid_sale_pct"] = canonical(rapid)
    return settings


def build_screening(report, preset=None, identity=None):
    """Describe one saved sample; a PASS identity is a raw-rechecked API receipt.

    Explicit identity receipts have ``state``, ``reason``, ``evidence`` and an
    optional ``address``. Their evidence is retained separately from report
    sources because a saved cohort identity can precede this collection. The API
    accepts no client-supplied identity decision. Without a receipt, only the
    current versioned raw-derived report wallet-identity component is admitted.
    """
    if not isinstance(report, dict):
        raise ValueError("Screening requires a saved report object")
    settings = validate_screening_preset(preset)
    coverage = report.get("coverage") if isinstance(report.get("coverage"), dict) else {}
    research = report.get("research") if isinstance(report.get("research"), dict) else {}
    current = research.get("version") == RESEARCH_VERSION
    wallet = coverage.get("wallet_evidence") if isinstance(coverage.get("wallet_evidence"), dict) else {}
    primary = set(_hashes([item.get("hash") for item in report.get("evidence", [])
                          if isinstance(item, dict)])) if isinstance(report.get("evidence"), list) else set()

    def linked(values):
        hashes = _hashes(values)
        return bool(hashes and set(hashes) <= primary)

    if identity is None:
        saved = wallet.get("wallet_identity")
        identity = deepcopy(saved) if isinstance(saved, dict) and saved.get("version") == IDENTITY_VERSION else {}
        if not linked(identity.get("evidence")):
            identity["state"] = "UNKNOWN"
    elif not isinstance(identity, dict):
        raise ValueError("Identity must be a raw-rechecked receipt object")
    else:
        identity = deepcopy(identity)
    identity_hashes = _hashes(identity.get("evidence"))
    identity_state = identity.get("state") if identity.get("state") in ("PASS", "FAIL") and identity_hashes else "UNKNOWN"
    if identity.get("address", report.get("address")) != report.get("address"):
        identity_state = "UNKNOWN"
    identity_receipt = {"state": identity_state, "evidence": identity_hashes,
                        "reason": identity.get("reason") or "A native signer and current system-account identity need evidence checking."}
    reasons = [{"key": "identity", **identity_receipt, "actual": report.get("address")}]

    events = report.get("events") if isinstance(report.get("events"), list) else []
    window = report.get("window") if isinstance(report.get("window"), dict) else {}
    try:
        begin, end = utc(window.get("start")), utc(window.get("end"))
        window_valid = begin < end
    except (ValueError, TypeError, OverflowError, AttributeError):
        begin = end = None
        window_valid = False
    accepted, seen = [], set()
    for event in events:
        if not isinstance(event, dict) or event.get("kind") not in ("buy", "sell") or not linked(event.get("evidence")):
            continue
        try:
            when = utc(event.get("timestamp"))
            quantity = raw_quantity(event.get("quantity_raw"))
        except (ValueError, TypeError, OverflowError, AttributeError):
            continue
        key = (event.get("signature"), event.get("path"), event.get("kind"), event.get("mint"))
        if (not window_valid or not begin <= when < end or quantity <= 0 or
                not isinstance(event.get("signature"), str) or not event["signature"] or key in seen):
            continue
        seen.add(key)
        accepted.append(event)
    event_hashes = list(dict.fromkeys(digest for event in accepted for digest in _hashes(event.get("evidence"))))
    reasons.append({"key": "supported_activity", "state": "PASS" if len(accepted) >= settings["min_supported_swaps"] else "UNKNOWN",
                    "actual": len(accepted), "expected": settings["min_supported_swaps"], "evidence": event_hashes,
                    "reason": "Supported buys and sales meet the sample minimum in this saved window." if len(accepted) >= settings["min_supported_swaps"] else
                              f"Observed {len(accepted)} supported swaps; this screening preset requires at least {settings['min_supported_swaps']}."})
    episodes = [deepcopy(row) for row in research.get("episodes", []) if isinstance(row, dict)] if current and isinstance(research.get("episodes"), list) else []
    for row in episodes:
        if not linked(row.get("evidence")):
            # Keep the population dependency. Dropping an unsupported slow
            # episode would manufacture a higher rapid-exit percentage, and
            # dropping an unsupported open episode would hide exposure.
            row.update(timing_state="UNKNOWN", quantity_state="UNKNOWN", quantity_raw=None,
                       remaining_basis_status="unknown", remaining_basis_sol=None, evidence=[],
                       hold_hours=None, first_sale_hours=None, sold_90_pct_hours=None)
    sale_rows = [row for row in research.get("sales_detail", []) if isinstance(row, dict) and linked(row.get("evidence"))] if current and isinstance(research.get("sales_detail"), list) else []
    matched = [row for row in sale_rows if row.get("monetary_state") == "PASS" and _number(row.get("conditional_profit_sol"), signed=True) is not None]
    # Sale details, rather than a caller-supplied count, determine this gate.
    matched_count = len({(row.get("signature"), row.get("timestamp"), row.get("mint"), row.get("quantity_raw")) for row in matched})
    matched_hashes = list(dict.fromkeys(digest for row in matched for digest in _hashes(row.get("evidence"))))
    reasons.append({"key": "matched_lots", "state": "PASS" if current and matched_count >= settings["min_matched_sales"] else "UNKNOWN",
                    "actual": matched_count if current else None, "expected": settings["min_matched_sales"], "evidence": matched_hashes,
                    "reason": "Evidenced conditional sale results use fetched FIFO purchase lots; earlier inventory remains a dependency." if current and matched_count >= settings["min_matched_sales"] else
                              f"Observed {matched_count} evidenced matched sales; this screening preset requires at least {settings['min_matched_sales']}." if current else
                              "Rebuild the saved report to obtain current sampled research observations."})
    profit = _number(research.get("conditional_observed_lot_profit_sol"), signed=True) if current and linked(research.get("evidence")) else None
    if settings["require_positive_conditional_profit"]:
        reasons.append({"key": "conditional_profit", "state": "UNKNOWN" if profit is None else "PASS" if profit > 0 else "FAIL",
                        "actual": canonical(profit), "evidence": _hashes(research.get("evidence")) if profit is not None else [],
                        "reason": "Preset requires a positive conditional matched-lot result; this remains separate from strict wallet profit."})

    # Reuse existing behavior derivation after removing unlinked sources from
    # the private view. An unsupported hash cannot create an exclusion label.
    safe_report = deepcopy(report)
    safe_report["events"] = [row for row in events if isinstance(row, dict) and linked(row.get("evidence"))]
    safe_report["positions"] = [deepcopy(row) for row in report.get("positions", []) if isinstance(row, dict)] if isinstance(report.get("positions"), list) else []
    for row in safe_report["positions"]:
        if not linked(row.get("evidence")):
            row.update(timing_state="UNKNOWN", evidence=[], hold_hours=None, first_sale_hours=None, sold_90_pct_hours=None)
    safe_report["research"] = {**research, "episodes": episodes}
    safe_report["token_risk"] = []
    observations = []
    for token in report.get("token_risk", []) if isinstance(report.get("token_risk"), list) else []:
        if not isinstance(token, dict):
            continue
        gates = token.get("gates") if isinstance(token.get("gates"), dict) else {}
        copied = deepcopy(token)
        copied["findings"] = [row for row in token.get("findings", []) if isinstance(row, dict) and linked(row.get("evidence"))] if isinstance(token.get("findings"), list) else []
        copied["gates"] = {}
        for key, gate in gates.items():
            gate = deepcopy(gate) if isinstance(gate, dict) else {}
            supported = gate.get("state") in ("PASS", "FAIL", "OBSERVED", "FLAGGED") and linked(gate.get("evidence"))
            state = gate.get("state") if supported else "UNKNOWN"
            copied["gates"][key] = {**gate, "state": state}
            if key in CONTROL_SETTINGS or key in ("current_liquidity", "liquidity_control", "holder_concentration", "historical_sellability"):
                observation = {"key": key, "state": state, "mint": token.get("mint"), "actual": deepcopy(gate.get("actual")) if supported else None,
                               "reason": gate.get("detail") if supported else "Linked primary evidence is missing or this observation is unresolved.",
                               "evidence": _hashes(gate.get("evidence")) if supported else [],
                               "scope": "Current token observation", "observed_at": token.get("observed_at"), "context_slot": token.get("context_slot")}
                observations.append(observation)
                if key in CONTROL_SETTINGS and settings[CONTROL_SETTINGS[key]] and state == "FAIL":
                    reasons.append({**observation, "reason": f"Excluded by this preset: {observation['reason']}"})
        safe_report["token_risk"].append(copied)
        observations.extend({"key": key, "state": "UNKNOWN", "mint": token.get("mint"),
                             "reason": "This token control has not been observed.", "actual": None, "evidence": []}
                            for key in CONTROL_SETTINGS if key not in gates)
    review = review_copy_behavior(safe_report)
    rapid = review["checks"]["rapid_first_sales"]
    rapid_pct = _number((rapid.get("actual") or {}).get("observed_pct")) if rapid.get("state") == "OBSERVED" and linked(rapid.get("evidence")) else None
    if rapid_pct is not None:
        reasons.append({"key": "rapid_first_sales", "state": "FAIL" if rapid_pct > Decimal(settings["max_rapid_sale_pct"]) else "PASS",
                        "actual": canonical(rapid_pct), "expected": settings["max_rapid_sale_pct"], "evidence": rapid["evidence"],
                        "reason": "Observed first-sale timing exceeds this sampled preset." if rapid_pct > Decimal(settings["max_rapid_sale_pct"]) else "Observed first-sale timing is within this sampled preset."})
    observations.extend({"key": key, "state": check["state"], "reason": check.get("detail"), "actual": deepcopy(check.get("actual")),
                         "evidence": check.get("evidence", []), "conditional": check.get("conditional", True)}
                        for key, check in review["checks"].items() if key in ("long_tail_holds", "rapid_first_sales", "creator_links", "follower_exploitation", "liquidity_withdrawal"))
    if not any(row["key"] in CONTROL_SETTINGS for row in observations):
        observations.extend({"key": key, "state": "UNKNOWN", "reason": "Current token controls have not been observed.", "actual": None, "evidence": []} for key in CONTROL_SETTINGS)
    observations.extend(_transfer_links(wallet, report.get("address"), linked))
    observations.append({"key": "forward_copy_outcomes", "state": "UNKNOWN", "reason": "Start a separate forward quote-based paper observation to measure follower outcomes.", "actual": None, "evidence": []})

    exposure = []
    for row in episodes:
        try:
            quantity = raw_quantity(row.get("quantity_raw"))
        except (ValueError, TypeError, AttributeError):
            quantity = None
        if row.get("status") != "closed" and (quantity is None or quantity > 0):
            exposure.append({"episode_id": row.get("id"), "mint": row.get("mint"), "status": row.get("status"),
                             "quantity_raw": str(quantity) if quantity is not None else None,
                             "remaining_basis_sol": row.get("remaining_basis_sol") if row.get("remaining_basis_status") == "known" else None,
                             "quantity_state": row.get("quantity_state", "UNKNOWN"), "evidence": _hashes(row.get("evidence")),
                             "market_value_sol": None, "valuation_state": "UNKNOWN", "conditional": True})
    collection = deepcopy(report.get("collection")) if isinstance(report.get("collection"), dict) else {}
    terminal = coverage.get("terminal_evidence") if isinstance(coverage.get("terminal_evidence"), list) else []
    stop = collection.get("stop_reason") or coverage.get("collection_stop_reason") or coverage.get("stop_reason") or coverage.get("scope_limit_reason")
    if not stop:
        stop = "Included account paging finished; complete historical ownership remains unproved." if coverage.get("included_account_paging_finished") is True else "Collection stop reason was not retained in this saved report."
    collection.update(stop_reason=stop, scope=coverage.get("ownership_scope") or coverage.get("scope") or research.get("scope"),
                      transactions=coverage.get("transactions"), pages=coverage.get("pages"), credits=coverage.get("credits"),
                      requested_range=deepcopy(coverage.get("requested_range", window)), fetched_range=deepcopy(coverage.get("fetched_range")),
                      terminal_evidence=deepcopy(terminal), gaps=deepcopy(coverage.get("missing_records", [])),
                      historical_ownership_verified=coverage.get("historical_ownership_verified") is True)
    failed = [row for row in reasons if row["state"] == "FAIL"]
    missing = [row for row in reasons if row["state"] == "UNKNOWN"]
    if report.get("source") != "live" or report.get("preview") is True:
        missing.append({"key": "live_source", "state": "UNKNOWN", "reason": "Synthetic and preview reports cannot establish a live wallet screening result.", "actual": report.get("source"), "evidence": []})
        reasons.append(missing[-1])
    result = "excluded_by_preset" if failed else "insufficient_evidence" if missing else "worth_observing"
    labels = {"excluded_by_preset": "Excluded by this preset", "insufficient_evidence": "Insufficient evidence", "worth_observing": "Worth observing"}
    reason = failed[0]["reason"] if failed else missing[0]["reason"] if missing else "The evidenced sample meets this screening preset. A forward paper observation can test follower outcomes."
    budget = {"max_transactions": settings["continuation_max_transactions"], "max_credits": settings["continuation_max_credits"], "max_accounts": settings["continuation_max_accounts"]}
    return {"version": VERSION, "report_id": report.get("id"), "address": report.get("address"), "source": report.get("source"),
            "result": result, "label": labels[result], "reason": reason, "reasons": reasons,
            "preset_snapshot": settings, "identity": identity_receipt, "strict_qualification": qualify_report(report),
            "trading_evidence": {"supported_swaps": len(accepted), "buy_signals": sum(row["kind"] == "buy" for row in accepted),
                "sell_signals": sum(row["kind"] == "sell" for row in accepted), "matched_sales": matched_count if current else None,
                "unmatched_sales": research.get("observed_unmatched_sales") if current else None,
                "unresolved_basis_sales": research.get("unresolved_basis_sales") if current else None,
                "conditional_matched_lot_profit_sol": canonical(profit), "open_exposure": exposure,
                "early_exits": {key: deepcopy(review["checks"][key]) for key in ("long_tail_holds", "rapid_first_sales")},
                "scope": research.get("scope") if current else "Current supported research needs an immutable rebuild",
                "window": deepcopy(window), "conditional": True, "wallet_profit_verified": False, "evidence": event_hashes},
            "risk_observations": observations, "collection": collection,
            "continuation": {"recommended": result == "insufficient_evidence" and identity_state != "FAIL", "action": "continue_investigation",
                "reason": "Recheck identity first." if identity_state != "PASS" else "Resume the saved checkpoint within an explicit additional budget; another sample may still leave historical dependencies unresolved.",
                "budget": budget, "checkpoint_required": True},
            "notes": ["Worth observing is a sampled research decision, not verified profitability or a promise of safe copying.",
                      "Conditional matched-lot profit excludes unmatched sales; open exposure and missing valuations remain visible.",
                      "Risk observations describe evidence and token capabilities without alleging intent or common control.",
                      "Strict financial qualification and full historical acceptance remain separate."]}


def _transfer_links(wallet, address, linked):
    """Show bounded direct transfer facts without inferring capital or control."""
    cash = wallet.get("native_cash_observations") if isinstance(wallet, dict) else None
    if not isinstance(cash, dict) or cash.get("version") != CASH_VERSION or not isinstance(cash.get("transactions"), dict):
        return [{"key": "direct_transfer_links", "state": "UNKNOWN", "reason": "Current raw-derived direct transfer observations are unavailable.", "actual": None, "evidence": []}]
    observations = []
    seen = set()
    for signature, transaction in cash["transactions"].items():
        if not isinstance(transaction, dict) or transaction.get("failed") is not False:
            continue
        for movement in transaction.get("movements", []) if isinstance(transaction.get("movements"), list) else []:
            if not isinstance(movement, dict):
                continue
            check = movement.get("check") if isinstance(movement.get("check"), dict) else {}
            if check.get("state") != "PASS" or not linked(check.get("evidence")) or movement.get("direction") == "self":
                continue
            key = (signature, movement.get("source"), movement.get("destination"), movement.get("lamports"), tuple(movement.get("raw_paths", [])))
            if key in seen or address not in (movement.get("source"), movement.get("destination")):
                continue
            seen.add(key)
            observations.append({"key": "direct_native_transfer", "state": "OBSERVED", "reason": "Executed direct SOL transfer link; economic purpose and common control are not established.",
                                 "actual": {"signature": signature, "source": movement.get("source"), "destination": movement.get("destination"), "lamports": movement.get("lamports")},
                                 "evidence": _hashes(check.get("evidence")), "paths": deepcopy(movement.get("raw_paths", [])), "relationship": "direct_transfer_only"})
    if not observations:
        observations.append({"key": "direct_transfer_links", "state": "UNKNOWN", "reason": "No supported direct native transfer link in this selected scope; unseen relationships remain unknown.", "actual": None, "evidence": []})
    return observations
