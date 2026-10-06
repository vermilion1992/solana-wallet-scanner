# Mass Wallet Search — invariant-based independent acceptance review

## Handoff header — the implementing agent completes this

Candidate full commit SHA: `PENDING_THIS_EVIDENCE_COMMIT — implementing agent will replace with the full SHA of the commit that lands this brief on cursor/research-search-b-fix-1055`
Application/tested SHA, if different: `SAME_AS_CANDIDATE`
Evidence-only SHA, if different: `SAME_AS_CANDIDATE if RESULT/TESTS land in the same commit; otherwise the later evidence-only SHA`
PR / branch: `PR #6 / cursor/research-search-b-fix-1055 (confirmed; base cursor/mass-wallet-funnel-v1-1055)`
Evidence manifest and raw-log paths: `evidence/mass-wallet-funnel/research-search-b-2026-10-06/INVARIANT_REGISTRY.md`; `evidence/mass-wallet-funnel/research-search-b-2026-10-06/offline-acceptance/RESULT.json`; `evidence/mass-wallet-funnel/research-search-b-2026-10-06/offline-acceptance/RAW_*.log`; `evidence/mass-wallet-funnel/research-search-b-2026-10-06/TESTS.md`; `evidence/mass-wallet-funnel/research-search-b-2026-10-06/RESULT.md`
Offline acceptance command(s): `.venv/bin/python scripts/offline_acceptance.py`
Known NOT RUN / BLOCKED items: `Physical-phone testing NOT RUN. Interactive browser/responsive walkthrough NOT RUN this pass (ranked phone/desktop/report/compare trees are mounted with react-dom/server under Node ≥22). Live capture BLOCKED (draft enabled:false). Provider/Helius/Birdeye calls NOT RUN and must stay blocked. Full keys-unset application suite is recorded separately in TESTS.md when executed.`

Do not assume a blank field is evidence of success. Resolve it from the accessible repository where possible; otherwise report the resulting limitation. Do not infer the candidate from the previous reviewed tip.

---

You are Mitch's strict independent reviewer for **Mass Wallet Search / Research Search B**, a read-only Solana wallet research application in `vermilion1992/solana-wallet-scanner`. The previous handoff used draft PR #6 and branch `cursor/research-search-b-fix-1055`; verify the candidate rather than assuming those references are unchanged.

Your task is to decide whether the new pinned candidate produces **correctly scoped, evidence-supported, repeatable research results**, and whether its still-disabled next-capture contract is structurally approval-ready. This is not a request to implement features, authorize capture, merge, or trade.

## 1. Context and the change in review standard

The last reviewed baseline was **`04a676fc22695eb679164ae734136687254f7ffa`**, with verdict **ACCEPT_AS_PROGRESS_ONLY — b**. The 08:42 review in this conversation found that exact examples had been patched while neighboring failures remained. Earlier independent verification also passed tips that subsequent review broke.

Therefore, do not merely rerun the named regressions. Establish the underlying invariants, inspect every consumer of their decisions, and independently try to falsify those invariants using cases the implementer did not supply.

Treat the previous review and `review_04a676f_probes.zip`, when available, as starting evidence. Its probes were isolated copied predicates, not a full checkout, integration run, browser run, or physical-phone test. Reproduce against the new repository's actual functions and public application paths; do not silently upgrade the old probes' evidentiary strength.

Do not promise “unbreakable.” Give a defensible acceptance decision with explicit scope, verified properties, remaining assumptions, and reproducible counterexamples or acceptance evidence.

This brief adds broader adversarial-testing and repeatability requirements. Label them **new process requirements**, not defects supposedly proved in earlier reviews. Accept equivalent evidence that establishes the invariant; do not insist on a particular testing library or architecture.

## 2. Binding constraints and preserved scope

No trading, signing, custody, secret inspection, real credentials, provider requests, billable quota probes, or live spend. Review can read repository/evidence data and run isolated offline tests. Capture tests must use a recording fake transport; any unexpected real provider access must fail. Local disposable test/mutation changes are allowed, but do not commit, push, merge, alter the submitted candidate, or enable capture.

