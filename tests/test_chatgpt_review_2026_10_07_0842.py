"""Closures for the 2026-10-07 08:42 re-review of PR #6 tip 04a676f.

Offline only. Every constructed wallet is SYNTHETIC. No provider calls.
"""
from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from scanner.mass_search.history_ingest import (
    bind_progress_to_replay,
    draft_execution_artifact_hash,
    empty_next_capture_state,
    evaluate_next_capture_dispatch,
    load_next_capture_draft,
    load_next_capture_state,
    named_dependency_progress,
    persist_next_capture_state,
    record_next_capture_replay,
    run_next_capture_offline,
    validate_fresh_approval_bind,
    validate_operator_quota_record,
)
from scanner.mass_search.qualification_gates import (
    amounts_agree,
    bindable_independent_audit,
    certificate_comparison_proof,
    reconcile_saved_profile,
)
from scanner.mass_search.research_profile import (
    build_research_profile,
    default_filters,
    independently_audited,
    qualification_category,
)
from scanner.mass_search.workflow import compare_reports, ranked_workflow_view
from scanner.storage import Store
from tests.test_chatgpt_review_2026_10_07_rereview import _eligible_report

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "frontend/scripts/assert-rereview-0842.mts"
DRAFT = ROOT / "config/live_authorization.ranked100-depth-biased-next-capture-draft.json"
NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def _quota_record(remaining=8, draft=None, **overrides):
    record = {
        "kind": "operator_quota_record_v1",
        "ceiling": 20,
        "reserved_unallocated": 12,
        "usable_ceiling": 8,
        "remaining": remaining,
        "baseline": remaining,
        "overages_enabled": False,
        "operator": "mitch-offline-synthetic",
        "confirmed_at": "2026-10-07T00:00:00Z",
    }
    if draft is not None:
        record["authorization_id"] = draft["authorization_id"]
        record["execution_artifact_hash"] = draft_execution_artifact_hash(draft)
    record.update(overrides)
    return record


def _synthetic_grant(draft, **overrides):
    quota = overrides.pop("current_remaining_quota_confirmation", _quota_record(draft=draft))
    if isinstance(quota, dict) and "authorization_id" not in quota:
        quota = {**quota, "authorization_id": draft["authorization_id"], "execution_artifact_hash": draft_execution_artifact_hash(draft)}
    grant = {
        "enabled": False,
        "synthetic_offline_authorization": True,
        "authorization_id": draft["authorization_id"],
        "execution_artifact_hash_of_this_draft": draft_execution_artifact_hash(draft),
        "current_remaining_quota_confirmation": quota,
        "overages_enabled": False,
        "approval_timestamp": "2026-10-07T00:00:00Z",
        "expiry": "2026-10-08T00:00:00Z",
    }
    grant.update(overrides)
    return grant


def _positive_saved(report, built):
    return {
        **built,
        "completed_episode_net": "12",
        "completed_episode_net_vector": {"SOL": "12"},
        "completed_known_cost_positions": 4,
        "evidence_class": {
            "position": {"class": 1, "label": "positive matched position evidence"},
            "account": {"class": 5},
        },
        "qualification_category": {
            "category": "positive_matched_position_evidence",
            "evidence_class": 1,
        },
        "qualification_level": {"level": "provisional_research_lead", "label": "provisional research lead"},
        "criteria_met": True,
        "evaluated_thresholds": {"min_completed_known_cost": {"applied": True}},
        "thresholds": {"min_completed_known_cost": "3", "min_scoped_pnl_sol": "0"},
        "funnel": {
            "A": {"state": "YES"},
            "B": {"state": "ESTABLISHED", "scoped_pnl": "12", "scoped_pnl_unit": "SOL", "completed_known_cost_positions": 4},
            "C": {"state": "MET", "criteria_met": True},
        },
        "independent_audit": report["independent_audit"],
        "audit_fingerprint": built["audit_fingerprint"],
    }


def _persist(store, report, profile, report_id):
    payload = {
        **report,
        "id": report_id,
        "source": "mass-search",
        "visible_report": True,
        "research_profile": profile,
        "funnel": profile.get("funnel") or report.get("funnel"),
        "window": report.get("window") or {"start": "2026-09-05T13:29:27Z", "end": "2026-10-05T13:29:27Z"},
    }
    store.put("reports", report_id, payload)
    return payload


def _universe_row(address):
    return {
        "address": address,
        "provider_rank": 101,
        "trade_count": 50,
        "provider_score": "1",
        "shortlisted": False,
        "capture_available": True,
        "label": "SYNTHETIC — ranked injection, not a genuine research wallet",
        "row_kind": "synthetic_fixture",
        "corpus_kind": "SYNTHETIC",
    }


