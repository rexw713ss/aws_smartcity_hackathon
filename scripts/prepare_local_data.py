"""Prepare the repository's core sources through the local approval workflow.

Run from the repository root. Without --approve, files stop at the review gate.
Re-running skips datasets whose current source and published Parquet both exist.
"""

import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from apps.api.dependencies import LocalRuntime
from scripts.collect_official_statistics import SOURCES as SUPPLEMENTAL_SOURCES
from youth_compass.config import CatalogProvider, QueryProvider, load_settings
from youth_compass.domain.contracts import DatasetStatus
from youth_compass.ports import ApprovalDecision, JobStatus

SOURCES = {
    "population": Path("01_人口/_全部年度_全區.csv"),
    "education": Path("02b_教育程度_含年齡/_全部年度_全區.csv"),
    "employment": Path("10_失業率_年齡別/_全部年度_全市.csv"),
}


def prepare_sources(
    runtime: LocalRuntime,
    source_root: Path,
    *,
    approve: bool,
    reviewed_by: str,
    include_supplemental: bool = False,
) -> bool:
    """Return true only when every source is published or ready for review."""
    if approve and not reviewed_by.strip():
        raise ValueError("--reviewed-by is required with --approve")
    available = {item.dataset_id: item for item in runtime.catalog.list_datasets()}
    complete = True
    sources = dict(SOURCES)
    if include_supplemental:
        sources.update(
            {item.topic: Path(item.folder) / "_全部年度_全市.csv" for item in SUPPLEMENTAL_SOURCES}
        )
    for topic, relative_path in sources.items():
        source = source_root / relative_path
        if not source.is_file():
            print(f"{topic}: missing source {source}", flush=True)
            complete = False
            continue
        checksum = hashlib.sha256(source.read_bytes()).hexdigest()
        current = available.get(topic)
        if current is not None and current.status is DatasetStatus.PUBLISHED:
            parquet = (
                runtime.data_root
                / "curated"
                / topic
                / f"version={current.version}"
                / "part-000.parquet"
            )
            if current.source_sha256 == checksum and parquet.is_file():
                print(f"{topic}: already published ({current.version})", flush=True)
                continue
        print(f"{topic}: profiling {source} ...", flush=True)
        reference = runtime.workflow.submit_file(
            source, submitted_by=reviewed_by or "local-setup", topic_hint=topic
        )
        job = runtime.workflow.get_job(reference.job_id)
        print(f"{topic}: {job.status.value}; job={job.job_id}", flush=True)
        if job.status is not JobStatus.AWAITING_APPROVAL:
            complete = False
            continue
        if not approve:
            print(f"Review: http://127.0.0.1:5173/?review={job.job_id}", flush=True)
            continue
        print(
            f"{topic}: transforming approved source (this can take a few minutes) ...", flush=True
        )
        runtime.workflow.resume_after_approval(
            job.job_id,
            ApprovalDecision(
                approved=True,
                decided_by=reviewed_by,
                decided_at=datetime.now(UTC),
                notes="Repository source approved via prepare_local_data --approve",
            ),
        )
        job = runtime.workflow.get_job(job.job_id)
        print(f"{topic}: {job.status.value}", flush=True)
        if job.status is not JobStatus.PUBLISHED:
            complete = False
            if job.manifest is not None:
                for issue in job.manifest.quality.issues:
                    print(f"  {issue.code}: {issue.message}", flush=True)
        elif job.manifest is None or not Path(job.manifest.parquet_uri).is_file():
            print(f"{topic}: published Parquet is missing; restore the data or use a new data root")
            complete = False
    return complete


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, help="Defaults to the API's configured data root")
    parser.add_argument("--source-root", type=Path, default=Path("data/source"))
    parser.add_argument("--approve", action="store_true", help="Explicitly approve these sources")
    parser.add_argument(
        "--include-supplemental", action="store_true", help="Include collected official statistics"
    )
    parser.add_argument(
        "--reviewed-by", default="", help="Reviewer recorded in the publication audit"
    )
    args = parser.parse_args()
    if args.approve and not args.reviewed_by.strip():
        parser.error("--reviewed-by is required with --approve")
    settings = load_settings()
    if (
        settings.environment != "local"
        or settings.catalog is None
        or settings.catalog.provider is not CatalogProvider.SQLITE
        or settings.query is None
        or settings.query.provider is not QueryProvider.DUCKDB
    ):
        parser.error("Use this script only with the local SQLite/DuckDB runtime; AWS uses uploads")
    runtime = LocalRuntime(args.data_root or settings.data_root, settings)
    print(f"API data root: {runtime.data_root}", flush=True)
    if not prepare_sources(
        runtime,
        args.source_root,
        approve=args.approve,
        reviewed_by=args.reviewed_by.strip(),
        include_supplemental=args.include_supplemental,
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
