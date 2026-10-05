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
    if isinstance(exc, SourceError):
        raise HTTPException(409, str(exc))
    if isinstance(exc, (ValueError, EvidenceError)):
        raise HTTPException(400, str(exc))
    raise exc


def mass_search_state(store):
    """Compact run summaries only. Never materialise the bulk universe into /api/state."""
    try:
        service = MassSearchService(store)
        runs = service.list_runs()
    except Exception:
        runs = []
    return {
        "runs": runs[:20],
        "bulk_capacity": MASS_UNIVERSE_CAPACITY,
        "legacy_candidate_cap": LIMITS["candidate_cap"],
        "legacy_deep_audit_cap": LIMITS["deep_audit_cap"],
        "live_default": False,
        "note": "Paginated candidate rows are served from /api/mass-search/runs/{id}/candidates.",
    }


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
