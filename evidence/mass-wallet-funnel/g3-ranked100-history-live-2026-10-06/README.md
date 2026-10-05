# G3_RANKED100_HISTORY — live one-shot (2026-10-05 / grant 2026-10-06)

Scrubbed box evidence. No API keys. No armed grant. No sqlite.
Repo grant `config/live_authorization.g3-ranked100-history-granted.json` stays `enabled: false`.
Not full G2. `PRODUCT_READY` is false. Do not invent profitability.

| File | Role |
| --- | --- |
| `G3_RANKED100_LIVE_SUMMARY.json` | Compact INCOMPLETE receipt |
| `OPERATOR_REPORT.json` | Per-wallet pages / episodes / decoder swap counts + spend |
| `NOTES.md` | Box-side run notes; local armed grant was not committed |
| `CREDITS_LEDGER.json` | Helius 10 requests / 100 documented-estimate credits (ceilings 15/150) |
| `DECODER_COVERAGE.json` | `spot-v7-native-flow-roles`: 0 decoded_swaps / 0 supported_transactions on these pages |
| `TRANSPORT_META.json` | 10× HTTP 200; no billing headers |
| `PREFLIGHT.json` | Box preflight (`grant_enabled` / `helius_key_present` are booleans; armed path was local-only) |
| `RUN_STDOUT.json` | Compact stdout (`authorization_id` over-redacted to `[REDACTED]` by key-name redact) |
| `FROZEN_CANDIDATES.json` | Freeze copy used on the box (ranks 1,3,5 + reserves 6,7) |
| `evidence/G3_RESULT.json` | Full runner receipt |
| `evidence/INDEX.json` | Pointer |

- Status: **INCOMPLETE** (honest)
- Grant: `live-g3-ranked100-history-2026-10-06-mitch` ran on a secure box under ceilings
- Investigated: frozen ranks 1, 3, 5 and reserves 6, 7 (2 pages each)
- Qualifying reports (≥10 supported closed episodes): **0 / target 3**
- Visible below G3: 0 (no supported closed pairs)
- Decoder: txs fetched (HTTP 200) but 0 decoded_swaps / 0 supported closed pairs — unsupported programs/discriminators / transfers-without-reviewed-swap / wallet absent from account keys / unsupported tx version
- Helius: 10 requests / ~100 documented-estimate credits (ceilings 15/150); dashboard credits not observed
- Birdeye: 0; setup-pilot untouched; $0 extra
- Stop: `wallet_investigation_cap`
- Application SHA at run: `c3a3ffe5d910823f1113ea5b4f8912c3cf47dfce`

Correction (not a re-pass): `CORRECTION.md`, `SOURCE_RECORDS_CACHE_INSPECT.json` (**SOURCE_RECORDS_DAMAGED**), `redaction_reproduction_result.json`. See `../DATA_INTEGRITY_RECOVERY.md`.
