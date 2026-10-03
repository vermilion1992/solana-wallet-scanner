# Targeted v0.3.11 baseline check

Date: 3 October 2026. This task answers the user's request to make the Codex workflow more efficient; it is not another comprehensive release review.

## Actual execution

The untouched test modules extracted from `Solana_Wallet_Scanner_v0_3_10_Review_Evidence.zip` were executed against the unchanged v0.3.11 source:

```sh
SCANNER_SOURCE=/path/to/extracted/v0.3.11/solana-wallet-scanner \
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider \
  /path/to/review-evidence/tests/test_v0310_controls.py \
  /path/to/review-evidence/tests/test_v0310_regressions.py
```

Result: **79 passed**, comprising the previous 44 R15 counterexamples and 35 controls. Runtime reported by pytest: 3.15 seconds. Exit code: 0. No original review assertions or application code were modified. The API helper contains credential and provider-denial guards. This handoff retained the test log, not a newly collected mainnet dataset.

Environment: Python 3.13.5. Package versions are in baseline-summary.json. In particular, this is the available review environment, not the declared release pins. The API test harness substitutes its guarded keyring module; an actual OS-keyring integration was not tested.

## Source observations

The v0.3.10-to-v0.3.11 diff changes permission targets to `source`, introduces authority-specific `mint` versus `account` branches, and adds a source-referenced schema fixture. The relevant source is in source-excerpts.md. R15 is verified only within the replayed cases; every admitted instruction schema was not independently checked here.

The latest developer response reports **1,527 passing Python tests and 264 subtests** and separate frontend/browser work. Those remain developer-reported totals: this handoff did not run the full suite, install exact locks, build the frontend or drive a browser. It did not retry the earlier environment failures or establish they still occur.

`scanner/history_evidence.py:659` still constructs wallet-level decisions as UNKNOWN; the current response also explicitly leaves R1 implementation and real-data acceptance open. Scope stabilisation must not be called complete wallet accounting.

No `AGENTS.md`, CI workflow directory or one-command consolidated validation script was present in the uploaded archive. This says nothing about files that may exist only in the developer's working repository. The working pack proposes additions rather than assuming that remote repository state.

## Integrity

Archive: `Solana_Wallet_Scanner_v0_3_11.zip`. SHA-256: `8da8ee0519643c02b156279f117244ea545631cc5775ddb2dfe5d74a680302f7`.

152 unique entries; CRC check passed; every original extracted source entry still matches its ZIP bytes: **True**. Source manifest is supplied for repeatable comparison. The original archive remains unchanged.

## Boundaries

No application patch, GitHub change or Codex task was submitted by this handoff. No new application defect was asserted. No provider/mainnet acquisition, funded wallet, signing, subscription purchase or financial-qualification test on complete real history was performed. The broader acceptance matrix, validation runner and R1 implementation are assignments for Codex, not completed deliverables in this pack.
