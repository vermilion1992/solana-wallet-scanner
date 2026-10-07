# Product-completion-v2 proof bundle

Release pass on draft-then-ready PR #4. No live provider calls. No spend.
No deployment. Both grant drafts stay DISABLED. `PRODUCT_READY` remains
false because the mandatory genuine ranked multi-wallet gate is BLOCKED.

Frozen / tested app SHA: `c34eb2cec41bdbb3a2ef6d7c349d20d01db635bc`.
Backend: 3607 passed / 0 failed. Frontend build passed
(`index-hN-S6YfT.js`). Clean `./run.sh` PASS (fresh + existing data dir).
A–H PASS. LAN PASS. 390×844 is Playwright browser emulation, not a
physical phone.

## Reproduction

```
git checkout c34eb2cec41bdbb3a2ef6d7c349d20d01db635bc
./.venv/bin/python -m pytest -q
cd frontend && npm ci && npm run build
PRODUCT_CLEAN_LAUNCH_OUT=/tmp/product-clean-launch ./.venv/bin/python tools/product_clean_launch.py
PRODUCT_PHONE_OUT=/tmp/product-phone-v2 ./.venv/bin/python tools/product_phone_acceptance.py
PRODUCT_LAN_OUT=/tmp/product-lan-v2 ./.venv/bin/python tools/product_lan_phone_acceptance.py
```

LAN: `./run.sh --lan --no-browser`. Operating notes: `docs/OPERATING.md`.

## Index

| File | Contents |
| --- | --- |
| `RELEASE_CHECKLIST.md` | Authoritative seven-section release checklist |
| `DEFECT_A.json` … `DEFECT_D.json` | One-paragraph fix + test node id + log path |
| `CLEAN_LAUNCH.json` | Fresh + existing `./run.sh` + LAN |
| `RESEARCH_RUN.json` | 99 inconclusive; rank-1 zero-qualified; search not executed |
| `DISPOSITION_100.json` | All 100 ranked wallets + qualification counts |
| `ACQUISITION_RECORD.json` | Not authorised, 0/0/$0 |
| `RESEARCH_SEARCH_PROPOSAL.json` | Separate disabled 10×2 / 200-credit draft |
| `VALIDATION.json` | Suite / build / clean launch / A–H / LAN |
| `TOKEN_ROUTES.json` | 80 `/api` routes 401 |
| `ui/v5_phone_*.png` | 390×844 screenshots (no tokens) |
