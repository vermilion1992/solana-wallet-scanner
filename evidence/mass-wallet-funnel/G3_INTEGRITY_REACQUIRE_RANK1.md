# G3_INTEGRITY_REACQUIRE_RANK1 — offline prep (STOP_NO_SEGMENT)

Narrow one-wallet integrity reacquire for original rank-1
`25865JdBJVVLbt6Kfe4KnKrVCy8UVCYFRRBAPvmJ17LL` pages 0 and 1.

Mitch explicitly approved grant id `live-g3-integrity-reacquire-rank1-2026-10-06-mitch`
at `2026-10-06 02:07` Australia/Adelaide (`2026-10-05T15:37:00Z`).

**This tree does not arm live spend.** Repo template stays `enabled: false`.
Leftover `live-g3-ranked100-history-2026-10-06-mitch` (15/150) must not be reused.
`PRODUCT_READY` stays false. Not full G2. Not MATCH.

## Segment status: STOP_NO_SEGMENT

Surviving PR metadata froze query encoding, historical windows, and page-level
hashes. It did **not** freeze the original 200 signatures or pagination tokens.
Newest-first `getTransactionsForAddress` now would substitute current/latest
history. Live dispatch is therefore blocked (`STOP_NO_SEGMENT`) even if a local
grant copy is armed.

See `g3-integrity-reacquire-rank1/OPERATOR_REPORT.md` and
`g3-integrity-reacquire-rank1/FROZEN_SEGMENTS.json`.

## Offline how-to

```bash
.venv/bin/python -m pytest -q tests/test_mass_search_g3_reacquire.py
.venv/bin/python tools/mass_search_g3_reacquire_offline.py --data-dir /tmp/g3-reacquire-offline
```

The offline CLI refuses `--live`. The live CLI on the secure box also refuses
dispatch while the freeze is `STOP_NO_SEGMENT`.
