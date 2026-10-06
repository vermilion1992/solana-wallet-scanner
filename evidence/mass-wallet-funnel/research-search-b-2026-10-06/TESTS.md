# Offline suite at the 2026-10-07 ChatGPT-review commit

App SHA of this evidence commit. Bundle recorded after `npm run build`.

- Keys unset (`env -u HELIUS_API_KEY -u BIRDEYE_API_KEY -u HELIUS_API_KEYS .venv/bin/python -m pytest -q`): pending clean run.
- Keys set (`HELIUS_API_KEY=dummy-helius-never-dispatch BIRDEYE_API_KEY=dummy-birdeye-never-dispatch .venv/bin/python -m pytest -q`): pending clean run.
- `npm run build`: pending.
- Phone-sized emulation 390×844: pending recapture of changed report/compare screens.
- No Helius or Birdeye calls. Dummy keys are never sent.
- `PRODUCT_READY` remains false.

Named regressions for this pass:

- `tests/test_chatgpt_review_2026_10_07.py`
  - `test_stale_audit_does_not_attach`
  - `test_99_5_count_80_value_does_not_qualify`
  - `test_20_episode_3_mint_one_day_burst_fails_stronger_shortlist`
  - `test_positive_worksheet_negative_episodes_does_not_qualify`
  - `test_cross_currency_sensitivity_blocks_lead`
  - `test_even_sample_median_uses_mean_of_two_central_values`
  - `test_asset_specific_atomic_tolerances`
  - `test_message_signers_header_cross_check_rejects_conflicting_flags`
  - `test_proven_platform_fee_is_a_cost_unexplained_transfer_is_not`
  - `test_synthetic_cases_never_count_as_genuine_research_wallets`
  - `test_token_2022_transfer_fee_bvzt_dq7n_jupiter_buys`
  - `test_rfq_fee_fill_bvzt_three_sales`
  - `test_unrelated_transfer_guard_still_rejects_non_rfq_outer_owned_transfer`
  - `test_swaptob_remains_unsupported_after_bounded_investigation`
  - `test_next_capture_box_driver_emits_supported_gta_request`
- `tests/test_mitch_review_2026_10_06.py::test_item17_next_capture_manifest_is_disabled`
- `tests/test_mitch_review_2026_10_06.py::test_labelled_wallets_are_independently_audited_in_committed_json`
- `tests/test_mitch_review_2026_10_06.py::test_compare_reports_mismatch_when_auditor_finds_episodes_app_missed`
- `tests/test_research_search_b_defects.py::test_d4_mixed_wallet_separate_quote_asset_worksheets`
