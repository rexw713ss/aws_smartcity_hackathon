"""The multi-dataset pipeline: an exact join across published tables.

A question that names several datasets must not silently become a question about
one of them. This module retrieves each named table separately, validates the
join at its declared grain, and combines the results only on exact canonical
entity-period keys. Where the inputs cannot line up — different granularities,
no shared district, no shared period — it says which of those it hit instead of
inventing an alignment.
"""

import re
from collections.abc import Iterable, Sequence
from datetime import datetime

from youth_compass.agent.contracts import (
    AnalysisOperation,
    CopilotResponse,
    CopilotStatus,
    DatasetInspection,
    DecomposedQuery,
    JoinedObservationRow,
    MultiDatasetAnalysis,
    ObservationPoint,
    ObservationSeries,
    RoutedToolPlan,
    ToolTrace,
    VisualizationColumn,
    VisualizationEncoding,
    VisualizationSpec,
    VisualizationType,
)
from youth_compass.agent.observation_tools import ObservationToolSuite
from youth_compass.agent.support import (
    AnswerSupport,
    answered,
    citation_from_series,
    name_language,
    unavailable_trace,
)
from youth_compass.decisioning import (
    AnalysisInput,
    AnalysisJoin,
    AnalysisPlan,
    AnalysisPlanValidator,
    JoinCardinality,
)
from youth_compass.domain.contracts import DatasetMetadata, DatasetStatus
from youth_compass.domain.errors import QueryExecutionError, YouthCompassError
from youth_compass.ontology import (
    extract_topics,
    humanize_code,
    readable_entity_name,
    resolve_district_name,
    resolve_topic_name,
)

#: Upper bound on datasets joined for one question. Every extra dataset costs
#: one inspect plus one scanned engine query, and a question that merely names a
#: broad topic can match many catalog entries, so the fan-out is capped rather
#: than left to the phrasing of the question.
_MAX_JOINED_DATASETS = 4


