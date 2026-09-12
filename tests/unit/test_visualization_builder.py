"""Deterministic visualization contracts for frontend renderers."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from youth_compass.agent import (
    CandidateInsight,
    EntityChange,
    EntityComparison,
    FeatureContributionInsight,
    ObservationPoint,
    ObservationSeries,
    RegionScheme,
    VisualizationBuilder,
    VisualizationSpec,
    VisualizationType,
)
from youth_compass.ports import ForecastPoint, ForecastResult


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

    assert [item.type for item in specs] == [VisualizationType.DATA_TABLE]
    assert specs[0].rows[0]["score"] == 87.5
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

    assert [item.type for item in specs] == [VisualizationType.LINE]
    assert specs[0].x is not None and specs[0].x.field == "period"
    assert specs[0].y is not None and specs[0].y.unit == "persons"
    assert specs[0].series_field == "entity_name"


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

    assert specs == ()


def test_forecast_builds_interval_line_and_table() -> None:
    result = ForecastResult(
        metric_code="population_count",
        model_version="seasonal-naive-v1",
        generated_at=datetime(2026, 9, 1, tzinfo=UTC),
        points=[
            ForecastPoint(
                district_code="banqiao",
                year_gregorian=2027,
                value=121,
                lower=115,
                upper=127,
            )
        ],
    )

    specs = VisualizationBuilder().forecast("預測板橋青年人口", result, ("data-1",))

    assert [item.type for item in specs] == [VisualizationType.DATA_TABLE]
    assert specs[0].rows[0]["lower"] == 115
    assert specs[0].rows[0]["upper"] == 127
    assert specs[0].columns[-1].label == "模型版本"
    assert all(item.citation_ids == ("data-1",) for item in specs)


def test_observation_map_shades_one_period_and_names_its_boundary_scheme() -> None:
    series = ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=(
            ObservationPoint(entity_id="淡水區", period="2024", value=90.0, estimated_value=0.0),
            ObservationPoint(entity_id="淡水區", period="2025", value=100.0, estimated_value=0.0),
            ObservationPoint(entity_id="Linkou", period="2025", value=72.0, estimated_value=0.0),
        ),
    )

    specs = VisualizationBuilder().observations(
        "Show population by district on a map", series, None, ("data-1",)
    )
    mapped = next(item for item in specs if item.type is VisualizationType.CHOROPLETH)

    assert mapped.region_field == "district_code"
    assert mapped.region_scheme is RegionScheme.NEW_TAIPEI_DISTRICT
    # Only the latest period is shaded, and both spellings become canonical codes.
    assert {row["district_code"]: row["value"] for row in mapped.rows} == {"12": 100.0, "17": 72.0}
    assert {row["period"] for row in mapped.rows} == {"2025"}
    assert mapped.citation_ids == ("data-1",)
    # A table fallback keeps the figures readable without a boundary file.
    assert [column.field for column in mapped.columns] == [
        "district_code",
        "district_name",
        "value",
    ]


def test_no_map_is_built_when_nothing_resolves_to_a_district() -> None:
    candidate = CandidateInsight(
        rank=1,
        entity_id="site-banqiao-station",
        entity_name="Banqiao Station",
        eligible=True,
        score=87.5,
    )

    specs = VisualizationBuilder().decision("Where should the charger go?", (candidate,), ())

    assert all(item.type is not VisualizationType.CHOROPLETH for item in specs)


def test_a_map_spec_must_declare_both_region_fields() -> None:
    with pytest.raises(ValidationError):
        VisualizationSpec(
            visualization_id="bad-map",
            type=VisualizationType.CHOROPLETH,
            title="No scheme",
            rows=({"district_code": "01", "value": 1.0},),
        )
    with pytest.raises(ValidationError):
        VisualizationSpec(
            visualization_id="bad-line",
            type=VisualizationType.LINE,
            title="Not a map",
            region_field="district_code",
            region_scheme=RegionScheme.NEW_TAIPEI_DISTRICT,
        )


def test_a_candidate_without_a_published_name_is_labelled_from_its_identifier() -> None:
    candidate = CandidateInsight(
        rank=1,
        entity_id="site-linkou-center",
        entity_name="site-linkou-center",
        eligible=True,
        score=55.0,
        contributions=(
            FeatureContributionInsight(
                feature_code="ev_demand_proxy",
                feature_name="ev_demand_proxy",
                raw_value=77,
                effective_weight=0.3,
                points=21,
                citations=("data-1",),
            ),
        ),
    )

    specs = VisualizationBuilder().decision(
        "Where should we place an EV charging station?", (candidate,), ("data-1",)
    )

    assert len(specs) == 1
    table = specs[0]
    assert table.type is VisualizationType.DATA_TABLE
    assert table.rows[0]["entity_name"] == "Linkou Center"


def test_a_published_feature_name_wins_over_the_derived_one() -> None:
    candidate = CandidateInsight(
        rank=1,
        entity_id="site-linkou-center",
        eligible=True,
        score=55.0,
        contributions=(
            FeatureContributionInsight(
                feature_code="charger_competition",
                feature_name="Charger competition",
                raw_value=35,
                effective_weight=0.2,
                points=10,
                citations=("data-1",),
            ),
            FeatureContributionInsight(
                feature_code="grid_accessibility",
                feature_name="Grid accessibility",
                raw_value=80,
                effective_weight=0.3,
                points=20,
                citations=("data-1",),
            ),
        ),
    )

    specs = VisualizationBuilder().decision(
        "Where should the charger go?", (candidate,), ("data-1",)
    )

    contributions = next(item for item in specs if item.type is VisualizationType.CONTRIBUTION_BAR)
    assert [row["feature_name"] for row in contributions.rows] == [
        "Grid accessibility",
        "Charger competition",
    ]


def test_a_chinese_question_names_forecast_districts_in_chinese() -> None:
    result = ForecastResult(
        metric_code="youth_population_total",
        model_version="v1",
        generated_at=datetime(2026, 9, 1, tzinfo=UTC),
        points=(
            ForecastPoint(
                district_code="17",
                year_gregorian=2030,
                value=1000,
                lower=900,
                upper=1100,
            ),
            ForecastPoint(
                district_code="17",
                year_gregorian=2031,
                value=1020,
                lower=910,
                upper=1130,
            ),
        ),
    )

    english = VisualizationBuilder().forecast("How many youth in 2030?", result, ("data-1",))
    chinese = VisualizationBuilder().forecast(
        "2030年的青年人口有多少？",  # noqa: RUF001
        result,
        ("data-1",),
    )

    assert english[0].rows[0]["entity_name"] == "Linkou"
    assert english[0].title.startswith("Youth population total")
    assert chinese[0].rows[0]["entity_name"] == "林口區"


def test_sparse_entities_are_excluded_from_a_line_without_a_duplicate_table() -> None:
    series = ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=(
            ObservationPoint(entity_id="banqiao", period="2024", value=100, estimated_value=0),
            ObservationPoint(entity_id="banqiao", period="2025", value=120, estimated_value=0),
            ObservationPoint(entity_id="linkou", period="2025", value=80, estimated_value=0),
        ),
    )

    specs = VisualizationBuilder().observations("Population trend", series, None, ("data-1",))

    assert [item.type for item in specs] == [VisualizationType.LINE]
    assert {row["entity_id"] for row in specs[0].rows} == {"banqiao"}


def test_map_is_omitted_when_districts_have_no_common_period() -> None:
    series = ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=(
            ObservationPoint(entity_id="banqiao", period="2025", value=120, estimated_value=0),
            ObservationPoint(entity_id="linkou", period="2024", value=80, estimated_value=0),
        ),
    )

    specs = VisualizationBuilder().observations(
        "Show population by district on a map", series, None, ("data-1",)
    )

    assert specs == ()


def test_zero_contributions_do_not_create_a_misleading_bar_chart() -> None:
    candidates = (
        CandidateInsight(
            rank=1,
            entity_id="site-a",
            eligible=True,
            score=60,
            contributions=(
                FeatureContributionInsight(
                    feature_code="ev_demand_proxy",
                    raw_value=0,
                    effective_weight=0.5,
                    points=0,
                    citations=("data-1",),
                ),
                FeatureContributionInsight(
                    feature_code="grid_accessibility",
                    raw_value=80,
                    effective_weight=0.5,
                    points=40,
                    citations=("data-1",),
                ),
            ),
        ),
        CandidateInsight(rank=2, entity_id="site-b", eligible=True, score=40),
    )

    specs = VisualizationBuilder().decision("Where should the charger go?", candidates, ("data-1",))

    assert [item.type for item in specs] == [VisualizationType.RANKING_BAR]


def test_ranking_chart_keeps_top_twelve_and_table_keeps_every_candidate() -> None:
    candidates = tuple(
        CandidateInsight(
            rank=index,
            entity_id=f"site-{index}",
            eligible=True,
            score=float(100 - index),
        )
        for index in range(1, 16)
    )

    specs = VisualizationBuilder().decision("Rank candidate sites", candidates, ("data-1",))

    ranking = next(item for item in specs if item.type is VisualizationType.RANKING_BAR)
    table = next(item for item in specs if item.type is VisualizationType.DATA_TABLE)
    assert len(ranking.rows) == 12
    assert ranking.truncated is True
    assert len(table.rows) == 15


def test_line_chart_limits_series_without_a_duplicate_observation_table() -> None:
    series = ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=tuple(
            ObservationPoint(
                entity_id=f"district-{entity}",
                period=str(period),
                value=float(entity * 10 + period),
                estimated_value=0,
            )
            for entity in range(10)
            for period in (2024, 2025)
        ),
    )

    specs = VisualizationBuilder().observations("Population trend", series, None, ("data-1",))

    line = next(item for item in specs if item.type is VisualizationType.LINE)
    assert len({row["entity_id"] for row in line.rows}) == 8
    assert line.truncated is True
    assert all(item.type is not VisualizationType.DATA_TABLE for item in specs)


def test_monthly_line_marks_a_missing_period_and_preserves_key_points_when_sampled() -> None:
    points = []
    for year in range(2018, 2024):
        for month in range(1, 13):
            if (year, month) == (2019, 9):
                continue
            value = float(25_000 + (year - 2018) * 500 + month * 10)
            if (year, month) == (2021, 6):
                value = 30_000
            points.append(
                ObservationPoint(
                    entity_id="linkou",
                    entity_name="林口區",
                    period=f"{year:04d}-{month:02d}",
                    value=value,
                    estimated_value=0,
                )
            )
    series = ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=tuple(points),
    )

    specs = VisualizationBuilder().observations("Population trend in Linkou", series, None, ())

    line = specs[0]
    assert len(line.rows) <= 48
    assert line.truncated is True
    assert any(row["period"] == "2019-09" and row["value"] is None for row in line.rows)
    assert any(row["period"] == "2021-06" and row["value"] == 30_000 for row in line.rows)
    assert line.rows[0]["period"] == "2018-01"
    assert line.rows[-1]["period"] == "2023-12"
