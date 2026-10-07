# Box commands — LIVE E2E proof (next run: 2026-10-12 draft)

The **next** live grant is `config/live_authorization.live-e2e-proof-2026-10-12-mitch-draft.json`
(`enabled: false` in repo). Expiry is `2026-10-12T00:00:00+10:30`
(`2026-10-11T13:30:00Z`). Caps: Birdeye ≤40 requests / ≤1,400 CU; Helius ≤3,000
requests / ≤30,000 credits. Phase 2 ≥600 req. Hard ceilings in
`scanner/mass_search/live_e2e.py` (`HARD_CEILINGS`) cannot be raised by a local
commit. `PINNED_DRAFT_HASHES` must match the armed `draft_artifact_hash`.

The 2026-10-07, 2026-10-09 and 2026-10-11 drafts are **retired for `--live`**.
`--live` refuses those authorization ids. The 10-11 leftover P2 cap cannot
support ~250 pre-screens. PRODUCT_READY stays false. Do not merge. No paid
spend, overages, or upgrades.

The ledger home is the **absolute** path pinned in the committed draft
(`pinned_ledger_home` = `/home/box/.scanner/live-e2e-ledgers`) and in
`COMMITTED_LEDGER_ABSOLUTE`. It must not depend on `HOME`. Re-arming with a
new ledger home, or a fresh HOME that relocates `~/.scanner/...`, is refused.

Phase caps are sized for ~250–300 pre-screens (600 req / 6,000 credits) and
deep histories at `--per-wallet-cap 10` (400 req; 24,000 credit unit budget
binds first). The ledger is hash-chained and verified on every start.

## Arming (local copy only)

1. Copy the 2026-10-12 draft outside the repo.
2. Set `enabled: true`, `authorized_by_user_at`, `existing_plan_confirmed`,
   `remaining_quota_confirmed_at`.
3. Set `draft_artifact_hash` to the **pinned** SHA-256 in
   `PINNED_DRAFT_HASHES["live-e2e-proof-2026-10-12-mitch"]` (must also equal
   `git show HEAD:config/live_authorization.live-e2e-proof-2026-10-12-mitch-draft.json | sha256sum`).
4. Record identity (required for `--live`):
   - `armed_home`: `python -c "from pathlib import Path; print(Path.home())"`
     (must be `/home/box` on the operator box)
   - `ledger_home`: `/home/box/.scanner/live-e2e-ledgers` (absolute; must equal
     the committed draft `pinned_ledger_home` and `COMMITTED_LEDGER_ABSOLUTE`)
5. Mode 0600. Never commit the armed copy.

`--live` refuses `SCANNER_LIVE_LEDGER_HOME` / `SCANNER_LIVE_LEDGER_DIR` unless
they equal the pinned ledger home, and refuses if `HOME` differs from
`armed_home`. Leave those env vars unset on the box. `--ledger-dir` must equal
the pinned path.

Helius pacing defaults to 0.5s min interval (2 rps) and 2s backoff on 429.
Birdeye pacing defaults to 4s and 4s backoff on 429; a 429 or `success: false`
body is an error in the ledger. Every attempt is receipted.

`--history-to-first` (plain; no `--earlier-history-days 2366`) walks back to
wallet creation under `--per-wallet-cap`. One wallet hitting that cap is marked
`history_complete=false` / `per_wallet_cap` and the run continues. A leftover
pagination token is not the end unless first-funding is proven; a later sale
of a mint with no in-history acquisition is unknown basis and never complete.

A new output dir can import previously paid pages with `--import-raw-dir`
(verified against the ledger sha; no re-send) or is refused with copy guidance.
`--explicit-retry` re-sends failed receipts only. Consumed successes and a
page already saved after a kill are adopted, never re-sent.

Discovery for discretionary solo traders: gainers-losers `1W` sorted by `PnL`,
and/or top-traders on liquid established tokens (SOL/USDC/USDT/JUP/BONK) at
`7d`–`30d` `realized_pnl`. Cheap pre-screen rank
`(supported-venue share) × (known-basis buys) × (not bundle/bot/controlled_pair)`
sends the full-history budget to likely provables. Counterparties of
own-funded wallets (no co-sign) are cheap seeds.

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
Empty `--birdeye-tokens` on top-traders defaults to the established liquid
set (SOL, USDC, USDT, JUP, BONK).

