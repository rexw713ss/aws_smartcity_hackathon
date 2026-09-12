"""Copilot API executes against an immutable local feature snapshot."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from adapters.local import FeatureParquetMaterializer
from apps.api.main import create_app
from youth_compass.decisioning import (
    DEFAULT_FEATURES,
    FeatureEvidence,
    FeatureRegistry,
    FeatureValue,
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
    assert "source_uri" not in response.text


def test_copilot_refuses_when_feature_snapshot_is_missing(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/v1/copilot/query",
        json={"question": "Where should I place an EV charger?"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_data"


def test_copilot_capabilities_are_discoverable(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.get("/api/v1/copilot/capabilities")

    assert response.status_code == 200
    assert {item["name"] for item in response.json()} == {
        "search_catalog",
        "get_features",
        "rank_candidates",
        "explain_lineage",
    }
