"""SQLite DataCatalog binding for the contract suite."""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from adapters.local import SQLiteCatalog
from tests.contract.registry import register_catalog
from youth_compass.ports import DataCatalog


@register_catalog("sqlite")
@contextmanager
def _sqlite_catalog() -> Iterator[DataCatalog]:
    with tempfile.TemporaryDirectory() as directory:
        yield SQLiteCatalog(Path(directory) / "catalog.sqlite3")
