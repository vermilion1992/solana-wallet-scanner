"""Offline source rebuilding preserves snapshots and never invents wallet completeness."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scanner.accounting import METHODOLOGY
from scanner.history_evidence import VERSION as HISTORY_METHODOLOGY
from scanner.position_evidence import VERSION as POSITION_METHODOLOGY
from scanner.config import STRICT
from scanner.report_rebuild import freeze_report_inputs, load_report_inputs
from scanner.storage import EvidenceError
from tests.test_discovery_integration_review import isolate_credentials_and_transport, session
from tests.test_review_v032_independent import synthetic_history, synthetic_position, WINDOW as SYNTHETIC_WINDOW, WALLET as SYNTHETIC_WALLET


def seed_report(store, *, frozen=True):
    bundle = json.loads((Path(__file__).parent / "fixtures" / "real-transaction-audit-mainnet.json").read_text())
    record = deepcopy(bundle["transactions"][0])
    raw, address, signature = record["raw"], bundle["address"], record["signature"]
    record["evidence_hash"] = store.archive(raw)
    end = datetime(2026, 10, 3, tzinfo=timezone.utc)
    start = end - timedelta(days=30)
    window = {"start": start.isoformat(), "end": end.isoformat()}
    page = {"method": "getSignaturesForAddress", "address": address,
            "params": {"commitment": "finalized", "limit": 100, "minContextSlot": raw["slot"]},
            "result": [{"signature": signature, "slot": raw["slot"], "blockTime": raw["blockTime"],
                        "err": raw["meta"]["err"], "confirmationStatus": "finalized"}]}
    page_hash = store.archive(page)
    evidence = [{"kind": "transaction", "signature": signature, "hash": record["evidence_hash"]},
                {"kind": "signature-page", "hash": page_hash}]
    checkpoint = {"version": "native-collector-v1", "address": address,
                  "start": int(start.timestamp()), "end": int(end.timestamp()),
                  "basis_floor": int((start - timedelta(days=90)).timestamp()),
                  "accounts": {address: {"address": address, "origin": "wallet", "cursor": None,
                                         "pages": 0, "terminal": None, "page_hashes": []}},
                  "snapshot": {"slot": raw["slot"], "network": "mainnet-beta", "commitment": "finalized"},
                  "transactions": {signature: {"signature": signature, "evidence_hash": record["evidence_hash"]}},
                  "evidence": evidence, "gaps": [], "ordering": {}}
    key = hashlib.sha256(f"{address}:{int(start.timestamp())}:{int(end.timestamp())}".encode()).hexdigest()
    store.put("collector_checkpoints", key, checkpoint)
    collected = {"transactions": [record], "checkpoint": checkpoint, "snapshot": checkpoint["snapshot"],
                 "coverage": {"status": "partial", "history_scope_complete": False}, "evidence": evidence}
    preset = {**STRICT, "min_profit_sol": "6"}
    report = {"id": "old-live-report", "scan_id": "saved-scan", "source": "live", "address": address,
              "created_at": "2026-10-03T00:00:00+00:00", "window": window, "preset": preset,
              "methodology": "fifo-v2", "metrics": {}, "events": [], "coverage": collected["coverage"],
              "evidence": evidence, "evidence_status": "partial", "policy": "UNRESOLVED", "token_risk": []}
    if frozen:
        report["collection_input_hash"] = freeze_report_inputs(store, address, window, collected)
    store.put("reports", report["id"], report)
    store.put("scans", "saved-scan", {"id": "saved-scan", "status": "paused", "audit_addresses": [address],
                                       "window": window, "preset": deepcopy(STRICT), "budget_mode": "setup-pilot"})
    return report, collected


@pytest.mark.parametrize("frozen", [True, False])
def test_rebuild_uses_exact_sources_and_preserves_original_window_and_preset(session, frozen):
    client, app, _ = session
    report, _ = seed_report(app.state.store, frozen=frozen)
    original = deepcopy(report)
    before = client.get("/api/state").json()["usage"]
    response = client.post("/api/reports/old-live-report/rebuild")
    assert response.status_code == 200, response.text
    identifier = response.json()["report_id"]
    rebuilt = client.get("/api/reports/" + identifier).json()
    assert identifier != original["id"]
    assert app.state.store.get("reports", original["id"]) == original
    assert rebuilt["window"] == original["window"]
    assert rebuilt["preset"] == original["preset"]
    assert rebuilt["rebuilt_from"] == original["id"]
    assert rebuilt["previous_methodology"] == "fifo-v2" and rebuilt["methodology"] == METHODOLOGY
    assert rebuilt["rebuild"]["provider_requests"] == 0
    assert rebuilt["rebuild"]["mint_observations_refreshed"] is False
    assert next(event for event in rebuilt["events"] if event["kind"] == "buy")["amount_sol"] == "0.25"
    assert rebuilt["policy"] == "UNRESOLVED" and not rebuilt["qualification"]["qualified"]
    assert rebuilt["coverage"]["history_evidence"]["metric_decisions"]["history"]["state"] == "UNKNOWN"
    assert rebuilt["history_assessment"]["state"] == "current"
    assert rebuilt["history_assessment"]["current_methodology"] == HISTORY_METHODOLOGY
    assert rebuilt["coverage"]["position_evidence"]["version"] == POSITION_METHODOLOGY
    assert rebuilt["position_assessment"]["state"] == "current"
    assert rebuilt["metric_coverage"]["positive_weeks"]["source"] == "primary_evidence_declaration"
    assert rebuilt["metric_coverage"]["positive_weeks"]["evidence"] == rebuilt["coverage"]["history_evidence"]["intervals"]["four_weeks"]["evidence"]
    assert rebuilt["metric_coverage"]["positive_weeks"]["status"] != "complete"
    assert client.get("/api/state").json()["usage"] == before
    assert len(app.state.store.list("reports")) == 2
    assert load_report_inputs(app.state.store, rebuilt)["transactions"][0]["raw"] == load_report_inputs(app.state.store, original)["transactions"][0]["raw"]


@pytest.mark.parametrize("saved_version,expected", [(None, "missing"), ("history-evidence-v1", "rebuild_required"), ("history-evidence-v2", "rebuild_required"), ("history-evidence-v3", "rebuild_required"), ("history-evidence-v4", "rebuild_required"), ("history-evidence-v5", "rebuild_required"), ("history-evidence-v6", "rebuild_required"), ("history-evidence-v7", "rebuild_required"), (HISTORY_METHODOLOGY, "current")])
def test_saved_receipt_assessment_is_read_only_on_state_report_and_export(session, saved_version, expected):
    client, app, _ = session
    report, _ = seed_report(app.state.store)
    if saved_version:
        report["coverage"]["history_evidence"] = {"version": saved_version, "native_address_metrics": {"periods": {"report_period": {"wallet_network_fees_sol": {"value": "0.00001", "status": "known"}}}}}
    app.state.store.put("reports", report["id"], report)
    original = deepcopy(report)
    before = client.get("/api/state").json()["usage"]
    for result in (client.get("/api/reports/" + report["id"]).json(),
                   client.get("/api/export/reports/" + report["id"] + ".json").json(),
                   next(item for item in client.get("/api/state").json()["reports"] if item["id"] == report["id"])):
        assert result["history_assessment"]["state"] == expected
        assert result["coverage"] == original["coverage"]
        assert not result["qualification"]["qualified"]
    assert app.state.store.get("reports", report["id"]) == original
    assert client.get("/api/state").json()["usage"] == before


@pytest.mark.parametrize("saved_version,expected", [(None, "missing"), ("account-position-evidence-v1", "rebuild_required"), ("account-position-evidence-v2", "rebuild_required"), ("account-position-evidence-v3", "rebuild_required"), ("account-position-evidence-v4", "rebuild_required"), ("account-position-evidence-v5", "rebuild_required"), ("account-position-evidence-v6", "rebuild_required"), ("account-position-evidence-v7", "rebuild_required"), ("account-position-evidence-v8", "rebuild_required"), ("account-position-evidence-v9", "rebuild_required"), (POSITION_METHODOLOGY, "current")])
def test_position_freshness_is_independent_of_current_history_and_preserves_saved_holds(session, saved_version, expected):
    client, app, _ = session
    report, _ = seed_report(app.state.store)
    report["coverage"]["history_evidence"] = {"version": HISTORY_METHODOLOGY}
    position = {"known_account_hold_median_hours": {"value": "6", "status": "known"},
                "positions": [{"hold_hours": {"value": "6", "status": "known"},
                               "stages": {"chronology": {"state": "PASS"}}}]}
    if saved_version:
        position["version"] = saved_version
    report["coverage"]["position_evidence"] = position
    app.state.store.put("reports", report["id"], report)
    original = deepcopy(report)
    before = client.get("/api/state").json()
    assert before["position_evidence_methodology"] == POSITION_METHODOLOGY
    for result in (client.get("/api/reports/" + report["id"]).json(),
                   client.get("/api/export/reports/" + report["id"] + ".json").json(),
                   next(item for item in before["reports"] if item["id"] == report["id"])):
        assert result["history_assessment"]["state"] == "current"
        assert result["position_assessment"]["state"] == expected
        assert result["position_assessment"]["saved_methodology"] == saved_version
        assert result["coverage"] == original["coverage"]
        assert not result["qualification"]["qualified"]
    assert app.state.store.get("reports", report["id"]) == original
    assert client.get("/api/state").json()["usage"] == before["usage"]


def test_rebuild_runs_scoped_position_stage_without_promoting_wallet_metrics(session, synthetic_position):
    client, app, _ = session
    history = synthetic_position
    checkpoint = deepcopy(history.cp)
    for reference in checkpoint["evidence"]:
        assert app.state.store.archive(history.store.evidence(reference["hash"])) == reference["hash"]
    identifier = hashlib.sha256(f"{SYNTHETIC_WALLET}:{checkpoint['start']}:{checkpoint['end']}".encode()).hexdigest()
    app.state.store.put("collector_checkpoints", identifier, checkpoint)
    window = {name: datetime.fromtimestamp(value, timezone.utc).isoformat() for name, value in SYNTHETIC_WINDOW.items()}
    collected = {"transactions": list(checkpoint["transactions"].values()), "checkpoint": checkpoint,
                 "snapshot": checkpoint["snapshot"], "evidence": checkpoint["evidence"], "coverage": {"status": "partial"}}
    original = {"id": "synthetic-position-source", "scan_id": "synthetic-position-job", "source": "live", "address": SYNTHETIC_WALLET,
                "created_at": "2026-10-02T00:00:00+00:00", "window": window, "preset": dict(STRICT), "methodology": "fifo-v3",
                "metrics": {}, "checks": [], "policy": "UNRESOLVED", "evidence_status": "partial", "coverage": {}, "token_risk": [],
                "evidence": checkpoint["evidence"], "collection_input_hash": freeze_report_inputs(app.state.store, SYNTHETIC_WALLET, window, collected)}
    app.state.store.put("reports", original["id"], original)
    app.state.store.put("scans", original["scan_id"], {"id": original["scan_id"], "status": "paused", "audit_addresses": [SYNTHETIC_WALLET],
                                                     "window": window, "preset": dict(STRICT), "budget_mode": "setup-pilot"})
    before = client.get("/api/state").json()["usage"]
    response = client.post("/api/reports/" + original["id"] + "/rebuild")
    assert response.status_code == 200, response.text
    child = client.get("/api/reports/" + response.json()["report_id"]).json()
    scoped = child["coverage"]["position_evidence"]
    assert scoped["counts"]["known_closed"] == 1
    assert scoped["known_account_hold_median_hours"]["status"] == "known"
    assert child["metrics"]["median_hold_hours"]["status"] == "unknown"
    assert child["metrics"]["profit_sol"]["status"] == "unknown"
    assert not child["qualification"]["qualified"] and child["policy"] == "UNRESOLVED"
    assert app.state.store.get("reports", original["id"]) == original
    assert client.get("/api/state").json()["usage"] == before


def test_missing_primary_record_refuses_rebuild_without_a_new_report(session):
    client, app, _ = session
    report, collected = seed_report(app.state.store)
    digest = collected["transactions"][0]["evidence_hash"]
    (app.state.store.path / "evidence" / (digest + ".json.gz")).unlink()
    response = client.post("/api/reports/old-live-report/rebuild")
    assert response.status_code == 409
    assert app.state.store.list("reports") == [report]


def test_wrong_frozen_window_or_signature_cannot_be_rebuilt(session):
    client, app, _ = session
    report, collected = seed_report(app.state.store)
    frozen = app.state.store.evidence(report["collection_input_hash"])
    frozen["window"]["end"] = "2026-10-04T00:00:00+00:00"
    report["collection_input_hash"] = app.state.store.archive(frozen)
    app.state.store.put("reports", report["id"], report)
    assert client.post("/api/reports/old-live-report/rebuild").status_code == 409
    assert len(app.state.store.list("reports")) == 1


def test_frozen_input_rejects_duplicate_transaction_links(session):
    client, app, _ = session
    report, _ = seed_report(app.state.store)
    frozen = app.state.store.evidence(report["collection_input_hash"])
    frozen["transactions"] *= 2
    report["collection_input_hash"] = app.state.store.archive(frozen)
    app.state.store.put("reports", report["id"], report)
    with pytest.raises(EvidenceError, match="duplicated"):
        load_report_inputs(app.state.store, report)


def test_rebuild_refuses_missing_job_context_demo_csrf_and_disk_shortfall(session, monkeypatch):
    client, app, _ = session
    report, _ = seed_report(app.state.store)
    token = client.headers.pop("x-csrf-token")
    assert client.post("/api/reports/old-live-report/rebuild").status_code == 403
    client.headers["x-csrf-token"] = token
    monkeypatch.setattr("shutil.disk_usage", lambda _: SimpleNamespace(free=0))
    assert client.post("/api/reports/old-live-report/rebuild").status_code == 409
    monkeypatch.undo()
    app.state.store.delete("scans", "saved-scan")
    assert client.post("/api/reports/old-live-report/rebuild").status_code == 409
    report["source"] = "demo"
    app.state.store.put("reports", report["id"], report)
    assert client.post("/api/reports/old-live-report/rebuild").status_code == 409
    assert client.post("/api/reports/missing/rebuild").status_code == 404
    assert len(app.state.store.list("reports")) == 1
