# Solana Wallet Scanner — four-file review and product-completion decision

Review date: 4 October 2026 (Australia/Brisbane).

## Decision

Continue from the stabilised candidate, not from the old ZIP and not from a new architecture. The submitted FINAL_GATES records developer acceptance of Gate A's declared subset. Gate B is explicitly still open: completed-wallet implementation is absent and the historical source/real acceptance contract is blocked. This review does not independently recertify Gate A or establish a new wallet-accounting defect.

The immediate work is a small validation receipt correction, one complete candidate/evidence handoff, and implementation of the supported real-wallet report. Do not let the small correction turn into another product-free release cycle.

## Inputs and independently executed checks

The four current uploads are FINAL_GATES.json, validate.py, test_instruction_contract_matrix.py and ISSUES.md. All were read in full. Current mounted files and relevant Project/Library searches were checked for the referenced current fixtures, source decision and browser tools; those dependencies were not available as standalone source files in this handoff. The earlier v0.3.11 ZIP is available but does not represent this candidate.

| Check | Independently observed result |
| --- | --- |
| Uploaded validate.py vs tools/validate.py in the manifest | SHA-256 matches exactly |
| Uploaded test_instruction_contract_matrix.py vs the test manifest entry | SHA-256 matches exactly |
| Uploaded ISSUES.md vs the manifest entry | SHA-256 matches exactly |
| Aggregate manifest digest, recomputed from its listed hashes and modes | Matches the claimed digest; 169 listed files |
| Embedded review source/commit and install lock/runtime identities | Internally agree with the final report |
| Gate records | All 13 listed gates say PASS |
| Comparison with earlier v0.3.11 ZIP | 17 additional paths and 8 changed common files |
| Unchanged runner: isolated control-flow tests | 25 passed; 7 ordinary failures |
| Proposed runner-only correction: same isolated tests | 32 passed |
| Current full backend suite, instruction matrix and real browser | Not independently executed here |

The runner tests execute the supplied main(), required_record() and gate_decision() with external commands, source snapshots and lock reads stubbed. They are unit-level runner checks, NOT 32 real browser runs, source integrity certification, exact installation or financial acceptance. They used Python 3.13.5 and pytest 9.0.2 in this review environment. No live provider, credentials, wallet database, trading or network installation was used.

`evidence/input-integrity.json` contains the hashes, the current-vs-earlier-archive path comparison and check boundaries. `evidence/validator-tests.log` and `evidence/proposed-fix-tests.log` contain execution output. The two scenario JSON files record each main() simulation. Original uploads remain byte-unchanged.

## What each supplied file supports

### FINAL_GATES.json

The candidate is commit `96fb1ebb7f6f41dc3c3c72ff4cac209a3fdcc272`, with source digest `b3ec1bc2b862af41952d2a0f93d47f26ea1ba9add07dd6e6d8021745fc213534`. The final summary reports 1,791 backend tests, 264 subtests, 315 frontend assertions, 61 matrix items, 38 reviewed schema examples, six offline browser children and 16 captures. These are developer-reported executions, not independently rerun counts.

The report explicitly identifies the review as a distinct developer pass by the same engineer, not third-party certification. The clean-install record describes a disposable Linux install using the matching dependency locks, while the candidate separately records frontend installation/build and runtime checks. This supersedes treating prior registry/browser restrictions as proof of current developer failure, but does not establish execution on other operating systems.

The `real_case_executed: true` field is not whole-wallet acceptance: the same summary keeps CAP-01 OPEN and DATA-01 BLOCKED. A cached-real offline browser example can be genuine and useful without satisfying the missing historical coverage and accounting contract.

Raw backend/browser/install logs are referred to by workspace paths. A pathname or a consistent manifest proves neither that the recipient has the bytes nor that the recorded assertions are true. Export the actual evidence and candidate at the next checkpoint, with relative paths and hashes. There is no basis here to claim the reported run was fabricated or failed.

Source anchors: FINAL_GATES.json lines 354–549, 552–664, 666–712.

### validate.py

The runner is a useful improvement. It separates focused and candidate checks, records commands and exit codes, binds locks/review metadata and checks whether source changed. Focused success becomes FOCUSED_PASS; Gate B stays separately OPEN. It must be reviewed/run as tools/validate.py inside the repository: ROOT is derived from the file's parent directories. The detached upload is not a standalone application validator.

One bounded defect is reproduced in the browser-result boundary, described below. Additional trust boundary: required_record() validates the shape and selected contents of supplied attestations; it does not independently replay their referenced logs. That is why raw evidence delivery matters. This review does not classify ordinary developer attestations as a security attack or propose rewriting the validation framework.

Source anchors: validate.py lines 15–34, 37–68, 71–149.

### test_instruction_contract_matrix.py

This is the right direction for preventing another one-example schema fix: examples and expected fields come from an external fixture rather than being generated from production tables; each required field is removed in a negative test; mixed representations are rejected; declared operation populations are compared; disjoint operations preserve timing. Token-2022 entries here cover the standard target shapes admitted by the test, not all extensions or full semantic support.

The module checks selected/alternative × outer/inner API behaviour specifically for withdrawFromNonce. Its all-example disjoint timing test uses alternative/inner only. Other modules might cover the remaining combinations, so absence in this module is not proof of a missing repository-wide test. Inspect the existing 61-item mapping before adding duplicates or demanding an exhaustive Cartesian product.

The actual instruction_family_schema.json and current scanner implementations were not supplied. Therefore this review cannot authenticate the claimed pinned primary examples or run the matrix by itself. Do not copy this module into the old ZIP and call that the candidate's test result.

