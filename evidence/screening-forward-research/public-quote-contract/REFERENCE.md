# Quote-only observation integration reference

Captured 2026-10-04 UTC. This is software integration evidence, not a wallet-profit or follower-fill demonstration.

## Genuine live quote

`live-keyless-sol-usdc-quote.json` contains one successful genuine GET, HTTP 200, requested at 2026-10-04T22:36:37.943282Z and received at 2026-10-04T22:36:38.606848Z. No API key or `taker` was supplied; `transaction` and `taker` returned null. No transaction was built, signed, or submitted. Input 10,000,000 lamports SOL; output 1,219,412 USDC base units. Router `jupiterz`, `feeBps: 2`; `platformFee.amount` and `expireAt` were absent. The response includes `guaranteedPrice:true`; that does not establish a hypothetical user's executed fill or even their eligibility to execute.

## Jupiter Swap V2 contract

Read-only endpoint: `GET https://api.jup.ag/swap/v2/order`.

Required query: `inputMint`, `outputMint` (Solana mint strings), `amount` (positive base-unit integer string). Omit `taker`, `receiver`, `payer`, referral parameters; no wallet or signing key is needed for quote-only observation. Only `ExactIn` is supported. Native SOL is represented as `So11111111111111111111111111111111111111112`; use integer units and documented token decimals, never floats for balances.

Optional `slippageBps`: integer 0–10000; defaults to Jupiter's automatic choice. Explicit optional settings can change routing/mode; retain exact request settings. `otherAmountThreshold` is minimum output after returned slippage; `outAmount` is expected output before slippage. The observation engine should define whether it uses expected output or threshold plus an extra adverse-execution haircut. Do not apply returned slippage twice if using threshold.

Use `inputMint`, `outputMint`, `inAmount`, `outAmount`, `otherAmountThreshold`, `swapMode`, `slippageBps`, `routePlan`, `router`, `requestId`, `feeMint`, `feeBps`, `platformFee`, `signatureFeeLamports`, `prioritizationFeeLamports`, `rentFeeLamports`, and gas payer fields when present. Validate requested pair, nonzero exact input/output amounts, and retain raw body for review. Null `transaction` is the successful quote-only case, not a failed quote.

`priceImpact` is percentage points: -0.1 means -0.1%, equivalent to -0.001 ratio. Deprecated `priceImpactPct` is a decimal ratio; convert using ×100 to percentage points. The live quote returned both consistently: -0.022674100336355564 percentage points and -0.00022674100336355564 ratio. For an impact exclusion compare the absolute adverse magnitude using one normalized unit and display the signed raw value. Missing impact is unknown, not zero.

Jupiter's platform fee is already included in the quote and deducted automatically. Top-level `feeBps` is the total rate, potentially including gasless recoup; `platformFee.feeBps` is Jupiter's component. They are not two independent costs to subtract again. Preserve these as observed quote metadata; apply only explicitly additional simulated network/priority/tip and adverse-execution costs. No-taker zero gas estimates do not prove a real follower would have no network or ATA costs. Rent is locked/refundable capital, not always a permanent economic loss; label any fixed simplification as modeled. Do not assume that `platformFee.amount` is always supplied or that fees are always paid in output mint.

Source-provided quote creation timestamp is not documented. `totalTime` is response duration milliseconds, not a market timestamp. `expireAt` is an optional RFQ expiry timestamp; `lastValidBlockHeight` is an optional aggregator transaction expiry block height. Both were absent on the actual no-taker quote. A captured quote must retain local request-start and response-received UTC timestamps, requested delay, detection/decoding time, earliest eligibility time, and any actual extra lateness. A request must start at or after decoded signal + reaction delay. Never attach an earlier leader price or a quote from before that eligibility time. Define a local quote maximum age; do not infer an expiry from a missing field.

As of captured documentation, keyless access is explicitly supported at 30 requests/minute (0.5 RPS), with a 60-second sliding window. Free API keys give 60/minute. Keyed auth uses `x-api-key`; no credential is configured in this session. Honor 429 and `x-ratelimit-reset` (Unix seconds); requests share a main bucket across Swap, Price, Tokens. Do not burst mark-to-market quotes through the keyless limit.

Classify unavailable quotes distinctly: authentication/permission (401/403), rate limit (429), transport/provider error, invalid request (400), explicit no route, malformed response, and stale quote. Gateway auth failure does not prove token liquidity is absent. API OpenAPI still declares ApiKeyAuth on the endpoint, but the newer rate-limit guide and actual 200 keyless probe establish current keyless availability; retain this distinction.

## Solana notification and retrieval contract

One WebSocket `logsSubscribe` request per wallet:

```json
{"jsonrpc":"2.0","id":1,"method":"logsSubscribe","params":[{"mentions":["WALLET"]},{"commitment":"confirmed"}]}
```

`mentions` supports exactly one address; multiple addresses return invalid params. Success returns an integer subscription ID. Notification method is `logsNotification`; `params.result.context.slot`, `params.result.value.signature`, `err`, `logs`, and `params.subscription` identify the event. Record local reception timestamp before retrieval. Filter failed transactions (`err != null`) with a retained exclusion reason.

Retrieval: `getTransaction(signature, {"commitment":"confirmed","encoding":"json","maxSupportedTransactionVersion":0})`. It can return null until the transaction is available at requested commitment. Use bounded retries and retain the detection/retrieval/decoding timestamps; null is not proof of no activity. Existing decoder should establish a supported buy/sell; logs alone do not establish trade side or amounts.

Persist signature-based dedupe and pending delayed events atomically with portfolio changes/checkpoints. Reconnect/overflow/retrieval failures/restart pauses require durable monitoring-gap records. On restart, old due events may be excluded as missed; do not collect later quotes and pretend they existed during outage. Subscription mentions and `getSignaturesForAddress` address-account references do not guarantee complete beneficial activity across all token accounts. A subscription has no replay cursor or completeness proof.

`getSignaturesForAddress` returns references newest first, supports bounded `limit` (1–1000), `before`, `until`, commitment and minContextSlot. It can establish a start checkpoint or identify missed signatures, but missed-period signals stay missed for live paper accounting. Slow watchlist polling must report its actual detection delay and gaps; it cannot claim seconds-level subscription performance.

## Sources

- https://developers.jup.ag/docs/api-reference/swap/order
- https://developers.jup.ag/docs/swap/v2/order
- https://developers.jup.ag/docs/portal/rate-limits
- https://developers.jup.ag/docs/portal/api-keys
- https://solana.com/docs/rpc/websocket/logssubscribe
- https://solana.com/docs/rpc/http/gettransaction
- https://solana.com/docs/rpc/http/getsignaturesforaddress
