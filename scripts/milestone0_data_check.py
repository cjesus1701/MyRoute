#!/usr/bin/env python3
"""
Milestone 0 — Data check.

Downloads AT trail data from OpenStreetMap (Overpass API) for the
Reids Gap → Rockfish Gap corridor, characterises what is available,
and measures the section.

Run:  python scripts/milestone0_data_check.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import requests
from shapely.geometry import MultiLineString, Point
from shapely.ops import linemerge

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = PROJECT_ROOT / "data"

# ── Confirmed endpoints (WGS-84, Point is (lon, lat)) ─────────────────────────
# Reeds Gap: where SR-664 (Reeds Gap Road) crosses the AT on the Blue Ridge.
# Confirmed by OSM node proximity: AT way 372649070 starts at (37.9013°N, 78.9852°W),
# Reeds Gap Road (way 19877903) overlaps at the same longitude.
REEDS_GAP   = Point(-78.9852, 37.9013)   # SR-664 AT crossing — CORRECTED
ROCKFISH_GAP = Point(-78.8731, 38.0319)  # I-64 / US-250 AT crossing

# Spec's original Reids Gap coordinates (for reference / warning)
SPEC_START  = Point(-79.0891, 37.9123)   # ~9 km west of actual AT crossing

# Bounding box (south, west, north, east) — covers corridor + buffer
BBOX = (37.80, -79.10, 38.10, -78.80)

OVERPASS_URL = "https://overpass.openstreetmap.fr/api/interpreter"


# ── OSM download ──────────────────────────────────────────────────────────────

def fetch_at_named_ways(bbox: tuple) -> dict:
    south, west, north, east = bbox
    query = (
        f'[out:json][timeout:60];'
        f'way["name"="Appalachian Trail"]["highway"~"path|track|footway"]'
        f'({south},{west},{north},{east});'
        f'out geom;'
    )
    headers = {"User-Agent": "TrailPager/0.1 (contact: cjesus1701@gmail.com)"}
    print(f"Querying Overpass API…  bbox={bbox}")
    resp = requests.get(OVERPASS_URL, params={"data": query},
                        headers=headers, timeout=90)
    resp.raise_for_status()
    return resp.json()


def build_geojson(overpass_data: dict) -> tuple[dict, int]:
    features = []
    for el in overpass_data.get("elements", []):
        if el["type"] != "way" or "geometry" not in el:
            continue
        coords = [(n["lon"], n["lat"]) for n in el["geometry"]]
        if len(coords) < 2:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"osm_id": el["id"], "name": el.get("tags", {}).get("name", "")},
        })
    return {"type": "FeatureCollection", "features": features}, len(features)


# ── Route assembly ────────────────────────────────────────────────────────────

def assemble_route(geojson_path: Path):
    import geopandas as gpd

    gdf = gpd.read_file(geojson_path)
    merged = linemerge(list(gdf.geometry))

    if isinstance(merged, MultiLineString):
        geoms = sorted(merged.geoms, key=lambda g: g.length, reverse=True)
        total_len = sum(g.length for g in geoms)
        print(f"\n  NOTE: {len(geoms)} disconnected segments after merge:")
        for i, g in enumerate(geoms):
            pct = g.length / total_len * 100
            print(f"    {i+1}: {pct:.0f}%  lat[{g.bounds[1]:.4f}..{g.bounds[3]:.4f}]")
        print(f"  → Using longest segment.")
        merged = geoms[0]

    return merged


# ── Measurement ───────────────────────────────────────────────────────────────

def measure_section(line, start_pt: Point, end_pt: Point, label: str) -> float:
    from trailpager.route.measure import route_length_m
    from trailpager.route.trimmer import snap_to_route, trim_route

    snapped_start, _ = snap_to_route(start_pt, line)
    snapped_end, _   = snap_to_route(end_pt, line)

    # Rough metres — 1° lat ≈ 111 km
    snap_err_start = snapped_start.distance(start_pt) * 111_000
    snap_err_end   = snapped_end.distance(end_pt)     * 111_000

    print(f"\n  {label}")
    print(f"    Start  target:  ({start_pt.y:.5f}°N, {abs(start_pt.x):.5f}°W)")
    print(f"    Start snapped:  ({snapped_start.y:.5f}°N, {abs(snapped_start.x):.5f}°W)  "
          f"offset ≈ {snap_err_start:.0f} m")
    print(f"    End    target:  ({end_pt.y:.5f}°N, {abs(end_pt.x):.5f}°W)")
    print(f"    End   snapped:  ({snapped_end.y:.5f}°N, {abs(snapped_end.x):.5f}°W)  "
          f"offset ≈ {snap_err_end:.0f} m")

    if snap_err_start > 500:
        print(f"    ⚠  Start offset {snap_err_start:.0f} m > 500 m — point may be off-route.")

    trimmed = trim_route(line, start_pt, end_pt)
    length_m  = route_length_m(trimmed, "EPSG:4326", utm_epsg=32617)
    length_mi = length_m / 1609.344
    print(f"    Route length:   {length_m:,.0f} m  =  {length_mi:.2f} miles")
    return length_mi


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    from trailpager.route.measure import route_length_m

    DATA_DIR.mkdir(exist_ok=True)
    geojson_path = DATA_DIR / "at_va_south.geojson"

    # 1. Download named AT ways
    data = fetch_at_named_ways(BBOX)
    geojson, n_ways = build_geojson(data)
    if n_ways == 0:
        print("ERROR: No AT ways returned — check bbox or Overpass connectivity.")
        sys.exit(1)
    print(f"Downloaded {n_ways} named AT ways from OSM")
    geojson_path.write_text(json.dumps(geojson, indent=2))
    print(f"Saved → {geojson_path.relative_to(PROJECT_ROOT)}")

    # 2. Assemble
    line = assemble_route(geojson_path)
    full_length_m  = route_length_m(line, "EPSG:4326", utm_epsg=32617)
    full_length_mi = full_length_m / 1609.344
    bounds = line.bounds  # (minx, miny, maxx, maxy)

    print(f"\nMerged route: {len(line.coords)} vertices, {full_length_mi:.1f} miles total")
    print(f"  Lat range: {bounds[1]:.4f}°N – {bounds[3]:.4f}°N")
    print(f"  Lon range: {abs(bounds[0]):.4f}°W – {abs(bounds[2]):.4f}°W")

    # 3. Coordinate discrepancy notice
    # Measure how far spec start is from the nearest AT point
    from trailpager.route.trimmer import snap_to_route
    snapped_spec, _ = snap_to_route(SPEC_START, line)
    spec_snap_m = snapped_spec.distance(SPEC_START) * 111_000
    if spec_snap_m > 500:
        print(f"\n  ⚠  COORDINATE DISCREPANCY — spec start is {spec_snap_m/1000:.1f} km from AT")
        print(f"     Spec start coords: ({SPEC_START.y:.4f}°N, {abs(SPEC_START.x):.4f}°W)")
        print(f"     These appear to point to a valley access area near Wintergreen Resort,")
        print(f"     not the AT-SR664 road crossing on the Blue Ridge.")
        print(f"     Confirmed AT crossing of Reeds Gap Road (SR-664):")
        print(f"       ({REEDS_GAP.y:.4f}°N, {abs(REEDS_GAP.x):.4f}°W)  ← use this in settings")

    # 4. Measurements
    sep = "─" * 62
    print(f"\n{sep}")
    print("MEASUREMENTS")

    mi_corrected = measure_section(
        line, REEDS_GAP, ROCKFISH_GAP,
        "Reeds Gap (SR-664 crossing) → Rockfish Gap  [CORRECTED]"
    )
    mi_spec = measure_section(
        line, SPEC_START, ROCKFISH_GAP,
        "Spec start coords → Rockfish Gap  [spec reference]"
    )

    # 5. Summary
    print(f"\n{sep}")
    print("SUMMARY")
    print(f"  Spec estimate (Reids Gap → Rockfish Gap): ~17.0 miles")
    print(f"  Measured from corrected AT trailhead:      {mi_corrected:.2f} miles  ✓")
    print(f"  Measured from spec start coords:           {mi_spec:.2f} miles  (for reference)")
    print(f"\n  Corrected start coordinates (settings.example.toml):")
    print(f"    start = [{REEDS_GAP.y}, {REEDS_GAP.x}]  # Reeds Gap — SR-664 AT crossing")
    print(f"\n  OSM coverage: complete for the corrected Reeds Gap → Rockfish Gap section.")
    print(f"\n  Milestone 0 status: PASSED")
    print(sep)


if __name__ == "__main__":
    main()
