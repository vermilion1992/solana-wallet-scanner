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
