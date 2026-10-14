import io

from matplotlib.backends.backend_pdf import PdfPages

from trailpager.config import Settings
from trailpager.layers.waypoints import Waypoint
from trailpager.pagination.paginator import PageFrame


def _default_settings() -> Settings:
    return Settings(
        route={"file": "data/dummy.gpx", "start": [37.9, -79.0], "end": [38.0, -78.9]},
        layers={"topo_basemap": False},  # no network in smoke tests
    )


def test_overview_renders(straight_line_utm):
    from trailpager.render.overview import render_overview_page

    frames = [PageFrame(
        page_number=1,
        bbox_proj=(700_000, 4_200_000, 707_000, 4_206_000),
        route_start_dist=0,
        route_end_dist=10_000,
    )]
    fig = render_overview_page(straight_line_utm, frames, _default_settings(), cache_dir=None)
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        pdf.savefig(fig)


def test_detail_page_renders(straight_line_utm):
    from trailpager.render.page import render_detail_page

    frame = PageFrame(
        page_number=1,
        bbox_proj=(700_000, 4_190_000, 707_000, 4_210_000),
        route_start_dist=0,
        route_end_dist=10_000,
    )
    fig = render_detail_page(frame, straight_line_utm, [], _default_settings(), total_pages=1)
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        pdf.savefig(fig)


def test_waypoint_table_renders():
    from trailpager.render.waypoint_table import render_waypoint_table

    waypoints = [
        Waypoint(name="Reids Gap", lat=37.9123, lon=-79.0891, note="Trailhead"),
        Waypoint(name="Rockfish Gap", lat=38.0319, lon=-78.8731, note="End"),
    ]
    fig = render_waypoint_table(waypoints, _default_settings())
    assert fig is not None


def test_disclaimer_renders():
    from trailpager.render.disclaimer import render_disclaimer_page

    fig = render_disclaimer_page(_default_settings(), data_date="2026-10-14")
    assert fig is not None
