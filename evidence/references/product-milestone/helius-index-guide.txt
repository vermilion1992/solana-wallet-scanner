> ## Documentation Index
> Fetch the complete documentation index at: https://www.helius.dev/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# getTransactionsForAddress Overview and Tutorial

> Learn how to query Solana transaction history with advanced filtering, bidirectional sorting, and efficient pagination using this Helius-exclusive RPC method.

## Overview

[`getTransactionsForAddress`](/docs/api-reference/rpc/http/gettransactionsforaddress) is a Helius-exclusive RPC method that returns an address's transaction history with advanced filtering, flexible sorting, and efficient pagination. It is not part of standard Solana RPC.

Unlike `getSignaturesForAddress`, which only returns signatures and skips associated token accounts, `getTransactionsForAddress` can return complete transaction data, including a wallet's associated token account (ATA) activity, in a single call. That makes it the fastest path to a full address history for backfilling, indexing, and analytics.

This method returns up to 1,000 full transactions per call.

<CardGroup cols={2}>
  <Card title="Flexible sorting" icon="arrows-up-down">
    Sort chronologically (oldest first) or reverse (newest first).
  </Card>

  <Card title="Advanced filtering" icon="filter">
    Filter by time ranges, slots, signatures, status, and token transfers.
  </Card>

  <Card title="Full transaction data" icon="database">
    Get complete transaction details in one call, no follow-up getTransaction needed.
  </Card>

  <Card title="Token accounts" icon="layer-group">
    Include transactions for an address's associated token accounts.
  </Card>
</CardGroup>

## When to use this

Use `getTransactionsForAddress` when you need:

* Complete wallet token history, including associated token accounts
* A fast single-call backfill for an indexer or data pipeline
* Time-based or slot-based transaction analysis and reporting
* Status filtering to keep only succeeded or only failed transactions
* Chronological historical replay (oldest-first ordering)
* Token launch analysis: first mint transactions and early holders
* Wallet funding history and counterparty discovery
* Compliance and audit reports for a specific time period

For parsed, transfer-only history (payments, balance reconciliation), use [`getTransfersByAddress`](/docs/rpc/gettransfersbyaddress) instead.

### Network support

| Network | Supported | Retention Period |
| - | - | - |
| Mainnet | Yes | Unlimited |
| Devnet | Yes | 2 weeks |
| Testnet | No | N/A |

## Quickstart