def _mutate_bridges(report, mutator):
    mutated = deepcopy(report)
    audit = mutated["independent_audit"]
    for index, bridge in enumerate(audit["component_bridges"]):
        audit["component_bridges"][index] = mutator(deepcopy(bridge), index)
    audit["episodes"] = [
        {**episode, "component_bridge": audit["component_bridges"][index]}
        for index, episode in enumerate(audit["episodes"])
    ]
    return mutated


def test_bridge_amounts_must_match_bound_ledger_not_just_auditor():
    report = _eligible_report()
    ledger = report["completed_episode_ledger"]
    assert certificate_comparison_proof(report["independent_audit"], ledger) is True

    both_sides = _mutate_bridges(report, lambda bridge, _index: {
        **bridge,
        "components": {
            **bridge["components"],
            "acquisition": {**bridge["components"]["acquisition"], "app": "999", "auditor": "999"},
            "proceeds": {**bridge["components"]["proceeds"], "app": "1002", "auditor": "1002"},
            "costs": {**bridge["components"]["costs"], "app": "0", "auditor": "0"},
            "net": {**bridge["components"]["net"], "app": "3", "auditor": "3"},
        },
    })
    assert certificate_comparison_proof(both_sides["independent_audit"], ledger) is False
    profile = build_research_profile(deepcopy(both_sides), filters=default_filters())
    assert independently_audited(both_sides, profile) is False
    assert bindable_independent_audit(both_sides["independent_audit"], profile["audit_fingerprint"], ledger) is None

    usdc = _mutate_bridges(report, lambda bridge, _index: {**bridge, "unit": "USDC"})
    assert certificate_comparison_proof(usdc["independent_audit"], ledger) is False

    proceeds_only = _mutate_bridges(report, lambda bridge, _index: {
        **bridge,
        "components": {
            **bridge["components"],
            "proceeds": {**bridge["components"]["proceeds"], "app": "99", "auditor": "99"},
        },
    })
    assert certificate_comparison_proof(proceeds_only["independent_audit"], ledger) is False

    costs_only = _mutate_bridges(report, lambda bridge, _index: {
        **bridge,
        "components": {
            **bridge["components"],
            "costs": {**bridge["components"]["costs"], "app": "9", "auditor": "9"},
        },
    })
    assert certificate_comparison_proof(costs_only["independent_audit"], ledger) is False

    usdc_ledger = [{**row, "unit": "USDC", "acquisition": "1", "proceeds": "4", "costs": "0", "net": "3"} for row in ledger]
    usdc_wrong = _mutate_bridges(report, lambda bridge, _index: {
        **bridge,
        "unit": "USDC",
        "components": {
            **bridge["components"],
            "acquisition": {**bridge["components"]["acquisition"], "app": "2", "auditor": "2"},
            "proceeds": {**bridge["components"]["proceeds"], "app": "5", "auditor": "5"},
            "costs": {**bridge["components"]["costs"], "app": "0", "auditor": "0"},
            "net": {**bridge["components"]["net"], "app": "3", "auditor": "3"},
        },
    })
    assert certificate_comparison_proof(usdc_wrong["independent_audit"], usdc_ledger) is False


def test_canonicalization_includes_auditor_identity_in_one_representation():
    report = _eligible_report()
    ledger = report["completed_episode_ledger"]
    mutated = deepcopy(report)
    episode_bridge = deepcopy(mutated["independent_audit"]["episodes"][0]["component_bridge"])
    membership = dict(episode_bridge["membership"])
    auditor = dict(membership["auditor"])
    auditor["close_signature"] = "altered-only-in-episode-representation"
    membership["auditor"] = auditor
    episode_bridge["membership"] = membership
    mutated["independent_audit"]["episodes"][0]["component_bridge"] = episode_bridge
    assert certificate_comparison_proof(mutated["independent_audit"], ledger) is False

    mint_only = deepcopy(report)
    episode_bridge = deepcopy(mint_only["independent_audit"]["episodes"][0]["component_bridge"])
    membership = dict(episode_bridge["membership"])
    auditor = dict(membership["auditor"])
    auditor["mint"] = "AlteredMintOnly0842AAAAAAAAAAAAAAAAAAAAA"
    membership["auditor"] = auditor
    episode_bridge["membership"] = membership
    mint_only["independent_audit"]["episodes"][0]["component_bridge"] = episode_bridge
    assert certificate_comparison_proof(mint_only["independent_audit"], ledger) is False

    empty_top = deepcopy(report)
    empty_top["independent_audit"]["component_bridges"] = []
    assert certificate_comparison_proof(empty_top["independent_audit"], ledger) is True

    unit_split = deepcopy(report)
    unit_split["independent_audit"]["episodes"][0]["component_bridge"] = {
        **unit_split["independent_audit"]["episodes"][0]["component_bridge"],
        "unit": "USDC",
    }
    assert certificate_comparison_proof(unit_split["independent_audit"], ledger) is False


