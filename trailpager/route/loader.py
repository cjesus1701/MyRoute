from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from math import dist as euclidean_dist
from pathlib import Path

import geopandas as gpd
import gpxpy
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

_GPX_SEGMENT_GAP_WARN_M = 100.0
_M_TO_FT = 3.28084


@dataclass
class ElevPoint:
    distance_m: float
    elevation_ft: float


@dataclass
class RouteData:
    line: LineString
    crs: str
    source_name: str
    elevation_profile: list[ElevPoint] = field(default_factory=list)

    @property
    def total_distance_miles(self) -> float:
        if not self.elevation_profile:
            return 0.0
        return self.elevation_profile[-1].distance_m / 1609.344

    @property
    def gain_ft(self) -> float:
        pts = self.elevation_profile
        return sum(max(0.0, pts[i].elevation_ft - pts[i-1].elevation_ft) for i in range(1, len(pts)))

    @property
    def loss_ft(self) -> float:
        pts = self.elevation_profile
        return sum(max(0.0, pts[i-1].elevation_ft - pts[i].elevation_ft) for i in range(1, len(pts)))


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

    segments_2d: list[list[tuple[float, float]]] = []
    segments_z:  list[list[tuple[float, float, float | None]]] = []

    for track in gpx.tracks:
        for seg in track.segments:
            pts_2d = [(pt.longitude, pt.latitude) for pt in seg.points]
            pts_z  = [(pt.longitude, pt.latitude, pt.elevation) for pt in seg.points]
            if pts_2d:
                segments_2d.append(pts_2d)
                segments_z.append(pts_z)

    if not segments_2d:
        raise ValueError(f"No track segments found in {path}")

    _warn_on_segment_gaps(segments_2d)

    all_coords   = [c for seg in segments_2d for c in seg]
    all_coords_z = [c for seg in segments_z  for c in seg]

    elev_profile = _build_elevation_profile(all_coords_z)
    return RouteData(
        line=LineString(all_coords),
        crs="EPSG:4326",
        source_name=path.name,
        elevation_profile=elev_profile,
    )


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

    # Extract Z coordinates if present
    raw = list(merged.coords)
    coords_z: list[tuple[float, float, float | None]] = [
        (c[0], c[1], c[2] if len(c) > 2 else None) for c in raw
    ]
    elev_profile = _build_elevation_profile(coords_z)

    return RouteData(
        line=merged,
        crs=f"EPSG:{crs_epsg}",
        source_name=path.name,
        elevation_profile=elev_profile,
    )


def _build_elevation_profile(
    coords_z: list[tuple[float, float, float | None]],
) -> list[ElevPoint]:
    """Build an elevation profile from (lon, lat, elev_m|None) triples.

    Returns an empty list if no elevation data is present.
    Uses the haversine formula for per-segment distances so the profile
    is accurate regardless of the source CRS.
    """
    has_elev = any(c[2] is not None for c in coords_z)
    if not has_elev:
        return []

    profile: list[ElevPoint] = []
    cum_dist = 0.0

    for i, (lon, lat, elev_m) in enumerate(coords_z):
        if i > 0:
            lon0, lat0 = coords_z[i-1][0], coords_z[i-1][1]
            cum_dist += _haversine_m(lat0, lon0, lat, lon)
        elev_ft = (elev_m or 0.0) * _M_TO_FT
        profile.append(ElevPoint(distance_m=cum_dist, elevation_ft=elev_ft))

    return profile


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


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
