"""Clock contract.

Feature: aws-stage1-foundation. Property 11 (aware, zero-offset, non-decreasing).
"""

from datetime import timedelta

from tests.contract import generators as gen
from youth_compass.ports import Clock


class TestClockContract:
    def test_property_11_now_is_timezone_aware_utc(self, clock: Clock) -> None:
        moment = clock.now()
        assert moment.tzinfo is not None
        assert moment.utcoffset() == timedelta(0)

    def test_property_11_now_is_non_decreasing(self, clock: Clock) -> None:
        previous = clock.now()
        for _ in gen.samples(100):
            current = clock.now()
            assert current >= previous, f"seed={gen.seed()}"
            previous = current
