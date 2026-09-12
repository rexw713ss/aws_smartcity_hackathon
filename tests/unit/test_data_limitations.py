"""Confidence and data-limitation audit attached to grounded answers."""

from datetime import UTC, datetime

from youth_compass.agent import (
    DataLimitationsBuilder,
    EvidenceCitation,
    ObservationPoint,
    ObservationSeries,
    RegionScheme,
)
from youth_compass.ontology import RegistrationBasis

NOW = datetime(2026, 9, 12, tzinfo=UTC)


def _citation(
    citation_id: str, published: datetime, dataset_id: str = "population"
) -> EvidenceCitation:
    return EvidenceCitation(
        citation_id=citation_id,
        dataset_id=dataset_id,
        dataset_version="v1",
        quality_score=0.95,
        retrieved_at=published,
    )


def _series(points: tuple[ObservationPoint, ...]) -> ObservationSeries:
    return ObservationSeries(
        dataset_id="population",
        dataset_version="v1",
        metric_code="population_count",
        unit_code="persons",
        population_scope="youth_specific",
        points=points,
    )


def test_each_source_reports_its_own_publication_age() -> None:
    limitations = DataLimitationsBuilder().build(
        now=NOW,
        citations=(
            _citation("data-1", datetime(2026, 3, 12, tzinfo=UTC), "marriage"),
            _citation("data-2", datetime(2026, 9, 5, tzinfo=UTC), "housing"),
        ),
        observed_entity_ids=["01"],
    )

    ages = {item.citation_id: item.age_days for item in limitations.freshness}
    assert ages == {"data-1": 184, "data-2": 7}
    assert {item.dataset_id for item in limitations.freshness} == {"marriage", "housing"}


def test_a_source_published_after_the_request_clock_never_reports_a_negative_age() -> None:
    limitations = DataLimitationsBuilder().build(
        now=NOW,
        citations=(_citation("data-1", datetime(2026, 10, 1, tzinfo=UTC)),),
        observed_entity_ids=["01"],
    )

    assert limitations.freshness[0].age_days == 0
    assert limitations.freshness[0].published_at == datetime(2026, 10, 1, tzinfo=UTC)


def test_a_citywide_question_is_measured_against_all_29_districts() -> None:
    limitations = DataLimitationsBuilder().build(
        now=NOW,
        citations=(),
        observed_entity_ids=[f"{index:02d}" for index in range(1, 28)],
    )

    coverage = limitations.coverage
    assert coverage is not None
    assert coverage.region_scheme is RegionScheme.NEW_TAIPEI_DISTRICT
    assert coverage.expected_entity_count == 29
    assert coverage.observed_entity_count == 27
    assert coverage.missing_entity_names == ("貢寮區", "烏來區")


def test_a_question_naming_districts_is_measured_against_only_those() -> None:
    limitations = DataLimitationsBuilder().build(
        now=NOW,
        citations=(),
        observed_entity_ids=["12"],
        requested_entity_ids=["Tamsui", "Lâm Khẩu"],
    )

    coverage = limitations.coverage
    assert coverage is not None
    assert coverage.expected_entity_count == 2
    assert coverage.observed_entity_count == 1
    assert coverage.missing_entity_names == ("林口區",)


def test_entities_outside_the_boundary_set_are_reported_not_counted_as_coverage() -> None:
    limitations = DataLimitationsBuilder().build(
        now=NOW,
        citations=(),
        observed_entity_ids=["banqiao", "site-linkou-center", "site-banqiao-station"],
        requested_entity_ids=["banqiao"],
    )

    coverage = limitations.coverage
    assert coverage is not None
    assert coverage.observed_entity_count == 1
    assert coverage.missing_entity_names == ()
    assert coverage.unmapped_entity_ids == ("site-banqiao-station", "site-linkou-center")


def test_coverage_is_omitted_when_no_entity_belongs_to_the_boundary_set() -> None:
    limitations = DataLimitationsBuilder().build(
        now=NOW,
        citations=(),
        observed_entity_ids=["site-a", "site-b"],
        requested_entity_ids=["site-a", "site-b"],
    )

    assert limitations.coverage is None


def test_the_population_basis_is_read_from_catalog_text_and_always_explained() -> None:
    registered = DataLimitationsBuilder().build(
        now=NOW,
        citations=(),
        observed_entity_ids=["01"],
        catalog_terms=("population", "05_初設戶籍", "population_count"),
    )
    silent = DataLimitationsBuilder().build(
        now=NOW,
        citations=(),
        observed_entity_ids=["01"],
        catalog_terms=("population", "youth_population", "population_count"),
    )

    assert registered.registration_basis is RegistrationBasis.REGISTERED_HOUSEHOLD
    assert "戶籍人口" in registered.notes[0]
    assert silent.registration_basis is RegistrationBasis.UNKNOWN
    assert "does not record" in silent.notes[0]


def test_estimated_observations_are_counted_in_the_notes() -> None:
    series = _series(
        (
            ObservationPoint(entity_id="01", period="2025", value=120.0, estimated_value=30.0),
            ObservationPoint(entity_id="17", period="2025", value=72.0, estimated_value=0.0),
        )
    )

    limitations = DataLimitationsBuilder().build(
        now=NOW, citations=(), observed_entity_ids=["01", "17"], series=series
    )

    assert any("1 of 2 observations" in note for note in limitations.notes)


def test_a_fully_reported_series_adds_no_estimation_note() -> None:
    series = _series(
        (ObservationPoint(entity_id="01", period="2025", value=120.0, estimated_value=0.0),)
    )

    limitations = DataLimitationsBuilder().build(
        now=NOW, citations=(), observed_entity_ids=["01"], series=series
    )

    assert len(limitations.notes) == 1
