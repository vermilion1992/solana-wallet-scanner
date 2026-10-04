# Acceptance — fewer handoffs, stronger gates

The matrix and validation runner implement this acceptance contract. Actual
acceptance still requires the exact candidate's explicitly passing receipts;
implementation of a gate does not mean it has executed. Retain the original
product contract; a narrower milestone does not change the promised wallet-wide
scope.

## Gate A: scoped evidence stabilisation

**Done:** all known in-scope release-blocking defects have a reproducible test and a verified fix; historical required regressions are retained; supported controls remain useful; the declared matrix is covered; full applicable tests/build/rebuild/browser checks have evidence; the final candidate has been reviewed. Every omitted or blocked check is explicit. This does not mean all imaginable bugs have been disproved.

### Shared matrix to map and fill

| Axis | Required coverage within the supported contract |
|---|---|
| Source role | Selected and alternative transactions; wallet/account signature pages; block order/time; ownership and relevant snapshot/metadata roles; declared unknown roles |
| Availability | Readable agreeing, conflicting, missing, corrupt/checksum-invalid, null/malformed, unsupported, omitted at a real cap, restored exact bytes |
| Representation | Legacy/v0 supported cases and rejected typed versions; outer/inner; parsed/compiled/partially decoded; mixed/program-identity conflicts; canonical target fields |
| Relevance/chronology | Relevant, provably disjoint, ambiguous; before/within/after; same-slot ordering; inclusive lower/exclusive upper boundary; unresolved times/slots/execution |
| Execution/quantity | Success/failure; pre/post absolute quantities; zero and nonzero boundaries; partial/full exit; ownership changes; fees isolated from unrelated token facts |
| Source set | Reference permutations; exact duplicate links; semantic agreement in different bytes; third-source conflict; budgets before/at/after limit |
| User path | Direct derivation; collection-to-report boundary; frozen rebuild API; displayed/exported state and cited source paths; old-method result freshness |

Use reusable property tests and parameterized examples. Cover every supported role/operation at the unit contract layer; select risk-based combinations for expensive integration/browser tests. A full all-axis cross product is not required. Map each requirement to test node IDs; a large raw test count is not a substitute.

### Invariants

1. A still-linked required source becoming unavailable cannot create stronger supported certainty. Keep its unresolved receipt; do not silently remove its reference. A genuinely irrelevant or independently redundant source may have a separately proved exclusion.
2. Permuting linked evidence does not change metric semantics. Repeating the same authenticated source does not count another trade or fee.
3. Two agreeing sources do not outvote a third relevant contradiction. Loss of that conflicting source does not by itself resolve the contradiction.
4. All relevant selected and alternative archives satisfy the same required format, identity, chronology, operation and quantity contracts.
5. Matching transfer deltas do not resolve conflicting absolute opening/closing balances. Supported placement must be established before it excludes a dependency.
6. UNKNOWN applies to dependent claims, not automatically every metric. Preserve independent supported fee observations and account timing where their own prerequisites hold.
7. Positive compatibility matters: canonical upstream-supported instructions must not become UNKNOWN because the application invented another field spelling.
8. Rebuilds preserve parent reports, frozen input hashes/lists, presets and windows; they create distinct children, make zero provider calls and do not look up credentials.
9. Content hashes establish byte integrity, not real-chain provenance or complete wallet history. A current method label describes interpretation version, not evidence completeness.

### Existing commands (application root)

Run in a disposable working copy and configured environment. These commands exist in v0.3.11; they are not a claim that every gate ran during this handoff.

```sh
# Iteration slice: earlier representation cases, R15 and the new source-referenced schemas
python -m pytest -q tests/review_v039 tests/review_v0310 tests/test_token_instruction_schema.py

# Full backend candidate gate
python -m pytest -q
python -m pip check

# Frontend gates after dependencies are installed from the existing lock
cd frontend
npm run check:format
npm run check:discovery
npm run build
```

For a fresh permitted setup, the existing `setup.sh` creates the virtual environment, installs hash-locked Python requirements, installs the local package without dependency re-resolution, and performs locked npm installation/build. Review and run it only in a disposable checkout with authorised registry access. Windows setup is separate; do not claim it tested after a Linux run. A new validation wrapper should use the configured interpreter instead of accidentally testing the system Python.

Backend/frontend pass does not replace actual browser acceptance. Exercise the guarded launcher with a new data directory, anonymous denial, authenticated access, settings, candidate loading, evidence inspection, rebuild and export at desktop and mobile widths. Cover a supported result, a required-source failure and restored source, an old-method parent, and the unchanged real cached case where available. Preserve browser/network/provider/credential logs. Store screenshots as supporting evidence, not substitutes for assertions.

