"""Authenticated mass-search HTTP routes. Existing session/CSRF/host guards apply."""
from __future__ import annotations

import json

from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response

from scanner.config import LIMITS
from scanner.storage import EvidenceError

from .adapters import FixtureTraderAdapter, SourceError
from .capability import access_blocker
from .plan import load_default_plan
from .schema import MASS_UNIVERSE_CAPACITY
from .service import MassSearchService
from .universe import synthetic_address


def _service(store):
    return MassSearchService(store)


def _error(exc):
    from .batch import BatchBusy
    if isinstance(exc, BatchBusy):
        raise HTTPException(409, str(exc))
    if isinstance(exc, SourceError):
        raise HTTPException(409, str(exc))
    if isinstance(exc, (ValueError, EvidenceError)):
        raise HTTPException(400, str(exc))
    raise exc


def mass_search_state(store):
    """Compact run summaries only. Never materialise the bulk universe into /api/state.

    Caps, ranked-100 browse, and notes live on /api/mass-search/runs and
    /api/mass-search/ranked-workflow so the shared /api/state budget stays
    under the 20000-byte compact-checkpoint limit.
    """
    try:
        service = MassSearchService(store)
        runs = service.list_runs()
    except Exception:
        runs = []
    return {"runs": runs[:20]}


def install_mass_search_routes(app, store):
    @app.get("/api/mass-search/capability")
    async def capability():
        return _service(store).capability_bundle()

    @app.post("/api/mass-search/preview")
    async def preview(payload: dict | None = None):
        try:
            return _service(store).preview_plan((payload or {}).get("plan"))
        except Exception as exc:
            _error(exc)

    @app.get("/api/mass-search/runs")
    async def list_runs():
        return {"runs": _service(store).list_runs(), "legacy_limits": dict(LIMITS),
                "bulk_capacity": MASS_UNIVERSE_CAPACITY}

    @app.post("/api/mass-search/runs")
    async def create_run(payload: dict | None = None):
        body = payload or {}
        try:
            return _service(store).create_run(
                body.get("plan"),
                source_id=body.get("source_id") or "fixture-traders",
                corpus_kind=body.get("corpus_kind") or "SYNTHETIC",
            )
        except Exception as exc:
            _error(exc)

    @app.get("/api/mass-search/runs/{run_id}")
    async def get_run(run_id: str):
        try:
            return _service(store).run_view(run_id)
        except Exception as exc:
            _error(exc)

    @app.post("/api/mass-search/runs/{run_id}/acquire")
    async def acquire(run_id: str, payload: dict | None = None):
        body = payload or {}
        service = _service(store)
        try:
            if body.get("live"):
                raise SourceError("UNAUTHORIZED", "Live acquisition is blocked without an enabled authorization")
            pages = body.get("pages")
            if not isinstance(pages, list) or not pages:
                raise ValueError("Offline acquire requires explicit fixture pages")
            adapter = FixtureTraderAdapter(pages, corpus_kind=body.get("corpus_kind") or "SYNTHETIC")
            return service.acquire_from_adapter(run_id, adapter, target_unique=body.get("target_unique"))
        except Exception as exc:
            _error(exc)

    @app.post("/api/mass-search/runs/{run_id}/stages/{stage_id}")
    async def evaluate(run_id: str, stage_id: str):
        try:
            return _service(store).evaluate_stage(run_id, stage_id)
        except Exception as exc:
            _error(exc)

    @app.post("/api/mass-search/runs/{run_id}/refilter")
    async def refilter(run_id: str, payload: dict | None = None):
        try:
            return _service(store).refilter(run_id, (payload or {}).get("plan"))
        except Exception as exc:
            _error(exc)

    @app.post("/api/mass-search/runs/{run_id}/reconstruct")
    async def reconstruct(run_id: str, payload: dict | None = None):
        body = payload or {}
        try:
            return _service(store).reconstruct_candidate(
                run_id, body["candidate_id"], body.get("events") or [],
                corpus_kind=body.get("corpus_kind"),
            )
        except Exception as exc:
            _error(exc)

    @app.get("/api/mass-search/runs/{run_id}/candidates")
    async def candidates(run_id: str, stage: str | None = None, cursor: str | None = None,
                         limit: int = 50, sort: str = "provider_realized_pnl"):
        try:
            return _service(store).page_candidates(run_id, stage=stage, cursor=cursor, limit=limit, sort_metric=sort)
        except Exception as exc:
            _error(exc)

    @app.post("/api/mass-search/runs/{run_id}/pause")
    async def pause(run_id: str):
        try:
            return _service(store).pause(run_id)
        except Exception as exc:
            _error(exc)

    @app.post("/api/mass-search/runs/{run_id}/resume")
    async def resume(run_id: str):
        try:
            return _service(store).resume(run_id)
        except Exception as exc:
            _error(exc)

    @app.post("/api/mass-search/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        try:
            return _service(store).cancel(run_id)
        except Exception as exc:
            _error(exc)

    @app.get("/api/mass-search/runs/{run_id}/reports")
    async def linked_reports(run_id: str):
        try:
            return {"reports": _service(store).linked_reports(run_id)}
        except Exception as exc:
            _error(exc)

    @app.get("/api/mass-search/runs/{run_id}/export")
    async def export_run(run_id: str):
        try:
            exported = _service(store).export_run(run_id)
            body = json.dumps(exported["payload"], indent=2, allow_nan=False)
            filename = f"mass-search-{run_id[:12]}.json"
            return Response(
                body,
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except Exception as exc:
            _error(exc)

    @app.post("/api/mass-search/vertical-slice")
    async def vertical_slice(payload: dict | None = None):
        body = payload or {}
        events = body.get("events")
        if not events:
            events = [
                {"kind": "buy", "seconds_from_start": 0, "units": "100", "consideration_sol": "1", "wallet_fee_sol": "0.01",
                 "address": body.get("address") or synthetic_address(1)},
                {"kind": "sell", "seconds_from_start": 20, "units": "50", "consideration_sol": "0.8", "wallet_fee_sol": "0.005"},
                {"kind": "sell", "seconds_from_start": 30, "units": "45", "consideration_sol": "0.72", "wallet_fee_sol": "0.005"},
                {"kind": "sell", "seconds_from_start": 172800, "units": "5", "consideration_sol": "0.08", "wallet_fee_sol": "0.005"},
            ]
        try:
            return _service(store).vertical_slice(events=events, corpus_kind=body.get("corpus_kind") or "SYNTHETIC")
        except Exception as exc:
            _error(exc)

    @app.post("/api/mass-search/benchmark/local")
    async def local_benchmark(payload: dict | None = None):
        body = payload or {}
        try:
            return _service(store).local_scale_benchmark(
                rows=int(body.get("rows") or 10000),
                warmups=int(body.get("warmups") or 5),
                measured=int(body.get("measured") or 20),
            )
        except Exception as exc:
            _error(exc)

    @app.get("/api/mass-search/access-blocker")
    async def blocker():
        return {"birdeye": access_blocker("birdeye-traders"), "helius": access_blocker("helius-history")}

    @app.get("/api/mass-search/ranked-workflow")
    async def ranked_workflow():
        from .workflow import ranked_workflow_view
        return ranked_workflow_view(store)

    @app.post("/api/mass-search/ranked-workflow/replay")
    async def ranked_workflow_replay(payload: dict | None = None):
        from .g3_reacquire import ALLOWED_WALLET
        from .workflow import replay_captured_wallet
        body = payload or {}
        try:
            return replay_captured_wallet(store, body.get("address") or ALLOWED_WALLET)
        except Exception as exc:
            _error(exc)

    @app.post("/api/mass-search/ranked-workflow/shortlist")
    async def ranked_workflow_shortlist(payload: dict | None = None):
        from .workflow import set_user_shortlist
        body = payload or {}
        try:
            return set_user_shortlist(store, body.get("address"), selected=body.get("selected", True))
        except Exception as exc:
            _error(exc)

    @app.post("/api/mass-search/ranked-workflow/batch")
    def ranked_workflow_batch(payload: dict | None = None):
        """Sync so overlapping HTTP callers run in the threadpool and contend for store.lock."""
        from .batch import create_and_run, create_batch
        body = payload or {}
        try:
            if body.get("run") is False:
                return create_batch(
                    store,
                    body.get("addresses") or [],
                    include_fixtures=bool(body.get("include_fixtures")),
                )
            return create_and_run(
                store,
                body.get("addresses") or [],
                include_fixtures=bool(body.get("include_fixtures")),
            )
        except Exception as exc:
            _error(exc)

    @app.get("/api/mass-search/ranked-workflow/batch/{batch_id}")
    async def ranked_workflow_batch_get(batch_id: str):
        from .batch import get_batch
        try:
            return get_batch(store, batch_id)
        except Exception as exc:
            _error(exc)

    @app.post("/api/mass-search/ranked-workflow/batch/{batch_id}/step")
    def ranked_workflow_batch_step(batch_id: str):
        from .batch import step_batch
        try:
            return step_batch(store, batch_id)
        except Exception as exc:
            _error(exc)

    @app.post("/api/mass-search/ranked-workflow/batch/{batch_id}/cancel")
    def ranked_workflow_batch_cancel(batch_id: str):
        from .batch import cancel_batch
        try:
            return cancel_batch(store, batch_id)
        except Exception as exc:
            _error(exc)

    @app.get("/api/mass-search/research-filters")
    async def get_research_filters():
        from .research_profile import load_filters
        return load_filters(store)

    @app.put("/api/mass-search/research-filters")
    async def put_research_filters(payload: dict | None = None):
        from .research_profile import save_filters
        body = payload or {}
        return save_filters(store, body)

    @app.post("/api/mass-search/research-compare")
    async def research_compare(payload: dict | None = None):
        from .workflow import compare_reports
        body = payload or {}
        try:
            return compare_reports(store, body.get("left_id"), body.get("right_id"))
        except Exception as exc:
            _error(exc)

    @app.get("/api/mass-search/acquisition-policy")
    async def get_acquisition_policy():
        from .workflow import acquisition_policy
        return acquisition_policy()

    @app.get("/api/mass-search/acquisition-gate")
    async def get_acquisition_gate():
        from .acquisition_gate import attempt_history_acquisition, gate_status
        return {
            "status": gate_status(store),
            "attempt": attempt_history_acquisition(store),
        }

    @app.post("/api/mass-search/acquisition-gate/check")
    async def check_acquisition_gate(payload: dict | None = None):
        from .acquisition_gate import attempt_history_acquisition
        body = payload or {}
        return attempt_history_acquisition(
            store,
            requested_requests=int(body.get("requested_requests") or 1),
            requested_units=int(body.get("requested_units") or 1),
        )

    @app.get("/api/mass-search/instrumentation")
    async def get_instrumentation():
        from .instrumentation import snapshot
        return snapshot()

    @app.get("/api/mass-search/phone-access")
    async def get_phone_access():
        from .workflow import phone_access_status
        return phone_access_status()

    @app.get("/api/mass-search/approval-proposal")
    async def get_approval_proposal():
        from .workflow import approval_proposal
        return approval_proposal()

    @app.get("/api/mass-search/research-search-proposal")
    async def get_research_search_proposal():
        from .workflow import research_search_proposal
        return research_search_proposal()