def answer_multi_dataset_observations(
    now: datetime,
    decomposition: DecomposedQuery,
    routed_plan: RoutedToolPlan,
    trace: list[ToolTrace],
    datasets: tuple[DatasetMetadata, ...],
    *,
    tools: ObservationToolSuite,
    support: AnswerSupport,
    min_quality_score: float,
) -> CopilotResponse:
    """Query several tables and inner-join exact canonical entity-period rows.

    The join is exact on canonical district identity and reporting period. No
    value is interpolated, no period is reshaped except the one documented
    granularity alignment, and an empty intersection is reported with the reason
    it was empty rather than papered over.
    """

    excluded = tuple(item.dataset_id for item in datasets[_MAX_JOINED_DATASETS:])
    datasets = datasets[:_MAX_JOINED_DATASETS]
    if excluded:
        trace.append(
            ToolTrace(
                tool="search_catalog",
                outcome="capped",
                summary=(
                    f"joined the first {_MAX_JOINED_DATASETS} matching datasets; "
                    f"excluded {', '.join(excluded)}"
                ),
            )
        )
    fan_out_warning = (
        (
            f"The question matched more than {_MAX_JOINED_DATASETS} datasets; "
            f"{', '.join(excluded)} were excluded from the join. Name the datasets "
            "explicitly to choose a different set.",
        )
        if excluded
        else ()
    )
    unavailable = tuple(
        item.dataset_id
        for item in datasets
        if item.status is not DatasetStatus.PUBLISHED or item.quality_score < min_quality_score
    )
    if unavailable:
        names = ", ".join(unavailable)
        trace.append(
            ToolTrace(
                tool="validate_dataset_scope",
                outcome="unavailable",
                summary=(f"requested datasets are not published at the required quality: {names}"),
            )
        )
        return CopilotResponse(
            status=CopilotStatus.INSUFFICIENT_DATA,
            answer=(
                f"I cannot combine the requested data because {names} is not currently "
                "published at the required quality. No partial answer was produced."
            ),
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            tool_trace=tuple(trace),
            warnings=(
                "Every requested dataset must be published before a multi-dataset join runs.",
                *fan_out_warning,
            ),
        )

    inspections: list[DatasetInspection] = []
    series_by_dataset: list[tuple[DatasetMetadata, ObservationSeries]] = []
    try:
        for metadata in datasets:
            inspection = tools.inspect_dataset.execute_for_dataset(
                decomposition,
                metadata.dataset_id,
                min_quality_score=min_quality_score,
            )
            current = tools.catalog.get(metadata.dataset_id)
            if current.version != inspection.dataset_version:
                raise QueryExecutionError(
                    f"published dataset {metadata.dataset_id!r} changed during analysis"
                )
            series = tools.query_observations.execute(decomposition, inspection, current)
            inspections.append(inspection)
            series_by_dataset.append((current, series))
            trace.extend(
                (
                    ToolTrace(
                        tool="inspect_dataset",
                        outcome="ok",
                        summary=(
                            f"resolved {metadata.dataset_id}@{inspection.dataset_version} "
                            f"metric {inspection.metric_code}"
                        ),
                    ),
                    ToolTrace(
                        tool="query_observations",
                        outcome="ok",
                        summary=(
                            f"retrieved {len(series.points)} aggregated observations from "
                            f"{metadata.dataset_id}"
                        ),
                    ),
                )
            )
    except YouthCompassError as exc:
        trace.append(unavailable_trace("query_observations", exc))
        return support.observation_failure(
            now,
            decomposition,
            routed_plan,
            trace,
            warning=str(exc),
        )

    aliases = tuple(f"source_{index}" for index in range(1, len(datasets) + 1))
    metric_fields = tuple(
        f"{alias}_{inspection.metric_code}"
        for alias, inspection in zip(aliases, inspections, strict=True)
    )
    analysis_plan = AnalysisPlan(
        inputs=tuple(
            AnalysisInput(
                alias=alias,
                dataset_id=metadata.dataset_id,
                dataset_version=metadata.version,
                dimensions=("entity_id", "period"),
                metrics=(metric_field,),
                grain=("entity_id", "period"),
            )
            for alias, metric_field, (metadata, _) in zip(
                aliases, metric_fields, series_by_dataset, strict=True
            )
        ),
        joins=tuple(
            AnalysisJoin(
                left_alias=aliases[0],
                right_alias=alias,
                keys=("entity_id", "period"),
                cardinality=JoinCardinality.ONE_TO_ONE,
            )
            for alias in aliases[1:]
        ),
        output_dimensions=("entity_id", "period"),
        output_metrics=metric_fields,
        max_rows=10_000,
    )
    validation = AnalysisPlanValidator().validate(analysis_plan)
    if not validation.valid:
        reasons = "; ".join(issue.message for issue in validation.issues)
        trace.append(
            ToolTrace(tool="validate_analysis_plan", outcome="blocked", summary=reasons[:300])
        )
        return CopilotResponse(
            status=CopilotStatus.INSUFFICIENT_DATA,
            answer="The requested datasets cannot be joined safely at their validated grain.",
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            tool_trace=tuple(trace),
            warnings=(reasons, *fan_out_warning),
        )
    trace.append(
        ToolTrace(
            tool="validate_analysis_plan",
            outcome="ok",
            summary="validated one-to-one join on canonical entity_id and period",
        )
    )

    # Inputs published at different granularities cannot share an exact
    # period key. The finer one is collapsed to each year's closing month,
    # which the answer states, because that reading is only correct for a
    # point-in-time count.
    series_by_dataset, alignment_notes = _align_period_granularity(series_by_dataset)
    if alignment_notes:
        trace.append(
            ToolTrace(
                tool="align_period_granularity",
                outcome="ok",
                summary="; ".join(alignment_notes)[:300],
            )
        )

    point_maps = [
        {_joined_observation_key(point.entity_id, point.period): point for point in series.points}
        for _, series in series_by_dataset
    ]
    common_keys = set.intersection(*(set(points) for points in point_maps))
    if not common_keys:
        # "No overlap" has two very different causes and the reader has to
        # know which one they hit: a genuine gap in coverage is a data
        # problem, whereas a granularity mismatch is a modelling decision
        # this executor refuses to make on its own.
        reason, diagnosis = _no_overlap_reason(series_by_dataset)
        trace.append(
            ToolTrace(tool="join_observations", outcome="unavailable", summary=reason[:300])
        )
        return CopilotResponse(
            status=CopilotStatus.INSUFFICIENT_DATA,
            answer=diagnosis,
            generated_at=now,
            decomposition=decomposition,
            routed_plan=routed_plan,
            tool_trace=tuple(trace),
            warnings=(reason,),
        )

    ordered_keys = sorted(common_keys, key=lambda key: (key[1], key[0]))
    truncated = len(ordered_keys) > analysis_plan.max_rows
    ordered_keys = ordered_keys[: analysis_plan.max_rows]
    joined_rows = tuple(
        JoinedObservationRow(
            entity_id=key[0],
            entity_name=next(
                (points[key].entity_name for points in point_maps if points[key].entity_name),
                None,
            ),
            period=key[1],
            values={
                metadata.dataset_id: points[key].value
                for (metadata, _), points in zip(series_by_dataset, point_maps, strict=True)
            },
        )
        for key in ordered_keys
    )
    analysis = MultiDatasetAnalysis(
        dataset_metrics={
            metadata.dataset_id: series.metric_code for metadata, series in series_by_dataset
        },
        rows=joined_rows,
    )
    trace.append(
        ToolTrace(
            tool="join_observations",
            outcome="ok",
            summary=f"joined {len(joined_rows)} exact entity-period rows",
        )
    )

    citations = tuple(
        citation_from_series(f"data-{index}", metadata, series, decomposition.original_question)
        for index, (metadata, series) in enumerate(series_by_dataset, start=1)
    )
    if AnalysisOperation.EXPLAIN_LINEAGE in decomposition.operations:
        trace.append(
            ToolTrace(
                tool="explain_lineage",
                outcome="ok",
                summary=f"attached {len(citations)} dataset-version citations",
            )
        )

    latest_period = max(row.period for row in joined_rows)
    latest_rows = [row for row in joined_rows if row.period == latest_period]
    citation_suffix = " ".join(f"[{item.citation_id}]" for item in citations)
    bullets = []
    for row in latest_rows[:10]:
        name = readable_entity_name(
            row.entity_id,
            row.entity_name,
            name_language(decomposition.original_question),
        )
        values = "; ".join(
            # .10g keeps grouping without collapsing a six-figure count
            # into scientific notation, which .4g did.
            f"{humanize_code(analysis.dataset_metrics[dataset_id])}: {value:,.10g}"
            for dataset_id, value in row.values.items()
        )
        bullets.append(f"- {name} — {values} {citation_suffix}")
    answer = (
        f"Combined {len(datasets)} published datasets using an exact district-and-period "
        f"join. The latest common period is {latest_period}:\n\n" + "\n".join(bullets)
    )
    if len(latest_rows) > len(bullets):
        answer += (
            f"\n\nShowing 10 of {len(latest_rows)} matching locations; the table has the rest."
        )
    # A reader comparing two columns must be told when one of them was moved
    # onto the other's calendar, and which reading that makes valid.
    for note in alignment_notes:
        answer += f"\n\nNote: {note}."
    scopes = {series.population_scope for _, series in series_by_dataset}
    if len(scopes) > 1:
        answer += (
            "\n\nNote: these datasets count different populations ("
            + ", ".join(sorted(scopes))
            + "), so the columns are not two measurements of the same group."
        )

    columns = [
        VisualizationColumn(field="entity_name", label="District"),
        VisualizationColumn(field="period", label="Period"),
    ]
    for index, (_, series) in enumerate(series_by_dataset, start=1):
        columns.append(
            VisualizationColumn(
                field=f"metric_{index}",
                label=humanize_code(series.metric_code),
                unit=series.unit_code,
            )
        )
    table_rows: list[dict[str, str | int | float | bool | None]] = []
    for row in latest_rows[:200]:
        table_row: dict[str, str | int | float | bool | None] = {
            "entity_name": row.entity_name or row.entity_id,
            "period": row.period,
        }
        for index, (dataset_id, value) in enumerate(row.values.items(), start=1):
            del dataset_id
            table_row[f"metric_{index}"] = value
        table_rows.append(table_row)
    citation_ids = tuple(item.citation_id for item in citations)
    visualizations: tuple[VisualizationSpec, ...] = (
        VisualizationSpec(
            visualization_id="multi-dataset-comparison",
            type=VisualizationType.DATA_TABLE,
            title=f"Multi-dataset comparison · {latest_period}",
            description="Exact inner join on canonical district identity and reporting period.",
            columns=tuple(columns),
            rows=tuple(table_rows),
            citation_ids=citation_ids,
            truncated=truncated or len(latest_rows) > 200,
        ),
    )
    # A join of exactly two metrics is a relationship question, and a table of
    # two columns is the one shape that hides a relationship. The scatter shows
    # whether the districts line up or scatter; it asserts no causation, and the
    # answer text never claims one.
    scatter = _scatter(series_by_dataset, table_rows, latest_period, citation_ids)
    if scatter is not None:
        visualizations = (scatter, *visualizations)
    support.trace_visualizations(trace, visualizations)
    limitations = support.limitations.build(
        now=now,
        citations=citations,
        observed_entity_ids=(row.entity_id for row in latest_rows),
        requested_entity_ids=decomposition.entity_ids,
        catalog_terms=tuple(
            term
            for metadata, series in series_by_dataset
            for term in (metadata.topic, metadata.dataset_id, series.metric_code)
        ),
    )
    support.trace_limitations(trace, limitations)
    warnings = (
        ("The joined result exceeded 10000 rows and was truncated.",) if truncated else ()
    ) + fan_out_warning
    return answered(
        answer=answer,
        now=now,
        decomposition=decomposition,
        routed_plan=routed_plan,
        trace=trace,
        multi_dataset_analysis=analysis,
        citations=citations,
        assumptions=(
            "Each source is aggregated independently before joining.",
            "Only exact canonical district and reporting-period matches are included.",
        ),
        warnings=warnings,
        visualizations=visualizations,
        limitations=limitations,
    )


