# Independent review response · v0.3.4

This responds to **Solana Wallet Scanner v0.3.3 — independent source review**, dated 3 October 2026, and its supplied evidence ZIP. The original source archive and prior review responses are preserved:

| Archive | Preserved SHA-256 |
| --- | --- |
| `Solana_Wallet_Scanner_v0_3.zip` | `44123897735a1b4f078ca8b9290e28b3e65fc815a0311a7357e01ac54bf9fec8` |
| `Solana_Wallet_Scanner_v0_3_1.zip` | `151348355534bcdbd5e85bf2e76bc401ed2ff9080cc14ead91bcc60773bf3919` |
| `Solana_Wallet_Scanner_v0_3_2.zip` | `19d149378968f2a0bfd452cf25ad4bc18c9d987c788db46067442f31cf0e534c` |
| `Solana_Wallet_Scanner_v0_3_3.zip` | `6e6a7e4a8c7e4f51419d06b8b461d268174df73ead918f72ce6b54c1c76417c5` |

The exact archived v0.3.3 response was extracted from its unchanged ZIP into [CODE_REVIEW_RESPONSE_v0_3_3.md](CODE_REVIEW_RESPONSE_v0_3_3.md), with SHA-256 `9fb4b165bad24b46b15e81561c66978e80b71aad89308aeb52044578a171e6ad`. The [v0.3.2](CODE_REVIEW_RESPONSE_v0_3_2.md) and [v0.3.1](CODE_REVIEW_RESPONSE_v0_3_1.md) responses also remain. Dated validation and dependency records are not relabeled as new checks.

**R1, full independently checked real-wallet financial acceptance, remains OPEN.** No end-to-end wallet financial completion branch has been implemented. The available historical source types still leave wallet-wide ownership, basis, population, costs, classification and valuation requirements UNKNOWN. The chronology corrections restore a narrower account-timing evidence boundary; they do not establish a profitable wallet or verified copy candidate.

| Finding | v0.3.4 response | Acceptance boundary |
| --- | --- | --- |
| R1: complete real-wallet qualification | **OPEN** | Cached real inventories start nonzero and interval coverage is partial. No complete wallet acceptance dataset or verified copy candidate. |
| R2: delivery and dependencies | **Prior dated evidence retained** | Current checks are recorded separately in VALIDATION.md. No new dependency installation, advisory audit or other-platform validation is inferred from an existing environment. |
| R3: independent four-week metric | **Retained** | The independent 28-day population remains separate from the display period, with unresolved history, basis and costs preserved. |
| R4: saved candidate continuity | **Retained** | Imports and dated deduplicated cohorts remain research leads, not complete market coverage or verified performance. |
| R5: offsetting unresolved native movements | **Retained** | Individual economic roles and actual validated fee links remain required even when net native conservation passes. |
| R6: contradictory account-page metadata | **Retained; independently verified for described cases** | Per-account reconciliation and separate observed/period arithmetic remain. |
| R7: contradictory block chronology | **Corrected in `history-evidence-v3`; supplied controls pass** | Shared per-slot assessment reconciles all linked times/order sources; a first/last receipt cannot erase a contradiction. |
| R8: time filtering hides an intervening dependency | **Corrected in `account-position-evidence-v2`; supplied controls pass** | Required records are evaluated in canonical slot/transaction order before report-window selection. |

## R7: reconcile every linked chronology source for a slot

The review reproduced three related failures: different transaction times within one slot, contradictory signature-order receipts for one slot, and an explicit block time that disagreed with mutually consistent transaction times. v0.3.3 could still expose a known six-hour named-account hold. A block-signature list establishes order at its supported resolution; it does not reconcile incompatible timestamps.

The shared chronology assessment compares linked raw transaction times, signature-page time/slot observations, every archived block-order receipt, optional block time and checkpoint indices. Contradictory source observations produce UNKNOWN for dependent order/time decisions. Evidence-reference ordering cannot select a preferred block receipt. Identical repeated observations remain valid. Optional block time can be absent when the other dependencies establish consistent timing; an explicitly contradictory time cannot be ignored.

Supported positive boundaries remain: same-slot records with one shared timestamp can establish a zero-hour interval at that timestamp resolution; an earlier opening slot and later sales sharing one later timestamp can establish the legitimate six-hour case. The formerly contradictory shipped same-slot fixture is corrected rather than retained as an acceptance example.

