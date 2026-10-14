from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path

import geopandas as gpd
import requests

USFS_REST_URL = (
    "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_ForestSystemBoundaries_01/MapServer"
    "/0/query"
)
NPS_REST_URL = (
    "https://services1.arcgis.com/fBc8EJBxQRMcHlei/arcgis/rest/services"
    "/NPS_Land_Resources_Division_Boundary_and_Tract_Data_Service/FeatureServer/2/query"
)


def _bbox_hash(bbox: tuple[float, float, float, float]) -> str:
    return hashlib.md5(json.dumps(bbox).encode()).hexdigest()[:8]


def _fetch_arcgis_boundary(
    url: str,
    bbox: tuple[float, float, float, float],
    cache_dir: Path,
    layer_name: str,
) -> gpd.GeoDataFrame:
    cache_file = cache_dir / f"boundary_{layer_name}_{_bbox_hash(bbox)}.geojson"

    if cache_file.exists():
        return gpd.read_file(cache_file)

    minx, miny, maxx, maxy = bbox
    params = {
        "where": "1=1",
        "geometry": f"{minx},{miny},{maxx},{maxy}",
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": "4326",
        "outSR": "4326",
        "f": "geojson",
        "outFields": "*",
        "returnGeometry": "true",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    cache_file.write_text(resp.text)
    return gpd.read_file(cache_file)


def fetch_usfs_boundary(
    bbox: tuple[float, float, float, float],
    cache_dir: Path,
) -> gpd.GeoDataFrame:
    return _fetch_arcgis_boundary(USFS_REST_URL, bbox, cache_dir, "usfs")


def fetch_nps_boundary(
    bbox: tuple[float, float, float, float],
    cache_dir: Path,
) -> gpd.GeoDataFrame:
    return _fetch_arcgis_boundary(NPS_REST_URL, bbox, cache_dir, "nps")


_COLORS = ["#2ca02c", "#1f77b4"]
_LABELS = ["George Washington NF", "National Park / BRP"]


def fetch_boundary_layers(
    settings,
    route_bounds_wgs84: tuple[float, float, float, float],
    cache_dir: Path,
) -> tuple[list[gpd.GeoDataFrame], list[str], list[str]]:
    """Fetch USFS and NPS boundary layers for the route bbox.

    Returns (gdfs, colors, labels) — one entry per layer.  A layer that
    fails is represented by an empty GeoDataFrame so downstream callers
    always receive a fixed-length list.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    minx, miny, maxx, maxy = route_bounds_wgs84
    # Add a 10 % buffer so boundaries are visible near the edges of page 1 / last page
    dx = (maxx - minx) * 0.10
    dy = (maxy - miny) * 0.10
    bbox = (minx - dx, miny - dy, maxx + dx, maxy + dy)

    gdfs: list[gpd.GeoDataFrame] = []

    def _safe_fetch(fetcher, name: str) -> gpd.GeoDataFrame:
        try:
            gdf = fetcher(bbox, cache_dir)
            return gdf
        except Exception as exc:
            warnings.warn(f"{name} boundary unavailable: {exc}", stacklevel=3)
            return gpd.GeoDataFrame()

    if settings.layers.usfs_boundary:
        gdfs.append(_safe_fetch(fetch_usfs_boundary, "USFS"))
    if settings.layers.nps_boundary:
        gdfs.append(_safe_fetch(fetch_nps_boundary, "NPS"))

    n = len(gdfs)
    return gdfs, _COLORS[:n], _LABELS[:n]
