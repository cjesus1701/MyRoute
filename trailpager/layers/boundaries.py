from __future__ import annotations

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import requests

USFS_REST_URL = (
    "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_ForestSystemBoundaries_01/MapServer"
    "/0/query"
)
NPS_REST_URL = (
    "https://services1.arcgis.com/fBc8EJBxQRMcHlei/arcgis/rest/services"
    "/NPS_Park_Boundaries/FeatureServer/0/query"
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
        "geometry": f"{minx},{miny},{maxx},{maxy}",
        "geometryType": "esriGeometryEnvelope",
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
