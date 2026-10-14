from __future__ import annotations

import warnings
from dataclasses import dataclass

import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Point

from trailpager.config import Settings
from trailpager.route.measure import MileMarker, mile_marker_points, route_length_m
from trailpager.route.trimmer import snap_to_route, trim_route

_SNAP_WARN_M = 500.0


@dataclass
class ProcessedRoute:
    line_wgs84: LineString
    line_proj: LineString
    crs_proj: str
    length_m: float
    mile_markers: list[MileMarker]
    snap_start_offset_m: float
    snap_end_offset_m: float

    @property
    def length_miles(self) -> float:
        return self.length_m / 1609.344


def process_route(settings: Settings) -> ProcessedRoute:
    """Load → snap → trim → project → measure.  Returns a ProcessedRoute."""
    from trailpager.route.loader import load_route

    route_data = load_route(settings.route.file)

    # Settings store [lat, lon]; Point/shapely uses (lon=x, lat=y)
    start_lat, start_lon = settings.route.start
    end_lat, end_lon = settings.route.end
    start_pt = Point(start_lon, start_lat)
    end_pt   = Point(end_lon,   end_lat)

    # Snap offsets (approx metres — 1° ≈ 111 km)
    snapped_start, _ = snap_to_route(start_pt, route_data.line)
    snapped_end,   _ = snap_to_route(end_pt,   route_data.line)
    snap_start_m = snapped_start.distance(start_pt) * 111_000
    snap_end_m   = snapped_end.distance(end_pt)     * 111_000

    if snap_start_m > _SNAP_WARN_M:
        warnings.warn(
            f"Start point is {snap_start_m:.0f} m from the nearest route point. "
            "Check that the route file covers the requested start.",
            stacklevel=2,
        )
    if snap_end_m > _SNAP_WARN_M:
        warnings.warn(
            f"End point is {snap_end_m:.0f} m from the nearest route point. "
            "Check that the route file covers the requested end.",
            stacklevel=2,
        )

    trimmed = trim_route(route_data.line, start_pt, end_pt)

    crs_proj = f"EPSG:{settings.epsg}"
    t = Transformer.from_crs(route_data.crs, crs_proj, always_xy=True)
    line_proj = shapely.transform(trimmed, t.transform, interleaved=False)

    length_m = route_length_m(trimmed, route_data.crs, settings.epsg)
    markers  = mile_marker_points(trimmed, route_data.crs, settings.epsg)

    return ProcessedRoute(
        line_wgs84=trimmed,
        line_proj=line_proj,
        crs_proj=crs_proj,
        length_m=length_m,
        mile_markers=markers,
        snap_start_offset_m=snap_start_m,
        snap_end_offset_m=snap_end_m,
    )
