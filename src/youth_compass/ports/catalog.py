"""DataCatalog port.

Stage 1 proposal originating from the AWS workstream. The backend workstream may
amend these signatures; see docs/12-aws-stage1-foundation.md for the amendment
procedure. Signatures transcribed from docs/01-system-architecture.md section 5.2.
"""

from typing import Protocol, runtime_checkable

from youth_compass.domain.contracts import DatasetMetadata
from youth_compass.domain.profiles import DatasetProfile


@runtime_checkable
class DataCatalog(Protocol):
    """Registry of dataset versions and their canonical metadata."""

    def register(self, dataset: DatasetMetadata) -> None:
        """Register ``dataset``, replacing any record with the same identifier.

        Registering the same identifier twice leaves exactly one retrievable
        record, carrying the later field values.
        """
        ...

    def get(self, dataset_id: str) -> DatasetMetadata:
        """Return the metadata registered under ``dataset_id``.

        Raises:
            DatasetNotFoundError: no dataset is registered under ``dataset_id``.
        """
        ...

    def search_compatible(self, profile: DatasetProfile) -> list[DatasetMetadata]:
        """Return registered datasets whose grain is compatible with ``profile``."""
        ...

    def list_datasets(self) -> list[DatasetMetadata]:
        """Return one visible record per dataset, preferring its published version."""
        ...

    def list_versions(self, dataset_id: str) -> list[DatasetMetadata]:
        """Return every registered version of ``dataset_id``, oldest first."""
        ...
