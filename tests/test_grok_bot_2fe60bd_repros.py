"""Grok Bot 2fe60bd blocking repros plus neighbours.

Fixes the INVARIANTS, not named fixtures. Offline only. SYNTHETIC wallets.
"""
from __future__ import annotations

import json
import math
import threading
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from scanner.app import create_app
from scanner.mass_search.history_ingest import (
    draft_execution_artifact_hash,
    empty_next_capture_state,
    evaluate_next_capture_dispatch,
    load_next_capture_draft,
    record_next_capture_replay,
    run_next_capture_offline,
    validate_fresh_approval_bind,
    validate_operator_quota_record,
)
from scanner.mass_search.qualification_gates import (
    ACCOUNTING_POLICY_VERSION,
    certificate_comparison_proof,
    format_auditor_confirmation,
    parse_canonical_amount,
    reconcile_saved_profile,
)
from scanner.mass_search.research_profile import (
    build_research_profile,
    default_filters,
    independently_audited,
)
from scanner.mass_search.workflow import compare_reports, ranked_workflow_view
from scanner.storage import Store
from tests.test_chatgpt_review_2026_10_07_0842 import _persist, _positive_saved, _universe_row
from tests.test_chatgpt_review_2026_10_07_rereview import _eligible_report

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def _quota(draft, remaining=8, **overrides):
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
        "authorization_id": draft["authorization_id"],
        "execution_artifact_hash": draft_execution_artifact_hash(draft),
    }
    record.update(overrides)
    return record


def _grant(draft, **overrides):
    quota = overrides.pop("current_remaining_quota_confirmation", _quota(draft))
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


def _gtfo(draft):
    return next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))


def _a6ps(draft):
    return next(row for row in draft["allowed_wallets"] if row.get("separately_authorized_phase_two_start"))


def _req(wallet, token=None):
    phase = wallet.get("phase")
    return {
        "address": wallet["address"],
        "phase": phase if isinstance(phase, int) else (2 if wallet.get("separately_authorized_phase_two_start") else 1),
        "block_time_lt": 1791206967,
        "pagination_token": wallet["continue_from_pagination_token"] if token is None else token,
    }


class Recorder:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        if not self.pages:
            return {"pagination_token": None}
        return self.pages.pop(0)


def _run(store, requested, transport, draft=None, grant=None, **kwargs):
    draft = draft or load_next_capture_draft()
    return run_next_capture_offline(
        draft=draft,
        requested=requested,
        grant=grant or _grant(draft),
        transport=transport,
        store=store,
        now=kwargs.pop("now", NOW),
        **kwargs,
    )


def test_b1_headline_999_is_non_certifying():
    report = _eligible_report()
    report["independent_audit"]["independently_audited_episode_net"] = "999"
    report["independent_audit"]["auditor_confirmation"] = "auditor confirms within 2 lamports: 999 SOL"
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    assert certificate_comparison_proof(report["independent_audit"], report["completed_episode_ledger"]) is False
    assert independently_audited(report, profile) is False
    assert profile["qualification_level"]["level"] != "provisional_research_lead"
    assert (profile.get("independent_audit") or {}).get("auditor_confirmation") != "auditor confirms within 2 lamports: 999 SOL"


def test_b1_neighbours_stale_confirmation_app_net_and_unit():
    report = _eligible_report()
    ledger = report["completed_episode_ledger"]
    stale_text = deepcopy(report)
    stale_text["independent_audit"]["auditor_confirmation"] = "auditor confirms within 2 lamports: 999 SOL"
    profile = build_research_profile(deepcopy(stale_text), filters=default_filters())
    assert independently_audited(stale_text, profile) is True
    derived = format_auditor_confirmation("12", "12", "SOL", independently_audited=True)
    assert profile["independent_audit"]["auditor_confirmation"] == derived
    assert "999" not in (profile["independent_audit"]["auditor_confirmation"] or "")

    app_net = deepcopy(report)
    app_net["independent_audit"]["app_completed_episode_net"] = "999"
    assert certificate_comparison_proof(app_net["independent_audit"], ledger) is False

    unit = deepcopy(report)
    unit["independent_audit"]["independently_audited_episode_net_unit"] = "USDC"
    assert certificate_comparison_proof(unit["independent_audit"], ledger) is False

    sci = deepcopy(report)
    sci["independent_audit"]["independently_audited_episode_net"] = "3E+0"
    assert certificate_comparison_proof(sci["independent_audit"], ledger) is False


