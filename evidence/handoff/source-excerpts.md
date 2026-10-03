# v0.3.11 numbered source excerpts

Copied from the uploaded archive; these are implementation/developer-source evidence, not independent execution of every claim.


## `docs/CODE_REVIEW_RESPONSE.md` — lines 1–26

```text
1: # Independent review response · v0.3.11
2: 
3: This responds to **Solana Wallet Scanner v0.3.10 — independent source review**, dated 3 October 2026. The reviewed ZIP remains unchanged: SHA-256 `bbaee877f65e7e74466ec71aff8c5dd94383d2c6ee96ec7552de43d9941237e7`. All 144 shipped source/compiled entries matched before edits. Its exact response is preserved as [CODE_REVIEW_RESPONSE_v0_3_10.md](CODE_REVIEW_RESPONSE_v0_3_10.md). All eleven prior ZIPs, historical responses and existing genuine fixture bytes are compared during packaging.
4: 
5: **R15 is corrected within the tested scoped contract. R14 representation guards remain in force. R1 remains OPEN in complete financial implementation and independent real-wallet acceptance.** No verified profitable wallet or copy-trading candidate is established.
6: 
7: ## Reproduction and correction
8: 
9: The untouched new review bundle on immutable v0.3.10 reproduces **35 passes and 44 ordinary failures**: 28 direct and 16 actual API cases for one required-target mapping defect. The failures represent false UNKNOWN for an otherwise supported synthetic named-account hold, not a new false profit qualification. Selected/alternative inputs retain eight/nine references and hashes. Profit remains unknown, policy UNRESOLVED, qualification false, wallet-wide gates UNKNOWN, and provider/credential calls zero.
10: 
11: The new R14 table incorrectly required `account` for approvals/revocation, and universally for `setAuthority`. I also wrote six positive supplemental cases against that incorrect spelling. Those tests did not establish RPC compatibility. This release corrects both the implementation and those inaccurate developer fixtures.
12: 
13: The primary Agave parser was fetched at commit `9480479ff42af8a9db3da1649297dfcd9d27e5be`; raw `parse_token.rs` SHA-256 is `50370cf477d4d526960a226a945f712426c059f220fd4c84f63f493da64d88c0`. [Pinned primary source](https://github.com/anza-xyz/agave/blob/9480479ff42af8a9db3da1649297dfcd9d27e5be/transaction-status/src/parse_token.rs): Approve/Revoke lines 180–219, SetAuthority 220–260, ApproveChecked 388–413. `tests/fixtures/token_instruction_schema.json` contains seven manually specified, source-referenced synthetic examples independent of the application's lookup table. They cover the three permission types and four standard authority branches. These are unsigned RPC-schema examples, not provider observations or authenticated mainnet transactions.
14: 
15: | Operation | Required scope references / branch |
16: | --- | --- |
17: | `approve` | `source`, `delegate` |
18: | `approveChecked` | `source`, `delegate`, `mint` |
19: | `revoke` | `source` |
20: | `setAuthority`: `mintTokens`, `freezeAccount` | `mint` |
21: | `setAuthority`: `accountOwner`, `closeAccount` | `account` |
22: 
23: An explicit supported string `authorityType` selects the authority branch. Missing, malformed, unreviewed extension or contradictory types/targets remain UNKNOWN; the competing `account`/`mint` field is unsupported even when values agree. `account` is not an admitted permission alias. Required targets remain nonempty strings; the resolver does not make targets optional or accept either name indiscriminately. Other minimum scope contracts and quantity/ownership semantics remain separate.
24: 
25: Permissions do not themselves transfer quantity or change account ownership. Later delegated transfers still need their own evidence. Valid unrelated mint-authority operations can prove disjointness; executed relevant account-owner and close-authority changes still block unsupported continuous-ownership claims. Rejections retain target/type/reference paths as well as signature, archive hash and reason. Parsed/opaque mixed representations, conflicting program identities and incomplete targets retain R14's guards. Atomic failure, independently supported fees and genuine disjoint/metadata witnesses retain their own meaning.
26: 
```


## `docs/CODE_REVIEW_RESPONSE.md` — lines 35–65

