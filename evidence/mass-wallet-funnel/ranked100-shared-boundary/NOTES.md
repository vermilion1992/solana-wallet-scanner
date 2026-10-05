# Ranked-100 shared decoder boundary + genuine page-0 replay

**Honest partial.** Shared wrap is fixed. This page has **0** reviewed SOL-settled swaps and **0** independently reconciled completed positions. Not MATCH. Not PRODUCT_READY. Not a G3 pass.

## Root causes
1. `_summarize_page` sent raw GTA records into `decode_supported_swaps` (expects a wrapped `signature`/`raw`/`evidence_hash` record). That produced 100× "Missing raw transaction result".
2. After the wrap, 80 Pump outers are pinned-IDL `distribute_fee_to_holders`, not buy/sell/buy_exact_sol_in. The existing Pump swap adapter was not the miss.
3. Real PumpSwap buy/sell/buy_exact_quote_in appear only as inners under an unreviewed Jupiter discriminator (`bb64facc31c4af14`) or other unreviewed outers, and they settle USDC. The reviewed decoder still requires one outer SOL/wSOL route.

## Capture
`evidence/mass-wallet-funnel/ranked100-anchored-validation-live/SOURCE_RESPONSE_page0.json`
sha256 `53a5c6f46ec2e0f8c895df6398116756ae3728892f0a6b702137f56d8624328d` (2,403,585 bytes).

## Classification (100 txs)
See CLASSIFICATION.json. Holder-fee 61, failed 19, unreviewed Jupiter 6, inner PumpSwap without reviewed outer 2, wallet absent 5, unsupported version 1, remainder no reviewed outer swap.

## Fees (not P&L)
Visible integer fees: 0.005654729 SOL (5654729 lamports) across 100 txs; failed-tx fees 0.000171 SOL. Raw SOL delta is not profit.

## Report
Saved application report is an honest partial: fees/failed/holder-fee/unresolved visible; P&L unknown; no forced winner. G1 archive control is unchanged (−0.167725526 AGREE, 4 buys + 1 sell, 598s timings).

## Next data (only if a later grant is separately approved)
See NEXT_DATA_MANIFEST.json. A page whose outer instruction is a reviewed Pump buy/sell/buy_exact_sol_in or a reviewed Jupiter route with SOL/wSOL settlement. This page does not contain that. Do not reuse leftover units.
