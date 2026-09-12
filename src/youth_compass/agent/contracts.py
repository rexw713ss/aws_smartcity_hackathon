"""Grounded copilot contracts shared by API and model-provider adapters."""

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from youth_compass.ontology import RegistrationBasis
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
    SEARCH_TOOLS = "search_tools"
    SEARCH_WEB = "search_web"
    DISCOVER_SOURCES = "discover_sources"
    INSPECT_DATASET = "inspect_dataset"
    ACQUIRE_SOURCE = "acquire_source"
    QUERY_OBSERVATIONS = "query_observations"
    JOIN_OBSERVATIONS = "join_observations"
    GET_FEATURES = "get_features"
    COMPOSE_FEATURES = "compose_features"
    COMPARE_ENTITIES = "compare_entities"
    RANK_CANDIDATES = "rank_candidates"
    FORECAST_METRIC = "forecast_metric"
    SIMULATE_SCENARIO = "simulate_scenario"
    ASSESS_CAPACITY = "assess_capacity"
    RECOMMEND_INVESTMENT = "recommend_investment"
    EXPLAIN_LINEAGE = "explain_lineage"


class QuestionFocus(StrEnum):
    """A data question answered beyond a plain trend or comparison.

    Each value has one deterministic handler. The decomposer sets it from
    curated cues; nothing here is inferred by the answer composer.
    """

    LARGEST_DECLINE = "largest_decline"
    PRIORITY_EXPLANATION = "priority_explanation"
    COMPLETENESS = "completeness"
    ESTIMATES = "estimates"
    POPULATION_SCOPE = "population_scope"
    VERSION_CHANGES = "version_changes"
    JOINABILITY = "joinability"
    EVIDENCE_SUMMARY = "evidence_summary"
    FORECAST_ACCURACY = "forecast_accuracy"


# The canonical gender vocabulary, mirroring youth_compass.mapping.gender. A
# filter may only name a category the transformation layer actually produces.
type GenderCode = Literal["male", "female", "other", "unknown"]


class AnalysisFilters(BaseModel):
    """Allowlisted analytical filters that may persist across conversation turns.

    Every field maps to one canonical column. Adding a filter is a deliberate
    act: an unbounded filter set would let a follow-up narrow an answer along a
    dimension no tool validates.
    """

    model_config = ConfigDict(frozen=True)

    age_lower: int | None = Field(default=None, ge=0, le=120)
    age_upper: int | None = Field(default=None, ge=0, le=120)
    gender_code: GenderCode | None = None

    def model_post_init(self, context: object) -> None:
        del context
        if (
            self.age_lower is not None
            and self.age_upper is not None
            and self.age_lower > self.age_upper
        ):
            raise ValueError("age_lower must not exceed age_upper")

    @property
    def is_empty(self) -> bool:
        """True when no filter narrows the analysis."""

        return self.age_lower is None and self.age_upper is None and self.gender_code is None


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
    filters: AnalysisFilters = AnalysisFilters()
    operations: tuple[AnalysisOperation, ...] = Field(min_length=1)
    focus: QuestionFocus | None = None
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, max_length=400)


class ConversationContext(BaseModel):
    """Structured session memory; it deliberately contains no transcript or reasoning."""

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(pattern=r"^ses_[a-f0-9]{32}$")
    revision: int = Field(default=1, ge=1)
    objective: str = Field(min_length=1, max_length=300)
    subject_terms: tuple[str, ...] = ()
    metric_terms: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    time_expression: str | None = Field(default=None, max_length=120)
    filters: AnalysisFilters = AnalysisFilters()
    operations: tuple[AnalysisOperation, ...] = Field(min_length=1)
    updated_at: AwareDatetime

    def next(self, decomposition: "DecomposedQuery", updated_at: AwareDatetime) -> Self:
        return self.model_copy(
            update={
                "revision": self.revision + 1,
                "objective": decomposition.objective,
                "subject_terms": decomposition.subject_terms,
                "metric_terms": decomposition.metric_terms,
                "entity_ids": decomposition.entity_ids,
                "time_expression": decomposition.time_expression,
                "filters": decomposition.filters,
                "operations": decomposition.operations,
                "updated_at": updated_at,
            }
        )


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


