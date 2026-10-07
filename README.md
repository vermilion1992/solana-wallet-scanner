# Solana Wallet Scanner · local v0.3.11

A local, read-only research application built from the supplied v0.3 blueprint. It runs a React interface and Python API on `127.0.0.1`, stores reports and compressed evidence locally, and never connects a signing wallet or submits transactions.

Start with **Discovery**: find or paste public wallet addresses, check native identity, and investigate a small sample. In **Research**, inspect and save a separate screening assessment, shortlist a wallet, and observe a defined hypothetical following strategy using quotes requested after detection, decoding and your selected reaction delay. Saved reports and observation runs retain their settings, evidence, costs, open exposure, exclusions and monitoring gaps. Keyless public access is available for this sampled workflow; provider refusals and exhausted budgets stay visible.

The release also includes saved candidate cohorts and offline public-address import, manual scans, a clearly labeled offline demonstration, FIFO accounting, editable research filters, optional watchlist monitoring, current token metadata enrichment, report exports, quota reservations, and verified backups. Broad market coverage, automatic meme-token classification, complete historical ownership, and reconciled whole-wallet equity are not established. Strict historical meme-policy `MATCH` remains unavailable for incomplete live evidence.

This revision responds to the v0.3.10 independent review. R15 corrects the RPC target contracts: approvals/revocation use `source`; standard authority changes use `mint` or `account` according to `authorityType`. Unsupported or contradictory types/targets remain unresolved. The R14 parsed/opaque representation guards remain in force. Primary-parser schema fixtures check supported inclusion, disjointness and actual report rebuilding independently of the application table. The affected position method advances to `account-position-evidence-v9`; history stays `history-evidence-v8`, source consistency v4 and chronology v2. Frozen parents and references remain unchanged; rebuilding creates a child. Details are recorded in [the review response](docs/CODE_REVIEW_RESPONSE.md) and [validation](docs/VALIDATION.md). Full real-wallet accounting remains **OPEN** in implementation and independent historical ownership/basis/valuation data, with no verified copy-trading candidate.

## Start locally

Install **Python 3.11+**. The repository includes compiled interface assets, so Node.js is optional when using this checkout. Check out the private branch or extract its source bundle into a regular local folder, open a terminal there, and run:

**macOS / Linux**

```sh
./setup.sh --skip-frontend
./run.sh
```

**Windows PowerShell**

```powershell
.\setup.ps1 -SkipFrontend
.\run.ps1
```

If Windows blocks local PowerShell scripts, use a process-scoped policy for this terminal, then rerun the commands:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Setup downloads the complete hash-locked Python dependency set into `.venv`, installs the local source without fetching an unlocked build environment, and checks dependency compatibility. Internet access is needed for setup. This is a source distribution, not a native installer. To rebuild the interface after editing it, install **Node.js 22.12+** with npm and run `./setup.sh` or `.\setup.ps1` without the skip option; this also runs `npm ci` and `npm run build` in `frontend`.

The launcher opens your browser after the API is ready and prints a session URL. Treat that URL as a local login link. Each process gets a fresh random token in the URL fragment; the frontend exchanges it for a session cookie and a CSRF token. Press **Ctrl+C** in the terminal to stop the app. An ordinary bookmark without the session fragment will need the fresh URL printed by the launcher.

For an alternate port or an explicit data directory:

```sh
./run.sh --port 8766 --data-dir ./local-data --no-browser
```

Windows accepts the same flags after `.\run.ps1`. Default bind is `127.0.0.1`. The launcher reserves its listening port before startup and reports a useful error if another application occupies it. An OS file lock permits only one running scanner process per data directory, including when different ports are used; the lock releases when the process stops. Do not expose the server through a reverse proxy or publish it to a public host.

To open the built app on a phone on the same Wi-Fi, start it once on your computer:

```sh
./run.sh --lan --no-browser
```

Scan the printed QR (or open the printed token URL) on the phone. Token auth stays mandatory; an unauthenticated API call returns 401. The token is not saved in the repo. Away from that LAN there is no permitted remote preview — do not add a tunnel or public host.

## Use the scanner

