# Dependency maintenance for the review revision

Verified on 2 October 2026 with Python 3.12.14 and Node.js 24.19.0 on Linux. These checks use the installed versions shipped by the revised lockfiles; they do not recertify live-chain accounting or wallet profitability.

## v0.3.2 delivery recheck

On 2 October 2026, both current registry audits again returned zero known findings: all **38 Python package/version pairs**, including the conditional platform branches, and the full npm lock assessment of **52 dependencies**. The Python lock is byte-identical to v0.3.1. Comparing the npm lock with the preserved v0.3.1 release archive found only the two project-version fields changed to 0.3.2; the dependency graph and integrity digests are unchanged. These checks retain the shipped pins rather than using the independent reviewer's different environment.

The actual `./setup.sh --skip-frontend` flow passed in a fresh isolated Linux source clone, including the hash-enforced dependency install, local editable installation and `pip check`. `./run.sh --version` and `--help` passed. Starting `run.sh` with a fresh data directory served the compiled interface on loopback, rejected unauthenticated API access, established a local session and returned version 0.3.2 with no configured key, jobs or provider credit use; shutdown completed normally. R5 source work continued during this installation check. Final application tests, rebuilt interface and browser checks are recorded separately in [VALIDATION.md](VALIDATION.md).

The new machine-readable record is [delivery_review_2026-10-02.json](capability/delivery_review_2026-10-02.json). The historical v0.3.1 audit record below remains unchanged. Windows/macOS and Python 3.11 were included in advisory coverage through their locked package pairs but were not run; registry audits remain checks of known advisories, not a security certification.

## Patched versions

| Component | Previous version | Revised version | Reason |
| --- | --- | --- | --- |
| FastAPI | 0.115.12 | 0.142.2 | Use current stable metadata compatible with patched Starlette. |
| Starlette | 0.46.2 in the former environment | 1.7.0, explicitly pinned | Outside the affected `>=0.39.0,<=0.49.0` range for GHSA-7f5h-v6xp-fcq8; first patch was 0.49.1. FastAPI 0.142.2 permits `starlette>=0.46.0`; this is a compatible pair, without overriding an old upper bound. |
| Vite | 6.0.7 | 8.3.2 | Current stable toolchain outside GHSA-vg6x-rcgg-rjx6's affected ranges. The normal launcher serves rebuilt static assets, while development still binds to loopback. |
| React Vite plugin | 4.3.4 | 6.1.1 | Official peer metadata supports Vite 8. Its optional compiler integrations are not enabled. |
| pytest | 8.3.5 | 9.1.1 | Broad audit also identified GHSA-6w46-j5rx-g56g, fixed in 9.0.3. |
| setuptools | 80.9.0 | 84.0.0 | Broad audit also identified GHSA-h35f-9h28-mq5c, fixed in 83.0.0. The local editable build uses the locked tool rather than fetching an isolated unlocked build environment. |

Python 3.11+ remains the application minimum. Rebuilding the frontend now requires **Node.js 22.12+**; the setup scripts and package engine field enforce the supported Vite minimum. Node is optional when using the compiled interface in the source ZIP. Windows and macOS dependency branches are retained in the lock, but those operating systems have not been executed in this validation.

HTTPX 0.28.1, Uvicorn 0.34.2, keyring 25.6.0, React 18.3.1 and TypeScript 5.7.3 remain pinned. Starlette's test client still works with HTTPX, but emits an upstream deprecation warning recommending HTTPX2. The application uses HTTPX for provider requests; its runtime behavior is unchanged by this warning.

## Reproducible installation

[requirements.txt](../requirements.txt) contains **38 exact package pins with SHA-256 distribution hashes**, including the complete runtime, test and local build dependency closure. Its conditional markers retain Windows `pywin32-ctypes`/`colorama`, Linux SecretStorage/Jeepney/cryptography and Python 3.11 compatibility packages. The hashes include available platform distributions rather than locking a Linux-only wheel. The compiler used was uv 0.12.19 with universal resolution against Python 3.11; users do not need uv to install.

Setup installs that file with `pip --require-hashes`, then installs this local project with `--no-deps --no-build-isolation` and runs `pip check`. The Python executable and pip bundled by `venv` are prerequisites rather than third-party application dependencies. The local project source is covered by the release archive hash, not a registry package hash.

To intentionally refresh the lock after reviewing dependency changes:

```sh
uv pip compile pyproject.toml requirements-build.in --extra dev --universal --python-version 3.11 --generate-hashes --no-emit-index-url --output-file requirements.txt --upgrade
```

[frontend/package-lock.json](../frontend/package-lock.json) locks the complete npm graph and integrity digests, including optional platform packages. Installation uses `npm ci`. Its current direct dependency versions are declared in [frontend/package.json](../frontend/package.json).

## Verification and limits

- Fresh isolated Python environment installed the hashed closure and local editable package successfully; `pip check` passed in both the isolated environment and application `.venv`.
- Patched runtime and pytest 9.1.1 passed 64 launcher, restore, API and local-edge tests. The upstream HTTPX test-client deprecation was the only warning. Full application tests are recorded separately in [VALIDATION.md](VALIDATION.md).
- `npm ci`, TypeScript compilation and Vite 8.3.2 production build passed. The dependency check ran 16 formatting and 65 discovery assertions before the concurrent feature revision; the final source build/checks are recorded in VALIDATION.md.
- `npm audit --json` reported zero known findings across its lockfile assessment (52 dependencies including platform variants).
- pip-audit 2.10.1 reported zero known findings after patching. In addition to the Linux-marker assessment, every one of the 38 locked package/version pairs was submitted without platform markers, covering otherwise skipped Windows/Python 3.11 pins. No extra packages were installed for that all-platform advisory query.
- Neither advisory's denial-of-service exploit was executed. These are dependency metadata/advisory checks, not a security certification. Advisory databases change; rerun audits when maintaining the release.
- No Helius credential, paid service, or live-chain call was used for dependency maintenance.

The concise machine-readable record is [dependency_review_2026-10-02.json](capability/dependency_review_2026-10-02.json).

## Primary sources

- [FastAPI 0.142.2 official package metadata](https://pypi.org/pypi/fastapi/0.142.2/json)
- [Starlette 1.7.0 official package metadata](https://pypi.org/pypi/starlette/1.7.0/json)
- [Starlette Range-header advisory](https://github.com/Kludex/starlette/security/advisories/GHSA-7f5h-v6xp-fcq8)
- [Vite development-server advisory](https://github.com/vitejs/vite/security/advisories/GHSA-vg6x-rcgg-rjx6)
- [Vite 8.3.2 official registry metadata](https://registry.npmjs.org/vite/8.3.2)
- [React Vite plugin 6.1.1 official registry metadata](https://registry.npmjs.org/@vitejs%2Fplugin-react/6.1.1)
- [pytest local temporary-directory advisory](https://github.com/advisories/GHSA-6w46-j5rx-g56g)
- [setuptools source-manifest advisory](https://github.com/advisories/GHSA-h35f-9h28-mq5c)
