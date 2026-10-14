from __future__ import annotations

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
@click.option("--dry-run", is_flag=True, help="Print page count and scale without rendering.")
@click.option("--verbose", "-v", is_flag=True)
def generate(config: Path, dry_run: bool, verbose: bool) -> None:
    """Generate a PDF map for the configured route."""
    settings = load_settings(config)

    if verbose:
        console.print(settings.model_dump())

    console.print(f"[bold]Route:[/bold] {settings.route.file}")
    console.print(
        f"[bold]Scale:[/bold] 1:{settings.map.scale:,}  "
        f"[bold]Page:[/bold] {settings.map.page_size} {settings.map.orientation}"
    )
    console.print(f"[bold]Output:[/bold] {settings.output.path}")

    if dry_run:
        console.print("[yellow]Dry run — no files written.[/yellow]")
        return

    console.print("[dim]Pipeline not yet wired — scaffold only.[/dim]")
