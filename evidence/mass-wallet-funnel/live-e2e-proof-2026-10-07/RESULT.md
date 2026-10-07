# LIVE E2E proof — box-ready, zero spend

**When:** 2026-10-07
**Base:** `6dc3424c81af117a13c6cfafe451761c74dddb71`
**PRODUCT_READY:** false
**Spend this task:** 0 Helius requests, 0 Birdeye requests, $0

## What is ready

- Filters F1–F4: reconstructed view re-evaluates reconciled values; unset does not hide; coverage filter is count AND value; `min_completed_known_cost` and `min_sample_positions` bind distinct fields; save rejects non-numeric/OOR with HTTP 422; read path sanitizes stored bad filters.
- Proof gates 0.99 / 0.95 stay non-weakenable (`proof_gates.weakenable_via_filter_api=false`).
- `scripts/live_e2e.py`: phases 1–4, dry-run recorder, durable store, reserve-before-transport on `--live`, single-use receipts, SHA-256 raw bytes, hard stop at caps.
- G1 committed grant retired (`enabled:false`). Draft grant `live-e2e-proof-2026-10-07-mitch` is `enabled:false` in repo.
- Pre-screen reports OKX SwapTob, DFlow, L2TExMFK, RFQ, Token-2022 observed-only.

## Dry-run counts (10 Search B wallets + discovery)

| Phase | Provider | Requests | Units | Cap |
|---|---|---:|---:|---|
| 1 discovery | Birdeye | 1 | 30 CU | 3 / 91 |
| 2 pre-screen | Helius | 20 | 200 credits | 500 / 5,000 |
| 3 history (empty recorder page) | Helius | 10 | 1,000 credits worst-case | 500 / 5,000 |
| 4 offline | — | 0 | 0 | — |
| **Total** | | **1 + 30** | **30 CU + 1,200 credits** | **within caps** |

Live phase 3 continues paging until the window is covered or the cap is hit. Dry-run stops after one empty full page per wallet.

## GTA page size

Documented max limit is 1,000. Signatures-only is 10 credits flat. Full is 10 credits / 100 txs. `limit=1000` full reduces **requests**, not credits, versus ten `limit=100` pages. Next-capture freeze stays `limit=100` and is unused here.

Arm a **local copy** of the draft only. Do not enable the committed file.
