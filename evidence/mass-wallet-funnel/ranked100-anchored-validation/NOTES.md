# RANKED100_ANCHORED_VALIDATION — offline prep

**OFFLINE_PASS.** Shared historical ingest now accepts authorization ID
`live-ranked100-anchored-validation-2026-10-06-mitch`. Repo grant template stays
`enabled: false` / `DISABLED; NOT AUTHORISED`. No approval_time/expiry.

Tested executable commit: `723c4d5877c39fa78a9e46b21b83e93988325579`
(reviewed baseline tip `3409b3ad5e8adda0cb232467192a52dab1ecbc92`).

Grant path: `config/live_authorization.ranked100-anchored-validation-draft.json`

## Binding

`accepted_historical_authorization_ids()` on the existing shared path now includes
the new ID alongside the historical reacquire ID. Changing a JSON filename or
re-enabling the old template is not the binding. `load_anchored_validation_grant()`
is the only loader for this ID; `load_reacquire_grant()` rejects it.

Cache / quarantine / source-capture keys include `authorization_id`, so a later
live run under this grant cannot overwrite the old reacquire capture.

## Referenced manifests (not rewritten)

- `evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1/FROZEN_SEGMENTS.json`
- `evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1/rank1-signature-overlay.json`

Those files keep authorization_id `live-g3-integrity-reacquire-rank1-2026-10-06-mitch`.
Page 0/1 remain EXTRACT_OK 100+100. Prior reports, damaged records, and ledgers
were not modified.

## Wallet / request shape

Wallet only: `25865JdBJVVLbt6Kfe4KnKrVCy8UVCYFRRBAPvmJ17LL` (frozen ranked-100 shortlist rank 1).

Page 0: `filters.signature.lte` =
`3Brdt8dMcSY96bjkKf3DZKDAWjo7r1znTMj6H2iuzBWSTA4XuwPGaBxVy4yDM6xeWDu2AKwX3o7WEFdAECc4GDHG`.
GTA full / limit=100 / desc / finalized / status=any / tokenAccounts=all /
maxSupportedTransactionVersion=1. No top-level `until`.

Conditional page 1: `paginationToken` `452802642:577` only after page 0 integrity
plus a recorded missing acquisition/position boundary.

## Hard limits

max 2 Helius GTA; max 20 credits; max 10 credits/call; limit 100; concurrency 1;
retries 0; 300s; Birdeye 0; $0 extra. Leftover units from any prior grant are
not reused.

## Live still paused

Zero Helius/Birdeye calls from this prep. Live still requires Mitch's **separate
explicit approval** of this authorization ID plus tariff/quota confirm on a local
uncommitted armed copy. Do not enable the repo template. Do not merge PR #4.
`PRODUCT_READY` stays false.
