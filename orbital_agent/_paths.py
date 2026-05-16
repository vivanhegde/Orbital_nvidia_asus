"""Make repo packages importable when running ``python -m orbital_agent.*``.

`orbital_data.store` does `from fetchers import ...` and `from models import ...`,
which requires `orbital_data/` itself on sys.path (not just the repo root).
This helper adds both. Idempotent — safe to call multiple times.
"""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_repo_on_path() -> None:
    root = Path(__file__).resolve().parent.parent
    candidates = (root / "orbital_data", root)
    for p in candidates:
        if p.is_dir():
            s = str(p)
            if s not in sys.path:
                sys.path.insert(0, s)
