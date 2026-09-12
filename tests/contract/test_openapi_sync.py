import json
from pathlib import Path

from apps.api.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_generated_openapi_contract_matches_application(tmp_path: Path) -> None:
    committed = json.loads((ROOT / "contracts" / "api" / "openapi.json").read_text())
    generated = create_app(tmp_path / "data").openapi()

    assert committed == generated
