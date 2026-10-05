# Independent read-only sampled screening / forward observation review

Reviewed the final implementation in `scanner/screening.py`,
`scanner/screening_routes.py`, `scanner/paper.py`, `scanner/observer.py`, their
`scanner/app.py` integration, discovery/import selection and frontend displays.
Read the repository working rules and original accounting/acceptance boundaries.
The reviewer changed no application or repository test files and made no commit.

The final deterministic offline review controls pass. `result.json` contains ten
grouped controls, including four malformed-owner cases, and the SHA-256 values
of the reviewed source files. Reproduce with:

```sh
cd /workspace/solana-wallet-scanner
.venv/bin/python /workspace/scratch/review/probes.py
```

These are synthetic controls, not pytest population counts, authenticated live
monitoring or a profitable-wallet demonstration. The review made zero provider
calls and zero credential lookups. It did not run the full suite or perform a
separate browser workflow. The root validation and browser receipts have their
own scopes and must remain separately reported.

## Reproduced findings and final disposition

| Finding reproduced during implementation | Final disposition |
| --- | --- |
| Observation export passed an envelope without `id` to `observation_view`, raising `KeyError`. | The route decorates `exported['run']`; the final envelope shape control passes. |
| Loss of an original quote archive left positive recorded P&L and `complete_observation=True`. | Recorded history is preserved; current source availability becomes unknown, supported P&L is null and completeness is false. Exact restoration recovers support. Signal, notification, settings and raw quote sources are retained dependencies. |
| Public sample retries/restarts reset a per-client request allowance, and failed attempts / mint reads escaped displayed sample usage. | A durable conservative attempt ledger and persisted tranche allowance cover collection and mint reads; fresh clients cannot renew allowance. Source and focused budget contracts inspected. |
| Initial connection and reconnect delays fell outside exported monitoring gap spans. | Independent virtual timeline exports the complete initial 5-second and reconnect 7-second intervals. Missed activity remains unbackfilled. |
| Rechecking a public candidate replaced its sampled native signature with an unrelated recent signature, invalidating the public sample association. | Public identity checks prioritize retained sampled signatures; imported addresses use bounded recent signatures. The selected association is preserved. |
| One ineligible signal could produce `worth_observing` and supported zero-activity performance. | The final control produces insufficient evidence, no supported performance and incomplete observation. |
| A quote received at/after the run deadline could spend cash before duration enforcement. | Duration enforcement precedes monetary application; a boundary receipt is retained as cancelled, with no position or cash change. |
| Continuing a selected wallet increased collection for every wallet in the original batch. | Continuation sets an explicit wallet target and preserves original batch membership; the other wallet's checkpoint remains byte-for-byte equivalent. |
| `saved_identity` selected any passing cohort despite a same-slot identity conflict in another cohort. | Same highest-slot contradictions remain unknown; latest supported system-account facts are assessed with all original sources retained. |
| Updating an identity pointer within one cohort left an older dated account observation incorrectly relevant to the current type question. | All linked same-address account observations enter the temporal comparison. A newer slot-12 system observation passes while the older slot-11 source stays cited; loss of that original remains unknown. |
| Malformed account owners could crash the new identity aggregation or produce an unsupported failure label. | Null, object, array and numeric owners all return unknown without an exception. |

The independently worked monetary control retains provider output once, applies
the selected adverse haircut and one additional execution cost per action, and
produces `-0.129 SOL` P&L / `1.871 SOL` cash for a 1-SOL entry and a 0.9-SOL
quoted exit under the specified costs. It does not consume the leader's price.

No outstanding release-blocking finding was reproduced in the final reviewed
paths. This is a bounded review, not a guarantee that every defect is excluded.
Strict financial qualification and full historical acceptance stay separate from
sampled screening and quote-based paper outcomes.

One conservative export limitation remains: when the original settings snapshot
itself is missing, `export_run` raises the existing evidence error instead of
recreating an original from the recorded settings view. Normal inspection still
reports the missing dependency and preserves recorded history. This was reported
to the owner as an optional usability improvement, without requesting fabricated
replacement evidence.
