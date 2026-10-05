# Codex final handoff template

## Actual outcome
A local Search funnel now runs offline from an authorised-or-fixture candidate source through a frozen universe, cheap triage, targeted reconstruction, subset P&L / median hold / material-exit worksheet, and a saved export. One synthetic source-to-report slice and a 1,000-unique fixture acquire work. The official local 10,000-row refilter (5 warmup / 20 measured, normal SQLite store) met the 500 ms p95 target. Live Birdeye acquisition, genuine multi-wallet analytics, and forward observation remain blocked: there is no enabled `live-research-authorization-v1`, and `config/live_authorization.example.json` is not a grant.

## Source and changes
- Repository: `vermilion1992/solana-wallet-scanner`
- Branch: `cursor/mass-wallet-funnel-v1-1055` (reversible; named for the cloud agent policy; equivalent intent to `codex/mass-wallet-funnel-v1`)
- Base: `codex/screening-forward-research` `fa9f1307b2ee6b8e4d4288b5ee55b0d220404f69` (open PR #1 left unmerged)
- Tested application SHA: `559b45c74182c29892521e18308b9154ea02ac0e`
- Source SHA-256 at that commit: `2c4d31f940a8ab21cd5e2e7dd2d255664d5e0582d56c3ecc80bd0d2e10249757`
- Lock SHA-256: see `ee7c645a3a7b499bb150b1ac84b96ced/source_manifest.json`
- Published SHA: same branch tip after this evidence commit (application files unchanged except issue/delivery notes)
- Draft PR: https://github.com/vermilion1992/solana-wallet-scanner/pull/2 — not merged, not deployed

Changed application files (purpose):
- `scanner/mass_search/*` — additive funnel: schema, plan, adapters, metrics, triage, universe, service, routes, quote-only forward helpers
- `scanner/app.py`, `scanner/storage.py`, `pyproject.toml` — install routes, ensure schema, package the module
- `frontend/src/MassSearch.tsx`, `App.tsx`, `types.ts`, `styles.css`, `scripts/check-discovery.mjs` — Search view and discovery assertions
- `tests/test_mass_search_*.py`, `tests/test_validation_gates.py`, `tools/validate.py` — focused/screening-forward selectors
- `CODEX_TASK.md`, `ISSUES.md` — prepended assignment and MS-* register; historical sections retained
- `work_packages/mass_wallet_search_v1/` — unpacked package (repository AGENTS.md / CODEX_TASK.md / acceptance history not overwritten by the zip)

## Gate matrix
| Gate | State | Evidence | Remaining dependency |
|---|---|---|---|
| G0 Baseline/safety/software | PASS (software) | Strict `strict-v0.3` unchanged; caps 20/5 retained; 10k local capacity separate; 31 mass-search tests; 249 app/storage/gates/funnel tests; frontend `check:discovery` and `npm run build`; receipt development profile CONTRACT_VALID | None for offline software |
| G1 Genuine vertical slice | BLOCKED | Synthetic slice persists FIFO worksheet `total_profit_sol=0.575`, `t90=30s`, final hold `172800s` | Named live-research-authorization-v1 for Birdeye page + Helius targeted history |
| G2 Genuine 1,000-candidate search | BLOCKED | Synthetic 1,000 unique acquire in 0.1508 s, 0 external requests; triage 200 promoted / 800 deferred | Birdeye `GET /trader/gainers-losers`, call ceiling 10, credit ceiling 250 CU, remaining quota confirmed, duration under 5 minutes if entitled |
| G3 Three genuine reconciled analytics reports | BLOCKED | Independent worksheet matches package dust-tail fixture; one synthetic report only | Helius `getTransactionsForAddress`, call ceiling 20, credit ceiling 600, without resetting setup-pilot; three genuine ≥10-episode reports including a loss/unresolved control |
| G4 Local 10,000-row performance | PASS | Official 5/20 on normal store: median 287.97 ms, p95 309.18 ms, max 312.42 ms, 0 external requests, 10,000 unique rows, peak RSS 83300 KB, Linux 6.12.94+ x86_64, Python 3.12.3 | None for the local synthetic SLA |
| G5 Genuine forward operation | BLOCKED | Quote-only fixed-entry/first-sale helpers; no genuine signals | Authorized delayed quotes after a frozen cohort; existing zero-signal subscription is not this gate |
| G6 Prospective financial research | NOT_RUN | Arms can be frozen; no observation started | 14-day authorized quote budget after G5 prerequisites |
| Legacy full-wallet acceptance | UNCHANGED / false | B1 NO_GO_CURRENT_SOURCE; PRODUCT_READY not relabelled | Existing R1/B2/B3 contract |

## Search result
Synthetic 10,000-row G4 parent (`ee7c645a3a7b499bb150b1ac84b96ced`): fixture-traders, SYNTHETIC, report window from the frozen plan, raw 10000 / unique 10000 / duplicate 0 / invalid 0. Triage 10000→200 promoted / 0 rejected / 9800 deferred (stage cap 200). Behaviour 200→0/0/200 (missing material exit). Reconstruct and forward_select input 0. This is candidate discovery and queue ranking, not completed wallet reconstruction.

Synthetic 1,000-unique acquire: same fixture source, 0.1508 s, 0 provider calls, triage 200/0/800/0. Cannot be counted as REAL_SEARCH_BENCHMARK.

Synthetic vertical slice (1 address): reconstructed through `accounting.analyze` / `research.summarize_research` plus independent FIFO/material-exit worksheet. Subset realised P&L 0.575 SOL; t90 30 s; final hold 172800 s. Corpus SYNTHETIC. No profitable-wallet claim. No three-wallet genuine set.

## Performance and cost
- Synthetic 1,000-unique acquire: 0.1508 s wall, 0 external requests, 0 paid spend.
- Official local 10k refilter+50-row page: 5 warmup / 20 measured; median 287.97 ms; p95 309.18 ms; max 312.42 ms; full helper wall 8.78 s including acquire; 0 external requests; peak RSS 83300 KB; hardware Linux-6.12.94+-x86_64, Python 3.12.3.
- Paid spend $0 / limit $0. No live units reserved. Disposable benchmark store started with unused setup-pilot; the unit test still proves an exhausted 200/200 setup-pilot ledger is not reset.
- Cold live seconds: not run.

## Validation and evidence
- `.venv/bin/python -m pytest -q tests/test_mass_search_funnel.py tests/test_mass_search_routes.py tests/test_mass_search_receipt.py tests/test_mass_search_scale.py` → 31 passed
- `.venv/bin/python -m pytest -q tests/test_app.py tests/test_storage.py tests/test_validation_gates.py tests/test_mass_search_funnel.py -k "not execute_main"` → 249 passed
- `frontend` `npm run check:discovery` → exit 0
- `frontend` `npm run build` → exit 0
- Receipt checker development → exit 0 CONTRACT_VALID; live-search → exit 2 INCOMPLETE (required)
- `tools/validate.py` FOCUSED / FOCUSED_GROUPS['screening'] / SCREENING_FORWARD include the four mass-search modules as an exact partition
- Browser launcher / 360px visual pass: not run (no browser automation in this environment). API routes covered by TestClient; UI compiled and discovery assertions passed.
- Independent reconciliation: package dust-tail events, oracle is `fifo_sale_results` / `material_exit_v1` in tests, not a silent call that copies production expectations into the fixture
- Live HTTP, source removal/restoration on genuine pages, and full screening-forward validate profile: not run in this batch
- Failed/blocked/not-run: G1/G2/G3/G5 live paths BLOCKED; G6 NOT_RUN; live-search receipt profile exit 2; full `tools/validate.py --profile screening-forward` not executed end-to-end here

## Next action
Issue one named `live-research-authorization-v1` (not the example file) that confirms, with remaining quota and cycle dates: Birdeye `GET /trader/gainers-losers` (page 100, offset+limit ≤ 10000, ceiling 10 calls / 250 CU, purpose G2 1,000 unique candidates, $0 extra spend) and, separately, Helius `getTransactionsForAddress` for surviving wallets only (ceiling 20 calls / 600 credits, purpose G1/G3 targeted history, do not reset setup-pilot). Offline software continues without that grant.

Independent outcomes: MASS_SEARCH_SOFTWARE = implemented offline. REAL_SEARCH_BENCHMARK, REAL_ANALYTICS_DEMONSTRATED, FORWARD_OPERATION_DEMONSTRATED, RESEARCH_OUTCOME = not demonstrated. Legacy PRODUCT_READY remains false.