Fresh install is required on a candidate/lock/environment change that needs that assurance, not on every small code edit. Cache dependencies keyed to the exact lockfiles. Within the same already verified environment, run affected tests while iterating; perform the complete candidate gates once the source is frozen. Do not silently substitute versions or call missing tooling a code defect.

## Gate B: complete-wallet capability and real acceptance

**Separate from Gate A.** R1 needs both implementation and data evidence. Split the work into B1 source feasibility, B2 implementation, B3 independent real-data acceptance. A feasible plan is not an implemented pipeline, and a synthetic green pipeline is not real-wallet acceptance.

For the supported real wallet/window, archive the raw inputs and provenance; establish required historical ownership and transaction scope; reconcile quantities and acquisition origins; calculate costs and positions; independently derive expected metrics; show those metrics through the normal report path. Include unknown-cost and missing-record negative controls and avoid selecting only winning positions. Economic P&L needs boundary inventories/marks and valued external flows; realised-only metrics should not be blocked for marks they do not require.

If required free/authorised history cannot be established, B1 must return a source/scope decision with the precise missing dependency. A labelled sampled-research tool can have a separate acceptance checkpoint, but do not mark wallet-wide R1 closed or introduce paid requirements without approval.

## Severity and review scope

False verified facts, broken immutability/security/quotas, or a broken essential supported workflow block the applicable candidate gate. A conservative incompatibility such as R15 may also block a claimed supported workflow; it is not equivalent to false profit certification. Optional UX polish and unclaimed new protocol support go into the backlog unless they expose a defect in a result the release currently claims to support.

Do not stop investigating after one finding. Complete the agreed matrix and changed-path review, return the findings together, and map adjacent variants to a shared cause. Conversely, do not turn every hypothetical unsupported future case into an indefinite release blocker. Confirm inputs, actual code path, result, affected claim, and positive control.

## Final evidence

Record source commit/manifest and lockfile hashes; runtime versions; command, exit status and logs for each gate; test changes with preserved intent; real versus synthetic corpus labels; parent/archive immutability; unresolved issues and explicit acceptance scope. Count test nodes once. Replayed copied tests, subtests, child API calls, permutations and screenshots are not additional unique test cases.


## Active product checkpoint commands

`python tools/check_product.py --output <new-directory>` executes the normal offline archive/report/rebuild/export application workflow independently of pytest. `python tools/product_browser.py --python <configured-app-python> --output <new-directory>` drives archive import, normal reports, source inspection, loss/restoration and downloads through the guarded real launcher at desktop/mobile widths. Run the browser command with the configured Playwright interpreter. Synthetic development and partial genuine inputs are distinct cases. `check_product.py --require-real-acceptance` must return BLOCKED/nonzero until an independently supported complete genuine corpus exists; a development PASS or Gate A acceptance does not close B1/B2/B3. Preserve historical `evidence/FINAL_GATES.json`; current checkpoint records live under `evidence/product-milestone/` with actual linked logs/captures.

## Current offline CI and accounting batch

`tools/validate.py` remains the only gate entry point. Ten disjoint focused groups
retain all 35 baseline selectors (the original 30 plus five metric regressions)
and add four current modules exactly once: historical membership, aggregate
position population, invocation-local source-fact reuse and disposed-origin
scopes. These are partitions of one focused suite, not additional test suites.
Focused summary requires all group receipts plus a separate offline-development
receipt, exact Git/source/locks/runtime, successful commands and explicit PASS
assertions; interrupted or absent execution cannot pass. CI artifacts use fixed
bounded allowlists (at most 4 MiB per included file) and exclude runtime databases,
raw private inputs and reports. Native CI is separate from full local candidate
acceptance. Focused and offline-development commands are capped at 600 seconds;
the hosted step cap is 15 minutes and whole-job cap 30 minutes so a command can
emit its timeout receipt and diagnostics first. Full candidate command caps stay
at 1,800 seconds; summary runtime probes are capped at 60 seconds. A timed-out or
running command, wrong argv/cwd, stale source or missing receipt fails its scope.
Later commands after a timeout remain explicitly BLOCKED. The strict union must
receive all ten focused receipts and the development receipt, bind their source
bytes/locks/runtime and verify command/log hashes; no subset establishes PASS.

Native run `37208279838` on preserved HEAD
`1040215f498b1317b1b942838994127f43a822bd` was cancelled without a completed
indexed receipt, and its final union returned INCOMPLETE / exit 2. Six successful
job artifacts were verified individually; they do not close the missing union.
The indexed shutdown cause is unproved. Preserve those observations as history,
and bind any new native run to its exact pushed HEAD independently.

The frozen candidate still requires the full unique backend suite, current matrix,
frontend locked install/check/build, applicable guarded browser workflows, current
install binding, distinct read-only consolidated review and unchanged source after
validation. Development internal PASS cases do not close B1/B2/B3. New arithmetic
and scope semantics require new child reports, not rewriting original evidence.
