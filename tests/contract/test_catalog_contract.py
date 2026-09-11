"""DataCatalog contract.

Feature: aws-stage1-foundation
Properties 8 (unknown id raises), 9 (register round-trip and upsert).
"""

from datetime import UTC, datetime

import pytest

from youth_compass.domain.contracts import (
    DatasetGrain,
    DatasetMetadata,
    DatasetRole,
    DatasetStatus,
    PopulationScope,
)
from youth_compass.domain.errors import DatasetNotFoundError
from youth_compass.ports import DataCatalog

_SHA = "a" * 64


def _metadata(dataset_id: str, quality: float, dims: list[str]) -> DatasetMetadata:
    return DatasetMetadata(
        dataset_id=dataset_id,
        version="2026-09-12T000000Z",
        source_uri="mem://incoming/file.csv",
        source_sha256=_SHA,
        topic="population",
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=dims),
        population_scope=PopulationScope.YOUTH_SPECIFIC,
        status=DatasetStatus.PUBLISHED,
        quality_score=quality,
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
    )


class TestDataCatalogContract:
    def test_property_9_register_then_get_field_equality(self, catalog: DataCatalog) -> None:
        record = _metadata("ds-1", 0.9, ["year_gregorian", "district_code"])
        catalog.register(record)
        assert catalog.get("ds-1") == record

    def test_property_9_reregistration_upserts_to_one_record(self, catalog: DataCatalog) -> None:
        catalog.register(_metadata("ds-1", 0.5, ["year_gregorian"]))
        catalog.register(_metadata("ds-1", 0.95, ["year_gregorian"]))
        got = catalog.get("ds-1")
        assert got.quality_score == 0.95

    def test_property_8_unknown_id_raises_domain_error(self, catalog: DataCatalog) -> None:
        with pytest.raises(DatasetNotFoundError):
            catalog.get("does-not-exist")
