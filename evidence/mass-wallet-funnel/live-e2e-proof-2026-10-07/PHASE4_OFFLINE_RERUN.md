# Offline Phase 4 replay (all five live-run attached pages)

Bounds: report `2026-09-07T10:52:20Z` → `2026-10-07T10:52:20Z`; history start `2026-07-09T10:52:20Z`.
30 Phase-3 wallets. `max_bot_rate`=25/day. PRODUCT_READY false. No live calls.
Decoder `spot-v18-pumpswap-native-tip-close-v1`.

## Phase 4 replay

| Wallet | history_complete | Bundle / pair flags | controlled_pair | Flag verdict | Venue share | Cov count / value | In-window completed | Realized P&L | Quarantine never-sold / sold | Audit | Auditor clean / net | App − auditor | Lead | Blocker |
|---|---|---|---|---|---:|---|---:|---|---|---|---|---|---|---|
| `BkRUpYSo` | no (pagination_token_remaining_earlier_history) | none | — | no exclusion flag | 1.0000 | 0.495677233 / 0.082552061 | 0 | None | 0 / 2 | not_independently_audited | — | — | insufficient_evidence | pagination_token_remaining_earlier_history |
| `8B3KyNP6` | yes (no_leftover_pagination_token) | none | — | no exclusion flag | 0.7986 | 0.647058824 / 0.663924597 | 20 | 173.180468671 | 1 / 8 | not_independently_audited | 17 / 320.992044616 | -147.811575945 | conditional_captured_lot_result | 1 open lots; 22 unresolved-basis sales; coverage gate requires count AND value; not independently audited; coverage_blocked |
| `E7KevJv8` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.6226 | 0.957446809 / 0.963053044 | 1 | 21.281202681 | 0 / 2 | not_independently_audited | 2 / 37.547732525 | -16.266529844 | conditional_captured_lot_result | 1 completed episode < min_sample 3; 2 open lots; coverage gate requires count AND value; not independently audited; watchlist_incomplete_evidence |
| `6i4nSG48` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.4996 | 0.994535519 / 0.999708937 | 0 | None | 0 / 3 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; 37 open lots; 63 unresolved-basis sales; sensitivity not established |
| `AUiycVsy` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.4238 | 0.2 / 0.08256424 | 0 | None | 0 / 0 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; 2 open lots; sensitivity not established; coverage_blocked |
| `6qVcd9kp` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.3467 | 0.125 / 0.000457643 | 0 | None | 0 / 0 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; 1 open lots; sensitivity not established; coverage_blocked |
| `jXtCVtdQ` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.0000 | 1 / 1 | 44 | 310.781644565 | 0 / 4 | not_independently_audited | 44 / 310.784669009 | -0.003024444 | conditional_captured_lot_result | not independently audited |
| `25865JdB` | yes (no_leftover_pagination_token) | multi_signer_bundle_buy | — | bundle: material same-swap partner (keep) | 0.0000 | 0.777777778 / 0.814823061 | 10 | 0.410996069 | 6 / 21 | not_independently_audited | 12 / None | — | insufficient_evidence | multi_signer_bundle_buy |
| `4WFgxbFD` | no (unknown_basis_sale) | multi_signer_bundle_buy | — | bundle: material same-swap partner (keep) | 0.9880 | 0.755775578 / 0 | 10 | 121.892720103 | 31 / 35 | not_independently_audited | 13 / 208.269877931 | -86.377157828 | insufficient_evidence | unknown_basis_sale |
| `5Qfie4Tb` | no (unknown_basis_sale) | none | — | no exclusion flag | 0.9757 | 0.473451327 / 0.396756262 | 0 | None | 0 / 4 | not_independently_audited | — | — | insufficient_evidence | unknown_basis_sale |
| `8wmGrD3F` | yes (wallet_created_in_range) | multi_signer_bundle_buy | — | bundle: material same-swap partner (keep) | 0.0000 | 0.990384615 / 0.990957737 | 2 | 358.971593577 | 0 / 1 | not_independently_audited | 3 / 414.674391225 | -55.702797648 | insufficient_evidence | multi_signer_bundle_buy |
| `96d9GKPQ` | yes (wallet_created_in_range) | none | — | no exclusion flag | 1.0000 | 0 / 0 | 0 | None | 0 / 6 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; sensitivity not established; coverage_blocked |
| `9R3m89gX` | yes (wallet_created_in_range) | multi_signer_bundle_buy,controlled_pair | 8zxkmeqHrpmqyzCSGxLNWZ4W7ZgjwHuo4HV11ALceNAg | controlled_pair (not a lead): 8zxkmeqH signs funding and dominates funding (100.00%) and withdrawals (100.00%); bundle: material same-swap partner (keep) | 1.0000 | 0.878718535 / 0.595349492 | 87 | -362.320121371 | 0 / 17 | not_independently_audited | 172 / 8220.714490507 | -8583.034611878 | insufficient_evidence | multi_signer_bundle_buy |
| `AMMLTuy9` | yes (wallet_created_in_range) | multi_signer_bundle_buy | — | bundle: material same-swap partner (keep) | 0.9165 | 0.98089172 / 0.022536921 | 20 | -0.009025192 | 0 / 1 | not_independently_audited | — | — | insufficient_evidence | multi_signer_bundle_buy |
| `AN344abT` | yes (wallet_created_in_range) | multi_signer_bundle_buy,sell_proceeds_to_cosigner | — | bundle: material same-swap partner (keep); proceeds to material co-signer | 1.0000 | 0.932960894 / 0.186643139 | 6 | -73.641140525 | 0 / 24 | not_independently_audited | 7 / -77.417969728 | 3.776829203 | insufficient_evidence | multi_signer_bundle_buy |
| `B8wZgcJA` | yes (no_leftover_pagination_token) | none | — | no exclusion flag | 0.1807 | 0 / 0 | 0 | None | 21 / 20 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; sensitivity not established; coverage_blocked |
| `BRjVGhFn` | yes (wallet_created_in_range) | controlled_pair | 8zxkmeqHrpmqyzCSGxLNWZ4W7ZgjwHuo4HV11ALceNAg | controlled_pair (not a lead): 8zxkmeqH signs funding and dominates funding (99.98%) and withdrawals (99.38%) | 1.0000 | 0.782135076 / 0.661087475 | 61 | 44.384845345 | 0 / 11 | not_independently_audited | 99 / 4232.114655222 | -4187.729809877 | insufficient_evidence | controlled_pair |
| `BSTs43nN` | yes (wallet_created_in_range) | controlled_pair | 98YDfUMbZ91Mk9PfHCyBLG6t5Gh1TWQvNUygUQV8gCtU | controlled_pair (not a lead): 98YDfUMb signs funding and dominates funding (100.00%) and withdrawals (100.00%) | 0.0503 | 1 / 1 | 1 | 218.241694699 | 0 / 2 | independently_audited | 1 / 218.2416947 | -1E-9 | insufficient_evidence | controlled_pair |
| `CfNx9LxW` | no (unknown_basis_sale) | multi_signer_bundle_buy,controlled_pair | G5GFpTfMFPU31nmXzu5C7198RqXiVC49ToUA1h5pGyph | controlled_pair (not a lead): G5GFpTfM is a fee-paying / swap co-signer that later sweeps proceeds; bundle: material same-swap partner (keep) | 1.0000 | 0.62601626 / 0.8916669 | 1 | 444.861224407 | 52 / 6 | not_independently_audited | 1 / 444.861224406 | 1E-9 | insufficient_evidence | unknown_basis_sale |
| `DKyapYGf` | yes (wallet_created_in_range) | multi_signer_bundle_buy,controlled_pair | Sm71cE7vTst5hTT5bPFqfQsh86ouJXSau12au5t6RZA | controlled_pair (not a lead): Sm71cE7v signs funding and dominates funding (100.00%) and withdrawals (100.00%); bundle: material same-swap partner (keep) | 0.1747 | 0.992125984 / 0.985793097 | 2 | 2.486627429 | 0 / 2 | not_independently_audited | 3 / 512.633417334 | -510.146789905 | insufficient_evidence | multi_signer_bundle_buy |
| `DXCWcAiB` | yes (wallet_created_in_range) | multi_signer_bundle_buy,sell_proceeds_to_cosigner | — | bundle: material same-swap partner (keep); proceeds to material co-signer | 0.9963 | 0.983606557 / 0.035192429 | 0 | None | 0 / 2 | not_independently_audited | — | — | insufficient_evidence | multi_signer_bundle_buy |
| `DtCiNAXm` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.3658 | 0.5 / 0.999584059 | 0 | None | 0 / 5 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; 1 open lots; sensitivity not established; coverage_blocked |
| `FWgfv6jS` | yes (wallet_created_in_range) | multi_signer_bundle_buy,sell_proceeds_to_cosigner | — | bundle: material same-swap partner (keep); proceeds to material co-signer | 0.9992 | 0.956521739 / 0.271892428 | 0 | None | 0 / 1 | not_independently_audited | — | — | insufficient_evidence | multi_signer_bundle_buy |
| `GnDVZMfX` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.0000 | 0.985507246 / 0.988437893 | 2 | -6.137550943 | 1 / 6 | not_independently_audited | 1 / 457.027411065 | -463.164962008 | conditional_captured_lot_result | 2 completed episodes < min_sample 3; 2 open lots; 214 unresolved-basis sales; coverage gate requires count AND value; not independently audited |
| `Gv3ksNUG` | yes (wallet_created_in_range) | multi_signer_bundle_buy,sell_proceeds_to_cosigner | — | bundle: material same-swap partner (keep); proceeds to material co-signer | 0.9995 | 0.96875 / 0.006107339 | 0 | None | 0 / 1 | not_independently_audited | — | — | insufficient_evidence | multi_signer_bundle_buy |
| `wae8YMC7` | yes (wallet_created_in_range) | multi_signer_bundle_buy,controlled_pair | V5wL73paYB8snnN4RGsyoHGQ3v1qnjPienLCmbqTbmt | controlled_pair (not a lead): V5wL73pa is a fee-paying / swap co-signer that later sweeps proceeds; bundle: material same-swap partner (keep) | 1.0000 | 0.870496592 / 0.632272895 | 10 | -51.216373895 | 0 / 18 | not_independently_audited | 113 / 7401.957035847 | -7453.173409742 | insufficient_evidence | multi_signer_bundle_buy |
| `9LajrZci` | yes (wallet_created_in_range) | multi_signer_bundle_buy | — | bundle: material same-swap partner (keep) | 0.968099595 | 0.917127072 / 0.968099595 | 19 | -69.444627935 | 11 / 5 | not_independently_audited | 12 / 35.678688601 | -105.123316536 | insufficient_evidence | multi_signer_bundle_buy |
| `9egz3vFB` | no (pagination_token_remaining_earlier_history) | multi_signer_bundle_buy | — | bundle: material same-swap partner (keep) | 0.837393957 | 0.771459227 / 0.837393957 | 48 | 7.916288612 | 109 / 21 | not_independently_audited | 77 / 11.998528893 | -4.082240281 | insufficient_evidence | pagination_token_remaining_earlier_history |
| `DKxKrP4y` | yes (wallet_created_in_range) | none | — | no exclusion flag | 0.998976585 | 0.981651376 / 0.998976585 | 0 | None | 8 / 0 | not_independently_audited | — | — | insufficient_evidence | 0 completed episodes; 1 unresolved-basis sale; sensitivity not established |
| `FLTEaaQQ` | no (unknown_basis_sale) | multi_signer_bundle_buy | — | bundle: material same-swap partner (keep) | 0 | 0.516129032 / 0 | 1 | None | 161 / 41 | not_independently_audited | 1 / 63.400338 | — | insufficient_evidence | unknown_basis_sale |

