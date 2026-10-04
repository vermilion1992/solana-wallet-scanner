# Independent review response · v0.3.5

This responds to **Solana Wallet Scanner v0.3.4 — independent source review**, dated 3 October 2026, and its supplied evidence ZIP. The five prior source ZIPs are preserved:

| Archive | Preserved SHA-256 |
| --- | --- |
| `Solana_Wallet_Scanner_v0_3.zip` | `44123897735a1b4f078ca8b9290e28b3e65fc815a0311a7357e01ac54bf9fec8` |
| `Solana_Wallet_Scanner_v0_3_1.zip` | `151348355534bcdbd5e85bf2e76bc401ed2ff9080cc14ead91bcc60773bf3919` |
| `Solana_Wallet_Scanner_v0_3_2.zip` | `19d149378968f2a0bfd452cf25ad4bc18c9d987c788db46067442f31cf0e534c` |
| `Solana_Wallet_Scanner_v0_3_3.zip` | `6e6a7e4a8c7e4f51419d06b8b461d268174df73ead918f72ce6b54c1c76417c5` |
| `Solana_Wallet_Scanner_v0_3_4.zip` | `f086fece1464aa99693d0b0514aa9d1c7b8ce9e3f7b9e37ebe89b74120d670da` |

The exact v0.3.4 response was extracted from its unchanged ZIP into [CODE_REVIEW_RESPONSE_v0_3_4.md](CODE_REVIEW_RESPONSE_v0_3_4.md), with SHA-256 `7659beb774c14a04278dcb7d3b5cef9bdf21bd1557a5240d003149c86bd332db`. Earlier v0.3.1–v0.3.3 responses and dated delivery/dependency records remain separate historical evidence.

**R1 remains OPEN in both implementation and data acceptance.** The new review correctly identifies the absent completed real-wallet financial evidence path. The required independent real historical ownership, acquisition-basis and boundary-valuation dataset is also unavailable. A narrower known named-account hold, observed swap arithmetic or successful immutable rebuild cannot supply those dependencies. No new full-wallet completion branch is implemented, no financial gate is removed, and no verified profitable wallet or copy candidate is established.

| Finding | v0.3.5 response | Acceptance boundary |
| --- | --- | --- |
| R1: complete real-wallet financial acceptance | **OPEN** | Both the implementation pipeline and independent real acceptance dataset remain missing. |
| R2: delivery/dependencies | **Current existing-environment and isolated-launch checks pass; historical evidence retained** | No fresh exact installation, new advisory audit, other-platform validation or comprehensive security is inferred. |
| R3–R6 | **Retained** | Existing tests remain; a green suite is not independent re-proof of every earlier domain. |
| R7: conflicting same-slot time/order receipts | **Original correction accepted by review** | Keep the original positive, contradiction and removal cases. |
| R8: report-end timestamp hides an intervening dependency | **Original correction accepted by review** | Keep canonical dependency-before-window behavior; do not generalize that result to every ambiguous placement. |
| R9: conflicting slot evidence excludes a potential dependency | **Corrected; 61 unique new controls pass** | Each possibly intersected account episode requires reconciled placement or supported exclusion before its hold can pass. |
| Durable-nonce sale decoding | **Prior scoped arithmetic accepted offline** | No new single-swap fixture or fresh mainnet authentication is claimed as R1 completion. |

## R9: uncertainty must reach every episode it may intersect

The supplied counterexample uses an entirely synthetic named-account episode: opening buy at slot 100, failed record on both archived account pages at slot 101, and final sale at slot 102. The middle raw transaction instead claims slot 99 or 103. Its content hash and signature remain internally consistent, but its placement disagrees with the linked pages. v0.3.4 detects the conflict in history evidence, then sorts by the raw-preferred slot and excludes it from the closed episode. The result can still show a known six-hour hold.

There are four ordinary failing assertions covering one defect: both conflicting placements directly and through the saved-report rebuild API. The reviewed API reports retain unknown wallet profit, financial policy UNRESOLVED, qualification false and all wallet-wide gates UNKNOWN. This is a scoped timing defect, not a reproduced profitable-wallet qualification bypass or evidence of an actual contradictory mainnet transaction.

The correction preserves all relevant possible placements and establishes exclusion only from supported evidence. A disputed account record whose page/raw positions may intersect an episode remains a dependency of that episode even when the raw-preferred position is before opening or after closing. Both direct/API variants now retain the middle dependency, return zero known closed account episodes and keep the scoped hold unknown. Wallet financial gates remain unknown.

