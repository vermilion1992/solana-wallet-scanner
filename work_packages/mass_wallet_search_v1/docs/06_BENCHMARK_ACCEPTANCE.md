# Real-data and performance proof

## 1. Independent lanes
Keep these lanes separate in every report:
- **Development:** synthetic transports/adversarial fixtures and local performance.
- **Genuine replay:** immutable real archived records processed offline. Proves derivation on those records, not a currently working acquisition route or forward capture.
- **Live search:** authorised current provider acquisition with provenance and budgets.
- **Forward observation:** data actually received after frozen selection, with real request/delay timestamps and hypothetical quotes.

No synthetic artifact may supply a live metric. Documentation examples are synthetic unless independently sourced provenance says otherwise. A real historical transaction replayed today is not a signal observed at its original time.

## 2. Gates
| Gate | Pass requirement | What it does not establish |
|---|---|---|
| G0: baseline and safety | Existing rules/caps preserved; applicable current code gates pass; no unauthorized spend or signing. | No financial acceptance. |
| G1: real vertical slice | Actual acquired candidate -> targeted native records -> supported real buy/sell -> populated report/reopen/export, independently reconciled. | No broad coverage. |
| G2: genuine mass acquisition | At least 1,000 unique valid candidate addresses, real source requests, source/cap restrictions and acquisition period recorded; stages conserve every candidate. | Not 1,000 reconstructed histories or every Solana wallet. |
| G3: useful real analytics | At least three genuine independently reconciled reports; each has at least 10 supported completed observed episodes, populated subset realised P&L and median observed hold with counts; losing/nonqualifying or unresolved control also inspected. | Not three profitable strict matches or complete historical ownership. |
| G4: local scale/performance | 10,000 lightweight rows; zero external calls for refilter; recorded hardware, payload size and repeated timing; no silent omissions. | Not 10,000 live scans. |
| G5: forward operational | Genuine eligible buy and exit signals, at least two delayed quotes and one complete hypothetical position, with costs/cash/gaps and real timestamps retained. | Not actual fills, profitable following or persistent edge. |
| G6: financial research outcome | Frozen cohorts/strategies; retained losses/open exposure; prospective comparison and uncertainty. May be negative or inconclusive. | No guaranteed future profit. |

The minimum of 10 episodes per G3 report is an engineering demonstration population, not statistical validation and not the original strict minimum of 50/100 positions. If records support only a smaller subset, show it, but mark G3 incomplete. Do not cherry-pick matched winners to reach ten; preserve the selected window and all unresolved/loss/open observations.

G2 and G3 are both needed before saying the redesigned search has been demonstrated with real analytics. G5 is separate. Missing access is a source blocker, not evidence that there are no suitable traders. Genuine failure to find three positive candidates is different from failure to evaluate them.

## 3. Freeze before a run
Write a pre-run record with:
- exact application commit, source manifest, locks, runtime and hardware;
- chosen source capabilities/entitlements and sanitized authorisation ID;
- acquisition start, selection cutoff, report/verification windows and timestamp semantics;
- candidate inclusion strata, sort/filter fields, deterministic ties and duplicate policy;
- stage caps and thresholds, unknown/defer handling, exploration sample and stop conditions;
- actual per-provider unit caps, request/concurrency/retry ceilings and zero additional-spend rule;
- accounting versions, original strict snapshot and following strategy/delay settings.

Use three different timestamps: freeze the **plan** before acquisition, seal the acquired **universe** after collection, and freeze the actual selected **cohort and strategy** after historical analysis but before any prospective observation. Do not pretend that an as-yet-uncollected universe hash existed at plan-registration time. The receipt contract keeps these events separate.

Changing a selection threshold or observation horizon after looking at results creates a new experiment and must not overwrite the old one.

## 4. Size and speed targets
Use a small genuine capability probe first. Then target 1,000 unique candidates for the first live mass run. A later 10,000-candidate live expansion requires measured capacity and authorised quota; it is not a prerequisite for the first useful release and not covered merely by local capacity.

Provisional local targets on recorded hardware: cached refilter p95 <= 500 ms and 50-row summary API p95 <= 750 ms at 10,000 rows. Perform 5 warm-ups and 20 measured runs, report median/p95/max, peak memory and record sizes. Measure the normal application path without profiler overhead. A faster reference script alone does not pass.

