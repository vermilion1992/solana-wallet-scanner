# Independent review response · v0.3.3

This responds to **Solana Wallet Scanner v0.3.2 — independent source review**, dated 3 October 2026 in the supplied document. Execution records use the actual check dates. The reviewed archives remain unchanged:

| Archive | Preserved SHA-256 |
| --- | --- |
| `Solana_Wallet_Scanner_v0_3.zip` | `44123897735a1b4f078ca8b9290e28b3e65fc815a0311a7357e01ac54bf9fec8` |
| `Solana_Wallet_Scanner_v0_3_1.zip` | `151348355534bcdbd5e85bf2e76bc401ed2ff9080cc14ead91bcc60773bf3919` |
| `Solana_Wallet_Scanner_v0_3_2.zip` | `19d149378968f2a0bfd452cf25ad4bc18c9d987c788db46067442f31cf0e534c` |

The exact v0.3.2 response was extracted from its preserved archive into [CODE_REVIEW_RESPONSE_v0_3_2.md](CODE_REVIEW_RESPONSE_v0_3_2.md). The earlier [v0.3.1 response](CODE_REVIEW_RESPONSE_v0_3_1.md) is also retained. Historical records are not relabeled as results for this revision.

**R1, full independently reviewed real-wallet qualification, remains OPEN.** Account-specific receipts, frozen inputs, reproducible rebuilding and scoped position timing are executable prerequisites. They do not supply a complete historical wallet dataset, acquisition costs, asset classification or reconciled boundary equity. No profitable-wallet or safe-copying claim is made.

| Finding | v0.3.3 response | Acceptance boundary |
| --- | --- | --- |
| R1: completed live-wallet qualification | **Additional scoped evidence stage; OPEN** | The new account-scoped strict-zero timing stage is separate from ROI and wallet-wide metric populations. No complete real-wallet acceptance dataset has been demonstrated. |
| R2: pinned delivery/current audits | **Prior dated delivery evidence retained; dependencies unchanged** | Earlier locked Linux setup and advisory checks remain dated evidence. The new review used different available libraries and could not independently reinstall/build the exact locks. Other OS/runtime branches remain untested. |
| R3: independent four-week metric | **Retained** | The exact independent 28-day population remains separate from a custom display window; missing history, basis or costs stays unknown. |
| R4: candidate research continuity | **Retained** | Offline imports, dated cohorts and deduplication retain source/stage limitations; no complete-market screening claim. |
| R5: zero-net unresolved flows pass fee allocation | **Retained; independently verified for tested cases** | Individual material movements and actual fee links control economic completeness. Native conservation does not resolve their roles. |
| R6: contradictory account-page metadata permits a period total | **Corrected in `history-evidence-v2`** | Account-specific reconciliation, canonical membership and connected boundary anchors are required. Conflicts retain UNKNOWN interval decisions; observed-set arithmetic remains a separate scope. |

## R6: reconcile each account before certifying an interval

The review supplied a synthetic two-record boundary case. Both records pay 5,000 lamports. The raw boundary transaction falls just before the lower bound, but the wallet page moves its timestamp into the interval while a token-account page still agrees with raw. The old helper could accept the matching token page, count both wallet-page entries and incorrectly report a known 0.000010 SOL period fee. The review's four ordinary failing controls vary time, slot, error and confirmation status. They identify a real implementation defect, not new mainnet observations.

`history-evidence-v2` reconciles each linked account/page observation against canonical raw metadata and the other linked receipts. A matching entry on another account cannot erase a contradiction. `paging.conflicts` records the account, signature, conflicting field, values and source hashes; account-specific receipts expose their own reconciliation checks. Raw timestamp and slot govern interval membership when the raw record exists. Contradictions at either lower or upper boundaries, including cross-account disagreement, block enumerated interval completion and native period totals until consistent evidence is restored.

An upper timestamp proof must come from a connected account chain that passes its checks. A detached page cannot anchor a wallet interval. Boundary entries without raw records require explicit finalized metadata and agreement across their linked receipts. `minContextSlot` alone does not establish an exact UTC time boundary or boundary equity.

For the corrected synthetic wallet page, the boundary transaction remains outside the period, so the known period fee is 0.000005 SOL. The two-record observed raw set can still have known fees of 0.000010 SOL because its explicitly enumerated arithmetic is a different population. Unknown interval coverage does not erase valid observed arithmetic, and known arithmetic does not certify an interval or wallet history. Quantity/fee/native endpoints retain the unsigned 64-bit protocol checks introduced in v0.3.2.

Rebuilding a saved live report uses the same frozen primary hashes, original window and preset and produces a new interpretation; the earlier snapshot remains unchanged. No provider calls or current-mint refresh are needed. The correction does not make any global ownership, basis, classification or valuation requirement pass.

