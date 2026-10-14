from __future__ import annotations

import math
import warnings
from pathlib import Path

import contextily as cx
from matplotlib.axes import Axes

USGS_TOPO_URL = (
    "https://basemap.nationalmap.gov/arcgis/rest/services"
    "/USGSTopo/MapServer/tile/{z}/{y}/{x}"
)
USGS_TOPO_ATTRIBUTION = "USGS National Map (USGSTopo)"


def add_basemap(
    ax: Axes,
    crs: str,
    zoom: int | str = "auto",
    cache_dir: Path | None = None,
) -> None:
    if cache_dir:
        cx.set_cache_dir(str(cache_dir))

    try:
        cx.add_basemap(
            ax,
            crs=crs,
            source=USGS_TOPO_URL,
            zoom=zoom,
            attribution=USGS_TOPO_ATTRIBUTION,
        )
    except Exception:
        warnings.warn(
            "USGS topo tiles unavailable; falling back to OpenStreetMap.",
            stacklevel=2,
        )
        cx.add_basemap(ax, crs=crs, source=cx.providers.OpenStreetMap.Mapnik.url, zoom=zoom)


def zoom_for_scale(scale: int, dpi: int = 300) -> int:
    """Return the web-tile zoom level whose pixel resolution matches the print scale.

    Derivation: web tiles have a native resolution of 156,543 m/px at zoom 0
    (equator, Web Mercator).  For a printed map at *scale* and *dpi*, each
    pixel represents (scale × 0.0254 / dpi) ground metres.  Setting the two
    equal and solving for Z gives the formula below.

    At 1:24,000 / 300 DPI this returns 16, which is the USGS 7.5-minute quad
    level — the zoom at which trail names, contour labels, and road names are
    all legible.
    """
    zoom = round(math.log2(156_543.04 * dpi / (scale * 0.0254)))
    return max(10, min(zoom, 18))
