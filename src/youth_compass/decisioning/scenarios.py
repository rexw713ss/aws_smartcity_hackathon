"""Auditable cohort-based what-if scenarios for district youth population.

The engine ages observed single-year cohorts forward and makes every retention
or migration assumption explicit. It does not infer a causal policy effect.
"""

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from statistics import median

import duckdb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from youth_compass.domain.errors import AnalyticsNotAvailableError, QueryNotPermittedError
from youth_compass.ontology import NameLanguage, localized_district_name, resolve_district_name


class ScenarioOperation(StrEnum):
    """Allowlisted transformations of one district population."""

    ABSOLUTE_CHANGE = "absolute_change"
    PERCENT_CHANGE = "percent_change"
    TRANSFER = "transfer"
    ANNUAL_NET_MIGRATION = "annual_net_migration"
    RETENTION_RATE_CHANGE = "retention_rate_change"
    MATCH_CITY_RETENTION = "match_city_retention"
    MATCH_TOP_QUARTILE_RETENTION = "match_top_quartile_retention"


class PopulationBalanceMode(StrEnum):
    """Whether a change alters the city total or redistributes it."""

    OPEN = "open"
    REDISTRIBUTE = "redistribute"


class EvidenceKind(StrEnum):
    """Origin of a number shown in a scenario response."""

    OFFICIAL = "official"
    DERIVED = "derived"
    USER_ASSUMPTION = "user_assumption"


class ScenarioAdjustment(BaseModel):
    """One explicit, reviewable user assumption."""

    model_config = ConfigDict(frozen=True)

    district_id: str = Field(min_length=1, max_length=80)
    operation: ScenarioOperation
    value: float = Field(default=0, ge=-1_000_000, le=1_000_000)
    source_district_id: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_operation(self) -> "ScenarioAdjustment":
        if self.operation is ScenarioOperation.TRANSFER:
            if self.source_district_id is None:
                raise ValueError("a transfer requires source_district_id")
            if self.value <= 0:
                raise ValueError("a transfer value must be greater than zero")
        elif self.source_district_id is not None:
            raise ValueError("source_district_id is only valid for a transfer")
        if (
            self.operation
            in {
                ScenarioOperation.PERCENT_CHANGE,
                ScenarioOperation.RETENTION_RATE_CHANGE,
            }
            and self.value < -100
        ):
            raise ValueError("a percent change cannot reduce a population by more than 100%")
        return self


class ScenarioEvidence(BaseModel):
    """A source or assumption disclosed by the calculation."""

    kind: EvidenceKind
    label: str
    detail: str
    source_url: str | None = None


class DistrictScenarioResult(BaseModel):
    """Before/after result for one canonical district."""

    district_code: str
    district_name: str
    baseline_value: int = Field(ge=0)
    scenario_value: int = Field(ge=0)
    absolute_delta: int
    percent_delta: float | None
    baseline_rank: int = Field(ge=1)
    scenario_rank: int = Field(ge=1)
    rank_change: int
    historical_retention_rate: float | None = None
    scenario_retention_rate: float | None = None


class ScenarioTrajectoryPoint(BaseModel):
    """City-wide projected totals at one year."""

    year: int
    baseline_value: int = Field(ge=0)
    scenario_value: int = Field(ge=0)
    absolute_delta: int


class YouthPopulationScenarioResult(BaseModel):
    """A deterministic comparison with enough context to audit every number."""

    metric_code: str = "youth_population_18_35"
    observed_period: str
    target_year: int
    baseline_method: str
    age_lower: int = 18
    age_upper: int = 35
    balance_mode: PopulationBalanceMode
    baseline_total: int = Field(ge=0)
    scenario_total: int = Field(ge=0)
    total_delta: int
    population_conserved: bool
    rows: tuple[DistrictScenarioResult, ...]
    trajectory: tuple[ScenarioTrajectoryPoint, ...]
    evidence: tuple[ScenarioEvidence, ...]
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]
    generated_at: datetime


