"""Integration tests for the full paginated PDF pipeline."""

import json
import warnings
from io import BytesIO
from pathlib import Path

import pytest
from matplotlib.backends.backend_pdf import PdfPages
from shapely.geometry import LineString

pytestmark = [pytest.mark.network, pytest.mark.slow]


@pytest.fixture
def at_settings():
    import os

    from trailpager.config import Settings

    if not os.path.exists("data/at_va_south.geojson"):
        pytest.skip("AT GeoJSON not found — run scripts/milestone0_data_check.py first")
    return Settings(
        route={
            "file": "data/at_va_south.geojson",
            "start": [37.9013, -78.9852],
            "end":   [38.0319, -78.8731],
        },
        map={"scale": 24000, "page_size": "letter", "orientation": "landscape",
             "overlap_m": 500, "margin_m": 200},
        layers={"topo_basemap": False, "usfs_boundary": False, "nps_boundary": False,
                "mile_markers": True, "utm_grid": False},
        output={"path": "output/test_pipeline.pdf"},
    )


def test_page_count_reasonable(at_settings):
    """At 1:24 000 the AT section should fit in 4–10 pages."""
    from trailpager.pagination.paginator import paginate
    from trailpager.route.pipeline import process_route

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        processed = process_route(at_settings)

    page_w, page_h = at_settings.page_ground_size_m
    frames = paginate(
        processed.line_proj, page_w, page_h,
        at_settings.map.overlap_m, at_settings.map.margin_m,
    )
    assert 4 <= len(frames) <= 10, f"Unexpected page count: {len(frames)}"


def test_full_coverage(at_settings):
    """Every vertex of the trimmed route must appear on at least one page."""
    from trailpager.pagination.paginator import paginate
    from trailpager.route.pipeline import process_route

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        processed = process_route(at_settings)

    page_w, page_h = at_settings.page_ground_size_m
    frames = paginate(
        processed.line_proj, page_w, page_h,
        at_settings.map.overlap_m, at_settings.map.margin_m,
    )

    uncovered = []
    for x, y in processed.line_proj.coords:
        on_page = any(
            f.bbox_proj[0] <= x <= f.bbox_proj[2] and f.bbox_proj[1] <= y <= f.bbox_proj[3]
            for f in frames
        )
        if not on_page:
            uncovered.append((x, y))

    assert not uncovered, f"{len(uncovered)} vertex/vertices not covered by any page"


def test_pages_render_to_pdf(at_settings, tmp_path):
    """Full pipeline (overview + detail + waypoint table + disclaimer) produces a valid PDF."""
    import datetime

    from trailpager.layers.waypoints import build_waypoints
    from trailpager.pagination.paginator import paginate
    from trailpager.render.disclaimer import render_disclaimer_page
    from trailpager.render.overview import render_overview_page
    from trailpager.render.page import render_detail_page
    from trailpager.render.waypoint_table import render_waypoint_table
    from trailpager.route.pipeline import process_route

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        processed = process_route(at_settings)

    page_w, page_h = at_settings.page_ground_size_m
    frames = paginate(
        processed.line_proj, page_w, page_h,
        at_settings.map.overlap_m, at_settings.map.margin_m,
    )

    waypoints = build_waypoints(processed, at_settings)

    buf = BytesIO()
    with PdfPages(buf) as pdf:
        fig = render_overview_page(
            processed.line_proj, frames, at_settings,
            mile_markers=processed.mile_markers,
        )
        pdf.savefig(fig)

        for frame in frames:
            fig = render_detail_page(
                frame, processed.line_proj, processed.mile_markers,
                at_settings, total_pages=len(frames),
            )
            pdf.savefig(fig)

        pdf.savefig(render_waypoint_table(waypoints, at_settings))
        pdf.savefig(render_disclaimer_page(at_settings, data_date=datetime.date.today().isoformat()))

    buf.seek(0)
    assert buf.read(4) == b"%PDF", "Output is not a valid PDF"


def test_waypoint_table_has_start_and_end(at_settings):
    """Waypoint list begins with Start and ends with End."""
    from trailpager.layers.waypoints import build_waypoints
    from trailpager.route.pipeline import process_route

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        processed = process_route(at_settings)

    waypoints = build_waypoints(processed, at_settings)
    assert waypoints[0].name == "Start"
    assert waypoints[-1].name == "End"
    # 17.69-mile route → start + 17 markers + end = 19 waypoints
    assert len(waypoints) >= 18
