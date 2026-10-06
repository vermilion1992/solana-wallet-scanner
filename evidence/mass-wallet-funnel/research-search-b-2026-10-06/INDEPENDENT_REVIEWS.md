# Independent reviews of the Mitch-review fix commit

App SHA reviewed: this branch tip after the aa2ef2d requirement-violation pass. Branch `cursor/research-search-b-fix-1055`. Draft PR #6.

Reviewers were instructed not to modify the application. They must name the affected requirement. Blocking findings stay blocking. Nits are recorded, not required.

Independence note: `tools/independent_episode_audit.py` imports no `scanner/` package. Shared code with the app is JSON parsing only. `tools/independent_capture_reconciliation.py` still shares the decoder and is not the item-15 auditor.

## This fix pass

| Reviewer | Scope | Verdict |
| --- | --- | --- |
| Accounting / items 1–12, 14–15 | coverage fields; published-list tips only; opening inventory; win rate unit interval; CccS sensitivity sign-flip cannot be a lead; coverage_status ≠ qualification_level from `research_label_tables`; An9s blocking_reason 1 episode < min_sample 3 plus 27 open lots; independent audit JSON | **ACCEPT pending suite-on-final-commit**. CccS is `conditional_captured_lot_result` / `coverage_eligibility_pending_reassessment`. An9s is `conditional_captured_lot_result` / `provisional_eligible`. provisional_research_lead = 0. PRODUCT_READY remains false. |
| App / security / items 13, 16–17 | catalog from committed manifest; no live dispatch; drafts `enabled:false`; OKX/DFlow not accepted; unauthenticated /api/state 401; phone-emulation screenshots required on the final commit | **ACCEPT pending suite + phone screenshots on the final commit**. PRODUCT_READY false. |

Accounting notes: 58PW win rate is now 2/2 = 1 on the same completed-episode set. Fee-audit verified tips require a published-list match (Jito, Astralane, Nozomi, Node1, NextBlock). Independent auditor reconstructs Pump / PumpSwap / Jupiter only — remaining venues mark the wallet not independently audited and keep it from being a lead.

App-security notes: committed `frontend/dist` must be rebuilt on this UI pass. Phone-emulation screenshots (390×844) are required on the final commit because the UI now shows both fields.