class YouthPopulationScenarioService:
    """Project observed cohorts under explicit retention and migration assumptions."""

    _SOURCE_URL = "https://www.ca.ntpc.gov.tw/"

    def __init__(self, population_csv: Path) -> None:
        self._population_csv = population_csv.resolve()

    def run(
        self,
        adjustments: tuple[ScenarioAdjustment, ...],
        *,
        balance_mode: PopulationBalanceMode,
        target_year: int | None = None,
    ) -> YouthPopulationScenarioResult:
        if not adjustments:
            raise QueryNotPermittedError("a what-if scenario requires at least one adjustment")
        period, ages, retention_rates = self._population_context()
        observed_year = int(period[:4])
        target_year = target_year or observed_year
        if target_year < observed_year or target_year > min(observed_year + 10, 2043):
            raise QueryNotPermittedError(
                f"target_year must be between {observed_year} and {min(observed_year + 10, 2043)}"
            )
        horizon = target_year - observed_year
        city_retention = median(retention_rates.values())
        ordered_rates = sorted(retention_rates.values())
        top_quartile_retention = ordered_rates[(len(ordered_rates) * 3) // 4]
        baseline = self._project(ages, retention_rates, horizon)
        scenario = dict(baseline)
        scenario_rates = dict(retention_rates)
        annual_flows = {code: 0.0 for code in baseline}
        disclosed: list[str] = []
        for adjustment in adjustments:
            target = _district_code(adjustment.district_id)
            if target not in scenario:
                raise QueryNotPermittedError(
                    f"district {adjustment.district_id!r} is absent from the observed baseline"
                )
            if adjustment.operation is ScenarioOperation.MATCH_CITY_RETENTION:
                scenario_rates[target] = max(retention_rates[target], city_retention)
                scenario[target] = self._project_one(
                    ages[target], scenario_rates[target], horizon
                ) + round(annual_flows[target] * horizon)
                disclosed.append(
                    f"Raise district {target} cohort retention to at least the city median "
                    f"({scenario_rates[target]:.4f}) through {target_year}."
                )
                continue
            if adjustment.operation is ScenarioOperation.MATCH_TOP_QUARTILE_RETENTION:
                scenario_rates[target] = max(retention_rates[target], top_quartile_retention)
                scenario[target] = self._project_one(
                    ages[target], scenario_rates[target], horizon
                ) + round(annual_flows[target] * horizon)
                disclosed.append(
                    f"Raise district {target} cohort retention to at least the observed "
                    f"top-quartile benchmark ({scenario_rates[target]:.4f}) through {target_year}."
                )
                continue
            if adjustment.operation is ScenarioOperation.RETENTION_RATE_CHANGE:
                scenario_rates[target] += adjustment.value / 100
                if scenario_rates[target] < 0:
                    raise QueryNotPermittedError("scenario retention rate cannot be negative")
                scenario[target] = self._project_one(
                    ages[target], scenario_rates[target], horizon
                ) + round(annual_flows[target] * horizon)
                disclosed.append(
                    f"Change district {target} annual cohort retention by "
                    f"{adjustment.value:g} percentage points through {target_year}."
                )
                continue
            if adjustment.operation is ScenarioOperation.ANNUAL_NET_MIGRATION:
                annual_flows[target] += adjustment.value
                scenario[target] += round(adjustment.value * horizon)
                disclosed.append(
                    f"Assume annual net youth migration of {adjustment.value:g} in district "
                    f"{target} through {target_year}."
                )
                continue
            if adjustment.operation is ScenarioOperation.TRANSFER:
                source = _district_code(adjustment.source_district_id or "")
                amount = round(adjustment.value)
                self._transfer(scenario, source, target, amount)
                disclosed.append(f"Transfer {amount:,} people from {source} to {target}.")
                continue

            current = scenario[target]
            delta = (
                round(adjustment.value)
                if adjustment.operation is ScenarioOperation.ABSOLUTE_CHANGE
                else round(current * adjustment.value / 100)
            )
            if current + delta < 0:
                raise QueryNotPermittedError(
                    f"the adjustment would make district {target} population negative"
                )
            if balance_mode is PopulationBalanceMode.REDISTRIBUTE:
                self._redistribute(scenario, target, delta)
            else:
                scenario[target] += delta
            disclosed.append(
                f"Apply {adjustment.operation.value}={adjustment.value:g} to district {target}."
            )

        baseline_ranks = _ranks(baseline)
        scenario_ranks = _ranks(scenario)
        rows = tuple(
            DistrictScenarioResult(
                district_code=code,
                district_name=localized_district_name(code, NameLanguage.ENGLISH) or code,
                baseline_value=baseline[code],
                scenario_value=scenario[code],
                absolute_delta=scenario[code] - baseline[code],
                percent_delta=(
                    round((scenario[code] - baseline[code]) / baseline[code] * 100, 4)
                    if baseline[code]
                    else None
                ),
                baseline_rank=baseline_ranks[code],
                scenario_rank=scenario_ranks[code],
                rank_change=baseline_ranks[code] - scenario_ranks[code],
                historical_retention_rate=round(retention_rates[code], 6),
                scenario_retention_rate=round(scenario_rates[code], 6),
            )
            for code in sorted(baseline, key=lambda item: (scenario_ranks[item], item))
        )
        baseline_total = sum(baseline.values())
        scenario_total = sum(scenario.values())
        conserved = baseline_total == scenario_total
        trajectory = tuple(
            self._trajectory_point(
                year,
                observed_year,
                ages,
                retention_rates,
                scenario_rates,
                annual_flows,
            )
            for year in range(observed_year, target_year + 1)
        )
        # Legacy one-off operations have no time path. Keep their terminal
        # comparison internally consistent while projection operations retain
        # a full annual trajectory.
        if trajectory and trajectory[-1].scenario_value != scenario_total:
            trajectory = (
                *trajectory[:-1],
                ScenarioTrajectoryPoint(
                    year=target_year,
                    baseline_value=baseline_total,
                    scenario_value=scenario_total,
                    absolute_delta=scenario_total - baseline_total,
                ),
            )
        return YouthPopulationScenarioResult(
            observed_period=period,
            target_year=target_year,
            baseline_method="observed_age_cohorts_with_historical_district_retention",
            balance_mode=balance_mode,
            baseline_total=baseline_total,
            scenario_total=scenario_total,
            total_delta=scenario_total - baseline_total,
            population_conserved=conserved,
            rows=rows,
            trajectory=trajectory,
            evidence=(
                ScenarioEvidence(
                    kind=EvidenceKind.OFFICIAL,
                    label="Observed district population",
                    detail=(
                        "New Taipei Civil Affairs monthly household-registration counts, "
                        f"single-year ages and sex, observed {period}."
                    ),
                    source_url=self._SOURCE_URL,
                ),
                ScenarioEvidence(
                    kind=EvidenceKind.DERIVED,
                    label="Cohort projection baseline",
                    detail=(
                        "Observed single-year cohorts are aged forward. Each district's median "
                        "same-month cohort transition rate from recent years is applied annually."
                    ),
                ),
                ScenarioEvidence(
                    kind=EvidenceKind.USER_ASSUMPTION,
                    label="Scenario adjustments",
                    detail=" ".join(disclosed),
                ),
            ),
            assumptions=tuple(disclosed),
            warnings=(
                "Scenario adjustments are user assumptions, not predictions or causal estimates.",
                "The source measures registered household population, not usual residence.",
                (
                    "Historical cohort retention combines migration, mortality and registration "
                    "changes; it does not identify a policy's causal effect."
                ),
            ),
            generated_at=datetime.now(UTC),
        )

    def _population_context(
        self,
    ) -> tuple[str, dict[str, dict[int, int]], dict[str, float]]:
        if not self._population_csv.is_file():
            raise AnalyticsNotAvailableError(
                "the district single-age population source is unavailable"
            )
        connection = duckdb.connect(database=":memory:")
        try:
            latest = connection.execute(
                """
                WITH source AS (
                    SELECT * FROM read_csv_auto(?)
                ), district_coverage AS (
                    SELECT "民國年" AS year_roc, "月" AS month, "區代碼" AS district_code
                    FROM source
                    WHERE "年齡下限" BETWEEN 18 AND 35
                      AND "年齡上限" BETWEEN 18 AND 35
                    GROUP BY 1, 2, 3
                    HAVING count(DISTINCT "年齡下限") = 18
                ), latest AS (
                    SELECT year_roc, month
                    FROM district_coverage
                    GROUP BY 1, 2
                    HAVING count(DISTINCT district_code) = 29
                    ORDER BY 1 DESC, 2 DESC
                    LIMIT 1
                )
                SELECT
                       max(latest.year_roc)::INTEGER AS year_roc,
                       max(latest.month)::INTEGER AS month
                FROM source, latest
                WHERE "民國年" = latest.year_roc
                  AND "月" = latest.month
                  AND "年齡下限" BETWEEN 18 AND 35
                  AND "年齡上限" BETWEEN 18 AND 35
                """,
                [str(self._population_csv)],
            ).fetchone()
            if latest is None:
                raise AnalyticsNotAvailableError(
                    "the population source has no complete district-age period"
                )
            year_roc, month = int(latest[0]), int(latest[1])
            rows = connection.execute(
                """
                SELECT "民國年"::INTEGER,
                       lpad(CAST("區代碼" AS VARCHAR), 2, '0'),
                       "年齡下限"::INTEGER,
                       SUM("人數")::BIGINT
                FROM read_csv_auto(?)
                WHERE "月" = ? AND "民國年" BETWEEN ? AND ?
                  AND "年齡下限" BETWEEN 0 AND 35
                  AND "年齡上限" = "年齡下限"
                GROUP BY 1, 2, 3
                ORDER BY 1, 2, 3
                """,
                [str(self._population_csv), month, year_roc - 4, year_roc],
            ).fetchall()
        except duckdb.Error as exc:
            raise AnalyticsNotAvailableError(
                f"the district population source could not be read: {str(exc)[:240]}"
            ) from exc
        finally:
            connection.close()
        current: dict[str, dict[int, int]] = {}
        history: dict[tuple[int, str], dict[int, int]] = {}
        for year, code, age, population in rows:
            history.setdefault((int(year), str(code)), {})[int(age)] = int(population)
            if int(year) == year_roc:
                current.setdefault(str(code), {})[int(age)] = int(population)
        if len(current) != 29 or any(len(values) < 36 for values in current.values()):
            raise AnalyticsNotAvailableError(
                "the latest district population snapshot does not cover all 29 districts"
            )
        rates: dict[str, float] = {}
        for code in current:
            transitions: list[float] = []
            for year in range(year_roc - 4, year_roc):
                before = history.get((year, code))
                after = history.get((year + 1, code))
                if before is None or after is None:
                    continue
                denominator = sum(before.get(age, 0) for age in range(17, 35))
                numerator = sum(after.get(age, 0) for age in range(18, 36))
                if denominator > 0:
                    transitions.append(numerator / denominator)
            rates[code] = median(transitions) if transitions else 1.0
        year = year_roc + 1911
        return f"{year:04d}-{month:02d}", current, rates

    @staticmethod
    def _project_one(ages: dict[int, int], retention_rate: float, horizon: int) -> int:
        cohort = sum(ages.get(age, 0) for age in range(18 - horizon, 36 - horizon))
        return max(0, round(cohort * retention_rate**horizon))

    def _project(
        self,
        ages: dict[str, dict[int, int]],
        rates: dict[str, float],
        horizon: int,
    ) -> dict[str, int]:
        return {
            code: self._project_one(values, rates[code], horizon) for code, values in ages.items()
        }

    def _trajectory_point(
        self,
        year: int,
        observed_year: int,
        ages: dict[str, dict[int, int]],
        baseline_rates: dict[str, float],
        scenario_rates: dict[str, float],
        annual_flows: dict[str, float],
    ) -> ScenarioTrajectoryPoint:
        horizon = year - observed_year
        baseline = sum(self._project(ages, baseline_rates, horizon).values())
        scenario = sum(self._project(ages, scenario_rates, horizon).values()) + round(
            sum(annual_flows.values()) * horizon
        )
        return ScenarioTrajectoryPoint(
            year=year,
            baseline_value=baseline,
            scenario_value=scenario,
            absolute_delta=scenario - baseline,
        )

    @staticmethod
    def _transfer(values: dict[str, int], source: str, target: str, amount: int) -> None:
        if source not in values:
            raise QueryNotPermittedError(f"source district {source!r} is absent from the baseline")
        if source == target:
            raise QueryNotPermittedError("transfer source and target must differ")
        if values[source] < amount:
            raise QueryNotPermittedError("transfer exceeds the source district population")
        values[source] -= amount
        values[target] += amount

    @staticmethod
    def _redistribute(values: dict[str, int], target: str, delta: int) -> None:
        if delta == 0:
            return
        others = [code for code in values if code != target]
        if delta > 0:
            if sum(values[code] for code in others) < delta:
                raise QueryNotPermittedError(
                    "redistribution exceeds the other districts' population"
                )
            allocation = _proportional_allocation(delta, {code: values[code] for code in others})
            for code, amount in allocation.items():
                values[code] -= amount
        else:
            allocation = _proportional_allocation(-delta, {code: values[code] for code in others})
            for code, amount in allocation.items():
                values[code] += amount
        values[target] += delta


def _district_code(value: str) -> str:
    resolution = resolve_district_name(value)
    if resolution.district is None:
        raise QueryNotPermittedError(f"unknown New Taipei district: {value!r}")
    return resolution.district.code


def _ranks(values: dict[str, int]) -> dict[str, int]:
    ordered = sorted(values, key=lambda code: (-values[code], code))
    return {code: index for index, code in enumerate(ordered, start=1)}


def _proportional_allocation(total: int, weights: dict[str, int]) -> dict[str, int]:
    """Allocate an integer exactly using the largest-remainder method."""

    denominator = sum(weights.values())
    if denominator <= 0:
        raise QueryNotPermittedError("there is no population available for redistribution")
    floors = {code: total * weight // denominator for code, weight in weights.items()}
    remainder = total - sum(floors.values())
    order = sorted(
        weights,
        key=lambda code: (-(total * weights[code] % denominator), code),
    )
    for code in order[:remainder]:
        floors[code] += 1
    return floors