class EvidenceExcerptRow(BaseModel):
    """One row actually used from a cited published snapshot.

    This is intentionally a bounded public projection, not a storage URI. It
    lets a reader verify the value and locate it by canonical keys without
    exposing filesystem paths, S3 bucket names, or credentials.
    """

    model_config = ConfigDict(frozen=True)

    entity_id: str
    entity_name: str
    metric_code: str
    metric_name: str
    value: float
    period: str | None = None
    observed_at: AwareDatetime | None = None


class EvidenceCitation(BaseModel):
    """Public provenance without leaking local storage paths or credentials."""

    model_config = ConfigDict(frozen=True)

    citation_id: str
    dataset_id: str
    dataset_version: str
    quality_score: float = Field(ge=0.0, le=1.0)
    retrieved_at: AwareDatetime
    excerpt: tuple[EvidenceExcerptRow, ...] = Field(default=(), max_length=100)


class WebCitation(BaseModel):
    """A search result used as web evidence, separate from published datasets."""

    model_config = ConfigDict(frozen=True)

    citation_id: str = Field(pattern=r"^web-\d+$")
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(pattern=r"^https://", max_length=2_000)
    snippet: str = Field(default="", max_length=2_000)
    published_at: AwareDatetime | None = None


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


class JoinedObservationRow(BaseModel):
    """One exact entity-period intersection across multiple published datasets."""

    model_config = ConfigDict(frozen=True)

    entity_id: str
    entity_name: str | None = None
    period: str
    values: dict[str, float] = Field(min_length=2)


class MultiDatasetAnalysis(BaseModel):
    """Validated one-to-one join of already aggregated observation series."""

    model_config = ConfigDict(frozen=True)

    join_dimensions: tuple[Literal["entity_id", "period"], ...] = (
        "entity_id",
        "period",
    )
    dataset_metrics: dict[str, str] = Field(min_length=2)
    rows: tuple[JoinedObservationRow, ...] = Field(min_length=1, max_length=10_000)


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


class ImpactDataGap(BaseModel):
    """Evidence required before one downstream impact may be estimated."""

    model_config = ConfigDict(frozen=True)

    domain: Literal["housing", "transport", "public_services"]
    required_metrics: tuple[str, ...]
    reason: str


class ImpactFinding(BaseModel):
    """One measured or derived link in an impact chain."""

    model_config = ConfigDict(frozen=True)

    stage: Literal["population", "housing", "transport", "public_services"]
    label: str
    baseline_value: float | None = None
    scenario_value: float | None = None
    absolute_delta: float | None = None
    unit: str
    evidence_kind: Literal["official", "derived", "user_assumption"]


class InvestmentRecommendation(BaseModel):
    """A recommendation emitted only when its capacity evidence is complete."""

    model_config = ConfigDict(frozen=True)

    priority: int = Field(ge=1)
    domain: Literal["housing", "transport", "public_services"]
    action: str
    rationale: str
    confidence: Literal["low", "medium", "high"]


class ImpactAnalysis(BaseModel):
    """Auditable scenario-to-impact-to-recommendation chain."""

    model_config = ConfigDict(frozen=True)

    district_code: str
    district_name: str
    observed_period: str
    target_year: int
    shock_people: int
    findings: tuple[ImpactFinding, ...]
    data_gaps: tuple[ImpactDataGap, ...] = ()
    recommendations: tuple[InvestmentRecommendation, ...] = ()
    confidence: Literal["insufficient", "low", "medium", "high"]


class VisualizationType(StrEnum):
    """Frontend-agnostic visualization templates supported by the API."""

    LINE = "line"
    COMPARISON_BAR = "comparison_bar"
    RANKING_BAR = "ranking_bar"
    CONTRIBUTION_BAR = "contribution_bar"
    CHOROPLETH = "choropleth"
    DATA_TABLE = "data_table"


