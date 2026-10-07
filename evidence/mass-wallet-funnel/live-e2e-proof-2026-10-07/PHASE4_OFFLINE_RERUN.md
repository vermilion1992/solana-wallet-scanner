# Offline Phase 4 + pre-screen ranking (attached cfe6e78 + bbc5bef pages)

Bounds: report `2026-09-07T07:51:22Z` → `2026-10-07T07:51:22Z`; history start `2026-07-09T07:51:22Z`.
78 distinct Phase-2 wallets, 14 with Phase-3 pages. `max_bot_rate`=50/day. PRODUCT_READY false. No live calls.

## Chosen for full history (rank > 0, not bundle/bot, known-basis buys)

| Wallet | Rank | Venue share | In-window txs | Bot rate | Bundle | Known buys | Source |
|---|---:|---:|---:|---:|---|---|---|
| `8wmGrD3F5bd439r2k7eJWcHk9UgssuQDLF6kNawBRBRF` | 0.9999 | 0.9999 | 111 | 3.7000 | no | yes | cfe6e78 |
| `DKyapYGfvKCBUTzKSCbTbvVVHbj9yMBKrHrkjdXZ24xx` | 0.9997 | 0.9997 | 262 | 8.7333 | no | yes | bbc5bef |
| `BSTs43nNTc3wBidj8ueY92RJbGn4wxvF8VYYKMVWGdNR` | 0.7939 | 0.7939 | 179 | 5.9667 | no | yes | bbc5bef |

**3 wallets** would be sent to Phase 3 under the 2026-10-09 plan (25 slots). None of the 14 already-fetched Phase-3 wallets remain eligible.

## Phase 4 replay (14 wallets with attached full-history pages)

| Wallet | Bundle / reasons | Venue share | Cov count / value | In-window completed | Realized P&L | Auditor (clean / net) | Lead |
|---|---|---:|---|---:|---|---|---|
| 25865JdB | yes / transfer_in_zero_basis,multi_signer_bundle_buy | 0.0000 | 0.77124183 / 0.814790942 | 10 | SOL 0.410996069, USDC 12620.493155 | 12 mixed: USDC 28896.882878358, SOL 0.410996069 | insufficient_evidence |
| 5Qfie4Tb | yes / transfer_in_zero_basis | 1.0000 | 0.473451327 / 0.396756262 | 0 | — | 0 | insufficient_evidence |
| 6i4nSG48 | yes / transfer_in_zero_basis | 0.4996 | 0.989071038 / 0.999170274 | 0 | — | 0 | insufficient_evidence |
| 8B3KyNP6 | yes / transfer_in_zero_basis | 0.7986 | 0.647058824 / 0.663924597 | 20 | SOL 173.180468671 | 17 / 320.992044616 SOL | insufficient_evidence |
| 96d9GKPQ | no | 1.0000 | 0 / 0 | 0 | — | 0 | insufficient_evidence |
| AMMLTuy9 | yes / multi_signer_bundle_buy | 0.9165 | 0.968152866 / 0.022276203 | 18 | SOL -0.004837792 | 0 | insufficient_evidence |
| B8wZgcJA | yes / transfer_in_zero_basis | 0.1807 | 0 / 0 | 0 | — | 0 | insufficient_evidence |
| CfNx9LxW | yes / transfer_in_zero_basis,multi_signer_bundle_buy | 1.0000 | 0.577235772 / 0.723830738 | 1 | SOL 444.861224407 | 1 / 444.861224406 SOL | insufficient_evidence |
| DXCWcAiB | yes / sell_proceeds_to_cosigner,multi_signer_bundle_buy | 0.9964 | 0.967213115 / 0.030765613 | 0 | — | 0 | insufficient_evidence |
| DtCiNAXm | yes / transfer_in_zero_basis | 0.3658 | 0.5 / 0.999584059 | 0 | — | 0 | insufficient_evidence |
| E7KevJv8 | yes / multi_signer_bundle_buy | 0.7133 | 0.936170213 / 0.944283872 | 0 | — | 2 / 37.547732525 SOL | insufficient_evidence |
| FWgfv6jS | yes / sell_proceeds_to_cosigner,multi_signer_bundle_buy | 0.9992 | 0.956521739 / 0.271892428 | 0 | — | 0 | insufficient_evidence |
| GnDVZMfX | yes / transfer_in_zero_basis | 0.9993 | 0.985507246 / 0.988437893 | 2 | SOL -6.137550943 | 1 / 457.027411065 SOL | insufficient_evidence |
| Gv3ksNUG | yes / sell_proceeds_to_cosigner,multi_signer_bundle_buy | 0.9995 | 0.9375 / 0.005337297 | 0 | — | 0 | insufficient_evidence |

