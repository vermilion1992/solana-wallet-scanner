Read-only performance findings for ab62858dca7eccbdb18b3365a83dedd9b2e8f413

Application source: 241 files; SHA-256 0fad6d9bd6647b2663724d4bae2e280a02ed499f03f730eeff58f057ac98d365. The source manifest and four original archived input files were verified identical before and after the bounded baseline. The analyst changed no application files. The fixture is the genuine 200-record original page pair used by tests/test_indexed_report_integration.py:198, not a complete-wallet witness. Exactly 184 selected records failed. The independent integer payer-matched fee sum is 8,904,733 lamports (0.008904733 SOL). Profit remains unknown, qualification remains false, and PRODUCT_READY remains false.

The normal import → saved report → default/full GET → original-source inspection → JSON/CSV export → same-source offline rebuild passed. Parent SQLite payload bytes remained unchanged. Provider, credential, HTTP transport, and socket attempts were all zero; usage was unchanged; no collector ancestry was created. Outer exit 0, no timeout, 98.77 seconds, 300-second bound. Import and rebuild included cProfile instrumentation, so their 19.96/20.43-second observations must only be compared with similarly instrumented measurements. Full GET 9.055 seconds; JSON parse 0.924; pretty JSON export 6.476; display GET 1.901; state summary 0.611. Full raw response and saved compact JSON were byte-identical (181,198,289 bytes). Pretty JSON export was 296,613,696 bytes; display 36,272,837; state summary 505,531. Baseline process peak RSS 2,585,816 KiB includes profiling, tree registry, and parsed export; this is not normal browser/process memory.

Main object inflation paths (compact UTF-8 bytes; nested paths overlap):

- archive_accounting: 113,648,864; coverage: 64,710,135.
- coverage.wallet_evidence and archive_accounting.wallet_evidence: 59,933,554 each.
- Those two adapter.source_consistency copies: 38,482,910 each; additionally archive_accounting.source_consistency: 37,972,717. These are separately current assessments and cannot simply be presumed interchangeable.
- query_accounting: 9,612,914 at all three paths (coverage.wallet_evidence, archive_accounting.wallet_evidence, archive_accounting).
- Inside each query_accounting, historical_membership is 7,652,260; accounts 4,103,163; transactions 3,493,219.
- production_evidence: 2,541,008 at both coverage and archive_accounting.
- Metric requirements/dependencies: 1,737,174 at coverage.metric_dependencies and archive_accounting.metric_requirements; adapter.metric_dependencies is separately 1,731,731; production metric_decisions is 1,753,030 twice; metrics with embedded evidence_decision is 1,963,941.
- Adapter.interval_checks and adapter.intervals are the same declared map, 520,642 each, serialized twice in each adapter copy.
- Chronology is 761,710 at each adapter plus archive_accounting; report research is only 98,610, positions 24,908, events 214,910. Research and chronology are not the dominant 181 MB cause.
- One identical 13,535-byte SHA-256 evidence array occurs 1,846 times. Hash strings and duplicated source-account proofs dominate; concatenated reasons are not the main measured cause.

Structural paths responsible:

- scanner/app.py build_report: report.coverage retains wallet_evidence, derived decisions, production evidence, then adds the whole archive_accounting containing their aliases.
- scanner/archive_input.py analyze_archive: embeds adapter, source/chronology receipts, copied components, metric requirements, production proof, and additional query_coverage/query_accounting aliases.
- scanner/wallet_evidence.py derive_wallet_evidence: returns components, per-record/source proofs, interval_checks plus intervals aliases, metric dependencies, historical membership and selected accounting proofs.
- scanner/source_consistency.py assess_source_consistency: expands source/fact/check receipts into each account, native checks plus each native metric projection, and transaction. Those are intentional visible scoped contracts but repeated structurally.
- scanner/metric_evidence.py compose_metric_decisions projects component receipts per metric; apply_metric_decisions embeds a deep copy in each metric; production composition produces further dependency/numerical decisions and gate receipts.
- Store.put serializes expanded compact JSON; Store.get/list reparses it, losing construction-time alias identity. An identity-only memoized serializer cannot recover all post-load repetition.
- FastAPI dictionary response processing traverses the full expanded proof via jsonable_encoder before JSONResponse traverses it again.

Read-only encoding experiment on that exact saved baseline row:

