#!/usr/bin/env python3
"""
Milestone 3 — Paginated PDF.

Runs the full pipeline: load → trim → paginate → render (overview +
detail pages) → assemble PDF.  This is the same pipeline as
`trailpager generate --config settings.example.toml`.

Run:  python3 scripts/milestone3_paginated_pdf.py
Output: output/at_reids_rockfish.pdf
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    config = PROJECT_ROOT / "settings.example.toml"
    result = subprocess.run(
        [sys.executable, "-m", "trailpager", "generate", "--config", str(config)],
        cwd=PROJECT_ROOT,
    )
    sys.exit(result.returncode)
