"""Tests for POI snap logic — no network calls."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from shapely.geometry import LineString

from trailpager.layers.pois import POI, fetch_pois


def _north_south_line():
    """Simple N-S line in UTM zone 17N."""
    return LineString([(700_000, 4_200_000), (700_000, 4_210_000)])


def _overpass_node(osm_id: int, lat: float, lon: float, tags: dict) -> dict:
    return {"type": "node", "id": osm_id, "lat": lat, "lon": lon, "tags": tags}


def _mock_response(elements: list[dict]):
    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"elements": elements}

    return _Resp()


# ── POI dataclass ────────────────────────────────────────────────────────────

def test_poi_icon_shelter():
    p = POI(name="X", lat=37.9, lon=-79.0, kind="shelter", distance_m=1000.0)
    assert p.icon == "▲"
    assert p.color == "#8B0000"


def test_poi_icon_spring():
    p = POI(name="X", lat=37.9, lon=-79.0, kind="spring", distance_m=1000.0)
    assert p.icon == "○"
    assert p.color == "#0D47A1"


def test_poi_gps_name_truncated():
    p = POI(name="Long Name Here", lat=37.9, lon=-79.0, kind="shelter", distance_m=8046.72)
    assert len(p.gps_name) <= 8


# ── fetch_pois — mocked Overpass ─────────────────────────────────────────────

def test_fetch_pois_filters_distant_nodes():
    """A node ~24 km west of the line should be dropped."""
    line = _north_south_line()
    # lon=-79.0 projects to UTM easting ~675_700 — 24 km from the line at 700_000
    elements = [_overpass_node(1, 37.97, -79.0, {"tourism": "wilderness_hut", "name": "Far Hut"})]

    with patch("trailpager.layers.pois.requests.post", return_value=_mock_response(elements)):
        pois = fetch_pois(line, "EPSG:32617", (-79.1, 37.9, -78.6, 38.1), max_dist_m=500.0)

    assert pois == []


def test_fetch_pois_keeps_near_nodes():
    """A node within 500 m of the line should be kept."""
    line = _north_south_line()
    # UTM (700_000, 4_205_000) → WGS84 lat≈37.971, lon≈-78.723  (on the line)
    elements = [_overpass_node(2, 37.971, -78.723, {"tourism": "wilderness_hut", "name": "Nearby Hut"})]

    with patch("trailpager.layers.pois.requests.post", return_value=_mock_response(elements)):
        pois = fetch_pois(line, "EPSG:32617", (-78.8, 37.9, -78.6, 38.1), max_dist_m=500.0)

    assert len(pois) == 1
    assert pois[0].name == "Nearby Hut"
    assert pois[0].kind == "shelter"


def test_fetch_pois_kind_classification():
    """All four Overpass tag combos map to the correct kind."""
    line = _north_south_line()
    # All nodes at lon≈-78.723 — on the line
    elements = [
        _overpass_node(1, 37.971, -78.723, {"tourism": "wilderness_hut"}),
        _overpass_node(2, 37.972, -78.723, {"amenity": "shelter"}),
        _overpass_node(3, 37.960, -78.724, {"natural": "spring"}),
        _overpass_node(4, 37.945, -78.724, {"amenity": "drinking_water"}),
    ]

    with patch("trailpager.layers.pois.requests.post", return_value=_mock_response(elements)):
        pois = fetch_pois(line, "EPSG:32617", (-78.8, 37.9, -78.6, 38.1), max_dist_m=500.0)

    kinds = {p.kind for p in pois}
    assert "shelter" in kinds
    assert "spring" in kinds
    assert "water" in kinds


def test_fetch_pois_auto_name():
    """Nodes without a name tag get an auto-generated name."""
    line = _north_south_line()
    elements = [_overpass_node(1, 37.971, -78.723, {"natural": "spring"})]

    with patch("trailpager.layers.pois.requests.post", return_value=_mock_response(elements)):
        pois = fetch_pois(line, "EPSG:32617", (-78.8, 37.9, -78.6, 38.1), max_dist_m=500.0)

    assert pois[0].name.startswith("Spring")


def test_fetch_pois_sorted_by_distance():
    """Multiple near nodes should come out sorted by distance_m."""
    line = _north_south_line()
    # Farther north = higher northing = higher distance along line
    elements = [
        _overpass_node(1, 37.990, -78.722, {"tourism": "wilderness_hut", "name": "North"}),
        _overpass_node(2, 37.935, -78.724, {"tourism": "wilderness_hut", "name": "South"}),
    ]

    with patch("trailpager.layers.pois.requests.post", return_value=_mock_response(elements)):
        pois = fetch_pois(line, "EPSG:32617", (-78.8, 37.9, -78.6, 38.1), max_dist_m=500.0)

    assert all(pois[i].distance_m <= pois[i + 1].distance_m for i in range(len(pois) - 1))


def test_fetch_pois_uses_cache(tmp_path):
    """Second call reads from cache and never hits the network."""
    line = _north_south_line()
    elements = [_overpass_node(1, 37.971, -78.723, {"natural": "spring", "name": "Cache Spring"})]
    bounds = (-78.8, 37.9, -78.6, 38.1)

    with patch("trailpager.layers.pois.requests.post", return_value=_mock_response(elements)) as mock_post:
        fetch_pois(line, "EPSG:32617", bounds, cache_dir=tmp_path)
        fetch_pois(line, "EPSG:32617", bounds, cache_dir=tmp_path)

    assert mock_post.call_count == 1  # second call read from cache


def test_fetch_pois_network_error_returns_empty():
    """A network failure should return [] with a warning, not raise."""
    line = _north_south_line()

    with patch("trailpager.layers.pois.requests.post", side_effect=OSError("no network")):
        import warnings
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            pois = fetch_pois(line, "EPSG:32617", (-78.8, 37.9, -78.6, 38.1))

    assert pois == []
    assert any("POI fetch failed" in str(w.message) for w in caught)
