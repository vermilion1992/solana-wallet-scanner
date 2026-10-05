# Codex assignment: mass discovery and progressively stronger shortlists

## 1. Mission and priorities
The user needs a scanner, not a trading bot. They ultimately use only a phone, but have explicitly prioritised proving the search and analytics before packaging. Implement a mobile-readable workflow in the existing app; APK, PWA deployment, public hosting, custody and execution are out of this milestone.

The product question is: **Which active traders merit observation after accounting for evidence quality, realised losses, open exposure, material exit speed and the follower's actual conditions?** Leaderboard P&L is an input, not the final answer.

Priorities, in order:
1. A genuine vertical slice with inspectable buys/sells and supported monetary/timing results.
2. Broad, economical acquisition and persistent successive shortlists.
3. Reproducible KPI calculations, observable following incompatibilities and rejection explanations.
4. Measured speed/cost, checkpointed operation and offline refiltering.
5. Prospective, quote-only comparison against a basic reported-profit ranking.

Do not begin by rewriting the accounting engine, adding several speculative providers, polishing a landing page or producing a new architecture document. Use this specification and write code. Update a decision record only where reality requires a change.

## 2. Existing reference and scope
Reference inspected for this package: private repository `vermilion1992/solana-wallet-scanner`; PR #1, branch `codex/screening-forward-research`; head `fa9f1307b2ee6b8e4d4288b5ee55b0d220404f69`. PR #1 was open and unmerged when inspected. This is a reference, not an instruction to discard later commits. See `docs/01_REPO_BASELINE.md` for existing modules and claims.

Read the current root and applicable scoped AGENTS instructions, existing CODEX_TASK, ACCEPTANCE, issue register and contracts. Inspect the working tree, branch ancestry and current CI. Create a reversible branch such as `codex/mass-wallet-funnel-v1` from the appropriate current implementation base. Never force-reset, force-push, merge another PR or replace old evidence to fit this package.

The newer user request authorises a mass-search implementation direction. It does **not** authorise payment, larger provider quotas, public deployment, real trading, blanket qualification or deletion of the earlier historical contract.

## 3. Success criteria
Deliver these independently named outcomes:
- `MASS_SEARCH_SOFTWARE`: functional staged pipeline, safety and regression gates.
- `REAL_SEARCH_BENCHMARK`: genuine acquisition and accounting of at least 1,000 unique candidates from the declared accessible universe, with conserved stage decisions and measured costs.
- `REAL_ANALYTICS_DEMONSTRATED`: at least three genuine, independently reconciled wallet reports with populated trade history, supported realised subset P&L and median observed completed hold. Minimum analytic population and evidence obligations are in the benchmark protocol.
- `FORWARD_OPERATION_DEMONSTRATED`: genuine eligible signals, delayed quotes and a complete hypothetical entry/exit path, with gaps and costs retained. Connection success alone fails this outcome.
- `RESEARCH_OUTCOME`: separate observed comparison, possibly inconclusive or negative. Three strong positive candidates are a target, never an output quota.

The legacy full-wallet PRODUCT_READY flag remains governed by its own existing acceptance, not by these flags. Do not relabel a narrower gate as full historical completion.

A missing source can leave the real benchmark blocked while software passes. A correctly measured loss can pass the analytics demonstration while failing the profitability filters. A functioning observer can pass operational acceptance without demonstrating profitable following. Return all statuses.

## 4. Design constraints
Use one primary indexed discovery adapter selected by a measured capability gate. Keep the current public sampler and address import as labelled fallbacks. Do not claim that either fallback proves mass profitable-wallet discovery when it does not.

Preserve the exact named Strict research preset. Create a separate `Mass research v1` plan for preliminary ranking; distinguish a queue priority from a KPI PASS. Never compare incompatible currency, period, population or cost-basis definitions as if they were equivalent.

