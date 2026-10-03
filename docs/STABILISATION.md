# Scoped stabilisation candidate

Baseline: immutable v0.3.11 ZIP, SHA-256 `8da8ee0519643c02b156279f117244ea545631cc5775ddb2dfe5d74a680302f7`, 152 entries; local baseline commit `3458aac9e39f598da9ec6adeb4c077126e9e33eb`. The working branch is `stabilise-evidence-contracts`. This is an unreleased candidate; package metadata remains 0.3.11. Exact candidate commit and file/mode manifest, locks, runtimes and executed commands are in the final gate record. Older ZIPs and raw genuine fixtures remain unchanged.

## Change and audit scope

SC-01 corrects `withdrawNonce` to canonical System `withdrawFromNonce` in the shared instruction-scope normalizer. Pinned Agave commit `9480479ff42af8a9db3da1649297dfcd9d27e5be`, `parse_system.rs:97`, establishes the spelling and target fields. The required `nonceAccount` and `destination` references stay mandatory. A disjoint valid operation preserves supported named-account timing; relevant unsupported reconstruction remains UNKNOWN. Only position interpretation advances, from v9 to v10. History v8, source consistency v4, chronology v2, FIFO v3 and swap/nonce interpretation remain unchanged. Old position snapshots need a new child report.

The new manually specified schema corpus covers all 38 declared Token, System and Associated Token contracts, including four authority branches. It is independent of production target fields. The tests compare the production population only to detect an unreviewed addition/removal; they do not generate expected fields from that table. These unsigned synthetic schema examples establish minimum field compatibility, not full instruction semantics or real-chain provenance. Standard Token-2022 counterparts are covered; unclaimed extensions remain unresolved.

The bounded audit covers source enumeration/read failures, normalization, chronology/relevance, absolute quantities/ownership, per-metric dependencies, frozen reconstruction, method freshness and display/export. `ACCEPTANCE_MATRIX.json` maps each requirement to actual collected node IDs. All roles/operations get unit-contract coverage; expensive API/browser combinations are selected by risk. Actual 40,000-source and retained 10,000-record/candidate/combined-budget boundaries are mapped. This does not assert arbitrary combinations or all possible bugs have been disproved.

## Reproduction and preserved controls

The final new baseline oracle produced seven failures and 207 passes in 214 cases: one canonical unit case, one disjoint timing case, four selected/alternative × outer/inner frozen API cases and one population guard. They share SC-01. Baseline focused historical/schema replay passed 194 cases. Original external reproducers remain auditable and are not skipped, xfailed or removed.

Four initial new assertions demanded a more specific rejection path than the existing enclosing parsed representation exposes. The assertions were corrected while preserving mandatory rejection. No production semantics changed for these cases (ND-01). Browser development also corrected harness locators for actual UI labels and allowed the legitimate saved-preset version change while keeping every threshold equal (ND-02).

The portable cached-real fixture initially omitted the original persisted collector checkpoint. Its fee result correctly became UNKNOWN: a caller-supplied/frozen object alone cannot invent trusted collector ancestry. The fixture now copies the actual checkpoint from the isolated earlier QA archive. The existing arbitrary-import negative control is mapped explicitly; production trust decisions remain unchanged (ND-03).

Before freezing, the expanded focused runner passed 457 tests and the affected freshness/gate checks passed 36. The development guarded browser passed six child rebuilds and 16 captures at 1440/390 px, including source loss/restoration and the unchanged cached real case. These are iteration evidence, not final candidate gates. Intermediate failures and raw logs are retained under `evidence/runs/`.

## Repeatable validation

From the application root:

```sh
.venv/bin/python tools/validate.py --profile focused
.venv/bin/python tools/validate.py --profile candidate \
  --browser-python /path/to/existing/playwright-python \
  --chromium /path/to/existing/chromium
```

The configured application interpreter must import this working copy. No wrapper dependency is added or silently substituted. Candidate mode runs the full backend, pip check, shell syntax, collected-node matrix, locked npm installation, formatter/UI checks, TypeScript/Vite build, guarded actual CLI/Chromium/rebuilds and exact-source consolidated review. `evidence/CLEAN_INSTALL.json` records a disposable original `setup.sh` installation with matching current locks and Python/Node/platform; a changed lock/runtime invalidates that cache. Windows/macOS, advisory scans and OS keyring operation are separate unexecuted assurances.

The guarded browser creates fresh QA storage and a separate empty ledger. It never resets or touches the exhausted user pilot ledger. Provider dispatch and credential operations are denied and counted; the CLI session token is drained privately and is not written to logs. Synthetic old parents are derived using the committed original v0.3.11 source, rather than fabricated by changing a label. The real corpus in `evidence/runs/real-cache/` copies only previously authorised isolated archives, parent/job context and its original collector checkpoint, with no credentials, configuration or ledger. If that optional corpus is unavailable, the result explicitly records that the real case did not run.

The browser asserts anonymous denial, authenticated access, unchanged settings thresholds, offline candidate import, supported/still-unknown old-parent rebuilding, required-source failure/restoration, evidence inspection, actual UI JSON download, immutable original parents/exports/frozen references and unchanged QA usage. It also checks JavaScript errors, external requests and desktop/mobile overflow. Screenshots support these assertions; they are developer browser validation, not independent browser certification.

Missing/failed/blocked required checks and changed source return nonzero. `FOCUSED_PASS` is iteration only. `ACCEPTED_IN_SCOPE` means Gate A within the declared contract; the runner always records Gate B OPEN. Evidence files are excluded from the software digest so gate logs/review attestations can be written without changing the reviewed software. Reference/corpus integrity is separately recorded by hash. The manual review attestation is not an automatic proof of correctness.

## Review and handoff

Run the distinct read-only review specified in `REVIEWER_TASK.md` against a detached exact-candidate worktree. Bind its complete findings and matrix review to the candidate manifest in `evidence/REVIEW.json`, then execute the candidate profile with unchanged source. `evidence/FINAL_GATES.json` is the final command/report location and outcome; raw command logs remain in the referenced run folder. Do not treat this document or the historic v0.3.11 response as an execution record.

Gate B is separate. `R1_SOURCE_DECISION.md` records actual archive coverage, primary documented source capabilities/current advertised limits, per-metric missing dependencies and concrete implementation tasks. Five real cached wallets contain 94 selected raw records, without a complete historical-owner/population witness. B2 is not implemented and B3 lacks a complete real expected-results corpus. No credential use, provider collection, credit spend, paid requirement, source-scope substitution, threshold relaxation or safe-copy claim occurs in this batch. No ZIP is needed for each fix.