1. Open **Discovery** and choose **Find wallet candidates**, or paste addresses with **Import a public candidate list**. Public discovery samples up to three current trending pools and retains at most 20 leads. Recent buying and selling sets investigation priority; importing an address establishes no trust.
2. Select a small set and choose **Check native identity**. The bounded public RPC check examines transaction signers, owned token movement and the current system account. A Helius key is optional for this sampled route. Identity failures, unavailable sources and provider refusals retain their reasons.
3. Choose **Investigate** for eligible native-checked candidates. Initial keyless samples collect at most 20 transactions within 50 conservative request attempts per wallet, including current mint-risk queries, under the shared public daily cap. A configured Helius source retains its existing setup-pilot or confirmed free-plan limits. Reaching a cap preserves the sample and checkpoint. **Continue investigation** adds only the selected wallet's explicit saved budget.
4. Open **Research**, select a saved report, adjust the screening preset if useful, and save the assessment. Inspect supported trades, conditional matched lots, unmatched sales, open exposure, early exits, token controls and collection stop reasons. **Worth observing** is separate from strict financial qualification and verified wallet profit.
5. Shortlist a wallet and start **quote-based paper observation**. Choose simulated capital, fixed entry size, reaction delay, costs and limits. Inspect dated quote outcomes, open losses, unavailable exits and gaps; stop or resume the run, reopen it and export JSON. Each run keeps its original settings. The application must remain running to observe future signals; missed periods are never replayed as followed activity.

Import saves a dated list without provider calls. Up to 1,000 input identifiers are validated, duplicates are removed and at most the configured 20 unique leads are retained; omissions stay counted. Imported addresses enter the common investigation route after their own native identity sources pass. The saved candidate view preserves dated memberships and evidence. **Candidate observed**, **identity checked**, **sample audited** and **history reconstructed** remain separate stages. Job completion, import or a sampled signer check never establishes complete history.

For larger manual scans, confirm your actual free plan and current provider billing-cycle dates in Settings, then run an address-specific capability test. Do not invent cycle dates to unlock a larger budget; the cycle end date is exclusive. This enables the monthly application limits and manual-address workflow.

Watchlist monitoring is off by default (`refresh_minutes=0`) and requires the confirmed monthly configuration and address-specific capability check. An interval of 15–1440 minutes rotates through at most five saved live addresses while the app is running, skips demo addresses and active or paused jobs, and respects the free quota threshold. It stops when the local process exits.

Optional GeckoTerminal enrichment fetches present-day metadata for at most five current mints on demand. It uses a 15-minute cache, a limit of eight calls per minute, and a 200-request daily cap. Current metadata never substitutes for a historical price or changes historical accounting metrics.

The report's **conditional observed-lot profit** models in-window sales fully matched to fetched purchase lots, less recorded wallet-paid fees, assuming no undiscovered earlier inventory or intervening flows. It excludes unmatched sales and is separate from verified wallet profit and strict meme-policy metrics. Conditional holding and exit times describe those observed lots. `observed_profit_sol` stays unknown without the required independent inventory evidence. These observations never create a strict policy match or a claim of safe copying.

Current mint checks can flag active mint/freeze authorities and certain Token-2022 controls. Revoked authorities describe the current observation only. Complete owner concentration, creator links, historical sellability, execution/slippage, and future safety remain unresolved unless supported by separate evidence. The adapter path is conservative and has synthetic coverage; see the validation record for exactly which real fixtures have been accepted or rejected.

Current swap reconstruction uses `spot-v4-durable-nonce`. It accepts a narrowly evidenced first System `advanceNonce` instruction as account administration only when identity, signer/account roles, unchanged nonce balance and exact native fee conservation pass. An archived real PumpSwap sale now reconstructs 5,218,627,960 raw units sold for 0.01134506 SOL with a 0.000042 SOL wallet-paid fee. It begins and ends with nonzero inventory of unknown acquisition cost; this is a transaction observation, not verified profit or a completed wallet position.

**Financial qualification** requires a saved live `MATCH`, verified evidence, the current `fifo-v3` accounting method, `history-evidence-v8` receipt method and `account-position-evidence-v8` position method, a known strict profit value, and every required named financial/evidence check explicitly `PASS`. Synthetic demonstrations, previews, conditional profit, missing checks, and partial or stale evidence do not qualify. Older or missing accounting, history or position assessments need a rebuild before they qualify under the current methods. Qualification refers to the saved preset and reporting window; the interface compares it with the active preset before presenting it as a current match. Use the unchanged Strict research preset for the PDF page 9 starting rules. Explicitly edited filters remain labeled as the current custom filters. The previously sampled live wallets remain unresolved, with **zero financially qualified wallets**.

