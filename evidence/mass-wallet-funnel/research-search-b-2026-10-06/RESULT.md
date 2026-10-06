# RANKED100_RESEARCH_SEARCH_HISTORY (grant B): attempt 1

**Outcome: implementation incomplete. Exact remaining blocker: code defects D1–D6 (see `DEFECTS.md`) must be
fixed by the cloud agent and re-verified offline against these captures. This executor had no CloudAgent tool,
so no code was changed. Captures are complete and reusable. A further live attempt is NOT needed for these 10 wallets.**

`PRODUCT_READY` = **false**. B3 = **BLOCKED** (unchanged). No profitability claim. Not MATCH.

## Grant and approval

- Grant `live-ranked100-research-search-2026-10-06-mitch`. Approved by Mitch Hoffman 2026-10-06 15:38 ACDT ("B", verbatim in
  `GRANT_ARMING_RECORD.json`). It was armed **locally only** on the secure box. The repo draft stays `enabled:false`. No enabled grant was committed.
- Wallets: the app's own `research_search_proposal()` selection. These are the top 10 ranked-100 wallets without a capture, ordered by provider trade count.

## Ledger (attempt 1)

| | Value |
| --- | --- |
| Tested app commit | `78678d18d8f74304380588410bdef2ae4bc4530b` (app code = `c34eb2c`) |
| Started / finished | 2026-10-06 15:46:15 → 15:46:17 ACDT (2.2 s) |
| Helius requests | **20 / 20** (all HTTP 200, 100 records each, no retries, concurrency 1) |
| Credits | **200** documented estimate (10 per 100 full txs, helius.dev/docs/billing/credits). The provider sent no billing headers, so there is no provider-reported figure. |
| $ spend | **$0** additional |
| Birdeye | 0 |
| Stop reason | `coverage_objective_reached` (10 wallets × 2 pages) |
| Cumulative (all attempts) | 1 attempt · 20 requests · 200 documented credits · $0 · 0 Birdeye |

Per-request provenance is in `attempt-1/LEDGER.json`: exact JSON-RPC body, pagination token used and returned, first/last signature, block-time span, dispatch/complete timestamps, response headers and raw sha256.

## Capture safety (the G3 SOURCE_RECORDS_DAMAGED hazard)

The app's live transport (`g3_reacquire.helius_gta_http`) is locked to the rank-1 wallet. It also stores a *redacted, re-serialised* body,
so it is not byte-for-byte. A local box driver (`box_driver/live_capture.py`) was used instead. It reuses the app's request
construction (`build_historical_gta_options`, `assert_gta_options_not_widened`, `EXACT_HELIUS_OPTIONS`) and writes
`response.content` verbatim. The sha256 is taken over those exact bytes and re-checked after writing.
Redaction applies only to the request URL: the key is never written.
A self-test against a local mock server confirmed byte-identical files and no key material before the first live call.
After the run, a scan of every box file and of this directory found no key material. Raw bodies are committed gzipped (`-9 -n`, 3.4 MB).
`gunzip` reproduces `raw_sha256`.

## Per-wallet results (window 2026-09-05T13:29:27Z → 2026-10-05T13:29:27Z, acquisition support from 2026-07-07)

Newest-first pages fetched on 2026-10-06 include records after the snapshot cutoff. Those are outside the report window and excluded.

