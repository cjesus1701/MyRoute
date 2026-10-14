"""Tests for elevation module — no network calls."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from shapely.geometry import LineString

from trailpager.layers.elevation import ElevationPoint, sample_route_elevation


def _simple_line():
    """10 km N-S line in UTM zone 17N."""
    return LineString([(700_000, 4_200_000), (700_000, 4_210_000)])


# ── ElevationPoint dataclass ─────────────────────────────────────────────────

def test_elevation_ft_conversion():
    ep = ElevationPoint(distance_m=0, lat=37.9, lon=-79.0, elevation_m=609.6)
    assert abs(ep.elevation_ft - 2000.0) < 0.5


# ── sample_route_elevation — mocked USGS ────────────────────────────────────

def _mock_epqs_response(elevation_m: float):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"value": str(elevation_m)}

    return _Resp()


def test_sample_returns_points():
    line = _simple_line()

    with patch(
        "trailpager.layers.elevation.requests.get",
        side_effect=lambda *a, **kw: _mock_epqs_response(700.0),
    ):
        points = sample_route_elevation(line, "EPSG:32617", length_m=10_000.0, interval_m=1000.0)

    assert len(points) == 11  # 0–10 000 at 1 000 m intervals = 11 points
    assert all(isinstance(p, ElevationPoint) for p in points)
    assert all(p.elevation_m == 700.0 for p in points)


def test_sample_sorted_by_distance():
    line = _simple_line()

    with patch(
        "trailpager.layers.elevation.requests.get",
        side_effect=lambda *a, **kw: _mock_epqs_response(500.0),
    ):
        points = sample_route_elevation(line, "EPSG:32617", length_m=5_000.0, interval_m=500.0)

    dists = [p.distance_m for p in points]
    assert dists == sorted(dists)


def test_sample_uses_cache(tmp_path):
    line = _simple_line()

    with patch(
        "trailpager.layers.elevation.requests.get",
        side_effect=lambda *a, **kw: _mock_epqs_response(650.0),
    ) as mock_get:
        sample_route_elevation(line, "EPSG:32617", length_m=5_000.0, interval_m=1000.0, cache_dir=tmp_path)
        sample_route_elevation(line, "EPSG:32617", length_m=5_000.0, interval_m=1000.0, cache_dir=tmp_path)

    assert mock_get.call_count == 6  # first call only (6 points: 0–5000 step 1000)


def test_sample_all_fail_returns_empty():
    line = _simple_line()

    with patch(
        "trailpager.layers.elevation.requests.get",
        side_effect=OSError("no network"),
    ):
        import warnings
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            points = sample_route_elevation(line, "EPSG:32617", length_m=3_000.0, interval_m=1000.0)

    assert points == []
    assert any("elevation" in str(w.message).lower() for w in caught)
