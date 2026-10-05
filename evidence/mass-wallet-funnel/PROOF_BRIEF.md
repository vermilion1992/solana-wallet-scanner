# Mass Wallet Search — honest proof brief

Shape: `work_packages/mass_wallet_search_v1/docs/08_DELIVERY_TEMPLATE.md`.
Priority: prove the general idea works. Not empty-state polish, not merge, not PRODUCT_READY.

**Synthetic offline is not real-trader proof.** The screenshots and the 0.575 SOL worksheet below are the package dust-tail fixture labeled SYNTHETIC. They show the funnel software can carry a candidate through supported buys/sells to subset P&L, median hold, exclusions, and a shortlist. They do not show that a real Solana trader was discovered, reconstructed, or profitable.

## Actual outcome
Mitch approved live G1 only. A real named grant is now enabled at `config/live_authorization.g1-granted.json` (`authorization_id` `live-g1-vertical-slice-2026-10-05-mitch`, Birdeye ≤10 / 250 CU, Helius ≤20 / 600 credits, $0 extra, no overages, no setup-pilot reset). The example file and the proof-grant draft stay disabled. The G1 runner froze that grant, then **stopped before any provider HTTP** because this runtime has no `BIRDEYE_API_KEY` and no `HELIUS_API_KEY`. Spend used is 0 / 250 CU and 0 / 600 credits. Setup-pilot is untouched (0 used / 200). G1 is BLOCKED on those missing credentials — not on the grant. No real candidate was acquired, no profitable wallet was invented, G2/G3/G5/G6 were not run, and nothing was merged. The offline SYNTHETIC 0.575 SOL loop still shows the idea; it is not real-trader proof.

## Source and changes
- Repository: `vermilion1992/solana-wallet-scanner`
- Branch: `cursor/mass-wallet-funnel-v1-1055`
- Base: `codex/screening-forward-research` `fa9f1307b2ee6b8e4d4288b5ee55b0d220404f69`
- Prior tested application SHA: `f7ac05742b9079b2532593698ef3d2a35b89c6b4`
- G1 grant + runner SHA: `0a6b5b1159cb9caea1a1512b2f1bd259eea370aa`
- Official G1 attempt: `138e499f181844a7bf867a3b6748c070`
- Follow-up PR: https://github.com/vermilion1992/solana-wallet-scanner/pull/4 — draft vs `codex/screening-forward-research`; not merged, not deployed

Changed files this turn:
- `config/live_authorization.g1-granted.json` — enabled named G1 grant
- `scanner/mass_search/live_g1.py`, `tools/mass_search_g1_live.py` — G1-only runner
- `tests/test_mass_search_g1.py`, `tools/validate.py`, `tests/test_validation_gates.py` — grant/oracle/blocker coverage
- `evidence/mass-wallet-funnel/138e499f181844a7bf867a3b6748c070/` — freeze + G1 BLOCKED receipt
- this brief, `ISSUES.md`, `INDEX.json`

## Gate matrix
| Gate | State | Evidence | Remaining dependency |
|---|---|---|---|
| G0 Baseline/safety/software | PASS | Offline staged funnel, strict-v0.3 unchanged, caps 20/5 retained, Search→Results→Compare→Research→shortlist synthetic loop | None for offline software |
| G1 Genuine vertical slice | BLOCKED | Grant enabled; freeze `138e499f181844a7bf867a3b6748c070/PRE_RUN_FREEZE.json`; live stopped with `missing_provider_credentials`; spend 0/250 CU and 0/600 credits; no specimen screenshots | `BIRDEYE_API_KEY` and `HELIUS_API_KEY` present in the runtime that runs G1 |
| G2 Genuine 1,000-candidate search | BLOCKED | Synthetic 1,000 unique acquire 0.1508 s, 0 external; not REAL_SEARCH_BENCHMARK | After G1: Birdeye ≤10 calls / ~250 CU, remaining quota confirmed |
| G3 Three genuine reconciled analytics reports | BLOCKED | One SYNTHETIC report only | After G2: Helius ≤20 calls / ~600 credits on survivors; ≥3 reports, ≥10 episodes, include losing/unresolved control |
| G4 Local 10,000-row performance | PASS | Official 5/20 p95 309.18 ms, 0 external, receipt `ee7c645a3a7b499bb150b1ac84b96ced/` | None for the local synthetic SLA |
| G5 Genuine forward operation | BLOCKED | Quote-only helpers exist; no genuine signals | Authorized delayed quotes after a frozen genuine cohort |
| G6 Prospective financial research | NOT_RUN | Arms can be frozen; no observation started | 14-day authorized quote budget after G5 |
| Legacy full-wallet acceptance | UNCHANGED / false | B1 NO_GO_CURRENT_SOURCE; PRODUCT_READY not relabelled | Existing R1/B2/B3 contract |