Read-time `history_assessment` annotations distinguish `current`, `rebuild_required` and `missing` receipt methods. Live qualification requires the current receipt version as well as the current accounting method; old or missing versions cannot qualify from stale passing checks. Report reads/exports may include these current annotations while preserving the original saved coverage, financial values, window and preset. A current method label still does not mean the evidence is complete.

## R1: account-scoped strict-zero timing, with full acceptance still open

The review correctly distinguishes an executable evidence stage from replacing a literal boolean with derived UNKNOWN decisions. Full-wallet requirements are still unresolved. `account-position-evidence-v1` therefore has a deliberately narrower boundary: strict-zero episodes and timing for a named token account, independent from price, fee allocation and ROI. It recomputes archived account-specific receipts rather than trusting a supplied PASS. Its collection, identity, primary opening-zero, chronology, quantity, continuity and final strict-zero stages must all pass before a hold is known. Basis, fees, classification and valuation remain separately unknown. The schema, raw prerequisites, source paths and recovery plans are documented in [CONTRACT.md](CONTRACT.md).

Known timing for a supported, fully evidenced scoped episode is not a known wallet-wide median hold, profitable closed position, qualifying meme cohort or complete position count. Missing opening ownership/quantity evidence, incomplete intervening account records, unresolved economic movements, missing chronology or a removed primary source prevent dependent timing from being accepted. An empty signature page is not a zero-inventory anchor. Scope and unknown reasons remain visible alongside any accepted observation.

The actual cached collection contains 94 records and no supported swap candidates. The independently reviewed PumpSwap buy establishes 0.25 SOL consideration and 10,663,612,056 acquired raw units, but its route begins with 44,824,210,540 raw units of pre-existing inventory of unknown basis. It does not establish a strict-zero opening or a completed position. Neither dataset is manufactured into a positive position example, a complete wallet or a financial match.

The remaining acceptance milestone is an independently reviewed complete real-wallet dataset with supported economic routes, historical account/ownership coverage, known opening inventory and acquisition costs, fee/capital-flow roles, qualifying asset evidence, closed episodes and reconciled equity. Deliberately incomplete versions must revoke the dependent decisions. A correctly reconstructed wallet may fail every profitability preference; passing a preference is not a prerequisite for accounting correctness.

No additional live provider calls were made during this revision. The original lifetime setup ledger remains exhausted at 200/200, actual Free-plan entitlement and billing-cycle clarification remain pending, and no complete real wallet or financially qualified live wallet has been added.

## R2: preserve dated evidence and distinguish review environments

The 38-package Python closure and 52-entry npm dependency graph are unchanged from the earlier reviewed release apart from release metadata. The existing [delivery record](capability/delivery_review_2026-10-02.json) records hash-enforced Linux setup, installed versions, isolated launcher checks and dated zero-known-advisory results. The older [dependency record](capability/dependency_review_2026-10-02.json) remains immutable. These are prior execution records, not a new v0.3.3 audit or comprehensive security certification.

The latest independent review ran the reviewed v0.3.2 source suite using its available Python 3.13/library environment, rather than the exact pinned runtime. It reproduced 494 tests and 133 subtests, and its prior independent R5 controls passed without expected-failure handling. Its new R6 controls had four ordinary failures before this correction. Exact lock installation/frontend rebuilding was blocked by DNS failures; its formatter check used a different preinstalled TypeScript version. An isolated launcher/API check succeeded with the available libraries, while browser navigation was blocked by the review environment. Those outcomes neither invalidate the earlier dated Linux delivery proof nor independently recertify the locked frontend or visual behavior.

Windows/macOS and Python 3.11 execution remain untested. Node 22.12+ is optional when rebuilding the shipped compiled interface. Final current-release checks and any source/archive verification belong in [VALIDATION.md](VALIDATION.md); historical counts above identify the reviewed archive only.

## Retained boundaries

Frozen `saved-report-input-v1` inputs and legacy-checkpoint limitations remain. R5 continues to keep individual unresolved movements UNKNOWN even when their signed amounts cancel, and to require the actual validated fee-to-trade link. Known network payment is separate from complete economic cost allocation. Conditional observed-lot research stays separate from strict wallet metrics. Imported identifiers, sampled identities, bounded audits, reconstructed history and financial qualification remain distinct stages.

The app remains local and read-only, with a private loopback session, CSRF/host/origin checks, one process per data directory, conservative quota reservations, immutable source archives and checksum-verified backups. No signing, custody, trading, replay, funded test wallet or safety score was added. Provider credentials and runtime databases are excluded from the source distribution.
