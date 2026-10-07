# Box commands — LIVE E2E proof (next run: 2026-10-09 draft)

The **next** live grant is `config/live_authorization.live-e2e-proof-2026-10-09-mitch-draft.json`
(`enabled: false` in repo). Expiry is `2026-10-10T00:00:00+10:30`
(`2026-10-09T13:30:00Z`). Caps: Birdeye ≤10 requests / ≤300 CU; Helius ≤1,500
requests / ≤15,000 credits. Hard ceilings in `scanner/mass_search/live_e2e.py`
(`HARD_CEILINGS`) cannot be raised by a local commit. `PINNED_DRAFT_HASHES`
must match the armed `draft_artifact_hash`.

The 2026-10-07 draft is **retired for `--live` immediately** (it is still
`enabled: false` in repo). `--live` refuses `live-e2e-proof-2026-10-07-mitch`.
PRODUCT_READY stays false. Do not merge. No new draft is required: the 09
grant still has Birdeye 2 req / 20 CU and Helius ~1,282 req / ~10,480 credits
of reserved headroom.

## Arming (local copy only)

1. Copy the 2026-10-09 draft outside the repo.
2. Set `enabled: true`, `authorized_by_user_at`, `existing_plan_confirmed`,
   `remaining_quota_confirmed_at`.
3. Set `draft_artifact_hash` to the **pinned** SHA-256 in
   `PINNED_DRAFT_HASHES["live-e2e-proof-2026-10-09-mitch"]` (must also equal
   `git show HEAD:config/live_authorization.live-e2e-proof-2026-10-09-mitch-draft.json | sha256sum`).
4. Record identity (required for `--live`):
   - `armed_home`: `python -c "from pathlib import Path; print(Path.home())"`
   - `ledger_home`: `$HOME/.scanner/live-e2e-ledgers` (must match the path
     `--ledger-dir` will use)
5. Mode 0600. Never commit the armed copy.

`--live` refuses `SCANNER_LIVE_LEDGER_HOME` / `SCANNER_LIVE_LEDGER_DIR` unless
they equal `ledger_home`, and refuses if `HOME` differs from `armed_home`.
Leave those env vars unset on the box. `--ledger-dir` must equal `ledger_home`.

Helius pacing defaults to 0.5s min interval (2 rps) and 2s backoff on 429
(`SCANNER_HELIUS_MIN_INTERVAL_SEC`, `SCANNER_HELIUS_BACKOFF_SEC`). Birdeye
pacing defaults to 4s (`SCANNER_BIRDEYE_MIN_INTERVAL_SEC`) and 4s backoff
on 429; a 429 or `success: false` body is an error in the ledger, not an
empty success. Every attempt is receipted. Phase 2 resume screens wallets
that are not yet `done`. Phase 3 resume fetches wallets that are not yet
`done`. A leftover `paginationToken` is not the end unless the wallet was
created in range (oldest native preBalance 0). Planner estimates pages per
wallet from pre-screen tx density (minimum 2). `--history-to-first` fetches
back to the first transaction (or `--history-start-unix`) under
`--per-wallet-cap`. Multiple `--discovery` requests in one output dir
(different source/window/sort/tokens) merge into one pool; each is counted.

Replace `$ARMED` and `$OUT`. One process at a time.

## Birdeye CU (docs.birdeye.so/docs/compute-unit-cost, reviewed 2026-10-07)

| Flag | Endpoint | Documented CU |
|---|---|---|
| `--discovery-source gainers-losers` (default) | `GET /trader/gainers-losers` | 30 CU fixed |
| `--discovery-source top-traders` | `GET /defi/v2/tokens/top_traders` | 35 CU fixed |

Gainers-losers windows: `yesterday`, `today`, `1W`, `30d`, `90d`. Sorts:
`PnL`, `realized_pnl`, `unrealized_pnl`, `trader_score`.
Top-traders time frames: `30m`–`24h` plus `2d`–`90d`. Sorts: `volume`,
`trade`, `total_pnl`, `unrealized_pnl`, `realized_pnl`, `volume_usd`.
10× gainers-losers = 300 CU. 8× top-traders = 280 CU. 1× gainers-losers +
7× top-traders = 275 CU.

