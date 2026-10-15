from __future__ import annotations

from matplotlib.figure import Figure

from trailpager.config import Settings

_BODY = """\
PLANNING AID ONLY

This map is produced from publicly available digital data and is intended as a
planning aid only. It does not replace official maps, a compass, or good judgment.

Verify trail conditions, closures, and regulations with the managing agency
before your trip.

DATA SOURCES
  Trail line:           Appalachian Trail Conservancy / OpenStreetMap
  Topographic basemap:  USGS National Map (USGSTopo)
  Land boundaries:      US Forest Service / National Park Service

PRINT INSTRUCTIONS
  Print at 100% — do not scale or fit to page.
  Printed scale will not be accurate if the page is scaled during printing.

DATUM
  WGS 84 / UTM Zone 17N.
  For practical navigation with a GPS in this region, NAD-83 is interchangeable
  (difference < 1 m).
"""


def render_disclaimer_page(settings: Settings, data_date: str = "") -> Figure:
    w_in, h_in = settings.page_size_inches
    fig = Figure(figsize=(w_in, h_in))
    ax = fig.add_subplot(1, 1, 1)
    ax.set_axis_off()

    body = _BODY
    if data_date:
        body += f"\nData retrieved: {data_date}"

    fig.text(0.1, 0.88, "Disclaimer", fontsize=14, fontweight="bold", va="top")
    fig.text(0.1, 0.80, body, fontsize=9, va="top", family="monospace")
    return fig
