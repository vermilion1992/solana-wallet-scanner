# Mass Wallet Search — honest proof brief

Shape: `work_packages/mass_wallet_search_v1/docs/08_DELIVERY_TEMPLATE.md`.
Priority: prove the general idea works. Not empty-state polish, not merge, not PRODUCT_READY.

**Synthetic offline is not real-trader proof.** The screenshots and the 0.575 SOL worksheet below are the package dust-tail fixture labeled SYNTHETIC. They show the funnel software can carry a candidate through supported buys/sells to subset P&L, median hold, exclusions, and a shortlist. They do not show that a real Solana trader was discovered, reconstructed, or profitable.

## Actual outcome
Mitch can run the local Search funnel offline today: fixture acquire → frozen universe → triage shortlist → reconstruct a supported buy+sell subset → independent worksheet (0.575 SOL realised, t90 30 s, final hold 48 h / 172800 s) → Results / Compare / Research screen / shortlist, all labeled reconstructed subset / UNRESOLVED / not a wallet-wide MATCH. G0 software and G4 local 10k refilter are PASS. G1 genuine vertical slice is BLOCKED: `evidence/runs/real-cache` holds 63 real native archives for one live wallet, but those archives have 0 closed positions, unknown profit, and no reviewed swap decoder — there is no honest genuine-replay input. Live G1–G3/G5 stay BLOCKED until a real `live-research-authorization-v1` exists. The file `config/live_authorization.proof-grant-draft.json` is prepared and **disabled**; it is not a grant. Example JSON is not a grant. No live providers were called. Setup-pilot was not reset. No profitable wallets were invented.

## Source and changes
- Repository: `vermilion1992/solana-wallet-scanner`
- Branch: `cursor/mass-wallet-funnel-v1-1055`
- Base: `codex/screening-forward-research` `fa9f1307b2ee6b8e4d4288b5ee55b0d220404f69`
- Prior tested application SHA: `f7ac05742b9079b2532593698ef3d2a35b89c6b4`
- Proof-brief / hunt / grant-draft SHA: `5d0ff5d3820615f5c324b406facc76270dd3e277`
- Follow-up PR: https://github.com/vermilion1992/solana-wallet-scanner/pull/4 — draft vs `codex/screening-forward-research`; not merged, not deployed

Changed files this turn:
- `evidence/mass-wallet-funnel/PROOF_BRIEF.md` — this brief
- `evidence/mass-wallet-funnel/GENUINE_REPLAY_HUNT.json` — hunt facts
- `config/live_authorization.proof-grant-draft.json` — disabled named grant draft
- `tests/test_mass_search_funnel.py` — draft is not a grant
- `ISSUES.md`, `evidence/mass-wallet-funnel/INDEX.json`, `evidence/mass-wallet-funnel/DELIVERY.md` — register the hunt and priority

## Gate matrix
| Gate | State | Evidence | Remaining dependency |
|---|---|---|---|
| G0 Baseline/safety/software | PASS | Offline staged funnel, strict-v0.3 unchanged, caps 20/5 retained, Search→Results→Compare→Research→shortlist synthetic loop | None for offline software |
| G1 Genuine vertical slice | BLOCKED | Hunt: real-cache exists but 0 closed / no supported buy+sell; genuine-replay NOT_RUN | Real grant **or** archived Birdeye page + archived Helius history with a supported closed buy+sell |
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
Grant draft (disabled): `config/live_authorization.proof-grant-draft.json`
Official G4: `evidence/mass-wallet-funnel/ee7c645a3a7b499bb150b1ac84b96ced/`

Failed / blocked / not-run:
- Genuine-replay G1: NOT_RUN (missing supported buy+sell archives)
- Live G1/G2/G3/G5: BLOCKED (no real grant)
- G6: NOT_RUN
- Live-search receipt profile: exit 2 INCOMPLETE (required)

## Next action
Do not enable the draft file. Do not merge. First live unlock after a real operator `live-research-authorization-v1` (authorization_id, timestamps, remaining-quota confirmation, enabled true): **G1 vertical slice only** — one real acquired candidate → supported buy/sell → report — under Helius ≤20 / ~600 and Birdeye ≤10 / ~250, $0 extra, no overages, no setup-pilot reset. Then G2, then G3.
