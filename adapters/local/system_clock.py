"""UTC system clock adapter."""

from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        """Return the current timezone-aware UTC instant."""

        return datetime.now(UTC)
