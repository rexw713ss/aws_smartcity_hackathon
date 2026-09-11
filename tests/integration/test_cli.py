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


def test_map_command_writes_profile_proposal_and_validation(tmp_path: Path) -> None:
    output = tmp_path / "mapping-analysis.json"
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["map", "tests/fixtures/employment_unfamiliar.csv", "--output", str(output)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["profile"]["row_count"] == 5
    assert payload["proposal"]["topic"] == "employment"
    assert payload["proposal"]["metrics"][0]["metric_code"] == "job_seekers"
    assert payload["validation"]["valid"] is True
    assert payload["validation"]["requires_human_approval"] is True


def test_map_command_accepts_topic_override() -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["map", "tests/fixtures/employment_unfamiliar.csv", "--topic", "custom"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["proposal"]["topic"] == "custom"


def test_map_command_reports_unmappable_schema_without_traceback(tmp_path: Path) -> None:
    source = tmp_path / "unmappable.csv"
    source.write_text("opaque_label,value\nalpha,10\n", encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(app, ["map", str(source)])

    assert result.exit_code == 2
    assert "No canonical grain dimensions could be inferred" in result.output
    assert "Traceback" not in result.output


def test_transform_command_requires_explicit_reviewer() -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["transform", "tests/fixtures/employment_unfamiliar.csv"],
    )

    assert result.exit_code == 2
    assert "--approved-by" in result.output


def test_transform_command_emits_manifest(tmp_path: Path) -> None:
    source = tmp_path / "population.csv"
    source.write_text(
        "year,district,age,population\n2025,板橋區,20-24,100\n",
        encoding="utf-8",
    )
    output = tmp_path / "manifest-output.json"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "transform",
            str(source),
            "--approved-by",
            "cli-reviewer",
            "--output-root",
            str(tmp_path / "curated"),
            "--quarantine-root",
            str(tmp_path / "quarantined"),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "published"
    assert payload["approved_by"] == "cli-reviewer"
    assert Path(payload["parquet_uri"]).is_file()
