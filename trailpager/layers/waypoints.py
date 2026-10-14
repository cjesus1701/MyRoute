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


def build_waypoints(processed, settings, pois=None) -> list[Waypoint]:
    """Build a GPS-ready waypoint list from a ProcessedRoute.

    Includes the trailhead start, every whole-mile marker, POIs (shelters
    and water sources), and the end — all sorted by distance along the route.
    """
    t_inv = Transformer.from_crs(
        f"EPSG:{settings.epsg}", "EPSG:4326", always_xy=True
    )

    # Build as (distance_m, Waypoint) so we can sort before returning
    entries: list[tuple[float, Waypoint]] = []

    sx, sy = processed.line_proj.coords[0]
    s_lon, s_lat = t_inv.transform(sx, sy)
    entries.append((0.0, Waypoint(name="Start", lat=s_lat, lon=s_lon, note="Mile 0.0")))

    for m in processed.mile_markers:
        if m.number == 0.0:
            continue
        lon, lat = t_inv.transform(m.point.x, m.point.y)
        entries.append((m.distance_m, Waypoint(
            name=f"Mile {m.number:.1f}",
            lat=lat, lon=lon,
            note=f"{m.number:.1f} mi from start",
        )))

    if pois:
        for poi in pois:
            entries.append((poi.distance_m, Waypoint(
                name=poi.name,
                lat=poi.lat,
                lon=poi.lon,
                note=f"{poi.kind.title()} — {poi.distance_m / 1609.344:.1f} mi",
            )))

    ex, ey = processed.line_proj.coords[-1]
    e_lon, e_lat = t_inv.transform(ex, ey)
    entries.append((processed.length_m, Waypoint(
        name="End",
        lat=e_lat, lon=e_lon,
        note=f"Mile {processed.length_miles:.1f}",
    )))

    entries.sort(key=lambda e: e[0])
    return [wp for _, wp in entries]
