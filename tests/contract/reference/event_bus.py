"""In-memory EventBus reference implementation."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from tests.contract.registry import register_event_bus
from youth_compass.ports import DomainEvent, EventBus


class InMemoryEventBus:
    """Synchronous fan-out to handlers subscribed to an exact event type."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[DomainEvent], None]]] = {}

    def publish(self, event: DomainEvent) -> None:
        for handler in self._handlers.get(event.event_type, []):
            handler(event)

    def subscribe(self, event_type: str, handler: Callable[[DomainEvent], None]) -> None:
        self._handlers.setdefault(event_type, []).append(handler)


@register_event_bus("reference")
@contextmanager
def _reference_event_bus() -> Iterator[EventBus]:
    yield InMemoryEventBus()
