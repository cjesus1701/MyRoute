from __future__ import annotations

import numpy as np
from matplotlib.axes import Axes
from shapely.geometry import LineString

from trailpager.route.measure import MileMarker

_BOUNDARY_COLORS = ["#2ca02c", "#1f77b4"]  # USFS green, NPS blue
_BOUNDARY_LABELS = ["National Forest", "National Park"]


def draw_scale_bar(
    ax: Axes,
    scale: int,
    length_m: float = 1000.0,
    position: tuple[float, float] = (0.05, 0.05),
) -> None:
    x0, y0 = position
    fig = ax.get_figure()
    bar_len_axes = length_m / (scale * 0.0254 * fig.get_figwidth())
    ax.annotate(
        "",
        xy=(x0 + bar_len_axes, y0),
        xytext=(x0, y0),
        xycoords="axes fraction",
        arrowprops=dict(arrowstyle="-", color="black", lw=2),
    )
    ax.text(
        x0 + bar_len_axes / 2, y0 + 0.02,
        f"{length_m:.0f} m",
        ha="center", va="bottom",
        transform=ax.transAxes, fontsize=7,
    )


def draw_north_arrow(ax: Axes, position: tuple[float, float] = (0.95, 0.08)) -> None:
    x, y = position
    ax.annotate(
        "N",
        xy=(x, y + 0.06),
        xytext=(x, y),
        xycoords="axes fraction",
        ha="center", fontsize=8, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="black", lw=1.5),
    )


def draw_route(
    ax: Axes,
    line: LineString,
    color: str = "#d62728",
    linewidth: float = 2.0,
    direction_dist: float | None = None,
) -> None:
    """Draw the route line.  If *direction_dist* (metres from line start) is
    given, a travel-direction arrowhead is placed at that point."""
    xs, ys = line.xy
    ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=5, solid_capstyle="round")

    if direction_dist is not None:
        total = line.length
        d0 = max(0.0, min(direction_dist, total))
        d1 = min(d0 + max(total * 0.02, 200.0), total)  # tail 2% of line or 200 m behind tip
        p0 = line.interpolate(d0)
        p1 = line.interpolate(d1)
        ax.annotate(
            "",
            xy=(p1.x, p1.y),
            xytext=(p0.x, p0.y),
            arrowprops=dict(
                arrowstyle="-|>",
                color=color,
                lw=linewidth,
                mutation_scale=14,
            ),
            zorder=6,
        )


def draw_mile_markers(ax: Axes, markers: list[MileMarker], color: str = "#d62728") -> None:
    for m in markers:
        ax.plot(m.point.x, m.point.y, "o", color=color, markersize=4, zorder=6)
        ax.annotate(
            f"{m.number:.0f}",
            xy=(m.point.x, m.point.y),
            xytext=(4, 4),
            textcoords="offset points",
            fontsize=6, color=color, zorder=7,
        )


def draw_utm_grid(
    ax: Axes,
    bbox_proj: tuple[float, float, float, float],
    interval_m: float = 1000.0,
) -> None:
    """Draw 1 km UTM grid lines with coordinate labels on all four borders.

    Labels show the kilometre value (e.g. "686" for 686 000 m E) with a
    white box so they read clearly over the basemap.  Labels appear at both
    the top & bottom edges for eastings, and both the left & right edges for
    northings, so a grid line is labelled wherever it reaches a page border.
    """
    minx, miny, maxx, maxy = bbox_proj
    xs = np.arange(np.ceil(minx / interval_m) * interval_m, maxx, interval_m)
    ys = np.arange(np.ceil(miny / interval_m) * interval_m, maxy, interval_m)

    box = dict(boxstyle="square,pad=0.15", facecolor="white", alpha=0.85, linewidth=0)
    lkw = dict(fontsize=7, color="black", bbox=box, zorder=8)

    for x in xs:
        ax.axvline(x, color="gray", linewidth=0.35, linestyle="--", zorder=2, alpha=0.65)
        label = f"{x / 1000:.0f}"
        ax.text(x, miny, label, ha="center", va="bottom", **lkw)
        ax.text(x, maxy, label, ha="center", va="top",    **lkw)

    for y in ys:
        ax.axhline(y, color="gray", linewidth=0.35, linestyle="--", zorder=2, alpha=0.65)
        label = f"{y / 1000:.0f}"
        ax.text(minx, y, label, ha="left",  va="center", **lkw)
        ax.text(maxx, y, label, ha="right", va="center", **lkw)


def draw_boundaries(
    ax: Axes,
    gdfs: list,
    target_epsg: int = 32617,
    colors: list[str] | None = None,
    labels: list[str] | None = None,
) -> None:
    if colors is None:
        colors = _BOUNDARY_COLORS
    if labels is None:
        labels = _BOUNDARY_LABELS
    for i, gdf in enumerate(gdfs):
        if gdf is None or gdf.empty:
            continue
        gdf_proj = gdf.to_crs(f"EPSG:{target_epsg}")
        color = colors[i % len(colors)]
        label = labels[i % len(labels)]
        gdf_proj.plot(
            ax=ax,
            facecolor="none",
            edgecolor=color,
            linewidth=1.2,
            linestyle="--",
            zorder=3,
            label=label,
        )
