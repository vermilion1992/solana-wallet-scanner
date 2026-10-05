# RANKED_100_DISCOVERY_PILOT — offline prep notes

This is **not** full G2 (1,000-wallet). Outcome label: `RANKED_100_DISCOVERY_PILOT`.
`PRODUCT_READY` stays false. G1 grant `live-g1-vertical-slice-2026-10-05-mitch` must not be reused.
Setup-pilot must not be reset.

## What was prepared (offline only)

- Dedicated preset: candidate target 100, local shortlist ceiling 20, Helius/live enrichment 0.
- Exact future query (support implemented; **not dispatched from this cloud VM**):
  - Birdeye `GET /trader/gainers-losers`
  - Solana; `type=30d`; `sort_by=trader_score`; `sort_type=desc`; `offset=0`; `limit=100`
  - No silent fallback to another sort, window, or source
  - Fewer than 100 unique valid wallets = honest incomplete acquisition
- `trader_score` is mapped as a **provider-reported rank**, kept separate from evidence status
- Candidate label: `Provider-ranked candidate — profitability and copyability not independently verified.`
- Trade-count proxy is **not** relabelled “completed profitable trades”
- One-request + 25 CU ceiling persists in the store ledger across restarts; a failed or timed-out dispatched request consumes the attempt
- Cached raw page + query + source order + scores + shortlist decisions: reopen / export / local filter changes make zero provider calls
- Grant file: `config/live_authorization.g2-ranked100-discovery-granted.json` (`enabled: false`)

## How to run the offline pilot

```bash
.venv/bin/python -m pytest -q tests/test_mass_search_ranked100.py
.venv/bin/python tools/mass_search_ranked100_offline.py --data-dir /tmp/ranked100-offline
```

The offline CLI never sends Birdeye/Helius HTTP, even if `--live` is passed.

## What still blocks a live run (operator / box — not this cloud VM)

Arming requires **all** of:

1. Confirm remaining Birdeye quota and that 25 documented CU is acceptable on the **existing** plan (`existing_plan_confirmed=true`, `remaining_quota_confirmed_at` set). Documented 25 CU is an **estimate**, not a confirmed dashboard receipt until the operator reads the billing page after the call.
2. Set `enabled: true` on the ranked-100 grant in a **separate secure runtime** that already holds `BIRDEYE_API_KEY`. Do not paste keys into git or this VM.
3. Grant still unexpired (`expires_at` 2026-10-06T13:01:00Z = 24h after Mitch’s ~23:31 Australia/Adelaide approval).
4. Do **not** enable or reuse the G1 grant for this query. Do **not** reset setup-pilot.
5. Helius stays 0/0. No retries, second page, automatic refresh, paid upgrade, or $ additional spend.

This cloud VM has no API keys and the grant stays disabled.

## What to report after a later live run

Write a receipt under `evidence/mass-wallet-funnel/<run_id>/` including:

| Field | Why it matters |
| --- | --- |
| Raw page (redacted) + `evidence_sha256` | Prove the exact response, no invented wallets |
| Exact query params actually sent | Must match `type=30d` / `sort_by=trader_score` / `sort_type=desc` / `offset=0` / `limit=100` |
| Source order and provider scores | Rank is the provider’s, not our evidence status |
| Unique valid wallets | If `< 100`, label **honest incomplete acquisition** |
| Shortlist count (0–20) and per-row inclusion / exclusion / uncertainty reasons | Zero qualifiers is honest; do not pad |
| Available metrics census (`trader_score`, `realized_pnl`+unit, `trade_count` proxy, `last_active`) | Missing stays unknown |
| Requests / CU: **documented estimate vs confirmed billing** | 1 request / 25 CU documented; confirm dashboard after the call |
| Helius requests/credits | Must be 0 / 0 |
| Setup-pilot usage before and after | Must be unchanged |
| Evidence path | Receipt + cache + shortlist JSON |
| Candidate label on every shortlisted row | Not independently verified profit/copyability |

Do not claim profitability, copyability, MATCH, full G2, or PRODUCT_READY from this pilot.
