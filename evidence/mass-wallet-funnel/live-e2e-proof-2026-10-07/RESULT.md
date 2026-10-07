# LIVE E2E proof — bbc5bef residuals closed offline

**When:** 2026-10-07
**Base:** `6dc3424c81af117a13c6cfafe451761c74dddb71` (merged PR #6)
**Live box tips:** `cfe6e78` then `bbc5bef` (0 proven leads on both; spend-safety GREEN; $0)
**This pass:** residual code + offline replay on attached pages from both runs
**Branch:** `cursor/live-e2e-proof-1055` (PR #7)
**PRODUCT_READY:** false
**Draft grants:** both `enabled: false`
**Spend this task:** 0 Helius requests, 0 Birdeye requests, $0. No live calls.

## Suites (keys unset + dummy)

| Suite | Result |
|---|---|
| keys unset | re-run after residual + fixture-expectation updates |
| dummy keys (`HELIUS_API_KEY=dummy`, `BIRDEYE_API_KEY=dummy`, `HELIUS_API_KEYS=dummy`) | re-run; dummy keys never sent |
| `scripts/offline_acceptance.py` | checks both live-e2e drafts `enabled:false`; includes bbc5bef residual tests |
| focused | `tests/test_live_e2e_bbc5bef_residuals.py` + spend-safety + filters + live-result (67 passed before full suite) |

## Evidence SHAs

| Artifact | SHA-256 |
|---|---|
| new draft grant `live-e2e-proof-2026-10-09-mitch` | `cda7b98d4d3bf0c219c53f4c37f2c6bc3b62d9480b60ad69d01f1709fc65af62` |
| retired draft grant `live-e2e-proof-2026-10-07-mitch` | `ca4c3f9637d5d8ee11475a8c1704bb964a0a7bed4e126c69e92c65ef9043f410` |
| `dry-run-2026-10-09/DRY_RUN_PLAN.json` | `2c4acff7adfd940db8cad49d0dc90c527bcdacfe09d2ee26f52a35568717bbd7` |
| `PHASE4_OFFLINE_RERUN.json` | `b3d7802c99efce0b450cfd31fddc42b4a40552813dd847fe9cc5a2f6f7b4b9f6` |
| `PHASE4_OFFLINE_RERUN.md` | `78673bf5e909a9d50a04dc659c5dd335706cd9b8bf6c67a6df17256a64e0d4fa` |

Armed local copies must set `draft_artifact_hash` to the **pinned** SHA in `PINNED_DRAFT_HASHES`. Caps cannot exceed `HARD_CEILINGS` (Birdeye 10/300, Helius 1500/15000).

## Spend-safety residuals

- `--live` refuses `SCANNER_LIVE_LEDGER_HOME` / `SCANNER_LIVE_LEDGER_DIR` unless they equal grant `ledger_home`, and refuses if `HOME` ≠ `armed_home`.
- Armed caps are bound by the pinned draft hash **and** hard ceilings. A local commit of an inflated draft cannot raise those ceilings.
- `redact_text` covers stdout/stderr, including top-level `BaseException` / `KeyboardInterrupt` handlers.
- Phase 2 resume screens wallets that are not yet `done`. It never reports `completed` with unscreened wallets.
- Helius default pace is 0.5s (2 rps) with 2s 429 backoff. Every attempt is receipted.

## Correctness

- Phase 4 verifies each saved page hash/receipt. Mismatch or JSON error body is blocked, never treated as an empty covered page.
- `--max-bot-rate` is computed from in-window activity (count / max(window_days, observed span, 1)).
- Planner budgets 2 full-history pages per wallet. Live paging stops on a short or empty page.
- State reflects the latest per-phase outcome (stale `RATE_LIMITED` is cleared on later success).
- Unsupported-program ranking counts only programs in undecoded swaps, by value then count. Pump fee-calc is infra.
- An undecoded earlier buy taints later sales as unknown-basis. Partial-match P&L is not shown.
- Independent OKX decoder in `tools/independent_episode_audit.py` (no scanner import). CfNx9LxW SwapTob: app `+444.861224407` SOL, auditor `+444.861224406` SOL.

## Find wallets

- Bundle/distribution detection: shared funder, multi-signer bundle buys, sell proceeds to co-signer, transfer-in zero basis. Excluded from lead eligibility with an explicit reason; pre-screen ranks them to 0.
- FLASHX, GMGN, Photon, Meteora DLMM Swap2, DFlow DST are reviewed outers on attached txs. Unknown stays blocked. B311 remains unsupported (low value).
- Discovery: `--discovery-source gainers-losers` (30 CU) or `top-traders` (35 CU) from Birdeye docs. Pre-screen rank = (supported-venue share by value) × (has known-basis buys) × (not bundle/bot).
- New 2026-10-09 draft: Birdeye ≤10/≤300 CU; Helius ≤1,500/≤15,000 credits; phase 2 200/2000; phase 3 200/12000.

## Next-run planner (100 pre-screen, 25 kept)

| Phase | Provider | Requests | Units | Cap |
|---|---|---:|---:|---|
| 1 discovery | Birdeye | 1 | 30 CU | 10 / 300 |
| 2 pre-screen | Helius | 200 | 2,000 credits | 200 / 2,000 |
| 3 history (planner min 2 pages) | Helius | 50 | 5,000 credits | 200 / 12,000 |
| 4 offline | — | 0 | 0 | — |
| **Total** | | **1 + 250** | **30 CU + 7,000 credits** | **fits** |

Live Phase 3 may fetch up to ~8 pages per wallet until the credit cap. Worst-case 25 × 8 × 100 credits would exceed 15,000; the ledger stops first. Attached pages were much shorter than 1,000 txs.

## Offline Phase 4 + pre-screen (attached pages from both live runs)

Bounds: report `2026-09-07T07:51:22Z` → `2026-10-07T07:51:22Z`; history `2026-07-09T07:51:22Z`. 78 distinct Phase-2 wallets, 14 with Phase-3 pages. Corpus `GENUINE_REPLAY`. `max_bot_rate` 50/day.

### Which of the ~80 would be chosen for full history

Rank > 0, known-basis buys, not bundle/bot (25 slots available; 3 qualify):

| Wallet | Rank | Venue share | In-window txs | Bot rate | Source |
|---|---:|---:|---:|---:|---|
| `8wmGrD3F5bd439r2k7eJWcHk9UgssuQDLF6kNawBRBRF` | 0.9999 | 0.9999 | 111 | 3.70 | cfe6e78 pre-screen only |
| `DKyapYGfvKCBUTzKSCbTbvVVHbj9yMBKrHrkjdXZ24xx` | 0.9997 | 0.9997 | 262 | 8.73 | bbc5bef pre-screen only |
| `BSTs43nNTc3wBidj8ueY92RJbGn4wxvF8VYYKMVWGdNR` | 0.7939 | 0.7939 | 179 | 5.97 | bbc5bef pre-screen only |

None of the 14 already-fetched Phase-3 wallets remain eligible (bundle / zero-basis / no known buys). Two more wallets have known buys and are not bundle/bot but venue share 0 (A6PS, An9s); rank 0, no full-history slot.

Drop reasons across 78: no_known_basis_buys 43, transfer_in_zero_basis 18, multi_signer_bundle_buy 8, sell_proceeds_to_cosigner 4, eligible 5.

### Phase 4 replay (14 wallets)

| Wallet | Bundle / reasons | Cov count / value | Completed | Realized P&L | Auditor | Lead |
|---|---|---|---:|---|---|---|
| 25865JdB | yes / transfer_in_zero_basis, multi_signer | 0.771 / 0.815 | 10 | SOL +0.411, USDC +12,620 | 12 mixed | insufficient |
| 5Qfie4Tb | yes / transfer_in_zero_basis | 0.473 / 0.397 | 0 | — | 0 | insufficient |
| 6i4nSG48 | yes / transfer_in_zero_basis | 0.989 / 0.999 | 0 | — | 0 | insufficient |
| 8B3KyNP6 | yes / transfer_in_zero_basis | 0.647 / 0.664 | 20 | SOL +173.18 | 17 / +320.99 SOL | insufficient |
| 96d9GKPQ | no | 0 / 0 | 0 | — | 0 | insufficient |
| AMMLTuy9 | yes / multi_signer | 0.968 / 0.022 | 18 | SOL −0.0048 | 0 | insufficient |
| B8wZgcJA | yes / transfer_in_zero_basis | 0 / 0 | 0 | — | 0 | insufficient |
| CfNx9LxW | yes / transfer_in_zero_basis, multi_signer | 0.577 / 0.724 | 1 | SOL **+444.86** | **1 / +444.86 SOL** | insufficient |
| DXCWcAiB | yes / sell_proceeds, multi_signer | 0.967 / 0.031 | 0 | — | 0 | insufficient |
| DtCiNAXm | yes / transfer_in_zero_basis | 0.500 / 1.000 | 0 | — | 0 | insufficient |
| E7KevJv8 | yes / multi_signer | 0.936 / 0.944 | 0 | — | 2 / +37.55 SOL | insufficient |
| FWgfv6jS | yes / sell_proceeds, multi_signer | 0.957 / 0.272 | 0 | — | 0 | insufficient |
| GnDVZMfX | yes / transfer_in_zero_basis | 0.986 / 0.988 | 2 | SOL −6.14 | 1 / +457.03 SOL | insufficient |
| Gv3ksNUG | yes / sell_proceeds, multi_signer | 0.938 / 0.005 | 0 | — | 0 | insufficient |

**0 proven leads.** Coverage still blocks every Phase-3 wallet, and bundle/zero-basis now excludes them from lead eligibility even when a single venue (OKX on CfNx9LxW) reconciles. FLASHX on 96d9GKPQ still fails closed on those attached txs. Full 78-wallet table: `PHASE4_OFFLINE_RERUN.md`.

Hand vs app on named wallets:
- **CfNx9LxW:** app and independent auditor now agree at +444.86 SOL on the SwapTob. Hand +444.8594. Wallet stays non-lead because of transfer-in / multi-signer bundle on the rest of the book.
- **8B3KyNP6:** app 20 / +173.18 after new venues + FIFO taint; auditor 17 / +320.99. Difference is still unsupported-venue / unknown-basis inventory. Bundle excluded.
- **DXCWcAiB:** no partial-match P&L. Undecoded earlier buy taints later sales. Bundle excluded.

## Box commands

See `BOX_COMMANDS.md`. Arm a **local copy** of the 2026-10-09 draft only. Record `armed_home` and `ledger_home`. Set `draft_artifact_hash` to the pinned SHA above. Leave `SCANNER_LIVE_LEDGER_*` unset. Do not enable the committed file.

No merge. No live calls. `PRODUCT_READY` false.
