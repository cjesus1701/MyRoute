from __future__ import annotations

from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, substring


def snap_to_route(point: Point, line: LineString) -> tuple[Point, float]:
    snapped, _ = nearest_points(line, point)
    distance = line.project(snapped)
    return snapped, distance


def trim_route(line: LineString, start_point: Point, end_point: Point) -> LineString:
    _, start_dist = snap_to_route(start_point, line)
    _, end_dist = snap_to_route(end_point, line)

    if start_dist > end_dist:
        start_dist, end_dist = end_dist, start_dist

    # Guard against floating-point edge cases at exact endpoints
    start_dist = max(0.0, start_dist)
    end_dist = min(end_dist, line.length)

    trimmed = substring(line, start_dist, end_dist)
    if not isinstance(trimmed, LineString):
        raise ValueError(
            "Trimmed route is not a LineString — start and end may be the same point."
        )
    return trimmed
