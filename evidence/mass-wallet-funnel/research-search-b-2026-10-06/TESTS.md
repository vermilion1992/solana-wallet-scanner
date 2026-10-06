# Offline suite (cloud agent, 2026-10-06)

See RESULT.md for the per-wallet table. Suite/build counts on the exact final commit are recorded after that commit is made.

Named regressions for this pass:

- `tests/test_mitch_review_2026_10_06.py`
  - `test_item11_sensitivity_sign_flip_cannot_be_provisional_research_lead`
  - `test_item11_label_tables_cannot_disagree`
  - `test_committed_wallet_table_matches_label_function`
  - `test_win_rate_stays_in_unit_interval_including_mixed`
  - `test_zero_completed_episodes_do_not_expose_net`
  - `test_item2_only_verified_jito_tips_count` (published Nozomi/Astralane true; wyvPk false)
  - `test_item8_fee_audit_records_largest_charges_and_roles`
  - `test_item15_independent_auditor_imports_no_scanner`
  - `test_item15_auditor_output_covers_labelled_episodes`
- `tests/test_research_search_b_defects.py::test_d4_mixed_wallet_separate_quote_asset_worksheets` (win rate in [0,1])

`PRODUCT_READY` remains false. No Helius or Birdeye calls.
