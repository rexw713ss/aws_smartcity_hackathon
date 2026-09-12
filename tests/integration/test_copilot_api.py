"""Copilot API executes against an immutable local feature snapshot."""

from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from adapters.local import FeatureParquetMaterializer
from apps.api.main import create_app
from youth_compass.acquisition import AcquiredSource, DataAcquisitionService
from youth_compass.decisioning import (
    DEFAULT_FEATURES,
    FeatureEvidence,
    FeatureRegistry,
    FeatureValue,
)
from youth_compass.domain import (
    DatasetGrain,
    DatasetMetadata,
)
from youth_compass.domain.contracts import DatasetRole, DatasetStatus, PopulationScope
from youth_compass.ports import DataRequirement, SourceCandidate


class _PopulationSourceConnector:
    candidate = SourceCandidate(
        candidate_id="ntpc-population",
        connector_id="test_sources",
        title="New Taipei population",
        publisher="New Taipei City Government",
        download_url="https://data.example.gov.tw/population.csv",
        file_name="population.csv",
        source_format="csv",
        topic_terms=("population",),
        metric_codes=("population_count",),
    )

    def discover(self, requirement: DataRequirement) -> tuple[SourceCandidate, ...]:
        return (self.candidate,) if "population_count" in requirement.metric_codes else ()

    def get(self, candidate_id: str) -> SourceCandidate | None:
        return self.candidate if candidate_id == self.candidate.candidate_id else None

    def fetch(self, candidate: SourceCandidate) -> AcquiredSource:
        return AcquiredSource(
            candidate=candidate,
            content=(b"year,district_code,district_name,population\n2025,banqiao,Banqiao,100\n"),
            retrieved_at=datetime(2026, 9, 12, tzinfo=UTC),
        )


def _feature(entity: str, code: str, value: float) -> FeatureValue:
    return FeatureValue(
        entity_id=entity,
        feature_code=code,
        value=value,
        observed_at=datetime(2026, 9, 1, tzinfo=UTC),
        evidence=(
            FeatureEvidence(
                dataset_id=f"{code}_source",
                dataset_version="v1",
                source_uri=f"s3://curated/{code}/v1",
                quality_score=0.95,
                retrieved_at=datetime(2026, 9, 2, tzinfo=UTC),
            ),
        ),
    )


def _write_home_features(data_root: Path) -> None:
    values = [
        _feature(entity, code, value)
        for entity, readings in {
            "banqiao": {
                "property_cost": 80,
                "transit_accessibility": 90,
                "amenity_accessibility": 90,
                "environmental_risk": 20,
            },
            "linkou": {
                "property_cost": 60,
                "transit_accessibility": 60,
                "amenity_accessibility": 50,
                "environmental_risk": 50,
            },
        }.items()
        for code, value in readings.items()
    ]
    FeatureParquetMaterializer(FeatureRegistry(DEFAULT_FEATURES)).materialize(
        values,
        data_root / "features" / "current.parquet",
    )


def _write_population_observations(data_root: Path) -> DatasetMetadata:
    destination = data_root / "curated" / "youth_population" / "version=v1"
    destination.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "year_gregorian": [2023, 2024, 2025, 2023, 2024, 2025],
                "month": [None] * 6,
                "city_code": ["ntpc"] * 6,
                "city_name": ["New Taipei City"] * 6,
                "district_code": ["banqiao"] * 3 + ["linkou"] * 3,
                "district_name": ["Banqiao"] * 3 + ["Linkou"] * 3,
                "metric_code": ["population_count"] * 6,
                "unit_code": ["persons"] * 6,
                "population_scope": ["youth_specific"] * 6,
                "is_estimated": [False] * 6,
                "metric_value": [100.0, 110.0, 120.0, 80.0, 76.0, 72.0],
            }
        ),
        destination / "part-000.parquet",
    )
    return DatasetMetadata(
        dataset_id="youth_population",
        version="v1",
        source_uri="fileobj://incoming/youth-population.csv",
        source_sha256="a" * 64,
        topic="population",
        dataset_role=DatasetRole.FACT,
        grain=DatasetGrain(dimensions=["year_gregorian", "district_code"]),
        population_scope=PopulationScope.YOUTH_SPECIFIC,
        status=DatasetStatus.PUBLISHED,
        quality_score=0.98,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        published_at=datetime(2026, 9, 2, tzinfo=UTC),
    )


def _write_population_forecast(data_root: Path) -> None:
    destination = data_root / "forecasts" / "current.parquet"
    destination.parent.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "metric_code": ["population_count"] * 4,
                "district_code": ["banqiao", "banqiao", "linkou", "linkou"],
                "year_gregorian": [2027, 2028, 2027, 2028],
                "value": [121.0, 122.0, 71.0, 70.0],
                "lower": [115.0, 116.0, 65.0, 64.0],
                "upper": [127.0, 128.0, 77.0, 76.0],
                "model_version": ["seasonal-naive-v1"] * 4,
                "generated_at": [datetime(2026, 9, 1, tzinfo=UTC)] * 4,
            }
        ),
        destination,
    )


