#!/usr/bin/env python3
"""Thin wrapper: python scripts/hot_topics_probe.py → src.hot_topics_probe."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.hot_topics_probe import main

if __name__ == "__main__":
    raise SystemExit(main())
