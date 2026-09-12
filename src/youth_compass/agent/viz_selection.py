"""Scoring that keeps the chart worth drawing and rejects the rest. Doc 30, stage 4.

A builder can construct many defensible specs from one result. Returning all of
them is what makes an answer look busy and say little: a bar chart of 29
districts whose values differ by one percent is a picture of nothing, and a line
beside a map of the same period is the same fact drawn twice.

Scoring reads the candidate's own rows, so it applies equally to a ranking, a
trend, or a choropleth. A `SeriesProfile` refines the verdict where one exists.
Rejections are returned, never swallowed: the caller records them on the tool
trace so a reviewer can see which views were considered and why each was cut.
"""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from youth_compass.agent.contracts import VisualizationSpec, VisualizationType
from youth_compass.agent.data_shape import SeriesProfile

# A trend that moves this much end to end earns full marks; less scales down.
_STRONG_TREND_RATIO = 0.10
# Relative spread across categories that earns full marks for a cross-entity view.
_STRONG_CONTRAST = 0.20
# Below this, a chart is not worth the space it takes from the answer.
_MIN_SCORE = 0.40
_DEFAULT_CHART_LIMIT = 2
# Even a perfectly targeted chart must carry some signal, so intent alone can
# never push a flat result over the line.
_INTENT_FLOOR = 0.25


class CandidateRole(StrEnum):
    """What a candidate shows. One view per role reaches the answer."""

    TREND = "trend"
    CROSS_ENTITY = "cross_entity"
    CONTRIBUTION = "contribution"
    AUDIT = "audit"


class RejectionReason(StrEnum):
    """Why a built candidate did not reach the answer."""

    BLOCKING_ISSUE = "blocking_issue"
    WEAK_SIGNAL = "weak_signal"
    WEAK_INTENT_FIT = "weak_intent_fit"
    REDUNDANT_VIEW = "redundant_view"
    OVER_LIMIT = "over_limit"


@dataclass(frozen=True, slots=True)
class VisualizationCandidate:
    """One spec a builder could return, with how well it fits what was asked."""

    spec: VisualizationSpec
    role: CandidateRole
    # 0 when the question gives no reason to draw this; 1 when it asked for it.
    intent_fit: float = 1.0


class RejectedVisualization(BaseModel):
    """An auditable record of a view that was built and then cut."""

    model_config = ConfigDict(frozen=True)

    visualization_id: str
    reason: RejectionReason
    detail: str = Field(min_length=1)


class SelectionResult(BaseModel):
    """What the answer shows, and what it deliberately does not."""

    model_config = ConfigDict(frozen=True)

    selected: tuple[VisualizationSpec, ...] = ()
    rejected: tuple[RejectedVisualization, ...] = ()


def select_visualizations(
    candidates: tuple[VisualizationCandidate, ...],
    *,
    profile: SeriesProfile | None = None,
    chart_limit: int = _DEFAULT_CHART_LIMIT,
) -> SelectionResult:
    """Keep the smallest set of views that each add something the others do not."""

    rejected: list[RejectedVisualization] = []
    scored: list[tuple[float, VisualizationCandidate]] = []
    blocked = profile is not None and profile.has_blocking_issue

    for candidate in candidates:
        if blocked and candidate.role is not CandidateRole.AUDIT:
            rejected.append(
                _rejection(
                    candidate,
                    RejectionReason.BLOCKING_ISSUE,
                    "the result contains a defect that would make any chart of it misleading",
                )
            )
            continue
        strength = informativeness(candidate)
        score = candidate.intent_fit * (_INTENT_FLOOR + (1 - _INTENT_FLOOR) * strength)
        if score < _MIN_SCORE:
            rejected.append(_weak(candidate, strength))
            continue
        scored.append((score, candidate))

    scored.sort(key=lambda item: (-item[0], item[1].spec.visualization_id))
    selected: list[VisualizationSpec] = []
    audits: list[VisualizationSpec] = []
    seen_roles: set[CandidateRole] = set()
    for score, candidate in scored:
        del score
        if candidate.role is CandidateRole.AUDIT:
            audits.append(candidate.spec)
            continue
        if candidate.role in seen_roles:
            rejected.append(
                _rejection(
                    candidate,
                    RejectionReason.REDUNDANT_VIEW,
                    f"another {candidate.role.value} view already shows this",
                )
            )
            continue
        if len(selected) >= chart_limit:
            rejected.append(
                _rejection(
                    candidate,
                    RejectionReason.OVER_LIMIT,
                    f"the answer already carries {chart_limit} charts",
                )
            )
            continue
        seen_roles.add(candidate.role)
        selected.append(candidate.spec)

    return SelectionResult(selected=tuple([*selected, *audits]), rejected=tuple(rejected))


