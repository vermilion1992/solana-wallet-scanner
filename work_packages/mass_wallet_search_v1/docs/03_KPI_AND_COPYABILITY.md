# KPI and following-quality contract

## 1. Record definition before value
Each metric needs: key, value or null, unit, inclusive start/exclusive end, population, sample count, calculation version, source/evidence hashes, fetch/observation time, evidence basis and missing dependencies. The `metric_record.schema.json` describes the transport shape; arithmetic invariants still require tests.

Suggested bases: `PROVIDER_REPORTED`, `RAW_DERIVED_SUBSET`, `INDEPENDENTLY_RECONCILED_SUBSET`, `STRICT_WALLET`, `FORWARD_QUOTE_MODEL`. Suggested states: `KNOWN`, `UNKNOWN`, `CONFLICT`, `STALE`. A known provider value does not make its wallet-wide truth verified. Stale snapshots retain their historical values but cannot silently satisfy a fresh decision.

The paired source window must match the comparison. Preserve original USD and SOL values separately. Converting one reported USD profit total with today's SOL price does not reproduce historical SOL-denominated trading P&L. Store conversion inputs and timestamps for any clearly labelled presentation conversion.

## 2. Preserve Strict research unchanged
Use `config/strict_preset.snapshot.json` and compare against the repository's actual constant. The existing target is 30-day reporting with 90-day verification, 5 SOL realised profit, 10% realised ROI, 5% median position ROI, 50–85% completed-position win rate, 1–72-hour median strict hold, at least 50/100 completed positions in the respective windows, 20–100 eligible mints, at most 10% rapid first sales, average buys 1–2 and sells 1–3, three positive weeks out of four, largest mint contribution at most 25% and positive economic P&L.

The new Mass research policy is separate. Its queue limits, unknown-handling, proxy metrics and delay scenarios are engineering/research choices, not changes to these thresholds and not evidence that these thresholds predict future returns.

## 3. Position and event populations
A transaction may contain several instructions and several routed swap legs. Deduplicate by canonical transaction identity and supported event path; do not count inner routing legs as separate economic trades. A failed transaction can cost fees without being a successful buy/sell.

A completed strict wallet position is a supported mint-aggregate inventory episode from zero through acquisition and disposition back to zero across its required ownership scope. A fetched buy followed by a sell does not establish no earlier inventory. An observed subset episode may still be shown as conditional, with its exact assumptions.

Transfers are not buys or sales. Unknown-basis transfers cannot acquire zero cost by default. Inventory transferred away is not automatically a realised loss or a sale. Multiple wallets with a transfer link are not automatically one owner. Scope uncertain events to affected quantities, monetary fields or timing; do not indiscriminately blank independent metrics.

Keep losing, breakeven, open, failed and unresolved events visible. Define win rate over eligible completed episodes, counting breakeven episodes in the denominator and reporting them separately. Do not substitute the number of profitable sells or provider token win-rate for completed-position win-rate.

## 4. P&L and costs
For a supported disposal:

`realised P&L = supported sale proceeds - FIFO acquisition basis consumed - attributable disposal costs`.

Buy-side costs enter acquisition basis and are realised only as their units are disposed. A cost included in pool/quote output is not deducted a second time. Supported wallet-paid overhead and failed-transaction costs need an explicit period allocation policy; costs with unknown economic roles remain dependencies, not silent zeros.

Subset P&L must name excluded unmatched sales and open/unknown exposure alongside the total. A positive subset total cannot create a verified whole-wallet label. Independently supported realised results do not require present-day marks; economic P&L does.

For reconciled total equity, use consistent opening/closing inventory valuations and external flows: `ending equity - starting equity - external inflows + external outflows`. Report valuation dates, priced fraction, unknown basis and flows. A token balance multiplied by an unexecutable displayed price is not an assured liquidation value.

Realised ROI uses realised net profit divided by the matched acquisition basis, including attributed buy costs. Report the denominator. If the required basis is missing or non-positive, return unknown instead of an infinite win. Freeze the existing accounting methodology unless a separately tested, versioned fix is necessary.

## 5. Timing: avoid dust-tail distortion
For each eligible episode show first acquisition, first sale, supported 50%/90% exit milestones and final closure. Reuse the existing versioned milestone semantics; do not silently reinterpret historical reports.

For a newly named `material-exit-v1` diagnostic, explicitly use cumulative sold units divided by total acquired units in the completed observed episode. Additional purchases can move the milestone. This is a retrospective behaviour diagnostic and must never be used as information that a follower knew before those purchases happened. Incoming transfers or unknown quantities invalidate the dependent ratio unless separately resolved.

