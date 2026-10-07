# Invariant registry — Research Search B / PR #6

Mapping: **ID → rule → source enforcement → tests → consumers → evidence**.

| ID | Rule | Source enforcement | Positive / negative / property / fault tests | Consumer coverage | Evidence artifact |
| --- | --- | --- | --- | --- | --- |
| CERT | Certification describes the bound completed-episode ledger. App-side acquisition/proceeds/costs/net/unit must match the matching ledger episode; headline auditor net must equal Σ bridge auditor nets; headline app net must equal ledger sum; units equal; confirmation is derived, never the stored string; empty/missing ledger is non-certifying; duplicated representations must include auditor identity. Shared money grammar is `^-?(?:0|[1-9]\\d*)(?:\\.\\d+)?$` strings only. | `certificate_comparison_proof`, `_stored_headline_matches`, `derived_certificate_headlines`, `parse_canonical_amount`, `bindable_independent_audit`, `independently_audited`, `completedEpisodeFields`, `certificateComparisonProof`, `parseCanonicalAmount` | Positive: eligible 4-episode fixture. Negative: stored headline 999; stale confirmation 999; sci-notation / +3 / padded amounts; USDC vs SOL; empty/missing ledger; contradictory representations. Property: half-even SOL/USDC 2-vs-3 atomic edges. | Ranked, report, compare, qualification, export inspect via `independently_audited` / derived confirmation | `tests/test_grok_bot_2fe60bd_repros.py`; `tests/test_chatgpt_review_2026_10_07_0842.py`; `frontend/scripts/assert-rereview-0842.mts` |
| STATE | Every reused decision follows reconciled evidence. Rebuild `evidence_class` before `qualification_category`; recompute A/B/C funnel, thresholds, audit bind; top-level `independent_audit` / `audit_fingerprint` / `completed_episode_ledger` come from the reconciled profile; never bind from `profile.independent_audit`. | `_invalidate_saved_decisions`, `reconcile_saved_profile`, `visible_mass_search_report`, `decorate_report`, `ranked_workflow_view`, `compare_reports` | Positive: eligible saved report still classifies. Negative: empty ledger after valid saved audit (GET/export); report.independent_audit=None with profile copy; policy-version bump; one NaN cert does not 500 `/api/state`. Property: reconcile twice is idempotent; `reconcile_saved_profile()["funnel"]` itself is recomputed (M4). | Ranked rows, compare, report GET/export top-level audit fields | `tests/test_grok_bot_2fe60bd_repros.py`; `test_saved_decisions_rebuild_evidence_class_and_funnels` |
| UI | Actual component trees show the same decision as the evidence. No auditor confirmation, stale positive category, or stale C=MET on negatives. | `RankedPhoneCard`, `RankedDesktopRow`, `ReportCertificationView`, `CompareCertificationView`, `authoritativeFunnel`, `authoritativeCategory` | Mounted react-dom/server trees for invalid certificates and stale category/funnel payloads. An9s non-lead wording remains in 0714. | MassSearch phone cards, desktop rows, report profile, compare panel | `frontend/scripts/assert-rereview-0842.mts`; `frontend/src/researchSurfaces.ts` |
| CAP-A | A durable store is required. Stale/empty supplied state cannot reset consumed attempts. Persist failure before transport prevents dispatch. Concurrent runners serialize via CAS on generation; the loser refuses before transport. | `run_next_capture_offline` store required; `Store.cas_put`; reserve-then-persist-then-transport | `store=None` twice → 0 calls; persist `OSError` before transport; two/three overlapping runners → 1 call and `requests_used` matches. | Offline runner, store reopen | `test_b7_store_none_refuses_before_transport`; `test_b8_overlapping_runners_serialize_and_count_budget` |
| CAP-B | Receipts match last_dispatch on address, page, authorization_id, and attempt. The runner mints `response_id`. Receipts are single-use. Progress binds to the accepted latest replay. | `_receipt_matches_dispatch`, `record_next_capture_replay`, `_mint_response_id` | Page-less receipt with matching response_id/address/grant/attempt rejects (M9); wrong wallet/attempt/grant reject; transport-supplied id is ignored. | Evaluator + runner | `test_b6_page_less_receipt_is_single_use_and_bound` |
| CAP-C | Terminal cursors stay terminal. Accepted not-started / open / exhausted. Not reopened this pass. | `wallet_cursor_state`, `EXHAUSTED_CURSOR` | 0714 terminal-cursor regressions | Evaluator + runner | `tests/test_chatgpt_review_2026_10_07_0714.py::test_replay_is_bound_to_last_response_and_terminal_cursor_refuses` |
| CAP-D | Exact committed draft is executable. A6PS additional page explicitly unavailable (no pseudo-mint). Per-wallet `acceptable_progress_observations` only. 58PW allowance 0. DQ7n/BVZt excluded. | Draft JSON; `named_dependency_progress`; `additional_page_unavailable` gate | First A6PS page still allowed after replay; second page `additional_page_unavailable`; gtfo rejects a generic classified-cost-role observation. | Evaluator against committed draft | `test_a6ps_additional_page_unavailable_and_wallet_observations` |
| CAP-E | Operator quota observation binds authorization_id + artifact hash to the grant. `confirmed_at` must be ≤ now and between approval and expiry. Remaining is a strict non-negative int (bool/float/inf/NaN/string rejected). Remaining 0 → zero recorder calls. | `validate_operator_quota_record`, `validate_fresh_approval_bind`, `_strict_nonneg_int` | Future confirmed_at; other-grant + zero hash; remaining True/1.9/inf; remaining 0. | Evaluator + runner + fake transport | `test_b4_future_confirmed_at_refuses_before_transport`; `test_b5_quota_record_must_bind_grant_and_artifact`; `test_quota_remaining_rejects_bool_float_inf_and_string` |

