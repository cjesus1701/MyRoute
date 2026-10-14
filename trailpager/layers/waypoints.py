from __future__ import annotations

from dataclasses import dataclass

from pyproj import Transformer


@dataclass
class Waypoint:
    name: str
    lat: float
    lon: float
    note: str = ""

    @property
    def gps_name(self) -> str:
        return self.name[:8].upper().replace(" ", "_")

    def to_utm(self, utm_epsg: int) -> tuple[float, float]:
        transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True)
        easting, northing = transformer.transform(self.lon, self.lat)
        return easting, northing
