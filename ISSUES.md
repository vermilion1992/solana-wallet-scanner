# Single issue register — initialise from v0.3.11

Status is deliberately split between execution evidence and future work. No new application defect is asserted by this workflow handoff.

| Work item | Existing finding IDs | Starting status | Owner / next deliverable | Acceptance |
|---|---|---|---|---|
| Evidence integrity, chronology and dependencies | R5–R14 | Historical scoped corrections retained by the release; not all independently replayed in this handoff | Builder: shared matrix and sibling-path audit; reviewer: consolidated findings | Gate A plus retained positive/removal/API controls |
| Instruction schema compatibility | R15 | **79 original review cases pass on v0.3.11 in this handoff**; full compatibility sweep not performed | Builder: audit all admitted target contracts, not only permission examples | Canonical upstream fixtures and retained R14 safeguards; Gate A |
| Complete financial implementation | R1 implementation | **OPEN** in v0.3.11 code and developer response | Builder: source-backed end-to-end implementation tasks | B2; normal report path, no unconditional completion override |
| Historical source feasibility and complete real dataset | R1 data | **OPEN**; no new source capability verified in this handoff | Builder/research pass: concrete source decision, then independent expected-results corpus | B1 and B3; no paid assumption or synthetic substitution |
| Exact delivery and independent interface acceptance | R2 delivery | Current full gates **NOT RUN in this handoff**; earlier environment restrictions are historical, not proof of current failure | Builder/QA: configured permitted environment and captured current results | Applicable clean-lock install, full build and actual browser checks |
| Period correctness and candidate continuity | R3/R4 | Earlier corrections are historical; unchanged requirements remain | Builder: retain existing tests; do not restart completed work without a reproduction | Full current suite; no global coverage claim from candidate imports |
| Working process | New process task, not a product bug | Proposed in this pack | Builder: one branch/register/validation entry point; reviewer: batch findings | No one-finding-per-ZIP delivery loop |

## Update convention

For each new confirmed item, add: ID, defect family, severity and affected claim, exact reproduction/test node, baseline and candidate identity, status, fix location, positive control, evidence, owner and remaining dependency. Use OPEN / IN_PROGRESS / FIXED_PENDING_VALIDATION / VERIFIED_IN_SCOPE / BLOCKED / DEFERRED.

Keep implementation, unavailable data and environment blockers separate. A green bug-fix suite cannot change R1 to VERIFIED. Do not reopen historically accepted issues merely to fill a new review report; add a new case only when a reproduction or a missing contract warrants it.
