# Offline suite at tested commit 78678d18 (secure box, 2026-10-06 ACDT)

- With provider keys unset (`env -u HELIUS_API_KEY -u BIRDEYE_API_KEY -u HELIUS_KEY pytest -q`): **3607 passed**, 440 subtests, 0 failed (8 min). EXIT 0.
- With provider keys exported (box default, `-x`): 3046 passed, then 1 failure:
  `tests/test_screening_routes.py::test_import_identity_sample_screen_is_saved_without_strict_promotion`
  (`budget_mode` 'setup-pilot' != 'public-sample'). The failure depends on the environment (D9). The same file passes with keys unset (18 passed).
- The suite is green even though D1–D6 exist, because no genuine multi-wallet SOL/mixed fixture was in the suite.
  The regression tests requested in `DEFECTS.md` close that gap.
- Frontend build was not run on the box: the box has Node 20.19.2 and `setup.sh` requires ≥ 22.12. The committed `frontend/dist` was served unchanged.