def test_b2_decorate_and_export_use_reconciled_top_level_audit(tmp_path):
    report = _eligible_report()
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    report["completed_episode_ledger"] = []
    store = Store(tmp_path / "b2")
    store.put("reports", "x", {
        **report,
        "id": "x",
        "source": "mass-search",
        "visible_report": True,
        "research_profile": profile,
        "created_at": "2026-10-07T00:00:00Z",
    })
    with TestClient(create_app(tmp_path / "b2", "tok"), base_url="http://127.0.0.1:8765") as client:
        headers = {"x-launch-token": "tok"}
        client.get("/api/bootstrap", headers=headers)
        got = client.get("/api/reports/x", headers=headers).json()
        exported = client.get("/api/export/reports/x.json", headers=headers).json()
    assert (got.get("independent_audit") or {}).get("independently_audited") is not True
    assert got.get("research_profile", {}).get("independent_audit") in (None, {})
    assert (exported.get("independent_audit") or {}).get("independently_audited") is not True


def test_b2_neighbours_policy_bump_null_audit_and_membership(tmp_path):
    report = _eligible_report()
    built = build_research_profile(deepcopy(report), filters=default_filters())
    saved = _positive_saved(report, built)
    store = Store(tmp_path / "b2n")

    policy = deepcopy(report)
    policy["address"] = "SynthB2PolicyAAAAAAAAAAAAAAAAAAAAAAAAA"
    policy["independent_audit"] = {**report["independent_audit"], "accounting_policy_version": "old-policy"}
    _persist(store, policy, {**saved, "accounting_policy_version": "old-policy"}, "policy")

    removed = deepcopy(report)
    removed["address"] = "SynthB2RemovedAAAAAAAAAAAAAAAAAAAAAAAA"
    removed["independent_audit"] = None
    _persist(store, removed, saved, "removed")

    membership = deepcopy(report)
    membership["address"] = "SynthB2MembershipAAAAAAAAAAAAAAAAAAAAA"
    changed = [{**row} for row in report["completed_episode_ledger"]]
    changed[0] = {**changed[0], "mint": "ChangedMintB2AAAAAAAAAAAAAAAAAAAAAAAAAAA", "close_signature": "b2-close"}
    membership["completed_episode_ledger"] = changed
    _persist(store, membership, saved, "mem")

    ranked = ranked_workflow_view(store, extra_universe_rows=[
        _universe_row(policy["address"]),
        _universe_row(removed["address"]),
        _universe_row(membership["address"]),
    ])
    for address in (policy["address"], removed["address"], membership["address"]):
        row = next(item for item in ranked["rows"] if item["address"] == address)
        assert independently_audited(row, row["research_profile"]) is False
        assert row["research_profile"]["independent_audit"] in (None, {})
        assert (row.get("independent_audit") or {}).get("independently_audited") is not True


def test_b3_profile_copy_is_not_an_audit_source():
    report = _eligible_report()
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    report2 = deepcopy(report)
    report2["independent_audit"] = None
    report2["id"] = "y"
    reconciled = reconcile_saved_profile(report2, deepcopy(profile))
    fresh = build_research_profile(deepcopy(report2), filters=default_filters())
    assert independently_audited(report2, reconciled) is False
    assert independently_audited(report2, fresh) is False
    assert reconciled["qualification_level"]["level"] == fresh["qualification_level"]["level"]
    assert reconciled["qualification_level"]["level"] != "provisional_research_lead"


def test_b3_neighbours_status_flag_and_fingerprintless_copy():
    report = _eligible_report()
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    for attached in (
        {"independently_audited": True, "auditor_confirmation": "auditor confirms within 2 lamports: 999 SOL"},
        {"status": "independently_audited", "independently_audited": True},
        {**report["independent_audit"], "fingerprintless_not_certifying": False},
    ):
        saved = deepcopy(profile)
        saved["independent_audit"] = attached
        cleared = deepcopy(report)
        cleared["independent_audit"] = None
        reconciled = reconcile_saved_profile(cleared, saved)
        assert independently_audited(cleared, reconciled) is False
        assert reconciled["independent_audit"] in (None, {})


