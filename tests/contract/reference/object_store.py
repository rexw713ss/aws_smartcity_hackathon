"""In-memory ObjectStore reference implementation."""

from collections.abc import Iterator
from contextlib import contextmanager

from tests.contract.registry import register_object_store
from youth_compass.domain.errors import ObjectNotFoundError
from youth_compass.ports import ObjectStore

_SCHEME = "mem://"


class InMemoryObjectStore:
    """Stores bytes in a dict; URIs are the key under a fixed scheme."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, key: str, content: bytes, metadata: dict[str, str]) -> str:
        self._objects[key] = content
        return f"{_SCHEME}{key}"

    def get(self, uri: str) -> bytes:
        key = self._key(uri)
        try:
            return self._objects[key]
        except KeyError as exc:
            raise ObjectNotFoundError(uri) from exc

    def list(self, prefix: str) -> list[str]:
        return sorted(k for k in self._objects if k.startswith(prefix))

    def exists(self, uri: str) -> bool:
        return self._key(uri) in self._objects

    @staticmethod
    def _key(uri: str) -> str:
        return uri[len(_SCHEME) :] if uri.startswith(_SCHEME) else uri


@register_object_store("reference")
@contextmanager
def _reference_object_store() -> Iterator[ObjectStore]:
    yield InMemoryObjectStore()
