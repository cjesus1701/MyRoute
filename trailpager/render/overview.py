from __future__ import annotations

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from shapely.geometry import LineString

from trailpager.config import Settings
from trailpager.pagination.paginator import PageFrame
from trailpager.render.cartography import draw_north_arrow, draw_route, draw_scale_bar


def render_overview_page(
    route_proj: LineString,
    page_frames: list[PageFrame],
    settings: Settings,
    cache_dir: Path | None = None,
) -> Figure:
    w_in, h_in = settings.page_size_inches
    fig, ax = plt.subplots(figsize=(w_in, h_in))
    ax.set_aspect("equal")

    minx, miny, maxx, maxy = route_proj.bounds
    padding = max(maxx - minx, maxy - miny) * 0.05
    ax.set_xlim(minx - padding, maxx + padding)
    ax.set_ylim(miny - padding, maxy + padding)

    if settings.layers.topo_basemap:
        from trailpager.tiles.fetcher import add_basemap
        add_basemap(ax, crs=f"EPSG:{settings.epsg}", zoom="auto", cache_dir=cache_dir)

    draw_route(ax, route_proj, linewidth=1.5)

    for frame in page_frames:
        fx0, fy0, fx1, fy1 = frame.bbox_proj
        rect = mpatches.Rectangle(
            (fx0, fy0), fx1 - fx0, fy1 - fy0,
            linewidth=1, edgecolor="navy", facecolor="none", alpha=0.7, zorder=4,
        )
        ax.add_patch(rect)
        ax.text(
            (fx0 + fx1) / 2, (fy0 + fy1) / 2,
            str(frame.page_number),
            ha="center", va="center", fontsize=8, color="navy", fontweight="bold",
        )

    draw_north_arrow(ax)
    draw_scale_bar(ax, settings.map.scale * 5)

    ax.set_axis_off()
    fig.text(
        0.5, 0.01,
        "Overview — all detail pages shown",
        ha="center", fontsize=7, color="gray",
    )
    fig.tight_layout(pad=0.2)
    return fig
