# Undecoded / partial venue inventory (attached live captures)

Offline scan of 190 wallets across all six attached raw trees. Ranked by
app-missed outer observations, then absolute wallet SOL delta on those
misses. Infra (System, Token, ComputeBudget, ATA, Memo, Lighthouse) omitted.
PRODUCT_READY false. No live calls.

| Program | Label | Wallets | Txs | App decoded / miss | Auditor decoded / miss | SOL abs miss | Notes |
|---|---|---:|---:|---:|---:|---:|---|
| `675kPX9MHTjS…` | Raydium AMM | 3 | 3801 | 1027 / 2774 | 0 / 3801 | 750.81 | Already reviewed; most misses are non-swap or unreconciled bots |
| `JUP6LkbZbjS1…` | Jupiter | 23 | 3890 | 1889 / 2001 | 1920 / 3890 | 23914.63 | `c1209b3341d69c81` = v1 shared_accounts_route (layout pinned in app); `93f17b64f484ae76` unknown — stays unresolved |
| `6EF8rrecthR5…` | Pump | 15 | 1063 | 65 / 998 | 71 / 1063 | 428.21 | `623691610246ad2b` create / non-swap |
| `DCA265Vj8a9C…` | Jupiter DCA | 2 | 872 | 0 / 872 | 0 / 872 | 709.48 | Recurring DCA, not a spot fill |
| `pAMMBay6oceH…` | PumpSwap | 22 | 3404 | 2802 / 602 | 3306 / 3404 | 61414.02 | Already reviewed |
| `j1o2qRpjcyUw…` | unknown | 3 | 561 | 0 / 561 | 0 / 561 | 1013.08 | Unreviewed |
| `BSfD6SHZigAf…` | unknown | 1 | 358 | 0 / 358 | 216 / 358 | 1795.42 | Single-wallet |
| `DeJBGdMFa1uy…` | unknown | 25 | 284 | 0 / 284 | 0 / 284 | 0.51 | Near-zero SOL |
| `BGUMAp9Gq7iT…` | Bubblegum | 15 | 253 | 0 / 253 | 0 / 253 | 0 | NFT compression, not a spot venue |
| `DF1ow4tspfHX…` | DFlow | 29 | 388 | 194 / 194 | 0 / 388* | 646.35 | *auditor was 0 before this series; wrap `2f3e9bac83cd25c9` is not a swap |
| `G2GMMDKkw3LX…` | G2GM | 22 | 159 | 0 / 159 | 0 / 159 | 0 | Telemetry / 0 SOL |
| `proVF4pMXVaY…` | OKX | 12 | 215 | 82 / 133 | 192 / 215 | 1717.12 | Already reviewed SwapTob |
| `B3111yJCeHBc…` | B311 | 4 | 122 | 0 / 122 | 0 / 122 | 0.38 | Multi-asset wrapper; stays unresolved |
| `routeUGWgWzq…` | unknown router | 2 | 112 | 0 / 112 | 0 / 112 | 3130.84 | Unreviewed |
| `cpamdpZCGKUy…` | Meteora DAMM v2 | 5 | 128 | 26 / 102 | 40 / 128 | 2277.48 | Already reviewed |
| `FLASHX8DrLbg…` | FLASHX | 3 | 122 | 38 / 84 | 0 / 122 | 92.98 | 0x01 wraps are not swaps; unparsed System inners still block some 0x00 swaps |
| `99vQwtBwYtrq…` | Photon | 9 | 68 | 0 / 68 | 0 / 68 | 5961.84 | Pinned, unsupported (no opposing SOL / multi-asset) |
| `T1TANpTeScye…` | Titan-like | 9 | 67 | 0 / 67 | 0 / 67 | 696.82 | Unreviewed |
| `mayan34Vednc…` | Mayan bridge | 4 | 35 | 0 / 35 | 0 / 35 | 257.33 | Bridge, not spot |
| `DGMgNKpqygAR…` | DGMg PumpSwap router | 1 | 1 | 0 / 1* | 0 / 1* | ~0.10 | *jXt 2EtPn1a61imQ — this series decodes it |

## What this series decodes

1. **DFlow** (`f8c69e91e17587c8` / `a8ac184dc59c8765`) in the auditor, independently of the app. Wrap `2f3e9bac83cd25c9` stays non-swap. Unlocks DKx `vYeWFHJd` (+32_679_409_659 Ge87 / 2.997013452 SOL).
2. **DGMg** PumpSwap buy router in both app and auditor (same Pump buy/sell discs; wallet at 1). This was jXt’s one unresolved-basis sale: mint `44y8UUEt…pump`, sell `5do8rV6utoNt` already decoded, buy `2EtPn1a61imQ` was the gap.
3. **FLASHX** non-0x00 opcodes are skipped as non-swaps (same rule as DFlow wraps). 0x00 swaps stay reviewed. B311 / Photon / unknown programs stay unresolved — never a silent zero basis.

B311 embeds inner Jupiter/DFlow discs and moves multiple assets (USDT/WBTC). It is not a single-wallet spot venue.
