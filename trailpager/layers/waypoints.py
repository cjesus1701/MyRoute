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


def build_waypoints(processed, settings) -> list[Waypoint]:
    """Build a GPS-ready waypoint list from a ProcessedRoute.

    Includes the trailhead start, every whole-mile marker, and the end.
    Points are back-projected from UTM to WGS-84.
    """
    from trailpager.config import Settings

    t_inv = Transformer.from_crs(
        f"EPSG:{settings.epsg}", "EPSG:4326", always_xy=True
    )

    waypoints: list[Waypoint] = []

    # Start
    sx, sy = processed.line_proj.coords[0]
    s_lon, s_lat = t_inv.transform(sx, sy)
    waypoints.append(Waypoint(name="Start", lat=s_lat, lon=s_lon, note="Mile 0.0"))

    # Whole-mile markers (skip mile 0 — duplicates Start)
    for m in processed.mile_markers:
        if m.number == 0.0:
            continue
        lon, lat = t_inv.transform(m.point.x, m.point.y)
        waypoints.append(Waypoint(
            name=f"Mile {m.number:.1f}",
            lat=lat,
            lon=lon,
            note=f"{m.number:.1f} mi from start",
        ))

    # End
    ex, ey = processed.line_proj.coords[-1]
    e_lon, e_lat = t_inv.transform(ex, ey)
    waypoints.append(Waypoint(
        name="End",
        lat=e_lat,
        lon=e_lon,
        note=f"Mile {processed.length_miles:.1f}",
    ))

    return waypoints
