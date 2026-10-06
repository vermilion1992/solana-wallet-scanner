# Product-completion-v2 release checklist

Authoritative file (replaces `COMPLETION_CHECKLIST.md`). Columns: requirement | status | evidence | remaining action.

Statuses are only PASS / FAIL / BLOCKED / NOT RUN. BLOCKED and NOT RUN are never passes.

Frozen app SHA: `c34eb2cec41bdbb3a2ef6d7c349d20d01db635bc`.
Harness-only follow-up: `50cc6e29fa0069e62e522236865755f73adbeb18`.
Frontend asset: `frontend/dist/assets/index-hN-S6YfT.js`.
Build identity: scanner v0.3.11 / `/api/health` version 0.3.11.
`PRODUCT_READY` is false because the mandatory gate **genuine ranked multi-wallet path** is BLOCKED (existing B3). B1 remains `NO_GO_CURRENT_SOURCE`; B2 remains `OPEN`.

Accepted accounting (not re-audited): rank-1 one matched `5tCju6YN` sell
3376.028087−3000=+376.028087 USDC; SOL fee 0.00032333 not deducted; 852s n=1;
six trades are not six positions. G1 −0.167725526 SOL.

## 1. Correctness fixes A–D

| requirement | status | evidence | remaining action |
| --- | --- | --- | --- |
| A. Batch race — atomic HTTP admission, 409/busy or identical attach, cancel releases only after work stops, single-process guard, independent of acquisition | PASS | `DEFECT_A.json`; `logs/PYTEST_AD.log`; `tests/test_mass_search_mitch_requirements.py::test_http_batch_admission_is_atomic_and_returns_409`; `::test_identical_create_and_run_attaches_without_rerunning`; `::test_concurrent_http_step_does_not_double_analyse` | none |
| B. `visible_report` exact persist (True/False); absent is unknown, never silent True | PASS | `DEFECT_B.json`; `logs/PYTEST_AD.log`; `::test_visible_report_true_and_false_survive_http_reopen`; `::test_absent_visible_report_never_defaults_true` | none |
| C. Partly backed sells — FIFO matched + unknown-basis remainder; fee-free 6@36 / sell 10@100 = +24 / 40 / 100; app = independent tool; labelled conditional on captured inventory | PASS | `DEFECT_C.json`; `INDEPENDENT_RECON_FEEFREE.json`; `logs/PYTEST_AD.log`; `::test_fee_free_partial_match_is_fully_accounted` | none |
| D. Compare windows — same-window control, different included trades, partial/non-overlap; own windows shown, mismatch blocks; cache key includes window | PASS | `DEFECT_D.json`; `logs/PYTEST_AD.log`; `::test_compare_same_window_control_and_differing_included_trades`; `::test_compare_partial_overlap_one_corpus_keeps_own_windows`; `::test_cache_key_includes_window` | none |

## 2. User workflow

| requirement | status | evidence | remaining action |
| --- | --- | --- | --- |
| Clean `./run.sh` journey on a fresh data dir: open, authenticate, browse 100, edit filters, shortlist, analyse, inspect trades/positions, compare, save, export, 390×844 emulation | PASS | `CLEAN_LAUNCH.json`; `logs/LOOPBACK_LAUNCHER.log`; `ui/v5_phone_ranked100_cards.png`; `ui/v5_phone_genuine_usdc_report.png`; `ui/v5_phone_compare_mismatches.png` | none |
| Same journey after process restart on the existing data dir | PASS | `CLEAN_LAUNCH.json` case `existing_dir_restart_reopen_export`; `ui/v5_phone_ah_report.png` | none |
| A–H real-app phone checks at 390×844 (Playwright Chromium emulation) | PASS | `phone-ah-result.json`; `VALIDATION.json` | none |

## 3. Genuine-data ingestion / analysis

