from __future__ import annotations

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from shapely.geometry import LineString

from trailpager.config import Settings
from trailpager.pagination.paginator import PageFrame
from trailpager.render.cartography import (
    draw_boundaries,
    draw_mile_markers,
    draw_north_arrow,
    draw_route,
    draw_scale_bar,
)


def render_overview_page(
    route_proj: LineString,
    page_frames: list[PageFrame],
    settings: Settings,
    cache_dir: Path | None = None,
    mile_markers: list | None = None,
    boundaries: list | None = None,
    boundary_colors: list[str] | None = None,
    boundary_labels: list[str] | None = None,
) -> Figure:
    w_in, h_in = settings.page_size_inches
    fig, ax = plt.subplots(figsize=(w_in, h_in))
    ax.set_aspect("equal")

    minx, miny, maxx, maxy = route_proj.bounds
    padding = max(maxx - minx, maxy - miny) * 0.05
    view_minx = minx - padding
    view_miny = miny - padding
    view_maxx = maxx + padding
    view_maxy = maxy + padding
    ax.set_xlim(view_minx, view_maxx)
    ax.set_ylim(view_miny, view_maxy)

    if settings.layers.topo_basemap:
        from trailpager.tiles.fetcher import add_basemap
        add_basemap(ax, crs=f"EPSG:{settings.epsg}", zoom="auto", cache_dir=cache_dir)

    if boundaries and (settings.layers.usfs_boundary or settings.layers.nps_boundary):
        draw_boundaries(
            ax, boundaries,
            target_epsg=settings.epsg,
            colors=boundary_colors,
            labels=boundary_labels,
        )

    draw_route(ax, route_proj, linewidth=1.5)

    if mile_markers and settings.layers.mile_markers:
        visible = [
            m for m in mile_markers
            if view_minx <= m.point.x <= view_maxx and view_miny <= m.point.y <= view_maxy
        ]
        draw_mile_markers(ax, visible)

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

    if boundaries:
        handles, lbls = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, lbls, loc="lower right", fontsize=6, framealpha=0.8)

    draw_north_arrow(ax)

    # Compute actual display scale from route extent vs physical page size
    extent_m = max(maxx - minx + 2 * padding, maxy - miny + 2 * padding)
    page_major_m = max(w_in, h_in) * 0.0254
    display_scale = max(1, int(extent_m / page_major_m))
    draw_scale_bar(ax, display_scale, length_m=5000)

    ax.set_axis_off()
    fig.text(0.5, 0.97, "Overview Map", ha="center", va="top", fontsize=10, fontweight="bold")
    footer = (
        f"Scale ≈ 1:{display_scale:,}  ·  WGS 84 / UTM Zone {settings.map.utm_zone}N  ·  "
        f"{len(page_frames)} detail page(s)  ·  Print at 100%"
        if page_frames else
        f"Scale ≈ 1:{display_scale:,}  ·  WGS 84 / UTM Zone {settings.map.utm_zone}N  ·  "
        "Print at 100%"
    )
    fig.text(0.5, 0.01, footer, ha="center", fontsize=6, color="gray")
    fig.tight_layout(pad=0.2)
    return fig
