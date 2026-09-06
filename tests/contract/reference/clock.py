"""In-memory Clock reference implementation."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from tests.contract.registry import register_clock
from youth_compass.ports import Clock


class InMemoryClock:
    """Monotonic, timezone-aware UTC clock; each call advances by one tick."""

    def __init__(self, start: datetime | None = None, tick: timedelta = timedelta(microseconds=1)):
        self._current = start or datetime(2026, 9, 12, tzinfo=UTC)
        self._tick = tick

    def now(self) -> datetime:
        value = self._current
        self._current = self._current + self._tick
        return value


@register_clock("reference")
@contextmanager
def _reference_clock() -> Iterator[Clock]:
    yield InMemoryClock()
