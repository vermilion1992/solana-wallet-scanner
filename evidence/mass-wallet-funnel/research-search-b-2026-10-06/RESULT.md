# RANKED100_RESEARCH_SEARCH_HISTORY (grant B): Grok Bot 2fe60bd 8-blocker fix

**Outcome: B1–B8 invariants closed on `4986e79` after Grok Bot broke tip `2fe60bd`. PRODUCT_READY stays false. No live calls. Next-capture draft stays enabled:false. G1 grant was not extended after its 2026-10-07T00:00:00Z expiry. No merge/deploy. Spend this pass 0/0/$0.**

Binding work order: Grok Bot independent adversarial verify of tip `2fe60bd` (8 blocking counterexamples). Fixes are in the predicates/runner/UI, not named fixtures. Gaps 3 and 4 stay closed. gtfo’s labelled six-atomic aggregate bridge stays accepted. DQ7n/BVZt honesty and capture exclusions stay. CAP-C missing-token-as-clean-finish is unchanged; error/garbage envelopes are no longer recorded as a clean terminal cursor.

## This-review claim status

| Gap | Reviewer required closure | Status |
| --- | --- | --- |
| B1 CERT | Headline auditor net = Σ bridge auditor nets; headline app net = ledger sum; units equal; confirmation from `format_auditor_confirmation(derived)` | CLOSED at the predicate (Python + JS). `independently_audited_episode_net='999'` is non-certifying. |
| B2 STATE | Top-level `independent_audit` / `audit_fingerprint` / `completed_episode_ledger` derived from reconciled profile on GET/export/ranked/compare | CLOSED. `decorate_report` no longer returns the raw stored audit. |
| B3 STATE | Never bind from `profile.independent_audit` | CLOSED. `_invalidate_saved_decisions` uses report-level audit only. |
| B4 CAP-E | `confirmed_at > now` refused (also after expiry / before approval) | CLOSED. |
| B5 CAP-E | Quota record binds authorization_id + artifact hash; remaining is a strict non-negative int | CLOSED. |
| B6 CAP-B | Receipt matches last_dispatch address/page/authorization_id/attempt; runner-minted `response_id`; single-use | CLOSED. |
| B7 CAP-A | Refuse without a durable store; no default `store=None` dispatch | CLOSED. |
| B8 CAP-A | CAS on generation from load through reserve-persist; loser refuses before transport | CLOSED. |
| UI / mutants | Mounted real payloads; M4 observable; M9/JS2/JS4 caught | CLOSED at harness/mutant scripts. Physical-phone testing NOT RUN. |
| CAP-C missing-token | Unchanged since 04a676f | Accepted / backlog. Error envelopes are not treated as clean terminals. |
| Gaps 3–4 | Decoders / exposure | Accepted — not reopened. |

## Residual backlog only

- Compare downgrade of a valid positive category (`CompareCertificationView` without ledger).
- Field-name lookup order mismatch (fails safe).
- CAP-C missing-token-as-clean-finish on a success envelope with no token.
- MassSearch desktop “Scoped P&L” header (optional rename).
- Physical-phone testing NOT RUN. Interactive browser walkthrough NOT RUN.

## Suite / build (2fe60bd fix)

See `TESTS.md` on this commit. Keys unset **3764 passed** / 3 G1-expiry failed / 440 subtests. Dummy **3764 passed** / same 3 failed. `npm run build` recorded there (`index-Dt5k-k7X.js`). Offline acceptance command green. Adapted `scripts/minimal_repros_2fe60bd.py` shows all 8 refuse/correct.

# RANKED100_RESEARCH_SEARCH_HISTORY (grant B): 2026-10-07 08:42 + invariant brief

**Outcome: 08:42 CERT / STATE / UI / CAP-A / CAP-B / CAP-D / CAP-E closed on `517c721`. PRODUCT_READY stays false. No live calls. No grant enabled. No merge/deploy. Spend this pass 0/0/$0.**

Binding work order: `CHATGPT_REVIEW_2026-10-07_0842_FULL.md` plus `INVARIANT_ACCEPTANCE_BRIEF_2026-10-07`. Gaps 3 and 4 stay closed and were not reopened. gtfo’s labelled six-atomic aggregate bridge stays accepted. DQ7n/BVZt honesty and capture exclusions stay. CAP-C stays accepted.

