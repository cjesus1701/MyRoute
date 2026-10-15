from __future__ import annotations

from pathlib import Path

from matplotlib.figure import Figure

from trailpager.config import Settings
from trailpager.pagination.paginator import PageFrame
from trailpager.render.cartography import (
    draw_boundaries,
    draw_mile_markers,
    draw_north_arrow,
    draw_pois,
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
    pois: list | None = None,
) -> Figure:
    w_in, h_in = settings.page_size_inches
    fig = Figure(figsize=(w_in, h_in))
    ax = fig.add_subplot(1, 1, 1)
    ax.set_aspect("equal")

    minx, miny, maxx, maxy = page_frame.bbox_proj
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)

    bw = settings.map.bw_print

    if settings.layers.topo_basemap:
        from trailpager.tiles.fetcher import add_basemap, zoom_for_scale
        add_basemap(
            ax,
            crs=f"EPSG:{settings.epsg}",
            zoom=zoom_for_scale(settings.map.scale),
            cache_dir=cache_dir,
            grayscale=bw,
        )

    if boundaries and (settings.layers.usfs_boundary or settings.layers.nps_boundary):
        bw_colors = ["#000000", "#444444"] if bw else boundary_colors
        bw_styles  = ["--", ":"]
        draw_boundaries(
            ax, boundaries,
            target_epsg=settings.epsg,
            colors=bw_colors,
            labels=boundary_labels,
            linestyles=bw_styles if bw else None,
        )

    route_color = "#000000" if bw else "#d62728"
    draw_route(ax, route_proj, color=route_color)

    if settings.layers.mile_markers:
        visible = [
            m for m in mile_markers
            if minx <= m.point.x <= maxx and miny <= m.point.y <= maxy
        ]
        draw_mile_markers(ax, visible, color="#000000" if bw else "#d62728")

    if settings.layers.utm_grid:
        draw_utm_grid(ax, page_frame.bbox_proj)

    if settings.layers.pois and pois:
        page_pois = [
            p for p in pois
            if page_frame.route_start_dist - 1000 <= p.distance_m <= page_frame.route_end_dist + 1000
        ]
        if page_pois:
            draw_pois(ax, page_pois, target_epsg=settings.epsg, bw=bw)

    draw_scale_bar(ax, settings.map.scale)
    draw_north_arrow(ax)

    ax.set_axis_off()

    start_mi = page_frame.route_start_dist / 1609.344
    end_mi   = page_frame.route_end_dist   / 1609.344
    n = page_frame.page_number
    prev_hint = f"← Pg {n - 1}  " if n > 1 else ""
    next_hint = f"  Pg {n + 1} →" if n < total_pages else ""
    fig.text(
        0.5, 0.01,
        f"{prev_hint}"
        f"Page {n} of {total_pages}  ·  Miles {start_mi:.1f} – {end_mi:.1f}  ·  "
        f"Scale 1:{settings.map.scale:,}  ·  Print at 100%  ·  "
        f"WGS 84 / UTM Zone {settings.map.utm_zone}N"
        f"{next_hint}",
        ha="center", fontsize=6, color="gray",
    )
    fig.tight_layout(pad=0.2)
    return fig
