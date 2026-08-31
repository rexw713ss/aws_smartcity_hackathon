import json
from pathlib import Path

from typer.testing import CliRunner

from youth_compass.cli import app


def test_profile_command_writes_valid_json(tmp_path: Path) -> None:
    output = tmp_path / "profile.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["profile", "tests/fixtures/employment_unfamiliar.csv", "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["row_count"] == 5
    assert payload["file_format"] == "csv"
