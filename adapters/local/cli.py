"""Command-line composition root for the durable offline ingestion workflow."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from adapters.local.filesystem_store import FileSystemObjectStore
from adapters.local.source_adapter import LocalTabularSourceAdapter
from adapters.local.sqlite_catalog import SQLiteCatalog
from adapters.local.sqlite_checkpoint import SQLiteCheckpointStore
from adapters.local.system_clock import SystemClock
from youth_compass.application import LocalIngestionWorkflow, LocalWorkflowOptions
from youth_compass.config import load_settings
from youth_compass.domain.errors import YouthCompassError
from youth_compass.ports import ApprovalDecision

app = typer.Typer(
    name="youth-compass-local",
    help="Durable offline ingestion with an explicit human-approval boundary.",
    no_args_is_help=True,
)


@app.command("submit")
def submit(
    source: Annotated[
        Path,
        typer.Argument(exists=True, file_okay=True, dir_okay=False, readable=True),
    ],
    submitted_by: Annotated[str, typer.Option("--submitted-by")],
    topic: Annotated[
        str | None,
        typer.Option(help="Override deterministic topic inference."),
    ] = None,
    data_root: Annotated[Path, typer.Option(help="Local durable data root.")] = Path("data"),
) -> None:
    """Store and analyze one CSV, stopping before transformation for review."""

    workflow = _build_workflow(data_root)
    try:
        reference = workflow.submit_file(
            source,
            submitted_by=submitted_by,
            topic_hint=topic,
        )
    except (YouthCompassError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="source") from exc
    typer.echo(reference.model_dump_json(indent=2))


@app.command("status")
def status(
    job_id: Annotated[str, typer.Argument()],
    data_root: Annotated[Path, typer.Option(help="Local durable data root.")] = Path("data"),
) -> None:
    """Show the mapping proposal and latest durable state for a job."""

    try:
        job = _build_workflow(data_root).get_job(job_id)
    except YouthCompassError as exc:
        raise typer.BadParameter(str(exc), param_hint="job_id") from exc
    typer.echo(job.model_dump_json(indent=2))


@app.command("decide")
def decide(
    job_id: Annotated[str, typer.Argument()],
    decided_by: Annotated[str, typer.Option("--decided-by")],
    approve: Annotated[
        bool,
        typer.Option("--approve/--reject", help="Approve publication or reject the proposal."),
    ],
    notes: Annotated[str | None, typer.Option(help="Optional reviewer notes.")] = None,
    data_root: Annotated[Path, typer.Option(help="Local durable data root.")] = Path("data"),
) -> None:
    """Settle a paused job exactly once, then display the resulting state."""

    workflow = _build_workflow(data_root)
    try:
        workflow.resume_after_approval(
            job_id,
            ApprovalDecision(
                approved=approve,
                decided_by=decided_by,
                decided_at=datetime.now(UTC),
                notes=notes,
            ),
        )
        job = workflow.get_job(job_id)
    except (YouthCompassError, ValueError) as exc:
        raise typer.BadParameter(str(exc), param_hint="job_id") from exc
    typer.echo(job.model_dump_json(indent=2))


def _build_workflow(data_root: Path) -> LocalIngestionWorkflow:
    settings = load_settings()
    metadata_database = data_root / "metadata" / "youth-compass.sqlite3"
    return LocalIngestionWorkflow(
        object_store=FileSystemObjectStore(data_root / "incoming"),
        catalog=SQLiteCatalog(metadata_database),
        checkpoints=SQLiteCheckpointStore(metadata_database),
        clock=SystemClock(),
        source_adapter=LocalTabularSourceAdapter(),
        options=LocalWorkflowOptions(
            curated_root=data_root / "curated",
            quarantine_root=data_root / "quarantined",
            batch_size=settings.transform.batch_size,
            max_rejection_rate=settings.transform.max_rejection_rate,
            transformation_version=settings.transform.transformation_version,
        ),
    )


if __name__ == "__main__":
    app()
