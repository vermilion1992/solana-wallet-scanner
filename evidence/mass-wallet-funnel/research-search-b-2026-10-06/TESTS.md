# Offline suite at fix commit 1d1b3ec (cloud agent, 2026-10-06)

- Keys unset (`env -u HELIUS_API_KEY -u BIRDEYE_API_KEY -u HELIUS_KEY .venv/bin/python -m pytest -q`): **3617 passed**, 440 subtests, 0 failed, 1 warning (8 min 40 s). EXIT 0.
- Keys set (`HELIUS_API_KEY=dummy-helius-not-live BIRDEYE_API_KEY=dummy-birdeye-not-live HELIUS_KEY=dummy-helius-not-live .venv/bin/python -m pytest -q`): **3617 passed**, 440 subtests, 0 failed, 1 warning (8 min 58 s). EXIT 0.
- D9 `tests/test_screening_routes.py::test_import_identity_sample_screen_is_saved_without_strict_promotion` clears provider keys via monkeypatch and passed in both runs.
- Frontend: `cd frontend && npm run build` → `tsc -b && vite build` OK in 234 ms. Bundle `frontend/dist/assets/index-DpiADeUU.js`.
- No Helius or Birdeye calls. Dummy keys were never sent.
