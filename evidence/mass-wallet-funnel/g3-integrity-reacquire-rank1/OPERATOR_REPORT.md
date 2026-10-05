# G3_INTEGRITY_REACQUIRE_RANK1 — operator report (offline prep)

**STOP_NO_SEGMENT.** Original rank-1 page 0/1 transaction signatures are **not**
in surviving PR / evidence metadata. Zero provider calls from this prep.

`PRODUCT_READY` stays false. Repo grant template stays `enabled: false`.
Do not merge PR #4. Do not reuse leftover `live-g3-ranked100-history-2026-10-06-mitch`.

## Frozen from surviving metadata (not current history)

| Field | Frozen value |
| --- | --- |
| Wallet | `25865JdBJVVLbt6Kfe4KnKrVCy8UVCYFRRBAPvmJ17LL` (rank 1 only) |
| Pages | 0 and 1 |
| Page 0 `evidence_sha256` | `b0fa9cb76a9e9531b5654f4fa22b0e9b7ef9a81ab61fa21bc16a649de0fb492d` |
| Page 0 `fetched_at` | `2026-10-05T14:35:32Z` |
| Page 0 records | 100 |
| Page 1 `evidence_sha256` | `2cdb237a8adbca04ee4f9e04abd469a525ce499beca1def7e39a3a908244a0fd` |
| Page 1 `fetched_at` | `2026-10-05T14:35:33Z` |
| Page 1 records | 100 |
| Query | Helius `getTransactionsForAddress`; `full`; `limit=100`; `sortOrder=desc`; `finalized`; `status=any`; `tokenAccounts=all`; `maxSupportedTransactionVersion=1` |
| Report window | `2026-09-05T13:29:27Z` → `2026-10-05T13:29:27Z` exclusive |
| Acquisition support | from `2026-07-07T13:29:27Z` |
| Pagination tokens | present on both pages; **values redacted** in surviving evidence |
| Signature counts frozen | page0 **0** / page1 **0** (expected 100+100 if original segments were identified) |

Manifest path: `evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1/FROZEN_SEGMENTS.json`

Hunted and empty of per-tx signatures: G3 freeze, `DECODER_COVERAGE.json`,
`TRANSPORT_META.json`, `G3_RESULT.json`, `SOURCE_RECORDS_CACHE_INSPECT.json`,
`OPERATOR_REPORT.json`. Damaged box sqlite was never exported
(`unmodified_original_bodies_found=false`).

A newest-first `getTransactionsForAddress` call **now** would substitute
current/latest history. That is forbidden.

## Grant (repo template)

- File: `config/live_authorization.g3-integrity-reacquire-rank1-draft.json`
- Id: `live-g3-integrity-reacquire-rank1-2026-10-06-mitch`
- Mitch explicit approval: `2026-10-06 02:07` Australia/Adelaide (`2026-10-05T15:37:00Z`)
- Expires: `2026-10-06T15:37:00Z`
- **`enabled: false` in git**
- Helius 2 requests / 20 credits / 10 documented credits per GTA / 300s / concurrency 1 / retries 0
- Birdeye 0. Extra spend $0. One wallet. Pages 0–1 only.
- Page 1 only after page 0 integrity **and** mint+sig+reason for a missing acquisition/position boundary. Not for `<10` episodes or better P&L.
- Stop once one completed position is independently reconciled into a visible report.

Leftover G3 15/150 units must not be reused.

## What still needs Mitch / box action before any live dispatch

1. Recover the original 200 signatures (and usable pagination tokens if required) from the **secure-box** damaged G3 sqlite — not by fetching current history.
2. Freeze those signatures into a local overlay that this runner will accept (100 per page). Cloud/PR metadata cannot invent them.
3. Arm a **local uncommitted** copy of the grant (`enabled: true`, Helius plan + remaining quota confirmed). Do not commit the armed file, `.env`, keys, or sqlite.
4. Confirm a fetch strategy that reacquires **those exact segments**. Newest-first GTA without the original cursor is **not** that strategy.
5. Run live **only on the secure box** with `HELIUS_API_KEY` in the environment. Cloud agents must not call Helius.

Until (1)–(4) are done, `tools/mass_search_g3_reacquire_live.py` returns `BLOCKED` / `STOP_NO_SEGMENT` with zero provider calls.

## Grok Bot commands (secure box)

```bash
# Offline verify (zero provider calls)
.venv/bin/python tools/mass_search_g3_reacquire_offline.py \
  --data-dir /tmp/g3-reacquire-offline \
  --evidence evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1

# Try to recover signatures from the G3 live sqlite (zero provider calls)
.venv/bin/python tools/mass_search_g3_reacquire_offline.py \
  --extract-local-signatures /path/to/g3-ranked100-live-results/data/scanner.sqlite \
  --extract-out /tmp/rank1-signature-overlay.json

# Live entry — will BLOCK with STOP_NO_SEGMENT until 100+100 original
# signatures are frozen. Copy the grant locally; do not edit the git template.
cp config/live_authorization.g3-integrity-reacquire-rank1-draft.json /tmp/g3-reacquire-armed.json
# local edit only: enabled=true, existing_plan_confirmed=true,
# remaining_quota_confirmed_at=<now>
.venv/bin/python tools/mass_search_g3_reacquire_live.py \
  --data-dir "$HOME/scanner-data" \
  --grant /tmp/g3-reacquire-armed.json \
  --evidence evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1-live
```

Do not print or commit secrets. Artifact paths:

- Grant template: `config/live_authorization.g3-integrity-reacquire-rank1-draft.json`
- Freeze: `evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1/FROZEN_SEGMENTS.json`
- Offline receipt (written by the offline CLI): `evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1/OFFLINE_PREP_RECEIPT.json`
- Live evidence dir (box only, do not pre-create with secrets): `evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1-live/`
