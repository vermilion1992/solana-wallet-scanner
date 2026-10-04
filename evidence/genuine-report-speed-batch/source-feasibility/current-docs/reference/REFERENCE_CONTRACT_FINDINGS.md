# Current Helius getTransactionsForAddress API reference

Unauthenticated public documentation retrieval only. No provider/RPC calls, credential/key/environment dumps, tests, source edits, or contact with humans.

Canonical page: https://www.helius.dev/docs/api-reference/rpc/http/gettransactionsforaddress

Markdown rendition: https://www.helius.dev/docs/api-reference/rpc/http/gettransactionsforaddress.md

Retrieval UTC: 2026-10-04T17:25:01.524959+00:00

Markdown SHA-256: `9dbb7415eb7389752ed7f0a0601983bd73bd0d32ff14f0d4e3b61a1e2aa6acec`

HTML SHA-256: `f78c3a18b7fedcdcb6a498b5ba2aa748c0b62026f5075fb2bceb9d71c2db2b09`

The retrieved HTML declares the page URL above as its canonical link. Both responses were HTTP 200. Raw bytes and response metadata are archived next to this file. Line citations below refer to the unmodified Markdown rendition, `gettransactionsforaddress.md`.

| Question | Exact reference wording and lines | What this establishes |
| --- | --- | --- |
| Broad history statement | L7: “getTransactionsForAddress returns complete Solana transaction history for an address in one call — time, slot, and status filters, sorting, and keyset paging.” | Broad history claim. It does not define exhaustive wallet membership or retention; L40–41 independently limits each request to at most 1,000 records. |
| Owner membership | L137–143: “Filter transactions for related token accounts. Controls whether to include transactions involving token accounts owned by the address.” Options: `none`, `balanceChanged`, `all`; default `none`. | Explicit token-account inclusion option, with ownership wording. No current-versus-event-time owner definition. |
| Account subtype | OpenAPI L210–211: “Token account support (include transactions for associated token accounts)” | Uses associated-account wording, without an explicit non-ATA coverage promise. |
| Closed/reassigned accounts and program coverage | No occurrences of closed, reassigned/reassignment, non-ATA, Token-2022, historical ownership, or owner intervals in the reference. | This reference alone does not establish closed/reassigned account discovery, temporal owner intervals, or both legacy and Token-2022 account populations. Absence is not proof of provider exclusion. |
| After-2022 cutoff / retention | No occurrence of 2022, retention, or archive in the reference. | No precise cutoff or retention floor/promise here. Attribute any separate-guide wording to that guide. |
| Status | L129–134: `filters.status`, default `any`; options `succeeded`, `failed`, `any`. | Failed transactions can be requested; selecting succeeded narrows the declared query. |
| Commitment | L29–33: default `finalized`; “The `processed` commitment is not supported.” `confirmed` and `finalized` allowed. | Explicit commitment exclusion and default. |
| Transaction formats | L48–58: encoding default `json`, options `json`, `jsonParsed`, `base58`, `base64`; “Set to 1 to receive legacy, v0, and v1 transactions.” | Explicit requested full-version/encoding support. This does not specify error versus silent omission when a lower/absent maximum encounters newer versions. |
| Paging | L44–45: token format “slot:position”; L617–624: “Pagination token for next page, or null if no more results.” | Explicit terminal marker for results of the declared query. This cannot establish the entire wallet ownership population by itself. |
| Other exclusions / nullable times | L145–146: transfer criteria narrow results and use AND semantics. L540–550, L602–612: blockTime can be null. | Filters narrow the result population; no null-time filter inclusion rule is stated here. |

The reference leaves these source-contract questions unresolved: whether owner membership is historical and scoped to event-time ownership intervals; closed/reopened/reassigned/non-ATA coverage; both token-program populations; exact earliest retained coverage; unsupported-version omission/error semantics; nullable-time filtering; and whether omitted historical metadata is possible. Its metadata shape description (L593–601) is not an independent retention guarantee for every field.

The reference includes no plan/billing requirement. No paid necessity is inferred. The observed existence of a terminal page for a specific query would establish that query's pagination result, not exhaustive historical wallet membership.
