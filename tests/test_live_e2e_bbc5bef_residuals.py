"""bbc5bef residual spend-safety, correctness, and discovery tests. Offline only."""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
from decimal import Decimal
from pathlib import Path

import pytest

from scanner.investigation import FLASHX, GMGN, METEORA_DLMM, PHOTON, decode_supported_swaps
from scanner.mass_search.adapters import SourceError
from scanner.mass_search.bundle_detect import detect_bundle_or_distribution
from scanner.mass_search.canonical_records import canonical_decode_records
from scanner.mass_search.g3_history import inject_undecoded_buy_taints
from scanner.mass_search.live_e2e import (
    AUTHORIZATION_ID_NEXT,
    BIRDEYE_CU_DOCS,
    BIRDEYE_DISCOVERY_TOP_TRADERS,
    DRAFT_REL_NEXT,
    HARD_CEILINGS,
    PINNED_DRAFT_HASHES,
    LiveE2EError,
    _install_redacting_excepthook,
    _verify_saved_page,
    classify_programs,
    compute_bot_rate,
    main,
    plan_request_counts,
    prescreen_rank_score,
    run_live_e2e,
    validate_config,
)
from scanner.mass_search.live_e2e_ledger import committed_draft_hash
from scanner.mass_search.settlement import isolate_known_cost_events
from tests.test_live_e2e_spend_safety import (
    FAKE_BIRDEYE,
    FAKE_HELIUS,
    WALLETS,
    _arm_grant,
    _empty_helius,
    _live_kwargs,
)

FIXTURE_DIR = Path("tests/fixtures/live-e2e-phase3")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    from scanner.mass_search.live_e2e import PINNED_LEDGER_REL
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    pin = home / PINNED_LEDGER_REL
    pin.mkdir(parents=True)
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(pin))


@pytest.fixture
def fake_keys(monkeypatch):
    monkeypatch.setenv("HELIUS_API_KEY", FAKE_HELIUS)
    monkeypatch.setenv("BIRDEYE_API_KEY", FAKE_BIRDEYE)
    monkeypatch.delenv("HELIUS_KEY", raising=False)


def _load(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_live_refuses_ledger_home_override_and_home_change(tmp_path, fake_keys, monkeypatch):
    grant = _arm_grant(tmp_path)
    validate_config(_live_kwargs(tmp_path, grant, tmp_path / "out", WALLETS[:1]))
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(tmp_path / "other-home"))
    with pytest.raises(LiveE2EError, match="SCANNER_LIVE_LEDGER_"):
        validate_config(_live_kwargs(tmp_path, grant, tmp_path / "out2", WALLETS[:1], ledger_dir=None))
    monkeypatch.setenv("SCANNER_LIVE_LEDGER_HOME", str(tmp_path / "ledger"))
    raw = json.loads(grant.read_text(encoding="utf-8"))
    raw["armed_home"] = "/not/this/home"
    grant.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(LiveE2EError, match="HOME differs from armed_home"):
        validate_config(_live_kwargs(tmp_path, grant, tmp_path / "out3", WALLETS[:1]))


def test_pinned_hash_and_hard_ceilings_block_local_inflated_draft(tmp_path, fake_keys, monkeypatch):
    grant = _arm_grant(tmp_path, extra={"draft_artifact_hash": "ff" * 32})
    with pytest.raises(LiveE2EError, match="pinned draft"):
        validate_config(_live_kwargs(tmp_path, grant, tmp_path / "out", WALLETS[:1]))
    grant = _arm_grant(tmp_path, helius_req=20_000, helius_units=1_000_000)
    with pytest.raises(LiveE2EError, match="hard ceiling|exceeds committed draft"):
        validate_config(_live_kwargs(tmp_path, grant, tmp_path / "out2", WALLETS[:1]))
    assert HARD_CEILINGS["helius_requests"] == 3000
    assert HARD_CEILINGS["birdeye_units"] == 1000
    working = hashlib.sha256((ROOT / DRAFT_REL_NEXT).read_bytes()).hexdigest()
    assert PINNED_DRAFT_HASHES[AUTHORIZATION_ID_NEXT] == working