def test_copilot_query_returns_grounded_ranking(tmp_path: Path) -> None:
    _write_home_features(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/v1/copilot/query",
        json={"question": "Tôi nên mua nhà ở đâu?", "entityIds": ["banqiao", "linkou"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["plan"]["profile_code"] == "home_buying"
    assert body["candidates"][0]["entity_id"] == "banqiao"
    assert body["citations"]
    assert [item["type"] for item in body["visualizations"]] == [
        "ranking_bar",
        "contribution_bar",
        "data_table",
    ]
    assert "source_uri" not in response.text


def test_copilot_refuses_when_feature_snapshot_is_missing(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/v1/copilot/query",
        json={"question": "Where should I place an EV charger?"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_data"


def test_missing_dataset_can_start_approval_gated_acquisition(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    runtime = app.state.runtime
    runtime.acquisition = DataAcquisitionService((_PopulationSourceConnector(),), runtime.workflow)
    runtime._copilot_service = None
    client = TestClient(app)

    query = client.post(
        "/api/v1/copilot/query",
        json={"question": "Compare population trend from 2023 to 2025"},
    )

    assert query.status_code == 200
    assert query.json()["status"] == "acquisition_required"
    assert query.json()["source_candidates"][0]["candidate_id"] == "ntpc-population"
    assert query.json()["visualizations"][0]["visualization_id"] == "source-candidates-table"

    started = client.post(
        "/api/v1/copilot/acquisitions",
        json={"candidateId": "ntpc-population", "submittedBy": "reviewer@example.com"},
    )

    assert started.status_code == 202
    assert started.json()["ingestion_status"] == "awaiting_approval"
    job_id = started.json()["ingestion_job_id"]
    status_response = client.get(f"/api/v1/ingestion-jobs/{job_id}")
    assert status_response.json()["status"] == "awaiting_approval"


def test_copilot_capabilities_are_discoverable(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/v1/copilot/capabilities")

    assert response.status_code == 200
    assert {item["name"] for item in response.json()} == {
        "acquire_source",
        "discover_sources",
        "search_catalog",
        "get_features",
        "rank_candidates",
        "explain_lineage",
        "inspect_dataset",
        "query_observations",
        "compare_entities",
        "forecast_metric",
    }


def test_copilot_compares_generic_observation_trends(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    app.state.runtime.catalog.register(_write_population_observations(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/api/v1/copilot/query",
        json={
            "question": "So sánh xu hướng dân số từ 2023 đến 2025",
            "entityIds": ["banqiao", "linkou"],
            "minQualityScore": 0.9,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["dataset_inspection"]["metric_code"] == "population_count"
    assert body["routed_plan"]["missing_operations"] == []
    changes = {item["entity_id"]: item for item in body["comparison"]["changes"]}
    assert changes["banqiao"]["percent_change"] == 20.0
    assert changes["linkou"]["percent_change"] == -10.0
    assert [item["tool"] for item in body["tool_trace"]] == [
        "query_decomposer",
        "search_catalog",
        "inspect_dataset",
        "query_observations",
        "compare_entities",
        "explain_lineage",
        "answer_composer",
        "visualization_builder",
    ]
    assert [item["type"] for item in body["visualizations"]] == [
        "line",
        "comparison_bar",
        "data_table",
    ]
    assert body["citations"][0]["dataset_version"] == "v1"
    assert "source_uri" not in response.text


def test_copilot_fails_closed_when_requested_entity_is_missing(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    app.state.runtime.catalog.register(_write_population_observations(tmp_path))
    client = TestClient(app)

    response = client.post(
        "/api/v1/copilot/query",
        json={
            "question": "Compare population trend from 2023 to 2025",
            "entityIds": ["unknown-district"],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_data"
    assert "unknown-district" in response.json()["warnings"][0]


def test_copilot_returns_published_forecast_with_intervals(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    app.state.runtime.catalog.register(_write_population_observations(tmp_path))
    _write_population_forecast(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/v1/copilot/query",
        json={
            "question": "Forecast youth population for the next 2 years",
            "entityIds": ["banqiao", "linkou"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["forecast_result"]["model_version"] == "seasonal-naive-v1"
    assert len(body["forecast_result"]["points"]) == 4
    assert body["routed_plan"]["missing_operations"] == []
    assert [item["tool"] for item in body["tool_trace"]] == [
        "query_decomposer",
        "search_catalog",
        "inspect_dataset",
        "forecast_metric",
        "explain_lineage",
        "answer_composer",
        "visualization_builder",
    ]
    assert body["visualizations"][0]["rows"][0]["lower"] == 115.0
    assert "source_uri" not in response.text