Source anchors: test_instruction_contract_matrix.py lines 11–43, 45–65, 67–75.

### ISSUES.md

Keep this register. It distinguishes confirmed defects, retained regressions, missing capability, data limitations, delivery evidence, non-defects and deferred protocol support. The source-decision summary says five wallets and 94 cached selected records do not establish complete historical ownership/populations and required financial dependencies. That is a limitation of the documented material, not a demonstrated impossibility of a free solution.

The current CAP-01 wording places the pipeline after B1. Resolve the input contract first, but do not interpret external acceptance-data unavailability as a blanket ban on executable local implementation. Positive synthetic development tests are legitimate as long as they cannot close B3 or supply fake real-world provenance. The active next task should now be product completion, not another general stabilisation assignment.

Source anchors: ISSUES.md lines 15–19, 24–38.

## Proposed PROC-03: browser receipt not required for a passing gate

### Reproduction boundary

The actual browser producer was unavailable. To test the runner's own enforcement, every external command was stubbed successful and source/lock identities held stable. Only browser/result.json varied. The supplied validator was loaded unchanged; no application code was invoked or edited.

| Browser subprocess | Result file | Unchanged runner result |
| --- | --- | --- |
| Exit 0 | Explicit PASS object | ACCEPTED_IN_SCOPE — expected |
| Exit 0 | Missing | ACCEPTED_IN_SCOPE — unsupported |
| Exit 0 | FAILED object | ACCEPTED_IN_SCOPE — unsupported |
| Exit 0 | INCOMPLETE object | ACCEPTED_IN_SCOPE — unsupported |
| Exit 0 | UNKNOWN object | ACCEPTED_IN_SCOPE — unsupported |
| Exit 0 | Object without state | ACCEPTED_IN_SCOPE — unsupported |
| Exit 0 | Malformed JSON / non-object JSON | Exception; no structured final decision |
| Exit 0 | BLOCKED object | INCOMPLETE — expected |
| Exit nonzero | Passing or failed object | FAILED — expected |

There are seven failing test variations for one receipt-handling boundary: five false acceptance outcomes and two unhandled parse/shape outcomes. They are ordinary failures, not xfails. The 25 passing controls include genuine command-failure preservation, focused-mode distinction, source changes, missing install/review records, mismatched locks/runtime/source, unresolved review blockers and aggregate state decisions.

The failure follows directly from validate.py lines 105–110 setting PASS from process exit and lines 133–135 special-casing only BLOCKED. The final aggregate then accepts the remaining PASS gates. This is a medium release-assurance issue in the wrapper, not a demonstrated profitable-wallet bypass or proof that candidate 96fb1eb's browser actually failed.

### Proposed correction and limitations

`proposed_fix/validate_receipt_guard.patch` adds a small result-reader/state-merger and calls it at the browser gate boundary. Both the command and explicit usable receipt must pass. FAILED/BLOCKED states are preserved, missing/malformed/unsupported receipts are incomplete, and the actual receipt bytes are hashed. The proposed standalone corrected file passes the same 32 tests.

This is a reference correction, not an integrated release. Reconcile the helper with the real browser-result schema and existing gate tests, then rerun the actual candidate checks with renewed source/review bindings. It does not authenticate the browser assertions merely by hashing their JSON. The patch makes no application-accounting, protocol or methodology change. Keep the historical candidate results unchanged.

## Product direction and acceptance

Keep the existing Gate A/B structure. Gate A is developer-recorded scoped stability; Gate B is the missing original product. Do not silently replace the latter with a sample-only tool, observed-trade profitability, relaxed thresholds or an arbitrary complete flag.

The next tasks are linked but need not all wait on the same external permission:

- B1/DATA-01: read and act on the existing full source decision. Establish the actual supported historical coverage contract and the minimal missing permission or evidence. These four files do not justify recommending a particular provider or subscription.
- B2/CAP-01: implement nonblocked parts of the normal evidence-to-report pipeline against that explicit contract, with working local input handling, event/ownership reconstruction, accounting, per-metric dependencies and existing UI/report/rebuild integration. Synthetic development cases stay synthetic.
- B3: prove the supported result on independently checked, authorised real inputs through the ordinary user workflow. Show positive supported metrics and targeted source-removal/restoration behaviour. A losing wallet is acceptable; an all-UNKNOWN report is not a completed positive accounting acceptance case.

Partial progress is useful and should be delivered truthfully. If a coverage or budget change is needed, expose it as the user's product decision, not as the engineer quietly redefining success. Full realised results, economic P&L, four-week consistency and wallet-wide holding populations retain their separate prerequisites.

OpenAI's current Codex guidance recommends supplying concrete goal, context, constraints and done-when conditions, and asking for tests and review before acceptance. The attached next task applies that approach to the existing repository rather than creating another process layer. External source checked: OpenAI, “Best practices,” https://developers.openai.com/codex/learn/best-practices/ (redirects to https://learn.chatgpt.com/guides/best-practices), sections “Context and prompts” and “Improve reliability with testing and review.” No external source was used to substitute for missing project documents.

## Next delivery

One candidate source/evidence checkpoint, not four detached status files and not a ZIP per fix. Include the current checkout, source decision, acceptance contract/matrix, canonical fixtures, required tools, final gate/review/install receipts and their raw logs/browser results. Include authorised real acceptance inputs only when claimed, without secrets or unapproved private data. The developer should read the full repository and continue nonblocked work rather than make the user retrieve every module manually.

The detailed execution assignment is CODEX_NEXT_PRODUCT_MILESTONE.md. This package is a review, a proposed runner-only patch and its tests—not a completed wallet scanner, submitted Codex job or patched full application release.