def explicit_catalog_datasets(
    question: str, records: Iterable[DatasetMetadata]
) -> tuple[DatasetMetadata, ...]:
    """Return catalog datasets whose topic or ID the question explicitly names.

    Matching is intentionally lexical and conservative. The guard exists to
    stop a one-table executor from dropping a requested input; it does not try
    to infer related datasets from broad concepts.

    A question is rarely typed in the catalog's own English slugs, so a curated
    spelling is accepted too: 人口 and dân số name the population topic just as
    "population" does. The vocabulary lives in `youth_compass.ontology.topics`
    and only recognizes spellings someone wrote down there, so this stays a
    naming question rather than an inference about which tables relate.
    """

    normalized = " ".join(question.casefold().replace("_", " ").replace("-", " ").split())
    spoken_topics = set(extract_topics(question))
    matched: dict[str, DatasetMetadata] = {}
    for item in records:
        dataset_phrase = " ".join(
            item.dataset_id.casefold().replace("_", " ").replace("-", " ").split()
        )
        topic_phrase = " ".join(item.topic.casefold().replace("_", " ").split())
        if (
            _contains_phrase(normalized, dataset_phrase)
            or _contains_phrase(normalized, topic_phrase)
            or resolve_topic_name(item.topic) in spoken_topics
        ):
            matched[item.dataset_id] = item
    return tuple(matched[key] for key in sorted(matched))


