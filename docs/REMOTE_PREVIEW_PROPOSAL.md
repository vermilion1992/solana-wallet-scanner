# Remote deployment proposal (not deployed)

No permitted remote preview or public host exists in repo CI, docs, or
deploy config. This page is a complete deployment proposal only. Do not
create a tunnel, public host, or new deployment from this text. Mitch has
not approved a remote deploy.

## Target that fits the current stack

Keep the existing local authenticated launcher (`./run.sh --lan`) as the
supported phone path on the operator LAN. If Mitch later approves a remote
preview, use a private-network replica of that same stack: one container or
VM running `uvicorn scanner` + the built `frontend/dist` same-origin, bound
to a private hostname, never `0.0.0.0` on the public internet.

Suggested shape: a single Fly.io / Cloud Run / small VPS service that:

- Serves the already-built frontend from the Python app (current launcher).
- Requires the same session token + CSRF + Host allow-list.
- Uses a private DNS name or IP allow-list, not a public Pages/Vercel site.

## Secrets list

- `SCANNER_LAUNCH_TOKEN` (or the process-generated token printed at start;
  never commit it)
- Optional later: Helius key in OS keyring only, never in env files in git
- TLS certificate for the private hostname
- No Birdeye/Helius keys are required for the offline ranked-100 path

## Auth settings

- Token in the URL fragment, exchanged for an HttpOnly session cookie
- CSRF header on mutating `/api/*`
- Host allow-list = the private hostname only (plus loopback for admin)
- Unauthenticated API, export, saved-result, and job/progress routes return 401
- Do not put the token in the repo, screenshots, or evidence

## Expected cost

- Offline preview: $0 if it stays on Mitch’s own computer (`./run.sh --lan`)
- If a private VM is later approved: typically a few USD/month for one small
  instance plus TLS. No provider spend is implied. Grant templates stay
  disabled.

## Deploy steps (only after written approval)

1. Build `frontend` with `npm ci && npm run build`.
2. Install Python deps from `requirements.txt` (`--require-hashes`).
3. Start `./run.sh --lan --no-browser` (or the equivalent bind to the
   approved private hostname).
4. Confirm unauthenticated `/api/state` is 401 and `/api/health` is 401
   without the session.
5. Open the printed token URL on the phone or approved client.

## Rollback

Stop the process. The data directory is local; deleting the VM/container
removes the preview. Do not leave a public bind or tunnel in place.

## Current blocker

Away from the operator LAN, **no permitted remote preview exists**. LAN
mode is browser-emulation tested, not a physical-phone certification.
