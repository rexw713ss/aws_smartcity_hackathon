"""EventBus contract.

Feature: aws-stage1-foundation.
"""

from datetime import UTC, datetime

from youth_compass.ports import DomainEvent, EventBus


def _event(event_type: str, resource_id: str) -> DomainEvent:
    return DomainEvent(
        event_type=event_type,
        occurred_at=datetime(2026, 9, 12, tzinfo=UTC),
        actor="worker",
        resource_id=resource_id,
    )


class TestEventBusContract:
    def test_subscriber_receives_matching_events_in_publish_order(
        self, event_bus: EventBus
    ) -> None:
        received: list[str] = []
        event_bus.subscribe("dataset.published", lambda e: received.append(e.resource_id))
        for i in range(5):
            event_bus.publish(_event("dataset.published", f"ds-{i}"))
        assert received == [f"ds-{i}" for i in range(5)]

    def test_subscriber_receives_no_non_matching_event(self, event_bus: EventBus) -> None:
        received: list[str] = []
        event_bus.subscribe("dataset.published", lambda e: received.append(e.resource_id))
        event_bus.publish(_event("dataset.quarantined", "ds-x"))
        assert received == []
