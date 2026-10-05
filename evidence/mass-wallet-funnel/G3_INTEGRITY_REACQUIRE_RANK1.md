# G3_INTEGRITY_REACQUIRE_RANK1 — offline prep (STOP_NO_SEGMENT)

Narrow one-wallet integrity reacquire for original rank-1
`25865JdBJVVLbt6Kfe4KnKrVCy8UVCYFRRBAPvmJ17LL` pages 0 and 1.

Mitch explicitly approved grant id `live-g3-integrity-reacquire-rank1-2026-10-06-mitch`
at `2026-10-06 02:07` Australia/Adelaide (`2026-10-05T15:37:00Z`).

**This tree does not arm live spend.** Repo template stays `enabled: false`.
Leftover `live-g3-ranked100-history-2026-10-06-mitch` (15/150) must not be reused.
`PRODUCT_READY` stays false. Not full G2. Not MATCH.

Application commit: `2b8dd944ddfe970d3b5070f38b008aa7cd6179ed`.
Offline tests: 178 passed. Receipt: `g3-integrity-reacquire-rank1/OFFLINE_PREP_RECEIPT.json`.

## Segment status: EXTRACT_OK

Box-local extract recovered the original 100+100 signatures and pagination
tokens (`452802642:577`, `452554670:596`). Page hashes match the damaged G3
run. Token balances remain `SOURCE_RECORDS_DAMAGED`. Live still requires a
local armed grant plus Helius quota confirm on the secure box. Returned
signatures must match the frozen manifest; mismatch stops the run.

See `g3-integrity-reacquire-rank1/OPERATOR_REPORT.md`,
`g3-integrity-reacquire-rank1/FROZEN_SEGMENTS.json`,
`g3-integrity-reacquire-rank1/rank1-signature-overlay.json`.

## Offline how-to

```bash
.venv/bin/python -m pytest -q tests/test_mass_search_g3_reacquire.py
.venv/bin/python tools/mass_search_g3_reacquire_offline.py --data-dir /tmp/g3-reacquire-offline
```

The offline CLI refuses `--live`. The live CLI attaches Helius only on the
secure box after a local armed grant and quota confirm. Signature mismatch
stops the run. Cloud agents must not call Helius.
