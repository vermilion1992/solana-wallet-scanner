# Codex task — stabilise by defect family, then complete a real product milestone

## Assignment

Act as the implementation engineer for the Solana Wallet Scanner. Start from v0.3.11 or the explicitly reconciled newer working tree. Do not simply patch the last review example and produce v0.3.12. Complete the stabilisation batch below in one working branch, using small coherent commits and a maintained issue register. A batch is not an instruction to produce one enormous unreviewable patch.

The existing codebase is retained. Shared chronology, source-consistency and instruction-scope components already exist; extend their contracts rather than duplicating them or rewriting the application.

## Baseline and what not to claim

The supplied v0.3.11 ZIP has SHA-256 `8da8ee0519643c02b156279f117244ea545631cc5775ddb2dfe5d74a680302f7` and 152 unique entries. A targeted external replay in this handoff passed all 79 original R15 cases. The developer reports a 1,527-test full suite; that complete claim was not independently rerun for this workflow handoff. Full wallet accounting remains open in current source and documentation. Read evidence/BASELINE_CHECK.md.

## Phase 1 — establish the candidate and the work queue

Record the source commit or manifest, lockfile hashes, interpreter/runtime versions, current method versions and the baseline outcomes. Preserve existing user work. Merge the short AGENTS.md rather than blindly replacing instructions.

Update ISSUES.md by evidence category: confirmed defect, retained regression, missing capability, external-data decision, environment blocker or deferred improvement. Do not treat an unavailable browser or package registry as an application bug. Do not count examples as separate defects.

Create one repeatable local validation entry point, such as `python tools/validate.py --profile focused|candidate`, using the real commands in ACCEPTANCE.md. Focused mode is for iteration; candidate mode runs every applicable gate and returns a nonzero/incomplete result if a required check is failed, blocked or missing. It must never print RELEASE_READY solely because pytest is green. Do not introduce a new dependency or a paid hosted runner just to wrap existing commands.

## Phase 2 — one bounded whole-path audit and implementation batch

Review the supported path end to end: source enumeration and read failures; format and instruction normalization; chronology and account relevance; absolute quantities and ownership; metric dependencies; frozen rebuild; displayed/exported status. Cover all source-role and instruction-contract entries the application claims to support, not only the most recently failing operation.

Use the matrix in ACCEPTANCE.md. Before coding a new fix, add the reproducer and a positive preservation control. Centralise common dependency decisions where that removes inconsistency. Identify untested sibling paths and test them within this batch. Record investigated non-defects without inventing a new finding.

Audit every existing instruction target mapping against a pinned primary schema reference, including Token, System and Associated Token entries already admitted by the application. Cover only the declared contract; unsupported extensions stay explicitly unsupported. Distinguish field-shape compatibility, operation semantics and real-chain provenance. Reuse the v0.3.11 source-referenced fixture approach; do not generate expected fields from the production table.

Generalise existing review tests into reusable, parametrised controls where safe. Keep external original reproducers auditable and do not delete them to reduce counts. Use deterministic seeds and focused combinations; avoid a huge unbounded Cartesian product. Cover every high-risk axis explicitly and representative cross-axis interactions, including real processing-cap boundaries.

## Phase 3 — review and close the stabilisation batch

Run focused checks after each change, then full backend, locked frontend checks/build and real launcher/browser/rebuild checks on a frozen candidate. Use an isolated data directory and deny provider/credential activity. Do not test on the user's live database.

Run a distinct review pass using REVIEWER_TASK.md. A fresh read-only Codex review/chat is useful when available, but it is not proof of independent correctness. Return the complete finding set, not one new issue per release. Resolve confirmed in-scope blockers, retest their affected paths, then rerun final candidate gates. Track optional improvements separately rather than silently expanding the batch.

If a required environment is unavailable, produce one concrete blocker entry with the failing command and required environment, and continue other checks. Do not repeatedly retry unchanged blocked setup or call that gate passed. A clean locked installation and an actual browser check must occur in a permitted environment before those gates close.

## Parallel planning workstream — turn R1 into a source and delivery decision

Do not let endless scoped holding-time hardening replace the scanner's product purpose. In parallel with the bounded stabilisation batch, map the R1 source and implementation dependencies. This planning may be concurrent; overlapping production-file edits may not.

Deliver `docs/R1_SOURCE_DECISION.md` with the supported scope, required historical ownership/lifecycle evidence, acquisition origins, transaction completeness, costs, classification, and valuation/flows needed by each claimed metric. Inventory what existing archives actually establish. Verify a proposed data source's capabilities and current limits from primary documentation; do not assume a free key, current token list or fixed-point paging proves historical completeness.

Stay inside the user's no-required-subscription constraint. Do not buy access, spend credits or use credentials without explicit approval. When no authorised source establishes a dependency, record exactly which metric remains blocked and present a bounded alternative scope as a product decision—not as silent satisfaction of the original wallet-wide requirement. Do not write an empty adapter and declare R1 implemented.

Once the data contract is genuinely supported, implement a narrow end-to-end real-wallet vertical slice in coherent tasks: acquisition/coverage -> event normalization and ownership -> cost and position accounting -> metric-specific evidence -> saved report/UI. Validate with archived real inputs and expected calculations derived independently of the production implementation. A loss or policy miss is acceptable. Synthetic datasets remain necessary negative controls but cannot close real-data acceptance.

Realised P&L does not inherently need boundary marks; economic P&L does. Scoped token-account timing is not the wallet-wide mint-aggregate completed population. Preserve losing, breakeven and unresolved eligible episodes. Keep the independent 28-day calculation distinct from the display period.

## Delivery and stopping conditions

Deliver one candidate when the scoped stabilisation gates in ACCEPTANCE.md are satisfied, or a truthful bounded blocker report when they cannot be. Then continue the separate R1 milestone under its source contract; do not pretend that Gate A closes Gate B.

The handoff should be short: baseline/candidate identity, issue IDs resolved with evidence, remaining blockers, gates executed, and source/test locations. Full raw logs live in an evidence folder. Export a ZIP only at an acceptance checkpoint or at explicit request. No cosmetic redesign, unrelated dashboard features, trading, paid source acquisition or threshold relaxation.
