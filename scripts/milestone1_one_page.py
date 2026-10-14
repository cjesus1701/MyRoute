#!/usr/bin/env python3
"""
Milestone 1 — One page.

Draws the full Reeds Gap → Rockfish Gap AT section on a single letter-
landscape page with USGS topo basemap, USFS/NPS boundary lines, mile
markers, scale bar, and north arrow.

Run:  python3 scripts/milestone1_one_page.py
Output: output/milestone1_overview.pdf
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import geopandas as gpd
import shapely
from pyproj import Transformer
from shapely.geometry import MultiLineString, Point
from shapely.ops import linemerge

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from trailpager.config import Settings
from trailpager.layers.boundaries import fetch_nps_boundary, fetch_usfs_boundary
from trailpager.pdf import assemble_pdf
from trailpager.render.overview import render_overview_page
from trailpager.route.measure import mile_marker_points
from trailpager.route.trimmer import trim_route

REEDS_GAP    = Point(-78.9852, 37.9013)   # SR-664 AT crossing
ROCKFISH_GAP = Point(-78.8731, 38.0319)   # I-64 / US-250

DATA_DIR   = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
CACHE_DIR  = PROJECT_ROOT / ".tile_cache"

# Bounding box for boundary queries: (west, south, east, north) WGS-84
BOUNDARY_BBOX = (-79.05, 37.85, -78.80, 38.10)

_SETTINGS = Settings(
    route={"file": str(DATA_DIR / "at_va_south.geojson"),
           "start": [37.9013, -78.9852], "end": [38.0319, -78.8731]},
    map={"scale": 75000, "page_size": "letter", "orientation": "landscape",
         "overlap_m": 500, "margin_m": 200},
    layers={"topo_basemap": True, "usfs_boundary": True, "nps_boundary": True,
            "mile_markers": True, "utm_grid": False},
    output={"path": str(OUTPUT_DIR / "milestone1_overview.pdf")},
)


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_and_trim_route():
    gdf = gpd.read_file(DATA_DIR / "at_va_south.geojson")
    merged = linemerge(list(gdf.geometry))
    if isinstance(merged, MultiLineString):
        merged = sorted(merged.geoms, key=lambda g: g.length, reverse=True)[0]
    trimmed = trim_route(merged, REEDS_GAP, ROCKFISH_GAP)
    return trimmed


def _project_to_utm(line):
    t = Transformer.from_crs("EPSG:4326", "EPSG:32617", always_xy=True)
    return shapely.transform(line, t.transform, interleaved=False)


def _fetch_boundary(fetcher, name: str):
    CACHE_DIR.mkdir(exist_ok=True)
    try:
        gdf = fetcher(BOUNDARY_BBOX, CACHE_DIR)
        print(f"  {name}: {len(gdf)} feature(s)")
        return gdf
    except Exception as exc:
        warnings.warn(f"{name} boundary unavailable: {exc}")
        print(f"  {name}: unavailable ({type(exc).__name__})")
        return gpd.GeoDataFrame()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("Loading and trimming route…")
    route_wgs84 = _load_and_trim_route()
    route_utm   = _project_to_utm(route_wgs84)
    length_mi   = route_utm.length / 1609.344
    print(f"  Route: {route_utm.length:,.0f} m = {length_mi:.2f} miles")

    print("Computing mile markers…")
    markers = mile_marker_points(route_wgs84, "EPSG:4326", utm_epsg=32617)
    print(f"  {len(markers)} markers (mile 0 – {len(markers) - 1})")

    print("Fetching boundary data…")
    usfs = _fetch_boundary(fetch_usfs_boundary, "USFS (George Washington NF)")
    nps  = _fetch_boundary(fetch_nps_boundary,  "NPS (Shenandoah NP)")

    print("Rendering overview page…")
    fig = render_overview_page(
        route_utm,
        page_frames=[],          # no paginated frames yet — Milestone 3
        settings=_SETTINGS,
        cache_dir=CACHE_DIR,
        mile_markers=markers,
        boundaries=[usfs, nps],
        boundary_colors=["#2ca02c", "#1f77b4"],
        boundary_labels=["George Washington NF", "Shenandoah NP"],
    )

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / "milestone1_overview.pdf"
    assemble_pdf([fig], output_path)
    print(f"Saved → {output_path.relative_to(PROJECT_ROOT)}")
    print("Milestone 1 complete — open the PDF and compare against PATC Map 12.")


if __name__ == "__main__":
    main()
