#!/usr/bin/env python3
"""Re-run Phase 3/4 on every cached raw-page set on the box, at $0.

Usage (from repo root):

    .venv/bin/python scripts/offline_replay_cached.py [output_dir] [cache_root ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scanner.mass_search.offline_replay import main

if __name__ == "__main__":
    raise SystemExit(main())
