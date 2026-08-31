"""Memory-bounded CSV profiler for unknown public-data sources."""

import codecs
import csv
import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from youth_compass.domain.profiles import (
    ColumnProfile,
    DatasetProfile,
    GeographyCoverage,
    ProfileWarning,
    TimeCoverage,
)
from youth_compass.domain.types import (
    FileFormat,
    PrimitiveType,
    SemanticRole,
    WarningSeverity,
)
from youth_compass.mapping.geography import normalize_district
from youth_compass.mapping.time import parse_year

_NULL_TOKENS = {"", "null", "none", "n/a", "na", "nan"}
_BOOLEAN_TOKENS = {"true", "false", "yes", "no", "是", "否"}
_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")

_ROLE_ALIASES: dict[SemanticRole, set[str]] = {
    SemanticRole.YEAR: {
        "年",
        "年度",
        "民國年",
        "year",
        "statyear",
        "reportyear",
    },
    SemanticRole.MONTH: {"月", "月份", "month", "statmonth", "reportmonth"},
    SemanticRole.DISTRICT_CODE: {
        "區代碼",
        "行政區代碼",
        "districtcode",
        "areacode",
    },
    SemanticRole.DISTRICT_NAME: {
        "區",
        "行政區",
        "鄉鎮市區",
        "district",
        "districtname",
        "area",
        "areaname",
    },
    SemanticRole.AGE_LABEL: {
        "年齡",
        "年齡標籤",
        "年齡組",
        "age",
        "agegroup",
        "agelabel",
    },
    SemanticRole.AGE_LOWER: {"年齡下限", "agelower", "agemin", "minage"},
    SemanticRole.AGE_UPPER: {"年齡上限", "ageupper", "agemax", "maxage"},
    SemanticRole.GENDER: {"性別", "gender", "sex"},
}

_DIMENSION_ALIASES = {
    "教育程度",
    "畢肄業",
    "婚姻狀況",
    "是否同性婚",
    "方向",
    "對象地區",
    "初設原因",
    "事件",
    "婚姻類型",
    "主題",
    "機關",
    "資料集",
    "education",
    "maritalstatus",
    "direction",
    "event",
    "topic",
}

_METRIC_HINTS = {
    "人數",
    "人口",
    "所得",
    "收入",
    "薪資",
    "戶數",
    "單位數",
    "count",
    "value",
    "population",
    "income",
    "salary",
    "jobseekers",
}


@dataclass(frozen=True, slots=True)
class CsvProfileOptions:
    sample_value_limit: int = 5
    distinct_value_cap: int = 10_000
    duplicate_check_limit: int = 100_000
    max_rows: int | None = None

    def __post_init__(self) -> None:
        if self.sample_value_limit < 1:
            raise ValueError("sample_value_limit must be positive")
        if self.distinct_value_cap < 1:
            raise ValueError("distinct_value_cap must be positive")
        if self.duplicate_check_limit < 1:
            raise ValueError("duplicate_check_limit must be positive")
        if self.max_rows is not None and self.max_rows < 1:
            raise ValueError("max_rows must be positive when provided")


@dataclass(slots=True)
class _ColumnAccumulator:
    sample_limit: int
    distinct_cap: int
    non_null_count: int = 0
    null_count: int = 0
    sample_values: list[str] = field(default_factory=list)
    distinct_values: set[str] = field(default_factory=set)
    distinct_is_lower_bound: bool = False
    all_boolean: bool = True
    all_integer: bool = True
    all_float: bool = True
    all_date: bool = True
    numeric_min: float | None = None
    numeric_max: float | None = None

    def observe(self, raw: str) -> None:
        value = raw.strip()
        if value.casefold() in _NULL_TOKENS:
            self.null_count += 1
            return

        self.non_null_count += 1
        if value not in self.sample_values and len(self.sample_values) < self.sample_limit:
            self.sample_values.append(value)
        if not self.distinct_is_lower_bound:
            if value in self.distinct_values:
                pass
            elif len(self.distinct_values) < self.distinct_cap:
                self.distinct_values.add(value)
            else:
                self.distinct_is_lower_bound = True

        folded = value.casefold()
        self.all_boolean = self.all_boolean and folded in _BOOLEAN_TOKENS
        is_integer = _INTEGER_PATTERN.fullmatch(value) is not None
        self.all_integer = self.all_integer and is_integer

        parsed_float = _parse_finite_float(value)
        self.all_float = self.all_float and parsed_float is not None
        if parsed_float is not None:
            self.numeric_min = (
                parsed_float if self.numeric_min is None else min(self.numeric_min, parsed_float)
            )
            self.numeric_max = (
                parsed_float if self.numeric_max is None else max(self.numeric_max, parsed_float)
            )

        self.all_date = self.all_date and _is_iso_date(value)

    def inferred_type(self) -> PrimitiveType:
        if self.non_null_count == 0:
            return PrimitiveType.EMPTY
        if self.all_boolean:
            return PrimitiveType.BOOLEAN
        if self.all_integer:
            return PrimitiveType.INTEGER
        if self.all_float:
            return PrimitiveType.FLOAT
        if self.all_date:
            return PrimitiveType.DATE
        return PrimitiveType.STRING


