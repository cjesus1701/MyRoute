from __future__ import annotations

import hashlib
import json
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import requests
from pyproj import Transformer
from shapely.geometry import LineString

_EPQS_URL = "https://epqs.nationalmap.gov/v1/json"
_NODATA = -1_000_000.0


@dataclass
class ElevationPoint:
    distance_m: float
    lat: float
    lon: float
    elevation_m: float

    @property
    def elevation_ft(self) -> float:
        return self.elevation_m * 3.28084


def _fetch_one(lat: float, lon: float) -> float | None:
    try:
        r = requests.get(
            _EPQS_URL,
            params={"x": lon, "y": lat, "wkid": "4326", "units": "Meters"},
            timeout=15,
        )
        r.raise_for_status()
        val = r.json().get("value")
        v = float(val)
        return v if v > _NODATA + 1 else None
    except Exception:
        return None


def sample_route_elevation(
    line_proj: LineString,
    crs_proj: str,
    length_m: float,
    interval_m: float = 500.0,
    cache_dir: Path | None = None,
) -> list[ElevationPoint]:
    """Sample elevation along the route at regular intervals.

    Uses the USGS 3DEP Elevation Point Query Service.  Results are cached
    by route geometry so subsequent calls are instant.  Returns an empty
    list (with a warning) if all requests fail.
    """
    cache_file: Path | None = None
    if cache_dir:
        route_hash = hashlib.md5(line_proj.wkb).hexdigest()[:12]
        cache_file = cache_dir / f"elevation_{route_hash}_{int(interval_m)}m.json"
        if cache_file.exists():
            raw = json.loads(cache_file.read_text())
            return [ElevationPoint(**r) for r in raw]

    t_inv = Transformer.from_crs(crs_proj, "EPSG:4326", always_xy=True)
    dists = np.unique(np.clip(np.arange(0, length_m + interval_m, interval_m), 0, length_m))

    samples: list[tuple[float, float, float]] = []
    for d in dists:
        pt = line_proj.interpolate(float(d))
        lon, lat = t_inv.transform(pt.x, pt.y)
        samples.append((float(d), lat, lon))

    results: dict[float, float | None] = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_one, lat, lon): dist for dist, lat, lon in samples}
        for future in as_completed(futures):
            results[futures[future]] = future.result()

    points = [
        ElevationPoint(distance_m=d, lat=lat, lon=lon, elevation_m=results[d])
        for d, lat, lon in samples
        if results.get(d) is not None
    ]

    if not points:
        warnings.warn(
            "Elevation fetch returned no data — elevation profile will be skipped.",
            stacklevel=2,
        )
        return []

    points.sort(key=lambda ep: ep.distance_m)

    if cache_file:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps([asdict(ep) for ep in points]))

    return points
