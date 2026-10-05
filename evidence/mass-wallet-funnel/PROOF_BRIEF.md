# Mass Wallet Search — honest proof brief

Shape: `work_packages/mass_wallet_search_v1/docs/08_DELIVERY_TEMPLATE.md`.
Priority: prove the general idea works. Not empty-state polish, not merge, not PRODUCT_READY.

**Synthetic offline is not real-trader proof.** The screenshots and the 0.575 SOL worksheet below are the package dust-tail fixture labeled SYNTHETIC. They show the funnel software can carry a candidate through supported buys/sells to subset P&L, median hold, exclusions, and a shortlist. They do not show that a real Solana trader was discovered, reconstructed, or profitable.

## Actual outcome
Mitch approved live G1 only. Named grant `config/live_authorization.g1-granted.json` (`authorization_id` `live-g1-vertical-slice-2026-10-05-mitch`, Birdeye ≤10 / 250 CU, Helius ≤20 / 600 credits, $0 extra, no overages, no setup-pilot reset) is enabled. Keys were present in this box runtime (length-only confirmed; values never printed).

**G1 PASS.** Official `tools/mass_search_g1_live.py` first returned BLOCKED (`no_supported_closed_pair`) after 1 Birdeye page + 5 oldest-50 Helius histories (`b3d5c6a8b1c44d49bdb3c55b27676c71/`). A same-grant follow-up used newest-first Helius history (limit 100) on remaining Birdeye-acquired candidates and found one supported closed buy+sell:

- address: `GatgyE2SqnNNjNeNGR8MG1VSVxFGxgyjB111hYJRTkee`
- mint: `4oPr8EG6qxbYksWt2F3rJ4CqqvpcPrZ4aWg4ByDJpump`
- events: 4 buys + 1 sell (PumpSwap / reviewed decoder)
- independent subset realised P&L: **-0.167725526 SOL** (loss; still a valid closed pair)
- episode hold (first buy → sale): **598 s**
- policy: UNRESOLVED / not wallet-wide MATCH
- evidence: `evidence/mass-wallet-funnel/1bffe2ac21854424aa3fe3b8bf6a22ae/` (PRE_RUN_FREEZE, G1_RESULT, WORKSHEET, REPORT, raw Helius archive)

Spend used: Birdeye **25 / 250 CU** (1 call); Helius **130 / 600 credits** (13 GTA @ 10 credits floor each); setup-pilot **0 / 200 untouched**. No overages. No G2/G3/G5/G6. No invented wallets. No merge. No secrets in evidence.

## Source and changes
- Repository: `vermilion1992/solana-wallet-scanner`
- Branch: `cursor/mass-wallet-funnel-v1-1055`
- Application SHA at run: `462cfa4843f3e288554380046aec09533c306fbd`
- Official blocked attempt: `b3d5c6a8b1c44d49bdb3c55b27676c71`
- Completed G1 PASS: `1bffe2ac21854424aa3fe3b8bf6a22ae`
- Follow-up PR: https://github.com/vermilion1992/solana-wallet-scanner/pull/4 — draft; not merged

## Gate matrix
| Gate | State | Evidence | Remaining dependency |
|---|---|---|---|
| G0 Baseline/safety/software | PASS | Offline staged funnel, strict-v0.3 unchanged, caps 20/5 retained | None for offline software |
| G1 Genuine vertical slice | **PASS** | Live grant + real Birdeye acquire + Helius history → supported closed buy+sell on `GatgyE2SqnNNjNeNGR8MG1VSVxFGxgyjB111hYJRTkee`; worksheet `1bffe2ac21854424aa3fe3b8bf6a22ae/WORKSHEET.json`; spend 25/250 CU and 130/600 credits; setup-pilot untouched | None for G1. Real-specimen UI screenshots optional / not taken this pass |
| G2 Genuine 1,000-candidate search | BLOCKED | Not in this grant | Separate authorization after G1 |
| G3 Three genuine reconciled analytics reports | BLOCKED | One genuine subset report only | After G2 |
| G4 Local 10,000-row performance | PASS | Official 5/20 p95 309.18 ms, receipt `ee7c645a3a7b499bb150b1ac84b96ced/` | None |
| G5 Genuine forward operation | BLOCKED | Out of grant | Authorized delayed quotes after frozen genuine cohort |
| G6 Prospective financial research | NOT_RUN | Out of grant | After G5 |
| Legacy full-wallet acceptance | UNCHANGED / false | B1 NO_GO_CURRENT_SOURCE; PRODUCT_READY not relabelled | Existing R1/B2/B3 contract |

