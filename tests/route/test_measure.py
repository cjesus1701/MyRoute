import shapely
from pyproj import Transformer
from shapely.geometry import LineString

from trailpager.route.measure import mile_marker_points, route_length_m

UTM17N = 32617


def _wgs84_from_utm(line_utm: LineString) -> LineString:
    t = Transformer.from_crs("EPSG:32617", "EPSG:4326", always_xy=True)
    return shapely.transform(line_utm, t.transform, interleaved=False)


def test_route_length_known_segment():
    line_wgs84 = _wgs84_from_utm(LineString([(700_000, 4_200_000), (710_000, 4_200_000)]))
    length = route_length_m(line_wgs84, "EPSG:4326", UTM17N)
    assert abs(length - 10_000) < 5


def test_mile_marker_count():
    # 17 000 m > 10 miles (16 093.44 m) → markers at 0, 1, …, 10 = 11 total
    line_wgs84 = _wgs84_from_utm(LineString([(700_000, 4_200_000), (717_000, 4_200_000)]))
    markers = mile_marker_points(line_wgs84, "EPSG:4326", UTM17N)
    assert len(markers) == 11