| requirement | status | evidence | remaining action |
| --- | --- | --- | --- |
| Rank-1 page-0 genuine capture reconstructs through the real batch; +376.028087 USDC; G1 control −0.167725526 SOL | PASS | `INDEPENDENT_RECON_RANK1.json`; `INDEPENDENT_RECON_G1.json`; `CAPTURE_PROVENANCE.json`; `HEADLINE_376.md` | none |
| Genuine ranked multi-wallet path — ≥2 distinct ranked-snapshot wallets with genuine captures through the real batch | **BLOCKED** | only rank-1 page-0 sha256 `53a5c6f4…`; G1 and synthetics do not count; `DISPOSITION_100.json` | capture a second ranked wallet through the real batch (external) |

## 4. Wallet qualification and ranking

| requirement | status | evidence | remaining action |
| --- | --- | --- | --- |
| Evidence classes 1–5; qualification categories mapped onto those states; screening pass/fail kept separate | PASS | `RESEARCH_RUN.json`; `scanner/mass_search/research_profile.py` `QUALIFICATION_CATEGORY`; `::test_research_screen_is_inconclusive_for_99_without_history` | none |
| Defaults fixed before evaluation: `min_completed_known_cost=1`, `min_sample_positions=3`; unknown never passes | PASS | `RESEARCH_RUN.json`; A–H / clean-launch research-screen text | none |
| Today's snapshot run: 99 inconclusive / not evaluated; rank-1 zero-qualified / analysed-incomplete; search not executed | PASS | `RESEARCH_RUN.json` `search_ran=not_executed`; `DISPOSITION_100.json` | none |
| Investigated wallets preserved including losses and inconclusive rows | PASS | batch outcomes keep `history_required` / `incomplete_evidence` / analysed; 100 disposition rows | none |

## 5. Persistence / auth / access

| requirement | status | evidence | remaining action |
| --- | --- | --- | --- |
| Token protects all `/api` data and action routes (80 routes 401) | PASS | `TOKEN_ROUTES.json` | none |
| LAN-only usable access: `./run.sh --lan --no-browser`; unauthenticated 401 | PASS | `lan-result.json`; `CLEAN_LAUNCH.json` case `lan_existing_dir`; `ui/v5_phone_lan_client.png` | none |
| Remote access away from the operator LAN | **BLOCKED** | `docs/REMOTE_PREVIEW_PROPOSAL.md` (proposal only, not deployed) | written approval of a remote host (external) |
| Save / serialize / reopen / restart preserves `visible_report` and reports | PASS | `DEFECT_B.json`; clean-launch existing-dir reopen | none |

## 6. Final build and verification

| requirement | status | evidence | remaining action |
| --- | --- | --- | --- |
| Full backend suite at frozen SHA | PASS | `logs/PYTEST_FULL.log`; 3607 passed / 0 failed | none |
| Frontend production build | PASS | `frontend/dist/assets/index-hN-S6YfT.js` sha256 `462fc01d…` | none |
| Clean launch + A–H + LAN + token enumerator at that SHA | PASS | `VALIDATION.json`; `CLEAN_LAUNCH.json`; `phone-ah-result.json`; `TOKEN_ROUTES.json` | none |
| Acquisition 0/0/$0; both drafts disabled | PASS | `ACQUISITION_RECORD.json`; `RESEARCH_SEARCH_PROPOSAL.json` | none |

## 7. Handover and PR state

| requirement | status | evidence | remaining action |
| --- | --- | --- | --- |
| Operating doc: start/open, stop/restart, data dir, preserve across update, research/acquire controls | PASS | `docs/OPERATING.md` (tested: Linux `./run.sh` and `./run.sh --lan --no-browser`) | none |
| PR #4 ready for review; not merged; PRODUCT_READY false | PASS | https://github.com/vermilion1992/solana-wallet-scanner/pull/4 | none (do not merge) |

## Backlog (optional)

| item | status | note |
| --- | --- | --- |
| Integer-base-unit quantization display for every split amount | NOT RUN | Fee-free and accepted genuine totals are already integer/canonical; not a release gate |
| Physical-phone certification on operator hardware | NOT RUN | 390×844 is labelled Playwright emulation |
| Second genuine ranked capture through the real batch | BLOCKED | Same external dependency as §3 |

## External dependencies (not passes)

1. Written approval of a draft grant **and** confirmed Helius credits before any live history.
2. Written approval if a remote host is wanted — **not deployed**.
