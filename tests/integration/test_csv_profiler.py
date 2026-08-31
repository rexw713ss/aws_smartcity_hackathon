from pathlib import Path

import pytest

from youth_compass.domain.types import PrimitiveType, SemanticRole
from youth_compass.ingestion import CsvProfileOptions, profile_csv

FIXTURE = Path("tests/fixtures/employment_unfamiliar.csv")


def test_profile_held_out_employment_csv() -> None:
    profile = profile_csv(FIXTURE)

    assert profile.file_name == FIXTURE.name
    assert profile.encoding == "utf-8"
    assert profile.delimiter == ","
    assert profile.row_count == 5
    assert profile.column_count == 6
    assert len(profile.content_sha256) == 64
    assert profile.duplicate_rows_checked == 5
    assert profile.duplicate_row_count == 1
    assert profile.duplicate_check_is_partial is False
    assert profile.time_coverage.year_gregorian_min == 2026
    assert profile.time_coverage.year_gregorian_max == 2026
    assert profile.time_coverage.source_year_system == "roc"
    assert profile.geography_coverage.recognized_district_count == 2
    assert profile.geography_coverage.unknown_values == ["Unknown"]

    columns = {column.name: column for column in profile.columns}
    assert columns["stat_year"].semantic_role == SemanticRole.YEAR
    assert columns["stat_year"].inferred_type == PrimitiveType.INTEGER
    assert columns["area"].semantic_role == SemanticRole.DISTRICT_NAME
    assert columns["age_group"].semantic_role == SemanticRole.AGE_LABEL
    assert columns["sex"].semantic_role == SemanticRole.GENDER
    assert columns["job_seekers"].semantic_role == SemanticRole.METRIC
    assert columns["job_seekers"].numeric_min == 100.0
    assert columns["job_seekers"].numeric_max == 3420.0
    assert columns["note"].null_count == 2
    assert {warning.code for warning in profile.warnings} >= {
        "DUPLICATE_ROWS",
        "UNKNOWN_DISTRICTS",
    }


def test_profile_detects_semicolon_and_respects_max_rows(tmp_path: Path) -> None:
    source = tmp_path / "sample.csv"
    source.write_text("year;district;count\n2024;板橋;10\n2025;林口;20\n", encoding="utf-8")
    profile = profile_csv(source, CsvProfileOptions(max_rows=1))

    assert profile.delimiter == ";"
    assert profile.row_count == 1
    assert profile.truncated_by_max_rows is True
    assert "PROFILING_TRUNCATED" in {warning.code for warning in profile.warnings}


def test_profile_detects_utf8_bom(tmp_path: Path) -> None:
    source = tmp_path / "bom.csv"
    source.write_text("年度,行政區,人數\n115,板橋區,10\n", encoding="utf-8-sig")
    profile = profile_csv(source)
    assert profile.encoding == "utf-8-sig"
    assert profile.columns[0].name == "年度"


def test_profile_detects_cp950(tmp_path: Path) -> None:
    source = tmp_path / "cp950.csv"
    source.write_bytes("年度,行政區,人數\n115,板橋區,10\n".encode("cp950"))
    profile = profile_csv(source)
    assert profile.encoding == "cp950"
    assert profile.geography_coverage.recognized_district_count == 1


def test_profile_warns_about_partial_latest_year(tmp_path: Path) -> None:
    source = tmp_path / "partial.csv"
    source.write_text(
        "year,month,district,count\n2025,1,板橋,10\n2025,2,板橋,11\n",
        encoding="utf-8",
    )
    profile = profile_csv(source)
    assert "PARTIAL_LATEST_YEAR" in {warning.code for warning in profile.warnings}
    assert profile.time_coverage.months_by_gregorian_year == {2025: [1, 2]}


def test_profile_reports_header_and_row_shape_problems(tmp_path: Path) -> None:
    source = tmp_path / "malformed.csv"
    source.write_text("year,,value,value\n2024,x,1,2,extra\n", encoding="utf-8")
    profile = profile_csv(source)
    codes = {warning.code for warning in profile.warnings}
    assert {"EMPTY_HEADER", "DUPLICATE_HEADER", "MALFORMED_ROWS"} <= codes
    assert [column.name for column in profile.columns] == [
        "year",
        "column_2",
        "value",
        "value__2",
    ]


def test_profile_marks_distinct_count_as_lower_bound(tmp_path: Path) -> None:
    source = tmp_path / "distinct.csv"
    source.write_text("category\na\nb\nc\n", encoding="utf-8")
    profile = profile_csv(source, CsvProfileOptions(distinct_value_cap=2))
    column = profile.columns[0]
    assert column.distinct_count == 2
    assert column.distinct_count_is_lower_bound is True
    assert "DISTINCT_VALUE_CAP_REACHED" in {warning.code for warning in profile.warnings}


def test_profile_supports_single_column_csv(tmp_path: Path) -> None:
    source = tmp_path / "single.csv"
    source.write_text("count\n1\n2\n", encoding="utf-8")
    profile = profile_csv(source)
    assert profile.delimiter == ","
    assert profile.column_count == 1
    assert profile.row_count == 2


def test_profile_header_only_csv_returns_error_warning(tmp_path: Path) -> None:
    source = tmp_path / "header-only.csv"
    source.write_text("year,district,count\n", encoding="utf-8")
    profile = profile_csv(source)
    warnings = {warning.code: warning for warning in profile.warnings}
    assert profile.row_count == 0
    assert warnings["EMPTY_DATASET"].severity.value == "error"


def test_profile_rejects_empty_file(tmp_path: Path) -> None:
    source = tmp_path / "empty.csv"
    source.write_bytes(b"")
    with pytest.raises(ValueError, match="CSV file is empty"):
        profile_csv(source)
