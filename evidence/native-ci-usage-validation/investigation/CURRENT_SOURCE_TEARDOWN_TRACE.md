# Current-source indexed integration teardown trace

Read-only inspection of HEAD `af02789bb33a3baa0ddf4592d883bab3074c093d` on
`codex/product-completion`. No application, test, configuration, or Git changes;
no provider, credential, or GitHub calls. Existing untracked evidence remains
untouched. This source trace is not a reproduced timeout or an accounting defect.

## Evidence and limits

The downloaded native attempt 1 backend log collected 15 items and prints 13
call-phase `PASSED` reports, ending with the genuine 200-record node at 86%.
Its final marker is `VALIDATION_COMMAND_TIMEOUT: limit=600s; command and supported
descendant scope stopped`. The receipt records backend state `BLOCKED`,
`timed_out=true`, `seconds=789.56`, source unchanged, overall `INCOMPLETE`.
Neither the log nor receipt records a traceback, memory sample, teardown duration,
or precise stalled stack. The two following CLI nodes have no execution receipt.

An older local profiling log under
`evidence/ci-completion-batch/ci/PROFILE_test_indexed_report_integration.log`
records the genuine call at 61.28s and its teardown at 24.36s, with 15 passed in
88.89s. This is historical evidence of costly teardown; it does not bind current
native timeout causality.

## Confirmed source path after the genuine call

1. `tests/test_indexed_report_integration.py:28` imports and uses the
   function-scoped `session` fixture from
   `tests/test_discovery_integration_review.py:55`, not from `conftest.py`.
   `session` opens `local_session`, which owns the `TestClient` lifespan context.
2. `guarded` snapshots `deepcopy(client.get('/api/state').json()['usage'])`
   before yielding. Its finalization first checks all three counters equal zero,
   then evaluates the same full-state request and asserts usage equality
   (`test_indexed_report_integration.py:46-49`). All report and parent immutability
   assertions already ran inside the genuine call.
3. `/api/state` defaults to `report_view='full'` (`scanner/app.py:765`). It computes
   storage statistics, then `reports('full')`, then `discovery_cohorts(saved_reports)`.
4. `report_inputs('full')` loads every complete saved report with
   `store.list('reports')`, JSON-decodes it, and sorts by creation time
   (`scanner/app.py:158-170`; `scanner/storage.py:64-67`). The genuine case saved
   both its parent and one rebuilt child, each carrying 200 selected records.
5. `decorate_report` performs qualification/copy review and appends current
   methodology assessments (`scanner/app.py:172-212`). Those functions inspect
   saved objects; they do not load archived bytes or start HTTP/credential work.
6. `discovery_cohorts` unconditionally executes `report_inputs('summary')` before
   reading the cohort list (`scanner/app.py:214-234`). Consequently even the
   genuine test's empty cohort list causes another SQL projection of report
   inputs. `summary_inputs` includes metrics, events, positions, research and
   token-risk objects needed by qualification/copy review, and JSON-decodes
   extracted objects before transient summary omissions
   (`scanner/report_view.py:12-70`). The full and summary reads are separate.
7. The state route returns a Python dictionary. FastAPI encodes its complete
   response and `client.get(...).json()` decodes the complete response before
   indexing only `usage`. The saved full report carries duplicated wallet,
   source-consistency and chronology proof trees in `coverage` and
   `archive_accounting` (`scanner/app.py:392-435`). This makes the fixture's
   usage-only check dependent on full-report serialization and memory demand.
8. Only after guarded finalization does session exit `TestClient`. Lifespan
   shutdown marks closing, cancels worker and scheduler, awaits both cancellations,
   then closes SQLite (`scanner/app.py:651-663`). The worker waits on `wake`, and
   the scheduler waits 15 seconds with refresh default zero
   (`scanner/app.py:522-526,590-596`). Offline imports save a completed scan
   directly and do not set `wake` (`scanner/app.py:1056-1071`). This inspection
   found no application timeout retry, provider dispatch, or archival reread in
   the normal shutdown path. A hang in a dependency is unproved.

## Minimal potential directions, pending runtime profile

- The narrowest fixture correction can snapshot and compare
  `client.get('/api/usage').json()` instead of loading full state twice. This
  endpoint returns the same `usage()` value as `state['usage']`
  (`scanner/app.py:788,793-795`). Keep the equality assertion and all three zero
  counters, every test node, independent fee arithmetic, parent bytes and rebuild
  assertions unchanged. This avoids irrelevant full-state work without reducing
  the guard's usage intent. Existing `tests/test_report_view.py:79-86` independently
  compares full and summary state usage/cohorts and saved-row immutability.
- A separate application cleanup could read cohorts first and omit planner report
  SQL projection when that list is empty. It must preserve nonempty cohort audit
  planning and all semantic summary inputs.
- If runtime profiling confirms FastAPI recursive encoding dominates the shared
  report/state API, an explicit `JSONResponse` for already JSON-safe saved payloads
  is a potential shared fix. Prove exact full/display/summary semantics and exports
  before accepting it. Do not globally cache mutable evidence or delete proof
  trees from saved parents. The trace alone does not establish its benefit.

No source edits or changed test scopes have been made. Native timeout cause,
environment limits, cancellation and OOM remain unproved. The bounded unchanged
source genuine-node profile is a separate agent workstream.

## Inspected source SHA-256

| Path | SHA-256 |
| --- | --- |
| scanner/app.py | b437ab3dc61a49c261949fb2b003957ccf5278337e38da09840161448940a3f6 |
| scanner/storage.py | df41e348e3a9cea123e7bd8b7aa0eb8369fe634931088e40496fb27adf263946 |
| scanner/report_view.py | e809083c2fee60dd2da0c8db9f8f5fd4040df8740c10fb2145469c76a62a9bdb |
| scanner/copy_review.py | d96f7cca8cf9c5d51f9c60721171d049e1785fe32177fb45878a3c05fb6242b1 |
| tests/test_indexed_report_integration.py | 396313d4f3cf33dde4599e0900ea23c9f014a7af7aa2d601f22c9a5e627f14f2 |
| tests/test_discovery_integration_review.py | 59c43b9f0a9d1c0c0fc53cf72f1c1578b8a4debf82fff137ca121ae812850eb9 |