```text
35: ## Versioning and offline rebuilding
36: 
37: Only the affected position interpretation advances to **`account-position-evidence-v9`**. History remains `history-evidence-v8`, source consistency `source-consistency-v4`, chronology v2, accounting fifo-v3 and swap/nonce spot-v4-durable-nonce. Position v8 and earlier reports require a new child rebuild even when history is current. Frozen input references, presets, windows, prior values and parents remain unchanged. Existing correctly spelled sources require reinterpretation, not recollection.
38: 
39: The browser session uses thirteen synthetic parents actually interpreted with immutable v0.3.10, plus the cached real 23-record parent. Current children recover supported permissions/mint disjointness, retain account-owner/close-authority/missing-type/contradictory-target/mixed-shape rejection, and preserve fee isolation. The cached real observation still supports **0.000240394 SOL** in observed network fees, no known closed account episode and unknown global financial gates.
40: 
41: ## Validation
42: 
43: | Check | Executed result |
44: | --- | --- |
45: | Untouched new external review | **79 passed**: 44 regressions +35 controls, overlapping faithful shipped copies |
46: | Untouched original R14 replay | **57 passed** separately; overlaps shipped cases |
47: | Primary-schema supplemental tests | **58 passed**: seven schema examples, ten API inclusion/disjointness/rejection cases, six authority-type controls, 24 authority-target controls, nine permission-alias controls and two source-removal/restoration cases |
48: | Full shipped Python suite | **1,527 passed; 264 subtests passed**, 226.38 s; one existing Starlette test-client deprecation warning |
49: | Population | 1,389 prior +79 faithful +58 supplemental +one freshness =1,527; one current-method node rename, no semantic deletion |
50: | Frontend | **315 assertions** (16 formatter +299 UI/data); pinned TypeScript/Vite production build passes; JS `index-B-AqKu-Q.js`, CSS `index-Brz2fDKJ.css` |
51: | Bounded probes | Unmodified 240 shape mutations: no unexpected exceptions; unmodified 24 permission compatibility probes: supported six-hour holds; separate from pytest, not exhaustive fuzzing |
52: | Browser | **14 completed offline child rebuilds; 30 captures** (28 full-page +two focused) at 1440/390 px; no overflow, JS errors or external browser requests |
53: | Browser/data guards | Original parent rows/exports, frozen references and source SQLite preserved; provider calls/credential lookups zero; exhausted pilot remains 200 used/zero reserved; QA server stopped |
54: | Local runtime | Existing pinned Python 3.12.14/Node 24.19.0 environment; editable 0.3.11 metadata, pip check and shell syntax pass |
55: | Package | CRC, exact source/compiled bytes, executable modes, asset links, exclusions, older ZIPs/responses/fixtures and actual extracted launcher checked; final file count/checksum in external release artifact |
56: 
57: The first full run exposed one stale literal version assertion; it was updated from position v8 to v9, then the accepted full suite was rerun. An earlier supplemental run showed two missing target-path witnesses on ownership-operation rejection; the rejection now retains the validated reference paths, and those assertions pass. Neither failure was skipped or marked expected. Intermediate harness attempts and repeats are not counted as accepted runs.
58: 
59: No fresh dependency installation, advisory audit, OS keyring validation, Windows/macOS execution, independent browser acceptance, provider/mainnet authentication or full real-wallet acquisition is claimed. Browser checks and schema fixtures are developer validation. Public parser retrieval is independent of the provider; no Helius credits were spent or quota reset.
60: 
61: ## R1 remains OPEN
62: 
63: Complete historical ownership, acquisition basis, eligible populations, classification, valued external flows/boundary inventories and economic costs are not implemented as a completed independently validated wallet branch. The review correctly identifies missing implementation as well as missing acceptance data. All wallet-level requirements remain unconditionally UNKNOWN. A named-account six-hour hold or observed fee sum cannot fill the full wallet median, ROI or strict-profit fields.
64: 
65: The next major product milestone remains one supported real-wallet report with frozen archived inputs, independently calculated expected results and evidence-removal controls; a correctly calculated loss or policy miss is valid acceptance. PDF page 6 requires an independent historical ownership witness because a hidden closed-account round trip can leave no residual mismatch. Page 18 requires an explicit source-sufficiency decision if native data cannot provide it. Current account enumeration, fixed-point paging, selected cached receipts, more quota, relaxed thresholds or synthetic completion flags cannot satisfy those prerequisites. No profitable MATCH is required for engineering acceptance, and no copy-trading safety claim follows from this scoped correction.
```


## `scanner/instruction_scope.py` — lines 1–41