def test_empty_or_missing_ledger_is_non_certifying():
    report = _eligible_report()
    audit = report["independent_audit"]
    assert certificate_comparison_proof(audit, None) is False
    assert certificate_comparison_proof(audit, []) is False
    assert bindable_independent_audit(audit, report["independent_audit"]["content_fingerprint"], []) is None
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    profile["completed_episode_ledger"] = []
    report["completed_episode_ledger"] = []
    assert independently_audited(report, profile) is False
    assert qualification_category(report, profile)["category"] != "positive_matched_position_evidence"


def test_gap1_mutations_reject_through_ranked_and_compare(tmp_path):
    report = _eligible_report()
    built = build_research_profile(deepcopy(report), filters=default_filters())
    store = Store(tmp_path / "gap1")
    amounts = _mutate_bridges(report, lambda bridge, _index: {
        **bridge,
        "components": {
            **bridge["components"],
            "acquisition": {**bridge["components"]["acquisition"], "app": "999", "auditor": "999"},
            "proceeds": {**bridge["components"]["proceeds"], "app": "1002", "auditor": "1002"},
        },
    })
    amounts["address"] = "SynthGap1Amounts0842AAAAAAAAAAAAAAAAAA"
    units = _mutate_bridges(report, lambda bridge, _index: {**bridge, "unit": "USDC"})
    units["address"] = "SynthGap1Units0842AAAAAAAAAAAAAAAAAAAA"
    identity = deepcopy(report)
    identity["address"] = "SynthGap1Identity0842AAAAAAAAAAAAAAAA"
    episode_bridge = deepcopy(identity["independent_audit"]["episodes"][0]["component_bridge"])
    membership = dict(episode_bridge["membership"])
    auditor = dict(membership["auditor"])
    auditor["close_signature"] = "one-representation-only"
    membership["auditor"] = auditor
    episode_bridge["membership"] = membership
    identity["independent_audit"]["episodes"][0]["component_bridge"] = episode_bridge

    extras = []
    for mutated, report_id in ((amounts, "amt"), (units, "unit"), (identity, "id")):
        profile = {
            **_positive_saved(mutated, built),
            "completed_episode_ledger": mutated["completed_episode_ledger"],
            "independent_audit": mutated["independent_audit"],
        }
        persisted = _persist(store, mutated, profile, report_id)
        extras.append(_universe_row(persisted["address"]))
        ranked = ranked_workflow_view(store, extra_universe_rows=[_universe_row(persisted["address"])])
        row = next(item for item in ranked["rows"] if item["address"] == persisted["address"])
        assert independently_audited(persisted, row["research_profile"]) is False, report_id
        level = (row["qualification_level"] or {}).get("level") if isinstance(row.get("qualification_level"), dict) else None
        assert level not in ("provisional_research_lead", "stronger_research_shortlist"), report_id
        compared = compare_reports(store, persisted["id"], persisted["id"])
        assert compared["window_policy"]["left_independently_audited"] is False