- SQLite existing-parent read 0.749s; parse 0.968s.
- Direct JSONResponse: 0.689s, exactly 181,198,289 bytes and exactly the original default/full SHA-256 cc2a7cc7586c1115b41346216f8382393eec7450fd47531dcf471d6391351fed.
- jsonable_encoder alone: 5.029s; subsequent JSONResponse: 0.707s; bytes identical.
- Display direct JSONResponse 0.120s versus jsonable_encoder 0.407s; bytes identical.
- Gzip level 1: 13,766,059 bytes, 0.380s compression/0.272s decompression, exact round trip.
- Gzip level 6: 7,357,663 bytes, 0.828s compression/0.228s decompression, exact round trip.
- Measurement-only generic order-preserving container pool: 60,960,326 bytes; 980,825 container occurrences / 123,914 unique container values. Pool calculation cost 17.14s. This is evidence of repetition, not a recommended production codec or speed claim.

Recommended practical implementation sequence:

1. Return direct JSONResponse for JSON-native saved report/full/display and sibling state/preview/enrich outputs. Keep default/full fields, source references, sorting, response codes/headers, API JSON values, exports, parent bytes, errors and security identical. Saved reports are already bounded JSON-native values. Independently test sibling preview and enrich paths rather than blindly replacing arbitrary objects.
2. Profile/reuse fresh bounded indexed page validation within a single import or rebuild invocation. The cProfile baseline showed 42 validate_page_envelope calls consuming 8.785 profiled cumulative seconds, 7,417 bounded_value calls (8.661s), four assess_source_consistency calls (3.676s). Current local record normalization reuse is useful but duplicated across invocation consumers. Reuse must key exact checksummed bytes, wallet, role, validation version and interpretation context; mutation, alternative bodies, missing sources, new requests and rebuilds must never borrow a persisted trusted PASS. Preserve existing raw-boundary budgets and negative references. Decoder reuse is a smaller target in this corpus: 802 spot-decoder calls consumed 0.471 profiled seconds.
3. Treat storage compression/ref packing as a separate reviewed change if needed. Store.get/list must preserve legacy expanded rows and exact public values; report_view.summary_inputs directly uses SQLite json_extract(payload), so opaque compressed TEXT/BLOB would break summary reads unless a compatible JSON projection/shared reader is provided. Backup/restore, metadata readers and raw-row parent immutability tests must be covered. Gzip saves disk, but decoding still expands the proof and does not remove CPU traversal. A graph codec adds strict schema/hash/node/size/cycle checks and value isolation concerns; the 61 MB naive pool plus 17s calculation is not currently preferable to the narrow response fix.
4. Future compact proof representation, only if justified: a versioned content-addressed registry, exact source/method/interval/context bindings, deterministic references, no raw-evidence repacking or source-loss shortcut, separately replayable original refs. Expand the same existing default/full API/export schema and keep missing/bad refs fail closed. Any explicit compact view must label omitted paths and resolve existing source inspection. Default expanded output retains 181 MB by compatibility; HTTP compression or explicitly requested presentation views can reduce transfer without changing default JSON values.

Required sibling verification fixtures: archived genuine200 failed-fee population; original genuine87 successful selected-lot corpus and frozen separate raw oracle; synthetic positive/loss/breakeven/mixed-open/closed cases; selected plus linked alternatives; present/missing/corrupt/conflicting/unsupported/restored sources; report/28/90 independence; quantity/money isolation; default/full/display/state-summary/preview/enrich/export equality; parent saved/raw evidence immutability; zero provider/key calls; source unchanged after replay. For any later codec: legacy storage reads, null/missing/boolean/Unicode/precise decimal strings/order, unsupported versions, missing/cyclic/invalid refs, checksum mismatch, expansion budgets, child rebuild and backup/restore. Compression or interface existence does not close B1/B2/B3 or certify whole-wallet qualification.

Evidence outside Git:
- benchmark.py: reusable public workflow and structural profiler.
- BASELINE_OUTER_RECEIPT.json and baseline-ab62858.log: exact command, timeout, outer exit and raw log hash.
- baseline-ab62858/result.json, EXPECTED_RAW.json, input.zip, import/rebuild profiles: frozen observations, per-path bytes, invariants and raw independent oracle.
- encoding_comparison.py, encoding-ab62858.log, encoding-ab62858/result.json: exact byte-equivalence and compression/serialization timings.
- private-runtime/ contains private SQLite/session/generated state and must not be committed or published.
