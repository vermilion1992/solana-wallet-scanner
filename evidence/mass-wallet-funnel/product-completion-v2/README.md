# Product-completion-v2 proof bundle

Mitch A–D + research-screen fold on draft PR #4. No live provider calls. No
spend. No deployment. Both grant drafts stay DISABLED. `PRODUCT_READY`
remains false.

Frozen / tested app SHA: `1ab254253900a48ee7858731e04faafd09d1210f`.
Backend: 3604 passed / 0 failed. Frontend build passed
(`index-DkLGyhOf.js`). A–H PASS. LAN PASS. 390×844 is Playwright browser
emulation, not a physical phone. Genuine multi-wallet validation is BLOCKED.

## Reproduction

```
git rev-parse HEAD   # evidence tip; app SHA 1ab254253900a48ee7858731e04faafd09d1210f
./.venv/bin/python -m pytest -q
cd frontend && npm ci && npm run build
PRODUCT_PHONE_OUT=/tmp/product-phone-v2 ./.venv/bin/python tools/product_phone_acceptance.py
PRODUCT_LAN_OUT=/tmp/product-lan-v2 ./.venv/bin/python tools/product_lan_phone_acceptance.py
PYTHONPATH=. ./.venv/bin/python tools/independent_capture_reconciliation.py --target rank1
PYTHONPATH=. ./.venv/bin/python tools/independent_capture_reconciliation.py --target g1
PYTHONPATH=. ./.venv/bin/python tools/independent_capture_reconciliation.py --target synthetic --fixture tests/fixtures/synthetic_engineering/partial-match-fee-free.json
```

LAN (operator Wi-Fi only): `./run.sh --lan --no-browser`. Token is printed
once; do not commit it. Unauthenticated API returns 401.

## Index

| File | Contents |
| --- | --- |
| `COMPLETION_CHECKLIST.md` | requirement / status / evidence / remaining action / external dependency |
| `DEFECT_A.json` … `DEFECT_D.json` | One evidence ref per defect |
| `ACCEPTANCE_CHECKLIST.md` | Tracks (a) app (b) genuine-data (c) access (d) research separately |
| `RESEARCH_RUN.json` | Snapshot screen: 99 inconclusive, rank-1 zero-qualified |
| `RESEARCH_SEARCH_PROPOSAL.json` | Separate disabled 10×2 / 200-credit draft |
| `CAPTURE_PROVENANCE.json` | Rank-1 page-0 + G1 control + synthetic separation |
| `HEADLINE_376.md` | Exact lots/sells behind +376.028087 USDC |
| `INDEPENDENT_RECON_RANK1.json` | Standalone Decimal FIFO from raw capture |
| `INDEPENDENT_RECON_G1.json` | Standalone G1 FIFO |
| `INDEPENDENT_RECON_FEEFREE.json` | Fee-free 6@36 / sell 10@100 |
| `APP_VS_INDEPENDENT.json` | Position-level app vs standalone |
| `DISPOSITION_100.json` | All 100 ranked wallets + research-screen counts |
| `DRAFT_RUN_PREPARED.json` | Five full addresses; next-candidates grant not enabled |
| `ACQUISITION_RECORD.json` | Not authorised, not performed, 0/0/$0 |
| `VALIDATION.json` | Suite / build / A–H / LAN at the frozen SHA |
| `TOKEN_ROUTES.json` | 80 `/api` routes 401 without session |
| `INDEPENDENT_REVIEWS.md` | Focused re-check of the final fold |
| `ui/` | 390×844 screenshots (no tokens) |
| `docs/REMOTE_PREVIEW_PROPOSAL.md` | Remote deployment proposal only |

Synthetic engineering fixtures stay out of genuine result files.
