# G3_INTEGRITY_REACQUIRE_RANK1 — operator report

**EXTRACT_OK.** Original rank-1 page 0/1 signatures and pagination tokens are
frozen from the box-local extract (zero provider calls). Token balances remain
**SOURCE_RECORDS_DAMAGED** and are not intact economics.

Live is still **box-only** after Helius quota confirm + a local uncommitted
armed grant. Do not call Helius from the cloud agent. Do not merge PR #4.
Repo grant template stays `enabled: false`. `PRODUCT_READY` stays false.
Do not reuse leftover `live-g3-ranked100-history-2026-10-06-mitch`.

## Frozen segments

| Field | Frozen value |
| --- | --- |
| Wallet | `25865JdBJVVLbt6Kfe4KnKrVCy8UVCYFRRBAPvmJ17LL` (rank 1 only) |
| Signature counts | page0 **100** / page1 **100** |
| Page 0 first/last | `3Brdt8dMcSY96bjk…AECc4GDHG` / `2jzBnCwEvyQkNuR2…8FsBycVg` |
| Page 1 first/last | `4DkivqAUbHY4RLud…VgLy61r2` / `5c2C218vHM5fZb6C…8JZghBUG` |
| Page 0 `evidence_sha256` | `b0fa9cb76a9e9531b5654f4fa22b0e9b7ef9a81ab61fa21bc16a649de0fb492d` |
| Page 1 `evidence_sha256` | `2cdb237a8adbca04ee4f9e04abd469a525ce499beca1def7e39a3a908244a0fd` |
| Page 0 pagination token | `452802642:577` (returned with page 0; used to request page 1) |
| Page 1 pagination token | `452554670:596` |
| Query | Helius `getTransactionsForAddress`; `full`; `limit=100`; `sortOrder=desc`; `finalized`; `status=any`; `tokenAccounts=all`; `maxSupportedTransactionVersion=1` |
| Report window | `2026-09-05T13:29:27Z` → `2026-10-05T13:29:27Z` exclusive |
| Acquisition support | from `2026-07-07T13:29:27Z` |
| Overlay | `rank1-signature-overlay.json` (`EXTRACT_OK`, 2026-10-05T15:49:10Z) |
| Extract report | `EXTRACT_REPORT.json` (`provider_calls`: 0) |

Returned live signatures must equal this manifest. Mismatch → stop. Do not
widen the query or substitute current/latest history.

## What still needs Mitch / box action before live dispatch

1. Confirm remaining Helius quota / GTA entitlement on the billing dashboard (`existing_plan_confirmed` + `remaining_quota_confirmed_at` on a **local** grant copy).
2. Arm that local uncommitted copy (`enabled: true`). Do not commit it, `.env`, keys, or sqlite.
3. Run **only on the secure box** with `HELIUS_API_KEY` in the environment.
4. Page 0 first. Page 1 only after page 0 integrity is INTACT and a recorded mint+sig+reason for a missing acquisition/position boundary. Stop once one completed position is independently reconciled into a visible report.

## Grok Bot commands (secure box)

```bash
# Offline verify (zero provider calls)
.venv/bin/python tools/mass_search_g3_reacquire_offline.py \
  --data-dir /tmp/g3-reacquire-offline \
  --evidence evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1 \
  --overlay evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1/rank1-signature-overlay.json

# Live — local armed grant only; repo template stays disabled
cp config/live_authorization.g3-integrity-reacquire-rank1-draft.json /tmp/g3-reacquire-armed.json
# local edit only: enabled=true, existing_plan_confirmed=true,
# remaining_quota_confirmed_at=<now>
.venv/bin/python tools/mass_search_g3_reacquire_live.py \
  --data-dir "$HOME/scanner-data" \
  --grant /tmp/g3-reacquire-armed.json \
  --overlay evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1/rank1-signature-overlay.json \
  --evidence evidence/mass-wallet-funnel/g3-integrity-reacquire-rank1-live
```

Do not print or commit secrets.
