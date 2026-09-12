"""Materialize deterministic demo values for both reference decision profiles."""

from datetime import UTC, datetime
from pathlib import Path

from adapters.local import FeatureParquetMaterializer
from youth_compass.decisioning import (
    DEFAULT_FEATURES,
    FeatureEvidence,
    FeatureRegistry,
    FeatureValue,
)

OUTPUT = Path("data/features/current.parquet")
_OBSERVED_AT = datetime(2026, 9, 1, tzinfo=UTC)
_RETRIEVED_AT = datetime(2026, 9, 12, tzinfo=UTC)

_HOME = {
    "banqiao": {
        "property_cost": 82,
        "transit_accessibility": 94,
        "amenity_accessibility": 91,
        "environmental_risk": 32,
    },
    "linkou": {
        "property_cost": 61,
        "transit_accessibility": 73,
        "amenity_accessibility": 70,
        "environmental_risk": 24,
    },
    "xindian": {
        "property_cost": 76,
        "transit_accessibility": 84,
        "amenity_accessibility": 83,
        "environmental_risk": 41,
    },
}

_CHARGERS = {
    "site-banqiao-station": {
        "ev_demand_proxy": 92,
        "transit_accessibility": 95,
        "parking_availability": 58,
        "grid_accessibility": 78,
        "charger_competition": 64,
        "site_feasibility": 1,
    },
    "site-linkou-center": {
        "ev_demand_proxy": 77,
        "transit_accessibility": 68,
        "parking_availability": 89,
        "grid_accessibility": 91,
        "charger_competition": 35,
        "site_feasibility": 1,
    },
    "site-xindian-river": {
        "ev_demand_proxy": 84,
        "transit_accessibility": 81,
        "parking_availability": 72,
        "grid_accessibility": 54,
        "charger_competition": 28,
        "site_feasibility": 0,
    },
}


def main() -> None:
    """Create the immutable demo snapshot once."""

    if OUTPUT.exists():
        print(f"Feature snapshot already exists: {OUTPUT}")
        return
    values = [
        _value(entity_id, feature_code, value)
        for candidates in (_HOME, _CHARGERS)
        for entity_id, readings in candidates.items()
        for feature_code, value in readings.items()
    ]
    FeatureParquetMaterializer(FeatureRegistry(DEFAULT_FEATURES)).materialize(values, OUTPUT)
    print(f"Wrote {len(values)} grounded demo feature values to {OUTPUT}")


def _value(entity_id: str, feature_code: str, value: float) -> FeatureValue:
    return FeatureValue(
        entity_id=entity_id,
        feature_code=feature_code,
        value=value,
        observed_at=_OBSERVED_AT,
        evidence=(
            FeatureEvidence(
                dataset_id=f"demo_{feature_code}",
                dataset_version="2026-09-demo",
                source_uri=f"demo://curated/{feature_code}/2026-09",
                quality_score=0.9,
                retrieved_at=_RETRIEVED_AT,
            ),
        ),
    )


if __name__ == "__main__":
    main()