## This-review claim status

| Gap | Reviewer required closure | Status |
| --- | --- | --- |
| CERT | Bind bridge amounts/units to ledger; unique 1:1; empty/missing ledger non-certifying; auditor identity in both representations; headline unit mismatch does not certify | CLOSED. Tests listed in TESTS.md and the registry. |
| STATE | Rebuild evidence_class before category; ranked/compare/report GET/export do not keep saved C=MET | CLOSED. |
| UI | Mount actual ranked-phone, desktop, report, compare trees; live ResearchProfilePanel uses authoritative funnel/category | CLOSED. Physical-phone testing NOT RUN. |
| CAP-A | Store-authoritative load; persist-before-transport; persist failure prevents dispatch | CLOSED. |
| CAP-B | Reservation invalidates last_dispatch; progress bound to latest replay; old receipt cannot re-arm | CLOSED. |
| CAP-C | Terminal cursors | Accepted — not reopened. |
| CAP-D | Committed draft; A6PS additional page unavailable; per-wallet observations | CLOSED. |
| CAP-E | Operator/confirmed_at/baseline; remaining enforced at reservation; remaining 0 → zero transport | CLOSED. |
| Gaps 3–4 | Decoders / exposure | Accepted — not reopened. |

## Residual backlog only

- MassSearch desktop “Scoped P&L” header (optional rename to “Captured results”; not a blocker).
- Open-position ages remain `not_evaluated` (count only).
- Token-2022 stays observed-only. SwapTob unsupported.
- Zero leads. Capture draft stays disabled.
- Physical-phone testing NOT RUN. Interactive browser walkthrough NOT RUN.

## Suite / build (08:42 pass)

See `TESTS.md` on this commit. Keys unset **3747 passed** / 440 subtests / 1 warning (9 min 24 s). Dummy keys **3747 passed** / 440 subtests / 1 warning (9 min 18 s). `npm run build` recorded there (`index-OhAg4lQK.js`). Offline acceptance command green.

# RANKED100_RESEARCH_SEARCH_HISTORY (grant B): 2026-10-07 07:14 re-review

**Outcome: ACCEPT_AS_PROGRESS_ONLY remaining blockers held and fixed. PRODUCT_READY stays false. No live calls. No grant enabled. No merge/deploy. Spend this pass 0/0/$0.**

Binding work order: `CHATGPT_REVIEW_2026-10-07_0714_FULL.md` of PR #6 at `5cd05b7`. Gaps 3 and 4 stay closed and were not reopened. gtfo’s labelled six-atomic aggregate bridge stays accepted. DQ7n/BVZt honesty and capture exclusions stay.

## This-review claim status

| Gap | Reviewer required closure | Status |
| --- | --- | --- |
| 1 Comparison evidence | Validate unique 1:1 identities, mint/close match, amounts/units/tolerance; reject stale-positive-flag payloads; `completedEpisodeFields()` contradiction + fingerprint + ledger membership; JS half-even assertions | Done. Tests in `tests/test_chatgpt_review_2026_10_07_0714.py`. |
| 2 Saved-report decisions | Reconcile invalidates/recomputes qualification, audit, filters; fingerprint on membership change; reject missing close; ranked-row assertions | Done. |
| 3 Decoders | Closed — not reopened | Closed. |
| 4 Exposure/history | Closed — not reopened | Closed. |
| Capture enforcement | Reserve-before-transport; persisted timeout consumption; receipt-bound replay; terminal cursor; committed named items + CccS preceding-page rule; operator quota record | Done. Draft `enabled:false`. |
| Wording | Actual JS rendering of An9s + non-certifying audits; visible “sample/activity filter matches (not certified research leads)” | Done. Physical-phone testing not run. |

## Residual backlog only

- MassSearch desktop “Scoped P&L” header (optional rename to “Captured results”; not a blocker).
- Open-position ages remain `not_evaluated` (count only).
- Token-2022 stays observed-only. SwapTob unsupported.
- Zero leads. Capture draft stays disabled.

