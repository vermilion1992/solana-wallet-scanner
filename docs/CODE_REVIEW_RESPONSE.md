# Independent review response · v0.3.11

This responds to **Solana Wallet Scanner v0.3.10 — independent source review**, dated 3 October 2026. The reviewed ZIP remains unchanged: SHA-256 `bbaee877f65e7e74466ec71aff8c5dd94383d2c6ee96ec7552de43d9941237e7`. All 144 shipped source/compiled entries matched before edits. Its exact response is preserved as [CODE_REVIEW_RESPONSE_v0_3_10.md](CODE_REVIEW_RESPONSE_v0_3_10.md). All eleven prior ZIPs, historical responses and existing genuine fixture bytes are compared during packaging.

**R15 is corrected within the tested scoped contract. R14 representation guards remain in force. R1 remains OPEN in complete financial implementation and independent real-wallet acceptance.** No verified profitable wallet or copy-trading candidate is established.

## Reproduction and correction

The untouched new review bundle on immutable v0.3.10 reproduces **35 passes and 44 ordinary failures**: 28 direct and 16 actual API cases for one required-target mapping defect. The failures represent false UNKNOWN for an otherwise supported synthetic named-account hold, not a new false profit qualification. Selected/alternative inputs retain eight/nine references and hashes. Profit remains unknown, policy UNRESOLVED, qualification false, wallet-wide gates UNKNOWN, and provider/credential calls zero.

The new R14 table incorrectly required `account` for approvals/revocation, and universally for `setAuthority`. I also wrote six positive supplemental cases against that incorrect spelling. Those tests did not establish RPC compatibility. This release corrects both the implementation and those inaccurate developer fixtures.