Median completed hold is the median of eligible completed episode durations. Report population count and excluded/open episodes. Compute quantity-weighted exit time as a separate statistic, never as a replacement for the median or t90. Open positions are censored observations, not zero-duration positions and not silently successful future exits.

Example fixture: buy 100 units; sell 50 at 20 seconds, 45 at 30 seconds and 5 at 48 hours. First sale and t50 are 20 seconds, t90 is 30 seconds, final closure is 48 hours. A long final hold must not hide the fast material exit. See independently specified arithmetic in `fixtures/acceptance_cases.json`.

## 6. Profit distribution and concentration
Show net P&L by mint, best/worst positions, realised losses, open losses and period results. Preserve the existing strict largest-mint/net-profit check, including its treatment of non-positive net profit. Separately add largest winner share of gross positive contributions and a 'remove largest winner' stress result. These denominators are different; label them.

Calculate four-week consistency on its own exact 28-day interval split into four non-overlapping seven-day periods. Overlapping 7/30/90-day profits are not independent positive periods. An empty period is zero only when required history/costs establish completeness for that population; otherwise unknown.

Drawdown requires a dated equity series with supported marks and flows. Do not calculate a whole-wallet drawdown from only closed winners. Report priced-coverage failures and scenario liquidation haircuts separately.

## 7. Following strategies and time available to act
Use two separately versioned, predeclared strategies:
- Keep existing `fixed-entry-first-sale-v1` as the baseline: fixed hypothetical entry on the eligible new signal, then its specified first-sale exit.
- Implement `fixed-entry-proportional-exit-v1` only after the baseline is demonstrated. Scale out by the leader's supported sold quantity divided by supported pre-sale inventory, applied to current simulated follower holdings. Unknown leader inventory means the proportional amount is unresolved; do not guess. Additional leader buys do not increase the follower's fixed entry unless a different strategy is explicitly named. Round down raw units; an evidenced full close triggers a full-exit attempt for the remainder.

One open simulated position per wallet/mint/strategy and explicit shared-cash rules prevent impossible simultaneous entries. Record ignored scale-ins, duplicate signals and rejected/unfunded entries.

The user's likely manual phone delay is not known precisely. Proposed **simulation-only** reaction scenarios are 15, 60 and 180 seconds, with 60 seconds the primary provisional scenario. Make these editable, freeze them per run, and report actual collection/decode latency in addition. These numbers are not execution promises or accepted user authorisation for live spend.

Earliest quote request time is after actual signal receipt, decoding and the selected reaction delay. Log leader chain time, source notification receipt, decode completion, delay deadline, quote request/response and quote context. Preserve clocks and monotonic durations; do not replace measured detection time with chain block time.

No future leader sale, final inventory, later quote, eventual token success or later candidate ranking may influence an earlier simulated decision. Proportional exits use information available on that sale, not the episode's future total acquisition.

## 8. Price/exit feasibility
Quotes must be amount-specific and dated. Entry buys the quantity implied by the actual delayed quote, not the leader's original quantity. Exit quotes use the follower's actual remaining units. Model extra execution costs once and document any adverse output haircut. Do not submit swaps or transaction simulations requiring a signing wallet.

A successful quote is not an actual fill. Keep unavailable routes, minimum amounts, excessive impact, stale responses and exhausted quote budgets visible. If an exit cannot be quoted, inventory remains open with unknown liquidation value unless a declared stress scenario values it at a haircut. Do not close it at the last good mark, exclude it from results or count it as a zero-cost win.

Measure delayed model P&L, exit availability, material leader exits before our action, adverse price movement after entry and drawdown/coverage separately. Do not infer deliberate follower exploitation, insider status, shared ownership or safety from these patterns alone.

Historical delay analysis needs authentic historical resolution and obtainable information. Current quotes or coarse candles cannot prove second-by-second past execution. Historical trade decoding and forward quote testing are separate lanes; real historical data replay is not genuine forward collection.

## 9. Ranking and evaluation
Use mandatory compatibility/evidence checks first, then transparent ranking. Never allow high reported P&L to offset an unmeasured critical exit or data-integrity failure. Separate exploratory candidates from strict passes.

For forward comparisons keep initial capital, position sizing, delay, fees, token exclusions and strategy consistent between selection methods. Compare reported-P&L ranking, original strict selection and new research selection on the same eligible universe. A strict arm with zero eligible members stays empty and is reported as such; do not fill it with relaxed substitutes.

Share token/transaction evidence for efficiency but preserve per-strategy state. Label common-token exposure and use overlap-aware analysis; three wallets trading the same token are not three independent validations. Statistical intervals must account for dependence, sample size and repeated strategy trials. No fixed sample size alone establishes persistent profitability.
