from shapely.geometry import LineString

from trailpager.pagination.paginator import PageFrame, paginate

PAGE_W = 6700.0
PAGE_H = 5200.0
OVERLAP = 500.0
MARGIN = 200.0


def _all_coords_covered(line: LineString, frames: list[PageFrame]) -> bool:
    for x, y in line.coords:
        if not any(
            f.bbox_proj[0] <= x <= f.bbox_proj[2] and f.bbox_proj[1] <= y <= f.bbox_proj[3]
            for f in frames
        ):
            return False
    return True


def test_coverage_straight_line():
    line = LineString([(700_000, 4_200_000), (730_000, 4_200_000)])
    frames = paginate(line, PAGE_W, PAGE_H, OVERLAP, MARGIN)
    assert _all_coords_covered(line, frames)


def test_page_order_straight_line():
    line = LineString([(700_000, 4_200_000), (730_000, 4_200_000)])
    frames = paginate(line, PAGE_W, PAGE_H, OVERLAP, MARGIN)
    dists = [f.route_start_dist for f in frames]
    assert dists == sorted(dists)


def test_overlap_straight_line():
    line = LineString([(700_000, 4_200_000), (730_000, 4_200_000)])
    frames = paginate(line, PAGE_W, PAGE_H, OVERLAP, MARGIN)
    for i in range(len(frames) - 1):
        shared = frames[i].route_end_dist - frames[i + 1].route_start_dist
        assert shared >= OVERLAP - 1.0, f"Page {i + 1}→{i + 2}: overlap {shared:.1f} < {OVERLAP}"


def test_coverage_z_shape(z_shape_utm):
    frames = paginate(z_shape_utm, PAGE_W, PAGE_H, OVERLAP, MARGIN)
    assert _all_coords_covered(z_shape_utm, frames)


def test_page_numbers_sequential():
    line = LineString([(700_000, 4_200_000), (730_000, 4_200_000)])
    frames = paginate(line, PAGE_W, PAGE_H, OVERLAP, MARGIN)
    assert [f.page_number for f in frames] == list(range(1, len(frames) + 1))


def test_short_route_single_page():
    line = LineString([(700_000, 4_200_000), (701_000, 4_200_000)])
    frames = paginate(line, PAGE_W, PAGE_H, OVERLAP, MARGIN)
    assert len(frames) == 1
