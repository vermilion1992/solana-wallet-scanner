# RANKED_100_DISCOVERY_PILOT — live one-shot notes

- Grant id: `live-g2-ranked100-discovery-2026-10-05-mitch`
- Clone justification: API keys exist only on this box (not Cloud Agents); local clone allowed when work depends on machine-local secrets.
- Repo: `/workspace/solana-wallet-scanner-g1` on `cursor/mass-wallet-funnel-v1-1055` at `745dd5e`.
- In-repo grant `config/live_authorization.g2-ranked100-discovery-granted.json` left `enabled: false` (uncommitted).
- Armed override (local only): `live_authorization.g2-ranked100-discovery-armed.json` — enabled=true, Birdeye 1 req / 30 CU, existing_plan_confirmed, remaining_quota_confirmed_at set. **Do not commit/push.**
- Working-tree CU amendment (not committed/pushed): arming hard-check and documented estimate raised 25→30 to match Mitch docs/ceiling.
- Official offline CLI refuses `--live`; used local `/workspace/ranked100-live-results/run_live_once.py` calling `run_ranked100_pilot(..., allow_live=True)`.
- Helius: 0 requests / 0 credits. PRODUCT_READY=false. No merge. Setup-pilot unchanged.
