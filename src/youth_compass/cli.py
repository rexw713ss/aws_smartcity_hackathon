"""Command-line entrypoints for offline development and operations."""

from pathlib import Path
from typing import Annotated

import typer

from youth_compass.config import load_settings
from youth_compass.ingestion import CsvProfileOptions, profile_csv
from youth_compass.mapping import MappingOptions, MappingProposalError, analyze_mapping
from youth_compass.transformation import (
    TransformOptions,
    run_csv_transformation,
)

app = typer.Typer(
    name="youth-compass",
    help="Offline-first data onboarding tools for New Taipei Youth Policy.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Run offline New Taipei Youth Policy utilities."""


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


@app.command("transform")
def transform_dataset(
    source: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True),
    ],
    approved_by: Annotated[
        str,
        typer.Option(
            "--approved-by",
            help="Reviewer identity authorizing deterministic publication.",
        ),
    ],
    dataset_id: Annotated[
        str | None,
        typer.Option(help="Stable ASCII dataset identifier; defaults to inferred topic."),
    ] = None,
    topic: Annotated[
        str | None,
        typer.Option(help="Override deterministic topic inference."),
    ] = None,
    max_rows: Annotated[
        int | None,
        typer.Option(help="Create an explicitly versioned sample publication."),
    ] = None,
    output_root: Annotated[
        Path | None,
        typer.Option(help="Curated output root; defaults to data/curated."),
    ] = None,
    quarantine_root: Annotated[
        Path | None,
        typer.Option(help="Quarantine root; defaults to data/quarantined."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Also write the manifest JSON to this file."),
    ] = None,
) -> None:
    """Transform an approved mapping and publish or quarantine versioned Parquet."""

    settings = load_settings()
    try:
        options = TransformOptions(
            approved_by=approved_by,
            curated_root=output_root or settings.data_root / "curated",
            quarantine_root=quarantine_root or settings.data_root / "quarantined",
            dataset_id=dataset_id,
            topic_hint=topic,
            max_rows=max_rows,
            batch_size=settings.transform.batch_size,
            max_rejection_rate=settings.transform.max_rejection_rate,
            transformation_version=settings.transform.transformation_version,
        )
        manifest = run_csv_transformation(source, options)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="source") from error
    _emit_json(manifest.model_dump_json(indent=2), output, "Publication manifest")


def _emit_json(payload: str, output: Path | None, label: str) -> None:
    if output is None:
        typer.echo(payload)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(f"{payload}\n", encoding="utf-8")
    typer.echo(f"{label} written to {output}", err=True)


if __name__ == "__main__":
    app()
