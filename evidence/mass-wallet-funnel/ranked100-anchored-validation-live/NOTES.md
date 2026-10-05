# Notes
- Box-only artifacts (not committed):
  - the raw credential-free source capture `SOURCE_RESPONSE_page0.json` (2.4 MB; sha256 recorded in INTEGRITY_CHECKS.json)
  - `scanner.sqlite`
  - the consumed local armed grant
  - all of these live under `/workspace/ranked100-anchored-validation-live/` on the secure box
- Freeze/overlay manifests under `g3-integrity-reacquire-rank1/` were referenced and not modified.
- Prior reacquire / leftover G3 / G1 / ranked-100 grants were not reused. A fresh data dir was used.
- Next step before any further live spend: fix the `_summarize_page` wrapping, then add a reviewed Pump.fun buy/sell decoder (bonding-curve) with fixtures. Without that decoder, this wallet cannot yield a reconciled position.
