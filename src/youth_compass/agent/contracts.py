"""Grounded copilot contracts shared by API and model-provider adapters."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from youth_compass.ports import DataRequirement, ForecastResult, SourceCandidate


class CopilotStatus(StrEnum):
    """Whether the available evidence supports an answer."""

    ANSWERED = "answered"
    INSUFFICIENT_DATA = "insufficient_data"
    ACQUISITION_REQUIRED = "acquisition_required"
    UNSUPPORTED_QUESTION = "unsupported_question"


class AnalysisOperation(StrEnum):
    """Generic operations that may be routed to registered tools."""

    SEARCH_CATALOG = "search_catalog"
    DISCOVER_SOURCES = "discover_sources"
    INSPECT_DATASET = "inspect_dataset"
    ACQUIRE_SOURCE = "acquire_source"
    QUERY_OBSERVATIONS = "query_observations"
    GET_FEATURES = "get_features"
    COMPOSE_FEATURES = "compose_features"
    COMPARE_ENTITIES = "compare_entities"
    RANK_CANDIDATES = "rank_candidates"
    FORECAST_METRIC = "forecast_metric"
    EXPLAIN_LINEAGE = "explain_lineage"


class DecomposedQuery(BaseModel):
    """Structured question decomposition proposed before tool selection."""

    model_config = ConfigDict(frozen=True)

    # original_question echoes the user, so it carries no upper bound here.
    # Every field the model composes does: a model that cannot decide what to
    # write in a free-text field degenerates into a run-on string and burns the
    # whole token budget, truncating the JSON. Bedrock strips maxLength from the
    # schema, so these bounds are enforced on validation instead.
    original_question: str = Field(min_length=3)
    objective: str = Field(min_length=1, max_length=300)
    subject_terms: tuple[str, ...] = ()
    metric_terms: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    time_expression: str | None = Field(default=None, max_length=120)
    operations: tuple[AnalysisOperation, ...] = Field(min_length=1)
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=400)


class ToolCapability(BaseModel):
    """Discoverable metadata for a bounded executable tool."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    operation: AnalysisOperation
    description: str = Field(min_length=1)
    requires: tuple[AnalysisOperation, ...] = ()


class RoutedToolStep(BaseModel):
    """One tool chosen deterministically for a decomposed operation."""

    model_config = ConfigDict(frozen=True)

    step_id: str = Field(pattern=r"^step_[0-9]+$")
    operation: AnalysisOperation
    tool_name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    depends_on: tuple[str, ...] = ()


class RoutedToolPlan(BaseModel):
    """Router result including explicit gaps for unavailable capabilities."""

    model_config = ConfigDict(frozen=True)

    steps: tuple[RoutedToolStep, ...] = ()
    missing_operations: tuple[AnalysisOperation, ...] = ()

    @property
    def executable(self) -> bool:
        return not self.missing_operations


class CopilotIntent(BaseModel):
    """Allowlisted interpretation that a future Bedrock planner may propose."""

    model_config = ConfigDict(frozen=True)

    profile_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    entity_ids: tuple[str, ...] = ()


class DecisionExecutionPlan(BaseModel):
    """Deterministic plan executed after intent validation."""

    model_config = ConfigDict(frozen=True)

    profile_code: str
    profile_version: str
    feature_codes: tuple[str, ...]
    entity_ids: tuple[str, ...] = ()
    min_quality_score: float = Field(ge=0.0, le=1.0)


class ToolTrace(BaseModel):
    """Auditable record of a bounded tool invocation."""

    model_config = ConfigDict(frozen=True)

    tool: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    outcome: str
    summary: str


class EvidenceCitation(BaseModel):
    """Public provenance without leaking local storage paths or credentials."""

    model_config = ConfigDict(frozen=True)

    citation_id: str
    dataset_id: str
    dataset_version: str
    quality_score: float = Field(ge=0.0, le=1.0)
    retrieved_at: AwareDatetime


