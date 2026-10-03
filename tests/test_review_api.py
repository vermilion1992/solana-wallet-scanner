"""Offline review acceptance: identifiers and scoped records never become picks."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from scanner.accounting import METHODOLOGY
from tests.test_discovery_integration_review import isolate_credentials_and_transport, session


WALLET = "4drEkXDZhjun3vjZmz1g7pQGM7kxANQbDuD9jtPZwzJZ"
TOKEN_ACCOUNT = "47YKPtLHM5joKbW5hCFhXhZcigp4Xb9NrGpiKFjfsNUM"


def fixture_bundle():
    return json.loads((Path(__file__).parent / "fixtures" / "real-transaction-audit-mainnet.json").read_text())


def test_import_is_offline_deduplicated_and_cannot_bypass_identity_audit(session):
    client, app, _ = session
    before = client.get("/api/state").json()["usage"]
    response = client.post("/api/discovery/import", json={"addresses": [WALLET, WALLET, TOKEN_ACCOUNT]})
    assert response.status_code == 200
    imported = response.json()
    assert imported["counts"]["duplicate_rows"] == 1
    cohort = client.get("/api/discovery/" + imported["cohort_id"]).json()
    assert len(cohort["candidates"]) == 2
    assert all(row["stage"] == "listed" and not any(row["states"].values()) for row in cohort["candidates"])
    assert all(row["qualification"]["qualified"] is False for row in cohort["candidates"])
    assert client.post(f"/api/discovery/{cohort['id']}/audit", json={"addresses": [WALLET]}).status_code == 422
    state = client.get("/api/state").json()
    assert state["methodology"] == METHODOLOGY
    assert state["candidate_universe"] == client.get("/api/discovery/universe").json()
    assert state["candidate_universe"]["counts"]["observed"] == 0
    assert state["candidate_universe"]["counts"]["history_reconstructed"] == 0
    assert state["scans"] == state["reports"] == []
    assert state["usage"] == before


def test_invalid_import_is_atomic_and_rejects_claimed_verification(session):
    client, app, _ = session
    assert client.post("/api/discovery/import", json={"addresses": [WALLET, "invalid-address"]}).status_code == 422
    assert client.post("/api/discovery/import", json={"addresses": [WALLET], "identity_verified": True}).status_code == 422
    assert app.state.store.list("discovery_cohorts") == []


def test_real_scoped_audit_reconstructs_costs_without_qualifying_a_wallet(session):
    client, app, _ = session
    before = client.get("/api/state").json()["usage"]
    example = client.get("/api/evidence/example")
    assert example.status_code == 200
    assert "attachment" in example.headers["content-disposition"]
    assert example.json() == fixture_bundle()
    response = client.post("/api/evidence/audit", json=example.json())
    assert response.status_code == 200
    result = response.json()
    identifier = result.pop("audit_id")
    assert result["certificate"]["status"] == "SCOPED_RECONSTRUCTION"
    assert result["certificate"]["wallet_history_complete"] is False
    assert result["certificate"]["financial_qualification"] == "UNRESOLVED"
    assert result["metrics"]["gross_buy_consideration_sol"]["value"] == "0.25"
    assert result["metrics"]["wallet_network_fees_sol"]["value"] == "0.000141389"
    assert result["metrics"]["outside_native_delta_sol"]["value"] == "-0.0035"
    assert result["metrics"]["wallet_profit_sol"]["value"] is None
    assert result["certificate"]["checks"]["opening_basis"]["state"] == "UNKNOWN"
    assert result["certificate"]["checks"]["fee_allocation"]["state"] == "UNKNOWN"
    assert result == client.get(f"/api/evidence/audits/{identifier}").json()
    exported = client.get(f"/api/evidence/audits/{identifier}/export")
    assert exported.json() == result
    assert "attachment" in exported.headers["content-disposition"]
    evidence = client.get("/api/evidence/" + result["evidence"][0]["hash"])
    assert evidence.status_code == 200
    state = client.get("/api/state").json()
    assert state["evidence_audits"] == [result]
    assert state["reports"] == state["scans"] == state["discovery_cohorts"] == []
    assert state["usage"] == before


def test_incomplete_declared_account_scope_revokes_trade_metrics_but_keeps_fee(session):
    client, app, _ = session
    bundle = fixture_bundle()
    bundle["scope"]["accounts"].remove(TOKEN_ACCOUNT)
    result = client.post("/api/evidence/audit", json=bundle).json()
    assert result["certificate"]["status"] == "INCOMPLETE"
    assert result["certificate"]["checks"]["account_boundary"]["state"] == "FAIL"
    assert result["metrics"]["gross_buy_consideration_sol"]["value"] is None
    assert result["metrics"]["wallet_network_fees_sol"]["value"] == "0.000141389"
    assert result["metrics"]["wallet_profit_sol"]["value"] is None


def test_large_bounded_bundle_uses_evidence_limit_and_duplicate_records_fail(session):
    client, app, _ = session
    bundle = fixture_bundle()
    bundle["transactions"] = [deepcopy(bundle["transactions"][0]) for _ in range(3)]
    assert len(json.dumps(bundle).encode()) > 65536
    response = client.post("/api/evidence/audit", json=bundle)
    assert response.status_code == 200
    assert response.json()["certificate"]["checks"]["transaction_set"]["state"] == "FAIL"
    assert response.json()["metrics"]["wallet_profit_sol"]["value"] is None
    assert client.post("/api/discovery/import", content=json.dumps(bundle), headers={"content-type": "application/json"}).status_code == 413


def test_oversized_evidence_and_malformed_json_leave_no_audit(session):
    client, app, _ = session
    assert client.post("/api/evidence/audit", content=b" " * (4 * 1024 * 1024 + 1)).status_code == 413
    assert client.post("/api/evidence/audit", content=b"{broken").status_code == 422
    assert app.state.store.list("evidence_audits") == []
    assert client.get("/api/evidence/audits/missing").status_code == 404


def test_evidence_audit_requires_csrf_before_archiving_primary_records(session):
    client, app, _ = session
    token = client.headers.pop("x-csrf-token")
    try:
        assert client.post("/api/evidence/audit", json=fixture_bundle()).status_code == 403
    finally:
        client.headers["x-csrf-token"] = token
    assert app.state.store.list("evidence_audits") == []
    assert app.state.store.list("artifacts") == []


def test_excessively_nested_json_is_rejected_before_evidence_storage(session):
    client, app, _ = session
    nested = b'{"nested":' + b'[' * 3000 + b'0' + b']' * 3000 + b'}'
    response = client.post("/api/evidence/audit", content=nested, headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert app.state.store.list("evidence_audits") == []
    assert app.state.store.list("artifacts") == []


def test_raw_evidence_ingestion_respects_free_disk_reserve_before_writing(session, monkeypatch):
    import shutil
    client, app, _ = session
    monkeypatch.setattr(shutil, "disk_usage", lambda _: SimpleNamespace(total=10**10, used=10**10, free=0))
    response = client.post("/api/evidence/audit", json=fixture_bundle())
    assert response.status_code == 409
    assert "free-disk reserve" in response.json()["detail"]
    assert app.state.store.list("artifacts") == []
    assert app.state.store.list("evidence_audits") == []