`PRODUCT_READY` remains false unless you explicitly justify a separately scoped recommendation to change it. Do not change the flag yourself. `enabled:false` remains unchanged. Product acceptance, capture-contract approval-readiness, merge permission, live authorization, and physical-phone usability are **separate decisions**; none implies another.

PASS requires evidence. **NOT RUN, BLOCKED, reported results, inspected tests, and executed tests are distinct.** A suite count is not an acceptance argument. Phone-sized Chromium emulation is not a physical-phone test; physical-phone testing remains NOT RUN unless genuinely performed and evidenced.

Zero qualifying wallets is acceptable. An incorrect positive qualification is not. Do not require a winning wallet, more purchased history, an APK, new metrics, or a new discovery source to close this captured-cohort review.

Blocking means a concrete wrong-money, wrong-qualification, authorization, data-loss, or required policy/implementation mismatch, or missing evidence necessary to establish a required acceptance property. Distinguish a demonstrated defect from an unverified requirement. Optional hardening and cosmetics belong in backlog unless you demonstrate a reachable blocking failure.

State the trust boundary. Include reachable malformed inputs, stale/corrupt saved reports, duplicate invocations and process failures. Do not claim protection against an operator rewriting the application or destroying all durable records; do not manufacture such a threat model to block this review.

Retain the previous acceptance of Gaps 3–4, gtfo's disclosed six-atomic aggregate difference, DQ7n/BVZt's honest coverage-blocked subsets, and the terminal-cursor closure unless a concrete regression appears. Preserve DQ7n/BVZt capture exclusions and 58PW's zero executable allowance. “Scoped P&L” naming remains cosmetic unless the underlying presentation demonstrably misstates results.

Historical Search B spend was reported as **20 Helius requests / 200 documented credits / $0 / 0 Birdeye**. Previous corrective passes were reported as zero spend. Keep that history separate from what you can actually establish about this review's provider activity.

## 3. Pin the evidence before judging it

Freeze the candidate full SHA. Identify the exact application, tests, fixtures, policy/configuration, capture draft, generated bundle, and evidence files under review. Do not silently move to a newer tip during review.

Where application, build, test, and evidence commits differ, establish ancestry and compare relevant trees. Evidence-only commits are acceptable when the tested application, tests, configuration and inputs are unchanged; do not reject harmless documentation differences or invent circular self-hashing requirements.

Read the prior-review-to-candidate diff **and the surrounding call chains**. Search for every reader of certification, fingerprints, evidence classes, qualification categories, thresholds, saved funnels, coverage state, replay receipts, progress, and quota balances. Inspect existing API, ranked, saved-report, compare, export, desktop and phone paths where supported. A correct new helper is insufficient when another consumer bypasses it.

Require a manifest recording commit identities, input hashes, runtime versions, dependency/lockfile identities, exact commands, test seeds, relevant configuration, raw results, build/bundle identity, and explicit NOT RUN items. Never include secret values. Verify generated assets correspond to the reviewed source rather than an older working build.

## 4. Turn the prior blockers into invariants

Use stable identifiers below in findings and the regression registry. Reopening the same rule through another input shape is not a new feature request. For each finding, say whether it is a remaining prior Required closure, a regression, or a newly raised blocker.

### CERT — certification describes the actual evidence

Certification requires a complete, internally coherent, uniquely matched correspondence between the **actual bound completed-episode ledger** and the app/auditor comparison evidence. Counts, matching supplied fingerprint strings, stored `agree` flags, or agreement between two detached copies are insufficient.

Verify complete episode identities and one-to-one membership, including mint and close signature and any genuinely necessary disambiguator. Check both app and auditor identities. Reject unexplained duplicates, missing/extra members, mismatched wallets or captures, and contradictory redundant representations. Inspect identities, amounts and units in both top-level and episode-local bridges; do not compare only a convenient subset. A single canonical representation is acceptable if contradictory legacy representations cannot silently survive.

