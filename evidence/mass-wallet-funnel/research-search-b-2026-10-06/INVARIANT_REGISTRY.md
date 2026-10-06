# Invariant registry — Research Search B / PR #6

Mapping: **ID → rule → source enforcement → tests → consumers → evidence**.

| ID | Rule | Source enforcement | Positive / negative / property / fault tests | Consumer coverage | Evidence artifact |
| --- | --- | --- | --- | --- | --- |
| CERT | Certification describes the bound completed-episode ledger. App-side acquisition/proceeds/costs/net/unit must match the matching ledger episode; app vs auditor stay within declared unit tolerances; empty/missing ledger is non-certifying; duplicated representations must include auditor identity. | `certificate_comparison_proof`, `_bridge_app_matches_ledger`, `_bridge_component_key`, `bindable_independent_audit`, `independently_audited`, `completedEpisodeFields`, `certificateComparisonProof` | Positive: eligible 4-episode fixture. Negative: 999/1002/0/3 vs 1/4/0/3; USDC vs SOL; episode-only auditor close/mint; empty/missing ledger; proceeds-only; costs-only; USDC amount mismatch; extra episode; missing acquisition; swapped unit; contradictory representations. Property: half-even SOL/USDC 2-vs-3 atomic edges. | Ranked, report, compare, qualification, export inspect via `independently_audited` / `completedEpisodeFields` | `tests/test_chatgpt_review_2026_10_07_0842.py`; `frontend/scripts/assert-rereview-0842.mts` |
| STATE | Every reused decision follows reconciled evidence. Rebuild `evidence_class` before `qualification_category`; recompute A/B/C funnel, thresholds, audit bind; ranked and compare must not prefer saved funnels. | `_invalidate_saved_decisions`, `reconcile_saved_profile`, `ranked_workflow_view`, `compare_reports` | Positive: eligible saved report still classifies. Negative: zero-completed + stale class 1; stale class 4; saved C=MET + empty/negative ledger; membership change detaches audit. Property: reconcile twice is idempotent. | Ranked rows, compare left/right funnels and categories, report `profile.funnel` | `tests/test_chatgpt_review_2026_10_07_0842.py::test_saved_decisions_rebuild_evidence_class_and_funnels` |
| UI | Actual component trees show the same decision as the evidence. No auditor confirmation, stale positive category, or stale C=MET on negatives. | `RankedPhoneCard`, `RankedDesktopRow`, `ReportCertificationView`, `CompareCertificationView`, `authoritativeFunnel`, `authoritativeCategory` | Mounted react-dom/server trees for invalid certificates and stale category/funnel payloads. An9s non-lead wording remains in 0714. | MassSearch phone cards, desktop rows, report profile, compare panel | `frontend/scripts/assert-rereview-0842.mts`; `frontend/src/researchSurfaces.ts` |
| CAP-A | When a store exists, durable state is authoritative. Stale/empty supplied state cannot reset consumed attempts. Persist failure before transport prevents dispatch. | `load_next_capture_state`, `run_next_capture_offline` reserve-then-persist-then-transport | Persisted timeout + empty/stale supplied reopen; persist `OSError` before transport (zero recorder calls). | Offline runner, store reopen | `test_durable_store_ignores_stale_or_empty_supplied_state`; `test_persist_failure_before_transport_does_not_dispatch` |
| CAP-B | Reservation replaces/invalidates `last_dispatch`. Progress binds to the accepted latest replay response/page. Failed newer attempts cannot re-arm older receipts. | `replay_bound_to_last_dispatch`, `bind_progress_to_replay`, runner `last_dispatch.status` reserved/failed | Success → replay → timeout → old receipt rejects; fresh receipt + stale/missing `response_id` progress rejects. | Evaluator + runner | `test_reservation_invalidates_last_dispatch_and_binds_progress` |
| CAP-C | Terminal cursors stay terminal. Accepted not-started / open / exhausted. Not reopened this pass. | `wallet_cursor_state`, `EXHAUSTED_CURSOR` | 0714 terminal-cursor regressions | Evaluator + runner | `tests/test_chatgpt_review_2026_10_07_0714.py::test_replay_is_bound_to_last_response_and_terminal_cursor_refuses` |
| CAP-D | Exact committed draft is executable. A6PS additional page explicitly unavailable (no pseudo-mint). Per-wallet `acceptable_progress_observations` only. 58PW allowance 0. DQ7n/BVZt excluded. | Draft JSON; `named_dependency_progress`; `additional_page_unavailable` gate | First A6PS page still allowed after replay; second page `additional_page_unavailable`; gtfo rejects a generic classified-cost-role observation. | Evaluator against committed draft | `test_a6ps_additional_page_unavailable_and_wallet_observations` |
| CAP-E | Operator quota observation (baseline, operator, confirmed_at vs approval/expiry) binds the grant. Remaining allowance is enforced at reservation. Remaining 0 → zero recorder calls. | `validate_operator_quota_record`, `validate_fresh_approval_bind`, remaining check in `evaluate_next_capture_dispatch` | Remaining 0; remaining 2 exhausts across success+failure; missing operator/confirmed_at/baseline; confirmed_at after expiry. | Evaluator + runner + fake transport | `test_remaining_quota_enforced_at_reservation` |

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

See `scripts/verify_safety_mutants.py`: CERT empty-ledger bypass; STATE stale evidence_class keep; CAP-A supplied-state preference; CAP-B progress bind disabled; CAP-E remaining check disabled.

## Accepted and not reopened

Gaps 3–4; gtfo six-atomic aggregate disclosure; DQ7n/BVZt honesty and exclusions; CAP-C terminal cursors; An9s coverage-gate / not-a-lead wording; screen-count “sample/activity filter matches (not certified research leads)”.
