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
| Accounting / C + qualification | [Accounting release review](bc-9ed96044-d638-5806-88fc-90a8840d3acf) | Partial-match FIFO, fee-free +24/40/100, rank-1 +376.028087 and G1 −0.167725526 unchanged, qualification categories |
| App / security A B D + grants | [App security release review](bc-9b5fc97a-107c-5fa0-88dc-c3ff84440334) | HTTP 409 admission, attach/step, visible_report persist, compare window policy, both drafts disabled, `./run.sh` |

[Accounting release review](bc-9ed96044-d638-5806-88fc-90a8840d3acf)
verdict: **ACCEPT** at `c34eb2c`. Requirement C holds: fee-free analytics
are matched 6@60 +24 and unmatched 4@40; qualification is separate from
screen pass/fail; rank-1 +376.028087 USDC and G1 −0.167725526 SOL
unchanged. Nits (not blocking, not fixed): non-USDC reconstruct path
skips isolate (G1 fully backed); classes 1/3/4 unused on today's
offline-replay path; unused screen keys stay UNSET.

[App security release review](bc-9b5fc97a-107c-5fa0-88dc-c3ff84440334)
verdict: **ACCEPT** at `c34eb2c`. Named requirements A, B, and D hold:
attach skips `run_batch`; `step_batch` claims one index; `visible_report`
absent never passes; compare is `own_windows_shown_mismatch_blocks`; both
drafts stay disabled. Nits (not blocking, not fixed): UI/`run_batch` retry
immediately on `already_executing`; unused `hydrate_visible_report(...,
fallback=True)` hook; cache compare skips a missing `analysis_cache_key`.

Prior fold reviewers [Accounting A-D review](bc-50968f34-9c5c-5886-9ffd-beb073a4fd7f)
and [App security A-D review](bc-70213343-7b25-5034-9cf4-c3634d700719)
returned BLOCK on attach re-run, collapsed partial-sell analytics, and
thin compare-window tests. Those named requirements were fixed on
`963308c` / `c34eb2c` (this freeze).
