from pathlib import Path

import pytest

from youth_compass.domain.contracts import MappingProposal
from youth_compass.ingestion import profile_csv
from youth_compass.mapping import analyze_mapping
from youth_compass.transformation.values import (
    LineageContext,
    RowTransformationError,
    transform_row,
)

HEADER = (
    "year,month,district_code,district,age,youth_relationship,youth_weight,"
    "gender,education,education_order,graduation_status,marital_status,"
    "same_sex_marriage,direction,counterpart_region,initial_registration_reason,"
    "event,marriage_type,count"
)
VALID_VALUES = (
    "2025,2,1,板橋區,18歲,fully_within,1,M,博士,7,畢業,"
    "有偶_相同性別,true,遷入,桃園市,入境定居,結婚,相同性別,100"
)


def _profile_and_row(tmp_path: Path) -> tuple[MappingProposal, dict[str, str]]:
    source = tmp_path / "all-transformations.csv"
    source.write_text(f"{HEADER}\n{VALID_VALUES}\n", encoding="utf-8")
    analysis = analyze_mapping(profile_csv(source))
    row = dict(zip(HEADER.split(","), VALID_VALUES.split(","), strict=True))
    return analysis.proposal, row


def _lineage() -> LineageContext:
    return LineageContext(
        source_row_number=2,
        source_sha256="a" * 64,
        dataset_id="test_dataset",
        dataset_version="version-1",
        mapping_version="mapping-1",
        transformation_version="canonical-v1",
    )


def test_executes_all_registered_dimension_transformations(tmp_path: Path) -> None:
    proposal, row = _profile_and_row(tmp_path)

    result = transform_row(row, proposal, _lineage())

    assert result.filter_reason is None
    assert len(result.observations) == 1
    observation = result.observations[0]
    assert observation["year_roc"] == 114
    assert observation["year_gregorian"] == 2025
    assert observation["month"] == 2
    assert observation["district_code"] == "01"
    assert observation["district_name"] == "板橋區"
    assert observation["period_granularity"] == "month"
    assert observation["gender_code"] == "male"
    assert observation["education_code"] == "博士"
    assert observation["education_order"] == 7
    assert observation["graduation_status"] == "graduated"
    assert observation["marital_status_code"] == "married"
    assert observation["same_sex_marriage"] is True
    assert observation["direction"] == "inbound"
    assert observation["counterpart_region"] == "桃園市"
    assert observation["initial_registration_reason"] == "入境定居"
    assert observation["event_code"] == "marriage"
    assert observation["marriage_type"] == "same_sex"
    assert observation["metric_value"] == 100.0


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("year", "not-a-year", "INVALID_YEAR"),
        ("month", "13", "INVALID_MONTH"),
        ("district", "Atlantis", "UNKNOWN_DISTRICT"),
        ("age", "mystery", "INVALID_AGE_RANGE"),
        ("gender", "X", "UNKNOWN_GENDER"),
        ("graduation_status", "mystery", "UNKNOWN_GRADUATION_STATUS"),
        ("marital_status", "mystery", "UNKNOWN_MARITAL_STATUS"),
        ("same_sex_marriage", "perhaps", "INVALID_BOOLEAN"),
        ("direction", "sideways", "UNKNOWN_DIRECTION"),
        ("event", "mystery", "UNKNOWN_EVENT"),
        ("marriage_type", "mystery", "UNKNOWN_MARRIAGE_TYPE"),
    ],
)
def test_rejects_invalid_dimension_values(
    tmp_path: Path,
    field: str,
    value: str,
    error_code: str,
) -> None:
    proposal, row = _profile_and_row(tmp_path)
    row[field] = value

    with pytest.raises(RowTransformationError) as captured:
        transform_row(row, proposal, _lineage())

    assert captured.value.code == error_code


def test_rejects_conflicting_district_identifiers(tmp_path: Path) -> None:
    proposal, row = _profile_and_row(tmp_path)
    row["district"] = "三重區"

    with pytest.raises(RowTransformationError) as captured:
        transform_row(row, proposal, _lineage())

    assert captured.value.code == "CONFLICTING_CANONICAL_VALUE"


def test_rejects_source_youth_derivation_mismatch(tmp_path: Path) -> None:
    proposal, row = _profile_and_row(tmp_path)
    row["youth_weight"] = "0.5"

    with pytest.raises(RowTransformationError) as captured:
        transform_row(row, proposal, _lineage())

    assert captured.value.code == "YOUTH_WEIGHT_MISMATCH"


def test_rejects_negative_or_missing_additive_metric(tmp_path: Path) -> None:
    proposal, row = _profile_and_row(tmp_path)
    row["count"] = "-1"

    with pytest.raises(RowTransformationError) as captured:
        transform_row(row, proposal, _lineage())
    assert captured.value.code == "NEGATIVE_ADDITIVE_METRIC"

    row["count"] = ""
    with pytest.raises(RowTransformationError) as captured:
        transform_row(row, proposal, _lineage())
    assert captured.value.code == "MISSING_METRIC_VALUE"


def test_filters_rows_outside_youth_range(tmp_path: Path) -> None:
    proposal, row = _profile_and_row(tmp_path)
    row["age"] = "40-44"
    row["youth_relationship"] = "unrelated"
    row["youth_weight"] = "0"

    result = transform_row(row, proposal, _lineage())

    assert result.filter_reason == "outside_youth_range"
    assert result.observations == []
