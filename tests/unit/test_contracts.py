from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from youth_compass.domain.contracts import (
    ColumnMapping,
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    MappingProposal,
    MetricMapping,
    PopulationScope,
    PublicationManifest,
    PublicationStatus,
    QualityReport,
    QualityStatus,
)


def test_dataset_grain_rejects_duplicate_dimensions() -> None:
    with pytest.raises(ValidationError, match="grain dimensions must be unique"):
        DatasetGrain(dimensions=["year", "district", "district"])


def test_column_mapping_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        ColumnMapping(
            source_column="area",
            target_field="district_name",
            transformation="normalize_district",
            confidence=1.1,
            evidence="Header and values match district aliases",
        )


def test_mapping_proposal_round_trip() -> None:
    proposal = MappingProposal(
        topic="employment",
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=["year", "district", "gender", "age_group"]),
        columns=[
            ColumnMapping(
                source_column="area",
                target_field="district_name",
                transformation="normalize_district",
                confidence=0.96,
                evidence="Values match the New Taipei district dictionary",
            )
        ],
        metrics=[
            MetricMapping(
                source_column="job_seekers",
                metric_code="job_seekers",
                unit_code="persons",
                population_scope=PopulationScope.YOUTH_SPECIFIC,
                aggregation_method="sum",
                confidence=0.9,
                evidence="Header and values indicate a count of people",
            )
        ],
        overall_confidence=0.93,
    )

    restored = MappingProposal.model_validate_json(proposal.model_dump_json())
    assert restored == proposal


def test_quality_report_enforces_row_count_consistency() -> None:
    report = QualityReport(
        status=QualityStatus.VALID,
        quality_score=1.0,
        rows_received=10,
        rows_accepted=9,
        rows_rejected=1,
    )
    assert report.rows_accepted == 9
    with pytest.raises(ValidationError, match="must equal rows_received"):
        QualityReport(
            status=QualityStatus.REJECTED,
            quality_score=0.5,
            rows_received=10,
            rows_accepted=9,
            rows_rejected=2,
        )


def test_dataset_metadata_requires_sha256() -> None:
    with pytest.raises(ValidationError):
        DatasetMetadata(
            dataset_id="population",
            version="v1",
            source_uri="data/source/population.csv",
            source_sha256="invalid",
            topic="population",
            dataset_role=DatasetRole.FACT,
            grain=DatasetGrain(dimensions=["year", "district"]),
            population_scope=PopulationScope.YOUTH_SPECIFIC,
            status=DatasetStatus.RECEIVED,
            quality_score=0.0,
            created_at=datetime.now(UTC),
        )


def test_publication_manifest_enforces_lineage_counts() -> None:
    quality = QualityReport(
        status=QualityStatus.VALID,
        quality_score=1.0,
        rows_received=2,
        rows_accepted=2,
        rows_rejected=0,
    )
    manifest = PublicationManifest(
        dataset_id="population",
        dataset_version="version-1",
        topic="population",
        source_uri="data/source/population.csv",
        source_sha256="a" * 64,
        mapping_version="mapping-v1",
        transformation_version="canonical-v1",
        approved_by="reviewer",
        status=PublicationStatus.PUBLISHED,
        output_uri="data/curated/population/version=1",
        parquet_uri="data/curated/population/version=1/part-000.parquet",
        rows_received=2,
        rows_accepted=2,
        rows_filtered_out=1,
        rows_filtered_youth=1,
        rows_filtered_totals=0,
        rows_rejected=0,
        observation_count=1,
        estimated_observation_count=1,
        quality=quality,
    )
    assert manifest.approved_by == "reviewer"

    with pytest.raises(ValidationError, match="filtered rows cannot exceed accepted rows"):
        PublicationManifest.model_validate({**manifest.model_dump(), "rows_filtered_out": 3})