<Steps>
  <Step title="Get your API key">
    Obtain your API key from the [Helius Dashboard](https://dashboard.helius.dev/api-keys).
  </Step>

  <Step title="Query with advanced features">
    Get all successful transactions for a wallet between two dates, sorted chronologically:

    ```javascript theme={"system"}
    // Get successful transactions between Jan 1-31, 2025 in chronological order
    const response = await fetch('https://mainnet.helius-rpc.com/?api-key=YOUR_API_KEY', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'getTransactionsForAddress',
        params: [
          'YOUR_ADDRESS_HERE',
          {
            transactionDetails: 'full',
            sortOrder: 'asc',
            limit: 1000,
            filters: {
              blockTime: {
                gte: 1735689600,   // Jan 1, 2025
                lt: 1738368000     // Before Feb 1, 2025
              },
              status: 'succeeded',  // Only successful transactions
              tokenAccounts: 'balanceChanged' // Include associated token accounts
            }
          }
        ]
      })
    });

    const data = await response.json();
    console.log('Successful transactions in January:', data.result.data);
    ```
  </Step>

  <Step title="Understand the parameters">
    This example shows the key features:

    * **transactionDetails**: set to `'full'` to get complete transaction data in one call
    * **sortOrder**: use `'asc'` for chronological order (oldest first) or `'desc'` for newest first
    * **filters.blockTime**: set time ranges with `gte` (greater than or equal) and `lte` (less than or equal)
    * **filters.status**: filter to only `'succeeded'` or `'failed'` transactions
    * **filters.tokenAccounts**: include transfers, mints, and burns for associated token accounts
  </Step>
</Steps>

## Request parameters

<ParamField body="address" type="string" required>
  Base-58 encoded public key of the account to query transaction history for
</ParamField>

<ParamField body="transactionDetails" type="string" default="signatures">
  Level of transaction detail to return:

  * `signatures`: Basic signature info (faster)
  * `full`: Complete transaction data (eliminates need for getTransaction calls, supports limit up to 1,000)
</ParamField>

<ParamField body="sortOrder" type="string" default="desc">
  Sort order for results:

  * `desc`: Newest first (default)
  * `asc`: Oldest first (chronological, great for historical analysis)
</ParamField>

<ParamField body="limit" type="number" default="1000">
  Maximum transactions to return:

  * Up to 1000 when `transactionDetails: "signatures"`
  * Up to 1000 when `transactionDetails: "full"`
</ParamField>

<ParamField body="paginationToken" type="string">
  Pagination token from previous response (format: `"slot:position"`)
</ParamField>

<ParamField body="commitment" type="string" default="finalized">
  Commitment level: `finalized` or `confirmed`. The `processed` commitment is not supported.
</ParamField>

<ParamField body="filters" type="object">
  Advanced filtering options for narrowing down results.
</ParamField>

<ParamField body="filters.slot" type="object">
  Filter by slot number using comparison operators: `gte`, `gt`, `lte`, `lt`

  Example: `{ "slot": { "gte": 1000, "lte": 2000 } }`
</ParamField>

<ParamField body="filters.blockTime" type="object">
  Filter by Unix timestamp using comparison operators: `gte`, `gt`, `lte`, `lt`, `eq`

  Example: `{ "blockTime": { "gte": 1640995200, "lte": 1641081600 } }`
</ParamField>

<ParamField body="filters.signature" type="object">
  Filter by transaction signature using comparison operators: `gte`, `gt`, `lte`, `lt`

  Example: `{ "signature": { "lt": "SIGNATURE_STRING" } }`
</ParamField>

<ParamField body="filters.status" type="string">
  Filter by transaction success/failure status:

  * `succeeded`: Only successful transactions
  * `failed`: Only failed transactions
  * `any`: Both successful and failed (default)

  Example: `{ "status": "succeeded" }`
</ParamField>

<ParamField body="filters.tokenAccounts" type="string" default="none">
  Filter transactions for related token accounts:

  * `none`: Only return transactions that reference the provided address (default)
  * `balanceChanged`: Return transactions that reference either the provided address or modify the balance of a token account owned by the provided address (recommended)
  * `all`: Return transactions that reference either the provided address or any token account owned by the provided address

  Example: `{ "tokenAccounts": "balanceChanged" }`
</ParamField>

<ParamField body="filters.tokenTransfer" type="object">
  Filter to transactions where the queried address participated in a token transfer matching a counterparty, direction, mint, or raw amount range. All fields are optional and combined with AND semantics.

  Example: `{ "tokenTransfer": { "direction": "in", "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" } }`
</ParamField>

<ParamField body="filters.tokenTransfer.with" type="string">
  Counterparty address. Matches transfers whose other side is this address.
</ParamField>

<ParamField body="filters.tokenTransfer.direction" type="string" default="any">
  Filter by transfer direction relative to the queried address:

  * `in`: Transfers received by the queried address
  * `out`: Transfers sent by the queried address
  * `any`: Incoming and outgoing transfers
</ParamField>

<ParamField body="filters.tokenTransfer.mint" type="string">
  Token mint to filter on.
</ParamField>

<ParamField body="filters.tokenTransfer.amount" type="object">
  Amount comparison using the raw on-chain amount, not the UI or decimal-adjusted amount. Supports `gt`, `gte`, `lt`, and `lte`.
</ParamField>

<ParamField body="encoding" type="string">
  Encoding format for transaction data (only applies when `transactionDetails: "full"`). Same as `getTransaction` API. Options: `json`, `jsonParsed`, `base64`, `base58`
</ParamField>

<ParamField body="maxSupportedTransactionVersion" type="number">
  Set the max transaction version to return. If omitted, only legacy transactions will be returned. Set to `1` to include legacy, v0, and v1 transactions.
</ParamField>

<ParamField body="minContextSlot" type="number">
  The minimum slot that the request can be evaluated at
</ParamField>

### Metering

Successful responses are metered by what is returned:

| Response type | Credits |
| - | - |
| Full transactions | 10 credits per 100 returned transactions, rounded up; 10-credit minimum |
| Signatures only | 10 credits flat, regardless of count |
| Failed API responses | Free |

## Response

The response shape depends on `transactionDetails`. Signatures mode returns lightweight signature records; full mode returns complete transaction and metadata objects.

<Tabs>
  <Tab title="Signatures Response">
    ```json theme={"system"}
    {
      "jsonrpc": "2.0",
      "id": 1,
      "result": {
        "data": [
          {
            "signature": "5h6xBEauJ3PK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv",
            "slot": 1054,
            "transactionIndex": 42,
            "err": null,
            "memo": null,
            "blockTime": 1641038400,
            "confirmationStatus": "finalized"
          }
        ],
        "paginationToken": "1055:5"
      }
    }
    ```
  </Tab>

  <Tab title="Full Transaction Response">
    ```json theme={"system"}
    {
      "jsonrpc": "2.0",
      "id": 1,
      "result": {
        "data": [
          {
            "slot": 1054,
            "transactionIndex": 42,
            "blockTime": 1641038400,
            "transaction": {
              "signatures": ["5h6xBEauJ3PK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv"],
              "message": {
                "accountKeys": ["...", "..."],
                "instructions": [...],
                // Complete transaction structure
              }
            },
            "meta": {
              "err": null,
              "fee": 5000,
              "preBalances": [1000000, 2000000],
              "postBalances": [999995000, 2000000],
              "preTokenBalances": [
                {
                  "accountIndex": 1,
                  "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                  "owner": "...",
                  "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                  "uiTokenAmount": {
                    "amount": "1500000",
                    "decimals": 6,
                    "uiAmount": 1.5,
                    "uiAmountString": "1.5"
                  }
                }
              ],
              "postTokenBalances": [
                {
                  "accountIndex": 1,
                  "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                  "owner": "...",
                  "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                  "uiTokenAmount": {
                    "amount": "500000",
                    "decimals": 6,
                    "uiAmount": 0.5,
                    "uiAmountString": "0.5"
                  }
                }
              ],
              "innerInstructions": [...],
              "logMessages": [...],
              "computeUnitsConsumed": 2100
              // Complete metadata — same shape as getTransaction
            }
          }
        ],
        "paginationToken": "1055:5"
      }
    }
    ```
  </Tab>
</Tabs>

### Response fields

| Field | Type | Description |
| - | - | - |
| `signature` | string | Transaction signature (base-58 encoded). Only in signatures mode. |
| `slot` | number | The slot containing the block with this transaction. |
| `transactionIndex` | number | The zero-based index of the transaction within its block. Useful for transaction ordering and block reconstruction. |
| `blockTime` | number \| null | Estimated production time as Unix timestamp (seconds since epoch). |
| `err` | object \| null | Error if the transaction failed, null if successful. Only in signatures mode. |
| `memo` | string \| null | Memo associated with the transaction. Only in signatures mode. |
| `confirmationStatus` | string | Transaction's cluster confirmation status. Only in signatures mode. |
| `transaction` | object | Full transaction data. Only in full mode. |
| `meta` | object | Transaction status metadata — same shape as `getTransaction`, including `err`, `fee`, `preBalances`/`postBalances`, `preTokenBalances`/`postTokenBalances`, `innerInstructions`, `logMessages`, and `computeUnitsConsumed`. Only in full mode. |
| `paginationToken` | string \| null | Token for fetching the next page, or null if no more results. |

The `transactionIndex` field is exclusive to `getTransactionsForAddress`. Other similar endpoints like `getSignaturesForAddress`, `getTransaction`, and `getTransactions` do not include this field.

In full mode, `meta` is the complete transaction metadata object — identical in shape to what `getTransaction` returns. It includes `preTokenBalances` and `postTokenBalances`, so you can compute token balance changes (for example, to detect swaps) directly from the response without any follow-up calls.

## Filters

You can use comparison operators for `slot`, `blockTime`, and `signature`, plus the special `status`, `tokenAccounts`, and `tokenTransfer` filters. Combining multiple filters narrows the result to their intersection.

### Comparison operators

These operators work like database queries to give you precise control over your data range.

| Operator | Full Name | Description | Example |
| - | - | - | - |
| `gte` | Greater Than or Equal | Include values ≥ specified value | `slot: { gte: 100 }` |
| `gt` | Greater Than | Include values > specified value | `blockTime: { gt: 1641081600 }` |
| `lte` | Less Than or Equal | Include values ≤ specified value | `slot: { lte: 2000 }` |
| `lt` | Less Than | Include values \< specified value | `blockTime: { lt: 1641168000 }` |
| `eq` | Equal | Include values exactly equal (only `blockTime`) | `blockTime: { eq: 1641081600 }` |

### Enum filters

| Filter | Description | Values |
| - | - | - |
| `status` | Filter transactions by success/failure | `succeeded`, `failed`, or `any` |
| `tokenAccounts` | Filter transactions for related token accounts | `none`, `balanceChanged`, or `all` |

Combined filter examples:

```javascript theme={"system"}
// Time range with successful transactions only
"filters": {
  "blockTime": {
    "gte": 1640995200,
    "lte": 1641081600
  },
  "status": "succeeded"
}

// Slot range
"filters": {
  "slot": {
    "gte": 1000,
    "lte": 2000
  }
}

// Only failed transactions
"filters": {
  "status": "failed"
}
```

### Associated token accounts

On Solana, a wallet doesn't hold tokens directly. Instead, the wallet owns token accounts, and those token accounts hold the tokens. When someone sends you USDC, it goes to your USDC token account, not your main wallet address.

This method is unique because it can query **complete token history**, including a wallet's associated token accounts (ATAs). Native RPC methods such as `getSignaturesForAddress` do not include ATAs.

The `tokenAccounts` filter controls this behavior:

* **`none`** (default): Only returns transactions that directly reference the wallet address. Use this when you only care about direct wallet interactions.
* **`balanceChanged`** (recommended): Returns transactions that reference the wallet address or modify the balance of a token account owned by the wallet. This filters out spam and unrelated operations like fee collections or delegations, giving you a clean view of meaningful wallet activity.
* **`all`**: Returns all transactions that reference the wallet address or any token account owned by the wallet.

The `tokenAccounts` filter does not support transactions prior to December 2022. It depends on token transfer metadata introduced to Solana on slot 111,491,819. To cover earlier activity, see the [historical token account workaround](#limitations-and-edge-cases).

### Token transfer filter

The `tokenTransfer` filter narrows results to transactions where the queried address participated in a token transfer matching specific criteria: a particular counterparty, mint, direction, or amount range.

Use it to answer questions like:

* When did this wallet receive USDC from a specific counterparty?
* Show every outgoing transfer above 1,000 tokens.
* When did this wallet ever touch this specific mint?

The filter is an optional field inside the `filters` object of the request config:

```json theme={"system"}
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "getTransactionsForAddress",
  "params": [
    "<address>",
    {
      "filters": {
        "tokenTransfer": {}
      }
    }
  ]
}
```

All fields inside `tokenTransfer` are optional. Combining multiple fields is treated as AND.

| Field | Type | Default | Description |
| - | - | - | - |
| `with` | string (pubkey) | - | Counterparty address. Matches transfers whose other side is this address. |
| `direction` | `"in"` \| `"out"` \| `"any"` | `"any"` | Whether the queried address received, sent, or either. |
| `mint` | string (pubkey) | - | Token mint to filter on. |
| `amount` | object | - | Amount comparison. Uses the raw on-chain amount, not the UI or decimal-adjusted amount. |

Amount range operators:

| Operator | Meaning |
| - | - |
| `gt` | Strictly greater than |
| `gte` | Greater than or equal |
| `lt` | Strictly less than |
| `lte` | Less than or equal |

You can combine amount operators, such as `{ "gte": 1000000, "lte": 5000000 }` for a closed range. `tokenTransfer` composes with the other top-level filters (`slot`, `blockTime`, `status`, and `tokenAccounts`); the final result is the intersection.

## Examples

### Time-based analytics

Generate monthly transaction reports:

```javascript theme={"system"}
// Get all successful transactions for January 2025
const startTime = Math.floor(new Date('2025-01-01').getTime() / 1000);
const endTime = Math.floor(new Date('2025-02-01').getTime() / 1000);

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "getTransactionsForAddress",
  "params": [
    "WALLET_OR_PROGRAM_ADDRESS",
    {
      "transactionDetails": "signatures",
      "filters": {
        "blockTime": {
          "gte": startTime,
          "lt": endTime
        },
        "status": "succeeded"
      },
      "limit": 1000
    }
  ]
}
```

Process for analytics:

```javascript theme={"system"}
// Calculate daily transaction volume
const dailyStats = {};
response.result.data.forEach(tx => {
  const date = new Date(tx.blockTime * 1000).toISOString().split('T')[0];
  dailyStats[date] = (dailyStats[date] || 0) + 1;
});

console.log('Daily Transaction Counts:', dailyStats);
```

### Token mint creation

Find the mint creation transaction for a specific token:

```javascript theme={"system"}
{
  "jsonrpc": "2.0",
  "id": "find-first-mints",
  "method": "getTransactionsForAddress",
  "params": [
    MINT_ADDRESS, // Token mint address
    {
      "encoding": "jsonParsed",
      "maxSupportedTransactionVersion": 1,
      "sortOrder": "asc",  // Chronological order from the beginning
      "limit": 10,
      "transactionDetails": "full"
    }
  ]
}
```

For liquidity pool creation, query the pool address:

```javascript theme={"system"}
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "getTransactionsForAddress", 
  "params": [
    "POOL_ADDRESS_HERE", // Raydium/Meteora pool address
    {
      "transactionDetails": "full",
      "sortOrder": "asc",  // First transaction is usually pool creation
      "limit": 1
    }
  ]
}
```

This finds the exact moment a token mint or liquidity pool was created, including the creator address and initial parameters.

### Funding transactions

Find who funded a specific address:

```javascript theme={"system"}
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "getTransactionsForAddress",
  "params": [
    "TARGET_WALLET_ADDRESS",
    {
      "transactionDetails": "full",
      "sortOrder": "asc",  // Oldest first
      "limit": 10
    }
  ]
}
```

Then analyze the transaction data to find SOL transfers:

```javascript theme={"system"}
response.result.data.forEach(tx => {
  // Look for SOL transfers in preBalances/postBalances
  const balanceChanges = tx.meta.preBalances.map((pre, index) => 
    tx.meta.postBalances[index] - pre
  );
  
  // Positive balance change = incoming SOL
  balanceChanges.forEach((change, index) => {
    if (change > 0) {
      console.log(`Received ${change} lamports from ${tx.transaction.message.accountKeys[index]}`);
    }
  });
});
```

The first few transactions often reveal the funding source and can help identify related addresses or funding patterns.

### Token transfers

Filter by `tokenTransfer` to isolate specific token movements.

USDC inflows to an address:

```json theme={"system"}
{
  "filters": {
    "tokenTransfer": {
      "direction": "in",
      "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    }
  }
}
```

Large outgoing transfers to a specific counterparty:

```json theme={"system"}
{
  "filters": {
    "tokenTransfer": {
      "with": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
      "direction": "out",
      "amount": { "gte": 1000000000 }
    }
  }
}
```

Combined with slot range and status:

```json theme={"system"}
{
  "filters": {
    "status": "succeeded",
    "slot": { "gte": 100000000, "lte": 200000000 },
    "tokenTransfer": {
      "direction": "in",
      "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
      "amount": { "gte": 5000000 }
    }
  }
}
```

## Pagination

When you have more transactions than your limit, use the `paginationToken` from the response to fetch the next page. The token is a simple string in the format `"slot:position"` that tells the API where to continue from.

Use the pagination token from each response to fetch the next page:

```javascript theme={"system"}
// First request
let paginationToken = null;
let allTransactions = [];

const getNextPage = async (paginationToken = null) => {
  const params = [
    'ADDRESS',
    {
      transactionDetails: 'signatures',
      limit: 100,
      ...(paginationToken && { paginationToken })
    }
  ];

  const response = await fetch(rpcUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'getTransactionsForAddress',
      params
    })
  });

  const data = await response.json();
  return data.result;
};

// Paginate through all results
do {
  const result = await getNextPage(paginationToken);
  allTransactions.push(...result.data);
  paginationToken = result.paginationToken;
  
  console.log(`Fetched ${result.data.length} transactions, total: ${allTransactions.length}`);
} while (paginationToken);
```

### Multiple addresses

You cannot query multiple addresses in a single request. Each address query counts as a separate API request and is metered accordingly. To fetch transactions for multiple addresses, query each address within the same time or slot window, then merge and sort:

```javascript theme={"system"}
const addresses = ['Address1...', 'Address2...', 'Address3...'];

// Query all addresses in parallel with slot filter
const results = await Promise.all(
  addresses.map(address => 
    fetch(rpcUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'getTransactionsForAddress',
        params: [address, {
          sortOrder: 'desc',
          filters: { slot: { gt: 250000000 } }
        }]
      })
    }).then(r => r.json())
  )
);

// Merge and sort by slot
const allTransactions = results
  .flatMap(r => r.result.data)
  .sort((a, b) => b.slot - a.slot);
```

For larger history scans, iterate through time or slot windows (e.g., 1000 slots at a time) and repeat this pattern.

## Best practices

**Performance.** Use `transactionDetails: "signatures"` when you don't need full transaction data. Use reasonable page sizes for better response times, and filter by time ranges or specific slots for more targeted queries.

**Filtering.** Start with broad filters and narrow down progressively. Use time-based filters for analytics and reporting workflows, and combine multiple filters for precise queries that target specific transaction types or time periods.

**Pagination.** Store pagination tokens when you need to resume large queries later. Monitor pagination depth for performance planning, and use ascending order when you need to replay historical events in chronological order.

**Error handling.** Handle rate limits gracefully with exponential backoff. Validate addresses before making requests, and cache results when appropriate to reduce API usage.

## Limitations and edge cases

A small set of addresses route to legacy archival, are limited to slot-scan fallback, or return empty. Token-account discovery before slot 111,491,819 also requires a workaround. Expand the sections below for the full details.

<Accordion title="Unsupported and specially-routed addresses">
  **Routed to old archival.** Requests for these addresses are routed to our old archival system.

  | Address | Name |
  | - | - |
  | `Stake11111111111111111111111111111111111111` | [Stake Program](https://orbmarkets.io/address/Stake11111111111111111111111111111111111111/history) |
  | `StakeConfig11111111111111111111111111111111` | [Stake Config](https://orbmarkets.io/address/StakeConfig11111111111111111111111111111111/history) |
  | `Sysvar1111111111111111111111111111111111111` | [Sysvar Owner](https://orbmarkets.io/address/Sysvar1111111111111111111111111111111111111/history) |
  | `AddressLookupTab1e1111111111111111111111111` | [Address Lookup Table](https://orbmarkets.io/address/AddressLookupTab1e1111111111111111111111111/history) |
  | `BPFLoaderUpgradeab1e11111111111111111111111` | [BPF Loader Upgradeable](https://orbmarkets.io/address/BPFLoaderUpgradeab1e11111111111111111111111/history) |

  **Slot-scan fallback.** Requests for these addresses are forwarded to our new archival system, and are queryable through a slot-by-slot scan approach (max 100 slots). However, this data is not indexed.

  | Address | Name |
  | - | - |
  | `11111111111111111111111111111111` | [System Program](https://orbmarkets.io/address/11111111111111111111111111111111/history) |
  | `ComputeBudget111111111111111111111111111111` | [Compute Budget](https://orbmarkets.io/address/ComputeBudget111111111111111111111111111111/history) |
  | `MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr` | [Memo Program](https://orbmarkets.io/address/MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr/history) |
  | `Vote111111111111111111111111111111111111111` | [Vote Program](https://orbmarkets.io/address/Vote111111111111111111111111111111111111111/history) |

  **Returns empty (`is_reserved_address`).** Requests are forwarded to our new archival system, however the data is not indexed, and queries return empty.

  | Address | Name |
  | - | - |
  | `BPFLoader1111111111111111111111111111111111` | [BPF Loader (deprecated)](https://orbmarkets.io/address/BPFLoader1111111111111111111111111111111111/history) |
  | `BPFLoader2111111111111111111111111111111111` | [BPF Loader](https://orbmarkets.io/address/BPFLoader2111111111111111111111111111111111/history) |
  | `Config1111111111111111111111111111111111111` | [Config Program](https://orbmarkets.io/address/Config1111111111111111111111111111111111111/history) |
  | `Ed25519SigVerify111111111111111111111111111` | [Ed25519 Program](https://orbmarkets.io/address/Ed25519SigVerify111111111111111111111111111/history) |
  | `Feature111111111111111111111111111111111111` | [Feature Program](https://orbmarkets.io/address/Feature111111111111111111111111111111111111/history) |
  | `KeccakSecp256k11111111111111111111111111111` | [Secp256k1 Program](https://orbmarkets.io/address/KeccakSecp256k11111111111111111111111111111/history) |
  | `LoaderV411111111111111111111111111111111111` | [Loader V4](https://orbmarkets.io/address/LoaderV411111111111111111111111111111111111/history) |
  | `NativeLoader1111111111111111111111111111111` | [Native Loader](https://orbmarkets.io/address/NativeLoader1111111111111111111111111111111/history) |
  | `SysvarC1ock11111111111111111111111111111111` | [Clock Sysvar](https://orbmarkets.io/address/SysvarC1ock11111111111111111111111111111111/history) |
  | `SysvarEpochSchedu1e111111111111111111111111` | [Epoch Schedule Sysvar](https://orbmarkets.io/address/SysvarEpochSchedu1e111111111111111111111111/history) |
  | `SysvarFees111111111111111111111111111111111` | [Fees Sysvar](https://orbmarkets.io/address/SysvarFees111111111111111111111111111111111/history) |
  | `Sysvar1nstructions1111111111111111111111111` | [Instructions Sysvar](https://orbmarkets.io/address/Sysvar1nstructions1111111111111111111111111/history) |
  | `SysvarRecentB1ockHashes11111111111111111111` | [Recent Blockhashes Sysvar](https://orbmarkets.io/address/SysvarRecentB1ockHashes11111111111111111111/history) |
  | `SysvarRent111111111111111111111111111111111` | [Rent Sysvar](https://orbmarkets.io/address/SysvarRent111111111111111111111111111111111/history) |
  | `SysvarRewards111111111111111111111111111111` | [Rewards Sysvar](https://orbmarkets.io/address/SysvarRewards111111111111111111111111111111/history) |
  | `SysvarS1otHashes111111111111111111111111111` | [Slot Hashes Sysvar](https://orbmarkets.io/address/SysvarS1otHashes111111111111111111111111111/history) |
  | `SysvarS1otHistory11111111111111111111111111` | [Slot History Sysvar](https://orbmarkets.io/address/SysvarS1otHistory11111111111111111111111111/history) |
  | `SysvarStakeHistory1111111111111111111111111` | [Stake History Sysvar](https://orbmarkets.io/address/SysvarStakeHistory1111111111111111111111111/history) |
  | `SysvarEpochRewards11111111111111111111111111` | [Epoch Rewards Sysvar](https://orbmarkets.io/address/SysvarEpochRewards11111111111111111111111111/history) |
  | `SysvarLastRestartS1ot1111111111111111111111` | [Last Restart Slot Sysvar](https://orbmarkets.io/address/SysvarLastRestartS1ot1111111111111111111111/history) |
</Accordion>

<Accordion title="Workaround: historical token account discovery (before slot 111,491,819)">
  For addresses with token account activity before slot 111,491,819, the `tokenAccounts` filter cannot determine ownership because the `owner` field in token balance metadata didn't exist yet. To get complete results, you can discover those token accounts manually by parsing early transaction instructions, then query `getTransactionsForAddress` in parallel for each one.

  ```javascript theme={"system"}
  const HELIUS_RPC = "https://mainnet.helius-rpc.com/?api-key=YOUR_API_KEY";
  const OWNER_CUTOFF_SLOT = 111_491_819;

  async function rpcCall(method, params) {
    const res = await fetch(HELIUS_RPC, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: "1", method, params }),
    });
    const json = await res.json();
    if (json.error) throw new Error(json.error.message);
    return json.result;
  }

  // Step 1: Discover token accounts owned by the address before the cutoff slot
  // by parsing initializeAccount instructions and transfer authorities.
  async function discoverHistoricalTokenAccounts(address) {
    const tokenAccounts = new Set();
    let paginationToken = null;

    do {
      const result = await rpcCall("getTransactionsForAddress", [
        address,
        {
          transactionDetails: "full",
          encoding: "jsonParsed",
          maxSupportedTransactionVersion: 1,
          sortOrder: "asc",
          limit: 100,
          filters: { slot: { lt: OWNER_CUTOFF_SLOT } },
          ...(paginationToken && { paginationToken }),
        },
      ]);
      if (!result?.data?.length) break;

      for (const entry of result.data) {
        const tx = entry.transaction;
        const meta = entry.meta;
        if (!tx || !meta) continue;

        const allInstructions = [
          ...(tx.message?.instructions ?? []),
          ...(meta.innerInstructions ?? []).flatMap((inner) => inner.instructions ?? []),
        ];

        for (const ix of allInstructions) {
          // AToken program "create" instruction
          if (ix.program === "spl-associated-token-account") {
            if (ix.parsed?.type === "create" && ix.parsed.info?.wallet === address && ix.parsed.info?.account) {
              tokenAccounts.add(ix.parsed.info.account);
            }
            continue;
          }

          if (ix.program !== "spl-token" && ix.program !== "spl-token-2022") continue;
          const type = ix.parsed?.type;
          const info = ix.parsed?.info;

          // Token account initialization
          if (type === "initializeAccount" || type === "initializeAccount2" || type === "initializeAccount3") {
            if (info?.owner === address && info?.account) tokenAccounts.add(info.account);
          }

          // Transfers where our address is the authority (source account is ours)
          if (type === "transfer" || type === "transferChecked") {
            if (info?.authority === address && info?.source) tokenAccounts.add(info.source);
          }
        }
      }
      paginationToken = result.paginationToken;
    } while (paginationToken);

    return Array.from(tokenAccounts);
  }

  // Step 2: Fetch all signatures for an address with pagination
  async function fetchAllSignatures(address, filters) {
    const allSignatures = [];
    let paginationToken = null;

    do {
      const result = await rpcCall("getTransactionsForAddress", [
        address,
        {
          transactionDetails: "signatures",
          sortOrder: "asc",
          limit: 1000,
          ...(filters && { filters }),
          ...(paginationToken && { paginationToken }),
        },
      ]);
      if (!result?.data?.length) break;
      allSignatures.push(...result.data);
      paginationToken = result.paginationToken;
    } while (paginationToken);

    return allSignatures;
  }

  // Step 3: Get complete history by combining tokenAccounts:"all" with
  // individual queries for historical token accounts
  async function getCompleteHistory(address) {
    const historicalAccounts = await discoverHistoricalTokenAccounts(address);

    if (historicalAccounts.length === 0) {
      return fetchAllSignatures(address, { tokenAccounts: "all" });
    }

    // Query main address with tokenAccounts:"all" + each historical account in parallel
    const results = await Promise.all([
      fetchAllSignatures(address, { tokenAccounts: "all" }),
      ...historicalAccounts.map((addr) => fetchAllSignatures(addr)),
    ]);

    // Merge and deduplicate by signature
    const seen = new Set();
    const merged = [];
    for (const batch of results) {
      for (const tx of batch) {
        if (!seen.has(tx.signature)) {
          seen.add(tx.signature);
          merged.push(tx);
        }
      }
    }
    return merged.sort((a, b) => a.slot - b.slot);
  }
  ```
</Accordion>

## How is this different from getSignaturesForAddress?

If you're familiar with the standard `getSignaturesForAddress` method, `getTransactionsForAddress` collapses multi-step workflows into a single call and adds filtering, sorting, and token-account support. For a step-by-step conversion of existing code, see the [migration guide](/docs/rpc/migrate-to-gettransactionsforaddress).

### Get full transactions in one call

With `getSignaturesForAddress`, you need two steps:

```javascript theme={"system"}
// Step 1: Get signatures
const signatures = await connection.getSignaturesForAddress(address, { limit: 1000 });

// Step 2: Get transaction details (1,000 additional calls!)
const transactions = await Promise.all(
  signatures.map(sig => connection.getTransaction(sig.signature))
);
```

With `getTransactionsForAddress`, it's one call:

```javascript theme={"system"}
const response = await fetch(heliusRpcUrl, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    jsonrpc: '2.0',
    id: 1,
    method: 'getTransactionsForAddress',
    params: [
      address,
      {
        transactionDetails: 'full',
        limit: 1000
      }
    ]
  })
});
```

### Get token history in one call

With `getSignaturesForAddress`, you need to first call `getTokenAccountsByOwner` and then query for every token account:

```javascript theme={"system"}
// OLD WAY (with getSignaturesForAddress)
// Step 1: Get all token accounts owned by this wallet
const tokenAccounts = await connection.getTokenAccountsByOwner(
  new PublicKey(walletAddress),
  { programId: TOKEN_PROGRAM_ID }
);

// Step 2: Fetch signatures for the wallet itself
const walletSignatures = await connection.getSignaturesForAddress(
  new PublicKey(walletAddress),
  { limit: 1000 }
);

// Step 3: Fetch signatures for EVERY token account (this is the painful part)
const tokenAccountSignatures = await Promise.all(
  tokenAccounts.value.map(async (account) => {
    return connection.getSignaturesForAddress(
      account.pubkey,
      { limit: 1000 }
    );
  })
);

// Step 4: Merge all results together
const allSignatures = [
  ...walletSignatures,
  ...tokenAccountSignatures.flat()
];

// Step 5: Deduplicate (many transactions touch multiple accounts)
const seen = new Set();
const uniqueSignatures = allSignatures.filter((sig) => {
  if (seen.has(sig.signature)) {
    return false;
  }
  seen.add(sig.signature);
  return true;
});

// Step 6: Sort chronologically
const sortedSignatures = uniqueSignatures.sort(
  (a, b) => a.slot - b.slot
);

return sortedSignatures;
```

With `getTransactionsForAddress` you only need to set `filters.tokenAccounts`:

```javascript theme={"system"}
// NEW WAY (with getTransactionsForAddress)
const response = await fetch("https://mainnet.helius-rpc.com/?api-key=YOUR_API_KEY", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    jsonrpc: "2.0",
    id: "helius-example",
    method: "getTransactionsForAddress",
    params: [
      walletAddress,
      {
        filters: {
          tokenAccounts: "all"
        },
        sortOrder: "asc",
        limit: 100
      }
    ]
  })
});

const { result } = await response.json();
return result;
```

### Additional capabilities

<CardGroup cols={2}>
  <Card title="Chronological sorting" icon="arrow-up">
    Sort transactions from oldest to newest with `sortOrder: 'asc'`.
  </Card>

  <Card title="Time-based filtering" icon="clock">
    Filter by time ranges using `blockTime` filters.
  </Card>

  <Card title="Status filtering" icon="filter">
    Get only successful or failed transactions with the `status` filter.
  </Card>

  <Card title="Simpler pagination" icon="list">
    Use `paginationToken` instead of confusing `before`/`until` signatures.
  </Card>
</CardGroup>

## Next steps

<CardGroup cols={2}>
  <Card title="Indexing guide" icon="layer-group" href="/docs/rpc/how-to-index-solana-data">
    Use getTransactionsForAddress to backfill and sync a Solana index.
  </Card>

  <Card title="getTransfersByAddress" icon="arrow-right-arrow-left" href="/docs/rpc/gettransfersbyaddress">
    Parsed, transfer-only history for payments and reconciliation.
  </Card>

  <Card title="API reference" icon="code" href="/docs/api-reference/rpc/http/gettransactionsforaddress">
    Full request and response schema for getTransactionsForAddress.
  </Card>

  <Card title="Historical data overview" icon="clock-rotate-left" href="/docs/rpc/historical-data">
    Compare all Solana historical data methods.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.