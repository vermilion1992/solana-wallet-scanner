> ## Documentation Index
> Fetch the complete documentation index at: https://www.helius.dev/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# getTransactionsForAddress

> getTransactionsForAddress returns complete Solana transaction history for an address in one call — time, slot, and status filters, sorting, and keyset paging.

## Request Parameters

<ParamField body="address" type="string" required>
  Solana account address to retrieve transaction history for (wallet, token, program, NFT, etc.).
</ParamField>

<ParamField body="transactionDetails" type="string" default="signatures">
  Level of transaction detail to return.

  * `signatures`
  * `full`
</ParamField>

<ParamField body="sortOrder" type="string" default="desc">
  Sort order for returned transactions.

  * `asc`
  * `desc`
</ParamField>

<ParamField body="commitment" type="string" default="finalized">
  The commitment level for the request. The `processed` commitment is not supported.

  * `confirmed`
  * `finalized`
</ParamField>

<ParamField body="minContextSlot" type="number">
  Minimum context slot to use for request (optional).
</ParamField>

<ParamField body="limit" type="number" default="1000">
  Maximum number of transactions per request. Use 1–1000 for transactionDetails:"signatures" and 1–1000 for transactionDetails:"full".
</ParamField>

<ParamField body="paginationToken" type="string">
  Pagination token from previous response to get next page of results (format "slot:position").
</ParamField>

<ParamField body="encoding" type="string" default="json">
  Encoding format for transaction data (applies only when transactionDetails=full).

  * `json`
  * `jsonParsed`
  * `base58`
  * `base64`
</ParamField>

<ParamField body="maxSupportedTransactionVersion" type="number">
  Maximum transaction version to return (applies only when transactionDetails=full). Set to 1 to receive legacy, v0, and v1 transactions.
</ParamField>

<ParamField body="filters" type="object">
  Advanced filters to narrow down transaction results.
</ParamField>

<ParamField body="filters.slot" type="object">
  Filter by slot number.
</ParamField>

<ParamField body="filters.slot.gte" type="number">
  Greater than or equal to slot number.
</ParamField>

<ParamField body="filters.slot.gt" type="number">
  Greater than slot number.
</ParamField>

<ParamField body="filters.slot.lte" type="number">
  Less than or equal to slot number.
</ParamField>

<ParamField body="filters.slot.lt" type="number">
  Less than slot number.
</ParamField>

<ParamField body="filters.blockTime" type="object">
  Filter by block timestamp (Unix timestamp).
</ParamField>

<ParamField body="filters.blockTime.gte" type="number">
  Greater than or equal to timestamp.
</ParamField>

<ParamField body="filters.blockTime.gt" type="number">
  Greater than timestamp.
</ParamField>

<ParamField body="filters.blockTime.lte" type="number">
  Less than or equal to timestamp.
</ParamField>

<ParamField body="filters.blockTime.lt" type="number">
  Less than timestamp.
</ParamField>

<ParamField body="filters.blockTime.eq" type="number">
  Equal to timestamp.
</ParamField>

<ParamField body="filters.signature" type="object">
  Filter by transaction signature.
</ParamField>

<ParamField body="filters.signature.gte" type="string">
  Get transactions with signatures greater than or equal to this value.
</ParamField>

<ParamField body="filters.signature.gt" type="string">
  Get transactions after this signature.
</ParamField>

<ParamField body="filters.signature.lte" type="string">
  Get transactions with signatures less than or equal to this value.
</ParamField>

<ParamField body="filters.signature.lt" type="string">
  Get transactions before this signature.
</ParamField>

<ParamField body="filters.status" type="string" default="any">
  Filter by transaction status.

  * `succeeded`
  * `failed`
  * `any`
</ParamField>

<ParamField body="filters.tokenAccounts" type="string" default="none">
  Filter transactions for related token accounts. Controls whether to include transactions involving token accounts owned by the address.

  * `none`
  * `balanceChanged`
  * `all`
</ParamField>

<ParamField body="filters.tokenTransfer" type="object">
  Narrows results to transactions where the queried address participated in a token transfer matching specific criteria. All fields are optional and combined with AND semantics.
</ParamField>

<ParamField body="filters.tokenTransfer.with" type="string">
  Counterparty address. Matches transfers whose other side is this address.