## Dry-run planner (must show the plan fits)

```bash
.venv/bin/python scripts/live_e2e.py \
  --dry-run \
  --grant config/live_authorization.live-e2e-proof-2026-10-09-mitch-draft.json \
  --discovery \
  --discovery-source gainers-losers \
  --birdeye-window 1W \
  --birdeye-sort PnL \
  --phases all \
  --window-days 30 \
  --earlier-history-days 60 \
  --max-bot-rate 25 \
  --history-to-first \
  --per-wallet-cap 8 \
  --ledger-dir "$HOME/.scanner/live-e2e-ledgers-dry-run" \
  --output evidence/mass-wallet-funnel/live-e2e-proof-2026-10-07/dry-run-2026-10-09
```

Top-traders alternative (35 CU per liquid token; supply mints):

```bash
.venv/bin/python scripts/live_e2e.py \
  --dry-run \
  --grant config/live_authorization.live-e2e-proof-2026-10-09-mitch-draft.json \
  --discovery \
  --discovery-source top-traders \
  --birdeye-tokens So11111111111111111111111111111111111111112,EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v \
  --birdeye-window 24h \
  --birdeye-sort volume \
  --phases 1 \
  --ledger-dir "$HOME/.scanner/live-e2e-ledgers-dry-run" \
  --output evidence/mass-wallet-funnel/live-e2e-proof-2026-10-07/dry-run-top-traders
```

## Phase 1 — discovery (≤10 / 300 CU)

```bash
.venv/bin/python scripts/live_e2e.py \
  --live \
  --grant "$ARMED" \
  --discovery \
  --discovery-source gainers-losers \
  --phases 1 \
  --birdeye-window 1W \
  --birdeye-sort PnL \
  --birdeye-limit 100 \
  --ledger-dir "$HOME/.scanner/live-e2e-ledgers" \
  --output "$OUT"
```

## Phase 2 — pre-screen (~100 wallets × 2 pages)

Rank key: (supported-venue share by value) × (has known-basis buys) × (not bundle/bot).
Bundles / zero-basis distribution are dropped with an explicit reason.

```bash
.venv/bin/python scripts/live_e2e.py \
  --live \
  --grant "$ARMED" \
  --phases 2 \
  --window-days 30 \
  --earlier-history-days 60 \
  --min-in-window-tx 0 \
  --max-unsupported-share 1 \
  --max-bot-rate 25 \
  --resume \
  --ledger-dir "$HOME/.scanner/live-e2e-ledgers" \
  --output "$OUT"
```

A 429 is receipted (failed) and back-off sleeps. Resume with `--explicit-retry`
for that wallet; new `--wallets` are screened even if phase 2 was previously
marked done.

## Phase 3 — full history for ~25 wallets (density-estimated pages; cap 200 / 12,000)

`--history-to-first` walks back to wallet creation (or `--history-start-unix`)
so open lots at window start get a real cost basis. Record `history_complete`
honestly: leftover token + preBalance > 0 is truncated.

```bash
.venv/bin/python scripts/live_e2e.py \
  --live \
  --grant "$ARMED" \
  --phases 3 \
  --window-days 30 \
  --history-to-first \
  --per-wallet-cap 8 \
  --resume \
  --ledger-dir "$HOME/.scanner/live-e2e-ledgers" \
  --output "$OUT"
```

## Phase 4 — offline replay (0 provider calls)

Every replayed page must match its `.integrity.json` `written_sha256`. A JSON
error body or hash mismatch is `blocked`, never “no records”.

```bash
.venv/bin/python scripts/live_e2e.py \
  --dry-run \
  --grant config/live_authorization.live-e2e-proof-2026-10-09-mitch-draft.json \
  --phases 4 \
  --resume \
  --ledger-dir "$HOME/.scanner/live-e2e-ledgers" \
  --output "$OUT"
```