The primary Agave parser was fetched at commit `9480479ff42af8a9db3da1649297dfcd9d27e5be`; raw `parse_token.rs` SHA-256 is `50370cf477d4d526960a226a945f712426c059f220fd4c84f63f493da64d88c0`. [Pinned primary source](https://github.com/anza-xyz/agave/blob/9480479ff42af8a9db3da1649297dfcd9d27e5be/transaction-status/src/parse_token.rs): Approve/Revoke lines 180–219, SetAuthority 220–260, ApproveChecked 388–413. `tests/fixtures/token_instruction_schema.json` contains seven manually specified, source-referenced synthetic examples independent of the application's lookup table. They cover the three permission types and four standard authority branches. These are unsigned RPC-schema examples, not provider observations or authenticated mainnet transactions.

| Operation | Required scope references / branch |
| --- | --- |
| `approve` | `source`, `delegate` |
| `approveChecked` | `source`, `delegate`, `mint` |
| `revoke` | `source` |
| `setAuthority`: `mintTokens`, `freezeAccount` | `mint` |
| `setAuthority`: `accountOwner`, `closeAccount` | `account` |

An explicit supported string `authorityType` selects the authority branch. Missing, malformed, unreviewed extension or contradictory types/targets remain UNKNOWN; the competing `account`/`mint` field is unsupported even when values agree. `account` is not an admitted permission alias. Required targets remain nonempty strings; the resolver does not make targets optional or accept either name indiscriminately. Other minimum scope contracts and quantity/ownership semantics remain separate.

Permissions do not themselves transfer quantity or change account ownership. Later delegated transfers still need their own evidence. Valid unrelated mint-authority operations can prove disjointness; executed relevant account-owner and close-authority changes still block unsupported continuous-ownership claims. Rejections retain target/type/reference paths as well as signature, archive hash and reason. Parsed/opaque mixed representations, conflicting program identities and incomplete targets retain R14's guards. Atomic failure, independently supported fees and genuine disjoint/metadata witnesses retain their own meaning.

[CONTRACT.md](CONTRACT.md) records these contracts. Original PDF pages 6–8 require event-time ownership and supported-operation evidence; page 9 starting filters are unchanged.

## Fixture correction and preservation

`tests/test_review_v039_independent.py` changes the four approve/revoke positive cases and two matching-program-identity positive cases to canonical `source`; approve fixtures also use the canonical `delegate`/`amount`, while revoke omits an invented delegate. Their assertion meanings and case population remain unchanged. Deliberately mixed negative fixtures still test the earlier representation guard. Existing upstream review modules, original archived sources, historical reports and genuine transaction fixtures are preserved. The v0.3.10 ZIP retains the old fixtures exactly; saved RPC JSON is never rewritten to insert `account`.

Faithful copies of the new 79 review cases adapt only sibling helper imports. The review helper remains byte-identical; schema helper and test module imports are qualified so historical helpers can coexist. The unmodified external bundle and untouched original R14 bundle also pass separately on final source (79 and 57 cases respectively). Earlier R7–R13 external executions remain historical; faithful shipped cases run in the current full suite. Repeated executions and browser/API children are not additional unique pytest cases.

## Versioning and offline rebuilding

Only the affected position interpretation advances to **`account-position-evidence-v9`**. History remains `history-evidence-v8`, source consistency `source-consistency-v4`, chronology v2, accounting fifo-v3 and swap/nonce spot-v4-durable-nonce. Position v8 and earlier reports require a new child rebuild even when history is current. Frozen input references, presets, windows, prior values and parents remain unchanged. Existing correctly spelled sources require reinterpretation, not recollection.

The browser session uses thirteen synthetic parents actually interpreted with immutable v0.3.10, plus the cached real 23-record parent. Current children recover supported permissions/mint disjointness, retain account-owner/close-authority/missing-type/contradictory-target/mixed-shape rejection, and preserve fee isolation. The cached real observation still supports **0.000240394 SOL** in observed network fees, no known closed account episode and unknown global financial gates.

## Validation

| Check | Executed result |
| --- | --- |
| Untouched new external review | **79 passed**: 44 regressions +35 controls, overlapping faithful shipped copies |
| Untouched original R14 replay | **57 passed** separately; overlaps shipped cases |
| Primary-schema supplemental tests | **58 passed**: seven schema examples, ten API inclusion/disjointness/rejection cases, six authority-type controls, 24 authority-target controls, nine permission-alias controls and two source-removal/restoration cases |
| Full shipped Python suite | **1,527 passed; 264 subtests passed**, 226.38 s; one existing Starlette test-client deprecation warning |
| Population | 1,389 prior +79 faithful +58 supplemental +one freshness =1,527; one current-method node rename, no semantic deletion |
| Frontend | **315 assertions** (16 formatter +299 UI/data); pinned TypeScript/Vite production build passes; JS `index-B-AqKu-Q.js`, CSS `index-Brz2fDKJ.css` |
| Bounded probes | Unmodified 240 shape mutations: no unexpected exceptions; unmodified 24 permission compatibility probes: supported six-hour holds; separate from pytest, not exhaustive fuzzing |
| Browser | **14 completed offline child rebuilds; 30 captures** (28 full-page +two focused) at 1440/390 px; no overflow, JS errors or external browser requests |
| Browser/data guards | Original parent rows/exports, frozen references and source SQLite preserved; provider calls/credential lookups zero; exhausted pilot remains 200 used/zero reserved; QA server stopped |
| Local runtime | Existing pinned Python 3.12.14/Node 24.19.0 environment; editable 0.3.11 metadata, pip check and shell syntax pass |
| Package | CRC, exact source/compiled bytes, executable modes, asset links, exclusions, older ZIPs/responses/fixtures and actual extracted launcher checked; final file count/checksum in external release artifact |

The first full run exposed one stale literal version assertion; it was updated from position v8 to v9, then the accepted full suite was rerun. An earlier supplemental run showed two missing target-path witnesses on ownership-operation rejection; the rejection now retains the validated reference paths, and those assertions pass. Neither failure was skipped or marked expected. Intermediate harness attempts and repeats are not counted as accepted runs.

No fresh dependency installation, advisory audit, OS keyring validation, Windows/macOS execution, independent browser acceptance, provider/mainnet authentication or full real-wallet acquisition is claimed. Browser checks and schema fixtures are developer validation. Public parser retrieval is independent of the provider; no Helius credits were spent or quota reset.

## R1 remains OPEN

Complete historical ownership, acquisition basis, eligible populations, classification, valued external flows/boundary inventories and economic costs are not implemented as a completed independently validated wallet branch. The review correctly identifies missing implementation as well as missing acceptance data. All wallet-level requirements remain unconditionally UNKNOWN. A named-account six-hour hold or observed fee sum cannot fill the full wallet median, ROI or strict-profit fields.

The next major product milestone remains one supported real-wallet report with frozen archived inputs, independently calculated expected results and evidence-removal controls; a correctly calculated loss or policy miss is valid acceptance. PDF page 6 requires an independent historical ownership witness because a hidden closed-account round trip can leave no residual mismatch. Page 18 requires an explicit source-sufficiency decision if native data cannot provide it. Current account enumeration, fixed-point paging, selected cached receipts, more quota, relaxed thresholds or synthetic completion flags cannot satisfy those prerequisites. No profitable MATCH is required for engineering acceptance, and no copy-trading safety claim follows from this scoped correction.
