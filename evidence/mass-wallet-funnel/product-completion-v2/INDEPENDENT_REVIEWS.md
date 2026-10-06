# Independent reviews (focused final fold)

App SHA reviewed: `1ab254253900a48ee7858731e04faafd09d1210f`
(reviewers launched against `7906f05`; the only later app change is the
filter-form default so research-screen `min_sample_positions=3` is not
written into saved reconstructed filters).

Reviewers were instructed not to modify the application. They must name
the affected requirement. Blocking findings stay blocking.

## This fold

| Reviewer | Agent | Scope |
| --- | --- | --- |
| Accounting / C + evidence classes | [Accounting A-D review](bc-50968f34-9c5c-5886-9ffd-beb073a4fd7f) | Partial-match FIFO, fee-free +24/40/100, rank-1 +376.028087 and G1 −0.167725526 unchanged, classes 1–5 |
| App / security A B D + grants | [App security A-D review](bc-70213343-7b25-5034-9cf4-c3634d700719) | HTTP 409 admission, visible_report persist, compare window policy, both drafts disabled |

Independence note: `tools/independent_capture_reconciliation.py` is
**algorithm-independent, shared decoder**. It does not import
`scanner.accounting` / `settlement` / `live_g1` / `metrics` / `service`.
It does share `decode_supported_swaps` + canonical wrap via
`investigation` / `capture_catalog`.

Prior nits at `c0128f2` / `accbf13` that Mitch required were folded into
this SHA (atomic HTTP admission, persist False, partial-match FIFO,
real window compare). Those are no longer open.

## Material findings requiring a code fix

None applied after the filter-form default fix (`1ab2542`). If either
reviewer returns a named blocking requirement, it will be fixed on a new
app SHA and this file updated.