```text
1: """Normalize instruction evidence before proving named-account irrelevance.
2: 
3: Compiled/partially decoded account lists and fully parsed instructions have
4: separate supported shapes. A mixed parsed/accounts or parsed/data shape has no
5: reviewed reconciliation contract here, so neither representation may win.
6: These local checks do not authenticate a transaction on Solana.
7: """
8: from .decoder import TOKEN_IDS, SYSTEM_ID, ASSOCIATED_ID, COMPUTE_ID, MEMO_IDS
9: 
10: _TOKEN_REFERENCES = {
11:     'transfer': ('source', 'destination'),
12:     'transferChecked': ('source', 'destination', 'mint'),
13:     'approve': ('source', 'delegate'), 'approveChecked': ('source', 'delegate', 'mint'),
14:     'revoke': ('source',), 'closeAccount': ('account', 'destination'),
15:     'mintTo': ('mint', 'account'), 'mintToChecked': ('mint', 'account'),
16:     'burn': ('account', 'mint'), 'burnChecked': ('account', 'mint'),
17:     'freezeAccount': ('account', 'mint'), 'thawAccount': ('account', 'mint'),
18:     'initializeAccount': ('account', 'mint'), 'initializeAccount2': ('account', 'mint'),
19:     'initializeAccount3': ('account', 'mint'), 'initializeImmutableOwner': ('account',),
20:     'syncNative': ('account',), 'getAccountDataSize': ('mint',),
21:     'initializeMint': ('mint',), 'initializeMint2': ('mint',),
22: }
23: # Agave parse_token.rs, pinned schema reference in the conformance fixture.
24: # Extension authority types need their own reviewed contracts before admission.
25: _AUTHORITY_TARGETS = {'mintTokens': 'mint', 'freezeAccount': 'mint',
26:                       'accountOwner': 'account', 'closeAccount': 'account'}
27: _SYSTEM_REFERENCES = {
28:     'transfer': ('source', 'destination'), 'transferWithSeed': ('source', 'destination', 'sourceBase'),
29:     'createAccount': ('source', 'newAccount'), 'createAccountWithSeed': ('source', 'newAccount', 'base'),
30:     'assign': ('account',), 'assignWithSeed': ('account', 'base'),
31:     'allocate': ('account',), 'allocateWithSeed': ('account', 'base'),
32:     'advanceNonce': ('nonceAccount', 'nonceAuthority', 'recentBlockhashesSysvar'),
33:     'initializeNonce': ('nonceAccount',), 'authorizeNonce': ('nonceAccount',),
34:     'withdrawNonce': ('nonceAccount', 'destination'),
35: }
36: _ASSOCIATED_REFERENCES = {'create': ('account', 'source', 'mint', 'wallet'),
37:                          'createIdempotent': ('account', 'source', 'mint', 'wallet')}
38: 
39: 
40: class InstructionEvidenceError(ValueError):
41:     def __init__(self, reason, paths):
```


## `scanner/instruction_scope.py` — lines 85–121

```text
85:             return {'program': program, 'references': references, 'paths': program_paths + [path + '.parsed'],
86:                     'non_economic': True, 'shape': 'parsed-memo'}
87:         info = parsed.get('info') if isinstance(parsed, dict) else None
88:         kind = parsed.get('type') if isinstance(parsed, dict) else None
89:         if (program not in TOKEN_IDS | {SYSTEM_ID, ASSOCIATED_ID} or not isinstance(info, dict) or not info
90:             or not isinstance(kind, str) or not kind):
91:             reject('Parsed instruction lacks a supported program/type/info representation', 'parsed', 'programId')
92:         contract = (_TOKEN_REFERENCES if program in TOKEN_IDS else
93:                     _SYSTEM_REFERENCES if program == SYSTEM_ID else _ASSOCIATED_REFERENCES).get(kind)
94:         if program in TOKEN_IDS and kind == 'setAuthority':
95:             authority = info.get('authorityType')
96:             target = _AUTHORITY_TARGETS.get(authority) if isinstance(authority, str) else None
97:             if target is None:
98:                 reject('Token authority type has no supported target contract', 'parsed.info.authorityType')
99:             competing_target = 'account' if target == 'mint' else 'mint'
100:             if competing_target in info:
101:                 reject('Token authority target fields contradict the supported authority type',
102:                        'parsed.info.authorityType', 'parsed.info.' + target, 'parsed.info.' + competing_target)
103:             contract = (target,)
104:         if program in TOKEN_IDS and kind in ('approve', 'approveChecked', 'revoke') and 'account' in info:
105:             reject('Token permission target must use the RPC source field', 'parsed.info.source', 'parsed.info.account')
106:         if contract is None:
107:             reject('Parsed operation has no supported account-reference contract', 'parsed.type', 'parsed.info')
108:         for field in contract:
109:             if not isinstance(info.get(field), str) or not info[field]:
110:                 reject('Parsed operation lacks a valid required account reference', 'parsed.info.' + field)
111:         pending = [(path + '.parsed.info.' + key, value) for key, value in info.items()]
112:         while pending:
113:             field, value = pending.pop()
114:             if isinstance(value, str) and value:
115:                 references.add(value)
116:                 reference_paths.append(field)
117:             elif isinstance(value, dict):
118:                 pending.extend((field + '.' + key, item) for key, item in value.items())
119:             elif isinstance(value, list):
120:                 pending.extend((field + '.' + str(index), item) for index, item in enumerate(value))
121:         shape = 'parsed'
```