</ParamField>

<ParamField body="filters.tokenTransfer.direction" type="string" default="any">
  Transfer direction relative to the queried address.

  * `in`
  * `out`
  * `any`
</ParamField>

<ParamField body="filters.tokenTransfer.mint" type="string">
  Token mint to filter on.
</ParamField>

<ParamField body="filters.tokenTransfer.amount" type="object">
  Raw on-chain amount range filter. All fields are optional and can be combined.
</ParamField>


## OpenAPI

````yaml openapi/rpc-http/getTransactionsForAddress.yaml POST /
openapi: 3.1.0
info:
  title: Solana RPC API
  version: 1.0.0
  description: >-
    Advanced Solana transaction history API with powerful filtering, sorting,
    and pagination capabilities for retrieving comprehensive transaction data
    for any address.
  license:
    name: Apache 2.0
    url: https://www.apache.org/licenses/LICENSE-2.0.html
servers:
  - url: https://mainnet.helius-rpc.com
    description: Mainnet RPC endpoint
  - url: https://devnet.helius-rpc.com
    description: Devnet RPC endpoint
security: []
paths:
  /:
    post:
      tags:
        - RPC
      summary: getTransactionsForAddress
      description: >
        Enhanced transaction history API that provides powerful filtering,
        sorting, and pagination capabilities 

        for retrieving transaction data associated with any Solana address. This
        advanced method overcomes the 

        limitations of getSignaturesForAddress by offering:


        - Bidirectional sorting (ascending/descending chronological order)

        - Advanced filtering by slot, time, signature, and transaction status

        - Token account support (include transactions for associated token
        accounts)

        - Token transfer filtering by counterparty, direction, mint, and raw
        amount

        - Efficient keyset pagination using slot-based keys

        - Option to return full transaction details or just signatures

        - Support for time range queries and status filtering


        Perfect for building comprehensive wallet histories, analytics
        dashboards, audit trails, 

        and any application requiring detailed transaction analysis with precise
        control over data retrieval.
      operationId: getTransactionsForAddress
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required:
                - jsonrpc
                - id
                - method
                - params
              properties:
                jsonrpc:
                  type: string
                  enum:
                    - '2.0'
                  example: '2.0'
                  description: The JSON-RPC protocol version.
                  default: '2.0'
                id:
                  type: string
                  example: '1'
                  description: A unique identifier for the request.
                  default: '1'
                method:
                  type: string
                  enum:
                    - getTransactionsForAddress
                  example: getTransactionsForAddress
                  description: The name of the RPC method to invoke.
                  default: getTransactionsForAddress
                params:
                  type: array
                  description: >-
                    Array containing the required account address and optional
                    configuration object.
                  minItems: 1
                  maxItems: 2
                  default:
                    - Vote111111111111111111111111111111111111111
                    - transactionDetails: signatures
                      limit: 50
                      sortOrder: desc
                      filters:
                        status: succeeded
                        slot:
                          gte: 1000
                          lt: 2000
                        tokenTransfer:
                          direction: in
                          mint: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
                  items:
                    oneOf:
                      - type: string
                        description: >-
                          Solana account address to retrieve transaction history
                          for (wallet, token, program, NFT, etc.).
                        example: Vote111111111111111111111111111111111111111
                      - type: object
                        description: >-
                          Advanced query configuration for filtering, sorting,
                          and pagination.
                        properties:
                          transactionDetails:
                            type: string
                            description: Level of transaction detail to return.
                            enum:
                              - signatures
                              - full
                            default: signatures
                            example: signatures
                          sortOrder:
                            type: string
                            description: Sort order for returned transactions.
                            enum:
                              - asc
                              - desc
                            default: desc
                            example: desc
                          commitment:
                            type: string
                            description: >-
                              The commitment level for the request. The
                              `processed` commitment is not supported.
                            enum:
                              - confirmed
                              - finalized
                            default: finalized
                            example: finalized
                          minContextSlot:
                            type: integer
                            description: >-
                              Minimum context slot to use for request
                              (optional).
                            example: 1000
                          limit:
                            type: integer
                            description: >-
                              Maximum number of transactions per request. Use
                              1–1000 for transactionDetails:"signatures" and
                              1–1000 for transactionDetails:"full".
                            minimum: 1
                            maximum: 1000
                            default: 1000
                            example: 100
                          paginationToken:
                            type: string
                            description: >-
                              Pagination token from previous response to get
                              next page of results (format "slot:position").
                            example: '1053:13'
                          encoding:
                            type: string
                            description: >-
                              Encoding format for transaction data (applies only
                              when transactionDetails=full).
                            enum:
                              - json
                              - jsonParsed
                              - base58
                              - base64
                            default: json
                            example: json
                          maxSupportedTransactionVersion:
                            type: integer
                            description: >-
                              Maximum transaction version to return (applies
                              only when transactionDetails=full). Set to 1 to
                              receive legacy, v0, and v1 transactions.
                            example: 1
                          filters:
                            type: object
                            description: >-
                              Advanced filters to narrow down transaction
                              results.
                            properties:
                              slot:
                                type: object
                                description: Filter by slot number.
                                properties:
                                  gte:
                                    type: integer
                                    description: Greater than or equal to slot number.
                                    example: 100
                                  gt:
                                    type: integer
                                    description: Greater than slot number.
                                    example: 100
                                  lte:
                                    type: integer
                                    description: Less than or equal to slot number.
                                    example: 200
                                  lt:
                                    type: integer
                                    description: Less than slot number.
                                    example: 200
                                additionalProperties: false
                              blockTime:
                                type: object
                                description: Filter by block timestamp (Unix timestamp).
                                properties:
                                  gte:
                                    type: integer
                                    description: Greater than or equal to timestamp.
                                    example: 1640995200
                                  gt:
                                    type: integer
                                    description: Greater than timestamp.
                                    example: 1640995200
                                  lte:
                                    type: integer
                                    description: Less than or equal to timestamp.
                                    example: 1641081600
                                  lt:
                                    type: integer
                                    description: Less than timestamp.
                                    example: 1641081600
                                  eq:
                                    type: integer
                                    description: Equal to timestamp.
                                    example: 1641038400
                                additionalProperties: false
                              signature:
                                type: object
                                description: Filter by transaction signature.
                                properties:
                                  gte:
                                    type: string
                                    description: >-
                                      Get transactions with signatures greater
                                      than or equal to this value.
                                    example: >-
                                      4h6xBEauJ3PK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv
                                  gt:
                                    type: string
                                    description: Get transactions after this signature.
                                    example: >-
                                      3jweEauJ3PK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv
                                  lte:
                                    type: string
                                    description: >-
                                      Get transactions with signatures less than
                                      or equal to this value.
                                    example: >-
                                      6k7xBEauJ3PK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv
                                  lt:
                                    type: string
                                    description: Get transactions before this signature.
                                    example: >-
                                      5h6xBEauJ3PK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv
                                additionalProperties: false
                              status:
                                type: string
                                description: Filter by transaction status.
                                enum:
                                  - succeeded
                                  - failed
                                  - any
                                default: any
                                example: succeeded
                              tokenAccounts:
                                type: string
                                description: >-
                                  Filter transactions for related token
                                  accounts. Controls whether to include
                                  transactions involving token accounts owned by
                                  the address.
                                enum:
                                  - none
                                  - balanceChanged
                                  - all
                                default: none
                                example: balanceChanged
                              tokenTransfer:
                                $ref: '#/components/schemas/TokenTransferFilter'
                                description: >-
                                  Filter to transactions where the queried
                                  address participated in a token transfer
                                  matching a counterparty, direction, mint, or
                                  raw amount range.
                            additionalProperties: false
      responses:
        '200':
          description: Successfully retrieved transactions for the specified address.
          content:
            application/json:
              schema:
                type: object
                properties:
                  jsonrpc:
                    type: string
                    description: The JSON-RPC protocol version.
                    enum:
                      - '2.0'
                    example: '2.0'
                  id:
                    type: string
                    description: Identifier matching the request.
                    example: '1'
                  result:
                    type: object
                    description: Transaction data and pagination information.
                    properties:
                      data:
                        type: array
                        description: List of transaction information.
                        items:
                          oneOf:
                            - type: object
                              description: >-
                                Signature-level transaction summary (when
                                transactionDetails is "signatures").
                              properties:
                                signature:
                                  type: string
                                  description: >-
                                    Transaction signature as a base-58 encoded
                                    string.
                                  example: >-
                                    5h6xBEauJ3PK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv
                                slot:
                                  type: integer
                                  description: >-
                                    The slot that contains the block with the
                                    transaction.
                                  example: 1054
                                transactionIndex:
                                  type: integer
                                  description: >-
                                    The zero-based index of the transaction
                                    within its block. Useful for determining
                                    transaction ordering within a block.
                                  example: 42
                                err:
                                  oneOf:
                                    - type: object
                                      description: Error if the transaction failed
                                    - type: 'null'
                                  description: >-
                                    Error if the transaction failed, or null if
                                    successful.
                                  example: null
                                memo:
                                  oneOf:
                                    - type: string
                                      description: Memo associated with the transaction
                                    - type: 'null'
                                  description: >-
                                    Memo associated with the transaction, or
                                    null if none.
                                  example: null
                                blockTime:
                                  oneOf:
                                    - type: integer
                                      description: >-
                                        Estimated production time as Unix
                                        timestamp
                                    - type: 'null'
                                  description: >-
                                    Estimated production time as Unix timestamp
                                    (seconds since epoch), or null if not
                                    available.
                                  example: 1641038400
                                confirmationStatus:
                                  oneOf:
                                    - type: string
                                      enum:
                                        - processed
                                        - confirmed
                                        - finalized
                                      description: >-
                                        Transaction's cluster confirmation
                                        status
                                    - type: 'null'
                                  description: Transaction's cluster confirmation status.
                                  example: finalized
                              required:
                                - signature
                                - slot
                                - transactionIndex
                              additionalProperties: false
                            - type: object
                              description: >-
                                Full transaction with status metadata (when
                                transactionDetails is "full").
                              properties:
                                slot:
                                  type: integer
                                  description: >-
                                    The slot that contains the block with the
                                    transaction.
                                  example: 1054
                                transactionIndex:
                                  type: integer
                                  description: >-
                                    The zero-based index of the transaction
                                    within its block. Useful for determining
                                    transaction ordering within a block.
                                  example: 42
                                transaction:
                                  type: object
                                  description: >-
                                    Encoded or parsed transaction object per the
                                    selected encoding.
                                meta:
                                  type: object
                                  description: >-
                                    Transaction status metadata — same shape as
                                    getTransaction, including err, fee,
                                    preBalances/postBalances,
                                    preTokenBalances/postTokenBalances,
                                    innerInstructions, logMessages, and
                                    computeUnitsConsumed.
                                blockTime:
                                  oneOf:
                                    - type: integer
                                      description: >-
                                        Estimated production time as Unix
                                        timestamp
                                    - type: 'null'
                                  description: >-
                                    Estimated production time as Unix timestamp
                                    (seconds since epoch), or null if not
                                    available.
                              required:
                                - slot
                                - transactionIndex
                                - transaction
                      paginationToken:
                        oneOf:
                          - type: string
                            description: Token for retrieving the next page of results
                          - type: 'null'
                        description: >-
                          Pagination token for next page, or null if no more
                          results.
                        example: '1055:5'
              examples:
                signaturesResponse:
                  summary: Response with signature details only
                  value:
                    jsonrpc: '2.0'
                    id: '1'
                    result:
                      data:
                        - signature: >-
                            5h6xBEauJ3PK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv
                          slot: 1054
                          transactionIndex: 42
                          err: null
                          memo: null
                          blockTime: 1641038400
                          confirmationStatus: finalized
                        - signature: >-
                            kwjd820slPK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv
                          slot: 1055
                          transactionIndex: 15
                          err: null
                          memo: null
                          blockTime: 1641038460
                          confirmationStatus: finalized
                      paginationToken: '1055:5'
                fullResponse:
                  summary: Response with full transaction details
                  value:
                    jsonrpc: '2.0'
                    id: '1'
                    result:
                      data:
                        - slot: 1054
                          transactionIndex: 42
                          transaction:
                            signatures:
                              - >-
                                5h6xBEauJ3PK6SWCZ1PGjBvj8vDdWG3KpwATGy1ARAXFSDwt8GFXM7W5Ncn16wmqokgpiKRLuS83KUxyZyv2sUYv
                            message:
                              accountKeys:
                                - ...
                                - ...
                              instructions:
                                - ...
                          meta:
                            err: null
                            fee: 5000
                            preBalances:
                              - 1000000
                              - 2000000
                            postBalances:
                              - 999995000
                              - 2000000
                            preTokenBalances:
                              - accountIndex: 1
                                mint: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
                                owner: ...
                                programId: TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA
                                uiTokenAmount:
                                  amount: '1500000'
                                  decimals: 6
                                  uiAmount: 1.5
                                  uiAmountString: '1.5'
                            postTokenBalances:
                              - accountIndex: 1
                                mint: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
                                owner: ...
                                programId: TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA
                                uiTokenAmount:
                                  amount: '500000'
                                  decimals: 6
                                  uiAmount: 0.5
                                  uiAmountString: '0.5'
                            logMessages:
                              - ...
                            computeUnitsConsumed: 2100
                          blockTime: 1641038400
                      paginationToken: '1055:5'
        '400':
          description: Bad Request - Invalid request parameters or malformed request.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
              example:
                jsonrpc: '2.0'
                error:
                  code: -32602
                  message: Invalid params
                id: '1'
        '401':
          description: Unauthorized - Invalid or missing API key.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
              example:
                jsonrpc: '2.0'
                error:
                  code: -32001
                  message: Unauthorized
                id: '1'
        '429':
          description: Too Many Requests - Rate limit exceeded.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
              example:
                jsonrpc: '2.0'
                error:
                  code: -32005
                  message: Too many requests
                id: '1'
        '500':
          description: Internal Server Error - An error occurred on the server.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
              example:
                jsonrpc: '2.0'
                error:
                  code: -32603
                  message: Internal error
                id: '1'
        '503':
          description: Service Unavailable - The service is temporarily unavailable.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
              example:
                jsonrpc: '2.0'
                error:
                  code: -32002
                  message: Service unavailable
                id: '1'
        '504':
          description: Gateway Timeout - The request timed out.
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
              example:
                jsonrpc: '2.0'
                error:
                  code: -32003
                  message: Gateway timeout
                id: '1'
      security:
        - ApiKeyQuery: []
