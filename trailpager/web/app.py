from __future__ import annotations

import io
import json
import tempfile
import uuid
import warnings
from pathlib import Path

import requests as _requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from trailpager.config import Settings

app = FastAPI(title="TrailPager")

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
        },
        layers=layers,
        output={"path": "output/web_generated.pdf"},
    )


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

    settings = _make_settings(entry["path"], req)

    from trailpager.pagination.paginator import paginate
    from trailpager.route.pipeline import process_route

    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            processed = process_route(settings)
        caught_warnings = [str(x.message) for x in w]
    except Exception as exc:
        raise HTTPException(422, str(exc))

    page_w_m, page_h_m = settings.page_ground_size_m
    frames = paginate(
        processed.line_proj, page_w_m, page_h_m,
        settings.map.overlap_m, settings.map.margin_m,
    )

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


@app.post("/api/generate")
async def generate_pdf(req: GenerateRequest) -> StreamingResponse:
    """Run the full pipeline and stream the PDF."""
    import datetime

    entry = _routes.get(req.route_id)
    if not entry:
        raise HTTPException(404, "Route not found — please re-upload the file.")

    settings = _make_settings(entry["path"], req)
    cache_dir = entry["path"].parent / ".trailpager_cache"
    cache_dir.mkdir(exist_ok=True)

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

    try:
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
                pois = fetch_pois(
                    processed.line_proj, processed.crs_proj, wgs_bounds, cache_dir
                )

        elev_points: list = []
        if settings.layers.elevation_profile:
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                elev_points = sample_route_elevation(
                    processed.line_proj, processed.crs_proj,
                    processed.length_m, cache_dir=cache_dir,
                )

        figures = []
        figures.append(render_overview_page(
            processed.line_proj, frames, settings,
            cache_dir=cache_dir,
            mile_markers=processed.mile_markers,
            boundaries=boundaries,
            boundary_colors=bcolors,
            boundary_labels=blabels,
            pois=pois or None,
        ))
        for frame in frames:
            figures.append(render_detail_page(
                frame, processed.line_proj, processed.mile_markers, settings,
                total_pages=len(frames),
                cache_dir=cache_dir,
                boundaries=boundaries,
                boundary_colors=bcolors,
                boundary_labels=blabels,
                pois=pois or None,
            ))

        waypoints = build_waypoints(processed, settings, pois=pois or None)
        figures.append(render_waypoint_table(waypoints, settings))

        if elev_points:
            figures.append(render_elevation_profile_page(
                elev_points, processed.mile_markers, settings, pois=pois or None,
            ))

        figures.append(render_disclaimer_page(settings, data_date=datetime.date.today().isoformat()))

        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
        buf = io.BytesIO()
        with PdfPages(buf) as pdf:
            for fig in figures:
                pdf.savefig(fig, bbox_inches="tight")
                plt.close(fig)
        buf.seek(0)

    except Exception as exc:
        raise HTTPException(500, f"Generation failed: {exc}")

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="trail_map.pdf"'},
    )


_OSRM_URL = "https://router.project-osrm.org/route/v1/foot/{lon1},{lat1};{lon2},{lat2}?geometries=geojson&overview=full"


@app.post("/api/route-from-points")
async def route_from_points(req: PointsRequest) -> JSONResponse:
    """Generate a walking/hiking route between two coordinates via OSRM."""
    start_lat, start_lon = req.start
    end_lat,   end_lon   = req.end

    url = _OSRM_URL.format(
        lon1=start_lon, lat1=start_lat,
        lon2=end_lon,   lat2=end_lat,
    )
    try:
        resp = _requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        raise HTTPException(502, f"Routing service unavailable: {exc}")

    if data.get("code") != "Ok" or not data.get("routes"):
        raise HTTPException(422, "No route found between these points. Try moving the markers closer to a trail.")

    route = data["routes"][0]
    coords = route["geometry"]["coordinates"]   # [[lon, lat], ...]
    distance_m = route["distance"]

    # Write as a GeoJSON FeatureCollection so load_route can read it
    geojson_fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"source": "osrm", "distance_m": round(distance_m, 1)},
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
    geojson_feature = {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {},
    }
    return JSONResponse({
        "route_id": route_id,
        "geojson": geojson_feature,
        "bounds": bounds,
        "default_start": req.start,
        "default_end":   req.end,
        "distance_m": round(distance_m, 1),
        "warnings": [],
    })


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
        '<gpx version="1.1" creator="TrailPager" xmlns="http://www.topografix.com/GPX/1/1">',
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
