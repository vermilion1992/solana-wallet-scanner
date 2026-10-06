# Independent reviews of the Mitch-review fix commit

App SHA reviewed: `f24aff7` plus the committed `frontend/dist` rebuild (`index-Dfbh-8ex.js`) and the regenerated 2000-record ledger. Branch `cursor/research-search-b-fix-1055`. Draft PR #6.

Reviewers were instructed not to modify the application. They must name the affected requirement. Blocking findings stay blocking. Nits are recorded, not required.

Independence note: `tools/independent_episode_audit.py` imports no `scanner/` package. Shared code with the app is JSON parsing only. `tools/independent_capture_reconciliation.py` still shares the decoder and is not the item-15 auditor.

## This fix pass

| Reviewer | Scope | Verdict |
| --- | --- | --- |
| Accounting / items 1–12, 14–15 | coverage fields and 90/95/96 bounds; verified Jito tips only; decoded-unresolved-cash vs unsupported_swap; opening inventory 100/100/100; partly backed sales not clean; cross-currency unconverted; qualification levels; worksheet errors surfaced; independent audit on this commit | **ACCEPT** at `f24aff7` + ledger regen. No requirement-violating findings. PRODUCT_READY remains false. CccS is the only provisional research lead and the only default-screen completed row. |
| App / security / items 13, 16–17 | catalog from committed manifest; no live dispatch; drafts `enabled:false` including the depth-biased next-capture file; OKX/DFlow not accepted as reviewed outers; dist rebuilt; PRODUCT_READY false | **ACCEPT** at `f24aff7` + dist rebuild. No requirement-violating findings. |

Accounting nits (not blocking): 58PW win-rate can print 3/2 = 1.5 when episode-P&L rows and clean-episode counts diverge; that wallet is coverage-blocked. Fee-audit verified tips on gtfo (3.303280298 SOL) are identified on compiled System transfers; they are a labelled cost series, not a reason to treat unresolved debits as tips. Independent auditor reconstructs Pump/PumpSwap/Jupiter only — remaining histogram venues stay out of its episode set. Ledger unresolved-sale counts can differ from worksheet counts when isolation includes opening-inventory fragments; item-12 status still agrees (gtfo/A6PS pending, CccS/An9s provisional eligible).

App-security nits (not blocking): committed `frontend/dist` was stale at `f24aff7` and is rebuilt in this evidence commit. Pre-existing consumed G1 grant file stays enabled in its own expired grant file and is not armed by this pass. Phone-emulation screenshots from pass 1 were not regenerated.

A6PS EkFRff residual (item 9): 0.001513840 SOL is explained by identified program-account funding, excluded from swap consideration. Never claimed recoverable rent or economically neutral.
