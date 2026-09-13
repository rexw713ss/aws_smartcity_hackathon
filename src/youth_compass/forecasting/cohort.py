"""Hamilton-Perry cohort change ratio projection of the youth (18-35) population.

Pure and IO-free. A cohort change ratio is the share of people aged ``a`` in one
annual snapshot who appear, aged ``a + 1``, in the same district one year later.
It folds survival, migration, and registration change into one observed number,
so no fertility, mortality, or migration assumption has to be invented. For any
horizon below 18 years every person who will be 18-35 is already counted today,
which is why ratios for ages 0-34 are sufficient.

Each projection splits exactly into people reaching 18, people passing 35, and
the change beyond ageing, so an answer can say why a district's youth count moves.
See docs/31-youth-population-forecast.md for the method and its references.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from statistics import median

MODEL_VERSION = "cohort-change-ratio-v1"
YOUTH_MIN_AGE = 18
YOUTH_MAX_AGE = 35
# Ratio pairs are drawn from this many calendar years before the origin, so a
# missing year shortens the window instead of reaching further into the past.
DEFAULT_WINDOW_YEARS = 5
# The youngest age ever needed: a horizon of 17 years moves age 1 to 18.
MAX_HORIZON_YEARS = YOUTH_MIN_AGE - 1

# year -> district code -> single year of age -> registered persons
Snapshots = Mapping[int, Mapping[str, Mapping[int, float]]]
# district code -> age -> cohort change ratio from that age to the next
ChangeRatios = dict[str, dict[int, float]]


class CohortInputError(ValueError):
    """The snapshots cannot support a cohort projection."""


@dataclass(frozen=True, slots=True)
class CohortProjection:
    """One district's projected youth count ``horizon`` years after the origin."""

    district_code: str
    origin_year: int
    horizon: int
    value: float
    base_value: float
    entering: float
    ageing_out: float
    net_change: float

    @property
    def year(self) -> int:
        return self.origin_year + self.horizon


def youth_count(ages: Mapping[int, float]) -> float:
    """Registered persons aged 18 through 35 in one snapshot."""

    return float(sum(ages.get(age, 0.0) for age in range(YOUTH_MIN_AGE, YOUTH_MAX_AGE + 1)))


def estimate_change_ratios(
    snapshots: Snapshots,
    origin_year: int,
    *,
    window_years: int = DEFAULT_WINDOW_YEARS,
) -> ChangeRatios:
    """Median cohort change ratio per district and age from the recent window.

    Only consecutive-year pairs ending at or before ``origin_year`` are used, so
    a backtest never sees the future. A district-age with no usable pair (a zero
    count in every year) takes the city-wide ratio for that age and window,
    which is the pooled experience of the same cohort elsewhere.

    Raises:
        CohortInputError: the window holds no consecutive pair of snapshots.
    """

    if window_years < 1:
        raise CohortInputError("window_years must be at least 1")
    pair_starts = [
        year
        for year in range(origin_year - window_years, origin_year)
        if year in snapshots and year + 1 in snapshots
    ]
    if not pair_starts:
        raise CohortInputError(
            f"no consecutive annual snapshots in the {window_years} years before {origin_year}"
        )
    districts = sorted(snapshots[origin_year]) if origin_year in snapshots else []
    if not districts:
        raise CohortInputError(f"no snapshot exists for origin year {origin_year}")

    city: dict[int, float] = {}
    for age in range(0, YOUTH_MAX_AGE):
        pooled: list[float] = []
        for year in pair_starts:
            # Only districts that had the cohort contribute where it went, or a
            # district with no one at this age would inflate the pooled ratio.
            counted = [
                code for code in districts if snapshots[year].get(code, {}).get(age, 0.0) > 0
            ]
            before = sum(snapshots[year][code][age] for code in counted)
            after = sum(snapshots[year + 1].get(code, {}).get(age + 1, 0.0) for code in counted)
            if before > 0:
                pooled.append(after / before)
        if not pooled:
            raise CohortInputError(f"no district has a positive count at age {age}")
        city[age] = median(pooled)

    ratios: ChangeRatios = {}
    for code in districts:
        by_age: dict[int, float] = {}
        for age in range(0, YOUTH_MAX_AGE):
            observed = [
                snapshots[year + 1].get(code, {}).get(age + 1, 0.0) / before
                for year in pair_starts
                if (before := snapshots[year].get(code, {}).get(age, 0.0)) > 0
            ]
            by_age[age] = median(observed) if observed else city[age]
        ratios[code] = by_age
    return ratios


def project_youth(
    district_code: str,
    base_ages: Mapping[int, float],
    ratios: Mapping[int, float],
    *,
    origin_year: int,
    horizon: int,
) -> CohortProjection:
    """Age the origin cohorts forward ``horizon`` years and sum ages 18-35."""

    if not 1 <= horizon <= MAX_HORIZON_YEARS:
        raise CohortInputError(f"horizon must be between 1 and {MAX_HORIZON_YEARS} years")
    value = 0.0
    for age in range(YOUTH_MIN_AGE - horizon, YOUTH_MAX_AGE + 1 - horizon):
        cohort = float(base_ages.get(age, 0.0))
        for step in range(age, age + horizon):
            cohort *= ratios[step]
        value += cohort
    base_value = youth_count(base_ages)
    entering = float(
        sum(base_ages.get(age, 0.0) for age in range(YOUTH_MIN_AGE - horizon, YOUTH_MIN_AGE))
    )
    ageing_out = float(
        sum(
            base_ages.get(age, 0.0) for age in range(YOUTH_MAX_AGE + 1 - horizon, YOUTH_MAX_AGE + 1)
        )
    )
    return CohortProjection(
        district_code=district_code,
        origin_year=origin_year,
        horizon=horizon,
        value=value,
        base_value=base_value,
        entering=entering,
        ageing_out=ageing_out,
        net_change=value - (base_value + entering - ageing_out),
    )
