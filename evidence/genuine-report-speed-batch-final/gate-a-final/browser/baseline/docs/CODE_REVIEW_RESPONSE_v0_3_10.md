# Independent review response · v0.3.10

This responds to **Solana Wallet Scanner v0.3.9 — independent source review**, dated 3 October 2026. The reviewed ZIP remains unchanged: SHA-256 `61be3f487251b5106f7eab90eb39cc2a71fa61d6f6bddfd7b074982a59f7f8c2`. Before edits, all 137 source/compiled entries matched the archive. Its exact response is preserved as [CODE_REVIEW_RESPONSE_v0_3_9.md](CODE_REVIEW_RESPONSE_v0_3_9.md). All ten previous ZIPs, historical responses and genuine fixture bytes remain immutable and are compared during release checks.

**R14 is corrected within the tested scoped contract. R1 remains OPEN in complete financial implementation and independent real-wallet acceptance.** No verified profitable wallet or copy-trading candidate is established.

| Finding | Response | Boundary |
| --- | --- | --- |
| R1 — complete real-wallet accounting | **OPEN** | Historical ownership/basis/population/classification/valuation branch and independent complete real dataset remain unfinished. |
| R2 — delivery/dependencies | Existing local delivery checked; historical dependency evidence preserved | No fresh dependency installation, new advisory audit, independent browser acceptance, security certification or other-platform execution. |
| R7–R13 | Retained within tested scope | Faithful shipped cases pass within the full suite; older separate external executions are historical evidence. |
| R14 — instruction account-list precedence hides ownership change | **Corrected** | Instruction representation and account-reference contracts are required before proving irrelevance; rejecting hashes/paths remain attached to the scoped result. |

## Reproduction and correction

On unchanged v0.3.9, the untouched new bundle reproduces **41 passes and 16 ordinary failures**, twelve direct and four actual saved-report API cases for one defect. Selected inputs retain eight authenticated references/hashes; alternatives retain nine. No cap, archive authentication, frozen reference list or original fixture is altered. Independently supported observed fees remain 0.000015 SOL. Profit stays unknown, policy UNRESOLVED, qualification false and wallet-level gates UNKNOWN.

The old `_references` function returned from an instruction's `accounts` list before checking its parsed participation. Empty/disjoint lists could hide two explicit account-owner changes in the partial-sale record, even though endpoint ownership and quantities matched. The same defect affects selected/alternate sources and outer/inner instructions; it is not established as newly introduced in v0.3.9 or as a real mainnet occurrence.

`instruction_scope.inspect_instruction` now validates the admitted representation before deciding relevance. Compiled/partially decoded account lists use typed in-range indices or decoded nonempty address strings; a heterogeneous list is unsupported, while an empty opaque list remains a valid disjointness witness. Each declared program ID/index validates independently and both must resolve to the same program. A program label cannot hide contradictory indexed identity, including before a metadata shortcut.

Fully parsed token/System/Associated Token operations require a type/info shape and the explicit operation-specific target-reference fields listed in the normalizer. These are minimum scope fields, not an exhaustive Solana parser. Unknown parsed operation types or missing/null/non-string required targets cannot prove irrelevance. Remaining quantity, amount, ownership and instruction semantics retain their own checks. Conservative nested info traversal preserves referenced-field paths. Supported parsed memo text and opaque Compute Budget/memo representations retain their no-token-quantity role after shape/program validation.

**Parsed instructions combined with `accounts` or `data` have no reviewed reconciliation contract in this release**, even when some values match. They remain unresolved; no representation takes precedence. This fixes a representation/relevance rule rather than blacklisting one `setAuthority` spelling. Explicit support for a combined shape would require a reviewed reconciliation contract.

The shared normalizer serves outer route recognition and the flattened outer/inner operation walk for every relevant selected or alternate archive. `InstructionEvidenceError` carries the rejecting raw paths. Position validation retains signature, archive hash, paths, UNKNOWN state and reason, and blocks dependent source/continuity/hold claims. Paths are actual `transaction.message.instructions.<index>` and `meta.innerInstructions.<group-index>.instructions.<index>` locations, with the inner group-array index distinguished from the associated outer instruction index. Valid disjointness and metadata witnesses are retained too. Offending archives and frozen references are not deleted, rewritten or relabelled.

During verification, eight additional missing/null parsed-target variants on unchanged v0.3.9 also retain the unsupported hold; four array-target controls already reject through the older recursive traversal. All twelve now require a valid target contract and retain the precise rejecting field path. This is additional developer acceptance for the same decision to skip an instruction, not an independent review finding or twelve additional vulnerabilities.

This is a scoped executed-operation dependency, not a blanket source veto. Proven atomic failure with unchanged token boundaries does not manufacture committed ownership changes from attempted instructions, including mixed representations. Supported native fees/endpoints and raw pre/post quantity facts retain their own evidence. A basic transaction-role receipt or endpoint-consistency PASS can coexist with UNKNOWN position-operation support. The old correctly excluded parsed/opaque operations and fee isolation controls still pass.

[CONTRACT.md](CONTRACT.md) records the admitted shapes, minimum target-reference contracts and rejected-path schema. This follows PDF pages 6–8's event-time ownership and supported-operation prerequisites; page 9 filters are unchanged.

