# Operating the local ranked-100 scanner

Tested on Linux with the documented launcher only. Environments claimed
here: `./run.sh --no-browser` on loopback, and `./run.sh --lan --no-browser`
on this machine’s LAN IPv4. Phone size is Playwright Chromium at 390×844
(labelled browser emulation, not a physical phone). No remote host, tunnel,
or public preview was started.

`PRODUCT_READY` stays false. No live provider calls are authorised.

## Start / open

From the repository root, after `./setup.sh --skip-frontend` (or a checkout
that already has `.venv` and `frontend/dist`):

```sh
./run.sh
```

The process prints a session URL (`http://127.0.0.1:8765/#session=…`). Open
that URL in a browser. The fragment is a one-time login; the app exchanges
it for a session cookie. A bookmark without the fragment will 401 on
`/api/*` data and action routes.

Explicit data directory and no automatic browser:

```sh
./run.sh --data-dir ./local-data --no-browser
```

Phone on the same Wi-Fi (operator LAN only):

```sh
./run.sh --lan --no-browser
```

Scan the printed QR or open the printed token URL. Unauthenticated
`/api/state` stays 401.

Default data directory on Linux: `$XDG_DATA_HOME/solana-wallet-scanner`
or `~/.local/share/solana-wallet-scanner` when `XDG_DATA_HOME` is unset.
One process per data directory (`.runtime.lock`). A second start on the
same directory fails with `InstanceAlreadyRunning`.

## Stop / restart

Press Ctrl+C in the launcher terminal. The file lock releases when the
process exits. Restart with the same `./run.sh` command and the same
`--data-dir`. Saved filters, shortlist, and reports reopen from that
directory. A restart issues a new session token.

## Where saved reports and exports live

- Application database: `<data-dir>/scanner.sqlite` (reports, filters,
  shortlist, batch records).
- Compressed evidence blobs: `<data-dir>/evidence/`.
- In the UI: Search → Saved subset reports → Open / Reopen report.
- JSON export: open a report, or `GET /api/export/reports/<id>.json` with
  the session cookie. Search-run export is the Export run control.

Do not copy the session token into exports, screenshots, or git.

## Preserve data across an update

1. Stop the launcher.
2. Keep the data directory you have been using (`--data-dir` path, or the
   default above). Do not delete `scanner.sqlite` or `evidence/`.
3. `git pull` the code (or check out a new tag). Rebuild the interface only
   if you changed frontend sources: `cd frontend && npm ci && npm run build`.
4. Start `./run.sh` with the **same** `--data-dir`.

Code and data are separate. Updating git does not move the data directory.

## Research and acquisition controls

On Search:

- Browse the saved ranked-100 snapshot (`ranked100-discovery-pilot-2026-10-05`).
- Edit filters and Save filters. Unset thresholds do not pass. Research-screen
  defaults, fixed before evaluation: `min_completed_known_cost=1`,
  `min_sample_positions=3`.
- Shortlist rows. Analyse shortlist, or Analyse available + fixtures.
- Inspect trades/positions on a saved report. Results are conditional on
  captured inventory.
- Compare two saved reports. Each report keeps its own window; a window
  mismatch blocks compare.
- **Acquire history** runs only with a valid armed authorization. Without
  one it shows the exact block reason and does not dispatch. Both grant
  drafts in `config/` stay `enabled: false`.

Qualification categories describe **evidence quality** and are not the
research-screen pass/fail: not evaluated; analysed-incomplete; positive
matched-position evidence; positive net realised over the window;
profitable account performance. Investigated wallets, including losses
and inconclusive rows, stay in the batch and saved reports.

## Scope of what this checkout can do offline

Usable: browse 100 ranked wallets, reconstruct the one genuine cached
rank-1 page-0 capture, reconstruct labelled synthetics, save/reopen/export,
LAN token access.

Not usable without an external step: a second genuine ranked-wallet
capture (draft grant + confirmed Helius credits), remote access away from
the operator LAN, or any claim that `PRODUCT_READY` is true.
