# G3_RANKED100_HISTORY — offline prep

Bounded history verification from the ranked-100 shortlist. **Not** full G2.
`PRODUCT_READY` stays false. G1 and ranked-100 grants must not be reused.
Setup-pilot must not be reset. No winner requirement.

## What was prepared (offline only)

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

## What still blocks live (operator / box — not this cloud VM)

A present `HELIUS_API_KEY` or the prior G1 pass is **not** enough. Before arming:

1. Confirm Helius **pricing** (documented 10 credits per GTA ≤100 full txs is an estimate until the dashboard is read).
2. Confirm **entitlement** for `getTransactionsForAddress` on the existing plan (`existing_plan_confirmed=true`).
3. Confirm **remaining quota** (`remaining_quota_confirmed_at`) so 15 requests / 150 credits fit with $0 extra spend.
4. Set `enabled: true` only in a separate secure runtime that already holds the key. Do not paste keys into git or this VM.
5. Grant must still be unexpired. Do not reuse G1 or ranked-100 grants. Do not reset setup-pilot.
6. No new discovery, page enlarge, endpoint switch, auto-retry, or additional addresses.

## Exact live query (implemented; not dispatched here)

Helius `getTransactionsForAddress`  
`transactionDetails=full`; `limit=100`; `sortOrder=desc`; `commitment=finalized`; `filters.status=any`; `filters.tokenAccounts=all`.

First page per initial candidate if no equivalent cache. Further pages need a recorded evidence-based reason (`insufficient_episodes_pagination_token_present`). Reserves 6, 7 only if three qualifying reports are not yet in hand. Every dispatched attempt counts, including fail/timeout.

## What to report after a later live run

| Field | Why |
| --- | --- |
| Freeze SHA + addresses actually investigated | No additional live addresses |
| Per-wallet pages, reasons, pagination tokens | Prove adaptive paging was evidence-based |
| Raw/redacted GTA pages + `evidence_sha256` | No invented history |
| Unique supported closed episodes per report | G3 bar is ≥10; smaller reports stay visible |
| Independently reconciled subset worksheet | Not MATCH, not wallet-wide |
| Qualifying report count (target 3) | Zero or fewer than 3 is honest |
| Helius requests / credits: documented 10 vs dashboard | Estimate vs confirmed billing |
| Birdeye requests | Must be 0 |
| setup-pilot before/after | Must be unchanged |
| Truncation / coverage | 90-day floor and missing timestamps stay unknown |

Do not claim profitability, copyability, MATCH, full G2, or PRODUCT_READY.
