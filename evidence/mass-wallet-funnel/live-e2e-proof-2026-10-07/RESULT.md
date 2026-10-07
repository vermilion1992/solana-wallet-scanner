# LIVE E2E proof — live-result blockers closed offline

**When:** 2026-10-07
**Base:** `6dc3424c81af117a13c6cfafe451761c74dddb71` (merged PR #6)
**Live box tip:** `cfe6e78aa6e15d081e29be65caaead9633f1b4b0` (0 proven leads / 11 Phase-3 wallets)
**Live-result code:** `099772f033412c18383a86c39848594e483473c3`
**Branch:** `cursor/live-e2e-proof-1055` (PR #7)
**PRODUCT_READY:** false
**Draft grant:** `enabled:false`
**Spend this task:** 0 Helius requests, 0 Birdeye requests, $0. No live calls. Phase 4 replayed the attached `cfe6e78` raw pages offline.

## Suites (keys unset + dummy)

| Suite | Result |
|---|---|
| keys unset | **3817 passed** / 440 subtests / 1 warning |
| dummy keys (`HELIUS_API_KEY=dummy`, `BIRDEYE_API_KEY=dummy`, `HELIUS_API_KEYS=dummy`) | **3817 passed** / 440 subtests / 1 warning. Dummy keys were never sent. |
| `scripts/offline_acceptance.py` | ok; `PRODUCT_READY` false; live-e2e draft `enabled:false` |
| spend-safety + filters + live-result | `tests/test_live_e2e_spend_safety.py` + `tests/test_live_e2e_filters_and_runner.py` + `tests/test_live_e2e_live_result_fixes.py` |

## Evidence SHAs

| Artifact | SHA-256 |
|---|---|
| `dry-run/DRY_RUN_PLAN.json` | `46b08344ab1cfe11eae1bc8828777a6c9a45bc29b25d3854d806b812ba1a7dd6` |
| `dry-run/RESULTS.json` | `2e68f68312c4ebff88347f041b5f68d872acdc58437da01992d81fe208675d7e` |
| `PHASE4_OFFLINE_RERUN.json` | `e9b4e82f1a60c62b35b241b17a897b22761d8852d9bbf6669c4af9591a75f191` |
| draft grant | `ca4c3f9637d5d8ee11475a8c1704bb964a0a7bed4e126c69e92c65ef9043f410` |
| retired G1 grant | `efacb45deb16af81c759b95e10aeb31081f0fdaacd696ba044c86e52e662cecc` |

Armed local copies must set `draft_artifact_hash` to the draft SHA above.

## Spend-safety invariants now in the runner

- Grant ledger + `GRANT.lock` live under `$SCANNER_LIVE_LEDGER_HOME/<authorization_id>` (default `~/.scanner/live-e2e-ledgers/<id>`). `--ledger-dir` must equal that home. A second ledger dir for the same grant is refused.
- Output dir takes `RUN.lock`. Concurrent `--resume` is refused.
- `--live` requires `draft_artifact_hash` equal to the **git object** of the committed draft (`git show HEAD:config/…-draft.json`). Working-tree edits and a missing hash are refused. Armed provider caps must be ≤ the git draft. Missing `phase_caps` inherit the draft.
- Write-ahead receipt keyed by `(wallet, phase, page, cursor)`. `reserved` / `dispatched` / `consumed` / `failed` = spent. Resume never silently re-sends; `--explicit-retry` **appends** `:retryN` and counts against the cap.
- Every `Exception` persists `RUN_STATE`. `BaseException` (SIGINT) persists then re-raises. Failed requests are in state spend and the ledger.
- Phase 3 uses `--wallets` when supplied; otherwise phase-2 kept rows. Plan == execution.
- Draft `phase_caps` are enforced at dispatch.
- Birdeye: one documented 30 CU reserve (adapter does not get the store).
- Window `report_start` / `report_end` persist in `RUN_STATE` at first run. `--resume` with a different `--window-days` is refused.
- `--wallets` accepts a file or a comma list; paths ≥255 chars are never passed to `Path.is_file()`.
- Helius auth is the documented `?api-key=` query param. The key never reaches disk, logs, receipts, or exception text.
- `redact_text` runs on every string written to logs/state/results/console. Raw pages: SHA-256 of the **provider bytes before scrub** is `original_sha256` (Birdeye included). A missing raw page is `MISSING_CAPTURE` / blocked, never an empty covered page.
- Phase 4 replays captures as `GENUINE_REPLAY` (offline). `GENUINE_LIVE` is not used on saved pages.
- Pre-screen resolves `programIdIndex` via accountKeys + loadedAddresses, including inner instructions. Token-2022 and Lighthouse are infra, not venue blockers.
- Qualification, completed counts and realized P&L use only episodes closed inside the report window. `window_days` anchors to report end, not last activity, and drops currencies with no in-window episodes.
- Token-2022 transfer / transferChecked / transferCheckedWithFee decode from instruction bytes, including transfer-fee extension amounts. OKX SwapTob is a reviewed outer (payer 0, user token accounts 1/2). DFlow layout is pinned but stays blocked until a real attached tx reconciles. Lighthouse is non-economic infra. FLASHX / B311 stay unsupported.

## Filters

- FL1: `only_shortlist` / `only_captured` / `only_user_shortlist` accept only JSON `true` / `false` / `null` (else HTTP 422). Load sanitizes junk to false.
- FL2: `window_days` clips to `[report_end - days, report_end)`. Currencies with no in-window episodes are dropped. Oracle in `test_fl2_window_days_changes_episodes_and_pnl` plus `test_fl2a_drops_stale_currency_and_fl2b_anchors_report_end`.
- FL3: user numbers must match `^-?(?:0|[1-9]\d*)(?:\.\d+)?$`. `1_000`, Unicode digits, spaces, `1e3`, `+3` are 422.

## Dry-run counts (10 Search B wallets + discovery)

| Phase | Provider | Requests | Units | Cap |
|---|---|---:|---:|---|
| 1 discovery | Birdeye | 1 | 30 CU | 3 / 91 |
| 2 pre-screen | Helius | 20 | 200 credits | 500 / 5,000 (phase 2: 200 / 2,000) |
| 3 history (empty recorder page) | Helius | 10 | 1,000 credits worst-case | 500 / 5,000 (phase 3: 300 / 3,000) |
| 4 offline | — | 0 | 0 | — |
| **Total** | | **1 + 30** | **30 CU + 1,200 credits** | **within caps** |

Live phase 3 continues paging until the window is covered or the cap is hit. Dry-run stops after one empty full page per wallet.

## GTA page size

Documented max limit is 1,000. Signatures-only is 10 credits flat. Full is 10 credits / 100 txs. `limit=1000` full reduces **requests**, not credits, versus ten `limit=100` pages. Next-capture freeze stays `limit=100` and is unused here.

## Box commands

See `BOX_COMMANDS.md`. Arm a **local copy** of the draft only. Do not enable the committed file. Set `draft_artifact_hash` to the git-object SHA of the committed draft. Use one ledger home for the grant. Do not run two resumes at once.

No merge. No live calls. `PRODUCT_READY` false.

## Phase 4 offline rerun (attached `cfe6e78` pages)

Bounds: report `2026-09-07T07:51:22Z` → `2026-10-07T07:51:22Z`; history start `2026-07-09T07:51:22Z`. 11 wallets, 23 raw pages. Corpus `GENUINE_REPLAY`. Independent auditor = `tools/independent_episode_audit.py` with those same bounds (pinned venues only; no scanner import).

| Wallet | Cov count / value | In-window completed | Realized P&L (episode vector) | Auditor (in-window clean / net) | Lead | vs live table §3.1 |
|---|---|---:|---|---|---|---|
| 25865JdB | 0.771 / 0.815 | **10** | SOL +0.411, USDC +12,620.49 | 12 mixed: USDC 26,240.57 / SOL +0.411 | conditional | Live profile 15 / window 10 with worksheet SOL **-1.614** + USDC 9,919. Now 10 in-window only. SOL matches auditor. USDC is the app subset (10 vs 12). |
| 5Qfie4Tb | 0.456 / 0.387 | **0** | — | 0 | insufficient | Live profile **21** (all pre-window) and SOL -22.8. Now 0 / hidden. |
| 6i4nSG48 | 0.989 / 0.999 | **0** | — | 0 | insufficient | Live profile 1 / window 0 still showed SOL -0.002. Now hidden. |
| 8B3KyNP6 | 0.537 / 0.550 | 17 | SOL **+320.992** | **17 / +320.992 exact** | conditional | Same as live app/auditor. Hand raw was 38 / +356.73: the extra +35.7 is unsupported venues (still 63/136 in-window swaps). |
| 96d9GKPQ | 0 / 0 | 0 | — | 0 | insufficient | Unchanged. FLASHX is 100% of in-window swaps. |
| AMMLTuy9 | 0.968 / 0.022 | 18 | SOL **-0.0048** | 0 (21 unresolved) | conditional | Live episode net -0.0048 / worksheet -0.0076. Coverage value 0.004 → 0.022 (Token-2022/Lighthouse no longer venue-block). Still far below 0.95. |
| B8wZgcJA | 0 / 0 | 0 | — | 0 | insufficient | Unchanged. B311 is 100% of in-window swaps. |
| CfNx9LxW | 0.577 / 0.724 | 1 | SOL **+444.86** | 0 | conditional | Live 0 completed. One new known-cost close after Token-2022/OKX. Auditor (pinned venues only) still 0. Coverage 0.463/0.340 → 0.577/0.724. |
| DtCiNAXm | 0.500 / 0.9996 | 0 | — | 0 | insufficient | Unchanged. |
| E7KevJv8 | 0.936 / 0.944 | 0 | — | 1 / +21.28 SOL | insufficient | Token-2022 coverage 0.766/0.711 → 0.936/0.944. Still below 0.99/0.95. App has no clean known-cost flatten; auditor's one episode is outside the app subset. |
| GnDVZMfX | 0.964 / 0.948 | **0** | — | 1 / +457.03 SOL | insufficient | Live profile **2** (both pre-window) and scoped SOL **+539.9**. Now 0 / hidden. Hand in-window 3 / +444.28 includes unsupported-venue deltas the app does not decode. Auditor 1 / +457.03 is its pinned-venue FIFO. |

**0 proven leads.** Coverage still blocks every wallet (gate count ≥ 0.99 AND value ≥ 0.95). Remaining value/count gaps: FLASHX (96d9GKPQ), B311 (B8wZgcJA), DFlow (layout pinned; ephemeral wSOL lifecycle unresolved — not guessed), leftover Jupiter/OKX-adjacent routes that fail balance-delta reconcile.

Hand vs app on the two named wallets:
- **8B3KyNP6:** app/auditor +320.992 over 17 episodes. Hand +356.73 over 38. Difference is unsupported-venue swaps counted in the raw SOL/token FIFO and excluded here.
- **GnDVZMfX:** app 0 in-window completed (the live +539.9 was pre-window + out-of-window sales). Hand 3 / +444.28. Auditor 1 / +457.03. The app is fail-closed on unknown venues; it does not claim the hand or auditor extras.