| Wallet | Rank | Pages (txs) | Span (UTC) | App: in-window trades | App: completed positions shown | App matched P&L | Independent matched P&L (`tools/independent_capture_reconciliation._fifo`) | Indep. unresolved-basis / open lots | App classification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CccS…y1eU | 4 | 2 (200) | 10-05 08:55 → 10-06 05:11 | 12 | 6 (flat-to-flat counted 0, D2) | +0.251129813 SOL | +0.251129813 SOL (6 sales), **AGREE** | 0 / 0 | analysed-incomplete; screen zero-qualified |
| gtfo…CgFL | 2 | 2 (200) | 10-04 05:35 → 10-06 04:59 | 75 | — (**report failed, D1**) | — | +3.411606267 SOL (55 sales) | 4 / 0 | not evaluated (no report) |
| A6PS…vbot | 15 | 2 (200) | 10-03 05:28 → 10-06 05:02 | 52 | **46 (should be 6, D3)** | +297.232334822 SOL | +297.232334822 SOL (46 sales), **AGREE** (totals); per-row display wrong (D6) | 0 / 0 | analysed-incomplete; zero-qualified |
| An9s…LYSB | 17 | 2 (200) | 10-03 18:15 → 10-05 08:40 | 0 (0 decoded swaps) | 0 | — | — | — | analysed-incomplete |
| CRXo…V68U | 90 | 2 (200) | 09-26 06:14 → 10-05 08:51 | 0 (0 decoded) | 0 | — | — | — | analysed-incomplete |
| BVZt…Y9n9 | 10 | 2 (200) | 09-29 11:59 → 10-05 22:46 | 2 (1 SOL, 1 USDC) | 0 | — | — (both sales unbacked) | 1 SOL + 1 USDC / 0 | analysed-incomplete |
| AW6P…MzD6 | 56 | 2 (200) | 10-01 03:18 → 10-06 02:11 | 0 (0 decoded) | 0 | — | — | — | analysed-incomplete |
| 58PW…xvDL | 53 | 2 (200) | 09-23 03:57 → 10-06 03:57 | 20 (18 USDC, 2 SOL) | 2 | **none (mixed settlement, D4)** | +14739.373324196 USDC (3 sales); SOL none | USDC 6 / 3; SOL 1 / 1 | analysed-incomplete |
| DQ7n…9Cys | 14 | 2 (200) | 10-02 23:36 → 10-06 04:24 | 1 (USDC) | 0 | — | — (1 unbacked sale) | 1 / 0 | analysed-incomplete |
| BSN5…BtCM | 11 | 2 (200) | 09-23 16:41 → 09-29 00:20 | 0 (0 decoded) | 0 | — | — | — | analysed-incomplete |

- **Qualifying accounts: 0.** Research screen outcome `inconclusive` (90 inconclusive, 9 zero-qualified, 0 qualified, 1 not-executed of 100).
  Under the current contract, every unset threshold of the 10 fails, so with only the two fixed defaults no wallet can qualify.
  That rule is a product decision, flagged in `DEFECTS.md` and not changed here.
  On corrected counts, CccS (6), A6PS (6) and gtfo (≥ 3 closed mints) would meet `min_completed_known_cost=1` and `min_sample_positions=3`.
  That is still only evidence class 2 (positive known basis, incomplete history), never account performance.
- P&L is matched P&L conditional on captured inventory. It is not net realised, not wallet-wide and not copyable.
  When tips exist, SOL P&L is gross of network fees and tips that the decoder leaves unallocated (D10).
- 4 of 10 wallets had 0 decoded swaps (unreviewed venues, tx version 1, tip flows), see D10.

## App vs independent reconciliation

Where the app produced a worksheet, the per-asset totals AGREE exactly (CccS, A6PS). The app is missing results for gtfo (D1) and 58PW USDC (D4).
The per-row display is misattributed for every multi-mint wallet (D6). Not all wallets agree yet. Each disagreement is explained in `DEFECTS.md`, with a fix and regression test specified.
Outputs: `recon/<address>.json`, `recon/SUMMARY.json`. Caveat: the reconciliation's FIFO is independent, but it shares the app decoder.

## App visibility (390×844 Playwright Chromium, phone-sized browser emulation, not a physical phone)

The app was launched with `./run.sh --data-dir <copy of the replay data dir> --no-browser` on loopback.
Unauthenticated `/api/state` returned 401. There were no external requests and no page errors.
Screenshots are in `screenshots/`: the ranked list shows the analysed wallets with **Open report**, reports open, and Compare CccS vs A6PS works.
These images show the attempt-1 **pre-fix** state, including defects D3/D6/D7 visible on screen.
The replay used `box_driver/ingest.py`, which patches the catalog in-process because of D5. A fresh checkout cannot reproduce this yet.

## Offline suite at the tested commit

With provider keys exported: 3046 passed, then stopped on 1 failure (D9, which depends on key presence).
With keys unset: see `TESTS.md`.

## Next step

Send `CLOUD_AGENT_STEER_DRAFT.md` to cloud agent `bc-3a674f17-fc60-5cc9-85c0-7fb378501055`. When the fix commit passes the full suite and build, pull it and re-run
`box_driver/ingest.py` and `box_driver/recon.py` **offline** on these captures (0 requests).
A second live attempt is only justified if a fix requires different pages. None of D1–D9 do.
