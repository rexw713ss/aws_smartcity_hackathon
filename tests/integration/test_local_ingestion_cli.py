import json
from pathlib import Path

from typer.testing import CliRunner

from adapters.local.cli import app


def test_cli_submit_status_and_approve_across_invocations(tmp_path: Path) -> None:
    source = tmp_path / "population.csv"
    source.write_text(
        "year,district,age,population\n2025,板橋區,20-24,100\n",
        encoding="utf-8",
    )
    data_root = tmp_path / "data"
    runner = CliRunner()

    submitted = runner.invoke(
        app,
        [
            "submit",
            str(source),
            "--submitted-by",
            "uploader@example.com",
            "--data-root",
            str(data_root),
        ],
    )
    assert submitted.exit_code == 0, submitted.output
    reference = json.loads(submitted.output)
    assert reference["status"] == "awaiting_approval"

    status = runner.invoke(
        app,
        ["status", reference["job_id"], "--data-root", str(data_root)],
    )
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["mapping_analysis"]["validation"]["valid"] is True

    approved = runner.invoke(
        app,
        [
            "decide",
            reference["job_id"],
            "--approve",
            "--decided-by",
            "reviewer@example.com",
            "--data-root",
            str(data_root),
        ],
    )
    assert approved.exit_code == 0, approved.output
    result = json.loads(approved.output)
    assert result["status"] == "published"
    assert Path(result["manifest"]["parquet_uri"]).is_file()
