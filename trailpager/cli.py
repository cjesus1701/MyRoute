from __future__ import annotations

import datetime
import warnings
from pathlib import Path

import click
from rich.console import Console

from trailpager.config import load_settings

console = Console()


@click.group()
def main() -> None:
    """TrailPager — generate printable PDF trail maps."""


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address.")
@click.option("--port", default=8000, show_default=True, help="Port to listen on.")
@click.option("--open/--no-open", "open_browser", default=True, show_default=True, help="Open browser on start.")
def serve(host: str, port: int, open_browser: bool) -> None:
    """Start the TrailPager web interface."""
    import threading
    import time
    import webbrowser

    import uvicorn

    url = f"http://{host}:{port}"
    console.print(f"[bold]TrailPager[/bold] → {url}")
    console.print("Press [bold]Ctrl+C[/bold] to stop.\n")

    if open_browser:
        def _open():
            time.sleep(0.8)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    from trailpager.web.app import app as web_app
    uvicorn.run(web_app, host=host, port=port, log_level="warning")


@main.command()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    default="settings.toml",
    show_default=True,
    help="Path to settings TOML file.",
)
@click.option("--dry-run", is_flag=True, help="Print settings summary without rendering.")
@click.option("--verbose", "-v", is_flag=True)
def generate(config: Path, dry_run: bool, verbose: bool) -> None:
    """Generate a PDF map for the configured route."""
    settings = load_settings(config)

    if verbose:
        console.print(settings.model_dump())

    console.print(f"[bold]Route:[/bold]  {settings.route.file}")
    console.print(
        f"[bold]Scale:[/bold]  1:{settings.map.scale:,}"
        f"   [bold]Page:[/bold] {settings.map.page_size} {settings.map.orientation}"
    )
    console.print(f"[bold]Output:[/bold] {settings.output.path}\n")

    if dry_run:
        console.print("[yellow]Dry run — no files written.[/yellow]")
        return

    from trailpager.layers.boundaries import fetch_boundary_layers
    from trailpager.layers.elevation import sample_route_elevation
    from trailpager.layers.pois import fetch_pois
    from trailpager.layers.waypoints import build_waypoints
    from trailpager.pagination.paginator import paginate
    from trailpager.pdf import assemble_pdf
    from trailpager.render.disclaimer import render_disclaimer_page
    from trailpager.render.elevation_profile import render_elevation_profile_page
    from trailpager.render.overview import render_overview_page
    from trailpager.render.page import render_detail_page
    from trailpager.render.waypoint_table import render_waypoint_table
    from trailpager.route.pipeline import process_route

    # ── 1. Process route ──────────────────────────────────────────────────────
    console.print("Loading and trimming route…")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        processed = process_route(settings)
    for w in caught:
        console.print(f"  [yellow]⚠  {w.message}[/yellow]")

    console.print(
        f"  Length:  [bold]{processed.length_m:,.0f} m[/bold] ="
        f" [bold]{processed.length_miles:.2f} miles[/bold]"
    )
    start_lat, start_lon = settings.route.start
    end_lat,   end_lon   = settings.route.end
    _snap_line("Start", start_lat, start_lon, processed.snap_start_offset_m)
    _snap_line("End  ", end_lat,   end_lon,   processed.snap_end_offset_m)

    # ── 2. Paginate ───────────────────────────────────────────────────────────
    console.print("\nPaginating…")
    page_w_m, page_h_m = settings.page_ground_size_m
    frames = paginate(
        processed.line_proj,
        page_w_m, page_h_m,
        settings.map.overlap_m,
        settings.map.margin_m,
    )
    console.print(
        f"  [bold]{len(frames)} detail page(s)[/bold]"
        f"  ({page_w_m:.0f} × {page_h_m:.0f} m  |  overlap {settings.map.overlap_m:.0f} m)"
    )
    for f in frames:
        console.print(
            f"    Page {f.page_number}: mile"
            f" {f.route_start_dist / 1609.344:.1f} –"
            f" {f.route_end_dist / 1609.344:.1f}"
        )

    cache_dir = config.parent / ".tile_cache"

    # ── 3. Boundaries ─────────────────────────────────────────────────────────
    console.print("\nFetching boundary data…")
    wgs_bounds = processed.line_wgs84.bounds  # (minx, miny, maxx, maxy)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        boundaries, bcolors, blabels = fetch_boundary_layers(settings, wgs_bounds, cache_dir)
    for w in caught:
        console.print(f"  [yellow]⚠  {w.message}[/yellow]")
    for gdf, lbl in zip(boundaries, blabels):
        status = f"{len(gdf)} feature(s)" if not gdf.empty else "unavailable"
        console.print(f"  {lbl}: {status}")

    # ── 4. POIs ───────────────────────────────────────────────────────────────
    pois: list = []
    if settings.layers.pois:
        console.print("\nFetching shelters and water sources…")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            pois = fetch_pois(processed.line_proj, processed.crs_proj, wgs_bounds, cache_dir)
        for w in caught:
            console.print(f"  [yellow]⚠  {w.message}[/yellow]")
        shelters = sum(1 for p in pois if p.kind == "shelter")
        water    = sum(1 for p in pois if p.kind != "shelter")
        console.print(f"  {shelters} shelter(s), {water} water source(s)")

    # ── 5. Elevation profile ──────────────────────────────────────────────────
    elev_points: list = []
    if settings.layers.elevation_profile:
        console.print("\nFetching elevation data…")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            elev_points = sample_route_elevation(
                processed.line_proj, processed.crs_proj,
                processed.length_m, cache_dir=cache_dir,
            )
        for w in caught:
            console.print(f"  [yellow]⚠  {w.message}[/yellow]")
        if elev_points:
            console.print(f"  {len(elev_points)} elevation samples")

    # ── 6. Render ─────────────────────────────────────────────────────────────
    console.print("\nRendering…")
    figures = []

    console.print("  Overview page…")
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
        console.print(f"  Page {frame.page_number}/{len(frames)}…")
        figures.append(render_detail_page(
            frame, processed.line_proj, processed.mile_markers, settings,
            total_pages=len(frames),
            cache_dir=cache_dir,
            boundaries=boundaries,
            boundary_colors=bcolors,
            boundary_labels=blabels,
            pois=pois or None,
        ))

    # ── 7. Waypoint table + elevation profile + disclaimer ────────────────────
    waypoints = build_waypoints(processed, settings, pois=pois or None)
    console.print(f"\nBuilding waypoint table ({len(waypoints)} waypoints)…")
    figures.append(render_waypoint_table(waypoints, settings))

    if elev_points:
        console.print("  Elevation profile…")
        figures.append(render_elevation_profile_page(
            elev_points, processed.mile_markers, settings, pois=pois or None,
        ))

    data_date = datetime.date.today().isoformat()
    figures.append(render_disclaimer_page(settings, data_date=data_date))

    # ── 8. Assemble PDF ───────────────────────────────────────────────────────
    console.print(f"\nAssembling PDF ({len(figures)} pages)…")
    assemble_pdf(figures, settings.output.path)
    console.print(f"[green]Saved → {settings.output.path}[/green]")


def _snap_line(label: str, lat: float, lon: float, offset_m: float) -> None:
    flag = "  [red]⚠  >500 m[/red]" if offset_m > 500 else ""
    console.print(
        f"  Snap {label}: ({lat:.4f}°N, {abs(lon):.4f}°W)"
        f" → offset [bold]{offset_m:.0f} m[/bold]{flag}"
    )
