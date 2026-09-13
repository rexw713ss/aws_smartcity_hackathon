"""Deterministic visualization contracts for frontend renderers."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from youth_compass.agent import (
    AnalysisOperation,
    AnnotationKind,
    CandidateInsight,
    DecomposedQuery,
    EntityChange,
    EntityComparison,
    FeatureContributionInsight,
    ObservationPoint,
    ObservationSeries,
    RegionScheme,
    VisualizationBuilder,
    VisualizationSpec,
    VisualizationType,
    choose_measure,
    profile_series,
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
                # Each district has to actually move, or selection rejects the
                # line as a picture of nothing before series limiting is reached.
                value=float((entity + 1) * 100 * (1.0 + 0.1 * (period - 2023))),
                estimated_value=0,
            )
            for entity in range(10)
            # Three periods keep this a line: two would make it a slope, which
            # has its own test.
            for period in (2023, 2024, 2025)
        ),
    )

    specs = VisualizationBuilder().observations("Population trend", series, None, ("data-1",))

    line = next(item for item in specs if item.type is VisualizationType.LINE)
    assert len({row["entity_id"] for row in line.rows}) == 8
    assert line.truncated is True
    assert all(item.type is not VisualizationType.DATA_TABLE for item in specs)


def test_long_multi_series_line_uses_one_sorted_sampling_timeline() -> None:
    series = ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=tuple(
            ObservationPoint(
                entity_id=f"district-{entity}",
                entity_name=f"District {entity}",
                period=f"{year:04d}-{month:02d}",
                value=float(100_000 - entity * 7_000 - offset * 100 * (entity + 1)),
                estimated_value=0,
            )
            for entity in range(8)
            for offset, (year, month) in enumerate(
                (index // 12, index % 12 + 1) for index in range(2023 * 12, 2026 * 12)
            )
        ),
    )

    line = VisualizationBuilder().observations("Population trend", series, None, ())[0]
    periods = [str(row["period"]) for row in line.rows]
    unique_periods = sorted(set(periods))

    assert periods == sorted(periods)
    assert len(unique_periods) <= 25
    assert {row["entity_id"] for row in line.rows if row["period"] == unique_periods[10]} == {
        f"district-{entity}" for entity in range(8)
    }


def test_monthly_line_chooses_quarterly_cadence_after_reading_missingness() -> None:
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
    assert len(line.rows) == 24
    assert line.truncated is True
    assert all(row["value"] is not None for row in line.rows)
    assert any(
        row["period"] == "2021-Q2" and row["source_period"] == "2021-06" and row["value"] == 30_000
        for row in line.rows
    )
    assert line.rows[0]["period"] == "2018-Q1"
    assert line.rows[-1]["period"] == "2023-Q4"
    assert line.description is None


def test_a_year_hole_uses_only_one_continuous_point_per_two_year_block() -> None:
    points = tuple(
        ObservationPoint(
            entity_id="linkou",
            period=f"{year:04d}-{month:02d}",
            value=float(200_000 - (year - 2011) * 5_000 - month * 10),
            estimated_value=0,
        )
        for year in range(2011, 2027)
        if year != 2017
        for month in range(1, 13)
    )
    series = ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=points,
    )

    line = VisualizationBuilder().observations("Population trend in Linkou", series, None, ())[0]

    assert [row["period"] for row in line.rows] == [
        "2012",
        "2014",
        "2016",
        "2018",
        "2020",
        "2022",
        "2024",
        "2026",
    ]
    assert all(row["value"] is not None for row in line.rows)
    assert line.description is None


def _observation_series(values: dict[str, dict[str, float]]) -> ObservationSeries:
    return ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=tuple(
            ObservationPoint(
                entity_id=entity,
                entity_name=entity.title(),
                period=period,
                value=value,
                estimated_value=0,
            )
            for entity, points in values.items()
            for period, value in points.items()
        ),
    )


def _decomposition(*entity_ids: str) -> DecomposedQuery:
    return DecomposedQuery(
        original_question="how did the youth population change by district",
        objective="describe the change",
        entity_ids=entity_ids,
        operations=(AnalysisOperation.QUERY_OBSERVATIONS,),
    )


def test_one_named_district_never_earns_a_map_even_when_the_word_district_appears() -> None:
    series = _observation_series(
        {
            "banqiao": {"2022": 1000.0, "2023": 800.0},
            "xindian": {"2022": 900.0, "2023": 880.0},
        }
    )

    candidates = VisualizationBuilder().observation_candidates(
        "How did the youth population of Banqiao district change?",
        series,
        None,
        ("data-1",),
        decomposition=_decomposition("banqiao"),
    )

    assert all(
        candidate.intent_fit == 0.0
        for candidate in candidates
        if candidate.spec.type is VisualizationType.CHOROPLETH
    )


def test_an_explicitly_spatial_question_gives_the_map_full_intent_fit() -> None:
    series = _observation_series(
        {
            "banqiao": {"2022": 1000.0, "2023": 800.0},
            "xindian": {"2022": 900.0, "2023": 880.0},
        }
    )

    candidates = VisualizationBuilder().observation_candidates(
        "Where did the youth population fall the most?",
        series,
        None,
        ("data-1",),
        decomposition=_decomposition(),
    )
    mapped = [
        candidate for candidate in candidates if candidate.spec.type is VisualizationType.CHOROPLETH
    ]

    assert mapped and mapped[0].intent_fit == 1.0


def test_a_city_wide_question_without_spatial_wording_keeps_the_map_as_a_weaker_option() -> None:
    series = _observation_series(
        {
            "banqiao": {"2022": 1000.0, "2023": 800.0},
            "xindian": {"2022": 900.0, "2023": 880.0},
        }
    )

    candidates = VisualizationBuilder().observation_candidates(
        "How has the youth population changed?",
        series,
        None,
        ("data-1",),
        decomposition=_decomposition(),
    )
    mapped = [
        candidate for candidate in candidates if candidate.spec.type is VisualizationType.CHOROPLETH
    ]

    # The question covers every district, so a map is defensible, but nothing in
    # it asks for one: it only wins if no stronger view competes for the slot.
    assert mapped and mapped[0].intent_fit == 0.5


def test_an_index_measure_rescales_the_line_without_methodology_on_the_chart() -> None:
    series = _observation_series(
        {
            "banqiao": {"2022": 50000.0, "2023": 49000.0},
            "pinglin": {"2022": 500.0, "2023": 400.0},
        }
    )
    profile = profile_series(series)
    measure = choose_measure(profile, _decomposition())

    specs = VisualizationBuilder().observations(
        "How did the youth population change?",
        series,
        None,
        ("data-1",),
        decomposition=_decomposition(),
        measure=measure,
        profile=profile,
    )
    line = next(item for item in specs if item.type is VisualizationType.LINE)
    values = {(row["entity_name"], row["period"]): row["value"] for row in line.rows}

    assert line.y is not None and line.y.unit == "index_100"
    assert values[("Banqiao", "2022")] == 100.0
    assert values[("Pinglin", "2023")] == 80.0
    # Every plotted point still carries the published figure it was derived from.
    assert all("source_value" in row for row in line.rows)
    assert line.description is None


def test_a_percentage_measure_moves_the_comparison_bar_off_absolute_change() -> None:
    series = _observation_series(
        {
            "banqiao": {"2022": 50000.0, "2023": 49000.0},
            "pinglin": {"2022": 500.0, "2023": 250.0},
        }
    )
    comparison = EntityComparison(
        metric_code="population_count",
        unit_code="persons",
        changes=(
            EntityChange(
                entity_id="banqiao",
                entity_name="Banqiao",
                first_period="2022",
                last_period="2023",
                first_value=50000,
                last_value=49000,
                absolute_change=-1000,
                percent_change=-2.0,
                direction="decreased",
                observation_count=2,
            ),
            EntityChange(
                entity_id="pinglin",
                entity_name="Pinglin",
                first_period="2022",
                last_period="2023",
                first_value=500,
                last_value=250,
                absolute_change=-250,
                percent_change=-50.0,
                direction="decreased",
                observation_count=2,
            ),
        ),
    )
    profile = profile_series(series)
    measure = choose_measure(
        profile,
        DecomposedQuery(
            original_question="which district fell fastest",
            objective="compare the fall",
            operations=(
                AnalysisOperation.QUERY_OBSERVATIONS,
                AnalysisOperation.COMPARE_ENTITIES,
            ),
        ),
    )

    specs = VisualizationBuilder().observations(
        "Which district fell fastest?",
        series,
        comparison,
        ("data-1",),
        measure=measure,
        profile=profile,
    )
    bar = next(item for item in specs if item.type is VisualizationType.COMPARISON_BAR)

    assert bar.y is not None and bar.y.field == "percent_change"
    assert bar.y.unit == "percent"
    # Absolute change would have ranked the large district first purely on size.
    assert bar.rows[0]["entity_name"] == "Pinglin"


def test_a_conflicting_observation_result_produces_no_chart_at_all() -> None:
    series = ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=(
            ObservationPoint(entity_id="banqiao", period="2022", value=1000.0, estimated_value=0),
            ObservationPoint(entity_id="banqiao", period="2023", value=800.0, estimated_value=0),
            ObservationPoint(entity_id="banqiao", period="2023", value=900.0, estimated_value=0),
        ),
    )

    specs = VisualizationBuilder().observations(
        "How did the youth population change?",
        series,
        None,
        ("data-1",),
        profile=profile_series(series),
    )

    assert specs == ()


def test_a_forecast_line_carries_the_interval_it_was_published_with() -> None:
    result = ForecastResult(
        metric_code="population_count",
        model_version="baseline-v1",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        points=(
            ForecastPoint(
                district_code="65000010",
                year_gregorian=2026,
                value=1000.0,
                lower=900.0,
                upper=1100.0,
            ),
            ForecastPoint(
                district_code="65000010", year_gregorian=2027, value=800.0, lower=650.0, upper=950.0
            ),
        ),
    )

    specs = VisualizationBuilder().forecast("Project the youth population", result, ("data-1",))
    line = next(item for item in specs if item.type is VisualizationType.LINE)

    assert line.band_lower_field == "lower"
    assert line.band_upper_field == "upper"
    assert {row["lower"] for row in line.rows} == {900.0, 650.0}


def test_two_periods_across_several_districts_become_a_slope_not_a_line() -> None:
    series = _observation_series(
        {
            "banqiao": {"2022": 1000.0, "2023": 800.0},
            "xindian": {"2022": 900.0, "2023": 1100.0},
            "sanchong": {"2022": 700.0, "2023": 500.0},
        }
    )

    specs = VisualizationBuilder().observations(
        "How did the youth population change?", series, None, ("data-1",)
    )

    assert any(item.type is VisualizationType.SLOPE for item in specs)
    assert all(item.type is not VisualizationType.LINE for item in specs)


def test_two_periods_across_two_districts_stay_a_line() -> None:
    series = _observation_series(
        {
            "banqiao": {"2022": 1000.0, "2023": 800.0},
            "xindian": {"2022": 900.0, "2023": 1100.0},
        }
    )

    specs = VisualizationBuilder().observations(
        "How did the youth population change?", series, None, ("data-1",)
    )

    assert any(item.type is VisualizationType.LINE for item in specs)


def test_a_band_may_not_be_declared_with_only_one_edge() -> None:
    with pytest.raises(ValidationError):
        VisualizationSpec(
            visualization_id="half-band",
            type=VisualizationType.LINE,
            title="Forecast",
            x={"field": "period", "label": "Period", "data_type": "temporal"},
            y={"field": "value", "label": "Value", "data_type": "quantitative"},
            band_lower_field="lower",
            rows=({"period": "2026", "value": 1.0, "lower": 0.5},),
        )


def test_only_a_line_may_carry_a_band() -> None:
    with pytest.raises(ValidationError):
        VisualizationSpec(
            visualization_id="banded-bar",
            type=VisualizationType.COMPARISON_BAR,
            title="Change",
            x={"field": "entity_name", "label": "Entity", "data_type": "nominal"},
            y={"field": "value", "label": "Value", "data_type": "quantitative"},
            band_lower_field="lower",
            band_upper_field="upper",
            rows=({"entity_name": "A", "value": 1.0, "lower": 0.5, "upper": 1.5},),
        )


def test_a_trend_chart_states_its_finding_and_marks_the_place_that_moved() -> None:
    series = _observation_series(
        {
            "banqiao": {"2020": 1000.0, "2021": 1005.0, "2022": 1002.0},
            "pinglin": {"2020": 500.0, "2021": 700.0, "2022": 300.0},
            "xindian": {"2020": 800.0, "2021": 805.0, "2022": 810.0},
        }
    )

    specs = VisualizationBuilder().observations(
        "How did the youth population change?", series, None, ("data-1",)
    )
    line = next(item for item in specs if item.type is VisualizationType.LINE)

    assert line.headline is not None
    assert "Pinglin" in line.headline and "fell" in line.headline and "40.0%" in line.headline
    assert line.focus_entities == ("Pinglin",)
    # The interior high point is not an endpoint, so naming it tells the reader
    # something the axis does not.
    peak = next(item for item in line.annotations if item.kind is AnnotationKind.PEAK)
    assert peak.period == "2021" and peak.value == 700.0


def test_endpoints_are_never_annotated_as_a_peak_or_trough() -> None:
    series = _observation_series(
        {
            "banqiao": {"2020": 1000.0, "2021": 900.0, "2022": 800.0},
            "xindian": {"2020": 500.0, "2021": 490.0, "2022": 480.0},
            "sanchong": {"2020": 700.0, "2021": 690.0, "2022": 680.0},
        }
    )

    specs = VisualizationBuilder().observations(
        "How did the youth population change?", series, None, ("data-1",)
    )
    line = next(item for item in specs if item.type is VisualizationType.LINE)

    assert line.annotations == ()


def test_three_or_more_places_get_a_median_line_to_read_against() -> None:
    series = _observation_series(
        {
            "banqiao": {"2020": 1000.0, "2021": 800.0},
            "xindian": {"2020": 500.0, "2021": 400.0},
            "sanchong": {"2020": 700.0, "2021": 600.0},
        }
    )

    specs = VisualizationBuilder().observations(
        "How did the youth population change?", series, None, ("data-1",)
    )
    chart = next(item for item in specs if item.reference_lines)

    assert chart.reference_lines[0].value == 600.0
    assert "2021" in chart.reference_lines[0].label


def test_two_places_are_not_enough_to_describe_a_middle() -> None:
    series = _observation_series(
        {
            "banqiao": {"2020": 1000.0, "2021": 800.0},
            "xindian": {"2020": 500.0, "2021": 400.0},
        }
    )

    specs = VisualizationBuilder().observations(
        "How did the youth population change?", series, None, ("data-1",)
    )

    assert all(item.reference_lines == () for item in specs)


def test_the_headline_is_written_in_the_language_of_the_question() -> None:
    series = _observation_series(
        {
            "banqiao": {"2020": 1000.0, "2021": 600.0},
            "xindian": {"2020": 500.0, "2021": 495.0},
        }
    )

    specs = VisualizationBuilder().observations(
        "Dân số thanh niên thay đổi thế nào?", series, None, ("data-1",)
    )
    line = next(item for item in specs if item.type is VisualizationType.LINE)

    assert line.headline is not None and "giảm" in line.headline
