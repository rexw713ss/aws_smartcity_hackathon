"""Glue + DynamoDB DataCatalog adapter.

Feature: aws-stage2-adapters, Requirement 3.

Schemas in Glue, app metadata (approval status, quality score, mapping version,
published-version pointer) in DynamoDB. The published-version pointer enables
rollback by repointing rather than deleting.
"""

import boto3
import botocore.exceptions

from youth_compass.domain.contracts import DatasetMetadata
from youth_compass.domain.errors import DatasetNotFoundError
from youth_compass.domain.profiles import DatasetProfile


class GlueCatalog:
    """DataCatalog backed by Glue + DynamoDB."""

    def __init__(
        self,
        database: str,
        table_name: str,
        region: str = "ap-northeast-1",
    ) -> None:
        self._database = database
        self._table_name = table_name
        self._glue = boto3.client("glue", region_name=region)
        self._ddb = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def register(self, dataset: DatasetMetadata) -> None:
        """Upsert into Glue and DynamoDB."""
        # Glue table (column schema placeholder — real columns TBD by the ingestion step)
        try:
            self._glue.create_table(
                DatabaseName=self._database,
                TableInput={
                    "Name": dataset.dataset_id,
                    "StorageDescriptor": {
                        "Columns": [{"Name": "placeholder", "Type": "string"}],
                    },
                },
            )
        except botocore.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "AlreadyExistsException":
                self._glue.update_table(
                    DatabaseName=self._database,
                    TableInput={
                        "Name": dataset.dataset_id,
                        "StorageDescriptor": {
                            "Columns": [{"Name": "placeholder", "Type": "string"}],
                        },
                    },
                )
            else:
                raise DatasetNotFoundError(dataset.dataset_id) from exc

        # DynamoDB item (full metadata serialized as JSON attributes)
        self._ddb.put_item(
            Item={
                "dataset_id": dataset.dataset_id,
                "version": dataset.version,
                "metadata_json": dataset.model_dump_json(),
                "quality_score": str(dataset.quality_score),
                "status": dataset.status.value if dataset.status else "unknown",
            }
        )
        # Published-version pointer: a special item that tracks which version is live.
        self._ddb.put_item(
            Item={
                "dataset_id": dataset.dataset_id,
                "version": "__published__",
                "published_version": dataset.version,
            }
        )

    def get(self, dataset_id: str) -> DatasetMetadata:
        """Get by looking up the published version pointer, then the full record."""
        try:
            pointer = self._ddb.get_item(Key={"dataset_id": dataset_id, "version": "__published__"})
            if "Item" not in pointer:
                raise DatasetNotFoundError(dataset_id)
            published_version = pointer["Item"]["published_version"]
            record = self._ddb.get_item(
                Key={"dataset_id": dataset_id, "version": published_version}
            )
            if "Item" not in record:
                raise DatasetNotFoundError(dataset_id)
            return DatasetMetadata.model_validate_json(record["Item"]["metadata_json"])
        except botocore.exceptions.ClientError as exc:
            raise DatasetNotFoundError(dataset_id) from exc

    def search_compatible(self, profile: DatasetProfile) -> list[DatasetMetadata]:
        """Scan for datasets whose grain is compatible with the profile."""
        wanted = set(profile.candidate_grain)
        results: list[DatasetMetadata] = []
        response = self._ddb.scan()
        for item in response.get("Items", []):
            if item.get("version") == "__published__":
                continue
            if "metadata_json" not in item:
                continue
            metadata = DatasetMetadata.model_validate_json(item["metadata_json"])
            if not wanted or wanted.issubset(set(metadata.grain.dimensions)):
                results.append(metadata)
        return results
