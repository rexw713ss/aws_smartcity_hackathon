"""The impact-scenario pipeline: a user assumption, projected and bounded.

An impact question ("what if 5,000 young people move to Sanxia by 2030?") mixes
one thing the data can answer with several it cannot. The population step is
projected from observed single-year cohorts; the housing, transport, and service
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
    PopulationBalanceMode,
    ScenarioAdjustment,
    ScenarioOperation,
    YouthPopulationScenarioResult,
    YouthPopulationScenarioService,
)
from youth_compass.domain.errors import YouthCompassError


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
    observed cohorts, and every downstream link (housing, transport, services)
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
    visualizations = _impact_visualizations(scenario, decomposition.original_question)
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
            "No housing, transport, or service impact is inferred without compatible "
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
        for term in ("giao thông", "transit", "transport", "metro", "bus", "交通", "捷運", "公車")
    ):
        gaps.append(
            ImpactDataGap(
                domain="transport",
                required_metrics=(
                    "transit_stop_coverage",
                    "transit_boardings",
                    "service_frequency",
                    "passenger_capacity",
                    "youth_mode_share",
                ),
                reason=(
                    "Transport pressure requires observed demand, service frequency, usable "
                    "capacity, and a youth travel-mode share."
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
    finding = impact.findings[0]
    gap_names = ", ".join(gap.domain.replace("_", " ") for gap in impact.data_gaps)
    if response_language_for_fallback(question) == "vi":
        if candidates_found:
            discovery = "Agent đã tìm thấy nguồn chính thức có thể đưa vào quy trình kiểm duyệt."
        elif discovery_failed:
            discovery = (
                "Việc tìm nguồn bên ngoài không chạy được, nên chưa thể kết luận là không "
                "có nguồn phù hợp."
            )
        else:
            discovery = (
                "Agent đã tìm trong catalog và danh sách nguồn được phép nhưng chưa có "
                "nguồn phù hợp."
            )
        return (
            f"Đến {impact.target_year}, baseline của {impact.district_name} là "
            f"{finding.baseline_value:,.0f} người 18-35 tuổi. Với giả định "
            f"{impact.shock_people:+,} người, scenario là {finding.scenario_value:,.0f}.\n\n"
            f"Chưa thể khuyến nghị đầu tư cho {gap_names}: dữ liệu sức chứa và mức sử dụng "
            f"chưa đủ để ước tính chuỗi tác động. {discovery}"
        )
    if candidates_found:
        discovery = "The agent found allowlisted official sources that can enter review."
    elif discovery_failed:
        discovery = (
            "The external source search could not run, so no conclusion can be drawn about "
            "whether a compatible source exists."
        )
    else:
        discovery = (
            "The agent searched the catalog and allowlisted sources but found no compatible source."
        )
    return (
        f"By {impact.target_year}, the {impact.district_name} baseline is "
        f"{finding.baseline_value:,.0f} residents aged 18-35. With the "
        f"{impact.shock_people:+,} person assumption, the scenario is "
        f"{finding.scenario_value:,.0f}.\n\n"
        f"I cannot yet recommend investment in {gap_names}: capacity and utilization evidence "
        f"is incomplete. {discovery}"
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
        "difference": "Scenario minus baseline",
        "trajectory_title": "Youth population impact through {year}",
        "trajectory_description": (
            "Observed cohorts under the baseline and user-supplied population shock."
        ),
        "difference_title": "Gap between the scenario and the baseline through {year}",
        "difference_description": (
            "Scenario minus baseline for each year. The two absolute paths sit within a "
            "few thousand people of each other, so the gap is plotted on its own axis "
            "instead of being left invisible on a shared one."
        ),
    },
    "zh": {
        "year": "年份",
        "residents": "18-35 歲居民",
        "difference": "情境減基線",
        "trajectory_title": "青年人口影響（至 {year} 年）",  # noqa: RUF001
        "trajectory_description": "在基線與使用者設定的人口變動下，觀測世代的推估結果。",  # noqa: RUF001
        "difference_title": "情境與基線的差距（至 {year} 年）",  # noqa: RUF001
        "difference_description": (
            "每一年的情境值減去基線值。兩條絕對數線相差僅數千人，"  # noqa: RUF001
            "放在同一座標軸上看不出差異，因此差距另外以自己的軸呈現。"  # noqa: RUF001
        ),
    },
    "vi": {
        "year": "Năm",
        "residents": "Cư dân 18-35 tuổi",
        "difference": "Kịch bản trừ baseline",
        "trajectory_title": "Tác động dân số thanh niên đến {year}",
        "trajectory_description": (
            "Các thế hệ quan sát được theo baseline và mức thay đổi dân số do người dùng đặt."
        ),
        "difference_title": "Chênh lệch giữa kịch bản và baseline đến {year}",
        "difference_description": (
            "Kịch bản trừ baseline theo từng năm. Hai đường tuyệt đối chỉ cách nhau vài "
            "nghìn người nên chênh lệch được vẽ trên trục riêng thay vì biến mất trên "
            "trục chung."
        ),
    },
}


def _impact_visualizations(
    scenario: YouthPopulationScenarioResult, question: str
) -> tuple[VisualizationSpec, ...]:
    """Chart the gap first, then the two absolute paths.

    A shock of a few thousand people against a city total near a million is
    about a quarter of one percent: on a shared axis the baseline and scenario
    lines are one stroke, which reads as "nothing changed". The difference
    series carries the same grounded numbers on an axis where it is legible;
    the absolute trajectory stays so the level is not lost.
    """

    labels = _IMPACT_CHART_LABELS[response_language_for_fallback(question)]
    difference_rows: tuple[dict[str, str | int | float | bool | None], ...] = tuple(
        {"year": point.year, "difference": point.absolute_delta} for point in scenario.trajectory
    )
    trajectory_rows: tuple[dict[str, str | int | float | bool | None], ...] = tuple(
        {
            "year": point.year,
            "path": path,
            "population": value,
        }
        for point in scenario.trajectory
        for path, value in (
            ("Baseline", point.baseline_value),
            ("Scenario", point.scenario_value),
        )
    )
    difference = VisualizationSpec(
        visualization_id="impact-population-difference",
        type=VisualizationType.COMPARISON_BAR,
        title=labels["difference_title"].format(year=scenario.target_year),
        description=labels["difference_description"],
        x=VisualizationEncoding(
            field="year", label=labels["year"], data_type="temporal", unit=None
        ),
        y=VisualizationEncoding(
            field="difference",
            label=labels["difference"],
            data_type="quantitative",
            unit="persons",
        ),
        rows=difference_rows,
    )
    trajectory = VisualizationSpec(
        visualization_id="impact-population-trajectory",
        type=VisualizationType.LINE,
        title=labels["trajectory_title"].format(year=scenario.target_year),
        description=labels["trajectory_description"],
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
        rows=trajectory_rows,
    )
    return (difference, trajectory)
