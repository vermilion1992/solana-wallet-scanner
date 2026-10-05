# Architecture: a cost-aware research funnel

## A. One pipeline, several evidence levels
The data flow is:

`authorised source -> immutable response archive -> bulk universe -> local triage -> targeted behaviour -> reconstructed reports -> frozen observation cohorts -> quote-only comparison`.

Every user-visible number must carry its basis. A provider estimate, a raw-derived subset result, an independently reconciled subset result, a strict whole-wallet result and a hypothetical follower result are different records, not successive renamings of the same field.

### Stages
| Stage | Question | Main input | Output / costly operation |
|---|---|---|---|
| A: acquisition | Which addresses are plausible leads? | Paged indexed rankings, diverse token cohorts, retained candidates or explicit imports | Frozen unique universe; do not retrieve full history for every row. |
| B: inexpensive triage | Is the available summary worth further work? | Bulk fields and cached summaries | First shortlist; request only missing discriminating summaries. |
| C: behaviour | Could this activity plausibly be followed? | Bounded targeted activity, token breakdown and liquidity observations | Material exit timing, acquisition-origin and concentration diagnostics. |
| D: reconstruction | Do supported results survive raw-data accounting? | Required history, purchase origins, costs and relevant evidence | Reconciled report, strict evaluation where supportable, unresolved dependencies. |
| E: forward selection | Which candidates deserve a fixed observation budget? | Frozen research results and explicit policy | Named prospective cohorts; never retrospective copied performance. |

Only apply a criterion when its definition and evidence prerequisites hold. A provider's trade count is not a safe upper/lower bound for our completed-position count without a proved mapping. A low provider figure may lower queue priority; it cannot automatically establish a strict policy failure.

## B. Universe design and pagination
Store a candidate once per chain/address, with multiple dated memberships. Preserve originating page, token/pool, source, ranking mode, source timestamp, fetch timestamp and inclusion reason. Imported labels are untrusted text, not identity or profitability certificates. Native identity is checked before stronger wallet claims.

Acquire diverse leads within the permitted source universe. Support retained candidates and token-age/liquidity strata when data and access permit. Do not claim market-wide recall or fill missing universe coverage with manufactured addresses. Record unavailable strata and provider-imposed floors/caps.

Freeze `selection_as_of` and the page acquisition interval. Provider offset rankings can move between requests. Deduplicate, detect repeated pages/non-progressing cursors, keep a bounded retry/reconciliation policy, and disclose that a collection may be a multi-time snapshot rather than an atomic ranking. Never call it an exact as-of historical universe without a source that supports that contract.

For each source: raw rows = valid unique additions + duplicate rows + invalid rows. A valid non-trader address can subsequently fail identity; do not silently discard it during aggregation. Keep source memberships even when the global address is a duplicate.

## C. Decision semantics and saved shortlists
A decision includes `run_id`, `stage_id`, `candidate_id`, policy/metric versions, decision time, source hashes, result, exact reason codes and next required capability.

Use four outcomes:
- `PROMOTED`: meets this stage's prerequisites or explicitly enters its labelled exploration lane.
- `REJECTED`: a supported stage criterion failed.
- `DEFERRED`: missing/stale/conflicting evidence, inaccessible source, insufficient remaining budget or a capped queue.
- `PENDING`: not evaluated yet.

For each stage: `input = promoted + rejected + deferred + pending`. The next stage's input equals the preceding stage's promoted output for that same frozen run. Budget-limited deferrals must not be counted twice as rejections. A resumed/new evidence run links to the earlier run and does not mutate its historical decision snapshot.

Do not auto-relax criteria until three candidates pass. A user edit creates a new policy snapshot and local preview; source refresh happens only on explicit action or already-authorised scheduling.

## D. Query design and persistence
Extend the existing SQLite design before introducing Redis, Celery, a new database or a distributed platform. Use additive, versioned migrations with backup/restore tests. Keep the single-process/data-directory lock and serialized transactions unless a separately reviewed change is necessary.

