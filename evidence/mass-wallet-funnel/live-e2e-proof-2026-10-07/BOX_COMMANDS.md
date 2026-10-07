# Box commands — LIVE E2E proof 2026-10-07

Arm a **local** copy of `config/live_authorization.live-e2e-proof-2026-10-07-mitch-draft.json`:
set `enabled: true`, `authorized_by_user_at`, `existing_plan_confirmed`, and
`remaining_quota_confirmed_at`. Do not commit that copy. Expiry is
`2026-10-09T00:00:00+10:30` (`2026-10-08T13:30:00Z`).

Replace `$ARMED` with the local armed grant path and `$OUT` with a writable
directory on the box. Spend is ledgered per `authorization_id` under the
fixed home `$SCANNER_LIVE_LEDGER_HOME` (default
`~/.scanner/live-e2e-ledgers/<authorization_id>`). `--ledger-dir` must equal
that home or the runner refuses a second ledger for the same grant. Armed
copies must set `draft_artifact_hash` to `git show HEAD:config/live_authorization.live-e2e-proof-2026-10-07-mitch-draft.json | sha256sum`
(the committed blob, not a working-tree edit). Missing hash is refused for
`--live`. Missing `phase_caps` inherit the draft. `--explicit-retry` appends
a new receipt. A different `--window-days` on `--resume` is an error. Helius
auth is `?api-key=` on the query string; the key is redacted in every written
string. Phase 4 is offline `GENUINE_REPLAY` on captured pages. Do not run two
`--resume` processes on the same grant or output.

## Dry-run (no spend) — already committed

```bash
.venv/bin/python scripts/live_e2e.py \
  --dry-run \
  --grant config/live_authorization.live-e2e-proof-2026-10-07-mitch-draft.json \
  --wallets config/live_e2e_search_b_cohort.json \
  --discovery \
  --phases all \
  --window-days 30 \
  --earlier-history-days 60 \
  --ledger-dir "$HOME/.scanner/live-e2e-ledgers-dry-run" \
  --output evidence/mass-wallet-funnel/live-e2e-proof-2026-10-07/dry-run
```

## Phase 1 — Birdeye discovery (≤1 request / 30 CU; grant 3 / 91)

```bash
.venv/bin/python scripts/live_e2e.py \
  --live \
  --grant "$ARMED" \
  --discovery \
  --phases 1 \
  --birdeye-window 30d \
  --birdeye-sort trader_score \
  --birdeye-limit 100 \
  --ledger-dir "$HOME/.scanner/live-e2e-ledgers" \
  --output "$OUT"
```

## Phase 2 — signatures-only + one full sample page (2 req / 20 credits per wallet)

```bash
.venv/bin/python scripts/live_e2e.py \
  --live \
  --grant "$ARMED" \
  --wallets config/live_e2e_search_b_cohort.json \
  --phases 2 \
  --window-days 30 \
  --earlier-history-days 60 \
  --min-in-window-tx 0 \
  --max-unsupported-share 1 \
  --resume \
  --ledger-dir "$HOME/.scanner/live-e2e-ledgers" \
  --output "$OUT"
```

## Phase 3 — full history, limit 1000, window + 60d earlier (hard stop at remaining cap)

```bash
.venv/bin/python scripts/live_e2e.py \
  --live \
  --grant "$ARMED" \
  --wallets config/live_e2e_search_b_cohort.json \
  --phases 3 \
  --window-days 30 \
  --earlier-history-days 60 \
  --resume \
  --ledger-dir "$HOME/.scanner/live-e2e-ledgers" \
  --output "$OUT"
```

## Phase 4 — offline replay / decode / qualify (0 provider calls)

```bash
.venv/bin/python scripts/live_e2e.py \
  --dry-run \
  --grant config/live_authorization.live-e2e-proof-2026-10-07-mitch-draft.json \
  --wallets config/live_e2e_search_b_cohort.json \
  --phases 4 \
  --resume \
  --ledger-dir "$HOME/.scanner/live-e2e-ledgers" \
  --output "$OUT"
```

Phase 4 can also run as `--live --phases 4`; it still makes no provider calls.

## All remaining phases after arming

```bash
.venv/bin/python scripts/live_e2e.py \
  --live \
  --grant "$ARMED" \
  --wallets config/live_e2e_search_b_cohort.json \
  --discovery \
  --phases all \
  --window-days 30 \
  --earlier-history-days 60 \
  --resume \
  --ledger-dir "$HOME/.scanner/live-e2e-ledgers" \
  --output "$OUT"
```
