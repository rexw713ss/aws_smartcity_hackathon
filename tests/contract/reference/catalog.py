"""In-memory DataCatalog reference implementation."""

from collections.abc import Iterator
from contextlib import contextmanager

from tests.contract.registry import register_catalog
from youth_compass.domain.contracts import DatasetMetadata
from youth_compass.domain.errors import DatasetNotFoundError
from youth_compass.domain.profiles import DatasetProfile
from youth_compass.ports import DataCatalog


class InMemoryDataCatalog:
    """Upserts by ``dataset_id``; ``search_compatible`` matches on grain."""

    def __init__(self) -> None:
        self._records: dict[str, DatasetMetadata] = {}

    def register(self, dataset: DatasetMetadata) -> None:
        self._records[dataset.dataset_id] = dataset

    def get(self, dataset_id: str) -> DatasetMetadata:
        try:
            return self._records[dataset_id]
        except KeyError as exc:
            raise DatasetNotFoundError(dataset_id) from exc

    def search_compatible(self, profile: DatasetProfile) -> list[DatasetMetadata]:
        wanted = set(profile.candidate_grain)
        if not wanted:
            return list(self._records.values())
        return [
            record
            for record in self._records.values()
            if wanted.issubset(set(record.grain.dimensions))
        ]


@register_catalog("reference")
@contextmanager
def _reference_catalog() -> Iterator[DataCatalog]:
    yield InMemoryDataCatalog()