Propagation is account- and episode-specific. Consistently placed failed records genuinely before opening or after closing can remain outside. An unrelated account's problem must not indiscriminately invalidate every known earlier hold. Original R7/R8 timestamp/order controls, missing-source dependencies, exact-zero semantics and wallet-wide financial gates remain required.

Shared placement envelopes retain all linked raw/page/block slot and index possibilities. Finite conflicting bounds may exclude a record only when the entire envelope is disjoint from the episode. Present malformed raw placement or an unavailable distinct alternative native archive makes the envelope unbounded; neither can certify exclusion. A sole missing raw archive with consistent linked outside pages retains the valid R8 exclusion, without treating those pages as proof of quantities.

The position result includes an explicit `placement` stage, source-backed `dependency_exclusions` before/after the episode, shared top-level `account_placement_sources` and `placement_scope` counts. At most 64 uncertain excluded receipts are inspected per episode; overflow remains UNKNOWN with omitted counts. These decisions occur before report-window selection. Independently valid native-fee arithmetic retains its own population. The exact fields and dependency rules are in [CONTRACT.md](CONTRACT.md).

## Method freshness and offline rebuilding

Affected methods advance to **`history-evidence-v4`**, **`account-position-evidence-v3`** and shared **`slot-chronology-evidence-v2`**. `fifo-v3`, `spot-v4-durable-nonce`, conditional research, scoped transaction audits and frozen input manifests retain separate interpretation boundaries.

Independent `history_assessment` and `position_assessment` annotations remain `current`, `rebuild_required` or `missing`. A current method label does not mean the evidence passed, and a current history method does not endorse an old position interpretation. Reads and exports preserve original financial values, coverage, window and preset. An offline rebuild uses archived primary hashes, creates a new child and retains its parent; it does not retrieve absent data or refresh current-token observations.

The actual desktop/mobile browser run rebuilt 11 offline children and captured 22 screenshots at 1440/390 px. It covers both R9 raw-slot variants, coherent disjoint before/after six-hour controls, retained R7/R8/R6 behavior, independent previous-method banners and the genuine cached 23-record report. Original reports, source SQLite and export bytes remain unchanged. Usage remains 200 used / zero reserved; provider requests, credential lookups, external browser requests, JavaScript errors and page overflow are all zero. The positive six-hour controls remain synthetic named-account results, with wallet-wide hold/profit unknown and qualification UNRESOLVED.

## R1: complete accounting needs a real acceptance dataset

The prior archived buy and durable-nonce sale are useful verified content arithmetic, not complete real-wallet performance. The buy begins with 44,824,210,540 raw units of prior inventory of unknown basis. The sale begins at 402,359,378,326 and ends at 397,140,750,366 raw units; it is neither opening zero nor final strict zero. The independently recalculated sale proceeds are 0.01134506 SOL with a 0.000042 SOL wallet-paid fee. Its uploaded raw hash is `25271562a99c96879c6d5f347792340320a6f55c12497a0ba3602db86eca6b4a`. Content integrity is separate from independent mainnet provenance; no fresh provider retrieval occurred in that review.

The developer's earlier read-only 94-record replay is a separately dated local observation. The latest reviewer did not independently replay its complete runtime database or validate the developer's browser captures. The uploaded single-record fixture cannot be presented as independent verification of the entire collection.

The PDF page 6 states: “A current token-account list is not a historical ownership index. Iterating until no additional accounts are discovered is useful but cannot prove that every previously closed, undiscovered account has been found. A completely hidden round trip can leave zero residual mismatch. Mark that scope limitation explicitly; require independent historical ownership evidence before a global completeness claim.” Current account enumeration and wallet/account paging therefore cannot supply a completion witness on their own. If the native source cannot supply that evidence, page 18 requires a new source decision. No independent historical ownership source adapter or complete alternative real dataset is available or implemented in this release.

The outstanding target is one independently checked real-wallet report within an explicit supported coverage contract. A future implementation must consume exhaustive historical ownership/lifecycle evidence, complete required raw/page/order intervals, recovered acquisition origins and exact cost roles, mint-wide strict-zero populations, provenance-backed classification and required boundary inventory/marks/valued flows. Existing 94 selected native receipts and windows of seconds to a few hours cannot certify the 30/90-day policy. The implementation and source acquisition remain unfinished; confirming a Free key and billing cycle alone does not complete either.

