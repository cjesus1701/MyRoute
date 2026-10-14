#!/usr/bin/env python3
"""
Milestone 2 — Trim and measure.

Exercises the full load → snap → trim → project → measure pipeline
using settings.example.toml and the AT GeoJSON from Milestone 0.
Equivalent to running:  trailpager generate --config settings.example.toml

Run:  python3 scripts/milestone2_trim_and_measure.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from trailpager.config import load_settings
from trailpager.route.pipeline import process_route

CONFIG = PROJECT_ROOT / "settings.example.toml"


def main() -> None:
    print(f"Config: {CONFIG.name}")
    settings = load_settings(CONFIG)
    print(f"Route file: {settings.route.file}")
    print(f"Start:      {settings.route.start}  [lat, lon]")
    print(f"End:        {settings.route.end}  [lat, lon]")
    print(f"Scale:      1:{settings.map.scale:,}  ({settings.map.page_size} {settings.map.orientation})")

    print("\nProcessing route…")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = process_route(settings)

    for w in caught:
        print(f"  ⚠  {w.message}")

    start_lat, start_lon = settings.route.start
    end_lat,   end_lon   = settings.route.end

    print(f"\nSnapping endpoints:")
    _snap("Start", start_lat, start_lon, result.snap_start_offset_m)
    _snap("End  ", end_lat,   end_lon,   result.snap_end_offset_m)

    print(f"\nRoute measurements:")
    print(f"  Length:       {result.length_m:,.0f} m = {result.length_miles:.2f} miles")
    print(f"  Spec estimate: ~17.0 miles")
    diff = abs(result.length_miles - 17.0)
    print(f"  Difference:    {diff:.2f} miles  ({'within tolerance' if diff < 2 else 'CHECK NEEDED'})")
    print(f"  Vertices:      {len(result.line_wgs84.coords):,}")
    print(f"  Projected CRS: {result.crs_proj}")

    n = len(result.mile_markers)
    print(f"\nMile markers:  {n}  (mile 0 – {n - 1})")
    print("  Mile  UTM Easting    UTM Northing")
    for m in result.mile_markers:
        print(f"   {m.number:4.0f}  {m.point.x:>12,.0f}  {m.point.y:>12,.0f}")

    print(f"\nMilestone 2 status: {'PASSED' if diff < 2 else 'CHECK NEEDED'}")


def _snap(label: str, lat: float, lon: float, offset_m: float) -> None:
    flag = "  ⚠  >500 m — check coordinates" if offset_m > 500 else ""
    print(f"  {label}: ({lat:.4f}°N, {abs(lon):.4f}°W)  offset {offset_m:.0f} m{flag}")


if __name__ == "__main__":
    main()
