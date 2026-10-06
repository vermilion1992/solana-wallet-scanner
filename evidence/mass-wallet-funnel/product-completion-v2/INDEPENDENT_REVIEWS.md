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

## Material findings requiring a code fix

None. No re-run of app gates required. Final HEAD may differ from tested SHA by evidence files only.
