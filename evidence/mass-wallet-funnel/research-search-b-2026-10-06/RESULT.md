# RANKED100_RESEARCH_SEARCH_HISTORY (grant B): fix pass

**Outcome: D1–D10 fixed and re-verified offline against attempt-1 captures. No further live attempt is needed for these 10 wallets.**

`PRODUCT_READY` = **false**. B3 = **BLOCKED**. Two newest-first GTA pages are not complete history. No profitability claim. Not MATCH. Qualifying means the wallet meets the screen on matched trades in the captured window, never account performance.

## Grant and approval

- Grant `live-ranked100-research-search-2026-10-06-mitch`. Approved by Mitch Hoffman 2026-10-06 15:38 ACDT ("B").
- Repo draft stays `enabled: false`. No grant was enabled in this pass. No Helius or Birdeye call was made.
- Attempt-1 captures (20 pages, all HTTP 200, 200 documented credits, $0, 0 Birdeye) are unchanged.

## Fix commit

Tested application commit: `1d1b3ec` (this evidence commit sits on top). Branch `cursor/research-search-b-fix-1055`. Draft PR #6.

## Per-wallet table (window 2026-09-05T13:29:27Z → 2026-10-05T13:29:27Z)

Offline `box_driver/ingest.py` + `box_driver/recon.py` on a fresh data dir. All 10 wallets saved a report. App == independent per quote asset and per sale for every completed known-cost position.

| Rank | Wallet | Pages | Completed positions | Gross SOL | Fees+tips SOL | Net SOL | USDC matched | Unresolved (SOL/USDC) | Open lots (SOL/USDC) | Unsupported txs | Screen |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | gtfo…CgFL | 2 | 16 | 5.272601609 | 3.258455778 | 2.014145839 | — | 4 / 0 | 0 / 0 | 179 | qualifies (matched trades in captured window) |
| 4 | CccS…y1eU | 2 | 6 | 0.254204813 | 0.133909877 | 0.120294936 | — | 0 / 0 | 0 / 0 | 46 | qualifies (matched trades in captured window) |
| 10 | BVZt…Y9n9 | 2 | 0 | — | — | — | — | 0 / 1 | 0 / 0 | 149 | fail (set minimums not met) |
| 11 | BSN5…BtCM | 2 | 0 | — | — | — | — | 0 / 0 | 0 / 0 | 160 | fail (set minimums not met) |
| 14 | DQ7n…9Cys | 2 | 0 | — | — | — | — | 0 / 1 | 0 / 0 | 198 | fail (set minimums not met) |
| 15 | A6PS…vbot | 2 | 6 | 297.232334822 | 9.848260002 | 287.384074822 | — | 0 / 0 | 0 / 0 | 196 | qualifies (matched trades in captured window) |
| 17 | An9s…LYSB | 2 | 0 | — | — | — | — | 0 / 0 | 0 / 0 | 199 | fail (set minimums not met) |
| 53 | 58PW…xvDL | 2 | 2 | — | — | — | 14739.373324196 | 0 / 6 | 1 / 3 | 181 | fail (`min_sample_positions=3`; 2 completed) |
| 56 | AW6P…MzD6 | 2 | 0 | — | — | — | — | 0 / 0 | 0 / 0 | 196 | fail (set minimums not met) |
| 90 | CRXo…V68U | 2 | 0 | — | — | — | — | 0 / 0 | 0 / 0 | 117 | fail (set minimums not met) |

- **Qualifying count: 3** (gtfo, CccS, A6PS). Research-screen outcome `completed` over the ranked-100 snapshot: inconclusive 89 · zero-qualified 7 · qualified 3 · not_executed 1 (rank-1 capture not replayed in this ingest).
- Qualification category for all 10 analysed research wallets remains `analysed_incomplete` (evidence class 2 when a positive known-basis subset exists). That is evidence quality, not a pass/fail.
- Unset thresholds are shown as "not set" and are not applied. The screen applies the configured defaults `min_completed_known_cost=1` and `min_sample_positions=3`.
- Attempt-1's gtfo +3.411606267 SOL was fee-light independent net. Current matched SOL is net of fees+tips: gross 5.272601609 − 3.258455778 = **2.014145839**, and app == independent.
- 58PW SOL unresolved sale is now a USDC→SOL conversion (not a SOL position). SOL: 0 known-cost, 0 unresolved, 1 open lot.

## D10 A6PS biggest-token residual

Token `EkFRff9a2jKztJHML1LG9FRmEkPJDR6XAYp3uCPdpump` (1 buy + 13 sells):

| Item | SOL |
| --- | --- |
| Decoded gross (sell − buy consideration) | 297.931068225 |
| Allocated network fee + same-tx tips | 5.954070 |
| Decoded net | 291.976998225 |
| Raw wallet SOL Δ on those 14 txs | 291.975484385 |
| Residual (net − raw) | 0.001513840 |

