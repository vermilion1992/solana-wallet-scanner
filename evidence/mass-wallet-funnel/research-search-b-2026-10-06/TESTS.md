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