def test_saved_decisions_rebuild_evidence_class_and_funnels(tmp_path):
    report = _eligible_report()
    built = build_research_profile(deepcopy(report), filters=default_filters())
    store = Store(tmp_path / "gap2")
    saved = _positive_saved(report, built)

    zero = deepcopy(report)
    zero["completed_episode_ledger"] = []
    zero["address"] = "SynthGap2Zero0842AAAAAAAAAAAAAAAAAAAA"
    zero_profile = {
        **saved,
        "completed_episode_ledger": [],
        "evidence_class": {"position": {"class": 1, "label": "stale"}, "account": {"class": 5}},
        "qualification_category": {"category": "positive_matched_position_evidence", "evidence_class": 1},
        "funnel": saved["funnel"],
        "criteria_met": True,
    }
    persisted_zero = _persist(store, zero, zero_profile, "zero")
    reconciled_zero = reconcile_saved_profile(zero, deepcopy(zero_profile))
    assert reconciled_zero["funnel"]["C"]["state"] != "MET"
    assert reconciled_zero["funnel"]["B"]["state"] != "ESTABLISHED"
    assert reconciled_zero["qualification_category"]["category"] != "positive_matched_position_evidence"
    zero_row = next(
        item for item in ranked_workflow_view(store, extra_universe_rows=[_universe_row(zero["address"])])["rows"]
        if item["address"] == zero["address"]
    )
    assert zero_row["research_profile"]["evidence_class"]["position"]["class"] != 1
    assert zero_row["qualification_category"]["category"] != "positive_matched_position_evidence"
    assert zero_row["funnel"]["C"]["state"] != "MET"
    assert zero_row["funnel"]["B"]["state"] != "ESTABLISHED"

    negative = deepcopy(report)
    negative["completed_episode_ledger"] = [{**row, "net": "-3"} for row in report["completed_episode_ledger"]]
    negative["address"] = "SynthGap2Neg0842AAAAAAAAAAAAAAAAAAAAA"
    persisted_neg = _persist(store, negative, deepcopy(saved), "neg")
    neg_row = next(
        item for item in ranked_workflow_view(store, extra_universe_rows=[_universe_row(negative["address"])])["rows"]
        if item["address"] == negative["address"]
    )
    assert neg_row["funnel"]["C"]["state"] != "MET"
    assert Decimal(str(neg_row["research_profile"]["completed_episode_net"])) == Decimal("-12")

    empty = deepcopy(report)
    empty["completed_episode_ledger"] = []
    empty["address"] = "SynthGap2Empty0842AAAAAAAAAAAAAAAAAAA"
    persisted_empty = _persist(store, empty, deepcopy(saved), "empty")
    membership = deepcopy(report)
    changed = [{**row} for row in report["completed_episode_ledger"]]
    changed[0] = {**changed[0], "mint": "ChangedMint0842AAAAAAAAAAAAAAAAAAAAAAAAA", "close_signature": "changed-close-0"}
    membership["completed_episode_ledger"] = changed
    membership["address"] = "SynthGap2Mem0842AAAAAAAAAAAAAAAAAAAAA"
    persisted_mem = _persist(store, membership, deepcopy(saved), "mem")

    ranked = ranked_workflow_view(store, extra_universe_rows=[
        _universe_row(zero["address"]),
        _universe_row(negative["address"]),
        _universe_row(empty["address"]),
        _universe_row(membership["address"]),
    ])
    for address in (zero["address"], negative["address"], empty["address"]):
        row = next(item for item in ranked["rows"] if item["address"] == address)
        assert row["funnel"]["C"]["state"] != "MET"
        assert row["qualification_category"]["category"] != "positive_matched_position_evidence"
    mem_row = next(item for item in ranked["rows"] if item["address"] == membership["address"])
    assert independently_audited(persisted_mem, mem_row["research_profile"]) is False
    assert mem_row["research_profile"]["independent_audit"] in (None, {})
    compared = compare_reports(store, persisted_neg["id"], persisted_empty["id"])
    assert compared["left_funnel"]["C"]["state"] != "MET"
    assert compared["right_funnel"]["C"]["state"] != "MET"
    assert (compared["left_funnel"].get("C") or {}).get("criteria_met") is not True
    assert compared["left_qualification_category"]["category"] != "positive_matched_position_evidence"
    assert compared["right_qualification_category"]["category"] != "positive_matched_position_evidence"

    stale_class4 = deepcopy(saved)
    stale_class4["evidence_class"] = {"position": {"class": 5}, "account": {"class": 4, "label": "stale account"}}
    stale_class4["qualification_category"] = {"category": "profitable_account_performance", "evidence_class": 4}
    empty_class = deepcopy(report)
    empty_class["completed_episode_ledger"] = []
    empty_class["address"] = "SynthGap2Class40842AAAAAAAAAAAAAAAAAA"
    persisted_class = _persist(store, empty_class, stale_class4, "class4")
    class_row = next(
        item for item in ranked_workflow_view(store, extra_universe_rows=[_universe_row(empty_class["address"])])["rows"]
        if item["address"] == empty_class["address"]
    )
    assert class_row["qualification_category"]["category"] != "profitable_account_performance"
    del persisted_zero, persisted_mem, persisted_class


def test_durable_store_ignores_stale_or_empty_supplied_state(tmp_path):
    draft = load_next_capture_draft()
    assert draft["enabled"] is False
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    store = Store(tmp_path / "cap-a")
    requested = {
        "address": gtfo["address"],
        "phase": 1,
        "block_time_lt": 1791206967,
        "pagination_token": gtfo["continue_from_pagination_token"],
    }
    first = run_next_capture_offline(
        draft=draft,
        requested=requested,
        grant=_synthetic_grant(draft),
        transport=lambda _request: (_ for _ in ()).throw(TimeoutError("timeout")),
        store=store,
        now=NOW,
    )
    assert first["attempt_consumed"] is True
    assert first["state"]["requests_used"] == 1

    stale = empty_next_capture_state()
    stale["requests_used"] = 0
    stale["replay_completed"] = True
    loaded = load_next_capture_state(store, draft, stale)
    assert loaded["requests_used"] == 1
    assert loaded["replay_completed"] is False
    reopened = run_next_capture_offline(
        draft=draft,
        requested=requested,
        grant=_synthetic_grant(draft),
        transport=lambda _request: (_ for _ in ()).throw(AssertionError("stale supplied state reached transport")),
        store=store,
        state=stale,
        now=NOW,
    )
    assert reopened["dispatched"] is False
    assert reopened["transport_calls"] == 0
    assert reopened["state"]["requests_used"] == 1
    assert reopened["code"] == "second_before_replay"


