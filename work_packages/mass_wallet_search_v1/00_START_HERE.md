# Mass Wallet Search — Codex work package
**Version 1.0 · Prepared 5 October 2026 · Gmgn project**

## The outcome
Build and prove a fast, budgeted, read-only pipeline that discovers many Solana wallet candidates, applies successive KPI shortlists, reconstructs the strongest survivors, and tests whether their apparent advantage survives a follower's delay, costs and exit constraints.

**Do not deliver another empty dashboard, an APK shell, or a test-count-only completion claim.** The next useful result is a real search with inspectable trades, P&L, median holding time, material exit timing, exclusion reasons, source limitations and measured collection cost.

## Start Codex
Give Codex this entire folder and the repository. Paste `START_CODEX.txt`. Codex's primary assignment is `CODEX_TASK.md`. The remaining documents specify implementation and acceptance; they are not a request to write more planning documents before coding.

Do not overwrite the repository's existing `AGENTS.md`, `CODEX_TASK.md` or acceptance history with this folder. A suitable location is `work_packages/mass_wallet_search_v1/`. Read the existing repository rules first. Resolve the particular mass-universe versus legacy 20-candidate cap as described in the architecture, not by removing quota protection.

## Read order
1. `CODEX_TASK.md` and `docs/01_REPO_BASELINE.md`.
2. `docs/02_ARCHITECTURE.md`, `docs/03_KPI_AND_COPYABILITY.md`, `docs/04_PROVIDER_GATE.md`.
3. `docs/05_IMPLEMENTATION_PLAN.md`, `docs/06_BENCHMARK_ACCEPTANCE.md`, `docs/07_TEST_MATRIX.md`.
4. Machine-readable examples in `config/`, contracts in `contracts/`, and the delivery template.

## What is included
- A repository-specific assignment with commit-sized tasks and clear stopping rules.
- Cheap-to-expensive discovery, triage, behaviour, reconstruction and forward-observation stages.
- Explicit separation of reported, reconstructed-subset, full-wallet and hypothetical follower results.
- Exact preserved strict-preset values and separately named provisional research settings.
- Provider access, completeness, request-budget and rate-limit checks before a bulk run.
- A genuine 1,000-candidate benchmark and a separate 10,000-row local-performance target.
- Synthetic adversarial acceptance vectors, a receipt JSON schema and a dependency-free receipt-contract checker with tests.

## What this package is not
It is not a modified scanner release, live dataset, profitable-wallet recommendation, APK, hosted service or authorisation to spend money. The example receipts and fixtures are **synthetic**. A passing receipt checker establishes structural consistency and file integrity, not chain provenance or financial correctness.

## Run the package's own checks
From this folder, using Python 3.11 or later:

```sh
python -m unittest discover -s tests -v
python tools/check_receipt_contract.py fixtures/receipt.synthetic.example.json --profile development
python tools/check_receipt_contract.py fixtures/receipt.synthetic.example.json --profile live-search
```

The last command must return exit **2 / INCOMPLETE** because the fixture is synthetic. None of these commands accesses the network, reads credentials or runs the actual scanner's tests.

## Non-negotiable distinction
A useful, honestly labelled subset report can pass the new analytics demonstration. It does not close the older full-wallet historical evidence requirement. Conversely, that unresolved full-wallet requirement must not be used as an excuse to suppress independently supported trades, fees, realised subset P&L or timing.

**Implementation first; then bounded real evidence; then an honest result.**