## Suite / build (07:14 pass)

See `TESTS.md` on this commit. Keys unset **3722 passed** / 440 subtests / 1 warning (8 min 55 s). Dummy keys **3722 passed** / 440 subtests / 1 warning (8 min 49 s). `npm run build` recorded there (`index-Dgx1_JEr.js`).

# RANKED100_RESEARCH_SEARCH_HISTORY (grant B): 2026-10-07 05:47 re-review

**Outcome: ACCEPT_AS_PROGRESS_ONLY remaining blockers held and fixed. PRODUCT_READY stays false. No live calls. No grant enabled. No merge/deploy. Spend this pass 0/0/$0.**

Binding work order: `CHATGPT_REVIEW_2026-10-07_0547_FULL.md` of PR #6 at `45c1494`. Gaps 3 and 4 stay closed and were not reopened. gtfo’s labelled six-atomic aggregate bridge stays accepted.

## This-review claim status

| Gap | Reviewer required closure | Status |
| --- | --- | --- |
| 1 Audit consumption | Certificate requires 1:1 + component proof, not fingerprint/status alone; ranked surfaces use `completedEpisodeFields()`; half-even tolerance parity | Done. Tests in `tests/test_chatgpt_review_2026_10_07_0547.py`. |
| 2 Saved ledger authority | `qualifying_profit()` / ranked / compare derive or reject; no saved-profile override | Done. |
| 3 Decoders | Closed — not reopened | Closed. |
| 4 Exposure/history | Closed — not reopened | Closed. |
| Capture enforcement | Named-item progress; phase/replay; A6PS start-only exception; executable_allowance; cursor continuity; recorder runner | Done. Draft `enabled:false`. |
| Wording | Ranked phone uses non-lead coverage display; no raw-boolean auditor text | Done. Physical-phone testing not run. |

## Residual backlog only

- MassSearch desktop “Scoped P&L” header (optional rename to “Captured results”; not a blocker).
- Open-position ages remain `not_evaluated` (count only).
- Token-2022 stays observed-only. SwapTob unsupported.
- Zero leads. Capture draft stays disabled.

## Suite / build (05:47 pass)

See `TESTS.md` on this commit. Keys unset **3714 passed** / 440 subtests / 1 warning (9 min 52 s). Dummy keys **3714 passed** / 440 subtests / 1 warning (9 min 24 s). `npm run build` recorded there (`index-sTfl9L_3.js`).

# RANKED100_RESEARCH_SEARCH_HISTORY (grant B): 2026-10-07 03:46 re-review

**Outcome: ACCEPT_AS_PROGRESS_ONLY blockers held and fixed. PRODUCT_READY stays false. No live calls. No grant enabled. No merge/deploy. Spend this pass 0/0/$0.**

Binding work order: `CHATGPT_REVIEW_2026-10-07_0346_FULL.md` of PR #6 at `76833dc` / `b1b1852`. Zero-lead outcome is accepted. The prior “no requirement-violating blockers” line is withdrawn.

## This-review claim status

| Gap | Reviewer required closure | Status |
| --- | --- | --- |
| 1 Audit | Fingerprint required; 1:1 membership; required components; gtfo aggregate labelled | Done. Tests listed in TESTS.md. |
| 2 Ledger + SOL sensitivity | Ledger authoritative; missing SOL is not established | Done. |
| 3 Decoders | RFQ requires transferChecked + real negatives; Token-2022 observed-only | Done. SwapTob remains unsupported. |
| 4 Exposure/history | No lot-count valuation; no requested-window fallback; open ages not evaluated | Done. |
| Capture | One progress rule; 58PW zero until named; reserved 12 not discretionary; fake-transport refuses | Done. Draft `enabled:false`. |
| Wording §8 | Worksheet total; bridge operands; An9s copy; verified tips; aggregate text | Done. 390×844 Chromium emulation only; physical-phone testing not run. |

## Per-wallet after this pass (vs 76833dc)

