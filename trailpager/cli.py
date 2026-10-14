from __future__ import annotations

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
        f"[bold]Scale:[/bold]  1:{settings.map.scale:,}  "
        f"  [bold]Page:[/bold] {settings.map.page_size} {settings.map.orientation}"
    )
    console.print(f"[bold]Output:[/bold] {settings.output.path}\n")

    if dry_run:
        console.print("[yellow]Dry run — no files written.[/yellow]")
        return

    from trailpager.route.pipeline import process_route

    console.print("Loading and trimming route…")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        processed = process_route(settings)

    for w in caught:
        console.print(f"  [yellow]⚠  {w.message}[/yellow]")

    console.print(
        f"  Length:  [bold]{processed.length_m:,.0f} m[/bold] = "
        f"[bold]{processed.length_miles:.2f} miles[/bold]"
    )
    console.print(f"  Vertices (trimmed): {len(processed.line_wgs84.coords):,}")

    start_lat, start_lon = settings.route.start
    end_lat,   end_lon   = settings.route.end
    _snap_line("Start", start_lat, start_lon, processed.snap_start_offset_m)
    _snap_line("End  ", end_lat,   end_lon,   processed.snap_end_offset_m)

    n = len(processed.mile_markers)
    console.print(
        f"\n  Mile markers: [bold]{n}[/bold]  "
        f"(mile 0 – {n - 1})"
    )

    console.print("\n[dim]Render pipeline not yet wired — coming in Milestone 3+.[/dim]")


def _snap_line(label: str, lat: float, lon: float, offset_m: float) -> None:
    flag = "  [red]⚠  >500 m — check coordinates[/red]" if offset_m > 500 else ""
    console.print(
        f"  Snap {label}: ({lat:.4f}°N, {abs(lon):.4f}°W) → offset [bold]{offset_m:.0f} m[/bold]{flag}"
    )
