# Codex next milestone — complete the supported wallet-report workflow

## Assignment and baseline

Continue the existing Solana Wallet Scanner repository. This is the next active assignment, not a replacement architecture, new issue tracker or restart of the stabilisation audit. Reconcile it into the existing CODEX_TASK.md and ISSUES.md; retain prior assignments and evidence as history. Preserve AGENTS.md and its safety constraints.

The supplied FINAL_GATES.json identifies candidate commit `96fb1ebb7f6f41dc3c3c72ff4cac209a3fdcc272` and source manifest `b3ec1bc2b862af41952d2a0f93d47f26ea1ba9add07dd6e6d8021745fc213534`. It records Gate A ACCEPTED_IN_SCOPE and Gate B OPEN. The external review checked the three supplied code/document hashes and manifest arithmetic, not the complete checkout or the reported backend/browser execution.

Use that candidate or an explicitly reconciled successor. Do not revert to the earlier v0.3.11 ZIP: comparison with the new manifest shows eight changed files and seventeen additional paths. Inspect the current diff and preserve user work; do not reset a dirty worktree to satisfy a hash check.

The next product objective is a supported real-wallet report through the ordinary application workflow: select a wallet and settings, acquire or import authorised evidence, pause/resume where collection applies, reconstruct the supported accounting, explain coverage and uncertainty, inspect sources, save/rebuild and export. The reported test count is not this acceptance criterion.

## Work boundaries

Keep the application local, read-only and scanner-only. No signing, custody, trade execution, private keys, required paid subscription, silent threshold relaxation or fabricated completion evidence. These instructions do not authorise new provider calls, credential lookups, use of the user's remaining quota or purchases. Public documentation review and local work may continue within the existing environment permissions. Use only already authorised archived data until any necessary live collection is specifically authorised.

Preserve prior reports, source bytes/hashes, frozen references, collector ancestry, quotas, settings, security controls and per-metric uncertainty. Do not turn a sample, imported declaration, synthetic fixture or newly created empty wallet into proof that an existing real trading wallet's historical population is complete.

## Small maintenance item — proposed PROC-03

The attached validator-boundary tests reproduce a runner problem, not a new wallet-accounting defect. With every external command stubbed successful, the unchanged tools/validate.py can return ACCEPTED_IN_SCOPE when browser/result.json is missing or reports FAILED, INCOMPLETE, UNKNOWN, or lacks a state. Malformed and non-object JSON raise an exception before a structured final decision. The actual browser_acceptance.py and its original result were not available to this reviewer, so no claim is made that the recorded browser run exhibited this mismatch.

Review `proposed_fix/validate_receipt_guard.patch` and integrate the equivalent small correction into the current runner. It requires a zero-exit command AND a readable explicitly PASS browser receipt, preserves FAILED/BLOCKED outcomes, records the receipt hash and handles invalid results as incomplete. It passed 32 isolated runner checks; that is not an integrated application/browser sign-off.

Merge the tests into the existing validation-gate module, adapting its positive receipt fixture to the actual browser producer's schema without weakening the rejection assertions. Audit the other structured-result boundaries the runner actually consumes in this same bounded change. Do not invent unsupported output formats or silently accept future status strings. Reuse existing required_record validation where appropriate.

This is a validation-tool change: do not bump financial or position methodology solely for it. The source manifest and review binding must be renewed for the next candidate. Retain the historical FINAL_GATES.json unchanged. Do not return a release containing only this maintenance fix as though the product objective is complete.

## B1 / DATA-01 — resolve the existing source decision, not another generic research plan

First read the actual `docs/R1_SOURCE_DECISION.md`, `docs/CONTRACT.md`, `docs/ACCEPTANCE_MATRIX.json`, available archive inventory and relevant blueprint sections. These files are already referenced in the candidate; their contents were not supplied with the four-file handoff. Do not reconstruct that decision from its title or the issue-summary sentence.

For each metric promised by the current product contract, identify the exact evidence prerequisite and the available proof. Name the source/method, supported interval and protocols, historical ownership/lifecycle coverage, acquisition origins, page termination and missing-history rules, cost/classification requirements, and boundary marks/valued flows where applicable. Distinguish documented provider capability, the account's actual entitlement, local retrieved evidence, and independent completeness verification.

Return a bounded go/no-go on the proposed source for each required claim. Unknown entitlement is not proof of unavailable capability; a generous quota is not proof of historical completeness. Do not conclude that no free route exists merely because the cached sample is insufficient. Conversely, do not promise a source solves the problem before validating its coverage contract.

When a live probe is genuinely necessary, specify the minimum read-only probe, requested fields, proposed request/credit cap, endpoint, evidence to retain and remaining permission required. Do not execute it without the relevant authority. Escalate the concrete data/access or material scope decision in one message, not an open-ended question about architecture.

If the original wallet-wide scope cannot presently be substantiated under the permitted sources, keep its acceptance OPEN/BLOCKED and describe a narrower research preview only as an explicit alternative product decision. Do not silently substitute that preview for Gate B.

