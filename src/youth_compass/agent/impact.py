"""The impact-scenario pipeline: a user assumption, projected and bounded.

An impact question ("what if 5,000 young people move to Sanxia by 2030?") mixes
one thing the data can answer with several it cannot. The population step is
projected from observed single-year cohorts; the housing and public-service
links are refused unless published capacity evidence exists, and the refusal
names the metrics that would close the gap. Nothing here infers a downstream
effect from a population number alone.
"""

import re
from datetime import datetime

from youth_compass.agent.contracts import (
    CopilotResponse,
    CopilotStatus,
    DecomposedQuery,
    ImpactAnalysis,
    ImpactDataGap,
    ImpactFinding,
    RoutedToolPlan,
    ToolTrace,
    VisualizationEncoding,
    VisualizationReferenceLine,
    VisualizationSpec,
    VisualizationType,
)
from youth_compass.agent.support import (
    AnswerSupport,
    discovery_warning,
    response_language_for_fallback,
    unavailable_trace,
)
from youth_compass.decisioning import (
    DistrictScenarioResult,
    PopulationBalanceMode,
    ScenarioAdjustment,
    ScenarioOperation,
    ScenarioTrajectoryPoint,
    YouthPopulationScenarioResult,
    YouthPopulationScenarioService,
)
from youth_compass.domain.errors import YouthCompassError
from youth_compass.ontology import NameLanguage, localized_district_name


def answer_impact_scenario(
    now: datetime,
    decomposition: DecomposedQuery,
    routed_plan: RoutedToolPlan,
    trace: list[ToolTrace],
    *,
    scenarios: YouthPopulationScenarioService | None,
    support: AnswerSupport,
) -> CopilotResponse:
    """Run the grounded part of an impact chain and fail closed at data gaps.

    The chain is deliberately partial: the population step is projected from
    observed cohorts, and every downstream link (housing and public services)
    is refused unless the capacity evidence for it is published. A refusal names
    the exact metrics that would close the gap.
    """

    if scenarios is None:
        return CopilotResponse(
            status=CopilotStatus.INSUFFICIENT_DATA,
            answer="The population scenario engine is unavailable.",
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            tool_trace=tuple(trace),
            warnings=("No scenario or impact estimate was produced.",),
        )
    if len(decomposition.entity_ids) != 1:
        return CopilotResponse(
            status=CopilotStatus.UNSUPPORTED_QUESTION,
            answer="Name exactly one New Taipei district for this impact scenario.",
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            tool_trace=tuple(trace),
            warnings=("The scenario was not run because its geography was ambiguous.",),
        )
    shock = _population_shock(decomposition.original_question)
    if shock is None:
        return CopilotResponse(
            status=CopilotStatus.UNSUPPORTED_QUESTION,
            answer="State the number of people entering or leaving the district.",
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            tool_trace=tuple(trace),
            warnings=("The scenario was not run because no population shock was found.",),
        )
    target_year = _scenario_target_year(decomposition.original_question) or 2030
    try:
        scenario = scenarios.run(
            (
                ScenarioAdjustment(
                    district_id=decomposition.entity_ids[0],
                    operation=ScenarioOperation.ABSOLUTE_CHANGE,
                    value=shock,
                ),
            ),
            balance_mode=PopulationBalanceMode.OPEN,
            target_year=target_year,
        )
    except YouthCompassError as exc:
        trace.append(unavailable_trace("simulate_scenario", exc))
        return CopilotResponse(
            status=CopilotStatus.INSUFFICIENT_DATA,
            answer="The requested population scenario could not be projected safely.",
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            tool_trace=tuple(trace),
            warnings=(str(exc),),
        )
    district = next(
        (row for row in scenario.rows if row.district_code == decomposition.entity_ids[0]),
        None,
    )
    if district is None:
        # The scenario ran but returned no row for the requested district,
        # so there is no baseline to project from. Report the gap rather
        # than letting the lookup raise out of the request.
        trace.append(
            ToolTrace(
                tool="simulate_scenario",
                outcome="unavailable",
                summary=(
                    "no baseline row for district "
                    f"{decomposition.entity_ids[0]} in the scenario snapshot"
                ),
            )
        )
        return CopilotResponse(
            status=CopilotStatus.INSUFFICIENT_DATA,
            answer="The requested district is not present in the population baseline.",
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            tool_trace=tuple(trace),
            warnings=(
                "No scenario or impact estimate was produced because the district has "
                "no observed cohort baseline.",
            ),
        )
    trace.append(
        ToolTrace(
            tool="simulate_scenario",
            outcome="ok",
            summary=(
                f"projected ages 18-35 in {district.district_name} to {target_year}: "
                f"{district.baseline_value:,} baseline, {district.scenario_value:,} scenario"
            ),
        )
    )
    gaps = _impact_data_gaps(decomposition.original_question)
    findings = (
        ImpactFinding(
            stage="population",
            label=f"Registered residents aged 18-35 in {district.district_name}",
            baseline_value=district.baseline_value,
            scenario_value=district.scenario_value,
            absolute_delta=district.absolute_delta,
            unit="persons",
            evidence_kind="derived",
        ),
    )
    impact = ImpactAnalysis(
        district_code=district.district_code,
        district_name=district.district_name,
        observed_period=scenario.observed_period,
        target_year=target_year,
        shock_people=shock,
        findings=findings,
        data_gaps=gaps,
        confidence="insufficient" if gaps else "medium",
    )
    if gaps:
        trace.append(
            ToolTrace(
                tool="assess_capacity",
                outcome="data_gap",
                summary="; ".join(
                    f"{gap.domain}: {', '.join(gap.required_metrics)}" for gap in gaps
                ),
            )
        )
        required_metrics = tuple(
            dict.fromkeys(metric for gap in gaps for metric in gap.required_metrics)
        )
        requirement, source_candidates, discovery_error = support.discover_sources(
            decomposition, trace, metric_codes=required_metrics
        )
        trace.append(
            ToolTrace(
                tool="recommend_investment",
                outcome="withheld",
                summary=("capacity evidence is incomplete; no infrastructure ranking was produced"),
            )
        )
        answer = _impact_gap_answer(
            impact,
            bool(source_candidates),
            decomposition.original_question,
            discovery_failed=discovery_error is not None,
        )
        status = (
            CopilotStatus.ACQUISITION_REQUIRED
            if source_candidates
            else CopilotStatus.INSUFFICIENT_DATA
        )
    else:
        requirement, source_candidates, discovery_error = None, (), None
        answer = _impact_population_answer(impact, decomposition.original_question)
        status = CopilotStatus.ANSWERED
    visualizations = _impact_visualizations(scenario, district, decomposition.original_question)
    support.trace_visualizations(trace, visualizations)
    return CopilotResponse(
        status=status,
        answer=answer,
        generated_at=now,
        decomposition=decomposition,
        routed_plan=routed_plan,
        impact_analysis=impact,
        tool_trace=tuple(trace),
        assumptions=(
            f"The user-supplied population shock is {shock:+,} people by {target_year}.",
            "The population baseline ages observed single-year cohorts forward using "
            "recent district transition rates.",
        ),
        warnings=(
            "No housing or public-service impact is inferred without compatible "
            "capacity and demand data.",
            "The population scenario is not evidence that a policy caused migration.",
            *discovery_warning(discovery_error),
        ),
        data_requirement=requirement,
        source_candidates=source_candidates,
        visualizations=visualizations,
    )


