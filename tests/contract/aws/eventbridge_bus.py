"""EventBridge EventBus binding for the contract suite under moto."""

from collections.abc import Iterator
from contextlib import contextmanager

import boto3
from moto import mock_aws

from adapters.aws.eventbridge_bus import EventBridgeBus
from tests.contract.registry import register_event_bus

_BUS_NAME = "contract-test-bus"
_REGION = "ap-northeast-1"


@register_event_bus("eventbridge-moto")
@contextmanager
def _eventbridge_bus() -> Iterator[EventBridgeBus]:
    with mock_aws():
        events = boto3.client("events", region_name=_REGION)
        events.create_event_bus(Name=_BUS_NAME)
        yield EventBridgeBus(bus_name=_BUS_NAME, region=_REGION)