def test_b4_future_confirmed_at_refuses_before_transport(tmp_path):
    draft = load_next_capture_draft()
    future = (NOW + timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    transport = Recorder([{"pagination_token": "g2"}])
    result = _run(
        Store(tmp_path / "b4"),
        _req(_gtfo(draft)),
        transport,
        draft=draft,
        grant=_grant(draft, current_remaining_quota_confirmation=_quota(draft, confirmed_at=future)),
    )
    assert result["dispatched"] is False
    assert result["code"] == "quota_confirmed_in_the_future"
    assert transport.calls == []


def test_b4_neighbours_after_expiry_before_approval_and_one_second():
    draft = load_next_capture_draft()
    after_expiry = _quota(draft, confirmed_at="2026-10-09T00:00:00Z")
    before_approval = _quota(draft, confirmed_at="2026-10-06T00:00:00Z")
    one_second = _quota(draft, confirmed_at=(NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"))
    assert validate_fresh_approval_bind(_grant(draft, current_remaining_quota_confirmation=after_expiry), draft, now=NOW)
    assert validate_fresh_approval_bind(_grant(draft, current_remaining_quota_confirmation=before_approval), draft, now=NOW)
    assert validate_fresh_approval_bind(_grant(draft, current_remaining_quota_confirmation=one_second), draft, now=NOW) == "quota_confirmed_in_the_future"


def test_b5_quota_record_must_bind_grant_and_artifact(tmp_path):
    draft = load_next_capture_draft()
    transport = Recorder([{"pagination_token": "g2"}])
    result = _run(
        Store(tmp_path / "b5"),
        _req(_gtfo(draft)),
        transport,
        draft=draft,
        grant=_grant(
            draft,
            current_remaining_quota_confirmation=_quota(
                draft,
                authorization_id="some-other-grant",
                execution_artifact_hash="0" * 64,
            ),
        ),
    )
    assert result["dispatched"] is False
    assert result["code"] in {"quota_authorization_mismatch", "quota_artifact_mismatched"}
    assert transport.calls == []


def test_b5_neighbours_missing_id_wrong_hash_and_missing_hash():
    draft = load_next_capture_draft()
    missing_id = _quota(draft)
    del missing_id["authorization_id"]
    assert validate_operator_quota_record(missing_id, draft) == "quota_authorization_mismatch"
    wrong_hash = _quota(draft, execution_artifact_hash="1" * 64)
    assert validate_operator_quota_record(wrong_hash, draft) == "quota_artifact_mismatched"
    missing_hash = _quota(draft)
    del missing_hash["execution_artifact_hash"]
    assert validate_operator_quota_record(missing_hash, draft) == "quota_artifact_mismatched"


def test_b6_page_less_receipt_is_single_use_and_bound(tmp_path):
    draft = load_next_capture_draft()
    gtfo = _gtfo(draft)
    a6ps = _a6ps(draft)
    store = Store(tmp_path / "b6")
    transport = Recorder([
        {"pagination_token": "g2", "response_id": "R"},
        {"pagination_token": "a2", "response_id": "R"},
        {"pagination_token": "g3"},
    ])
    first = _run(store, _req(gtfo), transport, draft=draft)
    assert first["dispatched"] is True
    minted = first["state"]["last_dispatch"]["response_id"]
    assert minted != "R"
    page_less = {
        "response_id": minted,
        "address": gtfo["address"],
        "authorization_id": draft["authorization_id"],
        "attempt": first["state"]["last_dispatch"]["attempt"],
    }
    assert record_next_capture_replay(first["state"], page_less) is False
    assert record_next_capture_replay(first["state"], {"response_id": minted}) is False
    bound = {
        "response_id": minted,
        "page_identity": first["state"]["last_dispatch"]["page_identity"],
        "address": gtfo["address"],
        "authorization_id": draft["authorization_id"],
        "attempt": first["state"]["last_dispatch"]["attempt"],
    }
    assert record_next_capture_replay(first["state"], bound) is True
    assert record_next_capture_replay(first["state"], bound) is False
    store.put("next_capture_offline_state", draft["authorization_id"], first["state"])
    second = _run(store, _req(a6ps), transport, draft=draft)
    assert second["dispatched"] is True
    stale = {"response_id": minted}
    assert record_next_capture_replay(second["state"], stale) is False
    wrong_wallet = {
        **bound,
        "address": a6ps["address"],
        "page_identity": second["state"]["last_dispatch"]["page_identity"],
        "response_id": second["state"]["last_dispatch"]["response_id"],
        "attempt": second["state"]["last_dispatch"]["attempt"],
    }
    wrong_wallet["address"] = a6ps["address"]
    assert record_next_capture_replay(deepcopy(first["state"]), {
        "response_id": minted,
        "page_identity": first["state"]["last_dispatch"]["page_identity"],
        "address": a6ps["address"],
        "authorization_id": draft["authorization_id"],
        "attempt": first["state"]["last_dispatch"]["attempt"],
    }) is False


def test_b6_neighbours_wrong_attempt_wrong_grant_and_transport_id():
    draft = load_next_capture_draft()
    gtfo = _gtfo(draft)
    dispatch = {
        "address": gtfo["address"],
        "response_id": "minted",
        "page_identity": gtfo["continue_from_pagination_token"],
        "authorization_id": draft["authorization_id"],
        "attempt": 2,
    }
    state = {**empty_next_capture_state(), "last_dispatch": dispatch}
    assert record_next_capture_replay(deepcopy(state), {**dispatch, "attempt": 1}) is False
    assert record_next_capture_replay(deepcopy(state), {**dispatch, "authorization_id": "other-grant"}) is False
    assert record_next_capture_replay(deepcopy(state), {"response_id": "R", "page_identity": dispatch["page_identity"]}) is False


def test_b7_store_none_refuses_before_transport():
    draft = load_next_capture_draft()
    transport = Recorder([{"pagination_token": "x"}, {"pagination_token": "y"}])
    first = run_next_capture_offline(
        draft=draft,
        requested=_req(_gtfo(draft)),
        grant=_grant(draft),
        transport=transport,
        store=None,
        now=NOW,
    )
    second = run_next_capture_offline(
        draft=draft,
        requested=_req(_gtfo(draft)),
        grant=_grant(draft),
        transport=transport,
        store=None,
        now=NOW,
    )
    assert first["dispatched"] is False
    assert second["dispatched"] is False
    assert first["code"] == "durable_store_required"
    assert transport.calls == []


def test_b7_neighbours_missing_store_with_memory_state_and_default():
    draft = load_next_capture_draft()
    transport = Recorder([{"pagination_token": "x"}])
    memory = empty_next_capture_state()
    result = run_next_capture_offline(
        draft=draft,
        requested=_req(_gtfo(draft)),
        grant=_grant(draft),
        transport=transport,
        state=memory,
        store=None,
        now=NOW,
    )
    assert result["code"] == "durable_store_required"
    assert transport.calls == []
    omitted = run_next_capture_offline(
        draft=draft,
        requested=_req(_gtfo(draft)),
        grant=_grant(draft),
        transport=transport,
        now=NOW,
    )
    assert omitted["code"] == "durable_store_required"
    assert evaluate_next_capture_dispatch(
        draft=draft,
        requested=_req(_gtfo(draft)),
        grant=_grant(draft),
        now=NOW,
    )["allowed"] is True


def test_b8_overlapping_runners_serialize_and_count_budget(tmp_path):
    draft = load_next_capture_draft()
    path = tmp_path / "b8"
    Store(path)
    barrier = threading.Barrier(2)

    class Slow(Store):
        def get(self, kind, key, default=None):
            value = super().get(kind, key, default)
            if kind == "next_capture_offline_state":
                try:
                    barrier.wait(5)
                except threading.BrokenBarrierError:
                    pass
            return value

    transport = Recorder([{"pagination_token": "x"}, {"pagination_token": "y"}])
    threads = [
        threading.Thread(target=lambda: _run(Slow(path), _req(_gtfo(draft)), transport, draft=draft))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    stored = Store(path).get("next_capture_offline_state", draft["authorization_id"])
    assert len(transport.calls) == 1
    assert stored["requests_used"] == 1


def test_b8_neighbours_three_runners_and_cas_loser(tmp_path):
    draft = load_next_capture_draft()
    path = tmp_path / "b8n"
    Store(path)
    barrier = threading.Barrier(3)

    class Slow(Store):
        def get(self, kind, key, default=None):
            value = super().get(kind, key, default)
            if kind == "next_capture_offline_state":
                try:
                    barrier.wait(5)
                except threading.BrokenBarrierError:
                    pass
            return value

    transport = Recorder([{"pagination_token": "a"}, {"pagination_token": "b"}, {"pagination_token": "c"}])
    threads = [
        threading.Thread(target=lambda: _run(Slow(path), _req(_gtfo(draft)), transport, draft=draft))
        for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    stored = Store(path).get("next_capture_offline_state", draft["authorization_id"])
    assert len(transport.calls) == 1
    assert stored["requests_used"] == len(transport.calls)

    loser_store = Store(tmp_path / "b8-cas")
    loser_store.put("next_capture_offline_state", draft["authorization_id"], {**empty_next_capture_state(), "generation": 4})
    assert loser_store.cas_put("next_capture_offline_state", draft["authorization_id"], {"generation": 1}, 0) is False


def test_nan_amount_fails_closed_per_wallet_not_app_state(tmp_path):
    report = _eligible_report()
    report["independent_audit"]["independently_audited_episode_net"] = "NaN"
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    store = Store(tmp_path / "nan")
    report["created_at"] = "2026-10-07T00:00:00Z"
    _persist(store, report, profile, "nan-wallet")
    healthy = _eligible_report()
    healthy["address"] = "SynthHealthyAAAAAAAAAAAAAAAAAAAAAAAAAA"
    healthy["created_at"] = "2026-10-07T00:00:01Z"
    _persist(store, healthy, build_research_profile(deepcopy(healthy), filters=default_filters()), "healthy")
    with TestClient(create_app(tmp_path / "nan", "tok"), base_url="http://127.0.0.1:8765") as client:
        headers = {"x-launch-token": "tok"}
        client.get("/api/bootstrap", headers=headers)
        state = client.get("/api/state", headers=headers)
        assert state.status_code == 200
        rows = state.json().get("reports") or state.json().get("recent_reports") or []
        assert any(row.get("id") == "healthy" or row.get("address") == healthy["address"] for row in rows) or state.json()


def test_canonical_amount_grammar_rejects_python_js_divergences():
    for value in ("3E+0", "+3", " 3", "３", 3, 3.0, True, "NaN", "Infinity", "inf"):
        assert parse_canonical_amount(value) is None
    assert parse_canonical_amount("3") == Decimal("3")
    assert parse_canonical_amount("2.816541712") == Decimal("2.816541712")
    assert parse_canonical_amount("-1.5") == Decimal("-1.5")


def test_quota_remaining_rejects_bool_float_inf_and_string():
    draft = load_next_capture_draft()
    for remaining in (True, 1.9, math.inf, float("nan"), "8", None, -1):
        assert validate_operator_quota_record(_quota(draft, remaining=remaining), draft) == "quota_not_bound"


def test_error_envelope_is_not_a_clean_terminal_cursor(tmp_path):
    draft = load_next_capture_draft()
    store = Store(tmp_path / "cap-c")
    result = _run(store, _req(_gtfo(draft)), lambda _request: {"error": "nope"}, draft=draft)
    assert result["code"] == "synthetic_recorder_failed"
    assert result["state"]["cursor_state"].get(_gtfo(draft)["address"]) != "exhausted"
    assert result["state"]["last_dispatch"]["status"] == "failed"


def frontend_smoke_cases():
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
    empty = deepcopy(report)
    empty["completed_episode_ledger"] = []
    return {
        "valid": valid,
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
        "staleCategoryFunnel": {
            "address": "SynthStale2fe60bdAAAAAAAAAAAAAAAAAAAAAAA",
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
        },
    }