def test_reservation_invalidates_last_dispatch_and_binds_progress(tmp_path):
    draft = load_next_capture_draft()
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    store = Store(tmp_path / "cap-b")
    first = run_next_capture_offline(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": gtfo["continue_from_pagination_token"]},
        grant=_synthetic_grant(draft),
        transport=lambda _request: {"pagination_token": "next-1", "response_id": "resp-success"},
        store=store,
        now=NOW,
    )
    assert first["dispatched"] is True
    old_id = first["response_id"]
    assert record_next_capture_replay(first["state"], {"response_id": old_id, "page_identity": gtfo["continue_from_pagination_token"]}) is True
    persist_next_capture_state(store, draft, first["state"])

    timed = run_next_capture_offline(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": "next-1"},
        grant=_synthetic_grant(draft),
        transport=lambda _request: (_ for _ in ()).throw(TimeoutError("newer attempt timeout")),
        store=store,
        previous_progress={
            "response_id": old_id,
            "page_identity": gtfo["continue_from_pagination_token"],
            "named_dependency_observations": [{
                "signature": gtfo["named_dependency_items"][0]["signature"],
                "unresolved_basis_cleared": True,
                "result": "named_sale_or_lot_unresolved_basis_cleared",
            }],
        },
        now=NOW,
    )
    assert timed["attempt_consumed"] is True
    assert timed["state"]["last_dispatch"]["status"] == "failed"
    assert timed["state"]["last_dispatch"]["response_id"] is None
    assert record_next_capture_replay(timed["state"], {"response_id": old_id, "page_identity": gtfo["continue_from_pagination_token"]}) is False
    stripped = bind_progress_to_replay(
        {"response_id": old_id, "named_dependency_observations": [{"signature": "x", "result": "named_sale_or_lot_unresolved_basis_cleared"}]},
        timed["state"]["last_dispatch"],
        [{"response_id": old_id}],
    )
    assert stripped["named_dependency_observations"] == []

    fresh_receipt_stale_progress = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": "next-1"},
        last_dispatch={"address": gtfo["address"], "response_id": "fresh-id", "page_identity": "next-1", "authorization_id": draft["authorization_id"], "attempt": 2},
        replay_receipts=[{"response_id": "fresh-id", "page_identity": "next-1", "address": gtfo["address"], "authorization_id": draft["authorization_id"], "attempt": 2}],
        previous_progress={
            "response_id": old_id,
            "named_dependency_observations": [{
                "signature": gtfo["named_dependency_items"][0]["signature"],
                "unresolved_basis_cleared": True,
                "result": "named_sale_or_lot_unresolved_basis_cleared",
            }],
        },
        requests_used=2,
        per_wallet_used={gtfo["address"]: 2},
        accepted_continuation={gtfo["address"]: "next-1"},
        cursor_state={gtfo["address"]: "open"},
    )
    assert fresh_receipt_stale_progress["code"] == "named_dependency_not_approached"

    missing_id = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": "next-1"},
        last_dispatch={"address": gtfo["address"], "response_id": "fresh-id", "page_identity": "next-1", "authorization_id": draft["authorization_id"], "attempt": 2},
        replay_receipts=[{"response_id": "fresh-id", "page_identity": "next-1", "address": gtfo["address"], "authorization_id": draft["authorization_id"], "attempt": 2}],
        previous_progress={
            "named_dependency_observations": [{
                "signature": gtfo["named_dependency_items"][0]["signature"],
                "unresolved_basis_cleared": True,
                "result": "named_sale_or_lot_unresolved_basis_cleared",
            }],
        },
        requests_used=2,
        per_wallet_used={gtfo["address"]: 2},
        accepted_continuation={gtfo["address"]: "next-1"},
        cursor_state={gtfo["address"]: "open"},
    )
    assert missing_id["code"] == "named_dependency_not_approached"