Episode nets and qualification labels are unchanged. gtfo confirmation text is now an aggregate rounding bridge (−0.000000006 SOL / 6 atomics; app 2.030645834 vs auditor 2.03064584), not “within 2 lamports.” BVZt/DQ7n remain independently audited at 4/4, coverage_blocked, not leads. An9s coverage_status stays `provisional_eligible` with display “Coverage gate eligible; not a research lead.”

# RANKED100_RESEARCH_SEARCH_HISTORY (grant B): 2026-10-07 ChatGPT review

**Outcome: Phase 1 A–L, Phase 2 decoders, Phase 3 disabled capture-draft rewrite. PRODUCT_READY stays false. No live calls. No grant enabled. No merge/deploy.**

`PRODUCT_READY` = **false**. B3 = **BLOCKED**. Two newest-first GTA pages are not complete history. No profitability claim. Not MATCH. Qualifying means the wallet meets the screen on matched trades in the captured window, never account performance.

Binding work order: `CHATGPT_REVIEW_2026-10-07_0116.md` of PR #6 at `6295021`. Each reviewer claim was checked against the code first. Stale claims are marked below.

**coverage_status and qualification_level are different fields.** Both are generated by `scanner.mass_search.labels.research_label_tables`. An9s is `coverage_status=provisional_eligible` and `qualification_level=conditional_captured_lot_result` at the same time.

## Grant and approval

- Grant `live-ranked100-research-search-2026-10-06-mitch` was already consumed. This pass did not enable it.
- Next-capture draft: `config/live_authorization.ranked100-depth-biased-next-capture-draft.json` (`enabled: false`). Uses `filters.blockTime.lt=1791206967` plus paginationToken. No top-level ISO `until`. Adaptive: one gtfo page first, then offline replay. 20 requests is a ceiling. `$0` is conditional on verified quota with overages disabled. Do not dispatch.
- Repo drafts stay `enabled: false`. No Helius or Birdeye call was made.

## Reviewer-claim verification

| Item | Reviewer claim | Verdict |
| --- | --- | --- |
| A | Audit inherited by address alone | True at `6295021`. Fixed: content fingerprint required. |
| B | qualification_level used count coverage only | True. Fixed: shared count-AND-value gate. |
| C | Stronger shortlist skipped days/span; NOT_EVALUATED | True. Fixed: ≥3 trading days and ≥7-day span from events. |
| D | qualification used worksheet / scoped_pnl | True. Fixed: completed-episode ledger only. |
| E | non-SOL sensitivity returned false | True. Fixed: `cross-currency sensitivity not established` blocks lead. |
| F | Proven router/platform fees and separate-tx tips | Partially done before; completed in this pass. |
| G | `_message_signers` missing header cross-check | True. Moved in, matching `compiled_instructions.py:150-185`. |
| H | “2 lamports” used for USDC | True. Asset-specific atomics + ROUND_HALF_EVEN. |
| I | An9s proceeds 196.517684744 vs 196.519198584 (Δ 0.001513840) | **Stale.** Both sides already 196.517684744. The quoted delta was ATA rent, previously counted as auditor proceeds. Remaining 4-lamport acquisition residue was on the app FIFO sale-row sum; the buy swap quote is 21.849947133. Costs agree within 1 lamport. |
| J | Worksheet-vs-episode bridges 58PW +45534.169937023, BVZt −1386.43924204 | True as of `6295021`. After Phase 2 decoders the worksheets moved; current bridges are below. |
| K | Concentration from sale-level profits; even-sample median wrong | True. Rebuilt from the episode ledger; A6PS now uses `positive subset; highly concentrated; negative excluding largest winner` in the summary table. |
| L | Exposure outside completed episodes / traversed interval / hold times | True gap. Added. |
| Phase 2 | Token-2022, RFQ fee-fill, SwapTob | True gaps. Token-2022 and the observed RFQ pattern implemented. SwapTob stays unsupported. |
| Phase 3 | Draft used top-level ISO `until` | True. Rewritten. Draft never runs. |

## Per-wallet table (window 2026-09-05T13:29:27Z → 2026-10-05T13:29:27Z exclusive)

