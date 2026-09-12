"""Local source adapter for CSV, Excel, JSON, and text-based PDF tables."""

from __future__ import annotations

import csv
import json
from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

import pdfplumber
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import PdfminerException

from youth_compass.domain.errors import SourceNormalizationError
from youth_compass.domain.types import FileFormat
from youth_compass.ports import NormalizedTabularSource

_CSV_EXTENSIONS = {".csv", ".tsv"}
_EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}
_JSON_EXTENSIONS = {".json", ".jsonl", ".ndjson"}
_PDF_EXTENSIONS = {".pdf"}
_MAX_COLUMNS = 512
_MAX_ROWS = 500_000


class LocalTabularSourceAdapter:
    """Convert supported uploads to UTF-8 CSV while preserving original bytes elsewhere."""

    def normalize(self, file_name: str, content: bytes) -> NormalizedTabularSource:
        safe_name = Path(file_name).name
        if not safe_name:
            raise SourceNormalizationError("source file name must not be empty")
        if not content:
            raise SourceNormalizationError("source file must not be empty")
        extension = Path(safe_name).suffix.casefold()
        if extension in _CSV_EXTENSIONS:
            return NormalizedTabularSource(
                content=content,
                file_name=safe_name,
                source_format=FileFormat.CSV,
            )
        if extension in _EXCEL_EXTENSIONS:
            normalized, warnings = _excel_to_csv(content)
            return NormalizedTabularSource(
                content=normalized,
                file_name=f"{Path(safe_name).stem}.csv",
                source_format=FileFormat.EXCEL,
                warnings=warnings,
            )
        if extension in _JSON_EXTENSIONS:
            normalized = _json_to_csv(content, line_delimited=extension != ".json")
            return NormalizedTabularSource(
                content=normalized,
                file_name=f"{Path(safe_name).stem}.csv",
                source_format=FileFormat.JSON,
            )
        if extension in _PDF_EXTENSIONS:
            normalized, warnings = _pdf_to_csv(content)
            return NormalizedTabularSource(
                content=normalized,
                file_name=f"{Path(safe_name).stem}.csv",
                source_format=FileFormat.PDF,
                warnings=warnings,
            )
        supported = ", ".join(
            sorted(_CSV_EXTENSIONS | _EXCEL_EXTENSIONS | _JSON_EXTENSIONS | _PDF_EXTENSIONS)
        )
        raise SourceNormalizationError(
            f"unsupported source format {extension or '<none>'}; supported: {supported}"
        )


def _pdf_to_csv(content: bytes) -> tuple[bytes, tuple[str, ...]]:
    try:
        with pdfplumber.open(BytesIO(content)) as document:
            return _extract_pdf_tables(document.pages)
    except SourceNormalizationError:
        raise
    except (
        PDFSyntaxError,
        PDFPasswordIncorrect,
        PdfminerException,
        OSError,
        ValueError,
    ) as exc:
        raise SourceNormalizationError("PDF is invalid, encrypted, or unreadable") from exc


