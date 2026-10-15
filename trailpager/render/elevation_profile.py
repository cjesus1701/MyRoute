from __future__ import annotations

import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator

from trailpager.config import Settings

_FILL_COLOR    = "#C4A35A"
_LINE_COLOR    = "#6D4C1F"
_SHELTER_COLOR = "#8B0000"
_WATER_COLOR   = "#0D47A1"

_FILL_COLOR_BW    = "#cccccc"
_LINE_COLOR_BW    = "#000000"
_SHELTER_COLOR_BW = "#000000"
_WATER_COLOR_BW   = "#000000"


def render_elevation_profile_page(
    elev_points: list,
    mile_markers: list,
    settings: Settings,
    pois: list | None = None,
) -> Figure:
    """Render a full-page elevation profile with optional POI markers."""
    bw = settings.map.bw_print

    fill_color    = _FILL_COLOR_BW    if bw else _FILL_COLOR
    line_color    = _LINE_COLOR_BW    if bw else _LINE_COLOR
    shelter_color = _SHELTER_COLOR_BW if bw else _SHELTER_COLOR
    water_color   = _WATER_COLOR_BW   if bw else _WATER_COLOR

    w_in, h_in = settings.page_size_inches
    fig = Figure(figsize=(w_in, h_in))
    ax = fig.add_subplot(1, 1, 1)
    fig.subplots_adjust(left=0.08, right=0.96, top=0.86, bottom=0.16)

    dists_mi = np.array([ep.distance_m / 1609.344 for ep in elev_points])
    elevs_ft = np.array([ep.elevation_ft for ep in elev_points])

    elev_min, elev_max = float(elevs_ft.min()), float(elevs_ft.max())
    elev_range = elev_max - elev_min
    floor = elev_min - elev_range * 0.12

    fill_kw = dict(color=fill_color, alpha=0.55)
    if bw:
        fill_kw["hatch"] = "///"
    ax.fill_between(dists_mi, elevs_ft, floor, **fill_kw)
    ax.plot(dists_mi, elevs_ft, color=line_color, linewidth=1.4)

    # Axes styling
    y_pad = elev_range * 0.18
    ax.set_ylim(floor, elev_max + y_pad)
    ax.set_ylabel("Elevation (ft)", fontsize=8)
    ax.set_xlim(0, float(dists_mi[-1]))
    ax.set_xlabel("Miles from start", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.yaxis.set_major_locator(MultipleLocator(500))
    ax.yaxis.grid(True, linewidth=0.3, alpha=0.4, linestyle="--")
    ax.xaxis.set_major_locator(MultipleLocator(1))
    ax.xaxis.grid(True, linewidth=0.3, alpha=0.3, linestyle="--")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # POI markers on the profile curve
    legend_entries: list[tuple[str, str]] = []  # (label, kind)
    if pois:
        elev_dists = [ep.distance_m for ep in elev_points]
        for poi in pois:
            poi_mi = poi.distance_m / 1609.344
            poi_elev = float(np.interp(poi.distance_m, elev_dists, elevs_ft))
            is_shelter = poi.kind == "shelter"
            color  = shelter_color if is_shelter else water_color
            marker = "^" if is_shelter else "o"
            ms     = 8  if is_shelter else 6
            if bw:
                # Shelter: filled black triangle; water: hollow circle
                fc = "black" if is_shelter else "white"
                ax.plot(poi_mi, poi_elev, marker, color=fc, markersize=ms, zorder=7,
                        markeredgecolor="black", markeredgewidth=1.2)
            else:
                ax.plot(poi_mi, poi_elev, marker, color=color, markersize=ms, zorder=7,
                        markeredgecolor="white", markeredgewidth=0.5)
            label = "Shelter" if is_shelter else "Water / Spring"
            if (label, poi.kind) not in legend_entries:
                legend_entries.append((label, poi.kind))

    if legend_entries:
        if bw:
            handles = [
                Line2D([0], [0],
                       marker="^" if k == "shelter" else "o",
                       color="w",
                       markerfacecolor="black" if k == "shelter" else "white",
                       markeredgecolor="black", markeredgewidth=1.2,
                       markersize=7, label=lbl)
                for lbl, k in legend_entries
            ]
        else:
            handles = [
                Line2D([0], [0], marker="^" if k == "shelter" else "o",
                       color="w",
                       markerfacecolor=_SHELTER_COLOR if k == "shelter" else _WATER_COLOR,
                       markersize=7, label=lbl)
                for lbl, k in legend_entries
            ]
        ax.legend(handles=handles, loc="upper right", fontsize=7, framealpha=0.85)

    # Gain / loss stats
    gain_ft = sum(max(0.0, float(b) - float(a)) for a, b in zip(elevs_ft, elevs_ft[1:]))
    loss_ft = sum(max(0.0, float(a) - float(b)) for a, b in zip(elevs_ft, elevs_ft[1:]))

    fig.suptitle("Elevation Profile", fontsize=13, fontweight="bold", y=0.96)
    fig.text(
        0.5, 0.91,
        f"{float(dists_mi[-1]):.1f} mi  ·  "
        f"+{gain_ft:,.0f} ft gain  ·  −{loss_ft:,.0f} ft loss  ·  "
        f"WGS 84 / UTM Zone {settings.map.utm_zone}N",
        ha="center", fontsize=7.5, color="gray",
    )

    return fig