## Dry-run planner (must show the plan fits)

```bash
.venv/bin/python scripts/live_e2e.py \
  --dry-run \
  --grant config/live_authorization.live-e2e-proof-2026-10-12-mitch-draft.json \
  --discovery \
  --discovery-source gainers-losers \
  --birdeye-window 1W \
  --birdeye-sort PnL \
  --phases all \
  --window-days 30 \
  --report-window-days 30 \
  --history-to-first \
  --per-wallet-cap 10 \
  --max-bot-rate 25 \
  --ledger-dir /home/box/.scanner/live-e2e-ledgers-dry-run \
  --output evidence/mass-wallet-funnel/live-e2e-proof-2026-10-07/dry-run-2026-10-12
```

Top-traders on liquid established tokens (35 CU each):

```bash
.venv/bin/python scripts/live_e2e.py \
  --dry-run \
  --grant config/live_authorization.live-e2e-proof-2026-10-12-mitch-draft.json \
  --discovery \
  --discovery-source top-traders \
  --birdeye-window 7d \
  --birdeye-sort realized_pnl \
  --phases 1 \
  --ledger-dir /home/box/.scanner/live-e2e-ledgers-dry-run \
  --output evidence/mass-wallet-funnel/live-e2e-proof-2026-10-07/dry-run-top-traders
```

## Phase 1 — discovery (≤40 / 1,400 CU)

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
  --history-to-first \
  --ledger-dir /home/box/.scanner/live-e2e-ledgers \
  --output "$OUT"
```

## Phase 2 — pre-screen (~300 wallets × 2 pages)

Rank key: (supported-venue share by value) × (has known-basis buys) ×
(not bundle / bot / controlled_pair). Service co-signers (Jito tip, Jupiter
`sighWH8K`) are not bundle partners. Closed-loop controller pairs are dropped.

```bash
.venv/bin/python scripts/live_e2e.py \
  --live \
  --grant "$ARMED" \
  --phases 2 \
  --window-days 30 \
  --history-to-first \
  --min-in-window-tx 0 \
  --max-unsupported-share 1 \
  --max-bot-rate 25 \
  --resume \
  --ledger-dir /home/box/.scanner/live-e2e-ledgers \
  --output "$OUT"
```

## Phase 3 — full history for ~40 wallets (per-wallet cap 10)

```bash
.venv/bin/python scripts/live_e2e.py \
  --live \
  --grant "$ARMED" \
  --phases 3 \
  --window-days 30 \
  --history-to-first \
  --per-wallet-cap 10 \
  --resume \
  --import-raw-dir "$PRIOR_RAW" \
  --ledger-dir /home/box/.scanner/live-e2e-ledgers \
  --output "$OUT"
```

`$PRIOR_RAW` is the previous run's `raw/` tree so paid pages are imported by
verified ledger sha. Omit it only when this output dir already holds those pages.

## Phase 4 — offline replay (0 provider calls)

Every replayed page must match the immutable ledger receipt sha256. A sidecar
rewrite of `written_sha256` alone is rejected.

```bash
.venv/bin/python scripts/live_e2e.py \
  --dry-run \
  --grant config/live_authorization.live-e2e-proof-2026-10-12-mitch-draft.json \
  --phases 4 \
  --resume \
  --ledger-dir /home/box/.scanner/live-e2e-ledgers \
  --output "$OUT"
```

Optional longer report window (default stays 30d):

```bash
.venv/bin/python scripts/live_e2e.py \
  --dry-run \
  --grant config/live_authorization.live-e2e-proof-2026-10-12-mitch-draft.json \
  --phases 4 \
  --resume \
  --window-days 30 \
  --report-window-days 90 \
  --ledger-dir /home/box/.scanner/live-e2e-ledgers \
  --output "$OUT"
```
