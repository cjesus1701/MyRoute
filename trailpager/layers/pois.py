from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from pyproj import Transformer
from shapely.geometry import LineString, Point

_OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

_ICONS = {"shelter": "▲", "spring": "○", "water": "○"}
_COLORS = {"shelter": "#8B0000", "spring": "#0D47A1", "water": "#0D47A1"}


@dataclass
class POI:
    name: str
    lat: float
    lon: float
    kind: str          # 'shelter' | 'spring' | 'water'
    distance_m: float  # along-route metres from start

    @property
    def icon(self) -> str:
        return _ICONS.get(self.kind, "•")

    @property
    def color(self) -> str:
        return _COLORS.get(self.kind, "#333333")

    @property
    def gps_name(self) -> str:
        prefix = {"shelter": "SHLT", "spring": "SPNG", "water": "H2O"}.get(self.kind, "POI")
        return f"{prefix}{self.distance_m / 1609.344:.0f}MI"[:8].upper()


def fetch_pois(
    line_proj: LineString,
    crs_proj: str,
    route_bounds_wgs84: tuple[float, float, float, float],
    cache_dir: Path | None = None,
    max_dist_m: float = 500.0,
) -> list[POI]:
    """Fetch AT shelters, springs, and water sources from Overpass.

    Only returns POIs within *max_dist_m* of the route line.
    Results are cached by bounding box.
    """
    cache_file: Path | None = None
    if cache_dir:
        bbox_hash = hashlib.md5(json.dumps(route_bounds_wgs84).encode()).hexdigest()[:8]
        cache_file = cache_dir / f"pois_{bbox_hash}.json"
        if cache_file.exists():
            raw = json.loads(cache_file.read_text())
            return [POI(**r) for r in raw]

    minlon, minlat, maxlon, maxlat = route_bounds_wgs84
    buf = 0.05  # ~5 km buffer around route bounds
    s, w, n, e = minlat - buf, minlon - buf, maxlat + buf, maxlon + buf

    query = f"""[out:json][timeout:30];
(
  node["tourism"="wilderness_hut"]({s},{w},{n},{e});
  node["amenity"="shelter"]({s},{w},{n},{e});
  node["leisure"="shelter"]({s},{w},{n},{e});
  node["natural"="spring"]({s},{w},{n},{e});
  node["amenity"="drinking_water"]({s},{w},{n},{e});
);
out body;"""

    headers = {
        "User-Agent": "TrailPager/1.0 (trail map generator; contact cjesus1701@gmail.com)",
        "Accept": "application/json",
    }
    elements = None
    last_exc: Exception | None = None
    for url in _OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, headers=headers, timeout=45)
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            break
        except Exception as exc:
            last_exc = exc
            continue
    if elements is None:
        warnings.warn(f"POI fetch failed: {last_exc}", stacklevel=2)
        return []

    t_fwd = Transformer.from_crs("EPSG:4326", crs_proj, always_xy=True)
    pois: list[POI] = []

    for el in elements:
        if el.get("type") != "node":
            continue
        lat, lon = el["lat"], el["lon"]
        tags = el.get("tags", {})

        if tags.get("tourism") == "wilderness_hut":
            kind = "shelter"
        elif tags.get("amenity") == "shelter" or tags.get("leisure") == "shelter":
            kind = "shelter"
        elif tags.get("natural") == "spring":
            kind = "spring"
        elif tags.get("amenity") == "drinking_water":
            kind = "water"
        else:
            continue

        x, y = t_fwd.transform(lon, lat)
        pt = Point(x, y)
        along_m = line_proj.project(pt)
        nearest = line_proj.interpolate(along_m)
        if pt.distance(nearest) > max_dist_m:
            continue

        name = tags.get("name", "").strip()
        if not name:
            label = {"shelter": "Shelter", "spring": "Spring", "water": "Water"}[kind]
            name = f"{label} ({along_m / 1609.344:.1f} mi)"

        pois.append(POI(name=name, lat=lat, lon=lon, kind=kind, distance_m=along_m))

    pois.sort(key=lambda p: p.distance_m)

    if cache_file:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps([asdict(p) for p in pois]))

    return pois
