"""Deterministic visualization contracts for frontend renderers."""

from youth_compass.agent import (
    CandidateInsight,
    EntityChange,
    EntityComparison,
    FeatureContributionInsight,
    ObservationPoint,
    ObservationSeries,
    VisualizationBuilder,
    VisualizationType,
)


def test_decision_builds_ranking_contribution_and_table_specs() -> None:
    candidate = CandidateInsight(
        rank=1,
        entity_id="banqiao",
        entity_name="Banqiao",
        eligible=True,
        score=87.5,
        contributions=(
            FeatureContributionInsight(
                feature_code="transit_accessibility",
                raw_value=90,
                effective_weight=0.4,
                points=36,
                citations=("data-1",),
            ),
        ),
    )

    specs = VisualizationBuilder().decision("Where should I buy a home?", (candidate,), ("data-1",))

    assert [item.type for item in specs] == [
        VisualizationType.RANKING_BAR,
        VisualizationType.CONTRIBUTION_BAR,
        VisualizationType.DATA_TABLE,
    ]
    assert specs[0].rows[0]["score"] == 87.5
    assert specs[1].rows[0]["points"] == 36
    assert all(item.citation_ids == ("data-1",) for item in specs)


def test_observations_build_line_comparison_and_table_with_stable_fields() -> None:
    series = ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=(
            ObservationPoint(
                entity_id="banqiao",
                entity_name="Banqiao",
                period="2024",
                value=100,
                estimated_value=0,
            ),
            ObservationPoint(
                entity_id="banqiao",
                entity_name="Banqiao",
                period="2025",
                value=120,
                estimated_value=0,
            ),
        ),
    )
    comparison = EntityComparison(
        metric_code="population_count",
        unit_code="persons",
        changes=(
            EntityChange(
                entity_id="banqiao",
                entity_name="Banqiao",
                first_period="2024",
                last_period="2025",
                first_value=100,
                last_value=120,
                absolute_change=20,
                percent_change=20,
                direction="increased",
                observation_count=2,
            ),
        ),
    )

    specs = VisualizationBuilder().observations(
        "Compare the population trend", series, comparison, ("data-1",)
    )

    assert [item.type for item in specs] == [
        VisualizationType.LINE,
        VisualizationType.COMPARISON_BAR,
        VisualizationType.DATA_TABLE,
    ]
    assert specs[0].x is not None and specs[0].x.field == "period"
    assert specs[0].y is not None and specs[0].y.unit == "persons"
    assert specs[0].series_field == "entity_name"
    assert specs[1].rows[0]["absolute_change"] == 20


def test_traditional_chinese_question_localizes_labels_not_data_fields() -> None:
    series = ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=(
            ObservationPoint(
                entity_id="banqiao", entity_name="板橋", period="2025", value=120, estimated_value=0
            ),
        ),
    )

    specs = VisualizationBuilder().observations(
        "板橋的人口趨勢如何？",  # noqa: RUF001
        series,
        None,
        ("data-1",),
    )

    assert specs[0].title.endswith("趨勢")
    assert specs[0].x is not None and specs[0].x.label == "期間"
    assert specs[0].rows[0]["entity_name"] == "板橋"
    assert "period" in specs[0].rows[0]
