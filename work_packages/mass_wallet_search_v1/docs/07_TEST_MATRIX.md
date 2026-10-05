# Required tests and failure controls

The cases below are requirements for the implementation, not tests already run on the scanner. Implement them in the existing test organisation and validation entry point. Use unit tests for pure rules and actual API/browser tests for workflow and persistence. Positive compatibility controls matter as much as rejection tests.

| ID | Case | Required result |
|---|---|---|
| SRC-01 | Primary discovery response + stable next page | Correct schema/units/window; validated unique candidates and preserved memberships. |
| SRC-02 | 401/403, entitlement failure, 429 and unavailable endpoint | Distinct source states, bounded retries, no fake empty-success list. |
| SRC-03 | Page duplicate/cursor loop/moving rank/order change | Deduplicated rows, bounded progress, no fabricated atomic snapshot. |
| SRC-04 | Provider floor excludes lower-profit users | Declared universe limitation; no claim of full-market search/recall. |
| SRC-05 | Unreviewed provider field or cost-basis method changes | Incompatible fields stay unknown; preserved raw record; no reused stale parser truth. |
| SRC-06 | Parsed source and raw native data disagree | Keep discrepancy; raw reconciliation is not outvoted by summaries. |
| UNI-01 | Same wallet appears in several token/source cohorts | One chain/address identity, all memberships retained. |
| UNI-02 | Import > legacy 20 with explicit bulk storage capacity | Bulk-only path can retain authorised local rows; old sampler caps/credits unchanged. |
| UNI-03 | 10,000 summaries and paginated detail queries | No repeated all-report materialisation, stable sorting and bounded payloads. |
| UNI-04 | Decimal strings `-2`, `-10`, `0.01`, `0.1`, `9`, `10` | Numeric order, exact currency/precision, no lexicographic ranking. |
| FIL-01 | Missing profit vs actual 0 vs negative | Unknown is deferred; genuine zero/negative evaluated according to policy. |
| FIL-02 | USD metric offered to SOL threshold | No automatic strict comparison or today's-price back-conversion. |
| FIL-03 | Average hold/token win-rate/trade count proxies | No substitution for median hold/position win-rate/completed positions. |
| FIL-04 | High profit with unknown exit or missing critical source | No composite-score override of failed/unknown prerequisites. |
| FIL-05 | Filter changed against a frozen cached universe | New decision snapshot, zero provider/credential calls. |
| FIL-06 | Supported decisive failure at cheap stage | No unnecessary later reconstruction except predeclared audit sample. |
| FIL-07 | Old strict preset and previous reports | Values and parent hashes unchanged; new plan separately named. |
| LED-01 | Each stage with all four outcomes | Exact count conservation; next input equals previous promoted set. |
| LED-02 | Per-stage cap below eligible survivors | Excess candidates deferred by budget; not rejected or silently omitted. |
| LED-03 | Resume after partial run | Existing decision/evidence snapshots retained; no duplicated events. |
| BUD-01 | Concurrent reservations approach cap | No oversubscription, including in-flight work and retries. |
| BUD-02 | Crash before dispatch / after dispatch / after archive | Release only unspent reservation; ambiguous charges retained; idempotent recovery. |
| BUD-03 | Unknown remaining quota, expired authorisation, overages | No live collection; exact reason; offline lane continues. |
| BUD-04 | Existing exhausted setup allowance | Not reset by new run, migration, provider route or restart. |
| BUD-05 | Multiple providers with different billing units | Separate limits/actuals; no ungrounded conversion or sum. |
| ACC-01 | Independently worked buy/sell pair with buy and sell fees | Exact FIFO basis consumed, no double subtraction. |
| ACC-02 | Transfer-in unknown acquisition basis followed by sale | Sale visible; dependent P&L unknown, not sale proceeds as profit. |
| ACC-03 | Fee-paying failed transaction | Fee retained, no successful buy/sell event. |
| ACC-04 | Multi-hop swaps, temporary wrapped SOL, supported refunds | Correct economic event/cost scope or explicit unsupported dependency. |
| ACC-05 | Missing opening/ownership/chronology fact | Dependent certainty falls; independent fees/timing survive where justified. |
| ACC-06 | Unsupported token or transaction version/route | Counted limitation; no silent removal of losing/unknown positions. |
| ACC-07 | Remove/restore raw acquisition source | Child rebuild changes only dependent support; originals immutable. |
| ACC-08 | One sale within window consumes pre-window buy basis | Correct cost attribution; no missing pre-window fees or arbitrary zero basis. |
| TIM-01 | 95% sold quickly, dust held 48h | Fast t90 visible beside long final hold; no 'slow trader' label. |
| TIM-02 | Additional buys after partial sales | Retrospective total-acquired milestone distinct from causal live proportion. |
| TIM-03 | Open episodes and missing close records | Censored/unknown, not zero hold or fabricated closure. |
| TIM-04 | Median of 0.5h, 2h, 48h | 2h, not mean; population count 3. |
| KPI-01 | Nonoverlapping weeks + overlapping 7/30/90 values | Four actual weeks used; missing complete week unknown. |
| KPI-02 | Closed +5 SOL with known open loss -8 SOL | Closed profit does not become positive total economics. |
| KPI-03 | One winner dominates gains | Both specified concentration measures and remove-winner result visible. |
| KPI-04 | Transfers/open holdings/unpriced assets excluded by provider | Coverage limitation preserved in summary and report. |
| FWD-01 | Real receipt -> decode -> reaction deadline -> quote | No quote/request before deadline; actual receipt time retained. |
| FWD-02 | Zero notifications despite acknowledged subscription | Operational capture remains incomplete, not demonstrated. |
| FWD-03 | No quote for an exit | Position remains open/unpriced; no last-price close or result omission. |
| FWD-04 | Shared cash exhausted / duplicate buy / scale-in | No unfunded entry; deterministic dedupe and explicit strategy response. |
| FWD-05 | Sale fraction with unknown pre-sale inventory | Proportional exit unresolved, not guessed from future total purchases. |
| FWD-06 | Process stopped or provider outage | Gap retained; recovered history is not retroactively followed activity. |
| FWD-07 | Future quote/ranking/sale injected into earlier decision | Test rejects look-ahead; selection and strategy were frozen first. |
| FWD-08 | Same token traded by several wallets | Exposure overlap shown; not counted as independent proof. |
| UI-01 | Mobile 360px + desktop, real populated report | Readable table/detail and labels; no horizontal control obstruction. |
| UI-02 | Empty, not scanned, no trades, source failure, cap reached | Specific next action and state; no unexplained blank dashboard. |
| UI-03 | Anonymous/CSRF-invalid new endpoints and export | Existing security model preserved; no leaked provider secrets. |
| UI-04 | Save, restart, reopen, export and rebuild | Same frozen settings/sources; no live calls during cached operations. |
| EVI-01 | Synthetic example submitted as live proof | Live gate incomplete; no live/financial/product readiness claim. |
| EVI-02 | Stale commit, dirty source, missing or wrong artifact hash | Contract invalid or acceptance blocked, never passed from labels alone. |
| EVI-03 | Three winners generated by threshold relaxation | Original selection retained; new experiment required and comparison disclosed. |

## Existing gate integration
The reference repository's `ACCEPTANCE.md` lists backend pytest, dependency checks, frontend `check:format`, `check:discovery`, build and guarded browser workflows. `tools/validate.py` is the active orchestration entry point. Inspect its current CLI before invoking a profile; do not guess options from this package.

Register new regressions once in the appropriate focused groups/profile. Run affected slices during development, then applicable full candidate gates against exactly the code being handed over. Preserve old failures and legitimate existing UNKNOWN results. Do not xfail/drop a regression to get a green badge.

The package's own standard-library tests validate its receipt checker only. They are not replacements for this matrix and are not additional scanner test results.
