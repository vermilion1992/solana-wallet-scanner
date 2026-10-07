# Offline suite at the Grok Bot 2fe60bd invariant-fix commit

App SHA `4986e795e6e336b4afdea31f521a94cbd6382cf4`. Bundle `frontend/dist/assets/index-Dt5k-k7X.js`. Broken tip under attack: `2fe60bd8d0e4ec3a996f80d8b2f1e9bac1152d20`.

- Keys unset: **3764 passed** / 3 failed / 440 subtests / 1 warning (9 min 15 s). The 3 failures are `tests/test_mass_search_g1.py` after `live-g1-vertical-slice-2026-10-05-mitch` expired at `2026-10-07T00:00:00Z` (clock crossed midnight during this run). Not an invariant regression; G1 grant was not extended.
- Dummy keys (`HELIUS_API_KEY=dummy`, `BIRDEYE_API_KEY=dummy`, `HELIUS_API_KEYS=dummy`): **3764 passed** / 3 failed / 440 subtests / 1 warning (8 min 35 s). Dummy keys were never sent. Same 3 G1 expiry failures.
- `npm run build`: `tsc -b && vite build` OK; bundle `frontend/dist/assets/index-Dt5k-k7X.js`.
- Offline acceptance: `.venv/bin/python scripts/offline_acceptance.py` → `ok: true` (stamp `20261006T235907Z`; 111 invariant tests + real mounted payloads + 9 safety mutants including M4/M9/JS2/JS4).
- Adapted 8-blocker reproducer: `.venv/bin/python scripts/minimal_repros_2fe60bd.py` — all 8 refuse/correct.
- Phone-sized Chromium emulation remains labelled as emulation, not a physical phone. Physical-phone testing is NOT RUN.
- No Helius or Birdeye calls. Dummy keys were never sent.
- `PRODUCT_READY` remains false.
- Spend this pass: 0/0/$0.
- Capture draft stays `enabled:false`.

Named 2fe60bd closures (`tests/test_grok_bot_2fe60bd_repros.py`):

- `test_b1_headline_999_is_non_certifying`
- `test_b1_neighbours_stale_confirmation_app_net_and_unit`
- `test_b2_decorate_and_export_use_reconciled_top_level_audit`
- `test_b2_neighbours_policy_bump_null_audit_and_membership`
- `test_b3_profile_copy_is_not_an_audit_source`
- `test_b3_neighbours_status_flag_and_fingerprintless_copy`
- `test_b4_future_confirmed_at_refuses_before_transport`
- `test_b4_neighbours_after_expiry_before_approval_and_one_second`
- `test_b5_quota_record_must_bind_grant_and_artifact`
- `test_b5_neighbours_missing_id_wrong_hash_and_missing_hash`
- `test_b6_page_less_receipt_is_single_use_and_bound`
- `test_b6_neighbours_wrong_attempt_wrong_grant_and_transport_id`
- `test_b7_store_none_refuses_before_transport`
- `test_b7_neighbours_missing_store_with_memory_state_and_default`
- `test_b8_overlapping_runners_serialize_and_count_budget`
- `test_b8_neighbours_three_runners_and_cas_loser`
- `test_nan_amount_fails_closed_per_wallet_not_app_state`
- `test_canonical_amount_grammar_rejects_python_js_divergences`
- `test_quota_remaining_rejects_bool_float_inf_and_string`
- `test_error_envelope_is_not_a_clean_terminal_cursor`

Prior 08:42 / 07:14 / 05:47 / 03:46 / 0116 named tests remain.

# Offline suite at the 2026-10-07 08:42 + invariant-brief commit

App SHA `517c721d25c9812ec113a7fad66d4aefffb396dc`. Bundle `frontend/dist/assets/index-OhAg4lQK.js`.