Independent outcomes: `MASS_SEARCH_SOFTWARE` = implemented offline. `REAL_SEARCH_BENCHMARK` = not demonstrated. `REAL_ANALYTICS_DEMONSTRATED` = not demonstrated. `FORWARD_OPERATION_DEMONSTRATED` = not demonstrated. `RESEARCH_OUTCOME` = not demonstrated. `PRODUCT_READY` = false.

## Search result
**Lane actually run: SYNTHETIC (labeled).** Genuine-replay was not run.

Synthetic vertical slice (1 fixture address): reconstructed through `accounting.analyze` / `research.summarize_research` plus independent FIFO/material-exit worksheet. Subset realised P&L 0.575 SOL; t90 30 s; final hold 172800 s. Corpus `SYNTHETIC`. Policy UNRESOLVED. Not a MATCH. No profitable-wallet claim.

Synthetic 1,000-unique acquire: fixture-traders, 0.1508 s, 0 provider calls, triage 200 promoted / 800 deferred. Cannot be counted as REAL_SEARCH_BENCHMARK.

Official G4 parent (`ee7c645a3a7b499bb150b1ac84b96ced`): 10,000 unique fixture rows, triage 200 promoted / 9800 deferred (stage cap). Candidate discovery and queue ranking, not completed wallet reconstruction.

**Genuine-replay hunt (preferred $0 path): archives found, unusable.**
- Path: `evidence/runs/real-cache` (gitignore exception; 63 gzip archives + `manifest.json.gz` SHA-256 `6353860af1eba9d5270e5416f6c5a93004b132a47694b026dd59d7bce12c7bec`)
- One reconstructed live wallet: `2QfBNK2WDwSLoUQRb1zAnp3KM12N9hQ8q6ApwUMnWW2T`
- 23 collected txs on that wallet; scan lists 5 addresses / 94 selected records historically; collection paused on free credit cap
- Archive methods: `getSignaturesForAddress` (34), transaction records (23), token/account/slot/balance — **0** Birdeye `gainers-losers` pages, **0** `getTransactionsForAddress` pages, **0** normalized buy/sell events
- Counts closed/open/interrupted/unresolved all 0; `profit_sol` unknown; `known_realised_profit_sol` −0.000240394 (fees only)
- Findings: “No reviewed decoder for this instruction/program; balance deltas do not prove a swap”
- Missing artifact: archived Birdeye trader pages **plus** archived Helius history that the current reviewed decoder can turn into at least one supported closed buy+sell
- Decoder-test goldens under `evidence/genuine-wallet-batch/` were not used: they are labeled development/synthetic-anchor diagnostics, not a discovered-candidate native corpus

## Performance and cost
- Synthetic 1,000-unique acquire: 0.1508 s wall, 0 external requests, $0
- Official local 10k refilter+page: median 287.97 ms; p95 309.18 ms; max 312.42 ms; 0 external; peak RSS 83300 KB
- Genuine-replay: not run (no usable archives)
- Live: not run. Paid spend $0. No units reserved. Setup-pilot not reset.

## Validation and evidence
Idea-working sequence — **SYNTHETIC, not genuine-replay:**

1. Search populated: `evidence/mass-wallet-funnel/ui-offline-browser/02-populated-slice-desktop.png`
2. Results subset P&L 0.575 SOL: `evidence/mass-wallet-funnel/ui-offline-browser/06-results-subset-pnl-desktop.png`
3. Compare reconstructed subset: `evidence/mass-wallet-funnel/ui-offline-browser/07-compare-subset-pnl-desktop.png`
4. Research worksheet / screen (insufficient evidence, not MATCH): `evidence/mass-wallet-funnel/ui-offline-browser/09-research-screen-subset-desktop.png`
5. Shortlist (Unresolved / reconstructed subset / 0.575 SOL / not MATCH): `evidence/mass-wallet-funnel/ui-offline-browser/11-watchlist-shortlist-subset-desktop.png`

Hunt receipt: `evidence/mass-wallet-funnel/GENUINE_REPLAY_HUNT.json`
Enabled grant: `config/live_authorization.g1-granted.json` (`live-g1-vertical-slice-2026-10-05-mitch`)
Draft (still not a grant): `config/live_authorization.proof-grant-draft.json`
Official G1 attempt: `evidence/mass-wallet-funnel/138e499f181844a7bf867a3b6748c070/`
Official G4: `evidence/mass-wallet-funnel/ee7c645a3a7b499bb150b1ac84b96ced/`

Failed / blocked / not-run:
- Live G1: BLOCKED (`missing_provider_credentials`); 0 provider HTTP
- Genuine-replay G1: still no usable archives
- G2/G3/G5: not run (out of this grant)
- G6: NOT_RUN
- Real-specimen Search/Results/Research screenshots: not taken (no acquired candidate)

## Next action
Do not merge. Do not start G2. Re-run `tools/mass_search_g1_live.py` in a runtime that already has `BIRDEYE_API_KEY` and `HELIUS_API_KEY`, under the same grant ceilings. That is the only remaining G1 unlock.
