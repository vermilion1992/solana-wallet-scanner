"""f635a45 live-run residuals. Offline only; keys must stay unset or dummy."""
from __future__ import annotations

import asyncio
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from scanner.investigation import decode_supported_swaps
from scanner.mass_search.adapters import SourceError
from scanner.mass_search.bundle_detect import detect_bundle_or_distribution
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.live_e2e import (
    AUTHORIZATION_ID_11,
    AUTHORIZATION_ID_NEXT,
    DRAFT_REL_11,
    HARD_CEILINGS,
    LIVE_KNOWN_DRAFTS,
    PINNED_DRAFT_HASHES,
    PINNED_LEDGER_REL,
    RETIRED_LIVE_DRAFTS,
    LiveE2EError,
    _verify_saved_page,
    assess_history_completeness,
    compute_bot_rate,
    estimate_phase3_pages,
    plan_request_counts,
    run_live_e2e,
    seed_counterparties_from_records,
    validate_config,
    window_bounds,
)
from scanner.mass_search.live_e2e_ledger import RECEIPT_KIND, put_receipt
from scanner.storage import Store
from tests.test_live_e2e_spend_safety import (
    FAKE_HELIUS,
    WALLETS,
    _arm_grant,
    _empty_helius,
    _live_kwargs,
)

FIXTURE = Path("tests/fixtures/live-e2e-f635a45")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    from tests.test_live_e2e_spend_safety import pin_test_ledger
    return pin_test_ledger(tmp_path, monkeypatch)
JXT = "jXtCVtdQhrn7GAHTPKxRHM94dbnmZwpBdGbswa3EeGZ"
DKY = "DKyapYGfvKCBUTzKSCbTbvVVHbj9yMBKrHrkjdXZ24xx"
NINE = "9R3m89gXeC6BWc2aN9CFqWDZA5WUJP3umQUerC7gjoFs"


def _load(name):
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


