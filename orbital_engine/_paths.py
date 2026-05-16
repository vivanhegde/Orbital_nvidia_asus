"""Ensure ``orbital_data`` is importable when running from the repo layout."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_orbital_data_on_path() -> None:
    """Prepend ``<repo>/orbital_data`` to ``sys.path`` if that directory exists."""
    root = Path(__file__).resolve().parent.parent
    od = root / "orbital_data"
    if od.is_dir():
        s = str(od)
        if s not in sys.path:
            sys.path.insert(0, s)
