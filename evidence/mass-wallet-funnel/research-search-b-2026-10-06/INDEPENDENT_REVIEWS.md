# Independent reviews of the Mitch-review fix commit

App SHA reviewed: `d961824` plus the phone-emulation screenshot / TESTS.md evidence commit on `cursor/research-search-b-fix-1055`. Draft PR #6. Bundle `frontend/dist/assets/index-Bj4UsG-X.js`.

Reviewers were instructed not to modify the application. They must name the affected requirement. Blocking findings stay blocking. Nits are recorded, not required.

Independence note: `tools/independent_episode_audit.py` imports no `scanner/` package. Shared code with the app is JSON parsing only.

## This fix pass

| Reviewer | Scope | Verdict |
| --- | --- | --- |
| Accounting / items 1–12, 14–15 | coverage fields; published-list tips only; opening inventory; win rate unit interval; CccS sensitivity sign-flip cannot be a lead; coverage_status ≠ qualification_level from `research_label_tables`; An9s blocking_reason `1 completed episode < min_sample 3; 27 open lots`; independent audit JSON; zero-episode wallets do not expose Net | **ACCEPT** at `d961824` + evidence commit. No requirement-violating findings. `provisional_research_lead` = 0. PRODUCT_READY remains false. |
| App / security / items 13, 16–17 | catalog from committed manifest; no live dispatch; drafts `enabled:false`; OKX/DFlow not accepted; dist rebuilt `index-Bj4UsG-X.js`; unauthenticated `/api/state` 401; 390×844 phone-emulation screenshots on this commit | **ACCEPT** at `d961824` + evidence commit. No requirement-violating findings. PRODUCT_READY false. |

Accounting notes: 58PW win rate is 2/2 = 1 on the same completed-episode set. Fee-audit verified tips require a published-list match (Jito, Astralane, Nozomi, Node1, NextBlock). Independent auditor reconstructs Pump / PumpSwap / Jupiter / Meteora DAMM v2 / RFQ Fill from pinned discriminators and isolates swap quote from tips/rent/program-account funding. Labelled wallets A6PS, gtfo, 58PW, CccS and An9s are independently_audited. BPxx Jupiter USDC legs reconstruct as trades but are not a clean completed episode (opening inventory / leftover), same as the app.

App-security notes: unauthenticated `/api/state` returned 401 in the phone-emulation run. No page errors. Dummy provider keys were never dispatched.
