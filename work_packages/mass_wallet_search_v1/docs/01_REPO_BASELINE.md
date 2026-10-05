# Inspected baseline and integration map

## Repository facts, not new acceptance
Inspected on 5 October 2026 through the connected private GitHub repository:
- Repository: `vermilion1992/solana-wallet-scanner`.
- PR #1: open, unmerged; source branch `codex/screening-forward-research`; target `codex/product-completion`.
- Published head: `fa9f1307b2ee6b8e4d4288b5ee55b0d220404f69`.
- PR description identifies the frozen application `94dcbba81b498cfa44f883408618a23654658bc3` and reports 645 affected backend nodes, 49 subtests and synthetic-transport browser validation. These are repository-recorded results, not checks rerun for this package.
- The recorded live workflow demonstrated an acknowledged subscription but zero live signals/quotes. The current sampled milestone does not require a profitable candidate.
- Full historical B1/B2/B3 and PRODUCT_READY remain separate and unresolved in the stated ways. Preserve historical evidence and acceptance flags.

## Existing modules to inspect and reuse
| Area | Existing paths | Direction |
|---|---|---|
| Discovery / imports | `scanner/discovery.py`, `scanner/candidate_import.py`, `frontend/src/Discovery.tsx`, `frontend/src/SelectedCohorts.tsx` | Add a bulk universe without pretending the old sampler is a leaderboard. Preserve original cohorts. |
| Settings / budgets | `scanner/config.py`, `scanner/providers.py`, `scanner/storage.py` | Keep quotas, backend-only keys, durable reservations, time/cycle controls and offline guards. |
| Targeted collection | `scanner/investigation.py`, `scanner/collector.py`, `scanner/indexed_input.py` | Adapt usable provider history to existing evidence/report contracts; no second accounting truth. |
| Financial / timing derivation | `scanner/accounting.py`, `scanner/research.py`, `scanner/copy_review.py` and evidence modules | Reuse FIFO, conditional observations, fee separation and 90%-exit analysis. |
| Screening / APIs | `scanner/screening.py`, `scanner/screening_routes.py`, `scanner/app.py` | Add immutable stages and API views. Do not turn worth-observing into verified profit. |
| Forward observation | `scanner/observer.py`, `scanner/paper.py`, `frontend/src/Research.tsx` | Reuse signal timestamps, quote-only simulation, cash, gaps, frozen settings and restart logic. |
| Reports / archives | `scanner/report_rebuild.py`, `scanner/report_view.py`, `frontend/src/report.tsx` | Rebuild children; retain parents, source references and metric-specific uncertainties. |
| Validation | `tools/validate.py`, `ACCEPTANCE.md`, existing test modules | Extend current gates and disjoint focused groups; don't double-count test nodes. |

Confirm paths and interfaces in the live checkout; this map is not a substitute for reading code.

## Important cap conflict to resolve explicitly
At the inspected head, `scanner/config.py` contains `candidate_cap=20`, `deep_audit_cap=5` and a validator that prevents raising legacy free-mode caps. `Store.list(kind)` materialises every matching JSON record. Blindly increasing the cap or loading every detailed report into the browser is not the mass-search design.

Add a distinct local **bulk-universe storage/display capacity** and a separate staged workload policy. A capacity of 10,000 lightweight candidate rows authorises no provider calls and no deeper audits. Continue to enforce existing provider-credit ceilings and authorised deep-work concurrency. Raise neither the original credit caps nor an exhausted ledger to make a benchmark run.

## Exact strict preset
`config/strict_preset.snapshot.json` is transcribed from the inspected `scanner/config.py` constant, including average buy/sell bounds. Codex must compare this snapshot with the selected checkout and preserve the named preset. A later legitimate change must be identified, not overwritten blindly.

## Source references
Private paths are pinned to the reference commit in `sources/source_registry.json`. Public API facts are separately dated. No private source code, credentials or user database is included in this package.