The review already identified a conflicting-index safeguard in the saved rebuild loader. This response does not claim its two-order-receipt variant bypassed that loader. The correction addresses the history/position derivation layer and shares chronology decisions across the applicable evidence paths. Valid selected raw-record quantities and fees remain separately observable; a contradictory time assessment does not transform those quantities into zero or certify their period membership.

## R8: establish dependencies before selecting displayed episodes

The review placed a failed record in a slot between the opening buy and final sale, then moved its timestamp to the report end or later. The old position resolver dropped it before examining its chronology or source dependencies. Removing its raw archive also left the hold known at the direct derivation layer.

`account-position-evidence-v2` evaluates candidate episode records in canonical slot/transaction order. Every record between the supported opening and closing boundaries must be examined or block the dependent stages, including failed execution, unavailable raw records and timestamps at or beyond the reporting boundary. Unknown or contradictory chronology cannot establish that a required record is outside the episode. Timestamp-based report selection happens after these dependencies are decided.

A later unrelated record does not invalidate an already supported earlier closed episode. The boundary is canonical episode membership, not the convenience of a timestamp. Failed instructions still establish no committed token change, but their chronology and required receipt remain dependencies when they lie within the episode.

The missing-raw defect was reproduced directly in derivation. The saved-report loader already requires linked primary archives; no missing-archive API bypass is claimed. The actual API regressions cover contradictory archived records, a new rebuilt child, retained originals and zero provider requests.

## Versioned interpretations and immutable rebuilding

Current chronology/timing methods are **`history-evidence-v3`** and **`account-position-evidence-v2`**, with shared **`slot-chronology-evidence-v1`** assessment. `fifo-v3`, `supported-subset-research-v2`, `scoped-evidence-audit-v2` and `saved-report-input-v1` retain their separate boundaries. The narrow durable-nonce decoder refinement uses `spot-v4-durable-nonce`.

Read-time `history_assessment` and `position_assessment` annotations independently report `current`, `rebuild_required` or `missing`. A current history method cannot silently endorse an old account hold. Current financial qualification and reviewed position use require their applicable current methods, in addition to the existing evidence requirements. Old stored coverage and financial values stay unchanged.

An offline rebuild reads the same frozen primary hashes and original window/preset, creates a new child report and retains the original. It neither collects missing sources nor refreshes current-mint observations. Reads, exports and the rebuild controls use zero provider calls. Independent valid observed fees/quantities remain available even when an interval or hold is unresolved.

## R1: the real-wallet acceptance milestone is still absent

Account-specific strict-zero timing is separate from wallet-wide cost basis, financial performance, completed-position populations and valuation. Its basis, economic-fee, classification and valuation stages remain UNKNOWN. A named-account count or median cannot populate the strict wallet cohort or establish `MATCH`.

The bundled genuine buy reconstructs 0.25 SOL consideration and 10,663,612,056 acquired raw units, but begins with 44,824,210,540 raw units of existing inventory of unknown acquisition basis. The additional [archived genuine sale](../tests/fixtures/mainnet-pumpswap-sell-durable-nonce.json) reconstructs 5,218,627,960 raw units sold for 0.01134506 SOL through persistent wSOL, with a 0.000042 SOL wallet-paid exit fee. It starts at 402,359,378,326 raw units and ends at 397,140,750,366, so neither opening zero nor final strict zero is established. Its raw SHA-256 is `25271562a99c96879c6d5f347792340320a6f55c12497a0ba3602db86eca6b4a`; archived collection/signature-page sources are included separately. No fresh RPC authentication is claimed for this offline replay.

`spot-v4-durable-nonce` accepts only the exact first outer System `advanceNonce` instruction with the investigated wallet as explicit signer/nonce authority, unique valid account roles, the actual read-only RecentBlockhashes sysvar, unchanged nonce balance and native endpoint conservation equal to the actual fee. It preserves the earlier temporary-wSOL proof and rejects other nonce operations or incomplete evidence. **24 dedicated cases pass**, including an actual frozen-input report-rebuild API case with archived receipts, unchanged original, a new child and zero provider requests. Sale proceeds/fees are known, while earlier basis and wallet profit remain null and qualification remains unresolved.

