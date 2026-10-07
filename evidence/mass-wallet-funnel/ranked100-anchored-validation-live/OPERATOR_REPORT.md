# RANKED100_ANCHORED_VALIDATION — live page 0 (secure box)

**Status: INCOMPLETE — page 0 MATCH + INTACT; zero decodable trades; page 1 gate denied; no saved report.**

- Authorization: `live-ranked100-anchored-validation-2026-10-06-mitch`. Mitch approved it at 2026-10-06 08:08 ACDT (2026-10-05T21:38:00Z). It expires 2026-10-07 08:08 ACDT and is single-use.
- Account confirm (Mitch, 2026-10-06 08:10 ACDT): GTA is entitled on the existing plan, ≥20 included credits remain, and autoscaling/overages are OFF.
- Armed copy: a local uncommitted copy on the secure box only. It was disabled and marked consumed after the dispatch. The repo template stays `enabled: false`.
- Application commit: `2f45759811f6b1a2ea2301c7fd75a2a926a7f140` (code identical to tested `723c4d5877c39fa78a9e46b21b83e93988325579`).
- Wallet: `25865JdBJVVLbt6Kfe4KnKrVCy8UVCYFRRBAPvmJ17LL`.

## Request (page 0, exact)
`getTransactionsForAddress` full / limit 100 / desc / finalized / status=any / tokenAccounts=all /
maxSupportedTransactionVersion=1 / `filters.signature.lte=3Brdt8dM…4GDHG`. There was no top-level `until` and no paginationToken.

## Match / integrity
- HTTP 200; 100 records; the response was persisted credential-free before validation.
- Signatures matched the frozen manifest exactly: **100/100, same order**. The first signature equals the frozen `lte`.
- The returned paginationToken `452802642:577` is identical to the frozen page-0 token.
- Integrity: `SOURCE_RECORDS_INTACT` (100 intact / 0 damaged / 0 malformed). Nothing was quarantined.
- Block-time range: 2026-10-03T02:46:53Z → 2026-10-05T14:21:37Z. 98 records fall before the 2026-10-05T13:29:27Z cutoff; 2 fall at or after it.

## Trades / positions / P&L / hold
- Decoded supported swaps: **0**. Completed positions: **0**. Reconciled: **0**.
- P&L: **none reported**. hold / t90: **n/a**.
- 80/100 transactions invoke Pump.fun (`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`). The decoder has no reviewed Pump.fun discriminator.
- Corrected offline decode, unresolved breakdown:
  - 67: no reviewed spot swap instruction
  - 8: no reviewed outer swap
  - 5: wallet absent from account keys
  - 1: unsupported tx version
  - 19 of the 100 failed on-chain

## Page 1
Not dispatched. The gate returned `page1_not_for_episode_count_or_pnl`. With no decoded sale, there is no named missing acquisition/position boundary (mint+sig).

## Runner defect found
`g3_reacquire._summarize_page` feeds unwrapped GTA records to `decode_supported_swaps`, so every record shows "Missing raw transaction result". The fix is to wrap the records via `live_g1._wrap_records`, as `replay_cached_history_to_report` already does. A corrected offline decode (zero calls) gives the same outcome: 0 swaps.

## Spend
Helius: 1 request / 10 documented credits. The ceiling was 2/20, and the remaining 1/10 is forfeited. Retries 0. Wall time 0.44 s. Birdeye 0. $0.

## Reopen
The store and evidence were reopened with the network blocked and provider keys unset:
- 0 provider calls
- match 100/100
- integrity INTACT
- 0 saved application reports

PRODUCT_READY false. Not MATCH (position-level). Not full G2. Do not merge.