## All 78 pre-screen wallets

| Wallet | Bundle | Bot | Venue share | Rank | Known buys | In-window | Cov count/value | Completed | P&L | Auditor | Lead | Chosen | Drop |
|---|---|---|---:|---:|---|---:|---|---:|---|---|---|---|---|
| 8wmGrD3F | no | no 3.7000 | 0.9999 | 0.9999 | yes | 111 | — | — | — | — | — | yes | — |
| DKyapYGf | no | no 8.7333 | 0.9997 | 0.9997 | yes | 262 | — | — | — | — | — | yes | — |
| BSTs43nN | no | no 5.9667 | 0.7939 | 0.7939 | yes | 179 | — | — | — | — | — | yes | — |
| A6PSQFRf | no | no 33.3333 | 0.0000 | 0.0000 | yes | 1000 | — | — | — | — | — | no | — |
| An9sREpL | no | no 33.3333 | 0.0000 | 0.0000 | yes | 1000 | — | — | — | — | — | no | — |
| 25865JdB | yes:transfer_in_zero_basis | no 20.9000 | 0.0000 | 0.0000 | no | 627 | 0.77124183 / 0.814790942 | 10 | 0.410996069 | 12/— mixed | insufficient_evidence | no | transfer_in_zero_basis |
| 291Yj2Yf | no | no 33.3333 | 1.0000 | 0.0000 | no | 1000 | — | — | — | — | — | no | no_known_basis_buys |
| 2apSyUwJ | no | no 8.7000 | 0.9992 | 0.0000 | no | 261 | — | — | — | — | — | no | no_known_basis_buys |
| 2ueo5yNJ | no | no 4.3667 | 1.0000 | 0.0000 | no | 131 | — | — | — | — | — | no | no_known_basis_buys |
| 3hcUVXt8 | no | no 4.7000 | 1.0000 | 0.0000 | no | 141 | — | — | — | — | — | no | no_known_basis_buys |
| 3oX6CE66 | no | no 5.3000 | 0.9920 | 0.0000 | no | 159 | — | — | — | — | — | no | no_known_basis_buys |
| 43VE6RJA | no | no 5.8000 | 1.0000 | 0.0000 | no | 174 | — | — | — | — | — | no | no_known_basis_buys |
| 4Gbhd8qD | no | no 8.1333 | 0.9980 | 0.0000 | no | 244 | — | — | — | — | — | no | no_known_basis_buys |
| 4JiNkbS5 | no | no 6.2667 | 1.0000 | 0.0000 | no | 188 | — | — | — | — | — | no | no_known_basis_buys |
| 4h4qaaQu | no | no 7.7000 | 0.9975 | 0.0000 | no | 231 | — | — | — | — | — | no | no_known_basis_buys |
| 4hiobwqg | yes:transfer_in_zero_basis | no 33.3333 | 0.5025 | 0.0000 | yes | 1000 | — | — | — | — | — | no | transfer_in_zero_basis |
| 5BFNwxC8 | no | no 5.1000 | 1.0000 | 0.0000 | no | 153 | — | — | — | — | — | no | no_known_basis_buys |
| 5DAubjPG | yes:transfer_in_zero_basis | no 33.3333 | 0.0155 | 0.0000 | yes | 1000 | — | — | — | — | — | no | transfer_in_zero_basis |
| 5H9w3ux1 | no | no 4.9000 | 0.9991 | 0.0000 | no | 147 | — | — | — | — | — | no | no_known_basis_buys |
| 5Qfie4Tb | no | no 6.0000 | 1.0000 | 0.0000 | no | 180 | 0.473451327 / 0.396756262 | 0 | — | 0/— | insufficient_evidence | no | no_known_basis_buys |
| 5azbu8CH | yes:transfer_in_zero_basis | no 33.3333 | 0.9875 | 0.0000 | yes | 1000 | — | — | — | — | — | no | transfer_in_zero_basis |
| 6i4nSG48 | yes:transfer_in_zero_basis | no 10.0000 | 0.4996 | 0.0000 | yes | 300 | 0.989071038 / 0.999170274 | 0 | — | 0/— | insufficient_evidence | no | transfer_in_zero_basis |
| 6rSQ5r58 | no | no 16.7667 | 0.9988 | 0.0000 | no | 503 | — | — | — | — | — | no | no_known_basis_buys |
| 6yDW8qpr | yes:transfer_in_zero_basis | no 33.3333 | 0.5000 | 0.0000 | no | 1000 | — | — | — | — | — | no | transfer_in_zero_basis |
| 71EqtHHU | no | no 6.1000 | 0.9995 | 0.0000 | no | 183 | — | — | — | — | — | no | no_known_basis_buys |
| 7JVtPBiQ | yes:transfer_in_zero_basis | no 31.4667 | — | 0.0000 | no | 944 | — | — | — | — | — | no | transfer_in_zero_basis |
| 7meYKsaz | no | no 4.6667 | 0.0000 | 0.0000 | no | 140 | — | — | — | — | — | no | no_known_basis_buys |
| 7vPV34sJ | yes:sell_proceeds_to_cosigner | no 1.4000 | 0.9986 | 0.0000 | yes | 42 | — | — | — | — | — | no | sell_proceeds_to_cosigner |
| 847CFpCv | no | no 17.1000 | 0.9986 | 0.0000 | no | 513 | — | — | — | — | — | no | no_known_basis_buys |
| 8B3KyNP6 | yes:transfer_in_zero_basis | no 12.8000 | 0.7986 | 0.0000 | yes | 384 | 0.647058824 / 0.663924597 | 20 | 173.180468671 | 17/320.992044616 SOL | insufficient_evidence | no | transfer_in_zero_basis |
| 8JLN2NsV | yes:multi_signer_bundle_buy | no 12.9333 | 0.9917 | 0.0000 | yes | 388 | — | — | — | — | — | no | multi_signer_bundle_buy |
| 8qgXwVpn | no | no 4.9000 | 0.9909 | 0.0000 | no | 147 | — | — | — | — | — | no | no_known_basis_buys |
| 8vjChJhB | yes:transfer_in_zero_basis | no 33.3333 | 0.0075 | 0.0000 | yes | 1000 | — | — | — | — | — | no | transfer_in_zero_basis |
| 91XzVsoZ | no | no 4.8667 | 1.0000 | 0.0000 | no | 146 | — | — | — | — | — | no | no_known_basis_buys |
| 96d9GKPQ | no | no 6.0667 | 1.0000 | 0.0000 | no | 182 | 0 / 0 | 0 | — | 0/— | insufficient_evidence | no | no_known_basis_buys |
| 96vJSNV4 | no | no 33.3333 | 0.6280 | 0.0000 | no | 1000 | — | — | — | — | — | no | no_known_basis_buys |
| 9Ad9QK8f | no | no 5.1000 | 1.0000 | 0.0000 | no | 153 | — | — | — | — | — | no | no_known_basis_buys |
| 9cyDJyYf | no | no 4.6000 | 0.9987 | 0.0000 | no | 138 | — | — | — | — | — | no | no_known_basis_buys |
| 9iG79XSB | no | no 4.8333 | 0.9975 | 0.0000 | no | 145 | — | — | — | — | — | no | no_known_basis_buys |
| AMMLTuy9 | yes:multi_signer_bundle_buy | no 7.8000 | 0.9165 | 0.0000 | yes | 234 | 0.968152866 / 0.022276203 | 18 | -0.004837792 | 0/— | insufficient_evidence | no | multi_signer_bundle_buy |
| AQWEYPwk | yes:multi_signer_bundle_buy,sell_proceeds_to_cosigner,transfer_in_zero_basis | no 33.3333 | 0.9548 | 0.0000 | no | 1000 | — | — | — | — | — | no | multi_signer_bundle_buy |
| AUn7v7iA | yes:transfer_in_zero_basis | no 13.9000 | 0.4999 | 0.0000 | no | 417 | — | — | — | — | — | no | transfer_in_zero_basis |
| AmDF6YBB | no | no 6.7000 | 0.9888 | 0.0000 | no | 201 | — | — | — | — | — | no | no_known_basis_buys |
| AyvDiGvj | no | no 5.4000 | 0.9960 | 0.0000 | no | 162 | — | — | — | — | — | no | no_known_basis_buys |
| B8wZgcJA | yes:transfer_in_zero_basis | no 5.6667 | 0.1807 | 0.0000 | no | 170 | 0 / 0 | 0 | — | 0/— | insufficient_evidence | no | transfer_in_zero_basis |
| BSN5bh8A | yes:transfer_in_zero_basis | no 33.3333 | 0.1072 | 0.0000 | no | 1000 | — | — | — | — | — | no | transfer_in_zero_basis |
| BYzCun17 | no | no 5.7667 | 1.0000 | 0.0000 | no | 173 | — | — | — | — | — | no | no_known_basis_buys |
| Bbu8XAvx | no | no 7.2333 | 0.9997 | 0.0000 | no | 217 | — | — | — | — | — | no | no_known_basis_buys |
| Bn6UXZQx | no | no 4.8667 | 0.9980 | 0.0000 | no | 146 | — | — | — | — | — | no | no_known_basis_buys |
| C74ibw78 | yes:transfer_in_zero_basis | no 11.8333 | 0.0009 | 0.0000 | no | 355 | — | — | — | — | — | no | transfer_in_zero_basis |
| CfNx9LxW | no | no 32.9333 | 1.0000 | 0.0000 | no | 988 | 0.577235772 / 0.723830738 | 1 | 444.861224407 | 1/444.861224406 SOL | insufficient_evidence | no | no_known_basis_buys |
| D5WjrRpQ | no | no 4.8000 | 1.0000 | 0.0000 | no | 144 | — | — | — | — | — | no | no_known_basis_buys |
| DSJVxpK1 | yes:transfer_in_zero_basis,multi_signer_bundle_buy | no 23.3333 | 0.4534 | 0.0000 | no | 700 | — | — | — | — | — | no | transfer_in_zero_basis |
| DXCWcAiB | yes:sell_proceeds_to_cosigner,multi_signer_bundle_buy | no 2.8000 | 0.9964 | 0.0000 | yes | 84 | 0.967213115 / 0.030765613 | 0 | — | 0/— | insufficient_evidence | no | sell_proceeds_to_cosigner |
| DY1f83rw | no | no 8.2333 | 0.9946 | 0.0000 | no | 247 | — | — | — | — | — | no | no_known_basis_buys |
| Do3BUVky | no | no 4.0667 | 0.9993 | 0.0000 | no | 122 | — | — | — | — | — | no | no_known_basis_buys |
| DtCiNAXm | yes:transfer_in_zero_basis | no 3.0667 | 0.3658 | 0.0000 | yes | 92 | 0.5 / 0.999584059 | 0 | — | 0/— | insufficient_evidence | no | transfer_in_zero_basis |
| E7KevJv8 | yes:multi_signer_bundle_buy | no 2.1667 | 0.7133 | 0.0000 | yes | 65 | 0.936170213 / 0.944283872 | 0 | — | 2/37.547732525 SOL | insufficient_evidence | no | multi_signer_bundle_buy |
| EP87qz6X | no | no 8.6000 | 0.9950 | 0.0000 | no | 258 | — | — | — | — | — | no | no_known_basis_buys |
| F1a7cR49 | yes:multi_signer_bundle_buy | no 33.3333 | 0.9998 | 0.0000 | no | 1000 | — | — | — | — | — | no | multi_signer_bundle_buy |
| FBfChxAZ | yes:transfer_in_zero_basis | no 9.1667 | 0.6417 | 0.0000 | no | 275 | — | — | — | — | — | no | transfer_in_zero_basis |
| FNvuekiK | no | no 8.2333 | — | 0.0000 | no | 247 | — | — | — | — | — | no | no_known_basis_buys |
| FWgfv6jS | yes:sell_proceeds_to_cosigner,multi_signer_bundle_buy | no 2.5000 | 0.9992 | 0.0000 | yes | 75 | 0.956521739 / 0.271892428 | 0 | — | 0/— | insufficient_evidence | no | sell_proceeds_to_cosigner |
| FvUNFkLV | no | no 7.2000 | 1.0000 | 0.0000 | no | 216 | — | — | — | — | — | no | no_known_basis_buys |
| G6SeWJ9f | yes:multi_signer_bundle_buy,transfer_in_zero_basis | no 33.3333 | 0.0000 | 0.0000 | no | 1000 | — | — | — | — | — | no | multi_signer_bundle_buy |
| GCGoRXVx | yes:multi_signer_bundle_buy,transfer_in_zero_basis | no 4.8333 | 0.5013 | 0.0000 | no | 145 | — | — | — | — | — | no | multi_signer_bundle_buy |
| GRJh4kKC | no | no 6.8667 | 0.9925 | 0.0000 | no | 206 | — | — | — | — | — | no | no_known_basis_buys |
| GnDVZMfX | yes:transfer_in_zero_basis | no 22.1333 | 0.9993 | 0.0000 | yes | 664 | 0.985507246 / 0.988437893 | 2 | -6.137550943 | 1/457.027411065 SOL | insufficient_evidence | no | transfer_in_zero_basis |
| GoSddySD | no | no 7.0000 | 1.0000 | 0.0000 | no | 210 | — | — | — | — | — | no | no_known_basis_buys |
| Gv3ksNUG | yes:sell_proceeds_to_cosigner,multi_signer_bundle_buy | no 1.7333 | 0.9995 | 0.0000 | yes | 52 | 0.9375 / 0.005337297 | 0 | — | 0/— | insufficient_evidence | no | sell_proceeds_to_cosigner |
| H3KxmKBy | no | no 5.5000 | 0.9988 | 0.0000 | no | 165 | — | — | — | — | — | no | no_known_basis_buys |
| J1WANisY | no | no 5.5000 | 0.9944 | 0.0000 | no | 165 | — | — | — | — | — | no | no_known_basis_buys |
| J6Q3tdQC | no | no 5.0000 | 1.0000 | 0.0000 | no | 150 | — | — | — | — | — | no | no_known_basis_buys |
| fJD8FEGY | no | no 4.8000 | 1.0000 | 0.0000 | no | 144 | — | — | — | — | — | no | no_known_basis_buys |
| gtfoTELA | yes:transfer_in_zero_basis | no 33.3333 | 0.5068 | 0.0000 | yes | 1000 | — | — | — | — | — | no | transfer_in_zero_basis |
| ji1bQ5he | yes:multi_signer_bundle_buy | no 27.8000 | 1.0000 | 0.0000 | no | 834 | — | — | — | — | — | no | multi_signer_bundle_buy |
| rQnGUGo5 | no | no 8.1000 | 0.9457 | 0.0000 | no | 243 | — | — | — | — | — | no | no_known_basis_buys |
| vumPmr5Q | no | no 4.9000 | 0.9985 | 0.0000 | no | 147 | — | — | — | — | — | no | no_known_basis_buys |

Drop reasons: no_known_basis_buys=43, transfer_in_zero_basis=18, multi_signer_bundle_buy=8, eligible=5, sell_proceeds_to_cosigner=4.
Eligible-but-rank-0 (known buys, not bundle/bot, unsupported venue share 0) are not given a full-history slot.

## Next-run planner (100 pre-screen, 25 kept)

| Phase | Provider | Requests | Units | Cap |
|---|---|---:|---:|---|
| 1 discovery | Birdeye | 1 | 30 CU | 10 / 300 |
| 2 pre-screen | Helius | 200 | 2000 credits | 200 / 2,000 |
| 3 history (planner min 2 pages) | Helius | 50 | 5000 credits | 200 / 12,000 |
| 4 offline | — | 0 | 0 | — |
| **Total** | | **1 + 250** | **30 CU + 7000 credits** | **fits** |

