"""Export versioned JSON Schemas from the canonical Pydantic contracts."""

import json
from pathlib import Path

from pydantic import BaseModel

from youth_compass.domain.contracts import (
    DatasetMetadata,
    MappingAnalysis,
    MappingProposal,
    QualityReport,
)
from youth_compass.domain.profiles import DatasetProfile

OUTPUT_DIR = Path("contracts/canonical")
CONTRACTS: dict[str, type[BaseModel]] = {
    "dataset-metadata.schema.json": DatasetMetadata,
    "dataset-profile.schema.json": DatasetProfile,
    "mapping-proposal.schema.json": MappingProposal,
    "mapping-analysis.schema.json": MappingAnalysis,
    "quality-report.schema.json": QualityReport,
}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for file_name, model in CONTRACTS.items():
        payload = json.dumps(
            model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True
        )
        (OUTPUT_DIR / file_name).write_text(f"{payload}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
