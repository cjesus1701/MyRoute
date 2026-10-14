from __future__ import annotations

from dataclasses import dataclass

import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Point

_METERS_PER_MILE = 1609.344


@dataclass
class MileMarker:
    number: float
    point: Point
    distance_m: float


def _project_line(line: LineString, from_crs: str, to_epsg: int) -> LineString:
    transformer = Transformer.from_crs(from_crs, f"EPSG:{to_epsg}", always_xy=True)
    return shapely.transform(line, transformer.transform, interleaved=False)


def route_length_m(line: LineString, crs: str, utm_epsg: int) -> float:
    return _project_line(line, crs, utm_epsg).length


def mile_marker_points(
    line: LineString,
    crs: str,
    utm_epsg: int,
    interval_m: float = _METERS_PER_MILE,
) -> list[MileMarker]:
    projected = _project_line(line, crs, utm_epsg)
    total = projected.length

    markers: list[MileMarker] = []
    dist = 0.0
    number = 0.0

    while dist <= total:
        clamped = max(0.0, min(dist, total))
        pt = projected.interpolate(clamped)
        markers.append(MileMarker(number=number, point=pt, distance_m=clamped))
        dist += interval_m
        number += interval_m / _METERS_PER_MILE

    return markers