class RegionScheme(StrEnum):
    """Boundary set a choropleth's region field is keyed against.

    The spec names the scheme instead of shipping geometry. A renderer joins the
    rows to whichever boundary file it already has for that scheme, so the
    backend never sends a megabyte of coordinates through the answer contract.
    """

    NEW_TAIPEI_DISTRICT = "new_taipei_district"


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
    # Set only on a choropleth: which row field carries the region key, and
    # which boundary set that key belongs to.
    region_field: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    region_scheme: RegionScheme | None = None
    columns: tuple[VisualizationColumn, ...] = ()
    rows: tuple[dict[str, VisualizationValue], ...] = Field(default=(), max_length=500)
    citation_ids: tuple[str, ...] = ()
    truncated: bool = False

    def model_post_init(self, context: object) -> None:
        del context
        mapped = self.type is VisualizationType.CHOROPLETH
        if mapped and (self.region_field is None or self.region_scheme is None):
            raise ValueError("a choropleth must name its region field and boundary scheme")
        if not mapped and (self.region_field is not None or self.region_scheme is not None):
            raise ValueError("only a choropleth may carry region fields")


class DataFreshness(BaseModel):
    """How old the evidence behind one citation was when the answer was built."""

    model_config = ConfigDict(frozen=True)

    citation_id: str
    dataset_id: str
    dataset_version: str
    published_at: AwareDatetime
    # Publication lag, not collection lag: a dataset published today can still
    # describe last year's reporting period.
    age_days: int = Field(ge=0)


class CoverageGap(BaseModel):
    """Which entities the requested boundary set expected but the answer lacks."""

    model_config = ConfigDict(frozen=True)

    region_scheme: RegionScheme
    expected_entity_count: int = Field(ge=0)
    observed_entity_count: int = Field(ge=0)
    missing_entity_names: tuple[str, ...] = ()
    # Entities the answer returned that are not part of the boundary set.
    unmapped_entity_ids: tuple[str, ...] = ()


class DataLimitations(BaseModel):
    """Reader-facing audit of freshness, coverage, and definitional basis.

    Every field is derived from evidence the answer already used. Nothing here
    is estimated, interpolated, or inferred from a topic name.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    freshness: tuple[DataFreshness, ...] = ()
    coverage: CoverageGap | None = None
    registration_basis: RegistrationBasis = RegistrationBasis.UNKNOWN
    notes: tuple[str, ...] = ()


class AnswerCompositionContext(BaseModel):
    """Only grounded, public facts that an answer composer may verbalize."""

    model_config = ConfigDict(frozen=True)

    question: str = Field(min_length=3)
    analysis_type: Literal[
        "decision", "dataset_inspection", "observation_comparison", "forecast", "data_question",
        "web_search"
    ]
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
    feature_name: str | None = None
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
    session_id: str | None = Field(default=None, pattern=r"^ses_[a-f0-9]{32}$")
    decomposition: DecomposedQuery | None = None
    routed_plan: RoutedToolPlan | None = None
    plan: DecisionExecutionPlan | None = None
    dataset_inspection: DatasetInspection | None = None
    observation_series: ObservationSeries | None = None
    multi_dataset_analysis: MultiDatasetAnalysis | None = None
    comparison: EntityComparison | None = None
    impact_analysis: ImpactAnalysis | None = None
    forecast_result: ForecastResult | None = None
    candidates: tuple[CandidateInsight, ...] = ()
    citations: tuple[EvidenceCitation, ...] = ()
    web_citations: tuple[WebCitation, ...] = ()
    tool_trace: tuple[ToolTrace, ...] = ()
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    data_requirement: DataRequirement | None = None
    source_candidates: tuple[SourceCandidate, ...] = ()
    visualizations: tuple[VisualizationSpec, ...] = ()
    limitations: DataLimitations | None = None