def informativeness(candidate: VisualizationCandidate) -> float:
    """How much of a story the candidate's own rows actually contain, in 0..1."""

    if candidate.role is CandidateRole.AUDIT:
        # A table's value is exactness, not contrast, so it is neither promoted
        # nor punished by the signal in its numbers.
        return 0.5
    if candidate.role is CandidateRole.TREND:
        return min(1.0, _trend_strength(candidate.spec) / _STRONG_TREND_RATIO)
    return min(1.0, _contrast(candidate.spec) / _STRONG_CONTRAST)


def _trend_strength(spec: VisualizationSpec) -> float:
    """The largest end-to-end movement any one series makes, relative to itself."""

    if spec.x is None or spec.y is None:
        return 0.0
    by_series: dict[str, list[tuple[str, float]]] = {}
    for row in spec.rows:
        value = row.get(spec.y.field)
        period = row.get(spec.x.field)
        if not isinstance(value, int | float) or not isinstance(period, str):
            continue
        key = str(row.get(spec.series_field) or "") if spec.series_field else ""
        by_series.setdefault(key, []).append((period, float(value)))
    ratios: list[float] = []
    for points in by_series.values():
        ordered = sorted(points)
        if len(ordered) < 2 or not ordered[0][1]:
            continue
        ratios.append(abs(ordered[-1][1] - ordered[0][1]) / abs(ordered[0][1]))
    return max(ratios, default=0.0)


def _contrast(spec: VisualizationSpec) -> float:
    """Spread across categories, scaled by the largest value on the axis.

    Using the largest magnitude as the denominator keeps this meaningful for
    changes, which straddle zero and would make a mean-based measure explode.
    """

    if spec.y is None:
        return 0.0
    values = [
        float(value) for row in spec.rows if isinstance(value := row.get(spec.y.field), int | float)
    ]
    if len(values) < 2:
        return 0.0
    scale = max(abs(min(values)), abs(max(values)))
    return (max(values) - min(values)) / scale if scale else 0.0


def _weak(candidate: VisualizationCandidate, strength: float) -> RejectedVisualization:
    if candidate.intent_fit < 1.0 and strength >= 0.5:
        return _rejection(
            candidate,
            RejectionReason.WEAK_INTENT_FIT,
            "the question gives no reason to draw this view",
        )
    return _rejection(
        candidate,
        RejectionReason.WEAK_SIGNAL,
        _weak_signal_detail(candidate),
    )


def _weak_signal_detail(candidate: VisualizationCandidate) -> str:
    if candidate.role is CandidateRole.TREND:
        return "the series barely moves, so a trend line would suggest a story that is not there"
    return "the categories differ by too little to be worth a chart"


def _rejection(
    candidate: VisualizationCandidate, reason: RejectionReason, detail: str
) -> RejectedVisualization:
    return RejectedVisualization(
        visualization_id=candidate.spec.visualization_id, reason=reason, detail=detail
    )


def role_for(spec_type: VisualizationType) -> CandidateRole:
    """Default role for a template, so a builder rarely has to name one."""

    match spec_type:
        case VisualizationType.LINE | VisualizationType.SLOPE:
            return CandidateRole.TREND
        case VisualizationType.CONTRIBUTION_BAR:
            return CandidateRole.CONTRIBUTION
        case VisualizationType.DATA_TABLE:
            return CandidateRole.AUDIT
        case _:
            return CandidateRole.CROSS_ENTITY


__all__ = [
    "CandidateRole",
    "RejectedVisualization",
    "RejectionReason",
    "SelectionResult",
    "VisualizationCandidate",
    "informativeness",
    "role_for",
    "select_visualizations",
]
