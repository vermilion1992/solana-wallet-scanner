"""Independent re-attack of the 08:42 named counterexamples against this tip.

Not a copy of the implementer-named fixtures only: each case is rebuilt here
and asserted through the public predicates and consumers.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from scanner.mass_search.history_ingest import (
    draft_execution_artifact_hash,
    empty_next_capture_state,
    evaluate_next_capture_dispatch,
    load_next_capture_draft,
    load_next_capture_state,
    persist_next_capture_state,
    record_next_capture_replay,
    run_next_capture_offline,
    validate_operator_quota_record,
)
from scanner.mass_search.qualification_gates import (
    bindable_independent_audit,
    certificate_comparison_proof,
    reconcile_saved_profile,
)
from scanner.mass_search.research_profile import (
    build_research_profile,
    default_filters,
    independently_audited,
)
from scanner.mass_search.workflow import compare_reports, ranked_workflow_view
from scanner.storage import Store
from tests.test_chatgpt_review_2026_10_07_rereview import _eligible_report

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def _grant(draft, remaining=8, **quota_over):
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
    record.update(quota_over)
    return {
        "enabled": False,
        "synthetic_offline_authorization": True,
        "authorization_id": draft["authorization_id"],
        "execution_artifact_hash_of_this_draft": draft_execution_artifact_hash(draft),
        "current_remaining_quota_confirmation": record,
        "overages_enabled": False,
        "approval_timestamp": "2026-10-07T00:00:00Z",
        "expiry": "2026-10-08T00:00:00Z",
    }


def _set_bridge_amounts(report, acquisition, proceeds, costs, net):
    mutated = deepcopy(report)
    audit = mutated["independent_audit"]
    for index, bridge in enumerate(audit["component_bridges"]):
        comps = dict(bridge["components"])
        for name, value in (("acquisition", acquisition), ("proceeds", proceeds), ("costs", costs), ("net", net)):
            comps[name] = {**comps[name], "app": value, "auditor": value}
        audit["component_bridges"][index] = {**bridge, "components": comps}
        audit["episodes"][index]["component_bridge"] = audit["component_bridges"][index]
    return mutated


def test_named_ledger_1_4_0_3_vs_bridge_999_1002_0_3_rejects():
    report = _eligible_report()
    ledger = [{
        **row,
        "acquisition": "1",
        "proceeds": "4",
        "costs": "0",
        "net": "3",
        "unit": "SOL",
    } for row in report["completed_episode_ledger"]]
    mutated = _set_bridge_amounts(report, "999", "1002", "0", "3")
    assert certificate_comparison_proof(mutated["independent_audit"], ledger) is False
    profile = build_research_profile({**mutated, "completed_episode_ledger": ledger}, filters=default_filters())
    assert independently_audited({**mutated, "completed_episode_ledger": ledger}, profile) is False


def test_named_bridge_usdc_vs_ledger_sol_rejects():
    report = _eligible_report()
    mutated = deepcopy(report)
    for index, bridge in enumerate(mutated["independent_audit"]["component_bridges"]):
        mutated["independent_audit"]["component_bridges"][index] = {**bridge, "unit": "USDC"}
        mutated["independent_audit"]["episodes"][index]["component_bridge"] = mutated["independent_audit"]["component_bridges"][index]
    assert certificate_comparison_proof(mutated["independent_audit"], report["completed_episode_ledger"]) is False


def test_named_auditor_close_only_in_episode_representation_rejects():
    report = _eligible_report()
    mutated = deepcopy(report)
    bridge = deepcopy(mutated["independent_audit"]["episodes"][0]["component_bridge"])
    membership = dict(bridge["membership"])
    auditor = dict(membership["auditor"])
    auditor["close_signature"] = "only-episode-local-close"
    membership["auditor"] = auditor
    bridge["membership"] = membership
    mutated["independent_audit"]["episodes"][0]["component_bridge"] = bridge
    assert certificate_comparison_proof(mutated["independent_audit"], report["completed_episode_ledger"]) is False
    assert bindable_independent_audit(
        mutated["independent_audit"],
        mutated["independent_audit"]["content_fingerprint"],
        report["completed_episode_ledger"],
    ) is None


def test_named_empty_and_missing_ledger_with_stale_audit_do_not_certify():
    report = _eligible_report()
    audit = report["independent_audit"]
    assert certificate_comparison_proof(audit, None) is False
    assert certificate_comparison_proof(audit, []) is False
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    profile["independent_audit"] = audit
    profile["completed_episode_ledger"] = []
    stale = {**report, "completed_episode_ledger": [], "research_profile": profile, "independent_audit": audit}
    assert independently_audited(stale, profile) is False


def test_named_mismatched_units_do_not_render_as_audited():
    report = _eligible_report()
    report["independent_audit"] = {
        **report["independent_audit"],
        "independently_audited": True,
        "independently_audited_episode_net_unit": "USDC",
        "app_completed_episode_net_unit": "SOL",
    }
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    profile["completed_episode_net_unit"] = "SOL"
    profile["independent_audit"] = report["independent_audit"]
    assert independently_audited(report, profile) is False
    usdc_bridges = deepcopy(report)
    for index, bridge in enumerate(usdc_bridges["independent_audit"]["component_bridges"]):
        usdc_bridges["independent_audit"]["component_bridges"][index] = {**bridge, "unit": "USDC"}
        usdc_bridges["independent_audit"]["episodes"][index]["component_bridge"] = usdc_bridges["independent_audit"]["component_bridges"][index]
    usdc_bridges["independent_audit"]["independently_audited_episode_net_unit"] = "USDC"
    built = build_research_profile(usdc_bridges, filters=default_filters())
    assert independently_audited(usdc_bridges, built) is False


def test_named_stale_class1_zero_completed_is_not_positive_matched(tmp_path):
    report = _eligible_report()
    built = build_research_profile(deepcopy(report), filters=default_filters())
    report["completed_episode_ledger"] = []
    report["address"] = "SynthAdvZero0842AAAAAAAAAAAAAAAAAAAAA"
    saved = {
        **built,
        "completed_episode_ledger": [],
        "completed_known_cost_positions": 0,
        "evidence_class": {"position": {"class": 1, "label": "stale"}, "account": {"class": 5}},
        "qualification_category": {"category": "positive_matched_position_evidence", "evidence_class": 1},
        "criteria_met": True,
        "evaluated_thresholds": {"min_completed_known_cost": {"applied": True}},
        "funnel": {"C": {"state": "MET", "criteria_met": True}, "B": {"state": "ESTABLISHED"}, "A": {"state": "YES"}},
    }
    store = Store(tmp_path / "adv-state")
    payload = {**report, "id": "adv-zero", "source": "mass-search", "visible_report": True, "research_profile": saved, "funnel": saved["funnel"]}
    store.put("reports", "adv-zero", payload)
    row = next(
        item for item in ranked_workflow_view(store, extra_universe_rows=[{
            "address": report["address"], "provider_rank": 101, "trade_count": 50, "provider_score": "1",
            "shortlisted": False, "capture_available": True, "label": "SYNTHETIC", "row_kind": "synthetic_fixture", "corpus_kind": "SYNTHETIC",
        }])["rows"]
        if item["address"] == report["address"]
    )
    assert row["qualification_category"]["category"] != "positive_matched_position_evidence"
    assert row["research_profile"]["evidence_class"]["position"]["class"] != 1
    assert row["funnel"]["C"]["state"] != "MET"
    compared = compare_reports(store, "adv-zero", "adv-zero")
    assert compared["left_funnel"]["C"]["state"] != "MET"
    assert compared["right_funnel"]["C"]["state"] != "MET"


def test_named_durable_store_ignores_empty_and_stale_supplied_after_timeout(tmp_path):
    draft = load_next_capture_draft()
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    store = Store(tmp_path / "adv-capa")
    requested = {"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": gtfo["continue_from_pagination_token"]}
    first = run_next_capture_offline(
        draft=draft, requested=requested, grant=_grant(draft),
        transport=lambda _r: (_ for _ in ()).throw(TimeoutError("timeout")),
        store=store, now=NOW,
    )
    assert first["state"]["requests_used"] == 1
    empty = empty_next_capture_state()
    stale = {**empty, "requests_used": 0, "replay_completed": True}
    assert load_next_capture_state(store, draft, empty)["requests_used"] == 1
    assert load_next_capture_state(store, draft, stale)["requests_used"] == 1
    reopen = run_next_capture_offline(
        draft=draft, requested=requested, grant=_grant(draft),
        transport=lambda _r: (_ for _ in ()).throw(AssertionError("transport")),
        store=store, state=stale, now=NOW,
    )
    assert reopen["transport_calls"] == 0
    assert reopen["state"]["requests_used"] == 1


def test_named_old_receipt_cannot_rearm_after_newer_timeout(tmp_path):
    draft = load_next_capture_draft()
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    store = Store(tmp_path / "adv-capb")
    first = run_next_capture_offline(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": gtfo["continue_from_pagination_token"]},
        grant=_grant(draft),
        transport=lambda _r: {"pagination_token": "page-2", "response_id": "page1-receipt"},
        store=store, now=NOW,
    )
    old = first["response_id"]
    assert record_next_capture_replay(first["state"], {"response_id": old, "page_identity": gtfo["continue_from_pagination_token"]}) is True
    persist_next_capture_state(store, draft, first["state"])
    timed = run_next_capture_offline(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": "page-2"},
        grant=_grant(draft),
        transport=lambda _r: (_ for _ in ()).throw(TimeoutError("page2")),
        store=store,
        previous_progress={
            "response_id": old,
            "page_identity": gtfo["continue_from_pagination_token"],
            "named_dependency_observations": [{
                "signature": gtfo["named_dependency_items"][0]["signature"],
                "result": "named_sale_or_lot_unresolved_basis_cleared",
                "unresolved_basis_cleared": True,
            }],
        },
        now=NOW,
    )
    assert timed["state"]["last_dispatch"]["status"] == "failed"
    assert record_next_capture_replay(timed["state"], {"response_id": old, "page_identity": gtfo["continue_from_pagination_token"]}) is False
    fresh_stale = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": "page-2"},
        last_dispatch={"address": gtfo["address"], "response_id": "page2-fresh", "page_identity": "page-2"},
        replay_receipts=[{"response_id": "page2-fresh", "page_identity": "page-2"}],
        previous_progress={
            "response_id": old,
            "named_dependency_observations": [{
                "signature": gtfo["named_dependency_items"][0]["signature"],
                "result": "named_sale_or_lot_unresolved_basis_cleared",
                "unresolved_basis_cleared": True,
            }],
        },
        requests_used=2,
        per_wallet_used={gtfo["address"]: 2},
        accepted_continuation={gtfo["address"]: "page-2"},
        cursor_state={gtfo["address"]: "open"},
    )
    assert fresh_stale["allowed"] is False


def test_named_a6ps_additional_page_unavailable():
    draft = load_next_capture_draft()
    a6ps = next(row for row in draft["allowed_wallets"] if row.get("separately_authorized_phase_two_start"))
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    assert a6ps.get("additional_page_unavailable") is True
    assert a6ps.get("named_dependency_items") == []
    replay = {
        "last_dispatch": {"address": gtfo["address"], "response_id": "gtfo-page-1", "page_identity": gtfo["continue_from_pagination_token"]},
        "replay_receipts": [{"response_id": "gtfo-page-1", "page_identity": gtfo["continue_from_pagination_token"]}],
    }
    second = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": a6ps["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": a6ps["continue_from_pagination_token"]},
        requests_used=2,
        per_wallet_used={a6ps["address"]: 1},
        accepted_continuation={a6ps["address"]: a6ps["continue_from_pagination_token"]},
        cursor_state={a6ps["address"]: "open"},
        **replay,
    )
    assert second["code"] == "additional_page_unavailable"


def test_named_remaining_zero_never_reaches_transport(tmp_path):
    draft = load_next_capture_draft()
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    calls = []
    result = run_next_capture_offline(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": gtfo["continue_from_pagination_token"]},
        grant=_grant(draft, remaining=0),
        transport=lambda request: calls.append(request) or {"response_id": "x"},
        store=Store(tmp_path / "adv-e"),
        now=NOW,
    )
    assert result["transport_calls"] == 0
    assert result["code"] == "quota_exhausted"
    assert calls == []
    assert validate_operator_quota_record({**_grant(draft)["current_remaining_quota_confirmation"], "operator": ""}) == "quota_operator_missing"
    assert validate_operator_quota_record({k: v for k, v in _grant(draft)["current_remaining_quota_confirmation"].items() if k != "confirmed_at"}) == "quota_confirmed_at_missing"


def test_neighbour_app_or_auditor_only_and_top_level_only_mutations_reject():
    report = _eligible_report()
    ledger = report["completed_episode_ledger"]
    app_only = deepcopy(report)
    for index, bridge in enumerate(app_only["independent_audit"]["component_bridges"]):
        comps = dict(bridge["components"])
        comps["acquisition"] = {**comps["acquisition"], "app": "999"}
        comps["proceeds"] = {**comps["proceeds"], "app": "1002"}
        app_only["independent_audit"]["component_bridges"][index] = {**bridge, "components": comps}
        app_only["independent_audit"]["episodes"][index]["component_bridge"] = app_only["independent_audit"]["component_bridges"][index]
    assert certificate_comparison_proof(app_only["independent_audit"], ledger) is False
    auditor_only = deepcopy(report)
    for index, bridge in enumerate(auditor_only["independent_audit"]["component_bridges"]):
        comps = dict(bridge["components"])
        comps["acquisition"] = {**comps["acquisition"], "auditor": "999"}
        comps["proceeds"] = {**comps["proceeds"], "auditor": "1002"}
        auditor_only["independent_audit"]["component_bridges"][index] = {**bridge, "components": comps}
        auditor_only["independent_audit"]["episodes"][index]["component_bridge"] = auditor_only["independent_audit"]["component_bridges"][index]
    assert certificate_comparison_proof(auditor_only["independent_audit"], ledger) is False
    top_only = deepcopy(report)
    for index, bridge in enumerate(top_only["independent_audit"]["component_bridges"]):
        comps = dict(bridge["components"])
        comps["acquisition"] = {**comps["acquisition"], "app": "999", "auditor": "999"}
        comps["proceeds"] = {**comps["proceeds"], "app": "1002", "auditor": "1002"}
        top_only["independent_audit"]["component_bridges"][index] = {**bridge, "components": comps}
    assert certificate_comparison_proof(top_only["independent_audit"], ledger) is False


def test_neighbour_stale_count_empty_ledger_report_and_whitespace_operator(tmp_path):
    from scanner.mass_search.workflow import visible_mass_search_report

    report = _eligible_report()
    built = build_research_profile(deepcopy(report), filters=default_filters())
    report["completed_episode_ledger"] = []
    report["address"] = "SynthAdvStaleCount0842AAAAAAAAAAAAAAAA"
    saved = {
        **built,
        "completed_episode_ledger": [],
        "completed_known_cost_positions": 4,
        "criteria_met": True,
        "evidence_class": {"position": {"class": 1, "label": "stale"}, "account": {"class": 5}},
        "qualification_category": {"category": "positive_matched_position_evidence", "evidence_class": 1},
        "funnel": {"C": {"state": "MET", "criteria_met": True}, "B": {"state": "ESTABLISHED"}, "A": {"state": "YES"}},
    }
    visible = visible_mass_search_report({
        **report,
        "id": "adv-stale-count",
        "source": "mass-search",
        "research_profile": saved,
        "funnel": saved["funnel"],
    })
    assert visible["funnel"]["C"]["state"] != "MET"
    assert visible["qualification_category"]["category"] != "positive_matched_position_evidence"
    assert independently_audited(visible, visible["research_profile"]) is False
    draft = load_next_capture_draft()
    assert validate_operator_quota_record({**_grant(draft)["current_remaining_quota_confirmation"], "operator": "   "}) == "quota_operator_missing"
    assert validate_operator_quota_record({**_grant(draft)["current_remaining_quota_confirmation"], "operator": None}) == "quota_operator_missing"


def test_neighbour_reserved_status_and_a6ps_first_page_still_gated():
    draft = load_next_capture_draft()
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    a6ps = next(row for row in draft["allowed_wallets"] if row.get("separately_authorized_phase_two_start"))
    reserved = {
        "last_dispatch": {"address": gtfo["address"], "page_identity": gtfo["continue_from_pagination_token"], "status": "reserved", "response_id": None},
        "replay_receipts": [{"response_id": "old-page1", "page_identity": gtfo["continue_from_pagination_token"]}],
    }
    blocked = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": "page-2"},
        requests_used=1,
        per_wallet_used={gtfo["address"]: 1},
        accepted_continuation={gtfo["address"]: "page-2"},
        cursor_state={gtfo["address"]: "open"},
        **reserved,
    )
    assert blocked["allowed"] is False
    first = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": a6ps["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": a6ps["continue_from_pagination_token"]},
        last_dispatch={"address": gtfo["address"], "response_id": "gtfo-page-1", "page_identity": gtfo["continue_from_pagination_token"]},
        replay_receipts=[{"response_id": "gtfo-page-1", "page_identity": gtfo["continue_from_pagination_token"]}],
        requests_used=1,
        per_wallet_used={a6ps["address"]: 0},
        accepted_continuation={},
        cursor_state={a6ps["address"]: "not-started"},
    )
    assert first["allowed"] is True
    assert first["code"] == "would_serialize_only"