Independent outcomes: `MASS_SEARCH_SOFTWARE` = implemented offline. `REAL_SEARCH_BENCHMARK` = not demonstrated (G1 only, not 1,000). `REAL_ANALYTICS_DEMONSTRATED` = **partial** — one genuine closed-pair subset worksheet, not three reconciled reports. `FORWARD_OPERATION_DEMONSTRATED` = not demonstrated. `RESEARCH_OUTCOME` = not demonstrated. `PRODUCT_READY` = false.

## Search result
**Lane actually run: GENUINE_LIVE (G1).** Plus retained SYNTHETIC offline loop.

Genuine G1 survivor: `GatgyE2SqnNNjNeNGR8MG1VSVxFGxgyjB111hYJRTkee` / mint `4oPr8EG6qxbYksWt2F3rJ4CqqvpcPrZ4aWg4ByDJpump` / subset P&L -0.167725526 SOL / hold 598 s / UNRESOLVED. Not a profitable-wallet claim. Not MATCH.

Synthetic vertical slice (fixture) remains documented below for software proof only.

## Performance and cost
- Live G1: Birdeye 1× gainers-losers (25 CU); Helius 13× getTransactionsForAddress (130 credits at 10/call floor); wall under 1 minute across official + follow-up; $0 extra; setup-pilot not reset
- Synthetic 1,000-unique acquire / G4: unchanged from prior receipts

## Validation and evidence
Genuine G1:
1. Freeze + grant: `1bffe2ac21854424aa3fe3b8bf6a22ae/PRE_RUN_FREEZE.json`
2. Result PASS: `1bffe2ac21854424aa3fe3b8bf6a22ae/G1_RESULT.json`
3. Independent worksheet: `1bffe2ac21854424aa3fe3b8bf6a22ae/WORKSHEET.json`
4. Report snapshot: `1bffe2ac21854424aa3fe3b8bf6a22ae/REPORT.json`
5. Raw Helius archive (redacted of secrets by construction — API key only in query string, not response body): `1bffe2ac21854424aa3fe3b8bf6a22ae/archives/helius_gta_survivor_desc100.json.gz`

Synthetic idea sequence (unchanged): `ui-offline-browser/` screenshots with 0.575 SOL fixture.

## Next action
Do not merge solely on G1 or this ranked-100 pilot. Do not start full G2 (1,000 wallets) from this evidence.

**RANKED_100_DISCOVERY_PILOT PASS** on a separate secure box (not this VM). Grant `live-g2-ranked100-discovery-2026-10-05-mitch`. Exact Birdeye `GET /trader/gainers-losers` solana `type=30d` `sort_by=trader_score` `sort_type=desc` `offset=0` `limit=100`. 100 raw / 100 unique; shortlist 20 (not padded); 80 below ceiling. Spend: Birdeye 1 request, documented estimate 30 CU (no CU billing headers; ratelimit 100/99); Helius 0; setup-pilot untouched; $0 extra. `last_active` unknown on all rows. `evidence_sha256` `03869fe91b21e0c3e7425a278989eddc58e3f3267b047add2cf8f86ab52ac9f4`. Receipt `ranked100-discovery-pilot-2026-10-05/`. Notes: `RANKED_100_DISCOVERY_PILOT.md`.

Repo ranked-100 grant template stays `enabled: false` (ceiling amended 25→30 CU to match current Birdeye docs). No keys on this VM. PRODUCT_READY stays false.

Mitch separately approved `live-g3-ranked100-history-2026-10-06-mitch` (2026-10-05T14:19:00Z). This cloud run is **G3 offline prep only**: grant file stays `enabled: false`, freeze of shortlist ranks 1/3/5 + reserves 6/7, no live Helius. Notes: `G3_RANKED100_HISTORY.md`. Live still blocked until Helius pricing/entitlement/remaining quota are confirmed on the box — a present key or the G1 pass is not enough.