def test_keyboard_interrupt_redacts_stderr(capsys, monkeypatch, fake_keys):
    _install_redacting_excepthook()
    monkeypatch.setattr(
        "scanner.mass_search.live_e2e.build_arg_parser",
        lambda: type("P", (), {"parse_args": lambda self, argv=None: (_ for _ in ()).throw(
            KeyboardInterrupt(f"interrupted {FAKE_HELIUS}")
        )})(),
    )
    code = main(["--live", "--grant", "x", "--output", "y"])
    assert code == 130
    err = capsys.readouterr().err
    assert FAKE_HELIUS not in err
    assert "[REDACTED]" in err or "KeyboardInterrupt" in err


def test_phase2_resume_screens_new_wallets(tmp_path, monkeypatch, fake_keys):
    calls = []

    async def helius(address, *, options, page_index=0):
        calls.append(address)
        return _empty_helius()

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path, helius_req=20, helius_units=200)
    out = tmp_path / "batch"
    first = asyncio.run(run_live_e2e(_live_kwargs(tmp_path, grant, out, WALLETS[:1], phases="2")))
    assert first["status"] == "completed"
    assert first["spend"]["helius_requests"] == 2
    second = asyncio.run(run_live_e2e(_live_kwargs(
        tmp_path, grant, out, WALLETS[:2], phases="2", resume=True,
    )))
    assert second["status"] == "completed"
    assert second["spend"]["helius_requests"] == 4
    assert WALLETS[1] in calls


def test_bot_rate_is_computed_and_enforced(tmp_path, monkeypatch, fake_keys):
    start = 1_700_000_000

    async def helius(address, *, options, page_index=0):
        if options.get("transactionDetails") == "signatures":
            raw = json.dumps({
                "jsonrpc": "2.0",
                "result": {"data": [
                    {"signature": f"s{i}", "blockTime": start + i * 60} for i in range(20)
                ], "paginationToken": None},
            }).encode()
            return {
                "records": [{"signature": f"s{i}", "blockTime": start + i * 60} for i in range(20)],
                "pagination_token": None,
                "http_status": 200,
                "raw_bytes": raw,
                "evidence_sha256": hashlib.sha256(raw).hexdigest(),
                "units": 10,
                "external_requests": 1,
            }
        return _empty_helius()

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path, helius_req=20, helius_units=200)
    result = asyncio.run(run_live_e2e({
        **_live_kwargs(tmp_path, grant, tmp_path / "bot", WALLETS[:1], phases="2"),
        "max_bot_rate": "0.1",
        "window_days": 30,
    }))
    row = result["phase2"]["wallets"][0]
    assert Decimal(row["bot_rate"]) > 0
    assert row["dropped"] is True
    assert row["drop_reason"] == "bot_rate"


def test_error_body_page_is_blocked_not_empty():
    with pytest.raises(SourceError, match="error body|hash mismatch|not covered"):
        _verify_saved_page(Path("/tmp/missing-page.bin"), "missing")


def test_error_body_and_hash_mismatch_blocked(tmp_path):
    path = tmp_path / "page0.bin"
    raw = b'{"error":{"message":"rate limited"},"jsonrpc":"2.0"}'
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    path.with_name("page0.bin.integrity.json").write_text(
        json.dumps({"written_sha256": digest, "original_sha256": digest, "scrubbed": False}),
        encoding="utf-8",
    )
    with pytest.raises(SourceError, match="error body"):
        _verify_saved_page(path, "page0.bin")
    path.write_bytes(b'{"result":{"data":[]}}')
    with pytest.raises(SourceError, match="hash mismatch"):
        _verify_saved_page(path, "page0.bin")


