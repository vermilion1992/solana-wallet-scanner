# Independent reviews (separated passes)

App SHA reviewed: `c0128f2e25d88d53e2bb0c4a45e6b8cb13f57cbf`.
Reviewers did not modify the application. Evidence-only files may follow.

## (i) Accounting / provenance — ACCEPT

Scope: standalone FIFO, rank-1 +376 meaning, G1 control, capture provenance,
checklist tracks (b) and (d).

| Finding | Severity | Resolution |
| --- | --- | --- |
| Independent tool imports decoder + canonical wrap, not `scanner.accounting` / `settlement` / `live_g1` / `metrics` / `service` | none | Accepted. Forbidden-import test walks the AST. |
| +376.028087 is one matched `5tCju6YN` sell: 3376.028087 − 3000 FIFO buy `59K92oti…`. SOL fee 0.00032333 not subtracted. Unbacked sell `4UAE8RXr…` 2954.546038 excluded. Three H4KU buys are inventory. | none | Matches `INDEPENDENT_RECON_RANK1.json` and app worksheet. No number change this pass. |
| G1 −0.167725526: 4 buys + 1 sell; buy fees in basis (3.200065 / 1.400065 / 1.500065 / 1.800065); sell fee 0.000065 off proceeds; AGREE | none | Matches archive and app. |
| Missing basis stays unknown; cash flow / known-basis realised / unrealised / unresolved stay separate | none | Unresolved sale recorded with unmatched qty; open lots listed; USDC fees out of P&L. |
| Genuine multi-wallet BLOCKED | none | Only one ranked-snapshot capture. G1 and synthetics correctly excluded. |
| PRODUCT_READY / safe_to_copy | none | Both remain false. |

Verdict: **ACCEPT**. No material accounting defect. No correction to +376.028087.

Separate reviewer [Accounting provenance review](bc-473f3e95-da35-5fc2-be86-b3cb8bb44d9a) returned **ACCEPT_WITH_NITS** on the same numbers:

| Finding | Severity | Resolution |
| --- | --- | --- |
| Tool AST is clean; runtime still loads accounting via `investigation` / `capture_catalog` → `g3_reacquire` → `history_ingest` | minor | Accepted as algorithm independence, not process isolation. FIFO `_fifo` does not call settlement. No number change. |
| APP_VS lists standalone lots; app lots live in product-completion-v1 APPLICATION_REPORT | minor | Totals AGREE; same signatures/qty/3000/3376.028087. Optional self-containment only. |
| Partial-match sell would drop consumed inventory then mark the whole sale unresolved | latent | Not on these tapes (leading unbacked sell; G1 full close). |

## (ii) App / security — ACCEPT_WITH_NITS

Scope: acquisition gate, batch, cache, token routes, LAN, draft grant,
compare mismatches, checklist tracks (a) and (c).

| Finding | Severity | Resolution |
| --- | --- | --- |
| Gate blocks missing / disabled / expired / consumed / insufficient / concurrent before transport | none | `test_auth_gate_blocks_before_provider_and_under_concurrency` + A–H G. |
| Atomic reservation under store lock; second thread concurrent; product path still `do_not_dispatch` | none | Accepted. |
| Cancel / consume helpers never restore allowance; no SDK retries | none | Draft `retries: 0`; consume only increases used_*. |
| Draft grant `enabled: false`; five full snapshot addresses ranks 4/2/15/17/90; optional rank-1 page skipped | none | `DRAFT_RUN_PREPARED.json`. |
| Token on every `/api` except bootstrap (the exchange itself) | none | `test_every_api_route_requires_the_session` (≥40 routes; health, export, mass-search). |
| Cache key = wallet + capture sha + decoder + window + mint + analysis version + snapshot raw sha | none | `evidence_cache_key`. |
| In-flight batch refused; History required honest; synthetic error isolated | none | Batch 6/6 shot. |
| Compare flags currency / window / corpus / incomplete-evidence | none | Phone compare shows corpus + unresolved-basis mismatches. |
| No secrets in repo/evidence | nit | Raw LAN stdout prints a QR of the live token URL. Evidence keeps `lan-launcher-redacted.log` only (QR omitted, `#session=[redacted]`). |
| Draft JSON still has `optional_rank1_earlier_page_for_unbacked_sale: true` | nit | Product proposal overrides to false with skip reason. Grant stays disabled. Not a dispatch risk. |
| Remote preview | none | Proposal only; `preview_available: false`. Not deployed. |
| PRODUCT_READY | none | False on bootstrap, health, reports, exports. |

Verdict: **ACCEPT_WITH_NITS**. Nits recorded; no application change required for this freeze.

Separate reviewer [App security review](bc-fb99d3b0-0af2-52bd-9273-ebc6a756d33f) returned **ACCEPT_WITH_NITS**:

| Finding | Severity | Resolution |
| --- | --- | --- |
| `visible_report` is on the replay result, not copied onto the saved report; cache hit defaults missing to True | minor | Accepted for current fixtures (rank-1 visible; no-history writes no report; SYNTH_BAD is error). Persist if a no-event capture is added. Rank-1 compare still flags unresolved basis. |
| Compare test name includes window; pair shares the same window so only currency/corpus assert | minor | Implementation flags differing windows. G1 windows differ if the name must stay literal. |
| `create_batch` inflight check and put are separate lock sections | minor | Sequential refuse works. Accepted for this local single-user app. |
| No `/api/jobs` route; job/progress is `/api/state` + scans | none | Enumerator still 401s every `/api` except bootstrap. |

## Material findings requiring a code fix

None from either reviewer. No re-run of app gates. Final HEAD may differ from tested SHA `c0128f2` by evidence files only.