Offline replay of the 10 genuine two-page captures. Generated by `research_label_tables`. Net P&L deducts verified costs only (network + published-list tips + proven router/platform fees). Unverified outside SOL withdrawals are the labelled sensitivity column, not tips. `AStZiY6…` is an unverified outside debit, not a tip. Wallets with 0 completed episodes do not show a Net figure.

| Rank | Wallet | qualification_level | coverage_status | blocking_reason | Coverage count / value | Concentration | Episode win rate | Verified tips SOL | Sensitivity unverified SOL | Completed | Net |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | gtfo…CgFL | conditional_captured_lot_result | coverage_eligibility_pending_reassessment | 4 unresolved-basis sales | 1 / 1 | positive subset | 11/16 = 0.6875 | 3.303280298 | 0.0547 | 16 | 2.030645834 SOL (completed-episode net); aggregate rounding bridge −0.000000006 SOL (6 atomics, not within 2 lamports; app 2.030645834 vs auditor 2.03064584; per-episode components may still agree); 2.030645839 SOL (worksheet total, partial coverage, not independently audited) |
| 4 | CccS…y1eU | conditional_captured_lot_result | coverage_eligibility_pending_reassessment | unresolved adjacent debits flip the sensitivity net sign | 1 / 1 | positive subset; highly concentrated; negative excluding largest winner | 3/6 = 0.5 | 1.131401016 | 0.296680516 | 6 | 0.120294936 SOL (completed-episode net); auditor confirms within 2 lamports: 0.120294936 SOL; 0.120294936 SOL (worksheet total, partial coverage, not independently audited) |
| 10 | BVZt…Y9n9 | conditional_captured_lot_result | coverage_blocked | 4 open lots; 7 unresolved-basis sales; cross-currency sensitivity not established; coverage gate requires count AND value; coverage_blocked | 0.785714286 / 0.803124951 | — | 2/4 = 0.5 | 0 | 0 | 4 | 234.310075 USDC (completed-episode net); auditor confirms within 2 USDC base units: 234.310075 USDC; 4403.445947971 USDC (worksheet total, partial coverage, not independently audited) |
| 11 | BSN5…BtCM | insufficient_evidence | coverage_blocked | 0 completed episodes; sensitivity not established; coverage_blocked | 0 / 0 | — | n/a | — | — | 0 | — |
| 14 | DQ7n…9Cys | conditional_captured_lot_result | coverage_blocked | 3 open lots; 1 unresolved-basis sale; cross-currency sensitivity not established; coverage gate requires count AND value; coverage_blocked | 0.933333333 / 0 | — | 3/4 = 0.75 | 0 | 0 | 4 | 54.96316 USDC (completed-episode net); auditor confirms within 2 USDC base units: 54.96316 USDC; 54.96316 USDC (worksheet total, partial coverage, not independently audited) |
| 15 | A6PS…vbot | conditional_captured_lot_result | coverage_eligibility_pending_reassessment | 3 unresolved-basis sales | 1 / 1 | positive subset; highly concentrated; negative excluding largest winner | 2/8 = 0.25 | 0.152 | 4.410 | 8 | 283.399579449 SOL (completed-episode net); auditor confirms within 2 lamports: 283.399579447 SOL; 283.399579449 SOL (worksheet total, partial coverage, not independently audited) |
| 17 | An9s…LYSB | conditional_captured_lot_result | provisional_eligible | 1 completed episode < min_sample 3; 27 open lots | 1 / 1 | positive subset | 1/1 = 1 | 0.112 | 0 | 1 | 174.657978612 SOL (completed-episode net); auditor confirms within 2 lamports: 174.657978611 SOL; 174.65797861 SOL (worksheet total, partial coverage, not independently audited) |
| 53 | 58PW…xvDL | conditional_captured_lot_result | coverage_blocked | 2 completed episodes < min_sample 3; 11 open lots; 2 unresolved-basis sales; cross-currency sensitivity not established; coverage gate requires count AND value; coverage_blocked | 0.8 / 0.853754365 | positive subset | 2/2 = 1 | 0 | 0 | 2 | 5614.586672 USDC (completed-episode net); auditor confirms within 2 USDC base units: 5614.586672 USDC; 50386.378661746 USDC (worksheet total, partial coverage, not independently audited) |
| 56 | AW6P…MzD6 | insufficient_evidence | coverage_blocked | 0 completed episodes; sensitivity not established; coverage_blocked | 0 / 0 | — | n/a | — | — | 0 | — |
| 90 | CRXo…V68U | insufficient_evidence | coverage_blocked | 0 completed episodes; sensitivity not established; coverage_blocked | 0 / 0 | — | n/a | — | — | 0 | — |

