# Independent code review response · v0.3.1

This revision responds to **Solana Wallet Scanner v0.3 — independent engineering review**, dated 3 October 2026 in the supplied review. The reviewed archive, `Solana_Wallet_Scanner_v0_3.zip`, remains unchanged with SHA-256 `44123897735a1b4f078ca8b9290e28b3e65fc815a0311a7357e01ac54bf9fec8`. The revised source is distributed separately as `Solana_Wallet_Scanner_v0_3_1.zip`.

The review's main product conclusion remains correct: this is a local read-only research application, and it has **not established end-to-end verified profitable-wallet qualification**. Correcting known defects and providing more scoped evidence does not make incomplete live history complete.

| Review item | Revision status | Acceptance boundary |
| --- | --- | --- |
| R1: live historical qualification has no completion path | **Partially implemented; full acceptance remains OPEN** | Repeatable transaction/account-scoped raw-record checks are available. No complete real-wallet acquisition history, classified closed-position population or reconciled boundary equity has been demonstrated. |
| R2: affected declared dependencies | **Fixed for the named advisories** | Compatible patched dependencies, complete hash-locked Python closure, npm lockfile and rebuilt assets. Known-advisory audits passed; this is not comprehensive security certification. |
| R3: custom report period corrupts four-week consistency | **Fixed** | `fifo-v3` calculates the independent `[end − 28 days,end)` interval and preserves unknown coverage/costs. The strict 30-day preset values stay unchanged. |
| R4: narrow discovery/setup sample | **Saved-candidate workflow implemented; sampling limits retained** | Offline list import, dated saved cohorts, cross-cohort deduplication and explicit evidence stages improve continuity. They do not broaden a sample into complete 30-day market or wallet coverage. |

## R1: repeatable scoped checks, with the product blocker retained

`scanner/evidence_audit.py` accepts a `raw-evidence-v1` bundle with 1–20 explicitly enumerated transactions, a 4 MiB limit, and an optional involved-account boundary. The `scoped-evidence-audit-v1` result records checks, primary hashes, raw JSON paths, exact values and dependencies for each supported metric. Checks cover record/signature agreement, event-time native signer metadata and owned token accounts, committed wrapped-SOL creation/initialization, funding/sync, ordered transfers and closure, integer token quantities, SOL consideration, wallet network fees and native balance reconciliation. Missing claimed records or involved owned accounts revoke dependent scoped results; extra accounts are not silently assumed to be owned.

Content hashes prove unchanged content, not that an arbitrary imported record was observed on mainnet. Reviewed-mainnet recognition is limited to the exact fingerprint of the supplied independently checked PumpSwap transaction. Other imports retain unknown chain provenance. `SCOPED_RECONSTRUCTION` means the core scoped reconstruction checks passed, not that every certificate check passed: provenance or fee allocation can still be unknown. Each metric lists the checks it requires.

The reviewed real fixture reconstructs one buy: 0.25 SOL consideration, 10,663,612,056 acquired raw token units and a 0.000141389 SOL wallet-paid network fee. Its pre-existing 44,824,210,540 raw units have unknown acquisition basis. A separate 0.0035 SOL native movement has an unresolved economic role. Its native wallet delta is −0.253641389 SOL: −0.25 SOL consideration, −0.000141389 SOL fee and −0.0035 SOL outside payments. The temporary wSOL account funds and returns 1,488,440 rent lamports, with zero native endpoints. Exact raw-path expectations are in [the public expected-value fixture](../tests/fixtures/real-transaction-audit-expected.json). A demonstrated wrapped-SOL lifecycle and exact transaction deltas do not establish that pre-existing inventory's cost, a closed position or wallet profit.

The certificate explicitly retains `wallet_history_complete=false` and `financial_qualification=UNRESOLVED`. Wallet profit, opening basis, strict closed positions, meme classification, boundary valuation, four-week history and copying safety remain unknown. This separate audit cannot upgrade a live report, set a global evidence flag or produce a strict `MATCH`. Existing live collections continue to be partial.

R1 remains open because no independently reviewed continuous real-wallet dataset yet demonstrates complete relevant account ownership/history, older acquisition costs and transfers, provenance-backed classifications, complete fee allocation, strict closed positions and boundary equity. A larger allowance alone does not solve those evidence requirements. Additional provider collection also requires the actual free-plan entitlement and billing-cycle confirmation; the original lifetime setup ledger remains exhausted at 200/200.

## R2: compatible patched and locked dependencies

