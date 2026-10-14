from __future__ import annotations

from pathlib import Path

import contextily as cx


def configure_cache(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cx.set_cache_dir(str(cache_dir))