The 0.00151384 SOL is same-tx account-funding for `6dGSmzDVAaP7UUWcsNvoj7evnUmAV2co6sfoF3yYHZb8` on buy `gWoowMidB14X…`. It is not swap consideration, not a network fee, and not a tip. Matched SOL P&L is net of network fee and same-tx tips; that rent/create-account native stays out of P&L.

Outside native movements stay listed as unresolved capital on the decoder (reviewed contract). Worksheets still net `fees_and_tips_sol`. Unsupported transactions are counted and listed; they are not silently skipped. Version 1 is accepted into the same decoder path.

## App vs independent

Every completed known-cost sale AGREE per quote asset and per signature. Outputs: `recon/<address>.json`, `recon/SUMMARY.json`. The recon tool shares the decoder and does not import app FIFO / settlement / service.

## App visibility (390×844 Playwright Chromium, phone-sized browser emulation, not a physical phone)

Launcher: `python -m scanner --data-dir <fresh ingest dir> --port 8771 --no-browser` on loopback. Unauthenticated `/api/state` = 401. Zero external requests. Zero page errors.

Screenshots in `screenshots/`, labeled as phone-sized browser emulation:

- `fix-01-ranked-list-phone.png` — captured wallets show cached capture / Open report; uncaptured rows still say History required.
- `fix-02-research-screen-phone.png` — screen completed, qualified 3, "not set is not applied".
- `fix-03-ranked-row-A6PSQF-phone.png` — A6PSQF analysed, B ESTABLISHED, no History required on analysed rows.
- `fix-04-report-A6PSQF-phone.png` — genuine replay report, 6 positions.
- `fix-05-compare-CccSh2-vs-A6PSQF-phone.png` — identical windows: "compare is shown", samples 6 vs 6, no `[object Object]`, no "Compare is blocked".

## Offline suite at the tested commit

- Keys unset (`env -u HELIUS_API_KEY -u BIRDEYE_API_KEY -u HELIUS_KEY pytest -q`): **3617 passed**, 440 subtests, 0 failed (8 min 40 s). EXIT 0.
- Keys set (dummy `HELIUS_API_KEY` / `BIRDEYE_API_KEY` / `HELIUS_KEY`): **3617 passed**, 440 subtests, 0 failed (8 min 58 s). EXIT 0. D9 monkeypatch clears keys.
- `npm run build` (frontend): `tsc -b && vite build` OK; `frontend/dist/assets/index-DpiADeUU.js`.

Regression tests (genuine fixtures, decompress + sha256 first):

- `tests/test_research_search_b_defects.py::test_d5_catalog_registers_hash_verified_research_captures`
- `tests/test_research_search_b_defects.py::test_d1_gtfo_sol_excess_saves_report_with_unresolved_basis`
- `tests/test_research_search_b_defects.py::test_d2_completed_episodes_time_order_and_isolate`
- `tests/test_research_search_b_defects.py::test_d3_zero_episodes_is_zero_and_a6ps_shows_six`
- `tests/test_research_search_b_defects.py::test_d4_mixed_wallet_separate_quote_asset_worksheets`
- `tests/test_research_search_b_defects.py::test_d6_analytics_keyed_by_signature`
- `tests/test_research_search_b_defects.py::test_d8_drafts_armed_with_approval_fields_validate`
- `tests/test_research_search_b_defects.py::test_d10_conversions_fees_and_unsupported_listed`
- `tests/test_research_search_b_defects.py::test_d10_a6ps_biggest_token_net_of_fees_vs_raw_sol_delta`
- `tests/test_research_search_b_defects.py::test_independent_recon_address_works_for_catalog_captures`
- `tests/test_screening_routes.py::test_import_identity_sample_screen_is_saved_without_strict_promotion`
- `tests/test_mass_search_product_completion.py::test_unset_thresholds_do_not_pass`

## Independent reviews of the fix commit

- Accounting / C + D1–D10 + screen decision: **ACCEPT** (no requirement-violating findings). See `INDEPENDENT_REVIEWS.md`.
- App-security / A B D5 D7 D8 D9: **ACCEPT** (no requirement-violating findings). Stale-dist nit was fixed by rebuilding `frontend/dist` in `1d1b3ec`.

## Still blocked

- **B3 / PRODUCT_READY:** two newest-first pages are not complete history. Open inventory, unresolved-basis sales, unsupported venues, and the other 89 ranked wallets remain.
- No live dispatch. Drafts stay disabled. Consumed grants stay consumed.
- A second live attempt is only justified if different pages are required. None of D1–D10 required that.
