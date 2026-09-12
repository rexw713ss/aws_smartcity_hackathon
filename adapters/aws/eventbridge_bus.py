"""EventBridge EventBus adapter.

Feature: aws-stage2-adapters, Requirement 5.

Publishes domain events to EventBridge and maintains an in-process subscription
table for delivery. The dotted audit vocabulary from ``docs/08`` section 6 is
carried as each event's ``event_type`` unchanged.
"""

from collections.abc import Callable

import boto3
import botocore.exceptions

from youth_compass.domain.errors import YouthCompassError
from youth_compass.ports.event_bus import DomainEvent


class EventBridgeBus:
    """EventBus backed by Amazon EventBridge with in-process fan-out."""

    def __init__(self, bus_name: str, region: str = "us-east-1") -> None:
        self._bus_name = bus_name
        self._client = boto3.client("events", region_name=region)
        self._handlers: dict[str, list[Callable[[DomainEvent], None]]] = {}

    def publish(self, event: DomainEvent) -> None:
        """Publish to EventBridge and fan out to in-process subscribers."""
        try:
            self._client.put_events(
                Entries=[
                    {
                        "Source": "youth-compass",
                        "DetailType": event.event_type,
                        "Detail": event.model_dump_json(),
                        "EventBusName": self._bus_name,
                    }
                ]
            )
        except botocore.exceptions.ClientError as exc:
            raise YouthCompassError(f"EventBridge publish failed: {exc}") from exc

        for handler in self._handlers.get(event.event_type, []):
            handler(event)

    def subscribe(self, event_type: str, handler: Callable[[DomainEvent], None]) -> None:
        """Register a handler for in-process fan-out."""
        self._handlers.setdefault(event_type, []).append(handler)
