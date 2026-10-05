# Implementation backlog and execution order

## Working method
Use small reviewable commits. Record actual progress in one ledger keyed by the IDs below. The listed paths are integration targets, not mandatory class names. Prefer extensions to current modules over a parallel app. Do not create one document-only PR for each task.

First milestone: **MS-00 through MS-04 produce one end-to-end report.** UI polish and full provider breadth wait. If real access is blocked, complete the same path with explicit synthetic transports while documenting that the real result is not yet demonstrated.

## MS-00 — Establish a safe current baseline
**Depends on:** nothing.

Inspect working tree/ancestry, AGENTS, active contracts, source and lock versions. Read existing tests for discovery, investigation, reports, observers and budgets. Record the baseline command results that matter. Preserve existing uncommitted work and failures. Choose the implementation base; do not assume the reference SHA is still newest.

**Deliver:** baseline receipt, source/lock identity, concise issue entries, branch.
**Proof:** affected baseline gates actually executed or precisely blocked. No credentials read or provider calls in offline checks.

## MS-01 — Choose a usable source and map definitions
**Depends on:** MS-00.

Implement the capability record and adapter interface. Recheck primary documentation, test one authorised indexed source under a bounded probe, map fields and choose GO/GO_LIMITED/NO_GO. Reuse existing provider gateway guards and durable reservations. Add a query-only adapter, not an external agent/CLI with trading capabilities. If no source is authorised, implement parsing against separately labelled fixtures and emit the concrete access blocker.

**Deliver:** one primary discovery adapter, schema fixtures, capability record, request-cost model.
**Proof:** pagination, schema drift, entitlement failure, secret redaction, read-only allowlist, unsupported fields and exact metering-unit tests.

## MS-02 — Add bulk universe and immutable decisions
**Depends on:** MS-00; adapter interface from MS-01.

Add versioned SQLite migrations and lightweight paginated queries. Preserve old records, backup/restore and data-dir lock. Separate a 10,000-row local capacity from legacy candidate/deep-audit caps and from authorised network work. Define run/membership/metric/decision structures and deterministic deduplication.

**Deliver:** bulk storage and service methods, frozen run IDs, stage summaries.
**Proof:** old database migration, exact restoration, duplicate pages, moving snapshots, deterministic order, invalid identifiers, count conservation and 10,000-row local query benchmark.

## MS-03 — Implement the inexpensive screening rules
**Depends on:** MS-01, MS-02.

Add separate Mass research plan validation, tri-state metric handling and four-outcome stage decisions. Preserve Strict research byte/value semantics. Compile supported provider filters only when they match the intended preliminary definition. Use summary proxies for queue priority, not strict qualification. Refilter frozen rows offline without provider calls.

**Deliver:** local triage engine, persisted first shortlist, reason codes, plan snapshots.
**Proof:** missing versus zero, USD versus SOL, average versus median, stale/conflicting windows, precision, unknown-provider floors, budget deferral and unchanged strict preset.

## MS-04 — Finish one genuine vertical slice
**Depends on:** MS-01–03 and actual authorised access for the live portion.

From a discovered candidate, use the existing targeted collector/history path and report pipeline. Adapt provider native records to current archive/evidence contracts; preserve original responses and checkpoint receipts. Produce at least one supported real purchase/sale pair with separately worked cost/timing expectations. Display through the normal authenticated API, reopen and export. A temporary minimal mobile-readable panel is enough.

**Deliver:** actual source-to-report application path, one genuine populated report or a precise live blocker; offline integration still completed.
**Proof:** true buys/sells, supported fee/P&L/timing values, source links, explicit unresolved dependencies, JSON export, restart. A balance observation or quote alone is not this result.

## MS-05 — Add targeted reconstruction for several survivors
**Depends on:** MS-04.

Plan needed history by metric, fetching older purchase basis only where relevant and preserving failed-transaction costs. Cache/decode each source once. Do not invent a second FIFO implementation or a blanket 'complete' flag. Expand the dominant supported routes only when genuine failures establish their importance; measure unparsed activity by economic relevance as well as count.

**Deliver:** genuine multi-wallet report set with raw-to-report reconciliation sheets and actionable missing-data reasons.
**Proof:** at least three genuine reports under the analytic population contract; include a non-qualifying/loss or unresolved control. Removing required evidence revokes only dependent metrics and creates no stronger financial conclusion.

## MS-06 — Add material-exit and research-quality features
**Depends on:** MS-03, MS-05.

