from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from trailpager.config import Settings
from trailpager.pagination.paginator import PageFrame
from trailpager.render.cartography import (
    draw_boundaries,
    draw_mile_markers,
    draw_north_arrow,
    draw_route,
    draw_scale_bar,
    draw_utm_grid,
)


def render_detail_page(
    page_frame: PageFrame,
    route_proj,
    mile_markers: list,
    settings: Settings,
    total_pages: int,
    cache_dir: Path | None = None,
    boundaries: list | None = None,
    boundary_colors: list[str] | None = None,
    boundary_labels: list[str] | None = None,
) -> Figure:
    w_in, h_in = settings.page_size_inches
    fig, ax = plt.subplots(figsize=(w_in, h_in))
    ax.set_aspect("equal")

    minx, miny, maxx, maxy = page_frame.bbox_proj
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)

    if settings.layers.topo_basemap:
        from trailpager.tiles.fetcher import add_basemap, zoom_for_scale
        add_basemap(
            ax,
            crs=f"EPSG:{settings.epsg}",
            zoom=zoom_for_scale(settings.map.scale),
            cache_dir=cache_dir,
        )

    if boundaries and (settings.layers.usfs_boundary or settings.layers.nps_boundary):
        draw_boundaries(
            ax, boundaries,
            target_epsg=settings.epsg,
            colors=boundary_colors,
            labels=boundary_labels,
        )

    draw_route(ax, route_proj)

    if settings.layers.mile_markers:
        visible = [
            m for m in mile_markers
            if minx <= m.point.x <= maxx and miny <= m.point.y <= maxy
        ]
        draw_mile_markers(ax, visible)

    if settings.layers.utm_grid:
        draw_utm_grid(ax, page_frame.bbox_proj)

    draw_scale_bar(ax, settings.map.scale)
    draw_north_arrow(ax)

    ax.set_axis_off()
    fig.text(
        0.5, 0.01,
        f"Page {page_frame.page_number} of {total_pages}  |  "
        f"Scale 1:{settings.map.scale:,}  |  Print at 100% — do not scale  |  "
        f"WGS 84 / UTM Zone {settings.map.utm_zone}N",
        ha="center", fontsize=6, color="gray",
    )
    fig.tight_layout(pad=0.2)
    return fig