- Keys unset: **3747 passed** / 440 subtests / 1 warning (9 min 24 s).
- Dummy keys (`HELIUS_API_KEY=dummy`, `BIRDEYE_API_KEY=dummy`, `HELIUS_API_KEYS=dummy`): **3747 passed** / 440 subtests / 1 warning (9 min 18 s). Dummy keys were never sent.
- `npm run build`: `tsc -b && vite build` OK; bundle `frontend/dist/assets/index-OhAg4lQK.js`.
- Offline acceptance: `.venv/bin/python scripts/offline_acceptance.py` → `ok: true` (`offline-acceptance/RESULT.json`, stamp `20261006T232144Z`; 91 invariant tests + mounted trees + safety mutants).
- Phone-sized Chromium emulation remains labelled as emulation, not a physical phone. Physical-phone testing is NOT RUN.
- No Helius or Birdeye calls. Dummy keys were never sent.
- `PRODUCT_READY` remains false.
- Spend this pass: 0/0/$0.
- Capture draft stays `enabled:false`.

Named 08:42 closures (`tests/test_chatgpt_review_2026_10_07_0842.py` + `tests/test_adversarial_0842_named_counterexamples.py`):

- `test_bridge_amounts_must_match_bound_ledger_not_just_auditor`
- `test_canonicalization_includes_auditor_identity_in_one_representation`
- `test_empty_or_missing_ledger_is_non_certifying`
- `test_gap1_mutations_reject_through_ranked_and_compare`
- `test_saved_decisions_rebuild_evidence_class_and_funnels`
- `test_durable_store_ignores_stale_or_empty_supplied_state`
- `test_reservation_invalidates_last_dispatch_and_binds_progress`
- `test_a6ps_additional_page_unavailable_and_wallet_observations`
- `test_remaining_quota_enforced_at_reservation`
- `test_mounted_component_trees_reject_invalid_and_stale_payloads`
- `test_named_ledger_1_4_0_3_vs_bridge_999_1002_0_3_rejects`
- `test_named_bridge_usdc_vs_ledger_sol_rejects`
- `test_named_auditor_close_only_in_episode_representation_rejects`
- `test_named_empty_and_missing_ledger_with_stale_audit_do_not_certify`
- `test_named_mismatched_units_do_not_render_as_audited`
- `test_named_stale_class1_zero_completed_is_not_positive_matched`
- `test_named_durable_store_ignores_empty_and_stale_supplied_after_timeout`
- `test_named_old_receipt_cannot_rearm_after_newer_timeout`
- `test_named_a6ps_additional_page_unavailable`
- `test_named_remaining_zero_never_reaches_transport`

Prior 07:14, 05:47, 03:46, and 0116 named tests remain.

# Offline suite at the 2026-10-07 07:14 re-review commit

App SHA of this evidence commit. Bundle `frontend/dist/assets/index-Dgx1_JEr.js`.

- Keys unset: **3722 passed** / 440 subtests / 1 warning (8 min 55 s).
- Dummy keys (`HELIUS_API_KEY=dummy`, `BIRDEYE_API_KEY=dummy`, `HELIUS_API_KEYS=dummy`): **3722 passed** / 440 subtests / 1 warning (8 min 49 s). Dummy keys were never sent.
- `npm run build`: `tsc -b && vite build` OK; bundle `frontend/dist/assets/index-Dgx1_JEr.js`.
- Phone-sized Chromium emulation remains labelled as emulation, not a physical phone. Physical-phone testing is NOT RUN.
- No Helius or Birdeye calls. Dummy keys were never sent.
- `PRODUCT_READY` remains false.
- Spend this pass: 0/0/$0.
- Capture draft stays `enabled:false`.

Named regressions for this pass (`tests/test_chatgpt_review_2026_10_07_0714.py`):

- `test_stale_positive_flag_comparisons_do_not_certify`
- `test_missing_close_signature_is_rejected`
- `test_reconcile_invalidates_stale_lead_and_audit_on_ranked_row`
- `test_fresh_approval_requires_quota_record_and_approval_relationship`
- `test_failed_timeout_consumes_attempt_across_reopen`
- `test_replay_is_bound_to_last_response_and_terminal_cursor_refuses`
- `test_committed_draft_page_bound_replay_allows_cccs_and_rejects_stale`
- `test_javascript_half_even_and_surface_rendering`

Prior 05:47, 03:46, and 0116 named tests remain.