All stages use `PROMOTED`, `REJECTED`, `DEFERRED` or `PENDING`. Unknown is not zero, a fail, or a pass. Budget exhaustion is a defer reason. Explicit failed criteria may reject; exploratory sampling may inspect rejects without rewriting the original decision.

Use deterministic stage rules first. Do not add an LLM to classify wallet profitability, infer intent, choose thresholds or silently decide exclusions. An optional later natural-language explanation can only render recorded evidence.

Preserve useful supported results. Unavailable opening inventory must not erase an independently supported transaction fee. Unavailable USD conversion must not erase a supported SOL result. Full-wallet uncertainty must not hide appropriately labelled subset analytics.

## 5. Live access and spending
Offline mode is the default in this package. Read public reference documentation separately from provider collection. Do not enumerate credentials as part of offline acceptance.

For live collection, reuse only already authorised access within the actual remaining quota. Otherwise present one consolidated approval request identifying provider, operation, purpose, call/credit ceiling and expected duration. No key values in chat, logs, screenshots or artifacts. Do not purchase plans, enable overages, change billing cycles or replenish exhausted allowances.

`config/live_authorization.example.json` is disabled deliberately. It is not a real permission grant. A verified API key's existence is not authority to consume an unknown budget. Stop only the affected live lane if permission, entitlement or source capability is missing. Continue implementation, fixtures, replay, tests and local performance checks.

Do not bypass authentication, provider rate limits or access controls; scrape protected GMGN pages; rotate identities to evade caps; install remote agent skills; configure signing keys; or call transaction-submission endpoints. Read-only quote requests are permitted only under the live authorisation contract.

## 6. First implementation slice
After a bounded baseline inspection, implement the smallest complete path using an existing authorised adapter or the chosen indexed source:

`one source page -> validated/deduplicated universe -> preliminary decision -> one targeted history job -> existing report derivation -> real trades, P&L/timing where supported -> persisted mobile-readable result -> export/reopen`.

The first real specimen needs an actual supported purchase and sale, not just a transfer, sample balance or subscription acknowledgement. Archive the source responses and independently work the expected arithmetic. When collection is blocked, finish this exact slice using explicitly synthetic transport fixtures and keep the genuine acceptance status blocked; do not call it the live demonstration.

Then scale the same path. Do not implement a special benchmark-only engine that bypasses the application's normal API, budget, storage or report path.

## 7. Execution and validation
Follow the work items in `docs/05_IMPLEMENTATION_PLAN.md`. Each item specifies output and proof. Keep one issue register and one candidate branch. Run affected tests while changing code and complete applicable gates on a frozen candidate. Integrate new tests into the current `tools/validate.py` structure rather than creating a competing acceptance system.

Record source and lock hashes, test commands, return codes, external request counts, old-report invariance and actual backend/browser outcomes. Preserve failed baseline receipts. Distinguish code defects from inaccessible providers and insufficient market observations.

`tools/check_receipt_contract.py` in this package checks a report's declared structure, counts, budget invariants and local artifact hashes. It is a useful guard, **not** an independent verifier of genuine data, profit or all application invariants. Port/extend it into the application only after reviewing its tests, and keep actual reconciliation/browser/source-provenance gates.

## 8. Autonomy and stop rules
Proceed with reversible code/test changes. Do not ask the user to choose class names, UI labels, queue internals or ordinary implementation details. Prefer the smallest useful extension to current modules. Seek approval only for an unresolved external permission, paid capability, destructive migration, changed research objective or new deployment.

Do not repeatedly stop after planning or after one green unit test. Conversely, do not run live loops until three winners happen to appear. Obey the frozen universe, approved caps and observation horizon. Preserve unsuccessful and inconclusive results.

At each completed work block report: implemented files, actual validation, genuine-data status, measured results, blockers and next item. The final handoff must follow `docs/08_DELIVERY_TEMPLATE.md`; no unsupported 'complete', 'safe to copy', 'verified profitable' or 'ready on your phone' claims.
