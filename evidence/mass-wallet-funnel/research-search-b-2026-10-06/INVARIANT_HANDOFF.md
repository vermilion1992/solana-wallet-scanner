# Invariant acceptance handoff (implementing agent)

Fill these values into the ChatGPT brief header.

- Candidate full commit SHA: pending the commit that lands this file; see git rev-parse HEAD after push
- Application/tested SHA: same as candidate
- Evidence-only SHA: same as candidate unless a later evidence-only commit exists
- PR / branch: PR #6 / `cursor/research-search-b-fix-1055` (confirmed)
- Evidence manifest: `evidence/mass-wallet-funnel/research-search-b-2026-10-06/INVARIANT_REGISTRY.md`
- Raw logs: `evidence/mass-wallet-funnel/research-search-b-2026-10-06/offline-acceptance/`
- Offline acceptance command:

```
.venv/bin/python scripts/offline_acceptance.py
```

- Known NOT RUN / BLOCKED: physical-phone testing; interactive browser walkthrough; live capture; any Helius/Birdeye request
- Flags: `PRODUCT_READY=false`; draft `enabled:false`; no merge; $0