def _extract_pdf_tables(pages: list[Any]) -> tuple[bytes, tuple[str, ...]]:
    primary_header: list[str] | None = None
    output_rows: list[list[str]] = []
    found_tables = 0
    ignored_tables = 0
    pages_with_text = 0
    pages_used: set[int] = set()

    for page_number, page in enumerate(pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages_with_text += 1
        tables = page.extract_tables(_line_table_settings())
        if not tables and text.strip():
            tables = page.extract_tables(_text_table_settings())
        for raw_table in tables:
            table = _rectangular_table(raw_table)
            if len(table) < 2 or len(table[0]) < 2:
                continue
            found_tables += 1
            header = table[0]
            if primary_header is None:
                primary_header = header
            elif header != primary_header:
                ignored_tables += 1
                continue
            rows = table[1:]
            if rows and rows[0] == primary_header:
                rows = rows[1:]
            output_rows.extend(row for row in rows if any(cell for cell in row))
            pages_used.add(page_number)
            if len(output_rows) > _MAX_ROWS:
                raise SourceNormalizationError(f"PDF table exceeds {_MAX_ROWS} rows")

    if primary_header is None or not output_rows:
        if pages_with_text == 0:
            raise SourceNormalizationError(
                "PDF appears to be scanned; OCR or Amazon Textract is required"
            )
        raise SourceNormalizationError("PDF contains text but no table could be detected")
    if len(primary_header) > _MAX_COLUMNS:
        raise SourceNormalizationError(f"PDF table exceeds {_MAX_COLUMNS} columns")

    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(primary_header)
    writer.writerows(output_rows)
    warnings = [
        f"Extracted {len(output_rows)} row(s) from {found_tables} table(s) "
        f"across {len(pages_used)} page(s); verify cell boundaries before approval"
    ]
    if ignored_tables:
        warnings.append(
            f"Ignored {ignored_tables} table(s) whose headers differed from the first table"
        )
    return output.getvalue().encode("utf-8"), tuple(warnings)


def _rectangular_table(raw_table: list[list[str | None]]) -> list[list[str]]:
    if not raw_table:
        return []
    width = max((len(row) for row in raw_table), default=0)
    rows: list[list[str]] = []
    for raw_row in raw_table:
        row = [_pdf_cell(value) for value in raw_row]
        row.extend([""] * (width - len(row)))
        rows.append(row)
    while rows and not any(rows[-1]):
        rows.pop()
    return rows


def _pdf_cell(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.replace("\x00", "").split())


def _line_table_settings() -> dict[str, object]:
    return {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "snap_tolerance": 3,
        "join_tolerance": 3,
        "intersection_tolerance": 3,
    }


def _text_table_settings() -> dict[str, object]:
    return {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "min_words_vertical": 2,
        "min_words_horizontal": 1,
    }


def _excel_to_csv(content: bytes) -> tuple[bytes, tuple[str, ...]]:
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, OSError, ValueError, KeyError) as exc:
        raise SourceNormalizationError("Excel workbook is invalid or unreadable") from exc
    try:
        visible = [sheet for sheet in workbook.worksheets if sheet.sheet_state == "visible"]
        if not visible:
            raise SourceNormalizationError("Excel workbook has no visible worksheet")
        sheet = visible[0]
        rows = sheet.iter_rows(values_only=True)
        header_row: tuple[Any, ...] | None = None
        skipped = 0
        for row in rows:
            if any(value is not None and str(value).strip() for value in row):
                header_row = row
                break
            skipped += 1
        if header_row is None:
            raise SourceNormalizationError("Excel worksheet is empty")
        width = _last_populated_index(header_row)
        if width == 0:
            raise SourceNormalizationError("Excel worksheet has no header")
        if width > _MAX_COLUMNS:
            raise SourceNormalizationError(f"Excel worksheet exceeds {_MAX_COLUMNS} columns")

        output = StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([_cell_text(value) for value in header_row[:width]])
        count = 0
        for row in rows:
            if count >= _MAX_ROWS:
                raise SourceNormalizationError(f"Excel worksheet exceeds {_MAX_ROWS} rows")
            values = [_cell_text(value) for value in row[:width]]
            if any(values):
                writer.writerow(values)
                count += 1
        if count == 0:
            raise SourceNormalizationError("Excel worksheet contains a header but no data rows")

        warnings: list[str] = []
        if skipped:
            warnings.append(f"Skipped {skipped} blank row(s) before the Excel header")
        if len(visible) > 1:
            warnings.append(
                f"Workbook has {len(visible)} visible sheets; imported the first sheet "
                f"{sheet.title!r}"
            )
        return output.getvalue().encode("utf-8"), tuple(warnings)
    finally:
        workbook.close()


def _json_to_csv(content: bytes, *, line_delimited: bool) -> bytes:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SourceNormalizationError("JSON source must use UTF-8 encoding") from exc
    try:
        if line_delimited:
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            payload = json.loads(text)
            records = _record_collection(payload)
    except json.JSONDecodeError as exc:
        raise SourceNormalizationError(
            f"JSON is invalid at line {exc.lineno}, column {exc.colno}"
        ) from exc
    if not records:
        raise SourceNormalizationError("JSON source contains no records")
    if len(records) > _MAX_ROWS:
        raise SourceNormalizationError(f"JSON source exceeds {_MAX_ROWS} records")
    if any(not isinstance(record, dict) for record in records):
        raise SourceNormalizationError("JSON records must be objects with named fields")

    headers: list[str] = []
    seen: set[str] = set()
    typed_records: list[dict[str, Any]] = records
    for record in typed_records:
        for raw_key in record:
            key = str(raw_key)
            if key not in seen:
                seen.add(key)
                headers.append(key)
    if not headers:
        raise SourceNormalizationError("JSON records contain no fields")
    if len(headers) > _MAX_COLUMNS:
        raise SourceNormalizationError(f"JSON source exceeds {_MAX_COLUMNS} fields")

    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    for record in typed_records:
        normalized = {str(key): _json_cell(value) for key, value in record.items()}
        writer.writerow(normalized)
    return output.getvalue().encode("utf-8")


def _record_collection(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "records", "results", "items"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return candidate
        return [payload]
    raise SourceNormalizationError("JSON root must be an object or an array of objects")


def _json_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return str(value)


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _last_populated_index(row: tuple[Any, ...]) -> int:
    for index in range(len(row), 0, -1):
        value = row[index - 1]
        if value is not None and str(value).strip():
            return index
    return 0
