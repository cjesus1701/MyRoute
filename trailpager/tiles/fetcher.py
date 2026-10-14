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


def zoom_for_scale(scale: int) -> int:
    zoom = round(math.log2(559_082_264 / (scale * 96 / 2.54)))
    return max(10, min(zoom, 16))