Suggested normalised tables (names may be adapted):
- `search_runs`: source/lock/plan hashes, window, status, budgets and parent run.
- `candidate_universe`: chain/address and identity state.
- `candidate_memberships`: run/source/page/stratum/rank and raw evidence hash.
- `metric_snapshots`: metric key, decimal value, units, period, population, evidence basis, status and freshness.
- `stage_decisions`: immutable run/stage/candidate decisions and reasons.
- `work_items`: idempotency key, lease, checkpoint, requested operation and budget reservation.
- `report_links`: existing immutable report IDs and reconciliation records.
- `benchmark_receipts`: performance and evidence summaries.

Index the fields used for filtering/pagination; use an exact fixed-point representation or validated decimal comparator for sortable money fields, not lexicographic decimal-string ordering or binary floating-point P&L. Keep canonical decimal strings at boundaries. Test negative numbers, ties, very small values and missing values.

Do not repeatedly call `Store.list()` for all detailed reports to render a 50-row table. Serve paginated lightweight summaries with stable tie-breaks; load report detail only on inspection. Preserve existing backup/export coverage for new tables.

## E. Cost-aware work planner
Stage policies specify required capability, maximum candidates, per-wallet request/transaction ceilings and shared provider-unit ceilings. Storage capacity and collection authorisation are separate limits.

Within eligible work, start with high information value at low marginal cost. Initially use a deterministic documented priority tuple: already cached -> likely decisive inexpensive criterion -> research priority -> stable candidate ID. Log each choice. Only adapt test ordering from measured rejection yield and cost in a new plan revision; do not train it on later financial outcomes of the same test cohort.

Reserve a small configurable exploration budget for a deterministic sample of early rejects/deferred cases. Preserve their original label and analyse them in a separate audit lane. This measures obvious false-negative behaviour, not chain-wide recall.

A decisive rejection stops further expensive work for that candidate except a predeclared audit sample. Unknowns generate the smallest necessary follow-up: e.g. an earlier purchase page, not a fresh 90-day scan of everything.

## F. Requests, caching and recovery
Reuse the current provider gateway/reservations and exact evidence archives. Add adapter-specific capability and metering contracts; an HTTP request is not always one billing unit. Keep providers' units separate.

Reserve the maximum plausible authorised cost before dispatch. Settle according to established metering; an ambiguous timeout cannot automatically refund a possibly charged request. Release only a provably undispatched reservation. A crashed worker resumes idempotently, does not restart quota or create duplicate financial events. Concurrency and retries must share the same persistent budget.

Cache keys include chain, provider, operation, parameters, snapshot/window and method version. Token-level facts can be reused only for the relevant time and scope. Today's mint permission cannot prove historical sellability. Deduplicate shared transaction bytes but retain every candidate's evidence linkage.

Incremental history uses stable checkpoints plus a bounded overlap and signature deduplication. Changed/forked or missing transactions remain reconciliation events, not invisible overwrites. Store confirmation and observation timestamps. Unsupported transaction versions or instruction routes remain counted gaps.

## G. API and phone-readable interface
Add routes equivalent to create/preview/start/pause/resume/cancel a search, inspect capability/budget status, page a stage's candidates, inspect decision reasons, open existing reports and export. Names should fit current route conventions. Existing session, CSRF, host and request-size guards apply to all new routes.

Minimum UI: one **Search** control with window, preset and approved budget; a stage funnel; a sortable shortlist; a report panel; and explicit progress/reason text. Keep 360px mobile width usable. No giant per-wallet settings form is required for normal operation.

Always distinguish `not scanned`, `no eligible trades observed`, `unsupported activity`, `source unavailable`, `budget reached`, `waiting for new activity` and `empty result after complete declared search`. Show actual dates, last update, decoded/raw counts, failed transactions and omitted metric populations.

Changing filters against cached rows should make zero external calls. Live updates and collection require a separate authorised command. Do not expose the localhost-only app publicly as part of this task.

## H. No new opaque composite score
Use hard prerequisites, then explainable multi-column ranking. Financial attractiveness cannot override an unknown exit or unmeasured coverage. Keep research merit, evidence quality and follower-operational compatibility separate. Do not invent a 0–100 'safe to copy' or 'legitimacy' score.