**Copy-behavior review** is separate from financial qualification. It compares final episode holding time with the time to sell 90% of observed acquired units, flags cases where 90% sold within five minutes but the final exit met the minimum hold, and shows the observed share of rapid first sales. Timings from incomplete history remain conditional and never change strict policy metrics. Unmatched basis, incoming transfers, and current token permissions remain visible. Missing token observations remain explicit unknown checks without accusation. Follower exploitation, creator links, liquidity withdrawal, and holder concentration stay `UNKNOWN` without reviewed primary evidence. The app does not infer intent, label a wallet as bait, or produce a legitimacy/safety score.

Qualification and copy-review annotations are computed from cached reports with **no provider calls**. This revision does not replenish or spend the original setup allowance: its recorded native ledger remains 200 used of 200, and it has produced no verified profitable-wallet match.

`MATCH` means every enabled threshold and evidence gate passed. `MISS` records at least one known failed threshold; other checks may still be unknown. `UNRESOLVED` means no threshold conclusively failed but a required metric or gate remains unknown. Missing evidence is never replaced by a zero. These labels describe research-filter results, not recommendations to trade.

The strict preset preserves the PDF page 9 starting thresholds: a 30-day report window and 90-day verification window; net realised meme-trading profit ≥5 SOL after identifiable costs; realised ROI ≥10%; median completed-position ROI ≥5%; completed-position win rate 50–85%; median strict completed hold 1–72 hours; at least 50 completed positions in 30 days and 100 in 90 days; 20–100 qualifying meme mints excluding settlement assets and spam; first-sale-within-five-minutes share ≤10%; average buys 1–2 and sells 1–3 per completed position; at least three of four seven-day periods positive; largest mint contribution ≤25% of net realised period profit; and positive reconciled economic P&L. Older purchase history is needed when the 90-day lookback cannot establish basis. Monetary values use decimal strings, native quantities use integer strings, and FIFO basis is explicit. Review each metric's population and evidence reason. See [the page-by-page alignment](docs/BLUEPRINT_ALIGNMENT.md).

New accounting reports use **`fifo-v3`**, which corrects four-week consistency to use its own exact `[report end − 28 days, report end)` interval regardless of the selected report length. Report-period, four-week and 90-day interval coverage and individual metric coverage remain separate; missing independent history produces an unknown four-week result rather than fictitious zero-profit weeks. A complete normalized-input declaration is a caller assertion, not proof of real provider coverage. The live app continues to keep missing historical evidence partial. The previous fee-allocation correction remains in effect: wallet-paid buy fees enter acquisition basis, including buys before the reporting window whose cost is realised later; eligible sell fees are deducted once from proceeds. Plain, unambiguous supported swaps allocate the retained fee event once, while ambiguous outside movements and unsupported routes retain unallocated costs and uncertainty. The conditional research definition is versioned separately. Existing `fifo-v1` and `fifo-v2` report snapshots retain their original values and provenance. A methodology change requires a new accounting rebuild from source evidence; cached threshold previews and copy-review annotations do not upgrade old financial figures. This distinction follows PDF pages 3, 7 and 14.

## Rebuild a saved live report offline

Open a saved live report and choose **Rebuild from saved records**. It can be rebuilt from its archived native records under the current interpretation without collecting data again. The rebuild saves a **new report**, links it to the earlier one, retains that report's window and preset, and preserves its current-mint observations with their original dates. The earlier financial snapshot stays unchanged. Cached filter previews remain separate.

New reports freeze their transaction hash links, observed collection checkpoint/snapshot and coverage in an immutable input manifest. Earlier reports may have saved transaction links but no original frozen checkpoint; a later matching checkpoint is explicitly marked as a legacy limitation and cannot prove the earlier report's completeness. Missing selected primary records, inconsistent transaction identity, invalid or conflicting archived order, missing original job context or insufficient disk space prevent rebuilding. Inspectable linked time, placement and semantic-source contradictions remain in the new child with dependent results unknown; they are not silently removed.