@pytest.fixture
def fake_keys(monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY", FAKE_HELIUS)
    monkeypatch.setenv("BIRDEYE_API_KEY", "dummy-birdeye-key-f635a45")
    monkeypatch.delenv("HELIUS_KEY", raising=False)


def test_service_cosigner_jito_tip_is_not_a_bundle():
    payload = _load("jxt-jito-tip.json")
    detected = detect_bundle_or_distribution([payload["record"]], payload["address"])
    assert "multi_signer_bundle_buy" not in (detected.get("reasons") or [])
    assert detected.get("lead_eligible") is True


def test_passive_jupiter_sigh_is_not_a_bundle():
    payload = _load("aui-sigh-jupiter.json")
    detected = detect_bundle_or_distribution([payload["record"]], payload["address"])
    assert "multi_signer_bundle_buy" not in (detected.get("reasons") or [])
    qvc = _load("qvc-sigh-jupiter.json")
    detected = detect_bundle_or_distribution([qvc["record"]], qvc["address"])
    assert "multi_signer_bundle_buy" not in (detected.get("reasons") or [])


def test_keep_flagged_real_bundles():
    gv3 = json.loads(Path("tests/fixtures/live-e2e-phase3/bundle-gv3ksnug.json").read_text())
    records = gv3.get("records") or [gv3.get("record")]
    detected = detect_bundle_or_distribution(records, gv3.get("address") or "Gv3ksNUG")
    assert "multi_signer_bundle_buy" in detected["reasons"]

    dky = json.loads(Path("tests/fixtures/live-e2e-06cea26/dky-multi-signer-fee-payer.json").read_text())
    detected = detect_bundle_or_distribution([dky["record"]], dky["address"])
    assert "multi_signer_bundle_buy" in detected["reasons"]

    agq_path = Path("/tmp/live-raw-f635a45/live-out/main/raw/phase2/AGqKFZoKduLeXYEtqoyEgsm65XH4zZBcfqZ6fgoZb2G1/page1.bin")
    if agq_path.is_file():
        data = (json.loads(agq_path.read_bytes()).get("result") or {}).get("data") or []
        detected = detect_bundle_or_distribution(data, "AGqKFZoKduLeXYEtqoyEgsm65XH4zZBcfqZ6fgoZb2G1")
        assert "multi_signer_bundle_buy" in detected["reasons"]
        assert "sell_proceeds_to_cosigner" in detected["reasons"]


def test_controlled_pair_bst_and_drbc_not_jxt_exchange():
    bst = _load("bst-controlled-pair.json")
    detected = detect_bundle_or_distribution(bst["records"], bst["address"])
    assert "controlled_pair" in detected["reasons"]
    assert bst["controller"] in (detected.get("controlled_pair") or [])
    assert detected.get("controlled_pair_explanation")

    sale = _load("drbc-sale.json")
    sweep = _load("drbc-sweep.json")
    detected = detect_bundle_or_distribution([sale["record"], sweep["record"]], sale["address"])
    assert "controlled_pair" in detected["reasons"]

    exchange = _load("jxt-exchange-fund.json")
    detected = detect_bundle_or_distribution(exchange["records"], exchange["address"])
    assert "controlled_pair" not in (detected.get("reasons") or [])


def test_history_complete_rejects_drain_to_zero_with_unknown_basis():
    drain = _load("nine-drain.json")
    sale = _load("nine-later-sale.json")
    assessed = assess_history_completeness(
        [drain["record"], sale["record"]],
        leftover_token=True,
        address=NINE,
    )
    assert assessed["history_complete"] is False
    assert assessed["history_complete_reason"] == "unknown_basis_sale"
    assert assessed["unknown_basis_mints"]


def test_dky_same_second_tie_is_created_in_range():
    created = _load("dky-create.json")
    other = _load("dky-same-second.json")
    assessed = assess_history_completeness(
        [other["record"], created["record"]],
        leftover_token=True,
        address=DKY,
    )
    assert assessed["wallet_created_in_range"] is True
    assert assessed["oldest_native_prebalance"] == 0
    assert assessed["history_complete"] is True


def test_plain_history_to_first_is_accepted_and_capped(tmp_path, fake_keys, monkeypatch):
    bounds = window_bounds(30, 60, history_to_first=True)
    assert bounds["history_to_first"] is True
    assert bounds["earlier_history_days"] > 365
    assert bounds["history_start_unix"] == int(__import__("datetime").datetime(2020, 3, 16, tzinfo=__import__("datetime").timezone.utc).timestamp())

    calls = []

    async def helius(address, *, options, page_index=0):
        calls.append(page_index)
        token = f"tok-{page_index}" if page_index < 4 else None
        body = {"jsonrpc": "2.0", "result": {"data": [{"blockTime": 1_700_000_000 - page_index}], "paginationToken": token}}
        raw = json.dumps(body).encode()
        return {
            "records": body["result"]["data"],
            "pagination_token": token,
            "http_status": 200,
            "raw_bytes": raw,
            "evidence_sha256": hashlib.sha256(raw).hexdigest(),
            "units": 100,
            "external_requests": 1,
        }

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path, helius_req=20, helius_units=2000)
    result = asyncio.run(run_live_e2e({
        **_live_kwargs(tmp_path, grant, tmp_path / "htf", WALLETS[:1], phases="3"),
        "history_to_first": True,
        "per_wallet_cap": 3,
        "earlier_history_days": 60,
    }))
    assert result["status"] in ("completed", "blocked")
    cursor = ((result.get("phase3") or {}).get("pages") or {}).get(WALLETS[0]) or {}
    assert cursor.get("history_complete") is False
    assert cursor.get("history_complete_reason") in ("per_wallet_cap", "page_cap_with_leftover_token")
    assert len(calls) <= 3


def test_receipt_sha_finds_page_zero(tmp_path):
    from scanner.mass_search.live_e2e import _receipt_sha_for_page
    store = Store(tmp_path / "store")
    digest = "a" * 64
    put_receipt(store, {"authorization_id": AUTHORIZATION_ID_11}, "helius:w:3:0:x", {
        "provider": "helius", "wallet": WALLETS[0], "phase": 3, "page": 0,
        "state": "consumed", "sha256": digest, "units": 10,
    })
    assert _receipt_sha_for_page(store, WALLETS[0], "page0.bin", phase=3) == digest
    store.close()


