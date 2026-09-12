"""Grounded decision-support copilot API."""

from fastapi import APIRouter, Request, status
from pydantic import Field

from apps.api.dependencies import LocalRuntime
from apps.api.schemas import ApiModel
from youth_compass.acquisition import AcquisitionStart
from youth_compass.agent import CopilotResponse, ToolCapability

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


class CopilotQueryRequest(ApiModel):
    """Natural-language question plus optional candidate and quality scope."""

    question: str = Field(min_length=3, max_length=2_000)
    entity_ids: tuple[str, ...] = Field(default=(), max_length=500)
    min_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)


class SourceAcquisitionRequest(ApiModel):
    """Reviewer identity selecting one candidate previously returned by the agent."""

    candidate_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    submitted_by: str = Field(min_length=1, max_length=320)


@router.get("/capabilities", response_model=list[ToolCapability])
def list_copilot_capabilities(request: Request) -> list[ToolCapability]:
    """List the bounded tools currently discoverable by the smart router."""

    runtime: LocalRuntime = request.app.state.runtime
    return list(runtime.copilot().list_capabilities())


@router.post("/query", response_model=CopilotResponse)
async def query_copilot(payload: CopilotQueryRequest, request: Request) -> CopilotResponse:
    """Execute an allowlisted decision plan and return grounded evidence."""

    runtime: LocalRuntime = request.app.state.runtime
    return await runtime.copilot().answer(
        payload.question,
        entity_ids=payload.entity_ids,
        min_quality_score=payload.min_quality_score,
    )


@router.post(
    "/acquisitions",
    response_model=AcquisitionStart,
    status_code=status.HTTP_202_ACCEPTED,
)
def acquire_source(payload: SourceAcquisitionRequest, request: Request) -> AcquisitionStart:
    """Snapshot an allowlisted candidate into the approval-gated ingestion workflow."""

    runtime: LocalRuntime = request.app.state.runtime
    return runtime.acquisition.start(
        payload.candidate_id,
        submitted_by=payload.submitted_by,
    )