Bind each app-side bridge's acquisition, proceeds, costs, net and unit to its ledger episode. Separately compare app and auditor components under the existing documented unit-specific tolerances. Ledger binding must not become a loose aggregate comparison. Do not widen tolerances to manufacture agreement or silently combine SOL and USDC. Distinguish deterministic ledger equality from permitted independent-auditor rounding differences.

An empty or missing displayed ledger must not disable membership validation. Stale positive metadata must not produce certification, an auditor-confirmation badge, or a lead. Preserve independently supported observations with accurate labels; do not erase valid evidence merely because certification fails.

Fingerprints and related bindings must cover all decision-affecting inputs, directly or through separately checked versioned bindings. Recompute rather than trusting incoming IDs. Changing membership with equal totals/counts, a component with unchanged net, units, or an applicable accounting/qualification policy must invalidate affected cached decisions unless revalidated.

Preserve the documented accounting rules. Missing cost basis, unknown ownership, unsupported decoding, sensitivity assumptions, and incomplete coverage cannot become favorable invented facts. Do not solve an admission defect by loosening accounting policy or suppressing warnings.

Test decimal handling across Python and actual JavaScript. Cover the existing signed half-even boundaries, two-/three-lamport edges, and relevant malformed, non-finite, precision and missing-unit inputs. State the supported representation contract; do not add permissive input formats merely for a test. Neither rounding nor parsing differences may create a frontend-only green result.

Previous witnesses to eliminate include: ledger `1 / 4 / 0 / 3 SOL` versus both bridge sides `999 / 1002 / 0 / 3 SOL`; USDC bridge versus SOL ledger; an auditor-close mutation only in the episode-local representation; empty/missing displayed ledger with stale matching IDs; and mismatched app/auditor headline units. These are seeds, not the entire test domain.

### STATE — all reused decisions follow the reconciled evidence

Reconciliation must update or explicitly invalidate **every dependent output**, not just completed net, count and principal lead status. Trace evidence class, qualification category, coverage-dependent decisions, thresholds, filters, saved funnels, counts, sorting fields where affected, badges, audit binding, compare outputs and supported exports.

There must be no fallback to a stale positive saved field after new evidence has invalidated it. In particular, inspect the former stale `evidence_class` to `positive_matched_position_evidence` path, saved funnel `C = MET`, ranked rows, and both compare funnels.

Persist a full otherwise-valid report, not a conveniently reduced profile. Reuse it with negative net, empty ledger, same-total/same-count membership changes, altered component values/units, removed audit evidence, and applicable policy changes. Keep stale positive fields wherever an older report could actually contain them. Exercise save/reopen and supported legacy loading.

Require idempotence: reconciling twice must not change the semantic result. A fresh computation and a resumed computation from the same normalized evidence and settings must agree. Explain expected differences such as generation timestamps rather than demanding irrelevant byte identity.

A partially missing report may still show supported observations. It must not inherit a stronger decision from a previous generation. Keep current qualification separate from an explicitly labelled immutable historical decision, where historical reports are supported.

### UI — actual users see the same decision the evidence supports

Test the actual ranked-phone, desktop, report and compare components, not only formatters, string searches or constructed text. Exercise the source-to-API-to-component path and verify the delivered build corresponds to it. DOM/component assertions prove rendering; browser checks establish responsive behavior; physical-phone claims require a real device.

Render missing/empty ledger, contradictory audit, mixed units, stale positive category/funnel, and legitimate non-certifying evidence. Inspect badges, summary counts, tooltips and visible decision text. Backend rejection paired with a positive frontend badge is a blocker.

Preserve the distinction between **sample/activity filter matches** and certified research leads. An9s's previously accepted status was coverage-gate eligible, below the minimum completed sample, and not a research lead. Re-establish the current status from evidence rather than hardcoding an old number. `certified_research_wallet` must not provide an alternative lead path.