def _population_shock(question: str) -> int | None:
    """Extract a bounded, explicitly stated people count from a scenario question."""

    match = re.search(
        r"(?<!\d)(\d{1,3}(?:[.,]\d{3})+|\d{1,7})\s*"
        # Chinese counts the noun through a measure word: 2,000 名青年.
        r"(?:名|位|個)?\s*"
        r"(?:thanh\s+niên|người|young\s+people|youth|people|persons|residents|青年|人)",
        question.casefold(),
    )
    if match is None:
        return None
    amount = int(match.group(1).replace(".", "").replace(",", ""))
    if amount <= 0 or amount > 1_000_000:
        return None
    departure = any(
        term in question.casefold()
        for term in ("rời", "chuyển đi", "leave", "depart", "搬出", "離開")
    )
    return -amount if departure else amount


def _scenario_target_year(question: str) -> int | None:
    years = [int(value) for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", question)]
    plausible = [year for year in years if 2026 <= year <= 2043]
    return max(plausible) if plausible else None


def _impact_data_gaps(question: str) -> tuple[ImpactDataGap, ...]:
    """Declare the exact evidence needed for each requested downstream link."""

    normalized = question.casefold()
    generic = any(
        term in normalized
        for term in ("hạ tầng", "infrastructure", "đầu tư", "invest", "投資", "基礎設施")
    )
    gaps: list[ImpactDataGap] = []
    if generic or any(
        term in normalized
        for term in ("giá nhà", "nhà ở", "housing", "house price", "property", "住宅", "房價")
    ):
        gaps.append(
            ImpactDataGap(
                domain="housing",
                required_metrics=(
                    "housing_unit_stock",
                    "vacant_housing_units",
                    "residential_completions",
                    "youth_household_size",
                ),
                reason=(
                    "Housing demand and price pressure require district supply, vacancy, "
                    "completion, and household-formation evidence."
                ),
            )
        )
    if generic or any(
        term in normalized
        for term in ("dịch vụ", "service", "y tế", "childcare", "醫療", "公共服務")
    ):
        gaps.append(
            ImpactDataGap(
                domain="public_services",
                required_metrics=(
                    "service_facility_count",
                    "service_facility_capacity",
                    "service_utilization",
                    "youth_service_usage_rate",
                ),
                reason=(
                    "A service recommendation requires facility capacity, current utilization, "
                    "and an age-compatible usage rate."
                ),
            )
        )
    return tuple(gaps)


def _impact_gap_answer(
    impact: ImpactAnalysis,
    candidates_found: bool,
    question: str,
    *,
    discovery_failed: bool = False,
) -> str:
    del candidates_found, discovery_failed
    finding = impact.findings[0]
    gap_names = ", ".join(gap.domain.replace("_", " ") for gap in impact.data_gaps)
    if response_language_for_fallback(question) == "vi":
        return (
            f"Đến {impact.target_year}, baseline của {impact.district_name} là "
            f"{finding.baseline_value:,.0f} người 18-35 tuổi. Với giả định "
            f"{impact.shock_people:+,} người, scenario là {finding.scenario_value:,.0f}. "
            f"Chưa đủ dữ liệu {gap_names} để khuyến nghị đầu tư."
        )
    return (
        f"By {impact.target_year}, the {impact.district_name} baseline is "
        f"{finding.baseline_value:,.0f} residents aged 18-35. With the "
        f"{impact.shock_people:+,} person assumption, the scenario is "
        f"{finding.scenario_value:,.0f}. More {gap_names} data is needed before recommending "
        "investment."
    )


def _impact_population_answer(impact: ImpactAnalysis, question: str) -> str:
    finding = impact.findings[0]
    if response_language_for_fallback(question) == "vi":
        return (
            f"Đến {impact.target_year}, {impact.district_name} có baseline "
            f"{finding.baseline_value:,.0f} người 18-35 tuổi và scenario "
            f"{finding.scenario_value:,.0f}, chênh {finding.absolute_delta:+,.0f} người."
        )
    return (
        f"By {impact.target_year}, {impact.district_name} has a baseline of "
        f"{finding.baseline_value:,.0f} residents aged 18-35 and a scenario of "
        f"{finding.scenario_value:,.0f}, a difference of {finding.absolute_delta:+,.0f}."
    )


_IMPACT_CHART_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "year": "Year",
        "residents": "Residents aged 18-35",
        "baseline": "Baseline",
        "scenario": "Scenario",
        "observed_level": "{year} level",
        "title": "{district} youth population through {year}",
        "description": (
            "The baseline ages {district}'s observed single-year cohorts forward; the "
            "scenario adds the stated shock. The dashed line marks the {observed} level."
        ),
        "share": "{shock} people is {percent} of {district}'s {year} baseline",
        "offsets_decline": ", offsetting {offset} of its projected decline since {observed}.",
        "reverses_decline": ", more than reversing its projected decline since {observed}.",
        "adds_to_growth": ", on top of projected growth of {growth} since {observed}.",
        "deepens_decline": ", deepening its projected decline since {observed}.",
        "end": ".",
    },
    "zh": {
        "year": "年份",
        "residents": "18-35 歲居民",
        "baseline": "基線",
        "scenario": "情境",
        "observed_level": "{year} 年水準",
        "title": "{district}青年人口（至 {year} 年）",  # noqa: RUF001
        "description": (
            "基線以{district}觀測到的單一年齡世代往後推估；情境再加上設定的人口變動。"  # noqa: RUF001
            "虛線為 {observed} 年的水準。"
        ),
        "share": "{shock} 人相當於{district} {year} 年基線的 {percent}",
        "offsets_decline": "，可抵銷自 {observed} 年起推估減少量的 {offset}。",  # noqa: RUF001
        "reverses_decline": "，足以扭轉自 {observed} 年起推估的減少。",  # noqa: RUF001
        "adds_to_growth": "，並疊加在自 {observed} 年起推估成長的 {growth} 人之上。",  # noqa: RUF001
        "deepens_decline": "，使自 {observed} 年起推估的減少更加明顯。",  # noqa: RUF001
        "end": "。",
    },
    "vi": {
        "year": "Năm",
        "residents": "Cư dân 18-35 tuổi",
        "baseline": "Baseline",
        "scenario": "Kịch bản",
        "observed_level": "Mức {year}",
        "title": "Dân số thanh niên {district} đến {year}",
        "description": (
            "Baseline đẩy các thế hệ theo từng tuổi quan sát được ở {district} về phía trước; "
            "kịch bản cộng thêm mức thay đổi đã nêu. Đường nét đứt là mức năm {observed}."
        ),
        "share": "{shock} người bằng {percent} baseline {year} của {district}",
        "offsets_decline": ", bù được {offset} mức giảm dự báo kể từ {observed}.",
        "reverses_decline": ", đủ đảo ngược mức giảm dự báo kể từ {observed}.",
        "adds_to_growth": ", cộng thêm vào mức tăng dự báo {growth} người kể từ {observed}.",
        "deepens_decline": ", làm mức giảm dự báo kể từ {observed} sâu thêm.",
        "end": ".",
    },
}


