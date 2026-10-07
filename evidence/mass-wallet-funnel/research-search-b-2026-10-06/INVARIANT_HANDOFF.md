# Invariant acceptance handoff (implementing agent)

Fill these values into the ChatGPT brief header.

- Candidate full commit SHA: `4986e795e6e336b4afdea31f521a94cbd6382cf4`
- Application/tested SHA: `4986e795e6e336b4afdea31f521a94cbd6382cf4`
- Evidence-only SHA: `cd5c80314694156d50813f26943d71700761c4e3`
- Broken tip under attack: `2fe60bd8d0e4ec3a996f80d8b2f1e9bac1152d20`
- PR / branch: PR #6 / `cursor/research-search-b-fix-1055` (confirmed; base `cursor/mass-wallet-funnel-v1-1055`)
- Evidence manifest: `evidence/mass-wallet-funnel/research-search-b-2026-10-06/INVARIANT_REGISTRY.md`
- Raw logs: `evidence/mass-wallet-funnel/research-search-b-2026-10-06/offline-acceptance/`
- Offline acceptance command:

```
.venv/bin/python scripts/offline_acceptance.py
```

- Adapted 8-blocker reproducer:

```
env -u HELIUS_API_KEY -u BIRDEYE_API_KEY .venv/bin/python scripts/minimal_repros_2fe60bd.py
```

- Known NOT RUN / BLOCKED: physical-phone testing; interactive browser walkthrough; live capture; any Helius/Birdeye request
- Flags: `PRODUCT_READY=false`; next-capture draft `enabled:false`; G1 grant expired on its documented `expires_at` (not extended); no merge; $0
- Suites: keys-unset 3764 passed / 3 G1-expiry failed / 440 subtests; dummy 3764 passed / 3 G1-expiry failed / 440 subtests; offline acceptance ok; 9/9 safety mutants caught (M4/M9/JS2/JS4 included)
