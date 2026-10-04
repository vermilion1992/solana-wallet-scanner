#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

build_frontend=1
if [[ "${1:-}" == "--skip-frontend" ]]; then
  build_frontend=0
  shift
fi
if [[ $# -ne 0 ]]; then
  echo "Usage: ./setup.sh [--skip-frontend]" >&2
  exit 2
fi

python_bin="${SCANNER_PYTHON:-python3}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "Python 3.11 or later is required. Set SCANNER_PYTHON to its executable if needed." >&2
  exit 1
fi
"$python_bin" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else "Python 3.11 or later is required.")'
"$python_bin" -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check --require-hashes -r requirements.txt
.venv/bin/python -m pip install --disable-pip-version-check --no-deps --no-build-isolation -e .
.venv/bin/python -m pip check

if [[ "$build_frontend" == 1 ]]; then
  if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
    echo "Node.js 22.12 or later and npm are required to build the interface. Install Node, then run setup again." >&2
    exit 1
  fi
  node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || (major === 22 && minor < 12)) { console.error("Node.js 22.12 or later is required."); process.exit(1); }'
  (
    cd frontend
    npm ci --no-audit --no-fund
    npm run build
  )
fi

echo "Setup complete. Start the scanner with ./run.sh"
