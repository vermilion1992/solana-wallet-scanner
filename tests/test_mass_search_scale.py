"""Local 10,000-row capacity and paginated summary path."""
from scanner.config import LIMITS
from scanner.mass_search.schema import MASS_UNIVERSE_CAPACITY
from scanner.mass_search.service import MassSearchService
from scanner.storage import Store


def test_ten_thousand_row_local_refilter_and_pagination(tmp_path):
    store = Store(tmp_path / "data")
    try:
        service = MassSearchService(store)
        result = service.local_scale_benchmark(rows=MASS_UNIVERSE_CAPACITY, warmups=1, measured=3, page_size=50)
        assert result["unique_candidates"] == 10000
        assert result["external_requests"] == 0
        assert result["legacy_candidate_cap"] == LIMITS["candidate_cap"] == 20
        page = service.page_candidates(result["run_id"], stage="triage", limit=50)
        assert len(page["items"]) == 50
        assert page["total"] == 10000
        assert page["next_cursor"]
        next_page = service.page_candidates(result["run_id"], stage="triage", limit=50, cursor=page["next_cursor"])
        assert next_page["items"][0]["candidate_id"] != page["items"][0]["candidate_id"]
        assert result["p95_ms"] >= result["median_ms"]
    finally:
        store.close()
