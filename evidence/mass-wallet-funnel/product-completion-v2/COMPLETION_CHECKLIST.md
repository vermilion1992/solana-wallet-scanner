# Product-completion-v2 completion checklist

One file. Columns: requirement | status | evidence | remaining action | external dependency.

Frozen / tested app SHA: `1ab254253900a48ee7858731e04faafd09d1210f`.
Frontend asset: `frontend/dist/assets/index-DkLGyhOf.js`.
`PRODUCT_READY` remains false. Draft grants remain DISABLED.

Accepted accounting (not re-audited): rank-1 one matched `5tCju6YN` sell
3376.028087−3000=+376.028087 USDC; SOL fee 0.00032333 not deducted; 852s n=1;
six trades are not six positions. G1 −0.167725526 SOL.

| requirement | status | evidence | remaining action | external dependency |
| --- | --- | --- | --- | --- |
| A. Batch race — atomic HTTP admission, 409/busy or identical attach, cancel releases only after work stops, single-process guard, independent of acquisition | PASS | `DEFECT_A.json`; `test_http_batch_admission_is_atomic_and_returns_409`; `test_cancel_releases_admission_only_after_executing_stops`; launcher `.runtime.lock` | none | none |
| B. `visible_report` exact persist (True/False); absent is unknown, never silent True | PASS | `DEFECT_B.json`; `scanner/mass_search/visible_report.py`; HTTP save/reopen/restart test; A–H provenance `visible_report true` | none | none |
| C. Partly backed sells — FIFO matched + unknown-basis remainder; fee-free 6@36 / sell 10@100 = +24 / 40 / 100; app = independent tool; labelled conditional on captured inventory | PASS | `DEFECT_C.json`; `INDEPENDENT_RECON_FEEFREE.json`; rank-1 +376.028087 and G1 −0.167725526 unchanged | none | none |
| D. Compare windows — same-window control, different included trades, non-overlap; own windows shown, mismatch blocks; cache key includes window | PASS | `DEFECT_D.json`; window-early/late fixtures; `test_cache_key_includes_window` | none | none |
| Complete app workflow — browse 100, filters, shortlist, batch, report, compare, export, reopen, token, 390×844 A–H | PASS | A–H PASS at `1ab2542`; `VALIDATION.json`; `ACCEPTANCE_CHECKLIST.md` track (a) | none | none |
| Research capability — classes 1–5; assessment fields; screen thresholds fixed first; 99 inconclusive; Acquire history blocks without dispatch | PASS | `RESEARCH_RUN.json`; A–H research-screen + acquire-block; rank-1 zero-qualified n=1 | none for the offline screen | live history for any second ranked wallet |
| Genuine ranked multi-wallet path — ≥2 distinct ranked-snapshot wallets with genuine captures through the real batch | **BLOCKED** | only rank-1 page-0 sha256 `53a5c6f4…`; G1 and synthetics do not count | capture a second ranked wallet through the real batch | written approval of a draft grant **and** confirmed Helius credits |
| Final verification — freeze SHA; full backend; frontend build; A–H + new checks; LAN; token enumerator; HEAD differs only by evidence | PASS | 3604 passed / 0 failed; frontend `index-DkLGyhOf.js`; A–H PASS; LAN PASS; 80 token-protected `/api` routes | none | none |
| Usable access — LAN-only; token on data/action routes; remote deploy proposal only | PASS (LAN-only) | `./run.sh --lan --no-browser`; 172.30.0.2 401 unauth; `docs/REMOTE_PREVIEW_PROPOSAL.md` | none on LAN | written approval if a remote host is wanted; **not deployed** |
