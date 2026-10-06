"""Negative regressions for the 2026-10-07 03:46 re-review of PR #6.

Every constructed wallet is SYNTHETIC and must never count as a genuine
research wallet. Zero live provider calls.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from scanner.investigation import (
    infer_token_2022_fee_bps,
    infer_token_2022_fee_bps_candidates,
    token_2022_ceiling_fee,
)
from scanner.mass_search.history_ingest import (
    evaluate_next_capture_dispatch,
    load_next_capture_draft,
    named_dependency_progress,
    serialize_box_driver_next_capture_first_request,
)
from scanner.mass_search.qualification_gates import (
    ACCOUNTING_POLICY_VERSION,
    SENSITIVITY_NOT_ESTABLISHED,
    aggregate_rounding_bridge,
    component_bridge,
    compute_audit_fingerprint,
    exposure_outside_completed_episodes,
    format_auditor_confirmation,
    hold_time_stats,
    is_synthetic_case,
    mark_synthetic,
    match_auditor_episode,
    requested_history_interval,
)
from scanner.mass_search.research_profile import (
    build_research_profile,
    default_filters,
    independently_audited,
    qualification_level,
)


def _coverage():
    return {"unsupported_swap_share_in_window": {"by_count": "0", "by_consideration": {"SOL": "0"}}}


def _eligible_report():
    day0 = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)
    ledger = []
    events = []
    for index in range(4):
        mint = f"EligMint{index}111111111111111111111111111"
        opened = int(day0.timestamp()) + index * 86400
        closed = opened + 3600
        ledger.append({
            "net": "3",
            "mint": mint,
            "unit": "SOL",
            "day": datetime.fromtimestamp(closed, tz=timezone.utc).date().isoformat(),
            "opened_at": opened,
            "closed_at": closed,
            "close_signature": f"elig-close-{index}",
            "acquisition": "1",
            "proceeds": "4.1",
            "costs": "0.1",
        })
        events.append({
            "kind": "buy", "mint": mint, "units": "1", "signature": f"elig-buy-{index}",
            "timestamp": opened, "consideration_sol": "1",
        })
        events.append({
            "kind": "sell", "mint": mint, "units": "1", "signature": f"elig-close-{index}",
            "timestamp": closed, "consideration_sol": "4.1",
        })
    report = mark_synthetic({
        "address": "SynthEligibleFingerprinted1111111111111111",
        "events": events,
        "wallet_completed_episodes": 4,
        "completed_episode_ledger": ledger,
        "completed_episode_net": "12",
        "completed_episode_net_unit": "SOL",
        "sensitivity_unverified_debits_sol": "0",
        "record_breakdown": _coverage(),
        "worksheet": {"total_profit_sol": "12", "settlement_asset": "SOL", "unresolved_basis_sales": 0},
        "window": {"start": "2026-09-05T13:29:27Z", "end": "2026-10-05T13:29:27Z"},
        "capture_sha256": "elig-capture-aaa",
        "corpus_kind": "GENUINE_REPLAY",
        "label": "SYNTHETIC — eligible fingerprinted fixture, not a genuine research wallet",
    }, reason="eligible fingerprinted fixture for one-at-a-time mutations")
    fingerprint = compute_audit_fingerprint(report, episodes=ledger)
    episodes = []
    for row in ledger:
        auditor = {
            "mint": row["mint"],
            "close_signature": row["close_signature"],
            "acquisition": row["acquisition"],
            "proceeds": row["proceeds"],
            "costs": row["costs"],
            "net": row["net"],
        }
        episodes.append({
            "mint": row["mint"],
            "close_signature": row["close_signature"],
            "component_bridge": component_bridge(row, auditor, row.get("unit") or "SOL"),
        })
    report["independent_audit"] = {
        "status": "independently_audited",
        "independently_audited": True,
        "independently_audited_episode_net": "12",
        "independently_audited_episode_net_unit": "SOL",
        "app_completed_episode_net": "12",
        "app_completed_episode_net_unit": "SOL",
        "content_fingerprint": fingerprint,
        "accounting_policy_version": ACCOUNTING_POLICY_VERSION,
        "one_to_one_membership": True,
        "episodes": episodes,
        "component_bridges": [item["component_bridge"] for item in episodes],
    }
    return report


def test_eligible_fingerprinted_fixture_can_qualify_machinery_but_is_not_genuine():
    report = _eligible_report()
    profile = build_research_profile(report, filters=default_filters())
    assert independently_audited(report, profile) is True
    assert profile["qualification_level"]["level"] == "provisional_research_lead"
    assert is_synthetic_case(report, profile) is True
    assert profile["not_a_genuine_research_wallet"] is True


def test_fingerprintless_audit_does_not_certify_genuine_path():
    report = _eligible_report()
    report["independent_audit"] = {
        "status": "independently_audited",
        "independently_audited": True,
        "app_completed_episode_net": "999",
    }
    profile = build_research_profile(report, filters=default_filters())
    assert independently_audited(report, profile) is False
    assert profile["qualification_level"]["level"] != "provisional_research_lead"
    assert profile["not_a_genuine_research_wallet"] is True


def test_mismatched_fingerprint_detaches_audit():
    report = _eligible_report()
    audit = dict(report["independent_audit"])
    stored = dict(audit["content_fingerprint"])
    stored["fingerprint"] = "0" * 64
    audit["content_fingerprint"] = stored
    report["independent_audit"] = audit
    profile = build_research_profile(report, filters=default_filters())
    assert independently_audited(report, profile) is False
    assert profile["qualification_level"]["independently_audited"] is False
    assert profile["qualification_level"]["level"] != "provisional_research_lead"


def test_negative_ledger_positive_summary_does_not_qualify():
    report = _eligible_report()
    report["completed_episode_ledger"] = [
        {**row, "net": "-3"} for row in report["completed_episode_ledger"]
    ]
    report["completed_episode_net"] = "99"
    report["wallet_completed_episodes"] = 20
    fingerprint = compute_audit_fingerprint(report, episodes=report["completed_episode_ledger"])
    report["independent_audit"]["content_fingerprint"] = fingerprint
    report["independent_audit"]["app_completed_episode_net"] = "99"
    profile = build_research_profile(report, filters=default_filters())
    assert Decimal(str(profile["completed_episode_net"])) == Decimal("-12")
    assert profile["completed_known_cost_positions"] == 4
    assert profile["ledger_summary_contradiction"] is True
    assert independently_audited(report, profile) is False
    judged = qualification_level(report, profile)
    assert judged["level"] != "provisional_research_lead"
    assert judged["positive_completed_episode_net"] is False


def test_missing_sol_sensitivity_blocks_lead():
    report = _eligible_report()
    del report["sensitivity_unverified_debits_sol"]
    profile = build_research_profile(report, filters=default_filters())
    assert profile["qualification_level"]["sensitivity_sign_flip"] == SENSITIVITY_NOT_ESTABLISHED
    assert profile["qualification_level"]["level"] != "provisional_research_lead"
    assert profile["sensitivity_evidence_state"] == "not_established"


def test_component_bridge_requires_exact_membership_and_present_components():
    app = {"mint": "M1", "close_signature": "close-a", "acquisition": "1", "proceeds": "2", "costs": "0.1", "net": "0.9"}
    other = {"mint": "M1", "close_signature": "close-b", "acquisition": "1", "proceeds": "2", "costs": "0.1", "net": "0.9"}
    same_mint = component_bridge(app, other, "SOL")
    assert same_mint["membership"]["agree"] is False
    assert same_mint["membership"]["mint_only_fallback"] is False
    assert same_mint["agree"] is False
    missing = component_bridge(
        {"mint": "M1", "close_signature": "close-a", "net": "0.9"},
        {"mint": "M1", "close_signature": "close-a", "net": "0.9"},
        "SOL",
    )
    assert missing["agree"] is False
    assert missing["components"]["acquisition"]["agree"] is False
    used = set()
    first = match_auditor_episode(app, [other, app], used=used)
    assert first["close_signature"] == "close-a"
    second = match_auditor_episode({"mint": "M1", "close_signature": "close-a"}, [other, app], used=used)
    assert second is None


def test_an9s_coverage_copy_is_eligible_not_a_lead():
    from pathlib import Path
    import json

    table = json.loads((
        Path(__file__).resolve().parents[1]
        / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage/WALLET_TABLE.json"
    ).read_text(encoding="utf-8"))
    an9s = next(row for row in table["wallets"] if row["label"] == "An9s")
    assert an9s["coverage_status"] == "provisional_eligible"
    assert an9s["qualification_level"] != "provisional_research_lead"
    assert an9s["coverage_status_display"] == "Coverage gate eligible; not a research lead."


def test_committed_gtfo_audit_uses_aggregate_rounding_bridge():
    from pathlib import Path
    import json

    payload = json.loads((
        Path(__file__).resolve().parents[1]
        / "evidence/mass-wallet-funnel/research-search-b-2026-10-06/coverage/INDEPENDENT_AUDIT.json"
    ).read_text(encoding="utf-8"))
    gtfo = next(row for row in payload["wallets"] if row["address"].startswith("gtfo"))
    assert gtfo["independently_audited"] is True
    assert gtfo["one_to_one_membership"] is True
    bridge = gtfo["aggregate_rounding_bridge"]
    assert bridge["within_declared_tolerance"] is False
    assert bridge["delta_atomics"] == 6
    assert "auditor confirms within 2 lamports" not in (gtfo.get("auditor_confirmation") or "")
    assert "aggregate rounding bridge" in (gtfo.get("auditor_confirmation") or "")
    assert str(gtfo["independently_audited_episode_net"]) in (gtfo.get("auditor_confirmation") or "")


def test_gtfo_aggregate_rounding_bridge_is_not_within_two_lamports():
    bridge = aggregate_rounding_bridge("2.030645834", "2.030645840", "SOL")
    assert bridge["within_declared_tolerance"] is False
    assert bridge["delta_atomics"] == 6
    text = format_auditor_confirmation("2.030645834", "2.030645840", "SOL", independently_audited=True)
    assert "auditor confirms within 2 lamports" not in text
    assert "aggregate rounding bridge" in text
    assert "app 2.030645834 vs auditor 2.03064584" in text
    agree = format_auditor_confirmation("283.399579449", "283.399579447", "SOL", independently_audited=True)
    assert "within 2 lamports" in agree


def test_unknown_cost_inventory_is_not_an_open_lot_count():
    exposure = exposure_outside_completed_episodes({}, {"open_buys_in_sample": 11})
    assert exposure["inventory_of_unknown_cost"] is None
    assert exposure["inventory_of_unknown_cost_status"] == "unknown"
    assert exposure["open_lots"] == 11
    assert exposure["open_lots_unit"] == "lots"


def test_traversed_interval_is_not_requested_window_fallback():
    interval = requested_history_interval({
        "window": {"start": "2026-09-05T13:29:27Z", "end": "2026-10-05T13:29:27Z"},
    })
    assert interval["requested_history_interval_actually_traversed"]["status"] == "not_evaluated"
    assert interval["requested_history_interval_actually_traversed"]["start"] is None
    observed = requested_history_interval({
        "window": {"start": "2026-09-05T13:29:27Z", "end": "2026-10-05T13:29:27Z"},
        "in_window_span": {"start": "2026-09-20T01:00:00Z", "end": "2026-09-21T01:00:00Z", "hours": "24"},
    })
    assert observed["requested_history_interval_actually_traversed"]["status"] == "observed"
    assert observed["traversed_start"] == "2026-09-20T01:00:00Z"


def test_open_position_ages_are_not_evaluated_without_positions():
    stats = hold_time_stats([{"hold_seconds": 12}, {"hold_seconds": 20}])
    assert stats["open_positions"]["status"] == "not_evaluated"
    wired = hold_time_stats(
        [{"hold_seconds": 12}],
        [{"opened_at": datetime(2026, 9, 1, tzinfo=timezone.utc)}],
        now=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    assert wired["open_positions"]["status"] == "observed"
    assert wired["open_positions"]["sample_count"] == 1


def test_token_2022_ambiguous_and_capped_are_not_config():
    # amount=50: bps 1 and 2 both withhold 1 under the uncapped ceiling.
    matches = infer_token_2022_fee_bps_candidates([50], 1)
    assert len(matches) > 1
    assert infer_token_2022_fee_bps([50], 1) is None
    # Capped/configuration-unknown: withheld below every positive uncapped ceiling
    # for a large transfer is not a unique TransferFeeConfig proof.
    assert infer_token_2022_fee_bps([10_000_000], 1) is None
    assert token_2022_ceiling_fee(10_000_000, 1) == 1000


def test_next_capture_fake_transport_refuses_wrong_wallet_cutoff_cursor_phase_budget_grants():
    draft = load_next_capture_draft()
    assert draft["enabled"] is False
    gtfo = next(row for row in draft["allowed_wallets"] if row["address"].startswith("gtfo"))
    a6ps = next(row for row in draft["allowed_wallets"] if row["address"].startswith("A6PS"))
    pw58 = next(row for row in draft["allowed_wallets"] if row["address"].startswith("58PW"))
    request = serialize_box_driver_next_capture_first_request()

    assert evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": "An9sREpLnAXVi4KMaTGuGvgET51CyaukLUTMtxzmLYSB", "phase": 1, "block_time_lt": 1791206967},
    )["code"] in {"excluded_wallet", "wrong_wallet"}
    assert evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1, "pagination_token": gtfo["continue_from_pagination_token"]},
    )["code"] == "wrong_cutoff"
    assert evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": "not-the-cursor"},
    )["code"] == "wrong_cursor"
    assert evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": a6ps["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": a6ps["continue_from_pagination_token"]},
        replay_completed=False,
    )["code"] in {"phase_two_before_replay", "non_gtfo_initial"}
    replay = {
        "last_dispatch": {"address": gtfo["address"], "response_id": "page-1", "page_identity": gtfo["continue_from_pagination_token"]},
        "replay_receipts": [{"response_id": "page-1", "page_identity": gtfo["continue_from_pagination_token"]}],
    }
    assert evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": gtfo["continue_from_pagination_token"]},
        requests_used=8,
        replay_completed=True,
        **replay,
    )["code"] == "over_budget"
    assert evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": pw58["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": pw58["continue_from_pagination_token"]},
        replay_completed=True,
        **replay,
    )["code"] == "zero_executable_allowance"
    consumed = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": gtfo["continue_from_pagination_token"]},
        grant={"enabled": False, "consumed": True, "authorization_id": draft["authorization_id"]},
    )
    assert consumed["code"] == "consumed_grant"
    wrong_kind = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": gtfo["address"], "phase": 1, "block_time_lt": 1791206967, "pagination_token": gtfo["continue_from_pagination_token"]},
        grant={"enabled": False, "authorization_id": "live-g1-vertical-slice-2026-10-05-mitch"},
    )
    assert wrong_kind["code"] == "wrong_kind_grant"
    cccs = next(row for row in draft["allowed_wallets"] if row["address"].startswith("CccS"))
    no_progress = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": cccs["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": cccs["continue_from_pagination_token"]},
        replay_completed=True,
        previous_progress={"wallet_turned_positive": True},
        requests_used=1,
        **replay,
    )
    assert no_progress["code"] == "named_dependency_not_approached"
    a6ps_ok = evaluate_next_capture_dispatch(
        draft=draft,
        requested={"address": a6ps["address"], "phase": 2, "block_time_lt": 1791206967, "pagination_token": a6ps["continue_from_pagination_token"]},
        replay_completed=True,
        requests_used=1,
        **replay,
    )
    assert a6ps_ok["allowed"] is True
    assert a6ps_ok["dispatched"] is False
    assert request["not_a_dispatched_request"] is True
    progress = named_dependency_progress(
        {"named_dependency_observations": [{
            "signature": "named-sale",
            "unresolved_basis_cleared": True,
            "result": "named_sale_or_lot_unresolved_basis_cleared",
        }]},
        {"named_dependency_items": [{"signature": "named-sale"}], "acceptable_progress_observations": ["named_sale_or_lot_unresolved_basis_cleared"]},
    )
    assert progress["progress"] is True
    assert draft["page_budget"]["reserved_cannot_override_per_wallet_limits"] is True
    assert "BVZt" in str(draft["excluded_from_this_draft"])
    assert "DQ7n" in str(draft["excluded_from_this_draft"])


def test_synthetic_marking_does_not_justify_permissive_audit_branch():
    report = deepcopy(_eligible_report())
    report["corpus_kind"] = "SYNTHETIC"
    report["independent_audit"] = {"status": "independently_audited", "independently_audited": True}
    profile = build_research_profile(report, filters=default_filters())
    assert independently_audited(report, profile) is False
    assert profile["qualification_level"]["independently_audited"] is False
    assert profile["not_a_genuine_research_wallet"] is True
