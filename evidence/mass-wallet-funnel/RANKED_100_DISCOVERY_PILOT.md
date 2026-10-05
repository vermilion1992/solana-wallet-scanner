# RANKED_100_DISCOVERY_PILOT

This is **not** full G2 (1,000-wallet). Outcome label: `RANKED_100_DISCOVERY_PILOT`.
`PRODUCT_READY` stays false. G1 grant `live-g1-vertical-slice-2026-10-05-mitch` was not reused.
Setup-pilot was not reset.

## Live result (secure box, 2026-10-05) — PASS

Evidence: `evidence/mass-wallet-funnel/ranked100-discovery-pilot-2026-10-05/`

| Item | Result |
| --- | --- |
| Status | **PASS** |
| Query | Birdeye `GET /trader/gainers-losers` solana `type=30d` `sort_by=trader_score` `sort_type=desc` `offset=0` `limit=100` |
| Raw / unique valid | 100 / 100 (acquisition complete) |
| Shortlist | 20 (not padded); 80 excluded below ceiling |
| Birdeye | 1 request; documented estimate **30 CU** (no CU billing headers; ratelimit 100 remaining 99) |
| Helius | 0 / 0 |
| setup-pilot | untouched (0 / 200) |
| Extra spend | $0; no retries, second page, or refresh |
| `last_active` | missing on all 100 rows (unknown) |
| `evidence_sha256` | `03869fe91b21e0c3e7425a278989eddc58e3f3267b047add2cf8f86ab52ac9f4` |

Documented 30 CU is an **estimate**, not a confirmed dashboard receipt. Provider response had no CU billing headers.

Every shortlisted row is labeled: *Provider-ranked candidate — profitability and copyability not independently verified.* Trade-count remains a proxy. This is not MATCH, not profitability proof, and not 1,000-wallet G2.

Repo grant `config/live_authorization.g2-ranked100-discovery-granted.json` stays **`enabled: false`**. Mitch amended the ceiling to 1 request / 30 CU (current Birdeye docs; older repo 25 was stale). The box used a local armed override that was **not** committed.

## Offline software (still usable)

```bash
.venv/bin/python -m pytest -q tests/test_mass_search_ranked100.py
.venv/bin/python tools/mass_search_ranked100_offline.py --data-dir /tmp/ranked100-offline
```

The offline CLI never sends Birdeye/Helius HTTP, even if `--live` is passed. This cloud VM has no API keys.

## After a live run — report checklist (this pass)

| Field | This run |
| --- | --- |
| Raw page + `evidence_sha256` | `RAW.json` / `03869fe91b21e0c3e7425a278989eddc58e3f3267b047add2cf8f86ab52ac9f4` |
| Exact query | matched; no fallback |
| Unique valid wallets | 100 |
| Shortlist count + reasons | 20 shortlisted; 80 below ceiling |
| Available metrics | `trader_score` 100, `realized_pnl` 100, `trade_count` 100, `last_active` 0 |
| Requests / CU estimate vs confirmed | 1 request / 30 CU documented estimate; dashboard CU not in headers |
| Helius | 0 / 0 |
| setup-pilot before/after | 0 / 200 both |
| Evidence path | `ranked100-discovery-pilot-2026-10-05/` |

Do not claim profitability, copyability, MATCH, full G2, or PRODUCT_READY from this pilot.
