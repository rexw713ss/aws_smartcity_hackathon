"""A small bounded cache for retrieval that is already deterministic.

Nothing in the agent cached anything: asking the same question twice re-scanned
Athena from the start and re-invoked Bedrock. That is unusually wasteful here,
because this architecture happens to satisfy the two conditions caching normally
fails on.

Everything is deterministic. Queries are typed specs against immutable published
Parquet, and the model runs at temperature 0. The same inputs genuinely produce
the same outputs.

And staleness is not a risk that has to be managed, because every dataset carries
a ``dataset_version`` and a published version is immutable. The version is part of
the key, so a republish does not invalidate an entry — it addresses a different
one. There is no window in which this returns data that has since changed, which
is what usually makes caching a query layer a judgment call rather than a free
win.

The saving is money rather than only latency. Athena bills by bytes scanned, and
the measured hot spot is dataset inspection: a full coverage scan that costs more
than the query the user actually asked for.

The TTL exists despite immutability, for two reasons that have nothing to do with
correctness: an entry for a superseded version would otherwise sit in memory
forever, and a long-lived process should not hold a snapshot of a catalog it has
stopped reading.
"""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Any

#: Default entries held per cache. Each holds one inspection or one aggregated
#: series for one dataset version, so this is a few tens of megabytes at worst in
#: a process that has been asked a great many different questions.
DEFAULT_MAX_ENTRIES = 256

#: Default lifetime. Long enough that a conversation's follow-ups all hit, short
#: enough that a superseded version is not retained indefinitely.
DEFAULT_TTL_SECONDS = 900.0


@dataclass
class CacheStats:
    """Hits and misses, so the cache can be shown to be working."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.lookups if self.lookups else 0.0


class TtlCache:
    """A thread-safe LRU cache with a time bound.

    Thread-safe because it has to be: retrieval now runs inside
    ``asyncio.to_thread``, so two concurrent requests genuinely reach this from
    two threads. An unsynchronized ``OrderedDict`` would corrupt its ordering
    under that, which is the kind of fault that shows up only under load.
    """

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self.stats = CacheStats()

    def get_or_call(self, key: Hashable, produce: Callable[[], Any]) -> Any:
        """Return the cached value for ``key``, or compute and store it.

        ``produce`` runs outside the lock. Holding the lock across a remote query
        would serialize every request behind the slowest one, which would make
        this cache a bottleneck rather than a saving. The cost is that two
        threads missing the same key may both compute it; since the computation
        is deterministic, the duplicate is wasted work and never a wrong answer.
        """

        found, value = self._lookup(key)
        if found:
            return value
        produced = produce()
        self._store(key, produced)
        return produced

    def _lookup(self, key: Hashable) -> tuple[bool, Any]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.stats.misses += 1
                return False, None
            stored_at, value = entry
            if self._clock() - stored_at > self._ttl:
                del self._entries[key]
                self.stats.misses += 1
                return False, None
            self._entries.move_to_end(key)
            self.stats.hits += 1
            return True, value

    def _store(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._entries[key] = (self._clock(), value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
                self.stats.evictions += 1

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_TTL_SECONDS",
    "CacheStats",
    "TtlCache",
]
