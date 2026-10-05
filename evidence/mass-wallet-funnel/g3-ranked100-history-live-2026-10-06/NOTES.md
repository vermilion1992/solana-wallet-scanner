# G3_RANKED100_HISTORY live ONE-SHOT — 2026-10-05T14:36:39Z

## Authorization
- Grant id: `live-g3-ranked100-history-2026-10-06-mitch`
- Local armed override only: `live_authorization.g3-ranked100-history-armed.json`
- In-repo `config/live_authorization.g3-ranked100-history-granted.json` remains `enabled: false` (not committed armed)
- Helius only; Birdeye 0; $0 extra; no overages

## Outcome label
**INCOMPLETE** (honest). Target was 3 qualifying reports (≥10 supported completed observed episodes each). Achieved **0**.

## Wallets investigated (frozen ranks 1,3,5 then reserves 6,7)
| Rank | Role | Address | Pages | Records | Episodes | Status |
| --- | --- | --- | ---: | ---: | ---: | --- |
| 1 | initial | 25865JdBJVVLbt6Kfe4KnKrVCy8UVCYFRRBAPvmJ17LL | 2 | 200 | 0 | NO_SUPPORTED_CLOSED_PAIR |
| 3 | initial | DSJVxpK1gwZvFsiYdaRz7Ly51vTXnAwHGfLGWcRvVJGE | 2 | 200 | 0 | NO_SUPPORTED_CLOSED_PAIR |
| 5 | initial | 3g8KsJE1yhJvBo6kvqvxLnoSXQ9suqQnHMqGFs3LFckM | 2 | 200 | 0 | NO_SUPPORTED_CLOSED_PAIR |
| 6 | reserve | 291Yj2YfCbbMoP6UF6cPkzagvBMvUuxDmBkDbuRFJKsQ | 2 | 200 | 0 | NO_SUPPORTED_CLOSED_PAIR |
| 7 | reserve | B4HUfUDVzVuVgd3xqEm4wfCmBofuHh4h5NqjV3EzKAzi | 2 | 200 | 0 | NO_SUPPORTED_CLOSED_PAIR |

Unused reserves: none (both required because initials did not qualify).

## Adaptive paging
- First page reason: `first_page_no_equivalent_cache` (no prior G3 cache)
- Second page reason (evidence-based): `insufficient_episodes_pagination_token_present` when page-0 episodes < 10 and pagination token present
- Stop: `wallet_investigation_cap` at 5 wallets; no third page (within max 3/wallet unused)

## Credits / requests
- Helius requests: **10** / 15 ceiling
- Documented estimate credits: **100** / 150 ceiling (10 per GTA)
- Units are: `documented_estimate_not_confirmed_dashboard_receipt`
- Dashboard-confirmed credits: **not observed** (no billing headers on responses)
- Birdeye: **0**
- setup-pilot: unchanged (0 used)

## Losses / unsupported / unknown (preserved)
- Live GTA pages returned full txs (100/page) for all five wallets
- Current `spot-v7-native-flow-roles` decoder: **0 decoded_swaps / 0 supported_transactions** on merged pages
- Dominant gaps: unreviewed program/discriminator, transfers-without-reviewed-outer-swap, wallet absent from account keys, unsupported tx version
- No invented episodes; smaller/visible reports also 0 because no closed supported pairs

## Evidence paths
- `/workspace/g3-ranked100-live-results/` (PREFLIGHT, OPERATOR_REPORT, G3_RANKED100_LIVE_SUMMARY, TRANSPORT_META, CREDITS_LEDGER, DECODER_COVERAGE, FROZEN_CANDIDATES, armed grant LOCAL-ONLY, data/scanner.sqlite cache+ledgers)
- `/workspace/g3-ranked100-live-results/evidence/G3_RESULT.json` + `INDEX.json`
- Repo HEAD: `c3a3ffe5d910823f1113ea5b4f8912c3cf47dfce` on `cursor/mass-wallet-funnel-v1-1055`

## Errors
None (no auth/entitlement/quota/rate-limit/schema/accounting failures). All 10 HTTP 200.

## PRODUCT_READY
false. Not full G2. Not MATCH. Winners not required.