def _impact_visualizations(
    scenario: YouthPopulationScenarioResult,
    district: DistrictScenarioResult,
    question: str,
) -> tuple[VisualizationSpec, ...]:
    """Chart the district's own path, and say what the shock means against it.

    The shock is the user's input, so plotting it alone restates the question.
    What the reader cannot see without help is its size relative to where the
    district is already heading: that goes in the headline, and the observed
    level is drawn as a reference so a jump reads against today, not zero.
    """

    language = response_language_for_fallback(question)
    labels = _IMPACT_CHART_LABELS[language]
    points = district.trajectory
    if not points:
        return ()
    name = (
        localized_district_name(district.district_code, NameLanguage.ZH_HANT)
        if language == "zh"
        else None
    ) or district.district_name
    start, end = points[0], points[-1]
    # The scenario leaves the baseline at the last unchanged year, so a one-off
    # shock appears as the jump it is rather than as a line drawn from nowhere.
    first_change = next(
        (index for index, point in enumerate(points) if point.absolute_delta != 0), None
    )
    scenario_from = max(0, first_change - 1) if first_change is not None else len(points)
    rows: list[dict[str, str | int | float | bool | None]] = [
        {"year": point.year, "path": labels["baseline"], "population": point.baseline_value}
        for point in points
    ]
    rows.extend(
        {"year": point.year, "path": labels["scenario"], "population": point.scenario_value}
        for point in points[scenario_from:]
    )
    return (
        VisualizationSpec(
            visualization_id="impact-population-trajectory",
            type=VisualizationType.LINE,
            title=labels["title"].format(district=name, year=scenario.target_year),
            headline=_impact_headline(labels, name, start, end),
            description=labels["description"].format(district=name, observed=start.year),
            x=VisualizationEncoding(
                field="year", label=labels["year"], data_type="temporal", unit=None
            ),
            y=VisualizationEncoding(
                field="population",
                label=labels["residents"],
                data_type="quantitative",
                unit="persons",
            ),
            series_field="path",
            reference_lines=(
                VisualizationReferenceLine(
                    label=labels["observed_level"].format(year=start.year),
                    value=start.baseline_value,
                ),
            ),
            rows=tuple(rows),
        ),
    )


def _impact_headline(
    labels: dict[str, str],
    name: str,
    start: ScenarioTrajectoryPoint,
    end: ScenarioTrajectoryPoint,
) -> str | None:
    delta = end.absolute_delta
    if delta == 0 or end.baseline_value <= 0:
        return None
    share = labels["share"].format(
        shock=f"{delta:+,}",
        percent=f"{abs(delta) / end.baseline_value:.1%}",
        district=name,
        year=end.year,
    )
    trend = end.baseline_value - start.baseline_value
    observed = start.year
    if start.year == end.year or trend == 0:
        return share + labels["end"]
    if trend < 0 and delta > 0:
        if delta >= -trend:
            return share + labels["reverses_decline"].format(observed=observed)
        offset = f"{delta / -trend:.0%}"
        return share + labels["offsets_decline"].format(offset=offset, observed=observed)
    if trend > 0 and delta > 0:
        return share + labels["adds_to_growth"].format(growth=f"{trend:+,}", observed=observed)
    if trend < 0 and delta < 0:
        return share + labels["deepens_decline"].format(observed=observed)
    return share + labels["end"]
