from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from shapely.geometry import LineString

_SAMPLE_INTERVAL_M = 50.0  # densify line to at most this segment length before walking


@dataclass
class PageFrame:
    page_number: int
    bbox_proj: tuple[float, float, float, float]  # minx, miny, maxx, maxy in projected CRS
    route_start_dist: float  # meters from route start
    route_end_dist: float    # meters from route end


def paginate(
    line_proj: LineString,
    page_width_m: float,
    page_height_m: float,
    overlap_m: float,
    margin_m: float,
) -> list[PageFrame]:
    """Walk along a projected LineString and return ordered north-up page frames."""
    # Densify so that sparse lines (e.g. 2-point segments) get sufficient sample resolution
    dense = _densify(line_proj, _SAMPLE_INTERVAL_M)
    coords = np.array(dense.coords)
    cum_dists = _cumulative_distances(coords)
    total_length = cum_dists[-1]

    frames: list[PageFrame] = []
    page_num = 1
    current_start_dist = 0.0
    # minimum advance per page — prevents infinite loops on sharp bends
    min_advance = max(overlap_m * 0.1, _SAMPLE_INTERVAL_M)

    while current_start_dist < total_length:
        cx, cy = _interpolate_at_dist(coords, cum_dists, current_start_dist)

        # Place the route entry point near the left edge of the frame
        minx = cx - margin_m
        miny = cy - page_height_m / 2
        maxx = minx + page_width_m
        maxy = miny + page_height_m

        # Safe inner boundary — route must stay within this to count for the page
        safe_maxx = maxx - margin_m
        safe_miny = miny + margin_m
        safe_maxy = maxy - margin_m

        page_end_dist = current_start_dist
        for i in range(len(coords)):
            d = cum_dists[i]
            if d < current_start_dist:
                continue
            x, y = coords[i]
            if minx <= x <= safe_maxx and safe_miny <= y <= safe_maxy:
                page_end_dist = d
            elif d > current_start_dist:
                break

        page_end_dist = max(page_end_dist, current_start_dist + min_advance)
        page_end_dist = min(page_end_dist, total_length)

        frames.append(PageFrame(
            page_number=page_num,
            bbox_proj=(minx, miny, maxx, maxy),
            route_start_dist=current_start_dist,
            route_end_dist=page_end_dist,
        ))

        if page_end_dist >= total_length:
            break

        current_start_dist = max(current_start_dist + min_advance, page_end_dist - overlap_m)
        page_num += 1

    return frames


def _densify(line: LineString, max_segment_m: float) -> LineString:
    total = line.length
    if total == 0:
        return line
    n = max(int(np.ceil(total / max_segment_m)), 1)
    dists = np.linspace(0.0, total, n + 1)
    pts = [line.interpolate(d) for d in dists]
    return LineString([(p.x, p.y) for p in pts])


def _cumulative_distances(coords: np.ndarray) -> np.ndarray:
    diffs = np.diff(coords, axis=0)
    seg_lengths = np.hypot(diffs[:, 0], diffs[:, 1])
    return np.concatenate([[0.0], np.cumsum(seg_lengths)])


def _interpolate_at_dist(
    coords: np.ndarray,
    cum_dists: np.ndarray,
    dist: float,
) -> tuple[float, float]:
    dist = max(0.0, min(dist, cum_dists[-1]))
    idx = int(np.searchsorted(cum_dists, dist, side="right")) - 1
    idx = min(idx, len(coords) - 2)
    seg_len = cum_dists[idx + 1] - cum_dists[idx]
    if seg_len == 0:
        return float(coords[idx, 0]), float(coords[idx, 1])
    t = (dist - cum_dists[idx]) / seg_len
    x = coords[idx, 0] + t * (coords[idx + 1, 0] - coords[idx, 0])
    y = coords[idx, 1] + t * (coords[idx + 1, 1] - coords[idx, 1])
    return float(x), float(y)