FastAPI 0.142.2 and explicitly pinned Starlette 1.7.0 replace the affected former pair. Vite 8.3.2 and React plugin 6.1.1 replace the affected development toolchain; the included production assets are rebuilt. The broader advisory check also resulted in pytest 9.1.1 and setuptools 84.0.0.

The complete Python runtime/test/local-build closure contains 38 exact package pins with SHA-256 distribution hashes and platform/Python markers. Setup enforces those hashes, installs the local source without fetching unlocked isolated build dependencies, and runs `pip check`. The npm lockfile retains dependency integrity digests. Fresh installation and known-advisory audits passed; official metadata and check boundaries are recorded in [DEPENDENCIES.md](DEPENDENCIES.md) and [its machine-readable record](capability/dependency_review_2026-10-02.json).

Python 3.11+ remains supported. Rebuilding the frontend requires Node.js 22.12+; Node remains optional for running the compiled interface. Windows/macOS and Python 3.11 runtime branches are locked but were not executed on this Linux/Python 3.12 host. No advisory exploit was run, and advisory databases can change.

## R3: independent metric windows and provenance

Four-week consistency now uses realised slices and unallocated costs across exactly `[report end − 28 days,report end)`, even when the selected display window is 7, 14 or 21 days. It no longer substitutes a shortened observation for four weeks. Weekly acquisition basis and exit-cost allocations retain their own boundaries.

`metric_intervals` separates the report period, four-week interval and 90-day verification interval. `metric_coverage` attaches the relevant bounds, coverage status, reason, evidence and metric status. Missing independent four-week coverage or unresolved weekly costs/basis yields `UNKNOWN` for four-week consistency. Report-period and 90-day declarations describe their coverage; their calculations retain the separate global history/basis conditions. The accounting function accepts explicitly shaped caller declarations for normalized input; those declarations and valid hash syntax are not independent raw-provider certificates and cannot upgrade live evidence.

The current method is `fifo-v3`. The earlier fee corrections remain in place; `supported-subset-research-v2` remains separate, and current `spot-v3-ephemeral-proof` additionally requires committed primary temporary-wSOL lifecycle/order and conservation proof. Failed instructions or incomplete lifecycle/ownership records cannot become positive swap or account certificates. Existing v1/v2 reports preserve their method and financial values. A current-method report requires rebuilding from source evidence; cached previews and annotations do not correct old accounting values.

## R4: saved research continuity without invented coverage

A public-address import saves a dated cohort offline, validates every input address, removes duplicates in first-occurrence order and retains at most the configured 20 candidates. Omitted addresses and duplicates stay counted. Imports supply identifiers only; they do not introduce identity, profitability, classification or completeness assertions and make no provider request.

The saved universe deduplicates addresses across cohorts while preserving dated memberships, pool sets, evidence, omissions and original audit eligibility. Its display cap does not delete original records or imply a profit ranking. The UI separates an address being listed, **candidate observed**, **identity checked**, **sample audited** and **history reconstructed**. A completed bounded job advances none of those evidence stages by itself. Identity eligibility belongs to a verified original cohort; imported addresses do not gain it from being listed.

Explicit resume still adds bounded collection work under the unchanged global credit cap. The current three-pool/24-hour discovery and setup audit remain samples; no unbounded whole-chain scan or automatic threshold relaxation was added. A saved universe is useful for longitudinal research, but does not establish complete 30-day screening.

## Validation and retained controls

The final shipped runtime passes **431 Python tests and 115 subtests**, with **114 frontend checks** and a successful production build. Actual desktop/mobile browser checks cover the cached real cohort, offline import/deduplication, reviewed raw record, missing-fee negative control, immutable export and source inspection without errors, overflow, external browser requests or provider-credit changes. Final release checks and their limits are recorded in [VALIDATION.md](VALIDATION.md), with page-grounded requirements in [BLUEPRINT_ALIGNMENT.md](BLUEPRINT_ALIGNMENT.md). Tests distinguish known scoped quantities from unknown financial metrics and exercise deliberately missing records/accounts, fees, ownership or unsupported routes. Synthetic accounting tests do not certify a real wallet.

Loopback authentication, CSRF checks, the data-directory process lock, read-only provider allowlist, TLS verification, durable reservations, conservative charging, evidence hashes and verified backup/restore remain. The revision adds no signing, custody, execution, copy trading, funded test wallet, replay, paid data or paid AI path. No provider credential or live runtime database is included in the distribution.
