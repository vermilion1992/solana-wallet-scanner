"""Adapted Grok Bot 2fe60bd minimal reproductions (offline, synthetic).

Run from repo root:
  env -u HELIUS_API_KEY -u BIRDEYE_API_KEY .venv/bin/python scripts/minimal_repros_2fe60bd.py
"""
from __future__ import annotations

import sys
import tempfile
import threading
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scanner.mass_search.history_ingest import record_next_capture_replay
from scanner.mass_search.qualification_gates import certificate_comparison_proof, reconcile_saved_profile
from scanner.mass_search.research_profile import build_research_profile, default_filters, independently_audited
from scanner.storage import Store
from tests.test_grok_bot_2fe60bd_repros import (
    NOW,
    Recorder,
    _a6ps,
    _eligible_report,
    _grant,
    _gtfo,
    _quota,
    _req,
    _run,
)
from tests.test_chatgpt_review_2026_10_07_rereview import _eligible_report as _report
from scanner.mass_search.history_ingest import load_next_capture_draft, run_next_capture_offline


def show(fid, expected, actual):
    print(f"[{fid}] expected: {expected} | actual: {actual}")


def main():
    # B1
    report = _report()
    report["independent_audit"]["independently_audited_episode_net"] = "999"
    report["independent_audit"]["auditor_confirmation"] = "auditor confirms within 2 lamports: 999 SOL"
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    show(
        "B1 CERT-HEADLINE",
        "proof False / not audited / no lead",
        f"proof={certificate_comparison_proof(report['independent_audit'], report['completed_episode_ledger'])} "
        f"audited={independently_audited(report, profile)} level={profile['qualification_level']['level']} "
        f"confirmation_shown={(profile.get('independent_audit') or {}).get('auditor_confirmation')!r}",
    )

    # B2
    from fastapi.testclient import TestClient
    from scanner.app import create_app

    data = Path(tempfile.mkdtemp())
    store = Store(data)
    report = _report()
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    report["completed_episode_ledger"] = []
    store.put("reports", "x", {
        **report,
        "id": "x",
        "source": "mass-search",
        "visible_report": True,
        "research_profile": profile,
        "created_at": "2026-10-07T00:00:00Z",
    })
    with TestClient(create_app(data, "tok"), base_url="http://127.0.0.1:8765") as client:
        headers = {"x-launch-token": "tok"}
        client.get("/api/bootstrap", headers=headers)
        got = client.get("/api/reports/x", headers=headers).json()
        exported = client.get("/api/export/reports/x.json", headers=headers).json()
    show(
        "B2 STATE-EXPORT",
        "top-level independent_audit null/non-certifying like research_profile",
        f"GET top independently_audited={(got.get('independent_audit') or {}).get('independently_audited')} "
        f"GET research_profile.independent_audit={got.get('research_profile', {}).get('independent_audit')} "
        f"export top independently_audited={(exported.get('independent_audit') or {}).get('independently_audited')}",
    )

    # B3
    report = _report()
    profile = build_research_profile(deepcopy(report), filters=default_filters())
    report2 = deepcopy(report)
    report2["independent_audit"] = None
    reconciled = reconcile_saved_profile(report2, deepcopy(profile))
    fresh = build_research_profile(deepcopy(report2), filters=default_filters())
    show(
        "B3 STATE-AUDIT-REMOVED",
        f"reconciled == fresh ({independently_audited(report2, fresh)}, {fresh['qualification_level']['level']})",
        f"reconciled audited={independently_audited(report2, reconciled)} level={reconciled['qualification_level']['level']}",
    )

    # B4
    draft = load_next_capture_draft()
    future = (NOW + timedelta(hours=6)).isoformat().replace("+00:00", "Z")
    transport = Recorder([{"pagination_token": "g2"}])
    result = _run(
        Store(Path(tempfile.mkdtemp())),
        _req(_gtfo(draft)),
        transport,
        draft=draft,
        grant=_grant(draft, current_remaining_quota_confirmation=_quota(draft, confirmed_at=future)),
    )
    show("B4 CAP-E-FUTURE-CONFIRMED_AT", "refused, 0 transport calls", f"code={result.get('code')} transport_calls={len(transport.calls)}")

    # B5
    transport = Recorder([{"pagination_token": "g2"}])
    result = _run(
        Store(Path(tempfile.mkdtemp())),
        _req(_gtfo(draft)),
        transport,
        draft=draft,
        grant=_grant(
            draft,
            current_remaining_quota_confirmation=_quota(draft, authorization_id="some-other-grant", execution_artifact_hash="0" * 64),
        ),
    )
    show("B5 CAP-E-QUOTA-BINDING", "refused, 0 transport calls", f"code={result.get('code')} transport_calls={len(transport.calls)}")

    # B6
    store = Store(Path(tempfile.mkdtemp()))
    transport = Recorder([
        {"pagination_token": "g2", "response_id": "R"},
        {"pagination_token": "a2", "response_id": "R"},
        {"pagination_token": "g3"},
    ])
    first = _run(store, _req(_gtfo(draft)), transport, draft=draft)
    stale = {"response_id": first["state"]["last_dispatch"]["response_id"]}
    accepted = record_next_capture_replay(first["state"], stale)
    store.put("next_capture_offline_state", draft["authorization_id"], first["state"])
    second = _run(store, _req(_a6ps(draft)), transport, draft=draft)
    accepted_again = record_next_capture_replay(second["state"], stale)
    show(
        "B6 CAP-B-RECEIPT-BINDING",
        "stale page-less receipt rejected; runner-minted id; no third dispatch from stale receipt",
        f"receipt_accepted={accepted} receipt_accepted_again={accepted_again} "
        f"transport_calls={len(transport.calls)} minted_id={first['state']['last_dispatch']['response_id']!r}",
    )

    # B7
    transport = Recorder([{"pagination_token": "x"}, {"pagination_token": "y"}])
    run_next_capture_offline(draft=draft, requested=_req(_gtfo(draft)), grant=_grant(draft), transport=transport, store=None, now=NOW)
    run_next_capture_offline(draft=draft, requested=_req(_gtfo(draft)), grant=_grant(draft), transport=transport, store=None, now=NOW)
    show("B7 CAP-A-NO-STORE", "refused, 0 transport calls", f"transport_calls={len(transport.calls)}")

    # B8
    path = Path(tempfile.mkdtemp())
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
    threads = [threading.Thread(target=lambda: _run(Slow(path), _req(_gtfo(draft)), transport, draft=draft)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    stored = Store(path).get("next_capture_offline_state", draft["authorization_id"])
    show(
        "B8 CAP-A-CONCURRENCY",
        "1 transport call and requests_used == transport calls",
        f"transport_calls={len(transport.calls)} stored requests_used={(stored or {}).get('requests_used')}",
    )


if __name__ == "__main__":
    main()
