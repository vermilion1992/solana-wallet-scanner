#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Run ./setup.sh --skip-frontend first to create the local Python environment (or ./setup.sh to rebuild the interface)." >&2
  exit 1
fi
exec .venv/bin/python -m scanner "$@"
