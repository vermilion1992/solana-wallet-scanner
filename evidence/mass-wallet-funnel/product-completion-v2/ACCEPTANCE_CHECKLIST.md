# Product-completion-v2 acceptance checklist

Tracks four tracks separately. `PRODUCT_READY` stays false while any existing
gate is unresolved (B1 `NO_GO_CURRENT_SOURCE`, B2 `OPEN`, B3 `BLOCKED`).

Frozen app SHA: `c0128f2e25d88d53e2bb0c4a45e6b8cb13f57cbf`.

## (a) Application functionality

| Check | Status | Evidence |
| --- | --- | --- |
| Browse all 100 ranked wallets | PASS | A–H case A; `DISPOSITION_100.json` |
| Edit filters; provider-proxy vs reconstructed thresholds stay separate | PASS | A–H A; `tests/test_mass_search_product_workflow.py` |
| Unknown / unset thresholds never pass | PASS | `test_unset_thresholds_do_not_pass` |
| Shortlist persist; selection/sort/nav persist across reload | PASS | A–H F; sessionStorage nav + store shortlist |
| Offline filters cannot trigger acquisition | PASS | instrumentation 0; gate disabled |
| Batch truthful progress + terminal outcomes | PASS | A–H B; step_batch + completed/cancelled |
| Failure isolation | PASS | `test_one_bad_wallet_does_not_prevent_later_success` |
| Cancel leaves a consistent cancelled state | PASS | `test_batch_cache_and_cancel_do_not_call_providers` |
| Duplicate-submit prevention | PASS | frontend `batchBusy`; `test_second_inflight_batch_is_refused` |
| Cache bound to wallet+capture+snapshot+analysis version | PASS | `evidence_cache_key`; cache-hit re-attaches filters |
| History required — not analysed | PASS | 99/100 rows; batch status `history_required` |
| No substituted / empty-as-success results | PASS | incomplete_evidence when `visible_report` is false |
| Trades / positions / summaries / compare / export share one ledger | PASS | same report worksheet + analytics + export |
| Compare flags currency / window / incomplete-evidence | PASS | `test_compare_flags_currency_window_and_incomplete_evidence`; A–H compare "Mismatches" |
| Saved analyses reopen with provenance | PASS | `data-report-provenance`; A–H F restart |
| Exports carry interpretation metadata | PASS | `mass_search_interpretation` on `/api/export` |
| Empty / no-match / missing-history / malformed / failed / stale states | PASS | A–H B/C; synthetic error fixture; cache invalidation |
| Token on every API / export / saved-result / job route | PASS | `test_every_api_route_requires_the_session` |
| `/api/health` reports version + PRODUCT_READY false | PASS | A–H health assert |
| Stable identities, ranks, snapshot context | PASS | snapshot_id `ranked100-discovery-pilot-2026-10-05` |
| Provider fields kept separate from evidence metrics | PASS | research_profile vs provider_score/trade_count |
| 390×844 real frontend+backend workflow | PASS | A–H + LAN (browser emulation, not a physical phone) |

## (b) Genuine-data validation

| Check | Status | Evidence |
| --- | --- | --- |
| Rank-1 page 0 through real batch | PASS | +376.028087 / 852s / n=1 / A=YES B=PARTIAL C=NOT_EVALUATED |
| Independent FIFO vs app at position level | PASS | `APP_VS_INDEPENDENT.json`, `HEADLINE_376.md` |
| G1 control FIFO AGREE | PASS (control only) | −0.167725526 SOL / 598s; not a ranked-snapshot wallet |
| ≥2 distinct ranked-snapshot wallets through the real batch | **BLOCKED** | Only rank-1 page 0 exists. G1, rank-1 duplicates, and synthetic fixtures do not count. |
| Synthetic fixtures labelled and separated | PASS | `SYNTHETIC — engineering fixture, not proof` |

## (c) Access / deployment

| Check | Status | Evidence |
| --- | --- | --- |
| `./run.sh --lan --no-browser` advertised address + QR + separate client | PASS | LAN harness (output redacted) |
| Token protects every API / export / saved-result / job/progress | PASS | `test_every_api_route_requires_the_session` + LAN 401 |
| Approved remote preview target | **NONE** | `docs/REMOTE_PREVIEW_PROPOSAL.md` written; not deployed |
| No secrets in repo / exports / screenshots / evidence | PASS | token redacted; no keys committed |

## (d) Wallet research conclusions

| Check | Status | Evidence |
| --- | --- | --- |
| Rank-1 not safe to copy | PASS | unresolved basis + open inventory + page-0 only |
| Funnel A/B/C honest | PASS | YES / PARTIAL / NOT_EVALUATED |
| Next-candidates proposal prepared, not enabled | PASS | `DRAFT_RUN_PREPARED.json` |
| Copy-trading / MATCH / PRODUCT_READY | **NOT CLAIMED** | PRODUCT_READY remains false |

## Existing gates (unchanged)

- B1 historical source: `NO_GO_CURRENT_SOURCE`
- B2 complete real accounting: `OPEN`
- B3 genuine whole-wallet acceptance: `BLOCKED`
- `PRODUCT_READY`: **false**
