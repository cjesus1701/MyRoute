from __future__ import annotations

import warnings
from dataclasses import dataclass
from math import dist as euclidean_dist
from pathlib import Path

import geopandas as gpd
import gpxpy
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

_GPX_SEGMENT_GAP_WARN_M = 100.0


@dataclass
class RouteData:
    line: LineString
    crs: str
    source_name: str


def load_route(path: Path | str) -> RouteData:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".gpx":
        return _load_gpx(path)
    if suffix in {".geojson", ".json"}:
        return _load_geojson(path)
    raise ValueError(f"Unsupported file type: {suffix!r}. Expected .gpx or .geojson")


def _load_gpx(path: Path) -> RouteData:
    with open(path) as f:
        gpx = gpxpy.parse(f)

    segments: list[list[tuple[float, float]]] = []
    for track in gpx.tracks:
        for seg in track.segments:
            coords = [(pt.longitude, pt.latitude) for pt in seg.points]
            if coords:
                segments.append(coords)

    if not segments:
        raise ValueError(f"No track segments found in {path}")

    _warn_on_segment_gaps(segments)

    all_coords = [coord for seg in segments for coord in seg]
    return RouteData(line=LineString(all_coords), crs="EPSG:4326", source_name=path.name)


def _load_geojson(path: Path) -> RouteData:
    gdf = gpd.read_file(path)
    lines = gdf[gdf.geometry.geom_type.isin(["LineString", "MultiLineString"])].geometry

    if lines.empty:
        raise ValueError(f"No LineString or MultiLineString features found in {path}")

    merged = linemerge(list(lines))
    if isinstance(merged, MultiLineString):
        geoms = sorted(merged.geoms, key=lambda g: g.length, reverse=True)
        total = sum(g.length for g in geoms)
        dominant_pct = geoms[0].length / total * 100
        warnings.warn(
            f"{path.name}: {len(geoms)} disconnected segments after merge; "
            f"using the longest ({dominant_pct:.0f}% of total length). "
            "Trim or repair the source file to suppress this warning.",
            stacklevel=4,
        )
        merged = geoms[0]

    crs_epsg = gdf.crs.to_epsg() if gdf.crs else 4326
    return RouteData(line=merged, crs=f"EPSG:{crs_epsg}", source_name=path.name)


def _warn_on_segment_gaps(segments: list[list[tuple[float, float]]]) -> None:
    for i in range(len(segments) - 1):
        end = segments[i][-1]
        start = segments[i + 1][0]
        # rough check: 1 degree ≈ 111 km
        approx_m = euclidean_dist(end, start) * 111_000
        if approx_m > _GPX_SEGMENT_GAP_WARN_M:
            warnings.warn(
                f"GPX segment gap between segment {i} and {i + 1} is ~{approx_m:.0f} m. "
                "Segments are joined but the route may contain a jump.",
                stacklevel=4,
            )
