from __future__ import annotations

import numpy as np
from matplotlib.axes import Axes
from shapely.geometry import LineString

from trailpager.route.measure import MileMarker


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
) -> None:
    xs, ys = line.xy
    ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=5, solid_capstyle="round")


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
    minx, miny, maxx, maxy = bbox_proj
    xs = np.arange(np.floor(minx / interval_m) * interval_m, maxx, interval_m)
    ys = np.arange(np.floor(miny / interval_m) * interval_m, maxy, interval_m)

    for x in xs:
        ax.axvline(x, color="gray", linewidth=0.3, linestyle="--", zorder=2, alpha=0.6)
        ax.text(x, miny + (maxy - miny) * 0.01, f"{x / 1000:.0f}",
                fontsize=5, ha="center", va="bottom", color="gray")
    for y in ys:
        ax.axhline(y, color="gray", linewidth=0.3, linestyle="--", zorder=2, alpha=0.6)
        ax.text(minx + (maxx - minx) * 0.01, y, f"{y / 1000:.0f}",
                fontsize=5, ha="left", va="center", color="gray")
