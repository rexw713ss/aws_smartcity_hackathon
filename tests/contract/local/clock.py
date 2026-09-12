"""System Clock binding for the contract suite."""

from collections.abc import Iterator
from contextlib import contextmanager

from adapters.local import SystemClock
from tests.contract.registry import register_clock
from youth_compass.ports import Clock


@register_clock("system")
@contextmanager
def _system_clock() -> Iterator[Clock]:
    yield SystemClock()
