import json
import warnings
from pathlib import Path

import pytest

from trailpager.config import Settings


def _write_straight_geojson(path: Path, n_pts: int = 50) -> None:
    """Write a ~10.5 km E-W LineString in WGS-84 to path.

    Lon span 0.12° at lat 37.95°N: 0.12 × 111 × cos(37.95°) ≈ 10.5 km.
    """
    coords = [(-79.0 + i * 0.12 / (n_pts - 1), 37.95) for i in range(n_pts)]
    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {},
        }],
    }
    path.write_text(json.dumps(geojson))


def _settings(route_file: Path) -> Settings:
    return Settings(
        route={
            "file": str(route_file),
            "start": [37.95, -79.0],    # [lat, lon] — west end
            "end":   [37.95, -78.88],   # east end  (~10.5 km)
        },
        map={"scale": 24000, "page_size": "letter", "orientation": "landscape",
             "overlap_m": 500, "margin_m": 200},
        layers={"topo_basemap": False},
        output={"path": "output/test.pdf"},
    )


def test_process_route_length(tmp_path):
    from trailpager.route.pipeline import process_route

    f = tmp_path / "straight.geojson"
    _write_straight_geojson(f)
    result = process_route(_settings(f))
    # 0.12° lon at lat 37.95°N ≈ 10.5 km; allow ±1 km for projection
    assert 9_000 < result.length_m < 12_000
    assert 5.5 < result.length_miles < 7.5


def test_process_route_mile_markers(tmp_path):
    from trailpager.route.pipeline import process_route

    f = tmp_path / "straight.geojson"
    _write_straight_geojson(f)
    result = process_route(_settings(f))
    # ~10.5 km ≈ 6.5 miles → markers at 0, 1, …, 6 = at least 6
    assert len(result.mile_markers) >= 6
    assert result.mile_markers[0].number == 0.0


def test_process_route_snap_on_line(tmp_path):
    from trailpager.route.pipeline import process_route

    f = tmp_path / "straight.geojson"
    _write_straight_geojson(f)
    result = process_route(_settings(f))
    # start/end are exactly on the line → small snap offsets
    assert result.snap_start_offset_m < 100
    assert result.snap_end_offset_m < 100


def test_process_route_line_proj_is_utm(tmp_path):
    from trailpager.route.pipeline import process_route

    f = tmp_path / "straight.geojson"
    _write_straight_geojson(f)
    result = process_route(_settings(f))
    # UTM Zone 17N eastings are in range ~600 000 – 800 000
    x = result.line_proj.coords[0][0]
    assert 600_000 < x < 800_000
    assert result.crs_proj == "EPSG:32617"


def test_loader_warns_on_multi_segment(tmp_path):
    """GeoJSON with a gap produces a warning, not an exception."""
    import geopandas as gpd
    from shapely.geometry import LineString

    from trailpager.route.loader import load_route

    # Two disconnected segments
    gdf = gpd.GeoDataFrame(
        geometry=[
            LineString([(-79.0, 37.9), (-78.95, 37.9)]),
            LineString([(-78.90, 38.0), (-78.85, 38.0)]),  # ~10 km gap
        ],
        crs="EPSG:4326",
    )
    f = tmp_path / "gap.geojson"
    gdf.to_file(f, driver="GeoJSON")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = load_route(f)

    assert any("disconnected" in str(w.message) for w in caught)
    # Returns the longest segment as a single LineString
    from shapely.geometry import LineString as LS
    assert isinstance(result.line, LS)