def _contains_phrase(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    if any("\u3400" <= character <= "\u9fff" for character in phrase):
        return phrase in text
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _period_granularity(period: str) -> str:
    """Name the reporting granularity a canonical period string encodes."""

    return "month" if "-" in period else "year"


def _align_period_granularity(
    series_by_dataset: "list[tuple[DatasetMetadata, ObservationSeries]]",
) -> tuple["list[tuple[DatasetMetadata, ObservationSeries]]", tuple[str, ...]]:
    """Collapse finer series onto the coarsest granularity the inputs share.

    A monthly series becomes annual by keeping the latest month present in each
    year, which is that year's closing snapshot. This is the correct reading for
    a point-in-time count such as a population register, and the wrong reading
    for a within-year total such as births, so every collapsed input is reported
    back to the caller and stated in the answer.

    Returns the aligned series and one note per input that was changed.
    """

    granularities = {
        _period_granularity(point.period)
        for _, series in series_by_dataset
        for point in series.points
    }
    if "year" not in granularities or granularities == {"year"}:
        return series_by_dataset, ()

    aligned: list[tuple[DatasetMetadata, ObservationSeries]] = []
    notes: list[str] = []
    for metadata, series in series_by_dataset:
        monthly = [point for point in series.points if _period_granularity(point.period) == "month"]
        if not monthly:
            aligned.append((metadata, series))
            continue
        latest: dict[tuple[str, str], ObservationPoint] = {}
        for point in series.points:
            year = point.period.split("-")[0]
            key = (point.entity_id, year)
            current = latest.get(key)
            if current is None or point.period > current.period:
                latest[key] = point
        collapsed = tuple(
            point.model_copy(update={"period": key[1]})
            for key, point in sorted(latest.items(), key=lambda item: (item[0][1], item[0][0]))
        )
        aligned.append((metadata, series.model_copy(update={"points": collapsed})))
        kept = sorted({point.period for point in latest.values()})
        notes.append(
            f"{metadata.dataset_id} reports monthly and was aligned to each year's closing "
            f"month ({', '.join(kept[:6])}{', …' if len(kept) > 6 else ''}); this reads as a "
            "point-in-time count, not a within-year total"
        )
    return aligned, tuple(notes)


def _no_overlap_reason(
    series_by_dataset: "list[tuple[DatasetMetadata, ObservationSeries]]",
) -> tuple[str, str]:
    """Explain why an exact entity-period join found nothing to align.

    Returns the machine-facing reason and the reader-facing diagnosis. A
    granularity mismatch is called out by name because the fix is a policy
    decision about how to aggregate over time, not more data.
    """

    granularities = {
        metadata.dataset_id: sorted({_period_granularity(point.period) for point in series.points})
        for metadata, series in series_by_dataset
    }
    distinct = {value for values in granularities.values() for value in values}
    if len(distinct) > 1:
        described = "; ".join(
            f"{dataset_id} reports by {' and '.join(values)}"
            for dataset_id, values in granularities.items()
        )
        return (
            f"datasets report at different period granularities ({described})",
            (
                "These datasets are published at different reporting granularities, so no "
                f"period lines up exactly ({described}). Combining them would mean deciding "
                "how to aggregate one of them over time, which changes what the numbers "
                "mean, so no answer was produced."
            ),
        )
    entity_sets = {
        metadata.dataset_id: {point.entity_id for point in series.points}
        for metadata, series in series_by_dataset
    }
    if not set.intersection(*entity_sets.values()):
        return (
            "datasets cover no district in common",
            (
                "These datasets cover no district in common, so they cannot be compared "
                "without inventing an alignment."
            ),
        )
    return (
        "datasets share districts but no common reporting period",
        (
            "These datasets share districts but no common reporting period, so they cannot "
            "be compared without inventing an alignment."
        ),
    )


def _joined_observation_key(entity_id: str, period: str) -> tuple[str, str]:
    district = resolve_district_name(entity_id).district
    return (district.code if district is not None else entity_id.casefold(), period)


_MIN_SCATTER_POINTS = 4


def _scatter(
    series_by_dataset: Sequence[tuple[DatasetMetadata, ObservationSeries]],
    table_rows: Sequence[dict[str, str | int | float | bool | None]],
    period: str,
    citation_ids: tuple[str, ...],
) -> VisualizationSpec | None:
    """Plot one joined metric against the other for the latest common period."""

    if len(series_by_dataset) != 2:
        return None
    rows = [
        row
        for row in table_rows
        if isinstance(row.get("metric_1"), int | float)
        and isinstance(row.get("metric_2"), int | float)
    ]
    if len(rows) < _MIN_SCATTER_POINTS:
        return None
    first, second = (series for _, series in series_by_dataset)
    return VisualizationSpec(
        visualization_id="multi-dataset-relationship",
        type=VisualizationType.SCATTER,
        title=(
            f"{humanize_code(first.metric_code)} against "
            f"{humanize_code(second.metric_code)} · {period}"
        ),
        description=(
            "One point per district in the latest period both datasets publish. "
            "Position shows how the two published figures sit together; it is not "
            "evidence that either causes the other."
        ),
        x=VisualizationEncoding(
            field="metric_1",
            label=humanize_code(first.metric_code),
            data_type="quantitative",
            unit=first.unit_code,
        ),
        y=VisualizationEncoding(
            field="metric_2",
            label=humanize_code(second.metric_code),
            data_type="quantitative",
            unit=second.unit_code,
        ),
        series_field="entity_name",
        rows=tuple(rows),
        citation_ids=citation_ids,
    )
