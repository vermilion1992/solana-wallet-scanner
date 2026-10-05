# G3_RANKED100_HISTORY — live INCOMPLETE + offline prep

Bounded history verification from the ranked-100 shortlist. **Not** full G2.
`PRODUCT_READY` stays false. G1 and ranked-100 grants were not reused.
Setup-pilot was not reset. No winner requirement. Do not invent profitability.

## Live result (secure box, 2026-10-05) — INCOMPLETE

Evidence: `evidence/mass-wallet-funnel/g3-ranked100-history-live-2026-10-06/`
Decoder coverage: `g3-ranked100-history-live-2026-10-06/DECODER_COVERAGE.json`

Grant `live-g3-ranked100-history-2026-10-06-mitch` ran on a secure box under ceilings.
Repo template `config/live_authorization.g3-ranked100-history-granted.json` stays **`enabled: false`**.
The box used a local armed override that was **not** committed.

| Item | Result |
| --- | --- |
| Status | **INCOMPLETE** (honest) |
| Qualifying reports (≥10 supported closed episodes) | **0 / target 3** |
| Visible below G3 | 0 (no supported closed pairs) |
| Investigated | frozen ranks 1, 3, 5 + reserves 6, 7 (2 pages each) |
| Per-wallet status | all `NO_SUPPORTED_CLOSED_PAIR`; 200 records / 0 episodes |
| Decoder | `spot-v7-native-flow-roles`: txs fetched HTTP 200; **0 decoded_swaps / 0 supported_transactions** on these pages |
| Decoder gaps | unsupported programs/discriminators; transfers-without-reviewed-swap; wallet absent from account keys; unsupported tx version |
| Helius | 10 requests / ~100 documented-estimate credits (ceilings 15/150) |
| Birdeye | 0 |
| setup-pilot | untouched (0 / 200) |
| Extra spend | $0; no retries, page enlarge, or endpoint switch |
| Stop | `wallet_investigation_cap` |
| Application SHA | `c3a3ffe5d910823f1113ea5b4f8912c3cf47dfce` |

Documented 10 credits/GTA is an **estimate**, not a confirmed dashboard receipt. Responses had no billing headers.

Page-0 `evidence_sha256`:
- rank 1 `b0fa9cb76a9e9531b5654f4fa22b0e9b7ef9a81ab61fa21bc16a649de0fb492d`
- rank 3 `9c249add35a7871c0aa5019181abb6f8c3e7cad2920039da414736d454965d8a`
- rank 5 `6c8b7f4c11d99d1189665ea0b78e5cf7ec213684d7e9b68193d6c2733a75c23c`
- rank 6 `8d159468e192e516dc8692416d981ce17264ef2443f8f7c78988d5d85860fa9d`
- rank 7 `f28b652f292994892f8bcf01cab35be19f7f2d1e680d0826491693fde964b749`

Zero qualifying reports is an honest outcome. Do not invent profitability, copyability, MATCH, full G2, or PRODUCT_READY.

## What was prepared (offline)

- Disabled grant: `config/live_authorization.g3-ranked100-history-granted.json`
  - id `live-g3-ranked100-history-2026-10-06-mitch`
  - approved `2026-10-05T14:19:00Z` (~2026-10-06T00:49 Australia/Adelaide)
  - expires `2026-10-06T14:19:00Z`
  - Helius 15 requests / 150 credits / 10 credits per `getTransactionsForAddress`
  - max 5 wallets, max 3 requests per wallet, concurrency 1, 900s, retries 0
  - Birdeye and other providers 0
- Freeze: `evidence/mass-wallet-funnel/g3-ranked100-history/FROZEN_CANDIDATES.json`
  - parent commit `159639b1bc4fd20d6504026f8d58247f1b2e42c9`
  - initials ranks 1, 3, 5 and reserves 6, 7 only
  - 30-day report window ending at discovery cutoff `2026-10-05T13:29:27Z`
  - acquisition-support from 90 days before cutoff
- Runner: `scanner/mass_search/g3_history.py` through `MassSearchService.reconstruct_candidate`
- Cache + Helius request/credit ledgers survive restart; reopen makes zero provider calls
- Offline CLI refuses `--live`

## How to run the offline prep

```bash
.venv/bin/python -m pytest -q tests/test_mass_search_g3.py
.venv/bin/python tools/mass_search_g3_ranked100_offline.py --data-dir /tmp/g3-ranked100-offline
```

## Exact query that was dispatched on the box

Helius `getTransactionsForAddress`  
`transactionDetails=full`; `limit=100`; `sortOrder=desc`; `commitment=finalized`; `filters.status=any`; `filters.tokenAccounts=all`.

First page per candidate: `first_page_no_equivalent_cache`. Second page: `insufficient_episodes_pagination_token_present`. No third page. All 10 HTTP 200. No auth/entitlement/quota/rate-limit/schema/accounting failures.

Do not claim profitability, copyability, MATCH, full G2, or PRODUCT_READY.
