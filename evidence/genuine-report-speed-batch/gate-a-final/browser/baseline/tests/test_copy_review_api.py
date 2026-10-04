"""Offline API decoration must preserve saved facts and reject stale qualification."""
from copy import deepcopy
import json

from scanner.accounting import METHODOLOGY
from tests.test_pdf_alignment import passing_report
# Import the already isolated loopback fixture and its automatic network guard.
from tests.test_discovery_integration_review import isolate_credentials_and_transport, session


def store_report(store, identifier, **changes):
    report = {**passing_report(), "id": identifier, "created_at": "2026-10-02T00:00:00+00:00",
              "address": "11111111111111111111111111111111", "positions": [], "events": [], "evidence": [], **changes}
    store.put("reports", identifier, report)
    return deepcopy(report)


def store_linked_cohort(store, reports):
    candidates = [{"address": report["address"], "report_id": report["id"], "status": "candidate",
                   "validation": {"identity_verified": True, "account_type": "system-owned signer",
                                  "economic_signers": [report["address"]]}, "qualification": {"qualified": True}}
                  for report in reports]
    candidates.append({"address": "So11111111111111111111111111111111111111112", "status": "candidate",
                       "validation": {"identity_verified": True, "account_type": "system-owned signer",
                                      "economic_signers": ["So11111111111111111111111111111111111111112"]},
                       "qualification": {"qualified": True}})
    cohort = {"id": "c" * 32, "created_at": "2026-10-02T00:00:00+00:00", "status": "completed",
              "candidates": candidates, "counts": {}, "evidence": [], "limitations": []}
    store.put("discovery_cohorts", cohort["id"], cohort)
    return deepcopy(cohort)


def test_state_and_cohort_use_current_linked_reports_without_mutating_saved_snapshots(session):
    client, app, _ = session
    current = store_report(app.state.store, "current-pass", methodology=METHODOLOGY)
    legacy = store_report(app.state.store, "old-fee-method", methodology="fifo-v1", qualification={"qualified": True})
    partial = store_report(app.state.store, "partial-scope", evidence_status="partial", qualification={"qualified": True})
    saved_cohort = store_linked_cohort(app.state.store, [legacy, partial, current])

    state = client.get("/api/state").json()
    reports = {report["id"]: report for report in state["reports"]}
    assert reports[current["id"]]["qualification"]["qualified"] is True
    for report in (legacy, partial):
        assert reports[report["id"]]["qualification"]["qualified"] is False
    assert reports[legacy["id"]]["policy"] == "MATCH"  # Saved historical policy remains inspectable.
    assert any(check["key"] == "methodology" for check in reports[legacy["id"]]["qualification"]["unknown_checks"])

    cohort = client.get(f"/api/discovery/{saved_cohort['id']}").json()
    linked = {candidate.get("report_id"): candidate for candidate in cohort["candidates"]}
    assert linked[current["id"]]["qualification"]["qualified"] is True
    assert linked[legacy["id"]]["qualification"]["qualified"] is False
    assert linked[partial["id"]]["qualification"]["qualified"] is False
    assert linked[None]["qualification"]["qualified"] is False
    assert linked[None]["qualification"]["financial_policy"] == "NOT_AUDITED"
    assert "native identity" in linked[None]["qualification"]["reason"].lower()
    assert next(row for row in state["discovery_cohorts"] if row["id"] == cohort["id"]) == cohort
    for original in (current, legacy, partial):
        assert app.state.store.get("reports", original["id"]) == original
    assert app.state.store.get("discovery_cohorts", saved_cohort["id"]) == saved_cohort


def test_get_report_and_json_export_recompute_qualification_without_rewriting_old_report(session):
    client, app, directory = session
    current = store_report(app.state.store, "current-export")
    legacy = store_report(app.state.store, "legacy-export", methodology="fifo-v1", qualification={"qualified": True})
    for original, qualifies in ((current, True), (legacy, False)):
        response = client.get(f"/api/reports/{original['id']}")
        assert response.status_code == 200
        rendered = response.json()
        assert rendered["qualification"]["qualified"] is qualifies
        assert "copy_review" in rendered
        exported = client.get(f"/api/export/reports/{original['id']}.json")
        assert exported.status_code == 200
        assert exported.json() == rendered
        assert exported.headers["content-type"].startswith("application/json")
        assert json.loads((directory / "exports" / f"{original['id']}.json").read_text()) == rendered
        assert app.state.store.get("reports", original["id"]) == original
    assert client.get("/api/usage").json()["used"] == 0


def test_cached_preview_never_becomes_a_qualified_live_match_or_mutates_original(session):
    client, app, _ = session
    original = store_report(app.state.store, "verified-current")
    assert client.get(f"/api/reports/{original['id']}").json()["qualification"]["qualified"] is True
    preview = client.post("/api/presets/preview", json={"preset": {}})
    assert preview.status_code == 200
    displayed = next(report for report in preview.json()["reports"] if report["id"] == original["id"])
    assert displayed["policy"] == "MATCH"
    assert displayed["preview"] is True
    assert displayed["qualification"]["qualified"] is False
    assert displayed["copy_review"]["conditional"] is True
    assert app.state.store.get("reports", original["id"]) == original
    assert client.get(f"/api/reports/{original['id']}").json()["qualification"]["qualified"] is True
    assert client.get("/api/usage").json()["used"] == 0