### CAP-A — durable authority and consumed attempts cannot roll back

Durably reserve budget before transport. A failed/timed-out/ambiguous attempt remains consumed under the documented contract. Reopen, stale supplied state, an empty state argument, or another reachable entry point must not reset authoritative accounting. A storage failure before reservation completes must prevent transport.

Exercise crash/fault boundaries: before persistence; after reservation but before transport; after transport but before response persistence; and during failed-attempt persistence. An uncertain outcome must not authorize an automatic unaccounted retry. Inspect the actual runner and durable store, not only a stand-in selector.

Check reachable duplicate-call/concurrent-writer behavior. Serialized single-runner enforcement is acceptable; do not require a distributed system. If two reachable calls can spend the same allowance, demonstrate the race or missing enforceable serialization.

### CAP-B — replay and progress belong to the latest relevant attempt

Track the newest attempted dispatch separately from the last successful response. Starting a new attempt invalidates preceding replay authority even when the new attempt fails. Bind receipts to the required wallet, capture/grant context, attempt/page identity, response identity and state generation. A supplied boolean or an old successful page must not stand in for current evidence.

Dependency progress must come from the same accepted replayed page/response, not from an independently supplied unbound progress object. Match an executable named item and that wallet/phase's allowed progress observations.

Exercise success → replay → next attempt timeout → reopen → old receipt, and fresh page-two receipt combined with page-one progress. Neither may unlock an otherwise prohibited request. Also vary wallet, page, response, receipt order, and state generation independently; matching one field does not establish the rest.

### CAP-C — cursor states are explicit and terminal means terminal

Retain the accepted not-started / valid-continuation / exhausted distinction. Exhaustion must survive reopen and never fall back to an initial or consumed cursor. A malformed response is not automatically a clean terminal result. Test the provider-response contract offline, including relevant missing fields and wrong-wallet/capture cursor reuse. Do not reopen the previously accepted closure without evidence of a regression.

### CAP-D — the exact committed policy is executable

Load the exact committed draft. Tests may use an explicitly synthetic, recorded in-memory test authorization; do not replace the policy with a simplified fixture or enable the real file.

Verify gtfo's executable dependency items, CccS's shared preceding-page phase-two rule, and per-wallet allowed observations. A6PS's previously descriptive pseudo-mint must be replaced by a genuine bound identity for any action that requires it, or that additional action must remain explicitly unavailable. Preserve any independently justified first-page rule rather than conflating it with additional-page permission.

Keep 58PW at zero executable allowance, the twelve reserved requests non-discretionary, and DQ7n/BVZt excluded. Missing or unsupported progress evidence must result in no additional dispatch, not an optimistic default.

### CAP-E — approved remaining quota constrains reservation

A truthy quota object, arithmetic consistency, or a hash alone does not establish fresh approval. Enforce the existing approval identity, artifact binding, operator attribution, quota observation and approval/expiry relationships. Clearly distinguish recorded human/provider assertions from facts the app verifies. Do not invent a new external identity service or billable preflight requirement.

Define the quota observation's baseline and deductions unambiguously. At reservation, enforce the most restrictive applicable remaining global, grant, wallet and phase allowances without spending reserved requests or double-subtracting already-accounted usage.

Zero remaining allowance must produce **zero transport calls**. A smaller positive allowance must stop exactly at its approved limit across successes, failures and reopen. Expired, future-dated, stale, conflicting, malformed or wrongly bound approval must not dispatch. Use the documented freshness policy; do not invent an arbitrary time limit during review.

Test through the real evaluator, reservation/store and fake transport, not merely a quota-record validator. Prove that the validated remaining balance is actually consumed by the dispatch decision.

## 5. Attack the rules beyond the supplied examples

Build a bounded adversarial matrix across **input shape × lifecycle × consumer × decision consequence**. Choose relevant combinations and explain omitted boundaries; do not pretend to exhaust all possible inputs.

