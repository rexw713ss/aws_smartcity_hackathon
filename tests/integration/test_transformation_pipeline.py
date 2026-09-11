from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from youth_compass.transformation import (
    TransformationError,
    TransformOptions,
    run_csv_transformation,
)


def _options(tmp_path: Path, **overrides: object) -> TransformOptions:
    defaults: dict[str, object] = {
        "approved_by": "test-reviewer",
        "curated_root": tmp_path / "curated",
        "quarantine_root": tmp_path / "quarantined",
        "batch_size": 100,
    }
    defaults.update(overrides)
    return TransformOptions(**defaults)  # type: ignore[arg-type]


def test_transform_publishes_weighted_canonical_parquet_and_is_idempotent(
    tmp_path: Path,
) -> None:
    source = tmp_path / "employment.csv"
    source.write_text(
        "stat_year,area,age_group,sex,job_seekers\n"
        "115,板橋,15-19,M,100\n"
        "115,板橋,20-24,F,200\n"
        "115,板橋,40-44,F,500\n",
        encoding="utf-8",
    )
    options = _options(tmp_path)

    manifest = run_csv_transformation(source, options)

    assert manifest.status == "published"
    assert manifest.rows_received == 3
    assert manifest.rows_accepted == 3
    assert manifest.rows_filtered_out == 1
    assert manifest.rows_filtered_youth == 1
    assert manifest.rows_filtered_totals == 0
    assert manifest.rows_rejected == 0
    assert manifest.observation_count == 2
    assert manifest.estimated_observation_count == 1
    assert manifest.quality.status == "warning"
    table = pq.read_table(manifest.parquet_uri)
    assert table.num_rows == 2
    assert table.column("year_roc").to_pylist() == [115, 115]
    assert table.column("year_gregorian").to_pylist() == [2026, 2026]
    assert table.column("district_code").to_pylist() == ["01", "01"]
    assert table.column("gender_code").to_pylist() == ["male", "female"]
    assert table.column("metric_value_original").to_pylist() == [100.0, 200.0]
    assert table.column("metric_value").to_pylist() == [40.0, 200.0]
    assert table.column("is_estimated").to_pylist() == [True, False]

    reused = run_csv_transformation(source, options)

    assert reused.reused is True
    assert reused.output_uri == manifest.output_uri
    assert reused.created_at == manifest.created_at

    upgraded = run_csv_transformation(
        source,
        _options(tmp_path, transformation_version="canonical-v2"),
    )
    assert upgraded.reused is False
    assert upgraded.dataset_version != manifest.dataset_version
    assert upgraded.output_uri != manifest.output_uri


def test_transform_quarantines_excessive_row_rejections(tmp_path: Path) -> None:
    source = tmp_path / "unknown-district.csv"
    source.write_text(
        "year,district,age,population\n2025,板橋區,20-24,100\n2025,Atlantis,25-29,50\n",
        encoding="utf-8",
    )

    manifest = run_csv_transformation(source, _options(tmp_path))

    assert manifest.status == "quarantined"
    assert manifest.rows_rejected == 1
    assert manifest.quality.status == "rejected"
    assert "ROW_REJECTIONS" in {issue.code for issue in manifest.quality.issues}
    assert manifest.rejected_rows_uri is not None
    rejected = pq.read_table(manifest.rejected_rows_uri)
    assert rejected.column("source_row_number").to_pylist() == [3]
    assert rejected.column("error_code").to_pylist() == ["UNKNOWN_DISTRICT"]


def test_transform_can_publish_below_configured_rejection_threshold(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tolerated-rejection.csv"
    source.write_text(
        "year,district,age,population\n2025,板橋區,20-24,100\n2025,Atlantis,25-29,50\n",
        encoding="utf-8",
    )

    manifest = run_csv_transformation(
        source,
        _options(tmp_path, max_rejection_rate=0.5),
    )

    assert manifest.status == "published"
    assert manifest.quality.status == "warning"
    assert manifest.quality.quality_score == 0.5


def test_transform_removes_verified_total_rows_from_declared_grain(
    tmp_path: Path,
) -> None:
    source = tmp_path / "migration.csv"
    source.write_text(
        "year,month,district,gender,direction,counterpart_region,count\n"
        "2025,1,板橋區,F,inbound,桃園市,20\n"
        "2025,1,板橋區,F,inbound,total,20\n",
        encoding="utf-8",
    )

    manifest = run_csv_transformation(
        source,
        _options(tmp_path, topic_hint="migration"),
    )

    assert manifest.status == "published"
    assert manifest.rows_filtered_totals == 1
    assert manifest.rows_filtered_youth == 0
    assert manifest.observation_count == 1


def test_transform_quarantines_duplicate_declared_grain(tmp_path: Path) -> None:
    source = tmp_path / "duplicates.csv"
    source.write_text(
        "year,district,age,population\n2025,板橋區,20-24,100\n2025,板橋區,20-24,100\n",
        encoding="utf-8",
    )

    manifest = run_csv_transformation(source, _options(tmp_path))

    assert manifest.status == "quarantined"
    issue = next(issue for issue in manifest.quality.issues if issue.code == "DUPLICATE_GRAIN")
    assert issue.blocking is True
    assert issue.row_count == 1


def test_transform_quarantines_when_every_row_is_outside_youth_range(
    tmp_path: Path,
) -> None:
    source = tmp_path / "no-youth.csv"
    source.write_text(
        "year,district,age,population\n2025,板橋區,40-44,100\n",
        encoding="utf-8",
    )

    manifest = run_csv_transformation(source, _options(tmp_path))

    assert manifest.status == "quarantined"
    assert manifest.rows_filtered_youth == 1
    assert manifest.observation_count == 0
    assert "NO_PUBLISHABLE_OBSERVATIONS" in {issue.code for issue in manifest.quality.issues}


def test_transform_stops_before_writing_when_mapping_is_invalid(tmp_path: Path) -> None:
    source = tmp_path / "unknown-unit.csv"
    source.write_text(
        "year,district,age,value\n2025,板橋區,20-24,100\n",
        encoding="utf-8",
    )

    with pytest.raises(TransformationError, match="UNKNOWN_METRIC_UNIT"):
        run_csv_transformation(source, _options(tmp_path))

    assert not (tmp_path / "curated").exists()
    assert not (tmp_path / "quarantined").exists()


def test_sample_publication_has_distinct_explicit_version(tmp_path: Path) -> None:
    source = tmp_path / "sample.csv"
    source.write_text(
        "year,district,age,population\n2025,板橋區,20-24,100\n2025,三重區,20-24,80\n",
        encoding="utf-8",
    )

    manifest = run_csv_transformation(source, _options(tmp_path, max_rows=1))

    assert manifest.is_sample is True
    assert manifest.dataset_version.endswith("sample1")
    assert manifest.rows_received == 1
