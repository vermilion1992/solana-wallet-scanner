# Invariant acceptance handoff (implementing agent)

Fill these values into the ChatGPT brief header.

- Candidate full commit SHA: `517c721d25c9812ec113a7fad66d4aefffb396dc`
- Application/tested SHA: `517c721d25c9812ec113a7fad66d4aefffb396dc`
- Evidence-only SHA: `ea0a0835eb99437015c776a4a504e744ee2f0670`
- PR / branch: PR #6 / `cursor/research-search-b-fix-1055` (confirmed; base `cursor/mass-wallet-funnel-v1-1055`)
- Evidence manifest: `evidence/mass-wallet-funnel/research-search-b-2026-10-06/INVARIANT_REGISTRY.md`
- Raw logs: `evidence/mass-wallet-funnel/research-search-b-2026-10-06/offline-acceptance/`
- Offline acceptance command:

```
.venv/bin/python scripts/offline_acceptance.py
```

- Known NOT RUN / BLOCKED: physical-phone testing; interactive browser walkthrough; live capture; any Helius/Birdeye request
- Flags: `PRODUCT_READY=false`; draft `enabled:false`; no merge; $0
- Suites: keys-unset 3747 passed / 440 subtests; dummy 3747 passed / 440 subtests; offline acceptance ok
