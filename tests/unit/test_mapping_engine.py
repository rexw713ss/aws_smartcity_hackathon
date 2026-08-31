from pathlib import Path

from youth_compass.domain.contracts import ColumnMapping, DatasetGrain
from youth_compass.domain.types import PrimitiveType, SemanticRole
from youth_compass.ingestion import profile_csv
from youth_compass.mapping.engine import (
    MappingOptions,
    analyze_mapping,
    propose_mapping,
    validate_mapping,
)

FIXTURE = Path("tests/fixtures/employment_unfamiliar.csv")


def test_employment_mapping_is_deterministic_and_reviewable() -> None:
    analysis = analyze_mapping(profile_csv(FIXTURE))

    assert analysis.proposal.topic == "employment"
    assert analysis.proposal.dataset_role == "fact"
    assert analysis.proposal.grain.dimensions == [
        "year_roc",
        "district_name",
        "age_label_original",
        "gender_code",
    ]
    assert analysis.proposal.metrics[0].metric_code == "job_seekers"
    assert analysis.proposal.metrics[0].unit_code == "persons"
    assert analysis.proposal.metrics[0].population_scope == "youth_specific"
    assert analysis.proposal.requires_human_approval is True
    assert analysis.validation.valid is True
    assert any("Unknown district values" in item for item in analysis.proposal.warnings)


def test_no_age_dimension_is_context_not_youth_specific(tmp_path: Path) -> None:
    source = tmp_path / "education.csv"
    source.write_text(
        "年度,行政區,教育程度,人數\n115,板橋區,大學,100\n",
        encoding="utf-8",
    )

    analysis = analyze_mapping(profile_csv(source))

    assert analysis.proposal.topic == "education"
    assert analysis.proposal.dataset_role == "context"
    assert analysis.proposal.metrics[0].population_scope == "district_context"
    assert analysis.proposal.metrics[0].metric_code == "education_population"
    assert analysis.validation.valid is True
    assert any("district context" in item for item in analysis.proposal.warnings)


def test_empty_optional_age_columns_do_not_block_mapping(tmp_path: Path) -> None:
    source = tmp_path / "education-empty-age.csv"
    source.write_text(
        "年度,行政區,年齡標籤,年齡下限,年齡上限,教育程度,人數\n115,板橋區,,,,大學,100\n",
        encoding="utf-8",
    )

    analysis = analyze_mapping(profile_csv(source))

    assert analysis.validation.valid is True
    assert analysis.proposal.dataset_role == "context"
    assert "INCOMPATIBLE_TRANSFORMATION_TYPE" not in {
        issue.code for issue in analysis.validation.issues
    }


def test_education_order_is_a_dimension_and_drives_education_topic(
    tmp_path: Path,
) -> None:
    source = tmp_path / "education-with-marriage.csv"
    source.write_text(
        "年度,行政區,年齡,教育程度,教育程度排序,婚姻狀況,人數\n115,板橋區,20-24,大學,4,未婚,100\n",
        encoding="utf-8",
    )

    analysis = analyze_mapping(profile_csv(source))

    assert analysis.proposal.topic == "education"
    assert "education_order" in {mapping.target_field for mapping in analysis.proposal.columns}
    assert {metric.source_column for metric in analysis.proposal.metrics} == {"人數"}
    assert analysis.validation.valid is True


def test_unknown_metric_unit_blocks_publication(tmp_path: Path) -> None:
    source = tmp_path / "unknown-unit.csv"
    source.write_text(
        "year,district,age,value\n2025,板橋區,15-19,10\n",
        encoding="utf-8",
    )

    analysis = analyze_mapping(profile_csv(source))

    assert analysis.validation.valid is False
    assert {issue.code for issue in analysis.validation.issues} >= {"UNKNOWN_METRIC_UNIT"}


def test_missing_geography_dimension_blocks_publication(tmp_path: Path) -> None:
    source = tmp_path / "no-geography.csv"
    source.write_text(
        "year,age,population\n2025,15-19,10\n",
        encoding="utf-8",
    )

    analysis = analyze_mapping(profile_csv(source))

    assert analysis.validation.valid is False
    assert {issue.code for issue in analysis.validation.issues} >= {"MISSING_GEOGRAPHY_DIMENSION"}


def test_validator_rejects_non_allowlisted_transformation() -> None:
    profile = profile_csv(FIXTURE)
    proposal = propose_mapping(profile)
    first = proposal.columns[0]
    proposal.columns[0] = ColumnMapping(
        source_column=first.source_column,
        target_field=first.target_field,
        transformation="execute_arbitrary_python",
        confidence=first.confidence,
        evidence="tampered proposal",
    )

    validation = validate_mapping(profile, proposal)

    assert validation.valid is False
    assert "UNKNOWN_TRANSFORMATION" in {issue.code for issue in validation.issues}


def test_validator_rejects_transformation_type_mismatch() -> None:
    profile = profile_csv(FIXTURE)
    proposal = propose_mapping(profile)
    age_mapping = next(
        mapping for mapping in proposal.columns if mapping.target_field == "age_label_original"
    )
    age_profile = next(
        column for column in profile.columns if column.name == age_mapping.source_column
    )
    age_profile.inferred_type = PrimitiveType.BOOLEAN

    validation = validate_mapping(profile, proposal)

    assert validation.valid is False
    assert "INCOMPATIBLE_TRANSFORMATION_TYPE" in {issue.code for issue in validation.issues}


def test_validator_checks_proposed_grain_and_required_mappings() -> None:
    profile = profile_csv(FIXTURE)
    proposal = propose_mapping(profile)
    proposal.columns = [
        mapping
        for mapping in proposal.columns
        if mapping.target_field not in {"year_roc", "district_name"}
    ]
    proposal.grain = DatasetGrain(dimensions=["year_roc", "district_name"])

    validation = validate_mapping(profile, proposal)
    issue_codes = {issue.code for issue in validation.issues}

    assert validation.valid is False
    assert issue_codes >= {
        "UNKNOWN_GRAIN_DIMENSION",
        "MISSING_TIME_MAPPING",
        "MISSING_GEOGRAPHY_MAPPING",
    }


def test_validator_checks_metric_source_and_uniqueness() -> None:
    profile = profile_csv(FIXTURE)
    proposal = propose_mapping(profile)
    metric = proposal.metrics[0]
    proposal.metrics.append(metric.model_copy(update={"source_column": "missing"}))

    validation = validate_mapping(profile, proposal)
    issue_codes = {issue.code for issue in validation.issues}

    assert validation.valid is False
    assert issue_codes >= {"DUPLICATE_METRIC_CODE", "UNKNOWN_METRIC_SOURCE"}


def test_mapping_options_validate_confidence_threshold() -> None:
    try:
        MappingOptions(review_confidence_threshold=1.1)
    except ValueError as error:
        assert "between 0 and 1" in str(error)
    else:
        raise AssertionError("Expected invalid confidence threshold to fail")


def test_semantic_profile_roles_come_from_shared_registry() -> None:
    profile = profile_csv(FIXTURE)
    roles = {column.name: column.semantic_role for column in profile.columns}

    assert roles["stat_year"] == SemanticRole.YEAR
    assert roles["area"] == SemanticRole.DISTRICT_NAME
    assert roles["job_seekers"] == SemanticRole.METRIC
