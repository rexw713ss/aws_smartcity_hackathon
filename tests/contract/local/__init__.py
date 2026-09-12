"""Register persistent local adapters with the shared contract suite."""

from tests.contract.local import clock as clock
from tests.contract.local import duckdb_query as duckdb_query
from tests.contract.local import filesystem_store as filesystem_store
from tests.contract.local import sqlite_catalog as sqlite_catalog
from tests.contract.local import sqlite_checkpoint as sqlite_checkpoint

__all__ = ["clock", "duckdb_query", "filesystem_store", "sqlite_catalog", "sqlite_checkpoint"]
