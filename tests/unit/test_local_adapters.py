from datetime import UTC, datetime
from pathlib import Path

from adapters.local import FileSystemObjectStore, SQLiteCatalog, SQLiteCheckpointStore
from youth_compass.domain.contracts import (
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    PopulationScope,
)
from youth_compass.ports import WorkflowCheckpoint


def _metadata(version: str, status: DatasetStatus) -> DatasetMetadata:
    return DatasetMetadata(
        dataset_id="population",
        version=version,
        source_uri="fileobj://incoming/source.csv",
        source_sha256="a" * 64,
        topic="population",
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=["year_gregorian", "district_code"]),
        population_scope=PopulationScope.YOUTH_SPECIFIC,
        status=status,
        quality_score=0.95,
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
    )


def test_filesystem_store_persists_across_instances_and_preserves_long_keys(
    tmp_path: Path,
) -> None:
    root = tmp_path / "objects"
    key = f"incoming/{'x' * 300}.csv"
    first = FileSystemObjectStore(root)

    uri = first.put(key, b"source", {"uploader": "tester"})
    second = FileSystemObjectStore(root)

    assert second.get(uri) == b"source"
    assert second.list("incoming/") == [key]


def test_sqlite_catalog_only_advances_pointer_for_published_version(tmp_path: Path) -> None:
    catalog = SQLiteCatalog(tmp_path / "catalog.sqlite3")
    catalog.register(_metadata("v1", DatasetStatus.PUBLISHED))
    catalog.register(_metadata("v2", DatasetStatus.QUARANTINED))

    assert catalog.published_version("population") == "v1"
    assert catalog.get("population").version == "v1"
    assert [record.version for record in catalog.list_versions("population")] == ["v1", "v2"]
    assert catalog.get_version("population", "v2").status is DatasetStatus.QUARANTINED
    assert [record.version for record in catalog.list_datasets()] == ["v1"]


def test_sqlite_checkpoint_survives_adapter_restart(tmp_path: Path) -> None:
    database = tmp_path / "workflow.sqlite3"
    checkpoint = WorkflowCheckpoint(
        workflow_id="job-1",
        node="awaiting_approval",
        state={"status": "awaiting_approval"},
        saved_at=datetime(2026, 9, 12, tzinfo=UTC),
    )
    SQLiteCheckpointStore(database).save("job-1", checkpoint)

    assert SQLiteCheckpointStore(database).load("job-1") == checkpoint
