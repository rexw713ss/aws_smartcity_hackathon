"""Caching is safe here because the version is part of the key."""

import threading

import pytest

from youth_compass.agent.caching import TtlCache


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_repeated_key_is_computed_once() -> None:
    calls: list[int] = []
    cache = TtlCache()

    for _ in range(3):
        cache.get_or_call("k", lambda: calls.append(1) or "value")

    assert len(calls) == 1
    assert cache.stats.hits == 2
    assert cache.stats.misses == 1


def test_cache_status_distinguishes_a_billable_miss_from_a_free_hit() -> None:
    cache = TtlCache()

    first, first_hit = cache.get_or_call_with_status("k", lambda: "value")
    second, second_hit = cache.get_or_call_with_status("k", lambda: "not-called")

    assert first == second == "value"
    assert first_hit is False
    assert second_hit is True


def test_a_new_dataset_version_addresses_a_different_entry_rather_than_a_stale_one() -> None:
    """This is what makes the cache semantically safe rather than a tradeoff.

    A published version is immutable, so a republish cannot change what an old key
    means. It produces a new key. There is no window in which a stale value is
    served, which is the risk that normally makes caching a query layer a
    judgment call.
    """

    cache = TtlCache()

    first = cache.get_or_call(("inspect", "population", "v1"), lambda: "coverage-v1")
    second = cache.get_or_call(("inspect", "population", "v2"), lambda: "coverage-v2")

    assert first == "coverage-v1"
    assert second == "coverage-v2"
    assert cache.stats.hits == 0


def test_an_entry_expires_so_a_superseded_version_is_not_held_forever() -> None:
    clock = _Clock()
    cache = TtlCache(ttl_seconds=10.0, clock=clock)
    calls: list[int] = []

    cache.get_or_call("k", lambda: calls.append(1) or "v")
    clock.now = 9.0
    cache.get_or_call("k", lambda: calls.append(1) or "v")
    clock.now = 11.0
    cache.get_or_call("k", lambda: calls.append(1) or "v")

    assert len(calls) == 2, "the entry should survive until the TTL and not beyond"


def test_the_least_recently_used_entry_is_evicted_when_full() -> None:
    cache = TtlCache(max_entries=2)

    cache.get_or_call("a", lambda: "a")
    cache.get_or_call("b", lambda: "b")
    cache.get_or_call("a", lambda: "recomputed")  # refreshes a's recency
    cache.get_or_call("c", lambda: "c")

    assert cache.stats.evictions == 1
    assert len(cache) == 2
    # "b" was the least recently used, so it is the one that went.
    recomputed: list[str] = []
    cache.get_or_call("b", lambda: recomputed.append("b") or "b")
    assert recomputed == ["b"]


def test_hit_rate_is_reportable_so_the_cache_can_be_shown_to_earn_its_place() -> None:
    cache = TtlCache()
    cache.get_or_call("a", lambda: 1)
    cache.get_or_call("a", lambda: 1)

    assert cache.stats.lookups == 2
    assert cache.stats.hit_rate == pytest.approx(0.5)


def test_concurrent_access_does_not_corrupt_the_cache() -> None:
    """Retrieval runs in asyncio.to_thread, so two requests reach this from two threads.

    An unsynchronized OrderedDict corrupts its ordering under that, which is a
    fault that only appears under load.
    """

    cache = TtlCache(max_entries=32)
    errors: list[BaseException] = []

    def hammer(offset: int) -> None:
        try:
            for index in range(200):
                cache.get_or_call(f"k{(index + offset) % 64}", lambda: offset)
        except BaseException as exc:  # pragma: no cover - the assertion is the point
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(offset,)) for offset in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(cache) <= 32


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [({"max_entries": 0}, "max_entries"), ({"ttl_seconds": 0}, "ttl_seconds")],
)
def test_incoherent_bounds_are_refused(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        TtlCache(**kwargs)  # type: ignore[arg-type]