## Versioning and immutable rebuilding

Only the affected position interpretation advances: **`account-position-evidence-v8`**. History stays `history-evidence-v8`, source consistency `source-consistency-v4`, chronology v2, accounting fifo-v3 and swap/nonce interpretation spot-v4-durable-nonce. Native fee arithmetic has no new interpretation in this correction. An old position v7 needs rebuilding even when its history method is current. Read/state/export annotations preserve the original values; an offline rebuild creates a separate current child from the same original window, preset and frozen reference lists.

The real cached 23-record observation still supports 0.000240394 SOL in observed network fees and no known closed account episode. Global financial gates remain UNKNOWN; this does not establish full interval costs or wallet profit.

## Validation and counting

| Check | Result |
| --- | --- |
| Untouched new external review on final source | **57 passed**; faithful copies overlap the suite and add no unique count |
| New unique R14 cases | **131**: faithful 57 +supplemental 74 |
| Supplemental controls | 62 representation/operation/program/metadata/atomicity/isolation cases plus twelve required parsed-target cases; four actual program-conflict API children are within those 74 cases |
| Full shipped Python suite | **1,389 passed; 264 subtests passed** in 210.63 s; one existing Starlette test-client deprecation warning |
| Population | 1,257 prior +131 R14 +one freshness =1,389; one dynamic current-method node rename, no semantic deletion |
| Frontend | **315 assertions**: 16 formatting +299 UI/data; pinned production TypeScript/Vite build passes |
| Unchanged bounded shape probe | **240 mutations, zero unexpected exceptions**; separate from pytest, not exhaustive fuzz/security assurance |
| Additional review shape probe | **73 mutations, zero unexpected exceptions**; original logic with only its hardcoded output destination redirected to scratch |
| Final browser/API session | **18 completed offline child rebuilds; 38 captures** at 1440/390 px; eight mixed-reference cases, two parsed-target cases and eight ownership/disjoint/metadata/atomicity/fee/program/cached-real controls |
| Browser/data guards | No overflow/JS errors/external/provider/credential requests; old rows, exports, frozen lists, original source SQLite and 200-used/zero-reserved ledger unchanged; QA server stopped |
| Local runtime | Editable 0.3.10, pip check and shell syntax pass in existing pinned Python 3.12.14/Node 24.19.0 environment; no fresh dependency install/advisory audit |
| Final package | **144 unique entries**; CRC, exact source/compiled bytes, executable modes, asset links, exclusions, ten earlier ZIPs/responses, genuine fixtures and extracted launcher checked in external release artifact |

The uploaded new helper is byte-identical. Each of the two shipped external modules qualifies only its sibling-helper import; external source-selection conftest is not bundled. No skip or xfail is introduced. The sixteen original failures reproduce one defect. Repeated external executions, API children, subtests, shape probes and captures are not added to unique pytest counts. The supplied 57 cases create eight API children per execution, while supplemental cases create four; these remain within their respective case counts.

Seventeen synthetic browser parents have actual immutable v0.3.9 interpretations, not relabelled current results. The final browser session uses the actual guarded launcher, compiled interface and a read-only backup of the original cached database. Its 38 captures comprise 36 full-page images and two focused recovery viewports. The application uses its pinned environment; Playwright uses the installed global runtime. A first browser harness used a JavaScript-style callable `first` selector; changing it to Python's locator property corrected the harness without an application edit. Earlier intermediate browser sessions are not counted as final-session acceptance.

The independent review's supplied **1,257/264** run and separate **41-pass/16-failure** new modules used available Python 3.13.5 review libraries, not exact pins. Retrieval/npm/DNS restrictions prevented exact installation and full pinned frontend build. Chromium administrator policy blocked independent rendering. Those limits are preserved rather than interpreted as invalid pins, independent acceptance of developer captures or security certification. Current local checks use the existing pinned environment; macOS/Windows execution and a real OS-keyring backend are not newly established.

## R1 remains the next product milestone

The supplied PDF page 6 requires independent historical ownership evidence because current account enumeration/fixed-point paging can miss hidden closed-account round trips with no residual mismatch. The existing 94 selected receipts and short caches do not establish 30/90-day eligible ownership, acquisition origins or complete wallet position populations. The inspected history decisions remain wallet-level UNKNOWN. The complete financial branch and ownership source adapter, and an independent complete real acceptance dataset, remain absent. Page 18 requires a source decision when native evidence is insufficient.

The next major product acceptance is one supported real-wallet report with archived source inputs, independently calculated expected results and source-removal controls. A correctly calculated loss or policy miss is valid acceptance. Realised P&L requires eligible population, acquisitions, economic costs and classification; economic P&L additionally requires relevant boundary inventories/marks and valued flows. Wallet-wide strict holding populations require mint-aggregate zero across eligible historical ownership, including losing, breakeven and unresolved episodes. Another scoped trade/timing fixture, a larger quota, synthetic completion declaration, relaxed thresholds or dashboard feature does not implement that branch.

No paid source, custody, signing, trading, threshold relaxation or new synthetic whole-wallet completion branch is supplied. The original setup ledger remains **200 used /zero reserved**; Free entitlement/cycle remain unknown. No new provider request or credential lookup occurs. Fixing R14 does not complete wallet profitability or copying-safety verification.
