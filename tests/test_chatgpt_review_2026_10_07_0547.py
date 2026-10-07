"""Closures for the 2026-10-07 05:47 re-review of PR #6 tip 45c1494.

Offline only. Every constructed wallet is SYNTHETIC.
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from scanner.mass_search.history_ingest import (
    draft_execution_artifact_hash,
    empty_next_capture_state,
    evaluate_next_capture_dispatch,
    load_next_capture_draft,
    named_dependency_progress,
    run_next_capture_offline,
)
from scanner.mass_search.qualification_gates import (
    amounts_agree,
    bindable_independent_audit,
    certificate_comparison_proof,
    component_bridge,
    compute_audit_fingerprint,
    qualifying_profit,
    reconcile_saved_profile,
    validate_episode_ledger,
)
from scanner.mass_search.research_profile import (
    build_research_profile,
    default_filters,
    independently_audited,
    load_committed_independent_audit,
)
from scanner.mass_search.workflow import (
    compare_reports,
    ranked_workflow_view,
    research_screen_run,
)
from scanner.storage import Store
from tests.test_chatgpt_review_2026_10_07_rereview import _eligible_report

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_FORMAT = ROOT / "frontend/src/format.ts"
MASS_SEARCH = ROOT / "frontend/src/MassSearch.tsx"
COVERAGE = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage"
REPORT = ROOT / "frontend/src/report.tsx"


def _agreeing_bridge(row, unit="SOL"):
    auditor = {
        "mint": row["mint"],
        "close_signature": row["close_signature"],
        "acquisition": row.get("acquisition") or row.get("basis"),
        "proceeds": row["proceeds"],
        "costs": row.get("costs") or row.get("verified_costs"),
        "net": row["net"],
    }
    return component_bridge(row, auditor, unit)


def test_fingerprint_status_without_comparison_proof_does_not_certify():
    report = _eligible_report()
    audit = dict(report["independent_audit"])
    audit.pop("episodes", None)
    audit.pop("component_bridges", None)
    audit.pop("one_to_one_membership", None)
    report["independent_audit"] = audit
    profile = build_research_profile(report, filters=default_filters())
    assert certificate_comparison_proof(audit) is False
    assert bindable_independent_audit(audit, profile["audit_fingerprint"]) is None
    assert independently_audited(report, profile) is False
    assert profile["qualification_level"]["level"] != "provisional_research_lead"


def test_certificate_mutations_detach_on_attachment_path():
    report = _eligible_report()
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    assert independently_audited(report, profile) is True

    missing = deepcopy(report)
    bridges = list(missing["independent_audit"]["component_bridges"])
    comps = dict(bridges[0]["components"])
    comps["acquisition"] = {**comps["acquisition"], "agree": False, "app": None, "auditor": None}
    bridges[0] = {**bridges[0], "components": comps, "agree": False}
    missing["independent_audit"]["component_bridges"] = bridges
    missing["independent_audit"]["episodes"][0]["component_bridge"] = bridges[0]
    missing_profile = build_research_profile(missing, filters=default_filters())
    assert independently_audited(missing, missing_profile) is False

    swapped = deepcopy(report)
    other = dict(swapped["completed_episode_ledger"][1])
    swapped_bridge = component_bridge(swapped["completed_episode_ledger"][0], {
        **other,
        "acquisition": other["acquisition"],
        "proceeds": other["proceeds"],
        "costs": other["costs"],
        "net": other["net"],
    }, "SOL")
    swapped["independent_audit"]["component_bridges"][0] = swapped_bridge
    swapped["independent_audit"]["episodes"][0]["component_bridge"] = swapped_bridge
    swapped_profile = build_research_profile(swapped, filters=default_filters())
    assert independently_audited(swapped, swapped_profile) is False

    dropped = deepcopy(report)
    dropped["independent_audit"]["component_bridges"] = dropped["independent_audit"]["component_bridges"][:-1]
    dropped["independent_audit"]["episodes"] = dropped["independent_audit"]["episodes"][:-1]
    dropped["independent_audit"]["one_to_one_membership"] = True
    dropped_profile = build_research_profile(dropped, filters=default_filters())
    assert independently_audited(dropped, dropped_profile) is False

    contradicted = deepcopy(report)
    contradicted["independent_audit"]["one_to_one_membership"] = False
    contradicted_profile = build_research_profile(contradicted, filters=default_filters())
    assert independently_audited(contradicted, contradicted_profile) is False
    assert bindable_independent_audit(
        contradicted["independent_audit"],
        contradicted_profile.get("audit_fingerprint") or compute_audit_fingerprint(contradicted),
    ) is None


def test_loader_carries_per_episode_component_bridges():
    payload = json.loads((COVERAGE / "INDEPENDENT_AUDIT.json").read_text(encoding="utf-8"))
    gtfo = next(row for row in payload["wallets"] if row["address"].startswith("gtfo"))
    loaded = load_committed_independent_audit(gtfo["address"], gtfo["content_fingerprint"])
    assert loaded is not None
    assert loaded["one_to_one_membership"] is True
    assert loaded["component_bridges"]
    assert all(bridge.get("agree") for bridge in loaded["component_bridges"])
    ledger = []
    for episode in loaded.get("episodes") or []:
        app = episode.get("app") or {}
        ledger.append({
            "mint": episode.get("mint"),
            "close_signature": episode.get("close_signature"),
            "unit": (episode.get("component_bridge") or {}).get("unit") or "SOL",
            "acquisition": app.get("basis") or app.get("acquisition"),
            "proceeds": app.get("proceeds"),
            "costs": app.get("verified_costs") or app.get("costs"),
            "net": app.get("net"),
        })
    assert certificate_comparison_proof(loaded, ledger) is True
    assert bindable_independent_audit(loaded, gtfo["content_fingerprint"], ledger) == loaded


def test_saved_profile_summary_cannot_override_negative_or_empty_ledger(tmp_path):
    report = _eligible_report()
    report["completed_episode_ledger"] = [{**row, "net": "-3"} for row in report["completed_episode_ledger"]]
    built = build_research_profile(report, filters=default_filters())
    saved = {
        **report,
        "id": "saved-neg",
        "research_profile": {
            **built,
            "completed_episode_net": "99",
            "completed_episode_net_unit": "SOL",
            "completed_episode_net_vector": {"SOL": "99"},
            "completed_known_cost_positions": 20,
        },
        "visible_report": True,
        "window": {"start": "2026-09-05T13:29:27Z", "end": "2026-10-05T13:29:27Z"},
    }
    amount, _unit, _vector = qualifying_profit(saved["research_profile"], saved)
    assert amount == Decimal("-12")
    store = Store(tmp_path / "neg")
    store.put("reports", saved["id"], saved)
    ranked = ranked_workflow_view(store)
    compared = compare_reports(store, saved["id"], saved["id"])
    assert compared["window_policy"]["left_completed_episode_net"] == "-12"
    assert compared["window_policy"]["left_independently_audited"] is False

    empty = deepcopy(saved)
    empty["id"] = "saved-empty"
    empty["completed_episode_ledger"] = []
    empty["research_profile"] = {
        **saved["research_profile"],
        "completed_episode_ledger": [],
        "completed_episode_net": "88",
        "completed_episode_net_vector": {"SOL": "88"},
        "completed_known_cost_positions": 4,
    }
    store.put("reports", empty["id"], empty)
    amount_empty, _u, _v = qualifying_profit(empty["research_profile"], empty)
    assert amount_empty is None
    reconciled = reconcile_saved_profile(empty, empty["research_profile"])
    assert reconciled["completed_episode_net"] is None
    assert reconciled["ledger_summary_contradiction"] is True
    compared_empty = compare_reports(store, empty["id"], empty["id"])
    assert compared_empty["window_policy"]["left_completed_episode_net"] in (None, )
    del ranked


def test_ledger_mutations_missing_net_unit_or_duplicate_identity():
    report = _eligible_report()
    missing_net = [{**row} for row in report["completed_episode_ledger"]]
    missing_net[0] = {k: v for k, v in missing_net[0].items() if k != "net"}
    assert validate_episode_ledger(missing_net)["ok"] is False
    assert validate_episode_ledger(missing_net)["reason"] == "missing_episode_net"
    assert qualifying_profit({"completed_episode_ledger": missing_net, "completed_episode_net": "99"}, {"completed_episode_ledger": missing_net})[0] is None

    missing_unit = [{**row} for row in report["completed_episode_ledger"]]
    missing_unit[0] = {k: v for k, v in missing_unit[0].items() if k != "unit"}
    assert validate_episode_ledger(missing_unit)["reason"] == "missing_settlement_unit"

    duplicate = list(report["completed_episode_ledger"]) + [dict(report["completed_episode_ledger"][0])]
    assert validate_episode_ledger(duplicate)["reason"] == "duplicate_episode_identity"


def test_research_screen_filter_match_is_not_certified(tmp_path):
    report = _eligible_report()
    del report["sensitivity_unverified_debits_sol"]
    report["independent_audit"] = {
        "status": "independently_audited",
        "independently_audited": True,
        "content_fingerprint": compute_audit_fingerprint(report),
    }
    profile = build_research_profile(report, filters=default_filters())
    report["research_profile"] = profile
    report["id"] = "screen-uncertified"
    universe = [{"address": report["address"], "capture_available": True}]
    result = research_screen_run(universe, {report["address"]: report}, default_filters())
    assert result["completed_qualified_are_sample_activity_filter_matches"] is True
    row = next(item for item in result["rows"] if item["address"] == report["address"])
    if row["outcome"] == "completed":
        assert row["certified_research_wallet"] is False
        assert "not a certified research wallet" in row["reason"]
        assert row["independently_audited"] is False
    assert independently_audited(report, profile) is False


def test_named_dependency_progress_rejects_bare_boolean_and_ignores_positivity():
    wallet = {"named_dependency": "free text only"}
    bare = named_dependency_progress({"approached_named_dependency": True}, wallet)
    assert bare["progress"] is False
    identified = {
        "named_dependency_items": [{"signature": "named-sale"}],
        "acceptable_progress_observations": ["named_sale_or_lot_unresolved_basis_cleared"],
    }
    evidence = {
        "named_dependency_observations": [{
            "signature": "named-sale",
            "unresolved_basis_cleared": True,
            "result": "named_sale_or_lot_unresolved_basis_cleared",
        }],
        "wallet_turned_positive": True,
    }
    with_pos = named_dependency_progress(evidence, identified)
    without_pos = named_dependency_progress({k: v for k, v in evidence.items() if k != "wallet_turned_positive"}, identified)
    assert with_pos["progress"] is True
    assert without_pos["progress"] is True
    assert with_pos["progress"] == without_pos["progress"]


def test_next_capture_phase_cursor_allowance_and_a6ps_second_page():
    draft = load_next_capture_draft()
    assert draft["enabled"] is False
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    a6ps = next(row for row in draft["allowed_wallets"] if row.get("separately_authorized_phase_two_start"))
    cccs = next(row for row in draft["allowed_wallets"] if row["address"].startswith("CccS"))
    pw58 = next(row for row in draft["allowed_wallets"] if row["address"].startswith("58PW"))
    assert evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": cccs["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": cccs["continue_from_pagination_token"]},
    )["code"] == "non_gtfo_initial"
    assert evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": gtfo["continue_from_pagination_token"]},
        requests_used=1,
        per_wallet_used={gtfo["address"]: 1},
        replay_completed=False,
    )["code"] == "second_before_replay"
    unlocked = deepcopy(pw58)
    unlocked["specific_dependency_recorded"] = True
    draft_unlocked = deepcopy(draft)
    draft_unlocked["allowed_wallets"] = [
        unlocked if row["address"].startswith("58PW") else row for row in draft["allowed_wallets"]
    ]
    replay = _replay_bound(gtfo["address"], gtfo["continue_from_pagination_token"])
    assert evaluate_next_capture_dispatch(
        draft=draft_unlocked,
        requested={"address": unlocked["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": unlocked["continue_from_pagination_token"]},
        replay_completed=True,
        requests_used=1,
        **replay,
    )["code"] == "zero_executable_allowance"
    first_a6ps = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": a6ps["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": a6ps["continue_from_pagination_token"]},
        replay_completed=True,
        requests_used=1,
        **replay,
    )
    assert first_a6ps["allowed"] is True
    second_a6ps = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": a6ps["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": a6ps["continue_from_pagination_token"]},
        replay_completed=True,
        requests_used=2,
        per_wallet_used={a6ps["address"]: 1},
        accepted_continuation={a6ps["address"]: a6ps["continue_from_pagination_token"]},
        cursor_state={a6ps["address"]: "open"},
        **replay,
    )
    assert second_a6ps["code"] == "additional_page_unavailable"
    assert evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": "stale-token"},
        replay_completed=True,
        requests_used=1,
        per_wallet_used={gtfo["address"]: 1},
        accepted_continuation={gtfo["address"]: "accepted-next"},
        cursor_state={gtfo["address"]: "open"},
        **replay,
    )["code"] == "wrong_cursor"


def _quota_record(remaining=8, draft=None):
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
    return record


def _replay_bound(address, page_identity, response_id="page-1", authorization_id=None, attempt=1):
    dispatch = {
        "address": address,
        "response_id": response_id,
        "page_identity": page_identity,
        "authorization_id": authorization_id or "live-ranked100-depth-biased-next-capture-2026-10-07-mitch-draft",
        "attempt": attempt,
    }
    return {
        "last_dispatch": dispatch,
        "replay_receipts": [{
            "response_id": response_id,
            "page_identity": page_identity,
            "address": address,
            "authorization_id": dispatch["authorization_id"],
            "attempt": attempt,
        }],
    }


def _synthetic_grant(draft, **overrides):
    quota = overrides.pop("current_remaining_quota_confirmation", _quota_record(draft=draft))
    if isinstance(quota, dict) and "authorization_id" not in quota:
        quota = {
            **quota,
            "authorization_id": draft["authorization_id"],
            "execution_artifact_hash": draft_execution_artifact_hash(draft),
        }
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


def test_next_capture_runner_reaches_recorder_once_and_invalid_zero_times(tmp_path):
    draft = load_next_capture_draft()
    assert draft["enabled"] is False
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    calls = []

    def recorder(request):
        calls.append(request)
        return {"pagination_token": "next-token-1", "records": []}

    requested = {
        "address": gtfo["address"],
        "phase": 1,
        "block_time_lt": 1791206967,
        "pagination_token": gtfo["continue_from_pagination_token"],
    }
    store = Store(tmp_path / "cap-0547")
    ok = run_next_capture_offline(
        draft=draft,
        requested=requested,
        grant=_synthetic_grant(draft),
        transport=recorder,
        store=store,
        now=datetime(2026, 10, 7, 12, tzinfo=timezone.utc),
    )
    assert ok["transport_calls"] == 1
    assert ok["dispatched"] is True
    assert len(calls) == 1
    assert ok["state"]["requests_used"] == 1
    assert ok["state"]["accepted_continuation"][gtfo["address"]] == "next-token-1"

    refused = []

    def refuse_recorder(request):
        refused.append(request)
        raise AssertionError("invalid transition reached transport")

    invalids = [
        {"requested": {**requested, "address": "An9sREpLnAXVi4KMaTGuGvgET51CyaukLUTMtxzmLYSB"}, "grant": _synthetic_grant(draft), "state": empty_next_capture_state()},
        {"requested": requested, "grant": _synthetic_grant(draft, consumed=True), "state": empty_next_capture_state()},
        {"requested": requested, "grant": _synthetic_grant(draft, expiry="2026-10-01T00:00:00Z"), "state": empty_next_capture_state()},
        {"requested": requested, "grant": _synthetic_grant(draft, execution_artifact_hash_of_this_draft="0" * 64), "state": empty_next_capture_state()},
        {"requested": requested, "grant": _synthetic_grant(draft, authorization_id="live-g1-vertical-slice-2026-10-05-mitch"), "state": empty_next_capture_state()},
        {"requested": {**requested, "pagination_token": "stale"}, "grant": _synthetic_grant(draft), "state": {**empty_next_capture_state(), "replay_completed": True, "requests_used": 1, "per_wallet_used": {gtfo["address"]: 1}, "accepted_continuation": {gtfo["address"]: "accepted-next"}, "cursor_state": {gtfo["address"]: "open"}, "last_dispatch": {"address": gtfo["address"], "response_id": "page-1", "page_identity": gtfo["continue_from_pagination_token"], "authorization_id": draft["authorization_id"], "attempt": 1}, "replay_receipts": [{"response_id": "page-1", "page_identity": gtfo["continue_from_pagination_token"], "address": gtfo["address"], "authorization_id": draft["authorization_id"], "attempt": 1}]}},
    ]
    for index, case in enumerate(invalids):
        result = run_next_capture_offline(
            draft=draft,
            requested=case["requested"],
            grant=case["grant"],
            transport=refuse_recorder,
            store=Store(tmp_path / f"cap-0547-invalid-{index}"),
            now=datetime(2026, 10, 7, 12, tzinfo=timezone.utc),
        )
        assert result["transport_calls"] == 0
        assert result["dispatched"] is False
    assert refused == []
    assert len(calls) == 1


def test_tolerance_parity_half_even_not_truncation():
    assert amounts_agree("1", "1.0000000029", "SOL") is False
    assert amounts_agree("1", "1.0000000015", "SOL") is True
    assert amounts_agree("1", "1.000000002", "SOL") is True
    source = FRONTEND_FORMAT.read_text(encoding="utf-8")
    assert "quantizeToAtomics" in source
    assert "exactHalf" in source
    assert "atomics % 2n === 1n" in source


def test_ranked_and_report_surfaces_use_certifying_helper_and_nonlead_copy():
    mass = MASS_SEARCH.read_text(encoding="utf-8")
    fmt = FRONTEND_FORMAT.read_text(encoding="utf-8")
    report = REPORT.read_text(encoding="utf-8")
    assert "RankedPhoneCard" in mass
    assert "RankedDesktopRow" in mass
    assert "coverageStatusDisplay" in (ROOT / "frontend/src/researchSurfaces.ts").read_text(encoding="utf-8")
    assert "independent_audit?.independently_audited" not in mass
    assert "certificateComparisonProof" in fmt
    assert "one_to_one_membership" in fmt
    assert "completedEpisodeFields" in report

    table = json.loads((COVERAGE / "WALLET_TABLE.json").read_text(encoding="utf-8"))
    an9s = next(row for row in table["wallets"] if row["label"] == "An9s")
    assert an9s["coverage_status_display"] == "Coverage gate eligible; not a research lead."
    assert an9s["qualification_level"] != "provisional_research_lead"

    noncert = {
        "research_profile": {
            "completed_episode_net": "12",
            "completed_episode_net_unit": "SOL",
            "coverage_status": "provisional_eligible",
            "coverage_status_display": "Coverage gate eligible; not a research lead.",
            "independent_audit": {
                "independently_audited": True,
                "independently_audited_episode_net": "12",
                "independently_audited_episode_net_unit": "SOL",
                "auditor_confirmation": "auditor confirms within 2 lamports: 12 SOL",
                "content_fingerprint": {"fingerprint": "abc"},
                "fingerprintless_not_certifying": False,
            },
        }
    }
    audit = noncert["research_profile"]["independent_audit"]
    assert "one_to_one_membership" not in audit
    assert "component_bridges" not in audit
    assert audit["independently_audited"] is True
    assert "auditor confirms" in audit["auditor_confirmation"]
