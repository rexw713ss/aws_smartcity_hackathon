"""Port Protocols: the seam between application logic and infrastructure.

Every Protocol here is a Stage 1 proposal originating from the AWS workstream.
The backend workstream may amend the signatures; see
docs/12-aws-stage1-foundation.md for the amendment procedure.

Modules import only from the standard library, ``pydantic``, and
``youth_compass.domain``. No module here may import ``boto3``, ``fastapi``, or
anything under ``adapters/``; a guard test enforces that.
"""

from youth_compass.ports.catalog import DataCatalog
from youth_compass.ports.checkpoint_store import CheckpointStore, WorkflowCheckpoint
from youth_compass.ports.clock import Clock
from youth_compass.ports.event_bus import DomainEvent, EventBus
from youth_compass.ports.forecast_service import (
    ForecastPoint,
    ForecastRequest,
    ForecastResult,
    ForecastService,
    TrainingRequest,
    TrainingRun,
    TrainingStatus,
)
from youth_compass.ports.model_provider import (
    ModelProvider,
    ModelRequest,
    ModelResponse,
)
from youth_compass.ports.object_store import ObjectStore
from youth_compass.ports.query_engine import QueryEngine, QueryResult, QuerySpec
from youth_compass.ports.source_adapter import NormalizedTabularSource, SourceAdapter
from youth_compass.ports.workflow_runner import (
    ApprovalDecision,
    IngestionRequest,
    JobReference,
    JobStatus,
    WorkflowRunner,
)

__all__ = [
    "ApprovalDecision",
    "CheckpointStore",
    "Clock",
    "DataCatalog",
    "DomainEvent",
    "EventBus",
    "ForecastPoint",
    "ForecastRequest",
    "ForecastResult",
    "ForecastService",
    "IngestionRequest",
    "JobReference",
    "JobStatus",
    "ModelProvider",
    "ModelRequest",
    "ModelResponse",
    "NormalizedTabularSource",
    "ObjectStore",
    "QueryEngine",
    "QueryResult",
    "QuerySpec",
    "SourceAdapter",
    "TrainingRequest",
    "TrainingRun",
    "TrainingStatus",
    "WorkflowCheckpoint",
    "WorkflowRunner",
]
