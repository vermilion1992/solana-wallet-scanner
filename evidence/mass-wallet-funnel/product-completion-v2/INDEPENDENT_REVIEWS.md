# Independent reviews (focused final changes)

App SHA reviewed: `c34eb2cec41bdbb3a2ef6d7c349d20d01db635bc`

Reviewers were instructed not to modify the application. They must name
the affected requirement. Blocking findings stay blocking.

Independence note: `tools/independent_capture_reconciliation.py` is
**algorithm-independent, shared decoder**. It does not import
`scanner.accounting` / `settlement` / `live_g1` / `metrics` / `service`.
It does share `decode_supported_swaps` + canonical wrap via
`investigation` / `capture_catalog`.

## This release pass

| Reviewer | Agent | Scope |
| --- | --- | --- |
| Accounting / C + qualification | launched after evidence push | Partial-match FIFO, fee-free +24/40/100, rank-1 +376.028087 and G1 −0.167725526 unchanged, qualification categories |
| App / security A B D + grants | launched after evidence push | HTTP 409 admission, attach/step, visible_report persist, compare window policy, both drafts disabled, `./run.sh` |

Prior fold reviewers [Accounting A-D review](bc-50968f34-9c5c-5886-9ffd-beb073a4fd7f)
and [App security A-D review](bc-70213343-7b25-5034-9cf4-c3634d700719)
returned BLOCK on attach re-run, collapsed partial-sell analytics, and
thin compare-window tests. Those named requirements were fixed on
`963308c` / `c34eb2c` (this freeze).
