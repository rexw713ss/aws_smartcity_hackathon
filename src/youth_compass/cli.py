"""Command-line entrypoints for offline development and operations."""

from pathlib import Path
from typing import Annotated

import typer

from youth_compass.config import load_settings
from youth_compass.ingestion import CsvProfileOptions, profile_csv

app = typer.Typer(
    name="youth-compass",
    help="Offline-first data onboarding tools for New Taipei Youth Compass.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Run offline New Taipei Youth Compass utilities."""


@app.command()
def profile(
    source: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write JSON to a file instead of stdout."),
    ] = None,
    max_rows: Annotated[
        int | None,
        typer.Option(help="Optionally stop after this many data rows."),
    ] = None,
) -> None:
    """Profile an unknown CSV and emit a validated JSON report."""

    settings = load_settings()
    options = CsvProfileOptions(
        sample_value_limit=settings.profile.sample_value_limit,
        distinct_value_cap=settings.profile.distinct_value_cap,
        duplicate_check_limit=settings.profile.duplicate_check_limit,
        max_rows=max_rows,
    )
    report = profile_csv(source, options)
    payload = report.model_dump_json(indent=2)
    if output is None:
        typer.echo(payload)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{payload}\n", encoding="utf-8")
    typer.echo(f"Profile written to {output}", err=True)


if __name__ == "__main__":
    app()
