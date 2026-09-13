"""Deterministic confidence and data-limitation audit attached to every answer.

A grounded number is not the same as a trustworthy one. The same answer can mix
a marriage series published two quarters ago with a housing snapshot published
this week, cover 27 of 29 districts, and count a population whose definitional
basis the catalog never recorded. This module states all three from evidence the
answer already used, so the reader sees the caveats without asking for them.

Nothing here estimates, interpolates, or infers. Every value is read from a
citation, a returned row, or catalog text.
"""

from collections.abc import Iterable, Sequence
from datetime import datetime

from youth_compass.agent.contracts import (
    CoverageGap,
    DataFreshness,
    DataLimitations,
    EvidenceCitation,
    ObservationSeries,
    RegionScheme,
)
from youth_compass.mapping.geography import DISTRICTS
from youth_compass.ontology import (
    RegistrationBasis,
    registration_basis_caveat,
    resolve_district_name,
    resolve_registration_basis,
)

_SECONDS_PER_DAY = 86_400
# Named so a reader can check the denominator behind "27 of 29".
_NEW_TAIPEI_DISTRICT_COUNT = len(DISTRICTS)


class DataLimitationsBuilder:
    """Assemble the limitation block for one answer."""

    def build(
        self,
        *,
        now: datetime,
        citations: Sequence[EvidenceCitation],
        observed_entity_ids: Iterable[str],
        requested_entity_ids: Sequence[str] = (),
        catalog_terms: Sequence[str] = (),
        series: ObservationSeries | None = None,
    ) -> DataLimitations:
        basis = resolve_registration_basis(*catalog_terms)
        basis_note = registration_basis_caveat(basis)
        notes = [basis_note] if basis_note is not None else []
        estimated = _estimated_note(series)
        if estimated is not None:
            notes.append(estimated)
        return DataLimitations(
            freshness=tuple(_freshness(now, citation) for citation in citations),
            coverage=_coverage(observed_entity_ids, requested_entity_ids),
            registration_basis=basis,
            notes=tuple(notes),
        )


def _freshness(now: datetime, citation: EvidenceCitation) -> DataFreshness:
    elapsed = (now - citation.retrieved_at).total_seconds()
    return DataFreshness(
        citation_id=citation.citation_id,
        dataset_id=citation.dataset_id,
        dataset_version=citation.dataset_version,
        published_at=citation.retrieved_at,
        # A clock skew between the catalog and the request must not surface as a
        # negative age; it floors at zero and the timestamp stays visible.
        age_days=max(0, int(elapsed // _SECONDS_PER_DAY)),
    )


def _coverage(
    observed_entity_ids: Iterable[str], requested_entity_ids: Sequence[str]
) -> CoverageGap | None:
    """Compare the districts an answer covers against the districts it implied.

    A question that named districts is judged against exactly those. A question
    that named none asked about the city, so the whole 29-district set is the
    denominator. Entities that are not districts are reported separately rather
    than counted as coverage, because placing them would need a spatial join
    this system does not perform.
    """

    observed_codes: set[str] = set()
    unmapped: list[str] = []
    for entity_id in observed_entity_ids:
        resolution = resolve_district_name(entity_id)
        if resolution.district is None:
            if entity_id and entity_id not in unmapped:
                unmapped.append(entity_id)
            continue
        observed_codes.add(resolution.district.code)

    if requested_entity_ids:
        expected = {
            resolution.district.code
            for entity_id in requested_entity_ids
            if (resolution := resolve_district_name(entity_id)).district is not None
        }
        if not expected:
            return None
    else:
        expected = {district.code for district in DISTRICTS}
        if not observed_codes:
            return None

    missing = sorted(expected - observed_codes)
    by_code = {district.code: district.name for district in DISTRICTS}
    return CoverageGap(
        region_scheme=RegionScheme.NEW_TAIPEI_DISTRICT,
        expected_entity_count=len(expected),
        observed_entity_count=len(observed_codes & expected),
        missing_entity_names=tuple(by_code[code] for code in missing),
        unmapped_entity_ids=tuple(sorted(unmapped)),
    )


def _estimated_note(series: ObservationSeries | None) -> str | None:
    """Report how much of the series came from weighted or derived values."""

    if series is None or not series.points:
        return None
    affected = sum(1 for point in series.points if point.estimated_value > 0)
    if not affected:
        return None
    return (
        f"{affected} of {len(series.points)} observations include values the ingestion "
        "pipeline flagged as estimated, such as an age band split by youth weight rather "
        "than reported directly."
    )


__all__ = ["DataLimitationsBuilder", "RegistrationBasis"]