D13 exclusive partitions (must not regress): gtfo 71/4/50/0/75; CccS 170/17/1/0/12; A6PS 52/4/77/0/66 + 1 conversion; An9s 0/1/132/0/67.

## Before / after per wallet (6295021 → this pass)

| Wallet | Before completed / episode net / worksheet | After completed / episode net / worksheet | Notes |
| --- | --- | --- | --- |
| gtfo | 16 / 2.030645839 SOL / same | 16 / 2.030645834 SOL / 2.030645839 SOL | Independently audited. Opening-basis dependency remains. |
| CccS | 6 / 0.120294936 SOL / same | unchanged | Sensitivity sign-flip remains. |
| BVZt | 2 / 940.492859 USDC / −445.94638304 | 4 / 234.310075 USDC / 4403.445947971 | Token-2022 + RFQ fee-fill. Independently audited. Not a lead. Reviewer bridge −1386.43924204 is stale. Current bridge +4169.135872971. |
| BSN5 | 0 | 0 | Evidence-negative control. |
| DQ7n | 2 / −149.107753 USDC / same | 4 / **+54.96316 USDC** / same | Matches the reviewer projection −149.107753 + 117.121794 + 86.949119. Independently audited. Not a lead (coverage value share 0; cross-currency). |
| A6PS | 8 / 283.399579449 SOL / same | unchanged | Concentration warning now consistent including the summary table. |
| An9s | 1 / 174.65797861 SOL / same | 1 / 174.657978612 SOL / 174.65797861 | Proceeds agree. Acquisition uses the buy quote. Independently audited. Still < min_sample 3. |
| 58PW | 2 / 5614.586672 USDC / 51148.756609023 | 2 / 5614.586672 USDC / 50386.378661746 | Completed-episode net unchanged. Worksheet moved with Token-2022/RFQ inventory. Reviewer bridge +45534.169937023 is stale. Current bridge +44771.791989746. |
| AW6P | 0 | 0 | Evidence-negative control. |
| CRXo | 0 | 0 | — |

Neither BVZt nor DQ7n is a lead.

## Per-level counts (same function as the table above)

### qualification_level

| qualification_level | Count | Wallets |
| --- | --- | --- |
| stronger_research_shortlist | 0 | — |
| provisional_research_lead | 0 | — |
| conditional_captured_lot_result | 7 | gtfo, CccS, BVZt, DQ7n, A6PS, An9s, 58PW |
| insufficient_evidence | 3 | BSN5, AW6P, CRXo |

### coverage_status

| coverage_status | Count | Wallets |
| --- | --- | --- |
| provisional_eligible | 1 | An9s only. This is item-12 coverage, not a research lead. |
| coverage_eligibility_pending_reassessment | 3 | gtfo (unresolved basis), CccS (sensitivity sign-flip), A6PS (unresolved basis) |
| watchlist_incomplete_evidence | 0 | — |
| coverage_blocked | 6 | BVZt, BSN5, DQ7n, 58PW, AW6P, CRXo |

Research-screen default: **0 qualified**.

## Independent auditor vs app

`tools/independent_episode_audit.py` imports no `scanner/` package. A wallet is `independently_audited` only when episode membership and the acquisition / proceeds / cost / net components agree (asset-specific 2-atomic tolerance) and the counts are equal. The badge attaches only when the content fingerprint matches (raw capture hashes, reporting window, ordered transaction set, completed-episode ledger, accounting-policy version).

