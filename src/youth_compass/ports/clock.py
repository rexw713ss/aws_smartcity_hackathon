"""Clock port.

Stage 1 proposal originating from the AWS workstream. The backend workstream may
amend these signatures; see docs/12-aws-stage1-foundation.md for the amendment
procedure. Signature transcribed from docs/07-project-structure.md section 7,
which fixes this module's filename.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Injectable time source, so time-dependent logic stays testable."""

    def now(self) -> datetime:
        """Return the current instant as a timezone-aware UTC ``datetime``.

        The Protocol cannot express awareness in the type, so the contract suite
        asserts ``tzinfo is not None`` and ``utcoffset() == timedelta(0)``, and
        that successive calls are non-decreasing.
        """
        ...