| Claimed result | Required evidence / removal boundary |
| --- | --- |
| Observed wallet-paid native fees | Valid selected fee/payer/endpoints; complete interval totals need their own wallet-address paging and boundaries. Missing token ownership does not erase valid selected fees. |
| Realised profit/ROI, win rate and contributions | Complete eligible ownership/transactions, acquisition origins, economic costs and classification; missing cost revokes affected monetary/population results. Boundary prices are not required for realised P&L. |
| Wallet-wide completed holding cohort | Complete eligible ownership/quantities, mint-aggregate strict zero, sale identity/order and classification; missing monetary cost alone need not erase separately proved scoped timing. |
| Four-week consistency | Its own exact 28-day history, origins, costs and classification; a shorter selected window is insufficient. |
| Economic P&L | Exact boundary inventories/marks and valued external flows; missing marks revoke economic P&L without necessarily revoking independently supported realised P&L. |

Frozen real inputs and hand-calculated expected results must be supplied, with source-removal controls that revoke dependent metrics without erasing independent arithmetic. Losing, breakeven and unresolved eligible episodes must not be dropped from a population to create winners. A correctly calculated loss or policy miss is a valid accounting acceptance case; a profitable MATCH is not required. Caller completion flags, deleted UNKNOWN gates, relaxed filters, a synthetic demonstration or another isolated swap do not satisfy this milestone. The completion design remains a proposed handoff; a new wallet-wide completion branch has not been implemented.

The setup ledger remains exhausted at 200/200 and actual Free-plan entitlement/billing-cycle confirmation remains pending. No new live collection or verified copy candidate is claimed by this revision.

## Supplied controls and current execution boundaries

Local exact baseline replay reproduces **26 passing controls and four ordinary R9 failures** against unchanged v0.3.4. The supplied 30 cases are retained byte-identically and pass against corrected source. The shipped faithful 30 plus 31 supplemental cases give **61 unique new R9 controls**, all passing normally; four supplemental cases remove distinct alternate archives. Re-running the same external 30 is not 30 additional controls. The prior 103 independent R6/R7/R8 controls also pass and retain their original scope. No expected failures or skipped cases are used to accept R9.

The frozen-source Python suite passes **759 tests and 219 subtests**. Frontend checks pass **228 assertions** (16 formatter, 212 UI/data), and the production build passes. Local editable version 0.3.5, `pip check` and shell syntax pass without a fresh dependency installation. The 111-entry candidate archive passes CRC, unique/source/compiled-byte, mode, asset-reference and runtime/credential-exclusion checks. The extracted CLI/import and actual isolated empty-data loopback launcher pass, including anonymous 401, authenticated bootstrap/state and compiled assets 200, correct current methods, no key/reports/jobs/audits, zero used/reserved credits, monitoring disabled and clean shutdown. The external release-check artifact records the repeated comparisons and clean exit for the exact final post-documentation ZIP; its digest is not embedded here. See [VALIDATION.md](VALIDATION.md) for the current and separately preserved historical checks.

The review ran the supplied v0.3.4 suite as **676 tests / 191 subtests** using Python 3.13.5 and available libraries, not the exact release pins. Its isolated formatter passed 16 assertions using TypeScript 5.8.3. Fresh hash-enforced Python installation and npm installation/full UI rebuilding did not complete because the registries were unavailable. Browser navigation was blocked by administrative policy; no independent mobile, overflow or interaction sign-off occurred. The unmodified launcher served HTML/authenticated local state and shut down cleanly. Those outcomes neither prove invalid pins nor recertify the developer's earlier compiled-interface/browser results.

The five original ZIPs and earlier [delivery](capability/delivery_review_2026-10-02.json) / [dependency](capability/dependency_review_2026-10-02.json) records remain historical. No new current vulnerability/advisory audit, OS-keyring validation, Windows/macOS execution, Python 3.11 matrix or live-provider reliability claim is made from that evidence.

## Retained scanner-only boundary

The app remains local and read-only with a fixed native method allowlist, private loopback session, host/origin/CSRF controls, one process per data directory, durable quotas, immutable evidence and checksum-verified backups. Candidate identity, sampled audit, scoped reconstruction, financial qualification and copying observations remain different stages. Source packaging excludes keys and runtime databases. No trading, custody, funded test wallet, replay/execution workflow, paid subscription or safety score is required for the correction.
