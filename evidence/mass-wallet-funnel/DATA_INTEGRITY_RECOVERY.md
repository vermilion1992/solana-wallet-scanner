# Data-integrity recovery (offline) — 2026-10-05

Not a live G3 re-run. Not a G3 pass. `PRODUCT_READY` stays false.
Grant templates stay `enabled: false`. No provider calls in this revision.

## Locked decision

Do not expand discovery, buy more history, activate grants, merge PR #4, or
promote the 2026-10-06 G3 live run. Preserve that evidence. Append this
correction. Do not invent profitability on the five G3 addresses.

## Confirmed defect

Reviewed `redact_secrets` at `864a75b9d45d3318d3593c2dd4c9c9b9dd973e93`
used substring matching of `api[_-]?key|authorization|secret|token|password|credential`.
`g3_history.fetch_helius_page` cached `redact_secrets(records)` and then decoded
those records. Legitimate fields `preTokenBalances`, `postTokenBalances`,
`uiTokenAmount`, `tokenAmount` and the public SPL Token program id `Tokenkeg…`
were replaced with `[REDACTED]`.

Standalone synthetic reproducer (zero network, does not import the app):

- `wallet_scanner_recovery/reproduce_transaction_redaction.py`
- result `DESTRUCTIVE_REDACTION_REPRODUCED` in
  `g3-ranked100-history-live-2026-10-06/redaction_reproduction_result.json`

The earlier G3 zero-swap observation is an observation of that pipeline, not a
clean venue-coverage measurement.

## Secure-box cache (already inspected; keys were not exported)

`SOURCE_RECORDS_CACHE_INSPECT.json` for grant
`live-g3-ranked100-history-2026-10-06-mitch`:

- 10 pages / 1000 txs
- `intact_preTokenBalances_arrays=0`
- `damaged_preTokenBalances=1000`
- no unmodified original bodies or raw sidecars

Classification: **SOURCE_RECORDS_DAMAGED** for those records.
A hash cannot restore deleted balances. Do not manufacture replacements or
silently reacquire. A later separately approved minimal repair acquisition may
be needed after this code fix; that grant is out of scope here.

## What this revision fixed (offline)

- Schema-aware credential handling: real secret keys/URLs redacted; public token
  fields and program IDs preserved. `authorization_id` is not treated as a secret.
- Transaction pages stored as `g3-history-page-v2` under a new cache key prefix.
  Legacy v1 pages are loaded as `SOURCE_RECORDS_DAMAGED` and are not overwritten.
- Integrity failure is a distinct classification from unsupported trading.
- Report window: frozen acquisition-start, exclusive report-end; missing
  timestamps stay missing; within-block order left unresolved when absent.
- Completed episodes are flat-to-flat position closes, not partial-exit sale
  counts. Qualification, worksheet and displayed declared subset use the same
  multi-mint population. Per-mint remains drilldown.
- Further paid pages are refused when inputs are corrupted, malformed, or
  classified unsupported / transfers-without-reviewed-swap / inactivity.
- Genuine G1 archived Helius page survives sanitize → cache → production
  decoder → independent worksheet at **−0.167725526 SOL**.
- Below-G3 reports and unresolved observations stay visible on the report API
  and subset worksheet panel. Reopen/export/refilter after restart make zero
  provider calls.

## What is still blocked

- The 2026-10-06 G3 sqlite cache cannot be repaired from hashes.
  G3 remains **INCOMPLETE** (0 / 3 qualifying reports) and is **not re-passed**.
- Recovering those five wallets needs a future, separately approved minimal
  reacquire of intact `getTransactionsForAddress` pages. Unused old-grant
  allowance must not be reused automatically.
- Rank-1 reacquire grant `live-g3-integrity-reacquire-rank1-2026-10-06-mitch`
  is encoded and stays `enabled: false`. Surviving metadata is
  `STOP_NO_SEGMENT` (0/0 original signatures). Do not fetch current history.
- Full G2, live Helius/Birdeye from this cloud tree, leftover G3 reuse, merge, APK, wallet-v2,
  profitability claims, and `PRODUCT_READY` remain out of scope.

## What is not claimed

Not PRODUCT_READY. Not G3 PASS. Not full G2. Not MATCH. Not a venue census of
the five frozen addresses. Not a decoder-coverage conclusion from the damaged
cache. No credentials, `.env`, armed grants, or request headers are in this
tree.
