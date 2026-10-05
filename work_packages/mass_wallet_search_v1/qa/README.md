# Package checks actually executed

The unit test log and profile receipts concern the handoff helper, not the wallet scanner.
45 helper/fixture tests passed. The synthetic receipt satisfies the development contract and correctly returns INCOMPLETE (exit 2) for both live-search and forward-operation. Three JSON Schemas were checked, and the synthetic example conforms to the receipt schema.

No genuine wallet scan, paid provider request, application test rerun, repository write, APK build or deployment was performed to create this package. Public documentation and the private repository baseline were read.

The test that exercises live-labelled receipt structure is deliberately synthetic. It demonstrates why declarations and hashes alone cannot establish authenticity. Independent acquisition provenance and arithmetic review remain separate acceptance requirements.
