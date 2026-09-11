"""In-memory reference adapters.

Importing this package registers one reference adapter per Port, so the contract
suite has something to run against before any real adapter exists. Every module
is imported here for its registration side effect.
"""

from tests.contract.reference import (  # noqa: F401
    catalog,
    checkpoint_store,
    clock,
    event_bus,
    forecast_service,
    model_provider,
    object_store,
    query_engine,
    workflow_runner,
)
