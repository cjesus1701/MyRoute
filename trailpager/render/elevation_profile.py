from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from trailpager.config import Settings

_FILL_COLOR    = "#C4A35A"
_LINE_COLOR    = "#6D4C1F"
_SHELTER_COLOR = "#8B0000"
_WATER_COLOR   = "#0D47A1"


def render_elevation_profile_page(
    elev_points: list,
    mile_markers: list,
    settings: Settings,
    pois: list | None = None,
) -> Figure:
    """Render a full-page elevation profile with optional POI markers."""
    w_in, h_in = settings.page_size_inches
    fig, ax = plt.subplots(figsize=(w_in, h_in))
    fig.subplots_adjust(left=0.08, right=0.96, top=0.86, bottom=0.16)

    dists_mi = np.array([ep.distance_m / 1609.344 for ep in elev_points])
    elevs_ft = np.array([ep.elevation_ft for ep in elev_points])

    elev_min, elev_max = float(elevs_ft.min()), float(elevs_ft.max())
    elev_range = elev_max - elev_min
    floor = elev_min - elev_range * 0.12

    ax.fill_between(dists_mi, elevs_ft, floor, color=_FILL_COLOR, alpha=0.55)
    ax.plot(dists_mi, elevs_ft, color=_LINE_COLOR, linewidth=1.4)

    # Axes styling
    y_pad = elev_range * 0.18
    ax.set_ylim(floor, elev_max + y_pad)
    ax.set_ylabel("Elevation (ft)", fontsize=8)
    ax.set_xlim(0, float(dists_mi[-1]))
    ax.set_xlabel("Miles from start", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.yaxis.set_major_locator(plt.MultipleLocator(500))
    ax.yaxis.grid(True, linewidth=0.3, alpha=0.4, linestyle="--")
    ax.xaxis.set_major_locator(plt.MultipleLocator(1))
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
            color = _SHELTER_COLOR if poi.kind == "shelter" else _WATER_COLOR
            marker = "^" if poi.kind == "shelter" else "o"
            ms = 8 if poi.kind == "shelter" else 6
            ax.plot(poi_mi, poi_elev, marker, color=color, markersize=ms, zorder=7,
                    markeredgecolor="white", markeredgewidth=0.5)
            label = "Shelter" if poi.kind == "shelter" else "Water / Spring"
            if (label, poi.kind) not in legend_entries:
                legend_entries.append((label, poi.kind))

    if legend_entries:
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
