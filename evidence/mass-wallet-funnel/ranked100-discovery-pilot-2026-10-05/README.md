# RANKED_100_DISCOVERY_PILOT — live one-shot (2026-10-05)

Scrubbed box evidence. No API keys. Repo grant template stays `enabled: false`.
Not full G2. `PRODUCT_READY` is false.

| File | Role |
| --- | --- |
| `SUMMARY.json` | Compact PASS receipt (`RANKED_100_LIVE_SUMMARY.json` is the same) |
| `OPERATOR_REPORT.json` | Raw/unique/shortlist/exclusion census + spend |
| `SHORTLIST.json` | 20 shortlisted rows with reasons (not padded) |
| `TRANSPORT.json` | HTTP 200 + ratelimit headers only (`TRANSPORT_META.json` is the same) |
| `NOTES.md` | Box-side run notes; local armed grant was not committed |
| `RAW.json` | Redacted raw page + `evidence_sha256` (`evidence/RAW_RESPONSE.json` is the same) |
| `RAW_PAGE_CACHE.json` | Cached parsed page used for local reopen |
| `PREFLIGHT.json` | Box preflight (armed locally only; `birdeye_key_present` is boolean) |
| `evidence/RANKED_100_RESULT.json` | Full runner receipt |
| `evidence/INDEX.json` | Pointer |

- Status: **PASS**
- Query: Birdeye `GET /trader/gainers-losers` solana `type=30d` `sort_by=trader_score` `sort_type=desc` `offset=0` `limit=100`
- 100 raw / 100 unique valid wallets
- Shortlist 20; 80 excluded below ceiling
- Birdeye 1 request; documented estimate **30 CU** (no CU billing headers; ratelimit 100/99)
- Helius 0 / 0; setup-pilot untouched; $0 extra; no retries
- `last_active` missing on all rows (unknown)
- `evidence_sha256`: `03869fe91b21e0c3e7425a278989eddc58e3f3267b047add2cf8f86ab52ac9f4`