components:
  schemas:
    TokenTransferFilter:
      type: object
      description: >-
        Narrows results to transactions where the queried address participated
        in a token transfer matching specific criteria. All fields are optional
        and combined with AND semantics.
      properties:
        with:
          type: string
          description: >-
            Counterparty address. Matches transfers whose other side is this
            address.
          example: 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM
        direction:
          type: string
          description: Transfer direction relative to the queried address.
          enum:
            - in
            - out
            - any
          default: any
          example: in
        mint:
          type: string
          description: Token mint to filter on.
          example: EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v
        amount:
          $ref: '#/components/schemas/TokenTransferAmountFilter'
          description: >-
            Amount comparison using the raw on-chain amount, not the UI or
            decimal-adjusted amount.
      additionalProperties: false
    ErrorResponse:
      type: object
      properties:
        jsonrpc:
          type: string
          description: The JSON-RPC protocol version.
          enum:
            - '2.0'
          example: '2.0'
        error:
          type: object
          properties:
            code:
              type: integer
              description: The error code.
              example: -32602
            message:
              type: string
              description: The error message.
            data:
              type: object
              description: Additional data about the error.
        id:
          type: string
          description: Identifier matching the request.
          example: '1'
    TokenTransferAmountFilter:
      type: object
      description: >-
        Raw on-chain amount range filter. All fields are optional and can be
        combined.
      properties:
        gt:
          type: number
          description: Strictly greater than.
          example: 1000000
        gte:
          type: number
          description: Greater than or equal.
          example: 1000000
        lt:
          type: number
          description: Strictly less than.
          example: 5000000
        lte:
          type: number
          description: Less than or equal.
          example: 5000000
      additionalProperties: false
  securitySchemes:
    ApiKeyQuery:
      type: apiKey
      in: query
      name: api-key
      description: >-
        Your Helius API key. You can get one for free in the
        [dashboard](https://dashboard.helius.dev/api-keys).

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.