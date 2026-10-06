# Offline suite at the phone-UI evidence commit (cloud agent, 2026-10-06)

App SHA `d961824` plus this screenshots/TESTS commit. Bundle `frontend/dist/assets/index-Bj4UsG-X.js`.

- Keys unset (`env -u HELIUS_API_KEY -u BIRDEYE_API_KEY -u HELIUS_KEY .venv/bin/python -m pytest -q`): **3647 passed**, 440 subtests, 0 failed, 1 warning (9 min 1 s). EXIT 0.
- Keys set (`HELIUS_API_KEY=dummy-helius-not-live BIRDEYE_API_KEY=dummy-birdeye-not-live HELIUS_KEY=dummy-helius-not-live .venv/bin/python -m pytest -q`): **3647 passed**, 440 subtests, 0 failed, 1 warning (8 min 51 s). EXIT 0.
- `npm run build`: `tsc -b && vite build` OK; bundle `frontend/dist/assets/index-Bj4UsG-X.js`.
- Phone-sized emulation 390×844: no page errors; unauthenticated `/api/state` = **401**. Shots in `screenshots/phone-0*.png`.
- No Helius or Birdeye calls. Dummy keys were never sent.
- `PRODUCT_READY` remains false.

Named regressions:

- `tests/test_mitch_review_2026_10_06.py`
  - `test_item11_sensitivity_sign_flip_cannot_be_provisional_research_lead`
  - `test_item11_label_tables_cannot_disagree`
  - `test_committed_wallet_table_matches_label_function`
  - `test_win_rate_stays_in_unit_interval_including_mixed`
  - `test_zero_completed_episodes_do_not_expose_net`
  - `test_item2_only_verified_jito_tips_count`
  - `test_item8_fee_audit_records_largest_charges_and_roles`
  - `test_item15_independent_auditor_imports_no_scanner`
  - `test_item15_auditor_output_covers_labelled_episodes`
- `tests/test_research_search_b_defects.py::test_d4_mixed_wallet_separate_quote_asset_worksheets`