Saved live reports show **separate history and position assessments**, each labeled current, **requires rebuild**, or **missing**. A current history method cannot endorse an older account hold. Current labels still require inspecting the individual evidence states. Reading a report or exporting it adds assessment/qualification annotations without rewriting its original coverage, financial values, window or preset. Old or missing methods cannot qualify simply because their historical snapshot contains a passing check.

Collection receipts check the archived native requests, pagination, record identity and chronology for the known account scope. Evaluated account-chain pages are reconciled with canonical receipt metadata; every admitted linked page also contributes execution/chronology facts to dependent source decisions. Contradictory wallet or token-account pages remain explicit conflicts. Shared per-slot chronology reconciles linked transaction/page times, block signature order, optional block time and checkpoint indices. Conflicting observations remain unknown; identical repeated receipts remain valid, and an absent optional block time alone does not invalidate supported timing. An unrelated detached page cannot establish a time boundary. Separately labeled observed-record metrics can show exact wallet-paid network fees and native transaction endpoint deltas even when interval coverage is unknown. Interval totals require their own completed wallet-address paging evidence at both boundaries; those deltas exclude rewards/other nontransaction changes and never mean profit. Passing those checks does not establish every historical owned account, opening inventory, acquisition cost, meme classification or boundary equity. Empty pages are never a zero-basis certificate. Rebuilding makes corrected interpretations reproducible; it does not obtain missing evidence or create verified wallet profit. **R1 remains open.**

The separate **Account-scoped position evidence** panel can establish strict-zero timing for a named token account under `account-position-evidence-v8`. It requires a primary zero balance before a supported acquisition, continuous event-time ownership and quantities through every required archived receipt, canonical chronology, explicit placement evidence, and a supported final sale returning that account to exactly zero. Required records are evaluated in reconciled slot/transaction order before report-window selection: a contradictory or missing record between opening and closing cannot disappear because its timestamp falls at or beyond the report end. Conflicting possible slot placements cannot prove exclusion merely because the raw record's preferred slot falls before opening or after closing. Every episode the disputed account record may intersect retains that dependency until placement or exclusion is supported. Malformed raw placement or an unavailable distinct alternative archive leaves placement unbounded. A solely missing raw record can still be excluded when consistent linked pages prove its placement outside the episode; those pages cannot authenticate its quantities. Exclusions retain their source evidence, and exceeding the 64 uncertain-exclusion inspection limit leaves timing unknown. Holding time is independent of price-based ROI; basis, economic fees, classification and valuation remain separate unknowns. Its closed-account count and median describe only that evidenced subset and never fill the wallet-wide strict holding or financial metrics. Missing or removed sources revoke dependent timing when it is re-derived. Recovery actions are evidence plans, not automatic provider requests. The cached real inventories begin nonzero and interval coverage remains partial; recognizing a further swap cannot supply the missing acquisition history or establish a verified wallet.

A matching token transfer delta cannot resolve conflicting absolute pre/post inventory. Linked raw versions are compared by normalized account identity and exact raw units, with owner, mint, decimals, token program and execution facts considered where the result depends on them. Missing facts remain distinct from explicit contradictions. Native fee/payer and wallet endpoint facts also require agreement across linked archives for their own metrics; token-only disputes do not erase agreeing native observations. Reordered balance arrays, optional log changes and identical repeated receipts do not create conflicts when the required facts agree. The original R10 cases are synthetic local source contradictions, not evidence of provider-generated mainnet records or a wallet-qualification bypass.

A source-consistency PASS requires completeness of the relevant linked source set, not merely agreement among the inspected prefix. Repeated identical references can be normalized before expensive archive inspection without deleting the original frozen links. A complete link index supports episode-specific decisions; an unsupported budget or incomplete index leaves omission relevance unproven and dependent holds unknown. Native observed/interval totals retain the existing raw-reference cap behavior: more than 40,000 references leaves those totals unknown even if inspected native facts agree. Stored current-mint and frozen-wrapper report metadata retains its citations after explicit validation; unknown collector roles remain gaps. The inspection fields, exclusion receipts and supported budgets are described in [CONTRACT.md](docs/CONTRACT.md).

