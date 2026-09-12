"""Public application contracts for external data acquisition."""

from pydantic import AwareDatetime, BaseModel, ConfigDict

from youth_compass.domain.types import FileFormat
from youth_compass.ports import SourceCandidate


class AcquisitionStart(BaseModel):
    """Public handoff from source acquisition to the ingestion workflow."""

    model_config = ConfigDict(frozen=True)

    candidate: SourceCandidate
    ingestion_job_id: str
    ingestion_status: str
    created_at: AwareDatetime


class LinkAcquisitionStart(BaseModel):
    """Public handoff after a reviewer-supplied link enters the ingestion workflow."""

    model_config = ConfigDict(frozen=True)

    url: str
    host: str
    file_name: str
    source_format: FileFormat
    ingestion_job_id: str
    ingestion_status: str
    created_at: AwareDatetime
