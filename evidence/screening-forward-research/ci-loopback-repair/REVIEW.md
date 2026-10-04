# CI isolation repair review

A fresh isolated Linux network namespace reproducibly fails a loopback socket connection with errno 101 because `lo` starts down. The original failure is retained in `namespace-loopback-baseline.json`. This is a CI environment failure, not a reason to skip the real WebSocket controls.

Each of the three workflow wrappers now enables only `lo` inside the isolated namespace and then executes the unchanged privilege-dropping command. The provider/credential guards remain intact. Independent inspection of the positive probe log verifies exactly one interface, `lo`, and only loopback routes: no default route, gateway or nonloopback route exists. Both actual local WebSocket tests pass in that namespace; the 154 validator controls also pass.

`RECEIPT.json` binds the actual 94dcbba source manifest and the preserved probe/log bytes. An exact Git comparison from c321 to 94dcbba changes only the workflow and three acceptance/issue documents. Runtime, frontend and dependency locks are unchanged. Earlier 35b4507/b53bd5 live receipts remain immutable; this comparison makes no new live-evidence claim. Final browser/product gates and the hosted result are separate receipts.