## jXtCVtdQ — true lead level through the committed pipeline (do not tune)

Pages: 2. Decoder `spot-v18-pumpswap-native-tip-close-v1`.
ZyPS6ThF (12.1 SOL PumpSwap buy / EGrRhYpj episode) now decodes; coverage count/value is `1` / `1`.
App completed trades: `44`; realized P&L SOL: `310.781644565`.
pnl_scope: `decoded`.
Auditor: `44` clean / `310.784669009` net; unresolved sales `1`.
App − auditor: `-0.003024444` SOL (≈3,024,444 lamports; far above the 2-lamport bind).
Auditor also lists one dropped loser (`BWsC2AZx`, −0.354958428 SOL, `not_in_window_or_unresolved`).
Independent-audit binding: `not_independently_audited` (mismatch / dropped-loser fail-closed).
Flags: `none`. controlled_pair: `none`. history_complete: yes (`wallet_created_in_range`).
Quarantine: 4 sold-quarantined mints (later moved airdrops; unresolved, never profit, not a wallet-level exclude). Never-sold quarantine count: 0.
Lead level: `conditional_captured_lot_result`. Sole blocker: not independently audited.
Buy/sell events decoded: `347`. Uncovered txs: `104` (non-swap / absent keys). Thresholds were not moved to make this a lead.

## Closest 4bbb364 wallets

- `9LajrZci`: JTO RFQ now in the app (19 completed, −69.444627935 SOL). Auditor still drops losers (12 / +35.678688601) so binding is `not_independently_audited`. Wallet-level block remains `multi_signer_bundle_buy` (RFQ maker class).
- `FLTEaaQQ`: scoped P&L is the completed-episode ledger (`+63.400338` USDC, 1 trade), not the prior +52,395 USDC figure. Blocked by `unknown_basis_sale` + bundle.
- `9egz3vFB`: cap-truncated (`pagination_token_remaining_earlier_history`); 48 completed / +7.92 SOL.
- `DKxKrP4y`: 0 completed in the default 30d report window (8 never-sold quarantined; no flags). Closed lots sit before the window; `--report-window-days 90` is the filter/run option (default stays 30d).
- Binding works: `BSTs43nN` is `independently_audited` (1 / +218.2416947) and still not a lead (`controlled_pair`).
- Bundle keep: `Gv3ksNUG`, `8wmGrD3F` stay `multi_signer_bundle_buy`.

JSON: `evidence/mass-wallet-funnel/live-e2e-proof-2026-10-07/PHASE4_OFFLINE_RERUN.json`
