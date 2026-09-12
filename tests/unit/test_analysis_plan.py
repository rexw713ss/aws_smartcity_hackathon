from youth_compass.decisioning import (
    AnalysisInput,
    AnalysisJoin,
    AnalysisPlan,
    AnalysisPlanValidator,
    JoinCardinality,
    PreAggregation,
)


def _population() -> AnalysisInput:
    return AnalysisInput(
        alias="population",
        dataset_id="population",
        dataset_version="v1",
        dimensions=("year_gregorian", "month", "district_code", "gender_code"),
        metrics=("population_count",),
        grain=("year_gregorian", "month", "district_code", "gender_code"),
    )


def _income() -> AnalysisInput:
    return AnalysisInput(
        alias="income",
        dataset_id="income",
        dataset_version="v2",
        dimensions=("year_gregorian", "district_code"),
        metrics=("median_income",),
        grain=("year_gregorian", "district_code"),
    )


def test_validator_accepts_many_to_one_join_at_declared_grains() -> None:
    plan = AnalysisPlan(
        inputs=(_population(), _income()),
        joins=(
            AnalysisJoin(
                left_alias="population",
                right_alias="income",
                keys=("year_gregorian", "district_code"),
                cardinality=JoinCardinality.MANY_TO_ONE,
            ),
        ),
        output_dimensions=("year_gregorian", "district_code"),
        output_metrics=("population_count", "median_income"),
    )

    assert AnalysisPlanValidator().validate(plan).valid is True


def test_validator_rejects_raw_many_to_many_join() -> None:
    education = AnalysisInput(
        alias="education",
        dataset_id="education",
        dataset_version="v1",
        dimensions=("year_gregorian", "district_code", "education_code"),
        metrics=("education_population",),
        grain=("year_gregorian", "district_code", "education_code"),
    )
    plan = AnalysisPlan(
        inputs=(_population(), education),
        joins=(
            AnalysisJoin(
                left_alias="population",
                right_alias="education",
                keys=("year_gregorian", "district_code"),
                cardinality=JoinCardinality.MANY_TO_MANY,
            ),
        ),
        output_dimensions=("year_gregorian", "district_code"),
        output_metrics=("population_count", "education_population"),
    )

    report = AnalysisPlanValidator().validate(plan)

    assert report.valid is False
    assert "UNSAFE_MANY_TO_MANY" in {issue.code for issue in report.issues}


def test_validator_accepts_join_after_explicit_preaggregation() -> None:
    plan = AnalysisPlan(
        inputs=(_population(), _income()),
        pre_aggregations=(
            PreAggregation(
                input_alias="population",
                group_by=("year_gregorian", "district_code"),
                metric_aggregations={"population_count": "sum"},
            ),
        ),
        joins=(
            AnalysisJoin(
                left_alias="population",
                right_alias="income",
                keys=("year_gregorian", "district_code"),
                cardinality=JoinCardinality.ONE_TO_ONE,
            ),
        ),
        output_dimensions=("year_gregorian", "district_code"),
        output_metrics=("population_count", "median_income"),
    )

    assert AnalysisPlanValidator().validate(plan).valid is True


def test_validator_detects_false_cardinality_claim() -> None:
    plan = AnalysisPlan(
        inputs=(_population(), _income()),
        joins=(
            AnalysisJoin(
                left_alias="population",
                right_alias="income",
                keys=("year_gregorian", "district_code"),
                cardinality=JoinCardinality.ONE_TO_ONE,
            ),
        ),
        output_dimensions=("district_code",),
        output_metrics=("population_count",),
    )

    report = AnalysisPlanValidator().validate(plan)

    assert report.valid is False
    assert "CARDINALITY_MISMATCH" in {issue.code for issue in report.issues}


def test_validator_rejects_unknown_join_and_output_fields() -> None:
    plan = AnalysisPlan(
        inputs=(_population(), _income()),
        joins=(
            AnalysisJoin(
                left_alias="population",
                right_alias="income",
                keys=("village_code",),
                cardinality=JoinCardinality.ONE_TO_ONE,
            ),
        ),
        output_dimensions=("unknown_dimension",),
        output_metrics=("unknown_metric",),
    )

    codes = {issue.code for issue in AnalysisPlanValidator().validate(plan).issues}

    assert codes >= {
        "JOIN_KEY_OUTSIDE_GRAIN",
        "UNKNOWN_OUTPUT_DIMENSION",
        "UNKNOWN_OUTPUT_METRIC",
    }


def test_validator_rejects_disconnected_input() -> None:
    plan = AnalysisPlan(
        inputs=(_population(), _income()),
        output_dimensions=("district_code",),
        output_metrics=("population_count",),
    )

    report = AnalysisPlanValidator().validate(plan)

    assert report.valid is False
    assert "UNJOINED_INPUT" in {issue.code for issue in report.issues}
