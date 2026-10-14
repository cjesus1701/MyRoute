from shapely.geometry import LineString, Point

from trailpager.route.trimmer import snap_to_route, trim_route


def test_snap_to_nearest_point():
    line = LineString([(0, 0), (10, 0)])
    snapped, dist = snap_to_route(Point(5, 3), line)
    assert abs(snapped.x - 5) < 0.01
    assert abs(snapped.y) < 0.01
    assert abs(dist - 5) < 0.01


def test_trim_preserves_endpoints():
    line = LineString([(0, 0), (100, 0)])
    trimmed = trim_route(line, Point(20, 0), Point(80, 0))
    assert isinstance(trimmed, LineString)
    assert abs(trimmed.coords[0][0] - 20) < 0.1
    assert abs(trimmed.coords[-1][0] - 80) < 0.1


def test_trim_full_line_is_identity():
    line = LineString([(0, 0), (100, 0)])
    trimmed = trim_route(line, Point(0, 0), Point(100, 0))
    assert abs(trimmed.length - 100) < 0.1


def test_trim_reversed_points_same_result():
    line = LineString([(0, 0), (100, 0)])
    t1 = trim_route(line, Point(20, 0), Point(80, 0))
    t2 = trim_route(line, Point(80, 0), Point(20, 0))
    assert abs(t1.length - t2.length) < 0.1