**Independent oracle and positive controls.** Establish at least one otherwise-eligible synthetic fixture with independently worked component arithmetic, plus genuine captured-cohort checkpoints. Synthetic fixtures must be unmistakably synthetic and must not enter real search evidence. Do not calculate “auditor expectations” by calling the production calculation being verified. Cross-language agreement is not an independent accounting oracle. Document shared dependencies and the actual scope of independence. A correctly supported eligible fixture must pass; “reject everything” is not a working product.

**Systematic mutations.** Delete, duplicate, substitute, reorder where semantics permit, and corrupt relevant identities, amounts, units, flags, versions and boundaries. Change only one of redundant representations; then test correlated changes that preserve count/net while violating provenance or components. Include invalid fields inside otherwise-valid payloads, not just obviously malformed objects.

**Property-based and metamorphic checks.** Use deterministic generated cases, recorded seeds and minimized failing examples. Reordering storage presentation while preserving economic execution order must not change the result. Reingesting identical captures must not double-count; duplicate input must be rejected or deduplicated by the documented rule. Equivalent ingestion batches, cache paths and save/reopen cycles must yield equivalent semantic results. Do not randomize causal transaction order and then demand FIFO invariance. Removing required evidence, absent verified replacement evidence or an explicit policy change, must not improve qualification.

**Fault/state-machine checks.** Generate relevant valid and invalid sequences through save/reconcile, reserve/dispatch/fail/reopen, and replay/progress/advance. Assert accounting conservation, monotonically consumed attempt budgets within a grant, immutable attempt identities, and no authorization resurrection. Test old-state/new-response and new-state/old-receipt combinations rather than only a linear happy path.

**Test the tests.** In a disposable worktree, deliberately remove or bypass selected safety checks: ledger component binding, unit equality, redundant-identity validation, stale-funnel invalidation, authoritative-state selection, failed-attempt replay invalidation, and remaining-quota enforcement. The relevant behavioral test must fail for the intended reason. A syntax/import failure is not meaningful mutation coverage. An undetected safety-relevant mutant is a test gap; report it. No arbitrary repository-wide mutation percentage is required.

**Independent challenge after freeze.** Choose additional fixtures/seeds and combinations after examining the pinned implementation. Do not rely exclusively on implementer-generated examples. Where feasible, keep the oracle independent of production helper structure. For every failure, trace reachability to an actual output or authorization decision. Distinguish a helper counterexample, integrated reproduction, source-traced concern, and speculative edge case.

Do not stop at the first blocker when other independent checks remain feasible. Finish a bounded review, report what was not executed, and avoid expanding into an unrelated feature audit.

## 6. Establish repeatability and honest search answers

The acceptance mechanism must be reusable, not a one-off review transcript. Require one documented offline entry point, or a small documented sequence, that runs the invariant suite, integration regressions, actual component tests, generated cases and committed genuine-fixture checks. It must exit nonzero for failures, detect or explicitly report skipped mandatory checks, and preserve machine-readable results and raw logs.

Maintain an invariant registry mapping **ID → rule → source enforcement → positive/negative/property/fault tests → consumer coverage → evidence artifact**. Future fixes extend the rule's test family, not merely append one incident-specific example.

Demonstrate fresh-process and persisted-reopen reproducibility using pinned inputs, versions and settings. Freeze or explain clock dependence; control nondeterminism and stable tie-breaking where it affects results. Relevant policy changes must re-evaluate current decisions or clearly label historical snapshots. Do not require new export/import features where none exist.

For genuine captured wallets, compare current output with the previous accepted baseline. Explain any change in completed count/net, certification, category, coverage, filters or lead status with source evidence and independently checked expectations. Do not force old numbers to remain unchanged after a proved accounting correction, and do not bless new numbers merely because the code generated them.

The search result must reveal what it actually knows: searched/captured universe and window, applicable policy, completed sample, per-unit amounts, audit status, coverage limits, sensitivity/concentration caveats where already supported, and a concrete reason for admission or exclusion. Distinguish observed captured results from whole-wallet profitability, and research eligibility from a claim of future profitability or copyability.

