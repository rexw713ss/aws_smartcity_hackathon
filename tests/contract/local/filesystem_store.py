"""Filesystem ObjectStore binding for the contract suite."""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from adapters.local import FileSystemObjectStore
from tests.contract.registry import register_object_store
from youth_compass.ports import ObjectStore


@register_object_store("filesystem")
@contextmanager
def _filesystem_store() -> Iterator[ObjectStore]:
    with tempfile.TemporaryDirectory() as directory:
        yield FileSystemObjectStore(Path(directory))
