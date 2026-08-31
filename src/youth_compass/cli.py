"""Command-line entrypoints for offline development and operations."""

from pathlib import Path
from typing import Annotated

import typer

from youth_compass.config import load_settings
from youth_compass.ingestion import CsvProfileOptions, profile_csv
from youth_compass.mapping import MappingOptions, MappingProposalError, analyze_mapping

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
    _emit_json(report.model_dump_json(indent=2), output, "Profile")


@app.command("map")
def map_dataset(
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
    topic: Annotated[
        str | None,
        typer.Option(help="Override deterministic topic inference."),
    ] = None,
) -> None:
    """Profile a CSV, propose a canonical mapping, and validate it."""

    settings = load_settings()
    profile_options = CsvProfileOptions(
        sample_value_limit=settings.profile.sample_value_limit,
        distinct_value_cap=settings.profile.distinct_value_cap,
        duplicate_check_limit=settings.profile.duplicate_check_limit,
        max_rows=max_rows,
    )
    report = profile_csv(source, profile_options)
    try:
        analysis = analyze_mapping(report, MappingOptions(topic_hint=topic))
    except MappingProposalError as error:
        raise typer.BadParameter(str(error), param_hint="source") from error
    _emit_json(analysis.model_dump_json(indent=2), output, "Mapping analysis")


def _emit_json(payload: str, output: Path | None, label: str) -> None:
    if output is None:
        typer.echo(payload)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{payload}\n", encoding="utf-8")
    typer.echo(f"{label} written to {output}", err=True)


if __name__ == "__main__":
    app()