The PDF page 6 explicitly warns that current token accounts and repeated account paging cannot certify all former historical ownership: a hidden closed-account round trip can leave no residual mismatch. Complete wallet analysis needs independent historical ownership evidence and a financial pipeline that consumes it with recovered costs, quantities, classifications and any required boundary valuations. The current 94 selected native receipts and short sample windows do not satisfy the 30/90-day policy. Confirming the provider plan and billing cycle can enable further budgeted collection, but cannot supply that missing evidence contract by itself. No new full-wallet completion branch is implemented in this release; PDF page 18 requires a new source decision if the native provider cannot supply the required evidence.

## Advanced manual raw-record audits

From **Discovery**, open **Advanced manual scan → Review saved transaction records**. Choose **Audit reviewed example** to check the included public mainnet record, or **Choose record bundle** to import your own saved raw JSON. The result and its JSON export stay separate from wallet reports. This works offline after installation and uses no provider credits.

The local API also accepts these explicitly listed records. After authenticating through the private launch URL, `GET /api/evidence/example` downloads the packaged public example from `scanner/examples/real-transaction-audit-mainnet.json`. Submit the JSON object to `POST /api/evidence/audit` with the session cookie and `X-CSRF-Token`; read or export its separate saved result through `GET /api/evidence/audits/{audit_id}` and `/export`. The exact bundle/API schema is in [CONTRACT.md](docs/CONTRACT.md).

The bundle limit is 20 transactions and 4 MiB. `scoped-evidence-audit-v2` checks individual material native movements and the actual validated fee-to-trade link. Offsetting unknown inflows/outflows can reconcile their net balance while fee allocation stays unknown; a zero net delta does not establish complete costs. Its certificate checks the listed record/account boundary, exact quantities, consideration, network fees and native balance paths. A content hash alone does not verify chain provenance; the recognized real mainnet example is one independently reviewed PumpSwap buy with pre-existing inventory of unknown basis. **Scoped reconstruction is not wallet profit**: missing historical ownership, opening costs, token classification, strict closed positions and boundary equity remain unknown. The audit keeps history incomplete and financial qualification unresolved, and cannot upgrade a live report to `MATCH`. Full R1 acceptance remains open.

## Free-only controls and provider readiness

When billing dates are unknown, the setup pilot permits at most **200 native credits over the lifetime of the local data directory**, including native candidate checks and investigations. It persists across restarts and key changes. It does not reset each day or claim that the provider has allocated a fresh allowance. Collection starts at 20 transactions and 30 native credits per wallet; explicit resumes can add another bounded tranche while the shared cap permits it. Each collection includes at most 200 account identities in setup mode and 1,000 in monthly mode; additional accounts remain outside the fetched scope and are reported as a coverage limitation.

Discovery and current enrichment share a public-provider limit of 200 requests per day, eight calls per minute, and a 15-minute observation cache. The public sample is bounded and misses other pools, older trades, and transactions beyond the returned sample.

With operator-confirmed free-plan entitlement and actual cycle dates, application limits start at 800,000 credits per explicit provider cycle, a 600,000-credit discovery pause threshold, 20 candidates, 5 deep audits, 10,000 transactions and 20,000 collection credits per wallet, and a 2 GiB free-disk threshold. Free-mode workload caps can be lowered; they cannot be raised above these ceilings. Outstanding reservations count against the cap, and dispatched requests are charged conservatively even after timeouts.

Fresh Linux setup, isolated launcher and current dependency advisory checks for v0.3.2 are recorded in [the delivery record](docs/capability/delivery_review_2026-10-02.json). Windows/macOS and Python 3.11 runtime execution remain untested; zero known advisories is not comprehensive security certification.

The local tariff manifest and capability test do not prove your provider's plan entitlement, dashboard usage, or future pricing. Confirm those in your provider account. Requests made by other software or other copies of this app are outside this local ledger. Automated tests use controlled responses; bounded live probes and real fixture outcomes are listed in [the validation record](docs/VALIDATION.md). Their success establishes only the recorded scope. The distributed app contains no provider key or live runtime database.

Provider credentials stay in an approved OS credential store when available. Without one they remain only in the running process; the interface reports the actual storage mode. `HELIUS_API_KEY` is also accepted from the process environment. Keys are never intentionally written into local reports, backups, frontend assets, or the application database. Enter public addresses only; the app has no seed-phrase or private-key flow.