def test_a6ps_additional_page_unavailable_and_wallet_observations():
    draft = load_next_capture_draft()
    assert draft["enabled"] is False
    a6ps = next(row for row in draft["allowed_wallets"] if row.get("separately_authorized_phase_two_start"))
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    assert a6ps["additional_page_unavailable"] is True
    assert a6ps["max_additional_pages_if_previous_resolved_named_dependency"] == 0
    assert a6ps["named_dependency_items"] == []
    replay = {
        "last_dispatch": {
            "address": gtfo["address"],
            "response_id": "gtfo-page-1",
            "page_identity": gtfo["continue_from_pagination_token"],
            "authorization_id": draft["authorization_id"],
            "attempt": 1,
        },
        "replay_receipts": [{
            "response_id": "gtfo-page-1",
            "page_identity": gtfo["continue_from_pagination_token"],
            "address": gtfo["address"],
            "authorization_id": draft["authorization_id"],
            "attempt": 1,
        }],
    }
    first = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": a6ps["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": a6ps["continue_from_pagination_token"]},
        requests_used=1,
        **replay,
    )
    assert first["allowed"] is True
    second = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": a6ps["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": a6ps["continue_from_pagination_token"]},
        requests_used=2,
        per_wallet_used={a6ps["address"]: 1},
        accepted_continuation={a6ps["address"]: a6ps["continue_from_pagination_token"]},
        cursor_state={a6ps["address"]: "open"},
        previous_progress={
            "response_id": "gtfo-page-1",
            "page_identity": gtfo["continue_from_pagination_token"],
            "named_dependency_observations": [{
                "mint": "A6PS-concentrated-largest-winner",
                "result": "named_sale_or_lot_gained_classified_cost_role",
            }],
        },
        **replay,
    )
    assert second["code"] == "additional_page_unavailable"

    generic = named_dependency_progress(
        {
            "response_id": "gtfo-page-1",
            "named_dependency_observations": [{
                "signature": gtfo["named_dependency_items"][0]["signature"],
                "result": "named_sale_or_lot_gained_classified_cost_role",
                "classified_cost_role": True,
            }],
        },
        gtfo,
    )
    assert generic["progress"] is False
    accepted = named_dependency_progress(
        {
            "response_id": "gtfo-page-1",
            "named_dependency_observations": [{
                "signature": gtfo["named_dependency_items"][0]["signature"],
                "result": "named_sale_or_lot_unresolved_basis_cleared",
                "unresolved_basis_cleared": True,
            }],
        },
        gtfo,
    )
    assert accepted["progress"] is True


def test_remaining_quota_enforced_at_reservation(tmp_path):
    draft = load_next_capture_draft()
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    requested = {
        "address": gtfo["address"],
        "phase": 1,
        "block_time_lt": 1791206967,
        "pagination_token": gtfo["continue_from_pagination_token"],
    }
    calls = []

    def recorder(request):
        calls.append(request)
        return {"pagination_token": f"n{len(calls)}", "response_id": f"r{len(calls)}"}

    zero = run_next_capture_offline(
        draft=draft,
        requested=requested,
        grant=_synthetic_grant(draft, current_remaining_quota_confirmation=_quota_record(0)),
        transport=recorder,
        store=Store(tmp_path / "q0"),
        now=NOW,
    )
    assert zero["dispatched"] is False
    assert zero["transport_calls"] == 0
    assert zero["code"] == "quota_exhausted"
    assert calls == []

    assert validate_operator_quota_record({**_quota_record(), "operator": ""}) == "quota_operator_missing"
    assert validate_operator_quota_record({k: v for k, v in _quota_record().items() if k != "confirmed_at"}) == "quota_confirmed_at_missing"
    assert validate_operator_quota_record({k: v for k, v in _quota_record().items() if k != "baseline"}) == "quota_baseline_missing"
    assert validate_fresh_approval_bind(
        _synthetic_grant(draft, current_remaining_quota_confirmation=_quota_record(confirmed_at="2026-10-09T00:00:00Z")),
        draft,
        now=NOW,
    ) == "quota_confirmed_after_expiry"

    store = Store(tmp_path / "q2")
    grant = _synthetic_grant(draft, current_remaining_quota_confirmation=_quota_record(2))
    first = run_next_capture_offline(draft=draft, requested=requested, grant=grant, transport=recorder, store=store, now=NOW)
    assert first["dispatched"] is True
    assert record_next_capture_replay(first["state"], {"response_id": first["response_id"], "page_identity": gtfo["continue_from_pagination_token"]}) is True
    persist_next_capture_state(store, draft, first["state"])
    second = run_next_capture_offline(
        draft=draft,
        requested={**requested, "pagination_token": first["state"]["accepted_continuation"][gtfo["address"]]},
        grant=grant,
        transport=lambda _request: (_ for _ in ()).throw(TimeoutError("fail counts")),
        store=store,
        previous_progress={
            "response_id": first["response_id"],
            "page_identity": gtfo["continue_from_pagination_token"],
            "named_dependency_observations": [{
                "signature": gtfo["named_dependency_items"][0]["signature"],
                "unresolved_basis_cleared": True,
                "result": "named_sale_or_lot_unresolved_basis_cleared",
            }],
        },
        now=NOW,
    )
    assert second["attempt_consumed"] is True
    third = run_next_capture_offline(
        draft=draft,
        requested={**requested, "pagination_token": first["state"]["accepted_continuation"][gtfo["address"]]},
        grant=grant,
        transport=recorder,
        store=store,
        now=NOW,
    )
    assert third["dispatched"] is False
    assert third["code"] == "quota_exhausted"
    assert third["transport_calls"] == 0
    assert len(calls) == 1