def _parse_finite_float(value: str) -> float | None:
    try:
        parsed = float(value.replace(",", ""))
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _normalized_header(value: str) -> str:
    return re.sub(r"[\s_\-()/\uff08\uff09]+", "", value.strip().casefold())


def infer_semantic_role(name: str, inferred_type: PrimitiveType) -> tuple[SemanticRole, float]:
    normalized = _normalized_header(name)
    for role, aliases in _ROLE_ALIASES.items():
        if normalized in aliases:
            return role, 0.99
    if normalized in {_normalized_header(value) for value in _DIMENSION_ALIASES}:
        return SemanticRole.DIMENSION, 0.95
    if any(hint in normalized for hint in _METRIC_HINTS):
        if inferred_type in {PrimitiveType.INTEGER, PrimitiveType.FLOAT}:
            return SemanticRole.METRIC, 0.90
        return SemanticRole.METRIC, 0.65
    if inferred_type in {PrimitiveType.INTEGER, PrimitiveType.FLOAT}:
        return SemanticRole.METRIC, 0.45
    return SemanticRole.UNKNOWN, 0.0


def _detect_encoding(sample: bytes) -> str:
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
    except UnicodeDecodeError:
        for encoding in ("cp950", "big5"):
            try:
                codecs.getincrementaldecoder(encoding)().decode(sample, final=False)
            except UnicodeDecodeError:
                continue
            return encoding
        raise ValueError("Unable to detect a supported CSV encoding") from None
    return "utf-8"


