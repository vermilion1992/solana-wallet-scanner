# Independent reviews of the research-search B fix commit

App SHA reviewed: `1b3f8d6` (accounting + app-security). Dist rebuild and decoder fee-isolation follow-up: `1d1b3ec`.

Reviewers were instructed not to modify the application. They must name the affected requirement. Blocking findings stay blocking. Nits are recorded, not required.

Independence note: `tools/independent_capture_reconciliation.py` is algorithm-independent and shares only the decoder. After `1b3f8d6` it does not import `scanner.accounting`, `scanner.mass_search.settlement`, `live_g1`, `metrics`, or `service`.

## This fix pass

| Reviewer | Agent | Scope | Verdict |
| --- | --- | --- | --- |
| Accounting / C + D1–D10 + screen decision | [Accounting re-review](bc-e737216f-3743-5195-8730-0cf5df8d9e56) | isolate known cost, completed episodes, 0≠sale-count, mixed worksheets, signature-keyed analytics, conversions, fees+tips, unsupported txs, unset thresholds not applied | **ACCEPT** at `1b3f8d6`. No requirement-violating findings. |
| App / security A B D5 D7 D8 D9 | [App-security re-review](bc-43d38d96-6c80-5eba-a7c2-30339867317d) | catalog from committed manifest, no live dispatch, analysed-row labels, compare text, drafts disabled, D9 monkeypatch, visible_report 0 stays 0, PRODUCT_READY false | **ACCEPT** at `1b3f8d6`. No requirement-violating findings. |

Accounting nits (not blocking, not required): UI subset panel still renders net more prominently than the three-way split; win-rate numerator is mint-level; `ValueError` around worksheet build still swallows; decoder imports `scanner.accounting` helpers; `supported_transaction_format` still excludes version 1 even though mass-search decode accepts it.

App-security nits (not blocking): committed `frontend/dist` was stale at `1b3f8d6`. That nit was fixed in `1d1b3ec` (`index-DpiADeUU.js`). Pre-existing consumed G1 grant file stays enabled in its own expired grant file and is not armed by this pass.

A6PS EkFRff residual (accounting review, independently recomputed): decoded gross 297.931068225 − fees+tips 5.954070 = net 291.976998225 vs raw wallet Δ 291.975484385. Residual 0.001513840 SOL is same-tx account-funding, not P&L.