| Wallet | Status | App | Auditor | Episode net |
| --- | --- | --- | --- | --- |
| gtfo | independently_audited | 16 | 16 | 2.030645834 / auditor 2.03064584 SOL |
| CccS | independently_audited | 6 | 6 | 0.120294936 SOL |
| A6PS | independently_audited | 8 | 8 | 283.399579449 / auditor 283.399579447 SOL |
| An9s | independently_audited | 1 | 1 | 174.657978612 / auditor 174.657978611 SOL |
| 58PW | independently_audited | 2 | 2 | 5614.586672 USDC |
| BVZt | independently_audited | 4 | 4 | 234.310075 USDC |
| DQ7n | independently_audited | 4 | 4 | 54.96316 USDC |
| BSN5 / AW6P / CRXo | no_completed_episodes | 0 | 0 | — |

### An9s component bridge

| Field | App | Auditor | Δ | agree |
| --- | --- | --- | --- | --- |
| mint / close | 57yWMyhK… / 2VB1kpB8… | same | — | yes |
| acquisition | 21.849947133 | 21.849947133 | 0 | yes (buy swap quote; FIFO sale-row sum had been +4 lamports) |
| proceeds | 196.517684744 | 196.517684744 | 0 | yes. Reviewer 196.519198584 / Δ 0.001513840 is stale ATA rent. |
| costs | 0.009758999 | 0.009759 | −1 lamport | yes |
| net | 174.657978612 | 174.657978611 | 1 lamport | yes |

## Phase 2 decoders

1. **Token-2022 transfer fees.** Distinguish observed gross / net / withheld from inferred mint config. Fee ceiling is `ceil(amount * bps / 10000)`. Mint account bytes (max-fee / epoch) are absent from GTA, so a unique uncapped-ceiling bps match is **not** TransferFeeConfig. Ambiguous rate fits and capped/unknown cases fail closed as observed-only. Independently observed nets are preserved. Regression: BVZt `4YAVTERN…`, `46LTwehR…`, `5gsBEZxK…`; DQ7n `1Y1QbF3E…`, `3m8Mv7ub…`, `4iEHb4sF…`.
2. **RFQ fee-fill.** Exact observed pattern only: separate top-level `transferChecked` to `9PnYDCTJ5B4mJJMPvjCZ97L6ZBcti48CYgxv5QU1mV5G` under RFQ Fill. Explicit `rfq_platform_fee` / `platform_fee_usdc` (`not_subtracted_again` because the USDC is already in the wallet delta). `9PnYDC` is **not** a global fee sink. Unrelated-transfer guard unchanged. Regression: BVZt `3otd93M7…`, `3kkiuPNL…`, `2cdzEPn6…`.
3. **proVF4p SwapTob.** Bounded investigation only. Discriminator `aa2955b184501f35`, 61-byte payload, 95+ accounts. Logs name SwapTob / DEX hops. Official account layout and user/authority indices are not established from bytes. Stays unsupported. Sample `3uXPRZpM…`.

## Phase 3 capture draft (enabled:false, never runs)

Rewritten against the current Helius `getTransactionsForAddress` contract (`filters.blockTime.lt` + `paginationToken`). Offline test `test_next_capture_box_driver_emits_supported_gta_request` proves the serializer emits that request and rejects top-level `until`.

Adaptive plan: phase 1 is one gtfo continuation, then offline replay. One explicit phase-two rule: a later page is allowed only after a named sale/lot shows an observable result (resolved or approached) on the previous page. CccS shares that rule; A6PS may start phase two after replay as a separately authorized exception but still shares the global stop/ceiling. 58PW executable allowance is 0 until a specific named sale/lot is recorded. Reserved 12 cannot override per-wallet limits or become discretionary spend. Fake-transport runner refuses wrong wallet/cutoff/cursor, phase-two before replay, over-budget, and consumed/wrong-kind grants. Fresh approval must bind execution artifact + current quota + overages-disabled + approval time + expiry; this pass does not invent a live grant. Exclusions: An9s / BVZt / DQ7n / CRXo. Never stop or continue because a wallet turned positive. `$0` stays conditional on verified quota with overages disabled.

## Named tests

