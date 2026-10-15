from __future__ import annotations

import asyncio
import io
import json
import math
import tempfile
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import matplotlib
matplotlib.use("Agg")   # non-interactive backend; must be set before any pyplot import

import requests as _requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from trailpager.config import Settings

app = FastAPI(title="MyRoute")

# In-memory store: route_id → { "path": Path }
_routes: dict[str, dict] = {}

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(_STATIC_DIR / "index.html")


# ── Request models ────────────────────────────────────────────────────────────

class PreviewRequest(BaseModel):
    route_id: str
    start: list[float]        # [lat, lon]
    end: list[float]          # [lat, lon]
    scale: int = 24_000
    page_size: str = "letter"
    orientation: str = "landscape"
    overlap_m: float = 500.0
    margin_m: float = 200.0
    utm_zone: int = 17
    bw_print: bool = False


class PointsRequest(BaseModel):
    start: list[float]   # [lat, lon]
    end: list[float]


class GenerateRequest(BaseModel):
    route_id: str
    start: list[float]
    end: list[float]
    scale: int = 24_000
    page_size: str = "letter"
    orientation: str = "landscape"
    overlap_m: float = 500.0
    margin_m: float = 200.0
    utm_zone: int = 17
    bw_print: bool = False
    layers: dict[str, bool] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_settings(route_path: Path, req: PreviewRequest | GenerateRequest) -> Settings:
    layers: dict = {}
    if isinstance(req, GenerateRequest) and req.layers:
        layers = req.layers
    else:
        layers = {
            "topo_basemap": True,
            "usfs_boundary": True,
            "nps_boundary": True,
            "mile_markers": True,
            "utm_grid": True,
            "elevation_profile": True,
            "pois": True,
        }
    return Settings(
        route={"file": str(route_path), "start": req.start, "end": req.end},
        map={
            "scale": req.scale,
            "page_size": req.page_size,
            "orientation": req.orientation,
            "overlap_m": req.overlap_m,
            "margin_m": req.margin_m,
            "utm_zone": req.utm_zone,
            "bw_print": req.bw_print,
        },
        layers=layers,
        output={"path": "output/web_generated.pdf"},
    )


def _user_error(exc: Exception) -> str:
    """Return a short, readable error message from an exception."""
    msg = str(exc)
    if "margin_m must be less than overlap_m" in msg:
        return "Overlap must be greater than the page margin (minimum 250 m)."
    # Strip verbose Pydantic boilerplate: keep only the first 'Value error' line
    for line in msg.splitlines():
        line = line.strip()
        if line.startswith("Value error,"):
            return line[len("Value error,"):].strip().capitalize()
    return msg.splitlines()[0] if msg else "Unknown error"


def _bbox_to_wgs84_ring(bbox_proj: tuple, epsg: int) -> list[list[float]]:
    from pyproj import Transformer
    t = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    minx, miny, maxx, maxy = bbox_proj
    corners = [(minx, miny), (maxx, miny), (maxx, maxy), (minx, maxy), (minx, miny)]
    return [[round(lon, 6), round(lat, 6)] for lon, lat in (t.transform(x, y) for x, y in corners)]


def _line_to_wgs84_coords(line_proj, epsg: int) -> list[list[float]]:
    from pyproj import Transformer
    t = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    return [[round(lon, 6), round(lat, 6)] for lon, lat in (t.transform(x, y) for x, y in line_proj.coords)]


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/route")
async def upload_route(file: UploadFile = File(...)) -> JSONResponse:
    """Accept a GPX or GeoJSON file; return route geometry and metadata."""
    suffix = Path(file.filename or "route").suffix.lower()
    if suffix not in {".gpx", ".geojson", ".json"}:
        raise HTTPException(400, "Only .gpx and .geojson files are supported.")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(await file.read())
    tmp.close()
    route_path = Path(tmp.name)

    from trailpager.route.loader import load_route
    caught_warnings: list[str] = []
    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            route_data = load_route(route_path)
        caught_warnings = [str(x.message) for x in w]
    except Exception as exc:
        route_path.unlink(missing_ok=True)
        raise HTTPException(422, f"Could not read route: {exc}")

    route_id = str(uuid.uuid4())
    _routes[route_id] = {"path": route_path}

    coords = list(route_data.line.coords)  # (lon, lat) in WGS84
    geojson_coords = [[round(lon, 6), round(lat, 6)] for lon, lat in coords]

    start_lonlat = geojson_coords[0]
    end_lonlat = geojson_coords[-1]
    bounds = list(route_data.line.bounds)  # [minx, miny, maxx, maxy]

    return JSONResponse({
        "route_id": route_id,
        "geojson": {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": geojson_coords},
            "properties": {},
        },
        "bounds": bounds,
        "default_start": [round(start_lonlat[1], 6), round(start_lonlat[0], 6)],
        "default_end": [round(end_lonlat[1], 6), round(end_lonlat[0], 6)],
        "warnings": caught_warnings,
    })


