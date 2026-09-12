"""Per-Port adapter factory registries.

Feature: aws-stage1-foundation, Property 12 (registration-only binding).

Binding an adapter to the contract suite is one decorated factory function. A
factory is a zero-argument callable returning a context manager that yields a
fresh adapter instance, so per-case state isolation falls out of the fixture
lifecycle. N factories registered for a Port produce N runs of that Port's
single contract class, with the class body untouched.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager

from youth_compass.agent import ConversationContextStore
from youth_compass.ports import (
    CheckpointStore,
    Clock,
    DataCatalog,
    EventBus,
    ForecastService,
    ModelProvider,
    ObjectStore,
    QueryEngine,
    WorkflowRunner,
)

type Factory[T] = Callable[[], AbstractContextManager[T]]

OBJECT_STORE_FACTORIES: dict[str, Factory[ObjectStore]] = {}
CATALOG_FACTORIES: dict[str, Factory[DataCatalog]] = {}
QUERY_ENGINE_FACTORIES: dict[str, Factory[QueryEngine]] = {}
MODEL_PROVIDER_FACTORIES: dict[str, Factory[ModelProvider]] = {}
FORECAST_SERVICE_FACTORIES: dict[str, Factory[ForecastService]] = {}
WORKFLOW_RUNNER_FACTORIES: dict[str, Factory[WorkflowRunner]] = {}
CHECKPOINT_STORE_FACTORIES: dict[str, Factory[CheckpointStore]] = {}
EVENT_BUS_FACTORIES: dict[str, Factory[EventBus]] = {}
CLOCK_FACTORIES: dict[str, Factory[Clock]] = {}
CONVERSATION_STORE_FACTORIES: dict[str, Factory[ConversationContextStore]] = {}


def _registrar[T](
    registry: dict[str, Factory[T]],
) -> Callable[[str], Callable[[Factory[T]], Factory[T]]]:
    def register(name: str) -> Callable[[Factory[T]], Factory[T]]:
        def decorator(factory: Factory[T]) -> Factory[T]:
            if name in registry:
                raise ValueError(f"adapter {name!r} is already registered for this Port")
            registry[name] = factory
            return factory

        return decorator

    return register


register_object_store = _registrar(OBJECT_STORE_FACTORIES)
register_catalog = _registrar(CATALOG_FACTORIES)
register_query_engine = _registrar(QUERY_ENGINE_FACTORIES)
register_model_provider = _registrar(MODEL_PROVIDER_FACTORIES)
register_forecast_service = _registrar(FORECAST_SERVICE_FACTORIES)
register_workflow_runner = _registrar(WORKFLOW_RUNNER_FACTORIES)
register_checkpoint_store = _registrar(CHECKPOINT_STORE_FACTORIES)
register_event_bus = _registrar(EVENT_BUS_FACTORIES)
register_clock = _registrar(CLOCK_FACTORIES)
register_conversation_store = _registrar(CONVERSATION_STORE_FACTORIES)
