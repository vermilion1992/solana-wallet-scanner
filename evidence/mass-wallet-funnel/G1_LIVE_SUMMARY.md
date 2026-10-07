# G1 live vertical slice — PASS

**Gate:** G1 PASS  
**Grant:** `live-g1-vertical-slice-2026-10-05-mitch`  
**When (Adelaide / ACST):** 2026-10-05 ~22:11–22:13  

## Spend vs ceilings
| Provider | Used | Ceiling | Notes |
|---|---|---|---|
| Birdeye | 25 CU (1 call) | 250 CU / 10 calls | trader gainers-losers page |
| Helius | 130 credits (13 GTA) | 600 credits / 20 calls | 10-credit floor each ≤100 full txs |
| setup-pilot | 0 | 200 | untouched; not reset |

$0 extra. No overages. Credentials confirmed by non-empty length only (never printed).

## Candidate
- **Address:** `GatgyE2SqnNNjNeNGR8MG1VSVxFGxgyjB111hYJRTkee`
- **Mint:** `4oPr8EG6qxbYksWt2F3rJ4CqqvpcPrZ4aWg4ByDJpump`
- **Supported closed buy+sell:** yes (4 buys + 1 sell)
- **Independent subset P&L:** −0.167725526 SOL
- **Episode hold:** 598 s (first buy → sale)
- **Policy:** UNRESOLVED (not wallet-wide MATCH)

## Path
1. Official `tools/mass_search_g1_live.py` → BLOCKED `no_supported_closed_pair` on first 5 candidates (oldest-50) — receipt `b3d5c6a8b1c44d49bdb3c55b27676c71`.
2. Same-grant follow-up: newest-first Helius history on remaining Birdeye-acquired candidates → survivor found.
3. Evidence package: `1bffe2ac21854424aa3fe3b8bf6a22ae/` (also mirrored here).

## Evidence (this package)
- `1bffe2ac21854424aa3fe3b8bf6a22ae/G1_RESULT.json`
- `1bffe2ac21854424aa3fe3b8bf6a22ae/PRE_RUN_FREEZE.json`
- `1bffe2ac21854424aa3fe3b8bf6a22ae/WORKSHEET.json`
- `1bffe2ac21854424aa3fe3b8bf6a22ae/REPORT.json`
- `1bffe2ac21854424aa3fe3b8bf6a22ae/archives/helius_gta_survivor_desc100.json.gz`
- `PROOF_BRIEF.md`, `FUNNEL_INDEX.json`

## Push status
`gh` is **not** authenticated on this box as vermilion1992. Results left here for handoff to the cloud agent. Suggested handoff: copy `/workspace/g1-live-results/` plus repo path `evidence/mass-wallet-funnel/{1bffe2ac…,PROOF_BRIEF.md,INDEX.json}` and `ISSUES.md` onto PR branch `cursor/mass-wallet-funnel-v1-1055` (PR #4) — evidence/docs only, no `.env` / keys.

## Not done
G2/G3/G5/G6 not run. No merge. No invented wallets. No real-specimen UI screenshots this pass.
