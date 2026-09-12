"""Grounded decision-support copilot API."""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request, status
from pydantic import Field
from starlette.responses import StreamingResponse

from apps.api.dependencies import LocalRuntime
from apps.api.schemas import MAX_UPLOAD_BYTES, ApiModel
from youth_compass.acquisition import AcquisitionStart, LinkAcquisitionStart
from youth_compass.agent import CopilotResponse, ToolCapability
from youth_compass.decisioning import (
    PopulationBalanceMode,
    ScenarioAdjustment,
    ScenarioOperation,
    YouthPopulationScenarioResult,
)

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


class CopilotQueryRequest(ApiModel):
    """Natural-language question plus optional candidate and quality scope."""

    question: str = Field(min_length=3, max_length=2_000)
    entity_ids: tuple[str, ...] = Field(default=(), max_length=500)
    min_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    session_id: str | None = Field(default=None, pattern=r"^ses_[a-f0-9]{32}$")


class SourceAcquisitionRequest(ApiModel):
    """Reviewer identity selecting one candidate previously returned by the agent."""

    candidate_id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    submitted_by: str = Field(min_length=1, max_length=320)


class LinkAcquisitionRequest(ApiModel):
    """A reviewer pointing at data the manifest does not list yet."""

    url: str = Field(min_length=12, max_length=2_000, pattern=r"^https://")
    submitted_by: str = Field(min_length=1, max_length=320)
    topic_hint: str | None = Field(default=None, max_length=100)


class DataIntakeOptions(ApiModel):
    """How a reviewer may supply missing data from the conversation."""

    link_hosts: tuple[str, ...]
    upload_formats: tuple[str, ...]
    max_upload_bytes: int


class ScenarioAdjustmentRequest(ApiModel):
    """A user-supplied scenario assumption, never presented as observed data."""

    district_id: str = Field(min_length=1, max_length=80)
    operation: ScenarioOperation
    value: float = Field(default=0, ge=-1_000_000, le=1_000_000)
    source_district_id: str | None = Field(default=None, min_length=1, max_length=80)


class YouthPopulationScenarioRequest(ApiModel):
    """A bounded cohort projection from the latest complete district snapshot."""

    balance_mode: PopulationBalanceMode = PopulationBalanceMode.OPEN
    target_year: int | None = Field(default=None, ge=2026, le=2043)
    adjustments: tuple[ScenarioAdjustmentRequest, ...] = Field(min_length=1, max_length=20)


@router.get("/capabilities", response_model=list[ToolCapability])
def list_copilot_capabilities(request: Request) -> list[ToolCapability]:
    """List the bounded tools currently discoverable by the smart router."""

    runtime: LocalRuntime = request.app.state.runtime
    return list(runtime.copilot().list_capabilities())


@router.post("/what-if", response_model=YouthPopulationScenarioResult)
def run_youth_population_scenario(
    payload: YouthPopulationScenarioRequest, request: Request
) -> YouthPopulationScenarioResult:
    """Compare observed district youth population with explicit user assumptions."""

    runtime: LocalRuntime = request.app.state.runtime
    adjustments = tuple(
        ScenarioAdjustment(
            district_id=item.district_id,
            operation=item.operation,
            value=item.value,
            source_district_id=item.source_district_id,
        )
        for item in payload.adjustments
    )
    return runtime.scenarios().run(
        adjustments,
        balance_mode=payload.balance_mode,
        target_year=payload.target_year,
    )


@router.post("/query", response_model=CopilotResponse)
async def query_copilot(payload: CopilotQueryRequest, request: Request) -> CopilotResponse:
    """Execute an allowlisted decision plan and return grounded evidence."""

    runtime: LocalRuntime = request.app.state.runtime
    return await runtime.copilot().answer(
        payload.question,
        entity_ids=payload.entity_ids,
        min_quality_score=payload.min_quality_score,
        session_id=payload.session_id,
    )


@router.post("/query/stream", response_class=StreamingResponse)
async def stream_copilot(payload: CopilotQueryRequest, request: Request) -> StreamingResponse:
    """Stream Bedrock answer snapshots, then the validated structured response."""

    runtime: LocalRuntime = request.app.state.runtime
    queue: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()
    last_text = ""

    async def on_text(text: str) -> None:
        nonlocal last_text
        if text.startswith(last_text):
            await queue.put({"type": "delta", "text": text[len(last_text) :]})
        else:
            # A grounding failure replaces provisional model output with the
            # deterministic safe answer.
            await queue.put({"type": "text", "text": text})
        last_text = text

    async def produce() -> None:
        try:
            response = await runtime.copilot().answer(
                payload.question,
                entity_ids=payload.entity_ids,
                min_quality_score=payload.min_quality_score,
                session_id=payload.session_id,
                on_text=on_text,
            )
            # Deterministic/refusal paths do not invoke Bedrock's answer composer.
            # Send their complete answer once before the structured result.
            if response.answer != last_text:
                await queue.put({"type": "text", "text": response.answer})
            await queue.put(
                {"type": "result", "response": response.model_dump(mode="json")}
            )
        except Exception as exc:  # The HTTP status is already committed once streaming begins.
            await queue.put({"type": "error", "message": str(exc)[:400]})
        finally:
            await queue.put(None)

    async def events() -> AsyncIterator[str]:
        task = asyncio.create_task(produce())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
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


@router.post(
    "/acquisitions/link",
    response_model=LinkAcquisitionStart,
    status_code=status.HTTP_202_ACCEPTED,
)
def acquire_link(payload: LinkAcquisitionRequest, request: Request) -> LinkAcquisitionStart:
    """Snapshot a reviewer link from an approved host into the approval-gated workflow."""

    runtime: LocalRuntime = request.app.state.runtime
    return runtime.acquisition.start_from_link(
        payload.url,
        submitted_by=payload.submitted_by,
        topic_hint=payload.topic_hint,
    )


@router.get("/intake-options", response_model=DataIntakeOptions)
def data_intake_options(request: Request) -> DataIntakeOptions:
    """Tell the chat which hosts a link may use, so it can say so before a reviewer tries."""

    runtime: LocalRuntime = request.app.state.runtime
    return DataIntakeOptions(
        link_hosts=runtime.acquisition.link_hosts,
        upload_formats=("csv", "json", "xlsx"),
        max_upload_bytes=MAX_UPLOAD_BYTES,
    )
