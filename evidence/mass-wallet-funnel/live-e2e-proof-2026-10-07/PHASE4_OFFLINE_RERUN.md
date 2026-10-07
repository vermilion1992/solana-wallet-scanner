# Offline Phase 4 replay (all four live-run attached pages)

Bounds: report `2026-09-07T10:52:20Z` → `2026-10-07T10:52:20Z`; history start `2026-07-09T10:52:20Z`.
26 Phase-3 wallets. `max_bot_rate`=25/day. PRODUCT_READY false. No live calls.
Decoder `spot-v17-jup-native-settle-token2022-close-v1`.

## Phase 4 replay

| Wallet | history_complete | Bundle / pair flags | controlled_pair | Flag verdict | Venue share | Cov count / value | In-window completed | Realized P&L | Auditor clean / net | App − auditor | Lead | Blocker |
|---|---|---|---|---|---:|---|---:|---|---|---|---|---|
| `BkRUpYSo` | no (pagination_token_remaining_earlier_history) | transfer_in_zero_basis | — | unknown/zero basis (later-sold or gifted mint) | 1.0000 | 0.495677233 / 0.082552061 | 0 | None | — | — | insufficient_evidence | pagination_token_remaining_earlier_history |
| `AUiycVsy` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.4238 | 0.2 / 0.08256424 | 0 | None | — | — | insufficient_evidence | 0 completed episodes; 2 open lots; sensitivity not established; coverage_blocked |
| `6qVcd9kp` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.3467 | 0.125 / 0.000457643 | 0 | None | — | — | insufficient_evidence | 0 completed episodes; 1 open lots; sensitivity not established; coverage_blocked |
| `25865JdB` | yes (no_leftover_pagination_token) | transfer_in_zero_basis,multi_signer_bundle_buy | — | bundle: material same-swap partner (keep); unknown/zero basis (later-sold or gifted mint) | 0.0000 | 0.77124183 / 0.814790942 | 10 | 0.410996069 | 12 / None | — | insufficient_evidence | transfer_in_zero_basis |
| `4WFgxbFD` | no (unknown_basis_sale) | transfer_in_zero_basis,multi_signer_bundle_buy | — | bundle: material same-swap partner (keep); unknown/zero basis (later-sold or gifted mint) | 0.9880 | 0.752475248 / 0 | 12 | 87.27162175 | 13 / 208.269877931 | -120.998256181 | insufficient_evidence | unknown_basis_sale |
| `5Qfie4Tb` | no (unknown_basis_sale) | transfer_in_zero_basis | — | unknown/zero basis (later-sold or gifted mint) | 0.9757 | 0.473451327 / 0.396756262 | 0 | None | — | — | insufficient_evidence | unknown_basis_sale |
| `6i4nSG48` | yes (wallet_created_in_range) | transfer_in_zero_basis | — | unknown/zero basis (later-sold or gifted mint) | 0.4996 | 0.994535519 / 0.999708937 | 0 | None | — | — | insufficient_evidence | transfer_in_zero_basis |
| `8B3KyNP6` | yes (no_leftover_pagination_token) | transfer_in_zero_basis | — | unknown/zero basis (later-sold or gifted mint) | 0.7986 | 0.647058824 / 0.663924597 | 20 | 173.180468671 | 17 / 320.992044616 | -147.811575945 | insufficient_evidence | transfer_in_zero_basis |
| `8wmGrD3F` | yes (wallet_created_in_range) | transfer_in_zero_basis,multi_signer_bundle_buy | — | bundle: material same-swap partner (keep); unknown/zero basis (later-sold or gifted mint) | 0.0000 | 0.990384615 / 0.990957737 | 2 | 358.971593577 | 3 / 414.674391225 | -55.702797648 | insufficient_evidence | transfer_in_zero_basis |
| `96d9GKPQ` | yes (wallet_created_in_range) | transfer_in_zero_basis | — | unknown/zero basis (later-sold or gifted mint) | 1.0000 | 0 / 0 | 0 | None | — | — | insufficient_evidence | transfer_in_zero_basis |
| `9R3m89gX` | yes (wallet_created_in_range) | multi_signer_bundle_buy,transfer_in_zero_basis,controlled_pair | 8zxkmeqHrpmqyzCSGxLNWZ4W7ZgjwHuo4HV11ALceNAg | controlled_pair (not a lead): 8zxkmeqH co-signs and dominates funding (100.00%) and withdrawals (100.00%); bundle: material same-swap partner (keep); unknown/zero basis (later-sold or gifted mint) | 1.0000 | 0.878718535 / 0.595349492 | 87 | -362.320121371 | 172 / 8220.714490507 | -8583.034611878 | insufficient_evidence | multi_signer_bundle_buy |
| `AMMLTuy9` | yes (wallet_created_in_range) | multi_signer_bundle_buy,transfer_in_zero_basis | — | bundle: material same-swap partner (keep); unknown/zero basis (later-sold or gifted mint) | 0.9165 | 0.98089172 / 0.022536921 | 20 | -0.009025192 | — | — | insufficient_evidence | multi_signer_bundle_buy |
| `AN344abT` | yes (wallet_created_in_range) | multi_signer_bundle_buy,transfer_in_zero_basis,sell_proceeds_to_cosigner | — | bundle: material same-swap partner (keep); proceeds to material co-signer; unknown/zero basis (later-sold or gifted mint) | 1.0000 | 0.932960894 / 0.186643139 | 6 | -73.641140525 | 7 / -77.417969728 | 3.776829203 | insufficient_evidence | multi_signer_bundle_buy |
| `B8wZgcJA` | yes (no_leftover_pagination_token) | transfer_in_zero_basis | — | unknown/zero basis (later-sold or gifted mint) | 0.1807 | 0 / 0 | 0 | None | — | — | insufficient_evidence | transfer_in_zero_basis |
| `BRjVGhFn` | yes (wallet_created_in_range) | transfer_in_zero_basis,controlled_pair | 8zxkmeqHrpmqyzCSGxLNWZ4W7ZgjwHuo4HV11ALceNAg | controlled_pair (not a lead): 8zxkmeqH co-signs and dominates funding (99.98%) and withdrawals (99.38%); unknown/zero basis (later-sold or gifted mint) | 1.0000 | 0.782135076 / 0.661087475 | 61 | 44.384845345 | 99 / 4232.114655222 | -4187.729809877 | insufficient_evidence | transfer_in_zero_basis |
| `BSTs43nN` | yes (wallet_created_in_range) | transfer_in_zero_basis,controlled_pair | 98YDfUMbZ91Mk9PfHCyBLG6t5Gh1TWQvNUygUQV8gCtU | controlled_pair (not a lead): 98YDfUMb co-signs and dominates funding (100.00%) and withdrawals (100.00%); unknown/zero basis (later-sold or gifted mint) | 0.0503 | 1 / 1 | 1 | 218.241694699 | 1 / 218.2416947 | -1E-9 | insufficient_evidence | transfer_in_zero_basis |
| `CfNx9LxW` | no (unknown_basis_sale) | transfer_in_zero_basis,multi_signer_bundle_buy,controlled_pair | G5GFpTfMFPU31nmXzu5C7198RqXiVC49ToUA1h5pGyph | controlled_pair (not a lead): G5GFpTfM is a fee-paying / swap co-signer that later sweeps proceeds; bundle: material same-swap partner (keep); unknown/zero basis (later-sold or gifted mint) | 1.0000 | 0.577235772 / 0.723830738 | 1 | 444.861224407 | 1 / 444.861224406 | 1E-9 | insufficient_evidence | unknown_basis_sale |
| `DKyapYGf` | yes (wallet_created_in_range) | transfer_in_zero_basis,multi_signer_bundle_buy,controlled_pair | Sm71cE7vTst5hTT5bPFqfQsh86ouJXSau12au5t6RZA | controlled_pair (not a lead): Sm71cE7v co-signs and dominates funding (100.00%) and withdrawals (100.00%); bundle: material same-swap partner (keep); unknown/zero basis (later-sold or gifted mint) | 0.1747 | 0.992125984 / 0.985793097 | 2 | 2.486627429 | 3 / 512.633417334 | -510.146789905 | insufficient_evidence | transfer_in_zero_basis |
| `DXCWcAiB` | yes (wallet_created_in_range) | multi_signer_bundle_buy,sell_proceeds_to_cosigner,transfer_in_zero_basis | — | bundle: material same-swap partner (keep); proceeds to material co-signer; unknown/zero basis (later-sold or gifted mint) | 0.9963 | 0.983606557 / 0.035192429 | 0 | None | — | — | insufficient_evidence | multi_signer_bundle_buy |
| `DtCiNAXm` | yes (wallet_created_in_range) | transfer_in_zero_basis | — | unknown/zero basis (later-sold or gifted mint) | 0.3658 | 0.5 / 0.999584059 | 0 | None | — | — | insufficient_evidence | transfer_in_zero_basis |
| `E7KevJv8` | yes (wallet_created_in_range) | transfer_in_zero_basis | — | unknown/zero basis (later-sold or gifted mint) | 0.6226 | 0.957446809 / 0.963053044 | 1 | 21.281202681 | 2 / 37.547732525 | -16.266529844 | insufficient_evidence | transfer_in_zero_basis |
| `FWgfv6jS` | yes (wallet_created_in_range) | multi_signer_bundle_buy,sell_proceeds_to_cosigner,transfer_in_zero_basis | — | bundle: material same-swap partner (keep); proceeds to material co-signer; unknown/zero basis (later-sold or gifted mint) | 0.9992 | 0.956521739 / 0.271892428 | 0 | None | — | — | insufficient_evidence | multi_signer_bundle_buy |
| `GnDVZMfX` | yes (wallet_created_in_range) | transfer_in_zero_basis | — | unknown/zero basis (later-sold or gifted mint) | 0.0000 | 0.985507246 / 0.988437893 | 2 | -6.137550943 | 1 / 457.027411065 | -463.164962008 | insufficient_evidence | transfer_in_zero_basis |
| `Gv3ksNUG` | yes (wallet_created_in_range) | multi_signer_bundle_buy,sell_proceeds_to_cosigner,transfer_in_zero_basis | — | bundle: material same-swap partner (keep); proceeds to material co-signer; unknown/zero basis (later-sold or gifted mint) | 0.9995 | 0.96875 / 0.006107339 | 0 | None | — | — | insufficient_evidence | multi_signer_bundle_buy |
| `jXtCVtdQ` | yes (wallet_created_in_range) | transfer_in_zero_basis | — | unknown/zero basis (later-sold or gifted mint) | 0.9970 | 0.997109827 / 0.989759154 | 43 | 302.359008744 | 44 / 310.784669009 | -8.425660265 | insufficient_evidence | transfer_in_zero_basis |
| `wae8YMC7` | yes (wallet_created_in_range) | transfer_in_zero_basis,multi_signer_bundle_buy,controlled_pair | V5wL73paYB8snnN4RGsyoHGQ3v1qnjPienLCmbqTbmt | controlled_pair (not a lead): V5wL73pa is a fee-paying / swap co-signer that later sweeps proceeds; bundle: material same-swap partner (keep); unknown/zero basis (later-sold or gifted mint) | 1.0000 | 0.870496592 / 0.632272895 | 10 | -51.216373895 | 113 / 7401.957035847 | -7453.173409742 | insufficient_evidence | transfer_in_zero_basis |