Reuse existing t90/copy review. Add versioned diagnostics only where needed: first/t50/t90/final exit distribution, gross-positive concentration versus strict net-profit concentration, remove-biggest-winner stress, open losses and origin restrictions. Represent insufficient data explicitly. Do not label people as scammers/insiders from correlations.

**Deliver:** behaviour shortlist and explainable metric card per survivor.
**Proof:** dust-tail fixture, scaling-in distinction, unknown transfer basis, open-loss omission control, one-hit-winner control, missing valuation and partial-history population tests.

## MS-07 — Implement cost-aware orchestration and recovery
**Depends on:** MS-02–06.

Add work leases, stable idempotency keys, operation-specific caps, checkpointed pagination, bounded concurrency, retries/backoff and hard cancellation. Use a persistent shared budget, including pending/in-flight reservations. Defer capped work; do not drop it. Reuse token and transaction evidence within correct scopes. Include deterministic audit sampling of early rejections.

**Deliver:** run/pause/resume/cancel service and next-work planner.
**Proof:** kill/restart after reserve, after dispatch and after archive; no quota reset/double charge/double event; first decisive fail avoids later expensive work; all stage counts conserve; timeout receipts are explicit.

## MS-08 — Complete the user-facing funnel
**Depends on:** MS-07; can evolve from MS-04's minimal UI.

Add Search, window/preset/budget summary, stage counts, paginated sortable candidates, decision explanations, detailed report opening, shortlist/export and progress. Place P&L, median hold, t90, sample size, costs and evidence basis together. Use current auth/CSRF guards. Do not build hosting/APK/sign-in infrastructure in this task.

**Deliver:** mobile-readable ordinary workflow, not a benchmark-only CLI.
**Proof:** 360px and desktop browser cases for real/synthetic distinction, populated report, no matches, source outage, budget cap, resume, filter change with zero network requests, export and restart.

## MS-09 — Run genuine mass and local-performance benchmarks
**Depends on:** MS-01–08; live authorisation for genuine collection.

Freeze source, locks, plan and universe acquisition protocol. Attempt the genuine 1,000-unique-candidate benchmark and the separate 10,000-row local performance benchmark. Record measured requests, charged units, elapsed time, memory/hardware, failures and stage yield. Do not pad the genuine universe with synthetic rows or repeatedly fetch it until its results improve.

**Deliver:** benchmark receipt, candidate/decision artifacts, request ledger, reconciliation records and browser evidence.
**Proof:** `docs/06_BENCHMARK_ACCEPTANCE.md` and the structural checker plus independent checks. A provider cap below the target means an explicit partial result, not a passed 1,000-wallet claim.

## MS-10 — Demonstrate forward operation and freeze a comparison
**Depends on:** MS-05, MS-06; baseline observer already exists.

Use the existing fixed-entry/first-sale strategy first. Record genuine detection -> delay -> quote -> hypothetical inventory -> exit. Add separately named proportional exits only with supported inventory. Freeze selection arms, dates, budget and delay scenarios before results; use the same economics across arms. Present historical replay separately from prospective capture.

**Deliver:** genuine operational example and pre-registered comparison; longer observation may remain RUNNING/INCONCLUSIVE.
**Proof:** no-look-ahead, unavailable exits retained, cash conservation, paused gaps not filled as followed trades, and no zero-signal success. At least one real eligible entry/exit path is required for operational demonstration; financial usefulness needs separate prospective evaluation.

## MS-11 — Freeze, review and hand over
**Depends on:** all implemented items; incomplete live/financial items remain labelled rather than hidden.

Run exact-candidate applicable backend, dependency, frontend, security/quota, archive/rebuild, browser and source-bound CI gates. Extend `tools/validate.py` without losing selectors or inflating counts. Distinct review should examine omissions, positive controls and claims, not merely restate developer receipts.

**Deliver:** one private implementation branch/PR when already authorised, otherwise local patch/bundle; final report, precise source SHA, full gate matrix and blockers. No merge, public deploy or secrets.
**Proof:** delivery template complete; old reports/evidence unchanged; source hashes match validated code; no financial or full-product conclusion from synthetic or empty evidence.

## Explicit non-goals and parking lot
Defer new hosting, mobile wrappers, notification services, trading execution, automated insider accusation, multi-chain support, ML ranking, distributed workers and an exhaustive whole-chain index. Historical wallet-wide completion remains a separately tracked contract; improvements discovered here may help it, but do not expand this milestone into an indefinite prerequisite for displaying useful subset analytics.
