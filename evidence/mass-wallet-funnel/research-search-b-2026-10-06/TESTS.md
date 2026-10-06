# Offline suite at the independent-audit reconciliation commit (cloud agent, 2026-10-06)

App SHA of this evidence commit. Bundle `frontend/dist/assets/index-l9mwD6zR.js`.

- Keys unset (`env -u HELIUS_API_KEY -u BIRDEYE_API_KEY -u HELIUS_API_KEYS .venv/bin/python -m pytest -q`): **3670 passed**, 440 subtests, 0 failed, 1 warning (9 min 16 s). EXIT 0.
- Keys set (`HELIUS_API_KEY=dummy-helius-never-dispatch BIRDEYE_API_KEY=dummy-birdeye-never-dispatch .venv/bin/python -m pytest -q`): **3670 passed**, 440 subtests, 0 failed, 1 warning (9 min 6 s). EXIT 0.
- `npm run build`: `tsc -b && vite build` OK; bundle `frontend/dist/assets/index-l9mwD6zR.js`.
- Phone-sized emulation 390×844: no page errors; unauthenticated `/api/state` = **401**. Shots in `screenshots/phone-0*.png`.
- No Helius or Birdeye calls. Dummy keys were never sent.
- `PRODUCT_READY` remains false.

Named regressions:

- `tests/test_mitch_review_2026_10_06.py`
  - `test_a6ps_75gg_buy_consideration_is_swap_quote_not_wallet_delta`
  - `test_a6ps_2rss_close_is_meteora_damm_v2_from_raw_bytes`
  - `test_gtfo_2af7_same_slot_order_closes_missing_episode`
  - `test_58pw_sales_are_rfq_fill_and_jupiter_usdc`
  - `test_labelled_wallets_are_independently_audited_in_committed_json`
  - `test_cccs_scoped_net_bridge_matches_debit_audit`
  - `test_auditor_owns_tip_list_outside_scanner_and_copies_agree`
  - `test_auditor_runs_without_scanner_directory_and_nets_match`
  - `test_auditor_fails_loudly_when_tip_list_missing`
  - `test_failed_transaction_transfers_are_excluded_from_fee_audit_and_app`
  - `test_cccs_failed_transaction_debits_are_excluded`
  - `test_58pw_independently_audited_sits_next_to_episode_net`
  - `test_compare_reports_mismatch_when_auditor_finds_episodes_app_missed`
  - `test_compare_tolerance_is_two_lamports`
  - `test_venue_notes_are_computed_from_auditor_decode`
  - `test_history_ingest_has_no_wallet_specific_residual_constant`
  - `test_jupiter_route_v2_usdc_version1_decodes_real_signatures`
  - `test_outer_ata_still_requires_message_signer`
  - `test_auditor_refuses_mixed_unit_episode_net_sum`
  - `test_fee_audit_recomputes_cccs_current_figures_from_captures`
  - `test_fee_audit_counts_only_wallet_paid_network_fees`
  - `test_a6ps_residual_is_in_window_new_account_rent_on_buys`
  - `test_astziy6_is_unverified_outside_debit_not_a_tip`
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
