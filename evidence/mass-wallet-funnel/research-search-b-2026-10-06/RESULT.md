# RANKED100_RESEARCH_SEARCH_HISTORY (grant B): Mitch-review fix pass

**Outcome: coverage ledger + items 1–15 landed offline on genuine attempt-1 pages. PRODUCT_READY stays false. No live calls. No grant enabled. No merge/deploy.**

`PRODUCT_READY` = **false**. B3 = **BLOCKED**. Two newest-first GTA pages are not complete history. No profitability claim. Not MATCH. Qualifying means the wallet meets the screen on matched trades in the captured window, never account performance.

Binding acceptance is Mitch's source review of `3453f8f` (`MITCH_REVIEW_2026-10-06_1804.md`). Item 12 replaces the 10% coverage rule. Item 13 replaces the earlier venue list. Item 2: only verified Jito tips count. Item 6: opening inventory may change qualifier counts; the table below is the honest result.

## Grant and approval

- Grant `live-ranked100-research-search-2026-10-06-mitch` was already consumed for attempt-1. This pass did not enable it.
- Depth-biased next-capture draft: `config/live_authorization.ranked100-depth-biased-next-capture-draft.json` (`enabled: false`). Requires Mitch's fresh approval. 20 req / 200 cr. Cursor continuity from committed page-1 tokens. Provider-side cutoff `2026-10-05T13:29:27Z`.
- Repo drafts stay `enabled: false`. No Helius or Birdeye call was made.

## Fix commits

Branch `cursor/research-search-b-fix-1055`. Draft PR #6 vs `cursor/mass-wallet-funnel-v1-1055`.

- `8643dc7` — 2000-record coverage ledger + discriminator histogram
- `be1215d` — items 1–15 (coverage policy, verified tips, opening inventory, Pump v2, independent audit, disabled next-capture draft)
- `f24aff7` — OKX/DFlow stay unsupported; partly backed sales are not clean episodes
- tip of this branch — rebuilt `frontend/dist` (`index-Dfbh-8ex.js`), regenerated 2000-record ledger with item-12 dependency statuses, re-ran independent audit

## Per-wallet table (window 2026-09-05T13:29:27Z → 2026-10-05T13:29:27Z exclusive)

Offline replay of the 10 genuine two-page captures on current code. Evidence labels are `qualification_level`. Coverage shares are `1 − unsupported_swap_share_in_window` (count and worst measurable notional). Net P&L deducts verified costs only (network + verified Jito tips). Unverified outside SOL withdrawals are the labelled sensitivity column, not tips.

| Rank | Wallet | Evidence label | Coverage count / value | Coverage status | Concentration | Episode win rate | Verified fees+tips SOL | Sensitivity unverified debits SOL | Completed | Net |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | gtfo…CgFL | conditional captured-lot result | 1 / 1 | pending reassessment (4 unresolved-basis sales) | positive subset | 11/16 = 0.6875 | 3.241955778 | 0.0547 | 16 | 2.030645839 SOL |
| 4 | CccS…y1eU | provisional research lead | 1 / 1 | provisional eligible | positive subset; highly concentrated; negative excluding largest winner | 3/6 = 0.5 | 0.01194306 | 1.428081532 | 6 | 0.242261753 SOL |
| 10 | BVZt…Y9n9 | insufficient evidence | 0.261904762 / 0.301547391 | coverage blocked | — | n/a | — | 0 | 0 | −2413.398216681 USDC (not a qualifier) |
| 11 | BSN5…BtCM | insufficient evidence | 0 / 0 | coverage blocked (L2 / unknown venue) | — | n/a | — | — | 0 | — |
| 14 | DQ7n…9Cys | insufficient evidence | 0.133333333 / 0 | coverage blocked | — | n/a | — | 0 | 0 | — |
| 15 | A6PS…vbot | conditional captured-lot result | 1 / 1 | pending reassessment (3 unresolved-basis sales) | positive subset | 2/8 = 0.25 | 6.285314998 | 4.562 | 8 | 283.431579449 SOL |
| 17 | An9s…LYSB | conditional captured-lot result | 1 / 1 | provisional eligible | positive subset | 1/1 = 1 | 0.009758999 | 0 | 1 | 174.65797861 SOL (1 episode; 27 open lots) |
| 53 | 58PW…xvDL | conditional captured-lot result | 0.783333333 / 0.845692925 | coverage blocked | — | display 3/2 = 1.5 (wins vs clean-episode count diverge) | — | 0 | 2 | 51148.756609023 USDC |
| 56 | AW6P…MzD6 | insufficient evidence | 0 / 0 | coverage blocked (OKX unreviewed) | — | n/a | — | — | 0 | — |
| 90 | CRXo…V68U | insufficient evidence | 0 / 0 | coverage blocked (OKX/DFlow unreviewed) | — | n/a | — | — | 0 | — |