## Local data and backups

Default storage locations are:

| Platform | Directory |
| --- | --- |
| Linux | `$XDG_DATA_HOME/solana-wallet-scanner`, or `~/.local/share/solana-wallet-scanner` |
| macOS | `~/Library/Application Support/solana-wallet-scanner` |
| Windows | `%LOCALAPPDATA%\solana-wallet-scanner` |

The directory contains `scanner.sqlite`, immutable SHA-256-addressed compressed JSON under `evidence/`, and `exports/`, `backups/`, and `logs/`. Durable checkpoints reference archived transactions and snapshots by hash; scan/state responses carry a compact checkpoint reference instead of repeating raw provider responses. Keep active data on a local disk; do not put an active SQLite data directory in a cloud-sync folder. The Settings view displays the actual directory. A backup uses SQLite's online backup API, copies evidence, and records SHA-256 checksums in `manifest.json`. OS keyring credentials are excluded. The `.runtime.lock` file may remain after shutdown; its presence is harmless because ownership is controlled by the OS lock, not by whether the file exists.

Stop the app before switching to restored data. Restore into a **new or empty** directory:

```sh
./run.sh restore /path/to/backup-folder --destination /path/to/new-restored-data
./run.sh --data-dir /path/to/new-restored-data
```

On Windows, use `.\run.ps1` with Windows paths. A ZIP containing the backup folder's contents, including `manifest.json` at the ZIP root, is also accepted. Restore checks paths, rejects symlinks and unexpected files, verifies every checksum and SQLite integrity, and commits only after verification. It refuses to overwrite existing data. Restore limits are 100,000 manifest files and 16 GiB of uncompressed file content. Keep the original data directory until you have inspected the restored reports.

## Development and validation

The unreleased stabilisation branch adds a repeatable acceptance runner. Use `.venv/bin/python tools/validate.py --profile focused` while editing and `--profile candidate` for the frozen candidate. Candidate acceptance also requires exact-source review evidence, a compatible clean locked installation, and the guarded launcher/browser checks. See [docs/STABILISATION.md](docs/STABILISATION.md) for setup, evidence paths and scope, and [docs/R1_SOURCE_DECISION.md](docs/R1_SOURCE_DECISION.md) for the remaining complete-wallet milestone.

```sh
.venv/bin/python -m pytest
.venv/bin/python -m pip check
cd frontend
npm run build
```

On Windows, use `.venv\Scripts\python.exe`. The production launcher serves `frontend/dist`; it does not run a development server. Rebuild the interface after editing frontend code. See [docs/VALIDATION.md](docs/VALIDATION.md) for actual checks and remaining limitations, and [docs/CONTRACT.md](docs/CONTRACT.md) for module/API contracts.

## Git review workflow

Use `codex/product-completion` as the active implementation branch. Review by exact commit and diff; release ZIPs are not the routine handoff. The tested application baseline is `a811e81aa2d46807d50915f47193a99f890eb854`; `b1296c1952f94ac67dcd63792eb845129cb48b1b` adds evidence and probe preparation. `evidence/product-completion/BASELINE_IDENTITY.json` binds the original 179-file source. Current source and acceptance are bound separately in the current candidate receipts. Git history is preserved.

The original PDF, non-secret 63-archive genuine partial corpus, current archive-workflow inputs and separately worked expectations are tracked for commit-based reproduction. The real sample remains partial; it cannot close B3. Runtime credentials, `.env.*`, keyring files and private databases are ignored. `tools/repository_audit.py` checks tracked files, reachable history, nested inputs and private-state ignore guards without printing credential values.

After an accessible **private** repository exists, the already-authorised publication can use:

```sh
.venv/bin/python tools/publish_private.py OWNER/REPOSITORY --push --output evidence/product-completion/PUBLISH.json
```

The publisher requires the committed active branch, both retained baseline ancestors, a passing audit, exact private repository metadata and push access; it uses no force push and verifies remote HEAD/privacy. It cannot create a repository when the GitHub app lacks creation permission. A private repository must also be granted to the ChatGPT GitHub connection for ChatGPT to inspect it; its URL alone does not grant access.

