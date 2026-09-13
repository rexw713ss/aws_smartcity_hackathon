import asyncio
import hashlib
import json
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from apps.api.main import create_app


def _excel_population() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["year", "district", "age", "population"])
    sheet.append([2025, "板橋區", "20-24", 100])
    sheet.append([2025, "林口區", "20-24", 50])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _pdf_population() -> bytes:
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=letter)
    table = Table(
        [
            ["year", "district_code", "age", "population"],
            ["2025", "01", "20-24", "100"],
            ["2025", "17", "20-24", "50"],
        ],
        colWidths=[90, 110, 90, 100],
    )
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
    document.build([table])
    return output.getvalue()


def test_reviewer_to_dashboard_vertical_slice_hides_local_paths(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = create_app(tmp_path / "data")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            uploaded = await client.post(
                "/api/v1/datasets/upload",
                files={
                    "file": (
                        "population.csv",
                        "year,district,age,population\n2025,板橋區,20-24,100\n",
                        "text/csv",
                    )
                },
                data={"submitted_by": "uploader@example.com"},
            )
            assert uploaded.status_code == 202, uploaded.text
            reference = uploaded.json()
            assert reference["status"] == "awaiting_approval"
            job_id = reference["jobId"]

            status_response = await client.get(f"/api/v1/ingestion-jobs/{job_id}")
            assert status_response.status_code == 200
            assert status_response.json()["currentStep"] == "awaiting_approval"
            assert str(tmp_path) not in status_response.text

            mapping = await client.get(f"/api/v1/ingestion-jobs/{job_id}/mapping")
            assert mapping.status_code == 200
            assert mapping.json()["validation"]["valid"] is True
            assert mapping.json()["profile"]["source_path"] == "population.csv"
            assert str(tmp_path) not in mapping.text

            preview = await client.get(f"/api/v1/ingestion-jobs/{job_id}/mapping-preview")
            assert preview.status_code == 200
            previews = {item["sourceColumn"]: item for item in preview.json()}
            assert previews["year"]["samples"][0]["source"] == "2025"
            assert previews["year"]["samples"][0]["canonical"] == {
                "year_gregorian": 2025,
                "year_roc": 114,
            }
            assert previews["district"]["samples"][0]["canonical"] == {
                "district_code": "01",
                "district_name": "板橋區",
            }
            assert str(tmp_path) not in preview.text

            approved = await client.post(
                f"/api/v1/ingestion-jobs/{job_id}/decision",
                json={
                    "decision": "approve",
                    "decidedBy": "reviewer@example.com",
                    "comment": "district and unit verified",
                },
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "published"
            assert str(tmp_path) not in approved.text

            quality = await client.get(f"/api/v1/ingestion-jobs/{job_id}/quality-report")
            assert quality.status_code == 200
            assert quality.json()["publicationStatus"] == "published"
            assert "parquetUri" not in quality.text

            datasets = await client.get("/api/v1/datasets")
            assert datasets.status_code == 200
            assert datasets.json()[0]["datasetId"] == "population"
            assert "sourceUri" not in datasets.text

            lineage = await client.get("/api/v1/datasets/population/lineage")
            assert lineage.status_code == 200
            assert len(lineage.json()["sourceSha256"]) == 64
            assert "sourceUri" not in lineage.text

            summary = await client.get(
                "/api/v1/city/summary",
                params={"datasetId": "population", "metricCode": "population_count"},
            )
            assert summary.status_code == 200, summary.text
            assert summary.json()["value"] == 100.0
            assert summary.json()["period"] == "2025"
            assert summary.json()["datasetVersion"]

            districts = await client.get(
                "/api/v1/districts",
                params={"datasetId": "population", "metricCode": "population_count"},
            )
            assert districts.status_code == 200
            assert districts.json()["districts"][0]["districtCode"] == "01"

            district = await client.get(
                "/api/v1/districts/01/profile",
                params={"datasetId": "population", "metricCode": "population_count"},
            )
            assert district.status_code == 200, district.text
            assert district.json()["districts"][0]["districtName"] == "板橋區"

            compared = await client.post(
                "/api/v1/districts/compare",
                json={
                    "datasetId": "population",
                    "districtCodes": ["01"],
                    "metricCode": "population_count",
                },
            )
            assert compared.status_code == 200
            assert compared.json()["districts"][0]["value"] == 100.0

    asyncio.run(scenario())


def test_api_returns_stable_error_envelope(tmp_path: Path) -> None:
    async def request() -> httpx.Response:
        app = create_app(tmp_path / "data")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/v1/ingestion-jobs/missing")

    response = asyncio.run(request())

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "WORKFLOW_NOT_FOUND"
    assert payload["error"]["traceId"].startswith("trc_")
    assert json.dumps(payload).find(str(tmp_path)) == -1


def test_openapi_contains_reviewer_and_dashboard_contracts(tmp_path: Path) -> None:
    paths = create_app(tmp_path / "data").openapi()["paths"]

    assert "/api/v1/datasets/upload" in paths
    assert "/api/v1/ingestion-jobs/{job_id}/decision" in paths
    assert "/api/v1/city/summary" in paths
    assert "/api/v1/districts" in paths
    assert "/api/v1/districts/compare" in paths


def test_request_validation_uses_error_envelope(tmp_path: Path) -> None:
    async def request() -> httpx.Response:
        app = create_app(tmp_path / "data")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/v1/datasets/upload")

    response = asyncio.run(request())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert response.json()["error"]["details"]


@pytest.mark.parametrize(
    ("file_name", "content", "source_format"),
    [
        (
            "population.json",
            json.dumps(
                [
                    {
                        "year": 2025,
                        "district": "板橋區",
                        "age": "20-24",
                        "population": 100,
                    },
                    {
                        "year": 2025,
                        "district": "林口區",
                        "age": "20-24",
                        "population": 50,
                    },
                ],
                ensure_ascii=False,
            ).encode(),
            "json",
        ),
        ("population.xlsx", _excel_population(), "excel"),
        ("population.pdf", _pdf_population(), "pdf"),
    ],
)
def test_non_csv_sources_reuse_the_complete_review_and_analytics_flow(
    tmp_path: Path,
    file_name: str,
    content: bytes,
    source_format: str,
) -> None:
    async def scenario() -> None:
        app = create_app(tmp_path / "data")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            uploaded = await client.post(
                "/api/v1/datasets/upload",
                files={"file": (file_name, content)},
                data={"submitted_by": "reviewer@example.com", "topic_hint": "population"},
            )
            assert uploaded.status_code == 202, uploaded.text
            job_id = uploaded.json()["jobId"]

            job = await client.get(f"/api/v1/ingestion-jobs/{job_id}")
            assert job.status_code == 200
            assert job.json()["sourceFormat"] == source_format

            mapping = await client.get(f"/api/v1/ingestion-jobs/{job_id}/mapping")
            assert mapping.status_code == 200
            assert mapping.json()["profile"]["file_format"] == source_format
            assert mapping.json()["proposal"]["metrics"][0]["metric_code"] == "population_count"

            approved = await client.post(
                f"/api/v1/ingestion-jobs/{job_id}/decision",
                json={"decision": "approve", "decidedBy": "reviewer@example.com"},
            )
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "published"

            summary = await client.get(
                "/api/v1/city/summary",
                params={"datasetId": "population", "metricCode": "population_count"},
            )
            assert summary.status_code == 200, summary.text
            assert summary.json()["value"] == 150

            lineage = await client.get("/api/v1/datasets/population/lineage")
            assert lineage.json()["sourceSha256"] == hashlib.sha256(content).hexdigest()

    asyncio.run(scenario())


def test_unsupported_upload_format_returns_safe_422(tmp_path: Path) -> None:
    async def request() -> httpx.Response:
        app = create_app(tmp_path / "data")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/v1/datasets/upload",
                files={"file": ("source.pdf", b"not-a-pdf")},
                data={"submitted_by": "reviewer@example.com"},
            )

    response = asyncio.run(request())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SOURCE_NORMALIZATION"
