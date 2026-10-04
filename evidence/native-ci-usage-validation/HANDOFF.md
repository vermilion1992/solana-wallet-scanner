# Validation-only continuation

Repository: `vermilion1992/solana-wallet-scanner`, private. Branch: `codex/product-completion`.

Accepted application commit: `8aee62e50297d6773f347b77cecc3e8794f233cf`.
Accepted application source manifest: 241 files, SHA-256 `05143c96aea6afd96ede6006fb27b99bf26e648611cf161fe620306154284e96`.
Its evidence-only published HEAD was `af02789bb33a3baa0ddf4592d883bab3074c093d`.

Validation fixture commit: `59a4c1e6a4f6556382f49961ddc13284ebca2604`.
Current overall source manifest: 241 files, SHA-256 `0fad6d9bd6647b2663724d4bae2e280a02ed499f03f730eeff58f057ac98d365`.
The exact mismatch is one test file: two usage-only calls in `tests/test_indexed_report_integration.py` now request `/api/usage` directly. Both routes use the same unchanged `usage()` closure. All other 240 source byte hashes and workspace modes are unchanged. Production, frontend, compiled assets, locks, tools, workflow and all assertions are unchanged. No new full application acceptance is claimed.

## Actual follow-up checks

- `fixture/COMMAND.json` and `fixture/RAW.log`: fixed interpreter, `-m pytest -v --durations=10 tests/test_indexed_report_integration.py`, actual exit 0, 15 terminal passing tests in 53.97 seconds, 600-second cap. Every retained guard finalizer completed with provider, credential and external transport counters zero and usage unchanged.
- `backend/COMMAND.json` and `backend/RAW.log`: fixed interpreter, `-m pytest -q`, actual exit 0, 3,167 terminal passing tests and 440 separately reported subtests in 434.13 seconds, 1,800-second cap. The integration group is included in this full suite; do not add its 15 repeated executions to the unique suite count.
- Both command receipts bind source, validation commit, current four locks and local Python 3.12.14 / Node 24.19.0 / Linux runtime, and verify stability after execution.
- `FRESH_SOURCE_EXTRACTION.json`: fresh Git archive extraction verifies all 241 source bytes and executable classes. Workspace permission modes and native Git checkout permission modes are deliberately distinguished.
- `review/FIXTURE_DIFF_REVIEW.json`: independent read-only review, exact two-expression byte diff, preserved normalized module AST, original 15-node contract, all accounting/parent-immutability assertions and all other source unchanged.

## Original hosted failure preserved

Run `37215031205`, attempt 1, at exact `af02789...`: ten jobs passed; indexed integration timed out and the strict union rejected that receipt. All twelve original API-digest-bound artifact ZIPs and immutable final metadata are retained under `original-native/`. `review/NATIVE_CI_FINAL_REVIEW.json` verifies their provenance and nonpassing outcome. Thirteen call-phase PASS markers before teardown are not completed test credit; there is no terminal integration summary. The receipt reports a 600-second timeout and 789.56 seconds elapsed. No OOM or complete root cause is asserted.

The unchanged-source local diagnostic shows the guard fetched a 362,400,903-byte full-state response solely for usage comparison and took 20.79 seconds in teardown. Its outer command exit is unavailable, so it is diagnostic evidence only. The modified instrumented genuine case has an actual exit-0 receipt: 54.48-second call, 0.029-second teardown, original inputs/locks/source/Git unchanged, and all three guards zero. Peak RSS remained about 2.46 GiB because the full financial-report assertions remain intact. Instrumentation setup failure and original command-lifecycle limits are preserved, not relabelled application defects or acceptance.

The new automatic hosted run must independently pass under the unchanged caps. This evidence commit precedes that run; native status comes from its exact GitHub Actions run and downloaded raw receipts. No manual rerun of the original failure is requested.

## Product scope remains separate

The original application evidence remains authoritative: `../position-history-batch/FINAL_GATES.json`, its thirteen scoped gates, browser receipts, four archived workflow commands and independent expectations. Those expensive application/browser/workflow checks were not repeated for this fixture-only follow-up. The full genuine archive workflow still correctly returns BLOCKED when real acceptance is required.

`PRODUCT_READY=false`. B1 historical completeness remains unresolved. B2's evidence interfaces and normal offline import/report/rebuild path are development-functional; complete real-wallet accounting remains OPEN. B3 complete genuine acceptance remains BLOCKED. The current issue register and source decision are unchanged; the remaining complete contracts are CAP-HIST, CAP-ORIGIN, CAP-ROUTES, CAP-CLASS, CAP-VALUATION and CAP-POSITIONS. This is not solely a missing-data claim: unfinished complete accounting implementations and unavailable population/history evidence remain distinct blockers.

The retained genuine indexed sample and its independently calculated fees are partial evidence, not wallet-wide profit or qualification. The current repository preserves the original raw inputs, separately worked expectations, fixtures, source decision, issue register, acceptance matrix, validation entry point and complete Git history. A normal clone includes those inherited dependencies; this directory is follow-up evidence, not a stand-alone replacement product.

No Helius probe, provider request, key retrieval, purchase, upgrade, funded wallet, transaction submission, signing or trading was performed for this continuation. Private publication is separately subject to the checksum-bound full baseline audit and inspection of every new current/history blob. No release ZIP or external public upload is produced. Preparation controls are reported separately from application tests.
