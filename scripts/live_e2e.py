#!/usr/bin/env python3
"""Box-executable LIVE E2E runner. See scanner.mass_search.live_e2e."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.mass_search.live_e2e import main


if __name__ == "__main__":
    raise SystemExit(main())