def _detect_delimiter(text_sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(text_sample, delimiters=",\t;|")
    except csv.Error:
        candidates = {delimiter: text_sample.count(delimiter) for delimiter in ",\t;|"}
        delimiter, count = max(candidates.items(), key=lambda item: item[1])
        if count == 0:
            return ","
        return delimiter
    return dialect.delimiter


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unique_headers(raw_headers: list[str]) -> tuple[list[str], list[ProfileWarning]]:
    headers: list[str] = []
    warnings: list[ProfileWarning] = []
    counts: Counter[str] = Counter()
    for index, raw in enumerate(raw_headers):
        base = raw.strip() or f"column_{index + 1}"
        counts[base] += 1
        name = base if counts[base] == 1 else f"{base}__{counts[base]}"
        headers.append(name)
        if not raw.strip():
            warnings.append(
                ProfileWarning(
                    code="EMPTY_HEADER",
                    message=f"Column {index + 1} had an empty header and was named {name}",
                    field=name,
                )
            )
        if counts[base] > 1:
            warnings.append(
                ProfileWarning(
                    code="DUPLICATE_HEADER",
                    message=f"Duplicate header {base!r} was renamed to {name!r} for profiling",
                    field=name,
                )
            )
    return headers, warnings


def profile_csv(path: Path, options: CsvProfileOptions | None = None) -> DatasetProfile:
    """Profile a CSV using bounded samples and streaming row processing."""

    options = options or CsvProfileOptions()
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    file_size = path.stat().st_size
    with path.open("rb") as stream:
        binary_sample = stream.read(64 * 1024)
    if not binary_sample:
        raise ValueError(f"CSV file is empty: {path}")
    encoding = _detect_encoding(binary_sample)
    text_sample = binary_sample.decode(encoding, errors="ignore")
    delimiter = _detect_delimiter(text_sample)

    warnings: list[ProfileWarning] = []
    row_count = 0
    malformed_row_count = 0
    duplicate_row_count = 0
    duplicate_rows_checked = 0
    seen_rows: set[tuple[str, ...]] = set()
    year_systems: Counter[str] = Counter()
    gregorian_years: set[int] = set()
    months: set[int] = set()
    months_by_year: defaultdict[int, set[int]] = defaultdict(set)
    district_codes: set[str] = set()
    unknown_districts: set[str] = set()
    truncated = False

    with path.open("r", encoding=encoding, newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter)
        try:
            raw_headers = next(reader)
        except StopIteration as error:
            raise ValueError(f"CSV file has no header: {path}") from error
        headers, header_warnings = _unique_headers(raw_headers)
        warnings.extend(header_warnings)
        accumulators = [
            _ColumnAccumulator(options.sample_value_limit, options.distinct_value_cap)
            for _ in headers
        ]
        preliminary_roles = [
            infer_semantic_role(header, PrimitiveType.STRING)[0] for header in headers
        ]
        year_index = _first_role_index(preliminary_roles, SemanticRole.YEAR)
        month_index = _first_role_index(preliminary_roles, SemanticRole.MONTH)
        district_index = _preferred_district_index(preliminary_roles)

        for raw_row in reader:
            if options.max_rows is not None and row_count >= options.max_rows:
                truncated = True
                break
            row_count += 1
            if len(raw_row) != len(headers):
                malformed_row_count += 1
                if len(raw_row) < len(headers):
                    raw_row = [*raw_row, *([""] * (len(headers) - len(raw_row)))]
                else:
                    raw_row = raw_row[: len(headers)]

            row = tuple(raw_row)
            if duplicate_rows_checked < options.duplicate_check_limit:
                duplicate_rows_checked += 1
                if row in seen_rows:
                    duplicate_row_count += 1
                else:
                    seen_rows.add(row)

            for accumulator, value in zip(accumulators, row, strict=True):
                accumulator.observe(value)

            parsed_year = parse_year(row[year_index]) if year_index is not None else None
            if parsed_year is not None:
                year_systems[parsed_year.detected_system] += 1
                gregorian_years.add(parsed_year.year_gregorian)
                if month_index is not None:
                    parsed_month = _parse_month(row[month_index])
                    if parsed_month is not None:
                        months.add(parsed_month)
                        months_by_year[parsed_year.year_gregorian].add(parsed_month)

            if district_index is not None:
                raw_district = row[district_index].strip()
                if raw_district:
                    district = normalize_district(raw_district)
                    if district is None:
                        if len(unknown_districts) < 20:
                            unknown_districts.add(raw_district)
                    else:
                        district_codes.add(district.code)

    if row_count == 0:
        warnings.append(
            ProfileWarning(
                code="EMPTY_DATASET",
                message="The CSV contains a header but no data rows",
                severity=WarningSeverity.ERROR,
            )
        )
    if malformed_row_count:
        warnings.append(
            ProfileWarning(
                code="MALFORMED_ROWS",
                message=f"{malformed_row_count} rows did not match the header column count",
            )
        )
    duplicate_check_is_partial = row_count > duplicate_rows_checked
    if duplicate_row_count:
        scope = "sampled rows" if duplicate_check_is_partial else "rows"
        warnings.append(
            ProfileWarning(
                code="DUPLICATE_ROWS",
                message=(
                    f"Found {duplicate_row_count} duplicate rows among "
                    f"{duplicate_rows_checked} {scope}"
                ),
            )
        )
    if duplicate_check_is_partial:
        warnings.append(
            ProfileWarning(
                code="PARTIAL_DUPLICATE_CHECK",
                message=(
                    f"Duplicate detection was limited to the first {duplicate_rows_checked} rows"
                ),
                severity=WarningSeverity.INFO,
            )
        )
    if unknown_districts:
        warnings.append(
            ProfileWarning(
                code="UNKNOWN_DISTRICTS",
                message=f"Could not resolve {len(unknown_districts)} sampled district values",
                field=headers[district_index] if district_index is not None else None,
            )
        )
    if truncated:
        warnings.append(
            ProfileWarning(
                code="PROFILING_TRUNCATED",
                message=f"Profiling stopped after max_rows={options.max_rows}",
                severity=WarningSeverity.INFO,
            )
        )
    if not truncated and months_by_year and gregorian_years:
        latest_year = max(gregorian_years)
        latest_months = months_by_year.get(latest_year, set())
        if latest_months != set(range(1, 13)):
            warnings.append(
                ProfileWarning(
                    code="PARTIAL_LATEST_YEAR",
                    message=(
                        f"Latest year {latest_year} contains {len(latest_months)} distinct months"
                    ),
                )
            )

    columns: list[ColumnProfile] = []
    for position, (header, accumulator) in enumerate(zip(headers, accumulators, strict=True)):
        inferred_type = accumulator.inferred_type()
        role, confidence = infer_semantic_role(header, inferred_type)
        if accumulator.distinct_is_lower_bound:
            warnings.append(
                ProfileWarning(
                    code="DISTINCT_VALUE_CAP_REACHED",
                    message=(
                        f"Distinct value tracking for {header!r} reached "
                        f"the cap of {options.distinct_value_cap}"
                    ),
                    severity=WarningSeverity.INFO,
                    field=header,
                )
            )
        total = accumulator.non_null_count + accumulator.null_count
        columns.append(
            ColumnProfile(
                name=header,
                position=position,
                inferred_type=inferred_type,
                semantic_role=role,
                semantic_confidence=confidence,
                non_null_count=accumulator.non_null_count,
                null_count=accumulator.null_count,
                null_rate=(accumulator.null_count / total if total else 0.0),
                distinct_count=len(accumulator.distinct_values),
                distinct_count_is_lower_bound=accumulator.distinct_is_lower_bound,
                sample_values=accumulator.sample_values,
                numeric_min=accumulator.numeric_min,
                numeric_max=accumulator.numeric_max,
            )
        )

    source_year_system = None
    if len(year_systems) == 1:
        source_year_system = next(iter(year_systems))
    elif year_systems:
        source_year_system = "mixed"

    candidate_grain = [
        column.name
        for column in columns
        if column.semantic_role
        in {
            SemanticRole.YEAR,
            SemanticRole.MONTH,
            SemanticRole.DISTRICT_CODE,
            SemanticRole.DISTRICT_NAME,
            SemanticRole.AGE_LABEL,
            SemanticRole.AGE_LOWER,
            SemanticRole.AGE_UPPER,
            SemanticRole.GENDER,
            SemanticRole.DIMENSION,
        }
    ]

    return DatasetProfile(
        source_path=path,
        file_name=path.name,
        file_format=FileFormat.CSV,
        encoding=encoding,
        delimiter=delimiter,
        file_size_bytes=file_size,
        content_sha256=_sha256(path),
        row_count=row_count,
        column_count=len(columns),
        columns=columns,
        candidate_grain=candidate_grain,
        duplicate_rows_checked=duplicate_rows_checked,
        duplicate_row_count=duplicate_row_count,
        duplicate_check_is_partial=duplicate_check_is_partial,
        time_coverage=TimeCoverage(
            year_gregorian_min=min(gregorian_years) if gregorian_years else None,
            year_gregorian_max=max(gregorian_years) if gregorian_years else None,
            source_year_system=source_year_system,
            months=sorted(months),
            months_by_gregorian_year={
                year: sorted(year_months) for year, year_months in sorted(months_by_year.items())
            },
        ),
        geography_coverage=GeographyCoverage(
            district_count=len(district_codes) + len(unknown_districts),
            recognized_district_count=len(district_codes),
            unknown_values=sorted(unknown_districts),
        ),
        warnings=warnings,
        truncated_by_max_rows=truncated,
    )


def _first_role_index(roles: list[SemanticRole], role: SemanticRole) -> int | None:
    try:
        return roles.index(role)
    except ValueError:
        return None


def _preferred_district_index(roles: list[SemanticRole]) -> int | None:
    name_index = _first_role_index(roles, SemanticRole.DISTRICT_NAME)
    return (
        name_index
        if name_index is not None
        else _first_role_index(roles, SemanticRole.DISTRICT_CODE)
    )


def _parse_month(value: str) -> int | None:
    cleaned = value.strip().removesuffix("月")
    if not cleaned.isdigit():
        return None
    month = int(cleaned)
    return month if 1 <= month <= 12 else None