@app.post("/api/preview")
async def preview_pages(req: PreviewRequest) -> JSONResponse:
    """Return page-frame polygons (WGS84 GeoJSON) for the given settings."""
    entry = _routes.get(req.route_id)
    if not entry:
        raise HTTPException(404, "Route not found — please re-upload the file.")

    from trailpager.pagination.paginator import paginate
    from trailpager.route.pipeline import process_route

    try:
        settings = _make_settings(entry["path"], req)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            processed = process_route(settings)
        caught_warnings = [str(x.message) for x in w]
        page_w_m, page_h_m = settings.page_ground_size_m
        frames = paginate(
            processed.line_proj, page_w_m, page_h_m,
            settings.map.overlap_m, settings.map.margin_m,
        )
    except Exception as exc:
        raise HTTPException(422, _user_error(exc))

    features = []
    for f in frames:
        ring = _bbox_to_wgs84_ring(f.bbox_proj, settings.epsg)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {
                "page": f.page_number,
                "start_mi": round(f.route_start_dist / 1609.344, 2),
                "end_mi": round(f.route_end_dist / 1609.344, 2),
            },
        })

    return JSONResponse({
        "frames": {"type": "FeatureCollection", "features": features},
        "page_count": len(frames),
        "length_miles": round(processed.length_miles, 2),
        "route_geojson": {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": _line_to_wgs84_coords(processed.line_proj, settings.epsg),
            },
            "properties": {},
        },
        "warnings": caught_warnings,
    })


def _run_generation(settings, cache_dir: Path) -> io.BytesIO:
    """All-synchronous PDF generation — runs in a thread pool."""
    import datetime
    from matplotlib.backends.backend_pdf import PdfPages

    from trailpager.layers.boundaries import fetch_boundary_layers
    from trailpager.layers.elevation import sample_route_elevation
    from trailpager.layers.pois import fetch_pois
    from trailpager.layers.waypoints import build_waypoints
    from trailpager.pagination.paginator import paginate
    from trailpager.render.disclaimer import render_disclaimer_page
    from trailpager.render.elevation_profile import render_elevation_profile_page
    from trailpager.render.overview import render_overview_page
    from trailpager.render.page import render_detail_page
    from trailpager.render.waypoint_table import render_waypoint_table
    from trailpager.route.pipeline import process_route

    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        processed = process_route(settings)

    page_w_m, page_h_m = settings.page_ground_size_m
    frames = paginate(
        processed.line_proj, page_w_m, page_h_m,
        settings.map.overlap_m, settings.map.margin_m,
    )

    wgs_bounds = processed.line_wgs84.bounds
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        boundaries, bcolors, blabels = fetch_boundary_layers(settings, wgs_bounds, cache_dir)

    pois: list = []
    if settings.layers.pois:
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            pois = fetch_pois(processed.line_proj, processed.crs_proj, wgs_bounds, cache_dir)

    elev_points: list = []
    if settings.layers.elevation_profile:
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            elev_points = sample_route_elevation(
                processed.line_proj, processed.crs_proj,
                processed.length_m, cache_dir=cache_dir,
            )

    # ── Render overview (sequential — sets up shared tile cache) ─────────────
    overview_fig = render_overview_page(
        processed.line_proj, frames, settings,
        cache_dir=cache_dir,
        mile_markers=processed.mile_markers,
        boundaries=boundaries,
        boundary_colors=bcolors,
        boundary_labels=blabels,
        pois=pois or None,
    )

    # ── Render detail pages in parallel ──────────────────────────────────────
    n_workers = min(4, len(frames)) if frames else 1
    detail_figs: list = [None] * len(frames)

    def _render_frame(frame):
        return render_detail_page(
            frame, processed.line_proj, processed.mile_markers, settings,
            total_pages=len(frames),
            cache_dir=cache_dir,
            boundaries=boundaries,
            boundary_colors=bcolors,
            boundary_labels=blabels,
            pois=pois or None,
        )

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        fut_to_idx = {pool.submit(_render_frame, f): i for i, f in enumerate(frames)}
        for fut in as_completed(fut_to_idx):
            detail_figs[fut_to_idx[fut]] = fut.result()

    # ── Assemble PDF ──────────────────────────────────────────────────────────
    waypoints = build_waypoints(processed, settings, pois=pois or None)
    tail_figs = [
        render_waypoint_table(waypoints, settings),
    ]
    if elev_points:
        tail_figs.append(render_elevation_profile_page(
            elev_points, processed.mile_markers, settings, pois=pois or None,
        ))
    tail_figs.append(render_disclaimer_page(settings, data_date=datetime.date.today().isoformat()))

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for fig in [overview_fig, *detail_figs, *tail_figs]:
            pdf.savefig(fig, bbox_inches="tight")
            fig.clf()   # release figure memory (Figure() objects aren't in pyplot registry)
    buf.seek(0)
    return buf