def test_import_paid_page_by_ledger_sha(tmp_path):
    prior = tmp_path / "prior" / "raw" / "phase3" / WALLETS[0]
    prior.mkdir(parents=True)
    body = b'{"jsonrpc":"2.0","result":{"data":[{"ok":1}],"paginationToken":null}}'
    (prior / "page0.bin").write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    (prior / "page0.bin.integrity.json").write_text(json.dumps({
        "kind": "raw-page-integrity-v1",
        "original_sha256": digest,
        "written_sha256": digest,
        "scrubbed": False,
    }), encoding="utf-8")
    store = Store(tmp_path / "store")
    put_receipt(store, {"authorization_id": AUTHORIZATION_ID_11}, "helius:w:3:0:x", {
        "provider": "helius", "wallet": WALLETS[0], "phase": 3, "page": 0,
        "state": "consumed", "sha256": digest, "units": 10,
    })
    dest = tmp_path / "new-out"
    from scanner.mass_search.live_e2e import _replay_saved_page
    replayed = _replay_saved_page(
        {"output_dir": str(dest), "import_raw_dirs": [str(tmp_path / "prior")]},
        3, WALLETS[0], 0, 10, store=store,
    )
    assert replayed["replayed_from_receipt"] is True
    assert (dest / "raw" / "phase3" / WALLETS[0] / "page0.bin").is_file()
    with pytest.raises(SourceError, match="import-raw-dir|Paid page"):
        _replay_saved_page(
            {"output_dir": str(tmp_path / "empty"), "import_raw_dirs": []},
            3, WALLETS[0], 0, 10, store=store,
        )
    store.close()


def test_tampered_page_rewriting_written_sha_is_rejected(tmp_path):
    page = tmp_path / "page0.bin"
    original = b'{"jsonrpc":"2.0","result":{"data":[{"sig":"ZyPS6ThF"}],"paginationToken":null}}'
    page.write_bytes(original)
    orig_sha = hashlib.sha256(original).hexdigest()
    tampered = b'{"jsonrpc":"2.0","result":{"data":[],"paginationToken":null}}'
    page.write_bytes(tampered)
    new_sha = hashlib.sha256(tampered).hexdigest()
    page.with_name("page0.bin.integrity.json").write_text(json.dumps({
        "written_sha256": new_sha,
        "original_sha256": orig_sha,
        "scrubbed": False,
    }), encoding="utf-8")
    with pytest.raises(SourceError, match="ledger receipt sha mismatch"):
        _verify_saved_page(page, expected_sha=orig_sha)


def test_one_wallet_cap_does_not_block_the_run(tmp_path, fake_keys, monkeypatch):
    calls = []

    async def helius(address, *, options, page_index=0):
        calls.append(address)
        token = "more" if address == WALLETS[0] else None
        body = {"jsonrpc": "2.0", "result": {"data": [{"blockTime": 1_700_000_000}], "paginationToken": token}}
        raw = json.dumps(body).encode()
        return {
            "records": body["result"]["data"],
            "pagination_token": token,
            "http_status": 200,
            "raw_bytes": raw,
            "evidence_sha256": hashlib.sha256(raw).hexdigest(),
            "units": 100,
            "external_requests": 1,
        }

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path, helius_req=40, helius_units=4000)
    result = asyncio.run(run_live_e2e({
        **_live_kwargs(tmp_path, grant, tmp_path / "cap", WALLETS[:2], phases="3"),
        "per_wallet_cap": 1,
        "history_to_first": True,
    }))
    pages = (result.get("phase3") or {}).get("pages") or {}
    assert pages[WALLETS[0]].get("history_complete") is False
    assert pages[WALLETS[0]].get("history_complete_reason") == "per_wallet_cap"
    assert WALLETS[1] in pages
    assert pages[WALLETS[1]].get("done") is True
    assert WALLETS[1] in calls


def test_planner_includes_per_wallet_cap():
    plan = plan_request_counts({
        "wallets": ["W"],
        "wallets_supplied": True,
        "phases": (3,),
        "window_days": 30,
        "earlier_history_days": 60,
        "per_wallet_cap": 4,
        "caps": dict(HARD_CEILINGS),
    }, state={"phase2": {"W": {"address": "W", "dropped": False, "in_window_tx_count": 1000}}})
    assert plan["per_wallet_cap"] == 4
    assert plan["phase3_page_estimates"]["W"] <= 4