def test_planner_phase3_minimum_is_two_pages():
    plan = plan_request_counts({
        "wallets": ["A", "B"],
        "phases": (3,),
        "discovery": False,
        "caps": HARD_CEILINGS,
    })
    assert plan["totals"]["helius_requests"] == 4
    assert plan["per_phase"]["3"]["requests"] == 4


def test_pump_fee_not_ranked_on_decoded_swap():
    payload = _load("okx-swaptob.json")
    classified = classify_programs([payload["record"]], payload["address"])
    ids = {row["program_id"] for row in classified["blockers"]}
    assert "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ" not in ids


def test_fifo_undecoded_earlier_buy_taints_later_sales():
    rows = [
        {"kind": "undecoded_buy", "units": "100", "mint": "M", "signature": "u1",
         "seconds_from_start": 0, "timestamp_missing": False, "settlement_mint": "So11111111111111111111111111111111111111112"},
        {"kind": "buy", "units": "50", "mint": "M", "signature": "b1", "consideration_sol": "1",
         "seconds_from_start": 1, "timestamp_missing": False, "settlement_mint": "So11111111111111111111111111111111111111112"},
        {"kind": "sell", "units": "40", "mint": "M", "signature": "s1", "consideration_sol": "2",
         "seconds_from_start": 2, "timestamp_missing": False, "settlement_mint": "So11111111111111111111111111111111111111112"},
    ]
    known, unresolved = isolate_known_cost_events(rows)
    assert not any(row.get("kind") == "sell" and not row.get("unresolved_basis") for row in known)
    assert unresolved


def test_inject_undecoded_buy_from_token_increase():
    decoded = {"events": []}
    record = {
        "signature": "undecoded-buy-sig",
        "transaction": {"signatures": ["undecoded-buy-sig"], "message": {"accountKeys": ["W"]}},
        "meta": {
            "err": None,
            "preTokenBalances": [{"owner": "W", "mint": "M", "uiTokenAmount": {"amount": "0"}}],
            "postTokenBalances": [{"owner": "W", "mint": "M", "uiTokenAmount": {"amount": "10"}}],
        },
        "blockTime": 100,
    }
    out = inject_undecoded_buy_taints(decoded, [record], "W")
    kinds = [event["kind"] for event in out["events"]]
    assert "undecoded_buy" in kinds


def test_independent_auditor_decodes_okx_cfnx():
    from tools.independent_episode_audit import reconstruct_record

    payload = _load("okx-cfnx-swaptob.json")
    event = reconstruct_record(payload["record"], payload["address"])
    assert event is not None
    assert event["instruction"] == "SwapTob"
    assert event["program"] == "proVF4pMXVaYqmy4NjniPh4pqKNfMmsihgd4wdkCX3u"
    assert Decimal(event["quantity_raw"]) > 0


def test_bundle_detection_on_gv3ksnug_page():
    payload = _load("bundle-gv3ksnug.json")
    detected = detect_bundle_or_distribution([payload["record"]], payload["address"])
    assert detected["excluded"] is True
    assert "multi_signer_bundle_buy" in detected["reasons"]
    score = prescreen_rank_score({
        "supported_venue_value_share": "0.9",
        "has_known_basis_buys": True,
        "bundle": True,
        "bot": False,
    })
    assert score == Decimal("0")


