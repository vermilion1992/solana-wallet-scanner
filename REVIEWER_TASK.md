# Reviewer assignment — one bounded consolidated review

Read the candidate diff, AGENTS.md, ACCEPTANCE.md, ISSUES.md and the source/schema evidence relevant to the changes. Review the exact recorded commit or source manifest, not an evolving working tree.

Review independently of the builder's prose conclusions. Use a separate read-only review pass or workspace; do not silently change production code. A fresh Codex session is a useful separation of roles, not independent certification by itself.

Check all defect families in Gate A, concentrating on changed decisions and sibling paths. Validate positive supported inputs as well as rejection inputs. Check selected/alternative and outer/inner parity; source-loss/restoration; actual budget edges; conflict/relevance/chronology; immutable offline rebuilding; and schema targets against pinned external examples. Inspect whether expected fixtures simply reproduce a production lookup table. Treat both false certainty and false UNKNOWN on a supported essential path as possible bugs, with different impacts.

Return all findings together. Each needs a reproducer or a clearly labelled unresolved hypothesis, exact source path, actual versus expected result, affected metric/contract, severity and a preservation control. Do not pad a report with speculative issues. Do not search indefinitely for one more novelty after the declared matrix and diff review are completed.

Report Gate A and R1/Gate B separately. Verify execution logs and identities, not test-count claims alone. A blocked browser/install check is a blocked validation gate, not evidence the source is defective. Missing R1 implementation remains open even when all scoped checks pass.

After builder corrections, verify the affected regressions and final candidate gates. Defer unrelated optional features explicitly. Return a compact decision: accepted within stated scope, blocked by enumerated reproducible issues, or incomplete due to named missing evidence. Never say all possible bugs are fixed.
