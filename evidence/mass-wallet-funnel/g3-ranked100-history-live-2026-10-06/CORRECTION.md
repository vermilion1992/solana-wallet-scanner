# Correction — do not overwrite the live INCOMPLETE receipt

The 2026-10-06 live G3 run remains **INCOMPLETE**. This note does not re-pass it.

Subsequent review showed the live pipeline cached `redact_secrets(records)`
using substring matching that destroyed `preTokenBalances` / `postTokenBalances`
/ `uiTokenAmount` / `tokenAmount` and public `Tokenkeg…` program IDs.

Secure-box inspection (`SOURCE_RECORDS_CACHE_INSPECT.json`): 10 pages, 1000 txs,
0 intact `preTokenBalances` arrays, 1000 damaged, no unmodified original bodies.
Classification: **SOURCE_RECORDS_DAMAGED**. Zero decoded swaps on that run is an
observation of the old pipeline, not a clean measurement of venue coverage.

Do not invent profitability for ranks 1, 3, 5, 6, or 7.
Do not silently reacquire. A later separately approved minimal repair
acquisition may be required after the offline code fix.

Standalone reproducer result: `redaction_reproduction_result.json`
(`DESTRUCTIVE_REDACTION_REPRODUCED` on a synthetic fixture).

Repo grant `config/live_authorization.g3-ranked100-history-granted.json` stays
`enabled: false`. `PRODUCT_READY` stays false.