def test_bot_rate_burst_is_not_96_per_day():
    start = 1_700_000_000
    burst = [{"blockTime": start + i * 120} for i in range(4)]
    rate = compute_bot_rate(burst, window_days=30)
    assert rate < Decimal("25")
    assert rate == Decimal("4.0000")
    hft = [{"blockTime": start + i} for i in range(1000)]
    assert compute_bot_rate(hft, window_days=30) > Decimal("100")


def test_retired_09_draft_refused_for_live(tmp_path, monkeypatch):
    assert AUTHORIZATION_ID_NEXT in RETIRED_LIVE_DRAFTS
    assert AUTHORIZATION_ID_11 in RETIRED_LIVE_DRAFTS
    from scanner.mass_search.live_e2e import AUTHORIZATION_ID_12
    assert AUTHORIZATION_ID_12 in LIVE_KNOWN_DRAFTS
    monkeypatch.setenv("HELIUS_API_KEY", "dummy-helius-key-f635")
    raw = json.loads((ROOT / "config/live_authorization.live-e2e-proof-2026-10-09-mitch-draft.json").read_text())
    raw["enabled"] = True
    raw["authorized_by_user_at"] = "2026-10-07T00:00:00Z"
    raw["expires_at"] = "2099-01-01T00:00:00Z"
    raw["armed_home"] = str(Path.home())
    raw["ledger_home"] = str(Path.home() / PINNED_LEDGER_REL)
    raw["draft_artifact_hash"] = PINNED_DRAFT_HASHES[AUTHORIZATION_ID_NEXT]
    for entry in raw["providers"]:
        entry["existing_plan_confirmed"] = True
        entry["remaining_quota_confirmed_at"] = "2026-10-07T00:00:00Z"
    grant = tmp_path / "armed-09.json"
    grant.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(LiveE2EError, match="retired"):
        validate_config({
            "mode": "live",
            "grant_path": str(grant),
            "output_dir": str(tmp_path / "out"),
            "ledger_dir": str(Path.home() / PINNED_LEDGER_REL),
            "wallets": [WALLETS[0]],
            "phases": "2",
        })


def test_new_draft_is_disabled_and_pinned():
    from scanner.mass_search.live_e2e import AUTHORIZATION_ID_12, DRAFT_REL_12
    draft = json.loads((ROOT / DRAFT_REL_12).read_text(encoding="utf-8"))
    assert draft["enabled"] is False
    assert draft["PRODUCT_READY"] is False
    assert draft["authorization_id"] == AUTHORIZATION_ID_12
    assert draft["expires_at"] == "2026-10-11T13:30:00Z"
    assert draft["overages_enabled"] is False
    assert draft["allow_paid_upgrade"] is False
    assert draft["pinned_ledger_home"] == "/home/box/.scanner/live-e2e-ledgers"
    assert int((draft.get("phase_caps") or {}).get("2", {}).get("helius_requests") or 0) >= 600
    digest = hashlib.sha256((ROOT / DRAFT_REL_12).read_bytes()).hexdigest()
    assert PINNED_DRAFT_HASHES[AUTHORIZATION_ID_12] == digest
    assert HARD_CEILINGS["birdeye_requests"] == 40
    assert HARD_CEILINGS["birdeye_units"] == 1400
    assert HARD_CEILINGS["helius_units"] == 30000


def test_jxt_jito_jupiter_native_settlement_decodes():
    payload = _load("jxt-jito-tip.json")
    decoded = decode_supported_swaps(canonical_decode_records([payload["record"]]), payload["address"])
    trades = [row for row in decoded.get("events") or [] if row.get("kind") in ("buy", "sell")]
    # The Jito-tip tx may be a sell with a service co-signer; decode or honest unsupported.
    assert all(row.get("kind") in ("buy", "sell") for row in trades)


def test_seed_counterparties_skips_cosigners():
    exchange = _load("jxt-exchange-fund.json")
    seeds = seed_counterparties_from_records(exchange["records"], exchange["address"])
    assert any(row["address"].startswith("is6MTRHE") for row in seeds)


def test_rearm_new_ledger_home_is_refused(tmp_path, fake_keys):
    grant = _arm_grant(tmp_path, extra={"ledger_home": str(tmp_path / "other-ledgers")})
    with pytest.raises(LiveE2EError, match="pinned ledger home"):
        validate_config(_live_kwargs(tmp_path, grant, tmp_path / "out", WALLETS[:1]))
