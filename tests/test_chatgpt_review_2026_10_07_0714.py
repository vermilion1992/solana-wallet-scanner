"""Closures for the 2026-10-07 07:14 re-review of PR #6 tip 5cd05b7.

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
    EXHAUSTED_CURSOR,
    draft_execution_artifact_hash,
    empty_next_capture_state,
    evaluate_next_capture_dispatch,
    load_next_capture_draft,
    persist_next_capture_state,
    record_next_capture_replay,
    run_next_capture_offline,
    validate_fresh_approval_bind,
)
from scanner.mass_search.qualification_gates import (
    amounts_agree,
    bindable_independent_audit,
    certificate_comparison_proof,
    component_bridge,
    compute_audit_fingerprint,
    validate_episode_ledger,
)
from scanner.mass_search.research_profile import (
    build_research_profile,
    default_filters,
    independently_audited,
)
from scanner.mass_search.workflow import compare_reports, ranked_workflow_view
from scanner.storage import Store
from tests.test_chatgpt_review_2026_10_07_rereview import _eligible_report

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_FORMAT = ROOT / "frontend/src/format.ts"
MASS_SEARCH = ROOT / "frontend/src/MassSearch.tsx"
COVERAGE = ROOT / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage"
DRAFT = ROOT / "config/live_authorization.ranked100-depth-biased-next-capture-draft.json"
SCRIPT = ROOT / "frontend/scripts/assert-rereview-0714.mts"


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


def _gtfo_progress(response_id="gtfo-page-1", page_identity=None):
    return {
        "response_id": response_id,
        "page_identity": page_identity,
        "named_dependency_observations": [{
            "signature": "5m3vQ8YP8mNzVsg2ZiUaEBnW3H3FrSTZr4qPk9mPLnTHnEXWZzWNcvA1HK1X4dxLqwAQBdpM6wrp7df4u8fe9bKU",
            "unresolved_basis_cleared": True,
            "result": "named_sale_or_lot_unresolved_basis_cleared",
        }],
    }


def _surface_source(report):
    profile = report.get("research_profile") or {}
    return {
        "completed_episode_ledger": report.get("completed_episode_ledger") or profile.get("completed_episode_ledger"),
        "independent_audit": report.get("independent_audit") or profile.get("independent_audit"),
        "research_profile": profile,
        "funnel": {"B": {
            "scoped_pnl": profile.get("scoped_pnl") or profile.get("completed_episode_net"),
            "scoped_pnl_unit": profile.get("scoped_pnl_unit") or profile.get("completed_episode_net_unit"),
            "completed_known_cost_positions": profile.get("completed_known_cost_positions"),
        }},
    }


def _mutate_stale_flags(report, kind):
    mutated = deepcopy(report)
    audit = mutated["independent_audit"]
    ledger = mutated["completed_episode_ledger"]
    if kind == "duplicate":
        first = deepcopy(audit["component_bridges"][0])
        audit["component_bridges"] = [deepcopy(first) for _ in ledger]
        audit["episodes"] = [deepcopy(audit["episodes"][0]) for _ in ledger]
        audit["one_to_one_membership"] = True
    elif kind == "removedAmounts":
        for bridge in audit["component_bridges"]:
            comps = dict(bridge["components"])
            comps["acquisition"] = {**comps["acquisition"], "app": None, "auditor": None, "agree": True}
            bridge["components"] = comps
            bridge["agree"] = True
        audit["episodes"] = [
            {**episode, "component_bridge": audit["component_bridges"][index]}
            for index, episode in enumerate(audit["episodes"])
        ]
    elif kind == "alteredClose":
        bridge = dict(audit["component_bridges"][0])
        membership = dict(bridge["membership"])
        auditor = dict(membership["auditor"])
        auditor["close_signature"] = "stale-auditor-close"
        membership["auditor"] = auditor
        membership["agree"] = True
        membership["one_to_one"] = True
        bridge["membership"] = membership
        bridge["agree"] = True
        audit["component_bridges"][0] = bridge
        audit["episodes"][0]["component_bridge"] = bridge
    mutated["research_profile"] = {
        **(mutated.get("research_profile") or {}),
        "completed_episode_ledger": ledger,
        "audit_fingerprint": audit.get("content_fingerprint"),
        "independent_audit": audit,
        "completed_episode_net": mutated.get("completed_episode_net"),
        "completed_episode_net_unit": mutated.get("completed_episode_net_unit"),
        "completed_known_cost_positions": len(ledger),
        "scoped_pnl": mutated.get("completed_episode_net"),
        "scoped_pnl_unit": mutated.get("completed_episode_net_unit"),
        "ledger_summary_contradiction": False,
    }
    return mutated


def test_stale_positive_flag_comparisons_do_not_certify():
    report = _eligible_report()
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    assert independently_audited(report, profile) is True
    assert certificate_comparison_proof(report["independent_audit"], report["completed_episode_ledger"]) is True

    for kind in ("duplicate", "removedAmounts", "alteredClose"):
        mutated = _mutate_stale_flags(report, kind)
        assert certificate_comparison_proof(
            mutated["independent_audit"],
            mutated["completed_episode_ledger"],
        ) is False, kind
        mutated_profile = build_research_profile(deepcopy(mutated), filters=default_filters())
        assert independently_audited(mutated, mutated_profile) is False, kind
        assert bindable_independent_audit(
            mutated["independent_audit"],
            mutated_profile["audit_fingerprint"],
            mutated["completed_episode_ledger"],
        ) is None, kind


def test_missing_close_signature_is_rejected():
    report = _eligible_report()
    missing = [{k: v for k, v in row.items() if k != "close_signature"} for row in report["completed_episode_ledger"]]
    judged = validate_episode_ledger(missing)
    assert judged["ok"] is False
    assert judged["reason"] == "missing_close_signature"


def _persist_saved(store, report, profile, report_id="saved-0714"):
    payload = {
        **report,
        "id": report_id,
        "source": "mass-search",
        "visible_report": True,
        "research_profile": profile,
        "window": report.get("window") or {"start": "2026-09-05T13:29:27Z", "end": "2026-10-05T13:29:27Z"},
    }
    store.put("reports", report_id, payload)
    return payload


def _synthetic_universe_row(address):
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


def _assert_ranked_row(store, report, *, net, lead=False, audited=False):
    ranked = ranked_workflow_view(store, extra_universe_rows=[_synthetic_universe_row(report["address"])])
    row = next(item for item in ranked["rows"] if item["address"] == report["address"])
    profile = row["research_profile"]
    if net is None:
        assert profile["completed_episode_net"] in (None, )
    else:
        assert Decimal(str(profile["completed_episode_net"])) == Decimal(str(net))
    level = profile.get("qualification_level") or {}
    level_name = level.get("level") if isinstance(level, dict) else level
    if lead:
        assert level_name in ("provisional_research_lead", "stronger_research_shortlist")
    else:
        assert level_name not in ("provisional_research_lead", "stronger_research_shortlist")
    assert independently_audited(report, profile) is audited
    compared = compare_reports(store, report["id"], report["id"])
    assert compared["window_policy"]["left_independently_audited"] is audited
    if net is None:
        assert compared["window_policy"]["left_completed_episode_net"] in (None, )
    else:
        assert Decimal(str(compared["window_policy"]["left_completed_episode_net"])) == Decimal(str(net))
    return row, ranked


def test_reconcile_invalidates_stale_lead_and_audit_on_ranked_row(tmp_path):
    report = _eligible_report()
    built = build_research_profile(deepcopy(report), filters=default_filters())
    assert built["qualification_level"]["level"] == "provisional_research_lead"
    store = Store(tmp_path / "gap2")

    negative = deepcopy(report)
    negative["completed_episode_ledger"] = [{**row, "net": "-3"} for row in report["completed_episode_ledger"]]
    saved = {
        **built,
        "completed_episode_net": "12",
        "completed_episode_net_vector": {"SOL": "12"},
        "completed_known_cost_positions": 4,
        "qualification_level": {"level": "provisional_research_lead", "label": "provisional research lead"},
        "independent_audit": report["independent_audit"],
        "audit_fingerprint": built["audit_fingerprint"],
        "threshold_results": {"min_completed_known_cost": {"state": "PASS", "passed": True, "applied": True}},
        "criteria_met": True,
        "thresholds": {"min_completed_known_cost": "3", "min_scoped_pnl_sol": "0"},
    }
    persisted = _persist_saved(store, negative, saved, "saved-neg")
    row, _ranked = _assert_ranked_row(store, persisted, net="-12", lead=False, audited=False)
    assert row["research_profile"]["ledger_summary_contradiction"] is True
    assert row["research_profile"]["criteria_met"] is False
    assert row["qualification_level"]["level"] != "provisional_research_lead"

    empty = deepcopy(report)
    empty["completed_episode_ledger"] = []
    empty_profile = {
        **saved,
        "completed_episode_ledger": [],
        "completed_episode_net": "88",
        "completed_known_cost_positions": 4,
    }
    empty["address"] = "SynthEmptyLedger0714AAAAAAAAAAAAAAAAAAAA"
    persisted_empty = _persist_saved(store, empty, empty_profile, "saved-empty")
    empty_row, _ = _assert_ranked_row(store, persisted_empty, net=None, lead=False, audited=False)
    assert empty_row["research_profile"]["completed_known_cost_positions"] == 0
    assert empty_row["research_profile"]["threshold_results"]["min_completed_known_cost"]["passed"] is False

    membership = deepcopy(report)
    changed = [{**row} for row in report["completed_episode_ledger"]]
    changed[0] = {**changed[0], "mint": "ChangedMint0714AAAAAAAAAAAAAAAAAAAAAAAAA", "close_signature": "changed-close-0"}
    membership["completed_episode_ledger"] = changed
    membership["address"] = "SynthMembership0714AAAAAAAAAAAAAAAAAA"
    same_profile = {
        **saved,
        "completed_episode_net": "12",
        "completed_known_cost_positions": 4,
        "audit_fingerprint": built["audit_fingerprint"],
        "independent_audit": report["independent_audit"],
        "qualification_level": {"level": "provisional_research_lead", "label": "provisional research lead"},
    }
    persisted_mem = _persist_saved(store, membership, same_profile, "saved-mem")
    mem_row, _ = _assert_ranked_row(store, persisted_mem, net="12", lead=False, audited=False)
    assert mem_row["research_profile"]["audit_fingerprint"]["fingerprint"] != built["audit_fingerprint"]["fingerprint"]
    assert mem_row["research_profile"]["independent_audit"] in (None, {})


def test_fresh_approval_requires_quota_record_and_approval_relationship():
    draft = load_next_capture_draft()
    now = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
    assert validate_fresh_approval_bind(_synthetic_grant(draft), draft, now=now) is None
    assert validate_fresh_approval_bind(
        _synthetic_grant(draft, current_remaining_quota_confirmation="quota-confirmed-offline"),
        draft,
        now=now,
    ) == "quota_not_bound"
    assert validate_fresh_approval_bind(
        _synthetic_grant(draft, current_remaining_quota_confirmation={**_quota_record(), "reserved_unallocated": 0}),
        draft,
        now=now,
    ) == "reserved_is_discretionary"
    assert validate_fresh_approval_bind(
        _synthetic_grant(draft, approval_timestamp="2026-10-09T00:00:00Z"),
        draft,
        now=now,
    ) == "approval_not_before_expiry"


def test_failed_timeout_consumes_attempt_across_reopen(tmp_path):
    draft = load_next_capture_draft()
    assert draft["enabled"] is False
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    store = Store(tmp_path / "capture")
    requested = {
        "address": gtfo["address"],
        "phase": 1,
        "block_time_lt": 1791206967,
        "pagination_token": gtfo["continue_from_pagination_token"],
    }

    def timeout(_request):
        raise TimeoutError("synthetic recorder timeout")

    first = run_next_capture_offline(
        draft=draft,
        requested=requested,
        grant=_synthetic_grant(draft),
        transport=timeout,
        store=store,
        now=datetime(2026, 10, 7, 12, tzinfo=timezone.utc),
    )
    assert first["attempt_consumed"] is True
    assert first["state"]["requests_used"] == 1
    assert first["state"]["attempts"][0]["status"] == "failed"

    reopened = Store(tmp_path / "capture")
    second = run_next_capture_offline(
        draft=draft,
        requested=requested,
        grant=_synthetic_grant(draft),
        transport=lambda _request: (_ for _ in ()).throw(AssertionError("unused retry reached transport")),
        store=reopened,
        now=datetime(2026, 10, 7, 12, tzinfo=timezone.utc),
    )
    assert second["dispatched"] is False
    assert second["code"] == "second_before_replay"
    assert second["state"]["requests_used"] == 1


def test_replay_is_bound_to_last_response_and_terminal_cursor_refuses(tmp_path):
    draft = load_next_capture_draft()
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    a6ps = next(row for row in draft["allowed_wallets"] if row.get("separately_authorized_phase_two_start"))
    store = Store(tmp_path / "replay")
    empty_flag = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": a6ps["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": a6ps["continue_from_pagination_token"]},
        replay_completed=True,
    )
    assert empty_flag["allowed"] is False
    assert empty_flag["code"] == "non_gtfo_initial"

    def page(token):
        def recorder(_request):
            return {"pagination_token": token, "response_id": f"resp-{token or 'end'}"}
        return recorder

    first = run_next_capture_offline(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": gtfo["continue_from_pagination_token"]},
        grant=_synthetic_grant(draft),
        transport=page("next-1"),
        store=store,
        now=datetime(2026, 10, 7, 12, tzinfo=timezone.utc),
    )
    assert first["dispatched"] is True
    response_id = first["response_id"]
    assert record_next_capture_replay(first["state"], {"response_id": "other", "page_identity": gtfo["continue_from_pagination_token"]}) is False
    assert record_next_capture_replay(first["state"], {"response_id": response_id, "page_identity": gtfo["continue_from_pagination_token"]}) is True
    persist_next_capture_state(store, draft, first["state"])

    a6ps_ok = run_next_capture_offline(
        draft=draft,
        requested={"address": a6ps["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": a6ps["continue_from_pagination_token"]},
        grant=_synthetic_grant(draft),
        transport=page(None),
        store=store,
        now=datetime(2026, 10, 7, 12, tzinfo=timezone.utc),
    )
    assert a6ps_ok["dispatched"] is True
    assert a6ps_ok["state"]["cursor_state"][a6ps["address"]] == "exhausted"
    assert a6ps_ok["state"]["accepted_continuation"][a6ps["address"]] == EXHAUSTED_CURSOR
    assert a6ps_ok["state"]["last_dispatch"]["response_id"] != response_id
    stale = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": a6ps["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": a6ps["continue_from_pagination_token"]},
        last_dispatch={"address": gtfo["address"], "response_id": response_id, "page_identity": gtfo["continue_from_pagination_token"], "authorization_id": draft["authorization_id"], "attempt": 1},
        replay_receipts=[{"response_id": response_id, "page_identity": gtfo["continue_from_pagination_token"], "address": gtfo["address"], "authorization_id": draft["authorization_id"], "attempt": 1}],
        requests_used=2,
        per_wallet_used={gtfo["address"]: 1, a6ps["address"]: 1},
        accepted_continuation={**a6ps_ok["state"]["accepted_continuation"]},
        cursor_state=a6ps_ok["state"]["cursor_state"],
    )
    assert stale["code"] == "cursor_exhausted"
    assert record_next_capture_replay(a6ps_ok["state"], {"response_id": a6ps_ok["response_id"], "page_identity": a6ps["continue_from_pagination_token"]}) is True
    refused = run_next_capture_offline(
        draft=draft,
        requested={"address": a6ps["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": a6ps["continue_from_pagination_token"]},
        grant=_synthetic_grant(draft),
        transport=lambda _request: (_ for _ in ()).throw(AssertionError("exhausted wallet reached transport")),
        store=store,
        state=a6ps_ok["state"],
        now=datetime(2026, 10, 7, 12, tzinfo=timezone.utc),
    )
    assert refused["dispatched"] is False
    assert refused["code"] == "cursor_exhausted"


def test_committed_draft_page_bound_replay_allows_cccs_and_rejects_stale():
    draft = load_next_capture_draft()
    assert draft["enabled"] is False
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    cccs = next(row for row in draft["allowed_wallets"] if row["address"].startswith("CccS"))
    assert gtfo["named_dependency_items"]
    assert cccs["shares_global_phase_two_progress_rule"] is True
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
    allowed = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": cccs["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": cccs["continue_from_pagination_token"]},
        previous_progress=_gtfo_progress(),
        requests_used=1,
        per_wallet_used={gtfo["address"]: 1},
        **replay,
    )
    assert allowed["allowed"] is True
    unrelated = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": cccs["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": cccs["continue_from_pagination_token"]},
        previous_progress={"named_dependency_observations": [{
            "signature": "unrelated-sale",
            "unresolved_basis_cleared": True,
            "result": "named_sale_or_lot_unresolved_basis_cleared",
        }]},
        requests_used=1,
        per_wallet_used={gtfo["address"]: 1},
        **replay,
    )
    assert unrelated["code"] == "named_dependency_not_approached"
    stale = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": cccs["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": cccs["continue_from_pagination_token"]},
        previous_progress=_gtfo_progress(),
        requests_used=1,
        per_wallet_used={gtfo["address"]: 1},
        last_dispatch={"address": gtfo["address"], "response_id": "newer-page", "page_identity": "accepted-next", "authorization_id": draft["authorization_id"], "attempt": 2},
        replay_receipts=[{"response_id": "gtfo-page-1", "page_identity": gtfo["continue_from_pagination_token"], "address": gtfo["address"], "authorization_id": draft["authorization_id"], "attempt": 1}],
    )
    assert stale["code"] == "second_before_replay"
    pw58 = next(row for row in draft["allowed_wallets"] if row["address"].startswith("58PW"))
    assert pw58["executable_allowance"] == 0
    assert pw58["named_dependency_items"] == []


def test_javascript_half_even_and_surface_rendering(tmp_path):
    report = _eligible_report()
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    report["research_profile"] = profile
    table = json.loads((COVERAGE / "WALLET_TABLE.json").read_text(encoding="utf-8"))
    audit_payload = json.loads((COVERAGE / "INDEPENDENT_AUDIT.json").read_text(encoding="utf-8"))
    an9s_table = next(row for row in table["wallets"] if row["label"] == "An9s")
    an9s_audit = next(row for row in audit_payload["wallets"] if row["address"] == an9s_table["address"])
    an9s = {
        "completed_episode_ledger": [
            {
                "mint": episode.get("mint"),
                "close_signature": episode.get("close_signature"),
            }
            for episode in (an9s_audit.get("episodes") or [])
        ],
        "independent_audit": an9s_audit,
        "research_profile": {
            "completed_episode_net": an9s_table["completed_episode_net"],
            "completed_episode_net_unit": an9s_table["completed_episode_net_unit"],
            "completed_known_cost_positions": an9s_table["completed"],
            "scoped_pnl": an9s_table["scoped_pnl"] or an9s_table["worksheet_total"],
            "scoped_pnl_unit": an9s_table["scoped_pnl_unit"] or an9s_table["worksheet_total_unit"],
            "coverage_status": an9s_table["coverage_status"],
            "coverage_status_display": an9s_table["coverage_status_display"],
            "qualification_level": {"level": an9s_table["qualification_level"]},
            "audit_fingerprint": an9s_audit.get("content_fingerprint"),
            "completed_episode_ledger": [
                {"mint": episode.get("mint"), "close_signature": episode.get("close_signature")}
                for episode in (an9s_audit.get("episodes") or [])
            ],
            "independent_audit": an9s_audit,
            "ledger_summary_contradiction": False,
        },
        "funnel": {"B": {
            "scoped_pnl": an9s_table["scoped_pnl"] or an9s_table["worksheet_total"],
            "scoped_pnl_unit": an9s_table["scoped_pnl_unit"] or an9s_table["worksheet_total_unit"],
            "completed_known_cost_positions": an9s_table["completed"],
        }},
    }
    payload = {
        "valid": _surface_source(report),
        "an9s": an9s,
        "duplicate": _surface_source(_mutate_stale_flags(report, "duplicate")),
        "removedAmounts": _surface_source(_mutate_stale_flags(report, "removedAmounts")),
        "alteredClose": _surface_source(_mutate_stale_flags(report, "alteredClose")),
    }
    cases_path = tmp_path / "0714-cases.json"
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
    assert body["half_even"] is True
    mass = MASS_SEARCH.read_text(encoding="utf-8")
    assert " · qualified ${count(ranked.research_screen.counts?.completed_qualified" not in mass
    assert "sample/activity filter matches" in mass
    assert "not certified research leads" in MASS_SEARCH.read_text(encoding="utf-8")
    assert "certified_research_wallet" not in MASS_SEARCH.read_text(encoding="utf-8")
    assert amounts_agree("1", "1.0000000029", "SOL") is False
    draft = json.loads(DRAFT.read_text(encoding="utf-8"))
    assert draft["enabled"] is False
    assert draft["PRODUCT_READY"] is False