Keep the one issue register (`ISSUES.md`), acceptance matrix (`docs/ACCEPTANCE_MATRIX.json`), validation entry point (`tools/validate.py`) and source decision (`docs/R1_SOURCE_DECISION.md`). Full product readiness stays false until B1/B2/B3 close. No live Helius probe, credit spend, trading or required subscription is part of Git publication.

The current completion batch adds source-backed discovery audit planning and terminal indexed-query replay from genuine archived records. The separate bounded collection operator is documented by its explicit plans and durable request/credit receipts; it does not broaden the production provider allowlist. Existing public Solana addresses can be inspected without connecting Phantom or another wallet. Never provide a seed phrase or signing key.

Current source feasibility and supported coverage are recorded in `docs/R1_SOURCE_DECISION.md`. Genuine inputs, independently worked raw calculations, source loss/restoration and final candidate evidence are under `evidence/genuine-wallet-batch/`. Indexed query completion is distinct from exhaustive historical wallet ownership and financial qualification. PRODUCT_READY remains false while those required proofs are absent; no paid plan is required by the implemented local/offline workflow.


## Sampled screening and forward copy research

Start with `./setup.sh` and `./run.sh` (or the existing Windows launcher). Open the
private launch URL. Discovery accepts pasted public addresses as well as public
pool leads. **Check native identity**, then **Investigate** to collect a bounded
sample. Keyless public native RPC is available for this sampled route; configured
Helius retains its existing accounting and free-plan quotas. A public endpoint
can refuse or rate-limit access; the saved reason and checkpoint stay visible.

Open **Research**, screen a saved report, inspect the evidence, save the assessment
and shortlist the wallet. Screening has its own adjustable preset and labels:
insufficient evidence, excluded by this preset, or worth observing. Conditional
matched-lot results describe only the supported fetched sample. Strict financial
qualification remains separately visible and unchanged. Continue investigation
uses the saved assessment's transaction/request allowance; it does not establish
exhaustive historical ownership. Initial public samples use at most 20 transactions
and 50 conservative wallet request attempts, including mint-risk reads. Failed
attempts and restarts do not reset that allowance. Explicit continuation can add
at most the saved preset allowance, while the shared public RPC cap is 1,000/day.

Start a **quote-based paper observation** with simulated SOL capital, fixed entry,
position limit, reaction delay, adverse output adjustment, modeled execution cost,
price-impact limit and event/quote/time budgets. The named strategy enters on an
eligible observed buy only while not holding that mint, and exits on the first
eligible subsequent observed leader sale. Additional buys and excluded events are
retained. Each run freezes its settings; changing a filter cannot rewrite it.

The observer subscribes to one wallet address per Solana logs subscription,
retrieves and decodes newly detected transactions and requests Jupiter Swap V2
quotes after decoding plus the selected delay. It omits `taker` and never requests
an executable transaction. Provider/pool fees are included in quote outputs;
modeled adverse execution and the additional SOL execution cost are applied once.
Quotes are observations, not execution guarantees. The app must stay running to
monitor; stop, disconnect, restart and missing-period gaps remain explicit and are
never filled using hindsight. These subscriptions do not prove complete wallet
activity. The older 15-minute watchlist refresh is separate.

Run details retain cash, closed outcomes, open losses or unknown exposure,
unavailable exits, exact timing, captured sources and evidence-backed strategy
exclusions. Stop/resume preserves the portfolio and settings with an explicit gap.
Request a current sell quote to mark remaining exposure within the original budget.
Expired or unavailable marks cannot support a current positive portfolio conclusion.
Reopen saved runs and export JSON from Research. Exports include excluded
notifications, observer checkpoints, source references and the frozen strategy.
No honest-wallet, intent or safe-to-copy score is produced.

Software workflow acceptance, genuinely captured adapter evidence and historical
full-wallet acceptance are recorded separately in
`docs/SCREENING_FORWARD_ACCEPTANCE.json`. `PRODUCT_READY` remains false.

Run the separate checkpoint with `.venv/bin/python tools/validate.py --profile screening-forward --browser-python .venv/bin/python --output <new-directory>`. It runs affected checks, the frontend build and the actual launcher browser workflow; it does not run or claim the historical full-wallet gates. Browser verification requires the test-only Playwright package and Chromium.