@app.post("/api/generate")
async def generate_pdf(req: GenerateRequest) -> StreamingResponse:
    """Run the full pipeline in a thread (keeps the event loop alive) and stream the PDF."""
    entry = _routes.get(req.route_id)
    if not entry:
        raise HTTPException(404, "Route not found — please re-upload the file.")

    try:
        settings = _make_settings(entry["path"], req)
    except Exception as exc:
        raise HTTPException(422, _user_error(exc))

    cache_dir = entry["path"].parent / ".trailpager_cache"
    cache_dir.mkdir(exist_ok=True)

    loop = asyncio.get_event_loop()
    try:
        buf = await loop.run_in_executor(None, _run_generation, settings, cache_dir)
    except Exception as exc:
        raise HTTPException(500, f"Generation failed: {exc}")

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="trail_map.pdf"'},
    )


_VALHALLA_URL = "https://valhalla1.openstreetmap.de/route"
_OSRM_URL = "https://router.project-osrm.org/route/v1/foot/{lon1},{lat1};{lon2},{lat2}?geometries=geojson&overview=full"

# If the routed distance exceeds this multiple of the straight-line distance,
# the router is going via roads rather than the trail.  Return a straight-line
# fallback so the map doesn't show a wild road detour.
_DETOUR_RATIO_THRESHOLD = 3.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _decode_polyline6(encoded: str) -> list[list[float]]:
    """Decode a Valhalla polyline6-encoded shape into [[lon, lat], ...] pairs."""
    coords: list[list[float]] = []
    index = lat = lng = 0
    while index < len(encoded):
        result = shift = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        lat += ~(result >> 1) if result & 1 else result >> 1
        result = shift = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1f) << shift
            shift += 5
            if b < 0x20:
                break
        lng += ~(result >> 1) if result & 1 else result >> 1
        coords.append([lng / 1e6, lat / 1e6])   # [lon, lat] for GeoJSON
    return coords


def _fetch_route_coords(
    start_lat: float, start_lon: float, end_lat: float, end_lon: float
) -> tuple[list[list[float]], float, bool]:
    """
    Return ([[lon, lat], ...], distance_m, detoured).

    Tries Valhalla pedestrian first; falls back to OSRM foot.
    If the best route is more than _DETOUR_RATIO_THRESHOLD × the straight-line
    distance, the router is going via roads instead of the trail.  In that case
    return a straight-line segment and set detoured=True so the caller can
    visually distinguish it.
    """
    straight_km = _haversine_km(start_lat, start_lon, end_lat, end_lon)

    def _check_detour(coords: list, distance_m: float) -> tuple[list, float, bool]:
        if straight_km > 0.05 and distance_m / 1000 / straight_km > _DETOUR_RATIO_THRESHOLD:
            straight_m = straight_km * 1000
            return [[start_lon, start_lat], [end_lon, end_lat]], straight_m, True
        return coords, distance_m, False

    # ── Valhalla (trail-aware) ────────────────────────────────────────────
    try:
        payload = {
            "locations": [
                {"lon": start_lon, "lat": start_lat},
                {"lon": end_lon,   "lat": end_lat},
            ],
            "costing": "pedestrian",
            "costing_options": {
                "pedestrian": {
                    "max_hiking_difficulty": 6,
                    "use_tracks": 1.0,
                    "walking_speed": 5.1,
                }
            },
            "shape_format": "geojson",
            "directions_options": {"units": "kilometers"},
        }
        resp = _requests.post(_VALHALLA_URL, json=payload, timeout=15)
        if resp.ok:
            data = resp.json()
            legs = data.get("trip", {}).get("legs", [])
            if legs:
                shape = legs[0]["shape"]
                if isinstance(shape, dict):           # geojson LineString
                    coords = shape["coordinates"]
                elif isinstance(shape, str):          # encoded polyline6 fallback
                    coords = _decode_polyline6(shape)
                else:
                    raise ValueError("Unexpected Valhalla shape format")
                distance_m = data["trip"]["summary"]["length"] * 1000
                return _check_detour(coords, distance_m)
    except Exception:
        pass   # fall through to OSRM

    # ── OSRM fallback ────────────────────────────────────────────────────
    url = _OSRM_URL.format(lon1=start_lon, lat1=start_lat, lon2=end_lon, lat2=end_lat)
    resp = _requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError("No route found between these points.")
    route = data["routes"][0]
    return _check_detour(route["geometry"]["coordinates"], route["distance"])


