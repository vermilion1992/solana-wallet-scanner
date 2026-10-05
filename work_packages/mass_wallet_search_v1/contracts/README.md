# Contract usage

These schemas are proposed application boundary contracts. They are not existing scanner endpoints. Codex should implement or adapt them with versioned mapping, preserving the meanings, not copy a schema and claim the runtime already enforces it.

The receipt checker is deliberately dependency-free and enforces a fixed receipt shape plus semantic invariants. It is not a generic JSON Schema engine. Standard JSON Schema validation may additionally be used in the application; timestamp ordering, count conservation, authorization, evidence-role requirements and actual financial derivation still need dedicated code and tests.

`benchmark_receipt.schema.json` uses decimal strings for monetary fields, integer counts, exact source/lock hashes and evidence-role references. Artifact paths resolve beneath `--evidence-root` (default: the receipt's directory); parent traversal and escaping symlinks are rejected. Hashes are verified against files, not trusted from their filenames.

Corpus kinds:
- SYNTHETIC: generated fixtures or simulated provider transports.
- GENUINE_REPLAY: genuine archived inputs processed offline; no claim of fresh acquisition/forward collection.
- GENUINE_LIVE: a declared fresh acquisition run, requiring independent provenance checks outside the structural checker.

The common contract forbids additional paid spend under package v1, source-dirty acceptance, external calls during cached refilter, impossible stage counts and legacy full-wallet readiness claims. A separately authorized paid research revision needs a separately reviewed contract; editing the amount field alone is not approval.

Profiles:
- `development`: validates structure, timestamps, budget/count invariants, declared claims and local artifact integrity.
- `live-search`: additionally requires genuine-live-labelled acquisition and the 1,000-candidate/three-reconciled-report/minimum-population evidence declarations and roles.
- `forward-operation`: additionally requires genuine-live-labelled causal entry/exit observation evidence and minimum counts.

Exit 0 means **contract checks satisfied**, not proof of genuine origin, full arithmetic, independence, performance targets or profitable following. Exit 1 means malformed/contradictory receipt or artifact-integrity failure. Exit 2 means structurally valid but insufficient for the requested live/forward profile. A true claim contradicted by its own receipt is invalid, not merely incomplete.

`selection.plan_frozen_at` records policy pre-registration. `universe_sealed_at` records the acquired snapshot sealing. `cohort_frozen_at` and `cohort_sha256` bind the actual prospective selection before the forward start. A pre-registered plan alone is not proof that wallets were selected before their observed outcomes.

No filled genuine example is supplied: inventing one would undermine the handoff. The sample receipt is synthetic and cannot pass the live or forward profiles.
