# RANKED100_ANCHORED_VALIDATION — live page 0

**LIVE INCOMPLETE.** Not MATCH. Not PRODUCT_READY. Not a G3 pass.

- Grant `live-ranked100-anchored-validation-2026-10-06-mitch` approved 2026-10-06 08:08 ACDT (`2026-10-05T21:38:00Z`). Single-use; expired/consumed after this job (`consumed_at` 2026-10-05T21:41:25Z). Repo template stayed `enabled: false`. Local armed copy was consumed and is not in git.
- Executable tip `2f45759811f6b1a2ea2301c7fd75a2a926a7f140` (code = `723c4d5877c39fa78a9e46b21b83e93988325579`).
- Page 0 used `filters.signature.lte` as prepared (`3Brdt8dMcSY96bjkKf3DZKDAWjo7r1znTMj6H2iuzBWSTA4XuwPGaBxVy4yDM6xeWDu2AKwX3o7WEFdAECc4GDHG`). HTTP 200; 100/100 signature MATCH; returned paginationToken matches frozen `452802642:577`; `SOURCE_RECORDS_INTACT` 100/0/0; persist-before-validate; no quarantine.
- Decoded supported swaps: **0**. Closed positions: **0**. No application report saved. Page 1 **not** fired (`page1_not_for_episode_count_or_pnl` — no named missing acquisition/position boundary).
- Decoder: ~80/100 Pump.fun bonding-curve `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` with no reviewed instruction path.
- Spend: Helius **1 request / 10 credits**; leftover **1/10 forfeited**; Birdeye 0; $0; no retries.
- Runner defect: `g3_reacquire._summarize_page` feeds unwrapped GTA records to `decode_supported_swaps` (all “Missing raw transaction result”). Offline re-wrap still yields 0 swaps. Fix that wrap offline, then add a reviewed Pump.fun decoder, before any further live spend.

## Box-only artifacts (not committed)

- raw credential-free source capture `SOURCE_RESPONSE_page0.json` (2.4 MB; sha256 recorded in INTEGRITY_CHECKS.json)
- `scanner.sqlite`
- the consumed local armed grant
- all of these live under `/workspace/ranked100-anchored-validation-live/` on the secure box

Freeze/overlay manifests under `g3-integrity-reacquire-rank1/` were referenced and not modified. Prior reacquire / leftover G3 / G1 / ranked-100 grants were not reused. A fresh data dir was used.
