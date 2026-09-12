"""Grounded copilot contracts shared by API and model-provider adapters."""

from datetime import datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class CopilotStatus(StrEnum):
    """Whether the available evidence supports an answer."""

    ANSWERED = "answered"
    INSUFFICIENT_DATA = "insufficient_data"
    UNSUPPORTED_QUESTION = "unsupported_question"


class AnalysisOperation(StrEnum):
    """Generic operations that may be routed to registered tools."""

    SEARCH_CATALOG = "search_catalog"
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

    original_question: str = Field(min_length=3)
    objective: str = Field(min_length=1)
    subject_terms: tuple[str, ...] = ()
    metric_terms: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    time_expression: str | None = None
    operations: tuple[AnalysisOperation, ...] = Field(min_length=1)
    needs_clarification: bool = False
    clarification_question: str | None = None


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
    candidates: tuple[CandidateInsight, ...] = ()
    citations: tuple[EvidenceCitation, ...] = ()
    tool_trace: tuple[ToolTrace, ...] = ()
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
