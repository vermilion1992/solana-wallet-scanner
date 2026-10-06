# Product-completion-v2 proof bundle

Lead-engineer completion pass on draft PR #4. No live provider calls. No
spend. No deployment. Draft grant stays DISABLED. `PRODUCT_READY` remains
false.

Frozen / tested app SHA: `c0128f2e25d88d53e2bb0c4a45e6b8cb13f57cbf`.
Backend: 3585 passed / 0 failed (+5 vs 8753392). Frontend build passed.
A–H PASS. LAN PASS. 390×844 is Playwright browser emulation, not a physical
phone. Genuine multi-wallet validation is BLOCKED.

## Reproduction

```
git rev-parse HEAD   # app SHA c0128f2e25d88d53e2bb0c4a45e6b8cb13f57cbf
./.venv/bin/python -m pytest -q
cd frontend && npm ci && npm run build
PRODUCT_PHONE_OUT=/tmp/product-phone-v2 ./.venv/bin/python tools/product_phone_acceptance.py
PRODUCT_LAN_OUT=/tmp/product-lan-v2 ./.venv/bin/python tools/product_lan_phone_acceptance.py
PYTHONPATH=. ./.venv/bin/python tools/independent_capture_reconciliation.py --target rank1
PYTHONPATH=. ./.venv/bin/python tools/independent_capture_reconciliation.py --target g1
```

LAN (operator Wi-Fi only): `./run.sh --lan --no-browser`. Token is printed
once; do not commit it. Unauthenticated API returns 401.

## Index

| File | Contents |
| --- | --- |
| `ACCEPTANCE_CHECKLIST.md` | Tracks (a) app (b) genuine-data (c) access (d) research separately |
| `CAPTURE_PROVENANCE.json` | Rank-1 page-0 + G1 control + synthetic separation |
| `HEADLINE_376.md` | Exact lots/sells behind +376.028087 USDC |
| `INDEPENDENT_RECON_RANK1.json` | Standalone Decimal FIFO from raw capture |
| `INDEPENDENT_RECON_G1.json` | Standalone G1 FIFO |
| `APP_VS_INDEPENDENT.json` | Position-level app vs standalone |
| `DISPOSITION_100.json` | All 100 ranked wallets |
| `DRAFT_RUN_PREPARED.json` | Five full addresses; grant not enabled |
| `ACQUISITION_RECORD.json` | Not authorised, not performed, 0/0/$0 |
| `VALIDATION.json` | Suite / build / A–H / LAN at the frozen SHA |
| `INDEPENDENT_REVIEWS.md` | Accounting and app/security review passes |
| `ui/` | 390×844 screenshots (no tokens) |
| `docs/REMOTE_PREVIEW_PROPOSAL.md` | Deployment proposal only |

Synthetic engineering fixtures stay out of genuine result files.
