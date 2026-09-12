import csv
import json
from io import BytesIO, StringIO

import pytest
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from adapters.local import LocalTabularSourceAdapter
from youth_compass.domain.errors import SourceNormalizationError
from youth_compass.domain.types import FileFormat


def _rows(content: bytes) -> list[list[str]]:
    return list(csv.reader(StringIO(content.decode("utf-8"))))


def _workbook_bytes(*, multiple_sheets: bool = False) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Population"
    sheet.append(["year", "district", "age", "population"])
    sheet.append([2025, "板橋區", "20-24", 100])
    if multiple_sheets:
        workbook.create_sheet("Notes").append(["ignored"])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _table_pdf_bytes() -> bytes:
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
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
            ]
        )
    )
    document.build([table])
    return output.getvalue()


def _blank_pdf_bytes(*, text: str | None = None) -> bytes:
    output = BytesIO()
    document = canvas.Canvas(output, pagesize=letter)
    if text:
        document.drawString(72, 720, text)
    document.showPage()
    document.save()
    return output.getvalue()


def test_csv_is_passed_through_without_changing_original_bytes() -> None:
    source = b"year,district,age,population\n2025,01,20-24,100\n"

    result = LocalTabularSourceAdapter().normalize("population.csv", source)

    assert result.source_format is FileFormat.CSV
    assert result.file_name == "population.csv"
    assert result.content == source


def test_excel_first_visible_sheet_is_normalized_to_utf8_csv() -> None:
    result = LocalTabularSourceAdapter().normalize(
        "population.xlsx", _workbook_bytes(multiple_sheets=True)
    )

    assert result.source_format is FileFormat.EXCEL
    assert result.file_name == "population.csv"
    assert _rows(result.content) == [
        ["year", "district", "age", "population"],
        ["2025", "板橋區", "20-24", "100"],
    ]
    assert "imported the first sheet 'Population'" in result.warnings[0]


@pytest.mark.parametrize("extension", ["json", "jsonl", "ndjson"])
def test_json_record_formats_are_normalized(extension: str) -> None:
    records = [
        {"year": 2025, "district": "板橋區", "age": "20-24", "population": 100},
        {"year": 2025, "district": "林口區", "age": "20-24", "population": 50},
    ]
    content = (
        json.dumps(records).encode()
        if extension == "json"
        else "\n".join(json.dumps(record) for record in records).encode()
    )

    result = LocalTabularSourceAdapter().normalize(f"population.{extension}", content)

    assert result.source_format is FileFormat.JSON
    assert _rows(result.content)[1:] == [
        ["2025", "板橋區", "20-24", "100"],
        ["2025", "林口區", "20-24", "50"],
    ]


def test_wrapped_json_and_nested_values_are_deterministic() -> None:
    content = json.dumps(
        {"data": [{"id": 1, "meta": {"source": "city"}, "tags": ["youth"]}]}
    ).encode()

    result = LocalTabularSourceAdapter().normalize("records.json", content)

    assert _rows(result.content) == [
        ["id", "meta", "tags"],
        ["1", '{"source":"city"}', '["youth"]'],
    ]


def test_text_pdf_table_is_normalized_with_review_warning() -> None:
    result = LocalTabularSourceAdapter().normalize("population.pdf", _table_pdf_bytes())

    assert result.source_format is FileFormat.PDF
    assert result.file_name == "population.csv"
    assert _rows(result.content) == [
        ["year", "district_code", "age", "population"],
        ["2025", "01", "20-24", "100"],
        ["2025", "17", "20-24", "50"],
    ]
    assert "verify cell boundaries before approval" in result.warnings[0]


def test_scanned_pdf_fails_closed_with_ocr_guidance() -> None:
    with pytest.raises(SourceNormalizationError, match="OCR or Amazon Textract"):
        LocalTabularSourceAdapter().normalize("scan.pdf", _blank_pdf_bytes())


def test_text_pdf_without_table_fails_closed() -> None:
    with pytest.raises(SourceNormalizationError, match="no table could be detected"):
        LocalTabularSourceAdapter().normalize(
            "narrative.pdf", _blank_pdf_bytes(text="This document has no table")
        )


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("source.docx", b"docx", "unsupported source format"),
        ("source.json", b"not-json", "JSON is invalid"),
        ("source.json", b"[1, 2]", "records must be objects"),
    ],
)
def test_invalid_sources_fail_closed(name: str, content: bytes, message: str) -> None:
    with pytest.raises(SourceNormalizationError, match=message):
        LocalTabularSourceAdapter().normalize(name, content)
