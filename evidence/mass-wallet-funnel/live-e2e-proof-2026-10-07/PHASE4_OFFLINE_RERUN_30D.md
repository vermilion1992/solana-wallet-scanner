# Offline Phase 4 replay (30d) — all six live-run attached pages

Bounds: report `2026-09-07T10:52:20Z` → `2026-10-07T10:52:20Z`; history start `2020-03-16T00:00:00Z`.
38 Phase-3 wallets. `max_bot_rate`=25/day. PRODUCT_READY false. No live calls.
Decoder `spot-v20-dflow-ata-rent-v1`.

## Phase 4 replay

| Wallet | history_complete | Bundle / pair flags | controlled_pair | Flag verdict | Venue share | Cov count / value | In-window completed | Realized P&L | Quarantine never-sold / sold | Audit | Auditor clean / net | App − auditor | Lead | Blocker |
|---|---|---|---|---|---:|---|---:|---|---|---|---|---|---|---|
| `BkRUpYSo` | no (pagination_token_remaining_earlier_history) | none | — | no exclusion flag | 1.0000 | 0.498559078 / 0.082552061 | 0 | None | 0 / 0 | not_independently_audited | — | — | insufficient_evidence | pagination_token_remaining_earlier_history |
| `8B3KyNP6` | yes (no_leftover_pagination_token) | none | — | no exclusion flag | 0.7986 | 0.647058824 / 0.663924597 | 20 | 173.180468671 | 1 / 8 | not_independently_audited | 17 / 320.992044616 | -147.811575945 | conditional_captured_lot_result | 1 open lots; 22 unresolved-basis sales; coverage gate requires count AND value; not independently audited; coverage_blocked |
| `E7KevJv8` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.6226 | 0.957446809 / 0.963053044 | 1 | 21.281202681 | 0 / 2 | not_independently_audited | 2 / 37.546386325 | -16.265183644 | conditional_captured_lot_result | 1 completed episode < min_sample 3; 2 open lots; coverage gate requires count AND value; not independently audited; watchlist_incomplete_evidence |
| `6i4nSG48` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.4996 | 1 / 1 | 0 | None | 0 / 2 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; 38 open lots; 59 unresolved-basis sales; sensitivity not established |
| `AUiycVsy` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.2259 | 0.9 / 0.848457959 | 0 | None | 0 / 0 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; 9 open lots; sensitivity not established; coverage_blocked |
| `6qVcd9kp` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.0000 | 1 / 1 | 0 | None | 0 / 0 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; 8 open lots; sensitivity not established |
| `jXtCVtdQ` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.0000 | 0.997126437 / 0.999911249 | 44 | 310.782990765 | 0 / 4 | not_independently_audited | 44 / 310.782990764 | 1E-9 | conditional_captured_lot_result | 1 unresolved-basis sale; not independently audited |
| `25865JdB` | yes (no_leftover_pagination_token) | none | — | no exclusion flag | 0.0000 | 0.784313725 / 0.814823061 | 10 | 0.410996069 | 5 / 20 | not_independently_audited | 12 / None | — | conditional_captured_lot_result | 27 open lots; 31 unresolved-basis sales; cross-currency sensitivity not established; coverage gate requires count AND value; not independently audited; coverage_blocked |
| `4WFgxbFD` | no (unknown_basis_sale) | none | — | no exclusion flag | 0.9880 | 0.795379538 / 0 | 12 | 87.27162175 | 30 / 11 | not_independently_audited | 13 / 208.269877931 | -120.998256181 | insufficient_evidence | unknown_basis_sale |
| `5Qfie4Tb` | no (unknown_basis_sale) | none | — | no exclusion flag | 0.9757 | 0.473451327 / 0.396756262 | 0 | None | 0 / 3 | not_independently_audited | — | — | insufficient_evidence | unknown_basis_sale |
| `8wmGrD3F` | yes (wallet_created_in_range) | multi_signer_bundle_buy | — | bundle: material same-swap partner (keep) | 0.0000 | 0.990384615 / 0.990957737 | 2 | 358.971593577 | 0 / 1 | not_independently_audited | 3 / 414.674391225 | -55.702797648 | insufficient_evidence | multi_signer_bundle_buy |
| `96d9GKPQ` | yes (wallet_created_in_range) | none | — | no exclusion flag | 1.0000 | 0 / 0 | 0 | None | 0 / 6 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; sensitivity not established; coverage_blocked |
| `9R3m89gX` | yes (wallet_created_in_range) | multi_signer_bundle_buy,controlled_pair | 8zxkmeqHrpmqyzCSGxLNWZ4W7ZgjwHuo4HV11ALceNAg | controlled_pair (not a lead): 8zxkmeqH signs funding and dominates funding (100.00%) and withdrawals (100.00%); bundle: material same-swap partner (keep) | 1.0000 | 0.878718535 / 0.595349492 | 87 | -362.320121371 | 0 / 12 | not_independently_audited | 172 / 8381.546726534 | -8743.866847905 | insufficient_evidence | multi_signer_bundle_buy |
| `AMMLTuy9` | yes (wallet_created_in_range) | multi_signer_bundle_buy | — | bundle: material same-swap partner (keep) | 0.9165 | 0.987261146 / 0.022565345 | 21 | -0.011779008 | 0 / 1 | not_independently_audited | — | — | insufficient_evidence | multi_signer_bundle_buy |
| `AN344abT` | yes (wallet_created_in_range) | multi_signer_bundle_buy,sell_proceeds_to_cosigner | — | bundle: material same-swap partner (keep); proceeds to material co-signer | 1.0000 | 0.932960894 / 0.186643139 | 6 | -73.641140525 | 0 / 6 | not_independently_audited | 7 / -77.417969728 | 3.776829203 | insufficient_evidence | multi_signer_bundle_buy |
| `B8wZgcJA` | yes (no_leftover_pagination_token) | none | — | no exclusion flag | 0.1807 | 0 / 0 | 0 | None | 21 / 20 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; sensitivity not established; coverage_blocked |
| `BRjVGhFn` | yes (wallet_created_in_range) | controlled_pair | 8zxkmeqHrpmqyzCSGxLNWZ4W7ZgjwHuo4HV11ALceNAg | controlled_pair (not a lead): 8zxkmeqH signs funding and dominates funding (99.98%) and withdrawals (99.38%) | 1.0000 | 0.789760349 / 0.661087804 | 61 | 44.384845345 | 0 / 11 | not_independently_audited | 99 / 4316.311226595 | -4271.926381250 | insufficient_evidence | controlled_pair |
| `BSTs43nN` | yes (wallet_created_in_range) | controlled_pair | 98YDfUMbZ91Mk9PfHCyBLG6t5Gh1TWQvNUygUQV8gCtU | controlled_pair (not a lead): 98YDfUMb signs funding and dominates funding (100.00%) and withdrawals (100.00%) | 0.0503 | 1 / 1 | 1 | 218.241694699 | 0 / 2 | independently_audited | 1 / 218.2416947 | -1E-9 | insufficient_evidence | controlled_pair |
| `CfNx9LxW` | no (unknown_basis_sale) | controlled_pair | G5GFpTfMFPU31nmXzu5C7198RqXiVC49ToUA1h5pGyph | controlled_pair (not a lead): G5GFpTfM is a fee-paying / swap co-signer that later sweeps proceeds | 1.0000 | 0.682926829 / 0.896949015 | 1 | 444.861224407 | 52 / 4 | not_independently_audited | 1 / 444.861224406 | 1E-9 | insufficient_evidence | unknown_basis_sale |
| `DKyapYGf` | yes (wallet_created_in_range) | multi_signer_bundle_buy,controlled_pair | Sm71cE7vTst5hTT5bPFqfQsh86ouJXSau12au5t6RZA | controlled_pair (not a lead): Sm71cE7v signs funding and dominates funding (100.00%) and withdrawals (100.00%); bundle: material same-swap partner (keep) | 0.1747 | 0.992125984 / 0.985793097 | 2 | 2.486627429 | 0 / 2 | not_independently_audited | 3 / 512.633417334 | -510.146789905 | insufficient_evidence | multi_signer_bundle_buy |
| `DXCWcAiB` | yes (wallet_created_in_range) | sell_proceeds_to_cosigner,multi_signer_bundle_buy | — | bundle: material same-swap partner (keep); proceeds to material co-signer | 0.9963 | 0.983606557 / 0.035192429 | 0 | None | 0 / 2 | not_independently_audited | — | — | insufficient_evidence | sell_proceeds_to_cosigner |
| `DtCiNAXm` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.3658 | 0.5 / 0.999584059 | 0 | None | 0 / 4 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; 1 open lots; sensitivity not established; coverage_blocked |
| `FWgfv6jS` | yes (wallet_created_in_range) | sell_proceeds_to_cosigner,multi_signer_bundle_buy | — | bundle: material same-swap partner (keep); proceeds to material co-signer | 0.9992 | 0.97826087 / 0.27338573 | 0 | None | 0 / 1 | not_independently_audited | — | — | insufficient_evidence | sell_proceeds_to_cosigner |
| `GnDVZMfX` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.0000 | 0.985507246 / 0.988437893 | 2 | -6.137550943 | 1 / 5 | not_independently_audited | 1 / 457.027411065 | -463.164962008 | conditional_captured_lot_result | 2 completed episodes < min_sample 3; 2 open lots; 71 unresolved-basis sales; coverage gate requires count AND value; not independently audited |
| `Gv3ksNUG` | yes (wallet_created_in_range) | sell_proceeds_to_cosigner,multi_signer_bundle_buy | — | bundle: material same-swap partner (keep); proceeds to material co-signer | 0.9995 | 0.96875 / 0.006107339 | 0 | None | 0 / 1 | not_independently_audited | — | — | insufficient_evidence | sell_proceeds_to_cosigner |
| `wae8YMC7` | yes (wallet_created_in_range) | multi_signer_bundle_buy,controlled_pair | V5wL73paYB8snnN4RGsyoHGQ3v1qnjPienLCmbqTbmt | controlled_pair (not a lead): V5wL73pa is a fee-paying / swap co-signer that later sweeps proceeds; bundle: material same-swap partner (keep) | 1.0000 | 0.870496592 / 0.632272886 | 10 | -51.216373895 | 0 / 14 | not_independently_audited | 113 / 7592.459355475 | -7643.675729370 | insufficient_evidence | multi_signer_bundle_buy |
| `3jvkujAb` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0 | 0.104895105 / 0 | 1 | -0.568119003 | 14 / 3 | independently_audited | 1 / -0.568119003 | 0E-9 | conditional_captured_lot_result | 1 completed episode < min_sample 3; 8 open lots; 7 unresolved-basis sales; coverage gate requires count AND value; coverage_blocked |
| `6h5bVioA` | yes (wallet_created_in_range) | none | — | no exclusion flag | — | — / — | 0 | None | 0 / 0 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; sensitivity not established; blocked_unknown_denominator |
| `9LajrZci` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.990134845 | 0.972375691 / 0.990134845 | 20 | -55.371971619 | 11 / 5 | not_independently_audited | 12 / 35.678688601 | -91.050660220 | conditional_captured_lot_result | 7 open lots; 2 unresolved-basis sales; coverage gate requires count AND value; not independently audited |
| `9egz3vFB` | no (pagination_token_remaining_earlier_history) | none | — | no exclusion flag | 0.601072909 | 0.529411765 / 0.601072909 | 50 | 9.615765199 | 109 / 18 | not_independently_audited | 77 / 11.998528893 | -2.382763694 | insufficient_evidence | pagination_token_remaining_earlier_history |
| `AAY2XpWj` | yes (wallet_created_in_range) | none | — | no exclusion flag | — | — / — | 0 | None | 0 / 0 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; sensitivity not established; blocked_unknown_denominator |
| `AcZRAAAb` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.226049238 | 0.29047619 / 0.226049238 | 0 | None | 36 / 13 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; 45 open lots; 20 unresolved-basis sales; sensitivity not established; coverage_blocked |
| `Aww5gi5E` | yes (wallet_created_in_range) | none | — | no exclusion flag | — | — / — | 0 | None | 0 / 0 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; sensitivity not established; blocked_unknown_denominator |
| `DKxKrP4y` | yes (wallet_created_in_range) | none | — | no exclusion flag | 1 | 1 / 1 | 0 | None | 8 / 0 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; sensitivity not established |
| `FLTEaaQQ` | no (unknown_basis_sale) | none | — | no exclusion flag | 0.439945541 | 0.555178268 / 0.439945541 | 1 | None | 161 / 21 | not_independently_audited | 1 / 63.400338 | — | insufficient_evidence | unknown_basis_sale |
| `GDoeg8nv` | yes (wallet_created_in_range) | none | — | no exclusion flag | — | — / — | 0 | None | 0 / 0 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; sensitivity not established; blocked_unknown_denominator |
| `HfU78yvk` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0 | 0 / 0 | 0 | None | 1 / 8 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; sensitivity not established; coverage_blocked |
| `ZXEW1FXj` | no (unknown_basis_sale) | controlled_pair,unknown_destination | DjdRjaoe5eMyBg6aXsfNKnBquCg1en1KFtGptJv1JfGc | controlled_pair (not a lead): DjdRjaoe signs funding and dominates funding (95.79%) and withdrawals (92.99%); DjdRjaoe is a fee-paying / swap co-signer that later sweeps proceeds; EnTMc1wm is a fresh address funded only by this wallet that forwards onward (unknown destination DKcmLRJB); ABs1KggY is a fresh address funded only by this wallet that forwards onward (unknown destination DKcmLRJB) | 0.516113999 | 0.413755695 / 0.516113999 | 0 | None | 2 / 29 | not_independently_audited | — | — | insufficient_evidence | unknown_basis_sale |

