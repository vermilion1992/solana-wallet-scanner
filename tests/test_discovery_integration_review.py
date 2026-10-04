"""Offline integration review of setup budgets and discovery authorization."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
import pytest

from scanner.app import create_app
from scanner.config import STRICT
from scanner.providers import Gateway
from scanner.storage import QuotaExceeded


BASE_URL = "http://127.0.0.1:8765"
LAUNCH_TOKEN = "discovery-review-launch-token"
TEST_KEY = "offline_discovery_review_test_key_123"
ADDRESS = "11111111111111111111111111111111"
OTHER_ADDRESS = "So11111111111111111111111111111111111111112"


@pytest.fixture(autouse=True)
def isolate_credentials_and_transport(monkeypatch):
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "keyring", SimpleNamespace(get_keyring=lambda: object()))

    async def no_external_transport(*args, **kwargs):
        raise AssertionError("Discovery integration review must use offline transports")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", no_external_transport)


@contextmanager
def local_session(directory):
    app = create_app(directory, LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as client:
        bootstrap = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        assert bootstrap.status_code == 200
        client.headers["x-csrf-token"] = bootstrap.json()["csrf"]
        yield client, app


@pytest.fixture
def session(tmp_path):
    with local_session(tmp_path / "data") as active:
        yield (*active, tmp_path / "data")


def wait_record(client, collection, identifier, terminal=("completed", "partial", "paused", "failed")):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        records = client.get("/api/state").json()[collection]
        record = next((record for record in records if record["id"] == identifier), None)
        if record and record["status"] in terminal:
            return record
        time.sleep(0.005)
    raise AssertionError(f"Local worker did not finish {collection}")


def save_cohort(store, candidates):
    # The former flags-only fixture cannot meet source-backed audit eligibility.
    # Preserve each assertion's intent using archived primary schema examples;
    # negative identity declarations also change the corresponding raw proof.
    from tests.test_discovery_audit_plan import development_cohort
    cohort = development_cohort(store, [row["address"] for row in candidates])
    for supplied, row in zip(candidates, cohort["candidates"]):
        validation = supplied["validation"]
        if validation.get("identity_verified") is False:
            digest = row["validation"]["transaction_evidence_hash"]
            raw = store.evidence(digest)
            raw["meta"]["err"] = {"InstructionError": [0, "InvalidAccountData"]}
            replacement = store.archive(raw)
            row["validation"]["transaction_evidence_hash"] = replacement
        elif validation.get("account_type") != "system-owned signer":
            digest = row["validation"]["account_evidence_hash"]
            raw = store.evidence(digest)
            raw["result"]["value"]["owner"] = OTHER_ADDRESS
            replacement = store.archive(raw)
            row["validation"]["account_evidence_hash"] = replacement
        elif row["address"] not in validation.get("economic_signers", []):
            digest = row["validation"]["transaction_evidence_hash"]
            raw = store.evidence(digest)
            for field in ("preTokenBalances", "postTokenBalances"):
                raw["meta"][field][0]["owner"] = OTHER_ADDRESS
            replacement = store.archive(raw)
            row["validation"]["transaction_evidence_hash"] = replacement
        else:
            continue
        row["evidence"] = [replacement if h == digest else h for h in row["evidence"]]
        for link in cohort["evidence"]:
            if link["hash"] == digest:
                link["hash"] = replacement
    store.put("discovery_cohorts", cohort["id"], cohort)
    return cohort["id"]


def candidate(address=ADDRESS, **validation):
    return {"address": address, "status": "candidate", "validation": {
        "identity_verified": True, "account_type": "system-owned signer",
        "economic_signers": [address], **validation}}


def charge(store, count, cycle="setup-pilot"):
    for _ in range(count):
        reservation = store.reserve("helius", "getSlot", 1, cycle, 200)
        store.dispatch(reservation)
        store.settle(reservation)


def cache_mint(store, mint, result, observed_at):
    if result is None:
        result = {"context": {"slot": 1_000_000_000}, "value": None}
    observation = {"method": "getAccountInfo", "address": mint, "commitment": "finalized",
                   "observed_at": observed_at, "result": result}
    digest = store.archive(observation)
    context_slot = result["context"]["slot"]
    store.put("mint_risk_observations", mint, {"mint": mint, "hash": digest, "observed_at": observed_at,
                                              "context_slot": context_slot})
    return digest


def test_key_only_setup_keeps_entitlement_unknown_and_secret_backend_only(session):
    client, app, directory = session
    response = client.post("/api/provider/key", json={"api_key": TEST_KEY})
    assert response.status_code == 200
    provider, usage = response.json()["provider"], response.json()["usage"]
    assert provider["configured"] is True
    assert provider["storage"] == "session-only"
    assert provider["free_plan_confirmed"] is False
    assert provider["cycle_start"] is provider["cycle_end"] is None
    assert usage["mode"] == "setup-pilot"
    assert usage["cap"] == 200
    assert usage["billing_cycle_verified"] is False
    assert usage["cycle_end"] is None
    assert client.post("/api/scans", json={"addresses": [ADDRESS]}).status_code == 409
    assert client.post("/api/provider/test", json={}).status_code == 409
    assert client.post("/api/backup").status_code == 200
    assert TEST_KEY not in response.text
    assert TEST_KEY not in client.get("/api/state").text
    for path in directory.rglob("*"):
        if path.is_file():
            assert TEST_KEY.encode() not in path.read_bytes(), path
            assert LAUNCH_TOKEN.encode() not in path.read_bytes(), path
            assert app.state.csrf.encode() not in path.read_bytes(), path


def test_discovery_mutations_require_local_session_and_csrf(tmp_path):
    app = create_app(tmp_path / "data", LAUNCH_TOKEN)
    with TestClient(app, base_url=BASE_URL) as client:
        for route, body in (("/api/provider/key", {"api_key": TEST_KEY}), ("/api/discovery", {}),
                            ("/api/discovery/" + "a" * 32 + "/audit", {})):
            assert client.post(route, json=body).status_code == 401
        response = client.get("/api/bootstrap", headers={"x-launch-token": LAUNCH_TOKEN})
        for route, body in (("/api/provider/key", {"api_key": TEST_KEY}), ("/api/discovery", {}),
                            ("/api/discovery/" + "a" * 32 + "/audit", {})):
            assert client.post(route, json=body).status_code == 403
            assert client.post(route, json=body, headers={"x-csrf-token": response.json()["csrf"], "origin": "https://remote.invalid"}).status_code == 403
        assert app.state.store.list("discovery_cohorts") == []


@pytest.mark.parametrize("payload", [{"rpc_url": "https://remote.invalid"}, {"private_key": "unused"},
                                    {"pool_cap": 4}, {"candidate_cap": 21}, {"validate_cap": 9}, {"validate_cap": True}])
def test_discovery_rejects_unbounded_or_transactional_inputs_before_queueing(session, payload):
    client, app, _ = session
    assert client.post("/api/discovery", json=payload).status_code == 422
    assert app.state.store.list("discovery_cohorts") == []


def test_setup_native_budget_counts_prior_usage_and_survives_key_reentry_and_restart(tmp_path, monkeypatch):
    import scanner.discovery as discovery
    import scanner.providers as providers

    dispatched = []
    def response(request):
        body = json.loads(request.content)
        dispatched.append(body["method"])
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": 123})

    monkeypatch.setattr(providers, "Gateway", lambda *args, **kwargs: Gateway(*args, **kwargs, transport=httpx.MockTransport(response)))
    async def no_throttle(self):
        return None
    monkeypatch.setattr(Gateway, "_throttle", no_throttle)

    async def bounded_discovery(store, native, **options):
        status = "completed"
        try:
            for _ in range(3):
                await native.rpc("getSlot", [{"commitment": "finalized"}])
        except QuotaExceeded:
            status = "paused"
        result = {"id": options["cohort_id"], "status": status, "created_at": "2026-10-02T00:00:00+00:00",
                  "candidates": [], "counts": {}, "evidence": [], "limitations": []}
        store.put("discovery_cohorts", result["id"], result)
        return result
    monkeypatch.setattr(discovery, "discover_candidates", bounded_discovery)

    directory = tmp_path / "data"
    with local_session(directory) as (client, app):
        charge(app.state.store, 198)
        assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).status_code == 200
        response = client.post("/api/discovery", json={})
        assert response.status_code == 200
        assert wait_record(client, "discovery_cohorts", response.json()["cohort_id"])["status"] == "paused"
        assert dispatched == ["getSlot", "getSlot"]
        assert client.get("/api/usage").json()["used"] == 200
        assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).json()["usage"]["used"] == 200
    with local_session(directory) as (client, app):
        assert client.get("/api/usage").json()["used"] == 200
        assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).json()["usage"]["remaining"] == 0
        cohort = save_cohort(app.state.store, [candidate()])
        assert client.post(f"/api/discovery/{cohort}/audit", json={}).status_code == 409
        assert dispatched == ["getSlot", "getSlot"]


def test_key_reentry_cannot_erase_active_monthly_cycle_anti_reset(session):
    client, app, _ = session
    today = date.today()
    original = {"api_key": TEST_KEY, "free_plan_confirmed": True,
                "cycle_start": today.isoformat(), "cycle_end": (today + timedelta(days=30)).isoformat()}
    assert client.post("/api/provider", json=original).status_code == 200
    charge(app.state.store, 2, today.isoformat())
    assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).status_code == 200
    changed = {**original, "cycle_start": (today - timedelta(days=1)).isoformat()}
    assert client.post("/api/provider", json=changed).status_code == 422
    assert client.post("/api/provider", json=original).status_code == 200
    assert client.get("/api/usage").json()["used"] == 2


@pytest.mark.parametrize("validation", [{"identity_verified": False}, {"account_type": "program-owned"}, {"economic_signers": [OTHER_ADDRESS]}])
def test_discovery_audit_requires_all_native_identity_evidence(session, validation):
    client, app, _ = session
    assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).status_code == 200
    cohort = save_cohort(app.state.store, [candidate(**validation)])
    assert client.post(f"/api/discovery/{cohort}/audit", json={"addresses": [ADDRESS]}).status_code == 422
    assert app.state.store.list("scans") == []


def test_discovery_audit_uses_fixed_setup_limits_and_partial_reports(session, monkeypatch):
    import scanner.collector as collector
    client, app, _ = session
    collected_limits = []

    async def empty_collection(gateway, store, address, start, end, limits, **options):
        collected_limits.append(limits)
        return {"transactions": [], "coverage": {"status": "partial", "history_scope_complete": False}, "evidence": []}
    monkeypatch.setattr(collector, "collect_wallet", empty_collection)

    assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).status_code == 200
    cohort = save_cohort(app.state.store, [candidate()])
    response = client.post(f"/api/discovery/{cohort}/audit", json={})
    assert response.status_code == 200
    assert response.json()["budget_mode"] == "setup-pilot"
    scan = wait_record(client, "scans", response.json()["scan_id"])
    assert scan["status"] == "completed"
    assert collected_limits[0]["transaction_limit"] == 20
    assert collected_limits[0]["wallet_credit_limit"] == 30
    assert collected_limits[0]["page_size"] == 25
    assert collected_limits[0]["basis_lookback_days"] == STRICT["verification_days"]
    report = client.get("/api/state").json()["reports"][0]
    assert report["evidence_status"] == "partial"
    assert report["policy"] != "MATCH"
    assert report["metrics"]["profit_sol"]["status"] == "unknown"
    assert report["metrics"]["economic_pnl_sol"]["status"] == "unknown"
    assert client.get("/api/usage").json()["billing_cycle_verified"] is False


def test_positive_observed_lot_model_never_certifies_wallet_profit_or_safe_copying(session, monkeypatch):
    import scanner.collector as collector
    from scanner.decoder import TOKEN_IDS
    from tests.test_investigation import record, WALLET, TOKEN
    from tests.test_discovery import MINT
    client, app, _ = session

    def replace_identity(value):
        if isinstance(value, dict):
            return {key: replace_identity(item) for key, item in value.items() if key != "uiAmount"}
        if isinstance(value, list):
            return [replace_identity(item) for item in value]
        return ADDRESS if value == WALLET else MINT if value == TOKEN else value

    buy, sale = replace_identity(record()), replace_identity(record(sell=True))
    now = datetime.now(timezone.utc)
    for entry, signature, slot, age in ((buy, "review-buy", 100, 3), (sale, "review-sale", 101, 2)):
        entry["signature"] = entry["raw"]["transaction"]["signatures"][0] = signature
        entry["raw"]["slot"] = slot
        entry["raw"]["blockTime"] = int((now - timedelta(days=age)).timestamp())
    # A fetched 1 SOL purchase followed by a 2 SOL sale; route token transfers,
    # wrapped/native balances and quote amounts agree with each other.
    sale["raw"]["meta"]["preTokenBalances"][3]["uiTokenAmount"]["amount"] = "2000000000"
    sale["raw"]["meta"]["postTokenBalances"][1]["uiTokenAmount"]["amount"] = "2000000000"
    sale["raw"]["meta"]["preBalances"][4] = 2_039_280 + 2_000_000_000
    sale["raw"]["meta"]["postBalances"][2] = 2_039_280 + 2_000_000_000
    sale["raw"]["meta"]["innerInstructions"][0]["instructions"][1]["parsed"]["info"]["tokenAmount"]["amount"] = "2000000000"
    for entry in (buy, sale):
        entry["evidence_hash"] = app.state.store.archive(entry["raw"])
    mint_result = {"context": {"slot": 110}, "value": {"owner": sorted(TOKEN_IDS)[0],
                   "data": {"parsed": {"type": "mint", "info": {"mintAuthority": None,
                            "freezeAuthority": None, "supply": "1000", "decimals": 6}}}}}
    cache_mint(app.state.store, MINT, mint_result, now.isoformat())

    async def observed_pair(gateway, store, address, start, end, limits, **options):
        return {"transactions": deepcopy([buy, sale]), "coverage": {"status": "partial", "history_scope_complete": False},
                "evidence": [{"hash": entry["evidence_hash"], "kind": "transaction", "signature": entry["signature"]} for entry in (buy, sale)]}
    monkeypatch.setattr(collector, "collect_wallet", observed_pair)
    assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).status_code == 200
    cohort_id = save_cohort(app.state.store, [candidate()])
    response = client.post(f"/api/discovery/{cohort_id}/audit", json={})
    assert response.status_code == 200
    assert wait_record(client, "scans", response.json()["scan_id"])["status"] == "completed"
    state = client.get("/api/state").json()
    report = state["reports"][0]
    assert Decimal(report["research"]["conditional_observed_lot_profit_sol"]) > 0
    assert report["research"]["observed_matched_sales"] == 1
    assert report["research"]["observed_profit_sol"] is None
    assert report["research"]["known_matched_profit_sol"] is None
    assert report["research"]["wallet_profit_verified"] is False
    assert report["research"]["history_complete"] is False
    assert report["evidence_status"] == "partial"
    assert report["policy"] != "MATCH"
    assert report["metrics"]["profit_sol"]["status"] == "unknown"
    assert all(event.get("classification") == "unknown" for event in report["events"] if event["kind"] in ("buy", "sell"))
    assert all(token["safe"] is None and token["status"] != "SAFE" for token in report["token_risk"])
    saved_candidate = next(cohort for cohort in state["discovery_cohorts"] if cohort["id"] == cohort_id)["candidates"][0]
    assert saved_candidate["observed_profit_sol"] is None


def test_setup_scan_resume_preserves_checkpoint_and_adds_only_bounded_tranche(session, monkeypatch):
    import scanner.collector as collector
    client, app, _ = session
    seen_limits = []
    checkpoint = {"transactions": {str(index): {} for index in range(20)}, "credits": 30}

    async def interrupted_collection(gateway, store, address, start, end, limits, **options):
        seen_limits.append(dict(limits))
        if len(seen_limits) == 1:
            raise collector.CollectionPaused("Native metadata temporarily unavailable.", deepcopy(checkpoint))
        assert options["checkpoint"] == checkpoint
        return {"transactions": [], "coverage": {"status": "partial"}, "evidence": []}
    monkeypatch.setattr(collector, "collect_wallet", interrupted_collection)
    assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).status_code == 200
    charge(app.state.store, 30)
    cohort = save_cohort(app.state.store, [candidate()])
    response = client.post(f"/api/discovery/{cohort}/audit", json={})
    identifier = response.json()["scan_id"]
    assert wait_record(client, "scans", identifier)["status"] == "paused"
    assert client.post(f"/api/scans/{identifier}/resume", json={}).status_code == 200
    assert wait_record(client, "scans", identifier)["status"] == "completed"
    assert seen_limits[0]["transaction_limit"] == 20
    assert seen_limits[0]["wallet_credit_limit"] == 30
    assert seen_limits[1]["transaction_limit"] == 40
    assert seen_limits[1]["wallet_credit_limit"] == 60
    assert client.get("/api/usage").json()["cap"] == 200
    assert client.get("/api/state").json()["provider"]["free_plan_confirmed"] is False


def test_exhausted_setup_scan_cannot_resume_into_unverified_monthly_budget(session):
    client, app, _ = session
    assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).status_code == 200
    charge(app.state.store, 200)
    identifier = "b" * 32
    app.state.store.put("scans", identifier, {"id": identifier, "status": "paused", "budget_mode": "setup-pilot"})
    response = client.post(f"/api/scans/{identifier}/resume", json={})
    assert response.status_code == 409
    assert "200-credit" in response.json()["detail"]
    assert app.state.store.get("scans", identifier)["status"] == "paused"


@pytest.mark.parametrize("reason,continues", [
    ("Unsupported transaction version is archived but cannot be decoded.", True),
    ("Paused by user; archived work is retained.", False),
    ("Free disk space is below the configured reserve.", False),
    ("Free application credit cap reached, including pending requests.", False),
    ("Provider requested extended rate-limit backoff; resume later.", False),
])
def test_pilot_skips_local_version_gap_but_preserves_global_stop_boundaries(session, monkeypatch, reason, continues):
    import scanner.collector as collector
    from tests.test_discovery import WALLET
    client, app, _ = session
    visited = []
    gap_checkpoint = {"transactions": {}, "credits": 2, "gaps": [{"reason": reason, "signature": "unsupported-record"}]}
    partial = {"transactions": [], "coverage": {"status": "partial", "history_scope_complete": False,
               "missing_records": gap_checkpoint["gaps"]}, "evidence": []}

    async def wallet_scoped_gap(gateway, store, address, start, end, limits, **options):
        visited.append(address)
        if address == ADDRESS:
            raise collector.CollectionPaused(reason, deepcopy(gap_checkpoint), deepcopy(partial))
        return {"transactions": [], "coverage": {"status": "partial", "history_scope_complete": False}, "evidence": []}
    monkeypatch.setattr(collector, "collect_wallet", wallet_scoped_gap)
    assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).status_code == 200
    charge(app.state.store, 2)
    cohort = save_cohort(app.state.store, [candidate(), candidate(WALLET)])
    response = client.post(f"/api/discovery/{cohort}/audit", json={})
    assert response.status_code == 200
    scan = wait_record(client, "scans", response.json()["scan_id"])
    if continues:
        assert scan["status"] == "completed"
        assert visited == [ADDRESS, WALLET]
        assert scan["pilot_wallet_checkpoints"][ADDRESS] == gap_checkpoint
        assert scan["pilot_scope_notes"][ADDRESS] == reason
        assert scan["progress"]["wallets_completed"] == 2
        reports = client.get("/api/state").json()["reports"]
        assert len(reports) == 2
        assert all(report["evidence_status"] == "partial" and report["policy"] != "MATCH" for report in reports)
        first = next(report for report in reports if report["address"] == ADDRESS)
        assert first["coverage"]["history_scope_complete"] is False
        assert first["coverage"]["missing_records"] == gap_checkpoint["gaps"]
    else:
        assert scan["status"] == "paused"
        assert visited == [ADDRESS]
        assert scan["checkpoint"]["wallet_index"] == 0
        assert scan["checkpoint"]["collector"] == gap_checkpoint
        assert scan["reason"] == reason


def test_successful_swap_replacement_keeps_sibling_unresolved_native_flows(session, monkeypatch):
    import scanner.collector as collector
    client, app, _ = session
    path = Path(__file__).parent / "fixtures" / "mainnet-pumpswap-buy-exact-quote.json"
    entry = json.loads(path.read_text())
    wallet = "4drEkXDZhjun3vjZmz1g7pQGM7kxANQbDuD9jtPZwzJZ"
    now = datetime.now(timezone.utc)
    # Exercise app window selection with the independently checked fixture's
    # structure, keeping this offline orchestration regression independent of age.
    entry["raw"]["blockTime"] = int((now - timedelta(days=1)).timestamp())
    entry["evidence_hash"] = app.state.store.archive(entry["raw"])
    for balance in entry["raw"]["meta"]["postTokenBalances"]:
        if balance.get("owner") == wallet:
            cache_mint(app.state.store, balance["mint"], None, now.isoformat())

    async def observed_swap_with_extra_flows(gateway, store, address, start, end, limits, **options):
        return {"transactions": [deepcopy(entry)], "coverage": {"status": "partial", "history_scope_complete": False},
                "evidence": [{"hash": entry["evidence_hash"], "kind": "transaction"}]}
    monkeypatch.setattr(collector, "collect_wallet", observed_swap_with_extra_flows)
    assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).status_code == 200
    cohort = save_cohort(app.state.store, [candidate(wallet)])
    response = client.post(f"/api/discovery/{cohort}/audit", json={})
    assert response.status_code == 200
    assert wait_record(client, "scans", response.json()["scan_id"])["status"] == "completed"
    report = client.get("/api/state").json()["reports"][0]
    buys = [event for event in report["events"] if event["kind"] == "buy"]
    assert len(buys) == 1 and buys[0]["amount_sol"] == "0.25"
    assert [event["amount_sol"] for event in report["events"] if event["kind"] == "capital"] == ["0.0025", "0.001"]
    assert not [event for event in report['events'] if event['kind'] == 'unsupported']
    assert buys[0]['native_cash_role_state'] == 'UNKNOWN'
    assert all(event['economic_role'] == 'unknown' for event in report['events'] if event['kind'] == 'capital')
    assert len([event for event in report["events"] if event["kind"] == "fee"]) == 1
    assert report["coverage"]["swap_reconstruction"]["unresolved_transactions"] == 1
    assert report["evidence_status"] == "partial" and report["policy"] != "MATCH"
    assert report["metrics"]["profit_sol"]["status"] == "unknown"
    assert report["research"]["unresolved_transactions"] == 2
    assert report['research']['conditional_observed_lot_profit_sol'] is None
    assert report['research']['observed_profit_sol'] is None
    assert report['research_assessment']['state'] == 'current'
    assert any(finding['title'] == 'Native monetary roles remain unresolved' for finding in report['research']['risk_findings'])


@pytest.mark.parametrize("meets_anchor", [False, True])
def test_mint_risk_requires_finalized_anchor_and_archives_requested_mint_with_pool_evidence(session, monkeypatch, meets_anchor):
    import scanner.collector as collector
    import scanner.providers as providers
    from scanner.decoder import TOKEN_IDS
    from scanner.investigation import WSOL
    client, app, _ = session
    entry = json.loads((Path(__file__).parent / "fixtures" / "mainnet-pumpswap-buy-exact-quote.json").read_text())
    wallet = "4drEkXDZhjun3vjZmz1g7pQGM7kxANQbDuD9jtPZwzJZ"
    now = datetime.now(timezone.utc)
    entry["raw"]["blockTime"] = int((now - timedelta(days=1)).timestamp())
    snapshot_slot = entry["raw"]["slot"] + 10
    mint = next(balance["mint"] for balance in entry["raw"]["meta"]["postTokenBalances"] if balance.get("owner") == wallet and balance["mint"] != WSOL)
    entry["evidence_hash"] = app.state.store.archive(entry["raw"])
    pool_hash = app.state.store.archive({"provider": "geckoterminal", "observed_at": now.isoformat(), "liquidity_usd": "123000"})
    requests = []
    def response(request):
        body = json.loads(request.content)
        requests.append(body)
        raw = {"context": {"slot": snapshot_slot if meets_anchor else snapshot_slot - 1},
               "value": {"owner": sorted(TOKEN_IDS)[0], "data": {"parsed": {"type": "mint", "info": {
                         "mintAuthority": None, "freezeAuthority": None, "supply": "1000", "decimals": 6}}}}}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": raw})
    monkeypatch.setattr(providers, "Gateway", lambda *args, **kwargs: Gateway(*args, **kwargs, transport=httpx.MockTransport(response)))
    async def observed_golden(gateway, store, address, start, end, limits, **options):
        return {"transactions": [deepcopy(entry)], "snapshot": {"slot": snapshot_slot},
                "coverage": {"status": "partial"}, "evidence": [{"hash": entry["evidence_hash"], "kind": "transaction"}]}
    monkeypatch.setattr(collector, "collect_wallet", observed_golden)
    assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).status_code == 200
    identifier = save_cohort(app.state.store, [candidate(wallet)])
    cohort = app.state.store.get("discovery_cohorts", identifier)
    cohort["universe"].append({"selected": True, "base_token_address": mint, "quote_token_address": WSOL,
                              "evidence_hash": pool_hash, "observed_at": now.isoformat(), "liquidity_usd": "123000"})
    app.state.store.put("discovery_cohorts", identifier, cohort)
    response = client.post(f"/api/discovery/{identifier}/audit", json={})
    assert wait_record(client, "scans", response.json()["scan_id"])["status"] == "completed"
    report = client.get("/api/state").json()["reports"][0]
    risk = next(risk for risk in report["token_risk"] if risk["mint"] == mint)
    assert len(requests) == 1 and requests[0]["method"] == "getAccountInfo"
    assert requests[0]["params"] == [mint, {"encoding": "jsonParsed", "commitment": "finalized", "minContextSlot": snapshot_slot}]
    cached = app.state.store.get("mint_risk_observations", mint)
    envelope = app.state.store.evidence(cached["hash"])
    assert envelope["method"] == "getAccountInfo" and envelope["address"] == mint
    assert envelope["commitment"] == "finalized" and envelope["observed_at"]
    assert envelope["result"]["context"]["slot"] == (snapshot_slot if meets_anchor else snapshot_slot - 1)
    if meets_anchor:
        assert risk["gates"]["mint_authority"]["state"] == "PASS"
        assert risk["gates"]["current_liquidity"]["state"] == "PASS"
        assert set(risk["evidence"]) == {cached["hash"], pool_hash}
        assert set(risk["gates"]["current_liquidity"]["evidence"]) == {cached["hash"], pool_hash}
    else:
        assert risk["gates"]["mint_authority"]["state"] == "UNKNOWN"
        assert risk["gates"]["current_liquidity"]["state"] == "UNKNOWN"
    assert risk["safe"] is None and report["policy"] != "MATCH"


def test_native_checkpoint_reference_keeps_state_compact_and_resumes_saved_cursor_across_restart(tmp_path, monkeypatch):
    import hashlib
    import scanner.collector as collector
    checkpoint = None
    visits = []
    async def durable_native_gap(gateway, store, address, start, end, limits, **options):
        nonlocal checkpoint
        visits.append(address)
        if len(visits) == 1:
            start_ts = int(datetime.fromisoformat(start).timestamp())
            end_ts = int(datetime.fromisoformat(end).timestamp())
            checkpoint = {"version": "native-collector-v1", "address": address, "start": start_ts, "end": end_ts,
                          "accounts": {address: {"cursor": "retained-native-signature-cursor"}}, "transactions": {}, "credits": 3,
                          "large_retained_evidence": "retained-marker-" * 5000}
            identifier = hashlib.sha256(f"{address}:{start_ts}:{end_ts}".encode()).hexdigest()
            store.put("collector_checkpoints", identifier, checkpoint)
            options["progress"]({"stage": "Retaining native cursor", "pages": 1, "transactions": 0, "credits": 3, "checkpoint": checkpoint})
            raise collector.CollectionPaused("Native metadata temporarily unavailable.", checkpoint)
        assert options["checkpoint"] == checkpoint
        assert options["checkpoint"]["accounts"][address]["cursor"] == "retained-native-signature-cursor"
        return {"transactions": [], "coverage": {"status": "partial"}, "evidence": []}
    monkeypatch.setattr(collector, "collect_wallet", durable_native_gap)
    directory = tmp_path / "data"
    with local_session(directory) as (client, app):
        assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).status_code == 200
        cohort = save_cohort(app.state.store, [candidate()])
        response = client.post(f"/api/discovery/{cohort}/audit", json={})
        scan_id = response.json()["scan_id"]
        scan = wait_record(client, "scans", scan_id)
        assert scan["status"] == "paused"
        assert "collector_ref" in scan["checkpoint"] and "collector" not in scan["checkpoint"]
        state = client.get("/api/state")
        assert "retained-marker-" not in state.text and len(state.content) < 20000
        assert app.state.store.get("collector_checkpoints", scan["checkpoint"]["collector_ref"]) == checkpoint
    with local_session(directory) as (client, app):
        assert client.post("/api/provider/key", json={"api_key": TEST_KEY}).status_code == 200
        assert client.post(f"/api/scans/{scan_id}/resume", json={}).status_code == 200
        assert wait_record(client, "scans", scan_id)["status"] == "completed"
        assert visits == [ADDRESS, ADDRESS]
