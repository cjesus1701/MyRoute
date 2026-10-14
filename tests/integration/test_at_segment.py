import pytest

pytestmark = [pytest.mark.network, pytest.mark.slow]


@pytest.fixture
def at_gpx():
    import os
    path = "data/at_va_south.gpx"
    if not os.path.exists(path):
        pytest.skip("AT GPX fixture not available — run Milestone 0 data check first")
    return path


def test_at_segment_length(at_gpx):
    from shapely.geometry import Point

    from trailpager.route.loader import load_route
    from trailpager.route.measure import route_length_m
    from trailpager.route.trimmer import trim_route

    route = load_route(at_gpx)
    trimmed = trim_route(route.line, Point(-79.0891, 37.9123), Point(-78.8731, 38.0319))
    length_miles = route_length_m(trimmed, route.crs, utm_epsg=32617) / 1609.344
    # Spec estimate ~17 miles; allow ±3 for data variation
    assert 14 <= length_miles <= 20, f"Unexpected length: {length_miles:.1f} miles"
