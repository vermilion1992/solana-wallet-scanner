# G1 material-exit v2 (offline control)

New saved/reopened report from the genuine G1 archive. Prior
`g1-offline-repair-replay` artifacts are left in place.

- Metric version: `material-exit-v2`
- first_sale / t50 / t90 / quantity-weighted exit time / final hold are
  opening-relative per completed position
- Quantity-weighted exit time is not quantity-weighted lot holding time
- Screening snapshot `material_exit_t90_seconds` uses the same opening-relative t90
- P&L unchanged at the established G1 subset control
- `PRODUCT_READY` false; not ranked-wallet / G3 proof