D13 exclusive partitions (must not regress): gtfo 71/4/50/0/75; CccS 170/17/1/0/12; A6PS 52/4/77/0/66 + 1 conversion; An9s 0/1/132/0/67.

After OKX/DFlow stay unsupported: BVZt 2/49/107/31/10 + 1 conversion; 58PW 2/0/138/13/45 + 2 conversions.

## Qualifier counts at each level

| Level | Count | Wallets |
| --- | --- | --- |
| stronger_research_shortlist | 0 | — |
| provisional_research_lead | 1 | CccS (coverage eligible; 6 clean episodes; positive scoped net; no unresolved basis). Not a frozen product default. Not MATCH. |
| coverage_eligibility_pending_reassessment | 2 | gtfo, A6PS (100% swap coverage by count/value, but a missing purchase can still change FIFO of a qualifying sale) |
| conditional_captured_lot_result | 4 | gtfo, A6PS, An9s, 58PW |
| insufficient_evidence | 5 | BVZt, BSN5, DQ7n, AW6P, CRXo (zero-position / coverage-blocked wallets are not “unprofitable”) |
| research-screen completed (default count-only, item-12 gate applied) | 1 | CccS only. Reason: “meets the sample/activity filters”. An9s is zero_qualified (1 episode < min_sample 3). gtfo/A6PS stay inconclusive pending reassessment. |

The previous 3 “qualifiers” (gtfo, CccS, A6PS) are **not** a shortlist. CccS is the only provisional research lead and the only default-screen completed row. gtfo and A6PS stay pending reassessment until opening-basis dependencies are cleared.

## Named tests

- `tests/test_mitch_review_2026_10_06.py` — items 1–8, 10–12, 15, 17
- `tests/test_research_search_b_defects.py` — D1–D15, including 99/95/blocked coverage (not the 10% gate)
- `tests/test_mass_search_mitch_requirements.py` — unset = not applied; compare; ANALYSIS_VERSION pin
- `tests/test_mass_search_product_completion.py::test_mixed_sol_and_usdc_worksheet_is_per_quote_asset` — item 10 cross-currency
- `tests/test_investigation.py::test_real_mainnet_wrappers_and_sponsored_router_are_explicit_gaps` — item 13 wrappers stay unsupported

## Suite / build on this exact commit

- Keys unset: **3641 passed**, 440 subtests, EXIT 0 (9 min 20 s) at `f24aff7`
- Keys set (dummy, never dispatched): **3641 passed**, 440 subtests, EXIT 0 (9 min 5 s) at `f24aff7`
- `npm run build`: `tsc -b && vite build` OK; bundle `frontend/dist/assets/index-Dfbh-8ex.js`
- Named regressions re-run on this evidence/dist commit (see TESTS.md)

## Independent audit

`tools/independent_episode_audit.py` imports no `scanner/` package. It reconstructs Pump / PumpSwap / Jupiter from pinned discriminators, raw balances and ownership, then FIFO with opening inventory consumed first. Output: `coverage/INDEPENDENT_AUDIT.json`. App episode counts and independent counts are not required to match: the auditor does not decode Raydium / Meteora / remaining histogram venues.

## Still blocked

- **PRODUCT_READY = false**
- Opening-basis dependencies on gtfo (4 worksheet / 6 ledger-isolation sells) and A6PS (3). Item 12 dependency rule blocks shortlist regardless of 100% swap coverage.
- OKX (`proVF4…`), DFlow (`DF1ow4…`), L2TExMFK, and unreviewed System opcode `4NK93B3R…` stay unsupported. Histogram ranks them; they cannot be reviewed with confidence.
- 58PW win-rate display is 3/2 = 1.5 when episode-P&L rows and clean-episode counts diverge. Coverage-blocked; not a qualifier.
- A6PS residual **0.001513840 SOL** is “explained by identified program-account funding, excluded from swap consideration”. Verified-cost residual vs raw wallet Δ is larger because unverified debits are no longer treated as tips.
- Stronger research shortlist (≥20 clean episodes, ≥3 mints, ≥7 calendar days) is empty.
- Depth-biased next capture is drafted `enabled:false` only. Do not dispatch without Mitch’s approval.
- Phone-emulation screenshots from pass 1 were not re-shot in this run (UI copy/coverage wording changed; behavior not re-verified in a browser here).
