# LIVE E2E proof — spend-safety closed, still zero spend

**When:** 2026-10-07
**Base:** `6dc3424c81af117a13c6cfafe451761c74dddb71` (merged PR #6)
**Prior tip attacked:** `edee60848030f489ddea1b4ea622b4c9cb23b218`
**Invariant code:** `1cfd34c1c9ab981f2d19bbb86c4b836b2ed58ff1`
**Evidence + suites:** `70bccd2262256e93f205c486b14041dc7e2106eb`
**Branch tip:** `cursor/live-e2e-proof-1055` (this pin commit)
**PRODUCT_READY:** false
**Spend this task:** 0 Helius requests, 0 Birdeye requests, $0. No live run.

Grok Bot Stage 1 (`edee608`) found spend-safety BROKEN and did not arm a grant.

## Suites (keys unset + dummy)

| Suite | Result |
|---|---|
| keys unset | **3801 passed** / 440 subtests / 1 warning |
| dummy keys (`HELIUS_API_KEY=dummy`, `BIRDEYE_API_KEY=dummy`, `HELIUS_API_KEYS=dummy`) | **3801 passed** / 440 subtests / 1 warning. Dummy keys were never sent. |
| `scripts/offline_acceptance.py` | ok; `PRODUCT_READY` false; live-e2e draft `enabled:false` |
| spend-safety + filters | `tests/test_live_e2e_spend_safety.py` + `tests/test_live_e2e_filters_and_runner.py` |

## Evidence SHAs

| Artifact | SHA-256 |
|---|---|
| `dry-run/DRY_RUN_PLAN.json` | `46b08344ab1cfe11eae1bc8828777a6c9a45bc29b25d3854d806b812ba1a7dd6` |
| `dry-run/RESULTS.json` | `2e68f68312c4ebff88347f041b5f68d872acdc58437da01992d81fe208675d7e` |
| draft grant | `ca4c3f9637d5d8ee11475a8c1704bb964a0a7bed4e126c69e92c65ef9043f410` |
| retired G1 grant | `efacb45deb16af81c759b95e10aeb31081f0fdaacd696ba044c86e52e662cecc` |

Armed local copies must set `draft_artifact_hash` to the draft SHA above.

## Spend-safety invariants now in the runner

- Grant ledger + `GRANT.lock` live under `--ledger-dir` / `SCANNER_LIVE_LEDGER_DIR` / `~/.scanner/live-e2e-ledgers/<authorization_id>`. Caps are per grant, not per output folder.
- Output dir takes `RUN.lock`. Concurrent `--resume` is refused.
- `--live` refuses armed provider/phase caps above the committed draft and a mismatched `draft_artifact_hash`.
- Write-ahead receipt keyed by `(wallet, phase, page, cursor)`. `reserved` / `dispatched` / `consumed` / `failed` = spent. Resume never silently re-sends; `--explicit-retry` counts against the cap.
- Every `Exception` persists `RUN_STATE`. `BaseException` (SIGINT) persists then re-raises. Failed requests are in state spend and the ledger.
- Phase 3 uses `--wallets` when supplied; otherwise phase-2 kept rows. Plan == execution.
- Draft `phase_caps` are enforced at dispatch.
- Birdeye: one documented 30 CU reserve (adapter does not get the store).
- Window `report_start` / `report_end` persist in `RUN_STATE` at first run.
- `--wallets` accepts a file or a comma list; paths ≥255 chars are never passed to `Path.is_file()`.
- Helius auth is the `api-key` header, not the query string.
- `redact_text` runs on every string written to logs/state/results/console. Raw pages: SHA-256 of the original bytes is stored in `pageN.bin.integrity.json` (`original_sha256`); the written `.bin` is the scrubbed copy when a secret appeared (`scrubbed: true`).

## Filters

- FL1: `only_shortlist` / `only_captured` / `only_user_shortlist` accept only JSON `true` / `false` / `null` (else HTTP 422). Load sanitizes junk to false.
- FL2: `window_days` clips reconstructed events/episodes then rebuilds sample counts and scoped P&L. Oracle in `test_fl2_window_days_changes_episodes_and_pnl`.
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

See `BOX_COMMANDS.md`. Arm a **local copy** of the draft only. Do not enable the committed file. Set `draft_artifact_hash` to the draft SHA. Use one `--ledger-dir` for the grant. Do not run two resumes at once.

No merge. No live calls. `PRODUCT_READY` false.
