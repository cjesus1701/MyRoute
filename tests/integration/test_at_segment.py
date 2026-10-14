import pytest

pytestmark = [pytest.mark.network, pytest.mark.slow]


@pytest.fixture
def at_geojson(tmp_path):
    import os
    path = "data/at_va_south.geojson"
    if not os.path.exists(path):
        pytest.skip("AT GeoJSON not found — run scripts/milestone0_data_check.py first")
    return path


def test_at_segment_length(at_geojson):
    """Trimmed Reeds Gap → Rockfish Gap section should be ~17 miles."""
    from shapely.geometry import Point

    from trailpager.route.loader import load_route
    from trailpager.route.measure import route_length_m
    from trailpager.route.trimmer import trim_route

    route = load_route(at_geojson)
    # Corrected Reeds Gap: SR-664 AT crossing; Rockfish Gap: I-64
    trimmed = trim_route(
        route.line,
        Point(-78.9852, 37.9013),
        Point(-78.8731, 38.0319),
    )
    length_miles = route_length_m(trimmed, route.crs, utm_epsg=32617) / 1609.344
    assert 15 <= length_miles <= 21, f"Unexpected length: {length_miles:.1f} miles"


def test_at_process_route_via_pipeline(at_geojson):
    """process_route() with settings.example.toml produces the expected length."""
    from trailpager.config import Settings
    from trailpager.route.pipeline import process_route

    settings = Settings(
        route={
            "file": at_geojson,
            "start": [37.9013, -78.9852],
            "end":   [38.0319, -78.8731],
        },
        map={"scale": 24000, "page_size": "letter", "orientation": "landscape",
             "overlap_m": 500, "margin_m": 200},
        layers={"topo_basemap": False},
        output={"path": "output/test.pdf"},
    )
    result = process_route(settings)
    assert 15 <= result.length_miles <= 21
    assert result.snap_start_offset_m < 100  # start is on the AT
    assert len(result.mile_markers) >= 15