def test_mounted_component_trees_reject_invalid_and_stale_payloads(tmp_path):
    report = _eligible_report()
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    valid = {
        "address": report["address"],
        "completed_episode_ledger": report["completed_episode_ledger"],
        "independent_audit": report["independent_audit"],
        "research_profile": profile,
        "qualification_category": profile.get("qualification_category"),
        "funnel": profile.get("funnel"),
        "capture_available": True,
        "provider_rank": 101,
        "trade_count": 50,
    }
    amounts = _mutate_bridges(report, lambda bridge, _index: {
        **bridge,
        "components": {
            **bridge["components"],
            "acquisition": {**bridge["components"]["acquisition"], "app": "999", "auditor": "999"},
            "proceeds": {**bridge["components"]["proceeds"], "app": "1002", "auditor": "1002"},
        },
    })
    empty = deepcopy(report)
    empty["completed_episode_ledger"] = []
    stale = {
        "address": "SynthStale0842AAAAAAAAAAAAAAAAAAAAAAAA",
        "completed_episode_ledger": [],
        "independent_audit": report["independent_audit"],
        "research_profile": {
            **profile,
            "completed_episode_ledger": [],
            "completed_known_cost_positions": 0,
            "criteria_met": False,
            "qualification_category": {"category": "positive_matched_position_evidence", "evidence_class": 1},
            "funnel": {"A": {"state": "YES"}, "B": {"state": "ESTABLISHED"}, "C": {"state": "MET", "criteria_met": True}},
            "independent_audit": report["independent_audit"],
        },
        "qualification_category": {"category": "positive_matched_position_evidence"},
        "funnel": {"A": {"state": "YES"}, "B": {"state": "ESTABLISHED"}, "C": {"state": "MET", "criteria_met": True}},
        "compare": {
            "left_funnel": {"C": {"state": "MET", "criteria_met": True}},
            "right_funnel": {"C": {"state": "MET", "criteria_met": True}},
            "left_qualification_category": {"category": "positive_matched_position_evidence"},
            "right_qualification_category": {"category": "positive_matched_position_evidence"},
            "window_policy": {
                "left_sample_size": 0,
                "right_sample_size": 0,
                "left_independently_audited": False,
                "right_independently_audited": False,
            },
        },
    }
    payload = {
        "valid": valid,
        "amounts": {
            **amounts,
            "research_profile": {**profile, "independent_audit": amounts["independent_audit"]},
            "qualification_category": {"category": "analysed_incomplete"},
            "funnel": {"C": {"state": "NOT_MET"}},
        },
        "emptyLedger": {
            **empty,
            "research_profile": {
                **profile,
                "completed_episode_ledger": [],
                "completed_known_cost_positions": 0,
                "independent_audit": empty["independent_audit"],
                "qualification_category": {"category": "analysed_incomplete"},
                "funnel": {"C": {"state": "NOT_MET"}},
            },
        },
        "staleCategoryFunnel": stale,
        "staleCountAndEmptyLedger": {
            "address": "SynthStaleCount0842AAAAAAAAAAAAAAAAAAA",
            "completed_episode_ledger": [],
            "independent_audit": report["independent_audit"],
            "research_profile": {
                **profile,
                "completed_episode_ledger": [],
                "completed_known_cost_positions": 4,
                "criteria_met": True,
                "qualification_category": {"category": "positive_matched_position_evidence", "evidence_class": 1},
                "funnel": {"A": {"state": "YES"}, "B": {"state": "ESTABLISHED"}, "C": {"state": "MET", "criteria_met": True}},
                "independent_audit": report["independent_audit"],
            },
            "qualification_category": {"category": "positive_matched_position_evidence"},
            "funnel": {"A": {"state": "YES"}, "B": {"state": "ESTABLISHED"}, "C": {"state": "MET", "criteria_met": True}},
            "compare": {
                "left_funnel": {"C": {"state": "MET", "criteria_met": True}},
                "right_funnel": {"C": {"state": "MET", "criteria_met": True}},
                "left_qualification_category": {"category": "positive_matched_position_evidence"},
                "right_qualification_category": {"category": "positive_matched_position_evidence"},
                "window_policy": {
                    "left_sample_size": 0,
                    "right_sample_size": 0,
                    "left_independently_audited": False,
                    "right_independently_audited": False,
                },
            },
        },
        "headline999": {
            **valid,
            "independent_audit": {
                **report["independent_audit"],
                "independently_audited_episode_net": "999",
                "auditor_confirmation": "auditor confirms within 2 lamports: 999 SOL",
            },
            "auditorConfirmationForbidden": "999",
        },
        "contradictoryRepresentation": {
            **valid,
            "independent_audit": {
                **report["independent_audit"],
                "episodes": [
                    {
                        **report["independent_audit"]["episodes"][0],
                        "component_bridge": {
                            **report["independent_audit"]["episodes"][0]["component_bridge"],
                            "components": {
                                **report["independent_audit"]["episodes"][0]["component_bridge"]["components"],
                                "net": {"app": "9", "auditor": "9"},
                            },
                        },
                    },
                    *report["independent_audit"]["episodes"][1:],
                ],
            },
        },
        "profileUnitMismatch": {
            **valid,
            "expectProof": True,
            "research_profile": {**profile, "completed_episode_net_unit": "USDC"},
            "auditorConfirmationForbidden": "auditor confirms",
        },
    }
    cases_path = tmp_path / "0842-cases.json"
    cases_path.write_text(json.dumps(payload), encoding="utf-8")
    result = subprocess.run(
        ["node", "--experimental-strip-types", str(SCRIPT), str(cases_path)],
        cwd=str(ROOT / "frontend"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    body = json.loads(result.stdout.strip().splitlines()[-1])
    assert body["ok"] is True
    assert body["mounted"] is True
    draft = json.loads(DRAFT.read_text(encoding="utf-8"))
    assert draft["enabled"] is False
    assert draft["PRODUCT_READY"] is False


def test_extra_variants_missing_component_extra_episode_and_idempotence():
    report = _eligible_report()
    ledger = report["completed_episode_ledger"]
    missing_acq = [{**row} for row in ledger]
    missing_acq[0] = {k: v for k, v in missing_acq[0].items() if k != "acquisition"}
    assert certificate_comparison_proof(report["independent_audit"], missing_acq) is False
    extra = list(ledger) + [{
        "mint": "ExtraMint0842AAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "close_signature": "extra-close",
        "unit": "SOL",
        "acquisition": "1",
        "proceeds": "1",
        "costs": "0",
        "net": "0",
    }]
    assert certificate_comparison_proof(report["independent_audit"], extra) is False
    swapped = [{**row} for row in ledger]
    swapped[0] = {**swapped[0], "unit": "USDC"}
    assert certificate_comparison_proof(report["independent_audit"], swapped) is False
    for app, auditor, unit, expected in (
        ("1", "1.000000002", "SOL", True),
        ("1", "1.000000003", "SOL", False),
        ("1", "1.000002", "USDC", True),
        ("1", "1.000003", "USDC", False),
        ("1.0000000015", "1.000000002", "SOL", True),
    ):
        assert amounts_agree(app, auditor, unit) is expected
    built = build_research_profile(deepcopy(report), filters=default_filters())
    saved = _positive_saved(report, built)
    empty = deepcopy(report)
    empty["completed_episode_ledger"] = []
    first = reconcile_saved_profile(empty, deepcopy(saved))
    second = reconcile_saved_profile(empty, deepcopy(first))
    assert first["qualification_category"]["category"] == second["qualification_category"]["category"]
    assert first["funnel"]["C"]["state"] == second["funnel"]["C"]["state"]
    assert first["completed_known_cost_positions"] == 0
    assert second["completed_known_cost_positions"] == 0


def test_persist_failure_before_transport_does_not_dispatch(tmp_path):
    draft = load_next_capture_draft()
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    inner = Store(tmp_path / "boom")
    calls = []

    class BoomStore:
        def get(self, kind, ident, default=None):
            return inner.get(kind, ident, default)

        def put(self, kind, ident, payload):
            raise OSError("durable persist failed before transport")

    try:
        run_next_capture_offline(
            draft=draft,
            requested={
                "address": gtfo["address"],
                "phase": 1,
                "block_time_lt": 1791206967,
                "pagination_token": gtfo["continue_from_pagination_token"],
            },
            grant=_synthetic_grant(draft),
            transport=lambda request: calls.append(request) or {"response_id": "x"},
            store=BoomStore(),
            now=NOW,
        )
    except OSError as exc:
        assert "persist failed" in str(exc)
    else:
        raise AssertionError("persist failure must surface")
    assert calls == []