“No qualifying wallets under these inputs and rules” is a legitimate result. “No profitable wallets exist,” “all history is complete,” or “safe to copy” requires evidence this scoped product may not possess. Do not demand new backlog metrics to make the existing scope honest.

## 7. Required answer format

Start with Mitch's decision in plain English: **what is trustworthy now, what is not, and whether the next action is more offline fixing or a separately authorized bounded capture.** Do not bury the answer under test totals.

Then provide these sections:

**1. Reviewed identity and evidence strength.** Exact candidate/application/evidence/bundle identities, source and paths inspected, actual executions and runtime, reported-only evidence, and NOT RUN/BLOCKED checks. State provider activity only to the extent observable. Do not imply repository access or execution you did not have.

**2. Independent verdicts.** Separately judge captured-cohort product acceptance, repeatable acceptance-harness sufficiency, capture-draft structural approval-readiness, and phone/browser usability evidence. Explicitly preserve no merge permission, no live authorization and unchanged flags. Do not conflate a scoped product verdict with completion of deployment or physical-phone operation.

**3. Required-closure table.** For CERT, STATE, UI and CAP-A through CAP-E: **closed / partially closed / still open / unverified**, with source locations, exact tests/artifacts and the strength of evidence. Confirm previously accepted closures remain accepted unless you demonstrate a regression.

**4. Blocking findings only.** For each, give stable ID, prior-required/regression/new classification, reachable entry point and prerequisites, minimal failing payload or event sequence, expected versus actual result, source/call chain, reproduction command/seed, user-visible or budget consequence, and the invariant-level closure test. Label unexecuted reproductions. Separate optional hardening afterwards.

**5. Adversarial coverage and test strength.** Show positive controls, generated-case bounds/seeds, metamorphic/state-machine coverage, cross-layer checks, and deliberate safety mutants detected or missed. Explain what the existing named tests would have failed to catch. Give remaining assumptions; do not invent a numerical confidence score or extrapolate zero sampled failures into a guarantee.

**6. Genuine-cohort and wording check.** Report only verified current results and material changes. Specifically recheck gtfo's six-atomic disclosure, DQ7n/BVZt's scoped subsets and exclusions, An9s's sample/coverage distinction, and screen-count wording. Do not repeat historical numbers as freshly recomputed results.

**7. Repeatability handoff.** Provide exact offline command(s), manifest, registry and raw-result locations, minimized counterexamples, and any untested environments. Where tools permit, supply a downloadable review bundle clearly separating executed probes from proposed tests. Never invent an artifact or a download link.

**8. One next action.** Choose exactly one:

- **a:** Capture draft is structurally approval-ready as written, still disabled; any actual execution requires Mitch's separate explicit authorization and the existing fresh-quota rules.
- **b:** Hold and fix the demonstrated product/integrity blockers or unmet Required closures first.
- **c:** Captured-cohort product is acceptable, but capture approval remains blocked; name only the capture blockers.
- **d:** Another necessary action, precisely specified, including obtaining inaccessible evidence when a defensible decision cannot be made.

Use **ACCEPT_AS_PRODUCT** only when required captured-cohort safety and repeatability properties are supported by sufficient evidence. Use **ACCEPT_AS_PROGRESS_ONLY** when progress is established but required closures remain open or materially unverified. Use **REJECT** for a candidate whose demonstrated regressions or unsound evidence warrant rejection; do not equate an unavailable tool with a proved code defect.

An offline captured-cohort acceptance does not establish whole-wallet completeness, live-capture permission, future trading performance, or physical-phone readiness. Explain the remaining boundary without manufacturing a new blocking feature requirement.

End with exactly one line:

`ACCEPT_AS_PRODUCT — <a|b|c|d>`

or

`ACCEPT_AS_PROGRESS_ONLY — <a|b|c|d>`

or

`REJECT — <a|b|c|d>`