## Extra variants probed beyond named 08:42 cases

- Mutate only proceeds; only costs
- USDC ledger vs wrong USDC amounts
- Missing ledger acquisition
- Extra unmatched episode
- Swapped unit on one ledger row
- Auditor mint-only change in one representation
- Empty top-level `component_bridges` with valid episode-local bridges (accepted when equivalent)
- Contradictory units between representations
- Half-even / 2-vs-3 atomic SOL and USDC edges
- Stale account class 4 → `profitable_account_performance`
- Saved B=ESTABLISHED + empty ledger
- Supplied state with `requests_used=0` and `replay_completed=True` after timeout
- Progress missing `response_id`; progress bound to an older response
- Persist failure before transport
- Reconcile idempotence on empty-ledger overlay
- App-side-only component mutation (auditor still matches ledger)
- Auditor-side-only component mutation (app still matches ledger)
- Top-level bridges mutated while episode-local copy stays valid
- Headline unit mismatch on `report.independent_audit` (not only profile)
- Stale completed count (4) + empty ledger + saved C=MET / class 1
- Whitespace-only and missing operator on quota record
- `last_dispatch.status=reserved` cannot re-arm an old page-1 receipt
- A6PS first page remains allowed; additional page stays unavailable
- Report GET / export copy via `visible_mass_search_report`
- Live `ResearchProfilePanel` uses authoritative funnel/category, not saved fields

## Safety mutants verified to fail the intended test

See `scripts/verify_safety_mutants.py`: CERT empty-ledger bypass; STATE stale evidence_class keep; CAP-A supplied-state preference; CAP-B progress bind disabled; CAP-E remaining check disabled; M4 keep-saved-funnel (observable on `reconcile_saved_profile()["funnel"]`); M9 page-less receipt; JS2 contradictory representation; JS4 profile/headline unit.

## Accepted and not reopened

Gaps 3–4; gtfo six-atomic aggregate disclosure; DQ7n/BVZt honesty and exclusions; CAP-C missing-token-as-clean-finish on a success envelope (error/garbage envelopes are not clean terminals); An9s coverage-gate / not-a-lead wording; screen-count “sample/activity filter matches (not certified research leads)”; compare downgrade of a valid positive category; field-name lookup order (fails safe).