## B2 / CAP-01 — implement the nonblocked end-to-end work

A missing real acceptance corpus blocks real-data acceptance, not every line of implementation. Once the input contract is specified, continue executable local work while source verification is pending. Do not build a provider-specific adapter around unverified fields, and do not submit an empty adapter as a completed feature.

Extend existing accounting, collector/history, source-consistency, report and UI components before adding parallel ones. Suggested internal slices, to reconcile against the current source:

1. A validated evidence-input/coverage contract and a functioning archived-evidence path. Retain source identity, raw hashes, acquisition receipts, scope, boundaries, unsupported states and precise missing dependencies. Integrity and source provenance are different checks; an imported `complete:true` cannot establish coverage.
2. Normalised events and historical account ownership/lifecycle for the supported scope, then a ledger and mint-aggregate position population. Include partial exits, re-entry, transfers, fees, failed records, losing/breakeven and unresolved episodes. An unknown incoming acquisition is not free inventory or profit.
3. Connect existing cost-basis calculations to those source-backed inputs, then derive metric-specific evidence and policy decisions in the normal saved-report/rebuild path. Do not replace hardcoded UNKNOWN decisions with caller-supplied booleans. Independent 28-day consistency must not be derived from a shorter display period.
4. Use the existing interface to show supported values, unresolved reasons and evidence paths; preserve import/scan, settings, progress, pause/resume where applicable, report inspection, immutable rebuild and export. Unsupported data must be visible rather than counted as a successful financial report.

Development fixtures may exercise a positive supported branch, but must stay visibly synthetic and cannot close real-data or whole-wallet acceptance. Add a separate executable product check rather than teaching the existing Gate A runner to claim that its unit-test success proves Gate B.

Dependency isolation is mandatory. A missing valuation mark can block economic P&L without automatically invalidating independently established realised P&L. An unknown acquisition cost blocks dependent monetary results without necessarily erasing independently established scoped timing or native fees. Wallet-wide cohorts and classifications still require their own eligible population proof.

## B3 — real report acceptance and product delivery

Before declaring the original product complete, run one genuine nontrivial wallet dataset through the normal report path, with explicit supported scope and authorised archived inputs. The dataset must support the actual population/period being claimed, not just selected winning transactions. Freeze expected results calculated independently of the production implementation. A losing or non-qualifying wallet is valid acceptance.

Exercise positive supported metrics and negative dependency-removal/restoration cases. Include coherent omissions, such as loss of an account lifecycle or acquisition record, not only corrupt JSON. Verify that removal cannot strengthen dependent certainty and that duplicates do not double-count. A scoped success must not become a global completeness claim.

Use the existing full candidate checks, a distinct diff review and actual browser workflow on the frozen final candidate. Retain the permitted Linux runtime evidence; do not assert Windows/macOS or the user's target-machine acceptance without execution. Complete any actual target-platform check required by the agreed delivery contract. In an offline harness, provider/credential counters must remain zero; an authorised live acquisition has its own bounded receipt and must not be described as zero-call offline validation.

Gate B closes only when the existing source, implementation and independent real-data acceptance requirements are met. A partially implemented slice or blocked source remains useful progress but is not PRODUCT_READY.

## Efficient execution and review

Maintain one integrated branch and one issue register. Parallelise source research and nonoverlapping implementation only after the evidence interface is agreed. Avoid concurrent edits to shared accounting/history modules. Make coherent internal commits. Use focused checks after related edits, then one full final candidate run after the batch; rerun earlier full gates only when their dependencies changed or a new reproduction requires it.

Do not reopen R5–R15 or deferred protocol extensions merely to expand the report. Retain their tests and investigate actual new regressions. Do not stop at another AGENTS.md, source-decision rewrite, green counter, or validation-tool-only handoff. Escalate only a genuine permission/spend/material-scope dependency; continue nonblocked work.

OpenAI's Codex guidance recommends concrete goal/context/constraints/done-when instructions and testing plus review before acceptance. This task supplies those boundaries; do not add another planning framework.

## Next handoff — one reproducible checkpoint

Return a compact status summary: candidate identity; implemented user-visible behaviour; completed issue IDs; B1/B2/B3 states; actual commands and outcomes; and the one remaining decision, if any. Keep complete logs as evidence, not repeated historical narratives.

Provide the exact candidate checkout/archive (or an accessible identified commit), existing R1 source decision and acceptance documents, canonical fixture JSON, the real application and validation tools, and FINAL_GATES plus its referenced raw logs and browser result. Include clean-install and review records, supporting captures and the authorised reproducible real-data corpus when B3 is claimed. Use portable relative paths and hashes. Exclude secrets, environments/dependency directories and unapproved private databases. Do not rewrite raw evidence just to make it exportable; identify any authorised access limitation explicitly.

A single checkpoint archive for review is appropriate; a new ZIP/version after every individual fix is not. If a source remains blocked, deliver the executable work actually completed plus the bounded blocker. Do not claim a working complete scanner from the four-file summary alone.
