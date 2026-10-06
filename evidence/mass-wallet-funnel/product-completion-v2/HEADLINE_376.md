# What +376.028087 USDC is

Not wallet-wide profit. Not safe to copy. Not net of SOL fees.

It is **known-cost realised USDC** on **one** matched sell of mint
`5tCju6YNxHq5zrA6tGndr6F7TK42mpUFmeE31cSFpump`.

| Side | Signature (full) | Quantity (raw) | USDC |
| --- | --- | --- | --- |
| Buy lot consumed | `59K92otieTG53v2uDYJiEhPP5bYXpKtvZALmi4K3uDM86PtNG7U8BuhYEdHpvfydmPnZpKebbve3qkzrZLh2kQ6d` | 1176477238638 | 3000 consideration (FIFO basis) |
| Matched sell | `5VRWeR5eXBXgx7MK1y1xVghYn1NQdTXBUew5LShUJgZ1VHJFnrs3Cyybn6ndrBRpussF3q9ricTfCEi4saQoZqHo` | same quantity | 3376.028087 gross proceeds |

**376.028087 = 3376.028087 − 3000.**

Gross vs net:

- Gross proceeds of that one sell: 3376.028087 USDC.
- FIFO buy consideration: 3000 USDC.
- SOL fee on the sell (`0.00032333` SOL) is **not** subtracted. USDC P&L does not convert or deduct SOL fees.
- No other sell enters the headline.

Excluded from the headline (still on the page):

- Leading unbacked sell `4UAE8RXr1DsdA5Lf9nARhUCJRG51VXAjihLznU6XHh91j5s2uLkvcBdF7TtCb2wzJ2jL7wQNZdmxrA2svARbKnXr` — 2954.546038 USDC gross, unmatched quantity 1191776693137. Missing basis stays **unknown**, never zero cost. Not in +376.
- Three open H4KU buys (`4Kg5mSUZ…` 3000, `pweNPfzN…` 2000, `51Kvmc8z…` 2000) are inventory, not profit.

App production FIFO, in-app independent worksheet, and standalone
`tools/independent_capture_reconciliation.py` (no `scanner.accounting` /
`settlement` / `live_g1` imports) all AGREE at 376.028087. No correction
changed the number this pass.

A=YES / B=PARTIAL / C=NOT_EVALUATED. `safe_to_copy=false`. `PRODUCT_READY=false`.