A <= 5-minute fresh 1,000-row acquisition is a **provisional objective**, conditional on actual provider throughput/access, not a guaranteed acceptance SLA. Report total wall time including throttling/retries and time to first usable shortlist. Do not exclude queue/429 time to make 'fast' appear true. Deep reconstruction has its own throughput/time/cost measurement.

Report candidate rows fetched, unique addresses, wallets with summaries, wallets with raw history, decoded transactions, supported economic trades, populated reports and qualifying outputs separately. Count no completed-wallet scan solely because an address was listed.

## 5. Independent reconciliation
For each of the three G3 reports, retain raw signature/event references, source acquisition details and a separate calculation worksheet. The worksheet states quantities, known opening facts, matched costs, fee allocation, proceeds, open inventory, first sale/t90/final hold, population exclusions and expected aggregates.

The oracle must not call the production accounting/ranking helper to compute its expected answers. Another provider's leaderboard is a comparison, not an arithmetic oracle. If using a distinct reviewer/tool, record what was independently checked and its limits.

Compare exact raw token units and lamports. Monetary tolerance is zero for exactly determined native amounts; any conversion rounding must have a specified decimal precision and bounded tolerance. At minimum inspect one losing/nonqualifying/unresolved control and an unknown-cost control, not only profitable cases. Losing examples can be separately selected controls, but label their selection and do not mix them into the frozen ranking as genuine random outcomes.

Rebuild offline from the saved inputs and verify identical supported outputs/versions. Remove a required acquisition/cost/chronology source: dependent certainty must fall, while independent supported fields survive. Restore exact bytes and verify reproducibility without rewriting the earlier snapshot.

## 6. Prospective comparison
Freeze three selection methods from the same universe: reported-P&L baseline, original strict preset and the new research funnel. Use equal per-arm simulated capital/limits and the same trade strategy, delay and costs. Empty arms remain empty; report both capital-normalised and per-deployed-capital results and deployment rates rather than concealing unused cash.

Define before observation: primary reaction scenario, optional stress scenarios, horizon, minimum observations, quote/stream budgets, valuation frequency, token restrictions and termination policy. A proposed exploratory target is at least 14 calendar days and 100 completed hypothetical positions across at least three wallets and five mints, subject to explicit authorised budgets. These are research targets, not a promise or a statistically sufficient proof. Reaching a budget cap pauses the run and records incomplete observation; never extend silently until profitable.

Do not discard accounts with no activity, failed entries, no exit route, late signals or open losses. Record drawdowns only with adequate marked-equity coverage. Report delayed model returns, priced exposure, open/closed positions, material early-exit frequency, fees, missed opportunities, monitoring gaps and token overlap.

For uncertainty analysis use token/day-aware grouping and disclose dependence, multiple trials and small samples. Do not claim that a few winning positions or a naive independent-trade confidence interval establishes an edge. Financial outcomes can be positive observed, negative observed, inconclusive or unavailable without changing G0–G5.

## 7. Evidence layout
Recommended application evidence directory: `evidence/mass-wallet-funnel/<run_id>/` for allowlisted, sanitized receipts only. Large raw/user/provider artifacts remain in the approved private runtime evidence store; export only within permitted retention terms.

Require candidate snapshot, stage decision rows, sanitized request log, budget ledger, source/lock manifest, wallet reports, independent reconciliation, test/browser evidence and (for G5) signal/quote/position records. Each receipt references immutable artifacts by local relative path and SHA-256. A hash proves byte integrity, not authenticity; retain genuine source/provenance records and independent review.

`contracts/benchmark_receipt.schema.json` and `tools/check_receipt_contract.py` define a transport/consistency guard. The checker does not parse every trade or authenticate a provider. Its success must be reported as **contract validation**, not G2/G3/G5 proof by itself.

## 8. Honest result categories
Use `PASS`, `FAIL`, `BLOCKED`, `INCOMPLETE`, `NOT_RUN` and `RUNNING` per gate. A timed-out step cannot pass. Return the exact missing dependency and smallest next action. Keep the actual evidence even when the benchmark loses money or fails to produce a three-wallet positive shortlist.
