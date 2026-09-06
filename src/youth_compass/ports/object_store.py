"""ObjectStore port.

Stage 1 proposal originating from the AWS workstream. The backend workstream may
amend these signatures; see docs/12-aws-stage1-foundation.md for the amendment
procedure. Signatures transcribed from docs/01-system-architecture.md section 5.1.

Note the key/URI asymmetry inherited from that section and deliberately preserved
rather than tidied, so the transcription stays auditable: ``put`` takes a key and
returns a URI, ``get``/``exists`` take a URI, and ``list`` takes a key prefix and
returns keys.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ObjectStore(Protocol):
    """Byte storage addressed by scheme-qualified URI."""

    def put(self, key: str, content: bytes, metadata: dict[str, str]) -> str:
        """Write ``content`` under ``key`` and return its scheme-qualified URI.

        Writing the same key twice leaves exactly one object carrying the later
        content, and the key appears exactly once in ``list``.
        """
        ...

    def get(self, uri: str) -> bytes:
        """Return the bytes stored at ``uri``.

        Raises:
            ObjectNotFoundError: no object exists at ``uri``.
        """
        ...

    def list(self, prefix: str) -> list[str]:
        """Return exactly the keys beginning with ``prefix``, empty when none match."""
        ...

    def exists(self, uri: str) -> bool:
        """Return whether an object is readable at ``uri``."""
        ...