## jXtCVtdQ after Jupiter native-settle + Token-2022 skip

Pages: 2. Decoder `spot-v20-dflow-ata-rent-v1`.
Coverage count/value: `0.997126437` / `0.999911249`.
App completed trades: `44`; realized P&L SOL: `310.782990765`.
pnl_scope: `decoded_subset`. App realized P&L is the decoded-subset FIFO, not the wallet's full balance-delta P&L. A high-coverage gap versus the auditor (e.g. 9R3m89gX −362 vs +8,221) means the decoded sample is not representative; unknown-basis / incomplete history blocks a lead.
Auditor: `44` clean / `310.782990764` net; unresolved sales `1`.
Flags: `none`. controlled_pair: `none`.
Buy/sell events decoded: `347`. Uncovered txs: `104`.

Uncovered tx causes (venue: reason → count):

- `unknown: no_outer_program`: 49
- `unknown: No reviewed outer spot swap; transfers and balances alone do not prove trading`: 41
- `unknown: Investigated wallet is absent from transaction account keys`: 14

App-vs-auditor gap is decoded-subset FIFO vs full balance-delta. Jupiter is closed; remaining uncovered txs are non-swap (transfers / unresolved programId / absent keys).

## DKxKrP4y

Completed: `0`; P&L SOL: `None`.
Audit: `not_independently_audited`; lead: `insufficient_evidence`; blocker: `0 completed episodes; sensitivity not established`.
Flags: `none`.

JSON: `evidence/mass-wallet-funnel/live-e2e-proof-2026-10-07/PHASE4_OFFLINE_RERUN_30D.json`
