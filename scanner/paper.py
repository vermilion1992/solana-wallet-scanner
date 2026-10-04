"""Durable, forward-only quote research with exact simulated cash and units.

This module never obtains transactions, requests quotes or signs anything. The
observer supplies newly decoded signals and quotes requested after their due
time. Quote outputs already include provider/pool fees; only the explicitly
modeled adverse haircut and additional SOL execution cost are deducted here.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
import uuid

from .config import validate_address
from .storage import EvidenceError, now

VERSION = "quote-paper-v1"
STRATEGY = "fixed-entry-first-sale-v1"
SOL_MINT = "So11111111111111111111111111111111111111112"
LAMPORTS = 1_000_000_000
U64_MAX = 2**64 - 1
DEFAULT_SETTINGS = {
    "capital_sol": "10", "entry_sol": "0.1", "max_open_positions": 5,
    "reaction_delay_seconds": 5, "adverse_bps": 100,
    "execution_fee_sol": "0.00001", "max_price_impact_pct": "5",
    "max_events": 1000, "max_quotes": 500, "max_duration_minutes": 60,
}
COPY_RESEARCH_PRESET = {
    "name": "Forward quote copy research", "version": "forward-copy-preset-v1",
    "exclude_after_leader_exits_before_entry": 2,
    "minimum_closed_positions_for_disadvantage": 3,
    "exclude_negative_aggregate_closed_pnl": True,
    "require_available_exits_and_known_open_valuation": True,
}


def _time(value=None):
    value = now() if value is None else value
    try:
        if isinstance(value, datetime):
            result = value
        elif type(value) in (int, float):
            result = datetime.fromtimestamp(value, timezone.utc)
        elif isinstance(value, str):
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise ValueError()
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError) as exc:
        raise ValueError("Observation time must be a valid timezone-aware timestamp") from exc


def _stamp(value=None):
    return _time(value).isoformat()


def _decimal(value, *, signed=False):
    if not isinstance(value, str) or len(value) > 40 or not re.fullmatch(
            r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?" if signed else r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
        raise ValueError("Amounts must be finite decimal strings")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal amount") from exc
    return result


def _units(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,19})", value):
        raise ValueError("Raw units must be exact unsigned integer strings")
    result = int(value)
    if result > U64_MAX:
        raise ValueError("Raw units exceed u64")
    return result


def _sol_units(value):
    number = _decimal(value) * LAMPORTS
    if number != number.to_integral_value() or number > U64_MAX:
        raise ValueError("SOL amounts must have at most nine fractional digits and fit u64")
    return int(number)


def _sol(value):
    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), LAMPORTS)
    return sign + str(whole) + ("." + str(fraction).rjust(9, "0").rstrip("0") if fraction else "")


def validate_settings(changes=None):
    if changes is None:
        changes = {}
    if not isinstance(changes, dict) or set(changes) - set(DEFAULT_SETTINGS):
        raise ValueError("Unknown paper observation setting")
    result = {**DEFAULT_SETTINGS, **changes}
    for key, maximum in (("max_open_positions", 25), ("reaction_delay_seconds", 3600),
                         ("adverse_bps", 5000), ("max_events", 10000),
                         ("max_quotes", 10000), ("max_duration_minutes", 480)):
        minimum = 0 if key in ("reaction_delay_seconds", "adverse_bps") else 1
        if type(result[key]) is not int or not minimum <= result[key] <= maximum:
            raise ValueError(f"{key} must be an integer between {minimum} and {maximum}")
    for key in ("capital_sol", "entry_sol", "execution_fee_sol"):
        amount = _sol_units(result[key])
        minimum = 0 if key == "execution_fee_sol" else 1
        maximum = 10 * LAMPORTS if key == "execution_fee_sol" else 1_000_000 * LAMPORTS
        if not minimum <= amount <= maximum:
            raise ValueError(f"Invalid {key}")
        result[key] = _sol(amount)
    if _sol_units(result["entry_sol"]) + _sol_units(result["execution_fee_sol"]) > _sol_units(result["capital_sol"]):
        raise ValueError("Entry amount and execution cost must fit simulated capital")
    impact = _decimal(result["max_price_impact_pct"])
    if impact > 100:
        raise ValueError("Maximum price impact cannot exceed 100%")
    result["max_price_impact_pct"] = format(impact, "f")
    return result


def _load(store, run_id):
    run = store.get("paper_runs", run_id)
    if not isinstance(run, dict) or run.get("version") != VERSION:
        raise ValueError("Paper observation run was not found")
    return run


def _source_availability(store, run):
    required, missing = set(), []

    def need(value, label):
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
            missing.append({"source": label, "hash": None, "reason": "Required original source hash is absent or malformed"})
        else:
            required.add(value)

    need(run.get("settings_snapshot_hash"), "settings_snapshot")
    for signal in run["signals"]:
        if signal.get("eligible"):
            need(signal.get("evidence_hash"), "signal:" + signal["id"])
            if "notification_evidence_hash" in signal:
                need(signal["notification_evidence_hash"], "signal_detection:" + signal["id"])
    for request in run["quote_requests"]:
        if request.get("quote") is not None:
            need(request.get("quote_evidence_hash"), "quote_interpretation:" + request["id"])
            need(request["quote"].get("evidence_hash"), "quote_raw:" + request["id"])
    available = 0
    for digest in sorted(required):
        try:
            source = store.evidence(digest)
            if digest == run.get("settings_snapshot_hash") and (
                    not isinstance(source, dict) or source.get("settings") != run["settings"]
                    or source.get("strategy") != run["strategy"] or source.get("address") != run["address"]
                    or source.get("copy_research_preset_snapshot") != run["copy_research_preset_snapshot"]):
                raise EvidenceError("Settings disagree with original immutable snapshot")
        except (EvidenceError, ValueError, TypeError) as error:
            missing.append({"source": "archive", "hash": digest, "reason": str(error)[:300]})
        else:
            available += 1
    return {"state": "UNKNOWN" if missing else "KNOWN", "required_sources": len(required) + sum(item["hash"] is None for item in missing),
            "available_sources": available, "missing_sources": missing,
            "reason": "Current supported performance is unavailable because required original sources are absent, unreadable or conflicting." if missing else "Required original settings, signal and quote archives remain available."}


def _summary(run, store):
    opened = [position for position in run["positions"] if position["status"] != "closed"]
    closed = [position for position in run["positions"] if position["status"] == "closed"]
    marked = [position for position in opened if position.get("mark") is not None]
    open_cost = sum(int(position["cost_lamports"]) for position in opened)
    marked_value = sum(int(position["mark"]["net_value_lamports"]) for position in marked)
    all_marked = len(marked) == len(opened)
    realised = sum(int(position["realised_pnl_lamports"]) for position in closed)
    requests = run["quote_requests"]
    incomplete = bool(run["gaps"] or any(position.get("exit_unavailable") for position in opened)
                      or any(request["status"] in ("pending", "in_flight", "interrupted", "cancelled") for request in requests))
    sources = _source_availability(store, run)
    economic = _sol(int(run["cash_lamports"]) + marked_value - int(run["initial_cash_lamports"])) if all_marked else None
    has_activity = bool(run["positions"])
    return {
        "initial_capital_sol": _sol(int(run["initial_cash_lamports"])),
        "cash_sol": _sol(int(run["cash_lamports"])), "realised_pnl_sol": _sol(realised),
        "open_positions": len(opened), "closed_positions": len(closed),
        "open_cost_sol": _sol(open_cost),
        "marked_open_value_sol": _sol(marked_value) if all_marked else None,
        "known_marked_open_value_sol": _sol(marked_value),
        "economic_pnl_sol": economic,
        "supported_economic_pnl_sol": economic if sources["state"] == "KNOWN" and has_activity else None,
        "source_availability": sources,
        "supported_performance_state": "SUPPORTED_QUOTE_RESEARCH" if has_activity and sources["state"] == "KNOWN" and all_marked and not incomplete else "INCOMPLETE",
        "open_pnl_sol": _sol(marked_value - open_cost) if all_marked else None,
        "valuation_status": "known" if all_marked else "partial" if marked else "unknown",
        "valuation_times": [position["mark"]["received_at"] for position in marked],
        "signal_count": len(run["signals"]), "quote_count": run["budgets"]["quotes_used"],
        "unavailable_quotes": sum(request["status"] in ("unavailable", "interrupted") for request in requests),
        "unavailable_exits": sum(bool(position.get("exit_unavailable")) for position in opened),
        "monitoring_gaps": len(run["gaps"]), "complete_observation": has_activity and all_marked and not incomplete and sources["state"] == "KNOWN",
        "result_label": "Quote-based paper results",
        "price_basis": "Quotes obtained after detection, decoding and reaction delay; quotes are not execution guarantees.",
        "fees": {"observed": "Provider/pool fees are already included in quoted output and are not deducted again.",
                 "modeled": "Adverse output haircut plus one additional SOL execution cost per hypothetical entry or exit."},
    }


def _copyability(run):
    summary = run["summary"]
    observations, exclusions, missing = [], [], []
    preset = run["copy_research_preset_snapshot"]
    source_known = summary["source_availability"]["state"] == "KNOWN"

    def observe(key, reason, actual, evidence, action="inspect"):
        observations.append({"key": key, "state": "OBSERVED" if source_known else "UNKNOWN",
                             "historical_state": "OBSERVED", "reason": reason, "actual": actual,
                             "evidence": list(dict.fromkeys(value for value in evidence if value)),
                             "response": action})

    early = [signal for signal in run["signals"] if signal.get("reason") == "leader_exited_before_hypothetical_entry"]
    if early:
        exclude = len(early) >= preset["exclude_after_leader_exits_before_entry"]
        reason = "Observed leader sales arrived before the delayed hypothetical entry could be completed."
        observe("leader_exit_before_entry", reason,
                {"count": len(early), "exclusion_threshold": preset["exclude_after_leader_exits_before_entry"],
                 "signals": [{"signature": s["signature"], "detected_at": s["detected_at"], "decoded_at": s["decoded_at"]} for s in early]},
                [s.get("evidence_hash") for s in early], "exclude_this_strategy" if exclude else "investigate")
        if exclude:
            exclusions.append(reason)
    closed = [p for p in run["positions"] if p["status"] == "closed"]
    if closed and Decimal(summary["realised_pnl_sol"]) < 0:
        exclude = len(closed) >= preset["minimum_closed_positions_for_disadvantage"] and preset["exclude_negative_aggregate_closed_pnl"]
        reason = "The defined follower strategy has negative aggregate closed paper outcomes after its recorded costs. This does not establish leader intent."
        observe("follower_disadvantage", reason,
                {"closed_positions": len(closed), "losing_positions": sum(int(p["realised_pnl_lamports"]) < 0 for p in closed),
                 "realised_pnl_sol": summary["realised_pnl_sol"]},
                [r.get("quote_evidence_hash") for r in run["quote_requests"] if r["action"] in ("entry", "exit") and r["status"] == "available"],
                "exclude_this_strategy" if exclude else "investigate")
        if exclude:
            exclusions.append(reason)
    unavailable_exits = [r for r in run["quote_requests"] if r["action"] == "exit" and r["status"] in ("unavailable", "interrupted", "cancelled")]
    if unavailable_exits:
        reason = "The first selected leader-sale exits could not be completed; hypothetical open exposure remains."
        observe("unavailable_exits", reason,
                {"count": len(unavailable_exits), "requests": [{"id": r["id"], "reason": r.get("reason"), "due_at": r["due_at"]} for r in unavailable_exits]},
                [r.get("quote_evidence_hash") for r in unavailable_exits], "investigate")
        missing.append(reason)
    impact = [r for r in run["quote_requests"] if r.get("reason") == "quote_price_impact_above_preset"]
    if impact:
        reason = "Captured quotes exceed this run's maximum price impact assumption."
        observe("excessive_quote_price_impact", reason, {"count": len(impact), "max_price_impact_pct": run["settings"]["max_price_impact_pct"]},
                [r.get("quote_evidence_hash") for r in impact], "exclude_this_strategy")
        exclusions.append(reason)
    if summary["open_pnl_sol"] is not None and Decimal(summary["open_pnl_sol"]) < 0:
        observe("open_paper_losses", "Current dated sell quotes show hypothetical open losses after modeled execution costs.",
                {"open_pnl_sol": summary["open_pnl_sol"], "valuation_times": summary["valuation_times"]},
                [p["mark"]["quote_evidence_hash"] for p in run["positions"] if p.get("mark")], "investigate")
    if summary["valuation_status"] != "known":
        missing.append("Open hypothetical exposure lacks complete current sell-quote valuation.")
    if run["gaps"]:
        missing.append("Monitoring gaps remain; missed periods were not reconstructed as followed activity.")
    if not source_known:
        missing.append(summary["source_availability"]["reason"])
    if not any(s.get("eligible") for s in run["signals"]):
        missing.append("No eligible forward strategy signal has been observed yet.")
    elif not run["positions"]:
        missing.append("No hypothetical entry has completed; follower performance has not been measured.")
    status = "insufficient_evidence" if not source_known else "excluded_by_copy_preset" if exclusions else "insufficient_evidence" if missing else "worth_observing"
    return observations, {"status": status, "reasons": exclusions + missing,
                          "preset_snapshot": deepcopy(preset),
                          "scope": "Defined hypothetical follower strategy; this does not qualify leader profit or establish trader intent or future safety."}


def _save(store, run, at):
    run["updated_at"] = _stamp(at)
    run["summary"] = _summary(run, store)
    run["risk_observations"], run["copyability"] = _copyability(run)
    store.put("paper_runs", run["id"], run)
    return deepcopy(run)


def _cancel_pending(run, reason):
    for request in run["quote_requests"]:
        if request["status"] in ("pending", "in_flight"):
            request.update(status="cancelled", reason=reason)
            position = next((p for p in run["positions"] if p["id"] == request.get("position_id")), None)
            if position and request["action"] == "exit":
                position.update(exit_unavailable=True, exit_reason=reason, mark=None)


def _limits(run, at):
    if _time(at) >= _time(run["deadline_at"]):
        if run["status"] == "running":
            run.update(status="budget_exhausted", stop_reason="duration_budget_exhausted", stopped_at=_stamp(at))
        _cancel_pending(run, "duration_budget_exhausted")
        for position in run["positions"]:
            if position["status"] != "closed" and position.get("mark"):
                position["prior_mark"] = position["mark"]
                position.update(mark=None, valuation_reason="run_deadline_passed_current_quote_unavailable")


def create_run(store, address, settings=None, screening_id=None, at=None):
    address = validate_address(address)
    settings = validate_settings(settings)
    timestamp = _time(at)
    snapshot = {"version": VERSION, "strategy": STRATEGY, "address": address, "settings": settings,
                "started_at": timestamp.isoformat(), "screening_id": screening_id,
                "copy_research_preset_snapshot": deepcopy(COPY_RESEARCH_PRESET)}
    identifier = uuid.uuid4().hex
    with store.lock:
        run = {**snapshot, "id": identifier, "settings_snapshot_hash": store.archive(snapshot),
               "status": "running", "stop_reason": None,
               "deadline_at": (timestamp + timedelta(minutes=settings["max_duration_minutes"])).isoformat(),
               "initial_cash_lamports": str(_sol_units(settings["capital_sol"])),
               "cash_lamports": str(_sol_units(settings["capital_sol"])),
               "signals": [], "quote_requests": [], "positions": [], "gaps": [],
               "budgets": {"events_used": 0, "quotes_used": 0},
               "checkpoint": {"last_signal_id": None, "last_detected_at": None}}
        return _save(store, run, timestamp)


def get_run(store, run_id, at=None):
    with store.lock:
        run = _load(store, run_id)
        _limits(run, at)
        return _save(store, run, at)


def list_runs(store):
    return [get_run(store, run["id"]) for run in store.list("paper_runs")]


def _request(run, action, signal, at, position=None):
    identifier = uuid.uuid4().hex
    mint = signal["mint"] if signal is not None else position["mint"]
    due = _time(at) if signal is None else max(_time(signal["detected_at"]), _time(signal["decoded_at"])) + timedelta(seconds=run["settings"]["reaction_delay_seconds"])
    request = {"id": identifier, "action": action, "status": "pending", "mint": mint,
               "signal_id": signal["id"] if signal else None, "position_id": position["id"] if position else None,
               "input_mint": SOL_MINT if action == "entry" else mint,
               "output_mint": mint if action == "entry" else SOL_MINT,
               "input_amount": str(_sol_units(run["settings"]["entry_sol"])) if action == "entry" else position["raw_units"],
               "due_at": due.isoformat(), "created_at": _stamp(at)}
    run["quote_requests"].append(request)
    if signal is not None:
        signal["quote_request_id"] = identifier
    return request


def record_signal(store, run_id, signal, at=None):
    if not isinstance(signal, dict):
        raise ValueError("Signal must be an object")
    timestamp = _time(at)
    signature = signal.get("signature")
    if not isinstance(signature, str) or not 1 <= len(signature) <= 128:
        raise ValueError("Signal signature is required")
    mint = validate_address(signal.get("mint"))
    side = signal.get("side")
    if side not in ("buy", "sell") or mint == SOL_MINT:
        raise ValueError("A supported token buy or sell is required")
    if signal.get("detected_at") is None or signal.get("decoded_at") is None:
        raise ValueError("Signal detection and decoding timestamps are required")
    detected, decoded = _time(signal["detected_at"]), _time(signal["decoded_at"])
    if detected > decoded or decoded > timestamp:
        raise ValueError("Signal detection and decoding must precede observation")
    decimals = signal.get("decimals")
    if type(decimals) is not int or not 0 <= decimals <= 255:
        raise ValueError("Signal token decimals must be an integer from 0 to 255")
    if signal.get("raw_quantity") is not None and _units(signal["raw_quantity"]) == 0:
        raise ValueError("Signal quantity must be positive")
    identifier = f"{signature}:{mint}:{side}"
    with store.lock:
        run = _load(store, run_id)
        if any(item["id"] == identifier for item in run["signals"]):
            return deepcopy(run)
        _limits(run, timestamp)
        if run["status"] != "running":
            return _save(store, run, timestamp)
        if run["budgets"]["events_used"] >= run["settings"]["max_events"]:
            run.update(status="budget_exhausted", stop_reason="event_budget_exhausted", stopped_at=timestamp.isoformat())
            _cancel_pending(run, run["stop_reason"])
            return _save(store, run, timestamp)
        item = {key: deepcopy(signal[key]) for key in ("signature", "mint", "side", "decimals", "raw_quantity", "block_time", "evidence_hash", "notification_evidence_hash", "reason", "leader_cash_role_state") if key in signal}
        item.update(id=identifier, detected_at=detected.isoformat(), decoded_at=decoded.isoformat(),
                    observed_at=timestamp.isoformat(), eligible=signal.get("eligible") is True and decimals <= 18)
        if decimals > 18:
            item["reason"] = "unsupported_token_decimals_for_strategy"
        run["signals"].append(item)
        run["budgets"]["events_used"] += 1
        run["checkpoint"] = {"last_signal_id": identifier, "last_detected_at": detected.isoformat()}
        if detected < _time(run["started_at"]):
            item.update(decision="excluded", reason="signal_detected_before_run_started")
        elif not item["eligible"]:
            item.update(decision="excluded", reason=item.get("reason") or "unsupported_or_ineligible_signal")
        else:
            position = next((p for p in run["positions"] if p["mint"] == mint and p["status"] != "closed"), None)
            pending = next((r for r in run["quote_requests"] if r["mint"] == mint and r["action"] == "entry" and r["status"] in ("pending", "in_flight")), None)
            if side == "sell" and pending:
                pending.update(status="cancelled", reason="leader_exited_before_hypothetical_entry")
                item.update(decision="entry_cancelled", reason="leader_exited_before_hypothetical_entry")
            elif side == "sell" and position:
                if position.get("exit_signal_id"):
                    item.update(decision="ignored", reason="first_eligible_sale_already_selected")
                else:
                    position.update(exit_signal_id=identifier, exit_detected_at=detected.isoformat(), mark=None)
                    item["decision"] = "exit_pending"
                    _request(run, "exit", item, timestamp, position)
            elif side == "sell":
                item.update(decision="ignored", reason="no_hypothetical_position")
            elif position or pending:
                item.update(decision="ignored", reason="already_holding_or_entry_pending")
            else:
                pending_entries = [r for r in run["quote_requests"] if r["action"] == "entry" and r["status"] in ("pending", "in_flight")]
                open_count = sum(p["status"] != "closed" for p in run["positions"])
                cost = _sol_units(run["settings"]["entry_sol"]) + _sol_units(run["settings"]["execution_fee_sol"])
                if open_count + len(pending_entries) >= run["settings"]["max_open_positions"]:
                    item.update(decision="excluded", reason="maximum_open_positions")
                elif int(run["cash_lamports"]) - len(pending_entries) * cost < cost:
                    item.update(decision="excluded", reason="insufficient_simulated_cash")
                else:
                    item["decision"] = "entry_pending"
                    _request(run, "entry", item, timestamp)
        return _save(store, run, timestamp)


def due_quotes(store, run_id, at=None):
    with store.lock:
        run = _load(store, run_id)
        _limits(run, at)
        _save(store, run, at)
        if _time(at) >= _time(run["deadline_at"]):
            return []
        return deepcopy([r for r in run["quote_requests"] if r["status"] == "pending" and _time(r["due_at"]) <= _time(at)
                         and (run["status"] == "running" or r["action"] == "mark")])


def begin_quote(store, run_id, request_id, at=None):
    with store.lock:
        run = _load(store, run_id)
        _limits(run, at)
        request = next((r for r in run["quote_requests"] if r["id"] == request_id), None)
        if request is None:
            raise ValueError("Quote request was not found")
        if request["status"] != "pending":
            return None
        if (run["status"] != "running" and request["action"] != "mark") or _time(at) >= _time(run["deadline_at"]):
            _save(store, run, at)
            return None
        if _time(at) < _time(request["due_at"]):
            raise ValueError("Quote request must wait for decoding and the selected reaction delay")
        if run["budgets"]["quotes_used"] >= run["settings"]["max_quotes"]:
            run.update(status="budget_exhausted", stop_reason="quote_budget_exhausted", stopped_at=_stamp(at))
            _cancel_pending(run, run["stop_reason"])
            _save(store, run, at)
            return None
        request.update(status="in_flight", request_started_at=_stamp(at))
        run["budgets"]["quotes_used"] += 1
        _save(store, run, at)
        return deepcopy(request)


def _unavailable(run, request, reason):
    request.update(status="unavailable", reason=reason)
    signal = next((s for s in run["signals"] if s["id"] == request.get("signal_id")), None)
    if signal:
        signal.update(decision=f"{request['action']}_unavailable", reason=reason)
    position = next((p for p in run["positions"] if p["id"] == request.get("position_id")), None)
    if position:
        position["mark"] = None
        if request["action"] == "exit":
            position.update(exit_unavailable=True, exit_reason=reason)


def apply_quote(store, run_id, request_id, quote, at=None):
    if not isinstance(quote, dict):
        raise ValueError("Quote must be an object")
    timestamp = _time(at)
    with store.lock:
        run = _load(store, run_id)
        _limits(run, timestamp)
        request = next((r for r in run["quote_requests"] if r["id"] == request_id), None)
        if request is None:
            raise ValueError("Quote request was not found")
        if request["status"] not in ("in_flight", "cancelled", "interrupted") or not request.get("request_started_at"):
            if request["status"] in ("available", "unavailable", "interrupted", "cancelled"):
                return deepcopy(run)
            raise ValueError("Quote must have a durable dispatched request")
        if request["status"] in ("cancelled", "interrupted") and request.get("received_at"):
            return deepcopy(run)
        if quote.get("received_at") is None:
            raise ValueError("Quote receipt timestamp is required")
        received = _time(quote["received_at"])
        if received < _time(request["request_started_at"]) or received > timestamp:
            raise ValueError("Quote receipt must follow its dispatched request")
        # The original provider record is retained independently of interpretations.
        request["quote_evidence_hash"] = store.archive({"request": deepcopy(request), "quote": deepcopy(quote)})
        request["quote"] = deepcopy(quote)
        request["received_at"] = received.isoformat()
        if request["status"] in ("cancelled", "interrupted"):
            return _save(store, run, timestamp)
        if quote.get("status") != "available":
            _unavailable(run, request, str(quote.get("reason") or "quote_unavailable")[:500])
        else:
            try:
                if quote.get("request_started_at") is not None and not (
                        _time(request["request_started_at"]) <= _time(quote["request_started_at"]) <= received):
                    raise ValueError("quote_was_not_requested_after_delay")
                if quote.get("input_mint") != request["input_mint"] or quote.get("output_mint") != request["output_mint"]:
                    raise ValueError("quote_mint_mismatch")
                if _units(quote.get("in_amount")) != int(request["input_amount"]):
                    raise ValueError("quote_input_amount_mismatch")
                output = _units(quote.get("out_amount"))
                if not output:
                    raise ValueError("quote_output_is_zero")
                impact = abs(_decimal(quote.get("price_impact_pct"), signed=True))
                if impact > _decimal(run["settings"]["max_price_impact_pct"]):
                    raise ValueError("quote_price_impact_above_preset")
            except ValueError as exc:
                _unavailable(run, request, str(exc))
            else:
                adjusted = output * (10000 - run["settings"]["adverse_bps"]) // 10000
                haircut = output - adjusted
                fee = _sol_units(run["settings"]["execution_fee_sol"])
                request.update(status="available", quoted_output_units=str(output),
                               modeled_adverse_units=str(haircut), adjusted_output_units=str(adjusted),
                               modeled_execution_fee_lamports=str(fee), observed_price_impact_pct=str(impact))
                signal = next((s for s in run["signals"] if s["id"] == request.get("signal_id")), None)
                position = next((p for p in run["positions"] if p["id"] == request.get("position_id")), None)
                if request["action"] == "entry":
                    if not adjusted:
                        _unavailable(run, request, "adverse_adjusted_output_is_zero")
                        return _save(store, run, timestamp)
                    cost = int(request["input_amount"]) + fee
                    run["cash_lamports"] = str(int(run["cash_lamports"]) - cost)
                    position = {"id": uuid.uuid4().hex, "mint": request["mint"], "decimals": signal["decimals"],
                                "status": "open", "raw_units": str(adjusted), "cost_lamports": str(cost),
                                "entry_signal_id": signal["id"], "entry_request_id": request["id"],
                                "opened_at": received.isoformat(), "mark": None, "exit_unavailable": False}
                    run["positions"].append(position)
                    request["position_id"] = position["id"]
                    signal["decision"] = "hypothetical_entry"
                elif request["action"] == "exit":
                    net = adjusted - fee
                    # A model cannot manufacture fee capital when even sale proceeds
                    # plus remaining cash cannot pay the modeled execution cost.
                    if int(run["cash_lamports"]) + net < 0:
                        _unavailable(run, request, "insufficient_simulated_cash_for_exit_cost")
                    else:
                        run["cash_lamports"] = str(int(run["cash_lamports"]) + net)
                        position.update(status="closed", closed_at=received.isoformat(), raw_units="0",
                                        exit_request_id=request["id"], net_exit_lamports=str(net),
                                        realised_pnl_lamports=str(net - int(position["cost_lamports"])), mark=None)
                        signal["decision"] = "hypothetical_exit"
                else:
                    position["mark"] = {"request_id": request["id"], "received_at": received.isoformat(),
                                        "net_value_lamports": str(adjusted - fee), "quote_evidence_hash": request["quote_evidence_hash"]}
        _limits(run, timestamp)
        return _save(store, run, timestamp)


def request_marks(store, run_id, at=None):
    with store.lock:
        run = _load(store, run_id)
        _limits(run, at)
        if _time(at) >= _time(run["deadline_at"]):
            return _save(store, run, at)
        if run["budgets"]["quotes_used"] >= run["settings"]["max_quotes"]:
            for position in run["positions"]:
                if position["status"] != "closed":
                    if position.get("mark"):
                        position["prior_mark"] = position["mark"]
                    position.update(mark=None, valuation_reason="quote_budget_exhausted")
            run.update(status="budget_exhausted", stop_reason="quote_budget_exhausted", stopped_at=_stamp(at))
            _cancel_pending(run, run["stop_reason"])
            return _save(store, run, at)
        for position in run["positions"]:
            if position["status"] == "closed":
                continue
            if any(r.get("position_id") == position["id"] and r["status"] in ("pending", "in_flight") for r in run["quote_requests"]):
                continue
            position["mark"] = None
            _request(run, "mark", None, at, position)
        return _save(store, run, at)


def record_gap(store, run_id, reason, start_at=None, end_at=None, *, started_at=None, ended_at=None):
    start, end = _time(started_at if started_at is not None else start_at), _time(ended_at if ended_at is not None else end_at)
    if end < start:
        raise ValueError("Monitoring gap end precedes start")
    with store.lock:
        run = _load(store, run_id)
        run["gaps"].append({"id": uuid.uuid4().hex, "reason": str(reason)[:500],
                            "start_at": start.isoformat(), "end_at": end.isoformat(), "backfilled": False})
        return _save(store, run, end)


def stop_run(store, run_id, reason="user_stopped", at=None):
    with store.lock:
        run = _load(store, run_id)
        run.update(status="stopped", stop_reason=str(reason)[:500], stopped_at=_stamp(at))
        _cancel_pending(run, run["stop_reason"])
        return _save(store, run, at)


def pause_run(store, run_id, reason="observer_interrupted", at=None):
    with store.lock:
        run = _load(store, run_id)
        run.update(status="paused", stop_reason=str(reason)[:500], stopped_at=_stamp(at))
        return _save(store, run, at)


def interrupt_requests(store, run_id, reason="monitoring_interrupted_no_hindsight_replay", at=None, include_marks=False):
    """Abandon signal quotes across a monitoring gap without inventing fills."""
    with store.lock:
        run = _load(store, run_id)
        for request in run["quote_requests"]:
            if request["status"] in ("pending", "in_flight") and (include_marks or request["action"] != "mark"):
                _unavailable(run, request, str(reason)[:500])
                request["status"] = "interrupted"
        return _save(store, run, at)


def resume_run(store, run_id, at=None):
    with store.lock:
        run = _load(store, run_id)
        if run["status"] == "running":
            return deepcopy(run)
        if run["status"] == "budget_exhausted":
            raise ValueError("An exhausted immutable run cannot be extended; start a new run")
        timestamp = _time(at)
        gap_start = _time(run.get("stopped_at", run["updated_at"]))
        if timestamp < gap_start:
            raise ValueError("Resume time precedes the run pause")
        run["gaps"].append({"id": uuid.uuid4().hex, "reason": "observation_paused_or_restarted",
                            "start_at": gap_start.isoformat(), "end_at": timestamp.isoformat(), "backfilled": False})
        for request in run["quote_requests"]:
            if request["status"] in ("pending", "in_flight"):
                _unavailable(run, request, "request_interrupted_no_hindsight_replay")
                request["status"] = "interrupted"
        run.update(status="running", stop_reason=None, resumed_at=timestamp.isoformat())
        _limits(run, timestamp)
        return _save(store, run, timestamp)


def export_run(store, run_id):
    run = get_run(store, run_id)
    return {"export_version": VERSION, "exported_at": now(), "run": run,
            "scope": "Forward quote-only paper observation; no signed transaction, actual fill or verified leader profit.",
            "settings_evidence": store.evidence(run["settings_snapshot_hash"])}