## jXtCVtdQ after Jupiter native-settle + Token-2022 skip

Pages: 2. Decoder `spot-v17-jup-native-settle-token2022-close-v1`.
Coverage count/value: `0.997109827` / `0.989759154`.
App completed trades: `43`; realized P&L SOL: `302.359008744`.
pnl_scope: `decoded_subset`. App realized P&L is the decoded-subset FIFO, not the wallet's full balance-delta P&L. A high-coverage gap versus the auditor (e.g. 9R3m89gX −362 vs +8,221) means the decoded sample is not representative; unknown-basis / incomplete history blocks a lead.
Auditor: `44` clean / `310.784669009` net; unresolved sales `1`.
Flags: `transfer_in_zero_basis`. controlled_pair: `none`.
Buy/sell events decoded: `346`. Uncovered txs: `105`.

Uncovered tx causes (venue: reason → count):

- `unknown: no_outer_program`: 49
- `unknown: No reviewed outer spot swap; transfers and balances alone do not prove trading`: 41
- `unknown: Investigated wallet is absent from transaction account keys`: 14
- `unknown: Temporary wrapped SOL closure and rent refund must belong to the investigated wallet`: 1

App-vs-auditor gap is one episode / −8.43 SOL (43 vs 44 clean; 302.36 vs 310.78).
Jupiter is closed (346 buy/sell; 0 remaining Jupiter gaps). The 105 uncovered
txs are non-swap: 49 compiled pages with no resolved outer programId, 41
plain transfers, 14 records whose account keys omit jXt, and 1 wSOL-close
attribution. Those stay in the auditor and out of app P&L.

