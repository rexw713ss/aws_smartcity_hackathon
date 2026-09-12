"""SourceAdapter Stage 1 proposal for heterogeneous tabular uploads.

The backend workstream may amend this boundary as new formats arrive. See the
ports section in docs/07-project-structure.md and the implementation details in
docs/18-tabular-source-adapters.md.
"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from youth_compass.domain.types import FileFormat


class NormalizedTabularSource(BaseModel):
    """CSV staging payload plus provenance from the original source."""

    model_config = ConfigDict(frozen=True)

    content: bytes
    file_name: str
    source_format: FileFormat
    warnings: tuple[str, ...] = ()


@runtime_checkable
class SourceAdapter(Protocol):
    """Normalize one supported source without applying business mappings."""

    def normalize(self, file_name: str, content: bytes) -> NormalizedTabularSource:
        """Return a UTF-8 CSV staging payload or raise SourceNormalizationError."""
        ...
