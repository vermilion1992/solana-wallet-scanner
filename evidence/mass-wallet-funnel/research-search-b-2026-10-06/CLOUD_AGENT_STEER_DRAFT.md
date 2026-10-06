# Draft steer for cloud agent bc-3a674f17-fc60-5cc9-85c0-7fb378501055 (send via CloudAgent action=reply, mode=steer if running)

Branch `cursor/mass-wallet-funnel-v1-1055`. Do NOT call Helius or Birdeye. Do NOT merge, deploy or tunnel. Do NOT enable any grant.
Genuine fixtures are already on the branch:
`evidence/mass-wallet-funnel/research-search-b-2026-10-06/attempt-1/raw/<address>_page{0,1}.json.gz`.
The manifest with sha256 of the raw bytes is `.../CAPTURE_MANIFEST.json`. Window: `capture_catalog.WINDOWS`.
The replay harness is `.../box_driver/ingest.py` and independent recon is `.../box_driver/recon.py`.
Full defect table with repros: `.../DEFECTS.md`.

Fix the following. Each item needs a regression test that uses the genuine fixtures (decompress in test; verify sha256 first):

1. D1: SOL-settled unbacked or excess sales must not crash. `service.reconstruct_candidate` (SOL branch calls
   `metrics.fifo_sale_results`, which raises "Sale exceeds supported inventory") and `g3_history.declared_subset_worksheet`
   (SOL branch drops the whole mint on ValueError) must isolate known cost per mint exactly as the USDC path does
   (`settlement.isolate_known_cost_by_mint`). Keep the remainder as `unresolved_basis` (never zero cost).
   Test: wallet gtfoTELAeEZHUgHetA6umfsCETiBMzJCN4tB2sqCgFL produces a saved report. Matched SOL total = 3.411606267
   (55 known-cost sales), with 4 unresolved-basis sales.
2. D2: `g3_history.completed_episodes` SOL branch must time-order rows (`_ordered_inventory_rows`) before
   `independent_fifo_worksheet`, and isolate known cost instead of zeroing a mint.
   Test: CccSh2xwBvmiwiUwZRjQvktwTQHz8yypSPCKM3tHy1eU = 6 completed flat-to-flat episodes,
   A6PSQFRfv93hoAn1LhQGRT2dYQtjDKX6SE2vN9MEvbot = 6. Shuffled input gives the same counts.
3. D3: `research_profile.build_research_profile` must not use `wallet_completed_episodes or len(known_sells)`.
   0 means 0. Expose the sale count separately. The analytics win-rate denominator and Compare must use the same
   position count. Test: A6PSQF shows 6 completed known-cost positions, not 46.
4. D4: Mixed SOL+USDC wallets must produce per-quote-asset worksheets (separate SOL and USDC totals, no FX) in
   production and independent worksheets, worksheet reconciliation, profile and UI.
   Test: 58PWvekDbHVPFB9FXGQrpumHD16NRajahkYLHiTvxvDL USDC matched = 14739.373324196 (3 sales, 6 unresolved-basis,
   3 open lots). SOL: 0 known-cost sales, 1 unresolved, 1 open lot.
5. D5: `capture_catalog` must register the research-search captures from the committed manifest (multi-page,
   hash-verified, `corpus_kind=GENUINE_REPLAY`, authorization_id `live-ranked100-research-search-2026-10-06-mitch`, WINDOWS).
   Then the ranked list shows `capture_available=true` for those 10 wallets, batch **Analyse** works offline, and
   `tools/independent_capture_reconciliation.py` gains `--address <addr>` for any catalog capture
   (per quote asset, sorted by (timestamp, order, signature)).
6. D6: `analytics.build_wallet_analytics` must key per-row basis and P&L by signature (and split part), not by index into
   the sorted-mint-concatenated `sale_fifo_basis_*`. Quantise the display.
   Test: A6PSQF row `3rd1Tifj…` basis 1 SOL, P&L 0.169276495. All rows equal the independent per-sale results.
7. D7 (UI): analysed rows must not say "History required — not analysed". Compare with identical windows must not show
   "Compare is blocked" or `[object Object]`. Rebuild `frontend/dist`.
8. D8 (config): the research-search draft must use `cycle_end_exclusive`, and the Birdeye zero entry needs the required fields
   (keep `enabled:false`). Add a test that the draft armed with only approval fields passes `validate_live_authorization`.
9. D9: `tests/test_screening_routes.py::test_import_identity_sample_screen_is_saved_without_strict_promotion` must clear
   provider keys via monkeypatch (it fails when `HELIUS_API_KEY` is set).

Do not change the research-screen "unset threshold fails" contract (`test_unset_thresholds_do_not_pass`) without an
explicit product decision. Report it as an open question.
Keep PRODUCT_READY false and B3 BLOCKED. Do not claim profitability.

Done means:
- The full offline suite passes with provider keys unset AND set.
- `npm run build` passes.
- `box_driver/ingest.py` and `box_driver/recon.py` on the new commit give all 10 wallets a report and app == independent per asset and per sale for every completed position.
- Push to the branch and reply with the commit SHA, the test names, and the suite/build output.
