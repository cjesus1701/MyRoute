from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

from trailpager.config import Settings
from trailpager.layers.waypoints import Waypoint


def render_waypoint_table(waypoints: list[Waypoint], settings: Settings) -> Figure:
    w_in, h_in = settings.page_size_inches
    fig, ax = plt.subplots(figsize=(w_in, h_in))
    ax.set_axis_off()

    zone = settings.map.utm_zone
    col_labels = [
        "GPS Name",
        "Lat (WGS-84)",
        "Lon (WGS-84)",
        f"UTM E (m) Z{zone}N",
        f"UTM N (m) Z{zone}N",
        "Note",
    ]
    rows = []
    for wp in waypoints:
        easting, northing = wp.to_utm(settings.epsg)
        rows.append([
            wp.gps_name,
            f"{wp.lat:.5f}",
            f"{wp.lon:.5f}",
            f"{easting:.0f}",
            f"{northing:.0f}",
            wp.note,
        ])

    table = ax.table(cellText=rows, colLabels=col_labels, loc="center", cellLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.4)

    fig.text(
        0.5, 0.92,
        f"Waypoint Table — WGS 84 / UTM Zone {settings.map.utm_zone}N",
        ha="center", fontsize=11, fontweight="bold",
    )
    fig.text(
        0.5, 0.05,
        f"Coordinates: WGS-84 / UTM Zone {settings.map.utm_zone}N  "
        "(NAD-83 equivalent for navigation in this region).",
        ha="center", fontsize=7, color="gray",
    )
    return fig
