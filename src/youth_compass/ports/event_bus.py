"""EventBus port and its payload model.

Stage 1 proposal originating from the AWS workstream. The backend workstream may
amend these signatures; see docs/12-aws-stage1-foundation.md for the amendment
procedure. Filename fixed by docs/07-project-structure.md section 7.

``event_type`` uses the dotted audit vocabulary already fixed in
docs/08-quality-security-observability.md section 6.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class DomainEvent(BaseModel):
    """An append-only audit event."""

    event_type: str = Field(min_length=1)
    occurred_at: datetime
    actor: str
    resource_id: str
    trace_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)


@runtime_checkable
class EventBus(Protocol):
    """Publish and subscribe for domain events."""

    def publish(self, event: DomainEvent) -> None:
        """Publish ``event`` to every handler subscribed to its type."""
        ...

    def subscribe(self, event_type: str, handler: Callable[[DomainEvent], None]) -> None:
        """Register ``handler`` for every event whose type equals ``event_type``.

        A subscribed handler receives every matching event in publish order, and
        no non-matching event.
        """
        ...
