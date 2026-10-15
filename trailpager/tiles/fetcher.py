from __future__ import annotations

import math
import warnings
from pathlib import Path

import contextily as cx
import numpy as np
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
    grayscale: bool = False,
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

    if grayscale:
        for artist in ax.get_images():
            rgba = artist.get_array()
            if rgba is None or rgba.ndim < 3:
                continue
            rgb = rgba[:, :, :3].astype(np.float32)
            lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
            gray_rgb = np.stack([lum, lum, lum], axis=-1).astype(rgba.dtype)
            if rgba.shape[2] == 4:
                out = np.dstack([gray_rgb, rgba[:, :, 3]])
            else:
                out = gray_rgb
            artist.set_array(out)


def zoom_for_scale(scale: int, dpi: int = 300) -> int:
    """Return the web-tile zoom level that gives readable labels at the print scale.

    Pixel-perfect matching (zoom 16 at 1:24 000/300 DPI) replicates the original
    USGS 7.5-minute quad text — typically 3–5 pt on paper, which is too small to
    read in the field.  Backing off by two zoom levels makes each tile span ~2 print
    inches, scaling the labels up ~4× to roughly 12–14 pt while keeping enough
    contour and trail detail for navigation.

    Typical results: 1:12 000 → 15, 1:24 000 → 14, 1:50 000 → 13, 1:100 000 → 12.
    """
    pixel_perfect = round(math.log2(156_543.04 * dpi / (scale * 0.0254)))
    zoom = pixel_perfect - 2
    return max(10, min(zoom, 18))