## `scanner/history_evidence.py` — lines 640–685

```text
640:         if missing:
641:             reasons.append("Required interval transaction receipts or chronology are missing: " + ", ".join(sorted(missing)))
642:         reasons = list(dict.fromkeys(reasons))
643:         state = "PASS" if not reasons else "UNKNOWN"
644:         paging_intervals[name] = _check(state, "; ".join(reasons) if reasons else "Archived requests, cursor chains, terminal pages, interval records and order verify the enumerated account scope.", used,
645:                                        required_transactions=len(required), missing_signatures=sorted(missing), scope="enumerated-accounts")
646:         interval_results[name] = {"start": _iso(lower), "end": _iso(upper), "status": "partial" if used else "unknown",
647:                                   "enumerated_scope_status": "complete" if state == "PASS" else "partial",
648:                                   "reason": "Global historical account ownership and economic completeness remain unproven; enumerated paging alone cannot certify wallet metrics.", "evidence": sorted(used)}
649:     requirements = {
650:         "history": ["global_historical_account_ownership", "report_period_records", "independent_four_week_records", "verification_interval_records"],
651:         "basis": ["opening_inventory_provenance", "earlier_acquisition_costs_for_disposed_units", "incoming_movement_acquisition_provenance"],
652:         "positions": ["historical_owned_balance_boundaries", "strict_zero_episode_reconstruction", "supported_economic_routes", "chronology"],
653:         "fees": ["all_wallet_paid_costs", "individual_native_movement_roles", "supported_fee_to_trade_allocations"],
654:         "classification": ["historical_asset_classification_with_primary_evidence"],
655:         "valuation": ["exact_report_boundary_inventory", "historical_boundary_marks", "valued_external_flows"],
656:         "identity": ["wallet_signer_and_system_owned_identity", "historical_token_account_ownership"],
657:         "findings": ["review_of_unsupported_routes_and_unexplained_movements", "primary_evidence_for_risk_decisions"],
658:     }
659:     decisions = {name: _check("UNKNOWN", "Current archived source types do not establish all required wallet-level evidence.", (), requirements=needed) for name, needed in requirements.items()}
660:     metric_needs = {
661:         "profit_sol": ["history", "basis", "fees", "classification"],
662:         "realised_roi_pct": ["history", "basis", "fees", "classification"],
663:         "median_roi_pct": ["history", "basis", "positions", "fees", "classification"],
664:         "win_rate_pct": ["history", "basis", "positions", "fees", "classification"],
665:         "median_hold_hours": ["history", "positions", "classification"],
666:         "completed_positions": ["history", "positions", "classification"],
667:         "completed_positions_90d": ["history", "positions", "classification"],
668:         "traded_mints": ["history", "classification"],
669:         "rapid_sale_pct": ["history", "positions", "classification"],
670:         "avg_buys": ["history", "positions", "classification"],
671:         "avg_sells": ["history", "positions", "classification"],
672:         "positive_weeks": ["history", "basis", "fees", "classification"],
673:         "largest_contribution_pct": ["history", "basis", "fees", "classification"],
674:         "economic_pnl_sol": ["history", "valuation"],
675:     }
676:     for metric, gates in metric_needs.items():
677:         name = "four_weeks" if metric == "positive_weeks" else "verification_90d" if metric == "completed_positions_90d" else "report_period"
678:         history_requirement = {"report_period": "report_period_records", "four_weeks": "independent_four_week_records",
679:                                "verification_90d": "verification_interval_records"}[name]
680:         needed = ["global_historical_account_ownership", history_requirement]
681:         needed += [item for gate in gates if gate != "history" for item in requirements[gate]]
682:         decisions[metric] = _check("UNKNOWN", "Required wallet evidence is unresolved; observed record arithmetic cannot substitute for the metric's supported population.", paging_intervals[name]["evidence"],
683:                                   interval=name, requirements=list(dict.fromkeys(needed)),
684:                                   enumerated_paging_state=paging_intervals[name]["state"])
685:     native_values = {signature: _native_amounts(raw, address) for signature, raw in valid_raw.items()}
```