class CommitRequest(BaseModel):
    coordinates: list[list[float]]   # [[lon, lat], ...]


@app.post("/api/route-from-points")
async def route_from_points(req: PointsRequest) -> JSONResponse:
    """Generate a walking/hiking route between two coordinates."""
    start_lat, start_lon = req.start
    end_lat,   end_lon   = req.end

    try:
        coords, distance_m, detoured = _fetch_route_coords(start_lat, start_lon, end_lat, end_lon)
    except Exception as exc:
        raise HTTPException(502, f"Routing service unavailable: {exc}")

    geojson_fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"source": "routed", "distance_m": round(distance_m, 1)},
        }],
    }
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".geojson", mode="w")
    json.dump(geojson_fc, tmp)
    tmp.close()

    route_id = str(uuid.uuid4())
    _routes[route_id] = {"path": Path(tmp.name), "source": "generated"}

    bounds = [
        min(c[0] for c in coords), min(c[1] for c in coords),
        max(c[0] for c in coords), max(c[1] for c in coords),
    ]
    return JSONResponse({
        "route_id": route_id,
        "geojson": {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {},
        },
        "bounds": bounds,
        "default_start": req.start,
        "default_end":   req.end,
        "distance_m": round(distance_m, 1),
        "detoured": detoured,
        "warnings": [],
    })


@app.post("/api/route-segment")
async def route_segment(req: PointsRequest) -> JSONResponse:
    """Return routed coordinates for a single segment — no temp file created."""
    start_lat, start_lon = req.start
    end_lat,   end_lon   = req.end
    try:
        coords, distance_m, detoured = _fetch_route_coords(start_lat, start_lon, end_lat, end_lon)
    except Exception as exc:
        raise HTTPException(502, f"Routing service unavailable: {exc}")
    return JSONResponse({"coordinates": coords, "distance_m": round(distance_m, 1), "detoured": detoured})


@app.post("/api/route-commit")
async def route_commit(req: CommitRequest) -> JSONResponse:
    """Save an accumulated coordinate list as a GeoJSON route; return route_id."""
    if len(req.coordinates) < 2:
        raise HTTPException(422, "Route must have at least 2 coordinates.")

    geojson_fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": req.coordinates},
            "properties": {"source": "drawn"},
        }],
    }
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".geojson", mode="w")
    json.dump(geojson_fc, tmp)
    tmp.close()

    route_id = str(uuid.uuid4())
    _routes[route_id] = {"path": Path(tmp.name), "source": "drawn"}

    bounds = [
        min(c[0] for c in req.coordinates), min(c[1] for c in req.coordinates),
        max(c[0] for c in req.coordinates), max(c[1] for c in req.coordinates),
    ]
    return JSONResponse({"route_id": route_id, "bounds": bounds})


@app.get("/api/export/{route_id}/geojson")
async def export_geojson(route_id: str) -> StreamingResponse:
    """Download the stored route as GeoJSON."""
    entry = _routes.get(route_id)
    if not entry:
        raise HTTPException(404, "Route not found — re-upload or regenerate.")
    content = entry["path"].read_bytes()
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/geo+json",
        headers={"Content-Disposition": 'attachment; filename="route.geojson"'},
    )


@app.get("/api/export/{route_id}/gpx")
async def export_gpx(route_id: str) -> StreamingResponse:
    """Download the stored route as GPX."""
    entry = _routes.get(route_id)
    if not entry:
        raise HTTPException(404, "Route not found — re-upload or regenerate.")

    from trailpager.route.loader import load_route
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        route_data = load_route(entry["path"])

    coords = list(route_data.line.coords)  # (lon, lat)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="MyRoute" xmlns="http://www.topografix.com/GPX/1/1">',
        "  <trk><name>Trail Route</name><trkseg>",
    ]
    for lon, lat in coords:
        lines.append(f'    <trkpt lat="{lat:.6f}" lon="{lon:.6f}"></trkpt>')
    lines += ["  </trkseg></trk>", "</gpx>"]

    content = "\n".join(lines).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/gpx+xml",
        headers={"Content-Disposition": 'attachment; filename="route.gpx"'},
    )
