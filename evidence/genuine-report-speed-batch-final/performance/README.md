Corrected-source normal offline timing observations bound to application 0db4125e8c1ab6b2df5bb1e79e807c80e3d195bd, 246 source files, SHA-256 babd86cab36e5674d286b8b59f4692e8f2f0109e0c2375a36ab7a86ad1185b3c. These are scoped archive observations, not full candidate acceptance, full-scan performance guarantees or product readiness.

The earlier eea37dc full candidate failed a frozen native-reference regression. Its raw records and original timing/browser observations are preserved under evidence/genuine-report-speed-batch. The corrected-source timings below do not retroactively change that candidate outcome.

genuine200-normal: import 7.634s; same-source rebuild 9.374s; default full GET 2.136s; JSON export 5.595s. No cProfile enabled. Provider/credential/transport/socket counters all zero; original archive/source/locks unchanged; parent payload immutable; child metrics equal; full JSON export semantically identical.

genuine87-augmented-normal: import 3.466s; same-source rebuild 3.931s; default full GET 0.655s; JSON export 1.727s. No cProfile enabled. Provider/credential/transport/socket counters all zero; original archive/source/locks unchanged; parent payload immutable; child metrics equal; full JSON export semantically identical.

Separately worked selected fees remain 0.008904733 SOL (genuine200) and 0.000158868 SOL (genuine87). The supported selected genuine87 losing lot remains -0.013270924 SOL with 529 seconds holding; current native observation remains 650,240 lamports. Historical population, boundary valuation, wallet-wide profit and qualification remain unresolved. PRODUCT_READY remains false.

RELOCATION_INDEX.json binds each copied artifact to its exact original absolute location/bytes/hash and lists the repository reproduction inputs. Private runtime databases, credential/session state and large generated full responses/exports are excluded. The existing exact genuine200 and augmented genuine87 archives are referenced rather than duplicated.

Replay with python tools/benchmark_report.py --archive <required_repository_reproduction_input.zip> --output /absolute/fresh/directory/outside/all/Git/worktrees --full-details. The CLI is an observability utility; tools/validate.py remains the acceptance entry point.