class DatasetInspection(BaseModel):
    """Schema and coverage selected from the published catalog."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    dataset_version: str
    topic: str
    grain: tuple[str, ...]
    metric_code: str
    available_metrics: tuple[str, ...]
    period_start: str
    period_end: str
    entity_count: int = Field(ge=0)
    quality_score: float = Field(ge=0.0, le=1.0)


class ObservationPoint(BaseModel):
    """One safely aggregated metric value for an entity and period."""

    model_config = ConfigDict(frozen=True)

    entity_id: str
    entity_name: str | None = None
    period: str
    value: float
    estimated_value: float = Field(ge=0.0)


class ObservationSeries(BaseModel):
    """Validated observation query output used by downstream analysis tools."""

    model_config = ConfigDict(frozen=True)

    dataset_id: str
    dataset_version: str
    metric_code: str
    unit_code: str
    population_scope: str
    points: tuple[ObservationPoint, ...]


class EntityChange(BaseModel):
    """Deterministic first-to-last change for one entity."""

    model_config = ConfigDict(frozen=True)

    entity_id: str
    entity_name: str | None = None
    first_period: str
    last_period: str
    first_value: float
    last_value: float
    absolute_change: float
    percent_change: float | None = None
    direction: str
    observation_count: int = Field(ge=1)


class EntityComparison(BaseModel):
    """Comparable changes calculated from one compatible observation series."""

    model_config = ConfigDict(frozen=True)

    metric_code: str
    unit_code: str
    changes: tuple[EntityChange, ...]


class VisualizationType(StrEnum):
    """Frontend-agnostic visualization templates supported by the API."""

    LINE = "line"
    COMPARISON_BAR = "comparison_bar"
    RANKING_BAR = "ranking_bar"
    CONTRIBUTION_BAR = "contribution_bar"
    DATA_TABLE = "data_table"


class VisualizationEncoding(BaseModel):
    """Stable mapping from one row field to a visual channel."""

    model_config = ConfigDict(frozen=True)

    field: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    data_type: Literal["nominal", "ordinal", "quantitative", "temporal"]
    unit: str | None = None


class VisualizationColumn(BaseModel):
    """One localized column in a table fallback."""

    model_config = ConfigDict(frozen=True)

    field: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    unit: str | None = None


type VisualizationValue = str | int | float | bool | None


class VisualizationSpec(BaseModel):
    """Declarative, allowlisted visualization with grounded inline rows."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    visualization_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    type: VisualizationType
    title: str = Field(min_length=1)
    description: str | None = None
    x: VisualizationEncoding | None = None
    y: VisualizationEncoding | None = None
    series_field: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    columns: tuple[VisualizationColumn, ...] = ()
    rows: tuple[dict[str, VisualizationValue], ...] = Field(default=(), max_length=500)
    citation_ids: tuple[str, ...] = ()
    truncated: bool = False


class AnswerCompositionContext(BaseModel):
    """Only grounded, public facts that an answer composer may verbalize."""

    model_config = ConfigDict(frozen=True)

    question: str = Field(min_length=3)
    analysis_type: Literal["decision", "dataset_inspection", "observation_comparison", "forecast"]
    grounded_facts_json: str = Field(min_length=2)
    allowed_citation_ids: tuple[str, ...] = ()
    fallback_answer: str = Field(min_length=1)


class ComposedAnswer(BaseModel):
    """Narrative selected after grounding and safety validation."""

    model_config = ConfigDict(frozen=True)

    answer: str = Field(min_length=1)
    citation_ids: tuple[str, ...] = ()
    mode: Literal["model", "deterministic"]


class AnswerDraft(BaseModel):
    """Strict schema returned by the model before safety checks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str = Field(min_length=1)
    citation_ids: tuple[str, ...] = ()


class FeatureContributionInsight(BaseModel):
    """Public explanation of one feature's score contribution."""

    model_config = ConfigDict(frozen=True)

    feature_code: str
    raw_value: float
    effective_weight: float
    points: float
    citations: tuple[str, ...]


class CandidateInsight(BaseModel):
    """Ranked candidate projection safe for an API response."""

    model_config = ConfigDict(frozen=True)

    rank: int | None = Field(default=None, ge=1)
    entity_id: str
    entity_name: str | None = None
    eligible: bool
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    contributions: tuple[FeatureContributionInsight, ...] = ()
    failed_constraints: tuple[str, ...] = ()
    missing_required_features: tuple[str, ...] = ()


class CopilotResponse(BaseModel):
    """Grounded answer with plan, trace, ranking, evidence, and limitations."""

    status: CopilotStatus
    answer: str
    generated_at: datetime
    decomposition: DecomposedQuery | None = None
    routed_plan: RoutedToolPlan | None = None
    plan: DecisionExecutionPlan | None = None
    dataset_inspection: DatasetInspection | None = None
    observation_series: ObservationSeries | None = None
    comparison: EntityComparison | None = None
    forecast_result: ForecastResult | None = None
    candidates: tuple[CandidateInsight, ...] = ()
    citations: tuple[EvidenceCitation, ...] = ()
    tool_trace: tuple[ToolTrace, ...] = ()
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    data_requirement: DataRequirement | None = None
    source_candidates: tuple[SourceCandidate, ...] = ()
    visualizations: tuple[VisualizationSpec, ...] = ()
