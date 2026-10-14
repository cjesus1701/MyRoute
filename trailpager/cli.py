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
    from trailpager.layers.waypoints import build_waypoints
    from trailpager.pagination.paginator import paginate
    from trailpager.pdf import assemble_pdf
    from trailpager.render.disclaimer import render_disclaimer_page
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

    # ── 3. Boundaries ─────────────────────────────────────────────────────────
    cache_dir = config.parent / ".tile_cache"
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

    # ── 4. Render ─────────────────────────────────────────────────────────────
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
        ))

    # ── 5. Waypoint table + disclaimer ───────────────────────────────────────
    waypoints = build_waypoints(processed, settings)
    console.print(f"\nBuilding waypoint table ({len(waypoints)} waypoints)…")
    figures.append(render_waypoint_table(waypoints, settings))

    data_date = datetime.date.today().isoformat()
    figures.append(render_disclaimer_page(settings, data_date=data_date))

    # ── 6. Assemble PDF ───────────────────────────────────────────────────────
    console.print(f"\nAssembling PDF ({len(figures)} pages)…")
    assemble_pdf(figures, settings.output.path)
    console.print(f"[green]Saved → {settings.output.path}[/green]")


def _snap_line(label: str, lat: float, lon: float, offset_m: float) -> None:
    flag = "  [red]⚠  >500 m[/red]" if offset_m > 500 else ""
    console.print(
        f"  Snap {label}: ({lat:.4f}°N, {abs(lon):.4f}°W)"
        f" → offset [bold]{offset_m:.0f} m[/bold]{flag}"
    )