## `scanner/history_evidence.py` — lines 750–770

```text
750:     # Do not leak bulky native page entries into the durable certificate.
751:     for account in account_results:
752:         account.pop("entries")
753:         account.pop("errors")
754:     return {"version": VERSION, "window": {"start": _iso(start), "end": _iso(end)},
755:             "verification_days": verification_days, "intervals": interval_results,
756:             "account_scope": {"kind": "enumerated-accounts", "included_account_count": len(inspected_accounts),
757:                               "omitted_account_count": omitted if _integer(omitted) else None,
758:                               "global_historical_ownership": "UNKNOWN", "wallet_history_complete": False},
759:             "paging": {"state": "PASS" if all(check["state"] == "PASS" for check in paging_intervals.values()) else "UNKNOWN",
760:                        "intervals": paging_intervals, "wallet_address_intervals": wallet_checks, "accounts": account_results,
761:                        "conflicts": conflicts, "chronology": chronology},
762:             "source_consistency": source_consistency,
763:             "source_set": source_consistency["source_set"],
764:             "record_provenance": {"trust_boundary": "local-native-collector receipts; no independent mainnet authentication",
765:                                   "state": "PASS" if receipts and all(receipt["state"] == "PASS" for receipt in receipts) else "UNKNOWN",
766:                                   "records": receipts, "counts": {"inspected": len(receipts), "local_native_receipts": sum(receipt["state"] == "PASS" for receipt in receipts),
767:                                                                       "unresolved": sum(receipt["state"] != "PASS" for receipt in receipts)}},
768:             "metric_decisions": decisions, "evidence_gates": {name: decisions[name]["state"] for name in requirements},
769:             "native_address_metrics": {"observed": native_observed, "periods": native_period,
770:                                        "notes": ["Native-address totals do not require global historical token ownership.", "Native wallet delta is the sum of selected transaction endpoint changes, including swaps, rent, transfers and fees; rewards and other nontransaction changes are outside this total, and it is not wallet profit.", "Exact network fee payment does not establish economic fee allocation."]},
```


## `pyproject.toml` — lines 1–32

```text
1: [build-system]
2: requires = ["setuptools==84.0.0"]
3: build-backend = "setuptools.build_meta"
4: 
5: [project]
6: name = "solana-wallet-scanner"
7: version = "0.3.11"
8: description = "A read-only, local Solana wallet research scanner"
9: requires-python = ">=3.11"
10: dependencies = [
11:   "fastapi==0.142.2",
12:   "starlette==1.7.0",
13:   "httpx==0.28.1",
14:   "uvicorn==0.34.2",
15:   "keyring==25.6.0",
16: ]
17: 
18: [project.optional-dependencies]
19: dev = ["pytest==9.1.1"]
20: 
21: [project.scripts]
22: solana-wallet-scanner = "scanner.__main__:main"
23: 
24: [tool.setuptools]
25: packages = ["scanner"]
26: 
27: [tool.setuptools.package-data]
28: scanner = ["examples/*.json"]
29: 
30: [tool.pytest.ini_options]
31: testpaths = ["tests"]
32: pythonpath = ["."]
```


## `frontend/package.json` — lines 1–28

```text
1: {
2:   "name": "solana-wallet-scanner-ui",
3:   "private": true,
4:   "version": "0.3.11",
5:   "type": "module",
6:   "engines": {
7:     "node": ">=22.12.0"
8:   },
9:   "scripts": {
10:     "dev": "vite --host 127.0.0.1",
11:     "build": "tsc -b && vite build",
12:     "preview": "vite preview --host 127.0.0.1",
13:     "check:format": "node scripts/check-format.mjs",
14:     "check:discovery": "node scripts/check-discovery.mjs"
15:   },
16:   "dependencies": {
17:     "lucide-react": "0.468.0",
18:     "react": "18.3.1",
19:     "react-dom": "18.3.1"
20:   },
21:   "devDependencies": {
22:     "@types/react": "18.3.18",
23:     "@types/react-dom": "18.3.5",
24:     "@vitejs/plugin-react": "6.1.1",
25:     "typescript": "5.7.3",
26:     "vite": "8.3.2"
27:   }
28: }
```