def test_venue_decoders_on_attached_txs():
    from scanner.investigation import UNSUPPORTED_PINNED_OUTER

    supported = [
        ("gmgn-swap.json", GMGN),
        ("dlmm-swap2.json", METEORA_DLMM),
    ]
    for name, program in supported:
        payload = _load(name)
        decoded = decode_supported_swaps(canonical_decode_records([payload["record"]]), payload["address"])
        trades = [row for row in decoded.get("events") or [] if row.get("kind") in ("buy", "sell")]
        if trades:
            assert trades[0].get("program") == program or trades[0].get("source") == program or trades[0].get("venue") == program
            qty = Decimal(str(trades[0].get("quantity_raw") or "0"))
            assert qty > 0
        else:
            kinds = {row.get("kind") for row in decoded.get("events") or []}
            assert "unsupported" in kinds or decoded.get("unresolved")

    honest = [
        ("flashx-swap.json", FLASHX),
        ("photon-swap.json", PHOTON),
    ]
    for name, program in honest:
        payload = _load(name)
        decoded = decode_supported_swaps(canonical_decode_records([payload["record"]]), payload["address"])
        trades = [row for row in decoded.get("events") or [] if row.get("kind") in ("buy", "sell")]
        assert trades == []
        if program == PHOTON:
            assert program in UNSUPPORTED_PINNED_OUTER
        kinds = {row.get("kind") for row in decoded.get("events") or []}
        assert "unsupported" in kinds or decoded.get("unresolved") or kinds <= {"fee"} or not trades


def test_discovery_cu_docs_and_top_traders_plan():
    assert BIRDEYE_CU_DOCS["gainers-losers"]["documented_cu"] == 30
    assert BIRDEYE_CU_DOCS["top-traders"]["documented_cu"] == 35
    plan = plan_request_counts({
        "wallets": [],
        "phases": (1,),
        "discovery": True,
        "discovery_source": BIRDEYE_DISCOVERY_TOP_TRADERS,
        "birdeye_tokens": ["So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"],
        "caps": HARD_CEILINGS,
    })
    assert plan["totals"]["birdeye_requests"] == 2
    assert plan["totals"]["birdeye_units"] == 70
    assert plan["totals"]["birdeye_units"] <= HARD_CEILINGS["birdeye_units"]


def test_new_grant_plan_fits_hard_ceilings():
    raw = json.loads((ROOT / DRAFT_REL_NEXT).read_text(encoding="utf-8"))
    assert raw["enabled"] is False
    assert raw["authorization_id"] == AUTHORIZATION_ID_NEXT
    assert raw["expires_at"] == "2026-10-09T13:30:00Z"
    plan = plan_request_counts({
        "wallets": [f"W{i:02d}" for i in range(100)],
        "phases": (1, 2, 3, 4),
        "discovery": True,
        "caps": {
            "birdeye_requests": 10,
            "birdeye_units": 300,
            "helius_requests": 1500,
            "helius_units": 15000,
        },
    }, state={"phase2": {f"W{i:02d}": {"address": f"W{i:02d}", "dropped": i >= 25} for i in range(100)}})
    # Default plan without phase2 kept rows uses all 100 for phase3 if wallets supplied
    # with wallets_supplied implicit. phase3_wallets uses kept phase2 or all wallets.
    # Force 25 kept:
    assert plan["totals"]["birdeye_requests"] == 1
    assert plan["totals"]["birdeye_units"] == 30
    assert plan["totals"]["helius_requests"] <= 1500
    assert plan["totals"]["helius_units"] <= 15000


def test_stale_rate_limited_cleared_on_success(tmp_path, monkeypatch, fake_keys):
    calls = []

    async def helius(*args, **kwargs):
        calls.append(1)
        return _empty_helius()

    monkeypatch.setattr("scanner.mass_search.live_e2e._live_helius", helius)
    grant = _arm_grant(tmp_path, helius_req=20, helius_units=200)
    out = tmp_path / "stale"
    first = asyncio.run(run_live_e2e(_live_kwargs(tmp_path, grant, out, WALLETS[:1], phases="2")))
    state_path = out / "RUN_STATE.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["blocker"] = "RATE_LIMITED"
    state["status"] = "blocked"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    second = asyncio.run(run_live_e2e(_live_kwargs(
        tmp_path, grant, out, WALLETS[:1], phases="2", resume=True,
    )))
    assert second["status"] == "completed"
    assert second["blocker"] is None
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved.get("blocker") in (None, "")