jXt is **not** a `controlled_pair` (exchange `is6MTRHE` funding does not
co-sign or take return flow). It is still not a lead: `transfer_in_zero_basis`
(later-sold gifted mints).

## Phase-2 notables (no Phase-3 pages in the four-run attach)

| Wallet | bot_rate | Flags | Verdict |
|---|---:|---|---|
| `AGqKFZoK` | 17.0 | multi_signer_bundle_buy, sell_proceeds_to_cosigner, transfer_in_zero_basis | keep: material bundle partner |
| `DrBCfATh` | 292.6 | controlled_pair (also bot) | keep: fee-payer sweeps proceeds; not a lead |
| `953V4zSz` | 132.5 | bot_rate | keep dropped (genuine HFT) |
| `wzafXT9G` | 500.0 | bot_rate | keep dropped (genuine HFT) |

`AUiycVsy` / `6qVcd9kp` no longer flag `multi_signer_bundle_buy` (passive Jupiter `sighWH8K`).
`DKyapYGf` history_complete is now yes (`wallet_created_in_range`; same-second preBalance-0 tie-break).
`8wmGrD3F` / `Gv3ksNUG` stay material-bundle flagged.

## #12 9R3m89gX app −362 vs auditor +8,221

`pnl_scope=decoded_subset`. App FIFO is the decoded sample only (coverage value 0.595).
The auditor reconstructs every balance-delta trade, including unreviewed outers.
Neither number is the wallet's economic P&L as a lead: `transfer_in_zero_basis`,
`multi_signer_bundle_buy`, and `controlled_pair` (8zxkmeqH) all block it.

JSON: `evidence/mass-wallet-funnel/live-e2e-proof-2026-10-07/PHASE4_OFFLINE_RERUN.json`
