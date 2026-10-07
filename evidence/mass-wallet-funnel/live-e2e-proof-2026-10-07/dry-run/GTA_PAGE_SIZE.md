{
  "kind": "helius-gta-page-size-v1",
  "docs": "https://www.helius.dev/docs/rpc/gettransactionsforaddress",
  "reviewed_on": "2026-10-07",
  "max_limit": 1000,
  "signatures_only": {
    "transactionDetails": "signatures",
    "limit": 1000,
    "credits": 10,
    "note": "10 credits flat for up to 1,000 signatures."
  },
  "full_sample": {
    "transactionDetails": "full",
    "limit": 100,
    "credits": 10,
    "note": "One sample page. 10 credits per 100 txs returned."
  },
  "full_history": {
    "transactionDetails": "full",
    "limit": 1000,
    "credits_worst_case": 100,
    "note": "Largest documented page. Same credits as ten limit=100 pages for 1,000 returned txs; fewer requests. next-capture freeze stays limit=100 and is not used here."
  },
  "PRODUCT_READY": false
}