A read-only replay of the previously described 94 cached records now reconstructs 18 PumpSwap sells in the 22-record wallet sample; the other four wallets have zero supported swaps. One of those 18 sells retains outside-flow/fee-role uncertainty, and two rows lack required order evidence. This improves observed decoder coverage rather than real-wallet acceptance. The original local records are unchanged, inventories start nonzero and interval coverage remains partial. Acquisition backfill, complete economic-flow roles and wallet-level evidence remain absent.

The required milestone remains one independently checked end-to-end real-wallet report within an explicit supported coverage contract, with archived inputs and reproducible expected calculations. It needs relevant historical accounts/ownership, opening inventory and acquisition basis, supported economic movements, actual fee/capital-flow roles, completed episodes, classification evidence and reconciled equity. Removing required inputs must revoke affected metrics without erasing unrelated valid observed arithmetic. A correctly reconstructed wallet may fail every profitability preference; a profitable `MATCH` is not needed to prove accounting correctness.

The app remains read-only. No provider calls are needed for these archived-record corrections or rebuilds. The lifetime setup ledger remains exhausted at 200/200; actual Free-plan entitlement and billing-cycle confirmation remain pending. No verified copy candidate is claimed.

## Review controls and delivery evidence

The actual supplied v0.3.3 evidence bundle contains 20 passing controls and 10 ordinary failing R7/R8 regressions, including the two report-rebuild API cases. Replaying that original bundle against unchanged v0.3.3 reproduced **20 passed / 10 failed** during this revision. These are ten cases covering two defects, not ten independent defects.

All 30 supplied cases are carried into the source regression suite faithfully: the helper is byte-identical and only two helper imports in test modules change to make them part of the shipped test package. **All 30 supplied cases and 20 separate supplemental controls pass: 50 unique controls, with no expected failures or skips.** The original external 30 also pass against the corrected source; this repeat execution is not added again to the unique-case count. Supplemental removal, duplicate-receipt, optional-block-time, canonical-order and method-freshness cases are separate from the supplied originals. The current full suite passes **676 tests / 191 subtests**; **213 frontend checks** and the production build pass. Candidate-source packaging and extracted launcher/CLI checks pass. The external release-check artifact delivered alongside the ZIP records final post-documentation archive comparisons. Focused counts overlap the full suite; [VALIDATION.md](VALIDATION.md) records the boundaries.

The actual loopback browser completed six offline rebuild scenarios with 12 desktop/mobile captures at 1440/390 px. Separate old-history/old-position assessments, corrected R7/R8 unknown holds, the supported synthetic six-hour account result, retained R6 observed-versus-period distinction and the genuine cached 23-record result remain visible. Original reports/exports, windows/presets and source SQLite stay unchanged; rebuilt children are separate. Observed real network fees remain 0.000240394 SOL while interval and wallet financial qualification stay unresolved. There was no overflow, JavaScript error or external browser request, and no attempted provider request or credential lookup. The existing quota remained 200 used / zero reserved.

The independent review's 579 tests / 168 subtests used Python 3.13.5 and its available libraries, rather than the exact pinned release runtime. Its 16 formatter assertions used TypeScript 5.8.3. It did not complete exact Python installation, npm installation/full rebuilding or loopback browser navigation. Those environmental failures are not evidence that the pins are invalid or insecure, and they do not independently revalidate the compiled interface. The reviewer performed no live blockchain collection, provider authentication or new complete advisory audit.

Earlier Linux hash-enforced setup and dated known-advisory results remain in [delivery_review_2026-10-02.json](capability/delivery_review_2026-10-02.json) and [dependency_review_2026-10-02.json](capability/dependency_review_2026-10-02.json). Windows/macOS, Python 3.11 and real OS-keyring integration remain unvalidated. Current release execution facts must be read from the new validation record rather than substituted with those historical results.

## Retained scanner boundary

The fixed native read allowlist, private loopback session, host/origin/CSRF checks, one process per data directory, durable quota reservations, content-addressed evidence and checksum-verified backups remain. Discovery identities, partial audits, scoped reconstruction, financial qualification and copying observations remain separate. No signing, custody, funded test wallet, execution/replay workflow, paid-data dependency or safety score was added. Source packaging excludes provider credentials and runtime databases.
