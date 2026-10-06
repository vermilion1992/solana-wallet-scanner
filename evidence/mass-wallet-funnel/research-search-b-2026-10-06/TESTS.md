# Offline suite at Mitch-review commit (cloud agent, 2026-10-06)

App SHA `f24aff7` plus this evidence/dist rebuild (`frontend/dist/assets/index-Dfbh-8ex.js`).

- Keys unset (`env -u HELIUS_API_KEY -u BIRDEYE_API_KEY -u HELIUS_KEY .venv/bin/python -m pytest -q`): **3641 passed**, 440 subtests, 0 failed, 1 warning (9 min 20 s). EXIT 0.
- Keys set (`HELIUS_API_KEY=dummy-helius-not-live BIRDEYE_API_KEY=dummy-birdeye-not-live HELIUS_KEY=dummy-helius-not-live .venv/bin/python -m pytest -q`): **3641 passed**, 440 subtests, 0 failed, 1 warning (9 min 5 s). EXIT 0.
- D9 `tests/test_screening_routes.py::test_import_identity_sample_screen_is_saved_without_strict_promotion` clears provider keys via monkeypatch and passed in both runs.
- Frontend: `cd frontend && npm run build` → `tsc -b && vite build` OK. Bundle `frontend/dist/assets/index-Dfbh-8ex.js`.
- Named regressions after ledger regen: `tests/test_mitch_review_2026_10_06.py` and D13 partitions in `tests/test_research_search_b_defects.py`.
- No Helius or Birdeye calls. Dummy keys were never sent.
- `PRODUCT_READY` remains false.