Phase 1: `tests/test_chatgpt_review_2026_10_07.py` — `test_stale_audit_does_not_attach` (A); `test_99_5_count_80_value_does_not_qualify` (B); `test_20_episode_3_mint_one_day_burst_fails_stronger_shortlist` (C); `test_positive_worksheet_negative_episodes_does_not_qualify` (D); `test_cross_currency_sensitivity_blocks_lead` (E); `test_proven_platform_fee_is_a_cost_unexplained_transfer_is_not` (F); `test_message_signers_header_cross_check_rejects_conflicting_flags` (G); `test_asset_specific_atomic_tolerances` (H); `test_even_sample_median_uses_mean_of_two_central_values` (K); `test_synthetic_cases_never_count_as_genuine_research_wallets`.

Phase 2: `test_token_2022_transfer_fee_bvzt_dq7n_jupiter_buys`; `test_rfq_fee_fill_bvzt_three_sales`; `test_unrelated_transfer_guard_still_rejects_non_rfq_outer_owned_transfer`; `test_swaptob_remains_unsupported_after_bounded_investigation`.

Phase 3: `test_next_capture_box_driver_emits_supported_gta_request`; `test_item17_next_capture_manifest_is_disabled`; `test_next_capture_fake_transport_refuses_wrong_wallet_cutoff_cursor_phase_budget_grants`.

03:46 re-review negatives (`tests/test_chatgpt_review_2026_10_07_rereview.py`): `test_fingerprintless_audit_does_not_certify_genuine_path`; `test_mismatched_fingerprint_detaches_audit`; `test_negative_ledger_positive_summary_does_not_qualify`; `test_missing_sol_sensitivity_blocks_lead`; `test_component_bridge_requires_exact_membership_and_present_components`; `test_gtfo_aggregate_rounding_bridge_is_not_within_two_lamports`; `test_committed_gtfo_audit_uses_aggregate_rounding_bridge`; `test_unknown_cost_inventory_is_not_an_open_lot_count`; `test_traversed_interval_is_not_requested_window_fallback`; `test_open_position_ages_are_not_evaluated_without_positions`; `test_token_2022_ambiguous_and_capped_are_not_config`; `test_synthetic_marking_does_not_justify_permissive_audit_branch`; `test_an9s_coverage_copy_is_eligible_not_a_lead`.

Prior labelled-wallet tests remain: `test_labelled_wallets_are_independently_audited_in_committed_json`; `test_58pw_independently_audited_sits_next_to_episode_net`; `test_compare_reports_mismatch_when_auditor_finds_episodes_app_missed` (now records the 4/4 reconciliation); `test_astziy6_is_unverified_outside_debit_not_a_tip`; `test_frontend_pnl_figures_carry_worksheet_or_episode_label`.

## Suite / build

See `TESTS.md` on this commit. Keys unset **3703 passed** / 440 subtests / 1 warning (9 min 9 s). Dummy keys **3703 passed** / 440 subtests / 1 warning (9 min 19 s). `npm run build` recorded there (`index-Cm9QhyzB.js`). Prior `76833dc` suites were 3688/440.

## Still blocked

- **PRODUCT_READY = false**
- **provisional_research_lead = 0.** CccS is blocked by sensitivity sign-flip. An9s is blocked by 1 episode < min_sample 3 and 27 open lots.
- Opening-basis dependencies on gtfo (4) and A6PS (3).
- OKX SwapTob, DFlow, L2TExMFK, and unreviewed System opcode stay unsupported.
- BVZt and DQ7n are independently audited at 4 episodes and still `coverage_blocked` / cross-currency. Not leads.
- Stronger research shortlist is empty.
- Next-capture draft stays `enabled:false`. Do not dispatch.
- 0-episode wallets (BSN5 / AW6P / CRXo) now say `sensitivity not established` because no SOL sensitivity field was populated; that is not a measured zero.
- Open-position ages stay `not_evaluated`: `analytics.open_positions` is a count, not a timestamp list. Traversed interval uses observed `in_window_span` start/end only.
- Token-2022 unique uncapped-ceiling bps is observed-only, not TransferFeeConfig. SwapTob remains unsupported.

## Backlog (document only; not built)

- Capital employed
- Return on capital
- Profit factor
- Out-of-sample confirmation
- Followability gate
- A fresh discovery cohort with selection rules fixed beforehand
- The dense compare screen (usability)
